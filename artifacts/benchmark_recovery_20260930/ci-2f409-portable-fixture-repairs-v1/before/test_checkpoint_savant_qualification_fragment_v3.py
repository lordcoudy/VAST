from __future__ import annotations

import hashlib
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_savant_qualification_fragment_v3 as target  # noqa: E402


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SavantQualificationFragmentV3Tests(unittest.TestCase):
    def image_manifest(self, path: Path) -> Path:
        source_sha = target.runtime_source_sha256(ROOT)
        bundle_sha = target.runtime_bundle_sha256(ROOT)
        value = {
            "schema_version": 3,
            "artifact_kind": "vast_savant_runtime_image_materialization_v3",
            "image_id": "sha256:" + "c" * 64,
            "repository_digests": [],
            "inspect_projection_sha256": "d" * 64,
            "entrypoint": ["/usr/local/bin/vast_savant_checkpoint_runtime"],
            "architecture": "amd64",
            "os": "linux",
            "savant_version": "0.5.17",
            "deepstream_version": "7.0",
            "base_image_id": target.SAVANT_BASE_IMAGE_ID,
            "native_builder_image_id": target.NATIVE_BUILDER_IMAGE_ID,
            "native_builder_source_sha256": target.NATIVE_BUILDER_SOURCE_SHA256,
            "runtime_source_sha256": source_sha,
            "runtime_bundle_sha256": bundle_sha,
            "publication_ready_label": "false",
        }
        path.write_text(
            json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
            encoding="ascii",
        )
        return path

    def test_phase_one_materializes_ten_physical_bindings_and_no_pilots(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            base = Path(temporary).resolve()
            manifest = self.image_manifest(base / "runtime-image.json")
            output = base / "qualification"
            result = target.materialize_qualification_fragment(
                project_root=ROOT,
                output_dir=output,
                runtime_image_manifest=manifest,
            )
            fragment_path = output / target.FRAGMENT_FILENAME
            self.assertEqual(result["fragment_path"], fragment_path)
            fragment = json.loads(fragment_path.read_text(encoding="utf-8"))
            self.assertEqual(set(fragment), {
                "schema_version", "artifact_kind", "system",
                "policy_bindings", "resource_bindings", "pilots",
            })
            self.assertEqual(fragment["schema_version"], 1)
            self.assertEqual(
                fragment["artifact_kind"],
                "vast_publication_qualification_system_fragment_v1",
            )
            self.assertEqual(fragment["system"], "savant")
            self.assertEqual(fragment["pilots"], [])
            self.assertEqual(len(fragment["policy_bindings"]), 8)
            self.assertEqual(len(fragment["resource_bindings"]), 2)
            self.assertEqual(
                {(row["branch"], row["resource"])
                 for row in fragment["policy_bindings"]},
                {(branch, resource) for branch in target.BRANCHES
                 for resource in target.RESOURCES},
            )
            self.assertEqual(
                {(row["branch"], row["resource"])
                 for row in fragment["resource_bindings"]},
                {("all_branches", "cpu"), ("all_branches", "gpu")},
            )

            paths: set[str] = set()
            inodes: set[tuple[int, int]] = set()
            for row in (
                *fragment["policy_bindings"],
                *fragment["resource_bindings"],
            ):
                self.assertEqual(set(row), target.ROW_FIELDS)
                artifact = ROOT / row["path"]
                info = artifact.lstat()
                self.assertTrue(stat.S_ISREG(info.st_mode))
                self.assertFalse(artifact.is_symlink())
                self.assertEqual(info.st_nlink, 1)
                self.assertEqual(info.st_size, row["size"])
                self.assertEqual(sha256_file(artifact), row["sha256"])
                self.assertNotIn(row["path"], paths)
                self.assertNotIn((info.st_dev, info.st_ino), inodes)
                paths.add(row["path"])
                inodes.add((info.st_dev, info.st_ino))
            self.assertEqual(len(paths), 10)
            self.assertEqual(len(inodes), 10)

            assessment = target.assess_qualification_fragment(
                project_root=ROOT,
                fragment_path=fragment_path,
                runtime_image_manifest=manifest,
            )
            self.assertTrue(assessment["passed"], assessment["blockers"])
            self.assertEqual(assessment["coverage"], {
                "policy_binding_count": 8,
                "resource_binding_count": 2,
                "pilot_cell_count": 0,
            })

    def test_refreeze_and_exact_runtime_identity_fields_are_bound(self) -> None:
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as temporary:
            base = Path(temporary).resolve()
            manifest = self.image_manifest(base / "runtime-image.json")
            output = base / "qualification"
            target.materialize_qualification_fragment(
                project_root=ROOT, output_dir=output,
                runtime_image_manifest=manifest,
            )
            fragment = json.loads(
                (output / target.FRAGMENT_FILENAME).read_text(encoding="utf-8")
            )
            for row in fragment["policy_bindings"]:
                self.assertEqual(set(row["runtime_identity"]), target.POLICY_RUNTIME_FIELDS)
                self.assertEqual(
                    row["runtime_identity"]["worker_image_digest"],
                    target.CPU_WORKER_IMAGE_ID
                    if row["resource"] == "cpu" else target.GPU_WORKER_IMAGE_ID,
                )
                identity = row["runtime_identity"]
                if row["resource"] == "cpu":
                    self.assertEqual(identity["device_api"], "CPU")
                    self.assertIsNone(identity["gpu_id"])
                    self.assertIn("device=CPU", identity["terminal_backend"])
                else:
                    self.assertEqual(identity["device_api"], "NVIDIA_CUDA")
                    self.assertEqual(identity["gpu_id"], 0)
                    self.assertIn(
                        "device=NVIDIA_CUDA:0",
                        identity["terminal_backend"],
                    )
                artifact = json.loads((ROOT / row["path"]).read_text())
                self.assertEqual(
                    artifact["protocol_identity_sha256"],
                    target.PROTOCOL_IDENTITY_SHA256,
                )
                self.assertEqual(
                    artifact["accepted_model_parity_manifest"]["sha256"],
                    target.ACCEPTED_PARITY[2],
                )
            for row in fragment["resource_bindings"]:
                self.assertEqual(set(row["runtime_identity"]), target.RESOURCE_RUNTIME_FIELDS)
                self.assertEqual(
                    row["runtime_identity"]["worker_image_digest"],
                    "sha256:" + "c" * 64,
                )
                if row["resource"] == "cpu":
                    self.assertEqual(
                        row["runtime_identity"]["analytics_device_api"],
                        "HOST_CPU",
                    )

    def test_source_and_dependency_hashes_use_only_exact_build_inputs(self) -> None:
        manifest = (
            ROOT / "deploy" / "savant" / "publication"
            / "runtime-source-allowlist.txt"
        )
        source_paths = tuple(manifest.read_text(encoding="utf-8").splitlines())
        source_rows = bytearray()
        for relative in source_paths:
            source_rows.extend(
                f"{sha256_file(ROOT / relative)}  {relative}\n".encode("ascii")
            )
        self.assertEqual(
            target.runtime_source_sha256(ROOT),
            hashlib.sha256(source_rows).hexdigest(),
        )
        dependencies = [ROOT / "deploy/deepstream/checkpoint/requirements.lock"]
        dependencies.extend(
            (ROOT / "deploy/deepstream/checkpoint/wheels").glob("*")
        )
        dependency_rows = bytearray()
        for path in sorted(
            dependencies, key=lambda value: value.relative_to(ROOT).as_posix()
        ):
            relative = path.relative_to(ROOT).as_posix()
            dependency_rows.extend(
                f"{sha256_file(path)}  {relative}\n".encode("ascii")
            )
        self.assertEqual(
            target.runtime_bundle_sha256(ROOT),
            hashlib.sha256(dependency_rows).hexdigest(),
        )


if __name__ == "__main__":
    unittest.main()
