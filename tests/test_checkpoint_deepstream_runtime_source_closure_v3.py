from __future__ import annotations

import importlib.util
import os
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKPOINT = ROOT / "deploy" / "deepstream" / "checkpoint"
VALIDATOR = CHECKPOINT / "validate_runtime_source_closure_v3.py"
MANIFEST = CHECKPOINT / "runtime-source-allowlist.txt"
DEPENDENCIES = CHECKPOINT / "runtime-dependency-allowlist.txt"
DOCKERFILE = CHECKPOINT / "Dockerfile.runtime"
BUILD_SCRIPT = ROOT / "scripts" / "build_deepstream_publication_runtime_v3.sh"


def _validator_module():
    spec = importlib.util.spec_from_file_location(
        "validate_deepstream_runtime_source_closure_v3", VALIDATOR,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("failed to load DeepStream runtime source validator")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DeepStreamRuntimeSourceClosureV3Tests(unittest.TestCase):
    def test_production_allowlist_is_exact_multi_entry_runtime_closure(self) -> None:
        module = _validator_module()
        result = module.validate_runtime_source_closure(
            project_root=ROOT,
            manifest_path=MANIFEST,
        )
        self.assertEqual(
            result["entry_modules"],
            (
                "checkpoint_deepstream_container_runtime_v3",
                "checkpoint_deepstream_sdk_runtime",
            ),
        )
        self.assertEqual(
            set(result["build_only_sources"]),
            {
                "deploy/deepstream/checkpoint/Dockerfile.runtime",
                "deploy/deepstream/checkpoint/validate_runtime_source_closure_v3.py",
                "scripts/build_deepstream_publication_runtime_v3.sh",
                "scripts/materialize_runtime_build_context_v3.py",
            },
        )
        for required in (
            "scripts/analytics_execution_protocol.py",
            "scripts/benchmark_contract.py",
            "scripts/checkpoint_deepstream_launcher.py",
            "scripts/checkpoint_deepstream_sdk_runtime.py",
            "deploy/native_gst_probe/checkpoint_admission_transport.hpp",
            "deploy/native_gst_probe/checkpoint_source_coordinator.cpp",
            "deploy/deepstream/checkpoint/vast_deepstream_meta_bridge.cpp",
            "deploy/deepstream/checkpoint/vast_deepstream_meta_bridge.h",
        ):
            self.assertIn(required, result["all_sources"])
        for unrelated in (
            "CMakeLists.txt",
            "scripts/checkpoint_openvino_execution_bridge.py",
            "scripts/checkpoint_savant_container_runtime_v3.py",
            "scripts/publication_policy_qualification.py",
            "scripts/run_experiments.py",
        ):
            self.assertNotIn(unrelated, result["all_sources"])

    def test_missing_extraneous_and_unrelated_module_drift_fail_as_expected(self) -> None:
        module = _validator_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "entry.py").write_text(
                "from helper import value\nprint(value)\n", encoding="utf-8",
            )
            (scripts / "helper.py").write_text("value = 1\n", encoding="utf-8")
            unrelated = scripts / "unrelated.py"
            unrelated.write_text("value = 2\n", encoding="utf-8")
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
                        "scripts/entry.py", "scripts/helper.py", "scripts/unrelated.py",
                    ),
                    entry_modules=("entry",),
                )
            expected = ("scripts/entry.py", "scripts/helper.py")
            self.assertEqual(
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=expected,
                    entry_modules=("entry",),
                ),
                expected,
            )
            unrelated.write_text("value = 'drifted but unreachable'\n", encoding="utf-8")
            self.assertEqual(
                module.validate_python_source_closure(
                    project_root=root,
                    declared_paths=expected,
                    entry_modules=("entry",),
                ),
                expected,
            )

    def test_docker_copy_and_isolated_build_context_match_validated_sets(self) -> None:
        module = _validator_module()
        result = module.validate_runtime_source_closure(
            project_root=ROOT, manifest_path=MANIFEST,
        )
        dockerfile = DOCKERFILE.read_text(encoding="utf-8")
        begin = dockerfile.index("# BEGIN VAST_DEEPSTREAM_RUNTIME_SOURCE_ALLOWLIST")
        end = dockerfile.index("# END VAST_DEEPSTREAM_RUNTIME_SOURCE_ALLOWLIST")
        copied = {
            token.rstrip(" \\")
            for token in dockerfile[begin:end].split()
            if token.startswith("scripts/") or token.startswith("deploy/")
        }
        self.assertEqual(copied, set(result["docker_copy_sources"]))
        self.assertNotIn("COPY scripts/*.py", dockerfile)
        self.assertNotIn("COPY deploy/native_gst_probe ", dockerfile)

        dependencies = tuple(DEPENDENCIES.read_text(encoding="utf-8").splitlines())
        dependency_begin = dockerfile.index("# BEGIN VAST_RUNTIME_DEPENDENCY_ALLOWLIST")
        dependency_end = dockerfile.index("# END VAST_RUNTIME_DEPENDENCY_ALLOWLIST")
        dependency_copy = {
            token.rstrip(" \\")
            for token in dockerfile[dependency_begin:dependency_end].split()
            if token.startswith("deploy/")
        }
        self.assertEqual(dependency_copy, set(dependencies))

        build = BUILD_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("validate_runtime_source_closure_v3.py", build)
        self.assertIn("runtime-source-allowlist.txt", build)
        self.assertIn("runtime-dependency-allowlist.txt", build)
        self.assertIn("materialize_runtime_build_context_v3.py", build)
        self.assertIn('build_context="$(mktemp -d /tmp/vast-deepstream-publication-v3.', build)
        self.assertIn('--file "$build_context/deploy/deepstream/checkpoint/Dockerfile.runtime"', build)
        self.assertIn('"$build_context"', build)
        self.assertNotIn("find scripts", build)
        self.assertNotIn("find deploy/native_gst_probe", build)
        self.assertIn("first_id", build)
        self.assertIn("second_id", build)

    @unittest.skipUnless(os.name == "posix", "symlink fixture requires POSIX")
    def test_dependency_closure_rejects_extraneous_symlinked_wheel(self) -> None:
        module = _validator_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            checkpoint = root / "deploy" / "deepstream" / "checkpoint"
            wheels = checkpoint / "wheels"
            wheels.mkdir(parents=True)
            requirements = checkpoint / "requirements.lock"
            wheel = wheels / "dependency-1-py3-none-any.whl"
            requirements.write_text("dependency==1\n", encoding="utf-8")
            wheel.write_bytes(b"physical-wheel")
            manifest = checkpoint / "runtime-dependency-allowlist.txt"
            manifest.write_text(
                "deploy/deepstream/checkpoint/requirements.lock\n"
                "deploy/deepstream/checkpoint/wheels/dependency-1-py3-none-any.whl\n",
                encoding="utf-8",
            )
            self.assertEqual(
                module.validate_dependency_source_closure(
                    project_root=root, manifest_path=manifest,
                ),
                tuple(manifest.read_text(encoding="utf-8").splitlines()),
            )
            (wheels / "extraneous.whl").symlink_to(wheel)
            with self.assertRaisesRegex(ValueError, "wheel dependency set drifted"):
                module.validate_dependency_source_closure(
                    project_root=root, manifest_path=manifest,
                )


if __name__ == "__main__":
    unittest.main()
