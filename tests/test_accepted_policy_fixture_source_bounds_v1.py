"""Pre-serialization limits for the artificial engine's actual reply tables."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_v1 as fixture


class FixtureSourceBoundsTests(unittest.TestCase):
    def test_del_escape_expansion_is_charged_before_canonicalization(self):
        with patch.object(fixture, "canonical_json_v1", side_effect=AssertionError("encoded too early")) as encode:
            with self.assertRaisesRegex(ValueError, "bound"):
                fixture._reply_table("image_replies", {"image": {"value": "\x7f" * (1024 * 1024)}}, inspection=True)
            encode.assert_not_called()

    def test_oversized_string_is_refused_before_canonicalization(self):
        with patch.object(fixture, "canonical_json_v1", side_effect=AssertionError("encoded too early")) as encode:
            with self.assertRaisesRegex(ValueError, "bound"):
                fixture._reply_table("image_replies", {"image": {"value": "x" * (8 * 1024 * 1024 + 1)}}, inspection=True)
            encode.assert_not_called()

    def test_recursive_and_nonfinite_values_are_refused_before_encoding(self):
        cycle = {}; cycle["cycle"] = cycle
        for value in (cycle, {"float": math.nan}, {"float": math.inf}, {"integer": 1 << 10000}):
            with self.subTest(value_type=next(iter(value))):
                with patch.object(fixture, "canonical_json_v1", side_effect=AssertionError("encoded too early")) as encode:
                    with self.assertRaises(ValueError):
                        fixture._reply_table("probe_replies", {"image": value}, inspection=False)
                    encode.assert_not_called()

    def test_table_count_is_checked_before_sorting_or_encoding_values(self):
        with patch.object(fixture, "canonical_json_v1", side_effect=AssertionError("encoded too early")) as encode:
            with self.assertRaisesRegex(ValueError, "bound"):
                fixture._reply_table("image_replies", {str(i): {} for i in range(4097)}, inspection=True)
            encode.assert_not_called()

    def test_valid_reply_representation_is_unchanged(self):
        self.assertEqual(fixture._reply_table("probe_replies", {"x": {"z": "quote\"", "a": 1}}, inspection=False),
            'static const struct reply probe_replies[] = {\n    {"x", "{\\"a\\":1,\\"z\\":\\"quote\\\\\\"\\"}"},\n    {NULL, NULL}\n};')

    def test_invalid_second_table_is_refused_before_first_table_encoding(self):
        with patch.object(fixture, "canonical_json_v1", side_effect=AssertionError("encoded too early")) as encode:
            with self.assertRaises(ValueError):
                fixture.build_fixture_source_v1("/* FIXTURE_REPLY_TABLES */", "/fresh/state",
                    {"valid": {}}, {"invalid": {"x": float("nan")}})
            encode.assert_not_called()

    def test_source_contains_actual_fresh_bindings(self):
        raw = fixture.build_fixture_source_v1("before\n/* FIXTURE_REPLY_TABLES */\nafter", "/fresh/state",
            {"image": {"Id": "fresh"}}, {})
        self.assertTrue(raw.startswith(b'#define STATE_FILE "/fresh/state"\n'))
        self.assertIn(b'#define DAEMON_ID "\\"fixture-daemon-1\\""\n', raw)
        self.assertIn(b'fresh', raw)
        self.assertNotIn(b'FIXTURE_REPLY_TABLES', raw)


if __name__ == "__main__":
    unittest.main()
