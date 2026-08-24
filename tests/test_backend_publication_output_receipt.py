from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_publication_dispatch import launcher_invocation_contract  # noqa: E402
from backend_publication_output_receipt import (  # noqa: E402
    ARM_CONTRACT_FILENAME,
    LAUNCHER_RESULT_FILENAME,
    OUTPUT_RECEIPT_FILENAME,
    BackendPublicationOutputReceiptError,
    commit_backend_publication_output_receipt,
    launcher_output_protocol,
    validate_backend_publication_artifacts,
    validate_backend_publication_output_receipt,
    write_immutable_backend_publication_arm_contract,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def execution(*, arm_id: str = "arm-1", sequence: int = 1) -> dict[str, object]:
    return {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_arm_execution_binding",
        "run_identity_sha256": "1" * 64,
        "sequence": sequence,
        "pair_id": f"pair-{sequence}",
        "attempt": 1,
        "arm_id": arm_id,
    }


def resolution(*, policy: str = "cpu_only") -> dict[str, object]:
    invocation = launcher_invocation_contract()
    value: dict[str, object] = {
        "schema_version": 2,
        "artifact_kind": "vast_backend_publication_dispatch_resolution",
        "backend_runtime_grant_sha256": "2" * 64,
        "identity_artifact_binding_sha256": "3" * 64,
        "system": "deepstream",
        "codec": "h264",
        "topology_kind": "shared_video_dag",
        "policy": policy,
        "deadline_ms": 50,
        "cell_identity_sha256": "4" * 64,
        "validation_record_sha256": "5" * 64,
        "runtime_binding_identity_sha256": "6" * 64,
        "launcher": {
            "path": "runtime/deepstream/publication_launcher.py",
            "size_bytes": 17,
            "sha256": "7" * 64,
        },
        "launcher_invocation": invocation,
        "launcher_invocation_sha256": invocation["invocation_sha256"],
    }
    value["resolution_sha256"] = canonical_sha(value)
    return value


def arm_contract(
    output_dir: Path,
    *,
    arm_id: str = "arm-1",
    sequence: int = 1,
    policy: str = "cpu_only",
    execution_binding: dict[str, object] | None = None,
    backend_grant_sha256: str = "2" * 64,
    resource_grant_sha256: str = "8" * 64,
    model_parity_grant_sha256: str = "9" * 64,
    model_parity_acceptance_binding_sha256: str = "a" * 64,
    identity_artifact_binding_sha256: str = "3" * 64,
) -> dict[str, object]:
    dispatch = resolution(policy=policy)
    binding = copy.deepcopy(
        execution_binding
        if execution_binding is not None
        else execution(arm_id=arm_id, sequence=sequence)
    )
    dispatch["backend_runtime_grant_sha256"] = backend_grant_sha256
    dispatch["identity_artifact_binding_sha256"] = (
        identity_artifact_binding_sha256
    )
    dispatch.pop("resolution_sha256")
    dispatch["resolution_sha256"] = canonical_sha(dispatch)
    value: dict[str, object] = {
        "schema_version": 2,
        "artifact_kind": "vast_backend_publication_arm_dispatch_contract",
        "full_publication_execution_binding": binding,
        "resource_capability_grant_sha256": resource_grant_sha256,
        "model_parity_grant_sha256": model_parity_grant_sha256,
        "model_parity_acceptance_binding_sha256": (
            model_parity_acceptance_binding_sha256
        ),
        "backend_runtime_grant_sha256": dispatch[
            "backend_runtime_grant_sha256"
        ],
        "identity_artifact_binding_sha256": dispatch[
            "identity_artifact_binding_sha256"
        ],
        "dispatch_resolution": dispatch,
        "runtime_inputs": {
            "system": "deepstream",
            "scenario": "checkpoint_video_dag_shared",
            "topology_kind": "shared_video_dag",
            "codec": "h264",
            "policy": policy,
            "deadline_ms": 50,
            "dataset": {"name": "kpp"},
            "streams": 6,
            "duration_s": 300,
            "repeat_index": 0,
            "base_seed": 20260323,
            "run_seed": 1234,
            "run_id": f"run-{arm_id}",
            "output_dir": str(output_dir.resolve()),
        },
        "launcher_output_protocol": launcher_output_protocol(policy),
    }
    value["contract_sha256"] = canonical_sha(value)
    return value


def write_launcher_evidence(output_dir: Path, contract: dict[str, object]) -> None:
    protocol = contract["launcher_output_protocol"]
    assert isinstance(protocol, dict)
    names = protocol["launcher_evidence_files"]
    assert isinstance(names, list)
    for index, name in enumerate(names):
        (output_dir / str(name)).write_bytes(f"evidence-{index}\n".encode())


def materialize(
    root: Path,
    *,
    arm_id: str = "arm-1",
    sequence: int = 1,
    policy: str = "cpu_only",
    execution_binding: dict[str, object] | None = None,
    backend_grant_sha256: str = "2" * 64,
    resource_grant_sha256: str = "8" * 64,
    model_parity_grant_sha256: str = "9" * 64,
    model_parity_acceptance_binding_sha256: str = "a" * 64,
    identity_artifact_binding_sha256: str = "3" * 64,
) -> tuple[dict[str, object], dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    contract = arm_contract(
        root,
        arm_id=arm_id,
        sequence=sequence,
        policy=policy,
        execution_binding=execution_binding,
        backend_grant_sha256=backend_grant_sha256,
        resource_grant_sha256=resource_grant_sha256,
        model_parity_grant_sha256=model_parity_grant_sha256,
        model_parity_acceptance_binding_sha256=(
            model_parity_acceptance_binding_sha256
        ),
        identity_artifact_binding_sha256=identity_artifact_binding_sha256,
    )
    contract_authority = write_immutable_backend_publication_arm_contract(
        root / ARM_CONTRACT_FILENAME,
        contract,
    )
    write_launcher_evidence(root, contract)
    receipt_authority = commit_backend_publication_output_receipt(
        arm_contract_path=root / ARM_CONTRACT_FILENAME,
        output_dir=root,
    )
    return contract_authority, receipt_authority


class BackendPublicationOutputReceiptTests(unittest.TestCase):
    def test_launcher_commit_and_runner_revalidation_crossbind_every_authority(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_authority, receipt_authority = materialize(root)
            checked = validate_backend_publication_artifacts(
                output_dir=root,
                expected_arm_contract_authority=contract_authority,
                expected_output_receipt_authority=receipt_authority,
            )
            self.assertEqual(
                checked["arm_contract_authority"], contract_authority
            )
            self.assertEqual(
                checked["output_receipt_authority"], receipt_authority
            )
            self.assertEqual(
                receipt_authority["launcher_result"]["path"],
                LAUNCHER_RESULT_FILENAME,
            )
            self.assertEqual(
                receipt_authority["path"], OUTPUT_RECEIPT_FILENAME
            )
            self.assertEqual(
                receipt_authority["full_publication_execution_binding"],
                execution(),
            )
            self.assertEqual(
                receipt_authority["run_identity_sha256"], "1" * 64
            )
            self.assertEqual(
                receipt_authority["backend_runtime_grant_sha256"], "2" * 64
            )
            self.assertEqual(
                receipt_authority["resource_capability_grant_sha256"], "8" * 64
            )
            self.assertEqual(
                receipt_authority["model_parity_grant_sha256"], "9" * 64
            )
            self.assertEqual(
                receipt_authority[
                    "model_parity_acceptance_binding_sha256"
                ],
                "a" * 64,
            )
            self.assertEqual(
                json.loads(
                    (root / ARM_CONTRACT_FILENAME).read_text(encoding="utf-8")
                )["dispatch_resolution"]["launcher_invocation"]["schema_version"],
                2,
            )
            self.assertEqual(
                checked["arm_contract_authority"]["model_parity_grant_sha256"],
                "9" * 64,
            )
            for filename in (
                ARM_CONTRACT_FILENAME,
                LAUNCHER_RESULT_FILENAME,
                OUTPUT_RECEIPT_FILENAME,
            ):
                physical = json.loads(
                    (root / filename).read_text(encoding="utf-8")
                )
                self.assertEqual(
                    physical["model_parity_acceptance_binding_sha256"],
                    "a" * 64,
                )
            receipt = json.loads(
                (root / OUTPUT_RECEIPT_FILENAME).read_text(encoding="utf-8")
            )
            unsigned = {
                key: value
                for key, value in receipt.items()
                if key != "receipt_sha256"
            }
            self.assertEqual(receipt["receipt_sha256"], canonical_sha(unsigned))

    def test_absent_receipt_or_ignored_contract_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = arm_contract(root)
            authority = write_immutable_backend_publication_arm_contract(
                root / ARM_CONTRACT_FILENAME,
                contract,
            )
            with self.assertRaisesRegex(
                BackendPublicationOutputReceiptError, "receipt.*missing"
            ):
                validate_backend_publication_output_receipt(
                    output_dir=root,
                    expected_arm_contract_authority=authority,
                )
            with self.assertRaisesRegex(
                BackendPublicationOutputReceiptError, "evidence.*missing"
            ):
                commit_backend_publication_output_receipt(
                    arm_contract_path=root / ARM_CONTRACT_FILENAME,
                    output_dir=root,
                )

    def test_tampered_result_receipt_and_evidence_fail_closed(self) -> None:
        for target_name in (
            LAUNCHER_RESULT_FILENAME,
            OUTPUT_RECEIPT_FILENAME,
            "frames.csv",
        ):
            with self.subTest(target=target_name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                contract_authority, receipt_authority = materialize(root)
                path = root / target_name
                path.write_bytes(path.read_bytes() + b"tamper")
                with self.assertRaises(BackendPublicationOutputReceiptError):
                    validate_backend_publication_artifacts(
                        output_dir=root,
                        expected_arm_contract_authority=contract_authority,
                        expected_output_receipt_authority=receipt_authority,
                    )

    def test_swapped_or_replayed_receipt_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            first = base / "first"
            second = base / "second"
            materialize(first, arm_id="arm-1", sequence=1)
            second_contract, second_receipt = materialize(
                second, arm_id="arm-2", sequence=2
            )
            for name in (LAUNCHER_RESULT_FILENAME, OUTPUT_RECEIPT_FILENAME):
                (second / name).write_bytes((first / name).read_bytes())
            with self.assertRaises(BackendPublicationOutputReceiptError):
                validate_backend_publication_artifacts(
                    output_dir=second,
                    expected_arm_contract_authority=second_contract,
                    expected_output_receipt_authority=second_receipt,
                )

    def test_immutable_collisions_and_hardlink_aliases_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_authority, receipt_authority = materialize(root)
            with self.assertRaisesRegex(
                BackendPublicationOutputReceiptError, "already exists"
            ):
                commit_backend_publication_output_receipt(
                    arm_contract_path=root / ARM_CONTRACT_FILENAME,
                    output_dir=root,
                )
            original = root / "frames.csv"
            alias_source = root / "alias-source"
            alias_source.write_bytes(original.read_bytes())
            original.unlink()
            os.link(alias_source, original)
            with self.assertRaisesRegex(
                BackendPublicationOutputReceiptError, "hardlink"
            ):
                validate_backend_publication_artifacts(
                    output_dir=root,
                    expected_arm_contract_authority=contract_authority,
                    expected_output_receipt_authority=receipt_authority,
                )

    def test_adaptive_policy_requires_feedback_in_exact_evidence_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract_authority, receipt_authority = materialize(
                root, policy="adaptive_weights"
            )
            names = {
                item["path"] for item in receipt_authority["evidence_files"]
            }
            self.assertIn("publication_policy_feedback.jsonl", names)
            validate_backend_publication_artifacts(
                output_dir=root,
                expected_arm_contract_authority=contract_authority,
                expected_output_receipt_authority=receipt_authority,
            )


if __name__ == "__main__":
    unittest.main()
