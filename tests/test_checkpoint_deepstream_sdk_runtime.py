from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checkpoint_deepstream_sdk_runtime import (  # noqa: E402
    AdmissionTransportFrame,
    AdmissionTransportError,
    CanonicalEventFdSink,
    DeepStreamGraphSpec,
    DeepStreamSdkPipeline,
    DeepStreamSdkRuntimeError,
    LifecycleChannel,
    MISSING_TIMESTAMP,
    NativeBranchQueue,
    _BranchWork,
    _PendingFrame,
    admission_identity_sha256,
    build_deepstream_stage_contract_rows,
    deepstream_buffer_timestamps,
    read_admission_transport_frame,
    write_deepstream_stage_contracts,
)


def _transport_frame(
    *,
    payload: bytes = b"\x00\x00\x00\x01\x65pilot",
    sequence: int = 3,
    access_pts: int = 90_000,
    transport_pts: int = 2_090_000,
    keyframe: bool = True,
) -> bytes:
    admission_id = b"run-sdk:2:admission:3"
    input_key = b"kpp_real_h264:2:" + b"a" * 64 + b":1:90000"
    digest = hashlib.sha256(payload).hexdigest().encode("ascii")
    header = struct.pack(
        ">8sHHQQQQQQIIIQ",
        b"VASTAU01",
        1,
        1 if keyframe else 0,
        sequence,
        1,
        access_pts,
        transport_pts,
        (1 << 64) - 1,
        33_333_333,
        len(admission_id),
        len(input_key),
        len(digest),
        len(payload),
    )
    self_check = len(header)
    if self_check != 80:  # pragma: no cover - documents the native ABI.
        raise AssertionError(self_check)
    return header + admission_id + input_key + digest + payload


def _read_once(payload: bytes):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, payload)
        os.close(write_fd)
        write_fd = -1
        return read_admission_transport_frame(read_fd)
    finally:
        os.close(read_fd)
        if write_fd >= 0:
            os.close(write_fd)


class DeepStreamAdmissionTransportTests(unittest.TestCase):
    def test_exact_native_vastau01_frame_preserves_access_and_transport_pts(self) -> None:
        frame = _read_once(_transport_frame())
        self.assertIsNotNone(frame)
        assert frame is not None
        self.assertEqual(frame.sequence, 3)
        self.assertTrue(frame.keyframe)
        self.assertEqual(frame.source_cycle, 1)
        self.assertEqual(frame.access_unit_pts_ns, 90_000)
        self.assertEqual(frame.transport_pts_ns, 2_090_000)
        self.assertEqual(frame.payload_sha256, hashlib.sha256(frame.payload).hexdigest())
        self.assertEqual(
            admission_identity_sha256(frame),
            hashlib.sha256(
                frame.admission_id.encode()
                + b"\0"
                + frame.input_frame_key.encode()
                + b"\0"
                + frame.payload_sha256.encode()
            ).digest(),
        )

    def test_transport_rejects_digest_mismatch_and_truncated_payload(self) -> None:
        corrupted = bytearray(_transport_frame())
        corrupted[-1] ^= 0x01
        with self.assertRaisesRegex(AdmissionTransportError, "digest"):
            _read_once(bytes(corrupted))
        with self.assertRaisesRegex(AdmissionTransportError, "truncated"):
            _read_once(_transport_frame()[:-1])

    def test_transport_preserves_delta_unit_and_rejects_unknown_flags(self) -> None:
        delta = _read_once(_transport_frame(keyframe=False))
        self.assertIsNotNone(delta)
        assert delta is not None
        self.assertFalse(delta.keyframe)
        unknown = bytearray(_transport_frame())
        unknown[10:12] = (2).to_bytes(2, "big")
        with self.assertRaisesRegex(AdmissionTransportError, "unsupported"):
            _read_once(bytes(unknown))

    def test_transport_accepts_b_frame_pts_reordering_with_monotonic_transport_pts(self) -> None:
        first = _read_once(_transport_frame(sequence=1, access_pts=80, transport_pts=1_000))
        second = _read_once(_transport_frame(sequence=2, access_pts=40, transport_pts=2_000))
        assert first is not None and second is not None
        self.assertGreater(first.access_unit_pts_ns, second.access_unit_pts_ns)
        self.assertLess(first.transport_pts_ns, second.transport_pts_ns)

    def test_scaled_cycle_pts_dts_mapping_matches_native_worker_contract(self) -> None:
        frame = AdmissionTransportFrame(
            sequence=7,
            keyframe=False,
            source_cycle=2,
            access_unit_pts_ns=54_000_000_000,
            transport_pts_ns=163_200_000_000,
            access_unit_dts_ns=53_998_000_000,
            duration_ns=1_000_000_000,
            admission_id="run:0:admission:7",
            input_frame_key="dataset:0:" + "a" * 64 + ":2:54000000000",
            payload_sha256=hashlib.sha256(b"au").hexdigest(),
            payload=b"au",
        )
        self.assertEqual(
            deepstream_buffer_timestamps(frame),
            (163_200_000_000, 163_198_000_000, 1_000_000_000),
        )

    def test_missing_dts_and_impossible_scaled_mapping_fail_closed(self) -> None:
        missing = AdmissionTransportFrame(
            sequence=1,
            keyframe=True,
            source_cycle=0,
            access_unit_pts_ns=0,
            transport_pts_ns=0,
            access_unit_dts_ns=MISSING_TIMESTAMP,
            duration_ns=0,
            admission_id="run:0:admission:1",
            input_frame_key="dataset:0:" + "a" * 64 + ":0:0",
            payload_sha256=hashlib.sha256(b"au").hexdigest(),
            payload=b"au",
        )
        self.assertEqual(
            deepstream_buffer_timestamps(missing, clock_time_none=999),
            (0, 999, 999),
        )
        invalid = AdmissionTransportFrame(
            **{**missing.__dict__, "access_unit_pts_ns": 100, "transport_pts_ns": 50}
        )
        with self.assertRaisesRegex(DeepStreamSdkRuntimeError, "precedes"):
            deepstream_buffer_timestamps(invalid)


class DeepStreamPhysicalGraphTests(unittest.TestCase):
    def test_baseline_is_one_decoder_preprocess_process_for_one_branch(self) -> None:
        graph = DeepStreamGraphSpec.build(
            topology_kind="independent_processes",
            codec="h264",
            stream_id=2,
            branches=("damage",),
        )
        self.assertEqual(graph.process_graph_count, 1)
        self.assertEqual(
            graph.shared_prefix_factories,
            (
                "appsrc",
                "h264parse",
                "nvv4l2decoder",
                "nvstreammux",
                "nvvideoconvert",
                "capsfilter",
            ),
        )
        self.assertEqual(graph.routes, (("damage", "appsink"),))

    def test_shared_is_one_decoder_and_four_native_bounded_routes(self) -> None:
        branches = ("plate_number", "vehicle_type", "damage", "foreign_object")
        graph = DeepStreamGraphSpec.build(
            topology_kind="shared_video_dag",
            codec="h265",
            stream_id=5,
            branches=branches,
        )
        self.assertEqual(graph.process_graph_count, 1)
        self.assertEqual(graph.decoder_count, 1)
        self.assertEqual(graph.shared_prefix_factories[-1], "tee")
        self.assertEqual(
            graph.routes,
            tuple((branch, "queue", "appsink") for branch in branches),
        )
        self.assertEqual(graph.native_queue_capacity_buffers, 1)
        self.assertEqual(graph.native_queue_drop_policy, "drop_newest")

    def test_pipeline_builds_system_memory_rgb_routes_for_frozen_preprocess(self) -> None:
        factories = DeepStreamSdkPipeline.pipeline_factories(
            DeepStreamGraphSpec.build(
                topology_kind="shared_video_dag",
                codec="h265",
                stream_id=0,
                branches=("plate_number", "vehicle_type", "damage", "foreign_object"),
            )
        )
        self.assertIn(("checkpoint_rgb_download", "capsfilter", "video/x-raw,format=RGB"), factories)
        self.assertEqual(
            [value for value in factories if value[1] == "appsink"],
            [
                (f"checkpoint_terminal_{branch}", "appsink", "video/x-raw,format=RGB")
                for branch in ("plate_number", "vehicle_type", "damage", "foreign_object")
            ],
        )

    def test_shared_pipeline_physically_links_rgb_prefix_into_tee_and_every_route(self) -> None:
        links: list[tuple[str, str]] = []

        class _Pad:
            @staticmethod
            def link(_other):
                return 1

            @staticmethod
            def add_probe(_probe_type, _callback):
                return 1

        class _Element:
            def __init__(self, _factory: str, name: str) -> None:
                self.name = name

            @staticmethod
            def set_property(_name: str, _value) -> None:
                return None

            def link(self, other) -> bool:
                links.append((self.name, other.name))
                return True

            @staticmethod
            def request_pad_simple(_name: str):
                return _Pad()

            @staticmethod
            def get_static_pad(_name: str):
                return _Pad()

            @staticmethod
            def connect(_signal: str, _callback, _branch: str) -> None:
                return None

        class _Pipeline:
            @staticmethod
            def add(_element) -> None:
                return None

        class _Gst:
            class Pipeline:
                @staticmethod
                def new(_name: str):
                    return _Pipeline()

            class ElementFactory:
                @staticmethod
                def make(factory: str, name: str):
                    return _Element(factory, name)

            class Caps:
                @staticmethod
                def from_string(value: str):
                    return value

            class Format:
                TIME = 1

            class PadLinkReturn:
                OK = 1

            class PadProbeType:
                BUFFER = 1

        graph = DeepStreamGraphSpec.build(
            topology_kind="shared_video_dag",
            codec="h264",
            stream_id=0,
            branches=("plate_number", "vehicle_type", "damage", "foreign_object"),
        )
        pipeline = object.__new__(DeepStreamSdkPipeline)
        pipeline.Gst = _Gst
        pipeline.graph = graph
        pipeline.decoder_gpu_id = 0
        pipeline._build_pipeline()

        expected = {
            ("checkpoint_admission_source", "checkpoint_access_unit_parser"),
            ("checkpoint_access_unit_parser", "checkpoint_nvdec_decoder"),
            ("checkpoint_single_stream_mux", "checkpoint_preprocess_surface"),
            ("checkpoint_preprocess_surface", "checkpoint_rgb_download"),
            ("checkpoint_rgb_download", "checkpoint_shared_fanout"),
        }
        for branch in graph.branches:
            expected.add(("checkpoint_shared_fanout", f"checkpoint_route_{branch}"))
            expected.add((f"checkpoint_route_{branch}", f"checkpoint_terminal_{branch}"))
        self.assertEqual(set(links), expected)

    def test_native_stage_contract_rows_bind_physical_domain_and_runtime_artifacts(self) -> None:
        digest = hashlib.sha256(b"runtime-artifact").hexdigest()
        artifacts = {
            "decode": [{"role": "decoder", "kind": "plugin", "logical_name": "nvv4l2decoder", "sha256": digest}],
            "preprocess": [{"role": "format_converter", "kind": "plugin", "logical_name": "nvvideoconvert", "sha256": digest}],
        }
        rows = build_deepstream_stage_contract_rows(
            run_id="deepstream-v3-run",
            worker_id="deepstream-baseline-stream-2-damage",
            topology_kind="independent_processes",
            branches=("damage",),
            execution_domain="runtime-host:pid-4321:worker-deepstream-baseline-stream-2-damage",
            implementation_version="DeepStream-7.0/GStreamer-1.20.3",
            decode_config={"backend": "deepstream", "decoder_factory": "nvv4l2decoder", "decoder_gpu_id": 0},
            preprocess_config={"backend": "deepstream", "converter_factory": "nvvideoconvert", "output_caps": "video/x-raw,format=RGB,width=1920,height=1080"},
            artifacts_by_stage=artifacts,
            decode_output={"media_type": "video/x-raw(memory:NVMM)", "format": "NV12", "shape": [1080, 1920, 3]},
            preprocess_output={"media_type": "video/x-raw", "format": "rgb24", "shape": [1080, 1920, 3]},
        )
        self.assertEqual([row["stage"] for row in rows], ["decode_damage", "preprocess_damage"])
        self.assertEqual({row["base_stage"] for row in rows}, {"decode", "preprocess"})
        self.assertEqual({row["execution_domain"] for row in rows}, {"runtime-host:pid-4321:worker-deepstream-baseline-stream-2-damage"})
        for row in rows:
            self.assertEqual(row["schema_version"], 2)
            self.assertEqual(row["semantic_contract_version"], 2)
            self.assertEqual(row["contract_provenance"], "runtime_loaded_configuration")
            self.assertEqual(row["implementation_artifact_provenance"], "runtime_loaded_artifacts_v1")
            self.assertEqual(row["telemetry_source"], "native")
            self.assertEqual(row["config_sha256"], hashlib.sha256(row["implementation_config_json"].encode("utf-8")).hexdigest())
            self.assertEqual(row["implementation_artifacts_sha256"], hashlib.sha256(row["implementation_artifacts_json"].encode("utf-8")).hexdigest())

    def test_shared_native_stage_contract_is_written_once_for_common_prefix(self) -> None:
        branches = ("plate_number", "vehicle_type", "damage", "foreign_object")
        digest = hashlib.sha256(b"plugin").hexdigest()
        rows = build_deepstream_stage_contract_rows(
            run_id="deepstream-v3-shared",
            worker_id="deepstream-shared-stream-0",
            topology_kind="shared_video_dag",
            branches=branches,
            execution_domain="runtime-host:pid-55:worker-deepstream-shared-stream-0",
            implementation_version="DeepStream-7.0/GStreamer-1.20.3",
            decode_config={"backend": "deepstream", "decoder_factory": "nvv4l2decoder"},
            preprocess_config={"backend": "deepstream", "converter_factory": "nvvideoconvert"},
            artifacts_by_stage={
                "decode": [{"role": "decoder", "kind": "plugin", "logical_name": "nvv4l2decoder", "sha256": digest}],
                "preprocess": [{"role": "format_converter", "kind": "plugin", "logical_name": "nvvideoconvert", "sha256": digest}],
            },
            decode_output={"media_type": "video/x-raw(memory:NVMM)", "format": "NV12", "shape": [1080, 1920, 3]},
            preprocess_output={"media_type": "video/x-raw", "format": "rgb24", "shape": [1080, 1920, 3]},
        )
        self.assertEqual([row["stage"] for row in rows], ["decode", "preprocess"])
        with tempfile.TemporaryDirectory() as temporary:
            path = write_deepstream_stage_contracts(Path(temporary), rows)
            lines = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(path.name, "stage_contracts.runtime.csv")
            self.assertEqual(len(lines), 3)
            with self.assertRaisesRegex(DeepStreamSdkRuntimeError, "already exists"):
                write_deepstream_stage_contracts(Path(temporary), rows)


class DeepStreamFdAndQueueTests(unittest.TestCase):
    def test_event_sink_writes_one_canonical_json_line_to_exact_fd(self) -> None:
        read_fd, write_fd = os.pipe()
        try:
            sink = CanonicalEventFdSink(write_fd)
            sink('{"b":2,"a":1}')
            os.close(write_fd)
            write_fd = -1
            self.assertEqual(os.read(read_fd, 1024), b'{"a":1,"b":2}\n')
        finally:
            os.close(read_fd)
            if write_fd >= 0:
                os.close(write_fd)

    def test_lifecycle_matches_coordinator_wire_grammar(self) -> None:
        control_read, control_write = os.pipe()
        status_read, status_write = os.pipe()
        try:
            channel = LifecycleChannel(
                worker_id="deepstream-shared-stream-0",
                control_fd=control_read,
                status_fd=status_write,
                monotonic_ns=lambda: 123,
                wall_time_ms=lambda: 456,
            )
            channel.ready()
            os.write(control_write, b"1 START 1000 2000 3000 4000\n")
            window = channel.await_start()
            self.assertEqual(window.common_start_monotonic_ns, 1000)
            channel.started()
            channel.decoder_placement_verified()
            os.write(control_write, b"1 STOP 3000\n")
            self.assertEqual(channel.await_stop(), 3000)
            channel.admission_stopped(3000)
            channel.drained(4000)
            os.close(status_write)
            status_write = -1
            lines = os.read(status_read, 4096).decode().splitlines()
            self.assertEqual(
                [line.split()[1] for line in lines],
                ["READY", "STARTED", "DECODER_PLACEMENT_VERIFIED", "ADMISSION_STOPPED", "DRAINED"],
            )
            self.assertTrue(all(line.split()[2] == "deepstream-shared-stream-0" for line in lines))
        finally:
            for fd in (control_read, control_write, status_read, status_write):
                if fd >= 0:
                    os.close(fd)

    def test_native_queue_drops_the_newest_buffer_at_capacity(self) -> None:
        drops: list[tuple[str, str]] = []
        queue = NativeBranchQueue(
            branch="damage",
            capacity_buffers=1,
            on_drop=lambda item, reason: drops.append((item, reason)),
        )
        self.assertTrue(queue.submit("first"))
        self.assertFalse(queue.submit("second"))
        self.assertEqual(queue.take_nowait(), "first")
        self.assertEqual(drops, [("second", "native_pre_detector_queue_full_drop_newest")])

    def test_pending_frame_is_evicted_only_after_every_exact_branch_terminal(self) -> None:
        graph = DeepStreamGraphSpec.build(
            topology_kind="shared_video_dag",
            codec="h264",
            stream_id=0,
            branches=("plate_number", "vehicle_type", "damage", "foreign_object"),
        )
        frame = AdmissionTransportFrame(
            sequence=1,
            keyframe=True,
            source_cycle=0,
            access_unit_pts_ns=0,
            transport_pts_ns=42,
            access_unit_dts_ns=MISSING_TIMESTAMP,
            duration_ns=1,
            admission_id="run:0:admission:1",
            input_frame_key="dataset:0:" + "a" * 64 + ":0:0",
            payload_sha256=hashlib.sha256(b"au").hexdigest(),
            payload=b"au",
        )
        identity = {
            "input_frame_key": frame.input_frame_key,
            "transport_pts_ns": frame.transport_pts_ns,
        }
        pipeline = object.__new__(DeepStreamSdkPipeline)
        pipeline.graph = graph
        pipeline._pending_lock = threading.RLock()
        pending = _PendingFrame(
            frame=frame,
            identity_sha256=admission_identity_sha256(frame),
            identity=dict(identity),
        )
        pipeline._pending = {frame.transport_pts_ns: pending}
        for branch in graph.branches[:-1]:
            pipeline._mark_branch_terminal(
                _BranchWork(identity=dict(identity), branch=branch, sample=object())
            )
            self.assertIn(frame.transport_pts_ns, pipeline._pending)
        pipeline._mark_branch_terminal(
            _BranchWork(identity=dict(identity), branch=graph.branches[-1], sample=object())
        )
        self.assertEqual(pipeline._pending, {})

    def test_nvdec_submit_timestamp_is_taken_after_buffer_materialization(self) -> None:
        graph = DeepStreamGraphSpec.build(
            topology_kind="independent_processes",
            codec="h264",
            stream_id=0,
            branches=("damage",),
        )
        frame = AdmissionTransportFrame(
            sequence=1,
            keyframe=True,
            source_cycle=0,
            access_unit_pts_ns=0,
            transport_pts_ns=42,
            access_unit_dts_ns=MISSING_TIMESTAMP,
            duration_ns=1,
            admission_id="run:0:admission:1",
            input_frame_key="dataset:0:" + "a" * 64 + ":0:0",
            payload_sha256=hashlib.sha256(b"au").hexdigest(),
            payload=b"au",
        )
        pipeline = object.__new__(DeepStreamSdkPipeline)
        pipeline.graph = graph
        pipeline._pending_lock = threading.RLock()
        pipeline._pending = {}
        pipeline._seen_transport_pts = set()
        pipeline.raise_callback_error = lambda: None

        class _Callbacks:
            def admit_transport_frame(self, observed: object, *, observed_timestamp_ms: int) -> None:
                self_outer.assertIs(observed, frame)
                self_outer.assertEqual(observed_timestamp_ms, 1)

        class _Buffer:
            pts = None
            dts = None
            duration = None

            @staticmethod
            def fill(offset: int, payload: bytes) -> int:
                self_outer.assertEqual(offset, 0)
                self_outer.assertEqual(payload, frame.payload)
                self_outer.assertIsNone(
                    pipeline._pending[frame.transport_pts_ns].decode_submit_start_ns
                )
                return len(payload)

            @staticmethod
            def unset_flags(_flags: object) -> None:
                return None

            @staticmethod
            def set_flags(_flags: object) -> None:
                raise AssertionError("keyframe must not be marked DELTA_UNIT")

        class _BufferFactory:
            @staticmethod
            def new_allocate(_allocator: object, size: int, _params: object) -> _Buffer:
                self_outer.assertEqual(size, len(frame.payload))
                return _Buffer()

        class _Gst:
            CLOCK_TIME_NONE = (1 << 64) - 1
            Buffer = _BufferFactory

            class BufferFlags:
                DELTA_UNIT = object()

            class FlowReturn:
                OK = object()

        class _AppSrc:
            @staticmethod
            def emit(signal: str, buffer: object) -> object:
                self_outer.assertEqual(signal, "push-buffer")
                self_outer.assertIsInstance(buffer, _Buffer)
                self_outer.assertEqual(
                    pipeline._pending[frame.transport_pts_ns].decode_submit_start_ns,
                    2_000_000,
                )
                return _Gst.FlowReturn.OK

        self_outer = self
        pipeline.callbacks = _Callbacks()
        pipeline.Gst = _Gst
        pipeline.appsrc = _AppSrc()
        with mock.patch(
            "checkpoint_deepstream_sdk_runtime.time.time_ns",
            side_effect=[1_000_000, 2_000_000],
        ):
            pipeline.push(frame)

    def test_finish_waits_for_every_appsink_eos_even_after_pipeline_bus_eos(self) -> None:
        branches = ("plate_number", "vehicle_type", "damage", "foreign_object")
        pipeline = object.__new__(DeepStreamSdkPipeline)
        pipeline.graph = DeepStreamGraphSpec.build(
            topology_kind="shared_video_dag",
            codec="h264",
            stream_id=0,
            branches=branches,
        )

        class _FlowReturn:
            OK = object()

        class _Gst:
            FlowReturn = _FlowReturn

        class _AppSrc:
            @staticmethod
            def emit(signal: str):
                self.assertEqual(signal, "end-of-stream")
                return _FlowReturn.OK

        pipeline.Gst = _Gst
        pipeline.appsrc = _AppSrc()
        pipeline._eos_seen = threading.Event()
        pipeline._eos_seen.set()
        pipeline._terminal_eos_seen = threading.Event()
        pipeline._terminal_eos_branches = set()
        pipeline._terminal_eos_lock = threading.Lock()
        pipeline._callback_error_lock = threading.Lock()
        pipeline._callback_error = None
        pipeline._queues = {}
        pipeline._pending_lock = threading.RLock()
        pipeline._pending = {}

        def observe_terminal_eos() -> None:
            with pipeline._terminal_eos_lock:
                pipeline._terminal_eos_branches.update(branches)
                pipeline._terminal_eos_seen.set()

        timer = threading.Timer(0.02, observe_terminal_eos)
        timer.start()
        try:
            pipeline.finish(timeout_s=1.0)
        finally:
            timer.cancel()
            timer.join()


if __name__ == "__main__":
    unittest.main()
