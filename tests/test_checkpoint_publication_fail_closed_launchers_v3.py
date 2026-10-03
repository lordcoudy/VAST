from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backend_publication_launcher_invocation_v3 as invocation
import checkpoint_deepstream_publication_launcher_v3 as deepstream
import checkpoint_gstreamer_custom_publication_launcher_v3 as gstreamer
import checkpoint_openvino_gva_publication_launcher_v3 as openvino
import checkpoint_publication_launcher_guard_v3 as guard
import checkpoint_savant_publication_launcher_v3 as savant


LAUNCHERS = (
    ("deepstream", deepstream),
    ("savant", savant),
    ("openvino_gva", openvino),
    ("gstreamer_custom", gstreamer),
)


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


class FailClosedPublicationLauncherV3Tests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, str]:
        output = root / "runs" / "nonpublication-v3-scaffold"
        output.mkdir(parents=True)
        contract = output / "backend_publication_arm_contract.json"
        payload = canonical(
            {
                "artifact_kind": "unimplemented_v3_arm_contract_fixture",
                "schema_version": 3,
            }
        )
        contract.write_bytes(payload)
        return output, contract, hashlib.sha256(payload).hexdigest()

    def _argv(
        self, root: Path, output: Path, contract: Path, digest: str
    ) -> list[str]:
        return [
            "--project-root",
            str(root),
            "--arm-contract",
            str(contract),
            "--arm-contract-sha256",
            digest,
            "--output-dir",
            str(output),
        ]

    def _run(self, launcher: object, argv: list[object]) -> tuple[int, dict]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = launcher.main(argv)
        self.assertEqual(stderr.getvalue(), "")
        return status, json.loads(stdout.getvalue())

    def test_exact_v3_argv_is_physically_bound_but_always_blocked(self) -> None:
        for system, launcher in LAUNCHERS:
            with self.subTest(system=system), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                output, contract, digest = self._fixture(root)
                before = sorted((p.name, p.read_bytes()) for p in output.iterdir())
                status, assessment = self._run(
                    launcher, self._argv(root, output, contract, digest)
                )
                self.assertEqual(status, 78)
                self.assertTrue(launcher.PUBLICATION_READY)
                self.assertEqual(assessment["system"], system)
                self.assertTrue(assessment["contract_bytes_externally_pinned"])
                self.assertTrue(assessment["canonical_contract_bytes_validated"])
                self.assertFalse(assessment["arm_contract_v3_semantics_validated"])
                self.assertFalse(assessment["execution_authorized"])
                self.assertFalse(assessment["publication_capable"])
                self.assertFalse(assessment["accepted_measurement_evidence_emitted"])
                self.assertFalse(assessment["publication_ready"])
                self.assertNotIn("filesystem_writes_performed", assessment)
                self.assertFalse(
                    assessment["project_or_output_filesystem_writes_performed"]
                )
                self.assertTrue(
                    assessment["local_module_bytecode_writes_disabled_after_wrapper_start"]
                )
                self.assertFalse(
                    assessment["python_startup_filesystem_writes_attested"]
                )
                self.assertIn("arm_contract_v3_semantics_invalid", assessment["blockers"])
                self.assertEqual(
                    assessment["invocation_contract_sha256"],
                    invocation.publication_launcher_invocation_v3_contract()[
                        "invocation_sha256"
                    ],
                )
                self.assertEqual(
                    sorted((p.name, p.read_bytes()) for p in output.iterdir()), before
                )

    def test_v2_reordered_unknown_and_non_string_argv_fail_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            output, contract, digest = self._fixture(root)
            exact = self._argv(root, output, contract, digest)
            invalid = (
                ["--arm-contract", str(contract), "--output-dir", str(output)],
                exact[2:4] + exact[0:2] + exact[4:],
                exact + ["--plan"],
                exact[:-1],
                exact[:-1] + [Path(exact[-1])],
            )
            for position, argv in enumerate(invalid):
                with self.subTest(position=position):
                    status, assessment = self._run(deepstream, list(argv))
                    self.assertEqual(status, 78)
                    self.assertFalse(assessment["contract_bytes_externally_pinned"])
                    self.assertEqual(
                        assessment["blockers"], ["invocation_argv_v3_not_exact"]
                    )

    def test_raw_sha_pin_rejects_self_consistent_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            output, contract, digest = self._fixture(root)
            replacement = {
                "artifact_kind": "unimplemented_v3_arm_contract_fixture",
                "schema_version": 3,
                "self_consistent_substitution": True,
            }
            contract.write_bytes(canonical(replacement))
            status, assessment = self._run(
                deepstream, self._argv(root, output, contract, digest)
            )
            self.assertEqual(status, 78)
            self.assertEqual(assessment["blockers"], ["arm_contract_file_sha256_mismatch"])

    def test_noncanonical_and_duplicate_json_are_rejected(self) -> None:
        payloads = (
            b'{"schema_version": 3, "artifact_kind": "x"}\n',
            b'{"artifact_kind":"x","artifact_kind":"x","schema_version":3}\n',
            b'{"artifact_kind":"x","schema_version":3}\n\n',
        )
        for index, payload in enumerate(payloads):
            with self.subTest(index=index), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                output, contract, _ = self._fixture(root)
                contract.write_bytes(payload)
                status, assessment = self._run(
                    deepstream,
                    self._argv(
                        root,
                        output,
                        contract,
                        hashlib.sha256(payload).hexdigest(),
                    ),
                )
                self.assertEqual(status, 78)
                self.assertIn(
                    assessment["blockers"][0],
                    {"arm_contract_json_not_unique", "arm_contract_bytes_not_canonical"},
                )

    def test_excessively_nested_json_is_rejected_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            output, contract, _ = self._fixture(root)
            payload = (b'{"value":' + (b"[" * 100_000) + b"0" + (b"]" * 100_000) + b"}\n")
            contract.write_bytes(payload)
            status, assessment = self._run(
                deepstream,
                self._argv(
                    root,
                    output,
                    contract,
                    hashlib.sha256(payload).hexdigest(),
                ),
            )
            self.assertEqual(status, 78)
            self.assertEqual(assessment["blockers"], ["arm_contract_json_invalid"])

    def test_contract_and_output_must_be_confined_to_canonical_project_root(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            root = Path(first).resolve()
            outside = Path(second).resolve()
            output, contract, digest = self._fixture(outside)
            status, assessment = self._run(
                deepstream, self._argv(root, output, contract, digest)
            )
            self.assertEqual(status, 78)
            self.assertEqual(assessment["blockers"], ["output_dir_escaped_project_root"])

    def test_resolution_and_terminal_path_races_fail_closed_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            output, contract, digest = self._fixture(root)
            argv = self._argv(root, output, contract, digest)
            with mock.patch.object(
                guard.Path, "resolve", side_effect=RuntimeError("symlink loop")
            ):
                status, assessment = self._run(deepstream, argv)
            self.assertEqual(status, 78)
            self.assertEqual(
                assessment["blockers"],
                ["project_root_not_canonical_plain_directory"],
            )

            original_lstat = guard.Path.lstat
            for fail_on_call in (2, 3):
                with self.subTest(fail_on_call=fail_on_call):
                    root_calls = 0

                    def disappearing_root(path: Path) -> object:
                        nonlocal root_calls
                        if path == root:
                            root_calls += 1
                            if root_calls == fail_on_call:
                                raise OSError("root disappeared")
                        return original_lstat(path)

                    with mock.patch.object(guard.Path, "lstat", disappearing_root):
                        status, assessment = self._run(deepstream, argv)
                    self.assertEqual(status, 78)
                    self.assertEqual(
                        assessment["blockers"], ["arm_contract_identity_changed"]
                    )

            nul_root = list(argv)
            nul_root[1] = f"{root}\0"
            status, assessment = self._run(deepstream, nul_root)
            self.assertEqual(status, 78)
            self.assertEqual(
                assessment["blockers"],
                ["project_root_not_canonical_plain_directory"],
            )

    def test_contract_path_with_dot_segments_is_not_canonical(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            output, contract, digest = self._fixture(root)
            intermediate = output / "existing"
            intermediate.mkdir()
            noncanonical = intermediate / ".." / contract.name
            status, assessment = self._run(
                deepstream, self._argv(root, output, noncanonical, digest)
            )
            self.assertEqual(status, 78)
            self.assertEqual(
                assessment["blockers"], ["arm_contract_path_not_fixed_direct_child"]
            )

            raw_dot = self._argv(root, output, contract, digest)
            raw_dot[3] = f"{output}{os.sep}.{os.sep}{contract.name}"
            status, assessment = self._run(deepstream, raw_dot)
            self.assertEqual(status, 78)
            self.assertEqual(
                assessment["blockers"], ["arm_contract_path_not_fixed_direct_child"]
            )

    def test_normal_python_launch_does_not_write_local_bytecode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            output, contract, digest = self._fixture(root)
            cache = root / "cache"
            environment = dict(os.environ)
            environment.pop("PYTHONDONTWRITEBYTECODE", None)
            environment["PYTHONPYCACHEPREFIX"] = str(cache)
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPTS / "checkpoint_deepstream_publication_launcher_v3.py"),
                    *self._argv(root, output, contract, digest),
                ],
                cwd=root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
            )
            self.assertEqual(completed.returncode, 78, completed.stderr)
            assessment = json.loads(completed.stdout)
            self.assertFalse(
                assessment["project_or_output_filesystem_writes_performed"]
            )
            self.assertFalse(
                assessment["python_startup_filesystem_writes_attested"]
            )
            local_names = {
                "checkpoint_publication_launcher_guard_v3",
                "backend_publication_launcher_invocation_v3",
            }
            observed = {
                path.name.split(".", 1)[0]
                for path in cache.rglob("*.pyc")
                if path.is_file()
            }
            self.assertTrue(local_names.isdisjoint(observed), observed)

    def test_invocation_declaration_itself_remains_nonauthorizing(self) -> None:
        value = invocation.validate_publication_launcher_invocation_v3(
            invocation.publication_launcher_invocation_v3_contract()
        )
        self.assertFalse(value["execution_authorized"])
        self.assertEqual(value["argv_template"], list(invocation.ARGV_TEMPLATE))


if __name__ == "__main__":
    unittest.main()
