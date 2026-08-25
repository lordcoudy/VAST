from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY = ROOT / "deploy" / "openvino_gva" / "publication"
VALIDATOR = DEPLOY / "validate_runtime_source_closure_v3.py"
MANIFEST = DEPLOY / "runtime-source-allowlist.txt"


def _module():
    spec = importlib.util.spec_from_file_location(
        "validate_openvino_gva_runtime_source_closure_v3", VALIDATOR
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load OpenVINO GVA source closure validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpenVINOGVARuntimeSourceClosureV3Tests(unittest.TestCase):
    def test_production_allowlist_is_exact_transitive_closure(self) -> None:
        result = _module().validate_runtime_source_closure(
            project_root=ROOT,
            manifest_path=MANIFEST,
        )
        self.assertEqual(
            result["entry_module"],
            "checkpoint_openvino_gva_container_coordinator_v3",
        )
        self.assertIn("scripts/checkpoint_gstreamer_runtime.py", result["python_sources"])
        self.assertIn(
            "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
            result["native_sources"],
        )
        self.assertNotIn(
            "deploy/openvino_gva/publication/runtime-source-allowlist.txt",
            result["all_sources"],
        )
        self.assertNotIn(
            "scripts/checkpoint_openvino_gva_qualification_fragment_v3.py",
            result["all_sources"],
        )

    def test_missing_and_extraneous_imports_fail_closed(self) -> None:
        module = _module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "entry.py").write_text("from helper import value\n", encoding="utf-8")
            (scripts / "helper.py").write_text("value = 1\n", encoding="utf-8")
            (scripts / "unused.py").write_text("value = 2\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing reachable Python source"):
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=("scripts/entry.py",),
                    entry_module="entry",
                )
            with self.assertRaisesRegex(ValueError, "extraneous Python source"):
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=("scripts/entry.py", "scripts/helper.py", "scripts/unused.py"),
                    entry_module="entry",
                )


if __name__ == "__main__":
    unittest.main()
