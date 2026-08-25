from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_publication_identity_artifacts as identity  # noqa: E402
import full_publication_identity_manifest_v2 as target  # noqa: E402
from tests.test_full_publication_identity_artifacts import Fixture  # noqa: E402


SYSTEMS = identity.SYSTEMS


def inputs(fixture: Fixture) -> dict[str, object]:
    accepted = fixture.output
    return {
        "analytics_model_parity": {
            "receipt": fixture.parity_receipt,
            "accepted_manifest": fixture.root
            / "configs/checkpoint_analytics_model_parity.accepted.yaml",
            "accepted_assessment": fixture.parity_assessment,
        },
        "analytics_execution_layer": {
            "artifact": fixture.root / "configs/analytics_execution_layer.yaml",
            "content_identity_sha256": fixture.execution_identity,
        },
        "policy_qualification": {
            "receipt": accepted / "checkpoint_policy_qualification_receipt.json",
            "capability_manifest": accepted / "checkpoint_policy_capability_manifest.json",
            "calibration_mapping": accepted / "checkpoint_policy_calibration_mapping.json",
        },
        "resource_qualification": {
            "receipt": accepted / "checkpoint_full_resource_qualification_receipt.json",
            "capability_manifest": accepted
            / "checkpoint_full_resource_capability_manifest.json",
        },
        "backend_runtime_qualification": {
            "binding_index": accepted
            / "checkpoint_backend_runtime_qualification_binding_index.json",
            "receipts": {
                system: accepted
                / f"checkpoint_{system}_backend_runtime_qualification_receipt.json"
                for system in SYSTEMS
            },
        },
    }


def loader(fixture: Fixture):
    def load(*, project_root: Path, manifest_path: Path) -> dict[str, object]:
        return identity.load_full_publication_identity_artifacts(
            project_root=project_root,
            manifest_path=manifest_path,
            parity_loader=fixture.parity_loader,
            parity_acceptance_loader=fixture.parity_acceptance_loader,
            execution_loader=fixture.execution_loader,
            policy_capability_assessor=fixture.policy_assessor,
        )

    return load


class FullPublicationIdentityManifestV2Tests(unittest.TestCase):
    def test_materializes_then_physically_validates_complete_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            fixture.manifest_path.unlink()
            result = target.build_full_publication_identity_manifest_v2(
                project_root=root,
                output_path=fixture.manifest_path,
                identity_loader=loader(fixture),
                **inputs(fixture),
            )
            self.assertEqual(result["binding"]["artifact_kind"], identity.BINDING_KIND)
            self.assertEqual(result["manifest_path"], str(fixture.manifest_path))
            self.assertEqual(len(result["binding"]["bindings"]["backend_runtime_qualification"]["receipts"]), 4)

    def test_missing_artifact_alias_and_output_collision_fail_before_replacement(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            fixture.manifest_path.unlink()
            values = inputs(fixture)
            values["policy_qualification"]["calibration_mapping"] = root / "missing.json"
            with self.assertRaisesRegex(target.FullPublicationIdentityManifestV2Error, "missing"):
                target.build_full_publication_identity_manifest_v2(
                    project_root=root,
                    output_path=fixture.manifest_path,
                    identity_loader=loader(fixture),
                    **values,
                )
            self.assertFalse(fixture.manifest_path.exists())

            values = inputs(fixture)
            values["resource_qualification"]["capability_manifest"] = values[
                "policy_qualification"
            ]["capability_manifest"]
            with self.assertRaisesRegex(target.FullPublicationIdentityManifestV2Error, "alias"):
                target.build_full_publication_identity_manifest_v2(
                    project_root=root,
                    output_path=fixture.manifest_path,
                    identity_loader=loader(fixture),
                    **values,
                )

            fixture.manifest_path.write_text("occupied\n", encoding="utf-8")
            with self.assertRaisesRegex(target.FullPublicationIdentityManifestV2Error, "already exists"):
                target.build_full_publication_identity_manifest_v2(
                    project_root=root,
                    output_path=fixture.manifest_path,
                    identity_loader=loader(fixture),
                    **inputs(fixture),
                )

    def test_atomic_replace_failure_removes_only_private_tempfile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = Fixture(root)
            fixture.manifest_path.unlink()
            sentinel = fixture.manifest_path.parent / "survive.txt"
            sentinel.write_text("survive\n", encoding="utf-8")
            with mock.patch.object(target.os, "replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(
                    target.FullPublicationIdentityManifestV2Error, "atomic commit"
                ):
                    target.build_full_publication_identity_manifest_v2(
                        project_root=root,
                        output_path=fixture.manifest_path,
                        identity_loader=loader(fixture),
                        **inputs(fixture),
                    )
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "survive\n")
            self.assertEqual(list(sentinel.parent.glob(".full-identity-v2.*")), [])


if __name__ == "__main__":
    unittest.main()
