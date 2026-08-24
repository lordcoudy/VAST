from __future__ import annotations

import csv
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from full_publication_results import export_finalized_results  # noqa: E402


MATRIX_SHA = "a" * 64
RUN_SHA = "b" * 64


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


class FakeRunner:
    def __init__(self, run_root: Path, snapshot: dict) -> None:
        self.run_root = run_root
        self.snapshot = snapshot

    def finalized_snapshot(self) -> dict:
        return self.snapshot


def fixture(root: Path) -> tuple[FakeRunner, Path]:
    pair = {
        "pair_id": "pair-0001",
        "arms": [
            {
                "arm_id": "baseline-arm",
                "scenario": "checkpoint_independent_processes_baseline",
                "system": "gstreamer_custom",
                "codec": "h264",
                "dataset": "kpp_real_h264",
                "policy": "cpu_only",
                "deadline_ms": 100.0,
                "repeat": 1,
            },
            {
                "arm_id": "shared-arm",
                "scenario": "checkpoint_video_dag_shared",
                "system": "gstreamer_custom",
                "codec": "h264",
                "dataset": "kpp_real_h264",
                "policy": "cpu_only",
                "deadline_ms": 100.0,
                "repeat": 1,
            },
        ],
    }
    accepted_arms = []
    for index, arm in enumerate(pair["arms"], start=1):
        accepted_arms.append(
            {
                "arm_id": arm["arm_id"],
                "scenario": arm["scenario"],
                "result": {
                    "status": "completed",
                    "throughput_fps": float(index * 10),
                    "latency_p95_ms": float(index * 20),
                },
                "arm_acceptance_summary": {
                    "full_resource_evidence_accepted": True
                },
                "full_resource_summary": {
                    "resource_contract_version": 2,
                    "nvdec_busy_equivalent_ns": index,
                },
                "qualification_authorities": {
                    "identity_artifact_binding_sha256": "c" * 64,
                    "resource_capability_grant_sha256": "d" * 64,
                    "backend_runtime_grant_sha256": "e" * 64,
                    "model_parity_grant_sha256": "f" * 64,
                    "model_parity_acceptance_binding_sha256": "0" * 64,
                },
            }
        )
    acceptance = {
        "schema_version": 2,
        "artifact_kind": "vast_full_publication_pair_acceptance",
        "status": "accepted",
        "matrix_sha256": MATRIX_SHA,
        "run_id": RUN_SHA,
        "pair_sequence": 0,
        "pair_id": pair["pair_id"],
        "arm_ids": ["baseline-arm", "shared-arm"],
        "qualification_authorities": copy.deepcopy(
            accepted_arms[0]["qualification_authorities"]
        ),
        "pair_gates": {
            "common_identity_and_qualification_authorities": True,
        },
        "arms": accepted_arms,
    }
    path = root / "accepted_pairs" / "0000_pair-0001.attempt-0001.acceptance.json"
    path.parent.mkdir(parents=True)
    payload = canonical(acceptance)
    path.write_bytes(payload)
    decision = {
        "acceptance_manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "compact_acceptance_relative_path": path.relative_to(root).as_posix(),
    }
    snapshot = {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_finalized_snapshot",
        "matrix_identity": {"schema_version": 2, "sha256": MATRIX_SHA},
        "run_identity": {"schema_version": 1, "sha256": RUN_SHA},
        "matrix": {
            "expected_pairs": 1,
            "expected_arms": 2,
            "pairs": [pair],
        },
        "verified_pairs": [
            {
                "sequence": 0,
                "pair_id": pair["pair_id"],
                "acceptance": decision,
            }
        ],
        "finalization": {"verified": True, "verified_pairs": 1},
    }
    return FakeRunner(root, snapshot), path


class FullPublicationResultsTests(unittest.TestCase):
    def test_exports_deterministic_compact_article_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, _ = fixture(root)
            bundle = export_finalized_results(runner)
            self.assertEqual(bundle["verified_pairs"], 1)
            self.assertEqual(bundle["verified_arms"], 2)
            with (root / "results" / "full_arms.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row["result_throughput_fps"] for row in rows},
                {"10.0", "20.0"},
            )
            self.assertEqual(export_finalized_results(runner), bundle)

    def test_rejects_compact_acceptance_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, path = fixture(root)
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ContractError, "hash drift"):
                export_finalized_results(runner)

    def test_rejects_legacy_or_split_qualification_authorities(self) -> None:
        for case in ("legacy", "top_level", "gate", "arm"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "run"
                runner, path = fixture(root)
                acceptance = json.loads(path.read_text(encoding="utf-8"))
                if case == "legacy":
                    acceptance["schema_version"] = 1
                elif case == "top_level":
                    acceptance["qualification_authorities"].pop(
                        "model_parity_grant_sha256"
                    )
                elif case == "gate":
                    acceptance["pair_gates"][
                        "common_identity_and_qualification_authorities"
                    ] = False
                else:
                    acceptance["arms"][1]["qualification_authorities"][
                        "model_parity_grant_sha256"
                    ] = "9" * 64
                payload = canonical(acceptance)
                path.write_bytes(payload)
                runner.snapshot["verified_pairs"][0]["acceptance"][
                    "acceptance_manifest_sha256"
                ] = hashlib.sha256(payload).hexdigest()

                with self.assertRaisesRegex(
                    ContractError,
                    "identity drift|qualification authorit",
                ):
                    export_finalized_results(runner)


if __name__ == "__main__":
    unittest.main()
