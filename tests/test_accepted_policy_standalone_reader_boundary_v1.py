"""Decision16 standalone-reader capture boundary with controlled real children.

Controlled programs replace only the reader child; the public reader keeps its
fixed default program and proof predicates. Linux owned-closure cases run in
hosted CI; other platforms have no owned-closure method to exercise.
"""
import ast
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader

LINUX = sys.platform.startswith("linux")
MIB = 1048576


def deadline(*, observe=20.0, term=1.0, kill=1.0, final=2.0):
    now = time.monotonic_ns()
    total = int((observe + term + kill + final) * 1e9)
    return {"absolute_monotonic_ns": now + total, "term_grace_ns": int(term * 1e9),
            "kill_grace_ns": int(kill * 1e9), "final_ns": int(final * 1e9)}


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    try:
        with open(f"/proc/{pid}/stat", "rb") as stream:
            return stream.read().rsplit(b")", 1)[1].split()[0] != b"Z"
    except FileNotFoundError:
        return False


class DeadlineRefusalTests(unittest.TestCase):
    def outputs(self, tmp):
        base = Path(tmp)
        return {"stdout": base / "out.raw", "stderr": base / "err.raw", "result": base / "result.json"}

    def test_missing_or_malformed_deadline_refuses_before_spawn(self):
        bad = [None, {}, {**deadline(), "extra": 1}, {**deadline(), "term_grace_ns": True},
               {**deadline(), "kill_grace_ns": 0}, {**deadline(), "final_ns": -1},
               deadline(observe=-1.0)]
        for value in bad:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                outputs = self.outputs(tmp)
                with mock.patch.object(reader.subprocess, "Popen") as popen:
                    with self.assertRaisesRegex(ValueError, "standalone reader deadline"):
                        reader._capture_owned_reader_v2(command=[sys.executable, "-c", "pass"],
                            cwd=Path(tmp), outputs=outputs, deadline=value)
                popen.assert_not_called()
                self.assertFalse(any(path.exists() for path in outputs.values()))

    def test_consumer_passes_one_recipe_deadline_without_default(self):
        # Parsed, not imported: the consumer's runtime imports are Linux/pandas-only.
        tree = ast.parse((ROOT / "tests/fixtures/accepted_policy_consumer_fixture_v2.py").read_text(encoding="utf-8"))
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                        and node.name == "complete_fixture_production_consumers_v2")
        names = [arg.arg for arg in function.args.kwonlyargs]
        default = function.args.kw_defaults[names.index("standalone_reader_deadline")]
        self.assertIsInstance(default, ast.Constant)
        self.assertIsNone(default.value)
        calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)
                 and getattr(node.func, "id", None) == "run_fixture_standalone_guardian_cold_reader_v2"]
        self.assertEqual(len(calls), 1)
        passed = {keyword.arg: keyword.value for keyword in calls[0].keywords}
        self.assertEqual(getattr(passed.get("deadline"), "id", None), "standalone_reader_deadline")

    def test_public_reader_requires_deadline_before_any_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            guardian = {"contract_path": Path(tmp) / "c.json", "receipt_path": Path(tmp) / "r.json",
                        "preprocessing_contract_sha256": "0" * 64}
            with mock.patch.object(reader.subprocess, "Popen") as popen:
                with self.assertRaisesRegex(ValueError, "standalone reader deadline"):
                    reader.run_fixture_standalone_guardian_cold_reader_v2(project_root=ROOT,
                        output_dir=Path(tmp), guardian=guardian, accepted_capability_path=Path(tmp) / "a.json")
            popen.assert_not_called()
            self.assertEqual(list(Path(tmp).iterdir()), [])


class ResultBoundTests(unittest.TestCase):
    def test_encoding_stops_before_crossing_result_ceiling(self):
        small = {"proof": {"k": "v"}, "causes": []}
        raw = reader._bounded_json_v2(small, 64)
        self.assertEqual(raw, json.dumps(small, sort_keys=True, separators=(",", ":")).encode("ascii"))
        self.assertIsNone(reader._bounded_json_v2({"proof": "x" * 100}, 64))

    def test_non_ascii_proof_expansion_yields_bounded_incomplete_failure(self):
        # 700,000 four-byte characters re-encode as 12 ASCII bytes each.
        evidence = {"proof": {"text": "\U0001F600" * 700_000}, "command": ["python"], "causes": [],
                    "standalone_guardian_cold_reader_passed": True, "error": None}
        raw, complete = reader._result_bytes_v2(evidence)
        self.assertFalse(complete)
        self.assertLessEqual(len(raw), reader.RESULT_LIMIT)
        record = json.loads(raw)
        self.assertTrue(record["incomplete"])
        self.assertFalse(record["standalone_guardian_cold_reader_passed"])
        self.assertIn("proof", record["omitted"])
        self.assertIn("reader_result_bound", record["causes"])

    def test_complete_result_keeps_every_proof_field(self):
        evidence = {"proof": {"a": 1, "loaded_production_sources": ["x"]}, "causes": [],
                    "standalone_guardian_cold_reader_passed": True, "error": None}
        raw, complete = reader._result_bytes_v2(evidence)
        self.assertTrue(complete)
        self.assertEqual(json.loads(raw), evidence)
        self.assertTrue(raw.endswith(b"\n"))


class _OwnedChildBase(unittest.TestCase):
    """Shared controlled-child setup; it defines no tests itself."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.outputs = {"stdout": self.base / "out.raw", "stderr": self.base / "err.raw",
                        "result": self.base / "result.json"}
        self.leaked = []
        self.addCleanup(self.reap_leaked)

    def reap_leaked(self):
        for pid in self.leaked:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def capture(self, program, **limits):
        return reader._capture_owned_reader_v2(command=[sys.executable, "-B", "-c", program],
            cwd=self.base, outputs=self.outputs, deadline=deadline(**limits))


@unittest.skipUnless(LINUX, "owned subreaper/pidfd closure exists only on Linux")
class OwnedCaptureTests(_OwnedChildBase):
    def test_normal_child_closes_with_exact_bytes_status_and_eof(self):
        facts, out, err = self.capture("import sys; sys.stdout.write('{\"ok\":true}'); sys.stderr.write('note')")
        self.assertEqual(facts["causes"], [])
        self.assertEqual((out, err), (b'{"ok":true}', b"note"))
        self.assertEqual(facts["returncode"], 0)
        self.assertIsNone(facts["signal"])
        self.assertFalse(facts["term_sent"] or facts["kill_sent"])
        self.assertTrue(facts["closure"]["closed"])
        for channel, data in (("stdout", out), ("stderr", err)):
            row = facts[channel]
            self.assertTrue(row["eof"])
            self.assertEqual((row["observed_bytes"], row["retained_bytes"], row["discarded_bytes"]),
                             (len(data), len(data), 0))
            self.assertFalse(row["remainder_unknown"])
            self.assertEqual(self.outputs[channel].read_bytes(), data)
            self.assertEqual(row["file"]["sha256"], hashlib.sha256(data).hexdigest())
            self.assertTrue(row["file"]["fsync_completed"] and row["file"]["close_completed"])
        self.assertIsInstance(facts["pid"], int)
        self.assertIsInstance(facts["start_ticks"], int)

    def test_exact_ceiling_is_accepted(self):
        facts, out, _ = self.capture(f"import sys; sys.stdout.buffer.write(b'x' * {MIB})")
        self.assertEqual(facts["causes"], [])
        self.assertEqual(len(out), MIB)
        self.assertEqual(self.outputs["stdout"].stat().st_size, MIB)

    def test_stdout_overflow_keeps_prefix_and_closes_owned_child(self):
        program = ("import sys, time; sys.stdout.buffer.write(b'y' * %d); sys.stdout.flush(); time.sleep(60)" % (MIB + 10))
        facts, out, _ = self.capture(program)
        self.assertEqual(facts["causes"][0], "reader_stdout_overflow")
        self.assertEqual(len(out), MIB)
        self.assertEqual(self.outputs["stdout"].read_bytes(), b"y" * MIB)
        row = facts["stdout"]
        self.assertEqual(row["retained_bytes"], MIB)
        self.assertGreater(row["observed_bytes"], MIB)
        self.assertEqual(row["discarded_bytes"], row["observed_bytes"] - MIB)
        self.assertTrue(facts["term_sent"])
        self.assertEqual(facts["signal"], signal.SIGTERM)
        self.assertTrue(facts["closure"]["closed"])

    def test_stderr_overflow_is_failure_with_exact_prefix(self):
        facts, _, err = self.capture("import sys; sys.stderr.buffer.write(b'e' * %d)" % (MIB + 1))
        self.assertIn("reader_stderr_overflow", facts["causes"])
        self.assertEqual(err, b"e" * MIB)
        self.assertEqual(self.outputs["stderr"].stat().st_size, MIB)

    def test_inherited_deadline_terminates_and_keeps_bytes_observed_before_it(self):
        facts, out, _ = self.capture("import sys, time; sys.stdout.write('abc'); sys.stdout.flush(); time.sleep(60)",
                                     observe=0.8, term=1.0, kill=1.0, final=1.0)
        self.assertEqual(facts["causes"][0], "reader_deadline")
        self.assertEqual(out, b"abc")
        self.assertEqual(self.outputs["stdout"].read_bytes(), b"abc")
        self.assertTrue(facts["term_sent"])
        self.assertFalse(facts["kill_sent"])
        self.assertEqual(facts["signal"], signal.SIGTERM)

    def test_ignored_term_is_followed_by_one_kill(self):
        program = "import signal, sys, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print('r', flush=True); time.sleep(60)"
        facts, _, _ = self.capture(program, observe=0.8, term=0.5, kill=1.0, final=1.0)
        self.assertEqual(facts["causes"][0], "reader_deadline")
        self.assertTrue(facts["term_sent"] and facts["kill_sent"])
        self.assertEqual(facts["signal"], signal.SIGKILL)
        self.assertTrue(facts["closure"]["closed"])

    def test_nonzero_and_self_signal_statuses_stay_original(self):
        facts, _, _ = self.capture("import sys; sys.exit(3)")
        self.assertEqual((facts["returncode"], facts["signal"]), (3, None))
        self.assertFalse(facts["term_sent"])
        facts2, _, _ = reader._capture_owned_reader_v2(
            command=[sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"],
            cwd=self.base, outputs={k: self.base / ("2" + v.name) for k, v in self.outputs.items()},
            deadline=deadline())
        self.assertEqual(facts2["signal"], signal.SIGKILL)
        self.assertFalse(facts2["term_sent"] or facts2["kill_sent"])

    def test_descendant_holding_pipe_is_owned_and_closed(self):
        marker = self.base / "grandchild.pid"
        program = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
                   "open(%r, 'w').write(str(p.pid))" % str(marker))
        facts, _, _ = self.capture(program, observe=2.0, term=1.0, kill=1.0, final=1.0)
        grandchild = int(marker.read_text())
        self.leaked.append(grandchild)
        self.assertIn(facts["causes"][0], ("reader_descendant_live", "reader_deadline"))
        self.assertTrue(facts["term_sent"])
        self.assertFalse(alive(grandchild))
        self.assertIn(grandchild, [row["pid"] for row in facts["closure"]["owned_descendants"]])
        self.assertTrue(facts["closure"]["closed"])

    def test_escaped_session_descendant_without_pipes_is_found_and_closed(self):
        marker = self.base / "escaped.pid"
        program = ("import subprocess, sys; p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
                   "start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL); "
                   "open(%r, 'w').write(str(p.pid))" % str(marker))
        facts, _, _ = self.capture(program, observe=3.0, term=1.0, kill=1.0, final=1.0)
        escaped = int(marker.read_text())
        self.leaked.append(escaped)
        self.assertEqual(facts["returncode"], 0)
        self.assertIn("reader_descendant_live", facts["causes"])
        self.assertFalse(alive(escaped))
        self.assertTrue(facts["closure"]["closed"])

    def test_preexisting_child_refuses_before_spawn(self):
        sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        self.addCleanup(sleeper.wait)
        self.addCleanup(sleeper.kill)
        with self.assertRaisesRegex(ValueError, "standalone reader owned closure"):
            self.capture("pass")
        self.assertFalse(any(path.exists() for path in self.outputs.values()))

    def test_raw_write_failure_is_unknown_extent_not_a_fabricated_count(self):
        original = reader._os_write
        def failing(fd, data):
            if os.readlink(f"/proc/self/fd/{fd}").endswith("out.raw"):
                raise OSError("synthetic raw write failure")
            return original(fd, data)
        with mock.patch.object(reader, "_os_write", failing):
            facts, out, _ = self.capture("print('data')")
        self.assertIn("reader_stdout_raw_write", facts["causes"])
        row = facts["stdout"]["file"]
        self.assertTrue(row["write_extent_unknown"])
        self.assertIsNone(row["sha256"])
        self.assertEqual(out, b"data\n")

    def test_short_raw_write_counts_confirmed_prefix_only(self):
        original = reader._os_write
        def short(fd, data):
            if os.readlink(f"/proc/self/fd/{fd}").endswith("out.raw"):
                return original(fd, data[:2])
            return original(fd, data)
        with mock.patch.object(reader, "_os_write", short):
            facts, _, _ = self.capture("import sys; sys.stdout.write('abcdef')")
        self.assertIn("reader_stdout_raw_short_write", facts["causes"])
        row = facts["stdout"]["file"]
        self.assertEqual((row["written_bytes"], row["sha256"]), (2, hashlib.sha256(b"ab").hexdigest()))
        self.assertEqual(self.outputs["stdout"].read_bytes(), b"ab")


@unittest.skipUnless(LINUX, "owned subreaper/pidfd closure exists only on Linux")
class ClosureHazardTests(_OwnedChildBase):
    """Independent-review hazards: races, internal errors, identity loss, drains."""

    def subreaper(self):
        import ctypes
        value = ctypes.c_int()
        ctypes.CDLL(None).prctl(37, ctypes.byref(value), 0, 0, 0)
        return value.value

    def fds(self):
        return set(os.listdir("/proc/self/fd"))

    def test_fork_chain_never_claims_closure_with_a_live_descendant(self):
        marker = self.base / "last.pid"
        program = ("import os, time\nfd = os.open('/dev/null', os.O_RDWR)\nif os.fork() == 0:\n"
                   "    os.dup2(fd, 1); os.dup2(fd, 2)\n    for _ in range(300):\n"
                   "        if os.fork() != 0:\n            os._exit(0)\n"
                   "    open(%r, 'w').write(str(os.getpid()))\n    time.sleep(30)\n    os._exit(0)\n" % str(marker))
        for attempt in range(5):
            with self.subTest(attempt=attempt):
                if marker.exists():
                    marker.unlink()
                self.outputs = {k: self.base / f"{attempt}-{v.name}" for k, v in self.outputs.items()}
                facts, _, _ = self.capture(program, observe=3.0)
                time.sleep(0.2)
                last = int(marker.read_text()) if marker.exists() else None
                if last is not None:
                    self.leaked.append(last)
                self.assertNotEqual(facts["causes"], [])
                if facts["closure"]["closed"]:
                    self.assertFalse(last is not None and alive(last))

    def test_internal_error_after_spawn_kills_reader_and_releases_everything(self):
        before = self.fds()
        original = reader._children_v2
        calls = []
        def failing(pid):
            calls.append(pid)
            if len(calls) > 3:
                raise RuntimeError("synthetic inventory failure")
            return original(pid)
        with mock.patch.object(reader, "_children_v2", failing):
            facts, _, _ = self.capture("import time; time.sleep(60)")
        self.assertIn("reader_internal_RuntimeError", facts["causes"])
        self.assertFalse(alive(facts["pid"]))
        self.assertFalse(facts["closure"]["closed"])
        self.assertEqual(self.fds(), before)
        self.assertEqual(self.subreaper(), 0)

    def test_internal_error_during_term_kills_the_whole_owned_chain(self):
        marker = self.base / "chain.pids"
        program = ("import os, time\nif os.fork() == 0:\n    b = os.fork()\n    if b == 0:\n        time.sleep(60)\n"
                   "        os._exit(0)\n    open(%r, 'w').write('%%d %%d' %% (os.getpid(), b))\n    time.sleep(60)\n"
                   "    os._exit(0)\ntime.sleep(60)\n" % str(marker))
        def broken(*args):
            raise RuntimeError("synthetic signal failure")
        with mock.patch.object(reader.signal, "pidfd_send_signal", broken):
            facts, _, _ = self.capture(program, observe=1.0, term=1.0, kill=1.0, final=2.0)
        chain = [int(pid) for pid in marker.read_text().split()]
        self.leaked.extend(chain)
        self.assertIn("reader_internal_RuntimeError", facts["causes"])
        self.assertFalse(facts["closure"]["closed"])
        self.assertFalse(alive(facts["pid"]))
        for pid in chain:
            self.assertFalse(alive(pid), pid)
        self.assertEqual(self.subreaper(), 0)

    def test_interrupt_after_spawn_is_contained_then_reraised(self):
        spawned = []
        original = reader._start_ticks_v2
        def interrupted(pid):
            spawned.append(pid)
            raise KeyboardInterrupt
        with mock.patch.object(reader, "_start_ticks_v2", interrupted):
            with self.assertRaises(KeyboardInterrupt):
                self.capture("import time; time.sleep(60)")
        self.assertTrue(spawned)
        self.assertFalse(alive(spawned[0]))
        self.assertEqual(self.subreaper(), 0)

    def test_identity_failure_still_signals_the_retained_reader(self):
        original = os.pidfd_open
        def no_reader_pidfd(pid, *args):
            if not getattr(no_reader_pidfd, "used", False):
                no_reader_pidfd.used = True
                raise OSError("synthetic pidfd failure")
            return original(pid, *args)
        with mock.patch.object(reader.os, "pidfd_open", no_reader_pidfd):
            facts, _, _ = self.capture("import time; time.sleep(60)", observe=0.5, term=1.0, kill=1.0, final=1.0)
        self.assertEqual(facts["causes"][:2], ["reader_identity", "reader_deadline"])
        self.assertGreaterEqual(facts["term_delivered"], 1)
        self.assertFalse(alive(facts["pid"]))
        self.assertEqual(facts["signal"], signal.SIGTERM)

    def test_flood_after_reader_exit_ends_observation_without_draining_window(self):
        program = ("import os, sys\nif os.fork() == 0:\n    block = b'z' * 65536\n    while True:\n"
                   "        os.write(1, block)\nos._exit(0)\n")
        started = time.monotonic()
        facts, out, _ = self.capture(program, observe=30.0, term=1.0, kill=1.0, final=1.0)
        self.assertLess(time.monotonic() - started, 10.0)
        self.assertIn("reader_stdout_overflow", facts["causes"])
        self.assertEqual(len(out), MIB)
        self.assertTrue(facts["closure"]["closed"])

    def test_raw_failure_still_reports_retained_prefix_hash(self):
        original = reader._os_write
        def failing(fd, data):
            if os.readlink(f"/proc/self/fd/{fd}").endswith("out.raw"):
                raise OSError("synthetic raw write failure")
            return original(fd, data)
        with mock.patch.object(reader, "_os_write", failing):
            facts, out, _ = self.capture("print('data')")
        self.assertEqual(facts["stdout"]["retained_sha256"], hashlib.sha256(out).hexdigest())


class ResultPersistenceDeadlineTests(unittest.TestCase):
    def test_result_completed_after_the_absolute_deadline_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            clock = iter([10, 10_000])
            with mock.patch.object(reader, "_monotonic_ns", lambda: next(clock)):
                persistence = reader._write_result_v2(Path(tmp) / "result.json", b"{}\n", 1_000)
            self.assertTrue(persistence["close_completed"])
            self.assertIn("result_deadline_exceeded", persistence["causes"])


@unittest.skipUnless(LINUX, "owned subreaper/pidfd closure exists only on Linux")
class PublicReaderTests(unittest.TestCase):
    def test_actual_default_reader_refusal_keeps_bounded_original_evidence(self):
        with tempfile.TemporaryDirectory(prefix="accepted-policy-standalone-bounded-") as raw:
            output = Path(raw)
            guardian = {"contract_path": ROOT / "artifacts" / output.name / "missing-contract.json",
                        "receipt_path": ROOT / "artifacts" / output.name / "missing-receipt.json",
                        "preprocessing_contract_sha256": "0" * 64}
            with self.assertRaisesRegex(ValueError, "fresh standalone default guardian reader refused") as caught:
                reader.run_fixture_standalone_guardian_cold_reader_v2(project_root=ROOT, output_dir=output,
                    guardian=guardian, accepted_capability_path=ROOT / "artifacts" / output.name / "missing.json",
                    deadline=deadline(observe=60.0))
            result = json.loads((output / "standalone-guardian-cold-reader.result.v2.json").read_bytes())
            self.assertFalse(result["standalone_guardian_cold_reader_passed"])
            self.assertNotEqual(result["original_exit_code"], 0)
            self.assertEqual(result["command"][3], reader._PROGRAM)
            self.assertTrue(result["capture"]["closure"]["closed"])
            self.assertNotIn("result_persistence", result)
            persistence = caught.exception.evidence["result_persistence"]
            self.assertTrue(persistence["fsync_completed"] and persistence["close_completed"])
            self.assertLessEqual((output / "standalone-guardian-cold-reader.result.v2.json").stat().st_size,
                                 reader.RESULT_LIMIT)

    def test_success_shaped_proof_after_forced_closure_cannot_pass(self):
        facts = {"causes": ["reader_deadline"], "returncode": -15, "signal": 15, "term_sent": True,
                 "kill_sent": False, "closure": {"closed": True}}
        proof = {"standalone_guardian_cold_reader_passed": True}
        self.assertEqual(reader._reader_error_v2(facts, json.dumps(proof).encode(), "x", "y", "z")[0],
                         "fresh standalone default guardian reader capture refused: reader_deadline")


if __name__ == "__main__":
    unittest.main(verbosity=2)
