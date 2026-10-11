"""Portable v2 producer checks; complete consumer qualification is explicit only."""
from pathlib import Path
import ast
import importlib
import inspect
import json
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

from tests.test_accepted_policy_production_validation import validate_native_cell, verified_fixture_manifest
from tests.fixtures.accepted_policy_native_fixture_v1 import write_native_policy_fixture_cell_v1
from tests.fixtures.accepted_policy_native_fixture_v2 import write_native_policy_fixture_cell_v2
from tests.fixtures.accepted_policy_change_paths_v1 import consumer_evidence_directory_v1


class AcceptedPolicyNativeFixtureV2Tests(unittest.TestCase):
    def test_v2_explicit_production_calls_match_actual_callable_keyword_signatures(self):
        root = Path(__file__).resolve().parents[1]
        files = [root / "tests/fixtures" / name for name in (
            "accepted_policy_physical_fixture_v2.py", "accepted_policy_consumer_fixture_v2.py",
            "accepted_policy_checkpoint_fixture_v1.py", "accepted_policy_consumer_assertions_v1.py")]
        checked = 0
        for path in files:
            tree = ast.parse(path.read_bytes(), filename=str(path))
            imported = {}
            modules = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and not node.module.startswith("tests."):
                    module = importlib.import_module(node.module)
                    imported.update({alias.asname or alias.name: getattr(module, alias.name)
                                     for alias in node.names if alias.name != "*"})
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        module = importlib.import_module(alias.name)
                        modules[alias.asname or alias.name] = module
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if isinstance(node.func, ast.Name):
                    target = imported.get(node.func.id)
                elif isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name):
                    target = getattr(modules.get(node.func.value.id), node.func.attr, None)
                else:
                    continue
                if not inspect.isfunction(target):
                    continue
                target_file = Path(inspect.getfile(target)).resolve(strict=True)
                if not target_file.is_relative_to(root / "scripts"):
                    continue
                with self.subTest(file=path.name, line=node.lineno, function=target.__name__):
                    inspect.signature(target, follow_wrapped=False).bind_partial(
                        *[object() for argument in node.args if not isinstance(argument, ast.Starred)],
                        **{keyword.arg: object() for keyword in node.keywords if keyword.arg is not None})
                checked += 1
        self.assertGreaterEqual(checked, 25)
        physical = ast.parse(files[0].read_bytes())
        runtime_calls = [node for node in ast.walk(physical) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Name)
                         and node.func.id == "materialize_publication_policy_qualification_runtime_inputs_v2"]
        self.assertEqual(len(runtime_calls), 1)
        keys = {keyword.arg for keyword in runtime_calls[0].keywords}
        self.assertIn("operational_capture_plan_path", keys)
        self.assertNotIn("operational_capture_plan", keys)

    def _entrypoint(self):
        root = Path(__file__).resolve().parents[1]
        path = consumer_evidence_directory_v1(root) / "build_production_fixture_v2.py"
        spec = importlib.util.spec_from_file_location("fixture_entrypoint_path_checks_v2", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_explicit_fixture_paths_refuse_parent_traversal_before_writes(self):
        entrypoint = self._entrypoint()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-path-boundary-") as raw:
            root = Path(raw) / "source"
            root.mkdir()
            (root / "artifacts").mkdir()
            for value in ("../outside", "artifacts/../../outside", str(root / ".." / "outside")):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    entrypoint._canonical_fixture_directory_v2(value, root=root, fresh=True)
            with self.assertRaises(ValueError):
                entrypoint._canonical_fixture_root_v2(root / ".." / "source", source_root=root)
            self.assertFalse((Path(raw) / "outside").exists())
            self.assertEqual(entrypoint._canonical_fixture_directory_v2("artifacts", root=root, fresh=False), root / "artifacts")
            self.assertEqual(entrypoint._canonical_fixture_directory_v2("artifacts/fresh", root=root, fresh=True), root / "artifacts/fresh")

    def test_explicit_fixture_paths_refuse_symlinked_ancestors_before_writes(self):
        entrypoint = self._entrypoint()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-path-alias-") as raw:
            root = Path(raw) / "source"
            root.mkdir()
            real = root / "real"
            real.mkdir()
            alias = root / "alias"
            os.symlink(real, alias, target_is_directory=True)
            with self.assertRaises(ValueError):
                entrypoint._canonical_fixture_directory_v2(alias, root=root, fresh=False)
            with self.assertRaises(ValueError):
                entrypoint._canonical_fixture_directory_v2(alias / "fresh", root=root, fresh=True)
            root_alias = Path(raw) / "root-alias"
            os.symlink(root, root_alias, target_is_directory=True)
            with self.assertRaises(ValueError):
                entrypoint._canonical_fixture_root_v2(root_alias, source_root=root)
            self.assertFalse((real / "fresh").exists())

    def test_explicit_fixture_initial_imports_fit_unchanged_executor_source_closure(self):
        root = Path(__file__).resolve().parents[1]
        program = (
            "import sys,json; from pathlib import Path; sys.path.insert(0,'scripts'); "
            "from tests.fixtures import accepted_policy_consumer_fixture_v2; "
            "from publication_policy_qualification_execution_code_closure_v1 import _discover_sources; "
            "from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1; "
            "root=Path.cwd(); allowed={str(path) for _,path in _discover_sources(root)}; "
            "records=loaded_fixture_production_sources_v1(project_root=root); "
            "print(json.dumps([row['module'] for row in records if row['loaded_path'] not in allowed]))"
        )
        completed = subprocess.run([sys.executable, "-B", "-c", program], cwd=root,
                                   check=True, capture_output=True, text=True)
        self.assertEqual(json.loads(completed.stdout), [])

    def test_explicit_consumer_helpers_retain_selected_production_source_provenance(self):
        from tests.fixtures import accepted_policy_consumer_fixture_v2
        from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1

        root = Path(__file__).resolve().parents[1]
        records = loaded_fixture_production_sources_v1(project_root=root)
        self.assertTrue(records)
        self.assertTrue(all(Path(row["loaded_path"]).is_relative_to(root / "scripts") for row in records))
        self.assertTrue(callable(accepted_policy_consumer_fixture_v2.complete_fixture_production_consumers_v2))
        entrypoint = consumer_evidence_directory_v1(root) / "build_production_fixture_v2.py"
        compile(entrypoint.read_bytes(), str(entrypoint), "exec")

    def test_data_only_rows_preserve_real_validated_cpu_and_gpu_observations(self):
        manifest = verified_fixture_manifest()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-fixture-v2-") as raw:
            root = Path(raw)
            for resource in ("cpu", "gpu"):
                with self.subTest(resource=resource):
                    results = []
                    for version, producer in (("v1", write_native_policy_fixture_cell_v1),
                                               ("v2", write_native_policy_fixture_cell_v2)):
                        output = root / resource / version
                        metadata = producer(output_dir=output, capability=manifest, system="gstreamer_custom",
                                            resource=resource, codec="h264", topology_kind="shared_video_dag",
                                            samples_per_branch=31, dropped_ingress=resource == "gpu")
                        frames, sidecars = validate_native_cell(output, metadata, "shared_video_dag")
                        self.assertEqual(len(frames), 31)
                        self.assertTrue(sidecars["reset_evidence"]["reset_claim_eligible"].all())
                        self.assertTrue(sidecars["resource_intervals"].attrs["full_resource_summary"]["full_resource_coverage_complete"])
                        results.append({path.name: path.read_bytes() for path in output.iterdir()
                                        if path.suffix in {".csv", ".jsonl"}})
                    self.assertEqual(results[0], results[1])


if __name__ == "__main__":
    unittest.main()
