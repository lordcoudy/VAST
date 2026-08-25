from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from checkpoint_savant_publication_specs_v3 import (  # noqa: E402
    SAVANT_SDK_RUNTIME,
    build_savant_publication_worker_specs,
)
from checkpoint_savant_runtime import build_savant_runtime_plan  # noqa: E402
from checkpoint_savant_resource_runtime_v3 import (  # noqa: E402
    EMITTER_ID,
    SavantNativeResourceRecorderV3,
)
import checkpoint_savant_sdk_runtime_v3 as savant_sdk_runtime_v3  # noqa: E402
from checkpoint_savant_sdk_runtime_v3 import (  # noqa: E402
    SavantSdkCallbackRuntime,
    materialize_worker_module_config,
)


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")


def plan(topology: str, codec: str = "h264") -> dict:
    config = yaml.safe_load(
        (ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8")
    )
    datasets = yaml.safe_load(
        (ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8")
    )["datasets"]
    scenario = (
        "checkpoint_independent_processes_baseline"
        if topology == "independent_processes"
        else "checkpoint_video_dag_shared"
    )
    return build_savant_runtime_plan(
        config=config,
        datasets=datasets,
        scenario=scenario,
        codec=codec,
        policy="cpu_only",
        deadline_ms=33.3,
    )


class SavantSdkRuntimeV3Tests(unittest.TestCase):
    def test_google_api_core_python_eol_warning_is_suppressed(self) -> None:
        expected = (
            "You are using a Python version (3.10.12) which Google will stop "
            "supporting in new releases of google.api_core once it reaches its "
            "end of life (2026-10-04). Please upgrade to the latest Python "
            "version, or at least Python 3.11, to continue receiving updates "
            "for google.api_core past that date."
        )
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            savant_sdk_runtime_v3._install_google_api_core_python_eol_filter()
            warnings.warn_explicit(
                expected,
                FutureWarning,
                filename="google/api_core/_python_version_support.py",
                lineno=275,
                module="google.api_core._python_version_support",
            )
        self.assertEqual(observed, [])

    def test_google_api_core_filter_keeps_unrelated_future_warning_visible(self) -> None:
        unrelated = "unrelated dependency remains visible"
        with warnings.catch_warnings(record=True) as observed:
            warnings.simplefilter("always")
            savant_sdk_runtime_v3._install_google_api_core_python_eol_filter()
            warnings.warn_explicit(
                unrelated,
                FutureWarning,
                filename="unrelated_dependency.py",
                lineno=1,
                module="unrelated_dependency",
            )
        self.assertEqual([str(item.message) for item in observed], [unrelated])

    def test_single_arm_specs_are_exact_24_or_6_genuine_sdk_workers(self) -> None:
        for topology, expected in (
            ("independent_processes", 24),
            ("shared_video_dag", 6),
        ):
            with self.subTest(topology=topology):
                value = plan(topology)
                specs = build_savant_publication_worker_specs(
                    value,
                        run_id="run-savant-v3",
                        arm_id="arm-savant-v3",
                        adapter_config_path="/opt/vast/input/adapter.json",
                        output_root=Path("/opt/vast/output/native_runtime"),
                        inherited_fds=(41, 43),
                )
                self.assertEqual(len(specs), expected)
                self.assertEqual({spec.stream_id for spec in specs}, set(range(6)))
                self.assertTrue(all(spec.native_event_source for spec in specs))
                self.assertTrue(all(spec.inherited_fds == (41, 43) for spec in specs))
                self.assertEqual(
                    len({spec.environment["SAVANT_STATUS_FILEPATH"] for spec in specs}),
                    expected,
                )
                self.assertEqual(
                    len({spec.environment["GST_REGISTRY"] for spec in specs}),
                    expected,
                )
                for spec in specs:
                    self.assertEqual(spec.command[:3], ("python3", "-B", SAVANT_SDK_RUNTIME))
                    self.assertIn("run", spec.command)
                    self.assertEqual(
                        spec.environment["VAST_SAVANT_ADAPTER_CONFIG"],
                        "/opt/vast/input/adapter.json",
                    )
                    descriptor = json.loads(
                        spec.environment["VAST_SAVANT_MODULE_DESCRIPTOR_JSON"]
                    )
                    source = json.loads(
                        spec.environment["VAST_SAVANT_SOURCE_BINDING_JSON"]
                    )
                    self.assertEqual(descriptor["module_id"], spec.worker_id)
                    self.assertEqual(source["stream_id"], spec.stream_id)
                    self.assertEqual(
                        source["source_id"],
                        (
                            "kpp_underbody_avi-stream-5"
                            if spec.stream_id == 5
                            else f"kpp_plate_avi-stream-{spec.stream_id}"
                        ),
                    )

    def test_worker_materializes_hash_bound_official_savant_module_config(self) -> None:
        value = plan("shared_video_dag")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            specs = build_savant_publication_worker_specs(
                value,
                run_id="run-savant-v3",
                arm_id="arm-savant-v3",
                adapter_config_path="/opt/vast/input/adapter.json",
                output_root=Path("/opt/vast/output/native_runtime"),
            )
            spec = specs[0]
            worker_output = output / "workers" / spec.worker_id
            worker_output.mkdir(parents=True)
            result = materialize_worker_module_config(
                output_dir=worker_output,
                descriptor_json=spec.environment[
                    "VAST_SAVANT_MODULE_DESCRIPTOR_JSON"
                ],
                source_json=spec.environment["VAST_SAVANT_SOURCE_BINDING_JSON"],
            )
            self.assertEqual(result["path"], worker_output / "module.json")
            self.assertTrue(result["path"].is_file())
            self.assertEqual(result["binding"].module_id, spec.worker_id)
            config = json.loads(result["path"].read_text(encoding="utf-8"))
            self.assertEqual(
                config["pipeline"]["pipeline_class"],
                "checkpoint_savant_native_module.SavantCheckpointNvDsPipeline",
            )
            self.assertEqual(
                [row["element"] for row in config["pipeline"]["elements"]],
                ["pyfunc"],
            )
            with self.assertRaises(Exception):
                materialize_worker_module_config(
                    output_dir=worker_output,
                    descriptor_json=spec.environment[
                        "VAST_SAVANT_MODULE_DESCRIPTOR_JSON"
                    ],
                    source_json=spec.environment[
                        "VAST_SAVANT_SOURCE_BINDING_JSON"
                    ],
                )


    def test_resource_emitter_uses_canonical_coordinator_trace_and_physical_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            recorder = SavantNativeResourceRecorderV3(
                output_dir=output,
                run_id="run-savant-v3",
                worker_id="savant-stream-0-shared-video-dag",
                stream_id=0,
                topology_kind="shared_video_dag",
                branches=BRANCHES,
            )
            recorder.record_nvdec(
                frame_id=7, input_frame_key="input-key-7",
                payload_bytes=4096,
                start_timestamp_ns=10, end_timestamp_ns=20,
            )
            recorder.record_fanout(
                frame_id=7, input_frame_key="input-key-7",
                branch="plate_number", payload_bytes=8192,
                start_timestamp_ns=21, end_timestamp_ns=25,
                thread_cpu_time_ns=3,
            )
            recorder.record_analytics_transfers(
                frame_id=7,
                input_frame_key="input-key-7",
                branch="plate_number",
                selected_resource="cpu",
                worker_received_monotonic_ns=100,
                path_enter_timestamp_ns=1_000,
                resource={
                    "process_cpu_time_ns": 10,
                    "rss_before_bytes": 1,
                    "rss_after_bytes": 1,
                    "accelerator_memory_bytes": 0,
                    "cuda_h2d_bytes": 0,
                    "cuda_d2h_bytes": 0,
                    "cuda_transfer_intervals": [],
                },
            )
            recorder.record_analytics_transfers(
                frame_id=7,
                input_frame_key="input-key-7",
                branch="plate_number",
                selected_resource="gpu",
                worker_received_monotonic_ns=100,
                path_enter_timestamp_ns=1_000,
                resource={
                    "process_cpu_time_ns": 10,
                    "rss_before_bytes": 1,
                    "rss_after_bytes": 2,
                    "accelerator_memory_bytes": 4_096,
                    "cuda_h2d_bytes": 2_048,
                    "cuda_d2h_bytes": 1_024,
                    "cuda_transfer_intervals": [
                        {
                            "direction": "h2d",
                            "host_start_monotonic_ns": 110,
                            "host_end_monotonic_ns": 120,
                            "device_elapsed_ns": 8,
                            "bytes": 2_048,
                            "device_id": "GPU-test-uuid",
                            "timing_source": "cudaEventElapsedTime",
                        },
                        {
                            "direction": "d2h",
                            "host_start_monotonic_ns": 130,
                            "host_end_monotonic_ns": 145,
                            "device_elapsed_ns": 11,
                            "bytes": 1_024,
                            "device_id": "GPU-test-uuid",
                            "timing_source": "cudaEventElapsedTime",
                        },
                    ],
                },
            )
            paths = recorder.close()
            self.assertEqual(
                set(paths),
                {"resource_intervals", "fanout_work_counters"},
            )
            rows = paths["resource_intervals"].read_text(
                encoding="utf-8"
            ).splitlines()
            self.assertIn("run-savant-v3:0:7", rows[1])
            self.assertNotIn(
                "savant-stream-0-shared-video-dag", rows[1]
            )
            self.assertEqual(
                recorder.emitter_id, EMITTER_ID
            )
            with paths["resource_intervals"].open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                interval_rows = list(csv.DictReader(handle))
            transfer_rows = [
                row for row in interval_rows if row["component"] == "transfer"
            ]
            self.assertEqual(
                [(row["direction"], row["stage"]) for row in transfer_rows],
                [("h2d", "plate_number"), ("d2h", "postprocess_plate_number")],
            )
            self.assertEqual(
                [row["execution_id"] for row in transfer_rows],
                [
                    "run-savant-v3:0:7:plate_number:analytics",
                    "run-savant-v3:0:7:plate_number:postprocess",
                ],
            )



    def test_callback_runtime_binds_native_admission_to_nvdec_and_fanout_intervals(self) -> None:
        value = plan("shared_video_dag")
        specs = build_savant_publication_worker_specs(
            value,
            run_id="run-savant-v3",
            arm_id="arm-savant-v3",
            adapter_config_path="/opt/vast/input/adapter.json",
            output_root=Path("/opt/vast/output/native_runtime"),
        )
        spec = specs[0]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary).resolve()
            materialized = materialize_worker_module_config(
                output_dir=output,
                descriptor_json=spec.environment[
                    "VAST_SAVANT_MODULE_DESCRIPTOR_JSON"
                ],
                source_json=spec.environment[
                    "VAST_SAVANT_SOURCE_BINDING_JSON"
                ],
            )

            class Callbacks:
                def __init__(self) -> None:
                    self.admissions = []
                    self.decoded = []
                    self.preprocessed = []
                    self.fanout = []
                    self.terminals = []

                def admit_transport_frame(self, frame, **values) -> None:
                    self.admissions.append((frame, values))

                def observe_decoded_frame(self, identity, **values) -> None:
                    self.decoded.append((identity, values))

                def observe_preprocessed_frame(self, identity, **values) -> None:
                    self.preprocessed.append((identity, values))

                def observe_fanout(self, identity, **values) -> None:
                    self.fanout.append((identity, values))

                def execute_branch_sample(self, identity, **values) -> None:
                    self.terminals.append((identity, values))

            class Recorder:
                def __init__(self) -> None:
                    self.nvdec = []
                    self.fanout = []

                def record_nvdec(self, **values) -> None:
                    self.nvdec.append(values)

                def record_fanout(self, **values) -> None:
                    self.fanout.append(values)

            callbacks = Callbacks()
            recorder = Recorder()
            runtime = SavantSdkCallbackRuntime(
                binding=materialized["binding"],
                callbacks=callbacks,
                resource_recorder=recorder,
            )
            runtime.bind_decoder("nvv4l2decoder", 0)
            frame = SimpleNamespace(
                frame_id=0,
                transport_pts_ns=100,
                input_frame_key="input-key-0",
                payload=b"encoded-access-unit",
            )
            runtime.admit_transport_frame(frame)
            identity = {
                "transport_pts_ns": 100,
                "frame_id": 0,
                "input_frame_key": "input-key-0",
            }
            with mock.patch(
                "checkpoint_savant_sdk_runtime_v3.build_native_frame_identity",
                return_value=identity,
            ):
                runtime.observe_prefix(
                    SimpleNamespace(pts=100),
                    SimpleNamespace(),
                    materialized["binding"],
                )
            runtime.capture_preprocess_caps = lambda _caps: None
            buffer = SimpleNamespace(pts=100, get_size=lambda: 8192)
            for branch in BRANCHES:
                runtime.observe_route_buffer(
                    buffer,
                    materialized["binding"],
                    branch,
                    sample=object(),
                    caps=object(),
                )
            runtime.assert_drained()
            self.assertEqual(len(callbacks.admissions), 1)
            self.assertEqual(len(recorder.nvdec), 1)
            self.assertEqual(len(recorder.fanout), 4)
            self.assertEqual(recorder.nvdec[0]["frame_id"], 0)
            self.assertEqual(recorder.nvdec[0]["input_frame_key"], "input-key-0")
            self.assertTrue(
                recorder.nvdec[0]["start_timestamp_ns"]
                < recorder.nvdec[0]["end_timestamp_ns"]
            )
            self.assertEqual(
                {row["branch"] for row in recorder.fanout}, set(BRANCHES)
            )
            self.assertTrue(
                all(row["thread_cpu_time_ns"] > 0 for row in recorder.fanout)
            )


if __name__ == "__main__":
    unittest.main()
