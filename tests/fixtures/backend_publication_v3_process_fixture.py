#!/usr/bin/env python3
"""Transaction-compatible synthetic child fixture for v3 process tests."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path


_DEFAULT_STDOUT = b"synthetic-backend-publication-v3-stdout\n"
_DEFAULT_STDERR = b"synthetic-backend-publication-v3-stderr\n"


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise RuntimeError("synthetic fixture write failed")
        view = view[written:]


def _grandchild(arguments: list[str]) -> int:
    if len(arguments) != 3:
        return 91
    mode, duration_text, output_text = arguments
    if mode == "sleep":
        time.sleep(float(duration_text))
        return 0
    if mode == "double_detach_sleep":
        if os.name != "nt":
            os.setsid()
            if os.fork() != 0:
                return 0
        descriptor = os.open(os.devnull, os.O_RDWR)
        try:
            os.dup2(descriptor, 1)
            os.dup2(descriptor, 2)
        finally:
            if descriptor > 2:
                os.close(descriptor)
        if os.name != "nt":
            _publish_pid(Path(output_text), os.getpid())
        time.sleep(float(duration_text))
        return 0
    if mode == "emit":
        _write_all(1, b"grandchild-stdout\x00\xff")
        _write_all(2, b"grandchild-stderr\x00\xfe")
        return 0
    return 92


def _canonical_existing_path(value: object, *, directory: bool) -> Path:
    if type(value) is not str or not value or "\x00" in value:
        raise RuntimeError("synthetic fixture path is invalid")
    path = Path(value)
    resolved = path.resolve(strict=True)
    if not path.is_absolute() or os.path.normcase(os.path.normpath(value)) != (
        os.path.normcase(os.path.normpath(str(resolved)))
    ):
        raise RuntimeError("synthetic fixture path is not canonical")
    if resolved.is_dir() is not directory:
        raise RuntimeError("synthetic fixture path kind drifted")
    return resolved


def _evidence_names(contract: dict[str, object]) -> list[str]:
    protocol = contract.get("launcher_output_protocol")
    if type(protocol) is not dict:
        raise RuntimeError("synthetic fixture output protocol is missing")
    names = protocol.get("launcher_evidence_files")
    if type(names) is not list or not names:
        raise RuntimeError("synthetic fixture evidence names are invalid")
    checked: list[str] = []
    for name in names:
        if (
            type(name) is not str
            or not name
            or "\x00" in name
            or Path(name).name != name
            or name in {".", ".."}
        ):
            raise RuntimeError("synthetic fixture evidence name escaped")
        checked.append(name)
    if len({name.casefold() for name in checked}) != len(checked):
        raise RuntimeError("synthetic fixture evidence names collide")
    return checked


def _load_contract(
    arguments: list[str],
) -> tuple[dict[str, object], dict[str, object], Path, list[str]]:
    if len(arguments) != 8 or arguments[0::2] != [
        "--project-root",
        "--arm-contract",
        "--arm-contract-sha256",
        "--output-dir",
    ]:
        raise RuntimeError("synthetic fixture argv drifted")
    project_root = _canonical_existing_path(arguments[1], directory=True)
    if project_root != Path.cwd().resolve(strict=True):
        raise RuntimeError("synthetic fixture project root differs from cwd")
    contract_path = _canonical_existing_path(arguments[3], directory=False)
    payload = contract_path.read_bytes()
    if hashlib.sha256(payload).hexdigest() != arguments[5]:
        raise RuntimeError("synthetic fixture contract SHA drifted")
    scripts_root = _canonical_existing_path(
        str(Path(__file__).resolve().parents[2] / "scripts"), directory=True
    )
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))
    from backend_publication_dispatch_v3 import (
        parse_backend_publication_arm_contract_v3_bytes,
    )

    try:
        value = parse_backend_publication_arm_contract_v3_bytes(
            payload,
            expected_file_sha256=arguments[5],
        )
    except Exception as exc:
        raise RuntimeError("synthetic fixture arm contract is invalid") from exc
    runtime = value.get("runtime_inputs")
    if type(runtime) is not dict or type(runtime.get("dataset")) is not dict:
        raise RuntimeError("synthetic fixture runtime dataset is missing")
    output_dir = _canonical_existing_path(arguments[7], directory=True)
    if (
        runtime.get("project_root") != str(project_root)
        or runtime.get("arm_contract_path") != str(contract_path)
        or runtime.get("output_dir") != str(output_dir)
    ):
        raise RuntimeError("synthetic fixture runtime paths differ from argv")
    try:
        output_dir.relative_to(project_root)
    except ValueError as exc:
        raise RuntimeError("synthetic fixture output escaped project root") from exc
    return value, runtime["dataset"], output_dir, _evidence_names(value)


def _publish_pid(output_dir: Path, pid: int) -> None:
    temporary = output_dir / f".grandchild-{os.getpid()}.pid.tmp"
    published = output_dir / "grandchild.pid"
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    try:
        _write_all(descriptor, str(pid).encode("ascii"))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    try:
        os.link(temporary, published)
    finally:
        os.unlink(temporary)


def _spawn_grandchild(mode: str, output_dir: Path) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        [
            sys.executable,
            str(Path(__file__).resolve()),
            "--grandchild",
            mode,
            "60",
            str(output_dir),
        ],
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        shell=False,
        env={},
        cwd=os.getcwd(),
        close_fds=True,
    )
    published = output_dir / "grandchild.pid"
    try:
        if os.name == "nt" or mode != "double_detach_sleep":
            _publish_pid(output_dir, process.pid)
        if mode == "double_detach_sleep":
            deadline = time.monotonic() + 3.0
            while not published.is_file() and time.monotonic() < deadline:
                time.sleep(0.01)
            if not published.is_file():
                raise RuntimeError("detached grandchild did not become ready")
            if os.name != "nt":
                process.wait(timeout=3.0)
    except BaseException:
        if published.is_file():
            try:
                published_pid = int(published.read_text(encoding="ascii"))
                if published_pid != process.pid:
                    os.kill(published_pid, signal.SIGKILL)
            except (OSError, ValueError):
                pass
        try:
            process.kill()
        except OSError:
            pass
        try:
            process.wait(timeout=3.0)
        except (OSError, subprocess.TimeoutExpired):
            pass
        raise
    return process


def _create_evidence(output_dir: Path, names: list[str]) -> None:
    for name in names:
        payload = (
            b"VAST:synthetic-backend-publication-evidence:v3\0"
            + name.encode("utf-8")
            + b"\n"
        )
        path = output_dir / name
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        try:
            _write_all(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def _write_dual(stdout_size: int, stderr_size: int) -> None:
    stdout_thread = threading.Thread(
        target=_write_all, args=(1, b"O" * stdout_size)
    )
    stderr_thread = threading.Thread(
        target=_write_all, args=(2, b"E" * stderr_size)
    )
    stdout_thread.start()
    stderr_thread.start()
    stdout_thread.join()
    stderr_thread.join()


def _linux_security_probe() -> dict[str, object]:
    if os.name == "nt" or not sys.platform.startswith("linux"):
        raise RuntimeError("synthetic security probe requires Linux")
    status: dict[str, str] = {}
    for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            status[key] = value.strip()
    parent_pid = os.getppid()
    libc = ctypes.CDLL(None, use_errno=True)
    ptrace = libc.ptrace
    ptrace.restype = ctypes.c_long
    ctypes.set_errno(0)
    ptrace_result = int(ptrace(0x4206, parent_pid, 0, 0))
    ptrace_errno = ctypes.get_errno() if ptrace_result != 0 else 0
    if ptrace_result == 0:
        ptrace(17, parent_pid, 0, 0)
    try:
        os.unshare(os.CLONE_NEWNS)
    except OSError as exc:
        mount_namespace_unshare_errno = exc.errno
    else:
        mount_namespace_unshare_errno = 0
    try:
        os.kill(parent_pid, signal.SIGKILL)
    except PermissionError:
        parent_sigkill_call_returned = False
    else:
        parent_sigkill_call_returned = True
    time.sleep(0.05)
    try:
        os.kill(parent_pid, 0)
    except OSError:
        parent_alive_after_sigkill = False
    else:
        parent_alive_after_sigkill = True
    return {
        "cap_ambient": int(status.get("CapAmb", "-1"), 16),
        "cap_bounding": int(status.get("CapBnd", "-1"), 16),
        "cap_effective": int(status.get("CapEff", "-1"), 16),
        "cap_inheritable": int(status.get("CapInh", "-1"), 16),
        "cap_permitted": int(status.get("CapPrm", "-1"), 16),
        "mount_namespace_unshare_errno": mount_namespace_unshare_errno,
        "no_new_privs": int(status.get("NoNewPrivs", "-1")),
        "parent_pid": parent_pid,
        "parent_alive_after_sigkill": parent_alive_after_sigkill,
        "parent_sigkill_call_returned": parent_sigkill_call_returned,
        "ptrace_parent_errno": ptrace_errno,
    }


def _main(arguments: list[str]) -> int:
    if arguments[:1] == ["--grandchild"]:
        return _grandchild(arguments[1:])

    _contract, dataset, output_dir, evidence_names = _load_contract(arguments)
    mode = dataset.get("synthetic_process_fixture_mode", "success")
    if type(mode) is not str:
        return 93
    if mode in {"success", "nonzero"}:
        if mode == "success":
            _create_evidence(output_dir, evidence_names)
        _write_all(
            1,
            bytes.fromhex(
                str(dataset.get("synthetic_stdout_hex", _DEFAULT_STDOUT.hex()))
            ),
        )
        _write_all(
            2,
            bytes.fromhex(
                str(dataset.get("synthetic_stderr_hex", _DEFAULT_STDERR.hex()))
            ),
        )
        return 0 if mode == "success" else int(
            dataset.get("synthetic_exit_code", 7)
        )
    if mode in {"dual", "stdout_overflow", "stderr_overflow", "capture_overflow"}:
        stdout_size = int(dataset.get("synthetic_stdout_size", 0))
        stderr_size = int(dataset.get("synthetic_stderr_size", 0))
        _write_dual(
            stdout_size,
            stderr_size,
        )
        return 0
    if mode == "grandchild_success":
        _create_evidence(output_dir, evidence_names)
        child = _spawn_grandchild("emit", output_dir)
        return child.wait()
    if mode == "timeout":
        _spawn_grandchild("sleep", output_dir)
        time.sleep(60)
        return 0
    if mode == "grandchild_exit":
        _spawn_grandchild("sleep", output_dir)
        return 0
    if mode == "detached_exit":
        _spawn_grandchild("double_detach_sleep", output_dir)
        return 0
    if mode == "kill_broker_exit":
        _spawn_grandchild("double_detach_sleep", output_dir)
        try:
            os.kill(os.getppid(), signal.SIGKILL)
        except PermissionError:
            return 0
        time.sleep(1)
        return 0
    if mode == "security_probe":
        _write_all(
            1,
            json.dumps(
                _linux_security_probe(),
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode("ascii"),
        )
        return 0
    return 93


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
