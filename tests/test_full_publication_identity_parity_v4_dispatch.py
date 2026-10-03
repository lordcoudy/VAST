from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import full_publication_identity_artifacts as identity_artifacts


class FullIdentityParityDispatchTest(unittest.TestCase):
    def _receipt(self, schema: int, kind: str) -> Path:
        directory = tempfile.mkdtemp(
            prefix="parity-v4-dispatch-", dir=ROOT / "staging"
        )
        self.addCleanup(
            lambda: __import__("shutil").rmtree(directory, ignore_errors=False)
        )
        path = Path(directory) / "receipt.json"
        path.write_text(
            json.dumps(
                {"schema_version": schema, "artifact_kind": kind},
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        return path

    def test_dispatches_only_exact_v4_coordinate(self) -> None:
        receipt = self._receipt(
            4, "vast_checkpoint_model_parity_acceptance_receipt_v4"
        )
        expected = {
            "schema_version": 4,
            "artifact_kind": "vast_verified_model_parity_acceptance_binding_v4",
        }
        with mock.patch(
            "checkpoint_model_parity_acceptance_v4.load_verified_model_parity_acceptance_v4",
            return_value=expected,
        ) as loader:
            result = identity_artifacts._default_parity_acceptance_loader(
                project_root=ROOT, receipt_path=receipt
            )
        self.assertEqual(result, expected)
        loader.assert_called_once_with(project_root=ROOT, receipt_path=receipt)

    def test_unknown_schema_kind_has_no_v3_fallback(self) -> None:
        receipt = self._receipt(
            4, "vast_checkpoint_model_parity_acceptance_receipt"
        )
        with mock.patch(
            "checkpoint_model_parity_acceptance.load_verified_model_parity_acceptance"
        ) as legacy:
            with self.assertRaisesRegex(
                identity_artifacts.IdentityArtifactError, "unsupported"
            ):
                identity_artifacts._default_parity_acceptance_loader(
                    project_root=ROOT, receipt_path=receipt
                )
        legacy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
