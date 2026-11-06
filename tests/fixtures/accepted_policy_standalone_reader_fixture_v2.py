"""Fresh-interpreter default guardian cold read with bounded original evidence.

Decision16: original stdout/stderr are retained up to 1 MiB each and the
complete result JSON up to 2 MiB, under one recipe-supplied absolute deadline
with owned Linux child/descendant closure. Late, forced, overflowed, nonzero or
unresolved readers never pass, whatever their proof claims.
"""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import threading
import time
from typing import Any, Mapping


_PROGRAM = """
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'scripts'))
import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian
expected_module=root/'scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py'
module_path=Path(guardian.__file__).resolve(strict=True)
module_sha256=hashlib.sha256(module_path.read_bytes()).hexdigest()
if module_path!=expected_module or module_sha256!=sys.argv[6]:
    raise ValueError('standalone default guardian module provenance drifted')
loaded=guardian.load_accepted_policy_guardian_preprocessing_contract_v1(
    project_root=root,preprocessing_contract_path=Path(sys.argv[2]),
    materialization_receipt_path=Path(sys.argv[3]),
    accepted_policy_capability_manifest_path=Path(sys.argv[4]))
semantic_sha256=guardian._semantic_sha(loaded['preprocessing_contract'])
if semantic_sha256!=loaded['receipt']['preprocessing_contract_content_sha256'] or semantic_sha256!=sys.argv[5]:
    raise ValueError('standalone default guardian contract semantic identity drifted')
from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
print(json.dumps({'standalone_guardian_cold_reader_passed':True,
    'default_module_path':str(module_path),'default_module_sha256':module_sha256,
    'preprocessing_contract_content_sha256':semantic_sha256,
    'loaded_production_sources':loaded_fixture_production_sources_v1(project_root=root),
    'campaign_authority':False},sort_keys=True))
"""


CHANNEL_LIMIT = 1048576
RESULT_LIMIT = 2097152
_CHUNK = 65536
_OWNED_LIMIT = 256
_POLL_NS = 20_000_000
_PR_SET_CHILD_SUBREAPER, _PR_GET_CHILD_SUBREAPER = 36, 37
_DEADLINE_KEYS = frozenset(("absolute_monotonic_ns", "term_grace_ns", "kill_grace_ns", "final_ns"))
_EXCLUSIVE_FLAGS = (os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
                    | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_BINARY", 0))
# Indirections let controlled tests fault external effects, never validators.
_os_write = os.write
_os_read = os.read
_monotonic_ns = time.monotonic_ns


def _sealed_deadline_v2(deadline: Any) -> dict[str, int]:
    """One recipe-supplied absolute clock; no default, reset or extension."""
    if type(deadline) is not dict or set(deadline) != _DEADLINE_KEYS or any(
            type(value) is not int or value <= 0 for value in deadline.values()):
        raise ValueError("standalone reader deadline is missing or malformed")
    closing = deadline["term_grace_ns"] + deadline["kill_grace_ns"] + deadline["final_ns"]
    observe_end = deadline["absolute_monotonic_ns"] - closing
    if observe_end <= _monotonic_ns():
        raise ValueError("standalone reader deadline leaves no observation window")
    return {**deadline, "observe_end_ns": observe_end}


def _stat_fields_v2(pid: int) -> list[bytes] | None:
    try:
        with open(f"/proc/{pid}/stat", "rb") as stream:
            raw = stream.read(4096)
    except (FileNotFoundError, ProcessLookupError):
        return None
    close = raw.rfind(b")")
    fields = raw[close + 2:].split()
    if close <= 0 or len(fields) < 20:
        raise OSError("process stat is malformed")
    return fields


def _start_ticks_v2(pid: int) -> int | None:
    fields = _stat_fields_v2(pid)
    return None if fields is None else int(fields[19])


def _children_v2(pid: int) -> set[int]:
    found: set[int] = set()
    try:
        tasks = list(Path(f"/proc/{pid}/task").iterdir())
    except (FileNotFoundError, ProcessLookupError):
        return found
    for task in tasks:
        try:
            raw = (task / "children").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue
        if len(raw) > 65536:
            raise OSError("child inventory overflowed")
        found.update(int(token) for token in raw.split())
    return found


class _OwnedScopeV2:
    """Subreaper scope from a caller without live children: every new child is owned.

    Reparenting only moves an orphan toward this subreaper, so once the reader
    is reaped, a direct-children list that stays empty after reaping proves no
    owned descendant is alive. Pre-existing zombies are foreign and untouched.
    """

    def __init__(self) -> None:
        if not sys.platform.startswith("linux") or not hasattr(os, "pidfd_open") \
                or not hasattr(signal, "pidfd_send_signal"):
            raise ValueError("standalone reader owned closure is unsupported on this platform")
        if threading.active_count() != 1:
            raise ValueError("standalone reader owned closure requires one Python thread")
        self.pid = os.getpid()
        self.foreign: set[int] = set()
        for pid in _children_v2(self.pid):
            fields = _stat_fields_v2(pid)
            if fields is not None and fields[0] != b"Z":
                raise ValueError("standalone reader owned closure requires a caller without live children")
            self.foreign.add(pid)
        self.libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        if self.libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(previous), 0, 0, 0) != 0:
            raise ValueError("standalone reader owned closure subreaper query failed")
        self.previous = previous.value
        if self.libc.prctl(_PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0:
            raise ValueError("standalone reader owned closure subreaper setup failed")

    def direct(self) -> set[int]:
        return _children_v2(self.pid) - self.foreign

    def subtree(self) -> set[int]:
        """Current owned processes below this caller, reader included."""
        pending, seen = self.direct(), set()
        while pending:
            pid = pending.pop()
            if pid in seen:
                continue
            seen.add(pid)
            if len(seen) > _OWNED_LIMIT:
                raise OSError("owned descendant inventory overflowed")
            pending.update(_children_v2(pid))
        return seen

    def reap(self, reader_pid: int) -> None:
        """Reap owned non-reader zombies; Popen alone reaps the reader."""
        for pid in self.direct() - {reader_pid}:
            try:
                os.waitpid(pid, os.WNOHANG)
            except ChildProcessError:
                pass

    def empty(self, reader_pid: int) -> bool:
        """True only when reaping leaves no owned direct child at all."""
        for _ in range(_OWNED_LIMIT):
            self.reap(reader_pid)
            remaining = self.direct()
            if not remaining:
                return True
            if any((fields := _stat_fields_v2(pid)) is not None and fields[0] != b"Z" for pid in remaining):
                return False
        return False

    def restore(self) -> bool:
        if self.libc.prctl(_PR_SET_CHILD_SUBREAPER, self.previous, 0, 0, 0) != 0:
            return False
        current = ctypes.c_int()
        return self.libc.prctl(_PR_GET_CHILD_SUBREAPER, ctypes.byref(current), 0, 0, 0) == 0 \
            and current.value == self.previous


class _RawFileV2:
    """Fresh exclusive raw file; counts only bytes a write call confirmed."""

    def __init__(self, path: Path) -> None:
        self.fd = os.open(path, _EXCLUSIVE_FLAGS, 0o600)
        self.digest = hashlib.sha256()
        self.failed = False
        self.facts = {"path": str(path), "written_bytes": 0, "write_extent_unknown": False,
                      "sha256": self.digest.hexdigest(), "fsync_completed": False, "close_completed": False}

    def write(self, data: bytes) -> str | None:
        if self.failed or not data:
            return None
        try:
            count = _os_write(self.fd, data)
        except OSError:
            self.failed = True
            self.facts.update(write_extent_unknown=True, sha256=None)
            return "raw_write"
        if type(count) is not int or not 0 <= count <= len(data):
            self.failed = True
            self.facts.update(write_extent_unknown=True, sha256=None)
            return "raw_write_contract"
        self.digest.update(data[:count])
        self.facts["written_bytes"] += count
        self.facts["sha256"] = self.digest.hexdigest()
        if count != len(data):
            self.failed = True
            return "raw_short_write"
        return None

    def close(self, absolute_ns: int) -> list[str]:
        causes = []
        if _monotonic_ns() < absolute_ns:
            try:
                os.fsync(self.fd)
                self.facts["fsync_completed"] = True
            except OSError:
                causes.append("raw_fsync")
        else:
            causes.append("raw_deadline")
        try:
            os.close(self.fd)
            self.facts["close_completed"] = True
        except OSError:
            causes.append("raw_close")
        if _monotonic_ns() >= absolute_ns and "raw_deadline" not in causes:
            causes.append("raw_deadline")
        return causes


def _capture_owned_reader_v2(*, command: list[str], cwd: Path, outputs: Mapping[str, Path],
                             deadline: Any) -> tuple[dict[str, Any], bytes, bytes]:
    """Run one owned child under fixed byte ceilings and one absolute deadline.

    Refusals before spawn raise ValueError and allocate nothing. After spawn,
    child/capture failures return original statuses, confirmed prefixes,
    explicitly unknown remainders and the first plus distinct secondary causes.
    An unexpected internal error or interrupt is recorded, the owned reader and
    descendants are killed and reaped, and only an interrupt is re-raised.
    """
    sealed = _sealed_deadline_v2(deadline)
    absolute = sealed["absolute_monotonic_ns"]
    scope = _OwnedScopeV2()
    causes: list[str] = []
    retained = {"stdout": bytearray(), "stderr": bytearray()}
    facts: dict[str, Any] = {"causes": causes, "deadline": dict(sealed), "pid": None, "start_ticks": None,
        "returncode": None, "signal": None, "forced": False,
        "term_sent": False, "kill_sent": False, "term_delivered": 0, "kill_delivered": 0,
        "closure": {"closed": False, "owned_descendants": [], "descendants_unknown": False,
                    "subreaper_restored": None},
        "stdout": None, "stderr": None}

    def fail(code: str) -> None:
        if code not in causes:
            causes.append(code)

    files: dict[str, _RawFileV2] = {}
    process = None
    pidfd = None
    selector = None
    signalled: dict[int, set[tuple[int, int | None]]] = {signal.SIGTERM: set(), signal.SIGKILL: set()}
    interrupt: BaseException | None = None
    try:
        try:
            for channel in ("stdout", "stderr"):
                files[channel] = _RawFileV2(outputs[channel])
                facts[channel] = {"observed_bytes": 0, "retained_bytes": 0, "discarded_bytes": None,
                                  "remainder_unknown": True, "eof": False, "overflow": False,
                                  "retained_sha256": None, "file": files[channel].facts}
        except OSError:
            fail("reader_raw_open")
            return facts, b"", b""
        try:
            # The object is retained before any fallible identity observation.
            process = subprocess.Popen(command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, start_new_session=True, close_fds=True)
        except OSError:
            # Popen can fail after fork; any live child here is still owned.
            fail("reader_spawn")
            return facts, b"", b""
        pipes = {process.stdout.fileno(): "stdout", process.stderr.fileno(): "stderr"}
        facts["pid"] = process.pid
        try:
            facts["start_ticks"] = _start_ticks_v2(process.pid)
        except (OSError, ValueError):
            fail("reader_identity")
        try:
            pidfd = os.pidfd_open(process.pid)
        except OSError:
            fail("reader_identity")

        def note(pid: int, ticks: int | None) -> None:
            rows = facts["closure"]["owned_descendants"]
            if len(rows) < 64 and {"pid": pid, "start_ticks": ticks} not in rows:
                rows.append({"pid": pid, "start_ticks": ticks})

        def deliver(descriptor: int | None, signo: int) -> bool:
            try:
                if descriptor is None:
                    process.send_signal(signo)
                else:
                    signal.pidfd_send_signal(descriptor, signo)
                return True
            except ProcessLookupError:
                return False

        def send(signo: int) -> None:
            """Signal each positively owned subject at most once per signal."""
            key = "term_delivered" if signo == signal.SIGTERM else "kill_delivered"
            if process.returncode is None and (process.pid, facts["start_ticks"]) not in signalled[signo]:
                signalled[signo].add((process.pid, facts["start_ticks"]))
                try:
                    facts[key] += deliver(pidfd, signo)
                except OSError:
                    fail("reader_signal")
            try:
                direct = scope.direct() - {process.pid}
            except (OSError, ValueError):
                direct = set()
            try:
                subjects = scope.subtree() - {process.pid}
            except (OSError, ValueError):
                facts["closure"]["descendants_unknown"] = True
                fail("reader_descendants_unknown")
                subjects = set()
            for pid in subjects | direct:
                try:
                    descriptor = os.pidfd_open(pid)
                except ProcessLookupError:
                    continue
                except OSError:
                    fail("reader_descendant_signal")
                    continue
                try:
                    try:
                        ticks, fields = _start_ticks_v2(pid), _stat_fields_v2(pid)
                    except (OSError, ValueError):
                        ticks = fields = None
                    if pid in direct:
                        # An unreaped direct child keeps its pid: signal it once without /proc.
                        if any(seen == pid for seen, _ in signalled[signo])                                 or (fields is not None and fields[0] == b"Z"):
                            continue
                    else:
                        # The pidfd pins identity; ownership is rechecked on it.
                        if ticks is None or fields is None:
                            fail("reader_descendant_signal")
                            continue
                        if fields[0] == b"Z" or (pid, ticks) in signalled[signo]:
                            continue
                        if int(fields[1]) != scope.pid and int(fields[1]) not in subjects | {process.pid}:
                            continue
                    signalled[signo].add((pid, ticks))
                    note(pid, ticks)
                    facts[key] += deliver(descriptor, signo)
                except (OSError, ValueError):
                    fail("reader_descendant_signal")
                finally:
                    os.close(descriptor)

        for fd in pipes:
            os.set_blocking(fd, False)
        selector = selectors.DefaultSelector()
        for fd in pipes:
            selector.register(fd, selectors.EVENT_READ)

        def overflowed() -> bool:
            return facts["stdout"]["overflow"] or facts["stderr"]["overflow"]

        def pump(until: int, observing: bool) -> None:
            """Read until both EOFs or `until`; bytes are retained before any clock check.

            Overflow ends observation at once; later phases only discard to reach EOF.
            """
            while selector.get_map():
                remaining = until - _monotonic_ns()
                if remaining <= 0:
                    return
                for key, _ in selector.select(min(remaining, _POLL_NS) / 1e9):
                    channel = pipes[key.fd]
                    row = facts[channel]
                    capacity = CHANNEL_LIMIT - row["retained_bytes"]
                    try:
                        data = _os_read(key.fd, _CHUNK if row["overflow"] else min(_CHUNK, capacity + 1))
                    except BlockingIOError:
                        continue
                    except OSError:
                        fail("reader_" + channel + "_read")
                        selector.unregister(key.fd)
                        continue
                    if not data:
                        row["eof"] = True
                        selector.unregister(key.fd)
                        continue
                    row["observed_bytes"] += len(data)
                    if row["overflow"]:
                        continue
                    kept = data[:capacity]
                    retained[channel].extend(kept)
                    row["retained_bytes"] += len(kept)
                    code = files[channel].write(kept)
                    if code is not None:
                        fail("reader_" + channel + "_" + code)
                    if len(data) > capacity:
                        row["overflow"] = True
                        fail("reader_" + channel + "_overflow")
                if not observing or overflowed():
                    return

        def closed_now() -> bool:
            # A read error unregisters a pipe without EOF; only real EOFs close.
            if process.poll() is None or selector.get_map()                     or not (facts["stdout"]["eof"] and facts["stderr"]["eof"]):
                return False
            try:
                return scope.empty(process.pid)
            except (OSError, ValueError):
                facts["closure"]["descendants_unknown"] = True
                fail("reader_descendants_unknown")
                return False

        def settle(until: int, observing: bool = False, signo: int | None = None) -> bool:
            """Observe until the reader, both channels and every owned descendant are closed."""
            while True:
                pump(until, observing)
                if closed_now():
                    return True
                if observing and overflowed():
                    return False
                if observing and process.returncode is not None and not selector.get_map():
                    fail("reader_descendant_live")
                    return False
                if facts["closure"]["descendants_unknown"] or _monotonic_ns() >= until:
                    return False
                if signo is not None:
                    send(signo)  # newly observed owned subjects only
                if process.returncode is not None and selector.get_map():
                    continue
                time.sleep(min(_POLL_NS, max(0, until - _monotonic_ns())) / 1e9)

        closed = settle(sealed["observe_end_ns"], observing=True)
        if not closed and _monotonic_ns() >= sealed["observe_end_ns"]:
            fail("reader_deadline")
        if not closed:
            # At most one TERM and one KILL per owned subject, inside the same clock.
            facts["forced"] = facts["term_sent"] = True
            send(signal.SIGTERM)
            closed = settle(min(_monotonic_ns() + sealed["term_grace_ns"],
                                absolute - sealed["kill_grace_ns"] - sealed["final_ns"]), signo=signal.SIGTERM)
        if not closed:
            facts["kill_sent"] = True
            send(signal.SIGKILL)
            closed = settle(min(_monotonic_ns() + sealed["kill_grace_ns"], absolute - sealed["final_ns"]),
                            signo=signal.SIGKILL)
        if not closed:
            fail("reader_closure_unknown")
        facts["closure"]["closed"] = closed and not facts["closure"]["descendants_unknown"]
    except BaseException as error:  # noqa: B036 - record, contain, then re-raise interrupts
        fail("reader_internal_" + type(error).__name__)
        facts["closure"]["closed"] = False
        if not isinstance(error, Exception):
            interrupt = error
    finally:
        def guard(name: str, step: Any) -> None:
            """Each cleanup step runs even if an earlier one fails or is interrupted."""
            nonlocal interrupt
            try:
                step()
            except BaseException as error:  # noqa: B036 - cleanup must reach restore
                fail("reader_cleanup_" + name + "_" + type(error).__name__)
                facts["closure"]["closed"] = False
                if not isinstance(error, Exception) and interrupt is None:
                    interrupt = error

        emergency = any(code.startswith(("reader_internal_", "reader_spawn")) for code in causes)

        def kill_reader() -> None:
            if process.poll() is None and emergency                     and (process.pid, facts["start_ticks"]) not in signalled[signal.SIGKILL]:
                # An unreaped direct child is positively owned; kill it once.
                facts["forced"] = facts["kill_sent"] = True
                process.kill()
                try:
                    process.wait(timeout=max(0.0, (absolute - _monotonic_ns()) / 1e9))
                except subprocess.TimeoutExpired:
                    fail("reader_kill_unconfirmed")

        def kill_direct() -> None:
            facts["closure"]["closed"] = False
            reader_pid = process.pid if process is not None else -1
            while True:
                scope.reap(reader_pid)
                remaining = scope.direct() - {reader_pid}
                if not remaining or _monotonic_ns() >= absolute:
                    if remaining:
                        fail("reader_descendants_survived")
                    return
                for pid in remaining:
                    key = (pid, _start_ticks_v2(pid))
                    if key not in signalled[signal.SIGKILL]:
                        signalled[signal.SIGKILL].add(key)
                        try:
                            os.kill(pid, signal.SIGKILL)  # unreaped direct child: identity is stable
                        except ProcessLookupError:
                            pass
                time.sleep(min(_POLL_NS, max(0, absolute - _monotonic_ns())) / 1e9)

        def status() -> None:
            process.poll()
            facts["returncode"] = process.returncode
            if process.returncode is not None and process.returncode < 0:
                facts["signal"] = -process.returncode

        def close_file(channel: str) -> None:
            row, file = facts[channel], files[channel]
            row["remainder_unknown"] = not row["eof"]
            row["discarded_bytes"] = row["observed_bytes"] - row["retained_bytes"] if row["eof"] or row["overflow"] else None
            row["retained_sha256"] = hashlib.sha256(retained[channel]).hexdigest()
            for code in file.close(absolute):
                fail("reader_" + channel + "_" + code)

        try:
            if selector is not None:
                guard("selector", selector.close)
            if process is not None:
                guard("kill", kill_reader)
            if emergency:
                guard("descendants", kill_direct)
            if process is not None:
                guard("status", status)
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        guard("pipe", stream.close)
            if pidfd is not None:
                guard("pidfd", lambda: os.close(pidfd))
            for channel in files:
                guard("raw", lambda channel=channel: close_file(channel))
        finally:
            restored = scope.restore()
            facts["closure"]["subreaper_restored"] = restored
            if not restored:
                fail("reader_subreaper_restore")
                facts["closure"]["closed"] = False
    if interrupt is not None:
        raise interrupt
    return facts, bytes(retained["stdout"]), bytes(retained["stderr"])


def _bounded_json_v2(value: Any, limit: int) -> bytes | None:
    """Encode incrementally; stop before the running size would cross `limit`."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    parts, total = [], 0
    try:
        for part in encoder.iterencode(value):
            total += len(part)
            if total > limit:
                return None
            parts.append(part)
    except (ValueError, TypeError, RecursionError):
        return None
    return "".join(parts).encode("ascii")


def _result_bytes_v2(evidence: Mapping[str, Any]) -> tuple[bytes, bool]:
    """Complete result if it fits; otherwise an explicitly incomplete failure record."""
    raw = _bounded_json_v2(evidence, RESULT_LIMIT - 1)
    if raw is not None:
        return raw + b"\n", True
    omitted = sorted(key for key in ("proof", "command") if key in evidence)
    causes = list(evidence.get("causes") or [])[:32]
    record = {key: value for key, value in evidence.items() if key not in omitted}
    record.update(incomplete=True, omitted=omitted, standalone_guardian_cold_reader_passed=False,
                  causes=causes + (["reader_result_bound"] if "reader_result_bound" not in causes else []))
    raw = _bounded_json_v2(record, RESULT_LIMIT - 1)
    if raw is None:
        raw = _bounded_json_v2({"incomplete": True, "omitted": "all_but_causes",
                                "standalone_guardian_cold_reader_passed": False,
                                "causes": record["causes"][:32]}, RESULT_LIMIT - 1)
    return raw + b"\n", False


def _reader_error_v2(facts: Mapping[str, Any], stdout: bytes, module_path: str, module_sha256: str,
                     contract_sha256: str) -> tuple[str | None, Any]:
    """Original success/refusal predicates, applied only to a normally closed reader."""
    if facts["causes"]:
        return "fresh standalone default guardian reader capture refused: " + facts["causes"][0], None
    if not facts["closure"]["closed"] or facts["forced"] or facts["signal"] is not None:
        return "fresh standalone default guardian reader capture refused: reader_closure_unknown", None
    if facts["returncode"] != 0:
        return "fresh standalone default guardian reader refused", None
    try:
        proof = json.loads(stdout)
    except (ValueError, UnicodeError, RecursionError):
        return "fresh standalone default guardian reader returned invalid proof JSON", None
    if (type(proof) is not dict or proof.get("standalone_guardian_cold_reader_passed") is not True
            or proof.get("default_module_path") != module_path
            or proof.get("default_module_sha256") != module_sha256
            or proof.get("preprocessing_contract_content_sha256") != contract_sha256
            or not proof.get("loaded_production_sources")):
        return "fresh standalone default guardian reader proof identity drifted", proof
    return None, proof


def _write_result_v2(path: Path, raw: bytes, absolute_ns: int) -> dict[str, Any]:
    """Write and close the result; these facts are returned, never self-attested in the file."""
    persistence = {"attempted": False, "written_bytes": 0, "write_extent_unknown": False,
                   "fsync_completed": False, "close_completed": False, "causes": []}
    if _monotonic_ns() >= absolute_ns:
        persistence["causes"].append("result_deadline")
        return persistence
    persistence["attempted"] = True
    try:
        fd = os.open(path, _EXCLUSIVE_FLAGS, 0o600)
    except OSError:
        persistence["causes"].append("result_open")
        return persistence
    try:
        try:
            count = _os_write(fd, raw)
            if type(count) is not int or not 0 <= count <= len(raw):
                raise OSError("write contract")
            persistence["written_bytes"] = count
            if count != len(raw):
                persistence["causes"].append("result_short_write")
        except OSError:
            persistence["write_extent_unknown"] = True
            persistence["causes"].append("result_write")
        try:
            os.fsync(fd)
            persistence["fsync_completed"] = True
        except OSError:
            persistence["causes"].append("result_fsync")
    finally:
        try:
            os.close(fd)
            persistence["close_completed"] = True
        except OSError:
            persistence["causes"].append("result_close")
    if _monotonic_ns() >= absolute_ns:
        persistence["causes"].append("result_deadline_exceeded")
    return persistence


class StandaloneReaderRefusedV2(ValueError):
    """Refusal carrying the returned, not self-attested, evidence."""

    def __init__(self, message: str, evidence: Mapping[str, Any]) -> None:
        super().__init__(message)
        self.evidence = evidence


def run_fixture_standalone_guardian_cold_reader_v2(
    *, project_root: Path, output_dir: Path, guardian: Mapping[str, Any], accepted_capability_path: Path,
    deadline: Mapping[str, int] | None = None,
) -> dict[str, Any]:
    """Keep engine custody alive in the caller; do not supply reader dependencies.

    `deadline` is the recipe's sealed absolute clock; without it nothing runs.
    The result file records the reader outcome only; acceptance is the returned
    evidence, whose `result_persistence` is never self-attested in that file.
    """
    sealed = _sealed_deadline_v2(deadline)
    root = project_root.resolve(strict=True)
    module_path = root / "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"
    module_sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest()
    outputs = {role: output_dir / name for role, name in (
        ("stdout", "standalone-guardian-cold-reader.stdout.raw"),
        ("stderr", "standalone-guardian-cold-reader.stderr.raw"),
        ("result", "standalone-guardian-cold-reader.result.v2.json"),
    )}
    if not output_dir.is_dir() or any(path.exists() or path.is_symlink() for path in outputs.values()):
        raise ValueError("fresh standalone cold reader requires exclusive evidence paths")
    command = [sys.executable, "-B", "-c", _PROGRAM, str(root), str(guardian["contract_path"]),
               str(guardian["receipt_path"]), str(accepted_capability_path),
               guardian["preprocessing_contract_sha256"], module_sha256]
    started = datetime.now(timezone.utc).isoformat()
    facts, stdout, stderr = _capture_owned_reader_v2(command=command, cwd=root, outputs=outputs,
        deadline={key: value for key, value in sealed.items() if key in _DEADLINE_KEYS})
    finished = datetime.now(timezone.utc).isoformat()
    error, proof = _reader_error_v2(facts, stdout, str(module_path), module_sha256,
                                    guardian["preprocessing_contract_sha256"])
    evidence = {"command": command, "cwd": str(root), "started_at": started, "finished_at": finished,
                "original_exit_code": facts["returncode"], "expected_default_module_path": str(module_path),
                "expected_default_module_sha256": module_sha256,
                "expected_contract_semantic_sha256": guardian["preprocessing_contract_sha256"],
                "stdout_path": str(outputs["stdout"]), "stdout_bytes": facts["stdout"]["file"]["written_bytes"]
                if facts["stdout"] and not facts["stdout"]["file"]["write_extent_unknown"] else None,
                "stdout_sha256": facts["stdout"]["file"]["sha256"] if facts["stdout"] else None,
                "stderr_path": str(outputs["stderr"]), "stderr_bytes": facts["stderr"]["file"]["written_bytes"]
                if facts["stderr"] and not facts["stderr"]["file"]["write_extent_unknown"] else None,
                "stderr_sha256": facts["stderr"]["file"]["sha256"] if facts["stderr"] else None,
                "standalone_guardian_cold_reader_passed": error is None, "proof": proof, "error": error,
                "causes": list(facts["causes"]), "capture": facts, "campaign_authority": False}
    raw, complete = _result_bytes_v2(evidence)
    persistence = _write_result_v2(outputs["result"], raw, sealed["absolute_monotonic_ns"])
    returned = {**evidence, "result_complete": complete, "result_persistence": persistence}
    if error is None and (not complete or persistence["causes"]):
        error = "fresh standalone default guardian reader result persistence refused"
        returned.update(standalone_guardian_cold_reader_passed=False, error=error)
    if error is not None:
        raise StandaloneReaderRefusedV2(error, returned)
    return returned
