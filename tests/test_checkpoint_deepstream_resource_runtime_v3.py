from __future__ import annotations

import csv
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from checkpoint_deepstream_resource_runtime_v3 import (  # noqa: E402
    DeepStreamNativeResourceRecorderV3,
    FANOUT_WORK_COUNTER_COLUMNS,
    RESOURCE_INTERVAL_COLUMNS,
)


class DeepStreamNativeResourceRecorderV3Tests(unittest.TestCase):
    def _recorder(
        self,
        root: Path,
        *,
        topology: str,
        decoder_gpu_index: int = 0,
    ) -> DeepStreamNativeResourceRecorderV3:
        return DeepStreamNativeResourceRecorderV3(
            output_dir=root,
            run_id="deepstream-qualification-run-001",
            worker_id="deepstream-shared-stream-0",
            stream_id=0,
            topology_kind=topology,
            branches=("plate_number", "vehicle_type", "damage", "foreign_object")
            if topology == "shared_video_dag"
            else ("plate_number",),
            decoder_gpu_index=decoder_gpu_index,
        )

    def test_records_native_nvdec_interval_with_exact_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = self._recorder(
                root,
                topology="independent_processes",
                decoder_gpu_index=2,
            )
            recorder.record_nvdec(
                frame_id=7,
                input_frame_key="kpp_iss_publication_v3_h264:0:source-sha:0:123",
                payload_bytes=4096,
                start_timestamp_ns=1_000_000_100,
                end_timestamp_ns=1_000_001_900,
            )
            paths = recorder.close()

            self.assertEqual(set(paths), {"resource_intervals"})
            with paths["resource_intervals"].open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                self.assertEqual(reader.fieldnames, list(RESOURCE_INTERVAL_COLUMNS))
                rows = list(reader)
            self.assertEqual(len(rows), 1)
            row = rows[0]
            trace = "deepstream-qualification-run-001:0:7"
            self.assertEqual(row["component"], "nvdec_submit_complete")
            self.assertEqual(row["stage"], "decode_plate_number")
            self.assertEqual(row["branch_id"], "plate_number")
            self.assertEqual(row["trace_id"], trace)
            self.assertEqual(
                row["execution_id"], f"{trace}:plate_number:decode"
            )
            self.assertEqual(row["device_id"], "nvdec:2")
            self.assertEqual(row["duration_ns"], "1800")

    def test_shared_fanout_records_real_interval_and_thread_cpu_counter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = self._recorder(root, topology="shared_video_dag")
            recorder.record_nvdec(
                frame_id=3,
                input_frame_key="kpp_iss_publication_v3_h265:0:source-sha:0:456",
                payload_bytes=8192,
                start_timestamp_ns=2_000_000_000,
                end_timestamp_ns=2_000_010_000,
            )
            recorder.record_fanout(
                frame_id=3,
                input_frame_key="kpp_iss_publication_v3_h265:0:source-sha:0:456",
                branch="damage",
                payload_bytes=1920 * 1080 * 3,
                start_timestamp_ns=2_000_020_000,
                end_timestamp_ns=2_000_030_000,
                serialized_topology_timestamp_ms=2_001,
                thread_cpu_time_ns=321,
            )
            paths = recorder.close()

            self.assertEqual(
                set(paths), {"resource_intervals", "fanout_work_counters"}
            )
            with paths["resource_intervals"].open(newline="", encoding="utf-8") as source:
                intervals = list(csv.DictReader(source))
            fanout = next(row for row in intervals if row["component"] == "fanout")
            trace = "deepstream-qualification-run-001:0:3"
            self.assertEqual(
                fanout["execution_id"], f"{trace}:damage:fanout"
            )
            self.assertEqual(fanout["device_id"], "gstreamer:tee-queue")
            self.assertEqual(fanout["duration_provenance"], "native_gstreamer_pad_probe_interval_v1")

            with paths["fanout_work_counters"].open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                self.assertEqual(reader.fieldnames, list(FANOUT_WORK_COUNTER_COLUMNS))
                counters = list(reader)
            self.assertEqual(len(counters), 1)
            self.assertEqual(
                counters[0]["execution_id"], f"{trace}:damage:fanout"
            )
            self.assertEqual(counters[0]["thread_cpu_time_ns"], "321")
            self.assertEqual(counters[0]["work_units"], "1")
            self.assertEqual(counters[0]["counter_provenance"], "native_thread_cpu_time_v1")

    def test_fanout_interval_end_tracks_clamped_serialized_topology_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = self._recorder(root, topology="shared_video_dag")
            recorder.record_fanout(
                frame_id=4,
                input_frame_key="clamped-fanout-frame",
                branch="damage",
                payload_bytes=1920 * 1080 * 3,
                start_timestamp_ns=1_000_000_001,
                end_timestamp_ns=1_000_000_321,
                serialized_topology_timestamp_ms=1_004,
                thread_cpu_time_ns=123,
            )
            path = recorder.close()["resource_intervals"]
            with path.open(newline="", encoding="utf-8") as source:
                row = next(csv.DictReader(source))
            self.assertEqual(row["host_end_timestamp_ns"], "1004000000")
            self.assertEqual(row["duration_ns"], "3999999")

    def test_independent_topology_refuses_fanout_and_emits_no_counter_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            recorder = self._recorder(root, topology="independent_processes")
            with self.assertRaisesRegex(ValueError, "shared"):
                recorder.record_fanout(
                    frame_id=0,
                    input_frame_key="frame-key",
                    branch="plate_number",
                    payload_bytes=1,
                    start_timestamp_ns=10,
                    end_timestamp_ns=11,
                    serialized_topology_timestamp_ms=1,
                    thread_cpu_time_ns=1,
                )
            paths = recorder.close()
            self.assertEqual(set(paths), {"resource_intervals"})
            self.assertFalse((root / "fanout_work_counters.runtime.csv").exists())

    def test_gpu_cuda_intervals_bind_h2d_to_analytics_and_d2h_to_postprocess(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recorder = self._recorder(Path(tmp), topology="independent_processes")
            device_id = "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266"
            recorder.record_analytics_transfers(
                frame_id=9,
                input_frame_key="kpp-analytics-frame",
                branch="plate_number",
                selected_resource="gpu",
                worker_received_monotonic_ns=1_000_000,
                path_enter_timestamp_ns=5_000_000_000,
                resource={
                    "process_cpu_time_ns": 100,
                    "rss_before_bytes": 1_000,
                    "rss_after_bytes": 1_100,
                    "accelerator_memory_bytes": 4_096,
                    "cuda_h2d_bytes": 256,
                    "cuda_d2h_bytes": 64,
                    "cuda_transfer_intervals": [
                        {
                            "direction": "h2d",
                            "host_start_monotonic_ns": 1_050_000,
                            "host_end_monotonic_ns": 1_200_000,
                            "device_elapsed_ns": 100_000,
                            "bytes": 256,
                            "device_id": device_id,
                            "timing_source": "cudaEventElapsedTime",
                        },
                        {
                            "direction": "d2h",
                            "host_start_monotonic_ns": 1_350_000,
                            "host_end_monotonic_ns": 1_500_000,
                            "device_elapsed_ns": 90_000,
                            "bytes": 64,
                            "device_id": device_id,
                            "timing_source": "cudaEventElapsedTime",
                        },
                    ],
                },
            )
            path = recorder.close()["resource_intervals"]
            with path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))

            self.assertEqual([row["direction"] for row in rows], ["h2d", "d2h"])
            trace = "deepstream-qualification-run-001:0:9"
            self.assertEqual(rows[0]["stage"], "plate_number")
            self.assertEqual(rows[0]["execution_id"], f"{trace}:plate_number:analytics")
            self.assertEqual(rows[1]["stage"], "postprocess_plate_number")
            self.assertEqual(rows[1]["execution_id"], f"{trace}:plate_number:postprocess")
            self.assertEqual(rows[0]["duration_ns"], "100000")
            self.assertEqual(rows[1]["duration_ns"], "90000")
            self.assertEqual(rows[0]["device_id"], f"gpu:{device_id.lower()}")
            self.assertEqual(rows[1]["duration_provenance"], "native_cuda_event_interval_v1")

    def test_cpu_path_requires_empty_cuda_receipt_and_emits_no_transfer_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recorder = self._recorder(Path(tmp), topology="independent_processes")
            recorder.record_analytics_transfers(
                frame_id=1,
                input_frame_key="cpu-frame",
                branch="plate_number",
                selected_resource="cpu",
                worker_received_monotonic_ns=1_000,
                path_enter_timestamp_ns=2_000,
                resource={
                    "process_cpu_time_ns": 100,
                    "rss_before_bytes": 1_000,
                    "rss_after_bytes": 1_100,
                    "accelerator_memory_bytes": 0,
                    "cuda_h2d_bytes": 0,
                    "cuda_d2h_bytes": 0,
                    "cuda_transfer_intervals": [],
                },
            )
            path = recorder.close()["resource_intervals"]
            with path.open(newline="", encoding="utf-8") as source:
                self.assertEqual(list(csv.DictReader(source)), [])

    def test_rejects_overlapping_cuda_transfer_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recorder = self._recorder(Path(tmp), topology="independent_processes")
            with self.assertRaisesRegex(ValueError, "out of order"):
                recorder.record_analytics_transfers(
                    frame_id=1,
                    input_frame_key="gpu-frame",
                    branch="plate_number",
                    selected_resource="gpu",
                    worker_received_monotonic_ns=1_000_000,
                    path_enter_timestamp_ns=5_000_000_000,
                    resource={
                        "process_cpu_time_ns": 100,
                        "rss_before_bytes": 1_000,
                        "rss_after_bytes": 1_100,
                        "accelerator_memory_bytes": 4_096,
                        "cuda_h2d_bytes": 256,
                        "cuda_d2h_bytes": 64,
                        "cuda_transfer_intervals": [
                            {
                                "direction": "h2d",
                                "host_start_monotonic_ns": 1_050_000,
                                "host_end_monotonic_ns": 1_400_000,
                                "device_elapsed_ns": 100_000,
                                "bytes": 256,
                                "device_id": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                                "timing_source": "cudaEventElapsedTime",
                            },
                            {
                                "direction": "d2h",
                                "host_start_monotonic_ns": 1_300_000,
                                "host_end_monotonic_ns": 1_500_000,
                                "device_elapsed_ns": 90_000,
                                "bytes": 64,
                                "device_id": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                                "timing_source": "cudaEventElapsedTime",
                            },
                        ],
                    },
                )
            recorder.close()

    def test_rejects_nonpositive_measured_intervals_and_cpu_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            recorder = self._recorder(Path(tmp), topology="shared_video_dag")
            with self.assertRaisesRegex(ValueError, "timestamp"):
                recorder.record_nvdec(
                    frame_id=0,
                    input_frame_key="frame-key",
                    payload_bytes=1,
                    start_timestamp_ns=10,
                    end_timestamp_ns=10,
                )
            with self.assertRaisesRegex(ValueError, "thread CPU"):
                recorder.record_fanout(
                    frame_id=0,
                    input_frame_key="frame-key",
                    branch="plate_number",
                    payload_bytes=1,
                    start_timestamp_ns=10,
                    end_timestamp_ns=11,
                    serialized_topology_timestamp_ms=1,
                    thread_cpu_time_ns=0,
                )
            recorder.close()

    @unittest.skipUnless(
        importlib.util.find_spec("pandas") is not None,
        "merge integration requires the benchmark pandas runtime",
    )
    def test_fragments_join_canonical_trace_to_worker_execution_identity(self) -> None:
        from checkpoint_gstreamer_runtime import (  # imported only in benchmark runtime
            merge_runtime_fanout_work_counters,
            merge_runtime_resource_intervals,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = root / "worker"
            worker.mkdir()
            recorder = DeepStreamNativeResourceRecorderV3(
                output_dir=worker,
                run_id="merge-run",
                worker_id="deepstream-shared-stream-0",
                stream_id=0,
                topology_kind="shared_video_dag",
                branches=("plate_number", "vehicle_type", "damage", "foreign_object"),
                decoder_gpu_index=0,
            )
            recorder.record_nvdec(
                frame_id=3,
                input_frame_key="canonical-input",
                payload_bytes=100,
                start_timestamp_ns=2_000_000_000,
                end_timestamp_ns=2_000_010_000,
            )
            recorder.record_fanout(
                frame_id=3,
                input_frame_key="canonical-input",
                branch="damage",
                payload_bytes=200,
                # The parent is serialized at 2001 ms.  Its upward-rounded
                # millisecond value may be up to 1 ms ahead of the precise
                # native interval start without violating causal order.
                start_timestamp_ns=2_000_100_000,
                end_timestamp_ns=2_002_010_000,
                serialized_topology_timestamp_ms=2_003,
                thread_cpu_time_ns=100,
            )
            recorder.close()

            trace = "merge-run:0:3"
            local = f"{trace}:deepstream-shared-stream-0"
            source_id = f"{local}:source"
            decode_id = f"{trace}:shared:decode"
            preprocess_id = f"{trace}:shared:preprocess"
            fanout_id = f"{trace}:damage:fanout"

            def event(
                *, kind: str, stage: str, branch: str, execution: str,
                parents: list[str], timestamp_ms: int,
            ) -> dict[str, object]:
                return {
                    "run_id": "merge-run",
                    "trace_id": trace,
                    "stream_id": 0,
                    "frame_id": 3,
                    "input_frame_key": "canonical-input",
                    "event_kind": kind,
                    "stage": stage,
                    "branch_id": branch,
                    "execution_id": execution,
                    "parent_execution_ids_json": json.dumps(parents),
                    "timestamp_ms": timestamp_ms,
                }

            topology = [
                event(
                    kind="source_read", stage="source", branch="shared",
                    execution=source_id, parents=[], timestamp_ms=1_999,
                ),
                event(
                    kind="stage_complete", stage="decode", branch="shared",
                    execution=decode_id, parents=[source_id], timestamp_ms=2_001,
                ),
                event(
                    kind="stage_complete", stage="preprocess", branch="shared",
                    execution=preprocess_id, parents=[decode_id], timestamp_ms=2_001,
                ),
                event(
                    kind="fanout", stage="fanout", branch="damage",
                    execution=fanout_id, parents=[preprocess_id], timestamp_ms=2_003,
                ),
            ]
            spec = SimpleNamespace(
                worker_id="deepstream-shared-stream-0",
                stream_id=0,
                branch_id=None,
                command=("worker", "--output-dir", str(worker)),
            )
            merged_intervals = merge_runtime_resource_intervals(
                specs=[spec],
                output_root=root / "merged",
                run_id="merge-run",
                topology_events=topology,
            )
            merged_counters = merge_runtime_fanout_work_counters(
                specs=[spec],
                output_root=root / "merged",
                run_id="merge-run",
                topology_events=topology,
            )
            self.assertTrue(merged_intervals.is_file())
            self.assertIsNotNone(merged_counters)
            self.assertTrue(merged_counters.is_file())

    @unittest.skipUnless(
        importlib.util.find_spec("pandas") is not None,
        "merge integration requires the benchmark pandas runtime",
    )
    def test_gpu_merge_accepts_cuda_device_duration_inside_host_envelope(self) -> None:
        from checkpoint_gstreamer_runtime import (
            ContractError,
            merge_runtime_resource_intervals,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker = root / "worker"
            worker.mkdir()
            recorder = DeepStreamNativeResourceRecorderV3(
                output_dir=worker,
                run_id="gpu-merge-run",
                worker_id="deepstream-branch-plate-stream-0",
                stream_id=0,
                topology_kind="independent_processes",
                branches=("plate_number",),
                decoder_gpu_index=0,
            )
            recorder.record_nvdec(
                frame_id=9,
                input_frame_key="gpu-input",
                payload_bytes=100,
                start_timestamp_ns=1_999_100_000,
                end_timestamp_ns=1_999_200_000,
            )
            recorder.record_analytics_transfers(
                frame_id=9,
                input_frame_key="gpu-input",
                branch="plate_number",
                selected_resource="gpu",
                worker_received_monotonic_ns=1_000_000,
                path_enter_timestamp_ns=2_000_000_000,
                resource={
                    "process_cpu_time_ns": 100,
                    "rss_before_bytes": 1_000,
                    "rss_after_bytes": 1_100,
                    "accelerator_memory_bytes": 4_096,
                    "cuda_h2d_bytes": 256,
                    "cuda_d2h_bytes": 64,
                    "cuda_transfer_intervals": [
                        {
                            "direction": "h2d",
                            "host_start_monotonic_ns": 1_050_000,
                            "host_end_monotonic_ns": 1_200_000,
                            "device_elapsed_ns": 100_000,
                            "bytes": 256,
                            "device_id": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                            "timing_source": "cudaEventElapsedTime",
                        },
                        {
                            "direction": "d2h",
                            "host_start_monotonic_ns": 1_350_000,
                            "host_end_monotonic_ns": 1_500_000,
                            "device_elapsed_ns": 90_000,
                            "bytes": 64,
                            "device_id": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                            "timing_source": "cudaEventElapsedTime",
                        },
                    ],
                },
            )
            recorder.close()

            trace = "gpu-merge-run:0:9"

            def event(stage: str, branch: str, execution: str, parents: list[str], timestamp_ms: int) -> dict[str, object]:
                return {
                    "run_id": "gpu-merge-run",
                    "trace_id": trace,
                    "stream_id": 0,
                    "frame_id": 9,
                    "input_frame_key": "gpu-input",
                    "event_kind": "stage_complete" if stage != "source" else "source_read",
                    "stage": stage,
                    "branch_id": branch,
                    "execution_id": execution,
                    "parent_execution_ids_json": json.dumps(parents),
                    "timestamp_ms": timestamp_ms,
                }

            source_id = f"{trace}:deepstream-branch-plate-stream-0:source"
            decode_id = f"{trace}:plate_number:decode"
            preprocess_id = f"{trace}:plate_number:preprocess"
            analytics_id = f"{trace}:plate_number:analytics"
            postprocess_id = f"{trace}:plate_number:postprocess"
            topology = [
                # The exact NVDEC host interval begins 0.9 ms before the
                # source event's upward-rounded millisecond timestamp.
                event("source", "plate_number", source_id, [], 2_000),
                event("decode_plate_number", "plate_number", decode_id, [source_id], 2_000),
                event("preprocess_plate_number", "plate_number", preprocess_id, [decode_id], 2_005),
                event("plate_number", "plate_number", analytics_id, [preprocess_id], 2_005),
                event("postprocess_plate_number", "plate_number", postprocess_id, [analytics_id], 2_005),
            ]
            spec = SimpleNamespace(
                worker_id="deepstream-branch-plate-stream-0",
                stream_id=0,
                branch_id="plate_number",
                command=("worker", "--output-dir", str(worker)),
                environment={"SCHEDULER_POLICY": "gpu_only"},
            )
            merged = merge_runtime_resource_intervals(
                specs=[spec],
                output_root=root / "merged",
                run_id="gpu-merge-run",
                topology_events=topology,
            )
            with merged.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            transfers = [row for row in rows if row["component"] == "transfer"]
            self.assertEqual([row["direction"] for row in transfers], ["h2d", "d2h"])
            self.assertEqual([row["duration_ns"] for row in transfers], ["100000", "90000"])
            self.assertTrue(
                all(int(row["duration_ns"]) < int(row["host_end_timestamp_ns"]) - int(row["host_start_timestamp_ns"]) for row in transfers)
            )

            # A parent ahead of the interval by less than the platform backward
            # clock step is the WSL wall clock, not a causal violation.
            topology[0]["timestamp_ms"] = 2_005
            merge_runtime_resource_intervals(
                specs=[spec],
                output_root=root / "platform-step",
                run_id="gpu-merge-run",
                topology_events=topology,
            )

            # Beyond that bound the disorder still fails closed.
            topology[0]["timestamp_ms"] = 2_012
            with self.assertRaisesRegex(
                ContractError, "resource interval starts before its topology parent"
            ):
                merge_runtime_resource_intervals(
                    specs=[spec],
                    output_root=root / "rejected",
                    run_id="gpu-merge-run",
                    topology_events=topology,
                )


if __name__ == "__main__":
    unittest.main()
