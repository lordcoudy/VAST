"""Composed owner/sink facts retain known returns and distinct stage failures."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_native_fixture_v2 as native


class ControlledFile:
    def __init__(self, *, close_error=None, flush_error=None, write_action=None):
        self.prefix = ""
        self.close_error, self.flush_error, self.write_action = close_error, flush_error, write_action
        self.write_calls = 0

    def write(self, text):
        self.write_calls += 1
        if self.write_action is not None:
            return self.write_action(self, text)
        self.prefix += text
        return len(text)

    def flush(self):
        if self.flush_error is not None:
            raise self.flush_error

    def fileno(self):
        return 9123

    def close(self):
        if self.close_error is not None:
            raise self.close_error


class FixtureSidecarWriteFactsTests(unittest.TestCase):
    def owner_failure(self, stream, emit):
        with patch.object(Path, "open", return_value=stream), \
                patch.object(native.pd.DataFrame, "to_csv", side_effect=emit), patch("os.fsync"):
            with self.assertRaises(native._FixtureSidecarWriteErrorV2) as caught:
                native._write_fixture_sidecar_table_v2(Path("write-facts-output-never-created"),
                    "frames.csv", native.FRAME_COLUMNS, [])
        return caught.exception

    def test_short_return_stays_known_through_owner_and_close(self):
        def short(stream, text):
            stream.prefix += text[:2]
            return 2

        for failed_close in (False, True):
            secondary = OSError("controlled close after known prefix") if failed_close else None
            stream = ControlledFile(close_error=secondary, write_action=short)
            with self.subTest(failed_close=failed_close):
                error = self.owner_failure(stream, lambda sink, **unused: sink.write("abcd"))
                self.assertEqual(stream.prefix, "ab")
                self.assertEqual(error.facts["accepted_text_bytes"], 2)
                self.assertFalse(error.facts["write_extent_unknown"])
                self.assertFalse(error.facts["flush_completed"])
                self.assertEqual(error.facts["close_completed"], not failed_close)
                self.assertEqual(error.secondary, (secondary,) if failed_close else ())

    def test_preforward_refusal_keeps_zero_known_extent(self):
        for kind in ("overflow", "nonascii"):
            stream = ControlledFile()

            def emit(sink, **unused):
                # Fixed frames header is below4KiB; this never allocates payload data.
                sink.write("x" * (sink.limit + 1) if kind == "overflow" else "\u00e9")

            with self.subTest(kind=kind):
                error = self.owner_failure(stream, emit)
                self.assertEqual(stream.write_calls, 0)
                self.assertEqual(error.facts["accepted_text_bytes"], 0)
                self.assertFalse(error.facts["write_extent_unknown"])
                self.assertTrue(error.facts["close_completed"])

    def test_flush_and_close_failures_leave_exact_submitted_prefix(self):
        for failed_close in (False, True):
            primary = OSError("controlled flush")
            secondary = OSError("controlled close") if failed_close else None
            stream = ControlledFile(flush_error=primary, close_error=secondary)
            with self.subTest(failed_close=failed_close):
                error = self.owner_failure(stream, lambda sink, **unused: sink.write("abcd"))
                self.assertIs(error.primary, primary)
                self.assertEqual(error.facts["accepted_text_bytes"], 4)
                self.assertFalse(error.facts["write_extent_unknown"])
                self.assertFalse(error.facts["flush_completed"])
                self.assertFalse(error.facts["fsync_completed"])
                self.assertEqual(error.facts["close_completed"], not failed_close)
                self.assertEqual(error.secondary, (secondary,) if failed_close else ())

    def test_stream_write_raise_keeps_prior_known_prefix_and_unknown_deposit(self):
        primary = OSError("controlled second write")

        def action(stream, text):
            if stream.write_calls == 2:
                raise primary
            stream.prefix += text
            return len(text)

        stream = ControlledFile(write_action=action)

        def emit(sink, **unused):
            sink.write("ab")
            sink.write("cd")

        error = self.owner_failure(stream, emit)
        self.assertIs(error.primary, primary)
        self.assertEqual(error.facts["accepted_text_bytes"], 2)
        self.assertTrue(error.facts["write_extent_unknown"])
        self.assertTrue(error.facts["close_completed"])

    def test_unusable_write_returns_keep_prior_prefix_and_unknown_deposit(self):
        for result in (None, True, 9, "2"):
            def action(stream, text):
                if stream.write_calls == 2:
                    return result
                stream.prefix += text
                return len(text)

            stream = ControlledFile(write_action=action)

            def emit(sink, **unused):
                sink.write("ab")
                sink.write("cd")

            with self.subTest(result=result):
                error = self.owner_failure(stream, emit)
                self.assertEqual(error.facts["accepted_text_bytes"], 2)
                self.assertTrue(error.facts["write_extent_unknown"])
                self.assertTrue(error.facts["close_completed"])


if __name__ == "__main__":
    unittest.main()
