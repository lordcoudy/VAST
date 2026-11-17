#!/usr/bin/env python3
"""Copy six immutable fresh pin inputs exactly, never overwrite historical receipts."""
import hashlib
import json
from pathlib import Path
import stat
import sys

ROOT = Path(__file__).resolve().parents[5]
BUILD = Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
BASE = "artifacts/accepted_policy_repair_20261011a"
CONFIGS = (
    "analytics_execution_layer.refreshed.v4.accepted-policy-repair-20261011a.json",
    "checkpoint_analytics_model_parity.refreshed.v4.accepted-policy-repair-20261011a.yaml",
    "checkpoint_analytics_model_parity.refreshed.v4.accepted-policy-repair-20261011a.accepted.yaml",
    "checkpoint_analytics_model_parity.refreshed.v4.accepted-policy-repair-20261011a.accepted.assessment.json",
    "checkpoint_analytics_model_parity.refreshed.v4.accepted-policy-repair-20261011a.accepted.acceptance_receipt.json",
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    require(ROOT.resolve(strict=True) == ROOT and BUILD.resolve(strict=True) == BUILD,
            "copy root alias")
    audit = json.loads((BUILD / BASE / "independent_parity_audit_v1/audit.v1.json").read_bytes())
    require(audit["status"] == "verified" and audit["physical_execution_count"] == 480
            and audit["individual_tensor_files_bound"] == 960, "independent parity audit missing")
    pairs = [("configs/" + name, "configs/" + name) for name in CONFIGS]
    pairs.append((BASE + "/runtime_images/gstreamer_custom.runtime.freeze.json",
                  BASE + "/selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json"))
    report = []
    for source, target in pairs:
        old, new = BUILD / source, ROOT / target
        before = old.lstat()
        require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1
                and old.resolve(strict=True) == old, "source not a single physical file")
        require(not new.exists() and not new.is_symlink(), "copy target already exists")
        payload = old.read_bytes()
        new.parent.mkdir(parents=True, exist_ok=True)
        require(new.parent.resolve(strict=True) == new.parent, "copy parent alias")
        with new.open("xb") as stream:
            stream.write(payload)
        require(new.read_bytes() == payload and old.read_bytes() == payload
                and old.lstat() == before, "copy/source drift")
        report.append({"source": source, "target": target,
                       "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)})
    print(json.dumps({"status": "copied_exactly", "files": report}, sort_keys=True, indent=1))


if __name__ == "__main__":
    require(sys.flags.optimize == 0, "unoptimized Python required")
    main()
