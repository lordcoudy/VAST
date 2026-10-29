"""Finalizer allocation boundaries with tiny CSVs and doubled external effects."""
import csv
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_physical_io_v1 import PhysicalRootCustodyV1
from tests.fixtures import accepted_policy_native_fixture_v2 as native
from tests.fixtures import accepted_policy_physical_fixture_v2 as fixture


class FinalizerReached(AssertionError):
    pass


class FinalizerBoundsTests(unittest.TestCase):
    def run_finalizer(self, *, frames=1, ingress=1, extra_header=False,
                      long_field=False, long_run=False, allow_path=False,
                      forbid_hash=False, unknown_hash=False, oversized_hash=None):
        root = Path.cwd()
        payloads = {"runtime.json": b'{"bundles":[{"arm_id":"arm","path":"bundle"}]}'}
        for name, count in (("frames.csv", frames), ("ingress_ledger.csv", ingress)):
            columns = list(native._FIXTURE_SIDECAR_SPECS_V2[name][0])
            if extra_header and name == "frames.csv":
                columns.append("unknown_column")
            output = io.StringIO(newline="")
            writer = csv.writer(output, lineterminator="\n")
            writer.writerow(columns)
            values = ["stream" if key == "stream_id" else "cohort" if key == "cohort_id" else "1" for key in columns]
            if long_field and name == "frames.csv":
                values[columns.index("stream_id")] = "s" * 513
            for _ in range(count):
                writer.writerow(values)
            payloads[name] = output.getvalue().encode("ascii")
        self.calls, self.pandas_calls, self.writes = [], [], []
        calls, writes = self.calls, self.writes

        class Custody:
            def __enter__(self):
                return self

            def __exit__(self, *ignored):
                return False

            def verify(self):
                pass

            def read_descriptor(self, path, *, label, maximum, capture=False):
                name = Path(path).name
                calls.append((name, maximum, capture))
                if name == oversized_hash and not capture:
                    raise ValueError("controlled hash-file size refusal")
                raw = payloads.get(name, b"controlled hash bytes\n")
                return {"path": name, "size_bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest()}, raw if capture else None

        class Writer:
            def __enter__(self):
                return self

            def __exit__(self, *ignored):
                return False

            def write(self, text):
                writes.append(text)
                return len(text)

        real_read = fixture.pd.read_csv

        def pandas_read(source, **kwargs):
            self.pandas_calls.append((isinstance(source, io.BytesIO), kwargs.get("nrows")))
            if isinstance(source, Path):
                if not allow_path:
                    raise AssertionError("pandas received an unbounded path")
                source = io.BytesIO(payloads[source.name])
            return real_read(source, **kwargs)

        def whole_read(path):
            if forbid_hash:
                raise AssertionError("finalizer allocated an entire hash input")
            return payloads.get(path.name, b"controlled hash bytes\n")

        row = {"phase": "qualification_cell", "operation_id": "op", "arm_id": "arm",
               "run_id": "r" * 8193 if long_run else "run", "system": "gstreamer_custom",
               "scenario": "checkpoint_video_dag_shared", "codec": "h264", "policy": "cpu_only", "deadline_ms": 100.0,
               "descriptors": {"calibration": {"path": str(root / "unused-calibration")}}}
        prepared = {"root": root, "runtime": {"receipt_path": root / "runtime.json"},
                    "transaction": {key: root / key for key in ("candidate_manifest_path", "candidate_receipt_path",
                        "candidate_index_path", "bootstrap_mapping_path", "bootstrap_receipt_path", "transaction_receipt_path")},
                    "preprocessing": {"contract_path": root / "contract", "receipt_path": root / "receipt"}}
        native_value = {"operations": [{"operation": row,
            "original": {"outputs": {"measurement_dir": str(root / "no-measurements")}},
            "source_plan": {"topology_kind": "shared_video_dag"}}]}
        names = ("unknown.csv",) if unknown_hash else fixture._acceptance_evidence_files("cpu_only")
        self.names, self.payloads = names, payloads
        with patch.object(PhysicalRootCustodyV1, "open", return_value=Custody()), \
                patch.object(Path, "read_bytes", autospec=True, side_effect=whole_read), \
                patch.object(Path, "open", return_value=Writer()) as opened, \
                patch.object(fixture.pd, "read_csv", side_effect=pandas_read), \
                patch.object(fixture, "schedule_fingerprint_for_records", return_value="f" * 64), \
                patch.object(fixture, "_acceptance_evidence_files", return_value=names), \
                patch.object(fixture, "finalize_checkpoint_qualification_pilot_acceptance_v1",
                    side_effect=FinalizerReached("default finalizer boundary")):
            self.opened = opened
            fixture.finalize_fixture_qualification_cells_v2(prepared=prepared, native=native_value,
                guardian_authority_path=root / "unused-authority")

    def test_csv_files_are_bounded_before_pandas_and_rows_have_limits(self):
        with self.assertRaises(FinalizerReached):
            self.run_finalizer()
        captures = [row for row in self.calls if row[2] and row[0] != "runtime.json"]
        self.assertEqual(captures, [("frames.csv", 512 * 1024, True), ("ingress_ledger.csv", 1024**2, True)])
        self.assertEqual(self.pandas_calls, [(True, 986), (True, 987)])

    def test_frames_row_overflow_refuses_before_pandas(self):
        with self.assertRaises(ValueError):
            self.run_finalizer(frames=986, allow_path=True)
        self.assertEqual(self.pandas_calls, [])

    def test_ingress_row_overflow_refuses_before_its_pandas_allocation(self):
        with self.assertRaises(ValueError):
            self.run_finalizer(ingress=987, allow_path=True)
        self.assertEqual(len(self.pandas_calls), 1)

    def test_unexpected_csv_header_refuses_before_pandas(self):
        with self.assertRaises(ValueError):
            self.run_finalizer(extra_header=True, allow_path=True)
        self.assertEqual(self.pandas_calls, [])

    def test_oversized_csv_record_refuses_before_pandas(self):
        with self.assertRaises(ValueError):
            self.run_finalizer(long_field=True, allow_path=True)
        self.assertEqual(self.pandas_calls, [])

    def test_hashes_stream_with_each_existing_file_role_cap(self):
        with self.assertRaises(FinalizerReached):
            self.run_finalizer(allow_path=True, forbid_hash=True)
        hashed = [row for row in self.calls if not row[2]]
        expected = [(name, native._FIXTURE_SIDECAR_SPECS_V2[name][3] if name in
                     native._FIXTURE_SIDECAR_SPECS_V2 else 64 * 1024**2, False) for name in self.names]
        self.assertEqual(hashed, expected)
        candidate = json.loads(self.writes[0])
        self.assertEqual(candidate["evidence_sha256"], {name: hashlib.sha256(
            self.payloads.get(name, b"controlled hash bytes\n")).hexdigest() for name in self.names})

    def test_unknown_hash_role_refuses_before_opening_candidate(self):
        with self.assertRaises(ValueError):
            self.run_finalizer(allow_path=True, unknown_hash=True)
        self.opened.assert_not_called()

    def test_oversized_hash_input_refuses_before_candidate(self):
        for name in ("policy_decisions.csv", "publication_policy_decisions.jsonl"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.run_finalizer(allow_path=True, oversized_hash=name)
            self.opened.assert_not_called()

    def test_candidate_encoding_refuses_over8KiB_before_open(self):
        with self.assertRaises(ValueError):
            self.run_finalizer(allow_path=True, long_run=True)
        self.opened.assert_not_called()

    def test_valid_candidate_remains_canonical_ascii_json_with_final_lf(self):
        with self.assertRaises(FinalizerReached):
            self.run_finalizer(allow_path=True)
        self.assertEqual(len(self.writes), 1)
        raw = self.writes[0]
        self.assertLessEqual(len(raw.encode("ascii")), 8192)
        self.assertEqual(raw, json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    unittest.main()
