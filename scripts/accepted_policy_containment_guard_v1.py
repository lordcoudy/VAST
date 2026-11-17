"""C:/E: containment guard for the PR9 split-engine route (design 2026-11-04).

The guard is containment, not admission. It runs one phase's owned client
process and keeps every volume (C: and E:) *fresh*: each volume has one reader
with at most one free-space read in flight, a new read starts at most once per
``interval``, and a read's observation time is its start. A failed read or a
valid read below the line breaches at once on either volume; a volume whose
latest valid read started more than two seconds ago breaches (checked on every
completion, on every tick and at each deadline); an in-flight read never extends
freshness and a declared breach is never undone. The phase launches only once
every volume has a valid read that started no more than one interval ago. On a
breach, an interruption or owned work outliving the client, it stops only that
phase's owned work:

* the client's process group (SIGTERM, then SIGKILL after the containers);
* containers whose Docker-written full CID files the phase placed in the
  guard's CID directory, launched with this run's owner label and a launch
  label equal to the CID file stem. Each is authenticated on the admitted
  daemon (engine ID, full CID, labels, and image/creation identity against its
  first observation) before mutation, and its retirement is confirmed on that
  daemon afterwards.

Partial state and causes are retained. The guard never prunes, removes,
retries or changes a floor. Phases must keep their Docker clients attached
(no ``docker run -d``): owned work that outlives the client is a failure.
"""
from __future__ import annotations

import argparse
import errno
import itertools
import json
import os
import re
import secrets
import signal
import stat as stat_mod
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

GIB = 1 << 30
C_FLOOR_BYTES = 42_949_672_960
C_RESERVE_BYTES = 48 * GIB
C_BREACH_BELOW = C_FLOOR_BYTES + C_RESERVE_BYTES  # 94,489,280,512
E_FLOOR_BYTES = 12 * GIB
E_RESERVE_BYTES = 10 * GIB
E_BREACH_BELOW = E_FLOOR_BYTES + E_RESERVE_BYTES  # 23,622,320,128
MAX_GAP_SECONDS = 2.0  # design: a volume is fresh while its latest valid read started <= 2 s ago
MAX_INTERVAL_SECONDS = 1.0  # read starts at most once per interval (<= 1.0 s)
LAUNCH_WAIT_SECONDS = 2.0  # a fresh valid read on every volume must arrive this soon, or nothing launches
REGISTER_SECONDS = 0.3  # registration per tick; with the 0.6 s docker reap allowance <= 0.9 s, so a
#                         freshness decision waits <= 1.0 s behind other guard work
POLL_SECONDS = 0.05  # wake-up granularity between ticks (deadlines, leader exit)
STOP_BUDGET_SECONDS = 10.0
CLI_REAP_SECONDS = 0.5
CID_SCAN_SECONDS = 0.4  # registration scan on the sample loop
STALLS_TO_BREACH = 2  # consecutive stalled registration scans
CID_STOP_SCAN_SECONDS = 1.0  # uncapped stop-path scan
LABEL_DISCOVERY_SECONDS = 0.4  # owner-label listing: with the reap allowance it delays the stop <= 1.0 s
DOCKER_OUTPUT_LIMIT = 1 << 20  # one inspect chunk of INSPECT_CHUNK CIDs fits well within it
SECOND_PASS_RESERVE_SECONDS = 3.0
CLIENT_TERM_GRACE_SECONDS = 2.0
OWNER_LABEL = "vast.pr9.containment-guard.owner"
LAUNCH_LABEL = "vast.pr9.containment-guard.launch"
DESKTOP_ENGINE_ID = "aa8f3d33-e1dc-4ed2-ad06-488b46b332d0"
NATIVE_ENGINE_ID = "1e493309-3767-45fb-9078-05b838bdfd80"
DRVFS_TYPES = frozenset({"9p", "drvfs", "virtiofs"})
_CID = re.compile(r"[0-9a-f]{64}")
_NO_SUCH = re.compile(r"\bNo such container: ([0-9a-f]{64})\s*$")
LIVE_STATES = frozenset({"running", "paused", "restarting"})
_LAUNCH = re.compile(r"[A-Za-z0-9._-]{1,64}")
_MAX_CID_FILES = 1024
RECORD_LIMIT_BYTES = 1 << 20
_MAX_CID_READ = 4 * 1024
STDERR_RECORD_LIMIT = 60_000  # below a default 64 KiB pipe buffer
STDERR_EMIT_SECONDS = 2.0
RECORD_STAT_SECONDS = 1.0
_INSPECT_FORMAT = (  # one JSON array per container: label values cannot inject lines
    "[{{json .Id}},{{json .Image}},{{json .Created}},{{json .State.Status}},"
    '{{json (index .Config.Labels "' + OWNER_LABEL + '")}},'
    '{{json (index .Config.Labels "' + LAUNCH_LABEL + '")}},{{json .HostConfig.RestartPolicy.Name}}]'
)
INSPECT_CHUNK = 512

Sampler = Callable[[str], int]
DockerRunner = Callable[[str, Sequence[str], float], "tuple[int, str]"]


def _bounded(fn, timeout: float, default):
    """Run fn() in a daemon worker thread; return (True, value) or (False, default)
    if it does not finish within timeout (e.g. a filesystem call stuck in D-state)."""
    box: dict = {}

    def call() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller as a failure
            box["error"] = exc

    worker = threading.Thread(target=call, name="guard-bounded", daemon=True)
    worker.start()
    worker.join(max(timeout, 0.0))
    if worker.is_alive() or "error" in box:
        return False, default
    return True, box.get("value", default)


def _read_cid_file(path: Path) -> str:
    """Read a small regular CID file without following links or blocking on FIFOs."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        st = os.fstat(fd)
        if not stat_mod.S_ISREG(st.st_mode) or st.st_size > 128:
            raise ValueError("not a small regular file")
        return os.read(fd, 129)[:128].decode("ascii").strip()
    finally:
        os.close(fd)


class GuardError(ValueError):
    """Invalid guard configuration; raised before the phase starts."""


class RecordWriteFailed(OSError):
    """The record could not be written; it was emitted on stderr instead."""


class GuardInterrupted(BaseException):
    """The guard itself received SIGTERM or SIGHUP."""


def statvfs_free(path: str) -> int:
    """Free bytes available to unprivileged writers on the volume at path."""
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize


def docker_runner(host: str, args: Sequence[str], timeout: float) -> "tuple[int, str]":
    """Run one docker CLI call against an explicit endpoint; never raises.

    Returns (rc, stdout) on success and (rc, stderr) on failure, each bounded
    to 4 KiB, so callers can distinguish Docker's proven absence from errors.
    """
    try:
        proc = subprocess.Popen(["docker", "--host", host, *args], stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError:
        return 127, ""
    try:
        stdout, stderr = proc.communicate(timeout=max(timeout, 0.1))
    except subprocess.TimeoutExpired:
        proc.kill()
        try:  # bounded: a CLI stuck in uninterruptible sleep is abandoned, not awaited
            proc.communicate(timeout=CLI_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            pass
        return 124, ""
    text = stdout if proc.returncode == 0 else stdout + b"\n" + stderr
    if len(text) > DOCKER_OUTPUT_LIMIT:
        return 126, ""  # truncated output would hide containers: unproved, not partial
    return proc.returncode, text.decode("utf-8", "replace")


def drvfs_mount_type(path: str, mounts: str = "/proc/self/mounts") -> str | None:
    """Filesystem type when path is itself a mount point, else None."""
    target = os.path.realpath(path)
    try:
        with open(mounts, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) >= 3 and parts[1] == target:
                    return parts[2]
    except OSError:
        return None
    return None


@dataclass(frozen=True)
class Volume:
    name: str
    path: str
    breach_below: int


@dataclass(frozen=True)
class OwnedDaemon:
    host: str
    engine_id: str
    cid_dir: Path


@dataclass
class GuardResult:
    phase: str
    owner_token: str
    breached: bool = False
    breach: dict | None = None
    child_returncode: int | None = None
    samples: int = 0
    max_staleness_seconds: float = 0.0
    reads: dict = field(default_factory=dict)
    longest_read_seconds: dict = field(default_factory=dict)
    last_sample: dict = field(default_factory=dict)
    stop: dict = field(default_factory=dict)
    containers: dict = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        if self.breached or self.stop.get("failures"):
            return 3
        return 0 if self.child_returncode == 0 else 1

    def as_record(self) -> dict:
        return {
            "schema": "vast.pr9.containment-guard.v1",
            "phase": self.phase,
            "owner_token": self.owner_token,
            "breached": self.breached,
            "breach": self.breach,
            "child_returncode": self.child_returncode,
            "samples": self.samples,
            "reads": self.reads,
            "longest_read_seconds": {k: round(v, 3) for k, v in self.longest_read_seconds.items()},
            "max_staleness_seconds": round(self.max_staleness_seconds, 3),
            "last_sample": self.last_sample,
            "stop": self.stop,
            "containers": self.containers,
            "exit_code": self.exit_code,
            "retained": "partial state retained; no prune, deletion, retry or floor change",
        }


class _VolumeReader:
    """One volume's free-space reader. It reads continuously from creation until
    stopped: at most one read is in flight, and each read starts at
    max(previous completion, previous start + interval), so reads start at most once
    per interval and never wait on the guard loop. A hung read leaves the volume
    stale."""

    def __init__(self, volume: Volume, sampler: Sampler, clock: Callable[[], float], wake: threading.Event,
                 interval: float) -> None:
        self.volume, self.sampler, self.clock, self.wake, self.interval = volume, sampler, clock, wake, interval
        self.lock = threading.Lock()
        self.latest: tuple[float, float, int] | None = None  # (start, done, value) of the latest valid read
        self.failure: tuple[str, float] | None = None  # (reason, completed at) of the first failed read, sticky
        self.below: tuple[int, float] | None = None  # (value, completed at) of the first read below the line
        self.reads = 0
        self.longest = 0.0
        self.last_start: float | None = None
        self.in_flight_since: float | None = None
        self._stopped = threading.Event()
        self.thread = threading.Thread(target=self._loop, name=f"guard-read-{volume.name[0]}", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def _loop(self) -> None:
        while not self._stopped.is_set():
            with self.lock:
                last = self.last_start
            if last is not None:  # never two starts within one interval
                spacing = last + self.interval - self.clock()
                if spacing > 0 and self._stopped.wait(spacing):
                    return
            with self.lock:
                start = self.clock()
                self.last_start = start
                self.in_flight_since = start
            try:
                value, error = self.sampler(self.volume.path), None
            except BaseException as exc:  # noqa: BLE001 - any failure is a failed read
                value, error = None, type(exc).__name__
            done = self.clock()
            with self.lock:
                self.in_flight_since = None
                self.reads += 1
                self.longest = max(self.longest, done - start)
                if error is not None:
                    self.failure = self.failure or (f"read failed: {error}", done)
                elif type(value) is not int or value < 0:
                    self.failure = self.failure or ("read not a non-negative integer", done)
                else:
                    if self.latest is None or start >= self.latest[0]:
                        self.latest = (start, done, value)
                    if value < self.volume.breach_below and self.below is None:
                        self.below = (value, done)
            self.wake.set()

    def state(self) -> tuple:
        with self.lock:
            return self.latest, self.failure, self.below, self.reads, self.longest


def default_volumes(c_path: str = "/mnt/c", e_path: str = "/mnt/e") -> tuple[Volume, Volume]:
    return (Volume("C:", c_path, C_BREACH_BELOW), Volume("E:", e_path, E_BREACH_BELOW))


class ContainmentGuard:
    def __init__(
        self,
        phase: str,
        volumes: Sequence[Volume],
        *,
        interval: float = 1.0,
        sampler: Sampler = statvfs_free,
        daemon: OwnedDaemon | None = None,
        docker: DockerRunner = docker_runner,
        owner_token: str | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not phase or not _LAUNCH.fullmatch(phase):
            raise GuardError("phase must be 1-64 characters of [A-Za-z0-9._-]")
        if not (0 < interval <= MAX_INTERVAL_SECONDS):
            raise GuardError(f"interval must be in (0, {MAX_INTERVAL_SECONDS}] seconds")
        if sorted(v.name for v in volumes) != ["C:", "E:"]:
            raise GuardError("exactly the C: and E: volumes must be guarded")
        for v in volumes:
            floor = C_BREACH_BELOW if v.name == "C:" else E_BREACH_BELOW
            if v.breach_below < floor:
                raise GuardError(f"{v.name} breach threshold below the reviewed floor plus reserve")
        if daemon is not None and daemon.engine_id not in (DESKTOP_ENGINE_ID, NATIVE_ENGINE_ID):
            raise GuardError("daemon engine ID is not an admitted engine")
        self.phase = phase
        self.volumes = tuple(volumes)
        self.interval = interval
        self.sampler = sampler
        self.daemon = daemon
        self.docker = docker
        self.owner_token = owner_token or secrets.token_hex(16)
        self.clock = clock
        self.hold_signals_after_run = False
        self.launched = False
        self._scan_timeouts = 0
        self._seen: dict[str, str] = {}  # every CID ever parsed, written by scan workers
        self._seen_lock = threading.Lock()
        self._identities: dict[str, dict] = {}
        self._wake = threading.Event()
        self._readers: list[_VolumeReader] = []

    # --- sampling -------------------------------------------------------
    def _start_readers(self) -> None:
        self._readers = [_VolumeReader(v, self.sampler, self.clock, self._wake, self.interval) for v in self.volumes]

    def _stop_readers(self) -> None:
        for reader in self._readers:
            reader.stop()

    def _snapshot(self) -> list:
        return [(r.volume, r.state()) for r in self._readers]

    def _evaluate(self, result: GuardResult, launched: bool = True, states: list | None = None) -> dict | None:
        """The breach decision on one snapshot: failed or below-line reads on either
        volume first, then staleness (latest valid read started more than 2 s ago).
        Every failure, below-line and staleness decision records how late it is:
        since the deciding read completed, or since the staleness deadline passed."""
        now = self.clock()
        states = self._snapshot() if states is None else states
        result.samples = sum(st[3] for _, st in states)
        staleness: dict = {}
        for volume, (latest, _, _, reads, longest) in states:
            result.reads[volume.name] = reads
            result.longest_read_seconds[volume.name] = longest
            result.last_sample[volume.name] = latest[2] if latest else None
            if latest is not None:
                staleness[volume.name] = now - latest[0]
                if launched:
                    result.max_staleness_seconds = max(result.max_staleness_seconds, staleness[volume.name])
        for volume, (_, failure, below, _, _) in states:
            if failure is not None:
                return {"volume": volume.name, "kind": "failed-read", "reason": failure[0],
                        "decision_lateness_seconds": round(now - failure[1], 3)}
            if below is not None:
                return {"volume": volume.name, "kind": "below-threshold", "free_bytes": below[0],
                        "breach_below": volume.breach_below, "decision_lateness_seconds": round(now - below[1], 3)}
        for volume, (latest, _, _, _, _) in states:
            if latest is None:
                if launched:
                    return {"volume": volume.name, "kind": "stale", "reason": "no valid read"}
                continue
            if staleness[volume.name] > MAX_GAP_SECONDS:
                return {"volume": volume.name, "kind": "stale",
                        "reason": "no valid read started within 2 s",
                        "staleness_seconds": round(staleness[volume.name], 3),
                        "decision_lateness_seconds": round(staleness[volume.name] - MAX_GAP_SECONDS, 3)}
        return None

    @staticmethod
    def _observed_since(moment: float, states: list) -> bool:
        """In this snapshot, every volume has a valid read that started at or after ``moment``."""
        return all(st[0] is not None and st[0][0] >= moment for _, st in states)

    def _decide(self, result: GuardResult, exit_at: float | None) -> tuple[dict | None, bool]:
        """One snapshot for both answers: the breach decision, and whether the
        client's exit is observed on every volume. A read published after the
        snapshot is in neither answer, so it is judged on the next decision."""
        states = self._snapshot()
        breach = self._evaluate(result, states=states)
        return breach, breach is None and exit_at is not None and self._observed_since(exit_at, states)

    def _next_deadline(self) -> float:
        deadlines = [st[0][0] + MAX_GAP_SECONDS for _, st in self._snapshot() if st[0] is not None]
        return min(deadlines) if deadlines else self.clock()

    def _launch_ready(self, result: GuardResult) -> dict | None:
        """Before launch: wait (at most LAUNCH_WAIT_SECONDS) until every volume has a
        valid read above its line that started no more than one interval ago. The
        breach check and the readiness check use the same snapshot."""
        give_up = self.clock() + LAUNCH_WAIT_SECONDS
        while True:
            states = self._snapshot()
            now = self.clock()
            breach = self._evaluate(result, launched=False, states=states)
            if breach is not None:
                return breach
            fresh = [st[0] is not None and now - st[0][0] <= self.interval for _, st in states]
            if all(fresh):
                return None
            if now >= give_up:
                # name the worst volume: one with no valid read at all, else the oldest read
                missing = sorted(((v.name, st[0]) for (v, st), ok in zip(states, fresh) if not ok),
                                 key=lambda item: (item[1] is not None, item[1][0] if item[1] else 0.0))
                return {"volume": missing[0][0], "kind": "stale", "reason": "no fresh valid read before launch",
                        "not_fresh": [name for name, _ in missing],
                        "decision_lateness_seconds": round(now - give_up, 3)}
            self._wake.wait(max(0.0, min(give_up, now + POLL_SECONDS) - now))
            self._wake.clear()

    # --- owned containers -----------------------------------------------
    def _cid_files(self, failures: list | None, limit: int | None = _MAX_CID_FILES) -> list[tuple[str, str]]:
        """Bounded wrapper: a CID-directory scan that does not finish in time is a
        failure (and, on the sample loop, a breach), never a hang."""
        local: list = []
        timeout = CID_SCAN_SECONDS if limit is not None else CID_STOP_SCAN_SECONDS
        ok, found = _bounded(lambda: self._cid_files_unbounded(local, limit), timeout, [])
        if failures is not None:
            if ok:  # a timed-out worker may still be appending: its list is never read
                for entry in list(local):
                    self._fail_list(failures, entry)
            else:
                self._fail_list(failures, {"what": "cid-dir", "reason": "scan did not finish in time"})
        if limit is not None:  # the sample-loop scan: count consecutive stalls only
            self._scan_timeouts = 0 if ok else self._scan_timeouts + 1
        return found

    def _cid_files_unbounded(self, failures: list, limit: int | None) -> list[tuple[str, str]]:
        """Valid (launch, CID) pairs from the CID directory. Reading stops after
        ``limit`` entries (registration) or the hard read cap (stop paths)."""
        assert self.daemon is not None
        cap = _MAX_CID_READ if limit is None else limit
        try:
            with os.scandir(self.daemon.cid_dir) as it:
                entries = sorted((Path(e.path) for e in itertools.islice(it, cap + 1)), key=lambda p: p.name)
        except OSError as exc:
            if failures is not None:
                self._fail_list(failures, {"what": "cid-dir", "reason": type(exc).__name__})
            return []
        found = []
        for path in entries[:cap]:
            launch = path.name[:-4] if path.name.endswith(".cid") else ""
            try:
                text = _read_cid_file(path)
            except (OSError, UnicodeDecodeError, ValueError) as exc:
                if failures is not None:
                    self._fail_list(failures, {"what": "cid-file", "file": path.name, "reason": type(exc).__name__})
                continue
            if not _LAUNCH.fullmatch(launch) or not _CID.fullmatch(text):
                if failures is not None:
                    self._fail_list(failures, {"what": "cid-file", "file": path.name,
                                               "reason": "not <launch>.cid with a full CID"})
                continue
            found.append((launch, text))
            with self._seen_lock:  # recorded as parsed: a scan that later stalls cannot lose it
                self._seen.setdefault(text, launch)
        if len(entries) > cap and failures is not None:
            self._fail_list(failures, {"what": "cid-dir", "reason": f"more than {cap} entries; the rest were not read"})
        return found

    def cid_overflow(self) -> bool:
        """True when the phase created more CID files than the guard can track, or
        the count cannot be taken in time."""
        if self.daemon is None:
            return False

        def count() -> bool:
            with os.scandir(self.daemon.cid_dir) as it:
                return sum(1 for _ in itertools.islice(it, _MAX_CID_FILES + 1)) > _MAX_CID_FILES

        ok, over = _bounded(count, CID_SCAN_SECONDS, False)
        if not ok:  # a stalled count is a stalled scan, not an overflow
            self._scan_timeouts += 1
        return bool(over) and ok

    def _docker(self, args: Sequence[str], deadline: float) -> tuple[int, str]:
        """One docker call, hard-bounded: it runs in a daemon worker thread that is
        abandoned if it outlives its budget (e.g. an exec stuck in uninterruptible sleep)."""
        assert self.daemon is not None
        remaining = deadline - self.clock()
        if remaining <= 0:
            return 124, ""
        box: dict = {}

        def call() -> None:
            try:
                box["result"] = self.docker(self.daemon.host, list(args), remaining)
            except Exception:  # noqa: BLE001 - an injected or OS failure is unknown
                box["result"] = (125, "")

        worker = threading.Thread(target=call, name="guard-docker", daemon=True)
        worker.start()
        worker.join(remaining + CLI_REAP_SECONDS + 0.1)
        if worker.is_alive():
            return 124, ""
        return box.get("result", (125, ""))

    def _engine_confirmed(self, deadline: float) -> bool:
        rc, out = self._docker(["info", "--format", "{{.ID}}"], deadline)
        return rc == 0 and self.daemon is not None and out.strip() == self.daemon.engine_id

    def _inspect_many(self, cids: Sequence[str], deadline: float) -> dict:
        """Batched inspect in chunks. Each CID maps to its identity, to {"absent": True}
        only for Docker's no-such-container line naming that full CID, or to None
        (unproved): any rc other than 0/1, a malformed line, or a CID reported more
        than once (found twice, or both found and absent)."""
        found: dict = {cid: None for cid in cids}
        seen: dict = {cid: 0 for cid in cids}
        for i in range(0, len(cids), INSPECT_CHUNK):
            chunk = list(cids[i:i + INSPECT_CHUNK])
            rc, out = self._docker(["container", "inspect", "--format", _INSPECT_FORMAT, *chunk], deadline)
            if rc not in (0, 1):
                continue
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("["):
                    try:
                        parts = json.loads(line)
                    except ValueError:
                        continue
                    if (not isinstance(parts, list) or len(parts) != 7
                            or not all(isinstance(x, str) for x in parts) or parts[0] not in found):
                        continue
                    seen[parts[0]] += 1
                    found[parts[0]] = {"id": parts[0], "image": parts[1], "created": parts[2], "status": parts[3],
                                       "running": parts[3] in LIVE_STATES, "owner": parts[4], "launch": parts[5],
                                       "restart": parts[6]}
                    continue
                gone = _NO_SUCH.search(line)
                if gone and gone.group(1) in found:
                    seen[gone.group(1)] += 1
                    found[gone.group(1)] = {"absent": True, "id": gone.group(1)}
        for cid, count in seen.items():
            if count != 1:
                found[cid] = None
        return found

    def _label_discovered(self, deadline: float, failures: list | None) -> set:
        """Full CIDs of every container on the admitted daemon carrying this run's
        secret owner label, whether or not the phase left a CID file."""
        rc, out = self._docker(["container", "ls", "--all", "--no-trunc", "--filter",
                                f"label={OWNER_LABEL}={self.owner_token}", "--format", "{{.ID}}"], deadline)
        if rc != 0:
            if failures is not None:
                self._fail_list(failures, {"what": "label-discovery", "reason": f"rc {rc}; owned containers may be unlisted"})
            return set()
        return {line.strip() for line in out.splitlines() if _CID.fullmatch(line.strip())}

    @staticmethod
    def _fail_list(failures: list, entry: dict) -> None:
        if entry not in failures:
            failures.append(entry)

    def _owned(self, launch: str | None, cid: str, ident: dict | None) -> bool:
        if ident is None or ident.get("absent") or ident["id"] != cid or ident["owner"] != self.owner_token:
            return False
        if launch is None:  # discovered on the daemon by this run's secret owner label
            return bool(_LAUNCH.fullmatch(ident["launch"]))
        return ident["launch"] == launch

    def register_containers(self, deadline: float) -> None:
        """Record first-observed identities of owned containers (no mutation)."""
        if self.daemon is None:
            return
        read = self._cid_files(None)
        new = [(launch, cid) for launch, cid in read if cid not in self._identities]
        if not new or self.clock() >= deadline:
            return
        idents = self._inspect_many(sorted({cid for _, cid in new}), deadline)
        for launch, cid in new:
            ident = idents.get(cid)
            # same rule as containment: the secret owner token authenticates, the stem is extra
            if cid not in self._identities and (self._owned(launch, cid, ident) or self._owned(None, cid, ident)):
                self._identities[cid] = {"launch": ident["launch"], "image": ident["image"],
                                         "created": ident["created"]}

    def _owned_targets(self, failures: list) -> list[tuple[str, str]]:
        """CID files now present, every registered container whose file vanished, and
        every CID read by an earlier registration scan (even if never inspected)."""
        targets: list = list(self._cid_files(failures, limit=None))
        listed = {cid for _, cid in targets}
        for cid, first in sorted(self._identities.items()):
            if cid not in listed:
                targets.append((first["launch"], cid))
                listed.add(cid)
        with self._seen_lock:
            seen = sorted(self._seen.items())
        for cid, launch in seen:  # read earlier, file since removed, never inspected
            if cid not in listed:
                targets.append((launch, cid))
                listed.add(cid)
        return targets

    @staticmethod
    def _fail(stop: dict, entry: dict) -> None:
        if entry not in stop["failures"]:
            stop["failures"].append(entry)

    def _stop_containers(self, deadline: float, stop: dict, containers: dict, settled: set,
                         first_pass: bool = True, client_gone: bool = False) -> None:
        """One containment pass. CIDs already known (CID files, registrations) are
        contained first; only then is the daemon asked, with a capped timeout, for
        further containers under this run's owner label, so a slow listing can never
        consume the budget before a known writer is killed."""
        if self.daemon is None:
            return
        known: dict[str, list] = {}
        for launch, cid in self._owned_targets(stop["failures"]):  # failures de-duplicated
            if cid not in settled:
                known.setdefault(cid, []).append(launch)
        self._contain_batch(known, deadline, stop, containers, settled, first_pass, client_gone)
        listing_deadline = min(deadline, self.clock() + LABEL_DISCOVERY_SECONDS)
        discovered = self._label_discovered(listing_deadline, stop["failures"])
        extra = {cid: [None] for cid in sorted(discovered) if cid not in known and cid not in settled}
        self._contain_batch(extra, deadline, stop, containers, settled, first_pass, client_gone)

    def _contain_batch(self, launches: dict, deadline: float, stop: dict, containers: dict, settled: set,
                       first_pass: bool, client_gone: bool) -> None:
        """One batched step: one engine check, one inspect, one kill and one confirming
        inspect for these CIDs. A CID is settled only by a proved terminal outcome, and
        (except proved absence) only on the pass that runs after the client group is
        gone; anything else is retried or failed."""
        if not launches:
            return
        if not self._engine_confirmed(deadline):
            for cid in launches:
                self._fail(stop, {"what": "container", "cid": cid,
                                  "reason": "engine identity not confirmed; not mutated"})
            return
        idents = self._inspect_many(list(launches), deadline)
        to_kill: list[tuple[str, bool, bool]] = []
        for cid, names in launches.items():
            ident = idents[cid]
            if ident is None:
                self._fail(stop, {"what": "container", "cid": cid, "reason": "absence or identity unproved; not mutated"})
                continue
            if ident.get("absent"):  # a removed CID can never run again
                containers[cid] = {"launch": names[0] or "", "state": "absent; proved on the original daemon"}
                with self._seen_lock:  # a removed CID never returns: stop re-checking it
                    self._seen.pop(cid, None)
                settled.add(cid)
                continue
            # The secret per-run owner token authenticates ownership; a matching CID-file
            # stem is extra evidence, so a decoy file name can never hide an owned writer.
            owning = [n for n in [*names, None] if self._owned(n, cid, ident)]
            if not owning:
                self._fail(stop, {"what": "container", "cid": cid, "reason": "foreign identity; not mutated"})
                continue
            first = self._identities.get(cid)
            if first is not None and (first["image"], first["created"]) != (ident["image"], ident["created"]):
                self._fail(stop, {"what": "container", "cid": cid,
                                  "reason": "identity changed since first observation; not mutated"})
                continue
            containers[cid] = {"launch": ident["launch"], "image": ident["image"], "created": ident["created"],
                               "restart_policy": ident["restart"],
                               "identity_source": ("first-observation" if first else
                                                   "stop-time" if any(n is not None for n in owning) else "owner-label discovery")}
            restartable = ident["restart"] not in ("", "no")
            if restartable:
                self._fail(stop, {"what": "container", "cid": cid,
                                  "reason": f"restart policy {ident['restart']}; retirement cannot be proved"})
            may_settle = not first_pass and client_gone and not restartable
            if ident["running"]:
                to_kill.append((cid, restartable, may_settle))
                continue
            if first_pass:
                containers[cid]["state"] = f"not live ({ident['status']}); re-checked after the client stops"
                continue
            containers[cid]["state"] = (
                "killed; retirement confirmed" if cid in stop["killed_containers"] and may_settle
                else f"not live ({ident['status']})")
            if ident["status"] == "created":
                self._fail(stop, {"what": "container", "cid": cid,
                                  "reason": "still created after the client stopped; retirement unconfirmed"})
            if may_settle:
                settled.add(cid)
        if to_kill:
            for cid, _, _ in to_kill:
                if cid not in stop.setdefault("live_found", []):
                    stop["live_found"].append(cid)
            rc, _ = self._docker(["container", "kill", *[cid for cid, _, _ in to_kill]], deadline)
            after = self._inspect_many([cid for cid, _, _ in to_kill], deadline)
            for cid, restartable, may_settle in to_kill:
                seen = after[cid]
                if seen is not None and (seen.get("absent") or not seen["running"]):
                    if cid not in stop["killed_containers"]:
                        stop["killed_containers"].append(cid)
                    if restartable:
                        containers[cid]["state"] = "killed; restart policy prevents proving retirement"
                    elif may_settle:
                        containers[cid]["state"] = "killed; retirement confirmed"
                    else:
                        containers[cid]["state"] = "killed; re-checked after the client stops"
                    if may_settle or seen.get("absent"):
                        settled.add(cid)
                else:
                    containers[cid]["state"] = "retirement unconfirmed"
                    self._fail(stop, {"what": "container", "cid": cid,
                                      "reason": f"kill rc {rc}; retirement not confirmed on the original daemon"})
        if not first_pass and not client_gone:
            for cid in launches:
                if cid not in settled:
                    self._fail(stop, {"what": "container", "cid": cid,
                                      "reason": "client group still alive; retirement unconfirmed"})

    # --- owned process group --------------------------------------------
    # The leader is never reaped until the guard is done with the group: an
    # exited, unreaped leader keeps its PID (and so the group ID) reserved, so
    # killpg can never reach a foreign group that reused the number.
    @staticmethod
    def _leader_exited(child: subprocess.Popen) -> bool:
        if child.returncode is not None:
            return True
        try:
            return os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is not None
        except ChildProcessError:
            return True

    @staticmethod
    def _group_members(pgid: int, proc: str = "/proc") -> list[int]:
        """Live (non-zombie) processes whose process group is pgid."""
        members = []
        try:
            names = os.listdir(proc)
        except OSError:
            return [pgid]  # unknown: assume the group is alive
        for name in names:
            if not name.isdigit():
                continue
            try:
                with open(f"{proc}/{name}/stat", "rb") as handle:
                    stat = handle.read().decode("ascii", "replace")
            except OSError:
                continue
            fields = stat[stat.rfind(")") + 2:].split()
            if len(fields) >= 3 and fields[2] == str(pgid) and fields[0] != "Z":
                members.append(int(name))
        return members

    def _group_alive(self, pgid: int) -> bool:
        return bool(self._group_members(pgid))

    def _signal_group(self, pgid: int, sig: int, stop: dict) -> None:
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            return
        except OSError as exc:  # e.g. EPERM for a member running as another user
            stop["failures"].append({"what": "client", "reason": f"{signal.Signals(sig).name} refused: {type(exc).__name__}"})
            return
        stop["client_signals"].append(signal.Signals(sig).name)

    def stop_owned(self, child: subprocess.Popen, result: GuardResult, cause: str,
                   deadline: float | None = None, signal_group: bool = True) -> None:
        """Stop owned work once within one cleanup budget; guard signals arriving
        meanwhile are recorded, not raised. A stop is terminal, so under main the
        signals stay deferred until the record is written."""
        before = len(_SIGNALS["deferred"])
        _SIGNALS["defer"] = True
        try:
            self._stop_owned(child, result, cause, deadline, signal_group)
        finally:
            _SIGNALS["defer"] = self.hold_signals_after_run
            if len(_SIGNALS["deferred"]) > before:
                result.stop["interrupted_during_stop"] = list(_SIGNALS["deferred"][before:])

    def _stop_owned(self, child: subprocess.Popen, result: GuardResult, cause: str,
                    deadline: float | None, signal_group: bool = True) -> None:
        if deadline is None:
            deadline = self.clock() + STOP_BUDGET_SECONDS
        # The second container pass keeps a reserved share of the one budget.
        pass2_reserve = min(SECOND_PASS_RESERVE_SECONDS, max(0.0, deadline - self.clock()) / 2)
        first_deadline = deadline - pass2_reserve
        stop = result.stop = {"cause": cause, "client_signals": [], "killed_containers": [], "failures": []}
        pgid = child.pid
        settled: set = set()
        # 1. ask the whole owned group to stop (also ends BuildKit build clients)
        if signal_group:
            self._signal_group(pgid, signal.SIGTERM, stop)
        # 2. containers are the real writers: stop them without waiting on the client
        self._stop_containers(first_deadline, stop, result.containers, settled)
        # 3. escalate the client group
        if signal_group:
            grace_end = min(self.clock() + CLIENT_TERM_GRACE_SECONDS, first_deadline)
            while self.clock() < grace_end and self._group_alive(pgid):
                time.sleep(0.05)
            if self._group_alive(pgid):
                self._signal_group(pgid, signal.SIGKILL, stop)
            while self.clock() < first_deadline and self._group_alive(pgid):
                time.sleep(0.05)
        # 4. a client that ignored SIGTERM may have started more containers; unsettled ones are retried
        self._stop_containers(deadline - 0.2, stop, result.containers, settled, first_pass=False,
                              client_gone=not self._group_alive(pgid))
        if signal_group and not self._leader_exited(child):
            stop["failures"].append({"what": "client", "reason": "client survived SIGKILL within budget"})
        if self._group_alive(pgid):
            stop["failures"].append({"what": "client", "reason": "owned process group member survived"})

    # --- run ------------------------------------------------------------
    def preflight(self) -> None:
        """Refuse before launch unless the daemon (if any) is the admitted engine."""
        if self.daemon is not None and not self._engine_confirmed(self.clock() + 5.0):
            raise GuardError("docker endpoint is not the admitted engine")

    def run(self, command: Sequence[str], *, env: dict | None = None) -> GuardResult:
        """Run the phase. Only configuration errors raise (before launch); every
        later failure, including an interruption, is returned in the result."""
        if not command:
            raise GuardError("a phase command is required")
        if self.daemon is not None:
            try:
                if any(self.daemon.cid_dir.iterdir()):
                    raise GuardError("CID directory must be empty when the phase starts")
            except OSError as exc:
                raise GuardError(f"CID directory unusable: {type(exc).__name__}") from exc
        self.preflight()
        result = GuardResult(self.phase, self.owner_token)
        self._start_readers()
        try:
            breach = self._launch_ready(result)
        except BaseException:
            self._stop_readers()
            raise
        if breach is not None:
            self._stop_readers()
            result.breached, result.breach = True, breach
            if self.hold_signals_after_run:
                _SIGNALS["defer"] = True
            return result  # breached before start: nothing launched
        child_env = dict(os.environ if env is None else env)
        child_env["VAST_PR9_GUARD_OWNER"] = self.owner_token
        child_env["VAST_PR9_GUARD_OWNER_LABEL"] = f"{OWNER_LABEL}={self.owner_token}"
        child_env["VAST_PR9_GUARD_LAUNCH_LABEL_KEY"] = LAUNCH_LABEL
        if self.daemon is not None:
            child_env["VAST_PR9_GUARD_CID_DIR"] = str(self.daemon.cid_dir)
            child_env["DOCKER_HOST"] = self.daemon.host
        # A guard signal during spawn is deferred, then handled inside the try,
        # so a launched phase is always stopped and recorded.
        signals_before = len(_SIGNALS["deferred"])
        _SIGNALS["defer"] = True
        try:
            child = subprocess.Popen(list(command), env=child_env, start_new_session=True, stdin=subprocess.DEVNULL)
        except BaseException:
            _SIGNALS["defer"] = False
            self._stop_readers()
            raise
        self.launched = True
        try:
            _SIGNALS["defer"] = False  # re-enabled only inside the try that stops owned work
            if len(_SIGNALS["deferred"]) > signals_before:
                _SIGNALS["raised"] = True
                raise GuardInterrupted(_SIGNALS["deferred"][-1])
            exit_at: float | None = None  # when the client was first seen to have exited
            while True:
                tick = self.clock()
                if exit_at is None and self._leader_exited(child):
                    exit_at = self.clock()  # taken after the exit was seen
                breach, observed = self._decide(result, exit_at)  # first, before any other guard work
                if observed:
                    break  # the client's last writes are observed on every volume: client-exit checks
                if breach is None:
                    # each bounded step is followed by a freshness decision (<= 1.0 s apart)
                    self.register_containers(tick + min(REGISTER_SECONDS, self.interval / 2))
                    breach = self._evaluate(result)
                if breach is None and self.cid_overflow():
                    breach = {"volume": None, "kind": "cid-overflow", "limit": _MAX_CID_FILES}
                if breach is None and self._scan_timeouts >= STALLS_TO_BREACH:
                    breach = {"volume": None, "kind": "cid-scan-stalled",
                              "reason": "CID directory scan did not finish in time"}
                if breach is None:
                    next_tick = tick + self.interval
                    while True:  # until the next tick: decide on every completion and at each deadline
                        if exit_at is None and self._leader_exited(child):
                            exit_at = self.clock()
                        breach, observed = self._decide(result, exit_at)
                        now = self.clock()
                        if breach is not None or observed or now >= next_tick:
                            break
                        self._wake.wait(max(0.0, min(next_tick, self._next_deadline(), now + POLL_SECONDS) - now))
                        self._wake.clear()
                if breach is not None:
                    result.breached, result.breach = True, breach
                    self.stop_owned(child, result, "breach")
                    break
            if not result.breached:
                self._after_client_exit(child, result)
        except BaseException as exc:  # noqa: BLE001 - recorded, never lost
            if not result.stop:
                result.breached = True
                kind = "interrupted" if isinstance(exc, (GuardInterrupted, KeyboardInterrupt)) else "internal-error"
                result.breach = {"volume": None, "kind": kind, "reason": type(exc).__name__}
                self.stop_owned(child, result, kind)
            else:
                result.stop.setdefault("failures", []).append(
                    {"what": "guard", "reason": f"{type(exc).__name__} after stop"})
        self._stop_readers()
        if self.hold_signals_after_run:
            _SIGNALS["defer"] = True  # main records later signals until the record is written
        # Reap the leader only now that the guard is done with its group.
        result.child_returncode = child.poll() if self._leader_exited(child) else None
        return result

    def _after_client_exit(self, child: subprocess.Popen, result: GuardResult) -> None:
        """Owned work must not outlive the client. Proof and containment are one
        pass in one budget: a live owned container is killed as soon as it is
        found. Leftovers or unproved state are a lifecycle failure."""
        deadline = self.clock() + STOP_BUDGET_SECONDS
        survivors = self._group_alive(child.pid)
        if not survivors and self.daemon is None:
            return  # nothing owned can remain: no daemon, no live group member
        cause = "owned work outlived client or state unproved"
        self.stop_owned(child, result, cause, deadline, signal_group=survivors)
        stop = result.stop
        live = list(stop.get("live_found", []))
        unproved = [f.get("cid") or f.get("file") or f["what"] for f in stop["failures"]
                    if f["what"] in ("container", "cid-file", "cid-dir") and f.get("cid") not in live]
        if survivors or live or stop["failures"] or stop.get("interrupted_during_stop"):
            stop["failures"].append({"what": "lifecycle", "reason": cause, "group_survivors": survivors,
                                     "running_containers": live, "unproved": unproved})
        else:
            result.stop = {}  # every owned container proved absent or retired: clean


def _stderr_summary(record: dict) -> bytes:
    """A bounded summary (<= STDERR_RECORD_LIMIT bytes) for the stderr fallback:
    breach and cause always; failures before CID lists; lists as counts plus a prefix."""
    stop = record.get("stop") or {}
    killed = list(stop.get("killed_containers") or [])
    live = list(stop.get("live_found") or [])
    failures = list(stop.get("failures") or [])
    total_failures = len(failures)
    keep_lists, keep_failures, trimmed = 64, 64, False
    while True:
        summary = {
            "schema": record.get("schema"), "phase": record.get("phase"), "breached": record.get("breached"),
            "breach": record.get("breach"), "exit_code": record.get("exit_code"),
            "stop_cause": stop.get("cause"), "client_signals": stop.get("client_signals"),
            "failures_count": total_failures, "failures": failures[:keep_failures],
            "killed_count": len(killed), "killed_containers_prefix": killed[:keep_lists],
            "live_found_count": len(live), "live_found_prefix": live[:keep_lists],
            "containers_count": len(record.get("containers") or {}), "truncated_for_stderr": True}
        data = (json.dumps(summary) + "\n").encode()
        if len(data) <= STDERR_RECORD_LIMIT:
            return data
        if keep_lists:
            keep_lists //= 2
        elif keep_failures > 1:
            keep_failures //= 2
        elif not trimmed:  # failures themselves are oversized: keep only their kinds
            failures = [{"what": f.get("what"), "reason": str(f.get("reason"))[:200]} for f in failures[:1]]
            trimmed = True
        else:  # provable exit: a fixed minimal summary
            return (json.dumps({"schema": record.get("schema"), "breached": record.get("breached"),
                                "exit_code": record.get("exit_code"), "failures_count": total_failures,
                                "killed_count": len(killed), "truncated_for_stderr": True}) + "\n").encode()


def _write_record(path: Path, record: dict, dir_fd: int | None = None) -> None:
    """Write the record exactly once. An oversized record is compacted, never dropped.
    O_CREAT|O_EXCL never follows a symlink and fails on any existing entry (FIFO
    included); with dir_fd the name is resolved in the directory pinned before launch."""
    data = (json.dumps(record, indent=2, sort_keys=True) + "\n").encode("utf-8")
    if len(data) > RECORD_LIMIT_BYTES:
        compact = dict(record)
        compact["containers"] = {"omitted_count": len(record.get("containers") or {})}
        stop = dict(compact.get("stop") or {})
        stop["killed_containers"] = {"count": len(stop.get("killed_containers") or [])}
        failures = stop.get("failures") or []
        extra = [{"what": "record", "reason": f"{len(failures) - 64} more failures omitted"}] if len(failures) > 64 else []
        stop["failures"] = failures[:64] + extra
        compact["stop"] = stop
        compact["compacted"] = True
        data = (json.dumps(compact, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = (os.open(path.name, flags, 0o644, dir_fd=dir_fd) if dir_fd is not None
              else os.open(path, flags, 0o644))
        with os.fdopen(fd, "wb") as handle:  # never overwrite an earlier record
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if dir_fd is not None:
            os.fsync(dir_fd)  # make the directory entry durable too
            pinned = os.fstat(dir_fd)
            if pinned.st_nlink == 0:  # the directory was removed: the record is unreachable
                raise FileNotFoundError(errno.ENOENT, "record directory was removed during the phase")
            ok, at_path = _bounded(lambda: os.stat(path.parent), RECORD_STAT_SECONDS, None)  # may sit on drvfs
            if at_path is None or (at_path.st_dev, at_path.st_ino) != (pinned.st_dev, pinned.st_ino):
                raise FileNotFoundError(errno.ENOENT, "record directory was moved during the phase; "
                                                      "the record is not at its path")
    except OSError as exc:  # includes FileExistsError from a create race
        # e.g. ENOSPC: the result must still reach the caller
        emitted = data if len(data) <= STDERR_RECORD_LIMIT else _stderr_summary(record)
        reason = str(exc).replace("\n", " ")[:300]
        header = f"containment guard: record write failed ({type(exc).__name__}: {reason}); record follows\n".encode()

        def emit() -> None:
            # raw fd writes take no Python-level lock, so a blocked pipe cannot
            # wedge interpreter shutdown after main has returned rc 4
            view = memoryview(header + emitted)
            try:
                while view:
                    view = view[os.write(2, view):]
            except OSError:
                pass

        _bounded(emit, STDERR_EMIT_SECONDS, None)  # a full stderr pipe cannot withhold rc 4
        raise RecordWriteFailed(str(path)) from exc


_SIGNALS: dict = {"defer": False, "deferred": [], "raised": False}


def _raise_interrupted(signum, _frame):  # exercised through a subprocess test
    """First guard signal outside a stop raises once; any other is only recorded."""
    name = signal.Signals(signum).name
    if _SIGNALS["defer"] or _SIGNALS["raised"]:
        _SIGNALS["deferred"].append(name)
        return
    _SIGNALS["raised"] = True
    raise GuardInterrupted(name)


def mount_of(path: str, mounts: str = "/proc/self/mounts") -> "tuple[str, str] | None":
    """(mount point, filesystem type) of the longest mount prefix containing path."""
    target = os.path.realpath(path)
    best = None
    try:
        with open(mounts, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 3:
                    continue
                mp = parts[1]
                if target == mp or target.startswith(mp.rstrip("/") + "/"):
                    if best is None or len(mp) > len(best[0]):
                        best = (mp, parts[2])
    except OSError:
        return None
    return best


def main(
    argv: Sequence[str] | None = None,
    *,
    sampler: Sampler = statvfs_free,
    docker: DockerRunner = docker_runner,
    mount_type: Callable[[str], "str | None"] = drvfs_mount_type,
    containing_mount: Callable[[str], "tuple[str, str] | None"] = mount_of,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--phase", required=True)
    parser.add_argument("--record", required=True, type=Path)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--c-path", default="/mnt/c")
    parser.add_argument("--e-path", default="/mnt/e")
    parser.add_argument("--docker-host")
    parser.add_argument("--engine-id")
    parser.add_argument("--cid-dir", type=Path)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    daemon_args = (args.docker_host, args.engine_id, args.cid_dir)
    if any(a is not None for a in daemon_args) and not all(a is not None for a in daemon_args):
        parser.error("--docker-host, --engine-id and --cid-dir go together")
    if args.record.exists() or args.record.is_symlink():
        parser.error("record path already exists")
    if os.path.realpath(args.c_path) == os.path.realpath(args.e_path):
        parser.error("C: and E: paths must be different mounts")
    for name, path in (("C:", args.c_path), ("E:", args.e_path)):
        if mount_type(path) not in DRVFS_TYPES:
            parser.error(f"{name} path {path!r} is not a Windows drive mount point")
    record_holder = containing_mount(str(args.record.parent.resolve()))
    if record_holder is None or record_holder[1] in DRVFS_TYPES:
        parser.error("record must be on a Linux filesystem, not a guarded Windows drive mount")
    try:  # pin the checked directory: a later swap of the path cannot redirect the record
        record_dir_fd = os.open(args.record.parent.resolve(), os.O_RDONLY | os.O_DIRECTORY)
    except OSError as exc:
        parser.error(f"record directory unusable: {type(exc).__name__}")
    if args.cid_dir is not None:
        holder = containing_mount(str(args.cid_dir))
        if holder is None or holder[1] in DRVFS_TYPES:
            parser.error("CID directory must be on a Linux filesystem, not a Windows drive mount")
    daemon = OwnedDaemon(args.docker_host, args.engine_id, args.cid_dir) if args.docker_host else None
    _SIGNALS.update(defer=False, deferred=[], raised=False)
    previous = {s: signal.signal(s, _raise_interrupted) for s in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)}
    guard = None
    try:
        try:
            guard = ContainmentGuard(args.phase, default_volumes(args.c_path, args.e_path),
                                     interval=args.interval, sampler=sampler, daemon=daemon, docker=docker)
            guard.hold_signals_after_run = True
            result = guard.run(command)  # after launch, run() returns rather than raises
        except GuardError as exc:
            parser.error(str(exc))
        except BaseException as exc:  # noqa: BLE001 - run() returns after launch, so nothing owned runs here
            interrupted = isinstance(exc, (GuardInterrupted, KeyboardInterrupt))
            result = GuardResult(args.phase, guard.owner_token if guard else "", breached=True,
                                 breach={"volume": None,
                                         "kind": ("interrupted-after-launch" if guard and guard.launched else
                                                  "interrupted-before-launch") if interrupted else "internal-error",
                                         "reason": type(exc).__name__})
        _SIGNALS["defer"] = True  # a signal now must not interrupt the record write
        record = result.as_record()
        record["guard_signals"] = list(_SIGNALS["deferred"])
        try:
            _write_record(args.record, record, record_dir_fd)
        except RecordWriteFailed:
            return 4  # result emitted on stderr; record file missing or partial
    finally:
        os.close(record_dir_fd)
        for s, handler in previous.items():
            signal.signal(s, handler)
        _SIGNALS["defer"] = False
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
