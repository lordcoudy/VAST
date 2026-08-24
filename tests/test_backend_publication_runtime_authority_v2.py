from __future__ import annotations

import copy
import ast
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_publication_runtime_authority_v2 as runtime_authority_v2  # noqa: E402
from backend_publication_runtime_authority_v2 import (  # noqa: E402
    ARTIFACT_KIND,
    BackendPublicationRuntimeAuthorityV2Error,
    UPSTREAM_IDENTITY_FIELDS,
    assess_backend_publication_runtime_authority_v2,
    build_backend_publication_runtime_authority_v2,
    validate_backend_publication_runtime_authority_v2,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def reseal(authority: dict[str, object]) -> None:
    unsigned = {
        key: value for key, value in authority.items()
        if key != "authority_sha256"
    }
    authority["authority_sha256"] = canonical_sha(unsigned)


def descriptor(root: Path, relative: str, payload: bytes) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def artifact(role: str, value: dict[str, object]) -> dict[str, object]:
    return {
        "role": role,
        "descriptor": copy.deepcopy(value),
        "content_identity_sha256": value["sha256"],
    }


def content_record(content: dict[str, object]) -> dict[str, object]:
    return {"content": content, "content_identity_sha256": canonical_sha(content)}


def fixture_fields(root: Path, *, policy: str = "cpu_only") -> dict[str, object]:
    manifest = descriptor(root, "dataset/manifest.json", b"dataset-manifest")
    dataset_file = descriptor(root, "dataset/kpp-h264.mp4", b"kpp-h264")
    source = artifact(
        "source_binary", descriptor(root, "runtime/source.bin", b"source")
    )
    backend = artifact(
        "runtime_binary", descriptor(root, "runtime/backend.bin", b"backend")
    )
    analytics_capability = artifact(
        "analytics_endpoint_capability",
        descriptor(root, "authority/analytics-capability.json", b"analytics-capability"),
    )
    analytics_binding = artifact(
        "analytics_worker_binding",
        descriptor(root, "authority/analytics-binding.json", b"analytics-binding"),
    )
    policy_capability = artifact(
        "policy_capability",
        descriptor(root, "authority/policy-capability.json", b"policy-capability"),
    )
    policy_calibration = artifact(
        "policy_calibration",
        descriptor(root, "authority/policy-calibration.json", b"policy-calibration"),
    )
    static_map = (
        artifact(
            "policy_static_map",
            descriptor(root, "authority/policy-static-map.json", b"policy-static-map"),
        )
        if policy == "static_hybrid" else None
    )
    resource_contract = content_record({"contract_version": 2})
    upstream_identities = {
        "dataset_manifest_sha256": manifest["sha256"],
        "policy_contract_sha256": "6" * 64,
        "policy_qualification_receipt_sha256": "7" * 64,
        "resource_contract_identity_sha256": resource_contract["content_identity_sha256"],
        "resource_qualification_receipt_sha256": "8" * 64,
        "analytics_execution_config_identity_sha256": "9" * 64,
        "model_parity_manifest_identity_sha256": "a" * 64,
        "model_parity_acceptance_binding_sha256": "b" * 64,
    }
    policy_authority = {
        "capability": policy_capability,
        "calibration": policy_calibration,
        "static_map": static_map,
    }
    expected_policy_outputs = {
        key: None if value is None else copy.deepcopy(value["descriptor"])
        for key, value in policy_authority.items()
    }
    return {
        "system": "gstreamer_custom",
        "policy": policy,
        "topology_kind": "shared_video_dag",
        "codec": "h264",
        "dataset_manifest": manifest,
        "dataset_files": [dataset_file],
        "source_runtime_artifacts": [source],
        "backend_runtime_artifacts": [backend],
        "analytics_authority": {
            "endpoint_authority": {
                "transport": "AF_UNIX/SOCK_SEQPACKET",
                "path_derivation_contract_sha256": "1" * 64,
                "peer_capability_identity_sha256": "2" * 64,
                "peer_binding_identity_sha256": "3" * 64,
                "bind_before_backend_launch": True,
                "peer_credentials_required": True,
            },
            "capability": analytics_capability,
            "bindings": [analytics_binding],
            "preprocessing_contract_sha256": "4" * 64,
        },
        "upstream_identities": upstream_identities,
        "expected_upstream_identities": copy.deepcopy(upstream_identities),
        "expected_policy_outputs": expected_policy_outputs,
        "policy_authority": policy_authority,
        "cohort_topology_plan": content_record({
            "topology_kind": "shared_video_dag", "warmup_s": 30,
            "measurement_s": 180, "source_decode_count": 1,
        }),
        "resource_contract": resource_contract,
        "system_specific_launcher_input": content_record({
            "system": "gstreamer_custom",
            "launcher_kind": "dedicated_publication_runtime",
        }),
    }


def validation_expectations(fields: dict[str, object]) -> dict[str, object]:
    return {
        "expected_system": fields["system"],
        "expected_policy": fields["policy"],
        "expected_topology_kind": fields["topology_kind"],
        "expected_codec": fields["codec"],
        "expected_upstream_identities": copy.deepcopy(
            fields["expected_upstream_identities"]
        ),
        "expected_policy_outputs": copy.deepcopy(fields["expected_policy_outputs"]),
    }


def build_fixture(
    root: Path, *, policy: str = "cpu_only",
) -> tuple[dict[str, object], dict[str, object]]:
    fields = fixture_fields(root, policy=policy)
    authority = build_backend_publication_runtime_authority_v2(
        project_root=root, **fields,
    )
    return authority, fields


class RuntimeAuthorityV2Test(unittest.TestCase):
    def test_build_validate_and_assess_closed_nonauthorizing_v2(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            validated = validate_backend_publication_runtime_authority_v2(
                authority, **validation_expectations(fields),
            )
            self.assertEqual(validated, authority)
            self.assertEqual(authority["artifact_kind"], ARTIFACT_KIND)
            self.assertEqual(authority["schema_version"], 2)
            self.assertNotIn("model_parity_acceptance_binding_sha256", authority)
            self.assertEqual(
                set(authority["upstream_identities"]),
                set(UPSTREAM_IDENTITY_FIELDS),
            )
            assessment = assess_backend_publication_runtime_authority_v2(
                authority, project_root=root, **validation_expectations(fields),
            )
            self.assertEqual(assessment["status"], "physically_valid")
            self.assertEqual(assessment["blockers"], [])
            self.assertFalse(assessment["execution_authorized"])
            self.assertFalse(assessment["analytics_provenance_validated"])
            self.assertFalse(assessment["static_map_semantics_validated"])
            self.assertNotIn("grant_sha256", assessment)
            self.assertNotIn("accepted", assessment)

    def test_exact_eight_upstream_identities_are_required_and_expected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            expected = validation_expectations(fields)
            self.assertEqual(len(UPSTREAM_IDENTITY_FIELDS), 8)
            for name in UPSTREAM_IDENTITY_FIELDS:
                with self.subTest(name=name):
                    drifted = copy.deepcopy(authority)
                    drifted["upstream_identities"][name] = "f" * 64
                    reseal(drifted)
                    with self.assertRaises(BackendPublicationRuntimeAuthorityV2Error):
                        validate_backend_publication_runtime_authority_v2(
                            drifted, **expected,
                        )
            for mutation in ("missing", "extra"):
                with self.subTest(mutation=mutation):
                    drifted = copy.deepcopy(authority)
                    if mutation == "missing":
                        del drifted["upstream_identities"][
                            "analytics_execution_config_identity_sha256"
                        ]
                    else:
                        drifted["upstream_identities"]["grant_sha256"] = "c" * 64
                    reseal(drifted)
                    with self.assertRaisesRegex(
                        BackendPublicationRuntimeAuthorityV2Error,
                        "upstream identity fields",
                    ):
                        validate_backend_publication_runtime_authority_v2(
                            drifted, **expected,
                        )

    def test_downstream_and_cyclic_fields_are_forbidden_everywhere(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            expected = validation_expectations(fields)
            forbidden = (
                "runtime_binding_identity_sha256", "qualification_receipt_sha256",
                "identity_artifact_binding_sha256", "grant_sha256", "run_id",
                "output_dir", "receipt_sha256", "publication_acceptance_sha256",
            )
            for name in forbidden:
                with self.subTest(location="top", name=name):
                    drifted = copy.deepcopy(authority)
                    drifted[name] = "c" * 64
                    reseal(drifted)
                    with self.assertRaises(BackendPublicationRuntimeAuthorityV2Error):
                        validate_backend_publication_runtime_authority_v2(
                            drifted, **expected,
                        )
                with self.subTest(location="upstream", name=name):
                    drifted = copy.deepcopy(authority)
                    drifted["upstream_identities"][name] = "c" * 64
                    reseal(drifted)
                    with self.assertRaises(BackendPublicationRuntimeAuthorityV2Error):
                        validate_backend_publication_runtime_authority_v2(
                            drifted, **expected,
                        )

    def test_dataset_manifest_binding_is_distinct_from_descriptor_set_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            self.assertEqual(
                authority["dataset"]["manifest"]["sha256"],
                authority["upstream_identities"]["dataset_manifest_sha256"],
            )
            self.assertNotEqual(
                authority["dataset"]["content_identity_sha256"],
                authority["upstream_identities"]["dataset_manifest_sha256"],
            )
            validate_backend_publication_runtime_authority_v2(
                authority, **validation_expectations(fields),
            )

    def test_derived_dataset_resource_and_policy_bindings_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            expected = validation_expectations(fields)

            dataset_drift = copy.deepcopy(authority)
            dataset_drift["upstream_identities"]["dataset_manifest_sha256"] = "d" * 64
            dataset_expected = copy.deepcopy(expected)
            dataset_expected["expected_upstream_identities"][
                "dataset_manifest_sha256"
            ] = "d" * 64
            reseal(dataset_drift)
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityV2Error, "dataset manifest",
            ):
                validate_backend_publication_runtime_authority_v2(
                    dataset_drift, **dataset_expected,
                )

            resource_drift = copy.deepcopy(authority)
            resource_drift["upstream_identities"][
                "resource_contract_identity_sha256"
            ] = "e" * 64
            resource_expected = copy.deepcopy(expected)
            resource_expected["expected_upstream_identities"][
                "resource_contract_identity_sha256"
            ] = "e" * 64
            reseal(resource_drift)
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityV2Error, "resource contract",
            ):
                validate_backend_publication_runtime_authority_v2(
                    resource_drift, **resource_expected,
                )

            policy_expected = copy.deepcopy(expected)
            policy_expected["expected_policy_outputs"]["capability"]["sha256"] = "f" * 64
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityV2Error, "policy capability",
            ):
                validate_backend_publication_runtime_authority_v2(
                    authority, **policy_expected,
                )

    def test_policy_outputs_are_closed_canonical_descriptors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root, policy="static_hybrid")
            expected = validation_expectations(fields)
            validate_backend_publication_runtime_authority_v2(
                authority, **expected,
            )
            self.assertIsNotNone(expected["expected_policy_outputs"]["static_map"])
            wrong = copy.deepcopy(expected)
            wrong["expected_policy_outputs"]["extra"] = None
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityV2Error,
                "expected policy output fields",
            ):
                validate_backend_publication_runtime_authority_v2(
                    authority, **wrong,
                )
            wrong_coordinate = copy.deepcopy(expected)
            wrong_coordinate["expected_policy"] = "cpu_only"
            with self.assertRaises(BackendPublicationRuntimeAuthorityV2Error):
                validate_backend_publication_runtime_authority_v2(
                    authority, **wrong_coordinate,
                )
            noncanonical = copy.deepcopy(expected)
            noncanonical["expected_policy_outputs"]["capability"][
                "size_bytes"
            ] = True
            with self.assertRaisesRegex(
                BackendPublicationRuntimeAuthorityV2Error,
                "expected policy capability descriptor is invalid",
            ):
                validate_backend_publication_runtime_authority_v2(
                    authority, **noncanonical,
                )

    def test_physical_tamper_blocks_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            runtime_path = root / authority[
                "backend_runtime_artifacts"
            ][0]["descriptor"]["path"]
            runtime_path.write_bytes(b"tampered")
            assessment = assess_backend_publication_runtime_authority_v2(
                authority, project_root=root, **validation_expectations(fields),
            )
            self.assertEqual(assessment["status"], "blocked")
            self.assertTrue(assessment["blockers"])
            self.assertFalse(assessment["execution_authorized"])

    def test_builder_requires_post_reconstruction_v2_physical_assessment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fields = fixture_fields(root)
            blocked = {
                "status": "blocked",
                "blockers": ["injected post-reconstruction blocker"],
            }
            with mock.patch.object(
                runtime_authority_v2,
                "assess_backend_publication_runtime_authority_v2",
                return_value=blocked,
            ) as assessor:
                with self.assertRaisesRegex(
                    BackendPublicationRuntimeAuthorityV2Error,
                    "physical assessment blocked.*injected",
                ):
                    build_backend_publication_runtime_authority_v2(
                        project_root=root, **fields,
                    )
            assessor.assert_called_once()

    def test_assessment_requires_exact_physically_valid_v1_response(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            projected_sha = runtime_authority_v2._project_to_v1(authority)[
                "authority_sha256"
            ]
            inconsistent = {
                "schema_version": 1,
                "artifact_kind": runtime_authority_v2.runtime_authority_v1.ASSESSMENT_KIND,
                "status": "blocked",
                "authority_sha256": projected_sha,
                "system": "gstreamer_custom",
                "policy": "cpu_only",
                "topology_kind": "shared_video_dag",
                "codec": "h264",
                "checked_artifact_count": 8,
                "blockers": [],
            }
            with mock.patch.object(
                runtime_authority_v2.runtime_authority_v1,
                "assess_backend_publication_runtime_authority",
                return_value=inconsistent,
            ):
                assessment = assess_backend_publication_runtime_authority_v2(
                    authority,
                    project_root=root,
                    **validation_expectations(fields),
                )
            self.assertEqual(assessment["status"], "blocked")
            self.assertTrue(any(
                "did not report physically_valid" in blocker
                for blocker in assessment["blockers"]
            ))

    def test_module_calls_only_public_v1_api_and_no_grant_or_readiness_api(self) -> None:
        source = (
            ROOT / "scripts" / "backend_publication_runtime_authority_v2.py"
        ).read_text(encoding="utf-8")
        tree = ast.parse(source)
        v1_attributes = {
            node.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == "runtime_authority_v1"
        }
        self.assertEqual(
            v1_attributes,
            {
                "ARTIFACT_KIND", "ASSESSMENT_KIND", "SCHEMA_VERSION",
                "BackendPublicationRuntimeAuthorityError",
                "assess_backend_publication_runtime_authority",
                "build_backend_publication_runtime_authority",
                "validate_backend_publication_runtime_authority",
            },
        )
        self.assertTrue(all(not name.startswith("_") for name in v1_attributes))
        called_names = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        self.assertFalse(any(
            "grant" in name or "readiness" in name
            for name in called_names
        ))
        imported_modules = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertFalse(any(
            "grant" in name or "readiness" in name
            for name in imported_modules
        ))

    def test_validation_requires_explicit_expected_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            authority, fields = build_fixture(root)
            with self.assertRaises(TypeError):
                validate_backend_publication_runtime_authority_v2(authority)
            expected = validation_expectations(fields)
            for name in (
                "expected_system", "expected_policy",
                "expected_topology_kind", "expected_codec",
            ):
                with self.subTest(name=name):
                    missing = copy.deepcopy(expected)
                    missing[name] = None
                    with self.assertRaisesRegex(
                        BackendPublicationRuntimeAuthorityV2Error, "is required",
                    ):
                        validate_backend_publication_runtime_authority_v2(
                            authority, **missing,
                        )


if __name__ == "__main__":
    unittest.main()
