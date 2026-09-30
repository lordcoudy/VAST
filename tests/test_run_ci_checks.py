from __future__ import annotations

import importlib.util
import io
from pathlib import Path
import tempfile
import unittest


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


if __name__ == "__main__":
    unittest.main()
