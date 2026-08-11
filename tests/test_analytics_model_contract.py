from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_model_contract import (  # noqa: E402
    MODEL_BINDING_ARTIFACT_KIND,
    MODEL_BINDING_SCHEMA_VERSION,
    load_analytics_model_bindings,
)
from benchmark_contract import ContractError  # noqa: E402


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
OMZ_REVISION = "602c643ac909f1bbfa1fed0f3c4723772508d7d9"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class AnalyticsModelContractTests(unittest.TestCase):
    def _write_manifest(self, root: Path) -> Path:
        branches = {}
        for index, branch in enumerate(BRANCHES, start=1):
            model = root / f"model-{index}.xml"
            weights = root / f"model-{index}.bin"
            model.write_text(f"model-{index}\n", encoding="utf-8")
            weights.write_bytes(f"weights-{index}\n".encode("ascii"))
            source_name = f"omz-proxy-{index}"
            branches[branch] = {
                "proxy_role": branch,
                "semantic_claim": "topology_load_proxy_only",
                "source_model_name": source_name,
                "source_model_config_url": (
                    "https://raw.githubusercontent.com/openvinotoolkit/"
                    f"open_model_zoo/{OMZ_REVISION}/models/intel/{source_name}/model.yml"
                ),
                "factory": "gvadetect",
                "device": "CPU",
                "input_format": "BGR",
                "batch_size": 1,
                "nireq": 1,
                "ie_config": "PERFORMANCE_HINT=LATENCY,NUM_STREAMS=1,INFERENCE_NUM_THREADS=1",
                "detector_id": f"{branch}-omz-fp16-v1",
                "model_path": model.name,
                "model_sha256": _digest(model),
                "model_source_url": (
                    "https://storage.openvinotoolkit.org/repositories/"
                    f"open_model_zoo/2023.0/models_bin/1/{source_name}/FP16/{source_name}.xml"
                ),
                "model_source_sha384": "a" * 96,
                "weights_path": weights.name,
                "weights_sha256": _digest(weights),
                "weights_source_url": (
                    "https://storage.openvinotoolkit.org/repositories/"
                    f"open_model_zoo/2023.0/models_bin/1/{source_name}/FP16/{source_name}.bin"
                ),
                "weights_source_sha384": "b" * 96,
                "input": {
                    "name": "image",
                    "layout": "NCHW",
                    "shape": [1, 3, 300 + index, 300 + index],
                    "color_order": "BGR",
                },
                "output": {
                    "semantics": "openvino_detection_output_1x1nx7",
                    "coordinates": "normalized_xyxy",
                },
            }
        manifest = {
            "schema_version": MODEL_BINDING_SCHEMA_VERSION,
            "artifact_kind": MODEL_BINDING_ARTIFACT_KIND,
            "manifest_id": "kpp-openvino-omz-proxies-fp16-v1",
            "selection_basis": "public_omz_proxies_frozen_before_benchmark_results",
            "runtime_family": "openvino_dlstreamer",
            "precision": "FP16",
            "effective_batch_size": 1,
            "provenance": {
                "catalog": "Open Model Zoo",
                "catalog_version": "2024.6.0",
                "catalog_revision": OMZ_REVISION,
                "license_spdx": "Apache-2.0",
                "license_url": (
                    "https://raw.githubusercontent.com/openvinotoolkit/"
                    f"open_model_zoo/{OMZ_REVISION}/LICENSE"
                ),
                "acquisition_tool": "omz_downloader",
            },
            "branches": branches,
        }
        path = root / "models.yaml"
        path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
        return path

    def test_accepts_exact_provenance_artifacts_and_interfaces(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bindings = load_analytics_model_bindings(
                self._write_manifest(Path(tmp)), required_branches=BRANCHES
            )

        self.assertEqual(set(bindings), set(BRANCHES))
        self.assertEqual(bindings["plate_number"]["factory"], "gvadetect")
        self.assertEqual(bindings["plate_number"]["device"], "CPU")
        self.assertEqual(bindings["plate_number"]["input_format"], "BGR")
        self.assertEqual(bindings["plate_number"]["batch_size"], "1")
        self.assertEqual(bindings["plate_number"]["nireq"], "1")
        self.assertIn("INFERENCE_NUM_THREADS=1", bindings["plate_number"]["ie_config"])
        self.assertEqual(bindings["damage"]["semantic_claim"], "topology_load_proxy_only")
        self.assertEqual(bindings["foreign_object"]["input_layout"], "NCHW")
        self.assertEqual(bindings["vehicle_type"]["output_semantics"], "openvino_detection_output_1x1nx7")

    def test_rejects_duplicate_detector_ids_and_source_models(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write_manifest(Path(tmp))
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            raw["branches"]["damage"]["detector_id"] = raw["branches"]["vehicle_type"]["detector_id"]
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "detector_id.*unique"):
                load_analytics_model_bindings(path, required_branches=BRANCHES)

            raw["branches"]["damage"]["detector_id"] = "damage-unique"
            raw["branches"]["damage"]["source_model_name"] = raw["branches"]["vehicle_type"]["source_model_name"]
            path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
            with self.assertRaisesRegex(ContractError, "source_model_name.*unique"):
                load_analytics_model_bindings(path, required_branches=BRANCHES)

    def test_rejects_license_source_interface_and_digest_drift(self) -> None:
        mutations = (
            (lambda raw: raw["provenance"].update({"license_spdx": "unknown"}), "license_spdx"),
            (
                lambda raw: raw["branches"]["damage"].update(
                    {"source_model_config_url": "https://example.invalid/model.yml"}
                ),
                "source_model_config_url",
            ),
            (
                lambda raw: raw["branches"]["damage"]["input"].update(
                    {"layout": "UNKNOWN"}
                ),
                "input.layout",
            ),
            (
                lambda raw: raw["branches"]["damage"].update(
                    {"model_sha256": "0" * 64}
                ),
                "model SHA-256",
            ),
        )
        for mutate, message in mutations:
            with self.subTest(message=message), tempfile.TemporaryDirectory() as tmp:
                path = self._write_manifest(Path(tmp))
                raw = yaml.safe_load(path.read_text(encoding="utf-8"))
                mutate(raw)
                path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
                with self.assertRaisesRegex(ContractError, message):
                    load_analytics_model_bindings(path, required_branches=BRANCHES)

    def test_repository_manifest_is_complete_and_hash_bound(self) -> None:
        bindings = load_analytics_model_bindings(
            ROOT / "configs" / "checkpoint_analytics_models_openvino.yaml",
            required_branches=BRANCHES,
        )
        self.assertEqual(set(bindings), set(BRANCHES))
        self.assertTrue(all(value["model_path"].endswith(".xml") for value in bindings.values()))
        self.assertTrue(all(value["weights_sha256"] for value in bindings.values()))
        self.assertTrue(all(value["factory"] == "gvadetect" for value in bindings.values()))
        self.assertTrue(all(value["input_format"] == "BGR" for value in bindings.values()))


if __name__ == "__main__":
    unittest.main()
