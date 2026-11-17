"""Producer report pre-encoding refusals; no real fixture or engine execution."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from tests.fixtures.accepted_policy_change_paths_v1 import consumer_evidence_directory_v1


def producer():
    root = Path(__file__).resolve().parents[1]
    path = consumer_evidence_directory_v1(root) / "build_production_fixture_v2.py"
    spec = importlib.util.spec_from_file_location("fixture_report_producer_v1", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FixtureReportWriterTests(unittest.TestCase):
    def refuse_before_open(self, value):
        # Keep every refused/partial original and empty GREEN root for review.
        output = Path(tempfile.mkdtemp(prefix="fixture-report-")) / "absent.json"
        try:
            with self.assertRaises(ValueError):
                producer()._fresh_json(output, value)
        finally:
            self.assertFalse(output.exists(), "report refusal opened its output")

    def test_complete_supported_fields_keep_exact_original_json_bytes(self):
        value = {"proof": {"path": Path("relative/path"), "rows": [True, None, 1, -1, 0.5]},
                 "unicode": "\u00e9\U0001f600", "escaped": 'quote" slash\\ newline\n'}
        output = Path(tempfile.mkdtemp(prefix="fixture-report-")) / "complete.json"
        producer()._fresh_json(output, value)
        self.assertEqual(output.read_bytes(),
            (json.dumps(value, sort_keys=True, separators=(",", ":"), default=str) + "\n").encode("ascii"))

    def test_unsupported_object_is_refused_without_custom_stringification(self):
        calls = []

        class Opaque:
            def __str__(self):
                calls.append("unbounded custom stringification")
                return "arbitrary object accepted"

        try:
            self.refuse_before_open({"opaque": Opaque()})
        finally:
            self.assertEqual(calls, [])

    def test_cycle_is_refused_before_output(self):
        value = []
        value.append(value)
        self.refuse_before_open({"proof": value})

    def test_excessive_depth_is_refused_before_output(self):
        value = 0
        for _ in range(33):
            value = [value]
        self.refuse_before_open(value)

    def test_container_count_is_refused_before_output(self):
        self.refuse_before_open({"k%04d" % index: 0 for index in range(4097)})

    def test_nonfinite_float_is_refused_before_output(self):
        for number in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(number=number):
                self.refuse_before_open({"proof": number})

    def test_outside_signed_int64_is_refused_before_output(self):
        for number in (2**63, -2**63 - 1):
            with self.subTest(number=number):
                self.refuse_before_open({"count": number})

    def test_astral_escaping_overflows_complete_report_before_output(self):
        # Each code point expands to12 ASCII JSON bytes. The22 repeated strings
        # require17,301,504 payload bytes before delimiters; retain any old write.
        value = {"proof": ["\U0001f600" * 65536] * 22}
        self.refuse_before_open(value)


if __name__ == "__main__":
    unittest.main()
