"""Fixed literal-source capture policy; process/filesystem effects are doubled."""
from contextlib import ExitStack, contextmanager
import hashlib
import importlib
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01"
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(DIRECTORY))
import build_production_fixture_v2 as positive
import build_per_cell_minimum_refusal_v1 as negative
from publication_physical_io_v1 import PhysicalRootCustodyV1
from tests.fixtures import accepted_policy_standalone_reader_fixture_v2 as reader

NOW = 1_000_000_000
DEADLINE = {"absolute_monotonic_ns": NOW + 200_000_000_000,
    "term_grace_ns": 5_000_000_000, "kill_grace_ns": 5_000_000_000,
    "final_ns": 5_000_000_000}
OBSERVE_END = DEADLINE["absolute_monotonic_ns"] - 15_000_000_000
CAPTURE, OUTPUT = ROOT / "controlled-source-capture", ROOT / "controlled-output"
POSITIVE = ("head", "status", "guardian")
NEGATIVE = ("before-head", "before-status", "before-proof", "after-proof", "after-head", "after-status")


def persistence(count):
    return {"attempted": True, "written_bytes": count, "write_extent_unknown": False,
        "fsync_completed": True, "close_completed": True, "causes": []}


class LiteralSourceCaptureTests(unittest.TestCase):
    def module(self):
        name = "tests.fixtures.accepted_policy_literal_source_capture_v2"
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError as error:
            if error.name != name:
                raise
            self.fail("the fixed bounded literal-source capture is absent")

    @contextmanager
    def controlled(self, *, negative=False, directory=CAPTURE, output=OUTPUT,
                   occupied=False, stdout=None, fault=None, write_fault=None, return_time=None,
                   deadline=DEADLINE, parent_error=None, clock_error=None, write_error=None):
        module = self.module()
        self.files, self.records, self.time = {}, [], NOW
        self.last_capture, self.last_persistence = None, None
        self.returned = False
        if occupied:
            self.files[CAPTURE / "foreign"] = b"x"

        @contextmanager
        def scandir(path):
            self.assertEqual(Path(path), CAPTURE)
            yield iter(SimpleNamespace(name=path.name) for path in self.files if path.parent == CAPTURE)

        def read(path, **kwargs):
            raw = self.files[Path(path)]
            if len(raw) > kwargs["maximum"]:
                raise ValueError("controlled read ceiling")
            return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, None

        def capture(*, command, cwd, outputs, deadline):
            self.assertEqual(cwd, ROOT)
            self.assertEqual(deadline, DEADLINE)
            name = Path(outputs["stdout"]).name
            if "proof" in name:
                raw = json.dumps({"raw_committed_bytes_verified": True, "tracked_path_count": 14147,
                    "verifier_path": str(ROOT / "scripts/run_ci_checks.py")}, sort_keys=True).encode() + b"\n"
            elif "head" in name:
                raw = b"a" * 40 + b"\n"
            elif "guardian" in name:
                raw = b"controlled original guardian\n"
            else:
                raw = b""
            if type(stdout) is dict:
                for slot, payload in stdout.items():
                    if name.startswith(slot + "."):
                        raw = payload
            elif stdout is not None:
                raw = stdout
            facts = {"causes": [], "returncode": 0, "signal": None, "forced": False,
                "closure": {"closed": True, "descendants_unknown": False,
                    "owned_descendants": [], "subreaper_restored": True}}
            for channel, payload in (("stdout", raw), ("stderr", b"")):
                path = Path(outputs[channel])
                self.files[path] = payload
                digest = hashlib.sha256(payload).hexdigest()
                facts[channel] = {"eof": True, "overflow": False, "remainder_unknown": False,
                    "observed_bytes": len(payload), "retained_bytes": len(payload), "discarded_bytes": 0,
                    "retained_sha256": digest, "file": {"path": str(path), "written_bytes": len(payload),
                        "write_extent_unknown": False, "fsync_completed": True, "close_completed": True,
                        "sha256": digest}}
            if fault is not None:
                fault(facts)
            self.last_capture = facts
            self.last_capture_snapshot = json.loads(json.dumps(facts))
            if return_time is not None:
                self.time = return_time
            self.returned = True
            return facts, raw, b""

        def write(path, raw, absolute):
            self.assertEqual(absolute, DEADLINE["absolute_monotonic_ns"])
            if write_error is not None:
                raise write_error
            self.files[Path(path)] = raw
            self.records.append(json.loads(raw))
            facts = persistence(len(raw))
            if write_fault is not None:
                facts.update(write_fault)
            self.last_persistence = facts
            return facts

        def now():
            if self.returned and clock_error is not None:
                raise clock_error
            return self.time

        with ExitStack() as stack:
            stack.enter_context(patch.object(module, "_qualified_parent_v2", side_effect=parent_error))
            stack.enter_context(patch.object(module, "_monotonic_ns", side_effect=now))
            stack.enter_context(patch.object(reader, "_monotonic_ns", return_value=NOW))
            stack.enter_context(patch.object(module.os, "scandir", side_effect=scandir))
            stack.enter_context(patch.object(Path, "resolve", autospec=True,
                side_effect=lambda path, **kwargs: path))
            stack.enter_context(patch.object(Path, "is_dir", return_value=True))
            stack.enter_context(patch.object(Path, "exists", autospec=True,
                side_effect=lambda path: path in self.files))
            stack.enter_context(patch.object(Path, "is_symlink", return_value=False))
            opened = stack.enter_context(patch.object(PhysicalRootCustodyV1, "open"))
            self.custody = opened.return_value
            self.custody.root = CAPTURE
            self.custody.read_descriptor.side_effect = read
            self.capture = stack.enter_context(patch.object(module, "_capture_owned_reader_v2", side_effect=capture))
            self.writer = stack.enter_context(patch.object(module, "_write_result_v2", side_effect=write))
            with module.LiteralSourceCaptureV2(project_root=ROOT, output_dir=output,
                    capture_dir=directory, deadline=deadline, expected_commit="a" * 40,
                    negative=negative) as owner:
                yield owner

    def test_git_without_explicit_owner_refuses_before_unbounded_subprocess(self):
        for args in (("rev-parse", "HEAD"), ("status", "--porcelain", "--untracked-files=no"),
                     ("show", positive.APPROVED_COMMIT + ":" + positive.GUARDIAN_SOURCE)):
            with self.subTest(args=args), patch.object(subprocess, "run",
                    return_value=SimpleNamespace(stdout=b"controlled")) as run:
                error = None
                try:
                    positive._git(ROOT, *args)
                except BaseException as caught:
                    error = caught
                self.assertIsInstance(error, ValueError)
                run.assert_not_called()

    def test_raw_proof_without_explicit_owner_refuses_before_unbounded_subprocess(self):
        with patch.object(subprocess, "run", return_value=SimpleNamespace(
                stdout=b"{}\n", stderr=b"", returncode=0)) as run:
            error = None
            try:
                negative._raw_committed_source_proof(ROOT)
            except BaseException as caught:
                error = caught
            self.assertIsInstance(error, ValueError)
            run.assert_not_called()

    def test_complete_fixed_rosters_reuse_original_deadline_and_persist_before_protocol(self):
        module = self.module()
        compile(module._RAW_SOURCE_PROOF_V2, "fixed-literal-source-proof", "exec")
        for negative, slots in ((False, POSITIVE), (True, NEGATIVE)):
            with self.subTest(negative=negative), self.controlled(negative=negative) as owner:
                for slot in slots:
                    returned = owner.capture(slot)
                    if "proof" in slot:
                        self.assertEqual(returned["original_exit_code"], 0)
                        self.assertEqual(returned["stderr"], "")
                        self.assertEqual(json.loads(returned["stdout"]), {
                            "raw_committed_bytes_verified": True, "tracked_path_count": 14147,
                            "verifier_path": str(ROOT / "scripts/run_ci_checks.py")})
                    else:
                        expected = b"a" * 40 + b"\n" if "head" in slot else (
                            b"controlled original guardian\n" if slot == "guardian" else b"")
                        self.assertEqual(returned, expected)
                self.assertEqual(self.capture.call_count, len(slots))
                self.assertEqual(self.writer.call_count, len(slots))
                for slot, call in zip(slots, self.capture.call_args_list):
                    command = call.kwargs["command"]
                    self.assertEqual(command[:2], ["/usr/bin/env", "-i"])
                    self.assertIn("GIT_WORK_TREE=" + str(ROOT), command)
                    self.assertIn("GIT_DIR=/mnt/e/STUDY/VAST/.git/worktrees/VAST8", command)
                    self.assertIn("--as=1073741824:1073741824", command)
                    if "proof" in slot:
                        self.assertEqual(command[-8:], [sys.executable, "-I", "-S", "-B", "-c",
                            module._RAW_SOURCE_PROOF_V2, str(ROOT), str(OBSERVE_END)])
                    else:
                        args = ("rev-parse", "HEAD") if "head" in slot else (
                            ("show", positive.APPROVED_COMMIT + ":" + positive.GUARDIAN_SOURCE)
                            if slot == "guardian" else ("status", "--porcelain", "--untracked-files=no"))
                        tail = ["/usr/bin/git", "-C", str(ROOT), *args]
                        self.assertEqual(command[-len(tail):], tail)
                for record in self.records:
                    self.assertNotIn("result_persistence", record)

    def test_incomplete_capture_outcomes_never_pass(self):
        module = self.module()
        faults = [lambda f: f.update(causes=["reader_io"]), lambda f: f.update(forced=True),
            lambda f: f.update(signal=9), lambda f: f.update(returncode=1),
            lambda f: f.update(returncode=None), lambda f: f["closure"].update(closed=False),
            lambda f: f["closure"].update(descendants_unknown=True),
            lambda f: f["closure"].update(subreaper_restored=False),
            lambda f: f["stdout"].update(eof=False), lambda f: f["stdout"].update(overflow=True),
            lambda f: f["stderr"].update(remainder_unknown=True),
            lambda f: f["stdout"]["file"].update(fsync_completed=False)]
        for index, fault in enumerate(faults):
            with self.subTest(fault=index), self.controlled(fault=fault) as owner:
                with self.assertRaises(module.LiteralSourceCaptureRefusedV2) as caught:
                    owner.capture("head")
                self.assertIs(caught.exception.evidence["capture"], self.last_capture)
                self.assertEqual(self.last_capture, self.last_capture_snapshot)
                self.writer.assert_called_once()

    def test_protocol_validation_requires_complete_exact_head_status_guardian_and_proof(self):
        module = self.module()
        proof = {"raw_committed_bytes_verified": True, "tracked_path_count": 14147,
            "verifier_path": str(ROOT / "scripts/run_ci_checks.py")}
        vectors = [("head", b"b" * 40 + b"\n"), ("head", b"a" * 40),
            ("head", b"a" * 40 + b"\nextra"), ("status", b" M changed\n"), ("guardian", b""),
            ("before-proof", b"{"), ("before-proof", b"{}\n"),
            ("before-proof", json.dumps({**proof, "tracked_path_count": True}).encode()),
            ("before-proof", json.dumps({**proof, "verifier_path": "/foreign.py"}).encode()),
            ("before-proof", b" " * 8193)]
        for slot, raw in vectors:
            with self.subTest(slot=slot, size=len(raw)), self.controlled(
                    negative=slot == "before-proof", stdout={slot: raw}) as owner:
                # Preceding slots are consumed through the real adapter under
                # normal controlled data; only the selected protocol is corrupt.
                prior = NEGATIVE[:2] if slot == "before-proof" else POSITIVE[:POSITIVE.index(slot)]
                for preceding in prior:
                    owner.capture(preceding)
                with self.assertRaises(module.LiteralSourceCaptureRefusedV2):
                    owner.capture(slot)
                self.assertEqual(self.writer.call_count, len(prior) + 1)

    def test_result_io_failures_preserve_original_facts_and_refuse(self):
        module = self.module()
        for fault in ({"written_bytes": 1}, {"write_extent_unknown": True}, {"fsync_completed": False},
                      {"close_completed": False}, {"causes": ["result_io"]}):
            with self.subTest(fault=fault), self.controlled(write_fault=fault) as owner:
                with self.assertRaises(module.LiteralSourceCaptureRefusedV2) as caught:
                    owner.capture("head")
                self.assertIs(caught.exception.evidence["result_persistence"], self.last_persistence)
                self.assertIs(caught.exception.evidence["capture"], self.last_capture)
                self.assertEqual(self.last_capture, self.last_capture_snapshot)

    def test_expiry_never_renews_observation_or_starts_a_remaining_slot(self):
        module = self.module()
        for late_return in (False, True):
            with self.subTest(late_return=late_return), self.controlled(
                    return_time=OBSERVE_END if late_return else None) as owner:
                if not late_return:
                    self.time = OBSERVE_END
                with self.assertRaises(ValueError) as caught:
                    owner.capture("head")
                self.assertEqual(self.capture.call_count, int(late_return))
                self.assertEqual(self.writer.call_count, int(late_return))
                self.assertEqual(len(self.records), int(late_return))
                if late_return:
                    self.assertIs(getattr(caught.exception, "evidence", {}).get("capture"), self.last_capture)
                    self.assertEqual(self.last_capture, self.last_capture_snapshot)

    def test_unknown_reused_or_out_of_order_slot_never_starts_another_capture(self):
        self.module()
        for slot, first in (("unknown", False), ("status", False), ("head", True)):
            with self.subTest(slot=slot, first=first), self.controlled() as owner:
                if first:
                    owner.capture("head")
                with self.assertRaises(ValueError):
                    owner.capture(slot)
                self.assertEqual(self.capture.call_count, int(first))
                self.assertEqual(self.writer.call_count, int(first))

    def test_invalid_clock_or_unqualified_parent_refuses_before_capture_and_writer(self):
        self.module()
        vectors = [(None, None), ({}, None), ({**DEADLINE, "absolute_monotonic_ns": False}, None),
            ({**DEADLINE, "absolute_monotonic_ns": NOW}, None),
            (DEADLINE, ValueError("controlled parent qualification failed"))]
        for clock, parent_error in vectors:
            with self.subTest(clock=clock, parent_error=parent_error):
                with self.assertRaises(ValueError):
                    with self.controlled(deadline=clock, parent_error=parent_error):
                        self.fail("unqualified parent/clock was admitted")
                self.capture.assert_not_called()
                self.writer.assert_not_called()

    def test_post_return_clock_failure_saves_actual_capture_and_distinct_writer_failure(self):
        self.module()
        for writer_fails in (False, True):
            clock_error = RuntimeError("controlled post-return clock observation failed")
            write_error = OSError("controlled result write failed") if writer_fails else None
            with self.subTest(writer_fails=writer_fails), self.controlled(
                    clock_error=clock_error, write_error=write_error) as owner:
                with self.assertRaises(Exception) as caught:
                    owner.capture("head")
                self.assertIs(getattr(caught.exception, "evidence", {}).get("capture"), self.last_capture)
                self.assertIs(getattr(caught.exception, "primary", None), clock_error)
                self.assertEqual(getattr(caught.exception, "secondary", None), (write_error,) if writer_fails else ())
                self.assertEqual(self.last_capture, self.last_capture_snapshot)
                self.writer.assert_called_once()
                self.assertIs(owner.records[-1]["capture"], self.last_capture)

    def test_missing_foreign_overlapping_or_occupied_directory_refuses_before_capture(self):
        self.module()
        for directory, occupied in ((None, False), (Path("relative"), False), (ROOT.parent / "foreign", False),
                (OUTPUT, False), (OUTPUT / "nested", False), (CAPTURE, True)):
            with self.subTest(directory=directory, occupied=occupied):
                with self.assertRaises(ValueError):
                    with self.controlled(directory=directory, occupied=occupied):
                        self.fail("invalid capture directory was admitted")
                self.capture.assert_not_called()
                self.writer.assert_not_called()

    def test_parent_address_space_requires_finite_ordered_soft_and_hard_bounds(self):
        module = self.module()
        gib = 1024**3
        for soft, hard in ((-1, -1), (0, 12 * gib), (13 * gib, 13 * gib), (12 * gib, 11 * gib),
                           (12 * gib, 12 * gib)):
            with self.subTest(soft=soft, hard=hard), patch.dict(sys.modules, {"resource": SimpleNamespace(
                    RLIMIT_AS=9, getrlimit=lambda key: (soft, hard))}):
                if 0 < soft <= hard <= 12 * gib:
                    module._parent_limit_v2()
                else:
                    with self.assertRaises(ValueError):
                        module._parent_limit_v2()


if __name__ == "__main__":
    unittest.main()
