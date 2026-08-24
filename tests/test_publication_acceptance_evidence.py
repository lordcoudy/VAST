from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_acceptance_evidence import (  # noqa: E402
    BASE_ACCEPTANCE_EVIDENCE_FILES,
    FROZEN_POLICY_DECISIONS_JSONL,
    FROZEN_POLICY_FEEDBACK_JSONL,
    FULL_RESOURCE_EVIDENCE_FILES,
    accepted_arm_evidence_files,
    pre_finalization_acceptance_evidence_files,
)


POLICIES = (
    "cpu_only",
    "gpu_only",
    "static_hybrid",
    "heft",
    "deadline_aware_heft",
    "queue_aware_edf",
    "adaptive_weights",
)


class PublicationAcceptanceEvidenceTests(unittest.TestCase):
    def test_all_frozen_policies_have_exact_policy_aware_sets(self) -> None:
        base = set(BASE_ACCEPTANCE_EVIDENCE_FILES)
        resource = set(FULL_RESOURCE_EVIDENCE_FILES)
        for policy in POLICIES:
            with self.subTest(policy=policy):
                pre_final = set(pre_finalization_acceptance_evidence_files(policy))
                full = set(
                    accepted_arm_evidence_files(policy, full_resource=True)
                )
                expected = base | {FROZEN_POLICY_DECISIONS_JSONL}
                if policy == "adaptive_weights":
                    expected.add(FROZEN_POLICY_FEEDBACK_JSONL)
                self.assertEqual(pre_final, expected)
                self.assertEqual(full, expected | resource)
                self.assertNotIn("policy_feedback.csv", pre_final)
                self.assertNotIn("policy_feedback.csv", full)

    def test_policy_normalization_does_not_expand_feedback_contract(self) -> None:
        self.assertIn(
            FROZEN_POLICY_FEEDBACK_JSONL,
            pre_finalization_acceptance_evidence_files(" ADAPTIVE_WEIGHTS "),
        )
        self.assertNotIn(
            FROZEN_POLICY_FEEDBACK_JSONL,
            pre_finalization_acceptance_evidence_files("ql_heft_online"),
        )


if __name__ == "__main__":
    unittest.main()
