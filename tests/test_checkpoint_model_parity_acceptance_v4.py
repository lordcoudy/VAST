from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import checkpoint_model_parity as parity_v3
import checkpoint_model_parity_v4 as parity_v4

from tests.test_checkpoint_model_parity_v4 import _descriptor, _sha


def _refresh() -> dict[str, object]:
    patch_workers = {
        "cpu": {
            "image": "vast/analytics-openvino-worker:publication-v3",
            "image_id": "sha256:" + "a" * 64,
            "base_image": "vast/openvino-native-probe:dlstreamer-2026.1",
            "base_image_id": "sha256:" + "c" * 64,
            "previous_accepted_image_id": "sha256:" + "1" * 64,
            "source_set_sha256": _sha("cpu-source"),
            "receipt_sha256": _sha("receipt"),
        },
        "gpu": {
            "image": "vast/analytics-tensorrt-worker:publication-v3",
            "image_id": "sha256:" + "b" * 64,
            "base_image": "vast/deepstream-native-probe:7.0",
            "base_image_id": "sha256:" + "d" * 64,
            "previous_accepted_image_id": "sha256:" + "2" * 64,
            "source_set_sha256": _sha("gpu-source"),
            "receipt_sha256": _sha("receipt"),
        },
    }
    probes = {
        resource: {
            **_descriptor(f"artifacts/v4/{resource}-probe.json", resource + "probe"),
            "worker_implementation_sha256": _sha(resource + "implementation"),
        }
        for resource in ("cpu", "gpu")
    }
    return {
        "image_identity_patch": {
            **_descriptor("artifacts/v4/image-patch.json", "patch"),
            "patch_sha256": _sha("patch-self"),
            "refresh_blockers": list(parity_v4.REFRESH_BLOCKERS),
            "resolved_blockers": [],
            "workers": patch_workers,
        },
        "workers": {
            resource: {
                "image": patch_workers[resource]["image"],
                "image_id": patch_workers[resource]["image_id"],
                "worker_implementation_sha256": probes[resource]["worker_implementation_sha256"],
                "source_set_sha256": patch_workers[resource]["source_set_sha256"],
                "receipt_sha256": patch_workers[resource]["receipt_sha256"],
            }
            for resource in ("cpu", "gpu")
        },
        "execution_config": {
            **_descriptor("artifacts/v4/execution.json", "execution"),
            "content_identity_sha256": _sha("execution-content"),
            "worker_projection_sha256": _sha("execution-workers"),
        },
        "binding_set": {
            "index": _descriptor("artifacts/v4/bindings/index.json", "index"),
            "identity_sha256": _sha("index-identity"),
            "bindings_identity_sha256": _sha("bindings-identity"),
            "bindings": {
                f"{branch}:{resource}": _descriptor(
                    f"artifacts/v4/bindings/{branch}-{resource}.json",
                    branch + resource,
                )
                for branch in parity_v3.BRANCHES
                for resource in ("cpu", "gpu")
            },
        },
        "runtime_probes": probes,
    }


def _transaction() -> dict[str, object]:
    return {
        **_descriptor("evidence/model_parity/v4/transaction_index.json", "transaction-file"),
        "transaction_sha256": _sha("transaction"),
        "files_sha256": _sha("transaction-files"),
        "output_segments_sha256": _sha("segments"),
        "execution_bundle_count": 480,
        "execution_bundles_sha256": _sha("bundles"),
    }


class AcceptanceV4AuthorityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = __import__("checkpoint_model_parity_acceptance_v4")

    def test_accepts_exact_patch_probe_config_and_eight_binding_crosslinks(self) -> None:
        value = self.module.validate_refresh_authority_v4(_refresh())
        self.assertEqual(len(value["binding_set"]["bindings"]), 8)
        self.assertEqual(value["workers"]["gpu"]["worker_implementation_sha256"], value["runtime_probes"]["gpu"]["worker_implementation_sha256"])

    def test_rejects_wrong_worker_id(self) -> None:
        value = _refresh()
        value["workers"]["cpu"]["image_id"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(self.module.ModelParityAcceptanceV4Error, "worker identity"):
            self.module.validate_refresh_authority_v4(value)

    def test_rejects_stale_patch_or_extra_blocker(self) -> None:
        value = _refresh()
        value["image_identity_patch"]["resolved_blockers"] = ["runtime:unrelated"]
        with self.assertRaisesRegex(self.module.ModelParityAcceptanceV4Error, "exact two"):
            self.module.validate_refresh_authority_v4(value)

    def test_rejects_transaction_output_or_bundle_drift(self) -> None:
        value = _transaction()
        self.module.validate_transaction_binding_v4(value)
        for field, replacement in (
            ("output_segments_sha256", "0" * 64),
            ("execution_bundle_count", 479),
            ("transaction_sha256", "not-a-sha"),
        ):
            tampered = copy.deepcopy(value)
            tampered[field] = replacement
            with self.assertRaises(self.module.ModelParityAcceptanceV4Error, msg=field):
                self.module.validate_transaction_binding_v4(tampered, expected=value)


if __name__ == "__main__":
    unittest.main()
