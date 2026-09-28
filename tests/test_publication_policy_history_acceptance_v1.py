from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import checkpoint_publication_runtime as runtime
import publication_q4_authority_source_request_v1 as source_request
from benchmark_contract import ContractError
from publication_acceptance_evidence import (
    FROZEN_POLICY_RUNTIME_HISTORY_JSONL as HISTORY,
    accepted_arm_evidence_files,
    pre_finalization_acceptance_evidence_files,
)
from tests.test_checkpoint_acceptance_metadata_binding import execution, metadata, write
from tests.test_checkpoint_native_policy_runtime import (
    coordinator, path_message, request_message, terminal_message,
)


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_row(columns, **values):
    return {**dict.fromkeys(columns, "fixture"), **values}


RESOURCE_ASSESSMENT = {
    "summary": {
        "resource_contract_version": 2,
        "evidence_accepted": True,
        "publication_bundle_bound": True,
        "full_resource_coverage_complete": True,
        "nvdec_busy_equivalent_ns": 123,
        "nvdec_counter_scope": "device_sample",
        "fanout_thread_cpu_time_ns": 456,
        "fanout_work_units": 789,
        "fanout_counter_scope": "per_trace_resource_work",
    }
}


class PublicationPolicyHistoryAcceptanceTests(unittest.TestCase):
    """Exercise file custody; graph/resource fixture mocks confer no qualification."""

    def publish_candidate(self, output: Path, *, policy="adaptive_weights", projected=True):
        output.mkdir()
        binding = execution()
        native = coordinator(policy)

        def issue(frame):
            request = request_message(frame_id=frame)
            response = native.handle_message(request["worker_id"], request)
            native.handle_message(request["worker_id"], path_message(response, request=request))
            return request, response

        def complete(pair):
            request, response = pair
            native.handle_message(request["worker_id"], terminal_message(response, request=request))

        if projected:
            warmup = issue(1)
        measured = issue(2 if projected else 1)
        if projected:
            complete(warmup)
        complete(measured)
        request, response = measured
        trace = "canonical-measurement-frame" if projected else request["trace_id"]
        native.promote(output, canonical_frames={request["input_frame_key"]: {
            "trace_id": trace, "stream_id": 0, "frame_id": request["frame_id"],
        }})
        if not projected:
            # A stock legacy record has neither projection metadata nor a history
            # leaf. Its original accepted bytes come from the actual coordinator.
            accepted = native._states[response["decision_id"]].accepted
            (output / "publication_policy_decisions.jsonl").write_text(
                json.dumps(accepted, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            (output / HISTORY).unlink(missing_ok=True)

        (output / "resource_events.csv").write_bytes(b"fixture-native-resource-events\n")

        common = {"schema_version": 1, "run_id": request["run_id"],
                  "trace_id": trace, "stream_id": 0, "frame_id": request["frame_id"]}
        frames = [record_row(runtime.FRAME_COLUMNS, **common, ingress_timestamp_ms=1000,
                            egress_timestamp_ms=1012, e2e_latency_ms=12, objects=1,
                            telemetry_source="native")]
        ledger = [record_row(runtime.INGRESS_LEDGER_COLUMNS, **common,
                            input_frame_key=request["input_frame_key"],
                            terminal_status="completed")]
        branches = [record_row(runtime.BRANCH_TERMINAL_COLUMNS, **common,
                              branch_id="plate_number")]
        topology = [record_row(runtime.TOPOLOGY_EVENT_COLUMNS, **common)]
        events = [record_row(runtime.FRAME_EVENT_COLUMNS, **common)]
        reset = [record_row(runtime.RESET_EVIDENCE_COLUMNS, run_id=request["run_id"])]
        drops = [record_row(runtime.DROP_COUNTER_COLUMNS, run_id=request["run_id"], stream_id=0)]
        stage_path = output.parent / "runtime_stage_contracts.csv"
        runtime._write_csv(stage_path, runtime.STAGE_CONTRACT_COLUMNS,
                           [record_row(runtime.STAGE_CONTRACT_COLUMNS, telemetry_source="native")])
        summary = {gate: True for gate in (
            "ingress_ledger_complete", "ingress_cohort_closed", "branch_terminal_trace_complete",
            "checkpoint_frame_aggregation_complete", "stage_semantic_contract_complete",
            "decoder_placement_verified", "resource_attribution_complete", "reset_state_verified",
        )}
        summary["c_obs_total_ms"] = 12
        run_result = SimpleNamespace(
            unresolved_frames=(), lifecycle_statuses={"fixture": ("READY", "DRAINED")},
            terminal_admission_audit={
                "engineering_terminal_accounting_complete": True,
                "engineering_cohort_closed_without_censoring": True,
                "measurement_schedule_fingerprint_sha256": "a" * 64,
            },
        )
        # Only unrelated graph conversion and semantic resource checks are
        # mocked. CSV writes, namespace selection, every file hash, candidate
        # persistence, rehash, metadata binding and acceptance commit stay real.
        with ExitStack() as stack:
            for name, value in {
                "_accepted_ingress_rows": (ledger, "fixture-measurement-cohort"),
                "_accepted_branch_rows": branches, "_accepted_frames": frames,
                "_accepted_topology_rows": topology, "_accepted_frame_event_rows": events,
                "_accepted_reset_rows": reset, "_accepted_drop_rows": drops,
                "summarize_sidecars": summary,
            }.items():
                stack.enter_context(mock.patch.object(runtime, name, return_value=value))
            for name in ("validate_stage_trace_coverage", "validate_drop_counters",
                         "write_provenance_labeled_sidecars", "validate_required_sidecars"):
                stack.enter_context(mock.patch.object(runtime, name))
            for name in ("canonicalize_frames_csv", "validate_frame_events", "validate_topology_events"):
                stack.enter_context(mock.patch.object(runtime, name, side_effect=lambda path, **kw: runtime.pd.read_csv(path)))
            candidate = runtime.publish_checkpoint_runtime(
                output_dir=output,
                plan={"system": "gstreamer_custom", "scenario": "checkpoint_video_dag_shared",
                      "benchmark_status": "supported", "decoder_placement": {"codec": "h265"},
                      "required_branches": ["plate_number"], "topology_kind": "shared_video_dag",
                      "streams": [{"stream_id": 0}]},
                scenario={"name": "checkpoint_video_dag_shared", "pipeline": []},
                dataset={"codec_variant": "h265", "streams": [{"stream_id": 0}]},
                result=run_result, reset_rows=(), reset_audit={"engineering_reset_state_complete": True},
                cohort_audit={"external_ingress_schedule_proven": True,
                              "measurement_schedule_fingerprint_sha256": "a" * 64},
                stage_contract_runtime_path=stage_path,
                worker_specs=[SimpleNamespace(native_event_source=True)],
                source_specs=[SimpleNamespace(native_source=True)],
                run_id=request["run_id"], policy=policy, deadline_ms=100.0,
                defer_full_resource_acceptance=True,
            )
        for name in runtime.FULL_RESOURCE_EVIDENCE_FILES:
            (output / name).write_bytes(("mocked-resource-assessment:" + name + "\n").encode())
        # Bind fixture authorities to the already emitted bytes. Do not let the
        # metadata helper replace the physical evidence with its placeholders.
        with mock.patch("tests.test_backend_publication_output_receipt.write_launcher_evidence"):
            write(output / "run_metadata.json", metadata(binding, output))
        return candidate, binding

    def finalize(self, output, candidate, binding):
        return runtime.finalize_checkpoint_publication_acceptance(
            output_dir=output, expected_run_id=candidate["run_id"],
            expected_system=candidate["system"], expected_scenario=candidate["scenario"],
            expected_codec=candidate["codec"], expected_policy=candidate["policy"],
            expected_deadline_ms=candidate["deadline_ms"], topology_kind=candidate["topology_kind"],
            hardware_collector_stopped=True, run_metadata_path=output / "run_metadata.json",
            expected_execution_binding=binding,
        )

    def source_template(self, output):
        pin = {"path": "fixture.json", "size_bytes": 1, "sha256": "b" * 64}
        sources = [{**pin, "path": name} for name in ("source.mp4", "source.json")]
        template = {
            "files": {role: dict(pin) for role in source_request.RUNTIME_MODULE_BY_SYSTEM["deepstream"].FILE_ROLES},
            "source_files": [{**item, "container_path": "/opt/input/" + item["path"]} for item in sources],
            "container_engine_socket": {"path": "/mock/docker.sock"},
            "endpoint_sockets": [{"container_path": "/mock/analytics.sock"}],
        }
        with mock.patch.object(source_request, "_socket_binding_from_live", return_value={"path": "/mock/socket"}), \
             mock.patch.object(source_request, "_endpoint_template", return_value=template["endpoint_sockets"]):
            return source_request._patch_runtime_template(
                custody=SimpleNamespace(root=output), template=template, system="deepstream",
                policy="adaptive_weights", codec="h265", dataset_files=sources,
                capability_descriptor=pin, calibration_descriptor=pin, static_map_descriptor=pin,
                execution_descriptor=pin, service={}, preprocessing_identity_sha256="c" * 64,
                scratch_root=str(output),
            )

    def test_source_builder_history_is_hashed_by_candidate_and_persisted_in_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "arm"
            candidate, binding = self.publish_candidate(output)
            source = self.source_template(output)
            candidate_names = set(source["evidence_mapping"]) - {
                "resource_intervals.csv", "fanout_work_counters.csv", "checkpoint_publication_candidate.json",
            }
            self.assertIn(HISTORY, candidate_names)
            expected = {name: file_sha(output / name) for name in candidate_names}
            self.assertEqual(candidate["evidence_sha256"], expected)
            candidate_path = output / "checkpoint_publication_candidate.json"
            self.assertEqual(json.loads(candidate_path.read_text())["evidence_sha256"], expected)
            candidate_bytes = candidate_path.read_bytes()
            history_bytes = (output / HISTORY).read_bytes()
            with mock.patch.object(runtime, "validate_full_resource_evidence", return_value=RESOURCE_ASSESSMENT) as validate:
                accepted = self.finalize(output, candidate, binding)
            validate.assert_called_once()
            self.assertEqual(set(accepted["evidence_sha256"]), set(accepted_arm_evidence_files(
                "adaptive_weights", full_resource=True, runtime_history=True,
            )))
            self.assertEqual(accepted["evidence_sha256"], {
                **expected, **{name: file_sha(output / name) for name in runtime.FULL_RESOURCE_EVIDENCE_FILES},
            })
            persisted = json.loads((output / "checkpoint_publication_acceptance.json").read_text())
            self.assertEqual(persisted, accepted)
            self.assertEqual(persisted["evidence_sha256"][HISTORY], hashlib.sha256(history_bytes).hexdigest())
            self.assertEqual((output / HISTORY).read_bytes(), history_bytes)
            self.assertEqual(candidate_path.read_bytes(), candidate_bytes)

    def test_mutated_history_blocks_acceptance_before_resource_assessment(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "arm"
            candidate, binding = self.publish_candidate(output)
            candidate_bytes = (output / "checkpoint_publication_candidate.json").read_bytes()
            original_sha = file_sha(output / HISTORY)
            with (output / HISTORY).open("ab") as stream:
                stream.write(b" \n")
            self.assertNotEqual(file_sha(output / HISTORY), original_sha)
            with mock.patch.object(runtime, "validate_full_resource_evidence", return_value=RESOURCE_ASSESSMENT) as validate:
                with self.assertRaisesRegex(ContractError, "candidate evidence hash drift: " + HISTORY):
                    self.finalize(output, candidate, binding)
            validate.assert_not_called()
            self.assertFalse((output / "checkpoint_publication_acceptance.json").exists())
            self.assertEqual((output / "checkpoint_publication_candidate.json").read_bytes(), candidate_bytes)

    def test_missing_candidate_history_blocks_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "arm"
            candidate, binding = self.publish_candidate(output)
            (output / HISTORY).unlink()
            with mock.patch.object(runtime, "validate_full_resource_evidence", return_value=RESOURCE_ASSESSMENT) as validate:
                with self.assertRaisesRegex(ContractError, "candidate evidence hash"):
                    self.finalize(output, candidate, binding)
            validate.assert_not_called()
            self.assertFalse((output / "checkpoint_publication_acceptance.json").exists())

    def test_projected_candidate_cannot_omit_the_physical_history_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "arm"
            candidate, binding = self.publish_candidate(output)
            history_bytes = (output / HISTORY).read_bytes()
            candidate_path = output / "checkpoint_publication_candidate.json"
            persisted = json.loads(candidate_path.read_text())
            self.assertEqual(persisted["evidence_sha256"].pop(HISTORY), file_sha(output / HISTORY))
            write(candidate_path, persisted)
            candidate_bytes = candidate_path.read_bytes()
            with mock.patch.object(runtime, "validate_full_resource_evidence", return_value=RESOURCE_ASSESSMENT) as validate:
                with self.assertRaises(ContractError):
                    self.finalize(output, candidate, binding)
            validate.assert_not_called()
            self.assertFalse((output / "checkpoint_publication_acceptance.json").exists())
            self.assertEqual(candidate_path.read_bytes(), candidate_bytes)
            self.assertEqual((output / HISTORY).read_bytes(), history_bytes)

    def test_legacy_cpu_and_adaptive_acceptance_keep_the_original_exact_names(self):
        for policy in ("cpu_only", "adaptive_weights"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / "arm"
                candidate, binding = self.publish_candidate(output, policy=policy, projected=False)
                self.assertFalse((output / HISTORY).exists())
                self.assertEqual(set(candidate["evidence_sha256"]), set(pre_finalization_acceptance_evidence_files(policy)))
                with mock.patch.object(runtime, "validate_full_resource_evidence", return_value=RESOURCE_ASSESSMENT):
                    accepted = self.finalize(output, candidate, binding)
                self.assertEqual(set(accepted["evidence_sha256"]), set(accepted_arm_evidence_files(policy, full_resource=True)))
                self.assertNotIn(HISTORY, accepted["evidence_sha256"])
                self.assertEqual(accepted["evidence_sha256"], {
                    name: file_sha(output / name) for name in accepted["evidence_sha256"]
                })


if __name__ == "__main__":
    unittest.main()
