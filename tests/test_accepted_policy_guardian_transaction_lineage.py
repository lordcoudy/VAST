"""Guard the cold transaction boundary before the expensive production assessment."""

from __future__ import annotations

import copy
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import publication_guardian_accepted_policy_preprocessing_contract_v1 as target
import publication_policy_qualification as stock
from test_publication_guardian_accepted_policy_preprocessing_contract_v1 import (
    descriptor, semantic, write_json,
)


class TransactionBoundaryFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.fragments = {}
        for system in target.SYSTEMS:
            path = root / "fragments" / f"{system}.json"
            write_json(path, {"artificial_fixture": system})
            self.fragments[system] = descriptor(root, path)
        self.authority_path = root / "authority.json"
        write_json(self.authority_path, {"artificial_fixture": "physical descriptor only"})
        authority = descriptor(root, self.authority_path)
        self.transaction_path = root / "transaction.json"
        self.transaction = {
            "schema_version": 2,
            "artifact_kind": "vast_publication_policy_qualification_input_transaction_v2",
            "status": "qualification_inputs_materialized_nonaccepted",
            "scope": "forced_resource_qualification_pilots_only",
            "accepted": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "systems": list(target.SYSTEMS),
            "cell_count": 32,
            "hardware_resource_collector": authority,
            "image_identity_patch": authority,
            "accepted_model_parity_manifest": authority,
            "accepted_model_parity_assessment": authority,
            "accepted_model_parity_receipt": authority,
            "fragments": self.fragments,
            "candidate": {name: authority for name in ("index", "manifest", "receipt")},
            "bootstrap": {
                "mapping": authority,
                "receipt": authority,
                "calibrations": {system: authority for system in target.SYSTEMS},
            },
        }
        self.closure_path = root / "closure.json"
        self.index_path = root / "index.json"
        self.closure_fragments = self.fragments
        self.index_fragments = self.fragments
        self.rewrite()

    def rewrite(self) -> None:
        self.transaction.pop("receipt_sha256", None)
        self.transaction["receipt_sha256"] = semantic(self.transaction)
        write_json(self.transaction_path, self.transaction)
        write_json(self.closure_path, {
            "qualification_input_transaction": {
                "receipt": descriptor(self.root, self.transaction_path),
                "receipt_sha256": self.transaction["receipt_sha256"],
                "fragments": self.closure_fragments,
            },
        })
        write_json(self.index_path, {
            "qualification_execution_closure": descriptor(self.root, self.closure_path),
            "bindings": [
                {"system": system, "fragment_artifact": self.index_fragments[system]}
                for system in target.SYSTEMS
            ],
        })

    def assess(self):
        return target._default_assess_policy_qualification(
            project_root=self.root, index_path=self.index_path,
        )


class DefaultGuardianTransactionLineageTests(unittest.TestCase):
    def test_cold_validation_holds_custody_and_restores_context_on_success_and_refusal(self):
        import publication_policy_qualification_transaction_validation_v2 as transaction

        read = transaction.PhysicalRootCustodyV1.read_descriptor_identity
        for refuse in (False, True):
            with self.subTest(refuse=refuse), tempfile.TemporaryDirectory() as temporary:
                fixture = TransactionBoundaryFixture(Path(temporary).resolve())
                if refuse:
                    fixture.authority_path.write_bytes(b"changed physical authority\n")
                self.assertIsNone(transaction._ACTIVE_CUSTODY.get())
                with mock.patch.object(
                    transaction.PhysicalRootCustodyV1, "read_descriptor_identity",
                    autospec=True, side_effect=read,
                ) as held_read, mock.patch.object(
                    stock, "assess_policy_qualification", return_value={},
                ) as assess:
                    if refuse:
                        with self.assertRaises(target.AcceptedPolicyGuardianPreprocessingContractV1Error):
                            fixture.assess()
                        assess.assert_not_called()
                    else:
                        fixture.assess()
                    labels = [call.kwargs["label"] for call in held_read.call_args_list]
                    self.assertIn("cold transaction receipt", labels)
                    self.assertIn("transaction receipt", labels)
                self.assertIsNone(transaction._ACTIVE_CUSTODY.get())

    def test_valid_cold_descriptors_select_shared_validators_not_a_stock_fallback(self):
        # The spy verifies routing only, not qualification or fragment/pilot acceptance.
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TransactionBoundaryFixture(Path(temporary).resolve())
            with mock.patch.object(stock, "assess_policy_qualification", return_value={}) as assess:
                fixture.assess()
            from publication_policy_qualification_fragment_validation_v2 import (
                validate_publication_policy_qualification_fragment_from_authority_v2,
            )
            from publication_policy_qualification_pilot_validation_v2 import policy_pilot_validator
            self.assertIs(assess.call_args.kwargs["fragment_validator"],
                          validate_publication_policy_qualification_fragment_from_authority_v2)
            self.assertIs(assess.call_args.kwargs["pilot_validator"], policy_pilot_validator)

    def test_foreign_or_mutated_transaction_refuses_before_assessment(self):
        cases = (
            lambda f: f.transaction.update(artifact_kind="study"),
            lambda f: f.transaction.update(schema_version=True),
            lambda f: f.transaction.update(status="accepted"),
            lambda f: f.transaction.update(scope="full_publication"),
            lambda f: f.transaction.update(accepted=True),
            lambda f: f.transaction.update(authorization_eligible=True),
            lambda f: f.transaction.update(cell_count=31),
            lambda f: f.transaction.update(systems=["deepstream"]),
            lambda f: f.closure_fragments.update(deepstream=f.fragments["savant"]),
            lambda f: f.index_fragments.update(deepstream=f.fragments["savant"]),
        )
        for position, mutate in enumerate(cases):
            with self.subTest(case=position), tempfile.TemporaryDirectory() as temporary:
                fixture = TransactionBoundaryFixture(Path(temporary).resolve())
                fixture.closure_fragments = copy.deepcopy(fixture.fragments)
                fixture.index_fragments = copy.deepcopy(fixture.fragments)
                mutate(fixture)
                fixture.rewrite()
                with mock.patch.object(stock, "assess_policy_qualification") as assess:
                    with self.assertRaises(target.AcceptedPolicyGuardianPreprocessingContractV1Error):
                        fixture.assess()
                    assess.assert_not_called()
        with tempfile.TemporaryDirectory() as temporary:
            fixture = TransactionBoundaryFixture(Path(temporary).resolve())
            fixture.authority_path.write_bytes(b"mutated physical authority\n")
            with mock.patch.object(stock, "assess_policy_qualification") as assess:
                with self.assertRaises(target.AcceptedPolicyGuardianPreprocessingContractV1Error):
                    fixture.assess()
                assess.assert_not_called()


if __name__ == "__main__":
    unittest.main()
