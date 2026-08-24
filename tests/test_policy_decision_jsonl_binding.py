from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError, validate_frozen_policy_decisions  # noqa: E402


class _Rows:
    def __init__(self, rows: list[dict]) -> None:
        self._rows = rows

    def iterrows(self):
        return iter(enumerate(self._rows))

    def __len__(self) -> int:
        return len(self._rows)


def _canonical_record() -> dict:
    payload = {
        "schema_version": 1,
        "artifact_kind": "vast_publication_policy_decision",
        "policy": "cpu_only",
        "decision_id": "decision-0001",
        "decision_seq": 1,
        "trace_id": "trace-0001",
        "branch": "damage",
        "selected_resource": "cpu",
        "record_status": "accepted_native_runtime_decision",
        "native_decision_evidence": {
            "decision_id": "decision-0001",
            "telemetry_source": "native",
            "terminal_status": "completed",
        },
    }
    payload["sha256"] = hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()
    return payload


class PolicyDecisionJsonlBindingTests(unittest.TestCase):
    def test_semantic_jsonl_csv_binding_and_tamper_rejection(self) -> None:
        record = _canonical_record()
        csv = _Rows([{
            "decision_id": "decision-0001",
            "trace_id": "trace-0001",
            "stage": "damage",
            "resource": "cpu",
            "policy": "cpu_only",
        }])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "publication_policy_decisions.jsonl"
            path.write_text(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                validate_frozen_policy_decisions(
                    path,
                    decisions=csv,
                    expected_policy="cpu_only",
                ),
                [record],
            )
            record["native_decision_evidence"]["terminal_status"] = "pending"
            record["sha256"] = hashlib.sha256(
                json.dumps(
                    {key: value for key, value in record.items() if key != "sha256"},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            path.write_text(
                json.dumps(record, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "linkage drifted"):
                validate_frozen_policy_decisions(
                    path,
                    decisions=csv,
                    expected_policy="cpu_only",
                )


if __name__ == "__main__":
    unittest.main()
