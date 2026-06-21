#!/usr/bin/env python3
from __future__ import annotations

import csv
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import (
    ContractError,
    FRAME_EVENT_COLUMNS,
    canonicalize_frames_csv,
    load_dataset,
    network_profile_matches,
    summarize_frames,
    validate_frame_events,
    validate_stage_trace_coverage,
)
from deploy.savant.native_probe import BasePyFuncPlugin, SavantLocalTelemetryProbe, frame_event_filename, merge_local_outputs
from distributed_executor import _combine_csv, parse_chrony_tracking, parse_iperf_output, parse_ping_output
from rtp_trace import RtpTrace, pack_trace, unpack_trace


def native_frame_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "trace_id": "r:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "ingress_timestamp_ms": 100,
        "egress_timestamp_ms": 130,
        "e2e_latency_ms": 30,
        "objects": 1,
        "detector": "d",
        "backend": "b",
        "telemetry_source": "native",
    }
    row.update(overrides)
    return row


def native_event_row(**overrides):
    row = {
        "schema_version": 2,
        "run_id": "r",
        "trace_id": "r:0:1",
        "stream_id": 0,
        "frame_id": 1,
        "stage": "decode",
        "role": "local",
        "host": "localhost",
        "resource": "cpu",
        "queue_enter_timestamp_ms": 100,
        "stage_start_timestamp_ms": 100,
        "stage_end_timestamp_ms": 110,
        "queue_depth": 0,
        "estimated_cost_ms": 10,
        "policy_action": "native:test",
    }
    row.update(overrides)
    return row


def write_savant_event_fragments(stream_dir: Path, rows: list[dict]) -> None:
    grouped: dict[str, list[dict]] = {}
    for row in rows:
        grouped.setdefault(str(row["stage"]), []).append(row)
    for stage, stage_rows in grouped.items():
        pd.DataFrame(stage_rows).to_csv(stream_dir / frame_event_filename(stage), index=False)


class BenchmarkContractTests(unittest.TestCase):
    def test_smoke_legacy_csv_is_canonicalized_as_synthetic(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [{"timestamp_ms": 100, "frame_id": 1, "stream_id": 0, "objects": 2, "latency_ms": 12.5}]
            ).to_csv(path, index=False)
            df = canonicalize_frames_csv(path, mode="smoke", run_id="r", detector="d", backend="b")
            self.assertEqual(df.iloc[0]["telemetry_source"], "synthetic")
            self.assertEqual(float(df.iloc[0]["e2e_latency_ms"]), 12.5)

    def test_benchmark_rejects_legacy_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame([{"timestamp_ms": 100, "frame_id": 1, "stream_id": 0, "latency_ms": 1}]).to_csv(
                path, index=False
            )
            with self.assertRaises(ContractError):
                canonicalize_frames_csv(path, mode="benchmark", run_id="r", detector="d", backend="b")

    def test_benchmark_rejects_schema_v2_synthetic_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 120,
                        "e2e_latency_ms": 20,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "synthetic",
                    }
                ]
            ).to_csv(path, index=False)
            with self.assertRaises(ContractError):
                canonicalize_frames_csv(path, mode="benchmark", run_id="r", detector="d", backend="b")

    def test_benchmark_requires_frame_event_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame_events.csv"
            pd.DataFrame([{"schema_version": 2, "run_id": "r"}]).to_csv(path, index=False)
            with self.assertRaises(ContractError):
                validate_frame_events(path)

    def test_benchmark_rejects_missing_native_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(ContractError):
                canonicalize_frames_csv(root / "frames.csv", mode="benchmark", run_id="r", detector="d", backend="b")
            with self.assertRaises(ContractError):
                validate_frame_events(root / "frame_events.csv")

    def test_rtp_trace_roundtrip(self) -> None:
        trace = RtpTrace(stream_id=3, frame_id=42, ingress_timestamp_ms=123456789)
        self.assertEqual(unpack_trace(pack_trace(trace)), trace)

    def test_native_frames_and_events_are_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 120,
                        "e2e_latency_ms": 20,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(frames, index=False)
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "stage": "aggregate",
                        "role": "aggregator",
                        "host": "localhost",
                        "resource": "cpu",
                        "queue_enter_timestamp_ms": 119,
                        "stage_start_timestamp_ms": 119,
                        "stage_end_timestamp_ms": 120,
                        "queue_depth": 0,
                        "estimated_cost_ms": 1,
                        "policy_action": "native:cpu",
                    }
                ]
            ).to_csv(events, index=False)

            canonicalize_frames_csv(frames, mode="benchmark", run_id="r", detector="d", backend="b")
            validate_frame_events(events)

    def test_benchmark_rejects_malformed_frame_timestamps(self) -> None:
        for bad_value in ("None", "", "not-a-number"):
            with self.subTest(bad_value=bad_value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "frames.csv"
                pd.DataFrame([native_frame_row(ingress_timestamp_ms=bad_value)]).to_csv(path, index=False)

                with self.assertRaisesRegex(ContractError, r"frames\.csv:2: .*ingress_timestamp_ms"):
                    canonicalize_frames_csv(path, mode="benchmark", run_id="r", detector="d", backend="b")

    def test_benchmark_rejects_malformed_frame_event_timestamps(self) -> None:
        for bad_value in ("None", "", "not-a-number"):
            with self.subTest(bad_value=bad_value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "frame_events.csv"
                pd.DataFrame([native_event_row(stage_start_timestamp_ms=bad_value)]).to_csv(path, index=False)

                with self.assertRaisesRegex(ContractError, r"frame_events\.csv:2: .*stage_start_timestamp_ms"):
                    validate_frame_events(path)

    def test_benchmark_rejects_extra_frame_event_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frame_events.csv"
            row = native_event_row()
            path.write_text(
                ",".join(FRAME_EVENT_COLUMNS)
                + "\n"
                + ",".join(str(row[column]) for column in FRAME_EVENT_COLUMNS)
                + ",extra\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, r"frame_events\.csv:2: unexpected extra CSV fields"):
                validate_frame_events(path)

    def test_stage_trace_coverage_accepts_merged_role_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 130,
                        "e2e_latency_ms": 30,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(frames, index=False)

            role_rows = {
                "edge": ("decode", 100, 110),
                "gpu_worker": ("detect", 111, 125),
                "aggregator": ("aggregate", 126, 130),
            }
            paths = []
            for role, (stage, start, end) in role_rows.items():
                path = root / "roles" / role / "frame_events.csv"
                path.parent.mkdir(parents=True)
                pd.DataFrame(
                    [
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": "r:0:1",
                            "stream_id": 0,
                            "frame_id": 1,
                            "stage": stage,
                            "role": role,
                            "host": "localhost",
                            "resource": "gpu" if role == "gpu_worker" else "cpu",
                            "queue_enter_timestamp_ms": start,
                            "stage_start_timestamp_ms": start,
                            "stage_end_timestamp_ms": end,
                            "queue_depth": 0,
                            "estimated_cost_ms": end - start,
                            "policy_action": f"native:{stage}",
                        }
                    ]
                ).to_csv(path, index=False)
                paths.append(path)

            merged_events = root / "frame_events.csv"
            _combine_csv(paths, merged_events, FRAME_EVENT_COLUMNS)
            validate_stage_trace_coverage(frames, merged_events, required_stages=["decode", "detect", "aggregate"])

    def test_stage_trace_coverage_accepts_edge_preroll_with_per_stream_frame_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            frame_rows = []
            event_rows = []
            run_id = "r"
            measured_frames = 3
            edge_frames = 7
            for stream_id in range(2):
                for frame_id in range(measured_frames):
                    trace_id = f"{run_id}:{stream_id}:{frame_id}"
                    frame_rows.append(native_frame_row(trace_id=trace_id, stream_id=stream_id, frame_id=frame_id))
                    for stage in ("detect", "track", "aggregate", "record"):
                        event_rows.append(native_event_row(trace_id=trace_id, stream_id=stream_id, frame_id=frame_id, stage=stage))
                for frame_id in range(edge_frames):
                    trace_id = f"{run_id}:{stream_id}:{frame_id}"
                    event_rows.append(native_event_row(trace_id=trace_id, stream_id=stream_id, frame_id=frame_id, stage="decode"))

            pd.DataFrame(frame_rows).to_csv(frames, index=False)
            pd.DataFrame(event_rows).to_csv(events, index=False)

            validate_stage_trace_coverage(
                frames,
                events,
                required_stages=["decode", "detect", "track", "aggregate", "record"],
            )

    def test_distributed_combine_rejects_truncated_event_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "roles" / "edge" / "frame_events.csv"
            source.parent.mkdir(parents=True)
            source.write_text(
                ",".join(FRAME_EVENT_COLUMNS)
                + "\n"
                + "2,r,r:0:1,0,1,decode,edge,localhost,cpu,100\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, r"frame_events\.csv:2: .*stage_start_timestamp_ms"):
                _combine_csv([source], root / "frame_events.csv", FRAME_EVENT_COLUMNS)

    def test_stage_trace_coverage_rejects_missing_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "ingress_timestamp_ms": 100,
                        "egress_timestamp_ms": 130,
                        "e2e_latency_ms": 30,
                        "objects": 1,
                        "detector": "d",
                        "backend": "b",
                        "telemetry_source": "native",
                    }
                ]
            ).to_csv(frames, index=False)
            pd.DataFrame(
                [
                    {
                        "schema_version": 2,
                        "run_id": "r",
                        "trace_id": "r:0:1",
                        "stream_id": 0,
                        "frame_id": 1,
                        "stage": "decode",
                        "role": "edge",
                        "host": "localhost",
                        "resource": "cpu",
                        "queue_enter_timestamp_ms": 100,
                        "stage_start_timestamp_ms": 100,
                        "stage_end_timestamp_ms": 110,
                        "queue_depth": 0,
                        "estimated_cost_ms": 10,
                        "policy_action": "native:decode",
                    }
                ]
            ).to_csv(events, index=False)
            with self.assertRaises(ContractError):
                validate_stage_trace_coverage(frames, events, required_stages=["decode", "detect", "aggregate"])

    def test_stage_trace_coverage_rejects_missing_declared_extra_stage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames = root / "frames.csv"
            events = root / "frame_events.csv"
            pd.DataFrame([native_frame_row()]).to_csv(frames, index=False)
            pd.DataFrame(
                [
                    native_event_row(stage="decode"),
                    native_event_row(stage="detect", resource="gpu"),
                    native_event_row(stage="track", resource="gpu"),
                    native_event_row(stage="record"),
                ]
            ).to_csv(events, index=False)

            with self.assertRaisesRegex(ContractError, "stage 'classify'"):
                validate_stage_trace_coverage(
                    frames,
                    events,
                    required_stages=["decode", "detect", "track", "classify", "record"],
                )

    def test_savant_local_stream_outputs_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for stream_id in range(2):
                stream_dir = root / "streams" / f"stream_{stream_id}"
                stream_dir.mkdir(parents=True)
                trace_id = f"r:{stream_id}:1"
                pd.DataFrame(
                    [
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": trace_id,
                            "stream_id": stream_id,
                            "frame_id": 1,
                            "ingress_timestamp_ms": 100,
                            "egress_timestamp_ms": 130,
                            "e2e_latency_ms": 30,
                            "objects": 3,
                            "detector": "peoplenet",
                            "backend": "deepstream_tensorrt",
                            "telemetry_source": "native",
                        }
                    ]
                ).to_csv(stream_dir / "frames.csv", index=False)
                pd.DataFrame(
                    [
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": trace_id,
                            "stream_id": stream_id,
                            "frame_id": 1,
                            "stage": stage,
                            "role": "local",
                            "host": "localhost",
                            "resource": "gpu" if stage == "detect" else "cpu",
                            "queue_enter_timestamp_ms": 100 + idx * 10,
                            "stage_start_timestamp_ms": 100 + idx * 10,
                            "stage_end_timestamp_ms": 110 + idx * 10,
                            "queue_depth": 0,
                            "estimated_cost_ms": 10,
                            "policy_action": "native:savant",
                        }
                        for idx, stage in enumerate(["decode", "detect", "aggregate"])
                    ]
                ).to_csv(stream_dir / "frame_events.csv", index=False)

            merge_local_outputs(root, streams=2)
            frames = canonicalize_frames_csv(root / "frames.csv", mode="benchmark", run_id="r", detector="d", backend="b")
            events = validate_frame_events(root / "frame_events.csv")
            validate_stage_trace_coverage(
                root / "frames.csv",
                root / "frame_events.csv",
                required_stages=["decode", "detect", "aggregate"],
            )
            self.assertEqual(frames.shape[0], 2)
            self.assertEqual(events.shape[0], 6)

    def test_savant_local_stage_event_fragments_are_merged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stream_dir = root / "streams" / "stream_0"
            stream_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    native_frame_row(
                        trace_id="r:0:1",
                        detector="peoplenet",
                        backend="deepstream_tensorrt",
                    )
                ]
            ).to_csv(stream_dir / "frames.csv", index=False)
            write_savant_event_fragments(
                stream_dir,
                [
                    native_event_row(trace_id="r:0:1", stage="decode", resource="cpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="detect", resource="gpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="track", resource="cpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="classify", resource="cpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:1", stage="record", resource="cpu", policy_action="native:savant"),
                ],
            )

            with mock.patch.dict(os.environ, {"EXPERIMENT_PIPELINE_STAGES": "decode,detect,track,classify,record"}):
                merge_local_outputs(root, streams=1)
            events = validate_frame_events(root / "frame_events.csv")
            self.assertEqual(set(events["stage"]), {"decode", "detect", "track", "classify", "record"})
            self.assertEqual(events.shape[0], 5)

    def test_savant_local_probe_writes_only_declared_stage_fragment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(
            os.environ,
            {"EXPERIMENT_PIPELINE_STAGES": "decode,detect"},
        ):
            root = Path(tmp)
            inactive = SavantLocalTelemetryProbe(
                stage="track",
                output_dir=str(root),
                run_id="r",
                detector="d",
                backend="b",
            )

            self.assertIsNone(inactive.events)
            self.assertFalse((root / frame_event_filename("track")).exists())
            inactive.on_stop()

    def test_savant_local_merge_filters_measurement_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "measurement_start_ms").write_text("1000\n", encoding="utf-8")
            (root / "measurement_end_ms").write_text("2000\n", encoding="utf-8")
            for stream_id in range(2):
                stream_dir = root / "streams" / f"stream_{stream_id}"
                stream_dir.mkdir(parents=True)
                frame_rows = []
                event_rows = []
                samples = [
                    (1, 100, 130),
                    (2, 1100, 1130),
                    (3, 2100, 2130),
                ]
                for frame_id, ingress_ms, egress_ms in samples:
                    trace_id = f"r:{stream_id}:{frame_id}"
                    frame_rows.append(
                        {
                            "schema_version": 2,
                            "run_id": "r",
                            "trace_id": trace_id,
                            "stream_id": stream_id,
                            "frame_id": frame_id,
                            "ingress_timestamp_ms": ingress_ms,
                            "egress_timestamp_ms": egress_ms,
                            "e2e_latency_ms": egress_ms - ingress_ms,
                            "objects": 3,
                            "detector": "peoplenet",
                            "backend": "deepstream_tensorrt",
                            "telemetry_source": "native",
                        }
                    )
                    for idx, stage in enumerate(["decode", "detect", "aggregate"]):
                        start_ms = ingress_ms + idx * 10
                        event_rows.append(
                            {
                                "schema_version": 2,
                                "run_id": "r",
                                "trace_id": trace_id,
                                "stream_id": stream_id,
                                "frame_id": frame_id,
                                "stage": stage,
                                "role": "local",
                                "host": "localhost",
                                "resource": "gpu" if stage == "detect" else "cpu",
                                "queue_enter_timestamp_ms": start_ms,
                                "stage_start_timestamp_ms": start_ms,
                                "stage_end_timestamp_ms": start_ms + 1,
                                "queue_depth": 0,
                                "estimated_cost_ms": 1,
                                "policy_action": "native:savant",
                            }
                        )
                pd.DataFrame(frame_rows).to_csv(stream_dir / "frames.csv", index=False)
                pd.DataFrame(event_rows).to_csv(stream_dir / "frame_events.csv", index=False)

            merge_local_outputs(root, streams=2)
            frames = canonicalize_frames_csv(
                root / "frames.csv",
                mode="benchmark",
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
            )
            events = validate_frame_events(root / "frame_events.csv")
            validate_stage_trace_coverage(
                root / "frames.csv",
                root / "frame_events.csv",
                required_stages=["decode", "detect", "aggregate"],
            )
            self.assertEqual(set(frames["frame_id"]), {2})
            self.assertEqual(frames.shape[0], 2)
            self.assertEqual(events.shape[0], 6)

    def test_savant_local_merge_rejects_malformed_unmeasured_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "measurement_start_ms").write_text("1000\n", encoding="utf-8")
            (root / "measurement_end_ms").write_text("2000\n", encoding="utf-8")
            stream_dir = root / "streams" / "stream_0"
            stream_dir.mkdir(parents=True)
            pd.DataFrame(
                [
                    native_frame_row(
                        trace_id="r:0:1",
                        frame_id=1,
                        ingress_timestamp_ms=100,
                        egress_timestamp_ms=130,
                        detector="peoplenet",
                        backend="deepstream_tensorrt",
                    ),
                    native_frame_row(
                        trace_id="r:0:2",
                        frame_id=2,
                        ingress_timestamp_ms=1100,
                        egress_timestamp_ms=1130,
                        detector="peoplenet",
                        backend="deepstream_tensorrt",
                    ),
                ]
            ).to_csv(stream_dir / "frames.csv", index=False)
            write_savant_event_fragments(
                stream_dir,
                [
                    native_event_row(trace_id="r:0:2", frame_id=2, stage="decode", policy_action="native:savant"),
                    native_event_row(
                        trace_id="r:0:1",
                        frame_id=1,
                        stage="detect",
                        stage_start_timestamp_ms="None",
                        policy_action="native:savant",
                    ),
                    native_event_row(trace_id="r:0:2", frame_id=2, stage="detect", resource="gpu", policy_action="native:savant"),
                    native_event_row(trace_id="r:0:2", frame_id=2, stage="aggregate", policy_action="native:savant"),
                ],
            )

            with self.assertRaisesRegex(RuntimeError, r"frame_events_detect\.csv:2: .*stage_start_timestamp_ms"):
                merge_local_outputs(root, streams=1)

    def test_savant_local_merge_rejects_malformed_measured_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stream_dir = root / "streams" / "stream_0"
            stream_dir.mkdir(parents=True)
            pd.DataFrame([native_frame_row(trace_id="r:0:1", detector="peoplenet", backend="deepstream_tensorrt")]).to_csv(
                stream_dir / "frames.csv",
                index=False,
            )
            pd.DataFrame(
                [
                    native_event_row(
                        trace_id="r:0:1",
                        stage_start_timestamp_ms="None",
                        policy_action="native:savant",
                    )
                ]
            ).to_csv(stream_dir / "frame_events.csv", index=False)

            with self.assertRaisesRegex(RuntimeError, r"frame_events\.csv:2: .*stage_start_timestamp_ms"):
                merge_local_outputs(root, streams=1)

    def test_savant_local_stage_event_writers_handle_concurrent_stage_writes(self) -> None:
        class Buffer:
            def __init__(self, frame_id: int) -> None:
                self.pts = frame_id
                self.offset = frame_id

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            probes = [
                SavantLocalTelemetryProbe(
                    stage=stage,
                    output_dir=str(root),
                    run_id="r",
                    detector="peoplenet",
                    backend="deepstream_tensorrt",
                    min_objects=1,
                    max_objects=3,
                )
                for stage in ("decode", "detect", "aggregate")
            ]
            errors: list[BaseException] = []

            def write_stage(probe: SavantLocalTelemetryProbe) -> None:
                try:
                    for frame_id in range(1000, 1050):
                        probe.process_buffer(Buffer(frame_id))
                except BaseException as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=write_stage, args=(probe,)) for probe in probes]
            try:
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join()
                self.assertEqual(errors, [])
            finally:
                for probe in probes:
                    probe.on_stop()

            self.assertFalse((root / "frame_events.csv").exists())
            for stage in ("decode", "detect", "aggregate"):
                path = root / frame_event_filename(stage)
                with path.open("r", newline="", encoding="utf-8") as src:
                    rows = list(csv.DictReader(src))
                self.assertEqual(len(rows), 50)
                for row_number, row in enumerate(rows, start=2):
                    for column in FRAME_EVENT_COLUMNS:
                        self.assertIsNotNone(row.get(column), f"row {row_number} column {column}")
                        self.assertNotEqual(str(row.get(column)).strip(), "", f"row {row_number} column {column}")
                validate_frame_events(path)

    def test_savant_local_pyfunc_writes_native_rows_from_buffer(self) -> None:
        class Buffer:
            pts = 42
            offset = 42

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            decode = SavantLocalTelemetryProbe(
                stage="decode",
                output_dir=str(root),
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
                min_objects=1,
                max_objects=3,
            )
            aggregate = SavantLocalTelemetryProbe(
                stage="aggregate",
                output_dir=str(root),
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
                min_objects=1,
                max_objects=3,
            )

            self.assertIsInstance(decode, BasePyFuncPlugin)
            decode.process_buffer(Buffer())
            aggregate.process_buffer(Buffer())
            self.assertTrue(decode.on_stop())
            self.assertTrue(aggregate.on_stop())

            frames = canonicalize_frames_csv(
                root / "frames.csv",
                mode="benchmark",
                run_id="r",
                detector="peoplenet",
                backend="deepstream_tensorrt",
            )
            decode_events = validate_frame_events(root / frame_event_filename("decode"))
            aggregate_events = validate_frame_events(root / frame_event_filename("aggregate"))
            events = pd.concat([decode_events, aggregate_events], ignore_index=True)

            self.assertFalse((root / "frame_events.csv").exists())
            self.assertEqual(frames.shape[0], 1)
            self.assertEqual(set(events["stage"]), {"decode", "aggregate"})

    def test_throughput_uses_completed_frames_per_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "frames.csv"
            pd.DataFrame(
                [
                    {"e2e_latency_ms": 10, "telemetry_source": "native"},
                    {"e2e_latency_ms": 20, "telemetry_source": "native"},
                    {"e2e_latency_ms": 40, "telemetry_source": "native"},
                    {"e2e_latency_ms": 80, "telemetry_source": "native"},
                ]
            ).to_csv(path, index=False)
            result = summarize_frames(path, deadline_s=0.05, measurement_s=2)
            self.assertEqual(result["throughput_fps"], 2.0)
            self.assertEqual(result["slo_violation_rate_percent"], 25.0)

    def test_publishable_dataset_requires_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = root / "datasets.yaml"
            manifest.write_text(
                yaml.safe_dump(
                    {
                        "datasets": {
                            "public": {
                                "publishable": True,
                                "streams": [{"path": "clip.mp4", "sha256": "SET_AFTER_PREPARATION"}],
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ContractError):
                load_dataset(manifest, "public", mode="benchmark", project_root=root, require_files=False)

    def test_network_acceptance_gate(self) -> None:
        ok, reason = network_profile_matches({"latency_ms": 80}, {"latency_ms": [60, 140]})
        self.assertTrue(ok)
        self.assertEqual(reason, "")
        ok, reason = network_profile_matches({"latency_ms": 10}, {"latency_ms": [60, 140]})
        self.assertFalse(ok)
        self.assertIn("outside", reason)

    def test_preflight_parsers(self) -> None:
        ping = "4 packets transmitted, 4 received, 0% packet loss\nrtt min/avg/max/mdev = 1.0/2.0/3.0/0.5 ms"
        self.assertEqual(parse_ping_output(ping)["latency_ms"], 2.0)
        self.assertEqual(parse_chrony_tracking("Last offset     : +0.000002 seconds"), 0.002)
        self.assertEqual(parse_iperf_output('{"end":{"sum_received":{"bits_per_second":125000000}}}'), 125.0)


if __name__ == "__main__":
    unittest.main()
