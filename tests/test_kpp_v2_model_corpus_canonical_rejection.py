from __future__ import annotations

import hashlib
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_model_parity as parity  # noqa: E402
import materialize_kpp_legacy_iss_v2_model_corpus as materializer  # noqa: E402


def _canonical_sha256(value: object) -> str:
    payload = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _generated_candidate() -> dict[str, object]:
    samples = [{"sample_id": f"synthetic-candidate-{index:02d}"} for index in range(30)]
    return {
        "schema_version": 1,
        "artifact_kind": materializer.CORPUS_CANDIDATE_ARTIFACT_KIND,
        "branch": "plate_number",
        "workload_slot_id": "opaque_rn18",
        "source_ref": "resnet18_v1_7",
        "source_role": "front_gate",
        "semantic_claim": "topology_load_proxy_candidate_only",
        "corpus_role": "calibration",
        "promotable": False,
        "publication_authorized": False,
        "evidence_accepted": False,
        "pi_approval_status": "required",
        "dataset_manifest": {
            "role": "synthetic dataset manifest candidate",
            "path": "staging/synthetic/dataset_manifest.json",
            "size_bytes": 1,
            "sha256": "0" * 64,
        },
        "dataset_aggregate_sha256": "1" * 64,
        "producer_contract": {"candidate_only": True},
        "sample_count": len(samples),
        "samples": samples,
        "samples_sha256": _canonical_sha256(samples),
        "claims": dict(materializer.CLAIMS),
    }


class CanonicalAssessorCandidateRejectionTests(unittest.TestCase):
    def test_candidate_schema_is_rejected_without_an_accepted_corpus(self) -> None:
        blockers, accepted_corpus, artifact_states = parity._corpus_blockers_v2(
            "plate_number",
            "opaque_rn18",
            _generated_candidate(),
            role="calibration",
            minimum=parity.MIN_CALIBRATION_SAMPLES,
            root=ROOT,
            preprocessing_sha="2" * 64,
        )

        self.assertEqual(
            blockers,
            ["branch:plate_number:calibration_corpus_schema_invalid"],
        )
        self.assertIsNone(accepted_corpus)
        self.assertEqual(artifact_states, {})


if __name__ == "__main__":
    unittest.main()
