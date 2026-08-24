from __future__ import annotations

import copy
import ctypes
import hashlib
import json
import os
import select
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
FIXTURE = (
    ROOT / "tests" / "fixtures" / "backend_publication_v3_process_fixture.py"
).resolve()
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backend_publication_process_supervisor_v3 as supervisor
from backend_publication_dispatch_v3 import (
    ARM_CONTRACT_FILENAME,
    build_backend_publication_arm_contract_v3,
    build_backend_publication_dispatch_resolution_v3,
    canonical_backend_publication_arm_contract_bytes_v3,
)
from backend_publication_launcher_invocation_v3 import (
    publication_launcher_invocation_v3_contract,
)


class SyntheticBrokerAbort(BaseException):
    pass


def _noop_posix_preexec() -> None:
    return None


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _pid_is_running(pid: int) -> bool:
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    open_process.restype = wintypes.HANDLE
    get_exit_code = kernel32.GetExitCodeProcess
    get_exit_code.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    get_exit_code.restype = wintypes.BOOL
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [wintypes.HANDLE]
    close_handle.restype = wintypes.BOOL
    handle = open_process(0x1000, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return bool(get_exit_code(handle, ctypes.byref(code))) and code.value == 259
    finally:
        close_handle(handle)


def _linux_tree_pidfds(root_pid: int) -> dict[int, int]:
    parents: dict[int, int] = {}
    try:
        processes = list(Path("/proc").iterdir())
    except OSError as exc:
        raise AssertionError("outer process inventory failed") from exc
    for process_path in processes:
        if not process_path.name.isdigit():
            continue
        pid = int(process_path.name)
        try:
            payload = (process_path / "stat").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError as exc:
            raise AssertionError("outer process stat inventory failed") from exc
        closing_parenthesis = payload.rfind(b")")
        fields = payload[closing_parenthesis + 1 :].split()
        if closing_parenthesis < 0 or len(fields) < 2:
            raise AssertionError("outer process stat is malformed")
        try:
            parents[pid] = int(fields[1])
        except ValueError as exc:
            raise AssertionError("outer process parent PID is malformed") from exc
    discovered = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent_pid in parents.items():
            if parent_pid in discovered and pid not in discovered:
                discovered.add(pid)
                changed = True
    pidfds: dict[int, int] = {}
    try:
        for pid in discovered:
            try:
                descriptor = os.pidfd_open(pid, 0)
                signal.pidfd_send_signal(descriptor, 0, None, 0)
            except ProcessLookupError:
                continue
            except OSError as exc:
                raise AssertionError("outer process pidfd open failed") from exc
            pidfds[pid] = descriptor
    except BaseException:
        for descriptor in pidfds.values():
            os.close(descriptor)
        raise
    return pidfds


def _assert_linux_pidfds_gone(
    case: unittest.TestCase, pidfds: dict[int, int]
) -> None:
    deadline = time.monotonic() + 5.0
    alive: list[int] = []
    while time.monotonic() < deadline:
        alive = []
        for pid, descriptor in pidfds.items():
            try:
                signal.pidfd_send_signal(descriptor, 0, None, 0)
            except ProcessLookupError:
                continue
            alive.append(pid)
        if not alive:
            break
        time.sleep(0.02)
    case.assertEqual(alive, [], f"outer descendants survived: {alive}")


def _kill_and_close_linux_pidfds(pidfds: dict[int, int]) -> None:
    for descriptor in pidfds.values():
        try:
            signal.pidfd_send_signal(descriptor, signal.SIGKILL, None, 0)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        alive = False
        for descriptor in pidfds.values():
            try:
                signal.pidfd_send_signal(descriptor, 0, None, 0)
            except ProcessLookupError:
                continue
            alive = True
        if not alive:
            break
        time.sleep(0.02)
    for descriptor in pidfds.values():
        os.close(descriptor)


class BackendPublicationProcessSupervisorV3Tests(unittest.TestCase):
    maxDiff = None

    def _invocation(
        self, root: Path, dataset: dict[str, object]
    ) -> tuple[tuple[str, ...], Path, Path]:
        canonical_root = root.resolve(strict=True)
        output_dir = canonical_root / "output"
        output_dir.mkdir()
        contract_path = output_dir / ARM_CONTRACT_FILENAME
        coordinate = {
            "system": "gstreamer_custom",
            "codec": "h264",
            "topology_kind": "shared_video_dag",
            "policy": "heft",
            "deadline_ms": 100,
        }
        dispatch = build_backend_publication_dispatch_resolution_v3(
            coordinate=coordinate,
            python_executable={
                "path": "synthetic/python",
                "size_bytes": 1,
                "sha256": "1" * 64,
            },
            publication_launcher={
                "path": "synthetic/publication_fixture.py",
                "size_bytes": 1,
                "sha256": "2" * 64,
            },
            launcher_invocation=publication_launcher_invocation_v3_contract(),
            backend_runtime_grant_sha256="3" * 64,
            identity_artifact_binding_sha256="4" * 64,
            cell_identity_sha256="5" * 64,
            validation_record_sha256="6" * 64,
            runtime_binding_identity_sha256="7" * 64,
        )
        runtime_inputs = {
            **coordinate,
            "scenario": "checkpoint_video_dag_shared",
            "dataset": dataset,
            "streams": 1,
            "duration_s": 1,
            "repeat_index": 0,
            "base_seed": 20260822,
            "run_seed": 20260823,
            "run_id": "synthetic-process-supervisor-v3",
            "project_root": str(canonical_root),
            "arm_contract_path": str(contract_path),
            "output_dir": str(output_dir),
        }
        contract = build_backend_publication_arm_contract_v3(
            dispatch_resolution=dispatch,
            full_publication_execution_binding={
                "schema_version": 1,
                "artifact_kind": "vast_full_publication_arm_execution_binding",
                "run_identity_sha256": "8" * 64,
                "sequence": 0,
                "pair_id": "synthetic-pair",
                "attempt": 1,
                "arm_id": "synthetic-arm",
            },
            resource_capability_grant_sha256="9" * 64,
            model_parity_grant_sha256="a" * 64,
            model_parity_acceptance_binding_sha256="b" * 64,
            runtime_inputs=runtime_inputs,
            launcher_evidence_files=(
                "latency_samples.json",
                "runtime_assessment.json",
            ),
        )
        payload = canonical_backend_publication_arm_contract_bytes_v3(contract)
        contract_path.write_bytes(payload)
        argv = (
            str(Path(sys.executable).resolve(strict=True)),
            str(FIXTURE),
            "--project-root",
            str(canonical_root),
            "--arm-contract",
            str(contract_path.resolve(strict=True)),
            "--arm-contract-sha256",
            hashlib.sha256(payload).hexdigest(),
            "--output-dir",
            str(output_dir.resolve(strict=True)),
        )
        return argv, canonical_root, output_dir

    def _assert_observation_hash(self, observation: dict[str, object]) -> None:
        self.assertEqual(set(observation), set(supervisor.OBSERVATION_FIELDS))
        unsigned = copy.deepcopy(observation)
        declared = unsigned.pop("observation_sha256")
        self.assertEqual(
            declared,
            hashlib.sha256(
                supervisor.OBSERVATION_DOMAIN + _canonical(unsigned)
            ).hexdigest(),
        )

    def _run_fault_injected(
        self, argv: tuple[str, ...], *, cwd: Path
    ) -> supervisor.BackendPublicationProcessRunV3:
        if os.name == "nt":
            return supervisor.run_backend_publication_process_v3(
                argv, cwd=cwd
            )
        command, canonical_cwd = supervisor._validate_invocation(argv, cwd)
        with mock.patch.object(
            supervisor,
            "_linux_backend_preexec_v3",
            new=_noop_posix_preexec,
        ):
            return supervisor._run_backend_with_posix_scope_v3(
                command, canonical_cwd
            )

    def _assert_pid_gone(self, pid_path: Path) -> None:
        self.assertTrue(pid_path.is_file(), "grandchild PID was not materialized")
        pid = int(pid_path.read_text(encoding="ascii"))
        deadline = time.monotonic() + 3.0
        while _pid_is_running(pid) and time.monotonic() < deadline:
            time.sleep(0.02)
        self.assertFalse(_pid_is_running(pid), f"grandchild {pid} survived")

    def _kill_pid_if_running(self, pid_path: Path) -> None:
        if os.name != "nt":
            return
        if not pid_path.is_file():
            return
        try:
            pid = int(pid_path.read_text(encoding="ascii"))
        except (OSError, ValueError):
            return
        if _pid_is_running(pid):
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                pass

    def test_success_returns_exact_raw_bytes_and_closed_observation(self) -> None:
        stdout = b"raw-stdout\x00\xff\r\n"
        stderr = b"raw-stderr\x00\xfe\n"
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw),
                {
                    "synthetic_stdout_hex": stdout.hex(),
                    "synthetic_stderr_hex": stderr.hex(),
                },
            )
            result = supervisor.run_backend_publication_process_v3(
                argv, cwd=cwd
            )
            expected_evidence = {
                name: (
                    b"VAST:synthetic-backend-publication-evidence:v3\0"
                    + name.encode("utf-8")
                    + b"\n"
                )
                for name in (
                    "latency_samples.json",
                    "runtime_assessment.json",
                )
            }
            for name, payload in expected_evidence.items():
                self.assertEqual((output / name).read_bytes(), payload)
            with self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as repeated:
                supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
            self.assertEqual(
                repeated.exception.observation["status"],  # type: ignore[index]
                "exit_nonzero",
            )
            for name, payload in expected_evidence.items():
                self.assertEqual((output / name).read_bytes(), payload)

        self.assertEqual(result.stdout, stdout)
        self.assertEqual(result.stderr, stderr)
        with self.assertRaises(FrozenInstanceError):
            result.stdout = b"drift"  # type: ignore[misc]
        observation = result.observation
        self._assert_observation_hash(observation)
        self.assertEqual(observation["status"], "succeeded")
        self.assertEqual(observation["exit_code"], 0)
        self.assertEqual(observation["stdout_size_bytes"], len(stdout))
        self.assertEqual(observation["stderr_size_bytes"], len(stderr))
        self.assertEqual(observation["stdout_sha256"], hashlib.sha256(stdout).hexdigest())
        self.assertEqual(observation["stderr_sha256"], hashlib.sha256(stderr).hexdigest())
        self.assertIs(observation["process_tree_quiescent"], True)
        self.assertIs(
            observation["unexpected_live_descendant_detected"], False
        )
        self.assertIs(observation["publication_execution_authorized"], False)
        self.assertIs(observation["shell"], False)
        self.assertEqual(observation["environment"], {})
        self.assertEqual(observation["stdin"], "DEVNULL")
        self.assertIs(observation["close_fds"], True)
        if os.name == "nt":
            self.assertIs(observation["create_suspended"], True)
            self.assertIs(observation["job_kill_on_close"], True)
            self.assertIs(observation["job_assigned_before_resume"], True)
            self.assertEqual(observation["active_processes_after_cleanup"], 0)
            self.assertIs(observation["start_new_session"], False)
            self.assertIs(observation["posix_child_subreaper"], False)
            self.assertIs(
                observation["posix_pidfd_descendant_cleanup"], False
            )
            self.assertIs(observation["posix_isolated_broker"], False)
        else:
            self.assertIs(observation["start_new_session"], True)
            self.assertIs(observation["posix_child_subreaper"], True)
            self.assertIs(
                observation["posix_pidfd_descendant_cleanup"], True
            )
            self.assertIs(observation["posix_isolated_broker"], True)
            self.assertEqual(observation["active_processes_after_cleanup"], 0)
            self.assertIs(observation["create_suspended"], False)
            self.assertIs(observation["job_kill_on_close"], False)
            self.assertIs(observation["job_assigned_before_resume"], False)
        tampered = result.observation
        tampered["status"] = "exit_nonzero"
        tampered["environment"]["INHERITED"] = "unsafe"
        self.assertEqual(result.observation["status"], "succeeded")
        self.assertEqual(result.observation["environment"], {})

    def test_popen_receives_exact_closed_process_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "success"}
            )
            real_popen = supervisor.subprocess.Popen
            calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

            def observed_popen(*args: object, **kwargs: object) -> object:
                calls.append((args, copy.deepcopy(kwargs)))
                return real_popen(*args, **kwargs)

            with mock.patch.object(
                supervisor.subprocess, "Popen", side_effect=observed_popen
            ):
                result = self._run_fault_injected(argv, cwd=cwd)

        self.assertEqual(result.observation["status"], "succeeded")
        self.assertEqual(len(calls), 1)
        positional, keywords = calls[0]
        self.assertEqual(positional, (list(argv),))
        self.assertIs(keywords["stdin"], subprocess.DEVNULL)
        self.assertIs(keywords["stdout"], subprocess.PIPE)
        self.assertIs(keywords["stderr"], subprocess.PIPE)
        self.assertIs(keywords["shell"], False)
        self.assertEqual(keywords["env"], {})
        self.assertEqual(keywords["cwd"], str(cwd))
        self.assertIs(keywords["close_fds"], True)
        self.assertEqual(keywords["bufsize"], 0)
        if os.name == "nt":
            self.assertEqual(
                int(keywords["creationflags"]) & supervisor._CREATE_SUSPENDED,
                supervisor._CREATE_SUSPENDED,
            )
            self.assertNotIn("start_new_session", keywords)
        else:
            self.assertIs(keywords["start_new_session"], True)
            self.assertIs(keywords["preexec_fn"], _noop_posix_preexec)
            self.assertNotIn("creationflags", keywords)

    def test_transaction_fixture_rejects_raw_arm_sha_drift(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(Path(raw), {})
            drifted = argv[:7] + ("0" * 64,) + argv[8:]
            with self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as raised:
                supervisor.run_backend_publication_process_v3(
                    drifted, cwd=cwd
                )
            observation = raised.exception.observation
            assert observation is not None
            self.assertEqual(observation["status"], "exit_nonzero")
            self.assertFalse((output / "latency_samples.json").exists())
            self.assertFalse((output / "runtime_assessment.json").exists())

    @unittest.skipIf(os.name == "nt", "POSIX isolated broker contract")
    def test_posix_broker_spawn_has_closed_explicit_contract(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(Path(raw), {})
            real_popen = supervisor.subprocess.Popen
            calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

            def observed_popen(*args: object, **kwargs: object) -> object:
                calls.append((args, copy.deepcopy(kwargs)))
                return real_popen(*args, **kwargs)

            with mock.patch.object(
                supervisor.subprocess, "Popen", side_effect=observed_popen
            ):
                result = supervisor.run_backend_publication_process_v3(
                    argv, cwd=cwd
                )
        self.assertEqual(result.observation["status"], "succeeded")
        self.assertEqual(len(calls), 1)
        positional, keywords = calls[0]
        self.assertEqual(
            positional,
            (
                [
                    argv[0],
                    str(Path(supervisor.__file__).resolve(strict=True)),
                    supervisor._POSIX_BROKER_MODE,
                ],
            ),
        )
        self.assertIs(keywords["stdin"], subprocess.PIPE)
        self.assertIs(keywords["stdout"], subprocess.PIPE)
        self.assertIs(keywords["stderr"], subprocess.PIPE)
        self.assertIs(keywords["shell"], False)
        self.assertEqual(keywords["env"], {})
        self.assertEqual(keywords["cwd"], str(cwd))
        self.assertIs(keywords["close_fds"], True)
        self.assertIs(keywords["start_new_session"], True)
        self.assertEqual(keywords["bufsize"], 0)

    def test_argv_and_cwd_are_exact_and_caller_cannot_tune_limits(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "success"}
            )
            other = cwd / "other"
            other.mkdir()
            cases: list[tuple[object, Path]] = [
                (argv[:-1], cwd),
                (argv[:2] + ("--unsafe",) + argv[3:], cwd),
                (argv[:3] + ("relative",) + argv[4:], cwd),
                (
                    argv[:3] + (str(cwd) + os.sep + ".",) + argv[4:],
                    cwd,
                ),
                (argv[:7] + ("A" * 64,) + argv[8:], cwd),
                (argv[:9] + (argv[9] + "\x00unsafe",), cwd),
                (argv, other),
                (" ".join(argv), cwd),
            ]
            for candidate, candidate_cwd in cases:
                with self.subTest(candidate=candidate), self.assertRaises(
                    supervisor.BackendPublicationProcessSupervisorV3Error
                ) as raised:
                    supervisor.run_backend_publication_process_v3(
                        candidate, cwd=candidate_cwd  # type: ignore[arg-type]
                    )
                self.assertIsNone(raised.exception.observation)
        self.assertEqual(
            list(supervisor.run_backend_publication_process_v3.__annotations__),
            ["argv", "cwd", "return"],
        )

    def test_stdout_and_stderr_are_drained_concurrently_without_deadlock(self) -> None:
        size = 192 * 1024
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(
                Path(raw),
                {
                    "synthetic_process_fixture_mode": "dual",
                    "synthetic_stdout_size": size,
                    "synthetic_stderr_size": size,
                },
            )
            result = supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
        self.assertEqual(result.stdout, b"O" * size)
        self.assertEqual(result.stderr, b"E" * size)
        self.assertEqual(result.observation["status"], "succeeded")

    def test_nonzero_exit_is_never_a_success_or_raw_payload_exception(self) -> None:
        payload = b"do-not-place-raw-payload-in-error\x00\xff"
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(
                Path(raw),
                {
                    "synthetic_process_fixture_mode": "nonzero",
                    "synthetic_stdout_hex": payload.hex(),
                    "synthetic_stderr_hex": payload[::-1].hex(),
                    "synthetic_exit_code": 7,
                },
            )
            with self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as raised:
                supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
        error = raised.exception
        self.assertNotIn("do-not-place", str(error))
        self.assertEqual(error.stdout, payload)
        self.assertEqual(error.stderr, payload[::-1])
        self.assertIsNotNone(error.observation)
        observation = error.observation
        assert observation is not None
        self._assert_observation_hash(observation)
        self.assertEqual(observation["status"], "exit_nonzero")
        self.assertEqual(observation["exit_code"], 7)
        self.assertIs(observation["process_tree_quiescent"], True)
        self.assertIs(observation["publication_execution_authorized"], False)
        observation["status"] = "succeeded"
        self.assertEqual(error.observation["status"], "exit_nonzero")  # type: ignore[index]

    def test_real_stdout_and_stderr_overflow_are_bounded_non_successes(self) -> None:
        for stream in ("stdout", "stderr"):
            with self.subTest(stream=stream), tempfile.TemporaryDirectory() as raw:
                contract = {
                    "synthetic_process_fixture_mode": f"{stream}_overflow",
                    "synthetic_stdout_size": (
                        32 * 1024 if stream == "stdout" else 0
                    ),
                    "synthetic_stderr_size": (
                        32 * 1024 if stream == "stderr" else 0
                    ),
                }
                argv, cwd, _output = self._invocation(Path(raw), contract)
                with mock.patch.object(
                    supervisor, "_MAX_STDOUT_BYTES", 4096
                ), mock.patch.object(
                    supervisor, "_MAX_STDERR_BYTES", 4096
                ), self.assertRaises(
                    supervisor.BackendPublicationProcessSupervisorV3Error
                ) as raised:
                    self._run_fault_injected(argv, cwd=cwd)
                observation = raised.exception.observation
                assert observation is not None
                self.assertEqual(observation["status"], f"{stream}_overflow")
                self.assertLessEqual(observation[f"{stream}_size_bytes"], 4096)
                self.assertIs(observation[f"{stream}_overflow"], True)
                self.assertIs(observation["process_tree_quiescent"], True)

    def test_status_precedence_is_exact_and_closed(self) -> None:
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=True,
                stderr_overflow=True,
                timed_out=True,
                capture_failed=True,
                exit_code=9,
                quiescent=True,
            ),
            "capture_overflow",
        )
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=True,
                stderr_overflow=True,
                timed_out=True,
                capture_failed=True,
                exit_code=9,
                quiescent=False,
            ),
            "capture_overflow",
        )
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=True,
                stderr_overflow=False,
                timed_out=True,
                capture_failed=True,
                exit_code=9,
                quiescent=False,
            ),
            "stdout_overflow",
        )
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=False,
                stderr_overflow=True,
                timed_out=True,
                capture_failed=True,
                exit_code=9,
                quiescent=False,
            ),
            "stderr_overflow",
        )
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=False,
                stderr_overflow=False,
                timed_out=True,
                capture_failed=True,
                exit_code=9,
                quiescent=False,
            ),
            "timed_out",
        )
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=False,
                stderr_overflow=False,
                timed_out=False,
                capture_failed=True,
                exit_code=9,
                quiescent=False,
            ),
            "capture_failed",
        )
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=False,
                stderr_overflow=False,
                timed_out=False,
                capture_failed=False,
                exit_code=9,
                quiescent=False,
            ),
            "exit_nonzero",
        )
        self.assertEqual(
            supervisor._select_status_v3(
                stdout_overflow=False,
                stderr_overflow=False,
                timed_out=False,
                capture_failed=False,
                exit_code=0,
                quiescent=False,
            ),
            "process_tree_not_quiescent",
        )
        self.assertEqual(
            set(supervisor.OBSERVATION_STATUSES),
            {
                "succeeded",
                "exit_nonzero",
                "timed_out",
                "stdout_overflow",
                "stderr_overflow",
                "capture_overflow",
                "capture_failed",
                "process_tree_not_quiescent",
            },
        )

    def test_timeout_kills_real_child_and_grandchild(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "timeout"}
            )
            with mock.patch.object(
                supervisor, "_PROCESS_TIMEOUT_MS", 750
            ), mock.patch.object(
                supervisor, "_TERMINATION_GRACE_SECONDS", 0.4
            ), self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as raised:
                self._run_fault_injected(argv, cwd=cwd)
            observation = raised.exception.observation
            assert observation is not None
            self.assertEqual(observation["status"], "timed_out")
            self.assertIs(observation["timed_out"], True)
            self.assertIs(observation["termination_attempted"], True)
            self.assertIs(observation["process_tree_quiescent"], True)
            self._assert_pid_gone(output / "grandchild.pid")

    def test_exit_zero_with_live_grandchild_is_rejected_and_cleaned(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {
                    "synthetic_process_fixture_mode": "grandchild_exit"
                }
            )
            with self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as raised:
                supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
            observation = raised.exception.observation
            assert observation is not None
            self.assertEqual(
                observation["status"], "process_tree_not_quiescent"
            )
            self.assertIs(
                observation["unexpected_live_descendant_detected"], True
            )
            self.assertIs(observation["termination_attempted"], True)
            self.assertIs(observation["process_tree_quiescent"], True)
            if os.name == "nt":
                self._assert_pid_gone(output / "grandchild.pid")
            else:
                self.assertTrue((output / "grandchild.pid").is_file())

    def test_detached_descendant_cannot_escape_quiescence_attestation(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {
                    "synthetic_process_fixture_mode": "detached_exit"
                }
            )
            pid_path = output / "grandchild.pid"
            try:
                with self.assertRaises(
                    supervisor.BackendPublicationProcessSupervisorV3Error
                ) as raised:
                    supervisor.run_backend_publication_process_v3(
                        argv, cwd=cwd
                    )
                observation = raised.exception.observation
                assert observation is not None
                self.assertEqual(
                    observation["status"], "process_tree_not_quiescent"
                )
                self.assertIs(
                    observation["unexpected_live_descendant_detected"], True
                )
                self.assertIs(
                    observation["process_tree_quiescent"], True
                )
                self.assertTrue(pid_path.is_file())
            finally:
                self._kill_pid_if_running(pid_path)

    @unittest.skipIf(os.name == "nt", "Linux PID namespace containment")
    def test_backend_cannot_kill_broker_and_orphan_detached_descendant(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {
                    "synthetic_process_fixture_mode": "kill_broker_exit"
                }
            )
            pid_path = output / "grandchild.pid"
            broker_pid_ready = threading.Event()
            broker_pid = 0
            outcomes: list[object] = []
            real_popen = supervisor.subprocess.Popen

            def observe_outer_broker(
                *args: object, **kwargs: object
            ) -> subprocess.Popen[bytes]:
                nonlocal broker_pid
                process = real_popen(*args, **kwargs)
                broker_pid = process.pid
                broker_pid_ready.set()
                return process

            def run_attack() -> None:
                try:
                    outcomes.append(
                        supervisor.run_backend_publication_process_v3(
                            argv, cwd=cwd
                        )
                    )
                except BaseException as exc:
                    outcomes.append(exc)

            captured_pidfds: dict[int, int] = {}
            worker = threading.Thread(target=run_attack)
            try:
                with mock.patch.object(
                    supervisor.subprocess,
                    "Popen",
                    side_effect=observe_outer_broker,
                ):
                    worker.start()
                    self.assertTrue(broker_pid_ready.wait(5.0))
                    deadline = time.monotonic() + 5.0
                    while not pid_path.is_file() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertTrue(pid_path.is_file())
                    captured_pidfds = _linux_tree_pidfds(broker_pid)
                    self.assertGreaterEqual(len(captured_pidfds), 4)
                    worker.join(10.0)
                self.assertFalse(worker.is_alive())
                self.assertEqual(len(outcomes), 1)
                self.assertIsInstance(
                    outcomes[0],
                    supervisor.BackendPublicationProcessSupervisorV3Error,
                )
                error = outcomes[0]
                assert isinstance(
                    error,
                    supervisor.BackendPublicationProcessSupervisorV3Error,
                )
                observation = error.observation
                self.assertIsNotNone(observation)
                assert observation is not None
                self.assertEqual(
                    observation["status"], "process_tree_not_quiescent"
                )
                self.assertIs(
                    observation["unexpected_live_descendant_detected"], True
                )
                _assert_linux_pidfds_gone(self, captured_pidfds)
                for descriptor in captured_pidfds.values():
                    os.close(descriptor)
                captured_pidfds = {}
            finally:
                if captured_pidfds:
                    _kill_and_close_linux_pidfds(captured_pidfds)
                if worker.is_alive():
                    worker.join(5.0)

    @unittest.skipIf(os.name == "nt", "Linux namespace security contract")
    def test_backend_is_unprivileged_inside_fresh_pid_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(
                Path(raw), {
                    "synthetic_process_fixture_mode": "security_probe"
                }
            )
            result = supervisor.run_backend_publication_process_v3(
                argv, cwd=cwd
            )
        probe = json.loads(result.stdout.decode("ascii"))
        self.assertEqual(
            probe,
            {
                "cap_ambient": 0,
                "cap_bounding": 0,
                "cap_effective": 0,
                "cap_inheritable": 0,
                "cap_permitted": 0,
                "mount_namespace_unshare_errno": 1,
                "no_new_privs": 1,
                "parent_alive_after_sigkill": True,
                "parent_pid": 1,
                "parent_sigkill_call_returned": True,
                "ptrace_parent_errno": 1,
            },
        )
        self.assertEqual(result.stderr, b"")
        self.assertEqual(result.observation["status"], "succeeded")

    @unittest.skipIf(os.name == "nt", "Linux controller-death containment")
    def test_controller_sigkill_cannot_orphan_backend_namespace(self) -> None:
        self.assertEqual(len(threading.enumerate()), 1)
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "timeout"}
            )
            pid_path = output / "grandchild.pid"
            broker_pid_read, broker_pid_write = os.pipe()
            controller_pid = os.fork()
            if controller_pid == 0:
                os.close(broker_pid_read)
                real_popen = supervisor.subprocess.Popen

                def publish_broker_pid(
                    *args: object, **kwargs: object
                ) -> subprocess.Popen[bytes]:
                    process = real_popen(*args, **kwargs)
                    os.write(
                        broker_pid_write,
                        f"{process.pid}\n".encode("ascii"),
                    )
                    os.close(broker_pid_write)
                    return process

                try:
                    with mock.patch.object(
                        supervisor.subprocess,
                        "Popen",
                        side_effect=publish_broker_pid,
                    ):
                        supervisor.run_backend_publication_process_v3(
                            argv, cwd=cwd
                        )
                except BaseException:
                    os._exit(70)
                os._exit(0)
            os.close(broker_pid_write)
            controller_reaped = False
            captured_pidfds: dict[int, int] = {}
            try:
                poller = select.poll()
                poller.register(
                    broker_pid_read,
                    select.POLLIN | select.POLLHUP | select.POLLERR,
                )
                self.assertTrue(poller.poll(5000))
                broker_pid_payload = os.read(broker_pid_read, 64)
                broker_pid = int(broker_pid_payload.decode("ascii"))
                deadline = time.monotonic() + 5.0
                while not pid_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pid_path.is_file())
                captured_pidfds = _linux_tree_pidfds(broker_pid)
                self.assertGreaterEqual(len(captured_pidfds), 4)
                os.kill(controller_pid, signal.SIGKILL)
                waited_pid, status = os.waitpid(controller_pid, 0)
                controller_reaped = True
                self.assertEqual(waited_pid, controller_pid)
                self.assertTrue(os.WIFSIGNALED(status))
                self.assertEqual(os.WTERMSIG(status), signal.SIGKILL)
                _assert_linux_pidfds_gone(self, captured_pidfds)
                for descriptor in captured_pidfds.values():
                    os.close(descriptor)
                captured_pidfds = {}
            finally:
                os.close(broker_pid_read)
                if not controller_reaped:
                    try:
                        os.kill(controller_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        os.waitpid(controller_pid, 0)
                    except ChildProcessError:
                        pass
                if captured_pidfds:
                    _kill_and_close_linux_pidfds(captured_pidfds)

    def test_normal_real_child_and_grandchild_reach_platform_quiescence(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {
                    "synthetic_process_fixture_mode": "grandchild_success"
                }
            )
            result = supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
            if os.name == "nt":
                self._assert_pid_gone(output / "grandchild.pid")
            else:
                self.assertTrue((output / "grandchild.pid").is_file())
        self.assertEqual(result.observation["status"], "succeeded")
        self.assertEqual(result.stdout, b"grandchild-stdout\x00\xff")
        self.assertEqual(result.stderr, b"grandchild-stderr\x00\xfe")
        self.assertIs(result.observation["process_tree_quiescent"], True)

    def test_baseexception_cleanup_kills_real_grandchild_and_reraises(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "timeout"}
            )
            pid_path = output / "grandchild.pid"

            def interrupt_after_grandchild(*_args: object, **_kwargs: object) -> object:
                deadline = time.monotonic() + 2.0
                while not pid_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise SyntheticBrokerAbort("synthetic broker abort")

            with mock.patch.object(
                supervisor,
                "_monitor_process_v3",
                side_effect=interrupt_after_grandchild,
            ), self.assertRaisesRegex(SyntheticBrokerAbort, "synthetic broker abort"):
                self._run_fault_injected(argv, cwd=cwd)
            self._assert_pid_gone(pid_path)

    @unittest.skipIf(os.name == "nt", "POSIX isolated broker cleanup")
    def test_posix_public_broker_baseexception_cleans_backend_tree(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "timeout"}
            )
            pid_path = output / "grandchild.pid"

            def interrupt_outer_broker(
                *_args: object, **_kwargs: object
            ) -> object:
                deadline = time.monotonic() + 3.0
                while not pid_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertTrue(pid_path.is_file())
                raise SyntheticBrokerAbort("synthetic outer broker abort")

            with mock.patch.object(
                supervisor,
                "_monitor_process_v3",
                side_effect=interrupt_outer_broker,
            ), self.assertRaisesRegex(
                SyntheticBrokerAbort, "synthetic outer broker abort"
            ):
                supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
            self.assertTrue(pid_path.is_file())
            self.assertEqual(
                [
                    (thread.name, thread.ident, thread.is_alive())
                    for thread in threading.enumerate()
                    if thread.name.startswith(supervisor.READER_THREAD_PREFIX)
                ],
                [],
            )

    @unittest.skipIf(os.name == "nt", "POSIX isolated broker cleanup")
    def test_posix_broker_cleanup_fails_closed_after_leader_reaped(self) -> None:
        helper = (
            "import os,subprocess,sys;"
            "child=subprocess.Popen([sys.executable,'-c',"
            "'import time;time.sleep(60)'],stdin=subprocess.DEVNULL,"
            "stdout=None,stderr=subprocess.DEVNULL,"
            "shell=False,env={},close_fds=True);"
            "os.write(1,(str(child.pid)+'\\n').encode('ascii'))"
        )
        process = subprocess.Popen(
            [sys.executable, "-c", helper],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env={},
            cwd=str(ROOT),
            close_fds=True,
            start_new_session=True,
        )
        identity = supervisor._PosixBrokerIdentity(process)
        assert process.stdout is not None
        child_pid = int(process.stdout.readline().decode("ascii"))
        process.wait(timeout=3.0)
        self.assertTrue(_pid_is_running(child_pid))
        try:
            with self.assertRaisesRegex(
                supervisor.BackendPublicationProcessSupervisorV3Error,
                "leader custody was lost",
            ):
                supervisor._terminate_posix_broker(process, identity)
            self.assertTrue(_pid_is_running(child_pid))
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            identity.close()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()

    @unittest.skipIf(os.name == "nt", "POSIX pidfd identity contract")
    def test_reaped_broker_never_signals_ambiguous_reused_group(self) -> None:
        process = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env={},
            cwd=str(ROOT),
            close_fds=True,
            start_new_session=True,
        )
        identity = supervisor._PosixBrokerIdentity(process)
        try:
            stdout, stderr = process.communicate(timeout=3.0)
            self.assertEqual(stdout, b"")
            self.assertEqual(stderr, b"")
            with mock.patch.object(
                identity,
                "_pipe_holder_pids",
                return_value={424242},
            ), mock.patch.object(
                supervisor.os,
                "pidfd_open",
                side_effect=AssertionError(
                    "numeric holder PID was rebound after scan"
                ),
            ), mock.patch.object(
                supervisor.os,
                "killpg",
                side_effect=AssertionError("ambiguous PGID was signaled"),
            ), self.assertRaisesRegex(
                supervisor.BackendPublicationProcessSupervisorV3Error,
                "leader custody was lost",
            ):
                supervisor._terminate_posix_broker(process, identity)
        finally:
            identity.close()

    def test_operational_exception_is_normalized_after_tree_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "timeout"}
            )
            pid_path = output / "grandchild.pid"

            def fail_after_grandchild(
                *_args: object, **_kwargs: object
            ) -> object:
                deadline = time.monotonic() + 2.0
                while not pid_path.is_file() and time.monotonic() < deadline:
                    time.sleep(0.01)
                raise PermissionError("noncanonical-operational-detail")

            with mock.patch.object(
                supervisor,
                "_monitor_process_v3",
                side_effect=fail_after_grandchild,
            ), self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as raised:
                self._run_fault_injected(argv, cwd=cwd)
            self.assertIsNone(raised.exception.observation)
            self.assertEqual(
                str(raised.exception),
                "backend publication process supervision failed",
            )
            self._assert_pid_gone(pid_path)

    def test_second_reader_start_failure_cleans_partial_setup(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "timeout"}
            )
            real_start = threading.Thread.start
            starts = 0

            def fail_second_reader(thread: threading.Thread) -> None:
                nonlocal starts
                if thread.name.startswith(supervisor.READER_THREAD_PREFIX):
                    starts += 1
                    if starts == 2:
                        raise OSError("synthetic second reader start failure")
                real_start(thread)

            with mock.patch.object(
                supervisor.threading.Thread,
                "start",
                new=fail_second_reader,
            ), self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as raised:
                self._run_fault_injected(argv, cwd=cwd)
            self.assertEqual(
                str(raised.exception),
                "backend publication process supervision failed",
            )
            self.assertIsNone(raised.exception.observation)
            self.assertFalse(
                any(
                    thread.name.startswith(supervisor.READER_THREAD_PREFIX)
                    for thread in threading.enumerate()
                )
            )

    @unittest.skipIf(os.name == "nt", "POSIX isolated broker setup")
    def test_posix_outer_second_reader_start_failure_cleans_broker(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(
                Path(raw), {"synthetic_process_fixture_mode": "timeout"}
            )
            real_start = threading.Thread.start
            starts = 0

            def fail_second_reader(thread: threading.Thread) -> None:
                nonlocal starts
                if thread.name.startswith(supervisor.READER_THREAD_PREFIX):
                    starts += 1
                    if starts == 2:
                        raise OSError("synthetic outer reader start failure")
                real_start(thread)

            with mock.patch.object(
                supervisor.threading.Thread,
                "start",
                new=fail_second_reader,
            ), self.assertRaises(
                supervisor.BackendPublicationProcessSupervisorV3Error
            ) as raised:
                supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
            self.assertEqual(
                str(raised.exception),
                "backend publication POSIX broker supervision failed",
            )
            self.assertFalse(
                any(
                    thread.name.startswith(supervisor.READER_THREAD_PREFIX)
                    for thread in threading.enumerate()
                )
            )

    @unittest.skipIf(os.name == "nt", "POSIX isolated broker contract")
    def test_posix_multithreaded_caller_is_isolated_from_subreaper(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            argv, cwd, _output = self._invocation(Path(raw), {})
            results: list[object] = []

            def worker() -> None:
                try:
                    results.append(
                        supervisor.run_backend_publication_process_v3(
                            argv, cwd=cwd
                        )
                    )
                except BaseException as exc:
                    results.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(10.0)
            self.assertFalse(thread.is_alive())
            self.assertEqual(len(results), 1)
            self.assertIsInstance(
                results[0], supervisor.BackendPublicationProcessRunV3
            )
            result = results[0]
            assert isinstance(
                result, supervisor.BackendPublicationProcessRunV3
            )
            self.assertEqual(result.observation["status"], "succeeded")

    def test_repeated_real_tree_success_leaves_no_broker_reader_threads(self) -> None:
        prefix = supervisor.READER_THREAD_PREFIX
        before = {thread.ident for thread in threading.enumerate() if thread.name.startswith(prefix)}
        for _index in range(8):
            with tempfile.TemporaryDirectory() as raw:
                argv, cwd, _output = self._invocation(
                    Path(raw), {
                        "synthetic_process_fixture_mode": "grandchild_success"
                    }
                )
                result = supervisor.run_backend_publication_process_v3(argv, cwd=cwd)
                self.assertEqual(result.observation["status"], "succeeded")
        after = {thread.ident for thread in threading.enumerate() if thread.name.startswith(prefix)}
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main()
