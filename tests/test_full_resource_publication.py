from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import (  # noqa: E402
    FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
    FULL_RESOURCE_PUBLICATION_SCOPE,
    PUBLICATION_EVIDENCE_BUNDLE_SCOPE,
    PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS,
    build_publication_evidence_bundle,
    publication_evidence_bundle_files,
    publication_evidence_bundle_identity,
    resolve_publication_evidence_bundle_scope,
    validate_publication_evidence_bundle,
)


def resource_capability_grant() -> dict:
    material = {
        "schema_version": 1,
        "artifact_kind": "vast_verified_pre_run_resource_capability_grant",
        "status": "accepted_pre_run_resource_capability_qualification",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "identity_artifact_binding_sha256": "a" * 64,
        "qualification_receipt": {
            "path": "artifacts/checkpoint_full_resource_qualification_receipt.json",
            "size_bytes": 101,
            "sha256": "b" * 64,
        },
        "capability_manifest": {
            "path": "artifacts/checkpoint_full_resource_capability_manifest.json",
            "size_bytes": 202,
            "sha256": "c" * 64,
        },
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    material["grant_sha256"] = hashlib.sha256(
        json.dumps(
            material,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return material


def identity_artifacts_for_grant(*, schema_version: int = 2) -> dict:
    receipt = {
        "path": "artifacts/checkpoint_full_resource_qualification_receipt.json",
        "size_bytes": 101,
        "sha256": "b" * 64,
    }
    capability = {
        "path": "artifacts/checkpoint_full_resource_capability_manifest.json",
        "size_bytes": 202,
        "sha256": "c" * 64,
    }
    files = [capability, receipt]
    value = {
        "schema_version": schema_version,
        "artifact_kind": "vast_full_publication_identity_artifact_binding",
        "manifest": {
            "path": "configs/full_publication_identity_artifacts.yaml",
            "size_bytes": 303,
            "sha256": "d" * 64,
        },
        "bindings": {
            "analytics_model_parity": {},
            "analytics_execution_layer": {},
            "policy_qualification": {},
            "resource_qualification": {
                "receipt": receipt,
                "outputs": {"capability_manifest": capability},
            },
            "backend_runtime_qualification": {},
        },
        "files": files,
        "files_sha256": hashlib.sha256(
            json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest(),
    }
    value["binding_sha256"] = hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    return value


class FullResourcePublicationTests(unittest.TestCase):
    def test_grant_is_derived_only_from_exact_validated_identity_binding(self) -> None:
        from benchmark_contract import resource_capability_grant_from_identity_artifacts

        identity = identity_artifacts_for_grant()
        grant = resource_capability_grant_from_identity_artifacts(identity)

        self.assertEqual(
            grant["identity_artifact_binding_sha256"], identity["binding_sha256"]
        )
        self.assertEqual(
            grant["qualification_receipt"],
            identity["bindings"]["resource_qualification"]["receipt"],
        )
        self.assertTrue(grant["post_run_per_arm_evidence_required"])
        self.assertFalse(grant["configuration_evidence_accepted_mutated"])

        identity["bindings"]["resource_qualification"]["receipt"]["sha256"] = "e" * 64
        with self.assertRaisesRegex(Exception, "self-hash drift"):
            resource_capability_grant_from_identity_artifacts(identity)

    def test_grant_rejects_legacy_identity_binding_schema_v1(self) -> None:
        from benchmark_contract import resource_capability_grant_from_identity_artifacts

        identity = identity_artifacts_for_grant(schema_version=1)
        with self.assertRaisesRegex(
            Exception, "validated full publication identity binding is invalid"
        ):
            resource_capability_grant_from_identity_artifacts(identity)

    def test_run_contract_binds_grant_and_resume_identity_will_detect_drift(self) -> None:
        from benchmark_contract import (
            publication_run_contract_identity,
            resolve_publication_run_contract,
        )

        with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
            config = copy.deepcopy(yaml.safe_load(source))
        result = {
            "system": "deepstream",
            "scenario": "checkpoint_video_dag_shared",
            "policy": "adaptive_weights",
        }
        grant = resource_capability_grant()
        contract = resolve_publication_run_contract(
            config, result, resource_capability_grant=grant
        )
        before = publication_run_contract_identity(contract)
        drifted = copy.deepcopy(grant)
        drifted["capability_manifest"]["sha256"] = "f" * 64
        drifted["grant_sha256"] = hashlib.sha256(
            json.dumps(
                {key: value for key, value in drifted.items() if key != "grant_sha256"},
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        after = publication_run_contract_identity(
            resolve_publication_run_contract(
                config, result, resource_capability_grant=drifted
            )
        )

        self.assertEqual(contract["pre_run_resource_capability_grant"], grant)
        self.assertNotEqual(before["sha256"], after["sha256"])

    def test_backend_run_contract_requires_current_crossbound_parity_grant(self) -> None:
        from benchmark_contract import ContractError, resolve_publication_run_contract
        from tests.test_checkpoint_acceptance_metadata_binding import (
            execution,
            metadata,
        )

        with tempfile.TemporaryDirectory() as tmp:
            stored = metadata(execution(), Path(tmp))[
                "publication_run_contract"
            ]
        resource_grant = stored["pre_run_resource_capability_grant"]
        backend_grant = stored["pre_run_backend_runtime_grant"]
        parity_grant = stored["pre_run_model_parity_grant"]
        config = {
            "systems": {"deepstream": {}},
            "benchmark": {},
            "protocol": {},
            "transport": {},
            "hardware_target": {},
        }
        result = {"system": "deepstream"}

        resolved = resolve_publication_run_contract(
            config,
            result,
            resource_capability_grant=resource_grant,
            backend_runtime_grant=backend_grant,
            model_parity_grant=parity_grant,
        )
        self.assertEqual(
            resolved["pre_run_model_parity_grant"], parity_grant
        )
        with self.assertRaisesRegex(
            ContractError, "requires resource, backend, and model-parity"
        ):
            resolve_publication_run_contract(
                config,
                result,
                resource_capability_grant=resource_grant,
                backend_runtime_grant=backend_grant,
            )

        replayed = copy.deepcopy(parity_grant)
        replayed["parity_acceptance_binding_sha256"] = "f" * 64
        authorization_fields = (
            "identity_artifact_binding_sha256",
            "parity_acceptance_binding_sha256",
            "acceptance_receipt",
            "accepted_manifest",
            "accepted_assessment",
            "acceptance_identity_sha256",
            "accepted_manifest_content_identity_sha256",
            "canonical_assessment_identity_sha256",
            "evidence_count",
            "evidence_sha256",
            "runtime_registries_sha256",
            "runtime_images_sha256",
        )
        replayed["authorization_material_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: replayed[key]
                    for key in authorization_fields
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        replayed["grant_sha256"] = hashlib.sha256(
            json.dumps(
                {
                    key: value
                    for key, value in replayed.items()
                    if key != "grant_sha256"
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(
            ContractError, "cross-binding drifted"
        ):
            resolve_publication_run_contract(
                config,
                result,
                resource_capability_grant=resource_grant,
                backend_runtime_grant=backend_grant,
                model_parity_grant=replayed,
            )

    def test_config_self_declared_post_run_acceptance_cannot_select_full_scope(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
            config = copy.deepcopy(yaml.safe_load(source))
        extension = config["benchmark"]["resource_interval_extension"]
        extension["status"] = "accepted_full_resource_publication_v2"
        extension["current_publication_bundle_scope"] = FULL_RESOURCE_PUBLICATION_SCOPE
        extension["publication_bundle_bound"] = True
        extension["evidence_accepted"] = True

        scope = resolve_publication_evidence_bundle_scope(
            config,
            {
                "system": "deepstream",
                "scenario": "checkpoint_video_dag_shared",
                "policy": "adaptive_weights",
            },
        )
        self.assertEqual(scope, PUBLICATION_EVIDENCE_BUNDLE_SCOPE)

    def test_verified_pre_run_grant_selects_full_scope_while_config_evidence_is_false(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
            config = copy.deepcopy(yaml.safe_load(source))

        scope = resolve_publication_evidence_bundle_scope(
            config,
            {
                "system": "deepstream",
                "scenario": "checkpoint_video_dag_shared",
                "policy": "adaptive_weights",
            },
            resource_capability_grant=resource_capability_grant(),
        )

        self.assertFalse(config["benchmark"]["resource_interval_extension"]["evidence_accepted"])
        self.assertEqual(scope, FULL_RESOURCE_PUBLICATION_SCOPE)

    def test_v2_scope_extends_v1_with_exact_resource_evidence(self) -> None:
        expected_resource_files = {
            "resource_intervals.csv",
            "hardware_resource_samples.csv",
            "fanout_work_counters.csv",
        }
        self.assertEqual(
            FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
            PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS
            | expected_resource_files
            | {"publication_policy_decisions.jsonl"},
        )
        self.assertEqual(
            set(publication_evidence_bundle_files(
                FULL_RESOURCE_PUBLICATION_SCOPE,
                policy="cpu_only",
            )),
            FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
        )

    def test_v2_bundle_identity_binds_every_resource_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES:
                (root / name).write_text(f"{name}\n", encoding="utf-8")
            bundle = build_publication_evidence_bundle(
                root,
                scope=FULL_RESOURCE_PUBLICATION_SCOPE,
                policy="cpu_only",
            )
            identity = publication_evidence_bundle_identity(bundle)

            self.assertEqual(bundle["scope"], FULL_RESOURCE_PUBLICATION_SCOPE)
            self.assertEqual(bundle["policy"], "cpu_only")
            self.assertEqual(
                {entry["relative_path"] for entry in bundle["files"]},
                FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
            )
            self.assertRegex(identity["sha256"], r"^[0-9a-f]{64}$")

    def test_adaptive_v2_bundle_rejects_missing_and_tampered_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = publication_evidence_bundle_files(
                FULL_RESOURCE_PUBLICATION_SCOPE,
                policy="adaptive_weights",
            )
            for name in files:
                (root / name).write_text(f"{name}\n", encoding="utf-8")
            bundle = build_publication_evidence_bundle(
                root,
                scope=FULL_RESOURCE_PUBLICATION_SCOPE,
                policy="adaptive_weights",
            )
            identity = publication_evidence_bundle_identity(bundle)
            feedback = root / "publication_policy_feedback.jsonl"
            original_feedback = feedback.read_bytes()
            feedback.unlink()
            with self.assertRaisesRegex(Exception, "is missing"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    identity,
                    expected_scope=FULL_RESOURCE_PUBLICATION_SCOPE,
                    expected_policy="adaptive_weights",
                )
            feedback.write_bytes(original_feedback)
            decisions = root / "publication_policy_decisions.jsonl"
            decisions.write_bytes(decisions.read_bytes() + b"tamper")
            with self.assertRaisesRegex(Exception, "does not match current"):
                validate_publication_evidence_bundle(
                    root,
                    bundle,
                    identity,
                    expected_scope=FULL_RESOURCE_PUBLICATION_SCOPE,
                    expected_policy="adaptive_weights",
                )


if __name__ == "__main__":
    unittest.main()
