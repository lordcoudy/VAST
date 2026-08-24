from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_runtime_grant import (  # noqa: E402
    BackendRuntimeGrantError,
    backend_runtime_grant_from_identity_artifacts,
    validate_pre_run_backend_runtime_grant,
)
from backend_publication_dispatch import runtime_binding_identity  # noqa: E402
from backend_runtime_qualification_v2 import (  # noqa: E402
    BINDING_INDEX_FILENAME,
    SYSTEMS,
    promote_backend_runtime_qualification_v2,
)
from tests.test_backend_runtime_qualification_v2 import (  # noqa: E402
    Fixture as QualificationFixture,
    raw_validator,
)
from tests.test_full_publication_identity_artifacts import (  # noqa: E402
    Fixture as IdentityFixture,
    descriptor,
    write_json,
)


class BackendRuntimeIdentityGrantV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.identity_fixture = IdentityFixture(self.root)
        self.qualification_fixture = QualificationFixture(self.root)

        policy_receipt = self.identity_fixture.output / "checkpoint_policy_qualification_receipt.json"
        resource_receipt = self.identity_fixture.output / "checkpoint_full_resource_qualification_receipt.json"
        resource_value = json.loads(resource_receipt.read_text(encoding="utf-8"))
        upstream = {
            "dataset_manifest_sha256": self.identity_fixture.dataset_sha,
            "policy_contract_sha256": self.identity_fixture.policy_contract_sha,
            "policy_qualification_receipt_sha256": descriptor(
                self.root, policy_receipt
            )["sha256"],
            "resource_contract_identity_sha256": resource_value[
                "resource_contract_identity_sha256"
            ],
            "resource_qualification_receipt_sha256": descriptor(
                self.root, resource_receipt
            )["sha256"],
            "analytics_execution_config_identity_sha256": self.identity_fixture.execution_identity,
            "model_parity_manifest_identity_sha256": self.identity_fixture.parity_identity,
            "model_parity_acceptance_binding_sha256": self.identity_fixture.parity_acceptance[
                "binding_sha256"
            ],
        }
        self.qualification_fixture.upstream = upstream
        self.qualification_fixture.value["upstream_identities"] = upstream
        for system in SYSTEMS:
            binding = self.qualification_fixture.value["systems"][system]
            binding["runtime_binding_identity_sha256"] = (
                runtime_binding_identity(
                    system=system,
                    launcher=binding["launcher"],
                    launcher_invocation=binding["launcher_invocation"],
                    upstream_identities=upstream,
                )
            )
        self.qualification_fixture.rewrite()

        self.output = self.root / "accepted/backend_v2"
        self.promotion = promote_backend_runtime_qualification_v2(
            project_root=self.root,
            index_path=self.qualification_fixture.index_path,
            output_dir=self.output,
            raw_evidence_validator=raw_validator,
        )
        manifest = json.loads(
            self.identity_fixture.manifest_path.read_text(encoding="utf-8")
        )
        manifest["bindings"]["backend_runtime_qualification"] = {
            "binding_index": descriptor(
                self.root, self.output / BINDING_INDEX_FILENAME
            ),
            "receipts": {
                system: descriptor(
                    self.root,
                    self.output
                    / f"checkpoint_{system}_backend_runtime_qualification_receipt.json",
                )
                for system in SYSTEMS
            },
        }
        write_json(self.identity_fixture.manifest_path, manifest)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_v2_identity_rehashes_all_evidence_and_derives_exact_grant(self) -> None:
        identity = self.identity_fixture.load()
        backend = identity["bindings"]["backend_runtime_qualification"]
        self.assertEqual(backend["schema_version"], 2)
        self.assertEqual(backend["coverage"]["runtime_cell_count"], 560)
        self.assertEqual(len(backend["systems"]), 4)
        self.assertEqual(
            backend["upstream_identities"][
                "model_parity_acceptance_binding_sha256"
            ],
            identity["bindings"]["analytics_model_parity"]["binding_sha256"],
        )
        raw_paths = {
            cell["raw_evidence"]["path"]
            for system in SYSTEMS
            for cell in backend["systems"][system]["qualified_cells"]
        }
        self.assertEqual(len(raw_paths), 560)
        self.assertTrue(raw_paths.issubset({item["path"] for item in identity["files"]}))

        grant = backend_runtime_grant_from_identity_artifacts(identity)
        validated = validate_pre_run_backend_runtime_grant(grant)
        self.assertEqual(validated["identity_artifact_binding_sha256"], identity["binding_sha256"])
        self.assertEqual(validated["coverage"]["runtime_cell_count"], 560)
        self.assertEqual(
            validated["qualification_binding_index"]["sha256"],
            backend["binding_index"]["sha256"],
        )

    def test_backend_v2_wrong_physical_parity_acceptance_binding_fails_identity(self) -> None:
        upstream = dict(self.qualification_fixture.upstream)
        upstream["model_parity_acceptance_binding_sha256"] = "0" * 64
        self.qualification_fixture.upstream = upstream
        self.qualification_fixture.value["upstream_identities"] = upstream
        for system in SYSTEMS:
            binding = self.qualification_fixture.value["systems"][system]
            binding["runtime_binding_identity_sha256"] = runtime_binding_identity(
                system=system,
                launcher=binding["launcher"],
                launcher_invocation=binding["launcher_invocation"],
                upstream_identities=upstream,
            )
        self.qualification_fixture.rewrite()
        output = self.root / "accepted/backend_v2_wrong_parity"
        promote_backend_runtime_qualification_v2(
            project_root=self.root,
            index_path=self.qualification_fixture.index_path,
            output_dir=output,
            raw_evidence_validator=raw_validator,
        )
        manifest = json.loads(
            self.identity_fixture.manifest_path.read_text(encoding="utf-8")
        )
        manifest["bindings"]["backend_runtime_qualification"] = {
            "binding_index": descriptor(self.root, output / BINDING_INDEX_FILENAME),
            "receipts": {
                system: descriptor(
                    self.root,
                    output
                    / f"checkpoint_{system}_backend_runtime_qualification_receipt.json",
                )
                for system in SYSTEMS
            },
        }
        write_json(self.identity_fixture.manifest_path, manifest)

        with self.assertRaisesRegex(Exception, "upstream cross-binding drift"):
            self.identity_fixture.load()

    def test_raw_evidence_and_launcher_tamper_fail_identity_before_grant(self) -> None:
        targets = (
            self.root / "accepted/backend/deepstream/cells/000.json",
            self.root / "runtime/deepstream/publication_launcher.py",
        )
        for target in targets:
            with self.subTest(target=target.name):
                original = target.read_bytes()
                target.write_bytes(original + b"tamper\n")
                with self.assertRaisesRegex(Exception, "size/SHA drift"):
                    self.identity_fixture.load()
                target.write_bytes(original)

    def test_legacy_v1_identity_remains_valid_but_cannot_derive_v2_grant(self) -> None:
        legacy_root = self.root / "legacy"
        legacy_root.mkdir()
        legacy = IdentityFixture(legacy_root).load()
        with self.assertRaisesRegex(BackendRuntimeGrantError, "backend qualification v2"):
            backend_runtime_grant_from_identity_artifacts(legacy)


if __name__ == "__main__":
    unittest.main()
