from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = (
    ROOT
    / "deploy"
    / "gstreamer_custom"
    / "publication"
    / "validate_runtime_source_closure_v3.py"
)
MANIFEST = (
    ROOT
    / "deploy"
    / "gstreamer_custom"
    / "publication"
    / "runtime-source-allowlist.txt"
)
DOCKERFILE = MANIFEST.with_name("Dockerfile")
BUILD_SCRIPT = ROOT / "scripts" / "build_gstreamer_custom_publication_runtime_v3.sh"


def _validator_module():
    spec = importlib.util.spec_from_file_location(
        "validate_gstreamer_runtime_source_closure_v3",
        VALIDATOR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load GStreamer runtime source-closure validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GStreamerCustomRuntimeSourceClosureV3Tests(unittest.TestCase):
    def test_production_allowlist_is_exact_reachable_runtime_closure(self) -> None:
        module = _validator_module()
        result = module.validate_runtime_source_closure(
            project_root=ROOT,
            manifest_path=MANIFEST,
        )
        self.assertEqual(result["entry_module"], "checkpoint_gstreamer_custom_container_coordinator_v3")
        self.assertIn("scripts/checkpoint_gstreamer_runtime.py", result["python_sources"])
        self.assertIn(
            "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
            result["native_sources"],
        )
        self.assertNotIn(
            "scripts/checkpoint_gstreamer_publication_runtime_v3.py",
            result["all_sources"],
        )
        self.assertNotIn(
            "scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py",
            result["all_sources"],
        )

    def test_missing_and_extraneous_python_imports_fail_closed(self) -> None:
        module = _validator_module()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "entry.py").write_text(
                "from helper import value\nprint(value)\n",
                encoding="utf-8",
            )
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
                    declared_paths=(
                        "scripts/entry.py",
                        "scripts/helper.py",
                        "scripts/unused.py",
                    ),
                    entry_module="entry",
                )
            self.assertEqual(
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=("scripts/entry.py", "scripts/helper.py"),
                    entry_module="entry",
                ),
                ("scripts/entry.py", "scripts/helper.py"),
            )

    def test_docker_copy_and_build_hash_use_only_the_validated_allowlist(self) -> None:
        declared = tuple(
            line
            for line in MANIFEST.read_text(encoding="utf-8").splitlines()
            if line
        )
        runtime_content = {
            path
            for path in declared
            if path.startswith("scripts/") or path.startswith("deploy/native_gst_probe/")
        }
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        begin = dockerfile.index("# BEGIN VAST_RUNTIME_SOURCE_ALLOWLIST")
        end = dockerfile.index("# END VAST_RUNTIME_SOURCE_ALLOWLIST")
        copy_block = dockerfile[begin:end]
        copied = {
            token.rstrip(" \\")
            for token in copy_block.split()
            if token.startswith("scripts/") or token.startswith("deploy/native_gst_probe/")
        }
        self.assertEqual(copied, runtime_content)
        self.assertNotIn("scripts/*.py", dockerfile)
        self.assertNotIn("COPY deploy/native_gst_probe/", dockerfile)

        build_script = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("runtime-source-allowlist.txt", build_script)
        self.assertIn("validate_runtime_source_closure_v3.py", build_script)
        self.assertNotIn("find scripts -maxdepth 1", build_script)
        self.assertNotIn("find deploy/native_gst_probe", build_script)


if __name__ == "__main__":
    unittest.main()
