from __future__ import annotations

import copy
import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_guardian_runtime_expectations_v1 as target  # noqa: E402


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def receipt(*, accepted: bool = False) -> dict[str, object]:
    return {
        "artifact_kind": (
            "vast_guardian_accepted_policy_preprocessing_contract_materialization_v1"
            if accepted
            else "vast_guardian_preprocessing_contract_materialization_v1"
        ),
        "preprocessing_contract_content_sha256": sha("preprocessing"),
        "policy_contract_sha256": sha("policy"),
        "model_parity_refresh_authority": {
            "image_identity_patch": {},
            "execution_config": {
                "path": "config.json",
                "size_bytes": 10,
                "sha256": sha("config-file"),
                "content_identity_sha256": sha("config-content"),
                "worker_projection_sha256": sha("workers"),
            },
            "binding_set": {
                "index": {
                    "path": "bindings/index.json",
                    "size_bytes": 10,
                    "sha256": sha("binding-index"),
                },
                "bindings": {
                    f"{branch}:{resource}": {
                        "path": f"bindings/{branch}-{resource}.json",
                        "size_bytes": 10,
                        "sha256": sha(f"binding-{branch}-{resource}"),
                    }
                    for branch in (
                        "plate_number",
                        "vehicle_type",
                        "damage",
                        "foreign_object",
                    )
                    for resource in ("cpu", "gpu")
                },
                "identity_sha256": sha("binding-set"),
                "bindings_identity_sha256": sha("bindings"),
            },
            "workers": {
                resource: {
                    "image": f"vast/{resource}:v1",
                    "image_id": "sha256:" + ("1" if resource == "cpu" else "2") * 64,
                    "worker_implementation_sha256": sha(f"impl-{resource}"),
                    "source_set_sha256": sha(f"source-{resource}"),
                    "receipt_sha256": sha(f"receipt-{resource}"),
                }
                for resource in ("cpu", "gpu")
            },
            "runtime_probes": {},
        },
    }


class RuntimeExpectationsV1Tests(unittest.TestCase):
    def test_derives_exact_external_runtime_expectations_for_both_receipt_kinds(self) -> None:
        for accepted in (False, True):
            observed = target.runtime_expectations_from_preprocessing_receipt_v1(
                receipt(accepted=accepted)
            )
            self.assertEqual(
                observed,
                {
                    "execution_config_identity_sha256": sha("config-content"),
                    "binding_set_identity_sha256": sha("binding-set"),
                    "bindings_identity_sha256": sha("bindings"),
                    "worker_image_ids": {
                        "cpu": "sha256:" + "1" * 64,
                        "gpu": "sha256:" + "2" * 64,
                    },
                    "policy_contract_sha256": sha("policy"),
                    "preprocessing_contract_content_sha256": sha("preprocessing"),
                },
            )

    def test_rejects_partial_replayed_and_self_anchored_shapes(self) -> None:
        cases: list[dict[str, object]] = []
        missing_gpu = receipt()
        del missing_gpu["model_parity_refresh_authority"]["workers"]["gpu"]  # type: ignore[index]
        cases.append(missing_gpu)
        extra = receipt()
        extra["model_parity_refresh_authority"]["workers"]["other"] = {}  # type: ignore[index]
        cases.append(extra)
        stale = receipt()
        stale["model_parity_refresh_authority"]["binding_set"][  # type: ignore[index]
            "identity_sha256"
        ] = "not-a-sha"
        cases.append(stale)
        service_artifact = copy.deepcopy(receipt())
        service_artifact["artifact_kind"] = (
            "vast_gstreamer_analytics_production_service_authority_v1"
        )
        cases.append(service_artifact)

        for value in cases:
            with self.subTest(value=value), self.assertRaises(
                target.GuardianRuntimeExpectationsV1Error
            ):
                target.runtime_expectations_from_preprocessing_receipt_v1(value)


if __name__ == "__main__":
    unittest.main()
