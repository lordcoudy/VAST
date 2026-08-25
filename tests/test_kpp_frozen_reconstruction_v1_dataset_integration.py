from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import kpp_frozen_reconstruction_v1_dataset as gate  # noqa: E402
from benchmark_contract import ContractError, load_dataset  # noqa: E402


class KppFrozenReconstructionV1DatasetIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.catalog = yaml.safe_load(
            (ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8")
        )["datasets"]
        corpus = ROOT / gate.TARGET_ROOT
        cls.manifest = json.loads(
            (corpus / gate.MANIFEST_NAME).read_text(encoding="ascii")
        )
        cls.authorization = json.loads(
            (corpus / gate.AUTHORIZATION_RECEIPT_NAME).read_text(encoding="ascii")
        )

    def test_catalog_has_both_distinct_publishable_reconstruction_ids(self) -> None:
        for codec, name in gate.DATASET_IDS.items():
            entry = self.catalog[name]
            self.assertTrue(
                gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
                    name, entry, project_root=ROOT, require_files=False
                )
            )
            self.assertEqual(entry["codec_variant"], codec)
            self.assertTrue(entry["publishable"])
            self.assertFalse(
                entry["provenance"]["claims"][
                    "historical_v1_dataset_identity_equivalent"
                ]
            )

    def test_historical_entries_remain_immutable_and_receipt_records_unavailability(self) -> None:
        for name in ("kpp_real_avi", "kpp_real_h264", "kpp_real_h265"):
            entry = self.catalog[name]
            self.assertTrue(entry["publishable"])
            self.assertNotIn("availability", entry)
            self.assertNotIn("status", entry)
        self.assertEqual(
            self.manifest["historical_v1"]["dataset_ids"],
            ["kpp_real_avi", "kpp_real_h264", "kpp_real_h265"],
        )
        self.assertFalse(self.manifest["historical_v1"]["source_bytes_available"])
        self.assertFalse(self.manifest["historical_v1"]["identity_recovered"])
        self.assertFalse(
            self.manifest["historical_v1"]["reconstruction_is_identity_substitute"]
        )

    def test_full_on_disk_corpus_and_receipt_graph_validate(self) -> None:
        name = gate.DATASET_IDS["h264"]
        self.assertTrue(
            gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
                name, self.catalog[name], project_root=ROOT, require_files=True
            )
        )

    def test_documents_reject_resealed_historical_identity_claim(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["claims"]["historical_v1_dataset_identity_equivalent"] = True
        with self.assertRaisesRegex(
            gate.KppFrozenReconstructionV1DatasetError, "historical.*identity"
        ):
            gate.validate_kpp_frozen_reconstruction_v1_documents(
                manifest, self.authorization
            )

    def test_documents_reject_manifest_self_hash_drift(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["manifest_sha256"] = "1" * 64
        with self.assertRaisesRegex(
            gate.KppFrozenReconstructionV1DatasetError, "self hash"
        ):
            gate.validate_kpp_frozen_reconstruction_v1_documents(
                manifest, self.authorization
            )

    def test_gate_ignores_unrelated_dataset(self) -> None:
        self.assertFalse(
            gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
                "smoke_testsrc",
                self.catalog["smoke_testsrc"],
                project_root=ROOT,
                require_files=False,
            )
        )

    def test_benchmark_loader_invokes_reconstruction_gate(self) -> None:
        entry = copy.deepcopy(self.catalog[gate.DATASET_IDS["h264"]])
        entry["provenance"]["claims"][
            "historical_v1_dataset_identity_equivalent"
        ] = True
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = Path(tmp) / "datasets.yaml"
            manifest_path.write_text(
                yaml.safe_dump({"datasets": {gate.DATASET_IDS["h264"]: entry}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ContractError, "provenance"):
                load_dataset(
                    manifest_path,
                    gate.DATASET_IDS["h264"],
                    mode="benchmark",
                    project_root=ROOT,
                    require_files=False,
                )


if __name__ == "__main__":
    unittest.main()
