#!/usr/bin/env python3
from __future__ import annotations

import csv
import hashlib
import json
import os
import shlex
import socket
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import (
    ContractError,
    STAGE_CONTRACT_COLUMNS,
    STAGE_SEMANTIC_CONTRACT_VERSION,
)
from checkpoint_admission import require_matching_measurement_schedule_fingerprints
from checkpoint_runtime import (
    DirectRuntimeJoinCoordinator,
    RuntimeMessage,
    SourceLaunchSpec,
    WorkerBinding,
    WorkerLaunchSpec,
    build_runtime_terminal_ingress_ledger,
    expected_worker_assignments,
    run_worker_processes,
    native_subprocess_environment,
    select_native_monotonic_clock,
)
from checkpoint_runtime_plan import build_primary_pair_plans
from checkpoint_gstreamer_runtime import (
    ENGINEERING_STATUS,
    NATIVE_TERMINAL_ANALYTICS_MODE,
    TOPOLOGY_ONLY_ANALYTICS_MODE,
    build_runtime_cohort_audit,
    build_gstreamer_source_specs,
    build_gstreamer_worker_specs,
    load_analytics_model_bindings,
    merge_runtime_fanout_intervals,
    merge_runtime_fanout_work_counters,
    merge_runtime_stage_contracts,
    seed_gstreamer_registry_copies,
    validate_source_provenance,
    validate_worker_source_provenance,
    write_runtime_branch_terminals,
)
from run_experiments import load_config
from full_resource_contract import FANOUT_WORK_COUNTER_COLUMNS
from resource_interval_contract import RESOURCE_INTERVAL_COLUMNS
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
FIXTURE = ROOT / "tests" / "fixtures" / "checkpoint_event_worker.py"


def message(
    *,
    worker_id: str,
    sequence: int,
    event_kind: str,
    stage: str,
    branch_id: str,
    execution_id: str,
    parents: list[str],
    trace_id: str = "run-1:0:0",
    frame_id: int = 0,
    input_frame_key: str = "dataset:0:sha:pts0",
) -> str:
    return json.dumps(
        {
            "protocol_version": 1,
            "worker_id": worker_id,
            "sequence": sequence,
            "run_id": "run-1",
            "trace_id": trace_id,
            "stream_id": 0,
            "frame_id": frame_id,
            "input_frame_key": input_frame_key,
            "topology_kind": INDEPENDENT_PROCESSES,
            "event_kind": event_kind,
            "stage": stage,
            "branch_id": branch_id,
            "execution_id": execution_id,
            "parent_execution_ids": parents,
            "timestamp_ms": 1000 + sequence,
        }
    )


def admission_message(
    *,
    terminal_reason: str | None = None,
    objects: int = 0,
    detector: str = "not-terminal",
    backend: str = "test-backend",
    **kwargs,
) -> str:
    row = json.loads(message(**kwargs))
    row["protocol_version"] = 3 if terminal_reason is not None else 2
    row["admission_id"] = "run-1:0:admission:1"
    row["payload_sha256"] = "1" * 64
    if terminal_reason is not None:
        row.update(
            {
                "terminal_reason": terminal_reason,
                "objects": objects,
                "detector": detector,
                "backend": backend,
            }
        )
    return json.dumps(row)


class CheckpointRuntimeTests(unittest.TestCase):
    def test_native_subprocess_environment_does_not_leak_python_import_paths(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "PYTHONPATH": "/untrusted/python",
                "PYTHONHOME": "/untrusted/home",
                "VAST_NATIVE_PYTHONPATH": "/trusted/dlstreamer",
                "GST_PLUGIN_PATH": "/gst",
            },
            clear=True,
        ):
            environment = native_subprocess_environment({"VAST_CHILD": "1"})

        self.assertEqual(environment["PYTHONPATH"], "/trusted/dlstreamer")
        self.assertNotIn("PYTHONHOME", environment)
        self.assertNotIn("VAST_NATIVE_PYTHONPATH", environment)
        self.assertEqual(environment["GST_PLUGIN_PATH"], "/gst")
        self.assertEqual(environment["VAST_CHILD"], "1")

    def test_registry_template_is_copied_to_distinct_immutable_runtime_seeds(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            template = root / "template.bin"
            template.write_bytes(b"prebuilt-gstreamer-registry")
            worker = WorkerLaunchSpec(
                worker_id="worker-0",
                stream_id=0,
                branch_id="plate_number",
                command=("worker",),
                environment={
                    "GST_REGISTRY": str(root / "worker.bin"),
                    "GST_REGISTRY_UPDATE": "no",
                },
            )
            source = SourceLaunchSpec(
                source_process_id="source-0",
                stream_id=0,
                dataset_id="dataset",
                source_sha256="a" * 64,
                command=("source",),
                environment={
                    "GST_REGISTRY": str(root / "source.bin"),
                    "GST_REGISTRY_UPDATE": "no",
                },
            )

            manifest = seed_gstreamer_registry_copies(
                [worker],
                [source],
                template_path=template,
                refresh_hardware_plugins=False,
            )

            self.assertEqual((root / "worker.bin").read_bytes(), template.read_bytes())
            self.assertEqual((root / "source.bin").read_bytes(), template.read_bytes())
            self.assertEqual(manifest["copy_count"], 2)
            self.assertTrue(manifest["registry_update_disabled"])
            self.assertEqual(
                manifest["base_template_sha256"],
                hashlib.sha256(template.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                manifest["seeded_template_sha256"],
                manifest["base_template_sha256"],
            )
            self.assertFalse(manifest["hardware_refresh"]["performed"])

    def test_gstreamer_engineering_specs_bind_every_blueprint_process_without_unblocking(self) -> None:
        config = load_config(ROOT / "configs" / "experiments.yaml")
        datasets = load_config(ROOT / "configs" / "datasets.yaml")["datasets"]
        pair = build_primary_pair_plans(config=config, datasets=datasets, system="gstreamer_custom")
        for key, expected_count, expected_role in (
            ("baseline", 24, "checkpoint_branch"),
            ("shared", 6, "checkpoint_shared"),
        ):
            with self.subTest(key=key):
                specs = build_gstreamer_worker_specs(
                    plan=pair[key],
                    binary=Path("/tmp/vast_native_gst_probe"),
                    output_root=Path("/tmp/vast-checkpoint-engineering"),
                    project_root=ROOT,
                    run_id="engineering-run",
                    duration_s=5,
                    detect_bin="identity",
                )
                source_specs = build_gstreamer_source_specs(
                    plan=pair[key],
                    source_binary=Path("/tmp/vast_checkpoint_source"),
                    project_root=ROOT,
                    run_id="engineering-run",
                )
                self.assertEqual(len(specs), expected_count)
                self.assertEqual(len(source_specs), 6)
                registry_paths = [
                    spec.environment["GST_REGISTRY"] for spec in (*specs, *source_specs)
                ]
                self.assertEqual(len(set(registry_paths)), expected_count + 6)
                self.assertTrue(
                    all(path.startswith("/tmp/vast-gst-registry-") for path in registry_paths))
                self.assertTrue(
                    all(
                        spec.environment["GST_REGISTRY_UPDATE"] == "no"
                        for spec in (*specs, *source_specs)
                    )
                )
                validate_worker_source_provenance(specs)
                self.assertEqual({spec.stream_id for spec in source_specs}, set(range(6)))
                self.assertTrue(all(spec.native_source for spec in source_specs))
                self.assertTrue(all(spec.native_event_source for spec in specs))
                self.assertTrue(
                    all(
                        spec.command[spec.command.index("--checkpoint-analytics-mode") + 1]
                        == TOPOLOGY_ONLY_ANALYTICS_MODE
                        for spec in specs
                    )
                )
                self.assertTrue(all(spec.command[spec.command.index("--role") + 1] == expected_role for spec in specs))
                self.assertEqual(len({spec.command[spec.command.index("--output-dir") + 1] for spec in specs}), expected_count)
                self.assertTrue(all("VAST_CHECKPOINT_SOURCE_SHA256" in spec.environment for spec in specs))
                self.assertTrue(all(spec.environment["VAST_CHECKPOINT_SOURCE_REPLAY"] == "continuous" for spec in specs))
                self.assertTrue(
                    all(
                        spec.command[spec.command.index("--checkpoint-allowed-decoder-factories") + 1]
                        == "nvh264dec,nvv4l2decoder"
                        for spec in specs
                    )
                )
                self.assertTrue(
                    all(
                        spec.environment["VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES"]
                        == "nvh264dec,nvv4l2decoder"
                        for spec in specs
                    )
                )
                self.assertTrue(
                    all(
                        spec.environment["VAST_CHECKPOINT_ADMISSION_MODE"]
                        == "native_common_source_coordinator"
                        for spec in specs
                    )
                )
                self.assertTrue(all(spec.environment["VAST_CHECKPOINT_DATASET_ID"] == pair[key]["dataset"] for spec in specs))
                self.assertTrue(
                    all(spec.command[spec.command.index("--dataset-id") + 1] == pair[key]["dataset"] for spec in specs)
                )
                expected_sources: dict[int, str] = {}
                for stream in pair[key]["streams"]:
                    owner = stream["workers"][0] if key == "baseline" else stream["graph_process"]
                    expected_sources[int(stream["stream_id"])] = str(ROOT / str(owner["input_path"]))
                for spec in specs:
                    self.assertNotIn("--dataset-streams-json", spec.command)
                    self.assertEqual(spec.command[spec.command.index("--checkpoint-container") + 1], "mp4")
                    self.assertEqual(spec.command[spec.command.index("--checkpoint-codec") + 1], "h264")
                    self.assertEqual(spec.command[spec.command.index("--source-replay") + 1], "continuous")
                    self.assertGreater(int(spec.command[spec.command.index("--source-duration-ns") + 1]), 0)
                for spec in source_specs:
                    self.assertEqual(
                        spec.command[spec.command.index("--source-path") + 1],
                        expected_sources[spec.stream_id],
                    )
                    self.assertEqual(
                        spec.environment["VAST_CHECKPOINT_ADMISSION_MODE"],
                        "native_common_source_coordinator",
                    )
                    self.assertEqual(
                        spec.command[spec.command.index("--playback-timestamp-scale") + 1],
                        "600",
                    )
                    self.assertEqual(spec.environment["VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE"], "600")
        self.assertEqual(ENGINEERING_STATUS, "engineering_runtime_incomplete_not_publishable")

    def test_native_analytics_terminal_mode_requires_explicit_branch_aware_adapter(self) -> None:
        config = load_config(ROOT / "configs" / "experiments.yaml")
        datasets = load_config(ROOT / "configs" / "datasets.yaml")["datasets"]
        plan = build_primary_pair_plans(
            config=config,
            datasets=datasets,
            system="gstreamer_custom",
        )["shared"]
        common = {
            "plan": plan,
            "binary": Path("/tmp/vast_native_gst_probe"),
            "output_root": Path("/tmp/vast-checkpoint-engineering"),
            "project_root": ROOT,
            "run_id": "engineering-run",
            "duration_s": 5,
            "analytics_terminal_mode": NATIVE_TERMINAL_ANALYTICS_MODE,
        }
        with self.assertRaisesRegex(ContractError, "non-identity"):
            build_gstreamer_worker_specs(detect_bin="identity", **common)
        with self.assertRaisesRegex(ContractError, r"\{branch\} placeholder"):
            build_gstreamer_worker_specs(detect_bin="vastanalytics", **common)

        specs = build_gstreamer_worker_specs(
            detect_bin="vastanalytics branch={branch}",
            **common,
        )
        self.assertEqual(len(specs), 6)
        self.assertTrue(
            all(
                spec.command[spec.command.index("--checkpoint-analytics-mode") + 1]
                == NATIVE_TERMINAL_ANALYTICS_MODE
                for spec in specs
            )
        )
        self.assertTrue(
            all(
                spec.environment["VAST_CHECKPOINT_ANALYTICS_MODE"]
                == NATIVE_TERMINAL_ANALYTICS_MODE
                for spec in specs
            )
        )

    def test_reference_analytics_terminal_requires_verified_branch_model_manifest(self) -> None:
        config = load_config(ROOT / "configs" / "experiments.yaml")
        datasets = load_config(ROOT / "configs" / "datasets.yaml")["datasets"]
        plan = build_primary_pair_plans(
            config=config,
            datasets=datasets,
            system="gstreamer_custom",
        )["shared"]
        template = (
            'videoconvert ! video/x-raw,format={input_format} ! vastanalyticsqueue branch-id={branch} detector-id={detector_id} '
            'expected-downstream-factory={factory} '
            'expected-model-sha256="{model_sha256}" '
            'expected-weights-sha256="{weights_sha256}" max-buffers={max_buffers} ! '
            '{factory} '
            'name=checkpoint_detector_{branch} batch-size={batch_size} nireq={nireq} ie-config={ie_config} model="{model_path}" device={device} ! '
            'vastanalyticsterminal branch-id={branch} detector-id={detector_id} '
            'expected-upstream-factory={factory} '
            'expected-model-sha256="{model_sha256}" '
            'expected-weights-sha256="{weights_sha256}"'
        )
        common = {
            "plan": plan,
            "binary": Path("/tmp/vast_native_gst_probe"),
            "output_root": Path("/tmp/vast-checkpoint-engineering"),
            "project_root": ROOT,
            "run_id": "engineering-run",
            "duration_s": 5,
            "detect_bin": template,
            "analytics_terminal_mode": NATIVE_TERMINAL_ANALYTICS_MODE,
        }
        unsafe = {**common, "detect_bin": template.replace(" name=checkpoint_detector_{branch}", "")}
        with self.assertRaisesRegex(ContractError, "unique branch-derived detector name"):
            build_gstreamer_worker_specs(**unsafe)

        with self.assertRaisesRegex(ContractError, "exact branch model bindings"):
            build_gstreamer_worker_specs(**common)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest_rows: dict[str, dict[str, str]] = {}
            for branch in BRANCHES:
                source_name = f"omz-proxy-{branch.replace('_', '-')}"
                model = root / f"{branch}.xml"
                weights = root / f"{branch}.bin"
                model.write_text(f'<net name="{branch}" version="11"/>\n', encoding="utf-8")
                weights.write_bytes(f"{branch}-weights\n".encode("utf-8"))
                manifest_rows[branch] = {
                    "proxy_role": branch,
                    "semantic_claim": "topology_load_proxy_only",
                    "source_model_name": source_name,
                    "source_model_config_url": (
                        "https://raw.githubusercontent.com/openvinotoolkit/open_model_zoo/"
                        "602c643ac909f1bbfa1fed0f3c4723772508d7d9/models/intel/"
                        f"{source_name}/model.yml"
                    ),
                    "factory": "gvadetect",
                    "device": "CPU",
                    "input_format": "BGR",
                    "batch_size": 1,
                    "nireq": 1,
                    "ie_config": "PERFORMANCE_HINT=LATENCY,NUM_STREAMS=1,INFERENCE_NUM_THREADS=1",
                    "detector_id": f"kpp-{branch}-v1",
                    "model_path": model.name,
                    "model_sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                    "model_source_url": (
                        "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
                        f"2023.0/models_bin/1/{source_name}/FP16/{source_name}.xml"
                    ),
                    "model_source_sha384": "a" * 96,
                    "weights_path": weights.name,
                    "weights_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
                    "weights_source_url": (
                        "https://storage.openvinotoolkit.org/repositories/open_model_zoo/"
                        f"2023.0/models_bin/1/{source_name}/FP16/{source_name}.bin"
                    ),
                    "weights_source_sha384": "b" * 96,
                    "input": {
                        "name": "image",
                        "layout": "NCHW",
                        "shape": [1, 3, 300, 300],
                        "color_order": "BGR",
                    },
                    "output": {
                        "semantics": "openvino_detection_output_1x1nx7",
                        "coordinates": "normalized_xyxy",
                    },
                }
            manifest = root / "analytics-models.yaml"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "artifact_kind": "checkpoint_analytics_model_bindings",
                        "manifest_id": "checkpoint-runtime-test-models-v2",
                        "selection_basis": "public_omz_proxies_frozen_before_benchmark_results",
                        "runtime_family": "openvino_dlstreamer",
                        "precision": "FP16",
                        "effective_batch_size": 1,
                        "provenance": {
                            "catalog": "Open Model Zoo",
                            "catalog_version": "2024.6.0",
                            "catalog_revision": "602c643ac909f1bbfa1fed0f3c4723772508d7d9",
                            "license_spdx": "Apache-2.0",
                            "license_url": (
                                "https://raw.githubusercontent.com/openvinotoolkit/"
                                "open_model_zoo/602c643ac909f1bbfa1fed0f3c4723772508d7d9/LICENSE"
                            ),
                            "acquisition_tool": "omz_downloader",
                        },
                        "branches": manifest_rows,
                    }
                ),
                encoding="utf-8",
            )
            bindings = load_analytics_model_bindings(
                manifest,
                required_branches=BRANCHES,
            )
            specs = build_gstreamer_worker_specs(
                analytics_model_bindings=bindings,
                **common,
            )
            self.assertEqual(len(specs), 6)
            for spec in specs:
                for branch in BRANCHES:
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_MODEL_PATH_{branch}"],
                        str((root / f"{branch}.xml").resolve()),
                    )
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_MODEL_SHA256_{branch}"],
                        manifest_rows[branch]["model_sha256"],
                    )
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_WEIGHTS_SHA256_{branch}"],
                        manifest_rows[branch]["weights_sha256"],
                    )
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_MAX_BUFFERS_{branch}"],
                        "1",
                    )
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_DEVICE_{branch}"],
                        "CPU",
                    )
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_INPUT_FORMAT_{branch}"],
                        "BGR",
                    )
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_BATCH_SIZE_{branch}"],
                        "1",
                    )
                    self.assertEqual(
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_NIREQ_{branch}"],
                        "1",
                    )
                    self.assertIn(
                        "INFERENCE_NUM_THREADS=1",
                        spec.environment[f"VAST_CHECKPOINT_ANALYTICS_IE_CONFIG_{branch}"],
                    )

            with self.assertRaisesRegex(ContractError, "differs from the preregistered primary value"):
                build_gstreamer_worker_specs(
                    analytics_model_bindings=bindings,
                    analytics_queue_max_buffers=2,
                    **common,
                )

            (root / "damage.bin").write_bytes(b"drifted-weights")
            with self.assertRaisesRegex(ContractError, "weights SHA-256 differs"):
                load_analytics_model_bindings(manifest, required_branches=BRANCHES)

    def test_runtime_branch_terminal_artifact_preserves_v3_without_becoming_accepted(self) -> None:
        ingress = {
            "run_id": "run-1",
            "cohort_id": "run-1:measurement",
            "trace_id": "run-1:0:0",
            "input_frame_key": "dataset:0:sha:0:90000",
            "stream_id": 0,
            "frame_id": 0,
            "ingress_timestamp_ms": 1000,
            "terminal_status": "completed",
            "terminal_timestamp_ms": 1208,
            "drain_end_timestamp_ms": 2000,
        }
        records = [
            {
                "run_id": "run-1",
                "trace_id": "run-1:0:0",
                "input_frame_key": "dataset:0:sha:0:90000",
                "stream_id": 0,
                "frame_id": 0,
                "branch_id": branch,
                "terminal_status": "completed",
                "terminal_timestamp_ms": 1200 + index,
                "objects": index,
                "detector": f"native-{branch}-v1",
                "backend": "openvino-gva",
                "terminal_reason": "native_result_committed",
                "runtime_protocol_version": 3,
                "event_provenance": "native_runtime_event",
                "telemetry_source": "native",
            }
            for index, branch in enumerate(BRANCHES)
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path, audit = write_runtime_branch_terminals(
                records=records,
                ingress_rows=[ingress],
                required_branches=BRANCHES,
                output_root=Path(tmp),
            )
            with path.open(newline="", encoding="utf-8") as source:
                rows = list(csv.DictReader(source))
        self.assertEqual(len(rows), 4)
        self.assertEqual({row["telemetry_source"] for row in rows}, {"engineering_runtime"})
        self.assertEqual(audit["fully_terminalized_ingress_count"], 1)
        self.assertFalse(audit["accepted_branch_terminals_written"])

        records[0]["runtime_protocol_version"] = 2
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ContractError, "protocol-v3"):
                write_runtime_branch_terminals(
                    records=records,
                    ingress_rows=[ingress],
                    required_branches=BRANCHES,
                    output_root=Path(tmp),
                )

    def test_native_probe_source_contains_physical_checkpoint_graphs_and_direct_emitter(self) -> None:
        body = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(encoding="utf-8")
        source_body = (
            ROOT / "deploy" / "native_gst_probe" / "checkpoint_source_coordinator.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn('#include "checkpoint_runtime_emitter.hpp"', body)
        self.assertIn('#include "checkpoint_admission_transport.hpp"', body)
        self.assertIn('#include "checkpoint_analytics_terminal_transport.hpp"', body)
        self.assertIn('#include "checkpoint_resource_interval_emitter.hpp"', body)
        self.assertIn('args_.role == "checkpoint_branch"', body)
        self.assertIn('args_.role == "checkpoint_shared"', body)
        self.assertIn('! tee name=checkpoint_tee', body)
        self.assertIn('queue name=checkpoint_fanout_', body)
        self.assertIn('"checkpoint-fanout-start"', body)
        self.assertIn('branch,\n                "sink"', body)
        self.assertIn('checkpoint_fanout_starts_by_branch', body)
        self.assertIn('resource_intervals.runtime.csv', (
            ROOT / "deploy" / "native_gst_probe" / "checkpoint_resource_interval_emitter.hpp"
        ).read_text(encoding="utf-8"))
        self.assertIn('fanout_work_counters.runtime.csv', (
            ROOT / "deploy" / "native_gst_probe" / "checkpoint_resource_interval_emitter.hpp"
        ).read_text(encoding="utf-8"))
        self.assertIn("CheckpointFanoutWorkCounterEmitter", body)
        self.assertIn("checkpoint_fanout_work_emitter_->emit(", body)
        self.assertIn("CLOCK_THREAD_CPUTIME_ID", body)
        self.assertIn('"branch_complete"', body)
        self.assertIn('std::numeric_limits<std::uint8_t>::max()', body)
        self.assertIn('state.traces.erase(', body)
        self.assertIn('args_.dataset_id + ":" + std::to_string(args_.logical_stream_id)', body)
        self.assertIn('std::to_string(trace.source_cycle)', body)
        self.assertIn('checkpoint_emitter_->emit_with_admission', body)
        self.assertIn('emit_branch_terminal_with_admission', body)
        self.assertIn('native_terminal_socket_v1', body)
        self.assertIn('"VAST_CHECKPOINT_ANALYTICS_" + field + "_" + branch', body)
        self.assertIn('checkpoint_analytics_binding(branch, "MODEL_PATH")', body)
        self.assertIn('replace_all(value, "{model_sha256}"', body)
        self.assertIn('replace_all(value, "{max_buffers}"', body)
        self.assertIn('replace_all(value, "{input_format}"', body)
        self.assertIn('replace_all(value, "{batch_size}"', body)
        self.assertIn('replace_all(value, "{nireq}"', body)
        self.assertIn('replace_all(value, "{ie_config}"', body)
        terminal_body = (
            ROOT / "deploy" / "gstreamer_analytics_terminal" / "gstvastanalyticsterminal.cpp"
        ).read_text(encoding="utf-8")
        provenance_body = (
            ROOT / "deploy" / "gstreamer_analytics_terminal" / "checkpoint_analytics_model_provenance.hpp"
        ).read_text(encoding="utf-8")
        queue_body = (
            ROOT / "deploy" / "gstreamer_analytics_terminal" / "gstvastanalyticsqueue.cpp"
        ).read_text(encoding="utf-8")
        self.assertIn('expected-model-sha256', terminal_body)
        prefix_queue_body = (
            ROOT / "deploy" / "gstreamer_analytics_terminal" / "gstvastcheckpointprefixqueue.cpp"
        ).read_text(encoding="utf-8")

        self.assertIn('expected-weights-sha256', terminal_body)
        self.assertIn('"current-level-buffers"', terminal_body)
        self.assertIn('weights_path = model_path.substr', provenance_body)
        self.assertIn(';model_sha256=', provenance_body)
        self.assertIn('native_pre_detector_queue_full_drop_newest', queue_body)
        self.assertIn('self->src_pad != nullptr && GST_IS_PAD(self->src_pad)', queue_body)
        self.assertIn('native_postdecode_preprocess_queue_full_drop_newest', prefix_queue_body)
        self.assertIn('const std::uint64_t transport_pts_ns = GST_BUFFER_PTS(buffer)', prefix_queue_body)
        self.assertIn('terminal.transport_pts_ns = transport_pts_ns', prefix_queue_body)
        self.assertIn('vastcheckpointprefixqueue name=checkpoint_prefix_queue', body)
        self.assertIn('VAST_CHECKPOINT_ANALYTICS_TERMINAL_FD', (
            ROOT / "deploy" / "native_gst_probe" / "checkpoint_analytics_terminal_transport.hpp"
        ).read_text(encoding="utf-8"))
        self.assertIn('ctx->kind == "checkpoint-branch" && self->native_checkpoint_analytics_enabled()', body)
        self.assertIn('stage_contracts.runtime.csv', body)
        launcher_body = (
            ROOT / "scripts" / "checkpoint_gstreamer_runtime.py"
        ).read_text(encoding="utf-8")
        publication_body = (
            ROOT / "scripts" / "checkpoint_publication_runtime.py"
        ).read_text(encoding="utf-8")
        self.assertIn('ingress_ledger.runtime.csv', launcher_body)
        self.assertIn('terminal_admission_audit.runtime.json', launcher_body)
        self.assertIn('from checkpoint_publication_runtime import publish_checkpoint_runtime', launcher_body)
        self.assertIn('--execute-publication-runtime', launcher_body)
        self.assertIn('publication_acceptance = publish_checkpoint_runtime(', launcher_body)
        self.assertIn('checkpoint_publication_acceptance.json', publication_body)
        self.assertIn('require_reset_evidence=True', publication_body)
        self.assertIn('"runtime_loaded_configuration"', body)
        self.assertIn('"runtime_loaded_artifacts_v1"', body)
        self.assertIn('implementation_artifacts_sha256', body)
        self.assertNotIn('static_cast<std::uint64_t>(ctx->stream_id)', body)
        self.assertNotIn('std::to_string(ctx->stream_id)', body)
        self.assertIn('gst_plugin_get_filename', body)
        self.assertIn('sha256_file(args_.executable_path)', body)
        self.assertIn('"native_pts_preserved_with_gap_free_decode_order_admission_v3"', body)
        self.assertIn('GST_BUFFER_PTS_IS_VALID(buffer)', body)
        self.assertIn('"checkpoint-ingress"', body)
        self.assertIn('appsrc name=checkpoint_appsrc', body)
        self.assertIn('gst_app_src_push_buffer', body)
        self.assertIn('appsrc EOS received; awaiting native terminal drain', body)
        self.assertNotIn('appsrc EOS reached before every admitted AU drained', body)
        self.assertIn('block=true', body)
        self.assertIn('leaky-type=none', body)
        self.assertIn('max-buffers=1', body)
        self.assertIn('kMaximumQueuedCheckpointAccessUnits = 1024', body)
        self.assertIn('checkpoint_ingress_queue_.size() < kMaximumQueuedCheckpointAccessUnits', body)
        self.assertIn('checkpoint_ingress_queue_', body)
        self.assertIn('receive_checkpoint_access_units', body)
        self.assertNotIn('g_object_get(G_OBJECT(appsrc_element), "dropped"', body)
        self.assertNotIn('native_predecode_ingress_queue_full_drop_newest', body)
        self.assertIn('CheckpointAdmissionTransport::read_frame', body)
        self.assertNotIn('decoded-buffer PTS is not strictly increasing', body)
        self.assertNotIn('filesrc name=file_src" << stream_id\n      << " ! qtdemux', body)
        self.assertIn('appsink name=checkpoint_source_sink', source_body)
        self.assertIn('gst_app_sink_try_pull_sample', source_body)
        self.assertIn('gst_element_seek_simple', source_body)
        self.assertIn('CheckpointAdmissionTransport::write_frame', source_body)
        self.assertIn('kMaximumQueuedAccessUnitsPerConsumer', source_body)
        self.assertIn('enqueue_for_all_consumers', source_body)
        self.assertIn('checkpoint consumer delivery queue overflow', source_body)
        self.assertIn('next_schedule_offset_ns_', source_body)
        self.assertIn('scheduled_admission_time', source_body)
        self.assertIn('args_.playback_timestamp_scale', source_body)
        self.assertIn('checked_multiply(native_pts', source_body)
        self.assertNotIn('native PTS is not strictly increasing within cycle', source_body)
        self.assertIn('VAST_CHECKPOINT_CONTROL_FD', body)
        self.assertIn('write_checkpoint_lifecycle_status("READY"', body)
        self.assertIn('verify_checkpoint_reset_state_before_ready();', body)
        self.assertIn('verify_reset_state_before_ready();', source_body)
        self.assertIn('write_checkpoint_lifecycle_status("ADMISSION_STOPPED"', body)
        self.assertIn('write_checkpoint_lifecycle_status("DECODER_PLACEMENT_VERIFIED"', body)
        self.assertIn('VAST_CHECKPOINT_ALLOWED_DECODER_FACTORIES', body)
        self.assertIn('--checkpoint-allowed-decoder-factories', launcher_body)
        self.assertIn('require_decoder_placement_verification=True', launcher_body)
        self.assertIn('checkpoint_admission_stopped_', body)
        self.assertIn('::poll(&descriptor, 1, 100)', body)
        self.assertIn('checkpoint_loop_finished_', body)
        self.assertIn('gst_bin_iterate_recurse', body)
        self.assertIn('gst_pad_get_current_caps', body)
        self.assertIn('\\"decoder_factory\\":\\"', body)
        self.assertIn('video/x-raw,format=RGB,width=640,height=360', body)
        self.assertIn('video/x-raw,format=BGR,width=640,height=360', body)
        self.assertNotIn('topology_events.csv', body)

    def test_cpp_resource_interval_emitter_writes_runtime_only_fanout_contract(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("C++ compiler is not available")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "checkpoint-resource-interval-emitter-test"
            fragment = root / "resource_intervals.runtime.csv"
            work_fragment = root / "fanout_work_counters.runtime.csv"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "checkpoint_resource_interval_emitter_test.cpp"),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            emitted = subprocess.run(
                [str(binary), str(fragment), str(work_fragment)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(emitted.returncode, 0, emitted.stderr)
            with fragment.open(newline="", encoding="utf-8") as source:
                reader = csv.DictReader(source)
                rows = list(reader)
            self.assertEqual(reader.fieldnames, RESOURCE_INTERVAL_COLUMNS)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["interval_contract_version"], "2")
            self.assertEqual(rows[0]["component"], "fanout")
            self.assertEqual(rows[0]["duration_ns"], "320")
            self.assertEqual(rows[0]["telemetry_source"], "native")
            with work_fragment.open(newline="", encoding="utf-8") as source:
                work_reader = csv.DictReader(source)
                work_rows = list(work_reader)
            self.assertEqual(work_reader.fieldnames, FANOUT_WORK_COUNTER_COLUMNS)
            self.assertEqual(len(work_rows), 1)
            self.assertEqual(work_rows[0]["thread_cpu_time_ns"], "25000")
            self.assertEqual(work_rows[0]["counter_scope"], "per_trace_resource_work")
            self.assertFalse((root / "resource_intervals.csv").exists())

    def test_runtime_fanout_fragments_are_topology_bound_and_not_accepted(self) -> None:
        run_id = "engineering-run"
        trace_id = f"{run_id}:0:7"
        preprocess_id = f"{trace_id}:shared:preprocess"
        fanout_id = f"{trace_id}:damage:fanout"
        input_frame_key = "kpp_real_h264:0:source:0:90000"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_id = "stream-0-shared-video-dag"
            worker_output = root / "workers" / worker_id
            worker_output.mkdir(parents=True)
            fragment = worker_output / "resource_intervals.runtime.csv"
            row = {
                "schema_version": "2",
                "interval_contract_version": "2",
                "run_id": run_id,
                "trace_id": trace_id,
                "stream_id": "0",
                "frame_id": "7",
                "input_frame_key": input_frame_key,
                "component": "fanout",
                "direction": "none",
                "stage": "fanout",
                "branch_id": "damage",
                "execution_id": fanout_id,
                "host_start_timestamp_ns": "1000000100",
                "host_end_timestamp_ns": "1000000500",
                "duration_ns": "400",
                "bytes": "691200",
                "device_id": "gstreamer:tee-queue",
                "counter_scope": "per_trace_interval",
                "native_event_id": hashlib.sha256(b"fanout-7-damage").hexdigest(),
                "duration_provenance": "native_gstreamer_pad_probe_interval_v1",
                "telemetry_source": "native",
            }
            with fragment.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=RESOURCE_INTERVAL_COLUMNS)
                writer.writeheader()
                writer.writerow(row)
            work_fragment = worker_output / "fanout_work_counters.runtime.csv"
            work_row = {
                "schema_version": "2",
                "resource_contract_version": "2",
                "run_id": run_id,
                "trace_id": trace_id,
                "stream_id": "0",
                "frame_id": "7",
                "input_frame_key": input_frame_key,
                "branch_id": "damage",
                "execution_id": fanout_id,
                "thread_cpu_time_ns": "25000",
                "work_units": "1",
                "device_id": "host:fanout",
                "counter_scope": "per_trace_resource_work",
                "counter_provenance": "native_thread_cpu_time_v1",
                "telemetry_source": "native",
            }
            with work_fragment.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=FANOUT_WORK_COUNTER_COLUMNS)
                writer.writeheader()
                writer.writerow(work_row)
            topology = [
                {
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "stream_id": 0,
                    "frame_id": 7,
                    "input_frame_key": input_frame_key,
                    "event_kind": "stage_complete",
                    "stage": "preprocess",
                    "branch_id": "shared",
                    "execution_id": preprocess_id,
                    "parent_execution_ids_json": "[]",
                    "timestamp_ms": 1000,
                },
                {
                    "run_id": run_id,
                    "trace_id": trace_id,
                    "stream_id": 0,
                    "frame_id": 7,
                    "input_frame_key": input_frame_key,
                    "event_kind": "fanout",
                    "stage": "fanout",
                    "branch_id": "damage",
                    "execution_id": fanout_id,
                    "parent_execution_ids_json": json.dumps([preprocess_id]),
                    "timestamp_ms": 1000,
                },
            ]
            spec = WorkerLaunchSpec(
                worker_id=worker_id,
                stream_id=0,
                branch_id=None,
                command=("/tmp/probe", "--output-dir", str(worker_output)),
                native_event_source=True,
            )
            merged = merge_runtime_fanout_intervals(
                specs=[spec],
                output_root=root,
                run_id=run_id,
                topology_events=topology,
            )
            self.assertEqual(merged, root / "resource_intervals.runtime.csv")
            self.assertFalse((root / "resource_intervals.csv").exists())
            merged_work = merge_runtime_fanout_work_counters(
                specs=[spec],
                output_root=root,
                run_id=run_id,
                topology_events=topology,
            )
            self.assertEqual(merged_work, root / "fanout_work_counters.runtime.csv")
            self.assertFalse((root / "fanout_work_counters.csv").exists())

            row["host_start_timestamp_ns"] = "999999999"
            row["duration_ns"] = str(int(row["host_end_timestamp_ns"]) - 999_999_999)
            with fragment.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=RESOURCE_INTERVAL_COLUMNS)
                writer.writeheader()
                writer.writerow(row)
            with self.assertRaisesRegex(ContractError, "before preprocess"):
                merge_runtime_fanout_intervals(
                    specs=[spec],
                    output_root=root,
                    run_id=run_id,
                    topology_events=topology,
                )

    def test_runtime_stage_contract_fragments_are_pid_bound_merged_and_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            worker_id = "stream-0-shared-video-dag"
            worker_output = root / "workers" / worker_id
            worker_output.mkdir(parents=True)
            pid = 43210
            run_id = "engineering-run"
            domain = f"{socket.gethostname()}:pid-{pid}:worker-{worker_id}"
            rows = []
            for stage in ("decode", "preprocess"):
                base_stage = stage
                config_json = json.dumps(
                    {"backend": "gstreamer", "stage": base_stage},
                    sort_keys=True,
                    separators=(",", ":"),
                )
                artifacts_json = json.dumps(
                    [
                        {
                            "kind": "executable",
                            "logical_name": "vast_native_gst_probe",
                            "role": "stage_host",
                            "sha256": hashlib.sha256(b"probe-binary").hexdigest(),
                        },
                        {
                            "kind": "plugin",
                            "logical_name": f"native-{base_stage}",
                            "role": "stage_plugin",
                            "sha256": hashlib.sha256(
                                f"plugin-{base_stage}".encode("utf-8")
                            ).hexdigest(),
                        },
                    ],
                    sort_keys=True,
                    separators=(",", ":"),
                )
                rows.append(
                    {
                        "schema_version": "2",
                        "semantic_contract_version": str(STAGE_SEMANTIC_CONTRACT_VERSION),
                        "run_id": run_id,
                        "contract_id": f"{run_id}:{domain}:{stage}",
                        "execution_domain": domain,
                        "stage": stage,
                        "base_stage": base_stage,
                        "implementation_name": f"vast-native-gstreamer-checkpoint-{base_stage}",
                        "implementation_version": "1.24.0.0",
                        "implementation_config_json": config_json,
                        "config_sha256": hashlib.sha256(config_json.encode("utf-8")).hexdigest(),
                        "implementation_artifacts_json": artifacts_json,
                        "implementation_artifacts_sha256": hashlib.sha256(
                            artifacts_json.encode("utf-8")
                        ).hexdigest(),
                        "implementation_artifact_provenance": "runtime_loaded_artifacts_v1",
                        "transform_json": json.dumps(
                            {
                                "normalization": {"mode": "identity"},
                                "resize": {"mode": "identity"},
                            },
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "output_media_type": "video/x-raw",
                        "output_format": "rgb24",
                        "output_dtype": "uint8",
                        "output_shape_json": '["source_height","source_width",3]',
                        "ordering_contract": "stream_native_pts_strictly_increasing_v1",
                        "contract_provenance": "runtime_loaded_configuration",
                        "telemetry_source": "native",
                    }
                )
            fragment = worker_output / "stage_contracts.runtime.csv"
            with fragment.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=STAGE_CONTRACT_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)

            spec = WorkerLaunchSpec(
                worker_id=worker_id,
                stream_id=0,
                branch_id=None,
                command=("/tmp/probe", "--output-dir", str(worker_output)),
                native_event_source=True,
            )
            topology = [
                {
                    "run_id": run_id,
                    "event_kind": "stage_complete",
                    "execution_domain": domain,
                    "stage": stage,
                }
                for stage in ("decode", "preprocess")
            ]
            merged = merge_runtime_stage_contracts(
                specs=[spec],
                process_ids={worker_id: pid},
                output_root=root,
                run_id=run_id,
                topology_events=topology,
            )

            self.assertEqual(merged, root / "stage_contracts.runtime.csv")
            with merged.open("r", newline="", encoding="utf-8") as source:
                merged_rows = list(csv.DictReader(source))
            self.assertEqual(len(merged_rows), 2)
            self.assertEqual({row["execution_domain"] for row in merged_rows}, {domain})
            self.assertFalse((root / "stage_contracts.csv").exists())

            rows[0]["execution_domain"] = "forged-domain"
            with fragment.open("w", newline="", encoding="utf-8") as output:
                writer = csv.DictWriter(output, fieldnames=STAGE_CONTRACT_COLUMNS)
                writer.writeheader()
                writer.writerows(rows)
            with self.assertRaisesRegex(ContractError, "not bound to the launched PID"):
                merge_runtime_stage_contracts(
                    specs=[spec],
                    process_ids={worker_id: pid},
                    output_root=root,
                    run_id=run_id,
                    topology_events=topology,
                )

    def test_source_provenance_validation_rejects_manifest_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "source.mp4"
            source.write_bytes(b"checkpoint-source")
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            spec = SourceLaunchSpec(
                source_process_id="stream-0-source-coordinator",
                stream_id=0,
                dataset_id="kpp_real_h264",
                source_sha256=digest,
                command=(
                    "/tmp/source",
                    "--source-path",
                    str(source),
                    "--dataset-id",
                    "kpp_real_h264",
                    "--source-sha256",
                    digest,
                    "--checkpoint-container",
                    "mp4",
                    "--checkpoint-codec",
                    "h264",
                    "--source-duration-ns",
                    "1000000000",
                    "--playback-timestamp-scale",
                    "20",
                    "--source-replay",
                    "continuous",
                    "--logical-stream-id",
                    "0",
                ),
                environment={
                    "VAST_CHECKPOINT_SOURCE_CONTAINER": "mp4",
                    "VAST_CHECKPOINT_SOURCE_CODEC": "h264",
                    "VAST_CHECKPOINT_SOURCE_DURATION_NS": "1000000000",
                    "VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE": "20",
                    "VAST_CHECKPOINT_SOURCE_REPLAY": "continuous",
                    "VAST_CHECKPOINT_ADMISSION_MODE": "native_common_source_coordinator",
                },
                native_source=True,
            )
            validate_source_provenance([spec])
            drifted_command = list(spec.command)
            drifted_command[drifted_command.index("--source-sha256") + 1] = "0" * 64
            drifted = SourceLaunchSpec(
                source_process_id=spec.source_process_id,
                stream_id=spec.stream_id,
                dataset_id=spec.dataset_id,
                source_sha256=spec.source_sha256,
                command=tuple(drifted_command),
                environment=spec.environment,
                native_source=True,
            )
            with self.assertRaisesRegex(ContractError, "binding drifted"):
                validate_source_provenance([drifted])

    def test_cpp_emitter_writes_parseable_gap_free_protocol(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("C++ compiler is not available")
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "checkpoint-runtime-emitter-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-pthread",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "checkpoint_runtime_emitter_test.cpp"),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            emitted = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
            self.assertEqual(emitted.returncode, 0, emitted.stderr)
        rows = [RuntimeMessage.parse(line) for line in emitted.stdout.splitlines()]
        self.assertEqual([row.sequence for row in rows], [1, 2, 3])
        self.assertEqual([row.timestamp_ms for row in rows], [1000, 1000, 1001])
        self.assertEqual(rows[0].worker_id, 'worker-"one')
        self.assertEqual(rows[1].parent_execution_ids, ("source",))
        self.assertEqual(rows[0].protocol_version, 1)
        self.assertEqual(rows[1].protocol_version, 2)
        self.assertEqual(rows[1].admission_id, "run-1:3:admission:1")
        self.assertEqual(
            rows[1].payload_sha256,
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        )
        self.assertEqual(rows[2].protocol_version, 3)
        self.assertEqual(rows[2].event_kind, "branch_complete")
        self.assertEqual(rows[2].terminal_reason, "native_result_committed")
        self.assertEqual(rows[2].objects, 3)
        self.assertEqual(rows[2].detector, "damage-net-v1")
        self.assertEqual(rows[2].backend, "gstreamer-native")

    def test_cpp_admission_transport_round_trips_binary_payload_and_rejects_truncation(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("C++ compiler is not available")
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "checkpoint-admission-transport-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "checkpoint_admission_transport_test.cpp"),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_cpp_analytics_terminal_transport_rejects_identity_and_ambiguous_drop(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        if compiler is None:
            self.skipTest("C++ compiler is not available")
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "checkpoint-analytics-terminal-transport-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "checkpoint_analytics_terminal_transport_test.cpp"),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run([str(binary)], text=True, capture_output=True, check=False)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_gstreamer_analytics_terminal_and_queue_emit_native_outcomes(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
        cmake = shutil.which("cmake")
        pkg_config = shutil.which("pkg-config")
        if compiler is None or cmake is None or pkg_config is None:
            self.skipTest("C++/CMake/pkg-config toolchain is not available")
        packages = subprocess.run(
            [
                pkg_config,
                "--exists",
                "gstreamer-1.0",
                "gstreamer-app-1.0",
                "gstreamer-base-1.0",
                "gstreamer-video-1.0",
            ],
            check=False,
        )
        if packages.returncode != 0:
            self.skipTest("GStreamer base/video development packages are not available")
        with tempfile.TemporaryDirectory() as tmp:
            build = Path(tmp) / "build"
            library = build / "lib"
            configured = subprocess.run(
                [
                    cmake,
                    "-S",
                    str(ROOT),
                    "-B",
                    str(build),
                    f"-DCMAKE_LIBRARY_OUTPUT_DIRECTORY={library}",
                    f"-DCMAKE_RUNTIME_OUTPUT_DIRECTORY={build / 'bin'}",
                    "-DVAST_BUILD_NATIVE_GST_PROBE=OFF",
                    "-DVAST_BUILD_CUSTOM_CUDA_QT=OFF",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(configured.returncode, 0, configured.stderr)
            built = subprocess.run(
                [
                    cmake,
                    "--build",
                    str(build),
                    "--target",
                    "gstvastanalyticsterminal",
                    "gstvastanalyticsqueue",
                    "gstvastcheckpointprefixqueue",
                    "-j2",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(built.returncode, 0, built.stderr)
            plugin_candidates = tuple(library.glob("*gstvastanalyticsterminal*"))
            self.assertEqual(len(plugin_candidates), 1)
            queue_plugin_candidates = tuple(library.glob("*gstvastanalyticsqueue*"))
            self.assertEqual(len(queue_plugin_candidates), 1)

            prefix_queue_candidates = tuple(library.glob("*gstvastcheckpointprefixqueue*"))
            self.assertEqual(len(prefix_queue_candidates), 1)
            flags = subprocess.run(
                [
                    pkg_config,
                    "--cflags",
                    "--libs",
                    "gstreamer-1.0",
                    "gstreamer-app-1.0",
                    "gstreamer-base-1.0",
                    "gstreamer-video-1.0",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(flags.returncode, 0, flags.stderr)
            binary = Path(tmp) / "gst-vast-analytics-terminal-test"
            compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "gst_vast_analytics_terminal_test.cpp"),
                    *shlex.split(flags.stdout),
                    "-o",
                    str(binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            completed = subprocess.run(
                [str(binary), str(plugin_candidates[0])],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
                env={**os.environ, "GST_REGISTRY_FORK": "no"},
            )
            if completed.returncode == 77:
                self.skipTest(completed.stderr.strip())
            self.assertEqual(completed.returncode, 0, completed.stderr)

            queue_binary = Path(tmp) / "gst-vast-analytics-queue-test"
            queue_compiled = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-I",
                    str(ROOT / "deploy" / "native_gst_probe"),
                    str(ROOT / "tests" / "cpp" / "gst_vast_analytics_queue_test.cpp"),
                    *shlex.split(flags.stdout),
                    "-o",
                    str(queue_binary),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(queue_compiled.returncode, 0, queue_compiled.stderr)
            queue_completed = subprocess.run(
                [str(queue_binary), str(queue_plugin_candidates[0])],
                text=True,
                capture_output=True,
                check=False,
                timeout=10,
                env={**os.environ, "GST_REGISTRY_FORK": "no"},
            )
            if queue_completed.returncode == 77:
                self.skipTest(queue_completed.stderr.strip())
            self.assertEqual(queue_completed.returncode, 0, queue_completed.stderr)

    def test_blueprint_expands_to_24_baseline_and_6_shared_process_assignments(self) -> None:
        config = load_config(ROOT / "configs" / "experiments.yaml")
        datasets = load_config(ROOT / "configs" / "datasets.yaml")["datasets"]
        pair = build_primary_pair_plans(config=config, datasets=datasets, system="gstreamer_custom")

        baseline = expected_worker_assignments(pair["baseline"])
        shared = expected_worker_assignments(pair["shared"])
        self.assertEqual(len(baseline), 24)
        self.assertEqual(len(shared), 6)
        self.assertEqual({branch for _, _, branch in baseline}, set(BRANCHES))
        self.assertEqual({branch for _, _, branch in shared}, {None})

    def test_baseline_workers_use_distinct_observed_pids_and_emit_live_join(self) -> None:
        specs = [
            WorkerLaunchSpec(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                command=(
                    sys.executable,
                    str(FIXTURE),
                    "--mode",
                    "baseline",
                    "--branches",
                    ",".join(BRANCHES),
                    "--sleep-after",
                    "0.15",
                ),
            )
            for branch in BRANCHES
        ]
        result = run_worker_processes(
            run_id="run-baseline",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            specs=specs,
            timeout_s=3.0,
            synchronized_lifecycle=True,
            warmup_s=0.0,
            measurement_s=0.05,
            drain_timeout_s=0.5,
            start_lead_s=0.02,
        )

        self.assertEqual(len(set(result.process_ids.values())), 4)
        joins = [row for row in result.events if row["event_kind"] == "join_complete"]
        self.assertEqual(len(joins), 1)
        self.assertEqual(result.unresolved_frames, ())
        join_observed = result.event_observed_ns[joins[0]["execution_id"]]
        self.assertLess(join_observed, max(result.process_exit_ns.values()))
        branch_domains = {
            row["execution_domain"]
            for row in result.events
            if row["event_kind"] == "branch_complete"
        }
        self.assertEqual(len(branch_domains), 4)
        self.assertEqual(joins[0]["event_provenance"], "runtime_contract_test")
        self.assertGreater(result.common_start_monotonic_ns, 0)
        self.assertGreater(result.window_end_timestamp_ms, result.window_start_timestamp_ms)
        self.assertEqual(
            set(result.lifecycle_statuses.values()),
            {("READY", "STARTED", "ADMISSION_STOPPED", "DRAINED")},
        )
        self.assertTrue(
            all(observed >= result.common_start_monotonic_ns for observed in result.event_observed_ns.values())
        )
        audit = build_runtime_cohort_audit(
            events=result.events,
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            window_start_timestamp_ms=result.window_start_timestamp_ms,
            window_end_timestamp_ms=result.window_end_timestamp_ms,
            drain_end_timestamp_ms=result.drain_end_timestamp_ms,
        )
        self.assertEqual(audit["measurement_source_event_count"], 4)
        self.assertEqual(audit["measurement_input_key_count"], 1)
        self.assertEqual(audit["complete_source_coverage_count"], 1)
        self.assertEqual(audit["completed_join_count"], 1)
        self.assertTrue(audit["baseline_branch_input_key_sets_identical"])
        self.assertFalse(audit["external_ingress_schedule_proven"])
        self.assertFalse(audit["accepted_ingress_ledger_written"])

    def test_decoder_placement_status_closes_during_warmup_before_measurement(self) -> None:
        specs = [
            WorkerLaunchSpec(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                command=(
                    sys.executable,
                    str(FIXTURE),
                    "--mode",
                    "baseline",
                    "--branches",
                    ",".join(BRANCHES),
                ),
                environment={"VAST_TEST_DECODER_PLACEMENT_STATUS": "verified"},
            )
            for branch in BRANCHES
        ]
        result = run_worker_processes(
            run_id="run-decoder-placement",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            specs=specs,
            timeout_s=3.0,
            synchronized_lifecycle=True,
            warmup_s=0.2,
            measurement_s=0.05,
            drain_timeout_s=0.5,
            start_lead_s=0.02,
            require_decoder_placement_verification=True,
        )

        self.assertEqual(
            set(result.lifecycle_statuses.values()),
            {("READY", "STARTED", "DECODER_PLACEMENT_VERIFIED", "ADMISSION_STOPPED", "DRAINED")},
        )
        for records in result.lifecycle_records.values():
            verification = next(
                value for value in records if value.state == "DECODER_PLACEMENT_VERIFIED"
            )
            self.assertLess(verification.timestamp, result.window_start_timestamp_ms)

    def test_slow_ready_does_not_consume_synchronized_execution_budget(self) -> None:
        specs = [
            WorkerLaunchSpec(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                command=(
                    sys.executable,
                    str(FIXTURE),
                    "--mode",
                    "baseline",
                    "--branches",
                    ",".join(BRANCHES),
                    *(
                        ("--sleep-before-ready", "0.7")
                        if branch == "plate_number"
                        else ()
                    ),
                ),
            )
            for branch in BRANCHES
        ]
        result = run_worker_processes(
            run_id="run-slow-ready",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            specs=specs,
            timeout_s=1.0,
            ready_timeout_s=1.0,
            synchronized_lifecycle=True,
            warmup_s=0.0,
            measurement_s=0.4,
            drain_timeout_s=0.1,
            start_lead_s=0.02,
        )

        self.assertEqual(
            set(result.lifecycle_statuses.values()),
            {("READY", "STARTED", "ADMISSION_STOPPED", "DRAINED")},
        )

    def test_ready_timeout_lists_missing_workers(self) -> None:
        specs = [
            WorkerLaunchSpec(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                command=(
                    sys.executable,
                    str(FIXTURE),
                    "--mode",
                    "baseline",
                    "--branches",
                    ",".join(BRANCHES),
                    *(
                        ("--sleep-before-ready", "0.5")
                        if branch == "plate_number"
                        else ()
                    ),
                ),
            )
            for branch in BRANCHES
        ]
        with self.assertRaisesRegex(
            ContractError,
            "READY barrier timed out; missing workers: stream-0-branch-plate_number",
        ):
            run_worker_processes(
                run_id="run-ready-timeout",
                topology_kind=INDEPENDENT_PROCESSES,
                branches=BRANCHES,
                specs=specs,
                timeout_s=1.0,
                ready_timeout_s=0.1,
                synchronized_lifecycle=True,
                warmup_s=0.0,
                measurement_s=0.4,
                drain_timeout_s=0.1,
                start_lead_s=0.02,
            )

    def test_decoder_placement_status_is_required_before_measurement(self) -> None:
        specs = [
            WorkerLaunchSpec(
                worker_id=f"stream-0-branch-{branch}",
                stream_id=0,
                branch_id=branch,
                command=(
                    sys.executable,
                    str(FIXTURE),
                    "--mode",
                    "baseline",
                    "--branches",
                    ",".join(BRANCHES),
                ),
            )
            for branch in BRANCHES
        ]
        with self.assertRaisesRegex(ContractError, "not verified before the measurement window"):
            run_worker_processes(
                run_id="run-decoder-placement-missing",
                topology_kind=INDEPENDENT_PROCESSES,
                branches=BRANCHES,
                specs=specs,
                timeout_s=3.0,
                synchronized_lifecycle=True,
                warmup_s=0.15,
                measurement_s=0.05,
                drain_timeout_s=0.5,
                start_lead_s=0.02,
                require_decoder_placement_verification=True,
            )

    def test_common_start_selects_clock_matching_native_ready_epoch(self) -> None:
        name, now_ns = select_native_monotonic_clock(
            [568_380_300_000_000, 568_380_300_100_000],
            candidate_clocks_ns={
                "python_monotonic": 133_034_000_000_000,
                "clock_monotonic": 568_374_400_000_000,
                "clock_monotonic_raw": 568_380_300_200_000,
            },
        )

        self.assertEqual(name, "clock_monotonic_raw")
        self.assertEqual(now_ns, 568_380_300_200_000)

    def test_common_start_rejects_unknown_native_clock_epoch(self) -> None:
        with self.assertRaisesRegex(ContractError, "do not match"):
            select_native_monotonic_clock(
                [500_000_000_000_000],
                candidate_clocks_ns={"python_monotonic": 100_000_000_000_000},
            )

    def test_baseline_join_pairs_native_input_key_not_worker_local_ordinals(self) -> None:
        bindings = [
            WorkerBinding(
                worker_id=branch,
                stream_id=0,
                branch_id=branch,
                pid=300 + index,
                execution_domain=f"host:pid-{300 + index}",
                native_event_source=False,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=bindings,
            coordinator_pid=os.getpid(),
            hostname="host",
            clock_ms=lambda: 2000,
        )
        emitted: list[dict] = []
        input_frame_key = "kpp_real_h264:0:source-sha:pts-90000"
        for index, branch in enumerate(BRANCHES):
            local_trace = f"worker-{branch}:local:{40 + index}"
            local_frame = 40 + index
            source = f"{local_trace}:{branch}:source"
            decode = f"{local_trace}:{branch}:decode"
            preprocess = f"{local_trace}:{branch}:preprocess"
            analytics = f"{local_trace}:{branch}:analytics"
            complete = f"{local_trace}:{branch}:complete"
            chain = (
                ("source_read", "source", source, []),
                ("stage_complete", f"decode_{branch}", decode, [source]),
                ("stage_complete", f"preprocess_{branch}", preprocess, [decode]),
                ("stage_complete", branch, analytics, [preprocess]),
                ("branch_complete", branch, complete, [analytics]),
            )
            for sequence, (event_kind, stage, execution_id, parents) in enumerate(chain, start=1):
                emitted.extend(
                    coordinator.accept(
                        message(
                            worker_id=branch,
                            sequence=sequence,
                            event_kind=event_kind,
                            stage=stage,
                            branch_id=branch,
                            execution_id=execution_id,
                            parents=parents,
                            trace_id=local_trace,
                            frame_id=local_frame,
                            input_frame_key=input_frame_key,
                        ),
                        observed_worker_id=branch,
                        observed_pid=300 + index,
                    )
                )

        self.assertEqual({row["trace_id"] for row in emitted}, {"run-1:0:0"})
        self.assertEqual({row["frame_id"] for row in emitted}, {0})
        self.assertEqual({row["input_frame_key"] for row in emitted}, {input_frame_key})
        self.assertEqual(sum(row["event_kind"] == "join_complete" for row in emitted), 1)
        self.assertEqual(coordinator.unresolved_frames(), ())

    def test_native_predecode_ingress_drop_is_rejected_for_baseline(self) -> None:
        bindings = [
            WorkerBinding(
                worker_id=branch,
                stream_id=0,
                branch_id=branch,
                pid=700 + index,
                execution_domain=f"host:pid-{700 + index}",
                native_event_source=True,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=bindings,
        )
        branch = BRANCHES[0]
        source = f"{branch}:source"
        coordinator.accept(
            admission_message(
                worker_id=branch,
                sequence=1,
                event_kind="source_read",
                stage="source",
                branch_id=branch,
                execution_id=source,
                parents=[],
                trace_id=f"{branch}:local:0",
                input_frame_key="dataset:0:sha:0:90000",
            ),
            observed_worker_id=branch,
            observed_pid=700,
        )
        with self.assertRaisesRegex(ContractError, "baseline drop parent mismatch"):
            coordinator.accept(
                admission_message(
                    worker_id=branch,
                    sequence=2,
                    event_kind="branch_drop",
                    stage=branch,
                    branch_id=branch,
                    execution_id=f"{branch}:drop",
                    parents=[source],
                    trace_id=f"{branch}:local:0",
                    input_frame_key="dataset:0:sha:0:90000",
                    terminal_reason="unsafe_predecode_drop",
                    detector=f"native-{branch};model_sha256={'1' * 64}",
                    backend="openvino-dlstreamer:gvadetect",
                ),
                observed_worker_id=branch,
                observed_pid=700,
            )

    def test_native_predecode_ingress_drop_is_rejected_for_shared(self) -> None:
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=SHARED_VIDEO_DAG,
            branches=BRANCHES,
            bindings=[
                WorkerBinding(
                    worker_id="shared",
                    stream_id=0,
                    branch_id=None,
                    pid=800,
                    execution_domain="host:pid-800",
                    native_event_source=True,
                )
            ],
        )
        source = "shared:source"
        coordinator.accept(
            admission_message(
                worker_id="shared",
                sequence=1,
                event_kind="source_read",
                stage="source",
                branch_id="shared",
                execution_id=source,
                parents=[],
                input_frame_key="dataset:0:sha:0:90000",
            ).replace(INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG),
            observed_worker_id="shared",
            observed_pid=800,
        )
        branch = BRANCHES[0]
        with self.assertRaisesRegex(ContractError, "shared drop parent mismatch"):
            coordinator.accept(
                admission_message(
                    worker_id="shared",
                    sequence=2,
                    event_kind="branch_drop",
                    stage=branch,
                    branch_id=branch,
                    execution_id=f"{branch}:drop",
                    parents=[source],
                    input_frame_key="dataset:0:sha:0:90000",
                    terminal_reason="unsafe_predecode_drop",
                    detector=f"native-{branch};model_sha256={'1' * 64}",
                    backend="openvino-dlstreamer:gvadetect",
                ).replace(INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG),
                observed_worker_id="shared",
                observed_pid=800,
            )
    def test_native_postdecode_prefix_drop_closes_baseline_after_decode(self) -> None:
        bindings = [
            WorkerBinding(
                worker_id=branch,
                stream_id=0,
                branch_id=branch,
                pid=900 + index,
                execution_domain=f"host:pid-{900 + index}",
                native_event_source=True,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=bindings,
        )
        emitted: list[dict] = []
        for index, branch in enumerate(BRANCHES):
            source = f"{branch}:source"
            decode = f"{branch}:decode"
            for sequence, event_kind, stage, execution_id, parents in (
                (1, "source_read", "source", source, []),
                (2, "stage_complete", f"decode_{branch}", decode, [source]),
                (3, "branch_drop", branch, f"{branch}:drop", [decode]),
            ):
                emitted.extend(
                    coordinator.accept(
                        admission_message(
                            worker_id=branch,
                            sequence=sequence,
                            event_kind=event_kind,
                            stage=stage,
                            branch_id=branch,
                            execution_id=execution_id,
                            parents=parents,
                            trace_id=f"{branch}:local:0",
                            input_frame_key="dataset:0:sha:0:90000",
                            terminal_reason=(
                                "native_postdecode_preprocess_queue_full_drop_newest"
                                if event_kind == "branch_drop"
                                else None
                            ),
                            detector=(
                                f"native-{branch};model_sha256={'1' * 64}"
                                if event_kind == "branch_drop"
                                else None
                            ),
                            backend=(
                                "openvino-dlstreamer:gvadetect"
                                if event_kind == "branch_drop"
                                else None
                            ),
                        ),
                        observed_worker_id=branch,
                        observed_pid=900 + index,
                    )
                )

        self.assertEqual(coordinator.unresolved_frames(), ())
        self.assertEqual(len(coordinator.branch_terminal_records()), len(BRANCHES))
        self.assertFalse(any(row["stage"].startswith("preprocess") for row in emitted))

    def test_native_postdecode_prefix_drop_closes_every_shared_branch_after_decode(self) -> None:
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=SHARED_VIDEO_DAG,
            branches=BRANCHES,
            bindings=[
                WorkerBinding(
                    worker_id="shared",
                    stream_id=0,
                    branch_id=None,
                    pid=950,
                    execution_domain="host:pid-950",
                    native_event_source=True,
                )
            ],
        )
        source = "shared:source"
        decode = "shared:decode"
        emitted: list[dict] = []
        for sequence, event_kind, stage, branch_id, execution_id, parents in (
            (1, "source_read", "source", "shared", source, []),
            (2, "stage_complete", "decode", "shared", decode, [source]),
        ):
            emitted.extend(
                coordinator.accept(
                    admission_message(
                        worker_id="shared",
                        sequence=sequence,
                        event_kind=event_kind,
                        stage=stage,
                        branch_id=branch_id,
                        execution_id=execution_id,
                        parents=parents,
                        input_frame_key="dataset:0:sha:0:90000",
                    ).replace(INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG),
                    observed_worker_id="shared",
                    observed_pid=950,
                )
            )
        for sequence, branch in enumerate(BRANCHES, start=3):
            emitted.extend(
                coordinator.accept(
                    admission_message(
                        worker_id="shared",
                        sequence=sequence,
                        event_kind="branch_drop",
                        stage=branch,
                        branch_id=branch,
                        execution_id=f"{branch}:drop",
                        parents=[decode],
                        input_frame_key="dataset:0:sha:0:90000",
                        terminal_reason="native_postdecode_preprocess_queue_full_drop_newest",
                        detector=f"native-{branch};model_sha256={'1' * 64}",
                        backend="openvino-dlstreamer:gvadetect",
                    ).replace(INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG),
                    observed_worker_id="shared",
                    observed_pid=950,
                )
            )

        self.assertEqual(coordinator.unresolved_frames(), ())
        self.assertEqual(len(coordinator.branch_terminal_records()), len(BRANCHES))
        self.assertFalse(any(row["event_kind"] in {"fanout", "join_complete"} for row in emitted))

    def test_terminal_cohort_uses_half_open_schedule_offsets_not_wall_clock_jitter(self) -> None:
        def admission(sequence: int, schedule_offset_ns: int) -> dict[str, object]:
            return {
                "run_id": "schedule-window-run",
                "admission_id": f"schedule-window-run:0:admission:{sequence}",
                "input_frame_key": f"dataset:0:{'1' * 64}:0:{sequence}",
                "stream_id": 0,
                "sequence": sequence,
                "source_sha256": "1" * 64,
                "source_cycle": 0,
                "access_unit_pts_ns": sequence,
                "payload_sha256": hashlib.sha256(str(sequence).encode()).hexdigest(),
                "payload_size_bytes": 10 + sequence,
                "schedule_offset_ns": schedule_offset_ns,
                "admission_timestamp_ms": 1_001 + sequence,
                "consumer_coverage_complete": True,
            }

        admissions = [
            admission(1, 4_999_999_800),
            admission(2, 6_000_000_000),
            admission(3, 15_000_000_000),
        ]
        terminal = [
            {
                "admission_id": "schedule-window-run:0:admission:2",
                "terminal_status": "completed",
                "terminal_timestamp_ms": 1_100,
                "terminal_reason": "all_required_branches_joined",
                "terminal_telemetry_source": "native",
                "trace_id": "schedule-window-run:0:1",
                "frame_id": 1,
            }
        ]
        ledger, audit = build_runtime_terminal_ingress_ledger(
            admission_records=admissions,
            terminal_frame_records=terminal,
            lifecycle_statuses={"worker": ("READY", "STARTED", "ADMISSION_STOPPED", "DRAINED")},
            measurement_start_schedule_offset_ns=5_000_000_000,
            measurement_end_schedule_offset_ns=15_000_000_000,
            window_start_timestamp_ms=1_000,
            window_end_timestamp_ms=2_000,
            drain_end_timestamp_ms=3_000,
        )
        self.assertEqual([row["admission_seq"] for row in ledger], [2])
        self.assertEqual(audit["pre_window_admission_count"], 1)
        self.assertEqual(audit["post_window_admission_count"], 1)
        self.assertEqual(audit["cohort_selection_basis"], "decode_order_schedule_offset_half_open")
        self.assertTrue(audit["engineering_terminal_accounting_complete"])
        paired = dict(audit)
        paired["admission_count"] = 2
        paired["post_window_admission_count"] = 0
        self.assertEqual(
            require_matching_measurement_schedule_fingerprints(audit, paired),
            audit["measurement_schedule_fingerprint_sha256"],
        )
    def test_explicit_native_branch_drop_resolves_frame_without_creating_join(self) -> None:
        bindings = [
            WorkerBinding(
                worker_id=branch,
                stream_id=0,
                branch_id=branch,
                pid=500 + index,
                execution_domain=f"host:pid-{500 + index}",
                native_event_source=True,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=bindings,
            coordinator_pid=os.getpid(),
            hostname="host",
            clock_ms=lambda: 2000,
        )
        emitted: list[dict] = []
        for index, branch in enumerate(BRANCHES):
            source = f"{branch}:source"
            decode = f"{branch}:decode"
            preprocess = f"{branch}:preprocess"
            chain = [
                ("source_read", "source", source, [], None, 0),
                ("stage_complete", f"decode_{branch}", decode, [source], None, 0),
                ("stage_complete", f"preprocess_{branch}", preprocess, [decode], None, 0),
            ]
            if branch == "damage":
                chain.append(
                    ("branch_drop", branch, f"{branch}:drop", [preprocess], "native_analytics_queue_drop", 0)
                )
            else:
                analytics = f"{branch}:analytics"
                chain.extend(
                    [
                        ("stage_complete", branch, analytics, [preprocess], None, 0),
                        (
                            "branch_complete",
                            branch,
                            f"{branch}:complete",
                            [analytics],
                            "native_result_committed",
                            index + 1,
                        ),
                    ]
                )
            for sequence, (event_kind, stage, execution_id, parents, reason, objects) in enumerate(chain, start=1):
                emitted.extend(
                    coordinator.accept(
                        admission_message(
                            worker_id=branch,
                            sequence=sequence,
                            event_kind=event_kind,
                            stage=stage,
                            branch_id=branch,
                            execution_id=execution_id,
                            parents=parents,
                            trace_id=f"{branch}:local:0",
                            input_frame_key="dataset:0:sha:0:90000",
                            terminal_reason=reason,
                            objects=objects,
                            detector=f"native-{branch}-v1",
                        ),
                        observed_worker_id=branch,
                        observed_pid=500 + index,
                    )
                )

        self.assertFalse(any(row["event_kind"] == "join_complete" for row in emitted))
        self.assertEqual(coordinator.unresolved_frames(), ())
        terminal = coordinator.terminal_frame_records()
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["terminal_status"], "drop")
        self.assertEqual(terminal[0]["terminal_reason"], "native_analytics_queue_drop")
        self.assertEqual(terminal[0]["terminal_event_provenance"], "native_drop_event")
        self.assertEqual(terminal[0]["terminal_telemetry_source"], "native")
        branch_terminals = coordinator.branch_terminal_records()
        self.assertEqual(len(branch_terminals), 4)
        self.assertTrue(all(row["runtime_protocol_version"] == 3 for row in branch_terminals))
        damage_terminal = next(row for row in branch_terminals if row["branch_id"] == "damage")
        self.assertEqual(damage_terminal["terminal_status"], "drop")
        self.assertEqual(damage_terminal["objects"], 0)
        self.assertEqual(damage_terminal["detector"], "native-damage-v1")
        ledger, audit = build_runtime_terminal_ingress_ledger(
            admission_records=[
                {
                    "run_id": "run-1",
                    "admission_id": "run-1:0:admission:1",
                    "input_frame_key": "dataset:0:sha:0:90000",
                    "stream_id": 0,
                    "sequence": 1,
                    "source_sha256": "1" * 64,
                    "source_cycle": 0,
                    "access_unit_pts_ns": 90_000,
                    "payload_sha256": "2" * 64,
                    "payload_size_bytes": 4096,
                    "schedule_offset_ns": 1_000_000,
                    "admission_timestamp_ms": 900,
                    "consumer_coverage_complete": True,
                }
            ],
            terminal_frame_records=terminal,
            lifecycle_statuses={branch: ("READY", "STARTED", "ADMISSION_STOPPED", "DRAINED") for branch in BRANCHES},
            measurement_start_schedule_offset_ns=0,
            measurement_end_schedule_offset_ns=2_000_000,
            window_start_timestamp_ms=800,
            window_end_timestamp_ms=1500,
            drain_end_timestamp_ms=2500,
        )
        self.assertEqual(ledger[0]["terminal_status"], "drop")
        self.assertEqual(ledger[0]["terminal_provenance"], "native_drop_event")
        self.assertEqual(audit["drop_count"], 1)
        self.assertTrue(audit["native_drop_event_coverage_complete"])
        self.assertFalse(audit["terminal_ingress_ledger_complete"])

    def test_shared_worker_emits_one_prefix_four_fanouts_and_live_join(self) -> None:
        result = run_worker_processes(
            run_id="run-shared",
            topology_kind=SHARED_VIDEO_DAG,
            branches=BRANCHES,
            specs=[
                WorkerLaunchSpec(
                    worker_id="stream-0-shared-video-dag",
                    stream_id=0,
                    branch_id=None,
                    command=(
                        sys.executable,
                        str(FIXTURE),
                        "--mode",
                        "shared",
                        "--branches",
                        ",".join(BRANCHES),
                        "--sleep-after",
                        "0.1",
                    ),
                )
            ],
        )

        self.assertEqual(sum(row["stage"] == "decode" for row in result.events), 1)
        self.assertEqual(sum(row["stage"] == "preprocess" for row in result.events), 1)
        self.assertEqual(sum(row["event_kind"] == "fanout" for row in result.events), 4)
        self.assertEqual(sum(row["event_kind"] == "join_complete" for row in result.events), 1)
        self.assertEqual(result.unresolved_frames, ())

    def test_incomplete_shared_branch_remains_unresolved_and_cannot_create_join(self) -> None:
        result = run_worker_processes(
            run_id="run-incomplete",
            topology_kind=SHARED_VIDEO_DAG,
            branches=BRANCHES,
            specs=[
                WorkerLaunchSpec(
                    worker_id="stream-0-shared-video-dag",
                    stream_id=0,
                    branch_id=None,
                    command=(
                        sys.executable,
                        str(FIXTURE),
                        "--mode",
                        "shared",
                        "--branches",
                        ",".join(BRANCHES),
                        "--omit-branch",
                        "damage",
                    ),
                )
            ],
        )

        self.assertFalse(any(row["event_kind"] == "join_complete" for row in result.events))
        self.assertEqual(result.unresolved_frames, (("run-incomplete:0:0", 0, 0),))

    def test_worker_cannot_claim_join_or_skip_sequence(self) -> None:
        bad_join = message(
            worker_id="plate",
            sequence=1,
            event_kind="join_complete",
            stage="join",
            branch_id="shared",
            execution_id="join",
            parents=["complete"],
        )
        with self.assertRaisesRegex(ContractError, "may not emit"):
            RuntimeMessage.parse(bad_join)

        bindings = [
            WorkerBinding(
                worker_id=branch,
                stream_id=0,
                branch_id=branch,
                pid=100 + index,
                execution_domain=f"host:pid-{100 + index}",
                native_event_source=False,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=bindings,
            coordinator_pid=os.getpid(),
            hostname="host",
            clock_ms=lambda: 2000,
        )
        source = message(
            worker_id="plate_number",
            sequence=2,
            event_kind="source_read",
            stage="source",
            branch_id="plate_number",
            execution_id="source",
            parents=[],
        )
        with self.assertRaisesRegex(ContractError, "sequence is not gap-free"):
            coordinator.accept(source, observed_worker_id="plate_number", observed_pid=100)

    def test_parent_must_arrive_on_direct_pipe_before_child(self) -> None:
        bindings = [
            WorkerBinding(
                worker_id=branch,
                stream_id=0,
                branch_id=branch,
                pid=200 + index,
                execution_domain=f"host:pid-{200 + index}",
                native_event_source=False,
            )
            for index, branch in enumerate(BRANCHES)
        ]
        coordinator = DirectRuntimeJoinCoordinator(
            run_id="run-1",
            topology_kind=INDEPENDENT_PROCESSES,
            branches=BRANCHES,
            bindings=bindings,
        )
        source = message(
            worker_id="plate_number",
            sequence=1,
            event_kind="source_read",
            stage="source",
            branch_id="plate_number",
            execution_id="source",
            parents=[],
        )
        coordinator.accept(source, observed_worker_id="plate_number", observed_pid=200)
        preprocess = message(
            worker_id="plate_number",
            sequence=2,
            event_kind="stage_complete",
            stage="preprocess_plate_number",
            branch_id="plate_number",
            execution_id="preprocess",
            parents=["decode-not-seen"],
        )
        with self.assertRaisesRegex(ContractError, "parent has not been observed directly"):
            coordinator.accept(preprocess, observed_worker_id="plate_number", observed_pid=200)


if __name__ == "__main__":
    unittest.main()
