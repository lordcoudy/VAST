"""Proposed private Windows capture support. No command-line entrypoint or authority."""
from __future__ import annotations

import ast
import copy
import ctypes
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
from typing import Any

SUPERVISOR_BYTES = 124707
SUPERVISOR_SHA256 = "99f772665d0d271b24d98f2393a50a0f9e0bbfe5c2840e5ccce65d89a84ed13e"
OWNER_DEFINITION_BYTES = 7981
OWNER_DEFINITION_SHA256 = "54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3"
STATIC_ARGUMENTS = {
    "model_review": (
        "--resume", "01a17ad0-d506-76d3-95b3-ddb27d4f3f5e",
        "--no-memory", "--no-auto-update", "--no-subagents", "--disable-web-search",
        "--tools", "read_file,grep,list_dir", "--disallowed-tools", "read_file,grep,list_dir",
        "--deny", "Read", "--deny", "Grep", "--deny", "Bash", "--deny", "Edit",
        "--deny", "Write", "--deny", "MCPTool", "--max-turns", "4", "--output-format", "json",
        "--prompt-file", r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST\openspec\changes\fix-accepted-policy-preprocessing\evidence\blocker-implementation-20261026-01\B3-B4-current-source-grok-prompt-03.original.txt",
    ),
    "inspect": ("inspect", "--json"),
    "plugin": ("plugin", "list", "--json"),
    "mcp": ("mcp", "list", "--json"),
}
CONTROL_PROGRAMS = {
    "control_normal": "import os;os.write(1,b'out\\n');os.write(2,b'err\\n')",
    "control_descendant": (
        "import os,subprocess,sys;"
        "subprocess.Popen([sys.executable,'-I','-B','-S','-c',"
        "'import time;time.sleep(30)'],stdout=sys.stdout,stderr=sys.stderr,close_fds=True);"
        "os.write(1,b'parent\\n')"
    ),
    "control_overflow": "import os;os.write(1,b'x'*2048)",
}


def load_reviewed_job(source: Path):
    """Load only the two authenticated classes, never the supervisor module."""
    if os.name != "nt":
        raise ValueError("Windows-only support")
    before = source.lstat()
    if (
        not stat.S_ISREG(before.st_mode) or source.is_symlink()
        or getattr(before, "st_file_attributes", 0) & 0x400
        or before.st_nlink != 1 or before.st_size != SUPERVISOR_BYTES
        or source.resolve(strict=True) != source
    ):
        raise ValueError("reviewed owner source unavailable")
    descriptor = os.open(source, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
    primary = None
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ):
            raise ValueError("reviewed owner source changed")
        raw = bytearray()
        while True:
            part = os.read(descriptor, min(16384, SUPERVISOR_BYTES - len(raw) + 1))
            if not part:
                break
            if len(part) > SUPERVISOR_BYTES - len(raw):
                raise ValueError("reviewed owner source grew")
            raw.extend(part)
        if len(raw) != SUPERVISOR_BYTES or hashlib.sha256(raw).hexdigest() != SUPERVISOR_SHA256:
            raise ValueError("reviewed owner source differs")
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns
        ):
            raise ValueError("reviewed owner source changed")
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException as close_error:
            if primary is not None and close_error is not primary:
                raise primary from close_error
            raise
    return load_reviewed_job_bytes(bytes(raw))


def load_reviewed_job_bytes(raw: bytes):
    """Accept authenticated captured bytes for a literal, path-free bootstrap."""
    if os.name != "nt" or type(raw) is not bytes or len(raw) != SUPERVISOR_BYTES:
        raise ValueError("reviewed owner source unavailable")
    if hashlib.sha256(raw).hexdigest() != SUPERVISOR_SHA256:
        raise ValueError("reviewed owner source differs")
    return _compile_reviewed_classes(raw)


def load_reviewed_job_definitions(raw: bytes):
    """Exactly the two unchanged class spans, bound back to the frozen source."""
    if os.name != "nt" or type(raw) is not bytes or len(raw) != OWNER_DEFINITION_BYTES:
        raise ValueError("reviewed owner definitions unavailable")
    if hashlib.sha256(raw).hexdigest() != OWNER_DEFINITION_SHA256:
        raise ValueError("reviewed owner definitions differ")
    return _compile_reviewed_classes(raw)


def _compile_reviewed_classes(raw: bytes):
    tree = ast.parse(raw, filename="authenticated-publication-owner")
    names = ("BackendPublicationProcessSupervisorV3Error", "_WindowsJob")
    selected = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    if tuple(node.name for node in selected) != names:
        raise ValueError("reviewed owner definitions unavailable")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    unit = ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[]))
    namespace = {
        "__name__": "_pr9_reviewed_windows_owner",
        "os": os, "ctypes": ctypes, "subprocess": subprocess, "copy": copy, "Any": Any,
    }
    exec(compile(unit, "authenticated-publication-owner", "exec"), namespace)
    return namespace["_WindowsJob"]


class WindowsObservation:
    def __init__(self):
        if os.name != "nt":
            raise ValueError("Windows-only support")
        from ctypes import wintypes
        self.types = wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.tick = self.kernel.GetTickCount64
        self.tick.argtypes = []
        self.tick.restype = ctypes.c_ulonglong
        self.times = self.kernel.GetProcessTimes
        self.times.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        self.times.restype = wintypes.BOOL

    def require_main_thread(self):
        # Asynchronous ReadFile requires no single-native-thread premise.
        if threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
            raise ValueError("closed main-thread capture required")
        return threading.get_native_id()

    def creation_time(self, process):
        rows = [self.types.FILETIME() for _ in range(4)]
        if not self.times(self.types.HANDLE(int(process._handle)), *(ctypes.byref(row) for row in rows)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (int(rows[0].dwHighDateTime) << 32) | int(rows[0].dwLowDateTime)




def bounded_environment(value: dict[str, str]) -> dict[str, str]:
    if type(value) is not dict or len(value) > 64:
        raise ValueError("reviewed environment bound")
    units = 1
    for name, item in value.items():
        if (
            type(name) is not str or type(item) is not str
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) is None
            or len(item) > 4096 or "\0" in item
        ):
            raise ValueError("reviewed environment scalar")
        units += len((name + "=" + item + "\0").encode("utf-16-le")) // 2
        if units > 32768:
            raise ValueError("reviewed environment aggregate")
    return value.copy()


# Strong process-global custody: pending Overlapped destructors can wait(TRUE).
# A poisoned controller may not start another capture; the bootstrap uses os._exit.
_QUARANTINED_READERS = [None, None]


def capture_literal(
    *, mode: str, executable: str, cwd: Path, environment: dict[str, str],
    deadline_tick_ms: int, job_type, observation: WindowsObservation,
    private_outputs: tuple[Path, Path] | None,
):
    """Closed auxiliary capture. Private bytes/exception objects stay private."""
    if any(operation is not None for operation in _QUARANTINED_READERS):
        raise ValueError("controller has unsettled overlapped ownership")
    control = mode in CONTROL_PROGRAMS
    if mode not in STATIC_ARGUMENTS and not control:
        raise ValueError("literal capture mode required")
    if control:
        if executable != sys.executable or private_outputs is not None:
            raise ValueError("fixed control executable and memory storage required")
        command = [sys.executable, "-I", "-B", "-S", "-c", CONTROL_PROGRAMS[mode]]
        limit = 1024
    else:
        if private_outputs is None or len(private_outputs) != 2:
            raise ValueError("private static channel pair required")
        command = [executable, *STATIC_ARGUMENTS[mode]]
        limit = 524288 if mode == "model_review" else 262144
    if type(deadline_tick_ms) is not int or not 0 < deadline_tick_ms - observation.tick() <= (600000 if mode == "model_review" else 180000):
        raise ValueError("inherited preparation deadline required")
    child_environment = bounded_environment(environment)
    entry_thread_id = observation.require_main_thread()
    observe_end = deadline_tick_ms - (30000 if mode == "model_review" else 15000)
    model_poll_counts = {"collection": 0, "retirement": 0, "cancel": 0} if mode == "model_review" else None

    def count_model_poll(role, maximum):
        if model_poll_counts is not None:
            if model_poll_counts[role] >= maximum:
                raise OverflowError("model poll count bound")
            model_poll_counts[role] += 1

    channels = [{
        "observed_bytes": 0, "written_prefix_bytes": 0, "discarded_bytes_lower_bound": 0,
        "write_extent_unknown": False, "retention_failed": False, "eof": False, "overflow": False,
        "fsync_completed": None if control else False, "close_completed": False,
        "read_starts": 0, "read_completions": 0, "pending_ever": False,
        "io_settled": False, "read_failed": False, "cancel_requested": False,
        "cancel_completed": False, "quarantined": False,
    } for _ in range(2)]
    prefixes = [bytearray(), bytearray()]
    descriptors = [None, None]
    read_handles = [None, None]
    write_handles = [None, None]
    write_fds = [None, None]
    readers = [None, None]
    pipe_closed = [False, False]
    parent_writers_closed = [False, False]
    labels = ("stdout", "stderr")
    process = job = None
    phase = "capture_setup"
    primary = None
    secondary = []
    cause_overflow = False
    forced = resumed = assigned = False
    active_after = None
    job_closed = process_handle_closed = False
    creation_time = root_pid = returncode = None
    observation_completed_tick = retirement_completed_tick = retirement_end = None
    kill_on_close = False
    modules_ready = False

    def fail(code, error):
        nonlocal primary, cause_overflow
        if primary is None:
            primary = (code, error)
        elif error is not primary[1] and not any(error is previous[1] for previous in secondary):
            if len(secondary) < 16:
                secondary.append((code, error))
            else:
                cause_overflow = True

    def require_observation_window():
        if observation.tick() >= observe_end:
            raise TimeoutError("preparation observation deadline")

    def retain(index, data):
        nonlocal phase
        row = channels[index]
        if type(data) is not bytes or len(data) > 4096:
            raise ValueError("overlapped read extent differs")
        if not data:
            row["eof"] = True
            return
        if row["observed_bytes"] > (1 << 64) - 1 - len(data):
            raise OverflowError("capture observation bound")
        row["observed_bytes"] += len(data)
        remaining = limit - row["written_prefix_bytes"]
        keep = 0 if row["write_extent_unknown"] or row["retention_failed"] else min(remaining, len(data))
        if keep:
            view = memoryview(data)[:keep]
            while view:
                count = len(view)
                if not control:
                    try:
                        phase = labels[index] + "_write"
                        count = os.write(descriptors[index], view)
                        if count <= 0 or count > len(view):
                            raise OSError("capture write stalled")
                    except BaseException:
                        row["write_extent_unknown"] = True
                        raise
                    row["written_prefix_bytes"] += count
                try:
                    phase = labels[index] + "_retain"
                    prefixes[index].extend(view[:count])
                except BaseException:
                    row["retention_failed"] = True
                    raise
                if control:
                    row["written_prefix_bytes"] += count
                view = view[count:]
        row["discarded_bytes_lower_bound"] += len(data) - keep
        if len(data) > remaining:
            row["overflow"] = True

    def read_completed(*, start=True):
        nonlocal phase
        for index in range(2):
            row = channels[index]
            if read_handles[index] is None or row["eof"] or row["read_failed"]:
                continue
            operation = readers[index]
            if operation is None:
                if not start:
                    continue
                if row["read_starts"] >= 65536:
                    raise OverflowError("overlapped start count bound")
                phase = labels[index] + "_read_start"
                operation = overlapped.Overlapped(0)
                readers[index] = operation  # Custody precedes the native call.
                _QUARANTINED_READERS[index] = operation
                row["read_starts"] += 1
                try:
                    operation.ReadFile(read_handles[index], 4096)
                except BaseException as error:
                    # CPython marks direct ReadFile109 completed; 233 does not.
                    if isinstance(error, OSError) and error.winerror == 109 and not operation.pending:
                        readers[index] = None
                        _QUARANTINED_READERS[index] = None
                        row["read_completions"] += 1
                        row["eof"] = True
                        continue
                    row["read_failed"] = True
                    raise
            phase = labels[index] + "_read_poll"
            if operation.pending:
                row["pending_ever"] = True
                continue
            phase = labels[index] + "_read_result"
            try:
                data = operation.getresult(False)
            except BaseException:
                row["read_failed"] = True
                readers[index] = None  # Completion was observed, not pending.
                _QUARANTINED_READERS[index] = None
                raise
            readers[index] = None
            _QUARANTINED_READERS[index] = None
            row["read_completions"] += 1
            retain(index, data)

    def close_writer(index):
        nonlocal phase
        if write_fds[index] is not None:
            phase = labels[index] + "_parent_writer_close"
            descriptor = write_fds[index]
            write_fds[index] = None  # Do not retry an ambiguously closed CRT fd.
            os.close(descriptor)
            parent_writers_closed[index] = True
        elif write_handles[index] is not None:
            phase = labels[index] + "_parent_raw_writer_close"
            handle = write_handles[index]
            write_handles[index] = None
            winapi.CloseHandle(handle)
            parent_writers_closed[index] = True

    try:
        phase = "reader_import"
        require_observation_window()
        # _overlapped initialization creates/closes one unconnected discovery
        # socket. It makes no connect request. No bytecode is written (-B).
        import _overlapped as overlapped
        import _winapi as winapi
        import msvcrt
        from asyncio import windows_utils
        modules_ready = True
        require_observation_window()
        for index in range(2):
            if not control:
                phase = labels[index] + "_capture_open"
                require_observation_window()
                descriptors[index] = os.open(
                    private_outputs[index], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY | os.O_NOINHERIT,
                    0o600,
                )
            phase = labels[index] + "_pipe_pair"
            require_observation_window()
            # The installed helper requests8KiB, uses one instance and <=21
            # collision attempts, and connects its own client before returning.
            read_handles[index], write_handles[index] = windows_utils.pipe(
                overlapped=(True, False), bufsize=8192,
            )
            phase = labels[index] + "_writer_fd"
            write_fds[index] = msvcrt.open_osfhandle(
                write_handles[index], os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT,
            )
            write_handles[index] = None  # CRT descriptor now owns this handle.
        phase = "job_create"
        require_observation_window()
        job = job_type()
        kill_on_close = job.kill_on_close
        phase = "process_create"
        require_observation_window()
        process = subprocess.Popen(
            command, cwd=cwd, env=child_environment, stdin=subprocess.DEVNULL,
            stdout=write_fds[0], stderr=write_fds[1], close_fds=True,
            creationflags=0x00000004 | subprocess.CREATE_NO_WINDOW,
        )
        root_pid = process.pid
        phase = "process_identity"
        creation_time = observation.creation_time(process)
        phase = "job_assign"
        require_observation_window()
        job.assign(process)
        assigned = True
        # EOF must depend only on child copies before the child is resumed.
        for index in range(2):
            close_writer(index)
        phase = "process_resume"
        require_observation_window()
        job.resume(process)
        resumed = True
        while True:
            count_model_poll("collection", 60000)
            phase = "capture_read"
            require_observation_window()
            read_completed()
            if any(row["overflow"] for row in channels):
                phase = "channel_overflow"
                raise OverflowError("capture channel bound")
            phase = "process_poll"
            returncode = process.poll()
            phase = "job_accounting"
            active = job.active_processes()
            if returncode is not None:
                if active:
                    raise RuntimeError("root exited with owned processes still active")
                if all(row["eof"] for row in channels):
                    if returncode:
                        raise RuntimeError("literal command returned nonzero")
                    phase = "observation_completion_clock"
                    observation_completed_tick = observation.tick()
                    if observation_completed_tick >= observe_end:
                        raise TimeoutError("preparation observation deadline")
                    break
            phase = "observation_sleep"
            time.sleep(0.01)
    except BaseException as error:
        fail(phase, error)
    finally:
        if modules_ready:
            for index in range(2):
                try:
                    close_writer(index)
                except BaseException as error:
                    fail(labels[index] + "_parent_writer_cleanup", error)
        if process is not None:
            try:
                returncode = process.poll()
                active = job.active_processes() if assigned else None
                if returncode is None or (active is not None and active > 0):
                    forced = True
                    if assigned:
                        job.terminate()
                    else:
                        process.kill()  # Original held handle, still suspended.
            except BaseException as error:
                fail("termination", error)
            try:
                phase = "retirement_clock"
                retirement_end = min(deadline_tick_ms - 7000, observation.tick() + 5000)
                while observation.tick() < retirement_end:
                    count_model_poll("retirement", 1000)
                    returncode = process.poll()
                    active_after = job.active_processes() if job is not None else None
                    read_completed()
                    if returncode is not None and active_after == 0 and all(row["eof"] for row in channels):
                        phase = "retirement_completion_clock"
                        retirement_completed_tick = observation.tick()
                        if retirement_completed_tick >= retirement_end:
                            raise TimeoutError("retirement observation deadline")
                        break
                    phase = "retirement_sleep"
                    time.sleep(0.01)
                    phase = "retirement_clock"
            except BaseException as error:
                fail("retirement_" + phase, error)
            if returncode is None or active_after != 0:
                fail("retirement_unknown", RuntimeError("owned retirement unavailable"))
        # Cancel without freeing pending storage; do not start further reads.
        if modules_ready:
            for index, operation in enumerate(readers):
                if operation is not None:
                    try:
                        if operation.pending:
                            channels[index]["cancel_requested"] = True
                            operation.cancel()
                    except BaseException as error:
                        fail(labels[index] + "_cancel", error)
            try:
                cancel_end = min(deadline_tick_ms - 5000, observation.tick() + 2000)
                while any(operation is not None for operation in readers) and observation.tick() < cancel_end:
                    count_model_poll("cancel", 1000)
                    for index, operation in enumerate(readers):
                        if operation is None or operation.pending:
                            continue
                        try:
                            data = operation.getresult(False)
                        except BaseException as error:
                            readers[index] = None
                            _QUARANTINED_READERS[index] = None
                            if isinstance(error, OSError) and error.winerror == 995 and channels[index]["cancel_requested"]:
                                channels[index]["cancel_completed"] = True
                            else:
                                fail(labels[index] + "_cancel_result", error)
                        else:
                            readers[index] = None
                            _QUARANTINED_READERS[index] = None
                            channels[index]["read_completions"] += 1
                            try:
                                retain(index, data)
                            except BaseException as error:
                                fail(labels[index] + "_cancel_retention", error)
                    if any(operation is not None for operation in readers):
                        time.sleep(0.01)
            except BaseException as error:
                fail("cancel_observation", error)
        for index, operation in enumerate(readers):
            if operation is not None:
                # Conservatively retain even if a completion check failed.
                _QUARANTINED_READERS[index] = operation
                channels[index]["quarantined"] = True
                fail(labels[index] + "_io_unsettled", RuntimeError("overlapped completion unavailable"))
            else:
                channels[index]["io_settled"] = True
        if process is not None and not all(row["eof"] for row in channels):
            fail("pipe_eof_unknown", RuntimeError("owned pipe EOF unavailable"))
        for index, descriptor in enumerate(descriptors):
            if descriptor is not None:
                try:
                    os.fsync(descriptor)
                    channels[index]["fsync_completed"] = True
                except BaseException as error:
                    fail(labels[index] + "_fsync", error)
                try:
                    os.close(descriptor)
                    channels[index]["close_completed"] = True
                except BaseException as error:
                    fail(labels[index] + "_close", error)
            elif control:
                channels[index]["close_completed"] = True
        if modules_ready:
            for index, handle in enumerate(read_handles):
                if handle is not None:
                    try:
                        winapi.CloseHandle(handle)
                        pipe_closed[index] = True
                    except BaseException as error:
                        fail(labels[index] + "_pipe_close", error)
        if process is not None:
            try:
                process._handle.Close()
                process_handle_closed = True
            except BaseException as error:
                fail("process_handle_close", error)
        if job is not None:
            try:
                job.close()
                job_closed = True
            except BaseException as error:
                fail("job_handle_close", error)
    finalized_prefixes = [None, None]
    for index in range(2):
        try:
            finalized_prefixes[index] = bytes(prefixes[index])
        except BaseException as error:
            channels[index]["retention_failed"] = True
            fail(labels[index] + "_retention_finalize", error)
    late = None
    try:
        late = observation.tick() >= deadline_tick_ms
    except BaseException as error:
        fail("completion_clock", error)
    for row in channels:
        row["remainder_unknown"] = not row["eof"]
    public = {
        "mode": mode, "storage": "memory_control" if control else "private_file",
        "entry_native_thread_id": entry_thread_id, "entry_python_thread_count": 1,
        "channel_limit": limit, "channels": channels, "original_pid": root_pid,
        "original_creation_filetime": creation_time, "returncode": returncode,
        "assigned_before_resume": assigned, "resumed": resumed,
        "active_after_retirement": active_after, "forced": forced,
        "job_kill_on_close": kill_on_close,
        "pipe_handles_closed": pipe_closed, "parent_writers_closed": parent_writers_closed,
        "reader_mode": "overlapped_readfile_no_reader_threads",
        "process_handle_closed": process_handle_closed, "job_handle_closed": job_closed,
        "deadline_exceeded": late, "deadline_tick_ms": deadline_tick_ms,
        "observe_end_tick": observe_end, "retirement_end_tick": retirement_end,
        "observation_completed_tick": observation_completed_tick,
        "retirement_completed_tick": retirement_completed_tick,
        "primary_code": None if primary is None else primary[0],
        "secondary_codes": [row[0] for row in secondary], "cause_overflow": cause_overflow,
    }
    if model_poll_counts is not None:
        public["model_poll_counts"] = model_poll_counts
    public["complete"] = bool(
        primary is None and not secondary and not cause_overflow and not forced and late is False
        and observation_completed_tick is not None and observation_completed_tick < observe_end
        and retirement_completed_tick is not None
        and assigned and resumed and active_after == 0 and returncode == 0
        and kill_on_close and job_closed and process_handle_closed
        and all(pipe_closed) and all(parent_writers_closed) and all(
            row["eof"] and row["io_settled"] and not row["quarantined"]
            and row["close_completed"] and not row["overflow"]
            and not row["write_extent_unknown"] and not row["retention_failed"]
            and (control or row["fsync_completed"]) for row in channels
        )
    )
    return {
        "facts": public, "private_channel_bytes": finalized_prefixes,
        "private_primary": primary, "private_secondary": tuple(secondary),
    }


# Definitions only. Physical controls and private Grok admissions are separate.

