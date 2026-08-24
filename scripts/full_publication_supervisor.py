#!/usr/bin/env python3
"""Durable retry supervisor for the multi-week full publication benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence


EXIT_COMPLETE = 0
EXIT_TRANSIENT = 75
EXIT_PERMANENT = 78
PHASES = ("run", "verify", "finalize", "export")
STATE_SCHEMA_VERSION = 1
STATE_FIELDS = {
    "schema_version",
    "artifact_kind",
    "command_identity_sha256",
    "phase",
    "attempt_seq",
    "transient_streak",
    "unexpected_streak",
    "last_exit_code",
    "last_artifact_kind",
    "last_payload_sha256",
    "updated_at",
    "completed_at",
}


class SupervisorError(RuntimeError):
    pass


class InvocationUnavailable(SupervisorError):
    pass


class UnexpectedProcessExit(SupervisorError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise SupervisorError(f"supervisor value is not canonical JSON: {error}") from error


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SupervisorError(f"invalid supervisor state: {error}") from error
    if type(value) is not dict:
        raise SupervisorError("invalid supervisor state: expected an object")
    return value


@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            if handle.read(1) == b"":
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise SupervisorError("another full publication supervisor holds the lock") from None
        else:
            import fcntl

            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise SupervisorError("another full publication supervisor holds the lock") from None
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == "nt":
                import msvcrt

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


class SubprocessEntrypointInvoker:
    """Invoke a fresh entrypoint process without persisting credentials."""

    def __init__(
        self,
        *,
        entrypoint: Path,
        entrypoint_args: Sequence[str],
        python_executable: str = sys.executable,
        run_process: Callable[..., Any] = subprocess.run,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.entrypoint = Path(entrypoint).resolve()
        self.entrypoint_args = tuple(str(value) for value in entrypoint_args)
        self.python_executable = str(python_executable)
        self.run_process = run_process
        self.environment = dict(os.environ if environment is None else environment)
        if not self.entrypoint.is_file():
            raise SupervisorError(f"full publication entrypoint is missing: {self.entrypoint}")
        if any(value in PHASES for value in self.entrypoint_args):
            raise SupervisorError("entrypoint arguments must not contain a command phase")

    @property
    def command_identity(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "entrypoint": str(self.entrypoint),
            "entrypoint_sha256": hashlib.sha256(self.entrypoint.read_bytes()).hexdigest(),
            "python_executable": str(Path(self.python_executable).resolve()),
            "entrypoint_args": list(self.entrypoint_args),
        }

    def __call__(self, phase: str) -> tuple[int, dict[str, Any]]:
        if phase not in PHASES:
            raise SupervisorError(f"unsupported supervisor phase: {phase}")
        command = [
            self.python_executable,
            str(self.entrypoint),
            *self.entrypoint_args,
            phase,
        ]
        try:
            completed = self.run_process(
                command,
                text=True,
                capture_output=True,
                check=False,
                env=self.environment,
            )
        except OSError:
            raise InvocationUnavailable("entrypoint process could not be started") from None
        return_code = int(completed.returncode)
        if return_code not in {EXIT_COMPLETE, EXIT_TRANSIENT, EXIT_PERMANENT}:
            raise UnexpectedProcessExit(
                f"entrypoint terminated with unexpected exit code {return_code}"
            )
        stdout = str(completed.stdout).strip()
        secret_values = {
            value
            for name, value in self.environment.items()
            if name in {"VAST_SEAFILE_UPLOAD_LINK", "VAST_SEAFILE_READ_LINK"}
            and value
        }
        secret_values.update(
            value.rstrip("/").rsplit("/", 1)[-1]
            for value in tuple(secret_values)
            if len(value.rstrip("/").rsplit("/", 1)[-1]) >= 8
        )
        if any(secret in stdout or secret in str(completed.stderr) for secret in secret_values):
            raise SupervisorError("entrypoint output exposed a configured capability secret")
        try:
            payload = json.loads(stdout)
        except json.JSONDecodeError:
            raise SupervisorError("entrypoint stdout is not one JSON object") from None
        if type(payload) is not dict:
            raise SupervisorError("entrypoint stdout must be a JSON object")
        _canonical_json(payload)
        return return_code, payload


class FullPublicationSupervisor:
    def __init__(
        self,
        *,
        state_path: Path | str,
        invoker: Callable[[str], tuple[int, dict[str, Any]]],
        command_identity: Mapping[str, Any],
        backoff_s: Sequence[float] = (30.0, 60.0, 120.0, 300.0, 600.0, 900.0),
        max_unexpected_retries: int = 3,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.state_path = Path(state_path).resolve()
        self.lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        self.invoker = invoker
        self.command_identity_sha256 = _sha256(dict(command_identity))
        self.backoff_s = tuple(float(value) for value in backoff_s)
        if not self.backoff_s or any(not math.isfinite(value) or value < 0 for value in self.backoff_s):
            raise SupervisorError("supervisor backoff must contain finite non-negative values")
        if type(max_unexpected_retries) is not int or max_unexpected_retries < 0:
            raise SupervisorError("max_unexpected_retries must be a non-negative integer")
        self.max_unexpected_retries = max_unexpected_retries
        self.sleep_fn = sleep_fn

    def _initial_state(self) -> dict[str, Any]:
        return {
            "schema_version": STATE_SCHEMA_VERSION,
            "artifact_kind": "vast_full_publication_supervisor_state",
            "command_identity_sha256": self.command_identity_sha256,
            "phase": "run",
            "attempt_seq": 0,
            "transient_streak": 0,
            "unexpected_streak": 0,
            "last_exit_code": None,
            "last_artifact_kind": None,
            "last_payload_sha256": None,
            "updated_at": _utc_now(),
            "completed_at": None,
        }

    def _load_state(self) -> dict[str, Any]:
        state = _read_json(self.state_path) if self.state_path.exists() else self._initial_state()
        if set(state) != STATE_FIELDS:
            raise SupervisorError("supervisor state fields have drifted")
        if state.get("schema_version") != STATE_SCHEMA_VERSION or state.get("artifact_kind") != "vast_full_publication_supervisor_state":
            raise SupervisorError("supervisor state schema has drifted")
        if state.get("command_identity_sha256") != self.command_identity_sha256:
            raise SupervisorError("supervisor command identity drift")
        if state.get("phase") not in set(PHASES) | {"complete", "failed_permanent"}:
            raise SupervisorError("supervisor phase is invalid")
        for field in ("attempt_seq", "transient_streak", "unexpected_streak"):
            if type(state.get(field)) is not int or state[field] < 0:
                raise SupervisorError(f"supervisor {field} is invalid")
        return state

    @staticmethod
    def _validate_success(phase: str, payload: Mapping[str, Any]) -> None:
        kind = payload.get("artifact_kind")
        if phase == "run":
            if (
                kind != "vast_full_publication_command_result"
                or payload.get("exit_code") != EXIT_COMPLETE
                or payload.get("status") != "complete"
                or type(payload.get("completed_pairs")) is not int
                or payload.get("completed_pairs") != payload.get("total_pairs")
                or payload.get("completed_arms") != payload.get("total_arms")
            ):
                raise SupervisorError("successful run payload is not complete")
        elif phase == "verify":
            if kind != "vast_full_publication_verification" or payload.get("passed") is not True or payload.get("complete") is not True:
                raise SupervisorError("successful verification payload is incomplete")
        elif phase == "finalize":
            if kind != "vast_full_publication_finalization" or payload.get("verified") is not True:
                raise SupervisorError("successful finalization payload is invalid")
        elif phase == "export":
            if kind != "vast_full_publication_compact_result_bundle":
                raise SupervisorError("successful export payload is invalid")

    def _persist_outcome(
        self,
        state: dict[str, Any],
        *,
        exit_code: int | None,
        payload: Mapping[str, Any] | None,
    ) -> None:
        state["attempt_seq"] += 1
        state["last_exit_code"] = exit_code
        state["last_artifact_kind"] = (
            str(payload.get("artifact_kind", "")) if payload is not None else None
        )
        state["last_payload_sha256"] = _sha256(dict(payload)) if payload is not None else None
        state["updated_at"] = _utc_now()
        _atomic_write_json(self.state_path, state)

    def _delay(self, streak: int) -> None:
        self.sleep_fn(self.backoff_s[min(max(streak - 1, 0), len(self.backoff_s) - 1)])

    def run(self) -> tuple[int, dict[str, Any]]:
        with _exclusive_lock(self.lock_path):
            state = self._load_state()
            if state["phase"] == "complete":
                return EXIT_COMPLETE, state
            if state["phase"] == "failed_permanent":
                return EXIT_PERMANENT, state

            while state["phase"] in PHASES:
                phase = str(state["phase"])
                try:
                    exit_code, payload = self.invoker(phase)
                except (InvocationUnavailable, UnexpectedProcessExit):
                    state["unexpected_streak"] += 1
                    self._persist_outcome(state, exit_code=None, payload=None)
                    if state["unexpected_streak"] > self.max_unexpected_retries:
                        state["phase"] = "failed_permanent"
                        state["updated_at"] = _utc_now()
                        _atomic_write_json(self.state_path, state)
                        return EXIT_PERMANENT, state
                    self._delay(state["unexpected_streak"])
                    continue
                except SupervisorError:
                    state["phase"] = "failed_permanent"
                    self._persist_outcome(state, exit_code=None, payload=None)
                    return EXIT_PERMANENT, state

                if exit_code not in {EXIT_COMPLETE, EXIT_TRANSIENT, EXIT_PERMANENT}:
                    raise SupervisorError("invoker returned an unsupported exit code")
                state["unexpected_streak"] = 0
                if exit_code == EXIT_TRANSIENT:
                    state["transient_streak"] += 1
                    self._persist_outcome(state, exit_code=exit_code, payload=payload)
                    self._delay(state["transient_streak"])
                    continue
                if exit_code == EXIT_PERMANENT:
                    state["phase"] = "failed_permanent"
                    self._persist_outcome(state, exit_code=exit_code, payload=payload)
                    return EXIT_PERMANENT, state

                try:
                    self._validate_success(phase, payload)
                except SupervisorError:
                    state["phase"] = "failed_permanent"
                    self._persist_outcome(
                        state, exit_code=EXIT_PERMANENT, payload=payload
                    )
                    return EXIT_PERMANENT, state
                state["transient_streak"] = 0
                state["phase"] = PHASES[PHASES.index(phase) + 1] if phase != "export" else "complete"
                if state["phase"] == "complete":
                    state["completed_at"] = _utc_now()
                self._persist_outcome(state, exit_code=exit_code, payload=payload)

            return EXIT_COMPLETE, state


def _parse_backoff(value: str) -> tuple[float, ...]:
    try:
        result = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    except ValueError:
        raise argparse.ArgumentTypeError("backoff must be comma-separated seconds") from None
    if not result or any(not math.isfinite(item) or item < 0 for item in result):
        raise argparse.ArgumentTypeError("backoff must contain finite non-negative seconds")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Supervise the full VAST publication run.")
    parser.add_argument(
        "--entrypoint",
        type=Path,
        default=Path(__file__).with_name("full_publication_entrypoint.py"),
    )
    parser.add_argument("--state-path", type=Path, required=True)
    parser.add_argument("--python-executable", default=sys.executable)
    parser.add_argument("--backoff-s", type=_parse_backoff, default=_parse_backoff("30,60,120,300,600,900"))
    parser.add_argument("--max-unexpected-retries", type=int, default=3)
    parser.add_argument("entrypoint_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    entrypoint_args = list(args.entrypoint_args)
    if entrypoint_args[:1] == ["--"]:
        entrypoint_args.pop(0)
    try:
        invoker = SubprocessEntrypointInvoker(
            entrypoint=args.entrypoint,
            entrypoint_args=entrypoint_args,
            python_executable=args.python_executable,
        )
        command_identity = dict(invoker.command_identity)
        command_identity["supervisor_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        supervisor = FullPublicationSupervisor(
            state_path=args.state_path,
            invoker=invoker,
            command_identity=command_identity,
            backoff_s=args.backoff_s,
            max_unexpected_retries=args.max_unexpected_retries,
        )
        exit_code, state = supervisor.run()
    except SupervisorError as error:
        exit_code = EXIT_PERMANENT
        state = {
            "schema_version": 1,
            "artifact_kind": "vast_full_publication_supervisor_error",
            "status": "permanent_error",
            "message": str(error),
        }
    print(json.dumps(state, indent=2, sort_keys=True, ensure_ascii=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "EXIT_COMPLETE",
    "EXIT_PERMANENT",
    "EXIT_TRANSIENT",
    "FullPublicationSupervisor",
    "InvocationUnavailable",
    "SubprocessEntrypointInvoker",
    "SupervisorError",
    "UnexpectedProcessExit",
    "build_parser",
    "main",
]
