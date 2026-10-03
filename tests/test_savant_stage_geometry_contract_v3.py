"""Source-relative geometry must preserve strict native stage equivalence."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from benchmark_contract import ContractError, validate_stage_contracts
from checkpoint_savant_native_module import SavantNativeModuleBinding
from checkpoint_savant_sdk_runtime_v3 import SavantSdkCallbackRuntime, SavantSdkRuntimeV3Error


class Caps:
    """Small GstCaps test double; native serialization is checked separately."""
    def __init__(self, width, height, *, decode=False, colorimetry="bt709"):
        self.decode = decode
        self.values = {"width": width, "height": height,
                       "format": "RGBA" if decode else "RGB", "colorimetry": colorimetry}

    def is_empty(self): return False
    def get_size(self): return 1
    def get_structure(self, index): return self
    def get_name(self): return "video/x-raw"
    def get_string(self, name): return self.values.get(name)
    def get_value(self, name): return self.values.get(name)
    def copy(self): return copy.deepcopy(self)
    def set_value(self, name, value): self.values[name] = value
    def to_string(self):
        media = "video/x-raw(memory:NVMM)" if self.decode else "video/x-raw"
        return media + ", " + ", ".join(
            f"{name}=({'int' if type(value) is int else 'string'}){value}"
            for name, value in self.values.items())


def runtime(width=1920, height=1080, *, stream=0, colorimetry="bt709"):
    module = f"savant-stream-{stream}-branch-damage"
    endpoint = f"ipc:///tmp/vast-savant-{'a' * 16}/module-{module}.ipc"
    binding = SavantNativeModuleBinding(
        module_id=module, descriptor_sha256="a" * 64,
        topology_kind="independent_processes", stream_id=stream, branches=("damage",),
        source_id=f"kpp_plate_avi-stream-{stream}", codec="h264",
        dataset_id="kpp_iss_publication_v3_h264", source_sha256="b" * 64,
        source_duration_ns=1_000_000_000, width=width, height=height, framerate="600/1",
        source_socket="dealer+connect:" + endpoint, module_socket="router+bind:" + endpoint,
        policy="cpu_only", deadline_ms=100,
        bridge_class="checkpoint_savant_protocol_bridge:SavantProtocolBridge")
    result = SavantSdkCallbackRuntime(binding=binding, callbacks=None, resource_recorder=None)
    result.bind_decoder("nvv4l2decoder", 0)
    # Unit fixture plugin paths are real regular files, never native evidence.
    result._loaded_factories = {name: [{"filename": __file__, "version": "unit-fixture"}]
                               for name in ("h264parse", "nvv4l2decoder", "nvstreammux",
                                            "nvvideoconvert", "capsfilter", "vastcheckpointbranchqueue")}
    result.capture_decode_caps(Caps(width, height, decode=True, colorimetry=colorimetry))
    result.capture_preprocess_caps(Caps(width, height, colorimetry=colorimetry))
    return result


def validate(runtimes):
    rows = [row for value in runtimes for row in value.stage_contract_rows(
        run_id="unit-geometry", worker_id=value.binding.module_id)]
    topology = pd.DataFrame([{**{key: row[key] for key in ("run_id", "execution_domain", "stage")},
                              "event_kind": "stage_complete"} for row in rows])
    with tempfile.TemporaryDirectory() as name:
        path = Path(name) / "stage_contracts.runtime.csv"
        pd.DataFrame(rows).to_csv(path, index=False)
        return validate_stage_contracts(path, topology_events=topology)


class SavantStageGeometryContractTests(unittest.TestCase):
    def test_heterogeneous_sources_have_same_identity_geometry_contract(self):
        a, b = runtime(), runtime(1700, 236, stream=5)
        rows = validate([a, b])
        self.assertEqual(len(rows), 4)
        for row in rows.to_dict("records"):
            channels = 4 if row["base_stage"] == "decode" else 3
            self.assertEqual(json.loads(row["output_shape_json"]), ["source_height", "source_width", channels])
            self.assertEqual(json.loads(row["transform_json"])["resize"], {"mode": "identity"})
        self.assertEqual(a._preprocess_output["shape"], [1080, 1920, 3])
        self.assertEqual(b._preprocess_output["shape"], [236, 1700, 3])
        self.assertIn("width=(int)1700", b._preprocess_caps)

    def test_unexpected_resize_rejected_at_observation(self):
        for stage in ("decode", "preprocess"):
            for width, height in ((640, 1080), (1920, 480)):
                with self.subTest(stage=stage, width=width, height=height):
                    value = runtime()
                    # Exercise the first observation, before within-worker drift detection.
                    setattr(value, f"_{stage}_output", None)
                    with self.assertRaisesRegex(SavantSdkRuntimeV3Error, "source geometry"):
                        getattr(value, f"capture_{stage}_caps")(Caps(width, height, decode=stage == "decode"))

    def test_non_geometry_caps_difference_still_blocks_reuse(self):
        with self.assertRaisesRegex(ContractError, "contracts differ across execution domains"):
            validate([runtime(), runtime(1700, 236, stream=5, colorimetry="bt601")])

    def test_concrete_observations_remain_available_for_audit(self):
        value = runtime(1700, 236, stream=5)
        observation = value.stage_contract_observations()
        self.assertEqual(observation["source_shape"], [236, 1700])
        self.assertEqual(observation["decode_output"]["shape"], [236, 1700, 4])
        self.assertEqual(observation["preprocess_output"]["shape"], [236, 1700, 3])
        self.assertIn("width=(int)1700", observation["preprocess_caps"])


if __name__ == "__main__":
    unittest.main()
