from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_qualification as qualification  # noqa: E402
import publication_policy_qualification_index_v2 as target  # noqa: E402
from tests.test_publication_policy_qualification import (  # noqa: E402
    SYSTEMS,
    _PolicyApi,
    _fake_fragment_validator,
    _fake_pilot_validator,
    _fragment_bound_fixture,
)


class PublicationPolicyQualificationIndexV2Tests(unittest.TestCase):
    def test_pilot_index_requires_distinct_qualification_acceptance_filename(self) -> None:
        self.assertEqual(
            target.PILOT_EVIDENCE_FILENAMES["checkpoint_acceptance"],
            "checkpoint_qualification_pilot_acceptance.json",
        )

    def _fixture(self, root: Path) -> tuple[dict[str, Path], Path]:
        _index_path, index = _fragment_bound_fixture(root)
        fragments = {}
        for system in SYSTEMS:
            row = next(value for value in index["bindings"] if value["system"] == system)
            fragments[system] = root / row["fragment_artifact"]["path"]
        return fragments, root / "pilots"

    def test_builds_nonaccepted_candidate_and_complete_fragment_bound_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            output = root / "qualification-v2"
            result = target.build_policy_qualification_index_v2(
                project_root=root,
                fragment_paths=fragments,
                pilot_root=pilots,
                output_dir=output,
                policy=_PolicyApi,
                fragment_validator=_fake_fragment_validator,
            )
            candidate = json.loads(result["candidate_manifest_path"].read_text(encoding="utf-8"))
            receipt = json.loads(result["candidate_receipt_path"].read_text(encoding="utf-8"))
            index = json.loads(result["index_path"].read_text(encoding="utf-8"))
            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(len(index["bindings"]), 32)
            self.assertEqual(len(index["pilots"]), 32)
            self.assertTrue(
                all(
                    pilot["evidence"]["checkpoint_acceptance"]["path"].endswith(
                        "/checkpoint_qualification_pilot_acceptance.json"
                    )
                    for pilot in index["pilots"]
                )
            )
            self.assertFalse(receipt["accepted"])
            self.assertFalse(receipt["publication_ready"])
            self.assertEqual(receipt["status"], "qualification_candidate_not_accepted")
            self.assertEqual(
                receipt["candidate_manifest"]["sha256"],
                target.sha256_file(result["candidate_manifest_path"]),
            )
            self.assertEqual(
                candidate["artifact_kind"],
                "vast_publication_policy_capability_manifest",
            )

            with mock.patch.object(qualification, "_load_policy_contract", return_value=_PolicyApi):
                assessment = qualification.assess_policy_qualification(
                    project_root=root,
                    index_path=result["index_path"],
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertTrue(assessment["passed"], assessment["blockers"])

    def test_fragment_only_candidate_breaks_bootstrap_cycle_and_stays_nonaccepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, _pilots = self._fixture(root)
            result = target.build_policy_qualification_index_v2(
                project_root=root,
                fragment_paths=fragments,
                pilot_root=None,
                output_dir=root / "fragment-only-candidate",
                policy=_PolicyApi,
                fragment_validator=_fake_fragment_validator,
            )

            index = json.loads(result["index_path"].read_text(encoding="utf-8"))
            candidate = json.loads(
                result["candidate_manifest_path"].read_text(encoding="utf-8")
            )
            receipt = json.loads(
                result["candidate_receipt_path"].read_text(encoding="utf-8")
            )
            self.assertEqual(index["schema_version"], 2)
            self.assertEqual(len(index["bindings"]), 32)
            self.assertEqual(index["pilots"], [])
            self.assertEqual(
                receipt["scope"], "forced_resource_qualification_pilots_only"
            )
            self.assertFalse(receipt["accepted"])
            self.assertFalse(receipt["publication_ready"])
            self.assertIn(
                "requires_32_cell_native_pilot_validation_and_atomic_promotion",
                receipt["blockers"],
            )
            self.assertEqual(
                candidate["artifact_kind"],
                "vast_publication_policy_capability_manifest",
            )

            with mock.patch.object(
                qualification, "_load_policy_contract", return_value=_PolicyApi
            ):
                assessment = qualification.assess_policy_qualification(
                    project_root=root,
                    index_path=result["index_path"],
                    pilot_validator=_fake_pilot_validator,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertFalse(assessment["passed"])
            self.assertIn("expected exactly 32 pilots", " ".join(assessment["blockers"]))

    def test_missing_pilot_evidence_and_fragment_drift_fail_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            missing = next(pilots.rglob("frames.csv"))
            missing.unlink()
            with self.assertRaisesRegex(target.PolicyQualificationIndexV2Error, "pilot evidence"):
                target.build_policy_qualification_index_v2(
                    project_root=root,
                    fragment_paths=fragments,
                    pilot_root=pilots,
                    output_dir=root / "missing-output",
                    policy=_PolicyApi,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertFalse((root / "missing-output").exists())

            fragments, pilots = self._fixture(root / "second")
            fragment = fragments["deepstream"]
            fragment.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(target.PolicyQualificationIndexV2Error, "fragment"):
                target.build_policy_qualification_index_v2(
                    project_root=root / "second",
                    fragment_paths=fragments,
                    pilot_root=pilots,
                    output_dir=root / "second" / "drift-output",
                    policy=_PolicyApi,
                    fragment_validator=_fake_fragment_validator,
                )
            self.assertFalse((root / "second" / "drift-output").exists())

    def test_atomic_commit_failure_cleans_only_private_staging_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fragments, pilots = self._fixture(root)
            sentinel = root / "must-survive.txt"
            sentinel.write_text("workspace sentinel\n", encoding="utf-8")
            output = root / "qualification-v2"

            with mock.patch.object(target.os, "replace", side_effect=OSError("injected")):
                with self.assertRaisesRegex(
                    target.PolicyQualificationIndexV2Error,
                    "atomic qualification candidate commit failed",
                ):
                    target.build_policy_qualification_index_v2(
                        project_root=root,
                        fragment_paths=fragments,
                        pilot_root=pilots,
                        output_dir=output,
                        policy=_PolicyApi,
                        fragment_validator=_fake_fragment_validator,
                    )

            self.assertEqual(
                sentinel.read_text(encoding="utf-8"), "workspace sentinel\n"
            )
            self.assertFalse(output.exists())
            self.assertEqual(list(root.glob(".qualification-index-v2.*")), [])


if __name__ == "__main__":
    unittest.main()
