from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_runtime_grant import backend_runtime_grant_from_identity_artifacts
from backend_publication_dispatch import runtime_binding_identity
from model_parity_grant import model_parity_grant_from_identity_artifacts
from checkpoint_acceptance_metadata_binding import (
    AcceptanceMetadataBindingError,
    bind_checkpoint_acceptance_to_durable_metadata,
    validate_checkpoint_acceptance_metadata_binding,
    validate_checkpoint_acceptance_metadata_binding_envelope,
)
from tests.test_backend_runtime_grant import v2_identity
from tests.test_backend_publication_output_receipt import materialize
from tests.test_model_parity_grant import identity as model_parity_identity

FULL_RESOURCE_PUBLICATION_SCOPE = (
    "primary_architecture_full_resource_raw_evidence_v2"
)


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode()).hexdigest()


def execution(arm_id: str = "arm-1") -> dict:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_arm_execution_binding",
        "run_identity_sha256": "1" * 64,
        "sequence": 7,
        "pair_id": "pair-7",
        "attempt": 2,
        "arm_id": arm_id,
    }


def resource(identity: str) -> dict:
    value = {
        "schema_version": 1,
        "artifact_kind": "vast_verified_pre_run_resource_capability_grant",
        "status": "accepted_pre_run_resource_capability_qualification",
        "publication_scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "identity_artifact_binding_sha256": identity,
        "qualification_receipt": {"path": "accepted/r.json", "size_bytes": 1, "sha256": "2" * 64},
        "capability_manifest": {"path": "accepted/c.json", "size_bytes": 1, "sha256": "3" * 64},
        "post_run_per_arm_evidence_required": True,
        "configuration_evidence_accepted_mutated": False,
    }
    value["grant_sha256"] = sha(value)
    return value


def metadata(
    binding: dict,
    output_dir: Path | None = None,
    *,
    parity_acceptance_identity_sha256: str | None = None,
) -> dict:
    identity = model_parity_identity()
    if parity_acceptance_identity_sha256 is not None:
        parity_binding = identity["bindings"]["analytics_model_parity"]
        parity_binding["acceptance_identity_sha256"] = (
            parity_acceptance_identity_sha256
        )
        parity_binding["binding_sha256"] = sha({
            key: value for key, value in parity_binding.items()
            if key != "binding_sha256"
        })
    backend_source = v2_identity()
    backend_binding = copy.deepcopy(
        backend_source["bindings"]["backend_runtime_qualification"]
    )
    backend_binding["upstream_identities"][
        "model_parity_acceptance_binding_sha256"
    ] = identity["bindings"]["analytics_model_parity"]["binding_sha256"]
    for system, system_binding in backend_binding["systems"].items():
        system_binding["runtime_binding_identity_sha256"] = (
            runtime_binding_identity(
                system=system,
                launcher=system_binding["launcher"],
                launcher_invocation=system_binding["launcher_invocation"],
                upstream_identities=backend_binding["upstream_identities"],
            )
        )
    identity["bindings"]["backend_runtime_qualification"] = backend_binding
    by_path = {
        item["path"]: copy.deepcopy(item)
        for item in [*identity["files"], *backend_source["files"]]
    }
    identity["files"] = [by_path[path] for path in sorted(by_path)]
    identity["files_sha256"] = sha(identity["files"])
    identity["binding_sha256"] = sha({
        key: value for key, value in identity.items()
        if key != "binding_sha256"
    })
    backend = backend_runtime_grant_from_identity_artifacts(identity)
    parity = model_parity_grant_from_identity_artifacts(identity)
    contract = {
        "pre_run_resource_capability_grant": resource(
            backend["identity_artifact_binding_sha256"]
        ),
        "pre_run_backend_runtime_grant": backend,
        "pre_run_model_parity_grant": parity,
        "full_publication_execution_binding": copy.deepcopy(binding),
    }
    if output_dir is not None:
        arm_authority, receipt_authority = materialize(
            output_dir,
            arm_id=str(binding["arm_id"]),
            sequence=int(binding["sequence"]),
            execution_binding=binding,
            backend_grant_sha256=backend["grant_sha256"],
            resource_grant_sha256=contract[
                "pre_run_resource_capability_grant"
            ]["grant_sha256"],
            model_parity_grant_sha256=parity["grant_sha256"],
            model_parity_acceptance_binding_sha256=parity[
                "parity_acceptance_binding_sha256"
            ],
            identity_artifact_binding_sha256=backend[
                "identity_artifact_binding_sha256"
            ],
        )
        contract["backend_publication_arm_contract_authority"] = arm_authority
        contract["backend_publication_output_receipt_authority"] = (
            receipt_authority
        )
    evidence = {
        "schema_version": 1,
        "scope": FULL_RESOURCE_PUBLICATION_SCOPE,
        "policy": "cpu_only",
        "files": [],
    }
    return {
        "schema_version": 2,
        "mode": "benchmark",
        "result": {"status": "completed"},
        "publication_run_contract": contract,
        "publication_run_contract_identity": {"schema_version": 1, "sha256": sha(contract)},
        "publication_evidence_bundle": evidence,
        "publication_evidence_bundle_identity": {"schema_version": 1, "sha256": sha(evidence)},
    }


def write(path: Path, value: dict) -> None:
    path.write_bytes(json.dumps(value, indent=2, sort_keys=True).encode())


def candidate() -> dict:
    return {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_runtime_acceptance",
        "status": "accepted_native_checkpoint_arm",
    }


class BindingTests(unittest.TestCase):
    def test_binds_exact_metadata_authorities_and_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_metadata.json"
            expected = execution()
            clean = metadata(expected, path.parent)
            value = copy.deepcopy(clean)
            write(path, value)
            accepted = bind_checkpoint_acceptance_to_durable_metadata(
                candidate(), run_metadata_path=path,
                expected_execution_binding=expected,
            )
            checked = validate_checkpoint_acceptance_metadata_binding(
                accepted, run_metadata_path=path,
                expected_execution_binding=expected,
            )
            material = accepted["publication_metadata_binding"]
            contract = value["publication_run_contract"]
            self.assertEqual(material["run_metadata_sha256"], hashlib.sha256(path.read_bytes()).hexdigest())
            self.assertEqual(material["publication_run_contract_identity"], value["publication_run_contract_identity"])
            self.assertEqual(material["publication_evidence_bundle_identity"], value["publication_evidence_bundle_identity"])
            self.assertEqual(material["identity_artifact_binding_sha256"], contract["pre_run_resource_capability_grant"]["identity_artifact_binding_sha256"])
            self.assertEqual(material["resource_capability_grant_sha256"], contract["pre_run_resource_capability_grant"]["grant_sha256"])
            self.assertEqual(material["backend_runtime_grant_sha256"], contract["pre_run_backend_runtime_grant"]["grant_sha256"])
            self.assertEqual(material["model_parity_grant_sha256"], contract["pre_run_model_parity_grant"]["grant_sha256"])
            self.assertEqual(material["model_parity_acceptance_binding_sha256"], contract["pre_run_model_parity_grant"]["parity_acceptance_binding_sha256"])
            self.assertEqual(checked["execution_binding"], expected)

    def test_tamper_swap_old_schema_and_missing_authorities_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_metadata.json"
            expected = execution()
            value = metadata(expected, path.parent)
            write(path, value)
            accepted = bind_checkpoint_acceptance_to_durable_metadata(
                candidate(), run_metadata_path=path,
                expected_execution_binding=expected,
            )
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(AcceptanceMetadataBindingError, "run_metadata SHA-256"):
                validate_checkpoint_acceptance_metadata_binding(
                    accepted, run_metadata_path=path,
                    expected_execution_binding=expected,
                )
            swapped = Path(tmp) / "swapped"
            swapped.mkdir()
            write(path, metadata(execution("arm-2"), swapped))
            with self.assertRaisesRegex(AcceptanceMetadataBindingError, "run_metadata SHA-256"):
                validate_checkpoint_acceptance_metadata_binding(
                    accepted, run_metadata_path=path,
                    expected_execution_binding=expected,
                )
            with self.assertRaisesRegex(AcceptanceMetadataBindingError, "execution binding"):
                bind_checkpoint_acceptance_to_durable_metadata(
                    candidate(), run_metadata_path=path,
                    expected_execution_binding=expected,
                )
            write(path, value)
            with self.assertRaisesRegex(AcceptanceMetadataBindingError, "schema"):
                validate_checkpoint_acceptance_metadata_binding(
                    {"schema_version": 1}, run_metadata_path=path,
                    expected_execution_binding=expected,
                )
            for key, message in (
                ("publication_run_contract_identity", "contract identity"),
                ("publication_evidence_bundle_identity", "evidence bundle identity"),
            ):
                changed = copy.deepcopy(value)
                changed.pop(key)
                write(path, changed)
                with self.subTest(key=key), self.assertRaisesRegex(AcceptanceMetadataBindingError, message):
                    bind_checkpoint_acceptance_to_durable_metadata(
                        candidate(), run_metadata_path=path,
                        expected_execution_binding=expected,
                    )
            for key, message in (
                ("pre_run_resource_capability_grant", "resource capability grant"),
                ("pre_run_backend_runtime_grant", "backend runtime grant"),
                ("pre_run_model_parity_grant", "model-parity grant"),
            ):
                changed = copy.deepcopy(value)
                changed["publication_run_contract"].pop(key)
                changed["publication_run_contract_identity"]["sha256"] = sha(changed["publication_run_contract"])
                write(path, changed)
                with self.subTest(key=key), self.assertRaisesRegex(AcceptanceMetadataBindingError, message):
                    bind_checkpoint_acceptance_to_durable_metadata(
                        candidate(), run_metadata_path=path,
                        expected_execution_binding=expected,
                    )

    def test_identity_crossbind_and_binding_self_hash_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_metadata.json"
            expected = execution()
            clean = metadata(expected, path.parent)
            value = copy.deepcopy(clean)
            backend = value["publication_run_contract"]["pre_run_backend_runtime_grant"]
            backend["identity_artifact_binding_sha256"] = "f" * 64
            backend.pop("grant_sha256")
            backend["grant_sha256"] = sha(backend)
            value["publication_run_contract_identity"]["sha256"] = sha(value["publication_run_contract"])
            write(path, value)
            with self.assertRaisesRegex(AcceptanceMetadataBindingError, "identity artifact binding"):
                bind_checkpoint_acceptance_to_durable_metadata(
                    candidate(), run_metadata_path=path,
                    expected_execution_binding=expected,
                )
            # Reuse the already-materialized immutable physical receipt.
            write(path, clean)
            accepted = bind_checkpoint_acceptance_to_durable_metadata(
                candidate(), run_metadata_path=path,
                expected_execution_binding=expected,
            )
            accepted["publication_metadata_binding"]["binding_sha256"] = "0" * 64
            with self.assertRaisesRegex(AcceptanceMetadataBindingError, "self-hash"):
                validate_checkpoint_acceptance_metadata_binding(
                    accepted, run_metadata_path=path,
                    expected_execution_binding=expected,
                )
            legacy = bind_checkpoint_acceptance_to_durable_metadata(
                candidate(), run_metadata_path=path,
                expected_execution_binding=expected,
            )
            legacy_binding = legacy["publication_metadata_binding"]
            legacy_binding["schema_version"] = 1
            legacy_binding["binding_sha256"] = sha({
                key: value for key, value in legacy_binding.items()
                if key != "binding_sha256"
            })
            with self.assertRaisesRegex(AcceptanceMetadataBindingError, "self-hash"):
                validate_checkpoint_acceptance_metadata_binding(
                    legacy, run_metadata_path=path,
                    expected_execution_binding=expected,
                )

    def test_parity_replay_and_authority_sha_drift_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_metadata.json"
            expected = execution()
            clean = metadata(expected, path.parent)
            for field in (
                "identity_artifact_binding_sha256",
                "parity_acceptance_binding_sha256",
            ):
                changed = copy.deepcopy(clean)
                parity = changed["publication_run_contract"][
                    "pre_run_model_parity_grant"
                ]
                parity[field] = "f" * 64
                authorization = {
                    key: parity[key]
                    for key in (
                        "identity_artifact_binding_sha256",
                        "parity_acceptance_binding_sha256",
                        "acceptance_receipt", "accepted_manifest",
                        "accepted_assessment", "acceptance_identity_sha256",
                        "accepted_manifest_content_identity_sha256",
                        "canonical_assessment_identity_sha256", "evidence_count",
                        "evidence_sha256", "runtime_registries_sha256",
                        "runtime_images_sha256",
                    )
                }
                parity["authorization_material_sha256"] = sha(authorization)
                parity["grant_sha256"] = sha({
                    key: value for key, value in parity.items()
                    if key != "grant_sha256"
                })
                changed["publication_run_contract_identity"]["sha256"] = sha(
                    changed["publication_run_contract"]
                )
                write(path, changed)
                with self.subTest(field=field), self.assertRaises(
                    AcceptanceMetadataBindingError
                ):
                    bind_checkpoint_acceptance_to_durable_metadata(
                        candidate(), run_metadata_path=path,
                        expected_execution_binding=expected,
                    )

    def test_envelope_only_rejects_crossbound_authority_swaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "run_metadata.json"
            expected = execution()
            write(path, metadata(expected, path.parent))
            accepted = bind_checkpoint_acceptance_to_durable_metadata(
                candidate(), run_metadata_path=path,
                expected_execution_binding=expected,
            )
            for case in (
                "authority_mismatch",
                "binding_mismatch",
                "authority_parity_acceptance_mismatch",
                "coherent_authority_parity_acceptance_mismatch",
                "binding_parity_acceptance",
                "arm_descriptor",
            ):
                changed = copy.deepcopy(accepted)
                binding = changed["publication_metadata_binding"]
                arm = binding["backend_publication_arm_contract_authority"]
                receipt = binding[
                    "backend_publication_output_receipt_authority"
                ]
                if case == "authority_mismatch":
                    receipt["model_parity_grant_sha256"] = "f" * 64
                elif case == "binding_mismatch":
                    arm["model_parity_grant_sha256"] = "f" * 64
                    receipt["model_parity_grant_sha256"] = "f" * 64
                elif case == "authority_parity_acceptance_mismatch":
                    receipt[
                        "model_parity_acceptance_binding_sha256"
                    ] = "f" * 64
                elif case == "coherent_authority_parity_acceptance_mismatch":
                    arm[
                        "model_parity_acceptance_binding_sha256"
                    ] = "f" * 64
                    receipt[
                        "model_parity_acceptance_binding_sha256"
                    ] = "f" * 64
                elif case == "binding_parity_acceptance":
                    binding[
                        "model_parity_acceptance_binding_sha256"
                    ] = "f" * 64
                else:
                    receipt["arm_contract"]["sha256"] = "f" * 64
                binding["binding_sha256"] = sha({
                    key: value for key, value in binding.items()
                    if key != "binding_sha256"
                })
                with self.subTest(case=case), self.assertRaisesRegex(
                    AcceptanceMetadataBindingError, "crossbound"
                ):
                    validate_checkpoint_acceptance_metadata_binding_envelope(
                        changed
                    )


if __name__ == "__main__":
    unittest.main()
