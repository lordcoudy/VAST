from __future__ import annotations

import csv
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from checkpoint_gstreamer_runtime import (  # noqa: E402
    checkpoint_decoder_factories,
    merge_runtime_resource_intervals,
    promote_runtime_interval_and_fanout_evidence,
    promote_runtime_full_resource_evidence,
    seed_gstreamer_registry_copies,
    validate_worker_source_provenance,
)
from checkpoint_runtime import SourceLaunchSpec, WorkerLaunchSpec  # noqa: E402
from full_resource_contract import (  # noqa: E402
    FANOUT_WORK_COUNTER_COLUMNS,
    HARDWARE_RESOURCE_SAMPLE_COLUMNS,
    FullResourceContractError,
    validate_full_resource_evidence,
    validate_hardware_resource_samples,
)
from resource_interval_contract import RESOURCE_INTERVAL_COLUMNS  # noqa: E402


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def nvdec_row(*, frame_id: int = 7, trace_id: str = "run-1:0:7") -> dict[str, object]:
    return {
        "schema_version": 2,
        "interval_contract_version": 2,
        "run_id": "run-1",
        "trace_id": trace_id,
        "stream_id": 0,
        "frame_id": frame_id,
        "input_frame_key": f"kpp_real_h265:0:source:0:{frame_id}",
        "component": "nvdec_submit_complete",
        "direction": "none",
        "stage": "decode",
        "branch_id": "shared",
        "execution_id": f"{trace_id}:shared:decode",
        "host_start_timestamp_ns": 1_000_000_100,
        "host_end_timestamp_ns": 1_000_000_500,
        "duration_ns": 400,
        "bytes": 42_000,
        "device_id": "nvdec:0",
        "counter_scope": "per_trace_interval",
        "native_event_id": hashlib.sha256(f"nvdec-{frame_id}".encode()).hexdigest(),
        "duration_provenance": "native_decoder_submit_complete_interval_v1",
        "telemetry_source": "native",
    }


def fanout_row(*, frame_id: int = 7, trace_id: str = "run-1:0:7") -> dict[str, object]:
    return {
        "schema_version": 2,
        "interval_contract_version": 2,
        "run_id": "run-1",
        "trace_id": trace_id,
        "stream_id": 0,
        "frame_id": frame_id,
        "input_frame_key": f"kpp_real_h265:0:source:0:{frame_id}",
        "component": "fanout",
        "direction": "none",
        "stage": "fanout",
        "branch_id": "damage",
        "execution_id": f"{trace_id}:damage:fanout",
        "host_start_timestamp_ns": 1_000_000_600,
        "host_end_timestamp_ns": 1_000_000_900,
        "duration_ns": 300,
        "bytes": 691_200,
        "device_id": "gstreamer:tee-queue",
        "counter_scope": "per_trace_interval",
        "native_event_id": hashlib.sha256(f"fanout-{frame_id}".encode()).hexdigest(),
        "duration_provenance": "native_gstreamer_pad_probe_interval_v1",
        "telemetry_source": "native",
    }


def topology_rows() -> list[dict[str, object]]:
    trace_id = "run-1:0:7"
    input_frame_key = "kpp_real_h265:0:source:0:7"
    source_id = f"{trace_id}:shared:source"
    decode_id = f"{trace_id}:shared:decode"
    preprocess_id = f"{trace_id}:shared:preprocess"
    return [
        {
            "run_id": "run-1",
            "trace_id": trace_id,
            "stream_id": 0,
            "frame_id": 7,
            "input_frame_key": input_frame_key,
            "event_kind": "source_read",
            "stage": "source",
            "branch_id": "shared",
            "execution_id": source_id,
            "parent_execution_ids_json": "[]",
            "timestamp_ms": 1000,
        },
        {
            "run_id": "run-1",
            "trace_id": trace_id,
            "stream_id": 0,
            "frame_id": 7,
            "input_frame_key": input_frame_key,
            "event_kind": "stage_complete",
            "stage": "decode",
            "branch_id": "shared",
            "execution_id": decode_id,
            "parent_execution_ids_json": json.dumps([source_id]),
            "timestamp_ms": 1000,
        },
        {
            "run_id": "run-1",
            "trace_id": trace_id,
            "stream_id": 0,
            "frame_id": 7,
            "input_frame_key": input_frame_key,
            "event_kind": "stage_complete",
            "stage": "preprocess",
            "branch_id": "shared",
            "execution_id": preprocess_id,
            "parent_execution_ids_json": json.dumps([decode_id]),
            "timestamp_ms": 1000,
        },
        {
            "run_id": "run-1",
            "trace_id": trace_id,
            "stream_id": 0,
            "frame_id": 7,
            "input_frame_key": input_frame_key,
            "event_kind": "fanout",
            "stage": "fanout",
            "branch_id": "damage",
            "execution_id": f"{trace_id}:damage:fanout",
            "parent_execution_ids_json": json.dumps([preprocess_id]),
            "timestamp_ms": 1000,
        },
    ]


class FullResourceRuntimeV2Tests(unittest.TestCase):
    def test_native_binding_reads_the_loaded_decoder_device_instead_of_hardcoding_gpu_zero(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(
            encoding="utf-8"
        )
        self.assertIn('"cuda-device-id"', body)
        self.assertIn('"gpu-id"', body)
        self.assertNotIn('\n            "nvdec:0",\n', body)

    def test_codec_specific_hardware_decoder_allowlists_include_h265(self) -> None:
        self.assertEqual(checkpoint_decoder_factories("h264"), ("nvh264dec", "nvv4l2decoder"))
        self.assertEqual(checkpoint_decoder_factories("h265"), ("nvh265dec", "nvv4l2decoder"))
        with self.assertRaisesRegex(ContractError, "unsupported checkpoint codec"):
            checkpoint_decoder_factories("vp9")

    def test_h265_worker_provenance_rejects_h264_factory_aliasing(self) -> None:
        command = (
            "/tmp/probe",
            "--dataset-id", "kpp_real_h265",
            "--source-sha256", "a" * 64,
            "--checkpoint-container", "mp4",
            "--checkpoint-codec", "h265",
            "--checkpoint-allowed-decoder-factories", "nvh265dec,nvv4l2decoder",
            "--source-duration-ns", "1000",
            "--source-replay", "continuous",
        )
        environment = {
            "VAST_CHECKPOINT_DATASET_ID": "kpp_real_h265",
            "VAST_CHECKPOINT_SOURCE_SHA256": "a" * 64,
            "VAST_CHECKPOINT_SOURCE_CONTAINER": "mp4",
            "VAST_CHECKPOINT_SOURCE_CODEC": "h265",
            "VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES": "nvh265dec,nvv4l2decoder",
            "VAST_CHECKPOINT_SOURCE_DURATION_NS": "1000",
            "VAST_CHECKPOINT_SOURCE_REPLAY": "continuous",
            "VAST_CHECKPOINT_ADMISSION_MODE": "native_common_source_coordinator",
        }
        spec = WorkerLaunchSpec(
            worker_id="worker-h265",
            stream_id=0,
            branch_id=None,
            command=command,
            environment=environment,
            native_event_source=True,
        )
        validate_worker_source_provenance([spec])
        drifted = WorkerLaunchSpec(
            worker_id=spec.worker_id,
            stream_id=spec.stream_id,
            branch_id=spec.branch_id,
            command=tuple(
                "nvh264dec,nvv4l2decoder" if value == "nvh265dec,nvv4l2decoder" else value
                for value in command
            ),
            environment={
                **environment,
                "VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES": "nvh264dec,nvv4l2decoder",
            },
            native_event_source=True,
        )
        with self.assertRaisesRegex(ContractError, "differs from codec contract"):
            validate_worker_source_provenance([drifted])

    def test_registry_refresh_probes_the_codec_specific_hardware_decoder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            template = root / "template.bin"
            template.write_bytes(b"base-registry")
            worker = WorkerLaunchSpec(
                worker_id="worker-h265",
                stream_id=0,
                branch_id=None,
                command=("probe", "--checkpoint-codec", "h265"),
                environment={
                    "GST_REGISTRY": str(root / "worker.bin"),
                    "GST_REGISTRY_UPDATE": "no",
                },
            )
            source = SourceLaunchSpec(
                source_process_id="source-0",
                stream_id=0,
                dataset_id="kpp_real_h265",
                source_sha256="a" * 64,
                command=("source", "--checkpoint-codec", "h265"),
                environment={
                    "GST_REGISTRY": str(root / "source.bin"),
                    "GST_REGISTRY_UPDATE": "no",
                },
            )
            commands: list[tuple[str, ...]] = []

            def fake_run(command, **kwargs):
                commands.append(tuple(command))
                registry = Path(kwargs["env"]["GST_REGISTRY"])
                registry.write_bytes(b"hardware-registry")
                return subprocess.CompletedProcess(command, 0, "", "")

            with mock.patch("checkpoint_gstreamer_runtime.subprocess.run", side_effect=fake_run):
                manifest = seed_gstreamer_registry_copies(
                    [worker],
                    [source],
                    template_path=template,
                    refresh_hardware_plugins=True,
                )

        self.assertIn(("gst-inspect-1.0", "nvh265dec"), commands)
        self.assertNotIn(("gst-inspect-1.0", "nvh264dec"), commands)
        self.assertEqual(manifest["hardware_refresh"]["factories_by_codec"], {"h265": "nvh265dec"})

    def test_cpp_emitter_writes_native_nvdec_and_fanout_rows(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("C++ compiler is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "resource-v2-emitter-test"
            fragment = root / "resource_intervals.runtime.csv"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "checkpoint_resource_v2_emitter_test.cpp"),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            emitted = subprocess.run([str(binary), str(fragment)], capture_output=True, text=True)
            self.assertEqual(emitted.returncode, 0, emitted.stderr)
            with fragment.open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                rows = list(reader)
        self.assertEqual(reader.fieldnames, RESOURCE_INTERVAL_COLUMNS)
        self.assertEqual([row["component"] for row in rows], ["nvdec_submit_complete", "fanout"])
        self.assertEqual(rows[0]["device_id"], "nvdec:0")
        self.assertEqual(rows[0]["duration_provenance"], "native_decoder_submit_complete_interval_v1")

    def test_runtime_merge_requires_exact_nvdec_and_shared_fanout_coverage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_output = root / "workers" / "shared-0"
            fragment = worker_output / "resource_intervals.runtime.csv"
            write_csv(fragment, RESOURCE_INTERVAL_COLUMNS, [nvdec_row(), fanout_row()])
            spec = WorkerLaunchSpec(
                worker_id="shared-0",
                stream_id=0,
                branch_id=None,
                command=("/tmp/probe", "--output-dir", str(worker_output)),
                native_event_source=True,
            )
            merged = merge_runtime_resource_intervals(
                specs=[spec],
                output_root=root,
                run_id="run-1",
                topology_events=topology_rows(),
            )
            with merged.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
            self.assertEqual({row["component"] for row in rows}, {"nvdec_submit_complete", "fanout"})
            self.assertFalse((root / "resource_intervals.csv").exists())

            write_csv(fragment, RESOURCE_INTERVAL_COLUMNS, [fanout_row()])
            with self.assertRaisesRegex(ContractError, "NVDEC.*coverage"):
                merge_runtime_resource_intervals(
                    specs=[spec],
                    output_root=root,
                    run_id="run-1",
                    topology_events=topology_rows(),
                )

    def test_each_nvml_device_must_cover_the_measurement_window(self) -> None:
        rows = []
        for device_id, sequence, timestamp_ns in (
            ("gpu:0", 1, 1_000_000_000),
            ("gpu:0", 2, 2_000_000_000),
            ("gpu:1", 1, 2_000_000_000),
            ("gpu:1", 2, 3_000_000_000),
        ):
            rows.append(
                {
                    "schema_version": 2,
                    "resource_contract_version": 2,
                    "run_id": "run-1",
                    "sample_seq": sequence,
                    "timestamp_ns": timestamp_ns,
                    "sample_period_us": 1_000_000,
                    "device_id": device_id,
                    "nvdec_util_percent": 50,
                    "gpu_util_percent": 25,
                    "memory_util_percent": 10,
                    "vram_used_bytes": 1_000_000,
                    "counter_scope": "device_sample",
                    "sample_provenance": "nvml_device_decoder_utilization_v1",
                    "telemetry_source": "native",
                }
            )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hardware_resource_samples.csv"
            write_csv(path, HARDWARE_RESOURCE_SAMPLE_COLUMNS, rows)
            with self.assertRaisesRegex(FullResourceContractError, "each GPU device"):
                validate_hardware_resource_samples(
                    path,
                    expected_run_id="run-1",
                    window_start_ns=0,
                    window_end_ns=3_000_000_000,
                )

    def test_full_gate_requires_positive_and_device_bound_nvdec_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "resource_intervals.csv").write_text("validated by mock\n", encoding="utf-8")
            fanout_work = {
                "schema_version": 2,
                "resource_contract_version": 2,
                "run_id": "run-1",
                "trace_id": "run-1:0:7",
                "stream_id": 0,
                "frame_id": 7,
                "input_frame_key": "kpp_real_h265:0:source:0:7",
                "branch_id": "damage",
                "execution_id": "run-1:0:7:damage:fanout",
                "thread_cpu_time_ns": 10,
                "work_units": 1,
                "device_id": "host:fanout",
                "counter_scope": "per_trace_resource_work",
                "counter_provenance": "native_thread_cpu_time_v1",
                "telemetry_source": "native",
            }
            write_csv(root / "fanout_work_counters.csv", FANOUT_WORK_COUNTER_COLUMNS, [fanout_work])
            ingress = pd.DataFrame(
                [{"window_start_timestamp_ms": 0, "window_end_timestamp_ms": 3000}]
            )
            topology = pd.DataFrame(
                [
                    {
                        "event_kind": "fanout",
                        "trace_id": "run-1:0:7",
                        "stream_id": 0,
                        "frame_id": 7,
                        "branch_id": "damage",
                        "execution_id": "run-1:0:7:damage:fanout",
                    }
                ]
            )
            interval_frame = pd.DataFrame(
                [{"component": "nvdec_submit_complete", "device_id": "nvdec:0"}]
            )
            zero_samples = []
            for sequence in (1, 2, 3):
                zero_samples.append(
                    {
                        "schema_version": 2,
                        "resource_contract_version": 2,
                        "run_id": "run-1",
                        "sample_seq": sequence,
                        "timestamp_ns": sequence * 1_000_000_000,
                        "sample_period_us": 1_000_000,
                        "device_id": "gpu:0",
                        "nvdec_util_percent": 0,
                        "gpu_util_percent": 0,
                        "memory_util_percent": 0,
                        "vram_used_bytes": 1,
                        "counter_scope": "device_sample",
                        "sample_provenance": "nvml_device_decoder_utilization_v1",
                        "telemetry_source": "native",
                    }
                )
            write_csv(root / "hardware_resource_samples.csv", HARDWARE_RESOURCE_SAMPLE_COLUMNS, zero_samples)
            with (
                mock.patch("full_resource_contract.validate_resource_intervals", return_value=interval_frame),
                mock.patch(
                    "full_resource_contract.summarize_resource_interval_extension",
                    return_value={"coverage_complete": True},
                ),
            ):
                with self.assertRaisesRegex(FullResourceContractError, "positive NVDEC"):
                    validate_full_resource_evidence(
                        root,
                        expected_run_id="run-1",
                        ingress_ledger=ingress,
                        topology_events=topology,
                        frame_events=pd.DataFrame(),
                        topology_kind="shared_video_dag",
                    )

                positive_samples = [dict(row) for row in zero_samples]
                positive_samples[1]["nvdec_util_percent"] = 50
                write_csv(
                    root / "hardware_resource_samples.csv",
                    HARDWARE_RESOURCE_SAMPLE_COLUMNS,
                    positive_samples,
                )
                mismatched_intervals = pd.DataFrame(
                    [{"component": "nvdec_submit_complete", "device_id": "nvdec:1"}]
                )
                with mock.patch(
                    "full_resource_contract.validate_resource_intervals",
                    return_value=mismatched_intervals,
                ):
                    with self.assertRaisesRegex(FullResourceContractError, "sampled GPU device"):
                        validate_full_resource_evidence(
                            root,
                            expected_run_id="run-1",
                            ingress_ledger=ingress,
                            topology_events=topology,
                            frame_events=pd.DataFrame(),
                            topology_kind="shared_video_dag",
                        )

    def test_promotion_is_fail_closed_and_never_promotes_warmup_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "native_runtime"
            accepted = root / "accepted"
            measurement = nvdec_row()
            warmup = nvdec_row(frame_id=6, trace_id="run-1:0:6")
            write_csv(runtime / "resource_intervals.runtime.csv", RESOURCE_INTERVAL_COLUMNS, [warmup, measurement])
            write_csv(runtime / "fanout_work_counters.runtime.csv", FANOUT_WORK_COUNTER_COLUMNS, [])
            write_csv(runtime / "hardware_resource_samples.runtime.csv", HARDWARE_RESOURCE_SAMPLE_COLUMNS, [])
            ingress = pd.DataFrame(
                [
                    {
                        "run_id": "run-1",
                        "trace_id": "run-1:0:7",
                        "stream_id": 0,
                        "frame_id": 7,
                        "input_frame_key": "kpp_real_h265:0:source:0:7",
                        "window_start_timestamp_ms": 0,
                        "window_end_timestamp_ms": 3000,
                    }
                ]
            )
            with self.assertRaises(FullResourceContractError):
                promote_runtime_full_resource_evidence(
                    runtime_resource_intervals=runtime / "resource_intervals.runtime.csv",
                    runtime_hardware_samples=runtime / "hardware_resource_samples.runtime.csv",
                    runtime_fanout_work_counters=runtime / "fanout_work_counters.runtime.csv",
                    output_root=accepted,
                    expected_run_id="run-1",
                    ingress_ledger=ingress,
                    topology_events=pd.DataFrame(topology_rows()[:2]),
                    frame_events=pd.DataFrame(),
                    topology_kind="independent_processes",
                )
            self.assertFalse((accepted / "resource_intervals.csv").exists())
            self.assertFalse((accepted / "hardware_resource_samples.csv").exists())
            self.assertFalse((accepted / "fanout_work_counters.csv").exists())

    def test_promotion_accepts_only_a_fully_valid_native_measurement_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "native_runtime"
            accepted = root / "accepted"
            measurement = nvdec_row()
            measurement.update(
                {
                    "stage": "decode_damage",
                    "branch_id": "damage",
                    "execution_id": "run-1:0:7:damage:decode",
                }
            )
            warmup = dict(measurement)
            warmup.update(
                {
                    "trace_id": "run-1:0:6",
                    "frame_id": 6,
                    "input_frame_key": "kpp_real_h265:0:source:0:6",
                    "execution_id": "run-1:0:6:damage:decode",
                    "native_event_id": hashlib.sha256(b"warmup-nvdec-6").hexdigest(),
                }
            )
            write_csv(runtime / "resource_intervals.runtime.csv", RESOURCE_INTERVAL_COLUMNS, [warmup, measurement])
            write_csv(runtime / "fanout_work_counters.runtime.csv", FANOUT_WORK_COUNTER_COLUMNS, [])
            samples = []
            for sequence, utilization in ((1, 25), (2, 50), (3, 25)):
                samples.append(
                    {
                        "schema_version": 2,
                        "resource_contract_version": 2,
                        "run_id": "run-1",
                        "sample_seq": sequence,
                        "timestamp_ns": sequence * 1_000_000_000,
                        "sample_period_us": 1_000_000,
                        "device_id": "gpu:0",
                        "nvdec_util_percent": utilization,
                        "gpu_util_percent": 25,
                        "memory_util_percent": 10,
                        "vram_used_bytes": 1_000_000,
                        "counter_scope": "device_sample",
                        "sample_provenance": "nvml_device_decoder_utilization_v1",
                        "telemetry_source": "native",
                    }
                )
            write_csv(
                runtime / "hardware_resource_samples.runtime.csv",
                HARDWARE_RESOURCE_SAMPLE_COLUMNS,
                samples,
            )
            input_key = "kpp_real_h265:0:source:0:7"
            ingress = pd.DataFrame(
                [
                    {
                        "run_id": "run-1",
                        "trace_id": "run-1:0:7",
                        "stream_id": 0,
                        "frame_id": 7,
                        "input_frame_key": input_key,
                        "ingress_timestamp_ms": 999,
                        "terminal_timestamp_ms": 1002,
                        "window_start_timestamp_ms": 0,
                        "window_end_timestamp_ms": 3000,
                    }
                ]
            )
            source_id = "run-1:0:7:damage:source"
            decode_id = "run-1:0:7:damage:decode"
            topology = pd.DataFrame(
                [
                    {
                        "run_id": "run-1",
                        "trace_id": "run-1:0:7",
                        "stream_id": 0,
                        "frame_id": 7,
                        "input_frame_key": input_key,
                        "event_kind": "source_read",
                        "stage": "source",
                        "branch_id": "damage",
                        "execution_id": source_id,
                        "parent_execution_ids_json": "[]",
                        "timestamp_ms": 1000,
                    },
                    {
                        "run_id": "run-1",
                        "trace_id": "run-1:0:7",
                        "stream_id": 0,
                        "frame_id": 7,
                        "input_frame_key": input_key,
                        "event_kind": "stage_complete",
                        "stage": "decode_damage",
                        "branch_id": "damage",
                        "execution_id": decode_id,
                        "parent_execution_ids_json": json.dumps([source_id]),
                        "timestamp_ms": 1001,
                    },
                ]
            )
            frame_events = pd.DataFrame(
                [
                    {
                        "run_id": "run-1",
                        "trace_id": "run-1:0:7",
                        "stream_id": 0,
                        "frame_id": 7,
                        "stage": "decode_damage",
                        "resource": "nvdec",
                        "stage_start_timestamp_ms": 1000,
                        "stage_end_timestamp_ms": 1001,
                    }
                ]
            )
            frame_result = promote_runtime_interval_and_fanout_evidence(
                runtime_resource_intervals=runtime / "resource_intervals.runtime.csv",
                runtime_fanout_work_counters=runtime / "fanout_work_counters.runtime.csv",
                output_root=root / "frame_accepted",
                expected_run_id="run-1",
                ingress_ledger=ingress,
                topology_events=topology,
                frame_events=frame_events,
                topology_kind="independent_processes",
            )
            result = promote_runtime_full_resource_evidence(
                runtime_resource_intervals=runtime / "resource_intervals.runtime.csv",
                runtime_hardware_samples=runtime / "hardware_resource_samples.runtime.csv",
                runtime_fanout_work_counters=runtime / "fanout_work_counters.runtime.csv",
                output_root=accepted,
                expected_run_id="run-1",
                ingress_ledger=ingress,
                topology_events=topology,
                frame_events=frame_events,
                topology_kind="independent_processes",
            )
            with (accepted / "resource_intervals.csv").open(newline="", encoding="utf-8") as source:
                accepted_rows = list(csv.DictReader(source))

        self.assertTrue(result["summary"]["evidence_accepted"])
        self.assertTrue(frame_result["hardware_samples_pending_external_collector"])
        self.assertEqual(result["accepted_interval_count"], 1)
        self.assertEqual([row["frame_id"] for row in accepted_rows], ["7"])


if __name__ == "__main__":
    unittest.main()
