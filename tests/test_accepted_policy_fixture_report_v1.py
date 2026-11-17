"""Producer report pre-encoding refusals; no real fixture or engine execution."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

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
                producer()._fresh_json(output, value,
                    absolute_deadline_ns=time.monotonic_ns() + 60_000_000_000)
        finally:
            self.assertFalse(output.exists(), "report refusal opened its output")

    def test_complete_supported_fields_keep_exact_original_json_bytes(self):
        value = {"proof": {"path": Path("relative/path"), "rows": [True, None, 1, -1, 0.5]},
                 "unicode": "\u00e9\U0001f600", "escaped": 'quote" slash\\ newline\n'}
        output = Path(tempfile.mkdtemp(prefix="fixture-report-")) / "complete.json"
        producer()._fresh_json(output, value,
            absolute_deadline_ns=time.monotonic_ns() + 60_000_000_000)
        self.assertEqual(output.read_bytes(),
            (json.dumps(value, sort_keys=True, separators=(",", ":"), default=str) + os.linesep).encode("ascii"))

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


class FixtureReportGeometryTests(unittest.TestCase):
    def report(self):
        from tests.fixtures import accepted_policy_fixture_report_v1
        return accepted_policy_fixture_report_v1

    def test_exact_byte_limit_and_one_over_refuse_before_encoder(self):
        report = self.report()
        self.assertEqual(report.fixture_report_bytes_v1("x" * 61, limit=64), b'"' + b"x" * 61 + b'"\n')
        with patch.object(report.json, "dumps", side_effect=AssertionError("overflow reached encoder")):
            with self.assertRaisesRegex(ValueError, "complete byte bound"):
                report.fixture_report_bytes_v1("x" * 62, limit=64)

    def test_unicode_controls_and_standard_paths_keep_exact_encoding(self):
        from pathlib import PurePosixPath, PureWindowsPath
        report = self.report()
        for text in ("\U0001f600", "\u00e9", "\x00", "\b\t\n\f\r", '"\\', "\x7f"):
            expected = (json.dumps(text, ensure_ascii=True) + "\n").encode("ascii")
            with self.subTest(text=text):
                self.assertEqual(report.fixture_report_bytes_v1(text, limit=len(expected)), expected)
                with patch.object(report.json, "dumps", side_effect=AssertionError("escaping overflow encoded")):
                    with self.assertRaises(ValueError):
                        report.fixture_report_bytes_v1(text, limit=len(expected) - 1)
        for value in (PurePosixPath("/" + "x" * 511), PureWindowsPath("C:/example/file"), Path("relative/path")):
            self.assertEqual(report.fixture_report_bytes_v1(value),
                (json.dumps(str(value)) + "\n").encode("ascii"))

    def test_exact_node_limit_and_one_over_refuse_before_encoder(self):
        report = self.report()
        value = [[0] * 15 for _ in range(4096)]
        value[0].pop()  # root +4095*(list+15scalars) +(list+14scalars) ==65536
        expected = (json.dumps(value, separators=(",", ":")) + "\n").encode("ascii")
        self.assertEqual(report.fixture_report_bytes_v1(value), expected)
        value[0].append(0)
        with patch.object(report.json, "dumps", side_effect=AssertionError("node overflow encoded")):
            with self.assertRaisesRegex(ValueError, "node/depth bound"):
                report.fixture_report_bytes_v1(value)

    def test_exact_depth_limit_and_one_over_refuse_before_encoder(self):
        report = self.report()
        value = 0
        for _ in range(32):
            value = [value]
        self.assertEqual(report.fixture_report_bytes_v1(value), b"[" * 32 + b"0" + b"]" * 32 + b"\n")
        with patch.object(report.json, "dumps", side_effect=AssertionError("depth overflow encoded")):
            with self.assertRaisesRegex(ValueError, "node/depth bound"):
                report.fixture_report_bytes_v1([value])

    def test_unsupported_subclasses_keys_strings_and_limits_do_not_encode(self):
        report, calls = self.report(), []

        class Text(str):
            def __str__(self):
                calls.append("callback")
                return "unsafe"

        class Rows(list):
            def __iter__(self):
                calls.append("callback")
                raise AssertionError("custom iteration")

        class Meta(type):
            def __eq__(cls, other):
                calls.append("metaclass equality")
                raise AssertionError("custom type equality")

        class PretendPath(metaclass=Meta):
            @property
            def parts(self):
                calls.append("custom parts")
                raise AssertionError("custom path lookup")

            def __str__(self):
                calls.append("custom path stringification")
                raise AssertionError("custom path stringification")

        for value in (Text("value"), Rows([1]), PretendPath(), {1: "integer key"}, "x" * 1048577):
            with self.subTest(kind=type(value).__name__), \
                    patch.object(report.json, "dumps", side_effect=AssertionError("unsupported input encoded")):
                with self.assertRaises(ValueError):
                    report.fixture_report_bytes_v1(value)
        with self.assertRaises(ValueError):
            report.fixture_report_bytes_v1({}, limit=True)
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
