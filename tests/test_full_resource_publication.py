from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import (  # noqa: E402
    FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
    FULL_RESOURCE_PUBLICATION_SCOPE,
    PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS,
    build_publication_evidence_bundle,
    publication_evidence_bundle_files,
    publication_evidence_bundle_identity,
    resolve_publication_evidence_bundle_scope,
)


class FullResourcePublicationTests(unittest.TestCase):
    def test_accepted_v2_config_selects_full_scope_for_matrix_policy(self) -> None:
        with (ROOT / "configs" / "experiments.yaml").open("r", encoding="utf-8") as source:
            config = copy.deepcopy(yaml.safe_load(source))
        extension = config["benchmark"]["resource_interval_extension"]
        extension["status"] = "accepted_full_resource_publication_v2"
        extension["current_publication_bundle_scope"] = FULL_RESOURCE_PUBLICATION_SCOPE
        extension["publication_bundle_bound"] = True
        extension["evidence_accepted"] = True

        scope = resolve_publication_evidence_bundle_scope(
            config,
            {
                "system": "deepstream",
                "scenario": "checkpoint_video_dag_shared",
                "policy": "adaptive_weights",
            },
        )
        self.assertEqual(scope, FULL_RESOURCE_PUBLICATION_SCOPE)

    def test_v2_scope_extends_v1_with_exact_resource_evidence(self) -> None:
        expected_resource_files = {
            "resource_intervals.csv",
            "hardware_resource_samples.csv",
            "fanout_work_counters.csv",
        }
        self.assertEqual(
            FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
            PRIMARY_ARCHITECTURE_REQUIRED_SIDECARS | expected_resource_files,
        )
        self.assertEqual(
            set(publication_evidence_bundle_files(FULL_RESOURCE_PUBLICATION_SCOPE)),
            FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
        )

    def test_v2_bundle_identity_binds_every_resource_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES:
                (root / name).write_text(f"{name}\n", encoding="utf-8")
            bundle = build_publication_evidence_bundle(
                root,
                scope=FULL_RESOURCE_PUBLICATION_SCOPE,
            )
            identity = publication_evidence_bundle_identity(bundle)

            self.assertEqual(bundle["scope"], FULL_RESOURCE_PUBLICATION_SCOPE)
            self.assertEqual(
                {entry["relative_path"] for entry in bundle["files"]},
                FULL_RESOURCE_PUBLICATION_EVIDENCE_FILES,
            )
            self.assertRegex(identity["sha256"], r"^[0-9a-f]{64}$")


if __name__ == "__main__":
    unittest.main()
