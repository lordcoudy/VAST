"""Real F5 refusal predicates with one explicit upstream acceptance boundary.

Portable tests substitute ONLY the pilot acceptance reader, whose bootstrap,
parity and live-service predecessors are unavailable in a portable fixture.
Native coordinator, descriptors, policy replay, sidecars and six-stream reset
validators are real. Valid sidecars reach the absent frozen-dataset gate;
these tests never claim complete qualification or campaign acceptance.

The separately callable genuine-fixture helpers use no substitution at all.
"""
from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

import publication_policy_contract as policy
import publication_policy_qualification as stock
import publication_policy_qualification_pilot_validation_v2 as f5
from benchmark_contract import ContractError
from publication_acceptance_evidence import accepted_arm_evidence_files
from tests.fixtures.accepted_policy_native_fixture_v1 import write_native_policy_fixture_cell_v1
from tests.test_accepted_policy_production_validation import validate_native_cell, verified_fixture_manifest


ROLE_FILES = {
    "checkpoint_acceptance": "checkpoint_qualification_pilot_acceptance.json",
    "policy_decisions_jsonl": "publication_policy_decisions.jsonl",
    "resource_intervals": "resource_intervals.csv",
    "ingress_ledger": "ingress_ledger.csv",
    "topology_events": "topology_events.csv",
    "frames": "frames.csv",
    "frame_events": "frame_events.csv",
    "branch_terminals": "branch_terminals.csv",
}


def _descriptor(root: Path, path: Path) -> dict:
    raw = path.read_bytes()
    return {"path": path.relative_to(root).as_posix(), "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest()}


class _PortableArm:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.output = root / "pilots/gstreamer_custom/gpu/h264/shared_video_dag"
        self.capability = verified_fixture_manifest()
        self.metadata = write_native_policy_fixture_cell_v1(
            output_dir=self.output, capability=self.capability, system="gstreamer_custom",
            resource="gpu", codec="h264", topology_kind="shared_video_dag",
            dropped_ingress=True,
        )
        self.frames, self.sidecars = validate_native_cell(self.output, self.metadata, "shared_video_dag")
        manifest = root / "configs/datasets.yaml"
        manifest.parent.mkdir(parents=True)
        manifest.write_text("schema_version: 1\ndatasets: {}\n", encoding="ascii")
        self.context = {"project_root": root, "policy": policy, "capability_manifest": self.capability,
                        "bindings": {}, "dataset_manifest": _descriptor(root, manifest)}
        self.acceptance_path = self.output / ROLE_FILES["checkpoint_acceptance"]
        self.acceptance = {
            "artifact_kind": "vast_test_f5_acceptance_boundary_v1",
            "fixture_only": True, "publication_eligible": False,
            "run_id": self.metadata["run_id"], "scenario": self.metadata["scenario"],
            "full_resource_summary": dict(self.sidecars["resource_intervals"].attrs["full_resource_summary"]),
            "full_resource_finalization": {
                "hardware_collector_stopped": True,
                "validation": "full_resource_evidence_v2_passed",
                "prepared_by": "prepare_checkpoint_publication_acceptance",
            },
        }
        self.pilot = {"system": "gstreamer_custom", "resource": "gpu", "codec": "h264",
                      "topology_kind": "shared_video_dag"}
        self.rebind_current_bytes()

    def rebind_current_bytes(self) -> None:
        self.acceptance["evidence_sha256"] = {
            name: hashlib.sha256((self.output / name).read_bytes()).hexdigest()
            for name in accepted_arm_evidence_files("gpu_only", full_resource=True)
        }
        self.acceptance_path.write_text(
            json.dumps(self.acceptance, sort_keys=True, separators=(",", ":")) + "\n", encoding="ascii")
        self.pilot["evidence"] = {
            role: _descriptor(self.root, self.output / filename) for role, filename in ROLE_FILES.items()
        }

    def run_f5(self) -> list[dict]:
        # Exactly one substituted boundary; every downstream file/validator is real.
        with mock.patch.object(f5, "validate_checkpoint_qualification_pilot_acceptance_v1",
                               return_value=json.loads(self.acceptance_path.read_bytes())):
            return f5.policy_pilot_validator(self.pilot, self.context)


class AcceptedPolicyF5RealRefusalTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="accepted-policy-f5-real-")
        self.addCleanup(self.temporary.cleanup)
        self.arm = _PortableArm(Path(self.temporary.name).resolve())

    def test_valid_native_sidecars_and_six_stream_reset_reach_only_the_dataset_gate(self) -> None:
        self.assertEqual(len(self.arm.frames), 30)
        self.assertEqual(set(self.arm.sidecars["ingress_ledger"]["stream_id"]), set(range(6)))
        self.assertTrue(self.arm.sidecars["reset_evidence"]["reset_claim_eligible"].all())
        self.assertEqual(len(self.arm.sidecars["policy_decisions"]), 123)
        with self.assertRaisesRegex(stock.QualificationError,
                                    "pilot sidecar revalidation failed: unknown dataset 'kpp_iss_publication_v3_h264'"):
            self.arm.run_f5()

    def test_changed_on_disk_native_evidence_refuses_before_sample_exclusion(self) -> None:
        source = self.arm.output / "resource_intervals.csv"
        raw = source.read_bytes()
        self.assertIn(b"4096", raw)
        source.write_bytes(raw.replace(b"4096", b"4097", 1))
        with self.assertRaisesRegex(stock.QualificationError, "pilot resource_intervals artifact size/SHA drift"):
            self.arm.run_f5()

    def test_duplicate_csv_decision_id_refuses_with_real_causal_validator(self) -> None:
        source = self.arm.output / "policy_decisions.csv"
        rows = pd.read_csv(source)
        rows.loc[1, "decision_id"] = rows.loc[0, "decision_id"]
        rows.to_csv(source, index=False)
        self.arm.rebind_current_bytes()
        with self.assertRaisesRegex(stock.QualificationError, "pilot sidecar revalidation failed: .*duplicate decision_id"):
            self.arm.run_f5()

    def test_duplicate_jsonl_decision_id_refuses_with_real_canonical_linkage_validator(self) -> None:
        source = self.arm.output / "publication_policy_decisions.jsonl"
        raw = source.read_bytes()
        source.write_bytes(raw + raw.splitlines(keepends=True)[0])
        self.arm.rebind_current_bytes()
        with self.assertRaisesRegex(stock.QualificationError,
                                    "pilot sidecar revalidation failed: .*canonical/CSV native decision linkage drifted"):
            self.arm.run_f5()

    def test_dropped_decision_cannot_bypass_missing_ingress_association(self) -> None:
        source = self.arm.output / "ingress_ledger.csv"
        rows = pd.read_csv(source)
        self.assertEqual((rows["terminal_status"] == "drop").sum(), 1)
        rows.loc[rows["terminal_status"] != "drop"].to_csv(source, index=False)
        self.arm.rebind_current_bytes()
        with self.assertRaisesRegex(stock.QualificationError,
                                    "pilot sidecar revalidation failed: .*native drop counter does not match ingress ledger"):
            self.arm.run_f5()

    def test_missing_reset_evidence_refuses_as_physical_evidence_and_real_sidecar_input(self) -> None:
        (self.arm.output / "reset_evidence.csv").unlink()
        with self.assertRaisesRegex(stock.QualificationError, "checkpoint acceptance evidence is missing: reset_evidence.csv"):
            self.arm.run_f5()
        with self.assertRaisesRegex((ContractError, FileNotFoundError), "reset_evidence.csv"):
            validate_native_cell(self.arm.output, self.arm.metadata, "shared_video_dag")

    def test_malformed_reset_evidence_refuses_with_real_reset_validator(self) -> None:
        source = self.arm.output / "reset_evidence.csv"
        rows = pd.read_csv(source).drop(columns=["reset_provenance"])
        rows.to_csv(source, index=False)
        self.arm.rebind_current_bytes()
        with self.assertRaisesRegex(stock.QualificationError, "pilot sidecar revalidation failed: .*reset_evidence.csv.*missing or empty value for reset_provenance"):
            self.arm.run_f5()

    def test_incomplete_six_stream_reset_process_coverage_refuses(self) -> None:
        source = self.arm.output / "reset_evidence.csv"
        rows = pd.read_csv(source)
        rows = rows.loc[rows["stream_id"] != 5]
        rows.to_csv(source, index=False)
        self.arm.rebind_current_bytes()
        with self.assertRaisesRegex(stock.QualificationError, "pilot sidecar revalidation failed: .*reset process coverage differs; missing="):
            self.arm.run_f5()


def genuine_f5_context_v1(project_root: Path, index_path: Path) -> tuple[dict, list[dict]]:
    """Derive actual F1 context; call only with a genuine purpose-built fixture."""
    from publication_qualification_promotion_v2 import _fragment_validator

    root = project_root.resolve(strict=True)
    index_path.resolve(strict=True).relative_to(root)
    index = json.loads(index_path.read_bytes())
    actual_policy = stock._load_policy_contract()
    dataset = stock._verify_descriptor(root, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True)
    capability, bindings = stock._derive_fragment_bound_manifest(
        index["bindings"], project_root=root, policy=actual_policy, fragment_validator=_fragment_validator)
    return {"project_root": root, "policy": actual_policy, "capability_manifest": capability,
            "bindings": bindings, "dataset_manifest": dataset}, index["pilots"]


def assert_genuine_f5_stock_samples_v1(pilot: dict, context: dict) -> dict:
    """Compare real validators on a CPU or positive-transfer-only GPU fixture arm.

    A dropped GPU arm with no transfer is deliberately not a stock-equivalence
    input: stock must refuse it, whereas reviewed F5 excludes its dropped samples.
    """
    actual = f5.policy_pilot_validator(pilot, context)
    reviewed_stock = stock._default_pilot_validator(pilot, context)
    if actual != reviewed_stock:
        raise AssertionError("actual F5 CPU/positive-transfer samples differ from stock")
    return {"resource": pilot["resource"], "sample_count": len(actual), "samples_equal_stock": True,
            "upstream_acceptance_substituted": False, "dataset_substituted": False}


if __name__ == "__main__":
    unittest.main()
