"""Amendment 8: Q1 steps 14-15 on real qualification transaction v2 outputs.

The fragments are materialized by the stock transaction-v2 fragment builder
(fixture of test_publication_policy_qualification_fragments_from_authority_v2);
only the authority loaders, the execution closure loader, the pilot validators
and the KPP dataset loader are substituted.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
for _path in (ROOT, SCRIPTS, ROOT / "tests"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from tests.test_publication_policy_qualification_fragments_from_authority_v2 import (  # noqa: E402
    Fixture as AuthorityFixture,
)
from tests.test_full_resource_qualification import (  # noqa: E402
    _datasets,
    _fake_pilot_validator as _fake_resource_pilot_validator,
)

import full_resource_qualification as resource_qualification  # noqa: E402
import full_resource_qualification_index_v1 as resource_index  # noqa: E402
import publication_policy_qualification as policy_qualification  # noqa: E402
import publication_policy_qualification_index_v2 as policy_index  # noqa: E402
import publication_policy_qualification_transaction_v2 as transaction_v2  # noqa: E402
import publication_qualification_promotion_v2 as promotion  # noqa: E402


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
RESOURCES = ("cpu", "gpu")
CODECS = ("h264", "h265")
TOPOLOGIES = ("independent_processes", "shared_video_dag")
# Host sources the resource index binds for transaction-v2 bindings (F2).
RESOURCE_SOURCES = (
    "scripts/full_resource_contract.py",
    "scripts/resource_interval_contract.py",
    "scripts/collect_metrics.py",
    "scripts/checkpoint_deepstream_resource_runtime_v3.py",
    "scripts/checkpoint_savant_resource_runtime_v3.py",
    "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp",
)
PILOT_FILES = sorted(
    set(policy_index.PILOT_EVIDENCE_FILENAMES.values())
    | set(resource_index.PILOT_EVIDENCE_FILENAMES.values())
)


def _canonical(value: object) -> bytes:
    return transaction_v2._canonical(value)


def _descriptor(root: Path, path: Path) -> dict:
    payload = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _write(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return path


def _fake_policy_pilot_validator(pilot: dict, context: dict) -> list[dict]:
    policy = context["policy"]
    cell = "-".join((pilot["system"], pilot["resource"], pilot["codec"], pilot["topology_kind"]))
    rows = []
    for branch_index, branch in enumerate(policy.ANALYTICS_BRANCHES, start=1):
        for sample in range(int(policy.MIN_CALIBRATION_SAMPLES)):
            rows.append({
                "system": pilot["system"], "resource": pilot["resource"],
                "codec": pilot["codec"], "topology_kind": pilot["topology_kind"],
                "branch": branch,
                "decision_id": f"decision-{cell}-{branch}-{sample:03d}",
                "trace_id": f"trace-{cell}-{branch}-{sample:03d}",
                "service_ms": float(branch_index + sample / 100.0),
                "transfer_ms": 0.0 if pilot["resource"] == "cpu" else 0.5,
            })
    return rows


class TransactionV2Outputs:
    """Real authority-v2 fragments plus the transaction and closure they bind."""

    def __init__(self, directory: Path) -> None:
        self.authority = AuthorityFixture(directory)
        self.root = self.authority.project_root.resolve()
        result, self.dependencies = self.authority.materialize()
        self.fragments = {system: Path(result[system]) for system in SYSTEMS}
        for relative in RESOURCE_SOURCES:
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / relative, target)
        self.pilot_root = self.root / "artifacts/pilots"
        for system in SYSTEMS:
            for resource in RESOURCES:
                for codec in CODECS:
                    for topology in TOPOLOGIES:
                        arm = self.pilot_root / system / resource / codec / topology
                        for filename in PILOT_FILES:
                            _write(arm / filename, f"{filename}:{system}:{resource}:{codec}:{topology}\n".encode("ascii"))
        self.transaction = self._transaction_receipt()
        self.closure = self._closure_receipt(self.transaction)

    def _transaction_receipt(self) -> Path:
        qual = self.root / "artifacts/qualification"
        dummy = {
            name: _write(qual / name, f"{name}\n".encode("ascii"))
            for name in (
                "candidate/index.json", "candidate/manifest.json", "candidate/receipt.json",
                "bootstrap/mapping.json", "bootstrap/receipt.json",
                *(f"bootstrap/calibration.{system}.json" for system in SYSTEMS),
            )
        }
        receipt = {
            "schema_version": transaction_v2.SCHEMA_VERSION,
            "artifact_kind": transaction_v2.TRANSACTION_KIND,
            "status": "qualification_inputs_materialized_nonaccepted",
            "hardware_resource_collector": _descriptor(self.root, self.root / "scripts/collect_metrics.py"),
            "image_identity_patch": _descriptor(self.root, self.authority.patch_path),
            "accepted_model_parity_manifest": _descriptor(self.root, self.authority.accepted_manifest),
            "accepted_model_parity_assessment": _descriptor(self.root, self.authority.accepted_assessment),
            "accepted_model_parity_receipt": _descriptor(self.root, self.authority.accepted_receipt),
            "fragments": {system: _descriptor(self.root, self.fragments[system]) for system in SYSTEMS},
            "candidate": {
                field: _descriptor(self.root, dummy[f"candidate/{field}.json"])
                for field in ("index", "manifest", "receipt")
            },
            "bootstrap": {
                "mapping": _descriptor(self.root, dummy["bootstrap/mapping.json"]),
                "calibrations": {
                    system: _descriptor(self.root, dummy[f"bootstrap/calibration.{system}.json"])
                    for system in SYSTEMS
                },
                "receipt": _descriptor(self.root, dummy["bootstrap/receipt.json"]),
            },
        }
        receipt["receipt_sha256"] = transaction_v2._self_sha(receipt, "receipt_sha256")
        return _write(qual / transaction_v2.TRANSACTION_RECEIPT_FILENAME, _canonical(receipt))

    def _closure_receipt(self, transaction: Path, *, name: str = "closure") -> Path:
        receipt = json.loads(transaction.read_bytes())
        value = {
            "schema_version": 1,
            "artifact_kind": "vast_publication_policy_qualification_execution_closure_v1",
            "status": "qualification_execution_closed_nonpublication",
            "qualification_execution_complete": True,
            "accepted_for_full_publication": False,
            "publication_ready": False,
            "authorization_eligible": False,
            "qualification_input_transaction": {
                "receipt": _descriptor(self.root, transaction),
                "receipt_sha256": receipt["receipt_sha256"],
                "fragments": copy.deepcopy(receipt["fragments"]),
                "hardware_resource_collector": copy.deepcopy(receipt["hardware_resource_collector"]),
            },
            "pilot_execution": {
                "pilot_root": {
                    "path": self.pilot_root.relative_to(self.root).as_posix(),
                    "cell_count": 32,
                },
                "cells": [{} for _ in range(32)],
            },
        }
        return _write(
            self.root / f"artifacts/{name}/qualification_execution_closure.v1.receipt.json",
            _canonical(value),
        )

    @staticmethod
    def closure_loader(*, project_root: Path, receipt_path: Path,
                       require_complete_operational_accounting: bool) -> dict:
        # Delegation only; the physical closure is proven by its own tests and G8.
        if require_complete_operational_accounting is not True:
            raise AssertionError("qualification requires strict cold accounting")
        root = Path(project_root)
        return {
            "receipt_descriptor": _descriptor(root, Path(receipt_path)),
            "receipt": json.loads(Path(receipt_path).read_bytes()),
        }

    @contextlib.contextmanager
    def substitutions(self, *, policy_pilot_validator=_fake_policy_pilot_validator):
        loader = self.closure_loader
        with contextlib.ExitStack() as stack:
            stack.enter_context(mock.patch.object(promotion.fragments_v2, "DEFAULT_DEPENDENCIES", self.dependencies))
            stack.enter_context(mock.patch.object(policy_index, "_default_execution_closure_loader", loader))
            stack.enter_context(mock.patch.object(resource_index, "_default_execution_closure_loader", loader))
            stack.enter_context(mock.patch.object(policy_qualification, "_load_execution_closure", loader))
            stack.enter_context(mock.patch.object(resource_qualification, "_load_execution_closure", loader))
            stack.enter_context(mock.patch.object(policy_qualification, "_default_pilot_validator", policy_pilot_validator))
            # F1 passes its own policy pilot validator (Amendment 9); the fixture pilots are not real.
            stack.enter_context(mock.patch.object(promotion, "policy_pilot_validator", policy_pilot_validator))
            stack.enter_context(mock.patch.object(resource_qualification, "_default_pilot_validator", _fake_resource_pilot_validator))
            stack.enter_context(mock.patch.object(resource_qualification, "_load_and_verify_kpp_datasets", return_value=_datasets()))
            yield

    def fragment_args(self, fragments: dict[str, Path] | None = None) -> list[str]:
        chosen = fragments or self.fragments
        args: list[str] = []
        for system in SYSTEMS:
            args += [f"--{system.replace('_', '-')}-fragment", str(chosen[system])]
        return args

    def common(self, transaction: Path | None = None) -> list[str]:
        return [
            "--project-root", str(self.root),
            "--qualification-transaction-receipt", str(transaction or self.transaction),
        ]

    def policy_index_args(self, output: Path, *, closure: Path | None = None, **kwargs) -> list[str]:
        return ["policy-index", *self.common(kwargs.get("transaction")), "--pilot-root", str(self.pilot_root),
                "--output-dir", str(output), "--execution-closure-receipt", str(closure or self.closure),
                *self.fragment_args(kwargs.get("fragments"))]

    def resource_index_args(self, output: Path, *, closure: Path | None = None, **kwargs) -> list[str]:
        return ["resource-index", *self.common(kwargs.get("transaction")), "--pilot-root", str(self.pilot_root),
                "--output-path", str(output), "--execution-closure-receipt", str(closure or self.closure),
                *self.fragment_args(kwargs.get("fragments"))]

    def index_args(self, command: str, index: Path, *, output: Path | None = None, **kwargs) -> list[str]:
        args = [command, *self.common(kwargs.get("transaction")), "--index-path", str(index)]
        if output is not None:
            args += ["--output-dir", str(output)]
        return [*args, *self.fragment_args(kwargs.get("fragments"))]


def _run(argv: list[str]) -> tuple[int, str]:
    stdout = io.StringIO()
    with contextlib.redirect_stdout(stdout):
        rc = promotion.main(argv)
    return rc, stdout.getvalue()


class _Base(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="promotion-v2-", dir=ROOT / "artifacts")
        self.addCleanup(temporary.cleanup)
        self.outputs = TransactionV2Outputs(Path(temporary.name))
        self.root = self.outputs.root
        self.policy_dir = self.root / "artifacts/policy_index_a8"
        self.resource_path = self.root / "artifacts/resource_index_a8.json"
        self.policy_index = self.policy_dir / policy_index.INDEX_FILENAME

    def build_indices(self) -> None:
        with self.outputs.substitutions():
            self.assertEqual(_run(self.outputs.policy_index_args(self.policy_dir))[0], 0)
            self.assertEqual(_run(self.outputs.resource_index_args(self.resource_path))[0], 0)


class TransactionV2StepsFourteenFifteenTests(_Base):
    """(a) both indices, both assessments and both promotions on real fragments."""

    def test_real_transaction_v2_fragments_pass_indices_assessments_and_promotions(self) -> None:
        self.build_indices()
        policy = json.loads(self.policy_index.read_bytes())
        resource = json.loads(self.resource_path.read_bytes())
        self.assertEqual(len(policy["bindings"]), 32)
        self.assertEqual(len(resource["bindings"]), 8)
        self.assertEqual(len(policy["pilots"]), 32)
        self.assertEqual(len(resource["pilots"]), 32)
        for row in resource["bindings"]:
            interval = row["emitters"]["resource_intervals"]["artifact"]["path"]
            self.assertEqual(interval, row["emitters"]["fanout_work_counters"]["artifact"]["path"])
            self.assertEqual(
                row["emitters"]["hardware_resource_samples"]["artifact"]["path"],
                "scripts/collect_metrics.py",
            )
            expected = (
                f"scripts/checkpoint_{row['system']}_resource_runtime_v3.py"
                if row["system"] in {"deepstream", "savant"}
                else "deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp"
            )
            self.assertEqual(interval, expected)

        with self.outputs.substitutions():
            # The stock assessments with the real fragment-bound manifest derivation.
            policy_assessment = policy_qualification.assess_policy_qualification(
                project_root=self.root,
                index_path=self.policy_index,
                fragment_validator=promotion.fragments_v2.validate_publication_policy_qualification_fragment_from_authority_v2,
            )
            self.assertTrue(policy_assessment["passed"], policy_assessment["blockers"])
            resource_assessment = resource_qualification.assess_full_resource_qualification(
                project_root=self.root, index_path=self.resource_path,
            )
            self.assertTrue(resource_assessment["passed"], resource_assessment["blockers"])

            before = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
            for command, index in (("policy-assess", self.policy_index), ("resource-assess", self.resource_path)):
                rc, printed = _run(self.outputs.index_args(command, index))
                self.assertEqual(rc, 0, printed)
                self.assertIs(json.loads(printed)["passed"], True)
            after = sorted(path.relative_to(self.root).as_posix() for path in self.root.rglob("*"))
            self.assertEqual(before, after, "assessment must not write")

            policy_out = self.root / "artifacts/policy_promoted_a8"
            resource_out = self.root / "artifacts/resource_promoted_a8"
            self.assertEqual(_run(self.outputs.index_args("policy-promote", self.policy_index, output=policy_out))[0], 0)
            self.assertEqual(_run(self.outputs.index_args("resource-promote", self.resource_path, output=resource_out))[0], 0)
        self.assertEqual(
            sorted(path.name for path in policy_out.iterdir()),
            sorted(policy_qualification._PROMOTION_FILE_SEQUENCE),
        )
        self.assertEqual(
            sorted(path.name for path in resource_out.iterdir()),
            sorted(resource_qualification._PROMOTION_FILE_SEQUENCE),
        )

    def test_stock_legacy_paths_still_refuse_transaction_v2_fragments(self) -> None:
        """(b) the legacy default validators and their CLIs are unchanged and keep refusing."""
        with self.outputs.substitutions():
            with self.assertRaises(policy_index.PolicyQualificationIndexV2Error):
                policy_index.build_policy_qualification_index_v2(
                    project_root=self.root, fragment_paths=self.outputs.fragments,
                    pilot_root=self.outputs.pilot_root, output_dir=self.root / "artifacts/legacy_policy",
                    execution_closure_receipt_path=self.outputs.closure,
                )
            with self.assertRaises(resource_index.FullResourceQualificationIndexV1Error):
                resource_index.build_full_resource_qualification_index_v1(
                    project_root=self.root, fragment_paths=self.outputs.fragments,
                    pilot_root=self.outputs.pilot_root, output_path=self.root / "artifacts/legacy_resource.json",
                    execution_closure_receipt_path=self.outputs.closure,
                )
        self.assertFalse((self.root / "artifacts/legacy_policy").exists())
        self.assertFalse((self.root / "artifacts/legacy_resource.json").exists())

        self.build_indices()
        with self.outputs.substitutions():
            legacy = policy_qualification.assess_policy_qualification(
                project_root=self.root, index_path=self.policy_index,
            )
        self.assertFalse(legacy["passed"])


class TransactionPreconditionTests(_Base):
    """(f) every precondition item is enforced before a stock function runs."""

    def _refused(self, argv: list[str], *must_not_exist: Path) -> None:
        with self.outputs.substitutions():
            with self.assertRaises(promotion.PromotionV2Error):
                _run(argv)
        for path in must_not_exist:
            self.assertFalse(path.exists(), path)

    def _rewrite_transaction(self, mutate, *, resign: bool = True) -> Path:
        value = json.loads(self.outputs.transaction.read_bytes())
        mutate(value)
        if resign:
            value["receipt_sha256"] = transaction_v2._self_sha(value, "receipt_sha256")
        return _write(self.root / "artifacts/forged/qualification_input_transaction.v2.receipt.json", _canonical(value))

    def test_transaction_kind_self_hash_and_cold_validation_are_required(self) -> None:
        wrong_kind = self._rewrite_transaction(lambda value: value.update(artifact_kind="vast_other_transaction_v2"))
        self._refused(self.outputs.policy_index_args(self.policy_dir, transaction=wrong_kind), self.policy_dir)
        wrong_hash = self._rewrite_transaction(lambda value: value.update(status="forged"), resign=False)
        self._refused(self.outputs.resource_index_args(self.resource_path, transaction=wrong_hash), self.resource_path)

        candidate = self.root / json.loads(self.outputs.transaction.read_bytes())["candidate"]["receipt"]["path"]
        original = candidate.read_bytes()
        candidate.write_bytes(original + b"drift\n")
        try:
            self._refused(self.outputs.policy_index_args(self.policy_dir), self.policy_dir)
        finally:
            candidate.write_bytes(original)

    def test_fragments_must_equal_the_transaction_fragments(self) -> None:
        copied = dict(self.outputs.fragments)
        foreign = self.root / "artifacts/foreign/deepstream/qualification_fragment.json"
        _write(foreign, self.outputs.fragments["deepstream"].read_bytes())
        copied["deepstream"] = foreign
        self._refused(self.outputs.policy_index_args(self.policy_dir, fragments=copied), self.policy_dir)
        self._refused(self.outputs.resource_index_args(self.resource_path, fragments=copied), self.resource_path)

    def test_execution_closure_must_bind_this_transaction(self) -> None:
        other = self._rewrite_transaction(lambda value: value.update(status="qualification_inputs_materialized_nonaccepted_b"))
        foreign_closure = self.outputs._closure_receipt(other, name="foreign_closure")
        self._refused(self.outputs.policy_index_args(self.policy_dir, closure=foreign_closure), self.policy_dir)
        self._refused(self.outputs.resource_index_args(self.resource_path, closure=foreign_closure), self.resource_path)

    def test_resource_index_binds_the_hardware_collector_to_the_transaction(self) -> None:
        closure = json.loads(self.outputs.closure.read_bytes())
        closure["qualification_input_transaction"]["hardware_resource_collector"]["sha256"] = "0" * 64
        forged = _write(
            self.root / "artifacts/collector_closure/qualification_execution_closure.v1.receipt.json",
            _canonical(closure),
        )
        with self.outputs.substitutions():
            with self.assertRaisesRegex(
                resource_index.FullResourceQualificationIndexV1Error, "hardware resource collector"
            ):
                _run(self.outputs.resource_index_args(self.resource_path, closure=forged))
        self.assertFalse(self.resource_path.exists())

    def test_index_commands_require_pilots_and_closure(self) -> None:
        argv = self.outputs.policy_index_args(self.policy_dir)
        for flag in ("--pilot-root", "--execution-closure-receipt"):
            position = argv.index(flag)
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                promotion.main(argv[:position] + argv[position + 2:])
        self.assertFalse(self.policy_dir.exists())

    def test_promotion_and_assessment_require_index_bound_to_these_fragments(self) -> None:
        self.build_indices()
        promoted = self.root / "artifacts/promoted"
        policy = json.loads(self.policy_index.read_bytes())
        foreign = self.root / "artifacts/foreign/deepstream/qualification_fragment.json"
        _write(foreign, self.outputs.fragments["deepstream"].read_bytes())
        for row in policy["bindings"]:
            if row["system"] == "deepstream":
                row["fragment_artifact"] = _descriptor(self.root, foreign)
        forged_policy = _write(self.root / "artifacts/forged/policy_index.json", _canonical(policy))
        self._refused(self.outputs.index_args("policy-assess", forged_policy))
        self._refused(self.outputs.index_args("policy-promote", forged_policy, output=promoted), promoted)

        resource = json.loads(self.resource_path.read_bytes())
        resource["bindings"][0]["implementation_artifact"] = _descriptor(self.root, foreign)
        forged_resource = _write(self.root / "artifacts/forged/resource_index.json", _canonical(resource))
        self._refused(self.outputs.index_args("resource-assess", forged_resource))
        self._refused(self.outputs.index_args("resource-promote", forged_resource, output=promoted), promoted)

        other = self._rewrite_transaction(lambda value: value.update(status="qualification_inputs_materialized_nonaccepted_b"))
        foreign_closure = self.outputs._closure_receipt(other, name="foreign_closure")
        for index_path, name in ((self.policy_index, "policy"), (self.resource_path, "resource")):
            index = json.loads(index_path.read_bytes())
            index["qualification_execution_closure"] = _descriptor(self.root, foreign_closure)
            forged = _write(self.root / f"artifacts/forged/{name}_closure_index.json", _canonical(index))
            self._refused(self.outputs.index_args(f"{name}-assess", forged))
            self._refused(self.outputs.index_args(f"{name}-promote", forged, output=promoted), promoted)

    def test_assess_returns_78_when_not_passed(self) -> None:
        self.build_indices()

        def too_few(pilot: dict, context: dict) -> list[dict]:
            return _fake_policy_pilot_validator(pilot, context)[1:]

        with self.outputs.substitutions(policy_pilot_validator=too_few):
            rc, printed = _run(self.outputs.index_args("policy-assess", self.policy_index))
        self.assertEqual(rc, promotion.ASSESSMENT_BLOCKED_EXIT)
        self.assertEqual(rc, 78)
        self.assertIs(json.loads(printed)["passed"], False)

        with self.outputs.substitutions(), mock.patch.object(
            resource_qualification, "_default_pilot_validator", side_effect=RuntimeError("blocked pilot"),
        ):
            rc, printed = _run(self.outputs.index_args("resource-assess", self.resource_path))
        self.assertEqual(rc, 78)
        self.assertIs(json.loads(printed)["passed"], False)


if __name__ == "__main__":
    unittest.main()
