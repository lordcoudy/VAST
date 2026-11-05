"""Containment guard checks with real child processes and a fake Docker endpoint.

No Docker daemon, WSL mount or host volume is touched: volume samples come from
an injected sampler and every Docker call goes to an in-memory fake. Children
signal readiness through files instead of relying on sample counts.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import accepted_policy_containment_guard_v1 as g  # noqa: E402

PLENTY = 500 * g.GIB
LOW_C = g.C_BREACH_BELOW - 1
CID_A = "a" * 64
CID_B = "b" * 64
TOKEN = "o" * 32
HOST = "unix:///run/vast-pr9-desktop-api.sock"


class CaptureFd2:
    """Capture file descriptor 2 (the guard's fallback uses raw os.write)."""

    def __enter__(self):
        self.r, w = os.pipe()
        self.saved = os.dup(2)
        os.dup2(w, 2)
        os.close(w)
        self.chunks = []
        self.reader = threading.Thread(target=self._drain, daemon=True)
        self.reader.start()
        return self

    def _drain(self):
        while True:
            chunk = os.read(self.r, 65536)
            if not chunk:
                return
            self.chunks.append(chunk)

    def __exit__(self, *exc):
        os.dup2(self.saved, 2)
        os.close(self.saved)
        self.reader.join(5)
        os.close(self.r)
        self.text = b"".join(self.chunks).decode("utf-8", "replace")
        return False


def volumes():
    return g.default_volumes("/vol/c", "/vol/e")


def wait_for(path: Path, timeout: float = 10.0) -> None:
    end = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > end:
            raise AssertionError(f"{path.name} never appeared")
        time.sleep(0.01)


class Sampler:
    """Thread-safe sampler. Values come from scripts[path]; once a trigger file
    exists, ``after_ready`` values are used instead (default PLENTY)."""

    def __init__(self, scripts=None, default=PLENTY, ready: Path | None = None, after_ready=None):
        self.scripts = {k: list(v) for k, v in (scripts or {}).items()}
        self.default = default
        self.ready = ready
        self.after_ready = after_ready or {}
        self.lock = threading.Lock()

    def __call__(self, path):
        with self.lock:
            if self.ready is not None and self.ready.exists() and path in self.after_ready:
                value = self.after_ready[path]
            else:
                seq = self.scripts.get(path)
                value = seq.pop(0) if seq else self.default
        if isinstance(value, BaseException):
            raise value
        if callable(value):
            return value()
        return value


class FakeDocker:
    def __init__(self, engine_id=g.DESKTOP_ENGINE_ID, containers=None, kill_rc=0, kill_works=True,
                 raise_on=None, slow_info=0.0, absent=(), absent_text=None, slow_call=0.0, ls_rc=0,
                 slow_ls=False):
        self.ls_rc = ls_rc
        self.slow_ls = slow_ls
        self.engine_id = engine_id
        self.absent = set(absent)  # CIDs Docker reports as "No such container"
        self.absent_text = absent_text
        # cid -> dict(owner, launch, image, created, running)
        self.containers = {k: dict(v) for k, v in (containers or {}).items()}
        self.kill_rc = kill_rc
        self.kill_works = kill_works
        self.raise_on = raise_on
        self.slow_info = slow_info
        self.slow_call = slow_call
        self.calls = []
        self.lock = threading.Lock()

    def __call__(self, host, args, timeout):
        with self.lock:
            self.calls.append((host, tuple(args), time.monotonic()))
        if self.slow_call:  # a slow daemon; like the real runner, the call honours its timeout
            time.sleep(min(self.slow_call, max(timeout, 0.0)))
            if timeout < self.slow_call:
                return 124, ""
        if self.raise_on and args[: len(self.raise_on)] == list(self.raise_on):
            raise TimeoutError("fake docker timeout")
        if args[:1] == ["info"]:
            if self.slow_info:
                time.sleep(self.slow_info)
            return 0, self.engine_id + "\n"
        if args[:2] == ["container", "inspect"]:  # batched, like the real CLI
            out, err = [], []
            for cid in args[4:]:
                c = self.containers.get(cid)
                if cid in self.absent:
                    err.append(self.absent_text or f"Error response from daemon: No such container: {cid}")
                elif c is None:
                    err.append(f"Error response from daemon: cannot inspect {cid[:12]}: unavailable")
                else:
                    out.append(json.dumps([cid, c["image"], c["created"],
                                           c.get("status") or ("running" if c["running"] else "exited"),
                                           c["owner"], c["launch"], c.get("restart") or "no"]))
            text = "\n".join(out) + "\n"
            return (1, text + "\n".join(err) + "\n") if err else (0, text)
        if args[:2] == ["container", "ls"]:  # --all --no-trunc --filter label=KEY=VALUE --format {{.ID}}
            if self.slow_ls:  # a wedged listing: answers only when its timeout expires
                time.sleep(max(timeout, 0.0))
                return 124, ""
            want = args[args.index("--filter") + 1].split("=", 2)[2]
            if self.ls_rc:
                return self.ls_rc, "Cannot connect to the Docker daemon\n"
            return 0, "".join(f"{cid}\n" for cid, c in sorted(self.containers.items())
                              if c["owner"] == want and cid not in self.absent)
        if args[:2] == ["container", "kill"]:
            for cid in args[2:]:
                if self.kill_works and cid in self.containers:
                    self.containers[cid]["running"] = False
                    self.containers[cid]["status"] = "exited"
            return self.kill_rc, "\n".join(args[2:]) + "\n"
        raise AssertionError(f"unexpected docker call {args}")

    def verbs(self):
        return [c[1][1] if c[1][0] == "container" else c[1][0] for c in self.calls]

    def mutations(self):
        return [c[1] for c in self.calls if c[1][:2] == ("container", "kill")]


class _Wrapped:
    """Docker runner proxy that routes calls through fn while exposing the fake's records."""

    def __init__(self, fake, fn):
        self.fake, self.fn = fake, fn

    def __call__(self, host, args, timeout):
        return self.fn(host, args, timeout)

    def __getattr__(self, name):
        return getattr(self.fake, name)


def container(launch, owner=TOKEN, image="sha256:" + "1" * 64, created="2026-11-04T00:00:00Z", running=True,
              status=None, restart="no"):
    return {"owner": owner, "launch": launch, "image": image, "created": created, "running": running,
            "status": status, "restart": restart}


def py(code):
    return [sys.executable, "-c", textwrap.dedent(code)]


def ready_sleeper(ready: Path, extra: str = "") -> list:
    return py(f"""
        import time, signal
        {extra}
        open({str(ready)!r}, 'w').write('1')
        time.sleep(60)
        """)


class ConfigurationTests(unittest.TestCase):
    def test_reviewed_thresholds_are_exact(self):
        self.assertEqual(g.C_BREACH_BELOW, 42_949_672_960 + 51_539_607_552)
        self.assertEqual(g.C_BREACH_BELOW, 94_489_280_512)
        self.assertEqual(g.E_BREACH_BELOW, 12_884_901_888 + 10_737_418_240)
        self.assertEqual(g.E_BREACH_BELOW, 23_622_320_128)
        self.assertEqual(g.MAX_GAP_SECONDS, 2.0)
        self.assertLess(g.MAX_INTERVAL_SECONDS, g.MAX_GAP_SECONDS)
        self.assertEqual(g.STOP_BUDGET_SECONDS, 10.0)

    def test_interval_must_leave_headroom_under_two_seconds(self):
        for bad in (0, -1, 1.01, 1.5, 2.0, 5):
            with self.subTest(bad=bad), self.assertRaises(g.GuardError):
                g.ContainmentGuard("p", volumes(), interval=bad, sampler=Sampler())
        g.ContainmentGuard("p", volumes(), interval=1.0, sampler=Sampler())

    def test_both_volumes_required_and_thresholds_not_weakened(self):
        c, e = volumes()
        with self.assertRaises(g.GuardError):
            g.ContainmentGuard("p", [c], sampler=Sampler())
        with self.assertRaises(g.GuardError):
            g.ContainmentGuard("p", [g.Volume("C:", "/vol/c", g.C_BREACH_BELOW - 1), e], sampler=Sampler())
        with self.assertRaises(g.GuardError):
            g.ContainmentGuard("p", [c, g.Volume("E:", "/vol/e", g.E_BREACH_BELOW - 1)], sampler=Sampler())

    def test_unadmitted_engine_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(g.GuardError):
                g.ContainmentGuard("p", volumes(), sampler=Sampler(),
                                   daemon=g.OwnedDaemon("unix:///x.sock", "f" * 36, Path(tmp)))

    def test_preflight_refuses_wrong_engine_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp, "ran")
            daemon = g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, Path(tmp))
            guard = g.ContainmentGuard("p", volumes(), sampler=Sampler(), daemon=daemon,
                                       docker=FakeDocker(engine_id=g.NATIVE_ENGINE_ID))
            with self.assertRaises(g.GuardError):
                guard.run(py(f"open({str(marker)!r},'w').write('x')"))
            self.assertFalse(marker.exists())

    class FakeProc:
        def __init__(self, rc=0, out=b"", err=b"", hang=False, unreapable=False):
            self.returncode, self.out, self.err = rc, out, err
            self.hang, self.unreapable, self.killed, self.calls = hang, unreapable, False, 0

        def communicate(self, timeout=None):
            self.calls += 1
            self.timeouts = getattr(self, "timeouts", []) + [timeout]
            if self.hang and (not self.killed or self.unreapable):
                raise subprocess.TimeoutExpired("docker", timeout)
            return self.out, self.err

        def kill(self):
            self.killed = True

    def with_popen(self, factory, fn):
        original = g.subprocess.Popen
        g.subprocess.Popen = factory
        try:
            return fn()
        finally:
            g.subprocess.Popen = original

    def test_docker_runner_returns_stderr_on_failure(self):
        proc = self.FakeProc(1, b"ignored", b"Error: No such container: x\n")
        out = self.with_popen(lambda *a, **k: proc, lambda: g.docker_runner(HOST, ["inspect", "x"], 1))
        self.assertEqual(out, (1, "ignored\nError: No such container: x\n"))  # stdout then stderr

    def test_docker_runner_timeout_is_bounded_even_if_the_cli_cannot_be_reaped(self):
        for unreapable in (False, True):
            with self.subTest(unreapable=unreapable):
                proc = self.FakeProc(hang=True, unreapable=unreapable)
                out = self.with_popen(lambda *a, **k: proc, lambda: g.docker_runner(HOST, ["info"], 1))
                self.assertEqual(out, (124, ""))
                self.assertTrue(proc.killed)
                self.assertEqual(proc.calls, 2)  # one bounded reap attempt, never an unbounded wait
                self.assertEqual(proc.timeouts[1], g.CLI_REAP_SECONDS)

    def test_docker_runner_truncated_output_is_unproved(self):
        proc = self.FakeProc(0, b"a" * (g.DOCKER_OUTPUT_LIMIT + 1))
        out = self.with_popen(lambda *a, **k: proc, lambda: g.docker_runner(HOST, ["container", "ls"], 1))
        self.assertEqual(out, (126, ""))

    def test_docker_call_is_hard_bounded_even_if_the_runner_hangs(self):
        gate = threading.Event()

        def hung(host, args, timeout):
            gate.wait(30)  # e.g. exec of the docker binary stuck in uninterruptible sleep
            return 0, ""

        guard = g.ContainmentGuard("p", volumes(), sampler=Sampler(), docker=hung, owner_token=TOKEN,
                                   daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, Path(".")))
        try:
            start = time.monotonic()
            self.assertEqual(guard._docker(["info"], time.monotonic() + 0.3), (124, ""))
            self.assertLess(time.monotonic() - start, 0.3 + g.CLI_REAP_SECONDS + 0.5)
        finally:
            gate.set()

    def test_runner_exception_is_contained_in_the_docker_worker(self):
        def broken(host, args, timeout):
            raise RuntimeError("runner bug")

        hits, original = [], threading.excepthook
        threading.excepthook = hits.append  # an escaping exception would print via sys.stderr
        try:
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=broken,
                                       daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, Path(tempfile.gettempdir())),
                                       owner_token=TOKEN)
            start = time.monotonic()
            self.assertEqual(guard._docker(["info"], guard.clock() + 2.0), (125, ""))
            self.assertLess(time.monotonic() - start, 1.0)
        finally:
            threading.excepthook = original
        self.assertEqual(hits, [])

    def test_inspect_format_json_encodes_every_field(self):
        fields = g._INSPECT_FORMAT.strip("[]").split("}},")
        self.assertEqual(len(fields), 7)
        for field in fields:
            self.assertTrue(field.startswith("{{json "), field)  # label text can never be emitted raw

    def test_docker_runner_missing_cli(self):
        def missing(*a, **k):
            raise FileNotFoundError("docker")

        self.assertEqual(self.with_popen(missing, lambda: g.docker_runner(HOST, ["info"], 1)), (127, ""))


class SamplingTests(unittest.TestCase):
    def guard(self, sampler, **kw):
        return g.ContainmentGuard("p", volumes(), interval=0.4, sampler=sampler, **kw)

    def test_threshold_boundary(self):
        at = self.guard(Sampler({"/vol/c": [g.C_BREACH_BELOW], "/vol/e": [g.E_BREACH_BELOW]}))
        self.assertIsNone(at.sample()[1])
        self.assertEqual(self.guard(Sampler({"/vol/c": [LOW_C]})).sample()[1]["volume"], "C:")
        self.assertEqual(self.guard(Sampler({"/vol/e": [g.E_BREACH_BELOW - 1]})).sample()[1]["volume"], "E:")

    def test_unknown_samples_are_breaches(self):
        cases = {"error": OSError("drvfs"), "none": None, "float": 1e15, "bool": True,
                 "negative": -1, "string": "123"}
        for name, value in cases.items():
            with self.subTest(name=name):
                sample, breach = self.guard(Sampler({"/vol/e": [value]})).sample()
                self.assertEqual((breach["kind"], breach["volume"], sample["E:"]), ("unknown", "E:", None))

    def test_hung_sample_is_a_breach_within_shared_budget(self):
        gate = threading.Event()
        try:
            guard = g.ContainmentGuard("p", volumes(), interval=1.0,
                                       sampler=Sampler({"/vol/c": [lambda: gate.wait(5) and PLENTY],
                                                        "/vol/e": [lambda: gate.wait(5) and PLENTY]}))
            start = time.monotonic()
            sample, breach = guard.sample()
            elapsed = time.monotonic() - start
            self.assertGreater(elapsed, 0.4)
            self.assertLess(elapsed, 1.6)  # one shared 0.5 s budget; a per-volume 2 x interval would take 2.0 s
            self.assertEqual(breach, {"volume": "C:", "kind": "unknown", "reason": "sample timed out"})
            self.assertEqual(sample, {"C:": None, "E:": None})
        finally:
            gate.set()

    def test_hung_sampler_saturation_is_unknown_without_new_threads(self):
        gate = threading.Event()
        try:
            guard = self.guard(Sampler(default=lambda: gate.wait(5) and PLENTY))
            for _ in range(g.MAX_HUNG_SAMPLERS // 2):
                guard.sample()
            count = lambda: sum(t.name == "guard-sample" for t in threading.enumerate())
            before = count()
            _, breach = guard.sample()
            self.assertEqual(breach["reason"], "sampler threads saturated by hung samples")
            self.assertLessEqual(count(), before)  # no new sampler thread was started
        finally:
            gate.set()

    def test_sampler_threads_are_daemon(self):
        gate = threading.Event()
        try:
            self.guard(Sampler({"/vol/c": [lambda: gate.wait(5) and PLENTY]})).sample()
            hung = [t for t in threading.enumerate() if t.name == "guard-sample"]
            self.assertTrue(hung)
            self.assertTrue(all(t.daemon for t in hung))
        finally:
            gate.set()


class RunTests(unittest.TestCase):
    def test_no_breach_passes_child_status_and_keeps_gap_under_two_seconds(self):
        guard = g.ContainmentGuard("p", volumes(), interval=1.0, sampler=Sampler())
        start = time.monotonic()
        result = guard.run(py("import time,sys; time.sleep(2.5); sys.exit(7)"))
        elapsed = time.monotonic() - start
        self.assertFalse(result.breached)
        self.assertEqual((result.child_returncode, result.exit_code), (7, 1))
        self.assertLessEqual(result.max_gap_seconds, g.MAX_GAP_SECONDS)
        self.assertGreaterEqual(result.samples, int(elapsed / 1.5))
        self.assertEqual(result.stop, {})

    def test_slow_successful_samples_do_not_stretch_the_cadence(self):
        def slow():
            time.sleep(0.15)
            return PLENTY

        guard = g.ContainmentGuard("p", volumes(), interval=0.4, sampler=Sampler(default=slow))
        result = guard.run(py("import time; time.sleep(2)"))
        self.assertFalse(result.breached)
        self.assertLessEqual(result.max_gap_seconds, g.MAX_GAP_SECONDS)

    def test_observed_gap_over_two_seconds_is_a_breach(self):
        class JumpClock:
            """Jumps 3 s once, after the child is ready (e.g. guard descheduled)."""

            def __init__(self, ready):
                self.ready, self.offset = ready, None

            def __call__(self):
                if self.offset is None and self.ready.exists():
                    self.offset = 3.0
                return time.monotonic() + (self.offset or 0.0)

        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp, "ready")
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), clock=JumpClock(ready))
            result = guard.run(ready_sleeper(ready))
            self.assertTrue(result.breached)
            self.assertEqual(result.breach["kind"], "sampling-gap")
            self.assertGreater(result.breach["gap_seconds"], 2.0)
            self.assertEqual(result.stop["cause"], "breach")
            self.assertEqual(result.exit_code, 3)

    def test_gap_is_measured_from_the_pre_launch_sample(self):
        class SlowFirstSample:
            def __init__(self):
                self.offset = 0.0

            def __call__(self):
                return time.monotonic() + self.offset

        clock = SlowFirstSample()

        class StallAfterFirstSample(g.ContainmentGuard):
            calls = 0

            def sample(self):
                out = super().sample()
                StallAfterFirstSample.calls += 1
                if StallAfterFirstSample.calls == 1:
                    clock.offset = 3.0  # the guard stalls right after the pre-launch sample
                return out

        result = StallAfterFirstSample("p", volumes(), interval=0.2, sampler=Sampler(), clock=clock).run(
            py("import time; time.sleep(30)"))
        self.assertEqual(result.breach["kind"], "sampling-gap")
        self.assertEqual(result.samples, 2)

    def test_late_sample_completion_is_caught_at_that_sample(self):
        class Clock:
            offset = 0.0

            def __call__(self):
                return time.monotonic() + self.offset

        clock = Clock()

        class StallInsideThirdSample(g.ContainmentGuard):
            calls = 0

            def sample(self):
                out = super().sample()
                StallInsideThirdSample.calls += 1
                if StallInsideThirdSample.calls == 3:
                    clock.offset += 2.5  # this sample's result arrived late
                return out

        result = StallInsideThirdSample("p", volumes(), interval=0.2, sampler=Sampler(), clock=clock).run(
            py("import time; time.sleep(30)"))
        self.assertEqual(result.breach["kind"], "sampling-gap")
        self.assertEqual(result.samples, 3)  # not one sample later

    def test_signal_during_spawn_still_stops_and_records(self):
        original = g.subprocess.Popen
        saved = {k: (list(v) if isinstance(v, list) else v) for k, v in g._SIGNALS.items()}

        def popen_with_signal(*a, **k):
            g._raise_interrupted(signal.SIGTERM, None)  # arrives while spawning (deferred)
            return original(*a, **k)

        g.subprocess.Popen = popen_with_signal
        try:
            g._SIGNALS.update(defer=False, deferred=[], raised=False)
            result = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler()).run(
                py("import time; time.sleep(30)"))
            raised_after_spawn = g._SIGNALS["raised"]
        finally:
            g.subprocess.Popen = original
            g._SIGNALS.update(saved)
        self.assertTrue(raised_after_spawn)  # a later signal cannot raise a second time
        self.assertEqual(result.breach, {"volume": None, "kind": "interrupted", "reason": "GuardInterrupted"})
        self.assertEqual(result.stop["client_signals"][0], "SIGTERM")
        self.assertIsNotNone(result.child_returncode)

    def test_exited_leader_is_not_reaped_or_counted_while_guarding(self):
        child = subprocess.Popen([sys.executable, "-c", "pass"], start_new_session=True)
        try:
            end = time.monotonic() + 10
            while not g.ContainmentGuard._leader_exited(child):
                self.assertLess(time.monotonic(), end)
                time.sleep(0.01)
            self.assertIsNone(child.returncode)  # still a zombie: its PID/PGID stays reserved
            self.assertTrue(os.path.exists(f"/proc/{child.pid}"))
            self.assertEqual(g.ContainmentGuard._group_members(child.pid), [])
        finally:
            child.wait()

    def test_clean_child_exits_zero(self):
        result = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler()).run(py("pass"))
        self.assertEqual((result.breached, result.child_returncode, result.exit_code), (False, 0, 0))

    def test_breach_before_start_launches_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp, "ran")
            result = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler({"/vol/c": [LOW_C]})).run(
                py(f"open({str(marker)!r},'w').write('x')"))
            self.assertTrue(result.breached)
            self.assertIsNone(result.child_returncode)
            self.assertEqual(result.exit_code, 3)
            self.assertFalse(marker.exists())

    def test_breach_stops_owned_process_group_and_retains_partial_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            partial, gpid, ready = Path(tmp, "partial.bin"), Path(tmp, "grandchild.pid"), Path(tmp, "ready")
            code = f"""
                import subprocess, sys, time
                open({str(partial)!r}, 'wb').write(b'x' * 4096)
                p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
                open({str(gpid)!r}, 'w').write(str(p.pid))
                open({str(ready)!r}, 'w').write('1')
                time.sleep(60)
                """
            sampler = Sampler(ready=ready, after_ready={"/vol/c": LOW_C})
            start = time.monotonic()
            result = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=sampler).run(py(code))
            self.assertLess(time.monotonic() - start, 15)
            self.assertTrue(result.breached)
            self.assertEqual((result.breach["volume"], result.breach["kind"]), ("C:", "below-threshold"))
            self.assertEqual(result.stop["client_signals"][0], "SIGTERM")
            self.assertEqual(result.stop["failures"], [])
            self.assertNotEqual(result.child_returncode, 0)
            self.assertEqual(result.exit_code, 3)
            self.assertEqual(partial.read_bytes(), b"x" * 4096)  # retained, not deleted
            pid = int(gpid.read_text())
            end = time.monotonic() + 5
            while time.monotonic() < end:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("grandchild in the owned process group survived")

    def test_term_ignoring_client_is_killed(self):
        with tempfile.TemporaryDirectory() as tmp:
            ready = Path(tmp, "ready")
            sampler = Sampler(ready=ready, after_ready={"/vol/e": OSError("gone")})
            result = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=sampler).run(
                ready_sleeper(ready, "signal.signal(signal.SIGTERM, signal.SIG_IGN)"))
            self.assertEqual(result.breach["kind"], "unknown")
            self.assertEqual(result.stop["client_signals"], ["SIGTERM", "SIGKILL"])
            self.assertEqual(result.child_returncode, -9)

    def test_child_is_started_once_no_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            count, ready = Path(tmp, "count"), Path(tmp, "ready")
            code = f"""
                import time
                open({str(count)!r}, 'a').write('1')
                open({str(ready)!r}, 'w').write('1')
                time.sleep(60)
                """
            sampler = Sampler(ready=ready, after_ready={"/vol/c": LOW_C})
            result = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=sampler).run(py(code))
            time.sleep(0.5)
            self.assertTrue(result.breached)
            self.assertEqual(count.read_text(), "1")

    def test_group_member_outliving_client_is_stopped_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            gpid = Path(tmp, "bg.pid")
            code = f"""
                import subprocess, sys
                p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
                open({str(gpid)!r}, 'w').write(str(p.pid))
                """
            result = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler()).run(py(code))
            self.assertEqual(result.child_returncode, 0)
            self.assertEqual(result.stop["cause"], "owned work outlived client or state unproved")
            self.assertTrue(any(f["what"] == "lifecycle" for f in result.stop["failures"]))
            self.assertEqual(result.exit_code, 3)
            pid = int(gpid.read_text())
            end = time.monotonic() + 5
            while time.monotonic() < end:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            else:
                self.fail("background group member survived")

    def test_child_environment_carries_owner_and_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, cid_dir = Path(tmp, "env.json"), Path(tmp, "cids")
            cid_dir.mkdir()
            daemon = g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir)
            keys = ["VAST_PR9_GUARD_OWNER", "VAST_PR9_GUARD_OWNER_LABEL", "VAST_PR9_GUARD_LAUNCH_LABEL_KEY",
                    "VAST_PR9_GUARD_CID_DIR", "DOCKER_HOST"]
            code = f"import json,os; json.dump({{k: os.environ.get(k) for k in {keys!r}}}, open({str(out)!r},'w'))"
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), daemon=daemon,
                                       docker=FakeDocker(), owner_token=TOKEN)
            self.assertEqual(guard.run(py(code)).exit_code, 0)
            env = json.loads(out.read_text())
            self.assertEqual(env, {
                "VAST_PR9_GUARD_OWNER": TOKEN,
                "VAST_PR9_GUARD_OWNER_LABEL": f"{g.OWNER_LABEL}={TOKEN}",
                "VAST_PR9_GUARD_LAUNCH_LABEL_KEY": g.LAUNCH_LABEL,
                "VAST_PR9_GUARD_CID_DIR": str(cid_dir),
                "DOCKER_HOST": HOST,
            })


def cid_child(cid_dir: Path, files: dict, ready: Path, extra: str = "", then: str = "time.sleep(60)") -> list:
    """A phase client that writes its CID files (as `docker run --cidfile` would), signals ready, then `then`."""
    return py(f"""
        import time, signal, pathlib
        {extra}
        for name, data in {files!r}.items():
            pathlib.Path({str(cid_dir)!r}, name).write_bytes(data)
        open({str(ready)!r}, 'w').write('1')
        {then}
        """)


class AfterReady:
    """C: sample that breaches on its second call after `ready`, so at least one
    registration pass has run after the CID files appeared."""

    def __init__(self, ready: Path, docker, mutate=None):
        self.ready, self.docker, self.mutate, self.calls = ready, docker, mutate, 0

    def __call__(self):
        self.calls += 1
        if self.calls < 2:
            return PLENTY
        if self.mutate and self.calls == 2:
            self.mutate(self.docker)
        return LOW_C


class OwnedContainerStopTests(unittest.TestCase):
    def run_breach(self, cid_files, docker, mutate_after_ready=None, extra=""):
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            daemon = g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir)
            sampler = Sampler(ready=ready, after_ready={"/vol/c": AfterReady(ready, docker, mutate_after_ready)})
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=sampler, daemon=daemon,
                                       docker=docker, owner_token=TOKEN)
            result = guard.run(cid_child(cid_dir, cid_files, ready, extra))
            remaining = sorted(p.name for p in cid_dir.iterdir())
        return result, remaining

    def test_registered_container_is_stopped_after_its_cid_file_vanishes(self):
        docker = FakeDocker(containers={CID_A: container("w1")})
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready, gone = Path(tmp, "cids"), Path(tmp, "ready"), Path(tmp, "gone")
            daemon = g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir)
            cid_dir.mkdir()
            # phase writes its CID file, waits until registered, then deletes it and runs on
            code = f"""
                import pathlib, time
                f = pathlib.Path({str(cid_dir)!r}, 'w1.cid')
                f.write_bytes({CID_A.encode()!r})
                time.sleep(1.0)
                f.unlink()
                open({str(gone)!r}, 'w').write('1')
                time.sleep(60)
                """
            sampler = Sampler(ready=gone, after_ready={"/vol/c": LOW_C})
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=sampler, daemon=daemon,
                                       docker=docker, owner_token=TOKEN)
            result = guard.run(py(code))
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.containers[CID_A]["identity_source"], "first-observation")

    def test_non_empty_cid_dir_is_refused_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, marker = Path(tmp, "cids"), Path(tmp, "ran")
            cid_dir.mkdir()
            Path(cid_dir, "old.cid").write_bytes(CID_A.encode())
            guard = g.ContainmentGuard("p", volumes(), sampler=Sampler(), docker=FakeDocker(),
                                       daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            with self.assertRaises(g.GuardError):
                guard.run(py(f"open({str(marker)!r},'w').write('x')"))
            self.assertFalse(marker.exists())

    def test_cid_overflow_is_a_breach(self):
        original = g._MAX_CID_FILES
        g._MAX_CID_FILES = 2
        try:
            docker = FakeDocker(containers={CID_A: container("a"), CID_B: container("b")})
            with tempfile.TemporaryDirectory() as tmp:
                cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
                cid_dir.mkdir()
                files = {"a.cid": CID_A.encode(), "b.cid": CID_B.encode(), "c.cid": ("c" * 64).encode()}
                guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                           owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
                result = guard.run(cid_child(cid_dir, files, ready))
        finally:
            g._MAX_CID_FILES = original
        self.assertEqual(result.breach["kind"], "cid-overflow")
        self.assertEqual(result.exit_code, 3)

    def test_owned_container_killed_and_retirement_confirmed(self):
        docker = FakeDocker(containers={CID_A: container("w1")})
        result, remaining = self.run_breach({"w1.cid": CID_A.encode()}, docker)
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.stop["failures"], [])
        self.assertEqual(result.containers[CID_A]["state"], "killed; retirement confirmed")
        self.assertEqual(result.containers[CID_A]["identity_source"], "first-observation")
        self.assertEqual(docker.mutations(), [("container", "kill", CID_A)])
        self.assertTrue(all(c[0] == HOST for c in docker.calls))
        self.assertEqual(remaining, ["w1.cid"])  # CID evidence retained
        kill_i = docker.verbs().index("kill")
        self.assertEqual(docker.verbs()[kill_i + 1], "inspect")  # retirement observed after kill

    def test_foreign_or_absent_identity_is_not_mutated(self):
        docker = FakeDocker(containers={CID_A: container("a", owner="someone-else")})
        c3 = "c" * 64
        result, _ = self.run_breach({"a.cid": CID_A.encode(), "c.cid": c3.encode()}, docker)
        self.assertEqual(result.stop["killed_containers"], [])
        reasons = sorted(f["reason"] for f in result.stop["failures"])
        self.assertEqual(reasons, ["absence or identity unproved; not mutated", "foreign identity; not mutated"])
        self.assertEqual(docker.mutations(), [])
        self.assertEqual(result.exit_code, 3)

    def test_decoy_registered_writer_survives_file_removal_and_a_wedged_listing(self):
        docker = FakeDocker(containers={CID_B: container("w1")}, slow_ls=True)
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, gone = Path(tmp, "cids"), Path(tmp, "gone")
            cid_dir.mkdir()
            code = f"""
                import pathlib, time
                f = pathlib.Path({str(cid_dir)!r}, 'decoy.cid')
                f.write_bytes({CID_B.encode()!r})
                time.sleep(1.0)
                f.unlink()
                open({str(gone)!r}, 'w').write('1')
                time.sleep(60)
                """
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, docker=docker, owner_token=TOKEN,
                                       daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir),
                                       sampler=Sampler(ready=gone, after_ready={"/vol/c": LOW_C}))
            result = guard.run(py(code))
        self.assertEqual(result.stop["killed_containers"], [CID_B])  # pinned at registration, not by ls
        self.assertEqual(result.containers[CID_B]["identity_source"], "first-observation")

    def test_cid_read_but_never_inspected_is_still_a_stop_target(self):
        class NoTimeToRegister(FakeDocker):
            armed = False

            def __call__(self, host, args, timeout):
                if args[:2] == ["container", "inspect"] and not self.armed:
                    with self.lock:
                        self.calls.append((host, tuple(args), time.monotonic()))
                    return 124, ""  # registration never gets an inspect through
                return super().__call__(host, args, timeout)

        docker = NoTimeToRegister(containers={CID_B: container("w1")}, slow_ls=True)
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, gone = Path(tmp, "cids"), Path(tmp, "gone")
            cid_dir.mkdir()
            code = f"""
                import pathlib, time
                f = pathlib.Path({str(cid_dir)!r}, 'decoy.cid')
                f.write_bytes({CID_B.encode()!r})
                time.sleep(1.0)
                f.unlink()
                open({str(gone)!r}, 'w').write('1')
                time.sleep(60)
                """

            def breach_and_arm():
                docker.armed = True
                return LOW_C

            guard = g.ContainmentGuard("p", volumes(), interval=0.2, docker=docker, owner_token=TOKEN,
                                       daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir),
                                       sampler=Sampler(ready=gone, after_ready={"/vol/c": breach_and_arm}))
            result = guard.run(py(code))
        self.assertEqual(result.stop["killed_containers"], [CID_B])  # the file is gone and ls is wedged

    def test_cid_parsed_by_a_scan_that_later_stalls_is_kept(self):
        docker = FakeDocker(containers={CID_A: container("a")}, slow_ls=True)
        gate = threading.Event()
        real_read = g._read_cid_file

        def read(path):
            if path.name == "b.cid":
                gate.wait(30)  # the scan has parsed a.cid and now blocks on b.cid
            return real_read(path)

        g._read_cid_file = read
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cid_dir = Path(tmp, "cids")
                cid_dir.mkdir()
                code = f"""
                    import pathlib, time
                    a = pathlib.Path({str(cid_dir)!r}, 'a.cid')
                    a.write_bytes({CID_A.encode()!r})
                    pathlib.Path({str(cid_dir)!r}, 'b.cid').write_bytes({CID_B.encode()!r})
                    time.sleep(0.3)
                    a.unlink()
                    time.sleep(60)
                    """
                guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                           owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
                result = guard.run(py(code))
        finally:
            g._read_cid_file = real_read
            gate.set()
        self.assertEqual(result.breach["kind"], "cid-scan-stalled")
        self.assertIn(CID_A, result.stop["killed_containers"])  # file gone, listing wedged, scans stalled

    def test_decoy_cid_file_name_cannot_hide_a_token_owned_writer(self):
        docker = FakeDocker(containers={CID_B: container("w1")})  # this run's token, launch label w1
        result, _ = self.run_breach({"decoy.cid": CID_B.encode()}, docker)
        self.assertEqual(result.stop["killed_containers"], [CID_B])
        # registered by token despite the decoy stem, so its first observation is checked before the kill
        self.assertEqual(result.containers[CID_B]["identity_source"], "first-observation")

    def test_identity_changed_since_first_observation_is_not_mutated(self):
        docker = FakeDocker(containers={CID_A: container("w1")})

        def swap(d):
            d.containers[CID_A]["image"] = "sha256:" + "2" * 64

        result, _ = self.run_breach({"w1.cid": CID_A.encode()}, docker, mutate_after_ready=swap)
        self.assertEqual(docker.mutations(), [])
        self.assertEqual(result.stop["failures"][0]["reason"], "identity changed since first observation; not mutated")

    def test_engine_identity_mismatch_at_stop_mutates_nothing(self):
        docker = FakeDocker(containers={CID_A: container("a")})

        def switch(d):
            d.engine_id = g.NATIVE_ENGINE_ID

        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker, mutate_after_ready=switch)
        self.assertEqual(result.stop["killed_containers"], [])
        self.assertEqual(result.stop["failures"][0]["reason"], "engine identity not confirmed; not mutated")
        self.assertEqual(docker.mutations(), [])

    def test_malformed_cid_files_are_failures_not_targets(self):
        docker = FakeDocker(containers={CID_A: container("ok")})
        result, _ = self.run_breach({"short.cid": b"abc123", "name.cid": b"vast-worker", "noext": CID_A.encode(),
                                     "ok.cid": CID_A.encode()}, docker)
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(sorted(f["file"] for f in result.stop["failures"]), ["name.cid", "noext", "short.cid"])

    def test_unconfirmed_retirement_is_a_failure_and_others_still_attempted(self):
        docker = FakeDocker(containers={CID_A: container("a"), CID_B: container("b")}, kill_rc=1, kill_works=False)
        result, _ = self.run_breach({"a.cid": CID_A.encode(), "b.cid": CID_B.encode()}, docker)
        self.assertGreaterEqual(len(docker.mutations()), 2)  # unsettled CIDs are retried by the second pass
        self.assertEqual(len(result.stop["failures"]), 2)  # each failure recorded once
        self.assertEqual({c["state"] for c in result.containers.values()}, {"retirement unconfirmed"})

    def test_created_container_is_rechecked_after_the_client_stops(self):
        class StartsLate(FakeDocker):
            armed = False

            def __call__(self, host, args, timeout):
                out = super().__call__(host, args, timeout)
                if self.armed and args[:2] == ["container", "inspect"] and args[-1] == CID_A:
                    self.containers[CID_A]["status"] = "running"  # the in-flight start completes
                    self.containers[CID_A]["running"] = True
                    self.armed = False
                return out

        def arm(d):
            d.armed = True

        started = StartsLate(containers={CID_A: container("a", running=False, status="created")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, started, mutate_after_ready=arm)
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.stop["failures"], [])

        stuck = FakeDocker(containers={CID_A: container("a", running=False, status="created")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, stuck)
        self.assertEqual(stuck.mutations(), [])
        self.assertEqual([f["reason"] for f in result.stop["failures"]],
                         ["still created after the client stopped; retirement unconfirmed"])

    def test_already_exited_container_is_not_killed_and_not_a_failure(self):
        docker = FakeDocker(containers={CID_A: container("a", running=False)})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertEqual(docker.mutations(), [])
        self.assertEqual(result.stop["failures"], [])
        self.assertEqual(result.containers[CID_A]["state"], "not live (exited)")

    def test_docker_timeout_during_stop_is_recorded_not_raised(self):
        docker = FakeDocker(containers={CID_A: container("a")})

        def break_docker(d):
            d.raise_on = ["container", "kill"]

        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker, mutate_after_ready=break_docker)
        self.assertTrue(result.breached)
        self.assertEqual(result.exit_code, 3)
        self.assertEqual(result.containers[CID_A]["state"], "retirement unconfirmed")
        self.assertIn("rc 125", result.stop["failures"][0]["reason"])
        json.dumps(result.as_record())

    def test_term_ignoring_client_does_not_starve_container_stop(self):
        docker = FakeDocker(containers={CID_A: container("a")})
        kill_time = {}
        original = g.os.killpg

        def spy(pgid, sig):
            if sig == signal.SIGKILL:
                kill_time["sigkill"] = time.monotonic()
            return original(pgid, sig)

        g.os.killpg = spy
        try:
            result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker,
                                        extra="signal.signal(signal.SIGTERM, signal.SIG_IGN)")
        finally:
            g.os.killpg = original
        container_kill = [c[2] for c in docker.calls if c[1][:2] == ("container", "kill")]
        self.assertEqual(result.stop["client_signals"], ["SIGTERM", "SIGKILL"])
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertLess(container_kill[0], kill_time["sigkill"])

    def test_refused_group_signal_is_recorded_not_raised(self):
        docker = FakeDocker(containers={CID_A: container("a")})
        original = g.os.killpg
        calls = {"n": 0}

        def eperm_once(pgid, sig):
            if sig == signal.SIGTERM and calls["n"] == 0:
                calls["n"] += 1
                raise PermissionError(1, "Operation not permitted")
            return original(pgid, sig)

        g.os.killpg = eperm_once
        try:
            result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        finally:
            g.os.killpg = original
        self.assertIn("SIGTERM refused: PermissionError", [f["reason"] for f in result.stop["failures"]])
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertIn("SIGKILL", result.stop["client_signals"])
        self.assertEqual(result.exit_code, 3)

    def run_until_exit(self, docker, files, then="time.sleep(0.3)"):
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            return guard.run(cid_child(cid_dir, files, ready, then=then))

    def test_running_owned_container_after_client_exit_is_stopped_as_failure(self):
        docker = FakeDocker(containers={CID_A: container("a")})
        result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})  # like `docker run -d`, then exit
        self.assertEqual(result.child_returncode, 0)
        self.assertEqual(result.stop["cause"], "owned work outlived client or state unproved")
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.exit_code, 3)

    def test_unproved_container_state_after_client_exit_is_a_failure(self):
        docker = FakeDocker(containers={})  # inspect fails: absence is not proved
        result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})
        self.assertEqual(result.child_returncode, 0)
        lifecycle = [f for f in result.stop["failures"] if f["what"] == "lifecycle"]
        self.assertEqual(lifecycle[0]["unproved"], [CID_A])
        self.assertEqual(docker.mutations(), [])
        self.assertEqual(result.exit_code, 3)

    def test_rm_removed_container_after_client_exit_is_proved_absent_and_clean(self):
        docker = FakeDocker(absent={CID_A})
        result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})
        self.assertEqual((result.breached, result.stop, result.exit_code), (False, {}, 0))
        verbs = docker.verbs()
        self.assertIn("info", verbs[verbs.index("inspect"):])  # engine confirmed when absence is trusted

    def test_absence_naming_another_cid_or_on_wrong_engine_is_unproved(self):
        cases = {
            "other-cid": FakeDocker(absent={CID_A}, absent_text=f"Error: No such container: {CID_B}"),
            "short-cid": FakeDocker(absent={CID_A}, absent_text=f"Error: No such container: {CID_A[:12]}"),
            "wrong-engine": FakeDocker(absent={CID_A}, engine_id=g.NATIVE_ENGINE_ID),
        }
        for name, docker in cases.items():
            with self.subTest(name=name):
                if name == "wrong-engine":
                    # admitted engine at preflight; later answers come from another engine
                    fake = docker
                    fake.engine_id = g.DESKTOP_ENGINE_ID

                    def switching(host, args, timeout, d=fake):
                        if args[:1] == ["info"] and any(c[1][:1] == ("info",) for c in d.calls):
                            d.engine_id = g.NATIVE_ENGINE_ID
                        return FakeDocker.__call__(d, host, args, timeout)

                    docker = _Wrapped(fake, switching)
                result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})
                lifecycle = [f for f in result.stop["failures"] if f["what"] == "lifecycle"]
                self.assertEqual(lifecycle[0]["unproved"], [CID_A])
                self.assertEqual(result.exit_code, 3)

    def test_absent_container_at_stop_is_recorded_not_failed(self):
        docker = FakeDocker(absent={CID_A})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertEqual(result.stop["failures"], [])
        self.assertEqual(result.containers[CID_A]["state"], "absent; proved on the original daemon")
        self.assertEqual(docker.mutations(), [])

    def test_exited_owned_container_after_client_exit_is_clean(self):
        docker = FakeDocker(containers={CID_A: container("a", running=False)})
        result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})
        self.assertEqual((result.breached, result.stop, result.exit_code), (False, {}, 0))

    def test_internal_error_after_launch_stops_owned_work_and_is_recorded(self):
        docker = FakeDocker(containers={CID_A: container("a")})
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            original = guard.cid_overflow

            def boom():
                if ready.exists() and any(cid_dir.iterdir()):
                    raise RuntimeError("bug")
                return original()

            guard.cid_overflow = boom
            result = guard.run(cid_child(cid_dir, {"a.cid": CID_A.encode()}, ready))
        self.assertEqual(result.breach, {"volume": None, "kind": "internal-error", "reason": "RuntimeError"})
        self.assertEqual(result.stop["cause"], "internal-error")
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.exit_code, 3)

    def test_guard_signal_during_stop_is_recorded_not_raised(self):
        class SignalingDocker(FakeDocker):
            armed = False

            def __call__(self, host, args, timeout):
                if self.armed and args[:2] == ["container", "kill"]:
                    g._raise_interrupted(signal.SIGTERM, None)  # what the installed handler does mid-stop
                return super().__call__(host, args, timeout)

        def arm(d):
            d.armed = True

        docker = SignalingDocker(containers={CID_A: container("a")})
        saved = {k: (list(v) if isinstance(v, list) else v) for k, v in g._SIGNALS.items()}
        try:
            g._SIGNALS.update(defer=False, deferred=["SIGHUP"], raised=False)  # recorded before this run
            result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker, mutate_after_ready=arm)
        finally:
            g._SIGNALS.update(saved)
        self.assertEqual(result.stop["interrupted_during_stop"], ["SIGTERM"])
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.stop["failures"], [])
        self.assertEqual(result.exit_code, 3)

    def test_paused_or_restarting_owned_container_after_client_exit_is_stopped(self):
        for status in ("paused", "restarting"):
            with self.subTest(status=status):
                docker = FakeDocker(containers={CID_A: container("a", status=status)})
                result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})
                self.assertEqual(result.stop["killed_containers"], [CID_A])
                lifecycle = [f for f in result.stop["failures"] if f["what"] == "lifecycle"]
                self.assertEqual(lifecycle[0]["running_containers"], [CID_A])
                self.assertEqual(result.exit_code, 3)

    def test_unauthenticated_cid_after_client_exit_is_unproved_not_clean(self):
        docker = FakeDocker(containers={CID_A: container("a", owner="someone-else", running=False)})
        result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})
        lifecycle = [f for f in result.stop["failures"] if f["what"] == "lifecycle"]
        self.assertEqual(lifecycle[0]["unproved"], [CID_A])
        self.assertEqual(docker.mutations(), [])
        self.assertEqual(result.exit_code, 3)

    def test_stop_reads_past_the_sample_scan_cap_when_the_listing_fails(self):
        cid_c = "c" * 64
        original = (g._MAX_CID_FILES, g.ContainmentGuard._cid_files.__defaults__)
        g._MAX_CID_FILES, g.ContainmentGuard._cid_files.__defaults__ = 2, (2,)
        try:
            docker = FakeDocker(containers={CID_A: container("a"), CID_B: container("b"), cid_c: container("c")},
                                ls_rc=1)  # only the CID files can find the containers
            with tempfile.TemporaryDirectory() as tmp:
                cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
                cid_dir.mkdir()
                files = {"a.cid": CID_A.encode(), "b.cid": CID_B.encode(), "c.cid": cid_c.encode()}
                guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                           owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
                result = guard.run(cid_child(cid_dir, files, ready))
        finally:
            g._MAX_CID_FILES, g.ContainmentGuard._cid_files.__defaults__ = original
        self.assertEqual(result.breach["kind"], "cid-overflow")
        self.assertEqual(sorted(result.stop["killed_containers"]), sorted([CID_A, CID_B, cid_c]))

    def test_token_owned_container_with_an_invalid_launch_label_is_not_mutated(self):
        docker = FakeDocker(containers={CID_A: container("not a launch!")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertEqual(docker.mutations(), [])  # neither the file stem nor the owner label proves it
        self.assertIn({"what": "container", "cid": CID_A, "reason": "foreign identity; not mutated"},
                      result.stop["failures"])
        self.assertEqual(result.exit_code, 3)

    def test_inspect_output_with_an_unexpected_rc_is_unproved(self):
        class BadRc(FakeDocker):
            def __call__(self, host, args, timeout):
                rc, out = super().__call__(host, args, timeout)
                return (125, out) if args[:2] == ["container", "inspect"] else (rc, out)

        docker = BadRc(containers={CID_A: container("a")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertEqual(docker.mutations(), [])
        self.assertIn({"what": "container", "cid": CID_A, "reason": "absence or identity unproved; not mutated"},
                      result.stop["failures"])

    def test_oversized_cid_file_with_a_valid_prefix_is_not_a_target(self):
        docker = FakeDocker(containers={CID_A: container("a")}, ls_rc=1)  # the file is the only lead
        result, _ = self.run_breach({"a.cid": CID_A.encode() + b" " * 70 + b"tail"}, docker)
        self.assertEqual(docker.mutations(), [])
        self.assertIn({"what": "cid-file", "file": "a.cid", "reason": "ValueError"}, result.stop["failures"])

    def test_killed_restart_policy_container_that_stays_down_is_not_retired(self):
        docker = FakeDocker(containers={CID_A: container("a", restart="unless-stopped")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertNotEqual(result.containers[CID_A]["state"], "killed; retirement confirmed")
        self.assertIn("restart policy unless-stopped; retirement cannot be proved",
                      [f["reason"] for f in result.stop["failures"]])
        self.assertEqual(result.exit_code, 3)

    def test_hung_cid_count_is_bounded_and_counted_as_a_stall(self):
        gate, real = threading.Event(), os.scandir
        box: dict = {}

        def hung(path):
            gate.wait(10)
            return real(path)

        with tempfile.TemporaryDirectory() as tmp:
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=FakeDocker(),
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, Path(tmp)))
            worker = threading.Thread(target=lambda: box.setdefault("over", guard.cid_overflow()), daemon=True)
            os.scandir = hung
            try:
                start = time.monotonic()
                worker.start()
                worker.join(3)
                finished, elapsed = not worker.is_alive(), time.monotonic() - start
            finally:
                os.scandir = real
                gate.set()
                worker.join(12)
        self.assertTrue(finished)
        self.assertLess(elapsed, 1.5)
        self.assertIs(box["over"], False)  # a stalled count is a stall, not an overflow
        self.assertEqual(guard._scan_timeouts, 1)

    def test_stop_keeps_signals_deferred_when_the_guard_holds_them(self):
        saved = {k: (list(v) if isinstance(v, list) else v) for k, v in g._SIGNALS.items()}
        try:
            for hold in (True, False):
                with self.subTest(hold=hold):
                    g._SIGNALS.update(defer=False, deferred=[], raised=False)
                    guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler())
                    guard.hold_signals_after_run = hold
                    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                             start_new_session=True)
                    try:
                        guard.stop_owned(child, g.GuardResult("p", ""), "test")
                    finally:
                        child.kill()
                        child.wait()
                    self.assertIs(g._SIGNALS["defer"], hold)  # main keeps them deferred until the record is written
        finally:
            g._SIGNALS.update(saved)

    def test_overflowing_cid_dir_still_stops_every_container(self):
        original = g._MAX_CID_FILES
        g._MAX_CID_FILES = 2
        cid_c = "c" * 64
        try:
            docker = FakeDocker(containers={CID_A: container("a"), CID_B: container("b"), cid_c: container("c")})
            with tempfile.TemporaryDirectory() as tmp:
                cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
                cid_dir.mkdir()
                files = {"a.cid": CID_A.encode(), "b.cid": CID_B.encode(), "c.cid": cid_c.encode()}
                guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                           owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
                result = guard.run(cid_child(cid_dir, files, ready))
        finally:
            g._MAX_CID_FILES = original
        self.assertEqual(result.breach["kind"], "cid-overflow")
        self.assertEqual(sorted(result.stop["killed_containers"]), sorted([CID_A, CID_B, cid_c]))

    def test_container_started_after_sigterm_is_stopped_in_the_second_pass(self):
        cid_c = "c" * 64
        docker = FakeDocker(containers={CID_A: container("a"), cid_c: container("late")})
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            late = Path(cid_dir, "late.cid")
            # ignores SIGTERM and, on it, starts one more owned container
            extra = ("import threading; signal.signal(signal.SIGTERM, lambda *a: threading.Timer(0.3, lambda: "
                     f"pathlib.Path({str(late)!r}).write_bytes({cid_c.encode()!r})).start())")
            sampler = Sampler(ready=ready, after_ready={"/vol/c": AfterReady(ready, docker)})
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=sampler, docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            result = guard.run(cid_child(cid_dir, {"a.cid": CID_A.encode()}, ready, extra))
        self.assertEqual(sorted(result.stop["killed_containers"]), sorted([CID_A, cid_c]))
        self.assertEqual(result.stop["client_signals"], ["SIGTERM", "SIGKILL"])

    def test_client_exit_proof_and_stop_share_one_budget(self):
        docker = FakeDocker(containers={CID_A: container("a")})
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            seen = {}
            original_after, original_stop = guard._after_client_exit, guard.stop_owned

            def after(child, result):
                seen["start"] = time.monotonic()
                return original_after(child, result)

            def stop(child, result, cause, deadline=None, **kw):
                seen["deadline"] = deadline
                return original_stop(child, result, cause, deadline, **kw)

            guard._after_client_exit, guard.stop_owned = after, stop
            result = guard.run(cid_child(cid_dir, {"a.cid": CID_A.encode()}, ready, then="time.sleep(0.3)"))
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertIsNotNone(seen["deadline"])
        self.assertLessEqual(seen["deadline"] - seen["start"], g.STOP_BUDGET_SECONDS + 0.05)

    def test_fifo_or_oversized_cid_file_does_not_block_the_guard(self):
        docker = FakeDocker()
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            code = f"""
                import os, time
                os.mkfifo({str(Path(cid_dir, 'w.cid'))!r})
                open({str(Path(cid_dir, 'big.cid'))!r}, 'wb').write(b'a' * 4096)
                time.sleep(0.5)
                """
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            start = time.monotonic()
            result = guard.run(py(code))
            self.assertLess(time.monotonic() - start, 15)
        self.assertEqual(result.exit_code, 3)
        lifecycle = [f for f in result.stop["failures"] if f["what"] == "lifecycle"]
        self.assertEqual(sorted(lifecycle[0]["unproved"]), ["big.cid", "w.cid"])

    def test_restart_policy_is_killed_but_never_counted_as_retired(self):
        class Revives(FakeDocker):
            revived = False

            def __call__(self, host, args, timeout):
                out = super().__call__(host, args, timeout)
                # dockerd restarts the killed container once its kill has been observed
                if args[:2] == ["container", "inspect"] and not self.revived and \
                        any(c[1][:2] == ("container", "kill") for c in self.calls):
                    self.containers[CID_A].update(running=True, status="running")
                    self.revived = True
                return out

        docker = Revives(containers={CID_A: container("a", restart="always")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertEqual(len(docker.mutations()), 2)  # revived container killed again by the second pass
        self.assertIn("restart policy always; retirement cannot be proved",
                      [f["reason"] for f in result.stop["failures"]])
        self.assertNotEqual(result.containers[CID_A]["state"], "killed; retirement confirmed")
        self.assertEqual(result.exit_code, 3)

    def test_exited_container_restarted_by_the_client_before_sigkill_is_stopped(self):
        class ClientRestarts(FakeDocker):
            armed = False

            def __call__(self, host, args, timeout):
                out = super().__call__(host, args, timeout)
                if self.armed and args[:2] == ["container", "inspect"] and args[-1] == CID_A:
                    self.containers[CID_A].update(running=True, status="running")  # `docker start` during grace
                    self.armed = False
                return out

        def arm(d):
            d.armed = True

        docker = ClientRestarts(containers={CID_A: container("a", running=False, status="exited")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker, mutate_after_ready=arm)
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.containers[CID_A]["state"], "killed; retirement confirmed")

    def test_duplicate_cid_under_a_foreign_name_does_not_hide_the_owned_launch(self):
        docker = FakeDocker(containers={CID_A: container("worker")})
        result, _ = self.run_breach({"old.cid": CID_A.encode(), "worker.cid": CID_A.encode()}, docker)
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.containers[CID_A]["launch"], "worker")

    def test_nothing_settles_while_the_client_group_is_alive(self):
        docker = FakeDocker(containers={CID_A: container("a", running=False, status="exited")})
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()

            class StuckClient(g.ContainmentGuard):
                stopping = False

                def _group_alive(self, pgid):  # e.g. a client in D-state that SIGKILL cannot clear
                    return True if self.stopping else super()._group_alive(pgid)

                def stop_owned(self, *a, **k):
                    self.stopping = True
                    return super().stop_owned(*a, **k)

            sampler = Sampler(ready=ready, after_ready={"/vol/c": AfterReady(ready, docker)})
            guard = StuckClient("p", volumes(), interval=0.2, sampler=sampler, docker=docker, owner_token=TOKEN,
                                daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            result = guard.run(cid_child(cid_dir, {"a.cid": CID_A.encode()}, ready))
        reasons = [f["reason"] for f in result.stop["failures"]]
        self.assertIn("client group still alive; retirement unconfirmed", reasons)
        self.assertNotEqual(result.containers[CID_A]["state"], "killed; retirement confirmed")
        self.assertEqual(result.exit_code, 3)

    def test_many_containers_are_stopped_in_batches_within_the_budget(self):
        cids = [f"{i:064x}" for i in range(1, 61)]
        docker = FakeDocker(containers={cid: container(f"w{i}") for i, cid in enumerate(cids)}, slow_call=0.3)
        files = {f"w{i}.cid": cid.encode() for i, cid in enumerate(cids)}
        start = {}
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            sampler = Sampler(ready=ready, after_ready={"/vol/c": AfterReady(ready, docker)})

            class Timed(g.ContainmentGuard):
                def stop_owned(self, *a, **k):
                    start["t"] = time.monotonic()
                    return super().stop_owned(*a, **k)

            guard = Timed("p", volumes(), interval=1.0, sampler=sampler, docker=docker, owner_token=TOKEN,
                          daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            result = guard.run(cid_child(cid_dir, files, ready))
            elapsed = time.monotonic() - start["t"]
        self.assertEqual(sorted(result.stop["killed_containers"]), sorted(cids))
        self.assertLessEqual(elapsed, g.STOP_BUDGET_SECONDS + 1.0)
        stop_calls = [c for c in docker.calls if c[2] >= start["t"]]
        self.assertLessEqual(len(stop_calls), 10)  # batched: not one CLI call per container

    def test_owned_container_without_a_cid_file_is_found_by_owner_label(self):
        # `docker run -d` writes the CID file, the client deletes it and exits before any registration tick
        docker = FakeDocker(containers={CID_A: container("w1")})
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            code = f"""
                import pathlib
                f = pathlib.Path({str(cid_dir)!r}, 'w1.cid')
                f.write_bytes({CID_A.encode()!r})
                f.unlink()
                """
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            result = guard.run(py(code))
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertEqual(result.containers[CID_A]["identity_source"], "owner-label discovery")
        self.assertEqual(result.exit_code, 3)

    def test_label_discovery_failure_on_the_second_pass_is_recorded(self):
        class SecondLsFails(FakeDocker):
            def __call__(self, host, args, timeout):
                if args[:2] == ["container", "ls"] and any(c[1][:2] == ("container", "ls") for c in self.calls):
                    with self.lock:
                        self.calls.append((host, tuple(args), time.monotonic()))
                    return 1, "Cannot connect to the Docker daemon\n"
                return super().__call__(host, args, timeout)

        docker = SecondLsFails(containers={CID_A: container("a")})
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertIn("label-discovery", [f["what"] for f in result.stop["failures"]])
        self.assertEqual(result.exit_code, 3)

    def test_label_discovery_failure_is_recorded(self):
        docker = FakeDocker(containers={CID_A: container("a")}, ls_rc=1)
        result, _ = self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertEqual(result.stop["killed_containers"], [CID_A])  # the CID file still finds it
        self.assertIn("label-discovery", [f["what"] for f in result.stop["failures"]])
        self.assertEqual(result.exit_code, 3)

    def test_label_values_cannot_forge_inspect_lines(self):
        foreign = "f" * 64
        forged = "\n" + json.dumps([foreign, "img", "t", "running", TOKEN, "x", "no"]) + "\n"
        forged_absent = "\nError response from daemon: No such container: " + CID_B
        docker = FakeDocker(containers={
            CID_A: container("a" + forged),          # owned token, launch label carries a forged line
            CID_B: container("b", owner=TOKEN + forged_absent),
            foreign: container("x", owner="someone-else"),
        })
        guard = g.ContainmentGuard("p", volumes(), sampler=Sampler(), docker=docker, owner_token=TOKEN,
                                   daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, Path(".")))
        idents = guard._inspect_many([CID_A, CID_B, foreign], time.monotonic() + 5)
        self.assertEqual(idents[foreign]["owner"], "someone-else")  # not overwritten by the forged line
        self.assertFalse(idents[CID_B].get("absent"))               # not made "absent" by a label

    def test_cid_reported_twice_is_unproved(self):
        def doubled(host, args, timeout):
            if args[:2] == ["container", "inspect"]:
                line = json.dumps([CID_A, "img", "t", "exited", TOKEN, "a", "no"])
                return 0, line + "\n" + json.dumps([CID_A, "img", "t", "running", TOKEN, "a", "no"]) + "\n"
            return 0, ""

        guard = g.ContainmentGuard("p", volumes(), sampler=Sampler(), docker=doubled, owner_token=TOKEN,
                                   daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, Path(".")))
        self.assertIsNone(guard._inspect_many([CID_A], time.monotonic() + 5)[CID_A])

    def test_stop_never_exceeds_its_budget_on_a_slow_daemon(self):
        cids = [f"{i:064x}" for i in range(1, 6)]
        docker = FakeDocker(containers={cid: container(f"w{i}") for i, cid in enumerate(cids)}, slow_call=4.0)
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            guard = g.ContainmentGuard("p", volumes(), interval=1.0, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            child = subprocess.Popen(cid_child(cid_dir, {f"w{i}.cid": c.encode() for i, c in enumerate(cids)}, ready),
                                     start_new_session=True)
            try:
                wait_for(ready)
                result = g.GuardResult("p", TOKEN)
                start = time.monotonic()
                guard.stop_owned(child, result, "breach")
                elapsed = time.monotonic() - start
            finally:
                child.wait(timeout=15)
        self.assertLessEqual(elapsed, g.STOP_BUDGET_SECONDS + 0.5)
        self.assertTrue(result.stop["failures"])  # what it could not prove is recorded, not assumed

    def test_one_slow_cid_scan_is_tolerated(self):
        docker = FakeDocker()
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir = Path(tmp, "cids")
            cid_dir.mkdir()
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            original, calls = guard._cid_files_unbounded, {"n": 0}

            def slow_once(failures, limit):
                calls["n"] += 1
                if calls["n"] == 2:
                    time.sleep(g.CID_SCAN_SECONDS + 0.2)  # one slow scan under phase I/O, then normal
                return original(failures, limit)

            guard._cid_files_unbounded = slow_once
            result = guard.run(py("import time; time.sleep(1.5)"))
        self.assertFalse(result.breached)
        self.assertEqual(result.exit_code, 0)

    def test_stalled_cid_directory_scan_is_a_breach_not_a_hang(self):
        docker = FakeDocker(containers={CID_A: container("a")})
        with tempfile.TemporaryDirectory() as tmp:
            cid_dir, ready = Path(tmp, "cids"), Path(tmp, "ready")
            cid_dir.mkdir()
            guard = g.ContainmentGuard("p", volumes(), interval=0.2, sampler=Sampler(), docker=docker,
                                       owner_token=TOKEN, daemon=g.OwnedDaemon(HOST, g.DESKTOP_ENGINE_ID, cid_dir))
            gate = threading.Event()
            original = guard._cid_files_unbounded

            def stalls(failures, limit):
                if ready.exists():
                    gate.wait(30)  # e.g. the scan is stuck in D-state on the pressured volume
                return original(failures, limit)

            guard._cid_files_unbounded = stalls
            try:
                start = time.monotonic()
                result = guard.run(cid_child(cid_dir, {"a.cid": CID_A.encode()}, ready))
                elapsed = time.monotonic() - start
            finally:
                gate.set()
        self.assertEqual(result.breach["kind"], "cid-scan-stalled")
        self.assertLess(elapsed, 20)
        self.assertEqual(result.exit_code, 3)

    def test_wedged_label_listing_cannot_starve_a_known_kill_after_client_exit(self):
        docker = FakeDocker(containers={CID_A: container("a")}, slow_ls=True)
        result = self.run_until_exit(docker, {"a.cid": CID_A.encode()})
        self.assertEqual(result.stop["killed_containers"], [CID_A])
        self.assertIn("label-discovery", [f["what"] for f in result.stop["failures"]])
        kill_at = [c[2] for c in docker.calls if c[1][:2] == ("container", "kill")][0]
        first_ls = [c[2] for c in docker.calls if c[1][:2] == ("container", "ls")][0]
        self.assertLess(kill_at, first_ls)  # the known writer is killed before the daemon is listed
        self.assertEqual(result.exit_code, 3)

    def test_guard_never_issues_prune_remove_or_retry(self):
        docker = FakeDocker(containers={CID_A: container("a")})
        self.run_breach({"a.cid": CID_A.encode()}, docker)
        self.assertLessEqual(set(docker.verbs()), {"info", "inspect", "kill", "ls"})
        source = (ROOT / "scripts" / "accepted_policy_containment_guard_v1.py").read_text()
        for forbidden in ('"rm"', '"prune"', '"rmi"', "shutil.rmtree", "os.remove(", "unlink(", "rmdir("):
            self.assertNotIn(forbidden, source)


DRIVER = """
import sys
sys.path.insert(0, {scripts!r})
import accepted_policy_containment_guard_v1 as g
sys.exit(g.main(sys.argv[1:], sampler=lambda p: 500 * g.GIB, mount_type=lambda p: "9p"))
"""


class CliTests(unittest.TestCase):
    def test_main_end_to_end_writes_record_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp, "guard.json")
            rc = g.main(["--phase", "cli", "--record", str(record), "--interval", "0.2", "--",
                         sys.executable, "-c", "pass"],
                        sampler=lambda p: PLENTY, mount_type=lambda p: "9p")
            self.assertEqual(rc, 0)
            data = json.loads(record.read_text())
            self.assertEqual((data["schema"], data["exit_code"], data["breached"]),
                             ("vast.pr9.containment-guard.v1", 0, False))
            before = record.read_bytes()
            with CaptureFd2() as err, self.assertRaises(g.RecordWriteFailed):
                g._write_record(record, data)  # an existing record is never overwritten
            self.assertEqual(record.read_bytes(), before)
            self.assertIn("FileExistsError", err.text)

    def test_cli_refusals_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            existing, marker = Path(tmp, "r.json"), Path(tmp, "ran")
            existing.write_text("{}")
            cmd = ["--", sys.executable, "-c", f"open({str(marker)!r},'w').write('x')"]
            fresh, cids = str(Path(tmp, "n.json")), str(Path(tmp, "cids"))
            daemon = ["--docker-host", HOST, "--engine-id", g.DESKTOP_ENGINE_ID, "--cid-dir", cids]
            drive, linux = (lambda p: "9p"), (lambda p: ("/", "ext4"))
            refusals = [
                ("record path already exists", ["--record", str(existing)], drive, linux),
                ("--docker-host, --engine-id and --cid-dir go together",
                 ["--record", fresh, "--docker-host", "unix:///x"], drive, linux),
                ("C: path '/' is not a Windows drive mount point", ["--record", fresh, "--c-path", "/"],
                 lambda p: "ext4" if p == "/" else "9p", linux),
                ("C: path '/mnt/c' is not a Windows drive mount point", ["--record", fresh], lambda p: None, linux),
                ("C: and E: paths must be different mounts", ["--record", fresh, "--e-path", "/mnt/c"], drive, linux),
                ("record must be on a Linux filesystem", ["--record", fresh], drive, lambda p: ("/mnt/c", "9p")),
                ("CID directory must be on a Linux filesystem", ["--record", fresh] + daemon, drive,
                 lambda p: ("/mnt/e", "9p") if p == cids else ("/", "ext4")),
            ]
            for message, argv, mount_type, containing in refusals:
                with self.subTest(message=message):
                    err = io.StringIO()
                    with self.assertRaises(SystemExit), contextlib.redirect_stderr(err):
                        g.main(["--phase", "p"] + argv + cmd, sampler=lambda p: PLENTY, mount_type=mount_type,
                               containing_mount=containing, docker=FakeDocker())
                    self.assertIn(message, err.getvalue())  # refused by this rule, not an earlier one
            self.assertEqual(existing.read_text(), "{}")
            self.assertFalse(marker.exists())
            self.assertFalse(Path(fresh).exists())

    def test_mount_of_uses_longest_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            mounts = Path(tmp, "mounts")
            mounts.write_text("/dev/sdf / ext4 rw 0 0\nC:\\134 /mnt/c 9p rw 0 0\n")
            self.assertEqual(g.mount_of("/mnt/c/x/y", str(mounts)), ("/mnt/c", "9p"))
            self.assertEqual(g.mount_of("/root/cids", str(mounts)), ("/", "ext4"))
            self.assertEqual(g.mount_of("/mnt/cx", str(mounts)), ("/", "ext4"))
            self.assertEqual(g.drvfs_mount_type("/mnt/c", str(mounts)), "9p")
            self.assertIsNone(g.drvfs_mount_type("/mnt/c/x", str(mounts)))

    def test_oversized_record_is_compacted_not_lost(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp, "big.json")
            many = {f"{i:064x}": {"launch": "x" * 64, "state": "killed; retirement confirmed"} for i in range(5000)}
            result = g.GuardResult("p", TOKEN, breached=True, breach={"volume": "C:", "kind": "below-threshold"},
                                   containers=many,
                                   stop={"cause": "breach", "client_signals": ["SIGTERM"],
                                         "killed_containers": list(many),
                                         "failures": [{"what": "container", "reason": "r"}] * 100})
            g._write_record(record, result.as_record())
            self.assertLessEqual(record.stat().st_size, g.RECORD_LIMIT_BYTES)
            data = json.loads(record.read_text())
            self.assertTrue(data["compacted"])
            self.assertEqual(data["containers"], {"omitted_count": 5000})
            self.assertEqual(data["stop"]["killed_containers"], {"count": 5000})
            self.assertEqual(len(data["stop"]["failures"]), 65)
            self.assertEqual(data["exit_code"], 3)

    def run_driver(self, tmp, signals):
        record, ready, driver = Path(tmp, "guard.json"), Path(tmp, "ready"), Path(tmp, "driver.py")
        driver.write_text(DRIVER.format(scripts=str(ROOT / "scripts")))
        child_code = f"import time; open({str(ready)!r},'w').write('1'); time.sleep(60)"
        proc = subprocess.Popen([sys.executable, str(driver), "--phase", "sig", "--record", str(record),
                                 "--interval", "0.2", "--", sys.executable, "-c", child_code])
        try:
            wait_for(ready)
            for sig in signals:
                proc.send_signal(sig)
                time.sleep(0.05)
            rc = proc.wait(timeout=15)
        finally:
            if proc.poll() is None:
                proc.kill()
        return rc, json.loads(record.read_text())

    def test_signal_while_building_the_record_keeps_the_real_breach(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp, "guard.json")
            original = g.GuardResult.as_record

            def as_record_with_signal(self):
                g._raise_interrupted(signal.SIGTERM, None)  # what the installed handler does now
                return original(self)

            g.GuardResult.as_record = as_record_with_signal
            try:
                rc = g.main(["--phase", "late", "--record", str(record), "--interval", "0.2", "--",
                             sys.executable, "-c", "pass"],
                            sampler=Sampler({"/mnt/c": [PLENTY, LOW_C]}), mount_type=lambda p: "9p")
            finally:
                g.GuardResult.as_record = original
            data = json.loads(record.read_text())
        self.assertEqual(rc, 3)
        self.assertEqual(data["breach"]["kind"], "below-threshold")
        self.assertEqual(data["guard_signals"], ["SIGTERM"])

    def test_guard_signal_handlers_cover_term_hup_and_int_during_the_phase(self):
        sigs = (signal.SIGTERM, signal.SIGHUP, signal.SIGINT)
        before, seen = {s: signal.getsignal(s) for s in sigs}, {}

        def sampler(path):
            seen.setdefault("handlers", {s: signal.getsignal(s) for s in sigs})
            return PLENTY

        with tempfile.TemporaryDirectory() as tmp:
            rc = g.main(["--phase", "h", "--record", str(Path(tmp, "guard.json")), "--interval", "0.2", "--",
                         sys.executable, "-c", "pass"], sampler=sampler, mount_type=lambda p: "9p")
        self.assertEqual(rc, 0)
        self.assertEqual(seen["handlers"], {s: g._raise_interrupted for s in sigs})
        self.assertEqual({s: signal.getsignal(s) for s in sigs}, before)  # restored afterwards

    def test_signal_while_recording_an_internal_error_is_deferred(self):
        original_run, original_as_record = g.ContainmentGuard.run, g.GuardResult.as_record

        def failing_run(self, command, *, env=None):
            raise RuntimeError("injected before launch")

        def as_record_with_signal(self):
            g._raise_interrupted(signal.SIGTERM, None)  # what the installed handler does now
            return original_as_record(self)

        saved = {k: (list(v) if isinstance(v, list) else v) for k, v in g._SIGNALS.items()}
        g.ContainmentGuard.run, g.GuardResult.as_record = failing_run, as_record_with_signal
        try:
            with tempfile.TemporaryDirectory() as tmp:
                record = Path(tmp, "guard.json")
                try:
                    rc = g.main(["--phase", "ie", "--record", str(record), "--interval", "0.2", "--",
                                 sys.executable, "-c", "pass"], sampler=lambda p: PLENTY, mount_type=lambda p: "9p")
                except BaseException as exc:  # noqa: BLE001
                    self.fail(f"signal escaped main while the record was built: {exc!r}")
                data = json.loads(record.read_text())
        finally:
            g.ContainmentGuard.run, g.GuardResult.as_record = original_run, original_as_record
            g._SIGNALS.update(saved)
        self.assertEqual(rc, 3)
        self.assertEqual(data["breach"]["kind"], "internal-error")
        self.assertEqual(data["guard_signals"], ["SIGTERM"])

    def test_record_write_failure_emits_the_record_on_stderr(self):
        import errno

        with tempfile.TemporaryDirectory() as tmp:
            record = Path(tmp, "guard.json")
            original = g.os.fsync

            def enospc(fd):
                raise OSError(errno.ENOSPC, "No space left on device")

            g.os.fsync = enospc
            try:
                with CaptureFd2() as err:
                    rc = g.main(["--phase", "full", "--record", str(record), "--interval", "0.2", "--",
                                 sys.executable, "-c", "pass"],
                                sampler=Sampler({"/mnt/c": [PLENTY, LOW_C]}), mount_type=lambda p: "9p")
            finally:
                g.os.fsync = original
        self.assertEqual(rc, 4)
        text = err.text
        self.assertIn("record write failed (OSError: [Errno 28]", text)
        self.assertEqual(json.loads(text[text.index("{"):])["breach"]["kind"], "below-threshold")

    def test_record_write_failure_survives_a_failing_stderr(self):
        # fd 2 itself fails (a pipe whose reader is gone: EPIPE) while the record write fails too
        import errno

        attempted = {"n": 0}
        real_write = g.os.write

        def counting_write(fd, data):
            if fd == 2:
                attempted["n"] += 1
            return real_write(fd, data)

        r, w = os.pipe()
        os.close(r)  # no reader: every write to fd 2 raises BrokenPipeError
        saved = os.dup(2)
        os.dup2(w, 2)
        os.close(w)
        original_fsync = g.os.fsync

        def enospc(fd):
            raise OSError(errno.ENOSPC, "No space left on device")

        g.os.fsync, g.os.write = enospc, counting_write
        try:
            with tempfile.TemporaryDirectory() as tmp:
                rc = g.main(["--phase", "full", "--record", str(Path(tmp, "r.json")), "--interval", "0.2", "--",
                             sys.executable, "-c", "pass"],
                            sampler=Sampler({"/mnt/c": [PLENTY, LOW_C]}), mount_type=lambda p: "9p")
        finally:
            g.os.fsync, g.os.write = original_fsync, real_write
            os.dup2(saved, 2)
            os.close(saved)
        self.assertEqual(rc, 4)
        self.assertGreaterEqual(attempted["n"], 1)  # the fallback really hit the failing fd

    def test_removed_record_directory_is_rc_4_not_a_silent_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp, "records")
            records.mkdir()
            remove = f"import os; os.rmdir({str(records)!r})"
            with CaptureFd2() as err:
                rc = g.main(["--phase", "rm", "--record", str(Path(records, "guard.json")), "--interval", "0.2",
                             "--", sys.executable, "-c", remove], sampler=lambda p: PLENTY, mount_type=lambda p: "9p")
        self.assertEqual(rc, 4)
        self.assertIn("FileNotFoundError", err.text)
        self.assertEqual(json.loads(err.text[err.text.index("{"):])["phase"], "rm")

    def test_directory_removed_after_create_is_caught_for_a_relative_record_path(self):
        cwd, real_fsync = os.getcwd(), os.fsync
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp, "d")
            d.mkdir()
            dir_fd = os.open(d, os.O_RDONLY | os.O_DIRECTORY)
            calls = {"n": 0}

            def remove_then_fsync(fd):
                calls["n"] += 1
                if calls["n"] == 1:  # the record file: unlink it and remove its directory
                    os.unlink(d / "guard.json")
                    os.rmdir(d)
                return real_fsync(fd)

            os.chdir(d)  # "." now names the pinned directory, so a path check alone cannot see the removal
            os.fsync = remove_then_fsync
            try:
                with CaptureFd2() as err, self.assertRaises(g.RecordWriteFailed):
                    g._write_record(Path("guard.json"), {"phase": "rel"}, dir_fd)
            finally:
                os.fsync = real_fsync
                os.chdir(cwd)
                os.close(dir_fd)
        self.assertIn("record directory was removed during the phase", err.text)

    def test_dangling_symlink_record_path_is_refused_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            link, marker = Path(tmp, "r.json"), Path(tmp, "ran")
            os.symlink(str(Path(tmp, "missing-target")), str(link))
            with self.assertRaises(SystemExit):
                g.main(["--phase", "p", "--record", str(link), "--", sys.executable, "-c",
                        f"open({str(marker)!r},'w').write('x')"],
                       sampler=lambda p: PLENTY, mount_type=lambda p: "9p")
            self.assertFalse(marker.exists())

    def test_full_stderr_pipe_cannot_withhold_rc_4_or_abort_shutdown(self):
        # A real pipe that nobody drains, already filled by the phase: the guard must
        # still exit with rc 4 (not hang, not abort at interpreter shutdown).
        driver = textwrap.dedent(f"""
            import errno, os, sys
            sys.path.insert(0, {str(ROOT / 'scripts')!r})
            import accepted_policy_containment_guard_v1 as g
            def enospc(fd):
                raise OSError(errno.ENOSPC, "No space left on device")
            g.os.fsync = enospc
            calls = {{"n": 0}}
            def sampler(path):
                calls["n"] += 1
                return 500 * g.GIB if calls["n"] <= 6 else g.C_BREACH_BELOW - 1
            sys.exit(g.main(sys.argv[1:], sampler=sampler, mount_type=lambda p: "9p"))
            """)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "driver.py")
            path.write_text(driver)
            filler = "import sys, time; sys.stderr.write('x' * 200000); sys.stderr.flush(); time.sleep(60)"
            proc = subprocess.Popen([sys.executable, str(path), "--phase", "full", "--record", str(Path(tmp, "r.json")),
                                     "--interval", "0.2", "--", sys.executable, "-c", filler],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                rc = proc.wait(timeout=30)  # stderr is never read while it runs
            finally:
                if proc.poll() is None:
                    proc.kill()
                proc.stderr.close()
        self.assertEqual(rc, 4)

    def test_large_record_on_stderr_keeps_breach_and_failures(self):
        import errno

        cids = [f"{i:064x}" for i in range(1024)]
        many = {cid: {"launch": "w" * 60, "state": "killed; retirement confirmed"} for cid in cids}
        result = g.GuardResult("p", TOKEN, breached=True, breach={"volume": "C:", "kind": "below-threshold"},
                               containers=many,
                               stop={"cause": "breach", "client_signals": ["SIGTERM"], "killed_containers": cids,
                                     "live_found": cids,
                                     "failures": [{"what": "container", "cid": "f" * 64, "reason": "unproved"}]})
        clean = g.GuardResult("p", TOKEN, breached=True, breach={"volume": "C:", "kind": "below-threshold"},
                              containers=many,
                              stop={"cause": "breach", "client_signals": ["SIGTERM"], "killed_containers": cids,
                                    "live_found": cids, "failures": []})
        for case, res in (("one failure", result), ("no failures", clean)):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                original = g.os.fsync

                def enospc(fd):
                    raise OSError(errno.ENOSPC, "No space left on device")

                g.os.fsync = enospc
                try:
                    with CaptureFd2() as err, self.assertRaises(g.RecordWriteFailed):
                        g._write_record(Path(tmp, "r.json"), res.as_record())
                finally:
                    g.os.fsync = original
                text = err.text
                body = text[text.index("{"):]
                summary = json.loads(body)  # one complete, parseable document
                self.assertLessEqual(len(body.encode()), g.STDERR_RECORD_LIMIT)
                self.assertTrue(summary["truncated_for_stderr"])
                self.assertEqual(summary["breach"]["kind"], "below-threshold")
                self.assertEqual((summary["killed_count"], summary["live_found_count"]), (1024, 1024))
                self.assertEqual(summary["containers_count"], 1024)
                self.assertEqual(summary["failures_count"], len(res.stop["failures"]))
                if res.stop["failures"]:
                    self.assertEqual(summary["failures"][0]["reason"], "unproved")

    def test_record_goes_to_the_directory_checked_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            records, elsewhere = Path(tmp, "records"), Path(tmp, "elsewhere")
            records.mkdir()
            elsewhere.mkdir()
            moved = Path(tmp, "records.moved")
            # the phase swaps the record directory for a symlink to another place
            swap = (f"import os; os.rename({str(records)!r}, {str(moved)!r}); "
                    f"os.symlink({str(elsewhere)!r}, {str(records)!r})")
            with CaptureFd2() as err:
                rc = g.main(["--phase", "swap", "--record", str(Path(records, "guard.json")), "--interval", "0.2",
                             "--", sys.executable, "-c", swap], sampler=lambda p: PLENTY, mount_type=lambda p: "9p")
            self.assertEqual(rc, 4)  # the record is not at its path: the caller must not miss that
            self.assertIn("moved during the phase", err.text)
            self.assertTrue(Path(moved, "guard.json").is_file())  # written into the pinned directory
            self.assertFalse(Path(elsewhere, "guard.json").exists())  # never redirected

    def test_hung_record_path_check_is_rc_4_not_a_hang(self):
        with tempfile.TemporaryDirectory() as tmp:
            records = Path(tmp, "records")
            records.mkdir()
            gate, armed = threading.Event(), threading.Event()
            real_stat = g.os.stat

            def stat(path, *a, **k):
                if armed.is_set() and str(path) == str(records):
                    gate.wait(30)  # e.g. the path now resolves onto a wedged drvfs mount
                return real_stat(path, *a, **k)

            def sampler(path):
                armed.set()  # first sample: all pre-launch path checks are done
                return PLENTY

            g.os.stat = stat
            try:
                start = time.monotonic()
                with CaptureFd2() as err:
                    rc = g.main(["--phase", "p", "--record", str(Path(records, "guard.json")), "--interval", "0.2",
                                 "--", sys.executable, "-c", "pass"], sampler=sampler,
                                mount_type=lambda p: "9p")
                elapsed = time.monotonic() - start
            finally:
                g.os.stat = real_stat
                gate.set()
        self.assertEqual(rc, 4)
        self.assertLess(elapsed, 15)
        self.assertIn("moved during the phase", err.text)

    def test_stderr_summary_always_terminates_within_its_bound(self):
        record = {"schema": "s", "phase": "p", "breached": True, "exit_code": 3,
                  "breach": {"kind": "x", "reason": "r" * 200_000}, "stop": {"cause": "breach", "failures": [
                      {"what": "container", "reason": "y" * 100_000}]}}
        data = g._stderr_summary(record)
        self.assertLessEqual(len(data), g.STDERR_RECORD_LIMIT)
        summary = json.loads(data)
        self.assertTrue(summary["truncated_for_stderr"])
        self.assertEqual((summary["exit_code"], summary["failures_count"]), (3, 1))
        record["stop"]["failures"] = [{"what": "container", "reason": "y" * 100_000}] * 5
        self.assertEqual(json.loads(g._stderr_summary(record))["failures_count"], 5)  # true count, not trimmed

    def test_record_on_a_windows_drive_mount_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit):
                g.main(["--phase", "p", "--record", str(Path(tmp, "r.json")), "--", "true"],
                       sampler=lambda p: PLENTY, mount_type=lambda p: "9p",
                       containing_mount=lambda p: ("/mnt/c", "9p"))
            self.assertFalse(Path(tmp, "r.json").exists())

    def test_repeated_guard_signals_still_write_one_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            rc, data = self.run_driver(tmp, [signal.SIGINT, signal.SIGHUP, signal.SIGTERM, signal.SIGINT])
        self.assertEqual(rc, 3)
        self.assertEqual(data["breach"]["kind"], "interrupted")
        self.assertIsNotNone(data["child_returncode"])

    def test_sigterm_to_guard_stops_phase_and_writes_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            record, ready, driver = Path(tmp, "guard.json"), Path(tmp, "ready"), Path(tmp, "driver.py")
            driver.write_text(DRIVER.format(scripts=str(ROOT / "scripts")))
            child_code = f"import time; open({str(ready)!r},'w').write('1'); time.sleep(60)"
            proc = subprocess.Popen([sys.executable, str(driver), "--phase", "sig", "--record", str(record),
                                     "--interval", "0.2", "--", sys.executable, "-c", child_code])
            try:
                wait_for(ready)
                proc.send_signal(signal.SIGTERM)
                rc = proc.wait(timeout=15)
            finally:
                if proc.poll() is None:
                    proc.kill()
            self.assertEqual(rc, 3)
            data = json.loads(record.read_text())
            self.assertEqual(data["breach"], {"volume": None, "kind": "interrupted", "reason": "GuardInterrupted"})
            self.assertEqual(data["stop"]["cause"], "interrupted")
            self.assertEqual(data["stop"]["client_signals"][0], "SIGTERM")
            self.assertIsNotNone(data["child_returncode"])


if __name__ == "__main__":
    unittest.main()
