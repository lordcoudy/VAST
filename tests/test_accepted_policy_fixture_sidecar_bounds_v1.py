"""Fixed artificial sidecar geometry and unchanged pandas output, in memory."""
from io import StringIO
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_native_fixture_v2 as native
from tests.test_accepted_policy_production_validation import verified_fixture_manifest


# Existing production column lists; these are twelve fixture outputs only.
TABLES = (
    ("frames.csv", native.FRAME_COLUMNS, 985, 512, 512 * 1024),
    ("frame_events.csv", native.FRAME_EVENT_COLUMNS, 15774, 1024, 16 * 1024**2),
    ("resource_events.csv", native.RESOURCE_EVENT_COLUMNS, 15774, 1024, 16 * 1024**2),
    ("ingress_ledger.csv", native.INGRESS_LEDGER_COLUMNS, 986, 1024, 1024**2),
    ("branch_terminals.csv", native.BRANCH_TERMINAL_COLUMNS, 3944, 2048, 8 * 1024**2),
    ("topology_events.csv", native.TOPOLOGY_EVENT_COLUMNS, 24625, 2048, 64 * 1024**2),
    ("reset_evidence.csv", native.RESET_EVIDENCE_COLUMNS, 30, 1024, 32 * 1024),
    ("drop_counters.csv", native.DROP_COUNTER_COLUMNS, 6, 512, 4 * 1024),
    ("stage_contracts.csv", native.STAGE_CONTRACT_COLUMNS, 48, 2048, 128 * 1024),
    ("resource_intervals.csv", native.RESOURCE_INTERVAL_COLUMNS, 12805, 1024, 16 * 1024**2),
    ("fanout_work_counters.csv", native.FANOUT_WORK_COUNTER_COLUMNS, 3940, 1024, 4 * 1024**2),
    ("hardware_resource_samples.csv", native.HARDWARE_RESOURCE_SAMPLE_COLUMNS, 3, 512, 2 * 1024),
)


class MemoryFile(StringIO):
    def __init__(self, close_error=None):
        super().__init__(newline="")
        self.saved = None
        self.close_error = close_error
        self.close_attempted = False

    def fileno(self):
        return 9123

    def close(self):
        self.close_attempted = True
        self.saved = self.getvalue()
        super().close()
        if self.close_error is not None:
            raise self.close_error

    def __del__(self):
        # Only an explicit owner close injects failures; GC owns no real file.
        StringIO.close(self)


class FixtureSidecarBoundsTests(unittest.TestCase):
    def test_selected_run_arm_limits_refuse_before_allocation(self):
        for field, value in (("run_id", "r" * 65), ("arm_id", "a" * 69)):
            with self.subTest(field=field), \
                    patch.object(Path, "mkdir", side_effect=AssertionError("name reached allocation")):
                with self.assertRaisesRegex(ValueError, "run|arm"):
                    native.write_native_policy_fixture_cell_v2(
                        output_dir=Path("sidecar-output-never-created"), capability=verified_fixture_manifest(),
                        system="gstreamer_custom", resource="cpu", codec="h264",
                        topology_kind="independent_processes", **{field: value})

    def test_run64_arm68_reach_only_allocation_marker(self):
        class AllocationReached(RuntimeError):
            pass

        with patch.object(Path, "mkdir", side_effect=AllocationReached), \
                patch.object(native, "NativePolicyRuntimeCoordinator", side_effect=AssertionError("generation is unselected")):
            with self.assertRaises(AllocationReached):
                native.write_native_policy_fixture_cell_v2(
                    output_dir=Path("sidecar-output-never-created"), capability=verified_fixture_manifest(),
                    system="gstreamer_custom", resource="cpu", codec="h264",
                    topology_kind="independent_processes", run_id="r" * 64, arm_id="a" * 68)

    def bound(self, filename, columns, rows):
        function = getattr(native, "_fixture_sidecar_table_bound_v2", None)
        self.assertTrue(callable(function), "fixed sidecar pre-encoding bounds are absent")
        return function(filename, columns, rows)

    def writer(self, filename, columns, rows):
        function = getattr(native, "_write_fixture_sidecar_table_v2", None)
        self.assertTrue(callable(function), "bounded fixture pandas forwarding is absent")
        return function(Path("sidecar-output-never-created"), filename, columns, rows)

    def sink(self, stream, limit):
        constructor = getattr(native, "_FixtureSidecarSinkV2", None)
        self.assertTrue(callable(constructor), "fixture sidecar sink is absent")
        facts = {"accepted_text_bytes": 0, "write_extent_unknown": False}
        return constructor(stream, limit, facts), facts

    def run_existing_boundary(self, replacement):
        metadata = {"run_id": "r", "observations": [], "source_sha256_by_stream": {},
            "canonical_frames": {"input:0:1": {"trace_id": "r:0:1", "stream_id": 0, "frame_id": 1}},
            "limits": {"coordinate": {"system": "gstreamer_custom", "resource": "cpu", "codec": "h264",
                "topology_kind": "shared_video_dag"}, "completed_samples_per_branch": 1}}
        policies = native.pd.DataFrame(columns=["trace_id", "stage"])
        with patch.object(native.pd, "read_csv", return_value=policies), \
                patch.object(native, "native_frame_row", side_effect=replacement), \
                patch.object(native.pd.DataFrame, "to_csv", side_effect=AssertionError("unbounded sidecar reached serialization")), \
                patch.object(Path, "open", side_effect=AssertionError("unbounded sidecar opened output")):
            with self.assertRaisesRegex(ValueError, "sidecar"):
                native._write_native_sidecars_v1(Path("sidecar-output-never-created"),
                    verified_fixture_manifest(), metadata)

    def test_actual_sidecar_entrypoint_refuses_large_field_before_serialization(self):
        original = native.native_frame_row

        def replacement(**values):
            return {**original(**values), "detector": "x" * 4097}

        self.run_existing_boundary(replacement)

    def test_actual_sidecar_entrypoint_refuses_callbacks_before_serialization(self):
        class NotAScalar:
            def __str__(self):
                raise AssertionError("unsupported scalar formatted itself")

        original = native.native_frame_row

        def replacement(**values):
            return {**original(**values), "detector": NotAScalar()}

        self.run_existing_boundary(replacement)

    def test_fixed_twelve_tables_and_empty_header_geometry(self):
        expected = getattr(native, "_FIXTURE_SIDECAR_SPECS_V2", None)
        self.assertIsNotNone(expected, "fixed sidecar roster is absent")
        self.assertEqual(set(expected), {row[0] for row in TABLES})
        for name, columns, count, row_cap, file_cap in TABLES:
            with self.subTest(name=name):
                self.assertEqual(expected[name], (columns, count, row_cap, file_cap))
                self.assertLessEqual(self.bound(name, columns, []), file_cap)

    def test_excess_rows_and_foreign_columns_refuse_before_dataframe_or_file(self):
        for name, columns, count, _, _ in TABLES:
            with self.subTest(name=name), \
                    patch.object(native.pd, "DataFrame", side_effect=AssertionError("rows reached dataframe")), \
                    patch.object(Path, "open", side_effect=AssertionError("rows reached file")):
                with self.assertRaisesRegex(ValueError, "sidecar"):
                    self.writer(name, columns, [{}] * (count + 1))
                with self.assertRaisesRegex(ValueError, "sidecar"):
                    self.writer(name, list(reversed(columns)), [])

    def test_scalar_refusals_do_not_format_values(self):
        class NotAScalar:
            def __str__(self):
                raise AssertionError("scalar callback")

        for value in ("x" * 4097, "\u00e9", 2**63, -(2**63) - 1,
                      math.inf, -math.inf, math.nan, NotAScalar(), ["x"]):
            with self.subTest(kind=type(value).__name__):
                with self.assertRaisesRegex(ValueError, "sidecar"):
                    self.bound("frames.csv", native.FRAME_COLUMNS, [{"detector": value}])

    def test_row_escaping_and_conservative_numeric_geometry(self):
        columns = native.FRAME_COLUMNS
        ordinary = self.bound("frames.csv", columns, [{"detector": "abc"}])
        quoted = self.bound("frames.csv", columns, [{"detector": 'a"b'}])
        self.assertGreater(quoted, ordinary)
        # Both endpoints are admitted without formatting unbounded integers.
        for value in (-(2**63), 2**63 - 1, -1.7976931348623157e308, True, None):
            self.assertLessEqual(self.bound("frames.csv", columns, [{"frame_id": value}]), 512 * 1024)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            self.bound("frames.csv", columns, [{"detector": '"' * 256}])

    def test_all_twelve_preserve_original_pandas_bytes_and_persistence_facts(self):
        for name, columns, _, _, _ in TABLES:
            rows = [{columns[0]: 2, columns[1]: "r", columns[-1]: 'CSV,"quoted"\nline'},
                    {columns[0]: 2.0, columns[1]: "r", columns[-1]: None},
                    {columns[1]: "r", "ignored_extra": object()}]
            original = StringIO(newline="")
            native.pd.DataFrame(rows, columns=columns).to_csv(original, index=False)
            stream = MemoryFile()
            with self.subTest(name=name), patch.object(Path, "open", return_value=stream) as opened, \
                    patch("os.fsync") as synced:
                facts = self.writer(name, columns, rows)
                self.assertEqual(stream.saved, original.getvalue())
                self.assertTrue(stream.close_attempted)
                self.assertEqual(facts["accepted_text_bytes"], len(stream.saved.encode("ascii")))
                self.assertTrue(facts["flush_completed"])
                self.assertTrue(facts["fsync_completed"])
                self.assertTrue(facts["close_completed"])
                self.assertFalse(facts["write_extent_unknown"])
                synced.assert_called_once_with(9123)
                self.assertEqual(opened.call_args.kwargs["encoding"], "utf-8")
                self.assertEqual(opened.call_args.kwargs["newline"], "")

    def test_sink_overflow_refuses_before_forwarding(self):
        stream = StringIO()
        sink, facts = self.sink(stream, 5)
        self.assertEqual(sink.write("abc"), 3)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            sink.write("def")
        self.assertEqual(stream.getvalue(), "abc")
        self.assertEqual(facts["accepted_text_bytes"], 3)
        self.assertFalse(facts["write_extent_unknown"])

    def test_sink_nonascii_refuses_before_forwarding(self):
        stream = StringIO()
        sink, facts = self.sink(stream, 8)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            sink.write("\u00e9")
        self.assertEqual(stream.getvalue(), "")
        self.assertEqual(facts["accepted_text_bytes"], 0)

    def test_sink_short_write_preserves_known_prefix(self):
        class ShortFile:
            def write(self, value):
                return 2

        sink, facts = self.sink(ShortFile(), 8)
        with self.assertRaisesRegex(ValueError, "sidecar"):
            sink.write("abcd")
        self.assertEqual(facts["accepted_text_bytes"], 2)
        self.assertFalse(facts["write_extent_unknown"])

    def test_write_failure_and_close_failure_preserve_primary_and_secondary(self):
        primary, secondary = OSError("original write"), OSError("distinct close")
        stream = MemoryFile(close_error=secondary)
        with patch.object(Path, "open", return_value=stream), \
                patch.object(native.pd.DataFrame, "to_csv", side_effect=primary), patch("os.fsync"):
            with self.assertRaises(ValueError) as caught:
                self.writer("frames.csv", native.FRAME_COLUMNS, [])
        self.assertIs(caught.exception.primary, primary)
        self.assertEqual(caught.exception.secondary, (secondary,))
        self.assertTrue(caught.exception.facts["close_attempted"])
        self.assertFalse(caught.exception.facts["close_completed"])
        self.assertTrue(caught.exception.facts["write_extent_unknown"])

    def test_fsync_failure_and_close_failure_preserve_primary_and_secondary(self):
        primary, secondary = OSError("original fsync"), OSError("distinct close")
        stream = MemoryFile(close_error=secondary)
        with patch.object(Path, "open", return_value=stream), patch("os.fsync", side_effect=primary):
            with self.assertRaises(ValueError) as caught:
                self.writer("frames.csv", native.FRAME_COLUMNS, [])
        self.assertIs(caught.exception.primary, primary)
        self.assertEqual(caught.exception.secondary, (secondary,))
        self.assertTrue(caught.exception.facts["flush_completed"])
        self.assertFalse(caught.exception.facts["fsync_completed"])
        self.assertFalse(caught.exception.facts["close_completed"])

    def test_output_collision_refuses_without_replacement(self):
        primary = FileExistsError("existing sidecar")
        with patch.object(Path, "open", side_effect=primary) as opened:
            with self.assertRaises(ValueError) as caught:
                self.writer("frames.csv", native.FRAME_COLUMNS, [])
        self.assertIs(caught.exception.primary, primary)
        self.assertEqual(caught.exception.secondary, ())
        self.assertEqual(opened.call_args.args, ("x",))


if __name__ == "__main__":
    unittest.main()
