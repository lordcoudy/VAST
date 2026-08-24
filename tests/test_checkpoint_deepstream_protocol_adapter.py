from __future__ import annotations

import hashlib
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checkpoint_deepstream_protocol_adapter import (  # noqa: E402
    CONFIG_CLAIM_STATUS,
    CONFIG_KIND,
    DeepStreamProtocolAdapterError,
    DeepStreamProtocolCallbacks,
    create_callbacks,
    validate_adapter_config,
)


class FakeStructure:
    def get_name(self):
        return "video/x-raw"

    def get_value(self, name):
        return {"format": "RGB", "width": 2, "height": 2}[name]


class FakeCaps:
    def get_size(self):
        return 1

    def get_structure(self, _index):
        return FakeStructure()


class FakeMap:
    data = bytes(range(12))


class FakeBuffer:
    pts = 123

    def map(self, flags):
        if flags != 1:
            raise AssertionError(flags)
        return True, FakeMap()

    def unmap(self, _mapping):
        pass


class FakeSample:
    def get_caps(self):
        return FakeCaps()

    def get_buffer(self):
        return FakeBuffer()


class FakeBridge:
    def __init__(self):
        self.calls = []

    def __getattr__(self, name):
        def record(*args, **kwargs):
            self.calls.append((name, args, kwargs))
        return record


def config() -> dict:
    resources = {
        resource: {
            "implementation_id": f"deepstream-plate_number-{resource}",
            "socket_path": f"/run/vast/plate_number-{resource}.sock",
            "binding_path": f"/run/vast/plate_number-{resource}-binding.json",
            "runtime_probe_path": f"/run/vast/plate_number-{resource}-probe.json",
        }
        for resource in ("cpu", "gpu")
    }
    return {
        "schema_version": 1,
        "artifact_kind": CONFIG_KIND,
        "claim_status": CONFIG_CLAIM_STATUS,
        "preprocessing_manifest_path": "/workspace/configs/checkpoint_analytics_model_parity.yaml",
        "branches": {"plate_number": resources},
    }


class DeepStreamProtocolAdapterTests(unittest.TestCase):
    def test_json_preprocessing_manifest_contract_is_schema_v3(self) -> None:
        source = (
            ROOT / "scripts" / "checkpoint_deepstream_protocol_adapter.py"
        ).read_text(encoding="utf-8")
        self.assertIn('manifest.get("schema_version") == 3', source)
        self.assertNotIn('manifest.get("schema_version") == 2', source)

    def test_config_requires_exact_cpu_gpu_endpoint_material(self) -> None:
        self.assertEqual(validate_adapter_config(config()), config())
        missing = config()
        del missing["branches"]["plate_number"]["gpu"]
        with self.assertRaisesRegex(DeepStreamProtocolAdapterError, "CPU/GPU"):
            validate_adapter_config(missing)
        extra = config()
        extra["publication_ready"] = True
        with self.assertRaisesRegex(DeepStreamProtocolAdapterError, "fields"):
            validate_adapter_config(extra)

    def test_rgb_sample_is_preprocessed_bound_and_executed_directly(self) -> None:
        bridge = FakeBridge()
        expected_sha = hashlib.sha256(b"preprocessing").hexdigest()

        def preprocess(payload, **kwargs):
            self.assertEqual(payload, bytes(range(12)))
            self.assertEqual(
                kwargs["frame"],
                {"format": "RGB", "width": 2, "height": 2, "stride": 6},
            )
            tensor = b"tensor"
            return tensor, {
                "name": "data",
                "dtype": "float32",
                "layout": "NCHW",
                "shape": [1, 3, 224, 224],
                "byte_length": len(tensor),
                "sha256": hashlib.sha256(tensor).hexdigest(),
                "preprocessing_contract_sha256": expected_sha,
            }

        callbacks = DeepStreamProtocolCallbacks(
            bridge=bridge,
            input_bindings={
                "plate_number": {
                    "input": {
                        "name": "data",
                        "dtype": "float32",
                        "layout": "NCHW",
                        "shape": [1, 3, 224, 224],
                    },
                    "preprocessing_contract_sha256": expected_sha,
                }
            },
            preprocessing_contract={"contract_id": "fixture"},
            preprocess=preprocess,
            deadline_ms=33.3,
            monotonic_ns=lambda: 1_000_000,
        )
        identity = {
            "input_frame_key": "dataset:0:source:0:0",
            "nvds_buf_pts_ns": 123,
        }
        callbacks.execute_branch_sample(identity, branch="plate_number", sample=FakeSample())
        self.assertEqual([value[0] for value in bridge.calls], ["bind_branch_tensor", "execute_branch"])
        execute = bridge.calls[1]
        self.assertEqual(execute[1][:2], (identity["input_frame_key"], "plate_number"))
        self.assertEqual(execute[2]["queue_depths"], {"cpu": 0, "gpu": 0})
        self.assertEqual(execute[2]["deadline_monotonic_ns"], 34_300_000)

    def test_factory_fails_before_linux_endpoint_imports_without_config(self) -> None:
        previous = os.environ.pop("VAST_DEEPSTREAM_ADAPTER_CONFIG", None)
        try:
            with self.assertRaisesRegex(DeepStreamProtocolAdapterError, "environment"):
                create_callbacks(context={}, event_sink=lambda _line: None, policy_exchange=lambda _message: {})
        finally:
            if previous is not None:
                os.environ["VAST_DEEPSTREAM_ADAPTER_CONFIG"] = previous


if __name__ == "__main__":
    unittest.main()
