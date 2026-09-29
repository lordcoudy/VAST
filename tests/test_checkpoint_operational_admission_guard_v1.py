"""Actual source admission gates, before retained state and producer ACK."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))
from benchmark_contract import ContractError
from checkpoint_admission import DirectAdmissionCoordinator, SourceBinding
from test_checkpoint_admission import BRANCHES, SOURCE_SHA256, admission_line


class OperationalAdmissionGuardTests(unittest.TestCase):
    def coordinator(self, limits=None):
        return DirectAdmissionCoordinator(
            run_id="source-bound-0001", topology_kind="shared_video_dag",
            branches=BRANCHES,
            bindings=[SourceBinding("stream-0-source-coordinator", 0, 700,
                                    "kpp_real_h264", SOURCE_SHA256, True)],
            operational_admission_limits=limits,
        )

    def accept(self, coordinator, sequence, offset):
        return coordinator.accept(
            admission_line(run_id="source-bound-0001", sequence=sequence,
                           pts_ns=sequence * 90_000, schedule_offset_ns=offset),
            observed_source_process_id="stream-0-source-coordinator", observed_pid=700,
        )

    def test_supported_cadence_accepts_original_values_at_boundary(self):
        runtime = self.coordinator({"max_admissions_per_stream": 281,
                                    "min_schedule_step_ns": 999_999_600})
        for sequence in range(1, 282):
            self.accept(runtime, sequence, (sequence - 1) * 999_999_600)
        records = runtime.admission_records()
        self.assertEqual(len(records), 281)
        self.assertEqual(records[-1]["schedule_offset_ns"], 280 * 999_999_600)

    def test_duration_fallback_is_rejected_before_allocating_second_admission(self):
        runtime = self.coordinator({"max_admissions_per_stream": 281,
                                    "min_schedule_step_ns": 999_999_600})
        self.accept(runtime, 1, 0)
        with self.assertRaisesRegex(ContractError, "cadence"):
            self.accept(runtime, 2, 1)
        self.assertEqual(len(runtime._admissions), 1)
        self.assertEqual(runtime._sequences["stream-0-source-coordinator"], 1)
        # A failed gate remains terminal, including if the caller tries to fix it.
        with self.assertRaises(ContractError):
            self.accept(runtime, 2, 1_000_000_000)

    def test_overflow_is_rejected_before_any_new_retained_identity(self):
        runtime = self.coordinator({"max_admissions_per_stream": 281,
                                    "min_schedule_step_ns": 999_999_600})
        for sequence in range(1, 282):
            self.accept(runtime, sequence, (sequence - 1) * 1_000_000_000)
        with self.assertRaisesRegex(ContractError, "count"):
            self.accept(runtime, 282, 281_000_000_000)
        self.assertEqual(len(runtime._admissions), 281)
        self.assertEqual(len(runtime._input_keys), 281)

    def test_observed_stream_substitution_fails_before_guard_state_changes(self):
        runtime = self.coordinator({"max_admissions_per_stream": 281,
                                    "min_schedule_step_ns": 999_999_600})
        message = json.loads(admission_line(run_id="source-bound-0001"))
        message["stream_id"] = 1
        message["admission_id"] = "source-bound-0001:1:admission:1"
        message["input_frame_key"] = f"kpp_real_h264:1:{SOURCE_SHA256}:0:90000"
        with self.assertRaisesRegex(ContractError, "stream"):
            runtime.accept(json.dumps(message),
                           observed_source_process_id="stream-0-source-coordinator", observed_pid=700)
        self.assertEqual(runtime.admission_records(), ())

    def test_inactive_path_preserves_existing_source_protocol(self):
        runtime = self.coordinator()
        self.accept(runtime, 1, 0)
        self.accept(runtime, 2, 1)
        self.assertEqual(len(runtime.admission_records()), 2)

    def test_unknown_or_relaxed_limits_are_not_a_supported_mode(self):
        for limits in ({"max_admissions_per_stream": 282, "min_schedule_step_ns": 999_999_600},
                       {"max_admissions_per_stream": 281, "min_schedule_step_ns": 1},
                       {"max_admissions_per_stream": True, "min_schedule_step_ns": 999_999_600},
                       {"max_admissions_per_stream": 281, "min_schedule_step_ns": 999_999_600,
                        "retry": True}):
            with self.subTest(limits=limits), self.assertRaises(ContractError):
                self.coordinator(limits)


if __name__ == "__main__":
    unittest.main()
