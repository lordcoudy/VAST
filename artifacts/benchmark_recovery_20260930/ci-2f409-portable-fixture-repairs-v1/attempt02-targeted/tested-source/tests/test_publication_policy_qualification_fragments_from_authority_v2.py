from __future__ import annotations

import copy
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

SCRIPT = SCRIPTS / "publication_policy_qualification_fragments_from_authority_v2.py"
SPEC = importlib.util.spec_from_file_location(
    "publication_policy_qualification_fragments_from_authority_v2", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
target = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = target
SPEC.loader.exec_module(target)
from test_checkpoint_deepstream_qualification_fragment_v1 import historical_worker_project


ACCEPTED_MANIFEST = ROOT / "configs/checkpoint_analytics_model_parity.accepted.yaml"
ACCEPTED_ASSESSMENT = (
    ROOT / "configs/checkpoint_analytics_model_parity.accepted.assessment.json"
)
ACCEPTED_RECEIPT = (
    ROOT / "configs/checkpoint_analytics_model_parity.accepted.acceptance_receipt.json"
)


def canonical(value: object) -> bytes:
    return target._canonical_bytes(value) + b"\n"


class Fixture:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.project_root = historical_worker_project(directory / "project")
        self.accepted_manifest = self.project_root / ACCEPTED_MANIFEST.relative_to(ROOT)
        self.accepted_assessment = self.project_root / ACCEPTED_ASSESSMENT.relative_to(ROOT)
        self.accepted_receipt = self.project_root / ACCEPTED_RECEIPT.relative_to(ROOT)
        sources = [target.POLICY_CONTRACT]
        omz = target._omz_bindings(ROOT)
        sources.extend(row[role]["path"] for row in omz.values() for role in ("model", "weights"))
        for relative in sources:
            destination = self.project_root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, destination)
        self.patch_path = self.project_root / "qualification_image_identity_patch.v1.json"
        manifest = yaml.safe_load(ACCEPTED_MANIFEST.read_text(encoding="utf-8"))
        workers = manifest["worker_runtime_registry"]
        worker_ids = {
            "cpu": workers["openvino_cpu"]["image_id"],
            "gpu": workers["tensorrt_cuda"]["image_id"],
        }
        self.inspections: dict[str, dict[str, object]] = {}
        worker_rows = {}
        for resource, image_id in worker_ids.items():
            observed = {
                "Id": image_id,
                "RepoDigests": [],
                "Architecture": "amd64",
                "Os": "linux",
                "Created": "2026-08-25T00:00:00Z",
                "Config": {
                    "Entrypoint": [f"/{resource}-worker"],
                    "User": "65532:65532",
                    "Labels": {"test.identity": resource},
                },
            }
            self.inspections[image_id] = observed
            worker_rows[resource] = {
                "name": f"analytics_worker_{resource}",
                "image": f"vast/{resource}-worker:publication-v3",
                "image_id": image_id,
                "image_inspect_sha256": target._canonical_sha(
                    target._inspect_projection(observed)
                ),
            }

        systems = {}
        for position, system in enumerate(target.SYSTEMS, start=3):
            image_id = "sha256:" + str(position) * 64
            repository = f"vast/{system}@{image_id}"
            final_reference = f"vast/{system}:materialized-attempt4"
            observed = {
                "Id": image_id,
                "RepoDigests": [repository],
                "Architecture": "amd64",
                "Os": "linux",
                "Created": "2026-08-25T00:00:00Z",
                "Config": {
                    "Entrypoint": [f"/opt/vast/{system}"],
                    "User": "root",
                    "Labels": {"test.system": system},
                },
            }
            self.inspections[final_reference] = observed
            if system == "savant":
                fragment_identity = {
                    "schema_version": 3,
                    "artifact_kind": "vast_savant_runtime_image_materialization_v3",
                    "image_id": image_id,
                    "repository_digests": [repository],
                    "entrypoint": [f"/opt/vast/{system}"],
                }
            else:
                fragment_identity = {
                    "image_id": image_id,
                    "repository_digest": repository,
                    "entrypoint": f"/opt/vast/{system}",
                    "inspect_projection_sha256": "a" * 64,
                    "base_image_id": "sha256:" + "b" * 64,
                }
            systems[system] = {
                "fragment_identity": fragment_identity,
                "physical_identity": {
                    "final_reference": final_reference,
                    "deterministic_references": [
                        final_reference + "-determinism-a",
                        final_reference + "-determinism-b",
                    ],
                    "image_id": image_id,
                    "inspect_full_sha256": target._canonical_sha(observed),
                },
            }
        self.patch = {
            "artifact_kind": target.PATCH_KIND,
            "patch_sha256": "9" * 64,
            "candidate_binding_eligible": True,
            "blockers": [],
            "workers": worker_rows,
            "systems": systems,
        }
        self.patch_path.write_bytes(canonical({"fixture": "physical-patch"}))

    def dependencies(self) -> target.FragmentAuthorityDependenciesV2:
        def load_patch(**_kwargs):
            return copy.deepcopy(self.patch)

        def load_v3(**_kwargs):
            return {
                "schema_version": 2,
                "artifact_kind": target.V3_BINDING_KIND,
                "receipt": target.file_descriptor(self.project_root, self.accepted_receipt),
                "accepted_manifest": target.file_descriptor(self.project_root, self.accepted_manifest),
                "accepted_assessment": target.file_descriptor(self.project_root, self.accepted_assessment),
                "binding_sha256": "8" * 64,
            }

        def load_v4(**_kwargs):  # pragma: no cover - v3 fixture must not branch here
            raise AssertionError("unexpected v4 loader")

        def inspect(_docker: str, reference: str):
            return copy.deepcopy(self.inspections[reference])

        return target.FragmentAuthorityDependenciesV2(
            load_identity_patch=load_patch,
            load_v3_acceptance=load_v3,
            load_v4_acceptance=load_v4,
            inspect_image=inspect,
        )

    def materialize(self):
        fragments_root = self.project_root / "fragments"
        fragments_root.mkdir()
        dependencies = self.dependencies()
        result = target.materialize_publication_policy_qualification_fragments_from_authority_v2(
            project_root=self.project_root,
            fragments_root=fragments_root,
            identity_patch_path=self.patch_path,
            accepted_model_parity_manifest_path=self.accepted_manifest,
            accepted_model_parity_assessment_path=self.accepted_assessment,
            accepted_model_parity_receipt_path=self.accepted_receipt,
            docker="docker",
            dependencies=dependencies,
        )
        return result, dependencies


class QualificationFragmentsFromAuthorityV2Tests(unittest.TestCase):
    def test_v4_probe_authority_projects_descriptor_and_cross_binds_implementation(self) -> None:
        descriptor = {
            "path": "artifacts/fixture.json",
            "size_bytes": 3,
            "sha256": "1" * 64,
        }
        implementations = {"cpu": "2" * 64, "gpu": "3" * 64}
        binding = {
            "binding_sha256": "4" * 64,
            "refresh_authority": {
                "image_identity_patch": {
                    **descriptor,
                    "patch_sha256": "5" * 64,
                    "refresh_blockers": list(target.REFRESH_BLOCKERS),
                    "resolved_blockers": [],
                },
                "workers": {
                    resource: {
                        "worker_implementation_sha256": implementation,
                    }
                    for resource, implementation in implementations.items()
                },
                "execution_config": {
                    **descriptor,
                    "content_identity_sha256": "6" * 64,
                    "worker_projection_sha256": "7" * 64,
                },
                "binding_set": {
                    "index": descriptor,
                    "identity_sha256": "8" * 64,
                    "bindings_identity_sha256": "9" * 64,
                    "bindings": {
                        f"{branch}:{resource}": {
                            **descriptor,
                            "path": f"artifacts/{branch}.{resource}.json",
                        }
                        for branch in target.BRANCHES
                        for resource in target.RESOURCES
                    },
                },
                "runtime_probes": {
                    resource: {
                        **descriptor,
                        "path": f"artifacts/{resource}.probe.json",
                        "worker_implementation_sha256": implementation,
                    }
                    for resource, implementation in implementations.items()
                },
            },
        }

        def descriptor_only(_root, value, *, label):
            self.assertEqual(set(value), target._DESCRIPTOR_FIELDS, label)
            return copy.deepcopy(value)

        with mock.patch.object(target, "_descriptor", side_effect=descriptor_only):
            normalized = target._normalize_v4_refresh_authority(ROOT, binding)
        self.assertEqual(
            normalized["runtime_probes"],
            {
                resource: {
                    **descriptor,
                    "path": f"artifacts/{resource}.probe.json",
                }
                for resource in target.RESOURCES
            },
        )

        binding["refresh_authority"]["runtime_probes"]["cpu"][
            "worker_implementation_sha256"
        ] = "a" * 64
        with mock.patch.object(target, "_descriptor", side_effect=descriptor_only):
            with self.assertRaisesRegex(
                target.QualificationFragmentsFromAuthorityV2Error,
                "implementation",
            ):
                target._normalize_v4_refresh_authority(ROOT, binding)

    def test_materializes_exact_four_fragments_and_forty_unique_bindings(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fragment-v2-", dir=ROOT / "artifacts") as raw:
            fixture = Fixture(Path(raw))
            result, dependencies = fixture.materialize()
            self.assertEqual(tuple(result), target.SYSTEMS)
            binding_paths = []
            for system in target.SYSTEMS:
                fragment = json.loads(result[system].read_bytes())
                self.assertEqual(fragment["system"], system)
                self.assertEqual(len(fragment["policy_bindings"]), 8)
                self.assertEqual(len(fragment["resource_bindings"]), 2)
                self.assertEqual(fragment["pilots"], [])
                binding_paths.extend(
                    fixture.project_root / row["path"]
                    for row in (
                        *fragment["policy_bindings"],
                        *fragment["resource_bindings"],
                    )
                )
            self.assertEqual(len(binding_paths), 40)
            self.assertEqual(len(set(binding_paths)), 40)
            self.assertTrue(all(path.is_file() for path in binding_paths))

            verified = target.validate_publication_policy_qualification_fragments_from_authority_v2(
                project_root=fixture.project_root,
                fragment_paths=result,
                identity_patch=fixture.patch,
                identity_patch_path=fixture.patch_path,
                accepted_model_parity_manifest_path=fixture.accepted_manifest,
                accepted_model_parity_assessment_path=fixture.accepted_assessment,
                accepted_model_parity_receipt_path=fixture.accepted_receipt,
                dependencies=dependencies,
            )
            self.assertEqual(set(verified), set(target.SYSTEMS))

            openvino = json.loads(
                next(
                    fixture.project_root / row["path"]
                    for row in json.loads(result["openvino_gva"].read_bytes())["policy_bindings"]
                    if row["branch"] == "plate_number" and row["resource"] == "cpu"
                ).read_bytes()
            )
            self.assertEqual(
                openvino["terminal_authority"],
                "external_analytics_execution_worker_only",
            )
            self.assertEqual(
                openvino["gva_sdk_binding_nonterminal"]["semantic_claim"],
                "topology_load_proxy_only",
            )
            self.assertEqual(
                openvino["runtime_identity"]["terminal_detector"],
                (
                    f"{openvino['analytics_execution_worker_binding_identity']['model_id']};"
                    "model_sha256="
                    f"{openvino['analytics_execution_worker_binding_identity']['source_model_sha256']}"
                ),
            )
            self.assertRegex(
                openvino["runtime_identity"]["terminal_backend"],
                r"^analytics-execution:openvino_cpu;runtime=[^;]+;"
                r"native_api=[^;]+;device=CPU:[^;]+$",
            )
            openvino_fragment = json.loads(result["openvino_gva"].read_bytes())
            openvino_gpu = json.loads(
                next(
                    fixture.project_root / row["path"]
                    for row in openvino_fragment["policy_bindings"]
                    if row["branch"] == "plate_number" and row["resource"] == "gpu"
                ).read_bytes()
            )
            self.assertRegex(
                openvino_gpu["runtime_identity"]["terminal_backend"],
                r"^analytics-execution:tensorrt_cuda;runtime=[^;]+;"
                r"native_api=[^;]+;device=NVIDIA_CUDA:[^;]+$",
            )
            self.assertEqual(
                openvino["openvino_gva_runtime_image"]["final_reference"],
                "vast/openvino_gva:materialized-attempt4",
            )

    def test_tampered_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fragment-v2-", dir=ROOT / "artifacts") as raw:
            fixture = Fixture(Path(raw))
            result, dependencies = fixture.materialize()
            fragment = json.loads(result["deepstream"].read_bytes())
            binding = fixture.project_root / fragment["policy_bindings"][0]["path"]
            binding.chmod(0o600)
            binding.write_bytes(binding.read_bytes().replace(b'"role":"policy"', b'"role":"tampered"'))
            with self.assertRaisesRegex(
                target.QualificationFragmentsFromAuthorityV2Error,
                "descriptor drifted|coordinate/self-identity",
            ):
                target.validate_publication_policy_qualification_fragments_from_authority_v2(
                    project_root=fixture.project_root,
                    fragment_paths=result,
                    identity_patch=fixture.patch,
                    identity_patch_path=fixture.patch_path,
                    accepted_model_parity_manifest_path=fixture.accepted_manifest,
                    accepted_model_parity_assessment_path=fixture.accepted_assessment,
                    accepted_model_parity_receipt_path=fixture.accepted_receipt,
                    dependencies=dependencies,
                )

    def test_stale_patch_cross_binding_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fragment-v2-", dir=ROOT / "artifacts") as raw:
            fixture = Fixture(Path(raw))
            result, dependencies = fixture.materialize()
            fixture.patch["patch_sha256"] = "7" * 64
            with self.assertRaisesRegex(
                target.QualificationFragmentsFromAuthorityV2Error,
                "stale or cross-bound|differs from physical authority",
            ):
                target.validate_publication_policy_qualification_fragments_from_authority_v2(
                    project_root=fixture.project_root,
                    fragment_paths=result,
                    identity_patch=fixture.patch,
                    identity_patch_path=fixture.patch_path,
                    accepted_model_parity_manifest_path=fixture.accepted_manifest,
                    accepted_model_parity_assessment_path=fixture.accepted_assessment,
                    accepted_model_parity_receipt_path=fixture.accepted_receipt,
                    dependencies=dependencies,
                )

    def test_v3_cannot_resolve_refresh_only_patch(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fragment-v2-", dir=ROOT / "artifacts") as raw:
            fixture = Fixture(Path(raw))
            fixture.patch["candidate_binding_eligible"] = False
            fixture.patch["blockers"] = list(target.REFRESH_BLOCKERS)
            with self.assertRaisesRegex(
                target.QualificationFragmentsFromAuthorityV2Error,
                "exact parity-refresh-only",
            ):
                target._load_patch_authority(
                    root=ROOT,
                    patch_path=fixture.patch_path,
                    parity={"version": 3},
                    dependencies=fixture.dependencies(),
                )

    def test_dangling_system_collision_is_never_treated_as_absent(self) -> None:
        with tempfile.TemporaryDirectory(prefix="fragment-v2-", dir=ROOT / "artifacts") as raw:
            fixture = Fixture(Path(raw))
            fragments_root = fixture.project_root / "fragments"
            fragments_root.mkdir()
            collision = fragments_root / "deepstream"
            collision.symlink_to(fragments_root / "missing", target_is_directory=True)
            with self.assertRaisesRegex(
                target.QualificationFragmentsFromAuthorityV2Error,
                "already exists",
            ):
                target.materialize_publication_policy_qualification_fragments_from_authority_v2(
                    project_root=fixture.project_root,
                    fragments_root=fragments_root,
                    identity_patch_path=fixture.patch_path,
                    accepted_model_parity_manifest_path=fixture.accepted_manifest,
                    accepted_model_parity_assessment_path=fixture.accepted_assessment,
                    accepted_model_parity_receipt_path=fixture.accepted_receipt,
                    dependencies=fixture.dependencies(),
                )
            self.assertTrue(collision.is_symlink())


if __name__ == "__main__":
    unittest.main()
