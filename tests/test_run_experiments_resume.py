from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import (  # noqa: E402
    ContractError,
    PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS,
    PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
    PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
    build_publication_evidence_bundle,
    load_dataset,
    publication_evidence_bundle_identity,
    publication_run_contract_identity,
    publication_evidence_bundle_files,
    primary_architecture_pair_metadata,
    primary_policy_pair_metadata,
    resolve_publication_run_contract,
    resolve_scenario_contract,
    scenario_contract_identity,
)
from run_experiments import load_resumable_result, run_directory, summary_fieldnames  # noqa: E402


class RunExperimentsResumeTests(unittest.TestCase):
    def test_run_directory_matches_canonical_layout(self) -> None:
        scenario = {"name": "checkpoint_video_dag_shared", "workload": {}}

        self.assertEqual(
            run_directory(Path("runs/root"), scenario, 6, "openvino_gva", 5),
            Path("runs/root/checkpoint_video_dag_shared/streams_6/openvino_gva/rep_05"),
        )
        self.assertEqual(
            run_directory(Path("runs/root"), scenario, 6, "openvino_gva", 5, 16.7),
            Path("runs/root/checkpoint_video_dag_shared/streams_6/deadline_16p7/openvino_gva/rep_05"),
        )

    def test_load_resumable_result_accepts_matching_completed_metadata(self) -> None:
        result = {field: "" for field in summary_fieldnames()}
        result.update({
            "timestamp": "2026-07-23T00:00:00+00:00",
            "status": "completed",
            "run_mode": "benchmark",
            "system": "openvino_gva",
            "scenario": "checkpoint_video_dag_shared",
            "repeat": 5,
            "streams": 6,
            "duration_s": 180,
            "policy": "cpu_only",
            "dataset": "kpp_real_avi",
            "deadline_ms": 16.7,
            "telemetry_source": "native",
        })
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(
                json.dumps({"schema_version": 2, "mode": "benchmark", "result": result}),
                encoding="utf-8",
            )

            self.assertEqual(
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="checkpoint_video_dag_shared",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="kpp_real_avi",
                    mode="benchmark",
                    deadline_ms=16.7,
                ),
                result,
            )

    def test_load_resumable_result_rejects_pair_metadata_outside_benchmark(self) -> None:
        result = {field: "" for field in summary_fieldnames()}
        result.update(
            {
                "timestamp": "2026-08-09T00:00:00+00:00",
                "status": "completed",
                "run_mode": "smoke",
                "system": "openvino_gva",
                "scenario": "checkpoint_video_dag_shared",
                "repeat": 1,
                "streams": 1,
                "duration_s": 5,
                "policy": "cpu_only",
                "dataset": "smoke_testsrc",
                "deadline_ms": 100.0,
                "telemetry_source": "smoke_synthetic",
            }
        )
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "mode": "smoke",
                        "primary_architecture_pair": {"contract_version": 1},
                        "result": result,
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ContractError,
                "primary pair metadata is valid only in benchmark mode",
            ):
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="checkpoint_video_dag_shared",
                    repeat_index=1,
                    streams=1,
                    duration_s=5,
                    policy="cpu_only",
                    dataset_name="smoke_testsrc",
                    mode="smoke",
                    deadline_ms=100.0,
                )

    def test_load_resumable_result_rejects_stale_summary_schema(self) -> None:
        result = {field: "" for field in summary_fieldnames()}
        result.update({
            "timestamp": "2026-07-23T00:00:00+00:00",
            "status": "completed",
            "run_mode": "benchmark",
            "system": "openvino_gva",
            "scenario": "checkpoint_video_dag_shared",
            "repeat": 5,
            "streams": 6,
            "duration_s": 180,
            "policy": "cpu_only",
            "dataset": "kpp_real_avi",
            "deadline_ms": 16.7,
            "telemetry_source": "native",
        })
        del result["measurement_signature"]
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(
                json.dumps({"schema_version": 2, "mode": "benchmark", "result": result}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ContractError,
                "incompatible summary schema.*benchmark completed row 1 is missing proof fields: measurement_signature",
            ):
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="checkpoint_video_dag_shared",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="kpp_real_avi",
                    mode="benchmark",
                    deadline_ms=16.7,
                )

    def test_load_resumable_result_rejects_incompatible_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(
                json.dumps(
                    {
                        "mode": "benchmark",
                        "result": {
                            "status": "completed",
                            "run_mode": "benchmark",
                            "system": "openvino_gva",
                            "scenario": "checkpoint_video_dag_shared",
                            "repeat": 1,
                            "streams": 6,
                            "duration_s": 180,
                            "policy": "gpu_only",
                            "dataset": "kpp_real_avi",
                        }
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ContractError, "does not match requested run.*repeat.*policy"):
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="checkpoint_video_dag_shared",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="kpp_real_avi",
                    mode="benchmark",
                )

    def test_load_resumable_result_rejects_top_level_mode_drift(self) -> None:
        result = {field: "" for field in summary_fieldnames()}
        result.update({
            "timestamp": "2026-07-23T00:00:00+00:00",
            "status": "completed",
            "run_mode": "benchmark",
            "system": "openvino_gva",
            "scenario": "checkpoint_video_dag_shared",
            "repeat": 5,
            "streams": 6,
            "duration_s": 180,
            "policy": "cpu_only",
            "dataset": "kpp_real_avi",
            "deadline_ms": 16.7,
            "telemetry_source": "native",
        })
        with tempfile.TemporaryDirectory() as tmp:
            metadata_path = Path(tmp) / "run_metadata.json"
            metadata_path.write_text(
                json.dumps({"schema_version": 2, "mode": "smoke", "result": result}),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ContractError,
                "metadata mode does not match requested run.*requested=benchmark.*metadata=smoke",
            ):
                load_resumable_result(
                    metadata_path,
                    system_key="openvino_gva",
                    scenario_key="checkpoint_video_dag_shared",
                    repeat_index=5,
                    streams=6,
                    duration_s=180,
                    policy="cpu_only",
                    dataset_name="kpp_real_avi",
                    mode="benchmark",
                    deadline_ms=16.7,
                )

    def test_load_resumable_result_rejects_scenario_or_dataset_contract_drift(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open(
            "r", encoding="utf-8"
        ) as handle:
            config = yaml.safe_load(handle)
        scenario = resolve_scenario_contract(
            "checkpoint_video_dag_shared",
            config["scenarios"]["checkpoint_video_dag_shared"],
        )
        scenario_identity = scenario_contract_identity(scenario)
        dataset = load_dataset(
            ROOT / "configs" / "datasets.yaml",
            "kpp_real_h264",
            mode="benchmark",
            project_root=ROOT,
            require_files=False,
        )
        result = {field: "" for field in summary_fieldnames()}
        result.update(
            {
                "timestamp": "2026-08-09T00:00:00+00:00",
                "status": "completed",
                "run_mode": "benchmark",
                "system": "gstreamer_custom",
                "scenario": "checkpoint_video_dag_shared",
                "repeat": 1,
                "streams": 6,
                "duration_s": 180,
                "policy": "static_hybrid",
                "dataset": "kpp_real_h264",
                "deadline_ms": 100.0,
                "seed": 20260323,
                "run_seed": 1001,
                "telemetry_source": "native",
            }
        )
        publication_run_contract = resolve_publication_run_contract(config, result)
        publication_run_identity = publication_run_contract_identity(
            publication_run_contract
        )
        metadata = {
            "schema_version": 2,
            "mode": "benchmark",
            "result": result,
            "resolved_scenario": json.loads(json.dumps(scenario)),
            "scenario_contract_identity": {
                "schema_version": scenario_identity["schema_version"],
                "sha256": scenario_identity["sha256"],
            },
            "dataset": json.loads(json.dumps(dataset)),
            "publication_run_contract": publication_run_contract,
            "publication_run_contract_identity": {
                "schema_version": publication_run_identity["schema_version"],
                "sha256": publication_run_identity["sha256"],
            },
        }

        def resume(
            metadata_path: Path,
            *,
            policy_name: str = "static_hybrid",
            architecture_pair: dict | None = None,
            policy_pair: dict | None = None,
        ):
            return load_resumable_result(
                metadata_path,
                system_key="gstreamer_custom",
                scenario_key="checkpoint_video_dag_shared",
                repeat_index=1,
                streams=6,
                duration_s=180,
                policy=policy_name,
                dataset_name="kpp_real_h264",
                mode="benchmark",
                deadline_ms=100.0,
                scenario_contract=scenario,
                dataset_contract=dataset,
                config=config,
                base_seed=20260323,
                run_seed=1001,
                primary_architecture_pair=architecture_pair,
                primary_policy_pair=policy_pair,
            )

        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp)
            for relative_name in sorted(PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS):
                (run_dir / relative_name).write_bytes(
                    (relative_name + "\n").encode("utf-8")
                )
            evidence_bundle = build_publication_evidence_bundle(
                run_dir,
                scope=PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
            )
            evidence_identity = publication_evidence_bundle_identity(evidence_bundle)
            metadata["publication_evidence_bundle"] = evidence_bundle
            metadata["publication_evidence_bundle_identity"] = {
                "schema_version": evidence_identity["schema_version"],
                "sha256": evidence_identity["sha256"],
            }
            metadata_path = run_dir / "run_metadata.json"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(resume(metadata_path), result)

            architecture_pair = primary_architecture_pair_metadata(
                config,
                repeat=1,
                scenario="checkpoint_video_dag_shared",
            )
            metadata["primary_architecture_pair"] = architecture_pair
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "unexpected primary architecture pair contract",
            ):
                resume(metadata_path)
            self.assertEqual(
                resume(metadata_path, architecture_pair=architecture_pair),
                result,
            )
            drifted_architecture_pair = dict(architecture_pair)
            drifted_architecture_pair["arm_position"] = 1
            metadata["primary_architecture_pair"] = drifted_architecture_pair
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "primary architecture pair metadata drift",
            ):
                resume(metadata_path, architecture_pair=architecture_pair)
            metadata.pop("primary_architecture_pair")
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "primary architecture pair metadata drift",
            ):
                resume(metadata_path, architecture_pair=architecture_pair)

            stage_contracts_path = run_dir / "stage_contracts.csv"
            original_stage_contracts = stage_contracts_path.read_bytes()
            stage_contracts_path.write_bytes(original_stage_contracts + b"tampered")
            with self.assertRaisesRegex(
                ContractError,
                "publication evidence bundle drift",
            ):
                resume(metadata_path)
            stage_contracts_path.write_bytes(original_stage_contracts)

            metadata["resolved_scenario"]["pipeline"].reverse()
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "scenario contract drift.*resolved_scenario_sha256",
            ):
                resume(metadata_path)
            metadata["resolved_scenario"] = json.loads(json.dumps(scenario))

            metadata["dataset"]["streams"][0]["camera_role"] = "foreign_object"
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "dataset contract drift.*dataset_manifest_sha256",
            ):
                resume(metadata_path)
            metadata["dataset"] = json.loads(json.dumps(dataset))

            metadata["publication_run_contract"]["protocol"]["warmup_s"] = 31
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "publication run contract drift.*publication_run_contract_sha256",
            ):
                resume(metadata_path)

            result["policy"] = "ql_heft_online"
            metadata["policy"] = "ql_heft_online"
            metadata["publication_run_contract"] = resolve_publication_run_contract(
                config,
                result,
            )
            online_run_identity = publication_run_contract_identity(
                metadata["publication_run_contract"]
            )
            metadata["publication_run_contract_identity"] = {
                "schema_version": online_run_identity["schema_version"],
                "sha256": online_run_identity["sha256"],
            }
            for relative_name in publication_evidence_bundle_files(
                PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE
            ):
                path = run_dir / relative_name
                if not path.exists():
                    path.write_bytes((relative_name + "\n").encode("utf-8"))
            online_bundle = build_publication_evidence_bundle(
                run_dir,
                scope=PUBLICATION_EVIDENCE_BUNDLE_POLICY_ONLINE_SCOPE,
            )
            online_bundle_identity = publication_evidence_bundle_identity(
                online_bundle
            )
            metadata["publication_evidence_bundle"] = online_bundle
            metadata["publication_evidence_bundle_identity"] = {
                "schema_version": online_bundle_identity["schema_version"],
                "sha256": online_bundle_identity["sha256"],
            }
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            self.assertEqual(
                resume(metadata_path, policy_name="ql_heft_online"),
                result,
            )

            policy_pair = primary_policy_pair_metadata(
                config,
                repeat=1,
                policy="ql_heft_online",
            )
            metadata["primary_policy_pair"] = policy_pair
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "unexpected primary policy pair contract",
            ):
                resume(metadata_path, policy_name="ql_heft_online")
            self.assertEqual(
                resume(
                    metadata_path,
                    policy_name="ql_heft_online",
                    policy_pair=policy_pair,
                ),
                result,
            )
            drifted_policy_pair = dict(policy_pair)
            drifted_policy_pair["arm_position"] = 1
            metadata["primary_policy_pair"] = drifted_policy_pair
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            with self.assertRaisesRegex(
                ContractError,
                "primary policy pair metadata drift",
            ):
                resume(
                    metadata_path,
                    policy_name="ql_heft_online",
                    policy_pair=policy_pair,
                )
            metadata.pop("primary_policy_pair")
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            feedback_path = run_dir / "policy_feedback.csv"
            original_feedback = feedback_path.read_bytes()
            feedback_path.write_bytes(original_feedback + b"tampered")
            with self.assertRaisesRegex(
                ContractError,
                "publication evidence bundle drift",
            ):
                resume(metadata_path, policy_name="ql_heft_online")


if __name__ == "__main__":
    unittest.main()
