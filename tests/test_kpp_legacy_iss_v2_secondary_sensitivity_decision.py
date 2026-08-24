from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import kpp_legacy_iss_v2_secondary_sensitivity_decision as decision
import materialize_kpp_legacy_iss_v2_model_corpus as corpus


class KppLegacyIssV2SecondarySensitivityDecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.path = ROOT / decision.DECISION_PATH

    def _write_resealed(self, value: dict[str, object], path: Path) -> None:
        unsigned = copy.deepcopy(value)
        unsigned.pop("decision_sha256", None)
        value["decision_sha256"] = hashlib.sha256(
            decision.DECISION_DOMAIN + decision.canonical_bytes(unsigned)
        ).hexdigest()
        path.write_bytes(decision.canonical_bytes(value) + b"\n")

    def test_checked_in_decision_is_exact_and_self_hashed(self) -> None:
        loaded = decision.load_decision(self.path)
        self.assertEqual(loaded, decision.expected_decision())
        self.assertEqual(
            hashlib.sha256(self.path.read_bytes()).hexdigest(),
            decision.EXPECTED_DECISION_FILE_SHA256,
        )

    def test_decision_records_only_the_confirmed_secondary_sensitivity_scope(
        self,
    ) -> None:
        loaded = decision.load_decision(self.path)
        self.assertEqual(loaded["authorized_dataset_roles"], ["secondary", "sensitivity"])
        self.assertEqual(loaded["branch_source_role"], corpus.BRANCH_SOURCE_ROLE)
        self.assertEqual(loaded["sampling_rule"], corpus.SAMPLING_RULE)
        self.assertEqual(
            loaded["sampling_allocation"],
            {
                "samples_per_branch": 60,
                "calibration": {"total": 30, "h264": 15, "h265": 15},
                "evaluation": {"total": 30, "h264": 15, "h265": 15},
            },
        )

    def test_decision_keeps_scientific_and_publication_claims_fail_closed(self) -> None:
        loaded = decision.load_decision(self.path)
        self.assertEqual(
            loaded["shared_front_frames"],
            {
                "allowed": True,
                "use": "topology_load_proxy_only",
                "accuracy_claim_authorized": False,
                "representativeness_claim_authorized": False,
                "statistical_independence_claimed": False,
            },
        )
        self.assertEqual(
            loaded["pilot_authorization"],
            {
                "authorized": True,
                "environments": ["wsl", "docker", "gpu"],
                "nonpublication_only": True,
                "accepted_evidence_authorized": False,
                "publication_readiness_elevation_authorized": False,
                "network_download_authorized": False,
                "cloud_upload_authorized": False,
            },
        )
        self.assertEqual(
            loaded["claims"],
            {
                "semantic_claim": "topology_load_proxy_only",
                "accuracy": False,
                "representative": False,
                "statistical_independence": False,
                "production_semantics": False,
                "model_acceptance": False,
                "runtime_acceptance": False,
                "publishable": False,
                "publication_authorized": False,
                "primary_replacement_authorized": False,
            },
        )

    def test_resealed_scope_drift_and_unknown_fields_are_rejected(self) -> None:
        original = json.loads(self.path.read_text(encoding="ascii"))
        mutations = (
            lambda value: value.__setitem__("authorized_dataset_roles", ["primary"]),
            lambda value: value["branch_source_role"].__setitem__(
                "foreign_object", "front_gate"
            ),
            lambda value: value["sampling_allocation"]["evaluation"].__setitem__(
                "h264", 30
            ),
            lambda value: value["shared_front_frames"].__setitem__(
                "accuracy_claim_authorized", True
            ),
            lambda value: value["pilot_authorization"].__setitem__(
                "publication_readiness_elevation_authorized", True
            ),
            lambda value: value["claims"].__setitem__("publishable", True),
            lambda value: value.__setitem__("unexpected", False),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for index, mutate in enumerate(mutations):
                with self.subTest(index=index):
                    drifted = copy.deepcopy(original)
                    mutate(drifted)
                    candidate = Path(temp_dir) / f"decision-{index}.json"
                    self._write_resealed(drifted, candidate)
                    with self.assertRaisesRegex(
                        decision.DecisionError, "decision contract differs"
                    ):
                        decision.load_decision(candidate)

    def test_noncanonical_bytes_and_bad_self_hash_are_rejected(self) -> None:
        original = json.loads(self.path.read_text(encoding="ascii"))
        with tempfile.TemporaryDirectory() as temp_dir:
            pretty = Path(temp_dir) / "pretty.json"
            pretty.write_text(json.dumps(original, indent=2) + "\n", encoding="ascii")
            with self.assertRaisesRegex(decision.DecisionError, "canonical bytes"):
                decision.load_decision(pretty)

            bad_hash = copy.deepcopy(original)
            bad_hash["decision_sha256"] = "0" * 64
            bad = Path(temp_dir) / "bad-hash.json"
            bad.write_bytes(decision.canonical_bytes(bad_hash) + b"\n")
            with self.assertRaisesRegex(decision.DecisionError, "self SHA-256"):
                decision.load_decision(bad)


if __name__ == "__main__":
    unittest.main()
