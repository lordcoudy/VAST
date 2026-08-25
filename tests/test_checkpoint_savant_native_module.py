import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_savant_native_module as native_target  # noqa: E402
from checkpoint_savant_native_module import (  # noqa: E402
    BASELINE_TOPOLOGY,
    BRANCHES,
    SHARED_TOPOLOGY,
    SavantAdmissionIngressFilter,
    SavantNativeModuleBinding,
    SavantNativeModuleError,
    SavantNativeRouteBufferPlugin,
    build_native_frame_identity,
    build_native_module_artifact,
    build_native_module_matrix,
    SavantEngineeringCanaryRuntime,
    register_native_runtime,
    unregister_native_runtime,
)


def canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def descriptor(topology: str, stream_id: int = 3, branch: str = "damage") -> dict:
    module_id = (
        f"savant-stream-{stream_id}-branch-{branch}"
        if topology == BASELINE_TOPOLOGY
        else f"savant-stream-{stream_id}-shared-video-dag"
    )
    branches = [branch] if topology == BASELINE_TOPOLOGY else list(BRANCHES)
    value = {
        "schema_version": 1,
        "artifact_kind": "savant_checkpoint_module_descriptor",
        "claim_status": "engineering_savant_module_descriptor_nonpublication",
        "system": "savant",
        "module_id": module_id,
        "topology_kind": topology,
        "stream_id": stream_id,
        "branches": branches,
        "source_process_id": f"source-stream-{stream_id}",
        "source_sha256": "a" * 64,
        "codec": "h264",
        "dataset": "kpp_iss_publication_v3_h264",
        "policy": "heft",
        "deadline_ms": 33.3,
        "module_config_path": f"/opt/vast/checkpoint/generated/{module_id}.yml",
        "module_config_status": "missing_not_built",
        "bridge_class": "checkpoint_savant_protocol_bridge:SavantProtocolBridge",
        "inherited_fd_contract": {
            "admission": "VAST_CHECKPOINT_ADMISSION_DATA_FD",
            "control": "VAST_CHECKPOINT_CONTROL_FD",
            "event": "VAST_CHECKPOINT_EVENT_FD",
            "policy": "VAST_CHECKPOINT_POLICY_FD",
            "status": "VAST_CHECKPOINT_STATUS_FD",
        },
        "accepted_measurement_evidence_emitted": False,
        "publication_ready": False,
    }
    if topology == BASELINE_TOPOLOGY:
        value["physical_pipeline"] = []
    else:
        value["shared_prefix"] = []
        value["routes"] = []
    value["descriptor_sha256"] = hashlib.sha256(canonical(value).encode()).hexdigest()
    return value


def source(stream_id: int = 3) -> dict:
    return {
        "stream_id": stream_id,
        "source_id": f"kpp_plate_avi-stream-{stream_id}",
        "source_sha256": "a" * 64,
        "source_codec": "h264",
        "width": 1920,
        "height": 1080,
    }


class FakeFrame:
    def __init__(self, binding: SavantNativeModuleBinding) -> None:
        self.source_id = binding.source_id
        self.codec = "h264"
        self.width = binding.width
        self.height = binding.height
        self.framerate = "600/1"
        self.pts = 7_000_000
        self.time_base = (1, 1_000_000_000)
        self.content = ("zeromq", None)
        self._tags = {
            "vast.admission_id": "admission-7",
            "vast.input_frame_key": (
                f"{binding.dataset_id}:{binding.stream_id}:"
                f"{binding.source_sha256}:2:5000000"
            ),
            "vast.payload_sha256": "b" * 64,
            "vast.access_unit_pts_ns": 5_000_000,
            "vast.transport_pts_ns": self.pts,
            "vast.source_cycle": 2,
            "vast.sequence": 7,
            "vast.event_provenance": "native_common_source_coordinator",
        }

    def get_attribute(self, namespace: str, name: str):
        if namespace != "default" or name not in self._tags:
            return None
        return SimpleNamespace(values=[self._tags[name]])


class FakeRuntime:
    def __init__(self) -> None:
        self.admitted = []

    def admit_video_frame(self, frame, binding) -> None:
        self.admitted.append((frame, binding))


class FakeBufferRouteRuntime(FakeRuntime):
    def __init__(self) -> None:
        super().__init__()
        self.routes = []

    def observe_route_buffer(self, buffer, binding, branch, *, sample, caps) -> None:
        self.routes.append((buffer, binding, branch, sample, caps))


class NativeModuleTests(unittest.TestCase):
    def test_canary_runtime_stays_nonpublication_and_records_native_identity(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        frame = FakeFrame(binding)
        native = SimpleNamespace(source_id=3, frame_num=41, buf_pts=frame.pts)
        frame_meta = SimpleNamespace(video_frame=frame, frame_meta=native)
        runtime = SavantEngineeringCanaryRuntime()
        runtime.admit_video_frame(frame, binding)
        runtime.bind_decoder("nvv4l2decoder", 0)
        runtime.observe_prefix(None, frame_meta, binding)
        runtime.observe_route(None, frame_meta, binding, "damage")
        receipt = runtime.receipt()
        self.assertEqual(receipt["decoded_frames"], 1)
        self.assertEqual(receipt["branch_terminals"], 1)
        self.assertFalse(receipt["publication_ready"])
        self.assertFalse(receipt["accepted_measurement_evidence_emitted"])

    def test_baseline_config_is_real_zeromq_nvds_one_branch_and_nonpublication(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        config = artifact["module_config"]
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        self.assertEqual(config["pipeline"]["source"]["element"], "zeromq_source_bin")
        self.assertNotIn("appsrc", canonical(config))
        self.assertEqual(config["pipeline"]["source"]["properties"]["socket"], binding.module_socket)
        self.assertEqual(config["pipeline"]["source"]["properties"]["source-timeout"], 60)
        self.assertEqual(
            config["pipeline"]["pipeline_class"],
            "checkpoint_savant_native_module.SavantCheckpointNvDsPipeline",
        )
        topology = config["parameters"]["checkpoint_native_topology"]
        self.assertEqual(topology["route_count"], 1)
        self.assertEqual(topology["routes"][0]["branch"], "damage")
        self.assertEqual(topology["routes"][0]["max_size_buffers"], 1)
        self.assertEqual(topology["routes"][0]["drop_policy"], "drop_newest")
        self.assertEqual(
            [item["element"] for item in config["pipeline"]["elements"]],
            ["pyfunc"],
        )
        self.assertFalse(artifact["publication_ready"])
        self.assertFalse(artifact["accepted_measurement_evidence_emitted"])

    def test_post_demux_terminal_uses_buffer_pts_without_removed_nvds_batch_meta(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        runtime = FakeBufferRouteRuntime()
        register_native_runtime(binding.descriptor_sha256, runtime)
        try:
            plugin = SavantNativeRouteBufferPlugin(
                binding_json=artifact["binding_json"], branch="damage"
            )
            buffer = SimpleNamespace(pts=7_000_000)
            caps = object()
            pad = SimpleNamespace(get_current_caps=lambda: caps)
            plugin.gst_element = SimpleNamespace(
                get_static_pad=lambda name: pad if name == "sink" else None
            )
            sample = object()
            sample_factory = SimpleNamespace(
                new=lambda actual_buffer, actual_caps, segment, info: (
                    sample
                    if (actual_buffer, actual_caps, segment, info)
                    == (buffer, caps, None, None)
                    else None
                )
            )
            with mock.patch.object(
                native_target, "Gst", SimpleNamespace(Sample=sample_factory)
            ):
                plugin.process_buffer(buffer)
            self.assertEqual(
                runtime.routes, [(buffer, binding, "damage", sample, caps)]
            )
        finally:
            unregister_native_runtime(binding.descriptor_sha256, runtime)

    def test_shared_config_declares_native_tee_and_four_exact_routes(self) -> None:
        artifact = build_native_module_artifact(descriptor(SHARED_TOPOLOGY), source())
        topology = artifact["module_config"]["parameters"]["checkpoint_native_topology"]
        self.assertEqual(
            topology["shared_prefix"],
            ["zeromq_source_bin", "savant_rs_video_decode_bin:nvv4l2decoder", "nvstreammux", "nvvideoconvert", "capsfilter:video/x-raw,format=RGB", "tee"],
        )
        self.assertEqual(topology["route_count"], 4)
        self.assertEqual(tuple(route["branch"] for route in topology["routes"]), BRANCHES)
        self.assertTrue(all(route["max_size_buffers"] == 1 for route in topology["routes"]))
        self.assertTrue(all(route["drop_policy"] == "drop_newest" for route in topology["routes"]))
        self.assertTrue(all(route["fanout_name"].startswith("vast_savant_route_fanout_") for route in topology["routes"]))

    def test_matrix_preserves_twenty_four_and_six_process_identities(self) -> None:
        baseline = [descriptor(BASELINE_TOPOLOGY, stream, branch) for stream in range(6) for branch in BRANCHES]
        shared = [descriptor(SHARED_TOPOLOGY, stream) for stream in range(6)]
        sources = {stream: source(stream) for stream in range(6)}
        baseline_matrix = build_native_module_matrix(baseline, sources)
        shared_matrix = build_native_module_matrix(shared, sources)
        self.assertEqual(len(baseline_matrix), 24)
        self.assertEqual(len(shared_matrix), 6)
        self.assertEqual(
            {row["module_id"] for row in baseline_matrix},
            {row["module_id"] for row in baseline},
        )
        self.assertEqual(
            {row["module_id"] for row in shared_matrix},
            {row["module_id"] for row in shared},
        )
        self.assertTrue(all(not row["publication_ready"] for row in baseline_matrix + shared_matrix))

    def test_ingress_filter_requires_external_zeromq_and_exact_eight_tags(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        runtime = FakeRuntime()
        register_native_runtime(binding.descriptor_sha256, runtime)
        try:
            frame = FakeFrame(binding)
            self.assertTrue(SavantAdmissionIngressFilter(binding_json=artifact["binding_json"])(frame))
            self.assertEqual(runtime.admitted, [(frame, binding)])
            frame.content = ("internal", None)
            with self.assertRaisesRegex(SavantNativeModuleError, "external zeromq"):
                SavantAdmissionIngressFilter(binding_json=artifact["binding_json"])(frame)
        finally:
            unregister_native_runtime(binding.descriptor_sha256, runtime)

    def test_native_identity_uses_actual_nvds_values_and_exact_admission_tags(self) -> None:
        artifact = build_native_module_artifact(descriptor(BASELINE_TOPOLOGY), source())
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        video_frame = FakeFrame(binding)
        native = SimpleNamespace(source_id=3, frame_num=41, buf_pts=video_frame.pts)
        frame_meta = SimpleNamespace(
            video_frame=video_frame,
            frame_meta=native,
            get_tag=lambda name: video_frame._tags[name],
        )
        identity = build_native_frame_identity(
            binding=binding,
            frame_meta=frame_meta,
            decoder_factory="nvv4l2decoder",
            decoder_gpu_id=0,
        )
        self.assertEqual(identity["module_id"], binding.module_id)
        self.assertEqual(identity["module_frame_id"], 6)
        self.assertEqual(identity["frame_id"], 6)
        self.assertEqual(identity["nvds_source_id"], 3)
        self.assertEqual(identity["nvds_frame_num"], 41)
        self.assertEqual(identity["nvds_buf_pts_ns"], video_frame.pts)
        native.source_id = 0
        with self.assertRaisesRegex(SavantNativeModuleError, "source_id"):
            build_native_frame_identity(
                binding=binding,
                frame_meta=frame_meta,
                decoder_factory="nvv4l2decoder",
                decoder_gpu_id=0,
            )


if __name__ == "__main__":
    unittest.main()
