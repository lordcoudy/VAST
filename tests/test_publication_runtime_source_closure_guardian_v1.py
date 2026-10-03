from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GUARDIAN_QUALIFICATION_SOURCES = (
    "scripts/checkpoint_deepstream_qualification_fragment_v1.py",
    "scripts/checkpoint_qualification_pilot_acceptance_v1.py",
    "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py",
    "scripts/publication_guardian_preprocessing_contract_v1.py",
    "scripts/publication_guardian_runtime_expectations_v1.py",
    "scripts/publication_policy_qualification.py",
    "scripts/publication_policy_qualification_execution_closure_v1.py",
)
RUNTIMES = {
    "deepstream": (
        "deploy/deepstream/checkpoint/validate_runtime_source_closure_v3.py",
        "deploy/deepstream/checkpoint/runtime-source-allowlist.txt",
    ),
    "savant": (
        "deploy/savant/publication/validate_runtime_source_closure_v3.py",
        "deploy/savant/publication/runtime-source-allowlist.txt",
    ),
    "openvino_gva": (
        "deploy/openvino_gva/publication/validate_runtime_source_closure_v3.py",
        "deploy/openvino_gva/publication/runtime-source-allowlist.txt",
    ),
    "gstreamer_custom": (
        "deploy/gstreamer_custom/publication/validate_runtime_source_closure_v3.py",
        "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt",
    ),
}


def _validator(system: str, relative: str):
    specification = importlib.util.spec_from_file_location(
        f"test_{system}_runtime_source_closure_v3", ROOT / relative,
    )
    if specification is None or specification.loader is None:
        raise RuntimeError(f"cannot load {system} runtime source validator")
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


def _validate_python(module, declared: tuple[str, ...]) -> tuple[str, ...]:
    if hasattr(module, "ENTRY_MODULES"):
        return module.validate_python_source_closure(
            project_root=ROOT,
            declared_paths=declared,
            entry_modules=module.ENTRY_MODULES,
        )
    return module.validate_python_source_closure(
        project_root=ROOT,
        declared_paths=declared,
        entry_module=module.ENTRY_MODULE,
    )


class PublicationRuntimeSourceClosureGuardianV1Tests(unittest.TestCase):
    def test_all_runtime_validators_accept_the_same_guardian_closure(self) -> None:
        for system, (validator_path, manifest_path) in RUNTIMES.items():
            with self.subTest(system=system):
                module = _validator(system, validator_path)
                declared = tuple(
                    value
                    for value in (ROOT / manifest_path).read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if value.startswith("scripts/")
                    and value.endswith(".py")
                    and value not in getattr(module, "BUILD_ONLY_SOURCES", set())
                )
                self.assertTrue(
                    set(GUARDIAN_QUALIFICATION_SOURCES).issubset(declared)
                )
                self.assertEqual(_validate_python(module, declared), declared)

    def test_all_runtime_validators_reject_the_same_missing_guardian_closure(
        self,
    ) -> None:
        expected = (
            "missing reachable Python source: "
            + ", ".join(GUARDIAN_QUALIFICATION_SOURCES)
        )
        for system, (validator_path, manifest_path) in RUNTIMES.items():
            with self.subTest(system=system):
                module = _validator(system, validator_path)
                declared = tuple(
                    value
                    for value in (ROOT / manifest_path).read_text(
                        encoding="utf-8"
                    ).splitlines()
                    if value.startswith("scripts/")
                    and value.endswith(".py")
                    and value not in getattr(module, "BUILD_ONLY_SOURCES", set())
                    and value not in GUARDIAN_QUALIFICATION_SOURCES
                )
                with self.assertRaisesRegex(ValueError, f"^{re.escape(expected)}$"):
                    _validate_python(module, declared)


if __name__ == "__main__":
    unittest.main()
