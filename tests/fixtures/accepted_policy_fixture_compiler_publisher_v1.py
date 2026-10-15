"""D15 PID1 publisher for one fixed, separately qualified fixture compiler.

This module performs no work on import. It is not a compiler/provider selector.
The keyword effects on run_publisher_v1 are for portable unit tests only; main
uses the real defaults. Container admission, seccomp, immutable provider inputs
and the outer actual client/container closure remain the host owner's gates.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import select
import signal
import stat
import struct
import subprocess
import sys
import time


SOURCE_LIMIT = 8 * 1024 * 1024
ELF_LIMIT = 16 * 1024 * 1024
CHANNEL_LIMIT = 1024 * 1024
METADATA_LIMIT = 65536
EXPORT_LIMIT = 18939904
DEADLINE_SECONDS = 60
TERM_GRACE_SECONDS = 5
KILL_GRACE_SECONDS = 5
EXPORT_RESERVE_SECONDS = 5
COMMAND = ("/usr/bin/cc", "-O0", "-std=c11", "/work/engine.c", "-o", "/work/engine")
COMPILER_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": "/work",
                "TMPDIR": "/work", "TMP": "/work", "TEMP": "/work"}


class _Refusal(Exception):
    pass


def _get_limit(name):
    import resource  # Linux-only effect, deliberately not an import prerequisite.
    return resource.getrlimit(getattr(resource, "RLIMIT_" + name))


def _open_file(path, mode):
    flags = os.O_RDONLY if mode == "rb" else os.O_WRONLY | os.O_CREAT | os.O_EXCL
    # cc and the interpreter can be qualified provider symlinks; owned work
    # outputs cannot be symlinks. Resolution of provider paths is qualified by
    # the host's pinned provider-input manifest, never guessed here.
    if path.startswith("/work/"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags | os.O_CLOEXEC, 0o600)
    try:
        return os.fdopen(fd, mode, buffering=0)
    except BaseException:
        os.close(fd)
        raise


def _nonblocking(stream):
    os.set_blocking(stream.fileno(), False)


def _kill_group(pid, kind):
    os.killpg(pid, signal.SIGTERM if kind == "TERM" else signal.SIGKILL)


def _wait_child():
    pid, status = os.waitpid(-1, os.WNOHANG)
    return pid, os.waitstatus_to_exitcode(status) if pid else None


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _native_elf(header):
    return (len(header) >= 64 and header[:7] == b"\x7fELF\x02\x01\x01"
            and int.from_bytes(header[16:18], "little") in (2, 3)
            and int.from_bytes(header[18:20], "little") == 62
            and int.from_bytes(header[20:24], "little") == 1)


def _snapshot(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def run_publisher_v1(stdin, stdout, *, stderr=None, clock=time.monotonic,
                     process_factory=subprocess.Popen, wait_ready=select.select,
                     get_limit=_get_limit, get_pid=os.getpid, open_file=_open_file,
                     file_stat=os.fstat, sync_file=os.fsync, wait_child=_wait_child,
                     kill_group=_kill_group, set_handler=signal.signal,
                     make_nonblocking=_nonblocking):
    """Read exactly one request and return 0 only for an unforced complete export.

    A single absolute deadline includes request input, compiler/descendant reap,
    ELF observation and export. A blocked/failed export can leave an incomplete
    frame: the outer owner must retain that prefix and refuse it. No second
    frame, fallback compiler, output adoption, retry or deletion is attempted.
    """
    deadline = clock() + DEADLINE_SECONDS
    if stderr is None:
        stderr = getattr(sys.stderr.buffer, "raw", sys.stderr.buffer)
    causes = []
    received_signal = None
    process = None
    owned_pid = None
    returncode = None
    compiler_reaped = False
    descendants_reaped = False
    term_sent = False
    kill_sent = False
    term_until = None
    kill_until = None
    compile_until = deadline - TERM_GRACE_SECONDS - KILL_GRACE_SECONDS - EXPORT_RESERVE_SECONDS
    close_until = deadline - EXPORT_RESERVE_SECONDS
    source = {"size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}
    runtime = {"pid": None, "core": None, "fsize": None,
               "interpreter_elf64_amd64": False, "compiler_elf64_amd64": False}
    channels = {name: {"stream": None, "data": bytearray(), "observed": 0,
                       "eof": False, "failed": False}
                for name in ("stdout", "stderr")}

    def cause(code):
        if code not in causes:
            causes.append(code)

    def remaining(*, allow_signal=False):
        if received_signal is not None and not allow_signal:
            raise _Refusal(received_signal)
        left = deadline - clock()
        if left <= 0:
            raise _Refusal("deadline")
        return left

    def handler(number, frame):
        nonlocal received_signal
        code = "signal_term" if number == signal.SIGTERM else "signal_int"
        cause(code)
        if received_signal is None:
            received_signal = code

    def close(stream, code):
        if stream is not None:
            try:
                stream.close()
            except BaseException:
                cause(code)

    def ready(readers=(), writers=(), *, allow_signal=False):
        left = remaining(allow_signal=allow_signal)
        result = wait_ready(list(readers), list(writers), [], min(left, 0.05))
        remaining(allow_signal=allow_signal)
        return result

    def read_chunk(stream, count):
        while True:
            readers, _, _ = ready((stream,))
            if stream not in readers:
                continue
            try:
                data = stream.read(count)
            except BlockingIOError:
                continue
            remaining()
            if data is not None:
                if type(data) is not bytes or len(data) > count:
                    raise _Refusal("request_invalid")
                return data

    def read_exact(count):
        # The caller supplies a prevalidated finite count; charge before append.
        value = bytearray()
        while len(value) < count:
            data = read_chunk(stdin, min(65536, count - len(value)))
            if not data:
                raise _Refusal("request_truncated")
            value.extend(data)
        return bytes(value)

    def write_exact(stream, data, *, timed, allow_signal=False):
        offset = 0
        view = memoryview(data)
        while offset < len(view):
            if timed:
                _, writers, _ = ready(writers=(stream,), allow_signal=allow_signal)
                if stream not in writers:
                    continue
            try:
                written = stream.write(view[offset:offset + 65536])
            except BlockingIOError:
                continue
            if written is None:
                if timed:
                    continue
                raise OSError("unavailable write")
            if type(written) is not int or not 0 < written <= min(65536, len(view) - offset):
                raise OSError("short or invalid write")
            offset += written
            remaining(allow_signal=allow_signal)

    def runtime_elf(path):
        stream = open_file(path, "rb")
        try:
            before = file_stat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_size < 64:
                raise _Refusal("runtime_preflight_failed")
            header = bytearray()
            while len(header) < 64:
                remaining()
                part = stream.read(64 - len(header))
                if type(part) is not bytes or not 0 < len(part) <= 64 - len(header):
                    raise _Refusal("runtime_preflight_failed")
                header.extend(part)
            after = file_stat(stream.fileno())
            remaining()
            if _snapshot(before) != _snapshot(after) or not _native_elf(header):
                raise _Refusal("runtime_preflight_failed")
            return True
        except BaseException:
            cause("runtime_preflight_failed")
            raise
        finally:
            close(stream, "runtime_file_close_error")

    def reap():
        nonlocal returncode, compiler_reaped
        # pids.max=32 is separately qualified. Refuse a larger observation rather
        # than building an unbounded journal or claiming an incomplete empty set.
        for _ in range(33):
            try:
                pid, code = wait_child()
            except ChildProcessError:
                return True
            except BaseException:
                cause("descendant_reap_error")
                return False
            if pid == 0:
                return False
            if type(pid) is not int or pid < 1 or type(code) is not int:
                cause("descendant_status_invalid")
                return False
            if owned_pid is not None and pid == owned_pid:
                returncode, compiler_reaped = code, True
                process.returncode = code
            elif code != 0:
                cause("descendant_exit_nonzero")
        cause("descendant_inventory_overflow")
        return False

    def terminate(sig):
        nonlocal term_sent, kill_sent, term_until, kill_until
        if owned_pid is None:
            return
        if sig == "TERM":
            if term_sent:
                return
            term_sent = True
            term_until = min(clock() + TERM_GRACE_SECONDS,
                             close_until - KILL_GRACE_SECONDS)
            cause("compiler_term_attempted")
        else:
            if kill_sent:
                return
            kill_sent = True
            kill_until = min(clock() + KILL_GRACE_SECONDS, close_until)
            cause("compiler_kill_attempted")
        try:
            kill_group(owned_pid, sig)
        except ProcessLookupError:
            pass
        except BaseException:
            cause("compiler_group_signal_error")

    def observe_compiler():
        nonlocal returncode, compiler_reaped, descendants_reaped
        while True:
            try:
                remaining(allow_signal=True)
            except _Refusal:
                cause("deadline")
                terminate("TERM")
                terminate("KILL")
                descendants_reaped = reap()
                return
            if received_signal is not None:
                terminate("TERM")
            if clock() >= compile_until and not term_sent:
                cause("compiler_deadline")
                terminate("TERM")
            if term_sent and not kill_sent and clock() >= term_until:
                terminate("KILL")
            try:
                code = process.poll()
                if code is not None:
                    if type(code) is not int or not -(2**31) <= code < 2**31:
                        cause("compiler_status_invalid")
                    else:
                        returncode, compiler_reaped = code, True
            except BaseException:
                cause("compiler_poll_error")
                terminate("TERM")
            descendants_reaped = reap()
            active = [row["stream"] for row in channels.values()
                      if row["stream"] is not None and not row["eof"] and not row["failed"]]
            if compiler_reaped and descendants_reaped and not active:
                return
            if kill_sent and clock() >= kill_until:
                if not compiler_reaped:
                    cause("compiler_closure_unknown")
                if not descendants_reaped:
                    cause("descendant_closure_unknown")
                for name, row in channels.items():
                    if not row["eof"]:
                        cause(name + "_eof_unknown")
                return
            try:
                readers, _, _ = ready(active, allow_signal=True)
            except _Refusal:
                continue
            except BaseException:
                cause("compiler_select_error")
                terminate("TERM")
                for row in channels.values():
                    row["failed"] = True
                continue
            for name, row in channels.items():
                if row["stream"] not in readers or row["failed"] or row["eof"]:
                    continue
                try:
                    part = row["stream"].read(65536)
                    if part is None:
                        continue
                    if type(part) is not bytes or len(part) > 65536:
                        raise OSError("invalid channel read")
                    if not part:
                        row["eof"] = True
                        remaining(allow_signal=True)
                        continue
                    row["observed"] += len(part)
                    keep = min(len(part), CHANNEL_LIMIT - len(row["data"]))
                    if keep:
                        row["data"].extend(memoryview(part)[:keep])
                    if keep != len(part):
                        cause(name + "_overflow")
                        terminate("TERM")
                    # Count and retain bytes actually returned by the read even
                    # if its completion crosses a clock/deadline boundary.
                    remaining(allow_signal=True)
                except BlockingIOError:
                    continue
                except _Refusal as error:
                    cause(str(error))
                except BaseException:
                    row["failed"] = True
                    cause(name + "_read_error")
                    terminate("TERM")

    try:
        set_handler(signal.SIGTERM, handler)
        set_handler(signal.SIGINT, handler)
        make_nonblocking(stdin)
        make_nonblocking(stdout)
        make_nonblocking(stderr)
        try:
            runtime["pid"] = get_pid()
            for name, expected in (("CORE", (1, 1)), ("FSIZE", (ELF_LIMIT, ELF_LIMIT))):
                value = get_limit(name)
                if (type(value) is not tuple or len(value) != 2
                        or any(type(number) is not int for number in value) or value != expected):
                    raise _Refusal("runtime_preflight_failed")
                runtime[name.lower()] = list(value)
            if type(runtime["pid"]) is not int or runtime["pid"] != 1:
                raise _Refusal("runtime_preflight_failed")
            runtime["interpreter_elf64_amd64"] = runtime_elf(sys.executable)
            runtime["compiler_elf64_amd64"] = runtime_elf("/usr/bin/cc")
            if not runtime["interpreter_elf64_amd64"] or not runtime["compiler_elf64_amd64"] or causes:
                raise _Refusal("runtime_preflight_failed")
        except _Refusal:
            raise
        except BaseException:
            raise _Refusal("runtime_preflight_failed") from None

        if read_exact(8) != b"VASTCC1\n":
            raise _Refusal("request_invalid")
        header_size = struct.unpack("!I", read_exact(4))[0]
        if not 0 < header_size <= METADATA_LIMIT - 12:
            raise _Refusal("request_invalid")
        raw = read_exact(header_size)
        try:
            header = json.loads(raw.decode("ascii"))
            if (type(header) is not dict or set(header) != {"source_size", "source_sha256"}
                    or type(header["source_size"]) is not int or not 0 < header["source_size"] <= SOURCE_LIMIT
                    or type(header["source_sha256"]) is not str
                    or re.fullmatch("[0-9a-f]{64}", header["source_sha256"]) is None
                    or _canonical(header) != raw):
                raise ValueError
        except (ValueError, UnicodeError, RecursionError):
            raise _Refusal("request_invalid") from None
        source_file = None
        source_hash = hashlib.sha256()
        try:
            source_file = open_file("/work/engine.c", "xb")
            while source["size_bytes"] < header["source_size"]:
                part = read_chunk(stdin, min(65536, header["source_size"] - source["size_bytes"]))
                if not part:
                    raise _Refusal("request_truncated")
                source_hash.update(part)
                source["size_bytes"] += len(part)
                source["sha256"] = source_hash.hexdigest()
                write_exact(source_file, part, timed=False)
            if read_chunk(stdin, 1) or source["sha256"] != header["source_sha256"]:
                raise _Refusal("source_binding_invalid")
            source_file.flush()
            sync_file(source_file.fileno())
            value = file_stat(source_file.fileno())
            if not stat.S_ISREG(value.st_mode) or value.st_size != source["size_bytes"]:
                raise _Refusal("source_binding_invalid")
            remaining()
        except _Refusal as error:
            cause(str(error))
            raise
        except BaseException:
            cause("source_io_error")
            raise _Refusal("source_io_error") from None
        finally:
            close(source_file, "source_close_error")
        if causes:
            raise _Refusal("source_io_error")

        if clock() >= compile_until:
            raise _Refusal("compile_window_unavailable")
        process = process_factory(list(COMMAND), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd="/work", env=dict(COMPILER_ENV),
            start_new_session=True, close_fds=True, bufsize=0)
        for name, row in channels.items():
            row["stream"] = getattr(process, name)
        if type(process.pid) is not int or process.pid <= 1:
            raise _Refusal("compiler_identity_invalid")
        owned_pid = process.pid
        for row in channels.values():
            if row["stream"] is None:
                raise _Refusal("compiler_channel_unavailable")
            make_nonblocking(row["stream"])
        observe_compiler()
        if returncode is not None and returncode != 0:
            cause("compiler_exit_nonzero")
    except _Refusal as error:
        cause(str(error))  # Only fixed internal refusal codes reach this type.
    except BaseException:
        cause("publisher_io_error")
    finally:
        if owned_pid is not None and not (compiler_reaped and descendants_reaped):
            terminate("TERM")
            try:
                observe_compiler()
            except BaseException:
                cause("compiler_cleanup_error")
        for name, row in channels.items():
            close(row["stream"], name + "_close_error")
        close(stdin, "stdin_close_error")

    # Signals remain handled through export and PID1 exit. Restoring default
    # handlers before the export would abandon this publisher's ownership role.
    elf_bytes = b""
    if not causes and compiler_reaped and descendants_reaped and returncode == 0:
        stream = None
        try:
            stream = open_file("/work/engine", "rb")
            before = file_stat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or not 64 <= before.st_size <= ELF_LIMIT:
                raise _Refusal("elf_invalid")
            buffer = bytearray()
            while len(buffer) < before.st_size:
                remaining()
                part = stream.read(min(65536, before.st_size - len(buffer)))
                if not part or type(part) is not bytes or len(part) > before.st_size - len(buffer):
                    raise _Refusal("elf_invalid")
                buffer.extend(part)
            if stream.read(1) or not _native_elf(buffer) or _snapshot(file_stat(stream.fileno())) != _snapshot(before):
                raise _Refusal("elf_invalid")
            remaining()
            elf_bytes = bytes(buffer)
        except _Refusal as error:
            cause(str(error))
        except BaseException:
            cause("elf_io_error")
        finally:
            close(stream, "elf_close_error")
    if causes:
        elf_bytes = b""

    def channel_record(row):
        return {"size_bytes": len(row["data"]), "sha256": hashlib.sha256(row["data"]).hexdigest(),
                "eof": row["eof"], "observed_bytes": row["observed"],
                "discarded_bytes": row["observed"] - len(row["data"]) if row["eof"] else None}

    metadata = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_export_v1",
        "source": source, "runtime": runtime,
        "compiler": {"returncode": returncode, "started": process is not None, "reaped": compiler_reaped,
                     **{name: channel_record(row) for name, row in channels.items()}},
        "elf": {"size_bytes": len(elf_bytes), "sha256": hashlib.sha256(elf_bytes).hexdigest(),
                "available": bool(elf_bytes)}, "causes": causes, "descendants_reaped": descendants_reaped}
    exported = False
    try:
        remaining(allow_signal=True)
        encoded = _canonical(metadata)
        total = 12 + len(encoded) + sum(len(row["data"]) for row in channels.values()) + len(elf_bytes)
        if 12 + len(encoded) > METADATA_LIMIT or total > EXPORT_LIMIT:
            raise _Refusal("metadata_overflow")
        for part in (b"VASTCE1\n", struct.pack("!I", len(encoded)), encoded,
                     channels["stdout"]["data"], channels["stderr"]["data"], elf_bytes):
            write_exact(stdout, part, timed=True, allow_signal=True)
        exported = True
    except _Refusal as error:
        cause(str(error))
        cause("publisher_export_write_error")
    except BaseException:
        cause("publisher_export_write_error")
    if exported:
        try:
            remaining(allow_signal=True)
            stdout.flush()
            remaining(allow_signal=True)
        except BaseException:
            cause("publisher_export_flush_error")
    close(stdout, "publisher_export_close_error")

    # A header already sent cannot contain a later write/flush/close failure.
    # Preserve fixed codes on the separate publisher stderr; the host retains
    # this channel independently and requires publisher/container exit0 too.
    diagnostic_size = 0
    for code in tuple(causes):
        line_size = len("VASTCC1_ERROR ") + len(code) + 1
        if diagnostic_size + line_size > 4096:
            break
        line = ("VASTCC1_ERROR " + code + "\n").encode("ascii")
        try:
            write_exact(stderr, line, timed=True, allow_signal=True)
            diagnostic_size += len(line)
        except BaseException:
            cause("publisher_diagnostic_unavailable")
            break
    try:
        remaining(allow_signal=True)
        stderr.flush()
        remaining(allow_signal=True)
    except BaseException:
        cause("publisher_diagnostic_unavailable")
    close(stderr, "publisher_diagnostic_close_error")
    return 0 if exported and not causes and elf_bytes else 1


def main():
    if len(sys.argv) != 1:
        return 2
    return run_publisher_v1(getattr(sys.stdin.buffer, "raw", sys.stdin.buffer),
                            getattr(sys.stdout.buffer, "raw", sys.stdout.buffer),
                            stderr=getattr(sys.stderr.buffer, "raw", sys.stderr.buffer))


if __name__ == "__main__":
    raise SystemExit(main())
