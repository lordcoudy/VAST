from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUBLICATION = ROOT / "deploy" / "savant" / "publication"
VALIDATOR = PUBLICATION / "validate_runtime_source_closure_v3.py"
MANIFEST = PUBLICATION / "runtime-source-allowlist.txt"
DOCKERFILE = PUBLICATION / "Dockerfile"
ENTRYPOINT = PUBLICATION / "vast_savant_checkpoint_runtime"
BUILD_SCRIPT = ROOT / "scripts" / "build_savant_publication_runtime_v3.sh"


def _validator_module():
    spec = importlib.util.spec_from_file_location(
        "validate_savant_runtime_source_closure_v3",
        VALIDATOR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load Savant runtime source-closure validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SavantRuntimeSourceClosureV3Tests(unittest.TestCase):
    def test_production_allowlist_is_exact_multi_entry_runtime_closure(self) -> None:
        module = _validator_module()
        result = module.validate_runtime_source_closure(
            project_root=ROOT,
            manifest_path=MANIFEST,
        )
        self.assertEqual(
            result["entry_modules"],
            (
                "checkpoint_savant_container_runtime_v3",
                "checkpoint_savant_sdk_runtime_v3",
            ),
        )
        self.assertEqual(
            set(result["build_only_sources"]),
            {
                "deploy/savant/publication/Dockerfile",
                "deploy/savant/publication/validate_runtime_source_closure_v3.py",
                "scripts/build_savant_publication_runtime_v3.sh",
                "scripts/materialize_runtime_build_context_v3.py",
            },
        )
        for required in (
            "scripts/analytics_execution_protocol.py",
            "scripts/benchmark_contract.py",
            "scripts/checkpoint_deepstream_protocol_bridge.py",
            "scripts/checkpoint_savant_native_module.py",
            "scripts/checkpoint_savant_protocol_adapter_v3.py",
            "scripts/freeze_kpp_iss_publication_v3.py",
            "scripts/kpp_iss_publication_v3_dataset.py",
            "deploy/native_gst_probe/checkpoint_source_coordinator.cpp",
        ):
            self.assertIn(required, result["all_sources"])
        for unrelated in (
            "scripts/checkpoint_gstreamer_publication_runtime_v3.py",
            "scripts/checkpoint_openvino_publication_runtime_v3.py",
            "scripts/checkpoint_savant_publication_runtime_v3.py",
            "scripts/checkpoint_savant_qualification_fragment_v3.py",
            "scripts/publication_policy_qualification.py",
            "deploy/savant/publication/savant_publication_runtime_v3.py",
        ):
            self.assertNotIn(unrelated, result["all_sources"])

    def test_missing_and_extraneous_transitive_imports_fail_closed(self) -> None:
        module = _validator_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
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
                    entry_modules=("entry",),
                )
            with self.assertRaisesRegex(ValueError, "extraneous Python source"):
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=(
                        "scripts/entry.py",
                        "scripts/helper.py",
                        "scripts/unused.py",
                    ),
                    entry_modules=("entry",),
                )
            self.assertEqual(
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=("scripts/entry.py", "scripts/helper.py"),
                    entry_modules=("entry",),
                ),
                ("scripts/entry.py", "scripts/helper.py"),
            )

    def test_constant_dynamic_local_import_is_in_the_reachable_set(self) -> None:
        module = _validator_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "entry.py").write_text(
                "helper = __import__('helper')\n",
                encoding="utf-8",
            )
            (scripts / "helper.py").write_text("value = 1\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "missing reachable Python source"):
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=("scripts/entry.py",),
                    entry_modules=("entry",),
                )

    def test_docker_copy_and_ab_build_use_only_validated_allowlist(self) -> None:
        module = _validator_module()
        result = module.validate_runtime_source_closure(
            project_root=ROOT, manifest_path=MANIFEST,
        )
        runtime_content = set(result["python_sources"]) | set(result["native_sources"])
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        begin = dockerfile.index("# BEGIN VAST_SAVANT_RUNTIME_SOURCE_ALLOWLIST")
        end = dockerfile.index("# END VAST_SAVANT_RUNTIME_SOURCE_ALLOWLIST")
        copy_block = dockerfile[begin:end]
        copied = {
            token.rstrip(" \\")
            for token in copy_block.split()
            if token.startswith("scripts/") or token.startswith("deploy/native_gst_probe/")
        }
        self.assertEqual(copied, runtime_content)
        self.assertNotIn("scripts/*.py", dockerfile)
        self.assertNotIn("savant_publication_runtime_v3.py", dockerfile)
        self.assertIn("--no-compile", dockerfile)
        self.assertIn("FROM ${SAVANT_BASE_IMAGE}", dockerfile)
        self.assertIn("FROM ${NATIVE_BUILDER_IMAGE} AS native-builder", dockerfile)

        build = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("base_build_ref", build)
        self.assertIn("native_builder_build_ref", build)
        self.assertIn('--build-arg "SAVANT_BASE_IMAGE=$base_build_ref"', build)
        self.assertIn('--build-arg "NATIVE_BUILDER_IMAGE=$native_builder_build_ref"', build)
        self.assertIn("validate_runtime_source_closure_v3.py", build)
        self.assertIn("runtime-source-allowlist.txt", build)
        self.assertIn("--no-cache", build)
        self.assertIn("--network=none", build)
        self.assertIn("first_id", build)
        self.assertIn("second_id", build)
        self.assertNotIn("find scripts -maxdepth 1", build)
        self.assertIn("runtime-dependency-allowlist.txt", build)
        self.assertIn("materialize_runtime_build_context_v3.py", build)
        self.assertIn(
            'build_context="$(mktemp -d /tmp/vast-savant-publication-v3.',
            build,
        )
        self.assertIn(
            '--file "$build_context/deploy/savant/publication/Dockerfile"',
            build,
        )
        self.assertIn('"$build_context"', build)

        entrypoint = ENTRYPOINT.read_text(encoding="utf-8")
        self.assertIn('"$1" != "arm"', entrypoint)
        self.assertIn("checkpoint_savant_container_runtime_v3.py", entrypoint)
        self.assertNotIn("savant_publication_runtime_v3.py", entrypoint)


if __name__ == "__main__":
    unittest.main()
