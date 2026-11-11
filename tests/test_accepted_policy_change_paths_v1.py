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


class ChangeDirectoryV1Tests(unittest.TestCase):
    """R1: one rule for the change directory, in the helper and inline in the component fixture."""
    RELATIVE = "openspec/changes/" + CHANGE + "/evidence/compiler-component-01/index.json"

    def layouts(self):
        yield "active", (CHANGE,), True
        yield "archive", ("archive/2026-11-11-" + CHANGE,), True
        yield "archive with siblings", ("archive/2026-11-11-" + CHANGE, "archive/2026-10-05-fix-decoder-preflight",
                                        "archive/2026-11-12-other-" + CHANGE + "-x"), True
        yield "missing", (), False
        yield "active and archive", (CHANGE, "archive/2026-11-11-" + CHANGE), False
        yield "two archives", ("archive/2026-11-11-" + CHANGE, "archive/2026-11-12-" + CHANGE), False
        yield "impossible date", ("archive/2026-02-30-" + CHANGE,), False

    def build(self, root, entries):
        for entry in entries:
            (root / "openspec/changes" / entry / "evidence/compiler-component-01").mkdir(parents=True)

    def test_helper_and_component_resolve_the_same_directory_or_both_refuse(self):
        from tests.fixtures.accepted_policy_change_paths_v1 import change_directory_v1, current_path_v1
        from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
        for name, entries, valid in self.layouts():
            with self.subTest(layout=name), tempfile.TemporaryDirectory() as raw:
                root = Path(raw).resolve()
                self.build(root, entries)
                if valid:
                    expected = root / "openspec/changes" / entries[0]
                    self.assertEqual(change_directory_v1(root), expected)
                    self.assertEqual(current_path_v1(root, self.RELATIVE),
                                     expected / "evidence/compiler-component-01/index.json")
                    self.assertEqual(component._open_v1(root, self.RELATIVE), current_path_v1(root, self.RELATIVE))
                else:
                    with self.assertRaises(ValueError):
                        change_directory_v1(root)
                    with self.assertRaises(component.ComponentRecipeError):
                        component._open_v1(root, self.RELATIVE)

    def test_paths_outside_this_change_are_not_rewritten(self):
        from tests.fixtures.accepted_policy_change_paths_v1 import current_path_v1
        from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            for relative in ("tests/fixtures/x.py", "openspec/changes/another-change/evidence/x.json"):
                self.assertEqual(current_path_v1(root, relative), root / relative)
                self.assertEqual(component._open_v1(root, relative), root / relative)

    def test_an_aliased_change_directory_is_refused(self):
        from tests.fixtures.accepted_policy_change_paths_v1 import change_directory_v1
        from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()
            real = root / "elsewhere"
            (real / "evidence/compiler-component-01").mkdir(parents=True)
            (root / "openspec/changes/archive").mkdir(parents=True)
            (root / ("openspec/changes/archive/2026-11-11-" + CHANGE)).symlink_to(real, target_is_directory=True)
            with self.assertRaises(ValueError):
                change_directory_v1(root)
            with self.assertRaises(component.ComponentRecipeError):
                component._open_v1(root, self.RELATIVE)


if __name__ == "__main__":
    unittest.main()
