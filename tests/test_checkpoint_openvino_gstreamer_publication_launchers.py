from __future__ import annotations

import copy
import importlib.util
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stderr
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(ROOT / "tests"))

from backend_publication_output_receipt import (  # noqa: E402
    ARM_CONTRACT_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
    write_immutable_backend_publication_arm_contract,
)
from test_backend_publication_output_receipt import (  # noqa: E402
    arm_contract,
    canonical_sha,
)

import checkpoint_gstreamer_custom_publication_launcher as gstreamer_custom  # noqa: E402
import checkpoint_openvino_gva_publication_launcher as openvino_gva  # noqa: E402


def contract_for(root: Path, system: str) -> dict[str, object]:
    value = copy.deepcopy(arm_contract(root))
    dispatch = value["dispatch_resolution"]
    runtime = value["runtime_inputs"]
    assert isinstance(dispatch, dict)
    assert isinstance(runtime, dict)
    dispatch["system"] = system
    dispatch.pop("resolution_sha256")
    dispatch["resolution_sha256"] = canonical_sha(dispatch)
    runtime["system"] = system
    value.pop("contract_sha256")
    value["contract_sha256"] = canonical_sha(value)
    return value


def output_tree_snapshot(root: Path) -> list[tuple[object, ...]]:
    snapshot: list[tuple[object, ...]] = []
    for path in sorted(root.iterdir(), key=lambda item: item.name):
        info = path.stat()
        snapshot.append((
            path.name,
            path.read_bytes(),
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
            info.st_nlink,
        ))
    return snapshot


class BlockedPublicationLauncherDelegationTest(unittest.TestCase):
    def _load_wrapper(
        self, system: str,
    ) -> tuple[types.ModuleType, list[tuple[list[str], str, str]]]:
        path = SCRIPTS / f"checkpoint_{system}_publication_launcher.py"
        self.assertTrue(path.is_file(), f"missing dedicated wrapper: {path.name}")
        calls: list[tuple[list[str], str, str]] = []
        guard = types.ModuleType("checkpoint_publication_launcher_guard")

        def run_fail_closed_publication_launcher(
            argv: list[str], *, expected_system: str, blocker: str,
        ) -> int:
            calls.append((list(argv), expected_system, blocker))
            return 78

        guard.run_fail_closed_publication_launcher = (
            run_fail_closed_publication_launcher
        )
        previous = sys.modules.get("checkpoint_publication_launcher_guard")
        sys.modules["checkpoint_publication_launcher_guard"] = guard
        try:
            spec = importlib.util.spec_from_file_location(
                f"test_{system}_publication_launcher", path,
            )
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        finally:
            if previous is None:
                sys.modules.pop("checkpoint_publication_launcher_guard", None)
            else:
                sys.modules["checkpoint_publication_launcher_guard"] = previous
        return module, calls

    def test_wrappers_delegate_exact_argv_and_fixed_backend_to_shared_guard(self) -> None:
        argv = [
            "--arm-contract", "C:/accepted/arm/backend_publication_arm_contract.json",
            "--output-dir", "C:/accepted/arm",
        ]
        for system in ("openvino_gva", "gstreamer_custom"):
            with self.subTest(system=system):
                module, calls = self._load_wrapper(system)
                self.assertEqual(module.main(argv), 78)
                self.assertEqual(len(calls), 1)
                observed_argv, expected_system, blocker = calls[0]
                self.assertEqual(observed_argv, argv)
                self.assertEqual(expected_system, system)
                self.assertIn(system, blocker)
                self.assertIn("not implemented", blocker)


class BlockedPublicationLauncherPhysicalContractTest(unittest.TestCase):
    def _write_contract(self, root: Path, system: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / ARM_CONTRACT_FILENAME
        write_immutable_backend_publication_arm_contract(
            path, contract_for(root, system),
        )
        return path

    def test_valid_contract_is_consumed_then_both_launchers_block_without_writes(self) -> None:
        for system, launcher in (
            ("openvino_gva", openvino_gva),
            ("gstreamer_custom", gstreamer_custom),
        ):
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                contract_path = self._write_contract(root, system)
                before = output_tree_snapshot(root)
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    status = launcher.main([
                        "--arm-contract", str(contract_path),
                        "--output-dir", str(root),
                    ])
                self.assertEqual(status, 78)
                self.assertFalse(launcher.PUBLICATION_READY)
                self.assertIn("publication launcher is blocked", stderr.getvalue())
                self.assertFalse((root / LAUNCHER_RESULT_FILENAME).exists())
                self.assertFalse((root / OUTPUT_RECEIPT_FILENAME).exists())
                self.assertEqual(output_tree_snapshot(root), before)

    def test_closed_argv_and_expected_system_are_fail_closed(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = openvino_gva.main([
                "--arm-contract", "arm.json",
                "--output-dir", "output",
                "--plan",
            ])
        self.assertEqual(status, 78)
        self.assertIn("closed invocation ABI", stderr.getvalue())

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            contract_path = self._write_contract(root, "openvino_gva")
            before = output_tree_snapshot(root)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = gstreamer_custom.main([
                    "--arm-contract", str(contract_path),
                    "--output-dir", str(root),
                ])
            self.assertEqual(status, 78)
            self.assertIn("system coordinate", stderr.getvalue())
            self.assertEqual(output_tree_snapshot(root), before)


if __name__ == "__main__":
    unittest.main()
