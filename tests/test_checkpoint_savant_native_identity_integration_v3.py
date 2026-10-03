"""Exercise the actual Savant identity/SDK/bridge boundary, without GPU claims."""
from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from checkpoint_deepstream_protocol_adapter import (
    DeepStreamProtocolAdapterError, DeepStreamProtocolCallbacks,
)
from checkpoint_deepstream_protocol_bridge import (
    DeepStreamProtocolBridge, DeepStreamProtocolBridgeError,
)
from checkpoint_savant_native_module import (
    SavantNativeModuleBinding, SavantNativeModuleError,
    build_native_frame_identity, build_native_module_artifact,
)
from checkpoint_savant_protocol_bridge import SavantProtocolBridge
from checkpoint_savant_sdk_runtime_v3 import SavantSdkCallbackRuntime
from test_checkpoint_deepstream_protocol_adapter import (
    FAKE_GST_MAP_READ, FakeBuffer, FakeCaps,
)
from test_checkpoint_deepstream_protocol_bridge import (
    PREPROCESS_SHA, FakePolicyExchange, StepClock, admission, endpoints, tensor, nvds_identity,
    mock_service_clock,
)
from test_checkpoint_savant_native_module import (
    BASELINE_TOPOLOGY, SHARED_TOPOLOGY, BRANCHES, FakeFrame, descriptor, source,
)


class RgbCaps(FakeCaps):
    def __init__(self):
        self.values = {"format": "RGB", "width": 2, "height": 2}

    def copy(self):
        result = type(self)()
        result.values = dict(self.values)
        return result

    def set_value(self, name, value):
        self.values[name] = value

    def is_empty(self):
        return False

    def to_string(self):
        return "video/x-raw," + ",".join(f"{key}={value}" for key, value in self.values.items())

    def get_structure(self, _index):
        return SimpleNamespace(get_name=lambda: "video/x-raw",
            get_string=lambda key: self.values[key],
            get_value=lambda key: self.values[key])


class SavantNativeIdentityIntegrationV3Tests(unittest.TestCase):
    def setUp(self):
        mock_service_clock(self)
        # Keep real SDK observations and the deterministic policy fixture on
        # the same unit-test epoch; no production clock behavior is changed.
        patcher = mock.patch("checkpoint_savant_sdk_runtime_v3.time.time_ns", return_value=1_000_000_000)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _native(self, topology=BASELINE_TOPOLOGY, stream=0, *, source_dimensions=None):
        source_binding = source(stream)
        if source_dimensions is not None:
            source_binding.update(width=source_dimensions[0], height=source_dimensions[1])
        artifact = build_native_module_artifact(descriptor(topology, stream), source_binding)
        binding = SavantNativeModuleBinding.from_json(artifact["binding_json"])
        video = FakeFrame(binding)
        payload = b"real-test-access-unit"
        video._tags["vast.admission_id"] = f"identity-test:{stream}:admission:7"
        video._tags["vast.payload_sha256"] = hashlib.sha256(payload).hexdigest()
        transport = SimpleNamespace(
            sequence=7, frame_id=6, payload=payload,
            payload_sha256=video._tags["vast.payload_sha256"],
            access_unit_pts_ns=video._tags["vast.access_unit_pts_ns"],
            transport_pts_ns=video.pts,
            admission_id=video._tags["vast.admission_id"],
            input_frame_key=video._tags["vast.input_frame_key"],
        )
        meta = SimpleNamespace(video_frame=video, frame_meta=SimpleNamespace(
            source_id=stream, frame_num=41, buf_pts=video.pts,
        ))
        return binding, video, transport, meta

    def _delegate(self, binding, events, **options):
        return DeepStreamProtocolBridge(
            run_id="identity-test", arm_id="identity-arm", worker_id=binding.module_id,
            topology_kind=binding.topology_kind, stream_id=binding.stream_id,
            branch_id=binding.branches[0] if len(binding.branches) == 1 else None,
            event_sink=lambda line: events.append(json.loads(line)),
            policy_exchange=FakePolicyExchange({branch: "cpu" for branch in binding.branches}),
            analytics_endpoints=endpoints(binding.branches), clock_ms=StepClock(), **options,
        )

    def _callbacks(self, binding, bridge, **options):
        def preprocess(_payload, **kwargs):
            spec, payload = tensor("damage")
            return payload, spec
        spec, _ = tensor("damage")
        return DeepStreamProtocolCallbacks(
            bridge=bridge,
            input_bindings={branch: {
                "input": {key: spec[key] for key in ("name", "dtype", "layout", "shape")},
                "preprocessing_contract_sha256": PREPROCESS_SHA,
            } for branch in binding.branches},
            preprocessing_contract={}, preprocess=preprocess, deadline_ms=100,
            gst_map_read_flag=FAKE_GST_MAP_READ, **options,
        )

    def test_sdk_prefix_passes_actual_mux_pts_through_unmocked_identity_and_bridge(self):
        binding, _video, transport, meta = self._native()
        events = []
        bridge = SavantProtocolBridge(
            module_id=binding.module_id, stream_id=0, topology_kind=binding.topology_kind,
            delegate=self._delegate(binding, events),
        )
        runtime = SavantSdkCallbackRuntime(binding=binding,
            callbacks=self._callbacks(binding, bridge), resource_recorder=mock.Mock())
        runtime.bind_decoder("nvv4l2decoder", 0)
        runtime.admit_transport_frame(transport)
        runtime.observe_prefix(SimpleNamespace(pts=123), meta, binding)
        self.assertEqual(runtime._identity_by_pts[transport.transport_pts_ns]["mux_gst_buffer_pts_ns"], 123)
        self.assertEqual([row["event_kind"] for row in events], ["source_read", "stage_complete"])
        self.assertEqual(events[-1]["stage"], "decode_damage")

    def test_all_native_stream_ids_are_bound_without_relabelling(self):
        for topology in (BASELINE_TOPOLOGY, SHARED_TOPOLOGY):
            for stream in range(6):
                with self.subTest(topology=topology, stream=stream):
                    binding, _video, transport, meta = self._native(topology, stream)
                    events = []
                    delegate = self._delegate(binding, events, nvds_source_id=stream)
                    bridge = SavantProtocolBridge(module_id=binding.module_id,
                        stream_id=stream, topology_kind=topology, delegate=delegate)
                    runtime = SavantSdkCallbackRuntime(binding=binding,
                        callbacks=self._callbacks(binding, bridge), resource_recorder=mock.Mock())
                    runtime.bind_decoder("nvv4l2decoder", 0)
                    runtime.admit_transport_frame(transport)
                    runtime.observe_prefix(SimpleNamespace(pts=123), meta, binding)
                    observed = runtime._identity_by_pts[transport.transport_pts_ns]
                    self.assertEqual(observed["nvds_source_id"], stream)
                    self.assertEqual(observed["mux_gst_buffer_pts_ns"], 123)

    def test_mux_pts_is_mandatory_and_never_copied_from_frame_pts(self):
        binding, video, _transport, meta = self._native()
        for pts in (None, -1, True, 1.5, (1 << 64) - 1):
            with self.subTest(pts=pts), self.assertRaises(SavantNativeModuleError):
                build_native_frame_identity(binding=binding, frame_meta=meta,
                    decoder_factory="nvv4l2decoder", decoder_gpu_id=0,
                    mux_gst_buffer_pts_ns=pts)
        observed = build_native_frame_identity(binding=binding, frame_meta=meta,
            decoder_factory="nvv4l2decoder", decoder_gpu_id=0, mux_gst_buffer_pts_ns=123)
        self.assertEqual(observed["nvds_buf_pts_ns"], video.pts)
        self.assertEqual(observed["mux_gst_buffer_pts_ns"], 123)
        self.assertNotEqual(video.pts, 123)

    def test_post_demux_sample_uses_original_pts_and_preserves_mux_identity(self):
        # The source binding, decoded frame and 12-byte RGB sample all use 2x2.
        binding, video, transport, meta = self._native(source_dimensions=(2, 2))
        events = []
        bridge = SavantProtocolBridge(module_id=binding.module_id, stream_id=0,
            topology_kind=binding.topology_kind, delegate=self._delegate(binding, events))
        callbacks = self._callbacks(binding, bridge, rgb_sample_pts_field="nvds_buf_pts_ns")
        runtime = SavantSdkCallbackRuntime(binding=binding, callbacks=callbacks,
            resource_recorder=mock.Mock())
        runtime.bind_decoder("nvv4l2decoder", 0)
        runtime.admit_transport_frame(transport)
        runtime.observe_prefix(SimpleNamespace(pts=123), meta, binding)
        identity = dict(runtime._identity_by_pts[video.pts])
        sample_buffer = FakeBuffer()
        sample_buffer.pts = video.pts
        sample = SimpleNamespace(get_buffer=lambda: sample_buffer, get_caps=RgbCaps)
        runtime.observe_route_buffer(sample_buffer, binding, "damage", sample=sample, caps=RgbCaps())
        runtime.assert_drained()
        self.assertEqual(identity["mux_gst_buffer_pts_ns"], 123)
        self.assertEqual(events[-1]["event_kind"], "branch_complete")

    def test_wrong_demux_pts_and_unknown_pts_mode_are_rejected_before_preprocessing(self):
        binding, _video, _transport, _meta = self._native()
        bridge = mock.Mock()
        callbacks = self._callbacks(binding, bridge, rgb_sample_pts_field="nvds_buf_pts_ns")
        identity = {"nvds_buf_pts_ns": 900, "mux_gst_buffer_pts_ns": 123}
        sample = SimpleNamespace(get_buffer=FakeBuffer, get_caps=FakeCaps)
        with self.assertRaisesRegex(DeepStreamProtocolAdapterError, "PTS"):
            callbacks.execute_branch_sample(identity, branch="damage", sample=sample)
        bridge.bind_branch_tensor.assert_not_called()
        with self.assertRaisesRegex(DeepStreamProtocolAdapterError, "PTS"):
            self._callbacks(binding, bridge, rgb_sample_pts_field="transport_pts_ns")

    def test_default_deepstream_still_rejects_nonzero_local_source_id(self):
        binding, _video, _transport, _meta = self._native()
        delegate = self._delegate(binding, [])
        admitted = admission("identity-test")
        delegate.admit_access_unit(json.dumps(admitted))
        identity = nvds_identity(admitted)
        identity["nvds_source_id"] = 5
        with self.assertRaisesRegex(DeepStreamProtocolBridgeError, "nvds_source_id"):
            delegate.observe_decoded_frame(identity)

    def test_module_webserver_ports_are_unique_for_the_full_process_matrix(self):
        ports = []
        for stream in range(6):
            for topology, branches in ((BASELINE_TOPOLOGY, BRANCHES), (SHARED_TOPOLOGY, ("damage",))):
                for branch in branches:
                    artifact = build_native_module_artifact(descriptor(topology, stream, branch), source(stream))
                    port = artifact["module_config"]["parameters"]["webserver_port"]
                    self.assertIs(type(port), int)
                    self.assertTrue(1024 <= port <= 65535)
                    ports.append(port)
        self.assertEqual(len(set(ports)), 30)


if __name__ == "__main__":
    unittest.main()
