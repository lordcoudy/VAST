from __future__ import annotations

import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
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
    def test_real_alias_launcher_uses_canonical_interpreter_for_suite_and_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            alias = base / "python-alias"
            alias.symlink_to(Path(sys.executable).resolve())
            output = base / "output"
            code = """
import importlib.util,json,sys,time
from pathlib import Path
spec=importlib.util.spec_from_file_location('ci',sys.argv[1]);ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)
root=Path(sys.argv[2]);root.mkdir();ci.ROOT=root;output=Path(sys.argv[3])
ci.tracked_paths=lambda root:[]
ci.verify_committed_bytes=lambda *a:None
ci.subprocess.run=lambda *a,**k:type('Result',(),{'stdout':'fixturecommit\\n'})()
ci.host_facts=lambda:{}
ci.specification_inventory=lambda root:{}
commands=[]
ci.command=lambda argv,*a:commands.append(argv) or {}
ci.gstreamer_factory_facts=lambda *a:{'fixture':True}
ci.namespace_diagnostic=lambda *a:{'capture_completed':True,'namespace_succeeded':True,'explicit_local_fixture':True}
def observe(factory,**kwargs):
 argv=factory(101,102,103)
 ci.write_json(output/'unittest-child.report.json',{'successful':True})
 ci.write_json(output/'argv.json',{'suite':argv,'commands':commands,'actual_executable':sys.executable})
 return {'successful':True}
ci._observer.observe_test_child=observe
sys.argv=['runner','--expected-commit','fixturecommit','--output-dir',sys.argv[3]]
raise SystemExit(ci.main())
"""
            child = subprocess.run([str(alias), "-I", "-B", "-c", code,
                                    str(ROOT / "scripts/run_ci_checks.py"), str(base / "root"), str(output)],
                                   capture_output=True, text=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)
            observed = json.loads((output / "argv.json").read_bytes())
            self.assertEqual(observed["actual_executable"], str(alias))
            canonical = str(Path(sys.executable).resolve())
            self.assertEqual(observed["suite"][:3], [canonical, "-I", "-B"])
            self.assertEqual(observed["commands"][0][:3], [canonical, "-I", "-B"])

    def test_isolated_default_discovery_imports_contained_namespaces_and_preserves_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / "repo"
            (root / "tests").mkdir(parents=True)
            (root / "deploy").mkdir()
            (root / '.ci').mkdir()
            (root / '.ci/integration-test-selection.v1.json').write_text(json.dumps({
                'schema_version':1,'kind':'vast_ci_explicit_test_lanes_v1','default_lane':'mandatory_portable',
                'integration_declarations':[],'allowed_portable_skips':[]}))
            (root / "tests/peer.py").write_text("VALUE=7\n")
            (root / "deploy/support.py").write_text("VALUE=9\n")
            (root / "tests/test_contract.py").write_text(
                "import unittest\nfrom tests.peer import VALUE\nfrom deploy.support import VALUE as OTHER\n"
                "class Contract(unittest.TestCase):\n def test_values(self): self.assertEqual((VALUE,OTHER),(7,9))\n")
            output = base / "out"
            output.mkdir()
            code = """
import contextlib,importlib.util,os,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('ci',sys.argv[1]);ci=importlib.util.module_from_spec(spec);spec.loader.exec_module(ci)
ci.ROOT=Path(sys.argv[2]);ci.REQUIRED_TESTS={'test_contract.Contract.test_values'}
@contextlib.contextmanager
def handler(*a): yield {'failure':None}
ci._observer.child_trace_handler=handler
fds=[os.open('/dev/null',os.O_RDWR) for _ in range(3)]
raise SystemExit(ci.suite_child(Path(sys.argv[3]),*fds))
"""
            child = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                                    str(ROOT / "scripts/run_ci_checks.py"), str(root), str(output)],
                                   capture_output=True, text=True, timeout=10)
            report = json.loads((output / "unittest-child.report.json").read_bytes())
            self.assertEqual(child.returncode, 0, report)
            self.assertEqual(report["successful_test_ids"], ["test_contract.Contract.test_values"])
            manifest = root / '.ci/integration-test-selection.v1.json'
            document = json.loads(manifest.read_bytes())
            document['integration_declarations'] = [{'test_id':'test_absent.Contract.test_values',
                'reason':'explicit invalid fixture declaration', 'required_capabilities':['real corpus']}]
            manifest.write_text(json.dumps(document))
            bad_output = base/'invalid-manifest-out'
            bad_output.mkdir()
            refused = subprocess.run([sys.executable,'-I','-B','-c',code,
                str(ROOT/'scripts/run_ci_checks.py'),str(root),str(bad_output)],
                capture_output=True,text=True,timeout=10)
            bad_report = json.loads((bad_output/'unittest-child.report.json').read_bytes())
            self.assertEqual(refused.returncode,1)
            self.assertEqual(bad_report['discovered_ids'],['test_contract.Contract.test_values'])
            self.assertFalse(bad_report['successful'])

    def test_foreign_namespace_origin_is_rejected_before_discovery(self):
        import types
        foreign = types.ModuleType("deploy")
        foreign.__path__ = [str(Path(tempfile.gettempdir()) / "foreign-deploy")]
        with mock.patch.dict(sys.modules, {"deploy": foreign}):
            with self.assertRaisesRegex(RuntimeError, "outside fixed repository"):
                ci.validate_repository_import_origins()

    def test_missing_runtime_factory_remains_a_failed_prerequisite(self):
        with tempfile.TemporaryDirectory() as directory:
            with mock.patch.object(ci.shutil, "which", return_value=sys.executable), \
                 mock.patch.object(ci, "command", side_effect=RuntimeError("original missing appsrc")):
                with self.assertRaisesRegex(RuntimeError, "original missing appsrc"):
                    ci.gstreamer_factory_facts(Path(directory), 10**30)

    def test_loaded_factory_facts_bind_original_metadata_and_plugin_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            plugin = output / "libgstfixture.so"
            plugin.write_bytes(b"explicit local plugin metadata fixture")
            def inspect(argv, destination, name, *args):
                self.assertEqual(argv[1], name.removeprefix("factory-"))
                (destination / (name + ".stdout")).write_text(
                    "Factory Details:\n  Rank none\nPlugin Details:\n  Name fixture\n"
                    f"  Filename {plugin}\n  Version 1.0\n")
                (destination / (name + ".stderr")).write_bytes(b"")
                return {"returncode": 0, "argv": argv}
            with mock.patch.object(ci.shutil, "which", return_value=str(plugin)), \
                 mock.patch.object(ci, "command", side_effect=inspect):
                facts = ci.gstreamer_factory_facts(output, 10**30)
            self.assertEqual(set(facts), {"appsrc", "queue", "videoconvert"})
            for row in facts.values():
                self.assertEqual(row["plugin"]["path"], str(plugin))
                self.assertEqual(row["plugin"]["size_bytes"], plugin.stat().st_size)
                self.assertEqual(row["command"]["returncode"], 0)

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
        import sys
        import textwrap
        import time

        # The external parent requests dumps; the real suite child has no timer
        # or observer thread that could invalidate the production subreaper rule.
        child = textwrap.dedent("""
            import importlib.util,io,json,sys,time,unittest
            from pathlib import Path
            spec=importlib.util.spec_from_file_location('ci',sys.argv[1])
            ci=importlib.util.module_from_spec(spec); spec.loader.exec_module(ci)
            class Waiting(unittest.TestCase):
                def runTest(self): time.sleep(.12)
            with ci._observer.child_trace_handler(int(sys.argv[2]),int(sys.argv[3]),int(sys.argv[4])):
                result=ci.run_test_suite(unittest.TestSuite([Waiting()]),io.StringIO())
            Path(sys.argv[5]).write_text(json.dumps({'passed':result.wasSuccessful()}))
        """)
        with tempfile.TemporaryDirectory() as directory:
            original = ci._observer.observe_test_child(
                lambda trace,event,stop: [sys.executable,"-I","-B","-c",child,
                    str(ROOT / "scripts/run_ci_checks.py"),str(trace),str(event),str(stop),
                    str(Path(directory)/"suite-result.json")],
                output_dir=Path(directory)/"observer", interval_s=.02,
                absolute_deadline_ns=time.monotonic_ns()+5_000_000_000)
            self.assertTrue(original['successful'], original)
            observation=json.loads((Path(directory)/"suite-result.json").read_text())
            trace=(Path(directory)/"observer/trace.original.log").read_text()
            ready=json.loads((Path(directory)/"observer/responses.original.jsonl").read_text().splitlines()[0])
        self.assertTrue(observation["passed"])
        self.assertEqual(ready['native_task_count'],1)
        self.assertIn("runTest",trace)
        self.assertIn("run_test_suite",trace)

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
