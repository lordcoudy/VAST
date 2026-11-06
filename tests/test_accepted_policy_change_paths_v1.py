"""Bounded active/archive layout checks without moving an actual OpenSpec change."""
import ast
from pathlib import Path
import tempfile
import unittest

from tests import test_accepted_policy_native_fixture_v2 as native_fixture_tests


CHANGE = "fix-accepted-policy-preprocessing"
ENTRYPOINTS = ("build_production_fixture_v2.py", "build_per_cell_minimum_refusal_v1.py")


class AcceptedPolicyChangePathsV1Tests(unittest.TestCase):
    def _resolve(self, root):
        from tests.fixtures.accepted_policy_change_paths_v1 import consumer_evidence_directory_v1
        return consumer_evidence_directory_v1(root)

    def _directory(self, root, archived=None):
        changes = root / "openspec/changes"
        change = changes / CHANGE if archived is None else changes / "archive" / archived
        directory = change / "evidence/consumer-01"
        directory.mkdir(parents=True)
        return directory

    def _entrypoint_module(self):
        return native_fixture_tests.AcceptedPolicyNativeFixtureV2Tests()._entrypoint()

    def test_actual_main_origin_expression_resolves_active_and_supported_archive(self):
        module = self._entrypoint_module()
        sources = {name: (Path(module.__file__).parent / name).read_bytes() for name in ENTRYPOINTS}
        with tempfile.TemporaryDirectory(prefix="accepted-policy-archive-origin-") as raw:
            root = Path(raw)
            for archive in (None, "2026-10-12-" + CHANGE):
                directory = self._directory(root, archive)
                for name, payload in sources.items():
                    entrypoint = directory / name
                    entrypoint.touch()
                    tree = ast.parse(payload)
                    main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
                    origin = next(node for node in main.body if isinstance(node, ast.Assign)
                                  and any(isinstance(target, ast.Name) and target.id == "source_root" for target in node.targets))
                    namespace = dict(vars(module), __file__=str(entrypoint))
                    exec(compile(ast.Module(body=[origin], type_ignores=[]), name, "exec"), namespace)
                    with self.subTest(archive=archive, entrypoint=name):
                        self.assertEqual(namespace["source_root"], root)

    def test_test_evidence_directory_resolves_active_change(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-active-path-") as raw:
            root = Path(raw)
            directory = self._directory(root)
            self.assertEqual(self._resolve(root), directory)

    def test_test_evidence_directory_resolves_one_supported_dated_archive(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-archive-path-") as raw:
            root = Path(raw)
            directory = self._directory(root, "2026-10-12-" + CHANGE)
            self.assertEqual(self._resolve(root), directory)

    def test_missing_evidence_directory_is_refused(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-missing-path-") as raw:
            with self.assertRaises(ValueError):
                self._resolve(Path(raw))

    def test_active_and_archive_evidence_are_ambiguous(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-ambiguous-path-") as raw:
            root = Path(raw)
            self._directory(root)
            self._directory(root, "2026-10-12-" + CHANGE)
            with self.assertRaises(ValueError):
                self._resolve(root)

    def test_multiple_supported_archives_are_ambiguous(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-multiple-archive-") as raw:
            root = Path(raw)
            self._directory(root, "2026-10-11-" + CHANGE)
            self._directory(root, "2026-10-12-" + CHANGE)
            with self.assertRaises(ValueError):
                self._resolve(root)

    def test_malformed_and_double_dated_archive_names_are_refused(self):
        for name in ("not-a-date-" + CHANGE, "2026-02-30-" + CHANGE,
                     "2026-10-12-2026-10-11-" + CHANGE):
            with self.subTest(name=name), tempfile.TemporaryDirectory(prefix="accepted-policy-malformed-archive-") as raw:
                root = Path(raw)
                self._directory(root, name)
                with self.assertRaises(ValueError):
                    self._resolve(root)

    def test_entrypoint_origin_refuses_missing_or_unsupported_layout(self):
        module = self._entrypoint_module()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-invalid-origin-") as raw:
            root = Path(raw)
            with self.assertRaises(ValueError):
                module._fixture_source_root_v2(root / "missing.py")
            for relative in (
                "elsewhere/evidence/consumer-01/build_production_fixture_v2.py",
                "openspec/changes/another-change/evidence/consumer-01/build_production_fixture_v2.py",
                "openspec/changes/archive/2026-02-30-" + CHANGE + "/evidence/consumer-01/build_production_fixture_v2.py",
            ):
                entrypoint = root / relative
                entrypoint.parent.mkdir(parents=True)
                entrypoint.touch()
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    module._fixture_source_root_v2(entrypoint)

    def test_entrypoint_origin_refuses_noncanonical_components(self):
        module = self._entrypoint_module()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-lexical-origin-") as raw:
            root = Path(raw)
            directory = self._directory(root)
            entrypoint = directory / ENTRYPOINTS[0]
            entrypoint.touch()
            with self.assertRaises(ValueError):
                module._fixture_source_root_v2(directory / ".." / "consumer-01" / ENTRYPOINTS[0])


if __name__ == "__main__":
    unittest.main()
