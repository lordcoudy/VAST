"""Domain gate: real qualification identifiers fit the operational request domain.

Q1 attempt 3 failed because DeepStream independent-process worker ids were
longer than the 37-character ``worker_id`` bound that operational capture
enforces through ``validate_native_request_source_v1`` (Amendment 7).  This
gate builds the actual process plans of every system for all 32 qualification
cells (the 4 native prechecks and the Savant original reuse cell run ids,
``publication_operational_capture_plan_v1.py``) and checks every process id
as ``worker_id`` together with the longest ``trace_id``, ``decision_id`` and
``input_frame_key`` the runtimes build from it.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, Iterator

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_operational_request_domain_v1 as domain  # noqa: E402
from checkpoint_deepstream_runtime import build_deepstream_runtime_plan  # noqa: E402
from checkpoint_gstreamer_runtime import build_publication_pair_plans  # noqa: E402
from checkpoint_openvino_runtime import build_openvino_topology_plan  # noqa: E402
from checkpoint_savant_runtime import build_savant_runtime_plan  # noqa: E402
from publication_policy_qualification_pilot_executor_v2 import qualification_pilot_cells_v2  # noqa: E402


MAX_STREAM_ID = 5
LONGEST_BRANCH = max(domain.BRANCHES, key=len)
# decision_id bound of the native occurrence and guardian records
# (publication_operational_request_domain_v1.py, publication_guardian_operational_recorder_v1.py).
DECISION_ID_CAP = 157


def load_inputs() -> tuple[dict, dict]:
    config = yaml.safe_load((ROOT / "configs" / "experiments.yaml").read_text(encoding="utf-8"))
    datasets = yaml.safe_load((ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8"))["datasets"]
    return config, datasets


def _process_ids(value: Any) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "process_id":
                yield str(item)
            else:
                yield from _process_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _process_ids(item)


def cell_plan(cell, config: dict, datasets: dict) -> Any:
    if cell.system == "deepstream":
        return build_deepstream_runtime_plan(config=config, datasets=datasets, scenario=cell.scenario,
                                             codec=cell.codec, policy=cell.policy, deadline_ms=cell.deadline_ms)
    if cell.system == "savant":
        return build_savant_runtime_plan(config=config, datasets=datasets, scenario=cell.scenario,
                                         codec=cell.codec, policy=cell.policy, deadline_ms=cell.deadline_ms)
    if cell.system == "openvino_gva":
        return build_openvino_topology_plan(scenario=cell.scenario, codec=cell.codec)
    if cell.system == "gstreamer_custom":
        # The publication pair holds both topologies; every process id is checked.
        return build_publication_pair_plans(config=config, datasets=datasets, system=cell.system, codec=cell.codec)
    raise AssertionError(f"unknown qualification system: {cell.system}")


def maximal_request(*, run_id: str, worker_id: str, dataset_id: str) -> dict[str, Any]:
    """Longest decision request a runtime builds for this run and worker."""

    frame_id = domain._request_bounds(None)[0]
    input_frame_key = f"{dataset_id}:{MAX_STREAM_ID}:{'f' * 64}:{domain.UINT64_MAX}:{domain.UINT64_MAX}"
    return {
        "schema_version": 1,
        "message_type": "decision_request",
        "run_id": run_id,
        "worker_id": worker_id,
        "input_frame_key": input_frame_key,
        # Bridge form (DeepStream, Savant, OpenVINO GVA); the native trace omits the worker suffix.
        "trace_id": f"{run_id}:{MAX_STREAM_ID}:{frame_id}:{worker_id}",
        "stream_id": MAX_STREAM_ID,
        "frame_id": frame_id,
        "transport_pts_ns": domain.UINT64_MAX,
        "branch": LONGEST_BRANCH,
        "arrival_ms": 1.0,
        "decision_time_ms": 2.0,
        "feature_observed_timestamp_ms": 1.0,
        "queue_depths": {"cpu": (1 << 32) - 1, "gpu": (1 << 32) - 1},
    }


def maximal_decision_id(*, run_id: str, worker_id: str) -> str:
    # checkpoint_native_policy_runtime.py: run:native-policy:seq:worker:pts:branch
    return (f"{run_id}:native-policy:{domain.MAX_NATIVE_DECISIONS_V1}:{worker_id}:"
            f"{domain.UINT64_MAX}:{LONGEST_BRANCH}")


def identifier_violations() -> list[str]:
    config, datasets = load_inputs()
    violations: list[str] = []
    for cell in qualification_pilot_cells_v2():
        dataset_id = build_deepstream_runtime_plan(
            config=config, datasets=datasets, scenario=cell.scenario, codec=cell.codec,
            policy=cell.policy, deadline_ms=cell.deadline_ms)["dataset"]
        worker_ids = sorted(set(_process_ids(cell_plan(cell, config, datasets))))
        if not worker_ids:
            violations.append(f"{cell.run_id}: plan has no process ids")
        for worker_id in worker_ids:
            try:
                domain.validate_native_request_source_v1(
                    maximal_request(run_id=cell.run_id, worker_id=worker_id, dataset_id=dataset_id))
                domain._text(maximal_decision_id(run_id=cell.run_id, worker_id=worker_id),
                             "decision_id", DECISION_ID_CAP)
            except domain.OperationalDomainError as error:
                violations.append(f"{cell.run_id} {worker_id} ({len(worker_id)}): {error}")
    return violations


class OperationalIdentifierDomainV1Tests(unittest.TestCase):
    def test_matrix_covers_all_systems_and_topologies(self) -> None:
        cells = qualification_pilot_cells_v2()
        self.assertEqual(len(cells), 32)
        self.assertEqual({(cell.system, cell.topology_kind) for cell in cells},
                         {(system, topology) for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
                          for topology in ("independent_processes", "shared_video_dag")})

    def test_maximal_identifiers_are_checked_against_the_bounds(self) -> None:
        # The constructors above must stay at the bound the validator enforces.
        request = maximal_request(run_id="r" * 64, worker_id="w" * 37, dataset_id="d" * 27)
        self.assertEqual(len(request["input_frame_key"]), 136)
        self.assertEqual(len(request["trace_id"]), 64 + 1 + 1 + 1 + 3 + 1 + 37)
        domain.validate_native_request_source_v1(request)
        with self.assertRaises(domain.OperationalDomainError):
            domain.validate_native_request_source_v1(
                maximal_request(run_id="r" * 64, worker_id="w" * 38, dataset_id="d" * 27))
        with self.assertRaises(domain.OperationalDomainError):
            domain._text(maximal_decision_id(run_id="r" * 64, worker_id="w" * 38), "decision_id", DECISION_ID_CAP)

    def test_real_qualification_identifiers_fit_the_operational_domain(self) -> None:
        violations = identifier_violations()
        self.assertEqual(violations, [], "\n" + "\n".join(violations))


if __name__ == "__main__":
    unittest.main()
