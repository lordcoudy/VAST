"""Actual-validator building blocks for complete accepted-policy fixture tests.

These protocol tests do not yet establish a complete authority-v2 consumer
success; real parity, operational closure and all native sidecars remain
required for that separate assertion.
"""
from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import canonicalize_frames_csv, validate_frame_events, validate_policy_decisions, validate_required_sidecars  # noqa: E402
from publication_policy_contract import ANALYTICS_BRANCHES, PUBLISHABLE_SYSTEMS, validate_decision_record  # noqa: E402
from publication_policy_projection_v1 import reconstruct_original_decision_v1  # noqa: E402
from publication_operational_capture_plan_v1 import _guardian_context, _native_context  # noqa: E402
from publication_operational_request_domain_v1 import iter_native_domain_v1, payload_with_sha256_v1  # noqa: E402
from tests.fixtures.accepted_policy_native_fixture_v1 import write_native_policy_fixture_cell_v1  # noqa: E402
from tests.fixtures.accepted_policy_guardian_journal_fixture_v1 import write_fixture_guardian_operational_journals_v1  # noqa: E402
from tests.test_checkpoint_native_policy_runtime import capability_manifest  # noqa: E402
from topology_contract import validate_topology_events  # noqa: E402


def verified_fixture_manifest() -> dict:
    manifest = capability_manifest()
    for system in manifest["systems"]:
        for branch in ANALYTICS_BRANCHES:
            for resource in ("cpu", "gpu"):
                binding = manifest["systems"][system]["branches"][branch][resource]
                detector = f"fixture-{branch};model_sha256={'a' * 64}"
                binding["terminal_detector"] = detector
                binding["runtime_identity"]["terminal_detector"] = detector
    return manifest


def validate_native_cell(output: Path, metadata: dict, topology: str) -> tuple:
    frames = canonicalize_frames_csv(output / "frames.csv", mode="benchmark", run_id="", detector="", backend="")
    events = validate_frame_events(output / "frame_events.csv")
    scenario = {"name": metadata["scenario"], "workload": {"routing_mode": "all_branches_per_stream", "analytics_function_types": 4},
                "topology": {"contract_version": 2, "kind": topology, "routing_mode": "all_branches_per_stream", "required_branches": list(ANALYTICS_BRANCHES)}}
    topology_rows = validate_topology_events(output / "topology_events.csv", frames=frames, frame_events=events, scenario=scenario)
    sidecars = validate_required_sidecars(
        output, require_labeled_provenance=True, require_full_policy_trace=True,
        require_causal_policy_trace=True, require_ingress_ledger=True,
        require_branch_terminals=True, require_stage_contracts=True,
        require_reset_evidence=True, required_branches=ANALYTICS_BRANCHES,
        topology_kind=topology, expected_streams=6,
        require_full_resource_evidence=True, expected_run_id=metadata["run_id"],
        frames=frames, topology_events=topology_rows,
    )
    return frames, sidecars


class AcceptedPolicyNativeFixtureBuildingBlockTests(unittest.TestCase):
    def test_complete_native_sidecars_run_real_ingress_reset_branch_and_resource_validation(self) -> None:
        manifest = verified_fixture_manifest()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-real-sidecars-") as raw:
            for resource in ("cpu", "gpu"):
                for topology in ("independent_processes", "shared_video_dag"):
                    with self.subTest(resource=resource, topology=topology):
                        output = Path(raw) / f"{resource}-{topology}"
                        metadata = write_native_policy_fixture_cell_v1(
                            output_dir=output, capability=manifest, system="gstreamer_custom",
                            resource=resource, codec="h264", topology_kind=topology,
                            dropped_ingress=True,
                        )
                        frames, sidecars = validate_native_cell(output, metadata, topology)
                        self.assertEqual(len(frames), 30)
                        self.assertEqual(len(sidecars["ingress_ledger"]), 31)
                        self.assertTrue(sidecars["branch_terminals"]["branch_terminal_claim_eligible"].all())
                        self.assertTrue(sidecars["reset_evidence"]["reset_claim_eligible"].all())
                        self.assertTrue(sidecars["resource_intervals"].attrs["full_resource_summary"]["full_resource_coverage_complete"])

    def test_complete_32_cell_native_matrix_at_minimum_and_larger_measured_counts(self) -> None:
        manifest = verified_fixture_manifest()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-real-matrix-") as raw:
            for samples_per_branch in (30, 31):
                total = 0
                coordinates = set()
                for system in PUBLISHABLE_SYSTEMS:
                    for resource in ("cpu", "gpu"):
                        for codec in ("h264", "h265"):
                            for topology in ("independent_processes", "shared_video_dag"):
                                coordinate = (system, resource, codec, topology)
                                with self.subTest(samples=samples_per_branch, coordinate=coordinate):
                                    output = Path(raw) / str(samples_per_branch) / system / resource / codec / topology
                                    metadata = write_native_policy_fixture_cell_v1(
                                        output_dir=output, capability=manifest, system=system,
                                        resource=resource, codec=codec, topology_kind=topology,
                                        samples_per_branch=samples_per_branch,
                                        dropped_ingress=resource == "gpu",
                                    )
                                    frames, sidecars = validate_native_cell(output, metadata, topology)
                                    self.assertEqual(len(frames), samples_per_branch)
                                    self.assertTrue(sidecars["resource_intervals"].attrs["full_resource_summary"]["full_resource_coverage_complete"])
                                    completed_decisions = sidecars["policy_decisions"]
                                    drop_traces = set(sidecars["ingress_ledger"].loc[sidecars["ingress_ledger"]["terminal_status"] == "drop", "trace_id"])
                                    if resource == "gpu":
                                        completed_decisions = completed_decisions.loc[~completed_decisions["trace_id"].isin(drop_traces)]
                                        intervals = sidecars["resource_intervals"]
                                        self.assertFalse(intervals["trace_id"].isin(drop_traces).any())
                                    for branch in ANALYTICS_BRANCHES:
                                        self.assertEqual((completed_decisions["stage"] == branch).sum(), samples_per_branch)
                                    total += len(completed_decisions)
                                    coordinates.add(coordinate)
                self.assertEqual(len(coordinates), 32)
                self.assertEqual(total, 32 * len(ANALYTICS_BRANCHES) * samples_per_branch)
                self.assertEqual(total, 3840 if samples_per_branch == 30 else 3968)

    def test_real_native_coordinator_and_replay_validate_completed_and_dropped_frame_decisions(self) -> None:
        manifest = capability_manifest()
        with tempfile.TemporaryDirectory(prefix="accepted-policy-real-protocol-") as raw:
            for resource in ("cpu", "gpu"):
                output = Path(raw) / resource
                run_id = f"fixture-operational-{resource}"
                descriptor = {"path": str(Path(raw) / "artificial-binding.json"), "size_bytes": 1, "sha256": "a" * 64}
                operation = {
                    "run_id": run_id, "arm_id": f"fixture-arm-{resource}",
                    "system": "gstreamer_custom", "scenario": "checkpoint_video_dag_shared",
                    "codec": "h264", "policy": "cpu_only" if resource == "cpu" else "gpu_only",
                    "deadline_ms": 100.0, "original_operation": descriptor,
                    "descriptors": {name: dict(descriptor) for name in (
                        "capability_manifest", "source_plan", "model_authority", "calibration",
                        "policy_request_source", "policy_coordinator_source", "execution_code_closure",
                    )},
                }
                context = _native_context(operation, "complete_qualification_operational_identity_v1")
                operational_dir = Path(raw) / f"{resource}.operational"
                metadata = write_native_policy_fixture_cell_v1(
                    output_dir=output,
                    capability=manifest,
                    system="gstreamer_custom",
                    resource=resource,
                    codec="h264",
                    topology_kind="shared_video_dag",
                    dropped_ingress=True,
                    run_id=run_id, arm_id=operation["arm_id"],
                    operational_context={"header": context["native_header"], "output_dir": operational_dir},
                    worker_ids_by_branch_stream={(branch, stream): f"fixture-worker-{stream}" for branch in ANALYTICS_BRANCHES for stream in range(6)},
                )
                rows = validate_policy_decisions(
                    output / "policy_decisions.csv",
                    require_labeled_provenance=True,
                    require_full_trace=True,
                    require_causal_trace=True,
                )
                records = [json.loads(line) for line in (output / "publication_policy_decisions.jsonl").read_text().splitlines()]
                self.assertEqual(len(records), 30 * len(ANALYTICS_BRANCHES) + 3)
                self.assertEqual(len(rows), len(records))
                self.assertEqual(set(rows["stream_id"].astype(int)), set(range(6)))
                for record in records:
                    original, _issued = reconstruct_original_decision_v1(record)
                    self.assertTrue(validate_decision_record(original, manifest)["passed"])
                native_path = operational_dir / "native_operational_requests.v1.jsonl"
                native_payload = native_path.read_bytes()
                native_descriptor = {"path": str(native_path), "size_bytes": len(native_payload), "sha256": hashlib.sha256(native_payload).hexdigest()}

                def original_authority(occurrence: dict) -> None:
                    assessment = validate_decision_record(occurrence["accepted_record"], manifest)
                    if not assessment["passed"]:
                        raise AssertionError(assessment)

                occurrences = list(iter_native_domain_v1(native_path, expected_descriptor=native_descriptor, original_authority_validator=original_authority))
                self.assertEqual(len(occurrences), len(records))
                self.assertTrue(all(item["measurement"] for item in occurrences))
                operation["front_workers_by_route"] = {
                    f"{branch}:{target}": [{"worker_id": f"fixture-worker-{stream}", "stream_id": stream} for stream in range(6)]
                    for branch in ANALYTICS_BRANCHES for target in ("cpu", "gpu")
                }
                guardian_descriptors = {name: dict(descriptor) for name in (
                    "capability_manifest", "execution_config", "execution_code_closure",
                    "model_authority", "native_protocol_source", "proxy_protocol_source",
                )}
                journal_dir = Path(raw) / f"{resource}.journals"
                guardian_context = _guardian_context([operation], "complete_qualification_operational_identity_v1",
                                                     guardian_descriptors, descriptor, descriptor, journal_dir)
                headers = guardian_context["headers_by_route"]
                for route, header in headers.items():
                    header.update(lifecycle_id="b" * 32, owner={"uid": 1000, "gid": 1000, "pid": 123, "proc_stat_starttime_ticks": 456},
                                  worker_capability={"worker_id": f"fixture-{route}"})
                    header["descriptors"]["service_authority"] = descriptor
                    headers[route] = payload_with_sha256_v1(header)
                journal = write_fixture_guardian_operational_journals_v1(
                    output_dir=journal_dir, headers_by_route=headers,
                    native_domains=[{"operation_id": run_id, "descriptor": native_descriptor}],
                    capability_manifest=manifest,
                )
                self.assertEqual(journal["lifecycle_counters"]["requests_started"], len(records))
                self.assertEqual(journal["lifecycle_counters"]["requests_completed"], len(records))
                self.assertEqual(journal["lifecycle_counters"]["requests_failed"], 0)
                self.assertFalse(journal["limits"]["physical_inference_observed"])
                self.assertFalse(metadata["limits"]["campaign_authority"])
                self.assertFalse(metadata["limits"]["physical_runtime_execution_observed"])


if __name__ == "__main__":
    unittest.main()
