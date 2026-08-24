from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import full_publication_identity_artifacts as target  # noqa: E402
from backend_runtime_grant import (  # noqa: E402
    BackendRuntimeGrantError,
    assess_pre_run_backend_runtime_grant_v3,
    backend_runtime_grant_from_identity_artifacts,
    validate_pre_run_backend_runtime_grant_v3,
)
from backend_runtime_qualification_v3 import (  # noqa: E402
    promote_backend_runtime_qualification_v3,
)
from tests.test_backend_runtime_qualification_v3 import (  # noqa: E402
    PhysicalV3Fixture,
    canonical_sha as qualification_canonical_sha,
    raw_validator,
)
from tests.test_full_publication_identity_artifacts import (  # noqa: E402
    Fixture,
    canonical_sha,
    descriptor,
    write_json,
)


SYSTEMS = target.SYSTEMS


class IdentityBoundPhysicalV3Fixture(PhysicalV3Fixture):
    def __init__(self, root: Path, identity_fixture: Fixture) -> None:
        self.identity_fixture = identity_fixture
        super().__init__(root)

    def _authority_fields(
        self, *, system: str, codec: str, topology: str, policy: str,
    ) -> dict[str, object]:
        fields = super()._authority_fields(
            system=system, codec=codec, topology=topology, policy=policy,
        )
        manifest = self.root / "runtime-authority-leaves/dataset-manifest.json"
        manifest.write_bytes(b"datasets")
        fields["dataset_manifest"] = descriptor(self.root, manifest)
        policy_capability = (
            self.identity_fixture.output
            / "checkpoint_policy_capability_manifest.json"
        )
        policy_calibration = (
            self.identity_fixture.output
            / "checkpoint_policy_calibration_mapping.json"
        )
        capability_descriptor = descriptor(self.root, policy_capability)
        calibration_descriptor = descriptor(self.root, policy_calibration)
        fields["policy_authority"]["capability"] = {
            "role": "policy_capability",
            "descriptor": capability_descriptor,
            "content_identity_sha256": capability_descriptor["sha256"],
        }
        fields["policy_authority"]["calibration"] = {
            "role": "policy_calibration",
            "descriptor": calibration_descriptor,
            "content_identity_sha256": calibration_descriptor["sha256"],
        }
        resource_capability = json.loads(
            (
                self.identity_fixture.output
                / "checkpoint_full_resource_capability_manifest.json"
            ).read_text(encoding="utf-8")
        )
        contract = resource_capability["resource_contract"]
        fields["resource_contract"] = {
            "content": contract,
            "content_identity_sha256": qualification_canonical_sha(contract),
        }
        return fields


class FullPublicationIdentityRuntimeAuthorityV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.fixture = Fixture(self.root)
        self.v3 = IdentityBoundPhysicalV3Fixture(self.root, self.fixture)
        self.v3.upstream = self._expected_upstream()
        self.v3.index = self.v3._build_index()
        self.v3.write_index(self.v3.index)
        self.output = self.root / "accepted-v3"
        self.output.mkdir()
        promoted = promote_backend_runtime_qualification_v3(
            project_root=self.root,
            index_path=self.v3.index_path,
            output_dir=self.output,
            raw_evidence_validator=raw_validator,
        )
        manifest = json.loads(self.fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["bindings"]["backend_runtime_qualification"] = {
            "binding_index": descriptor(
                self.root,
                self.output / promoted["binding_index_descriptor"]["path"],
            ),
            "receipts": {
                system: descriptor(
                    self.root,
                    self.output / promoted["receipt_descriptors"][system]["path"],
                )
                for system in SYSTEMS
            },
        }
        write_json(self.fixture.manifest_path, manifest)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _expected_upstream(self) -> dict[str, str]:
        policy_receipt = (
            self.fixture.output / "checkpoint_policy_qualification_receipt.json"
        )
        resource_receipt = (
            self.fixture.output
            / "checkpoint_full_resource_qualification_receipt.json"
        )
        return {
            "dataset_manifest_sha256": self.fixture.dataset_sha,
            "policy_contract_sha256": self.fixture.policy_contract_sha,
            "policy_qualification_receipt_sha256": descriptor(
                self.root, policy_receipt
            )["sha256"],
            "resource_contract_identity_sha256": json.loads(
                resource_receipt.read_text(encoding="utf-8")
            )["resource_contract_identity_sha256"],
            "resource_qualification_receipt_sha256": descriptor(
                self.root, resource_receipt
            )["sha256"],
            "analytics_execution_config_identity_sha256": (
                self.fixture.execution_identity
            ),
            "model_parity_manifest_identity_sha256": self.fixture.parity_identity,
            "model_parity_acceptance_binding_sha256": (
                self.fixture.parity_acceptance["binding_sha256"]
            ),
        }

    def test_v3_candidate_becomes_non_authorizing_identity_binding(self) -> None:
        identity = self.fixture.load()
        self.assertEqual(identity["schema_version"], 2)
        backend = identity["bindings"]["backend_runtime_qualification"]
        self.assertEqual(backend["schema_version"], 3)
        self.assertEqual(
            backend["artifact_kind"],
            "vast_full_publication_backend_runtime_qualification_binding_v3",
        )
        self.assertEqual(
            backend["source_status"],
            "qualified_runtime_authority_catalog_v3_pre_identity_candidate",
        )
        self.assertEqual(
            backend["source_qualification_scope"],
            "backend_runtime_authority_catalog_v3_pre_identity_only",
        )
        self.assertIs(backend["authorization_eligible"], False)
        self.assertEqual(
            backend["validation_trust_status"],
            "untrusted_callback_evidence_only",
        )
        self.assertIs(backend["semantic_crossbinding_complete"], False)
        self.assertEqual(
            backend["authorization_blockers"],
            target._BACKEND_V3_AUTHORIZATION_BLOCKERS,
        )
        self.assertEqual(
            backend["observed_validator_identity_sha256"],
            hashlib.sha256(b"backend-cell-raw-validator-v3").hexdigest(),
        )
        self.assertNotIn("accepted", backend)
        self.assertNotIn("grant_sha256", backend)
        self.assertRegex(backend["identity_binding_sha256"], r"^[0-9a-f]{64}$")
        self.assertRegex(
            backend["runtime_authority_leaf_set_sha256"], r"^[0-9a-f]{64}$"
        )
        self.assertEqual(
            backend["runtime_authority_leaf_set_sha256"],
            canonical_sha(backend["runtime_authority_leaves"]),
        )
        self.assertEqual(
            [item["path"] for item in backend["runtime_authority_leaves"]],
            sorted(item["path"] for item in backend["runtime_authority_leaves"]),
        )
        authority_paths = {
            record["artifact"]["path"]
            for system in SYSTEMS
            for record in backend["systems"][system]["runtime_authorities"]
        }
        self.assertEqual(len(authority_paths), 112)
        identity_paths = [record["path"] for record in identity["files"]]
        self.assertTrue(authority_paths.issubset(identity_paths))
        self.assertEqual(
            identity_paths.count("runtime-authority-leaves/source.bin"), 1
        )
        for system in SYSTEMS:
            system_binding = backend["systems"][system]
            self.assertEqual(
                system_binding["runtime_authority_leaf_set_sha256"],
                canonical_sha(system_binding["runtime_authority_leaves"]),
            )

        with self.assertRaisesRegex(
            BackendRuntimeGrantError, "qualification v2 material is required"
        ):
            backend_runtime_grant_from_identity_artifacts(identity)
        self.assertFalse(assess_pre_run_backend_runtime_grant_v3(backend)["passed"])
        with self.assertRaises(BackendRuntimeGrantError):
            validate_pre_run_backend_runtime_grant_v3(backend)
        unsigned_backend = {
            key: value
            for key, value in backend.items()
            if key != "identity_binding_sha256"
        }
        self.assertEqual(
            backend["identity_binding_sha256"], canonical_sha(unsigned_backend)
        )

    def test_v3_inconsistent_untrusted_validator_identity_fails_closed(self) -> None:
        def inconsistent_validator(
            cell: dict[str, object], context: dict[str, object],
        ) -> dict[str, object]:
            result = raw_validator(cell, context)
            result["validator_identity_sha256"] = hashlib.sha256(
                str(cell["system"]).encode("utf-8")
            ).hexdigest()
            result.pop("validation_record_sha256")
            result["validation_record_sha256"] = qualification_canonical_sha(
                result
            )
            return result

        output = self.root / "inconsistent-validator-v3"
        output.mkdir()
        promoted = promote_backend_runtime_qualification_v3(
            project_root=self.root,
            index_path=self.v3.index_path,
            output_dir=output,
            raw_evidence_validator=inconsistent_validator,
        )
        manifest = json.loads(
            self.fixture.manifest_path.read_text(encoding="utf-8")
        )
        manifest["bindings"]["backend_runtime_qualification"] = {
            "binding_index": descriptor(
                self.root, output / promoted["binding_index_descriptor"]["path"],
            ),
            "receipts": {
                system: descriptor(
                    self.root, output / promoted["receipt_descriptors"][system]["path"],
                )
                for system in SYSTEMS
            },
        }
        write_json(self.fixture.manifest_path, manifest)
        with self.assertRaisesRegex(
            target.IdentityArtifactError, "validator identity.*globally consistent",
        ):
            self.fixture.load()

    def test_v3_shared_runtime_leaf_physical_drift_fails_closed(self) -> None:
        leaf = self.root / "runtime-authority-leaves/source.bin"
        leaf.write_bytes(leaf.read_bytes() + b"drift")
        with self.assertRaisesRegex(
            target.IdentityArtifactError,
            "runtime authority physical assessment blocked|physical size|size/SHA drift",
        ):
            self.fixture.load()

    def test_v3_receipt_candidate_status_cannot_be_promoted_by_relabelling(self) -> None:
        receipt_path = (
            self.output
            / "checkpoint_deepstream_backend_runtime_qualification_v3_receipt.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["status"] = "accepted_pre_run_backend_runtime_qualification_v3"
        receipt.pop("receipt_sha256")
        receipt["receipt_sha256"] = hashlib.sha256(
            json.dumps(
                receipt,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        write_json(receipt_path, receipt)
        manifest = json.loads(self.fixture.manifest_path.read_text(encoding="utf-8"))
        manifest["bindings"]["backend_runtime_qualification"]["receipts"][
            "deepstream"
        ] = descriptor(self.root, receipt_path)
        write_json(self.fixture.manifest_path, manifest)
        with self.assertRaisesRegex(
            target.IdentityArtifactError, "v3.*candidate|status|embedded"
        ):
            self.fixture.load()

    def test_shared_leaf_registry_dedupes_only_exact_same_path_and_inode(self) -> None:
        leaf = self.root / "shared-leaf.bin"
        leaf.write_bytes(b"physical-shared-leaf")
        leaf_descriptor = descriptor(self.root, leaf)
        registry = target._Registry(self.root)
        first, _ = registry.add_shared(leaf_descriptor, "first shared leaf")
        second, _ = registry.add_shared(
            copy.deepcopy(leaf_descriptor), "recurring shared leaf"
        )
        self.assertEqual(first, second)
        self.assertEqual(list(registry.files), ["shared-leaf.bin"])

        drifted = copy.deepcopy(leaf_descriptor)
        drifted["sha256"] = "0" * 64
        with self.assertRaisesRegex(target.IdentityArtifactError, "size/SHA drift"):
            registry.add_shared(drifted, "drifted shared leaf")

        alias = self.root / "shared-leaf-alias.bin"
        try:
            os.link(leaf, alias)
        except OSError as error:
            self.skipTest(f"hardlinks unavailable: {error}")
        with self.assertRaisesRegex(target.IdentityArtifactError, "hardlink alias"):
            registry.add_shared(
                descriptor(self.root, alias), "hardlinked shared leaf alias"
            )

    def test_launcher_registration_never_uses_shared_leaf_exception(self) -> None:
        launcher = self.root / "launcher.py"
        launcher.write_bytes(b"publication-launcher")
        launcher_descriptor = descriptor(self.root, launcher)
        registry = target._Registry(self.root)
        registry.add(launcher_descriptor, "first system launcher")
        with self.assertRaisesRegex(
            target.IdentityArtifactError, "duplicates another artifact path"
        ):
            registry.add(launcher_descriptor, "second system launcher")

    def test_identity_descriptor_grammar_rejects_windows_and_root_escapes(self) -> None:
        for unsafe in (
            "/outside.bin", "C:outside.bin", "foo:stream", "foo\\bar.bin",
            "NUL.bin", "trailing-dot./artifact.bin",
        ):
            with self.subTest(unsafe=unsafe), self.assertRaises(
                target.IdentityArtifactError
            ):
                target._resolve_file(self.root, unsafe, "unsafe identity artifact")


if __name__ == "__main__":
    unittest.main()
