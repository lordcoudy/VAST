from __future__ import annotations

import hashlib
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MATERIALIZER = ROOT / "scripts" / "materialize_runtime_build_context_v3.py"


def _module():
    spec = importlib.util.spec_from_file_location(
        "materialize_runtime_build_context_v3", MATERIALIZER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load runtime build-context materializer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _aggregate(root: Path, relative_paths: tuple[str, ...]) -> str:
    rows = bytearray()
    for relative in sorted(relative_paths):
        digest = hashlib.sha256((root / relative).read_bytes()).hexdigest()
        rows.extend(f"{digest}  {relative}\n".encode("ascii"))
    return hashlib.sha256(rows).hexdigest()


class RuntimeBuildContextV3Tests(unittest.TestCase):
    def _fixture(self, parent: Path) -> tuple[Path, tuple[Path, Path], tuple[str, ...]]:
        project = parent / "project"
        (project / "manifests").mkdir(parents=True)
        (project / "runtime").mkdir()
        (project / "bundle").mkdir()
        (project / "runtime" / "entry.py").write_text(
            "value = 'runtime'\n", encoding="utf-8",
        )
        (project / "bundle" / "requirements.lock").write_text(
            "dependency==1 --hash=sha256:" + "a" * 64 + "\n",
            encoding="ascii",
        )
        (project / "bundle" / "dependency.whl").write_bytes(b"wheel-bytes")
        source_manifest = project / "manifests" / "runtime.txt"
        dependency_manifest = project / "manifests" / "dependencies.txt"
        source_manifest.write_bytes(
            b"manifests/dependencies.txt\n"
            b"manifests/runtime.txt\n"
            b"runtime/entry.py\n"
        )
        dependency_manifest.write_bytes(
            b"bundle/dependency.whl\n"
            b"bundle/requirements.lock\n"
        )
        paths = (
            "bundle/dependency.whl",
            "bundle/requirements.lock",
            "manifests/dependencies.txt",
            "manifests/runtime.txt",
            "runtime/entry.py",
        )
        return project, (source_manifest, dependency_manifest), paths

    def test_materializes_only_manifest_union_with_frozen_metadata(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, expected = self._fixture(parent)
            output = parent / "context"
            output.mkdir()
            result = module.materialize_runtime_build_context(
                project_root=project,
                output_dir=output,
                manifest_paths=manifests,
                source_date_epoch=1_722_470_400,
            )
            observed = tuple(sorted(
                path.relative_to(output).as_posix()
                for path in output.rglob("*") if path.is_file()
            ))
            self.assertEqual(observed, expected)
            self.assertEqual(result["relative_paths"], expected)
            self.assertEqual(result["aggregate_sha256"], _aggregate(output, expected))
            for relative in expected:
                path = output / relative
                self.assertEqual(path.read_bytes(), (project / relative).read_bytes())
                self.assertEqual(int(path.stat().st_mtime), 1_722_470_400)
                if os.name == "posix":
                    self.assertEqual(path.stat().st_mode & 0o777, 0o444)

    def test_rejects_nonempty_or_project_internal_output(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            internal = project / "context"
            internal.mkdir()
            with self.assertRaisesRegex(ValueError, "outside project root"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=internal,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            output = parent / "context"
            output.mkdir()
            (output / "foreign").write_text("do not overwrite", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "must be empty"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )

    def test_rejects_hardlinked_source_without_partial_copy(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            os.link(
                project / "bundle" / "dependency.whl",
                project / "bundle" / "dependency.alias.whl",
            )
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "single-link"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])

    def test_rejects_manifest_path_escape_and_member_escape(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            outside_manifest = parent / "outside.txt"
            outside_manifest.write_bytes(b"runtime/entry.py\n")
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "manifest escapes project root"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=(outside_manifest,),
                    source_date_epoch=0,
                )

            manifests[0].write_bytes(b"../outside.txt\n")
            with self.assertRaisesRegex(ValueError, "not canonical and relative"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])

    def test_rejects_source_replacement_before_held_copy(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            output = parent / "context"
            output.mkdir()
            original = module._copy_held_source
            replaced = False

            def replace_then_copy(source, destination, **kwargs):
                nonlocal replaced
                if not replaced:
                    replaced = True
                    source.write_bytes(source.read_bytes() + b"drift")
                return original(source, destination, **kwargs)

            with mock.patch.object(module, "_copy_held_source", replace_then_copy):
                with self.assertRaisesRegex(ValueError, "changed before copy"):
                    module.materialize_runtime_build_context(
                        project_root=project,
                        output_dir=output,
                        manifest_paths=manifests,
                        source_date_epoch=0,
                    )

    def test_rejects_concurrently_injected_empty_directory(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            output = parent / "context"
            output.mkdir()
            original = module._copy_held_source
            injected = False

            def copy_then_inject(source, destination, **kwargs):
                nonlocal injected
                digest = original(source, destination, **kwargs)
                if not injected:
                    injected = True
                    (output / "foreign-empty-directory").mkdir()
                return digest

            with mock.patch.object(module, "_copy_held_source", copy_then_inject):
                with self.assertRaisesRegex(ValueError, "inventory drifted"):
                    module.materialize_runtime_build_context(
                        project_root=project,
                        output_dir=output,
                        manifest_paths=manifests,
                        source_date_epoch=0,
                    )

    @unittest.skipUnless(os.name == "posix", "symlink fixture requires POSIX")
    def test_rejects_symlinked_manifest_member_without_partial_copy(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            target = project / "runtime" / "entry.py"
            target.unlink()
            target.symlink_to(project / "bundle" / "requirements.lock")
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "physical single-link regular file"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=manifests,
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])

    @unittest.skipUnless(os.name == "posix", "symlink fixture requires POSIX")
    def test_rejects_symlinked_manifest_itself(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            project, manifests, _ = self._fixture(parent)
            alias = project / "manifests" / "runtime-alias.txt"
            alias.symlink_to(manifests[0])
            output = parent / "context"
            output.mkdir()
            with self.assertRaisesRegex(ValueError, "physical single-link regular file"):
                module.materialize_runtime_build_context(
                    project_root=project,
                    output_dir=output,
                    manifest_paths=(alias, manifests[1]),
                    source_date_epoch=0,
                )
            self.assertEqual(list(output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
