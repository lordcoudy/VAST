"""Fresh direct gate-2 packet operator (component-admission-plan.v9.md section 3). Inert on import.

Windows: python -I -B <this file> <reviewed commit X> <approval URL> <manifest path> <manifest SHA256>.
One original 150 s deadline. Phases PRE, EXPORT and PACKET run these same verified bytes in Ubuntu as
uid 1000; P0 runs from Windows through the unchanged fixed collector. No Git, Node or network I/O,
no C/D, no retry and no cleanup. One canonical ASCII stdout document of at most 2,048 B.
Killing an owned wsl.exe never proves that its Linux child stopped.
"""
import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import stat
import subprocess
import sys
import threading
import time
import types

NS = 10**9
RUN_NS, WORK_NS, PHASE_NS = 150 * NS, 140 * NS, 15 * NS
OPERATOR = "tests/fixtures/accepted_policy_fixture_compiler_gate2_fresh_v1.py"
PLAN = "openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/component-admission-plan.v9.md"
GATE = "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py"
P0 = "tests/fixtures/accepted_policy_fixture_compiler_gate2_p0_v1.py"
EXPORT_CODE = tuple("tests/fixtures/accepted_policy_fixture_compiler" + name for name in (
    "_gate2_c_v1.py", "_component_v1.py", "_v1.py", "_publisher_v1.py", "_seccomp_v1.json")) + (
    "scripts/publication_operational_request_domain_v1.py",) + tuple(
    "tests/fixtures/accepted_policy_fixture_compiler" + name for name in (
    "_recovery_v1.py", "_gate2_p0_v1.py", "_gate2_d_v1.py", "_gate2_d_child_v1.py"))  # gate2_c CODE_PATHS, in order
REPO_WIN = Path("C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
REPO_LINUX = PurePosixPath("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
WSL = "C:/Windows/System32/wsl.exe"
UNC = "//wsl.localhost/Ubuntu"
ROOT_PREFIX = "/home/s-a-balashov/work/vast-fixture-compiler-gate2-"
RESUME_R1 = "/home/s-a-balashov/work/vast-fixture-compiler-gate2-465ab7986939c67ae3594344ee3b6266cd2abd7a-01/r1"
DOCKER_SOCKET = "/run/docker.sock"
INFO_REQUEST = b"GET /v1.55/info HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\nContent-Length: 0\r\n\r\n"
STDOUT_CAPS = {"PRE": 49152, "EXPORT": 8192, "PACKET": 8192}
PRE_IDENTITY = {"ID": "1e493309-3767-45fb-9078-05b838bdfd80", "ServerVersion": "29.7.2",
    "KernelVersion": "6.6.87.2-microsoft-standard-WSL2", "Driver": "overlayfs", "CgroupDriver": "systemd",
    "SecurityOptions": ["name=seccomp,profile=builtin", "name=cgroupns"], "DockerRootDir": "/var/lib/docker",
    "CgroupVersion": "2", "Containers": 3, "ContainersRunning": 0, "ContainersPaused": 0, "ContainersStopped": 3}
LINUX_MARGIN_NS = 3 * NS  # the Linux phase ends before Windows stops waiting, by more than WSL startup
P0_BUDGET_NS = 45 * NS  # P0 owns 30 s; PACKET needs its 15 s after it
TERMINAL_CAP = 2048
ENV = {"SystemRoot": "C:/Windows", "WINDIR": "C:/Windows", "PATH": "C:/Windows/System32;C:/Windows"}
BOOT = ("import hashlib,json,os,sys,types\n"
    "p='/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/"
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_fresh_v1.py'\n"
    "n,h=int(sys.argv[2]),sys.argv[3];b=b'';f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)\n"
    "try:\n while len(b)<=n:\n  c=os.read(f,n+1-len(b))\n  if not c:break\n  b+=c\n"
    "finally:os.close(f)\n"
    "if len(b)!=n or hashlib.sha256(b).hexdigest()!=h:raise SystemExit('fresh_operator_binding')\n"
    "m=types.ModuleType('gate2_fresh_verified');m.__file__=p;sys.modules[m.__name__]=m\n"
    "exec(compile(b,p,'exec'),m.__dict__)\n"
    "raise SystemExit(m.native_entry_v1(sys.argv[1],json.loads(sys.stdin.buffer.readline(262145))))\n")


class FreshRefusal(RuntimeError):
    def __init__(self, cause, facts=None):
        super().__init__(cause)
        self.cause, self.facts = cause, {} if facts is None else facts


def need(condition, cause, facts=None):
    if not condition:
        raise FreshRefusal(cause, facts)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def blob(raw):
    return {"size_bytes": len(raw), "sha256": sha(raw),
        "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()}


def decode(raw, cap):
    need(type(raw) is bytes and len(raw) <= cap, "json_bound")
    def pairs(rows):
        need(len({key for key, _ in rows}) == len(rows), "json_duplicate_key")
        return dict(rows)
    try:
        return json.loads(raw.decode("ascii"), object_pairs_hook=pairs,
            parse_constant=lambda value: need(False, "json_constant"))
    except (UnicodeDecodeError, ValueError) as error:
        raise FreshRefusal("json_invalid") from error


def read_once(path, cap):
    """One bounded read of a regular, unlinked-by-alias file; the bytes read are the bytes verified."""
    info = os.lstat(path)
    need(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= cap, "read_kind_bound")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0))
    try:
        now = os.fstat(fd)
        need(stat.S_ISREG(now.st_mode) and (now.st_dev, now.st_ino) == (info.st_dev, info.st_ino), "read_identity")
        raw = b""
        while len(raw) <= cap:
            chunk = os.read(fd, cap + 1 - len(raw))
            if not chunk:
                break
            raw += chunk
    finally:
        os.close(fd)
    need(len(raw) <= cap and len(raw) == now.st_size, "read_short_or_grown")
    return raw


def verified(path, row, cap):
    raw = read_once(path, cap)
    need(blob(raw) == row, "manifest_binding", {"path": str(path)})
    return raw


def manifest_v1(raw, commit):
    value = decode(raw, 8192)
    files = value.get("files") if type(value) is dict else None
    need(type(value) is dict and set(value) == {"schema_version", "commit", "files"} and
        type(value["schema_version"]) is int and value["schema_version"] == 1 and value["commit"] == commit and
        type(files) is dict and set(files) == set(EXPORT_CODE) | {PLAN, OPERATOR} and all(
        type(row) is dict and set(row) == {"size_bytes", "sha256", "git_blob"} and type(row["size_bytes"]) is int and
        0 < row["size_bytes"] <= 262144 and re.fullmatch("[0-9a-f]{64}", str(row["sha256"])) and
        re.fullmatch("[0-9a-f]{40}", str(row["git_blob"])) for row in files.values()), "manifest_shape")
    return value


def root_v1(commit):
    need(re.fullmatch("[0-9a-f]{40}", commit) is not None, "commit_shape")
    return ROOT_PREFIX + commit + "-01"


def native_argv_v1(phase, own):
    need(phase in STDOUT_CAPS, "native_phase")
    return [WSL, "-d", "Ubuntu", "-u", "s-a-balashov", "--cd", "/", "--exec", "/usr/bin/python3", "-I", "-S", "-B",
        "-c", BOOT, phase, str(len(own)), sha(own)]


def stop_owned(p, end):
    """R4: facts are copied first; then our own child is killed and waited for, bounded by the deadline."""
    facts = {"kill_called": False, "linux_side_known_stopped": False}
    try:
        p.kill()
        facts["kill_called"] = True
    except Exception as error:
        facts["kill_error"] = type(error).__name__
    try:
        facts["wait_returncode"] = p.wait(max(0, min(1, (end - time.monotonic_ns()) / NS)))
    except subprocess.TimeoutExpired:
        facts["wait_timed_out"] = True
    except Exception as error:
        facts["wait_error"] = type(error).__name__
    return facts


class Run:
    def __init__(self, start):
        now = time.monotonic_ns()
        need(type(start) is int and 0 < start <= now < start + WORK_NS, "original_start")
        self.start, self.end, self.work, self.events = start, start + RUN_NS, start + WORK_NS, []

    def remaining(self, end=None):
        left = min(self.work, end or self.work) - time.monotonic_ns()
        need(left > 0, "original_deadline")
        return left

    def process(self, argv, data, end, cap):
        self.remaining(end)
        p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, bufsize=0, env=ENV)
        rows = [{"raw": bytearray(), "bytes": 0, "hash": hashlib.sha256(), "eof": False, "error": False} for _ in range(2)]
        lock, causes, rc = threading.Lock(), [], None

        def drain(pipe, row, limit):
            try:
                while True:
                    chunk = pipe.read(min(4096, limit + 1 - row["bytes"]))
                    with lock:
                        if not chunk:
                            row["eof"] = True
                            return
                        row["bytes"] += len(chunk)
                        row["hash"].update(chunk)
                        row["raw"].extend(chunk[:max(0, limit - len(row["raw"]))])
                        if row["bytes"] > limit:
                            return
            except BaseException:
                with lock:
                    row["error"] = True
        sent = {"closed": False, "error": False}

        def send():
            try:
                p.stdin.write(data)
                p.stdin.close()
                sent["closed"] = True
            except BaseException:
                sent["error"] = True
        try:
            for pipe, row, limit in zip((p.stdout, p.stderr), rows, (cap, 4096)):
                threading.Thread(target=drain, args=(pipe, row, limit), daemon=True).start()
            threading.Thread(target=send, daemon=True).start()
            while True:
                need(time.monotonic_ns() < end, "phase_deadline")
                rc = p.poll()
                with lock:
                    done = all(row["eof"] for row in rows)
                    over = any(row["error"] or row["bytes"] > limit for row, limit in zip(rows, (cap, 4096)))
                need(not over, "pipe_overflow_or_read")
                if rc is not None and done:
                    break
                time.sleep(0.001)
        except BaseException as error:
            causes.append(str(getattr(error, "cause", error))[:48])
        with lock:
            facts = {name + "_" + key: (row["hash"].hexdigest() if key == "sha256" else row[key])
                for name, row in zip(("stdout", "stderr"), rows) for key in ("eof", "bytes", "sha256")}
            facts.update(pid=p.pid, returncode=rc, stdin_closed=sent["closed"], stdin_error=sent["error"],
                stdin_bytes=len(data), stdin_sha256=sha(data),
                argv_sha256=sha(canonical(argv)), unknown_closure=rc is None or not all(row["eof"] for row in rows))
            raw, err = bytes(rows[0]["raw"]), bytes(rows[1]["raw"])
        if rc is None:
            facts["kill"] = stop_owned(p, self.end)
        for pipe, row in zip((p.stdout, p.stderr), rows):
            if row["eof"]:  # a reader still blocked in a read could make close() block
                try:
                    pipe.close()
                except BaseException:
                    pass
        if causes or rc != 0:
            raise FreshRefusal(causes[0] if causes else "phase_status_nonzero",
                {"process": facts, "stderr_prefix": err.decode("ascii", "replace")})  # err is already capped at 4,096 B
        return raw, facts

    def phase(self, name, own, data):
        end = min(self.work, time.monotonic_ns() + PHASE_NS)
        left = self.remaining(end) - LINUX_MARGIN_NS
        need(left > 0, "phase_budget")
        payload = canonical(dict(data, remaining_ns=left)) + b"\n"
        try:
            raw, facts = self.process(native_argv_v1(name, own), payload, end, STDOUT_CAPS[name])
        except FreshRefusal as error:
            process = error.facts.get("process") or {}
            native = None
            # wsl.exe prefixes a UTF-16LE notice; drop its NULs so the child's ASCII JSON line parses.
            for line in reversed(str(error.facts.get("stderr_prefix", "")).replace("\x00", "").splitlines()):
                try:
                    native = json.loads(line).get("cause")
                    break
                except (ValueError, AttributeError):
                    continue
            failure = {"phase": name, "cause": error.cause, "native_cause": str(native)[:64] if native else None,
                "returncode": process.get("returncode"), "unknown_closure": process.get("unknown_closure"),
                "kill_called": (process.get("kill") or {}).get("kill_called"),
                "wait_timed_out": (process.get("kill") or {}).get("wait_timed_out")}
            self.events.append(dict(process, phase=name))
            raise FreshRefusal(error.cause, dict(error.facts, failure=failure)) from error
        self.events.append(dict(facts, phase=name))
        lines = raw.splitlines()
        need(len(lines) == 1, "native_extra_output", {"phase": name})
        return decode(lines[0], STDOUT_CAPS[name])


def load_verified_module(name, path, raw):
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(raw, str(path), "exec"), module.__dict__)
    return module


def dispatch_p0_v1(p0, output, binding, commit):
    result = p0.collect_native_p0_v1(output, binding, reviewed_code_commit=commit)
    need(type(result) is dict and result.get("accepted") is True and result.get("controlled") is False and
        result.get("physical_acceptance") is False and result.get("causes") == [], "p0_native_refused", {"p0": result})
    done = result["completion_record"]
    proof = done["write_proof"]
    need(all(proof.get(k) is True for k in ("open_completed", "fsync_completed", "close_completed", "completed")) and
        proof.get("late") is False and proof.get("extent_unknown") is False and
        proof["written_bytes"] == done["encoded_bytes"] and proof["prefix_sha256"] == done["sha256"],
        "p0_completion_write_refused", {"p0": result})
    return {"completion_record": {key: done[key] for key in ("relative_path", "encoded_bytes", "sha256")}}


def terminal_v1(value):
    """The single stdout document: bounded before encoding, never more than 2,048 B."""
    raw = canonical(value)
    while len(raw) > TERMINAL_CAP and value.get("causes"):
        value = dict(value, causes=value["causes"][:-1], causes_truncated=True)
        raw = canonical(value)
    if len(raw) > TERMINAL_CAP:
        raw = canonical({"completed": False, "causes": ["terminal_bound"], "physical_acceptance": False})
    return raw + b"\n"


def main(commit, approval, manifest_path, manifest_sha, *, _original_start_ns=None):
    start = time.monotonic_ns() if _original_start_ns is None else _original_start_ns
    out = {"completed": False, "causes": [], "packet": None, "boot_id": None, "charge": None,
        "post_ok": None, "phases": [], "physical_acceptance": False, "external_packet_review_required": True}
    try:
        need(os.name == "nt", "windows_operator")
        run = Run(start)
        need(type(approval) is str and 1 <= len(approval) <= 512 and
            re.fullmatch("[0-9a-f]{64}", manifest_sha or "") is not None, "operator_arguments")
        root_v1(commit)
        raw = read_once(manifest_path, 8192)
        need(sha(raw) == manifest_sha, "manifest_hash")
        manifest = manifest_v1(raw, commit)
        need(Path(__file__).resolve() == REPO_WIN / OPERATOR, "operator_path")
        own = verified(REPO_WIN / OPERATOR, manifest["files"][OPERATOR], 65536)
        p0 = load_verified_module("tests.fixtures.accepted_policy_fixture_compiler_gate2_p0_v1", REPO_WIN / P0,
            verified(REPO_WIN / P0, manifest["files"][P0], 262144))
        pre = run.phase("PRE", own, {"commit": commit})
        out["boot_id"] = pre.get("boot_id")
        need(pre.get("counts") == [3, 0, 0, 3] and pre.get("engine_id") == p0.KNOWN_ENGINE_ID, "pre_info_refused")
        run.phase("EXPORT", own, {"commit": commit, "manifest_b64": base64.b64encode(raw).decode("ascii"), "pre": pre})
        boot = pre["boot_id"]
        binding = {"known_engine_id": p0.KNOWN_ENGINE_ID, "boot": {"boot_id": boot}, "provenance": {
            "source": "external", "observer": "ordinary_api", "engine_id": pre["engine_id"], "boot_id": boot}}
        need(run.remaining() >= P0_BUDGET_NS, "p0_budget")
        returned = dispatch_p0_v1(p0, UNC + root_v1(commit) + "/p0", binding, commit)
        packet = run.phase("PACKET", own, {"commit": commit, "approval": approval, "pre": pre, "p0": returned})
        out.update(packet=packet["packet"], charge=packet["charge"], post_ok=packet["post_ok"],
            completed=packet["post_ok"] is True)
        if packet["post_ok"] is not True:
            out["causes"].append("fresh_post_check_failed")
    except BaseException as error:
        out["causes"].append(str(getattr(error, "cause", error))[:64])
        facts = getattr(error, "facts", None)
        if isinstance(facts, dict) and facts.get("failure"):
            out["failure"] = facts["failure"]
        if facts:
            out["facts_sha256"] = sha(canonical(facts) if isinstance(facts, dict) else repr(facts).encode())
    out["phases"] = [{key: row.get(key) for key in ("phase", "returncode", "unknown_closure", "stdout_sha256")}
        for row in (run.events if "run" in locals() else [])]
    os.write(1, terminal_v1(out))
    return 0 if out["completed"] else 1


# ---- Linux phases (uid 1000, these verified bytes) ----

def _measure():
    c, ext4 = os.statvfs("/mnt/c"), os.statvfs("/")
    return {"c_free_bytes": c.f_bavail * c.f_frsize, "ext4_used_bytes": (ext4.f_blocks - ext4.f_bfree) * ext4.f_frsize}


def _boot():
    return read_once("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip()


def allocation_v1(*roots):
    """Actual allocation of the fresh trees: each entry max(blocks, 4 KiB rounding) + 256 B for its inode."""
    pending, total, seen = [Path(r) for r in roots], 0, set()
    device = os.lstat(roots[0]).st_dev
    while pending:
        path = pending.pop()
        info = os.lstat(path)
        need(len(seen) < 512 and info.st_dev == device and (info.st_dev, info.st_ino) not in seen and
            (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode) and info.st_nlink == 1), "allocation_unknown")
        seen.add((info.st_dev, info.st_ino))
        total += max(info.st_blocks * 512, (info.st_size + 4095) // 4096 * 4096) + 256
        if stat.S_ISDIR(info.st_mode):
            pending.extend(Path(entry.path) for entry in os.scandir(path))
    return total


def _write_new(path, raw, deadline):
    need(time.monotonic_ns() < deadline, "phase_deadline")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            need(count > 0, "short_write")
            view = view[count:]
        os.fsync(fd)
    finally:
        os.close(fd)
    need(read_once(path, len(raw)) == raw and time.monotonic_ns() < deadline, "write_readback")


def _info():
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(4)
    try:
        sock.connect(DOCKER_SOCKET)
        sock.sendall(INFO_REQUEST)
        reply = b""
        while True:
            chunk = sock.recv(4096)
            if not chunk:
                break
            reply += chunk
            need(len(INFO_REQUEST) + len(reply) <= 16384, "info_wire_bound")
    finally:
        sock.close()
    return reply, decode(http_body_v1(reply), 16384)


def http_body_v1(reply):
    """The /info body, plain or chunked (the engine answers chunked); the raw reply stays the original."""
    head, separator, body = reply.partition(b"\r\n\r\n")
    lines = head.split(b"\r\n")
    need(separator and re.fullmatch(rb"HTTP/1\.[01] 200 [\x20-\x7e]*", lines[0]) is not None, "info_status")
    fields = {}
    for line in lines[1:]:
        name, colon, value = line.partition(b":")
        need(colon and name.lower() not in fields, "info_header")
        fields[name.lower()] = value.strip()
    need(b"content-encoding" not in fields and not (b"content-length" in fields and b"transfer-encoding" in fields), "info_header")
    if fields.get(b"transfer-encoding") == b"chunked":
        decoded = bytearray()
        while True:
            length, separator, body = body.partition(b"\r\n")
            need(separator and re.fullmatch(rb"[0-9A-Fa-f]{1,16}", length) is not None, "info_chunk")
            size = int(length, 16)
            if size == 0:
                need(body == b"\r\n", "info_chunk")
                return bytes(decoded)
            need(len(body) >= size + 2 and body[size:size + 2] == b"\r\n" and len(decoded) + size <= 16384, "info_chunk")
            decoded.extend(body[:size])
            body = body[size + 2:]
    need(re.fullmatch(rb"[0-9]{1,10}", fields.get(b"content-length", b"")) is not None and
        int(fields[b"content-length"]) == len(body), "info_length")
    return body


def _gate(root):
    sys.path[:0] = [root, root + "/scripts"]
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as gate
    need(Path(gate.__file__).resolve() == Path(root) / GATE, "gate_export_identity")
    return gate


def native_pre_v1(x, deadline):
    root = root_v1(x["commit"])
    for path in (root, root + ".operator-originals", RESUME_R1):
        need(not os.path.lexists(path), "fresh_scope_exists", {"path": path})
    boot, measurement = _boot(), _measure()
    reply, info = _info()
    need(time.monotonic_ns() < deadline, "phase_deadline")
    need({key: info.get(key) for key in PRE_IDENTITY} == PRE_IDENTITY, "pre_identity",
        {key: info.get(key) for key in PRE_IDENTITY if info.get(key) != PRE_IDENTITY[key]})
    return {"boot_id": boot, "engine_id": info.get("ID"), "measurement": measurement,
        "counts": [info.get(k) for k in ("Containers", "ContainersRunning", "ContainersPaused", "ContainersStopped")],
        "request_b64": base64.b64encode(INFO_REQUEST).decode("ascii"), "reply_b64": base64.b64encode(reply).decode("ascii")}


def native_export_v1(x, deadline):
    root = root_v1(x["commit"])
    aux = root + ".operator-originals"
    pre = x["pre"]
    need(_boot() == pre["boot_id"], "boot_drift")
    raw = base64.b64decode(x["manifest_b64"], validate=True)
    manifest = manifest_v1(raw, x["commit"])
    for path in (root, aux, RESUME_R1):
        need(not os.path.lexists(path), "fresh_scope_exists", {"path": path})
    os.mkdir(root, 0o700)
    os.mkdir(aux, 0o700)
    _write_new(aux + "/RPC01.request.original", base64.b64decode(pre["request_b64"], validate=True), deadline)
    _write_new(aux + "/RPC01.reply.original", base64.b64decode(pre["reply_b64"], validate=True), deadline)
    _write_new(aux + "/manifest.original.json", raw, deadline)
    _write_new(aux + "/phase.pre.original.json", canonical({k: v for k, v in pre.items() if not k.endswith("_b64")}), deadline)
    total = 0
    for rel in EXPORT_CODE + (PLAN,):
        body = verified(str(REPO_LINUX / rel), manifest["files"][rel], 262144)
        target = Path(root) / rel
        for parent in reversed(target.relative_to(root).parents[:-1]):
            if not os.path.lexists(Path(root) / parent):
                os.mkdir(Path(root) / parent, 0o700)
        _write_new(str(target), body, deadline)
        total += len(body)
    gate = _gate(root)
    b_root = Path(gate._resume_evidence_paths_v1()["b1_result"]).parents[2]
    index = gate.build_b2_index_v1(b_root=b_root, output_path=Path(aux) / "b2.corrected-index.v1.json")
    need(time.monotonic_ns() < deadline, "phase_deadline")
    record = {"files": len(EXPORT_CODE) + 1, "bytes": total, "b2_index": index}
    _write_new(aux + "/phase.export.original.json", canonical(record), deadline)
    return record


def fresh_authority_v1(gate, root, aux, x, pre_packet, measured):
    """Authority and context, with A including the authority's own allocation (V9 section 5)."""
    raw = read_once(aux + "/manifest.original.json", 8192)
    files = manifest_v1(raw, x["commit"])["files"]
    pre = x["pre"]
    reply = base64.b64decode(pre["reply_b64"], validate=True)
    identity = gate._resume_info_identity_v1(gate._http_json_v1(reply))
    context = {"schema_version": 1, "project_root": root, "consumer_commit": x["commit"],
        "approval_reference": x["approval"], "manifest": {"size_bytes": len(raw), "sha256": sha(raw)},
        "operator": dict(files[OPERATOR], path=OPERATOR), "plan": dict(files[PLAN], path=PLAN),
        "f2_producer": {"commit": gate.RESUME_PRODUCER_COMMIT_V1, "plan_sha256": gate.F2_PRODUCER_PLAN_V1["sha256"]},
        "boot_id": pre["boot_id"], "info": {"request": {"size_bytes": len(INFO_REQUEST), "sha256": sha(INFO_REQUEST)},
            "reply": {"size_bytes": len(reply), "sha256": sha(reply)}, "identity": identity},
        "measurements": {"pre": pre["measurement"], "pre_packet": pre_packet}}
    own = 4096 + 256
    for _ in range(3):
        charge = gate.fresh_charge_v1(pre=pre["measurement"], pre_packet=pre_packet, allocation_bytes=measured + own)
        context.update({key: charge[key] for key in ("allocation_bytes", "noise_bytes", "excess_bytes")})
        authority = canonical({"schema_version": 1, "code_commit": x["commit"], "approval_reference": x["approval"],
            "operator_sha256": context["operator"]["sha256"], "context_sha256": sha(canonical(context)),
            "context": context, "external_approval_required": True})
        need(len(authority) <= 8192, "authority_bound")
        size = (len(authority) + 4095) // 4096 * 4096 + 256
        if size == own:
            return context, authority, charge, files
        own = size
    raise FreshRefusal("authority_allocation_unsettled")


def native_packet_v1(x, deadline):
    root = root_v1(x["commit"])
    aux = root + ".operator-originals"
    pre = x["pre"]
    need(_boot() == pre["boot_id"], "boot_drift")
    gate = _gate(root)
    _write_new(aux + "/phase.p0.original.json", canonical(x["p0"]), deadline)
    pre_packet = _measure()
    context, authority, charge, files = fresh_authority_v1(gate, root, aux, x, pre_packet, allocation_v1(root, aux))
    _write_new(aux + "/operator.authority.original.json", authority, deadline)
    review = {"commit": x["commit"], "approval_reference": x["approval"], "evidence_sha256": sha(authority)}
    evidence = {}
    for key, path in gate._fresh_evidence_paths_v1(Path(root)).items():
        body = read_once(str(path), 16384 if key == "f2_accounting" else 1048576)
        evidence[key] = gate._descriptor(path, body)
    plan = read_once(root + "/" + PLAN, 40960)
    p0_raw = read_once(root + "/p0/p0-completion.v1.json", 65536)
    done = x["p0"]["completion_record"]
    need(done["relative_path"] == "p0-completion.v1.json" and len(p0_raw) == done["encoded_bytes"] and
        sha(p0_raw) == done["sha256"], "p0_completion_binding")
    need(time.monotonic_ns() < deadline, "phase_deadline")
    packet = gate.build_packet_v1(project_root=Path(root), review=review,
        physical_plan_descriptor=gate._descriptor(Path(root) / PLAN, plan), code={rel: files[rel] for rel in EXPORT_CODE},
        evidence=evidence, p0_descriptor=gate._descriptor(Path(root) / "p0/p0-completion.v1.json", p0_raw),
        boot_id=pre["boot_id"], initial_charged_bytes=charge["initial_charged_bytes"], initial_measurement=pre["measurement"],
        operator_authority_descriptor=gate._descriptor(Path(aux) / "operator.authority.original.json", authority),
        prior_retention=None, fresh_context=context)
    need(time.monotonic_ns() < deadline, "phase_deadline")
    desc = gate.write_record_v1(Path(root) / "gate2.packet.original.json", packet, cap=gate.FRESH_PACKET_LIMIT_V1,
        absolute_deadline_ns=deadline)
    gate.validate_packet_v1(project_root=Path(root), packet_descriptor=desc, expected_packet_sha256=desc["sha256"],
        expected_code_commit=x["commit"])
    need(time.monotonic_ns() < deadline, "phase_deadline")
    post, measured = _measure(), allocation_v1(root, aux)
    try:
        checked = gate.fresh_post_check_v1(pre=pre["measurement"], post=post, allocation_bytes=charge["allocation_bytes"],
            measured_post_allocation_bytes=measured, excess_bytes=charge["excess_bytes"])
        post_ok = True
    except gate.Gate2Refusal as error:
        checked, post_ok = {"refusal": error.cause}, False
    record = {"pre": pre["measurement"], "pre_packet": pre_packet, "post": post, "post_allocation_bytes": measured,
        "post_check": checked, "post_ok": post_ok, "charge": charge}
    _write_new(aux + "/measurements.original.json", canonical(record), deadline)
    _write_new(aux + "/phase.packet.original.json", canonical({"packet": desc, "post_ok": post_ok}), deadline)
    return {"packet": {"size_bytes": desc["size_bytes"], "sha256": desc["sha256"]}, "charge": charge, "post_ok": post_ok}


def native_entry_v1(phase, x):
    try:
        need(os.name == "posix" and os.getuid() == 1000 and phase in STDOUT_CAPS and type(x) is dict, "native_entry")
        left = x.get("remaining_ns")
        need(type(left) is int and 0 < left <= PHASE_NS, "native_budget")
        deadline = time.monotonic_ns() + left
        result = {"PRE": native_pre_v1, "EXPORT": native_export_v1, "PACKET": native_packet_v1}[phase](x, deadline)
        raw = canonical(result) + b"\n"
        need(len(raw) <= STDOUT_CAPS[phase] and time.monotonic_ns() < deadline, "native_result_bound_deadline")
        need(os.write(1, raw) == len(raw), "native_result_short")
        return 0
    except BaseException as error:
        try:
            os.write(2, canonical({"cause": str(getattr(error, "cause", repr(error)))[:64],
                "physical_acceptance": False}) + b"\n")
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:5]) if len(sys.argv) == 5 else 2)
