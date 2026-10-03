from __future__ import annotations

import copy
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_acceptance_evidence import accepted_arm_evidence_files  # noqa: E402
from publication_article_statistics_v1 import (  # noqa: E402
    ArticleStatisticsV1Error,
    build_article_statistics_pair_record_v1,
    build_primary_architecture_inference_from_article_records_v1,
    persist_article_statistics_pair_record_v1,
    seal_pair_article_statistics_v1,
    validate_article_statistics_binding_v1,
    validate_article_statistics_pair_record_v1,
)
from generate_vast_report_artifacts import (  # noqa: E402
    build_primary_architecture_pairs_from_run_metrics,
)


SHA = "a" * 64


class InjectedCrash(BaseException):
    pass


def _distribution(count: int, value: float) -> dict[str, object]:
    return {
        "count": count,
        "sum": value * count,
        "sum_squares": value * value * count,
        "sum_squared_deviations": 0.0,
        "minimum": value if count else None,
        "p25": value if count else None,
        "p50": value if count else None,
        "p75": value if count else None,
        "p90": value if count else None,
        "p95": value if count else None,
        "p99": value if count else None,
        "maximum": value if count else None,
        "mean": value if count else None,
        "population_stddev": 0.0 if count else None,
    }


def _performance(count: int = 1, value: float = 20.0) -> dict[str, object]:
    return {
        "ingress": {
            "count": count,
            "completed": count,
            "dropped": 0,
            "censored": 0,
            "completed_rate_percent": 100.0 if count else None,
            "drop_rate_percent": 0.0 if count else None,
            "censored_rate_percent": 0.0 if count else None,
        },
        "completed_latency_ms": _distribution(count, value),
        "deadline_outcomes": [
            {"deadline_ms": 100.0, "violations": 0, "rate_percent": 0.0}
        ],
        "throughput_completed_fps": count / 180.0,
    }


def _policy_stats(row_count: int = 0) -> dict[str, object]:
    return {
        "row_count": row_count,
        "decision_counts": [],
        "resource_counts": [],
        "stage_counts": [],
        "reason_counts": [],
        "terminal_status_counts": [],
    }


def _drop_stats(total: int = 0) -> dict[str, object]:
    return {
        "row_count": 0,
        "dropped_frames": 0,
        "late_frames": 0,
        "total_frames": total,
        "drop_rate_percent": 0.0 if total else None,
        "late_rate_percent": 0.0 if total else None,
    }


def _measurement_passport(
    *,
    ingress: int,
    completed: int,
    duration_ms: float,
    input_schedule_sha256: str = "1" * 64,
    input_frame_key_sequence_sha256: str = "2" * 64,
    c_obs_in_ms_per_ingress: float = 1.0,
    c_obs_cpu_in_ms_per_ingress: float = 0.5,
    c_obs_gpu_in_ms_per_ingress: float = 0.5,
    c_obs_is_partial: bool = False,
) -> dict[str, object]:
    signature_payload_json = "{}"
    total = c_obs_in_ms_per_ingress * ingress
    cpu = c_obs_cpu_in_ms_per_ingress * ingress
    gpu = c_obs_gpu_in_ms_per_ingress * ingress
    return {
        "resource_attribution_complete": True,
        "resource_attribution": "native_per_trace_bounded_stage_interval_ingress_cohort_v4",
        "resource_attributed_ingress_count": ingress,
        "resource_unattributed_event_count": 0,
        "input_schedule_sha256": input_schedule_sha256,
        "input_frame_key_sequence_sha256": input_frame_key_sequence_sha256,
        "measurement_window_duration_ms": duration_ms,
        "measurement_signature": hashlib.sha256(
            signature_payload_json.encode("ascii")
        ).hexdigest(),
        "measurement_signature_payload_json": signature_payload_json,
        "c_obs_total_ms": total,
        "c_obs_cpu_total_ms": cpu,
        "c_obs_gpu_total_ms": gpu,
        "c_obs_in_ms_per_ingress": c_obs_in_ms_per_ingress,
        "c_obs_cpu_in_ms_per_ingress": c_obs_cpu_in_ms_per_ingress,
        "c_obs_gpu_in_ms_per_ingress": c_obs_gpu_in_ms_per_ingress,
        "c_obs_comp_ms_per_completed": total / completed if completed else None,
        "c_obs_is_partial": c_obs_is_partial,
    }


def _full_resource_statistics() -> dict[str, object]:
    return {
        "summary": {
            "assessment_schema_version": 1,
            "resource_contract_version": 2,
            "evidence_accepted": True,
            "publication_bundle_bound": True,
            "full_resource_coverage_complete": True,
            "measurement_window_start_ns": 0,
            "measurement_window_end_ns": 180000000000,
            "nvdec_busy_equivalent_ns": 500000,
            "nvdec_interval_device_ids": ["nvdec:0"],
            "nvdec_sampled_gpu_device_ids": ["gpu:0"],
            "nvdec_counter_scope": "device_sample_busy_equivalent",
            "fanout_thread_cpu_time_ns": 0,
            "fanout_work_units": 0,
            "fanout_counter_scope": "per_trace_resource_work",
            "resource_interval_summary": {},
        },
        "hardware_by_device": [
            {
                "device_id": "gpu:0",
                "sample_count": 1,
                "sample_period_us": _distribution(1, 1000.0),
                "nvdec_util_percent": _distribution(1, 50.0),
                "gpu_util_percent": _distribution(1, 50.0),
                "memory_util_percent": _distribution(1, 25.0),
                "vram_used_bytes": _distribution(1, 1024.0),
            }
        ],
        "interval_by_component": [
            {
                "component": "nvdec_submit_complete",
                "direction": "device",
                "device_id": "nvdec:0",
                "row_count": 1,
                "duration_ns": _distribution(1, 1000.0),
                "bytes": _distribution(1, 0.0),
            }
        ],
        "fanout": {"row_count": 0, "thread_cpu_time_ns": 0, "work_units": 0},
    }


def _descriptive() -> dict[str, object]:
    streams = []
    for stream_id in range(6):
        streams.append(
            {
                "stream_id": stream_id,
                "performance": _performance(),
                "stage_statistics": [],
                "resource_statistics": [],
                "policy_decision_statistics": _policy_stats(),
                "drop_counter_statistics": _drop_stats(1),
            }
        )
    return {
        "measurement_window_duration_ms": 180000.0,
        "arm_performance": _performance(6),
        "per_stream": streams,
        "stage_statistics": [],
        "resource_statistics": [],
        "policy_decision_statistics": _policy_stats(),
        "drop_counter_statistics": _drop_stats(6),
        "measurement_passport": _measurement_passport(
            ingress=6, completed=6, duration_ms=180000.0
        ),
        "full_resource_statistics": _full_resource_statistics(),
    }


def _arm_material(
    pair_dir: Path,
    arm_index: int,
    *,
    scenario: str | None = None,
    arm_id: str | None = None,
    coordinate_overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    scenario = scenario or (
        "checkpoint_independent_processes_baseline"
        if arm_index == 0
        else "checkpoint_video_dag_shared"
    )
    arm_id = arm_id or f"arm-{arm_index + 1}"
    position = arm_index + 1
    coordinate = {
        "arm_position": position,
        "system": "gstreamer_custom",
        "scenario": scenario,
        "codec": "h264",
        "dataset": "kpp_iss_publication_v3_h264",
        "policy": "static_hybrid",
        "deadline_ms": 100.0,
        "repeat": 1,
        "streams": 6,
        "seed": 20260323,
        "warmup_s": 30,
        "measurement_s": 180,
        "run_seed": 99,
        "deployment_mode": "single-server-distributed",
        "host_topology": "single_host_ssh",
        "run_mode": "benchmark",
        "telemetry_source": "native",
    }
    coordinate.update(coordinate_overrides or {})
    arm_root = pair_dir / "arms" / f"{position:02d}_{arm_id}"
    arm_root.mkdir(parents=True)
    names = [
        *accepted_arm_evidence_files(str(coordinate["policy"]), full_resource=True),
        "checkpoint_publication_acceptance.json",
        "run_metadata.json",
    ]
    descriptors = []
    for name in sorted(names):
        payload = f"{arm_id}:{name}\n".encode("ascii")
        path = arm_root / name
        path.write_bytes(payload)
        descriptors.append(
            {
                "relative_path": path.relative_to(pair_dir).as_posix(),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return {
        "arm_index": arm_index,
        "arm_id": arm_id,
        "coordinate": coordinate,
        "evidence_files": descriptors,
        "descriptive_statistics": _descriptive(),
        "primary_architecture_run_metric": None,
    }


def _record(run_root: Path) -> tuple[Path, dict[str, object]]:
    pair_dir = run_root / "pairs" / "0001_pair-0001" / "attempt-0001"
    pair_dir.mkdir(parents=True)
    record = build_article_statistics_pair_record_v1(
        pair_identity={
            "matrix_sha256": SHA,
            "run_id": "full-run-001",
            "pair_sequence": 1,
            "pair_id": "pair-0001",
            "pair_sha256": "b" * 64,
            "attempt": 1,
        },
        arms=[_arm_material(pair_dir, 0), _arm_material(pair_dir, 1)],
        primary_architecture_pair_metric=None,
    )
    return pair_dir, record


def _primary_metric_rows(config: dict[str, object]) -> list[dict[str, object]]:
    primary = config["benchmark"]["primary_architecture_contrast"]
    baseline = str(primary["baseline_scenario"])
    shared = str(primary["shared_scenario"])
    rows = []
    for repeat in range(1, int(primary["repeats"]) + 1):
        first = primary["arm_order"]["first_arm_by_pair"][repeat - 1]
        second = shared if first == baseline else baseline
        positions = {first: 1, second: 2}
        common = {
            "system": primary["system"],
            "policy": primary["policy"],
            "dataset": primary["dataset"],
            "deadline_ms": float(primary["deadline_ms"]),
            "streams": int(primary["streams"]),
            "repeat": repeat,
            "seed": int(primary["seed"]),
            "run_seed": 1000 + repeat,
            "input_schedule_sha256": f"{repeat:064x}",
            "input_frame_key_sequence_sha256": f"{repeat + 100:064x}",
            "measurement_window_duration_ms": float(primary["measurement_s"]) * 1000.0,
            "drain_rule": "drain_to_empty",
            "resource_attribution": "native_per_trace_bounded_stage_interval_ingress_cohort_v4",
            "measurement_signature": hashlib.sha256(b"{}").hexdigest(),
            "semantic_prefix_contract_sha256": "b" * 64,
            "decoder_factory": "nvh264dec",
            "branch_analytics_contract_sha256": "c" * 64,
            "c_obs_is_partial": False,
            "pair_contract_version": 1,
            "pair_order_strategy": primary["arm_order"]["strategy"],
            "pair_repeat": repeat,
            "pair_first_arm": first,
            "pair_second_arm": second,
            "run_gate_pass": True,
            "run_gate_blockers": "",
        }
        for scenario, vmax, drop, token_offset, sink_offset, c_obs in (
            (baseline, 5.0, 2.0, 1000, 2000, 10.0 + repeat / 10.0),
            (shared, 4.0, 1.0, 3000, 4000, 5.0 + repeat / 20.0),
        ):
            ingress = 60000
            dropped = int(ingress * drop / 100.0)
            completed = ingress - dropped
            rows.append(
                {
                    **common,
                    "scenario": scenario,
                    "pair_arm_position": positions[scenario],
                    "reset_process_start_tokens_json": json.dumps(
                        [f"{repeat + token_offset:064x}"]
                    ),
                    "reset_telemetry_sink_id": f"{repeat + sink_offset:064x}",
                    "c_obs_in_ms_per_ingress": c_obs,
                    "c_obs_cpu_in_ms_per_ingress": c_obs * 0.6,
                    "c_obs_gpu_in_ms_per_ingress": c_obs * 0.4,
                    "event_factor_decode": 4.0 if scenario == baseline else 1.0,
                    "event_factor_preprocess": 4.0 if scenario == baseline else 1.0,
                    "vmax_completed_slo_violation_rate_percent": vmax,
                    "drop_max_ingress_rate_percent": drop,
                    "ingress_frame_count": ingress,
                    "completed_frame_count": completed,
                    "dropped_frame_count": dropped,
                    "censored_frame_count": 0,
                    "run_dir": "filled-when-record-is-created",
                }
            )
    return rows


def _primary_descriptive(
    metric: dict[str, object], *, deadlines_ms: list[float]
) -> dict[str, object]:
    duration_ms = float(metric["measurement_window_duration_ms"])
    duration_s = duration_ms / 1000.0
    stream_count = int(metric["streams"])
    ingress_per_stream = int(metric["ingress_frame_count"]) // stream_count
    dropped_per_stream = int(metric["dropped_frame_count"]) // stream_count
    completed_per_stream = int(metric["completed_frame_count"]) // stream_count
    violation_rate = float(metric["vmax_completed_slo_violation_rate_percent"])
    violations_per_stream = int(completed_per_stream * violation_rate / 100.0)

    def latency_distribution(count: int, violations: int) -> dict[str, object]:
        low = 20.0
        high = 120.0
        total = low * (count - violations) + high * violations
        total_squares = low * low * (count - violations) + high * high * violations
        mean = total / count
        m2 = (low - mean) ** 2 * (count - violations) + (high - mean) ** 2 * violations
        return {
            "count": count,
            "sum": total,
            "sum_squares": total_squares,
            "sum_squared_deviations": m2,
            "minimum": low,
            "p25": low,
            "p50": low,
            "p75": low,
            "p90": low,
            "p95": low,
            "p99": high,
            "maximum": high,
            "mean": mean,
            "population_stddev": (m2 / count) ** 0.5,
        }

    def performance(multiplier: int) -> dict[str, object]:
        ingress = ingress_per_stream * multiplier
        dropped = dropped_per_stream * multiplier
        completed = completed_per_stream * multiplier
        violations = violations_per_stream * multiplier
        return {
            "ingress": {
                "count": ingress,
                "completed": completed,
                "dropped": dropped,
                "censored": 0,
                "completed_rate_percent": completed / ingress * 100.0,
                "drop_rate_percent": dropped / ingress * 100.0,
                "censored_rate_percent": 0.0,
            },
            "completed_latency_ms": latency_distribution(completed, violations),
            "deadline_outcomes": [
                {
                    "deadline_ms": float(deadline),
                    "violations": (
                        completed
                        if float(deadline) < 20.0
                        else violations
                        if float(deadline) < 120.0
                        else 0
                    ),
                    "rate_percent": (
                        100.0
                        if float(deadline) < 20.0
                        else violations / completed * 100.0
                        if float(deadline) < 120.0
                        else 0.0
                    ),
                }
                for deadline in deadlines_ms
            ],
            "throughput_completed_fps": completed / duration_s,
        }

    streams = []
    for stream_id in range(stream_count):
        streams.append(
            {
                "stream_id": stream_id,
                "performance": performance(1),
                "stage_statistics": [],
                "resource_statistics": [],
                "policy_decision_statistics": _policy_stats(),
                "drop_counter_statistics": {
                    "row_count": 1,
                    "dropped_frames": dropped_per_stream,
                    "late_frames": 0,
                    "total_frames": ingress_per_stream,
                    "drop_rate_percent": dropped_per_stream / ingress_per_stream * 100.0,
                    "late_rate_percent": 0.0,
                },
            }
        )
    return {
        "measurement_window_duration_ms": duration_ms,
        "arm_performance": performance(stream_count),
        "per_stream": streams,
        "stage_statistics": [],
        "resource_statistics": [],
        "policy_decision_statistics": _policy_stats(),
        "drop_counter_statistics": {
            "row_count": stream_count,
            "dropped_frames": int(metric["dropped_frame_count"]),
            "late_frames": 0,
            "total_frames": int(metric["ingress_frame_count"]),
            "drop_rate_percent": float(metric["drop_max_ingress_rate_percent"]),
            "late_rate_percent": 0.0,
        },
        "measurement_passport": _measurement_passport(
            ingress=int(metric["ingress_frame_count"]),
            completed=int(metric["completed_frame_count"]),
            duration_ms=duration_ms,
            input_schedule_sha256=str(metric["input_schedule_sha256"]),
            input_frame_key_sequence_sha256=str(
                metric["input_frame_key_sequence_sha256"]
            ),
            c_obs_in_ms_per_ingress=float(metric["c_obs_in_ms_per_ingress"]),
            c_obs_cpu_in_ms_per_ingress=float(
                metric["c_obs_cpu_in_ms_per_ingress"]
            ),
            c_obs_gpu_in_ms_per_ingress=float(
                metric["c_obs_gpu_in_ms_per_ingress"]
            ),
            c_obs_is_partial=bool(metric["c_obs_is_partial"]),
        ),
        "full_resource_statistics": _full_resource_statistics(),
    }


class PublicationArticleStatisticsV1Tests(unittest.TestCase):
    def test_production_seal_uses_runtime_metadata_authority_and_frozen_pair_override(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open(
            "r", encoding="utf-8"
        ) as source:
            config = yaml.safe_load(source)
        primary = config["benchmark"]["primary_architecture_contrast"]
        metrics = [row for row in _primary_metric_rows(config) if row["repeat"] == 1]
        metrics.sort(key=lambda row: int(row["pair_arm_position"]))
        first = str(primary["arm_order"]["first_arm_by_pair"][0])
        second = (
            str(primary["shared_scenario"])
            if first == primary["baseline_scenario"]
            else str(primary["baseline_scenario"])
        )
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            run_root = Path(tmp) / "run"
            pair_id = "primary-production-pair"
            pair_dir = run_root / "pairs" / f"0000_{pair_id}" / "attempt-0001"
            pair_dir.mkdir(parents=True)
            arms = []
            records = []
            descriptive_by_scenario = {}
            metric_by_scenario = {}
            for arm_index, metric in enumerate(metrics):
                arm_id = f"production-primary-a{arm_index + 1}"
                metric["run_dir"] = (
                    pair_dir / "arms" / f"{arm_index + 1:02d}_{arm_id}"
                ).relative_to(run_root).as_posix()
                material = _arm_material(
                    pair_dir,
                    arm_index,
                    scenario=str(metric["scenario"]),
                    arm_id=arm_id,
                    coordinate_overrides={
                        "system": metric["system"],
                        "codec": primary["codec"],
                        "dataset": metric["dataset"],
                        "policy": metric["policy"],
                        "deadline_ms": metric["deadline_ms"],
                        "repeat": 1,
                        "streams": metric["streams"],
                        "seed": metric["seed"],
                        "warmup_s": primary["warmup_s"],
                        "measurement_s": primary["measurement_s"],
                        "run_seed": metric["run_seed"],
                    },
                )
                descriptive = _primary_descriptive(
                    metric,
                    deadlines_ms=sorted(
                        {
                            *map(float, config["benchmark"]["report_deadline_ms"]),
                            float(metric["deadline_ms"]),
                        }
                    ),
                )
                descriptive_by_scenario[str(metric["scenario"])] = descriptive
                metric_by_scenario[str(metric["scenario"])] = metric
                coordinate = material["coordinate"]
                pair_metadata = {
                    "contract_version": 1,
                    "strategy": primary["arm_order"]["strategy"],
                    "repeat": 1,
                    "first_arm": first,
                    "arm_position": arm_index + 1,
                    "second_arm": second,
                }
                arms.append(
                    {
                        "arm_id": arm_id,
                        **{
                            field: coordinate[field]
                            for field in (
                                "arm_position",
                                "system",
                                "scenario",
                                "codec",
                                "dataset",
                                "policy",
                                "deadline_ms",
                                "repeat",
                                "streams",
                                "seed",
                                "warmup_s",
                                "measurement_s",
                            )
                        },
                        "primary_architecture_pair": pair_metadata,
                    }
                )
                descriptors = {
                    Path(row["relative_path"]).name: row
                    for row in material["evidence_files"]
                }
                records.append(
                    {
                        "arm_id": arm_id,
                        "run_id": f"native-run-{arm_index + 1}",
                        "runtime_acceptance_relative_path": (
                            pair_dir
                            / descriptors["checkpoint_publication_acceptance.json"][
                                "relative_path"
                            ]
                        ).relative_to(run_root).as_posix(),
                        "runtime_acceptance_sha256": descriptors[
                            "checkpoint_publication_acceptance.json"
                        ]["sha256"],
                        "run_metadata_sha256": descriptors["run_metadata.json"][
                            "sha256"
                        ],
                        "evidence_sha256": {
                            name: row["sha256"]
                            for name, row in descriptors.items()
                            if name
                            not in {
                                "checkpoint_publication_acceptance.json",
                                "run_metadata.json",
                            }
                        },
                        "result": {
                            "status": "completed",
                            **{
                                field: coordinate[field]
                                for field in (
                                    "system",
                                    "scenario",
                                    "dataset",
                                    "policy",
                                    "deadline_ms",
                                    "repeat",
                                    "streams",
                                    "seed",
                                    "run_seed",
                                    "deployment_mode",
                                    "host_topology",
                                    "run_mode",
                                    "telemetry_source",
                                )
                            },
                        },
                    }
                )

            pair = {
                "pair_id": pair_id,
                "system": primary["system"],
                "codec": primary["codec"],
                "dataset": primary["dataset"],
                "policy": primary["policy"],
                "deadline_ms": primary["deadline_ms"],
                "repeat": 1,
                "arms": arms,
            }

            def descriptive_side_effect(
                _evidence: object, *, coordinate: dict[str, object], **_kwargs: object
            ) -> dict[str, object]:
                return copy.deepcopy(descriptive_by_scenario[str(coordinate["scenario"])])

            def primary_side_effect(
                _root: Path,
                row: pd.Series,
                _primary: dict[str, object],
                _config: dict[str, object],
                **kwargs: object,
            ) -> dict[str, object]:
                self.assertFalse(kwargs["validate_metadata"])
                expected = next(
                    arm["primary_architecture_pair"]
                    for arm in arms
                    if arm["scenario"] == row["scenario"]
                )
                self.assertEqual(kwargs["primary_pair_metadata_override"], expected)
                return copy.deepcopy(metric_by_scenario[str(row["scenario"])])

            evidence_stub = {
                "raw_summary": {},
                "sidecars": {"ingress_ledger": pd.DataFrame()},
                "topology_events": pd.DataFrame(),
                "events": pd.DataFrame(),
            }
            with (
                mock.patch(
                    "generate_vast_report_artifacts._validated_publication_run_artifacts",
                    return_value=evidence_stub,
                ) as validated,
                mock.patch(
                    "generate_vast_report_artifacts._primary_run_metric",
                    side_effect=primary_side_effect,
                ) as primary_metric,
                mock.patch(
                    "publication_article_statistics_v1.validate_full_resource_evidence",
                    return_value={},
                ),
                mock.patch(
                    "publication_article_statistics_v1._descriptive_from_evidence",
                    side_effect=descriptive_side_effect,
                ),
            ):
                binding = seal_pair_article_statistics_v1(
                    run_root=run_root,
                    pair_dir=pair_dir,
                    config=config,
                    pair=pair,
                    arm_records=records,
                    matrix_sha256=SHA,
                    run_id="full-production-run",
                    pair_sequence=0,
                    pair_id=pair_id,
                    pair_sha256="b" * 64,
                    attempt=1,
                )

            self.assertEqual(validated.call_count, 2)
            self.assertTrue(
                all(call.kwargs["validate_metadata"] is False for call in validated.call_args_list)
            )
            self.assertEqual(primary_metric.call_count, 2)
            validate_article_statistics_binding_v1(
                binding,
                run_root=run_root,
                pair_dir=pair_dir,
                require_attempt_copy=True,
                require_retained_copy=True,
                require_raw_evidence=True,
            )

    def test_twenty_sealed_arms_reproduce_exact_preregistered_paired_inference(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open(
            "r", encoding="utf-8"
        ) as source:
            config = yaml.safe_load(source)
        metrics = _primary_metric_rows(config)
        primary = config["benchmark"]["primary_architecture_contrast"]
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            run_root = Path(tmp) / "run"
            paths = []
            for repeat in range(1, int(primary["repeats"]) + 1):
                pair_id = f"primary-pair-r{repeat:02d}"
                pair_sequence = repeat - 1
                pair_dir = (
                    run_root
                    / "pairs"
                    / f"{pair_sequence:04d}_{pair_id}"
                    / "attempt-0001"
                )
                pair_dir.mkdir(parents=True)
                repeat_metrics = [
                    copy.deepcopy(row)
                    for row in metrics
                    if int(row["repeat"]) == repeat
                ]
                repeat_metrics.sort(key=lambda row: int(row["pair_arm_position"]))
                arms = []
                for arm_index, metric in enumerate(repeat_metrics):
                    arm_id = f"primary-r{repeat:02d}-a{arm_index + 1}"
                    metric["run_dir"] = (
                        pair_dir
                        / "arms"
                        / f"{arm_index + 1:02d}_{arm_id}"
                    ).relative_to(run_root).as_posix()
                    material = _arm_material(
                        pair_dir,
                        arm_index,
                        scenario=str(metric["scenario"]),
                        arm_id=arm_id,
                        coordinate_overrides={
                            "system": metric["system"],
                            "codec": primary["codec"],
                            "dataset": metric["dataset"],
                            "policy": metric["policy"],
                            "deadline_ms": metric["deadline_ms"],
                            "repeat": metric["repeat"],
                            "streams": metric["streams"],
                            "seed": metric["seed"],
                            "warmup_s": primary["warmup_s"],
                            "measurement_s": primary["measurement_s"],
                            "run_seed": metric["run_seed"],
                        },
                    )
                    material["descriptive_statistics"] = _primary_descriptive(
                        metric,
                        deadlines_ms=sorted(
                            {
                                *map(
                                    float,
                                    config["benchmark"]["report_deadline_ms"],
                                ),
                                float(metric["deadline_ms"]),
                            }
                        ),
                    )
                    material["primary_architecture_run_metric"] = metric
                    arms.append(material)
                pair_metric = build_primary_architecture_pairs_from_run_metrics(
                    pd.DataFrame(repeat_metrics), config
                )
                selected = pair_metric[pair_metric["repeat"] == repeat]
                self.assertEqual(len(selected), 1)
                record = build_article_statistics_pair_record_v1(
                    pair_identity={
                        "matrix_sha256": SHA,
                        "run_id": "full-primary-run",
                        "pair_sequence": pair_sequence,
                        "pair_id": pair_id,
                        "pair_sha256": f"{repeat + 500:064x}",
                        "attempt": 1,
                    },
                    arms=arms,
                    primary_architecture_pair_metric=selected.iloc[0].to_dict(),
                    config=config,
                )
                binding = persist_article_statistics_pair_record_v1(
                    record, run_root=run_root, pair_dir=pair_dir
                )
                paths.append(run_root / binding["retained_copy"]["relative_path"])

            inference = build_primary_architecture_inference_from_article_records_v1(
                paths, config=config
            )
            self.assertEqual(len(inference["source_records"]), 10)
            self.assertEqual(len(inference["pairs"]), 10)
            self.assertEqual(inference["claim_state"]["accepted_pairs"], 10)
            self.assertEqual(
                inference["claim_state"]["claim_state"],
                "favorable_preregistered_rule_satisfied",
            )
            self.assertRegex(inference["result_identity_sha256"], r"^[0-9a-f]{64}$")

    def test_record_is_self_hashed_and_both_copies_are_physically_bound(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, record = _record(run_root)
            binding = persist_article_statistics_pair_record_v1(
                record,
                run_root=run_root,
                pair_dir=pair_dir,
            )

            checked = validate_article_statistics_binding_v1(
                binding,
                run_root=run_root,
                pair_dir=pair_dir,
                require_attempt_copy=True,
                require_retained_copy=True,
                require_raw_evidence=True,
            )
            self.assertEqual(
                checked["record_identity_sha256"], record["record_identity_sha256"]
            )
            self.assertEqual(
                checked["attempt_copy"]["sha256"],
                checked["retained_copy"]["sha256"],
            )

    def test_retained_parent_redirect_is_rejected_before_either_copy_write(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, record = _record(run_root)
            outside = Path(tmp) / "outside"
            outside.mkdir()
            redirect = run_root / "article_statistics"
            try:
                redirect.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks are unavailable: {error}")

            with self.assertRaisesRegex(
                ArticleStatisticsV1Error,
                "physical namespace rejected",
            ):
                persist_article_statistics_pair_record_v1(
                    record,
                    run_root=run_root,
                    pair_dir=pair_dir,
                )

            self.assertFalse((pair_dir / "article_statistics.v1.json").exists())
            self.assertEqual(list(outside.iterdir()), [])

    def test_preexisting_attempt_leaf_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, record = _record(run_root)
            attempt = pair_dir / "article_statistics.v1.json"
            attacker_payload = b"attacker-owned\n"
            attempt.write_bytes(attacker_payload)

            with self.assertRaisesRegex(
                ArticleStatisticsV1Error,
                "immutable article-statistics commit/collision",
            ):
                persist_article_statistics_pair_record_v1(
                    record,
                    run_root=run_root,
                    pair_dir=pair_dir,
            )

            self.assertEqual(attempt.read_bytes(), attacker_payload)
            self.assertEqual(
                list((run_root / "article_statistics" / "pairs").iterdir()),
                [],
            )

    @unittest.skipUnless(os.name == "posix", "atomic crash recovery is POSIX-only")
    def test_same_path_retry_recovers_both_copies_at_every_physical_window(
        self,
    ) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for leaf in ("attempt", "retained"):
            for step in steps:
                with (
                    self.subTest(leaf=leaf, step=step),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    run_root = Path(tmp) / "run"
                    pair_dir, record = _record(run_root)
                    pair = record["pair"]
                    attempt_path = pair_dir / "article_statistics.v1.json"
                    retained_path = (
                        run_root
                        / "article_statistics"
                        / "pairs"
                        / (
                            f"{pair['pair_sequence']:04d}_{pair['pair_id']}"
                            f".attempt-{pair['attempt']:04d}.v1.json"
                        )
                    )

                    def crash(observed: str) -> None:
                        if observed == f"{leaf}:{step}":
                            raise InjectedCrash(observed)

                    with self.assertRaises(InjectedCrash):
                        persist_article_statistics_pair_record_v1(
                            record,
                            run_root=run_root,
                            pair_dir=pair_dir,
                            after_physical_commit_step=crash,
                        )
                    existing_identities = {
                        path: (path.stat().st_dev, path.stat().st_ino)
                        for path in (attempt_path, retained_path)
                        if path.exists()
                    }
                    binding = persist_article_statistics_pair_record_v1(
                        record,
                        run_root=run_root,
                        pair_dir=pair_dir,
                    )
                    checked = validate_article_statistics_binding_v1(
                        binding,
                        run_root=run_root,
                        pair_dir=pair_dir,
                        require_attempt_copy=True,
                        require_retained_copy=True,
                        require_raw_evidence=True,
                    )
                    self.assertEqual(
                        checked["attempt_copy"]["sha256"],
                        checked["retained_copy"]["sha256"],
                    )
                    self.assertEqual(
                        attempt_path.read_bytes(), retained_path.read_bytes()
                    )
                    for path in (attempt_path, retained_path):
                        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                        self.assertEqual(path.stat().st_nlink, 1)
                    for path, expected_identity in existing_identities.items():
                        self.assertEqual(
                            (path.stat().st_dev, path.stat().st_ino),
                            expected_identity,
                        )

    def test_validator_rejects_per_stream_aggregate_drift_even_with_rehashed_record(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            _, record = _record(Path(tmp) / "run")
            changed = copy.deepcopy(record)
            changed["arms"][0]["descriptive_statistics"]["arm_performance"][
                "ingress"
            ]["completed"] = 5
            changed["arms"][0]["descriptive_statistics"]["arm_performance"][
                "ingress"
            ]["count"] = 5
            latency = changed["arms"][0]["descriptive_statistics"][
                "arm_performance"
            ]["completed_latency_ms"]
            latency["count"] = 5
            latency["sum"] = 100.0
            latency["sum_squares"] = 2000.0
            changed["arms"][0]["descriptive_statistics"]["arm_performance"][
                "throughput_completed_fps"
            ] = 5.0 / 180.0
            changed.pop("record_identity_sha256")
            changed["record_identity_sha256"] = hashlib.sha256(
                __import__("json").dumps(
                    changed,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            with self.assertRaisesRegex(
                ArticleStatisticsV1Error, "per-stream ingress aggregate"
            ):
                validate_article_statistics_pair_record_v1(changed)

    def test_binding_rejects_retained_copy_tamper_and_raw_evidence_tamper(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            run_root = Path(tmp) / "run"
            pair_dir, record = _record(run_root)
            binding = persist_article_statistics_pair_record_v1(
                record,
                run_root=run_root,
                pair_dir=pair_dir,
            )
            retained = run_root / binding["retained_copy"]["relative_path"]
            retained.write_bytes(retained.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                ArticleStatisticsV1Error, "retained article-statistics copy"
            ):
                validate_article_statistics_binding_v1(
                    binding,
                    run_root=run_root,
                    pair_dir=pair_dir,
                    require_attempt_copy=True,
                    require_retained_copy=True,
                    require_raw_evidence=True,
                )

            retained.write_bytes(
                pair_dir.joinpath("article_statistics.v1.json").read_bytes()
            )
            raw = pair_dir / record["arms"][0]["evidence_files"][0]["relative_path"]
            raw.write_bytes(raw.read_bytes() + b"tamper")
            with self.assertRaisesRegex(
                ArticleStatisticsV1Error, "raw evidence descriptor"
            ):
                validate_article_statistics_binding_v1(
                    binding,
                    run_root=run_root,
                    pair_dir=pair_dir,
                    require_attempt_copy=True,
                    require_retained_copy=True,
                    require_raw_evidence=True,
                )


if __name__ == "__main__":
    unittest.main()
