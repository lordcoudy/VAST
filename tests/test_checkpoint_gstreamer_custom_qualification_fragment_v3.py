from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_gstreamer_custom_qualification_fragment_v3 as target  # noqa: E402
from analytics_execution_endpoint import (  # noqa: E402
    expected_capability_from_binding_and_probe,
    terminal_detector_identity,
)


def expected_terminal_detector(artifact: dict[str, object], resource: str) -> str:
    binding_descriptor = artifact["analytics_execution_worker_binding"]
    probe_descriptor = artifact["analytics_runtime_probe"]
    assert isinstance(binding_descriptor, dict)
    assert isinstance(probe_descriptor, dict)
    binding = json.loads(
        (ROOT / str(binding_descriptor["path"])).read_text(encoding="utf-8")
    )
    probe = json.loads(
        (ROOT / str(probe_descriptor["path"])).read_text(encoding="utf-8")
    )
    capability = expected_capability_from_binding_and_probe(
        binding=binding,
        runtime_probe=probe,
        resource=resource,
    )
    return terminal_detector_identity(capability)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_runtime_source_sha256() -> str:
    validator = (
        ROOT / "deploy" / "gstreamer_custom" / "publication"
        / "validate_runtime_source_closure_v3.py"
    )
    manifest = validator.with_name("runtime-source-allowlist.txt")
    specification = importlib.util.spec_from_file_location(
        "qualification_gstreamer_source_closure_validator", validator,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError("failed to load GStreamer source closure validator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    result = module.validate_runtime_source_closure(
        project_root=ROOT, manifest_path=manifest,
    )
    rows = bytearray()
    for relative in result["all_sources"]:
        digest = hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        rows.extend(f"{digest}  {relative}\n".encode("ascii"))
    return hashlib.sha256(rows).hexdigest()


class GstreamerCustomQualificationFragmentV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._runtime_source_sha256 = target.GSTREAMER_RUNTIME_SOURCE_SHA256
        target.GSTREAMER_RUNTIME_SOURCE_SHA256 = current_runtime_source_sha256()

    def tearDown(self) -> None:
        target.GSTREAMER_RUNTIME_SOURCE_SHA256 = self._runtime_source_sha256

    def test_phase_one_materializes_exact_physical_binding_fragment(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            output = Path(temporary).resolve() / "qualification"
            result = target.materialize_qualification_fragment(
                project_root=ROOT,
                output_dir=output,
            )

            fragment_path = output / target.FRAGMENT_FILENAME
            self.assertEqual(result["fragment_path"], fragment_path)
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            self.assertEqual(
                set(fragment),
                {
                    "schema_version",
                    "artifact_kind",
                    "system",
                    "policy_bindings",
                    "resource_bindings",
                    "pilots",
                },
            )
            self.assertEqual(fragment["schema_version"], 1)
            self.assertEqual(
                fragment["artifact_kind"],
                "vast_publication_qualification_system_fragment_v1",
            )
            self.assertEqual(fragment["system"], "gstreamer_custom")
            self.assertEqual(fragment["pilots"], [])
            self.assertEqual(len(fragment["policy_bindings"]), 8)
            self.assertEqual(len(fragment["resource_bindings"]), 2)

            expected_policy_coordinates = {
                (branch, resource)
                for branch in target.BRANCHES
                for resource in target.RESOURCES
            }
            self.assertEqual(
                {
                    (row["branch"], row["resource"])
                    for row in fragment["policy_bindings"]
                },
                expected_policy_coordinates,
            )
            self.assertEqual(
                {
                    (row["branch"], row["resource"])
                    for row in fragment["resource_bindings"]
                },
                {("all_branches", "cpu"), ("all_branches", "gpu")},
            )

            identities: set[tuple[int, int]] = set()
            paths: set[str] = set()
            for row in (
                *fragment["policy_bindings"],
                *fragment["resource_bindings"],
            ):
                self.assertEqual(
                    set(row),
                    {
                        "role",
                        "branch",
                        "resource",
                        "path",
                        "sha256",
                        "size",
                        "implementation_id",
                        "emitter_id",
                        "runtime_identity",
                    },
                )
                artifact = ROOT / row["path"]
                info = artifact.lstat()
                self.assertTrue(stat.S_ISREG(info.st_mode))
                self.assertFalse(artifact.is_symlink())
                self.assertEqual(info.st_nlink, 1)
                self.assertEqual(info.st_size, row["size"])
                self.assertEqual(sha256_file(artifact), row["sha256"])
                self.assertNotIn(row["path"], paths)
                self.assertNotIn((info.st_dev, info.st_ino), identities)
                paths.add(row["path"])
                identities.add((info.st_dev, info.st_ino))

            self.assertEqual(len(paths), 10)
            self.assertEqual(len(identities), 10)
            assessment = target.assess_qualification_fragment(
                project_root=ROOT,
                fragment_path=fragment_path,
            )
            self.assertTrue(assessment["passed"], assessment["blockers"])
            self.assertEqual(assessment["coverage"], {
                "policy_binding_count": 8,
                "resource_binding_count": 2,
                "pilot_cell_count": 0,
            })

    def test_exact_accepted_parity_preprocessing_and_runtime_images_are_bound(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            output = Path(temporary).resolve() / "qualification"
            target.materialize_qualification_fragment(
                project_root=ROOT,
                output_dir=output,
            )
            fragment = json.loads(
                (output / target.FRAGMENT_FILENAME).read_text(encoding="utf-8")
            )
            for row in fragment["policy_bindings"]:
                artifact = json.loads((ROOT / row["path"]).read_text(encoding="utf-8"))
                self.assertEqual(
                    artifact["accepted_model_parity_manifest"],
                    {
                        "path": "configs/checkpoint_analytics_model_parity.refreshed.v4.a59.accepted.yaml",
                        "size_bytes": 29684,
                        "sha256": "766cc161ec0ab46d0dfc4e8d232a952fd0ffd118c5ce19acc694730be0f38643",
                        "content_identity_sha256": "6d5b87b63baaba29dc76b9b32d822e61b44b175326fa23182ea2a1207aa743d4",
                    },
                )
                self.assertEqual(
                    artifact["preprocessing_contract_sha256"],
                    "0307abfe6c5f652cc06f3f3df8ecf5050e5ed29b9ed5f40cb6fe728f47627090",
                )
                expected_worker = (
                    target.CPU_WORKER_IMAGE_ID
                    if row["resource"] == "cpu"
                    else target.GPU_WORKER_IMAGE_ID
                )
                self.assertEqual(
                    row["runtime_identity"]["worker_image_digest"],
                    expected_worker,
                )
                self.assertEqual(
                    row["runtime_identity"]["device_api"],
                    "CPU" if row["resource"] == "cpu" else "NVIDIA_CUDA",
                )
                self.assertEqual(
                    row["runtime_identity"]["gpu_id"],
                    None if row["resource"] == "cpu" else 0,
                )
                self.assertEqual(
                    artifact["gstreamer_runtime_image"]["image_id"],
                    target.GSTREAMER_IMAGE_ID,
                )
                self.assertEqual(
                    artifact["gstreamer_runtime_image"]["source_set"][
                        "runtime_source_sha256"
                    ],
                    target.GSTREAMER_RUNTIME_SOURCE_SHA256,
                )
                self.assertEqual(
                    artifact["gstreamer_runtime_image"]["source_set"]["validator"][
                        "path"
                    ],
                    "deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py",
                )
                self.assertEqual(
                    artifact["runtime_identity"]["terminal_detector"],
                    expected_terminal_detector(artifact, row["resource"]),
                )
                self.assertIn(
                    "analytics-execution:",
                    artifact["runtime_identity"]["terminal_backend"],
                )

    def test_materialization_is_idempotent_and_collision_or_fragment_drift_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            output = Path(temporary).resolve() / "qualification"
            first = target.materialize_qualification_fragment(
                project_root=ROOT,
                output_dir=output,
            )
            second = target.materialize_qualification_fragment(
                project_root=ROOT,
                output_dir=output,
            )
            self.assertEqual(first, second)

            fragment_path = output / target.FRAGMENT_FILENAME
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            fragment["unexpected"] = True
            fragment_path.write_text(
                json.dumps(fragment, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            assessment = target.assess_qualification_fragment(
                project_root=ROOT,
                fragment_path=fragment_path,
            )
            self.assertFalse(assessment["passed"])
            self.assertIn("fields", " ".join(assessment["blockers"]))
            with self.assertRaises(target.QualificationFragmentError):
                target.materialize_qualification_fragment(
                    project_root=ROOT,
                    output_dir=output,
                )

    def test_assessment_recomputes_and_rejects_stale_runtime_source_closure(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            output = Path(temporary).resolve() / "qualification"
            target.materialize_qualification_fragment(
                project_root=ROOT,
                output_dir=output,
            )
            with mock.patch.object(
                target, "GSTREAMER_RUNTIME_SOURCE_SHA256", "0" * 64,
            ):
                assessment = target.assess_qualification_fragment(
                    project_root=ROOT,
                    fragment_path=output / target.FRAGMENT_FILENAME,
                )
            self.assertFalse(assessment["passed"])
            self.assertIn(
                "transitive runtime source identity drifted",
                " ".join(assessment["blockers"]),
            )


if __name__ == "__main__":
    unittest.main()
