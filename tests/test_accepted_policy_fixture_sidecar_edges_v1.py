"""Review-found sidecar failure paths, with memory-only controlled doubles."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests import test_accepted_policy_fixture_sidecar_bounds_v1 as sidecar_tests
from tests.fixtures import accepted_policy_native_fixture_v2 as native


class FixtureSidecarFailureEdgesTests(unittest.TestCase):
    def test_dataframe_failure_keeps_original_and_prior_table_facts(self):
        primary = OSError("controlled dataframe failure")
        prior = {"controlled_prior_fact": True}
        metadata = {"run_id": "r", "observations": [], "source_sha256_by_stream": {},
            "canonical_frames": {"input:0:1": {"trace_id": "r:0:1", "stream_id": 0, "frame_id": 1}},
            "limits": {"coordinate": {"system": "gstreamer_custom", "resource": "cpu", "codec": "h264",
                "topology_kind": "shared_video_dag"}, "completed_samples_per_branch": 1}}
        policies = native.pd.DataFrame(columns=["trace_id", "stage"])
        original = native._write_fixture_sidecar_table_v2

        def staged_writer(output, filename, columns, rows):
            if filename == "frames.csv":
                return prior
            with patch.object(native.pd, "DataFrame", side_effect=primary):
                return original(output, filename, columns, rows)

        with patch.object(native.pd, "read_csv", return_value=policies), \
                patch.object(native, "_write_fixture_sidecar_table_v2", side_effect=staged_writer), \
                patch.object(Path, "open", side_effect=AssertionError("construction failure reached output")) as opened:
            with self.assertRaises(Exception) as caught:
                native._write_native_sidecars_v1(Path("sidecar-output-never-created"),
                    sidecar_tests.verified_fixture_manifest(), metadata)
        self.assertIsInstance(caught.exception, native._FixtureSidecarWriteErrorV2)
        self.assertIs(caught.exception.primary, primary)
        self.assertEqual(caught.exception.secondary, ())
        self.assertEqual(caught.exception.facts["failure_stage"], "dataframe")
        self.assertFalse(caught.exception.facts["open_completed"])
        self.assertEqual(caught.exception.completed, {"frames.csv": prior})
        opened.assert_not_called()

    def test_same_exception_from_primary_and_close_is_not_duplicated(self):
        for stage in ("write", "fsync"):
            primary = OSError("same controlled failure object")
            stream = sidecar_tests.MemoryFile(close_error=primary)
            with self.subTest(stage=stage), patch.object(Path, "open", return_value=stream), \
                    patch("os.fsync", side_effect=primary if stage == "fsync" else None):
                if stage == "write":
                    with patch.object(native.pd.DataFrame, "to_csv", side_effect=primary):
                        with self.assertRaises(native._FixtureSidecarWriteErrorV2) as caught:
                            native._write_fixture_sidecar_table_v2(Path("sidecar-output-never-created"),
                                "frames.csv", native.FRAME_COLUMNS, [])
                else:
                    with self.assertRaises(native._FixtureSidecarWriteErrorV2) as caught:
                        native._write_fixture_sidecar_table_v2(Path("sidecar-output-never-created"),
                            "frames.csv", native.FRAME_COLUMNS, [])
                self.assertIs(caught.exception.primary, primary)
                self.assertEqual(caught.exception.secondary, ())
                self.assertFalse(caught.exception.facts["close_completed"])


if __name__ == "__main__":
    unittest.main()
