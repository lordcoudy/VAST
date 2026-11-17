#!/usr/bin/env python3
"""Independently cold-read fresh parity and rehash every physical tensor member."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
ROOT = Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a"
PARITY = BASE / "model_parity_v4"
RECEIPT = ROOT / "configs/checkpoint_analytics_model_parity.refreshed.v4.accepted-policy-repair-20261011a.accepted.acceptance_receipt.json"
COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"
REFERENCE_SHA = "2ea6487d5c6dceae1c166ff9150b4fcbeee221b9003bd1896fbd2f42bc0c5e9d"


def main():
    library = REPO / "openspec/changes/qualify-full-benchmark/evidence/physical-v6-rebuild-20261008e/independent_audits/audit_model_parity_v1.py"
    spec = importlib.util.spec_from_file_location("reviewed_physical_parity_auditor", library)
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    audit.ROOT = ROOT
    audit.relative.__defaults__ = (ROOT,)
    require = audit.require
    require(os.getuid() == 1000 and sys.flags.optimize == 0, "audit requires unoptimized WSL UID1000")
    require(subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                    text=True).strip() == COMMIT, "parity root commit drifted")
    require((BASE / "model-parity-control/rc.txt").read_text().strip() == "0", "producer did not pass")
    output = BASE / "independent_parity_audit_v1"
    output.mkdir(mode=0o700, exist_ok=False)
    sys.path.insert(0, str(ROOT / "scripts"))
    from checkpoint_model_parity_acceptance_v4 import load_verified_model_parity_acceptance_v4

    binding = load_verified_model_parity_acceptance_v4(project_root=ROOT, receipt_path=RECEIPT)
    receipt = audit.read_json(RECEIPT, "receipt_sha256")
    binding_path = PARITY / "acceptance_binding.v4.json"
    index_path = PARITY / "materialization/transaction_index.json"
    disk_binding = audit.read_json(binding_path, "binding_sha256")
    index = audit.read_json(index_path, "transaction_sha256")
    require(binding == disk_binding, "fresh binding differs from stock cold reader")
    require(receipt["status"] == "accepted_physical_model_parity_v4"
            and receipt["blockers"] == [] and receipt["publication_ready"] is True
            and receipt["evidence_count"] == 32, "fresh parity acceptance state differs")
    require(index["execution_bundle_count"] == len(index["execution_bundles"]) == 480
            and index["synthetic_or_mock_evidence_accepted"] is False
            and index["claimed_aggregates_accepted"] is False, "physical count/authority differs")
    for document in (receipt, disk_binding, index):
        audit.visit(document)
    groups = Counter((row["branch"], row["resource"], row["role"], row["codec"])
                     for row in index["execution_bundles"])
    require(len(groups) == 32 and set(groups.values()) == {15}, "parity group coverage differs")
    require(sum(audit.cache[path]["descriptor"]["size_bytes"] for path in audit.descriptor_paths)
            <= 64 * 1024**3, "physical aggregate exceeds bound")
    members = tensors = 0
    for row in index["execution_bundles"]:
        manifest_path = audit.relative(row["manifest"]["path"])
        manifest = audit.read_json(manifest_path)
        unsigned = {key: value for key, value in manifest.items() if key != "identity"}
        require(manifest["identity"] == {"algorithm": "sha256", "sha256": hashlib.sha256(
            audit.canonical(unsigned)).hexdigest()} and manifest["identity"]["sha256"]
            == row["manifest_identity_sha256"] and manifest["request_id"] == row["request_id"],
            "physical execution manifest identity differs")
        require(set(manifest["files"]) == {"input_tensor", "output_tensor", "request", "response"},
                "physical member namespace differs")
        for kind, entry in manifest["files"].items():
            path = audit.relative(entry["path"], manifest_path.parent)
            observed = audit.describe(path)
            require(path in audit.descriptor_paths, "execution member not inventoried")
            require((observed["sha256"], observed["size_bytes"]) == (entry["sha256"], entry["bytes"])
                    and observed["sha256"] == row[kind + "_sha256"], "physical member hash differs")
            members += 1
            tensors += int(kind in {"input_tensor", "output_tensor"})
    require(members == 1920 and tensors == 960, "physical member counts differ")
    reference = audit.describe(audit.A244)
    require(reference["sha256"] == REFERENCE_SHA and reference["size_bytes"] == 1430946,
            "canonical reference bytes drifted")
    current = audit.tensor_pairs(index)
    original = audit.tensor_pairs(audit.read_json(audit.A244))
    require(len(current) == len(original) == 480 and current == original,
            "fresh physical tensor pairs differ from canonical reference")
    for path, entry in audit.cache.items():
        require(audit.signature(audit.physical(path)) == entry["signature"], "physical file changed")
    report = {
        "schema_version": 1, "artifact_kind": "vast_accepted_policy_repair_physical_parity_audit_v1",
        "status": "verified", "completed_at_utc": datetime.now(timezone.utc).isoformat(),
        "build_commit": COMMIT, "stock_cold_reader_calls": 1, "physical_execution_count": 480,
        "groups": 32, "samples_per_group": 15, "execution_members_rehashed": members,
        "individual_tensor_files_bound": tensors, "all_tensor_pairs_match_canonical_reference": True,
        "canonical_reference": reference, "acceptance_receipt": audit.describe(RECEIPT),
        "acceptance_binding": audit.describe(binding_path), "transaction_index": audit.describe(index_path),
        "descriptor_count": audit.descriptor_count, "unique_files": len(audit.descriptor_paths),
        "verified_physical_descriptors": sorted((audit.cache[path]["descriptor"]
            for path in audit.descriptor_paths), key=lambda row: row["path"]),
        "auditor_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "reviewed_helper_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "limitations": ["Read-only physical parity audit, not Q1 or full publication acceptance.",
                        "Canonical comparison uses reference tensor hashes, not historical acceptance authority."]
    }
    report["payload_sha256"] = hashlib.sha256(audit.canonical(report)).hexdigest()
    observed = audit.exclusive(output / "audit.v1.json", report)
    print(json.dumps({"status": "verified", "report": observed, "physical_execution_count": 480,
                      "groups": 32, "individual_tensor_files_bound": tensors}, sort_keys=True))


if __name__ == "__main__":
    main()
