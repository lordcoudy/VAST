from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from publication_acceptance_evidence import FROZEN_POLICY_RUNTIME_HISTORY_JSONL
from production_arm_evidence_finalizer_v1 import (
    RUNTIME_INPUT_KEYS,
    _runtime_finalization_contract,
    finalized_production_evidence_files_v1,
    native_candidate_evidence_files_v1,
)
from publication_q4_runtime_contract_v4 import qualification_launcher_evidence_files_v4
from publication_q4_runtime_registry_materializer_v4 import (
    PublicationQ4RuntimeRegistryMaterializerV4Error,
    _build_launcher_input_projection_v3,
    _validate_launcher_input_projection_v3,
    canonical_sha256,
)


def runtime_template(*, runtime_history: bool, scratch: str = "/unused") -> dict:
    return {
        "schema_version": 3,
        "artifact_kind": "test_native_runtime_template",
        "defer_full_resource_acceptance": True,
        "scratch_root": scratch,
        "evidence_mapping": {
            name: name for name in native_candidate_evidence_files_v1(
                "adaptive_weights", runtime_history=runtime_history,
            )
        },
    }


class PublicationPolicyHistoryNamespaceTests(unittest.TestCase):
    def test_adaptive_history_is_bound_through_both_q4_projection_roles(self):
        raw = native_candidate_evidence_files_v1("adaptive_weights", runtime_history=True)
        self.assertEqual(raw, qualification_launcher_evidence_files_v4(
            "adaptive_weights", runtime_history=True,
        ))
        for role in ("qualification_raw", "production_finalized"):
            with self.subTest(role=role):
                projection = _build_launcher_input_projection_v3(
                    role=role, policy="adaptive_weights",
                    runtime_input_template=runtime_template(runtime_history=True),
                )
                checked = _validate_launcher_input_projection_v3(
                    projection, role=role, policy="adaptive_weights",
                )
                self.assertIn(FROZEN_POLICY_RUNTIME_HISTORY_JSONL, checked["launcher_evidence_files"])
                self.assertEqual(checked["runtime_input_template"]["evidence_mapping"],
                                 {name: name for name in raw})

    def test_resealed_template_cannot_remove_history_from_a_bound_projection(self):
        projection = _build_launcher_input_projection_v3(
            role="production_finalized", policy="adaptive_weights",
            runtime_input_template=runtime_template(runtime_history=True),
        )
        tampered = copy.deepcopy(projection)
        del tampered["runtime_input_template"]["evidence_mapping"][FROZEN_POLICY_RUNTIME_HISTORY_JSONL]
        tampered["runtime_input_template_sha256"] = canonical_sha256(tampered["runtime_input_template"])
        tampered["projection_sha256"] = canonical_sha256({
            key: value for key, value in tampered.items() if key != "projection_sha256"
        })
        with self.assertRaisesRegex(PublicationQ4RuntimeRegistryMaterializerV4Error, "evidence namespace"):
            _validate_launcher_input_projection_v3(
                tampered, role="production_finalized", policy="adaptive_weights",
            )

    def test_finalizer_requires_the_same_history_namespace_as_the_bound_runtime(self):
        with tempfile.TemporaryDirectory() as temporary:
            request = SimpleNamespace(
                system="deepstream",
                runtime_inputs={
                    "policy": "adaptive_weights",
                    "dataset": {RUNTIME_INPUT_KEYS["deepstream"]: runtime_template(
                        runtime_history=True, scratch=temporary,
                    )},
                },
                launcher_evidence_files=finalized_production_evidence_files_v1(
                    "adaptive_weights", runtime_history=True,
                ),
            )
            _contract, raw_names, _scratch = _runtime_finalization_contract(request)
            self.assertIn(FROZEN_POLICY_RUNTIME_HISTORY_JSONL, raw_names)
            request.launcher_evidence_files = finalized_production_evidence_files_v1("adaptive_weights")
            with self.assertRaisesRegex(Exception, "production_finalized_evidence_contract_drifted"):
                _runtime_finalization_contract(request)

    def test_legacy_projection_stays_exact_and_nonadaptive_history_is_rejected(self):
        projection = _build_launcher_input_projection_v3(
            role="qualification_raw", policy="adaptive_weights",
            runtime_input_template=runtime_template(runtime_history=False),
        )
        checked = _validate_launcher_input_projection_v3(
            projection, role="qualification_raw", policy="adaptive_weights",
        )
        self.assertNotIn(FROZEN_POLICY_RUNTIME_HISTORY_JSONL, checked["launcher_evidence_files"])
        for policy in ("cpu_only", "gpu_only", "static_hybrid", "heft", "deadline_aware_heft", "queue_aware_edf"):
            with self.subTest(policy=policy), self.assertRaises(ValueError):
                native_candidate_evidence_files_v1(policy, runtime_history=True)


if __name__ == "__main__":
    unittest.main()
