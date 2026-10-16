"""2.10 in-container probe program (B1 environment/CORE, B2 bad-ABI, B3 stall).

Bind-mounted read-only at /fixture/compiler.py under the identical fixed
compiler config and run as PID1 by `python3 -I -S -B`. Self-contained, stdlib
only, Python 3.10 compatible. It reads one VASTPB1 request on stdin and writes
one VASTCE1 export frame on stdout whose compiler.stdout member is the bounded
JSON report and whose ELF member is empty. It records; it never accepts.
"""
from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import re
import select
import signal
import struct
import subprocess
import sys
import time

REQUEST_MAGIC = b"VASTPB1\n"
EXPORT_MAGIC = b"VASTCE1\n"
REPORT_LIMIT = 1048576
METADATA_LIMIT = 65536
SOURCE_LIMIT = 8 * 1024 * 1024
FIELD_LIMIT = 65536
WORK = "/work"
CC = "/usr/bin/cc"
SOURCE_NAMES = ("c1", "c2", "c3", "c4", "c5")
CC_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "HOME": WORK, "TMPDIR": WORK, "TMP": WORK, "TEMP": WORK}
NR_SETRLIMIT, NR_PRLIMIT64 = 160, 302
RLIMIT_CORE, RLIMIT_NOFILE = 4, 7
X32_ASM = """\t.globl _start
_start:
\tmovl $0x40000027, %eax
\tsyscall
\tcmpq $-1, %rax
\tje 1f
\tmovl $4, %edi
\tjmp 2f
1:\tmovl $3, %edi
2:\tmovl $60, %eax
\tsyscall
"""
I386_ASM = """\t.globl _start
_start:
\tmovl $20, %eax
\tint $0x80
\tmovl $4, %edi
\tmovl $60, %eax
\tsyscall
"""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode("ascii")


def bounded_text(raw, limit=FIELD_LIMIT):
    """Exact prefix as text plus explicit size facts; never silently complete."""
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
            "text": raw[:limit].decode("utf-8", "replace"), "truncated": len(raw) > limit}


def read_bounded(path, limit=FIELD_LIMIT):
    try:
        with open(path, "rb") as file:
            return bounded_text(file.read(limit + 1), limit)
    except OSError as error:
        return {"error": errno.errorcode.get(error.errno, str(error.errno))}


def rw_mount_rows(mountinfo):
    """Exactly the host owner's rw-mount rows and canonical hash."""
    rows = []
    for line in mountinfo.splitlines():
        left, separator, right = line.partition(" - ")
        head, tail = left.split(), right.split()
        if not separator or len(head) < 6 or len(tail) != 3:
            raise ValueError("mountinfo line")
        if "rw" in head[5].split(","):
            rows.append([head[4], tail[0], head[5], tail[2]])
    return sorted(rows), hashlib.sha256(canonical(sorted(rows))).hexdigest()


def elf64_amd64(path):
    try:
        with open(path, "rb") as file:
            head = file.read(20)
    except OSError:
        return None
    return len(head) == 20 and head[:4] == b"\x7fELF" and head[4] == 2 and int.from_bytes(head[18:20], "little") == 62


def file_identity(path):
    try:
        real = os.path.realpath(path)
        digest, size = hashlib.sha256(), 0
        with open(real, "rb") as file:
            while True:
                block = file.read(1 << 20)
                if not block:
                    break
                digest.update(block)
                size += len(block)
        return {"path": path, "realpath": real, "size_bytes": size, "sha256": digest.hexdigest(),
                "elf64_amd64": elf64_amd64(real)}
    except OSError as error:
        return {"path": path, "error": errno.errorcode.get(error.errno, str(error.errno))}


def run_bounded(argv, *, timeout, stdin=b"", stdout_limit=FIELD_LIMIT, stderr_limit=FIELD_LIMIT, count_only=False):
    """One owned child in a fresh session; outputs bounded or counted; killed at its deadline."""
    started = time.monotonic()
    try:
        child = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 env=dict(CC_ENV), cwd=WORK, start_new_session=True, close_fds=True)
    except OSError as error:
        return {"argv": argv, "spawn_error": errno.errorcode.get(error.errno, str(error.errno))}
    try:
        child.stdin.write(stdin)
        child.stdin.close()
    except OSError:
        pass
    kept = {child.stdout.fileno(): bytearray(), child.stderr.fileno(): bytearray()}
    counts = dict.fromkeys(kept, 0)
    limits = {child.stdout.fileno(): stdout_limit, child.stderr.fileno(): stderr_limit}
    open_fds, killed = set(kept), False
    while open_fds:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            killed = True
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            break
        ready, _, _ = select.select(list(open_fds), [], [], min(remaining, 0.25))
        for fd in ready:
            data = os.read(fd, 65536)
            if not data:
                open_fds.discard(fd)
                continue
            counts[fd] += len(data)
            if not count_only and len(kept[fd]) < limits[fd]:
                kept[fd].extend(data[:limits[fd] - len(kept[fd])])
    status = child.wait()
    return {"argv": argv, "returncode": status, "killed_at_deadline": killed,
            "elapsed_s": round(time.monotonic() - started, 3),
            "stdout": bounded_text(bytes(kept[child.stdout.fileno()]), stdout_limit) | {"observed_bytes": counts[child.stdout.fileno()]},
            "stderr": bounded_text(bytes(kept[child.stderr.fileno()]), stderr_limit) | {"observed_bytes": counts[child.stderr.fileno()]}}


class Rlimit(ctypes.Structure):
    _fields_ = [("cur", ctypes.c_uint64), ("max", ctypes.c_uint64)]


def raw_syscall(number, *args):
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    result = libc.syscall(ctypes.c_long(number), *args)
    return {"result": int(result), "errno": errno.errorcode.get(ctypes.get_errno(), ctypes.get_errno()) if result < 0 else None}


def in_disposable_child(function):
    """Run one probe in a forked child; never in PID1 or an inheritance parent."""
    read_fd, write_fd = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read_fd)
        try:
            payload = canonical({"ok": function()})
        except BaseException as error:  # noqa: B036 - the child reports and exits
            payload = canonical({"exception": type(error).__name__})
        os.write(write_fd, payload[:65536])
        os._exit(0)
    os.close(write_fd)
    chunks = []
    while True:
        block = os.read(read_fd, 65536)
        if not block:
            break
        chunks.append(block)
    os.close(read_fd)
    _, status = os.waitpid(pid, 0)
    try:
        value = json.loads(b"".join(chunks) or b"null")
    except ValueError:
        value = None
    return {"wait_status": status, "report": value}


def core_probes():
    def query():
        old = Rlimit()
        return raw_syscall(NR_PRLIMIT64, ctypes.c_long(0), ctypes.c_long(RLIMIT_CORE), None, ctypes.byref(old)) | {
            "cur": old.cur, "max": old.max}

    def setrlimit_raw(cur, maximum, resource=RLIMIT_CORE):
        return lambda: raw_syscall(NR_SETRLIMIT, ctypes.c_ulong(resource), ctypes.byref(Rlimit(cur, maximum)))

    def prlimit_raw(cur, maximum, resource=RLIMIT_CORE):
        return lambda: raw_syscall(NR_PRLIMIT64, ctypes.c_long(0), ctypes.c_ulong(resource),
                                   ctypes.byref(Rlimit(cur, maximum)), None)

    def glibc_setrlimit():
        import resource
        try:
            resource.setrlimit(resource.RLIMIT_CORE, (1, 1))
            return {"result": 0, "errno": None}
        except OSError as error:
            return {"result": -1, "errno": errno.errorcode.get(error.errno, error.errno)}

    def nofile_control():
        current = Rlimit()
        raw_syscall(NR_PRLIMIT64, ctypes.c_long(0), ctypes.c_long(RLIMIT_NOFILE), None, ctypes.byref(current))
        return setrlimit_raw(current.cur, current.max, RLIMIT_NOFILE)()

    alias = 4 | (1 << 32)
    return {"query_null_new": in_disposable_child(query),
            "setrlimit_unchanged": in_disposable_child(setrlimit_raw(1, 1)),
            "setrlimit_zero": in_disposable_child(setrlimit_raw(0, 0)),
            "prlimit64_unchanged": in_disposable_child(prlimit_raw(1, 1)),
            "prlimit64_zero": in_disposable_child(prlimit_raw(0, 0)),
            "prlimit64_upper_alias_zero": in_disposable_child(prlimit_raw(0, 0, alias)),
            "glibc_setrlimit": in_disposable_child(glibc_setrlimit),
            "nofile_positive_control": in_disposable_child(nofile_control),
            "fork_exec_inheritance": run_bounded([sys.executable, "-I", "-S", "-c",
                "import sys;sys.stdout.write(open('/proc/self/limits').read()+open('/proc/self/status').read())"],
                timeout=5)}


def tmpfs_probes():
    def fill_bytes():
        signal.signal(signal.SIGXFSZ, signal.SIG_IGN)
        start = sorted(os.listdir(WORK))
        files, block = [], b"\0" * (1 << 20)
        try:
            for index in range(64):
                path = "%s/vast-fill-%02d" % (WORK, index)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                written, outcome = 0, "complete"
                try:
                    while written < 16 << 20:
                        try:
                            count = os.write(fd, block)
                        except OSError as error:
                            outcome = errno.errorcode.get(error.errno, error.errno)
                            break
                        written += count
                        if count != len(block):
                            outcome = "short"
                            break
                finally:
                    os.close(fd)
                files.append({"bytes": written, "outcome": outcome})
                if outcome != "complete":
                    break
        finally:
            for index in range(len(files)):
                os.unlink("%s/vast-fill-%02d" % (WORK, index))
        return {"starting_entries": start, "files": files, "total_bytes": sum(row["bytes"] for row in files)}

    def fill_inodes():
        created, outcome = 0, None
        try:
            for index in range(8192):
                try:
                    os.close(os.open("%s/vast-inode-%05d" % (WORK, index), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
                    created += 1
                except OSError as error:
                    outcome = errno.errorcode.get(error.errno, error.errno)
                    break
        finally:
            for index in range(created):
                os.unlink("%s/vast-inode-%05d" % (WORK, index))
        return {"created": created, "outcome": outcome}

    return {"bytes": in_disposable_child(fill_bytes), "inodes": in_disposable_child(fill_inodes)}


def environment_probe():
    mountinfo = open("/proc/self/mountinfo", "rb").read(FIELD_LIMIT + 1)
    rows, digest = rw_mount_rows(mountinfo.decode("ascii"))
    mounts = []
    for row in rows:
        point = row[0]
        try:
            info = os.statvfs(point)
            capacity = {"bytes": info.f_blocks * info.f_frsize, "free_bytes": info.f_bavail * info.f_frsize,
                        "inodes": info.f_files, "free_inodes": info.f_favail}
        except OSError as error:
            capacity = {"error": errno.errorcode.get(error.errno, error.errno)}
        probe = os.path.join(point, ".vast-probe-write")
        try:
            os.close(os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600))
            os.unlink(probe)
            writable = True
        except OSError as error:
            writable = errno.errorcode.get(error.errno, error.errno)
        mounts.append({"row": row, "statvfs": capacity, "uid1000_writable": writable})
    status = open("/proc/self/status", "rb").read(FIELD_LIMIT).decode("ascii", "replace")
    selected = {key: value.strip() for key, _, value in (line.partition(":") for line in status.splitlines())
                if key in ("Uid", "Gid", "NoNewPrivs", "Seccomp", "Seccomp_filters", "CapInh", "CapPrm",
                           "CapEff", "CapBnd", "CapAmb")}
    return {"uid": os.getuid(), "gid": os.getgid(), "status": selected,
            "limits": read_bounded("/proc/self/limits"),
            "cgroup": {name: read_bounded("/sys/fs/cgroup/" + name, 256) for name in
                       ("memory.max", "memory.swap.max", "pids.max", "cpu.max")},
            "mountinfo": bounded_text(mountinfo), "rw_mounts": mounts, "rw_mounts_sha256": digest,
            "network_interfaces": sorted(os.listdir("/sys/class/net")),
            "dev_entries": sorted(os.listdir("/dev")),
            "environment": dict(sorted(os.environ.items()))}


def toolchain_probe(sources):
    for name, raw in sources.items():
        with open("%s/%s.c" % (WORK, name), "wb") as file:
            file.write(raw)
    record = {"python": file_identity(sys.executable), "python_version": sys.version,
              "cc": file_identity(CC),
              "cc_version": run_bounded([CC, "--version"], timeout=5),
              "dumpmachine": run_bounded([CC, "-dumpmachine"], timeout=5),
              "dumpspecs": run_bounded([CC, "-dumpspecs"], timeout=5)}
    helpers = {}
    for prog in ("cc1", "as", "ld", "collect2"):
        found = run_bounded([CC, "-print-prog-name=" + prog], timeout=5)
        path = found.get("stdout", {}).get("text", "").strip()
        helpers[prog] = file_identity(path) if path.startswith("/") else {"print_prog_name": path}
    files = {}
    for name in ("crt1.o", "crti.o", "crtn.o", "crtbegin.o", "crtend.o", "libc.so", "libc_nonshared.a",
                 "libgcc.a", "libgcc_s.so", "ld-linux-x86-64.so.2"):
        found = run_bounded([CC, "-print-file-name=" + name], timeout=5)
        path = found.get("stdout", {}).get("text", "").strip()
        files[name] = file_identity(path) if path.startswith("/") else {"print_file_name": path}
    record.update(helpers=helpers, files=files, dry_runs={}, headers={})
    reached = set()
    for name in SOURCE_NAMES:
        record["dry_runs"][name] = run_bounded([CC, "-###", "-O0", "-std=c11", "%s/%s.c" % (WORK, name),
                                                "-o", "%s/%s" % (WORK, name)], timeout=5, stderr_limit=16384)
    for name in ("c1", "c2", "c3"):
        run = run_bounded([CC, "-E", "-H", "-O0", "-std=c11", "%s/%s.c" % (WORK, name), "-o", "/dev/null"],
                          timeout=10, stderr_limit=FIELD_LIMIT)
        record["headers"][name] = run
        for line in run.get("stderr", {}).get("text", "").splitlines():
            match = re.match(r"^\.+ (/\S+)$", line)
            if match:
                reached.add(match.group(1))
    record["headers"]["c4"] = run_bounded([CC, "-E", "-O0", "-std=c11", WORK + "/c4.c", "-o", "/dev/null"],
                                          timeout=10, count_only=True)
    record["reached_headers"] = [file_identity(path) for path in sorted(reached)[:256]]
    record["reached_headers_total"] = len(reached)
    return record


def c5_slope_probe():
    """C5 runs only here, bounded: output counted, RSS/CPU sampled, killed at 20 s."""
    child = subprocess.Popen([CC, "-E", "-O0", "-std=c11", WORK + "/c5.c"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(CC_ENV), cwd=WORK,
                             start_new_session=True, close_fds=True)
    started, samples, output = time.monotonic(), [], {"stdout": 0, "stderr": 0}
    fds = {child.stdout.fileno(): "stdout", child.stderr.fileno(): "stderr"}
    for fd in fds:
        os.set_blocking(fd, False)
    next_sample = started
    while time.monotonic() - started < 20:
        ready, _, _ = select.select(list(fds), [], [], 0.2)
        for fd in ready:
            try:
                data = os.read(fd, 65536)
            except BlockingIOError:
                continue
            if data:
                output[fds[fd]] += len(data)
            else:
                fds.pop(fd)
        if time.monotonic() >= next_sample:
            samples.append({"t_s": round(time.monotonic() - started, 2), "output_bytes": output["stdout"],
                            **session_usage(child.pid)})
            next_sample += 1
        if child.poll() is not None and not fds:
            break
    finished = child.poll() is not None
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    status = child.wait()
    return {"finished_before_kill": finished, "returncode": status, "samples": samples, "output": output}


def session_usage(session):
    rss_kib, ticks, processes = 0, 0, 0
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            stat = open("/proc/%s/stat" % name, "rb").read().decode("ascii", "replace")
            fields = stat[stat.rfind(")") + 2:].split()
            if int(fields[3]) != session:
                continue
            processes += 1
            ticks += int(fields[11]) + int(fields[12])
            for line in open("/proc/%s/status" % name):
                if line.startswith("VmRSS:"):
                    rss_kib += int(line.split()[1])
        except (OSError, ValueError, IndexError):
            continue
    return {"rss_kib": rss_kib, "cpu_ticks": ticks, "processes": processes}


def bad_abi_probe():
    old = Rlimit()
    core = raw_syscall(NR_PRLIMIT64, ctypes.c_long(0), ctypes.c_long(RLIMIT_CORE), None, ctypes.byref(old))
    result = {"core_query": core | {"cur": old.cur, "max": old.max}}
    for name, text in (("x32", X32_ASM), ("i386", I386_ASM)):
        source, binary = "%s/%s.S" % (WORK, name), "%s/%s" % (WORK, name)
        with open(source, "w") as file:
            file.write(text)
        build = run_bounded([CC, "-nostdlib", "-static", source, "-o", binary], timeout=10)
        entry = {"build": build}
        if build.get("returncode") == 0:
            pid = os.fork()
            if pid == 0:
                try:
                    os.execv(binary, [binary])
                finally:
                    os._exit(127)
            deadline, status = time.monotonic() + 2, None
            while time.monotonic() < deadline:
                done, raw = os.waitpid(pid, os.WNOHANG)
                if done:
                    status = raw
                    break
                time.sleep(0.02)
            if status is None:
                os.kill(pid, signal.SIGKILL)
                _, status = os.waitpid(pid, 0)
                entry["killed_at_deadline"] = True
            entry.update(wait_status=status, wait_status_hex="0x%x" % status,
                         signaled=os.WIFSIGNALED(status), signal=os.WTERMSIG(status) if os.WIFSIGNALED(status) else None,
                         core_flag=bool(status & 0x80), exit_code=os.WEXITSTATUS(status) if os.WIFEXITED(status) else None)
        result[name] = entry
    return result


def read_request(stream):
    def exact(count):
        data = bytearray()
        while len(data) < count:
            block = stream.read(count - len(data))
            if not block:
                raise ValueError("request truncated")
            data.extend(block)
        return bytes(data)
    if exact(8) != REQUEST_MAGIC:
        raise ValueError("request magic")
    size = struct.unpack("!I", exact(4))[0]
    if not 0 < size <= METADATA_LIMIT - 12:
        raise ValueError("request size")
    raw = exact(size)
    header = json.loads(raw.decode("ascii"))
    if type(header) is not dict or canonical(header) != raw or set(header) != {"probe", "sources"}:
        raise ValueError("request header")
    if header["probe"] not in ("B1", "B2", "B3") or type(header["sources"]) is not dict:
        raise ValueError("request probe")
    sources, total = {}, 0
    for name in sorted(header["sources"]):
        row = header["sources"][name]
        if name not in SOURCE_NAMES or type(row) is not dict or set(row) != {"size_bytes", "sha256"}:
            raise ValueError("request source")
        total += row["size_bytes"]
        if total > SOURCE_LIMIT:
            raise ValueError("request source bound")
        data = exact(row["size_bytes"])
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise ValueError("request source binding")
        sources[name] = data
    if stream.read(1):
        raise ValueError("request trailing bytes")
    return header["probe"], sources, raw + b"".join(sources[name] for name in sorted(sources))


def build_report(probe, sources):
    report = {"probe": probe, "started_monotonic_s": time.monotonic()}
    if probe == "B1":
        report["environment"] = environment_probe()
        report["core"] = core_probes()
        report["tmpfs"] = tmpfs_probes()
        report["toolchain"] = toolchain_probe(sources)
        report["c5_slope"] = c5_slope_probe()
    elif probe == "B2":
        report["bad_abi"] = bad_abi_probe()
    report["finished_monotonic_s"] = time.monotonic()
    return report


def export_frame(report_raw, diagnostic, request_raw, causes):
    def member(raw):
        return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "eof": True,
                "observed_bytes": len(raw), "discarded_bytes": 0}
    metadata = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_export_v1",
                "source": {"size_bytes": len(request_raw), "sha256": hashlib.sha256(request_raw).hexdigest()},
                "runtime": {"pid": os.getpid(), "probe_program": True},
                "compiler": {"returncode": None, "started": False, "reaped": True,
                             "stdout": member(report_raw), "stderr": member(diagnostic)},
                "elf": {"size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest(), "available": False},
                "causes": causes, "descendants_reaped": True}
    encoded = canonical(metadata)
    if 12 + len(encoded) > METADATA_LIMIT:
        raise ValueError("metadata bound")
    return EXPORT_MAGIC + struct.pack("!I", len(encoded)) + encoded + report_raw + diagnostic


def main():
    causes, request_raw, report = [], b"", None
    stdin = getattr(sys.stdin.buffer, "raw", sys.stdin.buffer)
    try:
        probe, sources, request_raw = read_request(stdin)
    except (ValueError, UnicodeError, OSError) as error:
        causes.append("probe_request_" + type(error).__name__)
        probe, sources = None, {}
    if probe == "B3":
        # Stall past the host work window, ignoring SIGTERM; only SIGKILL ends it.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        while True:
            time.sleep(3600)
    if probe is not None:
        try:
            report = build_report(probe, sources)
        except BaseException as error:  # noqa: B036 - reported, not raised
            causes.append("probe_exception_" + type(error).__name__)
    report_raw = canonical({"report": report, "causes": causes})
    if len(report_raw) > REPORT_LIMIT:
        causes.append("probe_report_bound")
        report_raw = canonical({"report": None, "causes": causes, "report_bytes": len(report_raw)})
    frame = export_frame(report_raw, b"", request_raw, causes)
    out = getattr(sys.stdout.buffer, "raw", sys.stdout.buffer)
    view = memoryview(frame)
    while view:
        view = view[out.write(view):]
    return 0


if __name__ == "__main__":
    sys.exit(main())
