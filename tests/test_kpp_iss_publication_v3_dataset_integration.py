from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from benchmark_contract import ContractError, load_dataset  # noqa: E402
import kpp_iss_publication_v3_dataset as gate  # noqa: E402
import prepare_benchmark_dataset as prepare  # noqa: E402


DATASET_IDS = (
    "kpp_iss_publication_v3_h264",
    "kpp_iss_publication_v3_h265",
)
CORPUS_ROOT = "data/videos/kpp/kpp_iss_publication_v3"
MANIFEST_PATH = f"{CORPUS_ROOT}/kpp_iss_publication_v3_manifest.json"
AUTHORIZATION_PATH = (
    f"{CORPUS_ROOT}/kpp_iss_publication_v3_authorization_receipt.json"
)
HISTORICAL_ENTRY_SHA256 = {
    "kpp_real_avi": "9d36bc982b321f0b8f9b9ffe51f5eb37914c974c726284bb2b8a85edf6de55b9",
    "kpp_real_h264": "70f9ab8d2770d19632a7e2b70f53fc46c4e682134c679524b9031b64b461aad0",
    "kpp_real_h265": "fc6629f82983884e82cf82a68c1170853948a18770e04f67a69095e7e9bd7032",
    "kpp_legacy_iss_v2_avi": "8a3227f27efd9f098899360e86e1951d0c195fa06bb3587b1fc964329f2b1997",
    "kpp_legacy_iss_v2_h264": "b314850eb37aa13aa78c00d87287bcab3760a0269471e589030f85ea5a116794",
    "kpp_legacy_iss_v2_h265": "5993c04d2f0fa32cc2628dfc3fc35f1feef415349483db7bdf1457b0ef9de88b",
}


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def sha(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def read_json(relative: str) -> dict[str, object]:
    return json.loads((ROOT / relative).read_text(encoding="ascii"))


class KppIssPublicationV3DatasetIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = yaml.safe_load(
            (ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8")
        )
        cls.datasets = config["datasets"]
        cls.manifest = read_json(MANIFEST_PATH)
        cls.authorization = read_json(AUTHORIZATION_PATH)
        cls.receipts = {
            str(value["role"]): read_json(str(value["path"]))
            for value in cls.manifest["source_receipts"]
        }

    def test_repository_yaml_adds_exact_publishable_v3_without_historical_drift(self) -> None:
        for name, expected in HISTORICAL_ENTRY_SHA256.items():
            with self.subTest(historical=name):
                self.assertEqual(sha(self.datasets[name]), expected)

        self.assertTrue(set(DATASET_IDS).issubset(self.datasets))
        for name in DATASET_IDS:
            with self.subTest(dataset=name):
                entry = self.datasets[name]
                self.assertEqual(entry["dataset_contract_version"], 3)
                self.assertEqual(entry["generation_id"], "kpp_iss_publication_v3")
                self.assertEqual(entry["status"], "frozen_publication_corpus")
                self.assertIs(entry["publishable"], True)
                self.assertEqual(
                    entry["publication_scope"],
                    "performance_and_topology_benchmark_results_only",
                )
                self.assertIs(entry["annotations"]["accuracy_ground_truth"], False)
                self.assertTrue(gate.validate_kpp_iss_publication_v3_manifest_entry(
                    name,
                    entry,
                    project_root=ROOT,
                    require_files=False,
                ))

    def test_manifest_pin_self_hash_authorization_receipts_media_and_claims_are_exact(self) -> None:
        descriptor = self.datasets[DATASET_IDS[0]]["provenance"][
            "publication_manifest"
        ]
        payload = (ROOT / MANIFEST_PATH).read_bytes()
        self.assertEqual(descriptor, gate.EXPECTED_MANIFEST_DESCRIPTOR)
        self.assertEqual(descriptor["path"], MANIFEST_PATH)
        self.assertEqual(descriptor["size_bytes"], len(payload))
        self.assertEqual(descriptor["file_sha256"], hashlib.sha256(payload).hexdigest())
        self.assertEqual(
            descriptor["manifest_sha256"], self.manifest["manifest_sha256"]
        )
        for name in DATASET_IDS:
            with self.subTest(dataset=name):
                self.assertTrue(gate.validate_kpp_iss_publication_v3_documents(
                    name,
                    self.datasets[name],
                    self.manifest,
                    self.authorization,
                    self.receipts,
                ))

    def test_require_files_rehashes_the_complete_exact_corpus(self) -> None:
        self.assertTrue(gate.validate_kpp_iss_publication_v3_manifest_entry(
            DATASET_IDS[0],
            self.datasets[DATASET_IDS[0]],
            project_root=ROOT,
            require_files=True,
        ))

    def test_self_consistent_broad_claims_and_integrity_drift_fail_closed(self) -> None:
        mutations = (
            "yaml_manifest_pin",
            "manifest_self_hash",
            "authorization_claim",
            "source_receipt_claim",
            "media_path",
            "yaml_claim",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                entry = copy.deepcopy(self.datasets[DATASET_IDS[0]])
                manifest = copy.deepcopy(self.manifest)
                authorization = copy.deepcopy(self.authorization)
                receipts = copy.deepcopy(self.receipts)
                if mutation == "yaml_manifest_pin":
                    entry["provenance"]["publication_manifest"]["file_sha256"] = "f" * 64
                elif mutation == "manifest_self_hash":
                    manifest["manifest_sha256"] = "f" * 64
                elif mutation == "authorization_claim":
                    authorization["claims"]["accuracy_ground_truth_validated"] = True
                    authorization["authorization_receipt_sha256"] = gate.document_self_hash(
                        authorization,
                        field="authorization_receipt_sha256",
                        domain=gate.AUTHORIZATION_RECEIPT_DOMAIN,
                    )
                elif mutation == "source_receipt_claim":
                    receipt = receipts["transcode"]
                    receipt["claims"]["publication_authorized"] = True
                    receipt["transcode_receipt_sha256"] = gate.document_self_hash(
                        receipt,
                        field="transcode_receipt_sha256",
                        domain=gate.SOURCE_RECEIPT_DOMAINS["transcode"],
                    )
                elif mutation == "media_path":
                    manifest["media_artifacts"][0]["path"] = (
                        f"{CORPUS_ROOT}/h264/unreceipted.mp4"
                    )
                    manifest["manifest_sha256"] = gate.document_self_hash(
                        manifest,
                        field="manifest_sha256",
                        domain=gate.MANIFEST_DOMAIN,
                    )
                else:
                    entry["provenance"]["claims"][
                        "production_routing_validated"
                    ] = True
                with self.assertRaises(gate.KppIssPublicationV3DatasetError):
                    gate.validate_kpp_iss_publication_v3_documents(
                        DATASET_IDS[0], entry, manifest, authorization, receipts
                    )

    def test_benchmark_loader_accepts_structural_v3_and_preparation_is_check_only(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            empty_root = Path(raw).resolve()
            for name in DATASET_IDS:
                with self.subTest(dataset=name):
                    dataset = load_dataset(
                        ROOT / "configs" / "datasets.yaml",
                        name,
                        mode="benchmark",
                        project_root=empty_root,
                        require_files=False,
                    )
                    self.assertIs(dataset["publishable"], True)
                    self.assertEqual(len(dataset["streams"]), 6)

        runner = mock.Mock(side_effect=AssertionError("ffmpeg must not run"))
        for name in DATASET_IDS:
            with self.subTest(prepare=name):
                plans = prepare.build_clip_plans(
                    manifest=ROOT / "configs" / "datasets.yaml",
                    dataset_name=name,
                    project_root=ROOT,
                    source_root=Path("data/videos"),
                    output_dir=Path("data/benchmark"),
                )
                self.assertEqual(plans, [])
                runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
