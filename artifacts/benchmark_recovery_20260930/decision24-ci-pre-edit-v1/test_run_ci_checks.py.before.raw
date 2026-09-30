from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("vast_ci_checks", ROOT / "scripts/run_ci_checks.py")
ci = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ci)


class NamedCase(unittest.TestCase):
    def __init__(self, identifier):
        super().__init__()
        self.identifier = identifier

    def id(self):
        return self.identifier


class RunCiChecksTests(unittest.TestCase):
    def result(self):
        return ci.RecordedResult(unittest.runner._WritelnDecorator(io.StringIO()), True, 2)

    def test_required_native_skip_does_not_become_a_pass(self):
        result = self.result()
        for identifier in ci.REQUIRED_TESTS:
            case = NamedCase(identifier)
            result.startTest(case)
            result.addSkip(case, "compiler unavailable")
            result.stopTest(case)
        report = ci.suite_report(result)
        self.assertFalse(report["successful"])
        self.assertEqual(set(report["missing_required_successes"]), ci.REQUIRED_TESTS)
        self.assertEqual(len(report["skips"]), 3)

    def test_empty_discovery_fails(self):
        self.assertFalse(ci.suite_report(self.result())["successful"])

    def test_required_native_successes_allow_other_explicit_skips(self):
        result = self.result()
        for identifier in ci.REQUIRED_TESTS:
            case = NamedCase(identifier)
            result.startTest(case)
            result.addSuccess(case)
            result.stopTest(case)
        skipped = NamedCase("physical_gpu_not_available")
        result.startTest(skipped)
        result.addSkip(skipped, "requires NVIDIA hardware")
        result.stopTest(skipped)
        report = ci.suite_report(result)
        self.assertTrue(report["successful"])
        self.assertEqual(report["skips"], [{"test_id": skipped.id(), "reason": "requires NVIDIA hardware"}])

    def test_changed_added_and_removed_sources_are_reported(self):
        self.assertEqual(ci.source_changes({"a": 1, "b": 2}, {"a": 3, "c": 4}), ["a", "b", "c"])

    def test_manifest_detects_equal_size_source_replacement(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.py"
            source.write_bytes(b"first")
            before = ci.manifest(root, ["source.py"])
            source.write_bytes(b"other")
            self.assertEqual(ci.source_changes(before, ci.manifest(root, ["source.py"])), ["source.py"])

    def test_failure_traceback_is_flushed_before_the_suite_returns(self):
        class Failing(unittest.TestCase):
            def runTest(self):
                self.fail("original immediate failure")

        class ObservedStream(io.StringIO):
            def __init__(self):
                super().__init__()
                self.flushed = []

            def flush(self):
                self.flushed.append(self.getvalue())

        stream = ObservedStream()
        result = ci.RecordedResult(unittest.runner._WritelnDecorator(stream), True, 2)
        Failing().run(result)
        self.assertTrue(any("original immediate failure" in text and "Traceback" in text
                            for text in stream.flushed))
        self.assertIn('"event": "test_started"', stream.getvalue())
        self.assertIn('"event": "test_terminal"', stream.getvalue())
        self.assertIn('"outcome": "failure"', stream.getvalue())
        self.assertEqual(len(result.failures), 1)

    def test_subtest_error_traceback_is_flushed_and_parent_terminal_is_error(self):
        class Subtests(unittest.TestCase):
            def runTest(self):
                with self.subTest(frame=7):
                    raise ValueError("original subtest error")

        stream = io.StringIO()
        result = ci.RecordedResult(unittest.runner._WritelnDecorator(stream), True, 2)
        Subtests().run(result)
        self.assertIn("original subtest error", stream.getvalue())
        self.assertIn('"event": "subtest_error"', stream.getvalue())
        self.assertIn('"outcome": "error"', stream.getvalue())
        self.assertEqual(len(result.errors), 1)

    def test_interrupted_test_start_does_not_invent_a_terminal(self):
        stream = io.StringIO()
        result = ci.RecordedResult(unittest.runner._WritelnDecorator(stream), True, 2)
        result.startTest(NamedCase("original_blocked_case"))
        self.assertIn('"event": "test_started"', stream.getvalue())
        self.assertNotIn('"event": "test_terminal"', stream.getvalue())

    def test_host_facts_are_bounded_and_exclude_environment_secrets(self):
        import json
        with mock.patch.dict("os.environ", {"VAST_DIAGNOSTIC_TEST_SECRET": "never-print-this"}):
            facts = ci.host_facts()
        raw = json.dumps(facts).encode()
        self.assertLessEqual(len(raw), 16 * 1024)
        self.assertNotIn(b"never-print-this", raw)
        self.assertNotIn("environment", facts)
        self.assertIn("executable_realpath", facts)
        self.assertIn("kernel_release", facts)
        self.assertIn("namespace_sysctls", facts)

    def test_real_periodic_stack_capture_keeps_the_active_test_and_result(self):
        import json
        import subprocess
        import sys
        import textwrap

        # faulthandler has one process-wide timer. Isolate the regression so it
        # cannot replace/cancel the outer full-discovery runner's 60s timer.
        child = textwrap.dedent("""
            import importlib.util,io,json,sys,tempfile,time,unittest
            spec=importlib.util.spec_from_file_location('ci',sys.argv[1])
            ci=importlib.util.module_from_spec(spec); spec.loader.exec_module(ci)
            class Waiting(unittest.TestCase):
                def runTest(self): time.sleep(.08)
            with tempfile.TemporaryFile(mode='w+',encoding='utf8') as stacks:
                result=ci.run_test_suite(unittest.TestSuite([Waiting()]),io.StringIO(),stacks,.02)
                stacks.seek(0); original=stacks.read()
            print(json.dumps({'passed':result.wasSuccessful(),'stacks':original}))
        """)
        original = subprocess.run([sys.executable, "-I", "-B", "-c", child,
                                   str(ROOT / "scripts/run_ci_checks.py")],
                                  check=True, capture_output=True, text=True, timeout=10)
        observation = json.loads(original.stdout)
        self.assertTrue(observation["passed"])
        self.assertIn("Timeout", observation["stacks"])
        self.assertIn("runTest", observation["stacks"])
        self.assertIn("run_test_suite", observation["stacks"])

    def test_expected_failure_and_unexpected_success_keep_original_outcomes(self):
        stream = io.StringIO()
        result = ci.RecordedResult(unittest.runner._WritelnDecorator(stream), True, 2)
        expected = NamedCase("expected_failure_case")
        result.startTest(expected)
        try:
            raise ValueError("original expected failure")
        except ValueError:
            import sys
            result.addExpectedFailure(expected, sys.exc_info())
        result.stopTest(expected)
        unexpected = NamedCase("unexpected_success_case")
        result.startTest(unexpected)
        result.addUnexpectedSuccess(unexpected)
        result.stopTest(unexpected)
        self.assertIn('"outcome": "expected_failure"', stream.getvalue())
        self.assertIn('"outcome": "unexpected_success"', stream.getvalue())
        self.assertEqual(len(result.expectedFailures), 1)
        self.assertFalse(result.wasSuccessful())


if __name__ == "__main__":
    unittest.main()
