"""Fixed invocation/prefix tests with controlled external effects only."""
import hashlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c

COMMIT = "a" * 40
SHA = "b" * 64
ROOT = "/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + COMMIT + "-01"


class InvocationTests(unittest.TestCase):
    def test_fixed_external_args_derive_only_approved_prior_paths(self):
        kw = c.parse_native_invocation_v1([COMMIT, "1234", SHA, "-"], stage="C1")
        self.assertEqual(kw["project_root"], ROOT)
        self.assertEqual(kw["expected_code_commit"], COMMIT)
        self.assertEqual(kw["completion_authorities"], {})
        kw = c.parse_native_invocation_v1([COMMIT, "1234", SHA, ",".join(["456:" + SHA] * 6)], stage="D")
        self.assertEqual(list(kw["completion_authorities"]), list(c.STAGES))
        self.assertEqual(kw["completion_authorities"]["C6"], {
            "path": ROOT + "/outputs/C6/outer.invocation.original.json", "size_bytes": 456, "sha256": SHA})

    def test_foreign_commit_paths_counts_and_scalar_shapes_refuse(self):
        for args, stage in ((["A" * 40, "1234", SHA, "-"], "C1"),
                ([COMMIT, "true", SHA, "-"], "C1"), ([COMMIT, "0", SHA, "-"], "C1"),
                ([COMMIT, "1234", SHA, "../file"], "C2"),
                ([COMMIT, "1234", SHA, "8193:" + SHA], "C2"),
                ([COMMIT, "1234", SHA, "-"], "D"), ([COMMIT, "1234", SHA, "-"], "arbitrary")):
            with self.subTest(args=args, stage=stage), self.assertRaises(c.Gate2Refusal):
                c.parse_native_invocation_v1(args, stage=stage)

    def test_large_failure_retains_hash_ordered_causes_prefix_and_unknown(self):
        facts = {"causes": ["first", "secondary"], "write_extent_unknown": True, "payload": "x" * 60000}
        error = c.Gate2Refusal("stopped", facts)
        raw = c.native_failure_bytes_v1(error)
        self.assertLessEqual(len(raw), 768)
        value = json.loads(raw)
        self.assertEqual(value["causes"][:2], ["first", "secondary"])
        self.assertEqual(value["facts_sha256"], hashlib.sha256(c.component.canonical_json_v1(facts)).hexdigest())
        self.assertTrue(value["facts_remainder_unknown"])
        self.assertFalse(value["physical_acceptance"])
        self.assertTrue(value["external_status_eof_required"])

    def test_unserializable_failure_is_explicitly_unknown_and_still_bounded(self):
        raw = c.native_failure_bytes_v1(c.Gate2Refusal("stopped", {"opaque": object()}))
        self.assertLessEqual(len(raw), 768)
        self.assertTrue(json.loads(raw)["facts_unknown"])

    def test_adversarial_failure_labels_cycles_and_flags_remain_bounded(self):
        for facts in ({"causes": ["z" * 1000] * 20, "write_extent_unknown": True,
                "unknown_closure": True, "stdout_eof": False, "stderr_eof": False, "payload": "x" * 60000}, {}):
            if not facts:
                facts["cycle"] = facts
            raw = c.native_failure_bytes_v1(c.Gate2Refusal('\"\\\n' * 1000, facts))
            self.assertLessEqual(len(raw), 768)
            self.assertTrue(json.loads(raw)["cause_remainder_unknown"])
            self.assertTrue(json.loads(raw)["facts_remainder_unknown"])
            self.assertTrue(raw.endswith(b"\n"))

    def test_actual_c_refusal_and_completion_wrappers_project_nested_facts(self):
        for wrapper, facts in (("c_stage_stopped", {"cause": "guard_refused",
                "failure_facts": {"causes": ["guard_stdout_short_write", "guard_eof_unknown"],
                    "files": {"stdout": {"write_extent_unknown": True, "written_bytes": 7}}},
                "refusal_write_failure": {"failure_causes": ["record_deadline"], "write_extent_unknown": False}}),
                ("c_completion_stopped", {"cause": "record_short_write", "failure_facts": {
                    "write_extent_unknown": False, "written_bytes": 7, "failure_causes": ["record_short_write"]},
                    "write_facts": None})):
            raw = c.native_failure_bytes_v1(c.Gate2Refusal(wrapper, facts))
            value = json.loads(raw)
            self.assertLessEqual(len(raw), 768)
            self.assertEqual(value["causes"][0], facts["cause"])
            self.assertGreaterEqual(len(value["causes"]), 2 if wrapper == "c_stage_stopped" else 1)
            self.assertTrue(any("write_extent_unknown" == row[1] for row in value["observations"]))
            self.assertTrue(value["facts_remainder_unknown"])

    def test_bootstrap_import_and_resolution_errors_are_bounded(self):
        source = Path(c.__file__).read_text()
        prefix = source[:source.index("STAGES =")]
        args = ["program", "C1", COMMIT, "1234", SHA, "-"]
        for error in (OSError("resolve failed"), None):
            with patch.object(sys, "argv", args), patch.object(c.os, "write") as write, \
                    patch.object(Path, "resolve", side_effect=error, return_value=Path(ROOT) / "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py"):
                if error is None:
                    original_import = __import__
                    def failing_import(name, *a, **kw):
                        if name == "tests.fixtures":
                            raise ImportError("damaged export")
                        return original_import(name, *a, **kw)
                    import_patch = patch("builtins.__import__", side_effect=failing_import)
                else:
                    import_patch = patch("builtins.__import__", wraps=__import__)
                with import_patch, self.assertRaises(SystemExit) as caught:
                    exec(compile(prefix, str(Path(c.__file__)), "exec"), {"__name__": "__main__", "__file__": str(Path(c.__file__))})
                self.assertEqual(caught.exception.code, 1)
                self.assertEqual(write.call_args.args, (2, b'{"cause":"c_native_bootstrap","unknown":true}\n'))

    def test_partial_and_unreturned_stdout_writes_refuse_with_truthful_extent(self):
        for effect, unknown in ((3, False), (OSError("partial unreturned"), True)):
            with self.subTest(effect=effect), patch.object(c.time, "monotonic_ns", return_value=100), \
                    patch.object(c.os, "write", side_effect=effect if isinstance(effect, Exception) else None,
                                 return_value=effect if isinstance(effect, int) else None):
                with self.assertRaises(c.Gate2Refusal) as caught:
                    c.emit_native_bytes_v1(b'{"ok":true}\n', 1000)
                self.assertIs(caught.exception.facts["write_extent_unknown"], unknown)

    def test_late_stdout_admission_does_not_write(self):
        with patch.object(c.time, "monotonic_ns", return_value=1001), patch.object(c.os, "write") as write:
            with self.assertRaises(c.Gate2Refusal):
                c.emit_native_bytes_v1(b'{}\n', 1000)
        write.assert_not_called()

    def test_flush_failure_and_late_flush_keep_confirmed_write_extent(self):
        raw = b'{}\n'
        for clock, flush in (([100, 100], OSError("pipe flush")), ([100, 100, 1001], None)):
            with patch.object(c.time, "monotonic_ns", side_effect=clock), \
                    patch.object(c.os, "write", return_value=len(raw)), patch.object(c.sys.stdout, "flush", side_effect=flush):
                with self.assertRaises(c.Gate2Refusal) as caught:
                    c.emit_native_bytes_v1(raw, 1000)
            self.assertEqual(caught.exception.facts["written_bytes"], len(raw))
            self.assertFalse(caught.exception.facts["write_extent_unknown"])
            self.assertEqual(caught.exception.facts["flush_completed"], flush is None)

    def test_isolated_cli_refuses_foreign_export_before_project_imports(self):
        source = Path(c.__file__).resolve()
        result = subprocess.run([sys.executable, "-I", "-S", "-B", str(source),
            "C1", COMMIT, "1234", SHA, "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b'{"cause":"c_native_bootstrap","unknown":true}\n')

    def test_c_main_calls_existing_entrypoints_and_emits_only_completion(self):
        completion = {"completion": {"path": "fixed", "size_bytes": 123, "sha256": SHA},
                      "completion_deadline_ns": 1000, "external_approval": False}
        with patch.object(c, "run_c_v1", return_value={"actual": "result"}) as run, \
                patch.object(c, "complete_c_invocation_v1", return_value=completion) as complete, \
                patch.object(c, "emit_native_bytes_v1") as emit:
            self.assertEqual(c.native_main_v1(["C1", COMMIT, "1234", SHA, "-"]), 0)
        self.assertEqual(run.call_args.args, ("C1",))
        self.assertEqual(complete.call_args.kwargs["returned_result"], {"actual": "result"})
        self.assertEqual(json.loads(emit.call_args.args[0]), completion)
        self.assertEqual(emit.call_args.args[1], 1000)

    def test_c_failure_does_not_complete_and_uses_bounded_stderr(self):
        with patch.object(c, "run_c_v1", side_effect=c.Gate2Refusal("native_unknown", {"unknown_closure": True})), \
                patch.object(c, "complete_c_invocation_v1") as complete, patch.object(c.os, "write") as write:
            self.assertEqual(c.native_main_v1(["C1", COMMIT, "1234", SHA, "-"]), 1)
        complete.assert_not_called()
        self.assertEqual(write.call_args.args[0], 2)
        self.assertLessEqual(len(write.call_args.args[1]), 768)


class GuardPrefixTests(unittest.TestCase):
    def test_fixed_phase_files_are_distinct_and_default_names_unchanged(self):
        class Stream(io.BytesIO):
            def fileno(self): return 18
        class Process:
            pid = 88
            def __init__(self): self.stdout, self.stderr = Stream(b"12\n"), Stream(b"")
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(c.subprocess, "Popen", side_effect=lambda *a, **kw: Process()), \
                    patch.object(c.os, "set_blocking"), \
                    patch.object(c.select, "select", side_effect=lambda readers, *_: (readers, [], [])), \
                    patch.object(c.time, "monotonic_ns", return_value=100):
                for phase in (None, "before", "after"):
                    result = c.capture_guard_v1("gpu", output_dir=root, absolute_deadline_ns=10_000_000_000,
                        record_original=False, _phase_prefix=phase)
                    self.assertTrue(result["closed"])
            self.assertEqual({p.name for p in root.iterdir()}, {
                "gpu.stdout.original", "gpu.stderr.original", "before.gpu.stdout.original",
                "before.gpu.stderr.original", "after.gpu.stdout.original", "after.gpu.stderr.original"})
            for prefix in ("", "before.", "after."):
                self.assertEqual((root / (prefix + "gpu.stdout.original")).read_bytes(), b"12\n")

    def test_arbitrary_prefix_refuses_before_files_or_spawn(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(c.subprocess, "Popen") as spawn:
            for value in ("../before", "before.", "arbitrary", 1):
                with self.subTest(value=value), self.assertRaises(c.Gate2Refusal):
                    c.capture_guard_v1("gpu", output_dir=Path(directory).resolve(),
                        absolute_deadline_ns=10_000_000_000, _phase_prefix=value)
            self.assertEqual(list(Path(directory).iterdir()), [])
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
