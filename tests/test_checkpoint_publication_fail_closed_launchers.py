from __future__ import annotations

import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
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
from checkpoint_publication_launcher_guard import (  # noqa: E402
    CheckpointPublicationLauncherGuardError,
    load_and_validate_blocked_publication_arm_contract,
)

import checkpoint_deepstream_publication_launcher as deepstream  # noqa: E402
import checkpoint_savant_publication_launcher as savant  # noqa: E402


MAX_ARM_CONTRACT_BYTES = 1024 * 1024


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


class FailClosedPublicationLauncherTests(unittest.TestCase):
    def _write_contract(self, root: Path, system: str) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / ARM_CONTRACT_FILENAME
        write_immutable_backend_publication_arm_contract(
            path, contract_for(root, system)
        )
        return path

    def test_valid_contract_is_read_but_both_unimplemented_launchers_fail_closed(self) -> None:
        for system, launcher in (
            ("deepstream", deepstream),
            ("savant", savant),
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
                self.assertIn("publication launcher is blocked", stderr.getvalue())
                self.assertFalse(launcher.PUBLICATION_READY)
                self.assertFalse((root / LAUNCHER_RESULT_FILENAME).exists())
                self.assertFalse((root / OUTPUT_RECEIPT_FILENAME).exists())
                self.assertEqual(output_tree_snapshot(root), before)

    def test_closed_invocation_abi_rejects_plan_or_introspection_arguments(self) -> None:
        for launcher in (deepstream, savant):
            with self.subTest(launcher=launcher.__name__):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    status = launcher.main([
                        "--arm-contract", "arm.json",
                        "--output-dir", "output",
                        "--plan",
                    ])
                self.assertEqual(status, 78)
                self.assertIn("closed invocation ABI", stderr.getvalue())

    def test_contract_system_cannot_be_cross_dispatched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            contract_path = self._write_contract(root, "savant")
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = deepstream.main([
                    "--arm-contract", str(contract_path),
                    "--output-dir", str(root),
                ])
            self.assertEqual(status, 78)
            self.assertIn("system coordinate", stderr.getvalue())
            self.assertFalse((root / LAUNCHER_RESULT_FILENAME).exists())
            self.assertFalse((root / OUTPUT_RECEIPT_FILENAME).exists())

    def test_arm_contract_must_be_the_fixed_unique_physical_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            contract_path = self._write_contract(root, "deepstream")
            alias = root / "arm-contract-alias.json"
            alias.hardlink_to(contract_path)
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = deepstream.main([
                    "--arm-contract", str(contract_path),
                    "--output-dir", str(root),
                ])
            self.assertEqual(status, 78)
            self.assertIn("hardlink", stderr.getvalue())
            self.assertFalse((root / LAUNCHER_RESULT_FILENAME).exists())
            self.assertFalse((root / OUTPUT_RECEIPT_FILENAME).exists())

            stderr = io.StringIO()
            with redirect_stderr(stderr):
                status = deepstream.main([
                    "--arm-contract", str(alias),
                    "--output-dir", str(root),
                ])
            self.assertEqual(status, 78)
            self.assertIn("fixed path", stderr.getvalue())

    def test_contract_bytes_are_read_from_the_same_opened_inode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            original = contract_for(root, "deepstream")
            root.mkdir(parents=True, exist_ok=True)
            contract_path = root / ARM_CONTRACT_FILENAME
            write_immutable_backend_publication_arm_contract(
                contract_path, original
            )
            transient = copy.deepcopy(original)
            runtime = transient["runtime_inputs"]
            assert isinstance(runtime, dict)
            runtime["run_id"] = "transient-swapped-run"
            transient.pop("contract_sha256")
            transient["contract_sha256"] = canonical_sha(transient)
            transient_payload = json.dumps(
                transient,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("utf-8") + b"\n"
            backup = root / "original-arm-contract.backup"
            original_read_bytes = Path.read_bytes

            def transient_path_swap(path: Path) -> bytes:
                if path != contract_path:
                    return original_read_bytes(path)
                contract_path.replace(backup)
                try:
                    contract_path.write_bytes(transient_payload)
                    return original_read_bytes(contract_path)
                finally:
                    contract_path.unlink(missing_ok=True)
                    backup.replace(contract_path)

            from unittest.mock import patch

            with patch.object(Path, "read_bytes", transient_path_swap):
                checked = load_and_validate_blocked_publication_arm_contract(
                    arm_contract_path=contract_path,
                    output_dir=root,
                    expected_system="deepstream",
                )
            self.assertEqual(
                checked["contract_sha256"], original["contract_sha256"]
            )
            self.assertEqual(
                checked["runtime_inputs"]["run_id"],
                original["runtime_inputs"]["run_id"],
            )

    def test_output_root_cannot_be_swapped_before_contract_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            container = Path(tmp).resolve()
            root = container / "output"
            replacement = container / "replacement"
            parked = container / "parked-original"
            contract_path = self._write_contract(root, "deepstream")
            replacement.mkdir()
            transient = contract_for(root, "deepstream")
            runtime = transient["runtime_inputs"]
            assert isinstance(runtime, dict)
            runtime["run_id"] = "replacement-root-run"
            transient.pop("contract_sha256")
            transient["contract_sha256"] = canonical_sha(transient)
            (replacement / ARM_CONTRACT_FILENAME).write_text(
                json.dumps(
                    transient,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                    allow_nan=False,
                ) + "\n",
                encoding="utf-8",
            )
            original_resolve = Path.resolve
            swapped = False

            def swap_root_before_contract_resolve(
                path: Path, strict: bool = False
            ) -> Path:
                nonlocal swapped
                if path == contract_path and not swapped:
                    root.replace(parked)
                    replacement.replace(root)
                    swapped = True
                return original_resolve(path, strict=strict)

            from unittest.mock import patch

            try:
                with patch.object(
                    Path, "resolve", swap_root_before_contract_resolve
                ):
                    with self.assertRaisesRegex(
                        CheckpointPublicationLauncherGuardError,
                        "output directory changed",
                    ):
                        load_and_validate_blocked_publication_arm_contract(
                            arm_contract_path=contract_path,
                            output_dir=root,
                            expected_system="deepstream",
                        )
            finally:
                if swapped:
                    root.replace(replacement)
                    parked.replace(root)

    def test_arm_contract_size_is_bounded_before_content_decode(self) -> None:
        for label, payload in (
            ("zero", b""),
            ("oversized", b"x" * (MAX_ARM_CONTRACT_BYTES + 1)),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                contract_path = root / ARM_CONTRACT_FILENAME
                contract_path.write_bytes(payload)
                with self.assertRaisesRegex(
                    CheckpointPublicationLauncherGuardError,
                    "size",
                ):
                    load_and_validate_blocked_publication_arm_contract(
                        arm_contract_path=contract_path,
                        output_dir=root,
                        expected_system="deepstream",
                    )

    def test_direct_api_rejects_non_string_argv_without_traceback(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            status = deepstream.main([
                "--arm-contract", Path("arm.json"),
                "--output-dir", "output",
            ])
        self.assertEqual(status, 78)
        self.assertIn("closed invocation ABI", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
