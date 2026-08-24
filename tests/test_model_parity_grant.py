from __future__ import annotations

import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from model_parity_grant import (  # noqa: E402
    ModelParityGrantError,
    assess_pre_run_model_parity_grant,
    model_parity_grant_from_identity_artifacts,
    validate_pre_run_model_parity_grant,
)


def sha(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def descriptor(path: str) -> dict[str, object]:
    return {"path": path, "size_bytes": 10, "sha256": hashlib.sha256(path.encode()).hexdigest()}


def identity() -> dict[str, object]:
    receipt = descriptor("accepted/parity-receipt.json")
    manifest = descriptor("configs/parity.accepted.yaml")
    assessment = descriptor("accepted/parity-assessment.json")
    evidence = [descriptor(f"evidence/model_parity/v3/{index:02d}.json") for index in range(32)]
    parity_files = sorted([receipt, manifest, assessment, *evidence], key=lambda item: item["path"])
    parity = {
        "schema_version": 1,
        "artifact_kind": "vast_verified_model_parity_acceptance_binding",
        "receipt": receipt,
        "accepted_manifest": manifest,
        "accepted_assessment": assessment,
        "acceptance_identity_sha256": "a" * 64,
        "accepted_manifest_content_identity_sha256": "b" * 64,
        "canonical_assessment_identity_sha256": "c" * 64,
        "evidence_count": 32,
        "evidence_sha256": "d" * 64,
        "runtime_registries_sha256": "e" * 64,
        "runtime_images_sha256": "f" * 64,
        "files": parity_files,
        "files_sha256": sha(parity_files),
    }
    parity["binding_sha256"] = sha(parity)
    files = sorted([descriptor("configs/full-publication.json"), *parity_files], key=lambda item: item["path"])
    result = {
        "schema_version": 2,
        "artifact_kind": "vast_full_publication_identity_artifact_binding",
        "manifest": descriptor("configs/full-publication.json"),
        "bindings": {
            "analytics_model_parity": parity,
            "analytics_execution_layer": {},
            "policy_qualification": {},
            "resource_qualification": {},
            "backend_runtime_qualification": {},
        },
        "files": files,
        "files_sha256": sha(files),
    }
    result["binding_sha256"] = sha(result)
    return result


class ModelParityGrantTests(unittest.TestCase):
    def test_schema2_physical_acceptance_derives_exact_self_hashed_grant(self) -> None:
        source = identity()
        grant = model_parity_grant_from_identity_artifacts(source)
        self.assertTrue(assess_pre_run_model_parity_grant(grant)["passed"])
        self.assertEqual(validate_pre_run_model_parity_grant(grant), grant)
        self.assertEqual(grant["evidence_count"], 32)
        self.assertEqual(grant["identity_artifact_binding_sha256"], source["binding_sha256"])

    def test_legacy_identity_and_base_manifest_binding_cannot_authorize(self) -> None:
        legacy = identity()
        legacy["schema_version"] = 1
        legacy["binding_sha256"] = sha({key: value for key, value in legacy.items() if key != "binding_sha256"})
        with self.assertRaisesRegex(ModelParityGrantError, "schema-2"):
            model_parity_grant_from_identity_artifacts(legacy)
        base = identity()
        base["bindings"]["analytics_model_parity"] = {
            "artifact": descriptor("configs/checkpoint_analytics_model_parity.yaml"),
            "content_identity_sha256": "a" * 64,
        }
        base["binding_sha256"] = sha({key: value for key, value in base.items() if key != "binding_sha256"})
        with self.assertRaisesRegex(ModelParityGrantError, "physical"):
            model_parity_grant_from_identity_artifacts(base)

    def test_nested_parity_binding_tamper_and_file_unbinding_fail(self) -> None:
        for mode in ("coverage", "binding", "unbound"):
            with self.subTest(mode=mode):
                value = identity()
                parity = value["bindings"]["analytics_model_parity"]
                if mode == "coverage":
                    parity["evidence_count"] = 31
                elif mode == "binding":
                    parity["runtime_images_sha256"] = "0" * 64
                else:
                    parity["receipt"] = descriptor("accepted/unbound.json")
                value["binding_sha256"] = sha({key: item for key, item in value.items() if key != "binding_sha256"})
                with self.assertRaises(ModelParityGrantError):
                    model_parity_grant_from_identity_artifacts(value)

    def test_grant_tamper_is_rejected_even_after_rehashing_one_boundary(self) -> None:
        grant = model_parity_grant_from_identity_artifacts(identity())
        for field, value in (("evidence_count", 31), ("evidence_sha256", "0" * 64), ("status", "fake_ready")):
            with self.subTest(field=field):
                drifted = copy.deepcopy(grant)
                drifted[field] = value
                drifted["grant_sha256"] = sha({key: item for key, item in drifted.items() if key != "grant_sha256"})
                self.assertFalse(assess_pre_run_model_parity_grant(drifted)["passed"])


if __name__ == "__main__":
    unittest.main()
