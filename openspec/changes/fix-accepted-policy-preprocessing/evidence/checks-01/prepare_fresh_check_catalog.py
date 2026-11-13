"""Render an additive catalog from the exact passed fresh parity audit, no copy."""

import json
from pathlib import Path
import re
import subprocess
import sys

from copy_check_inputs import plain, reviewed, safe_relative


BASE = "artifacts/accepted_policy_repair_20261011a"
BUILD_COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"
AUDIT_SHA = "75922812dde1281dc57f7969d5cd5bd3d32fa6cd10e34a6638b8e54ce51fb95b"
OBSERVATIONS = {
    "image-inspect-map.json": "890fecbd90e5f9c7af3ceecd0500e06e2d9fde8dc1ec38324f9d66de2335ecdb",
    "device-probe-map.json": "5253f71f50662019e3543ac8338d2ef7ac09c9a26a25132f4af45564bdaf4921",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def descriptor(value):
    row = {key: value[key] for key in ("path", "size_bytes", "sha256")}
    safe_relative(row["path"])
    require(type(row["size_bytes"]) is int and row["size_bytes"] > 0, "catalog descriptor size invalid")
    require(len(row["sha256"]) == 64 and all(char in "0123456789abcdef" for char in row["sha256"]),
            "catalog descriptor hash invalid")
    return row


def main():
    require(len(sys.argv) == 5, "PHYSICAL_ROOT HOST_ROOT EXACT_SOURCE_COMMIT AUDIT_SHA required")
    physical, host, source_commit, audit_sha = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4]
    require(re.fullmatch(r"[0-9a-f]{40}", source_commit) is not None, "exact current source commit required")
    require(physical == Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
            and physical.resolve(strict=True) == physical and host.resolve(strict=True) == host,
            "fresh catalog roots drifted or aliased")
    require(subprocess.check_output(["git", "-C", str(physical), "rev-parse", "HEAD"], text=True).strip()
            == source_commit, "physical source commit drifted")
    require(not subprocess.check_output(["git", "-C", str(physical), "status", "--porcelain",
            "--untracked-files=no"], text=True).strip(), "physical tracked sources are dirty")
    require(audit_sha == AUDIT_SHA, "exact independently reviewed audit required")
    audit_path = physical / BASE / "independent_parity_audit_v1/audit.v1.json"
    reviewed(audit_path, audit_sha)
    audit = json.loads(audit_path.read_bytes())
    require(audit["status"] == "verified" and audit["build_commit"] == BUILD_COMMIT
            and audit["physical_execution_count"] == 480 and audit["individual_tensor_files_bound"] == 960
            and audit["execution_members_rehashed"] == 1920 and audit["unique_files"] == 2478,
            "independent full physical parity audit coverage drifted")
    observed = {}
    for value in audit["verified_physical_descriptors"]:
        row = descriptor(value)
        require(row["path"] not in observed, "audit physical descriptor duplicated")
        observed[row["path"]] = row
    require(len(observed) == 2478, "audit unique descriptor count drifted")
    copies = {path: row for path, row in observed.items() if path.startswith(BASE + "/")}
    tracked = {path: row for path, row in observed.items() if path.startswith("configs/")}
    assets = {path: row for path, row in observed.items() if path.startswith("data/videos/kpp/kpp_iss_publication_v3/")}
    require(len(copies) == 2466 and len(tracked) == 7 and len(assets) == 5
            and len(copies) + len(tracked) + len(assets) == len(observed), "audit path classification drifted")
    binding = descriptor(audit["acceptance_binding"])
    require(binding["path"] == BASE + "/model_parity_v4/acceptance_binding.v4.json", "fresh binding path drifted")
    copies[binding["path"]] = binding
    patch_row = copies[BASE + "/qualification_image_identity_patch.json"]
    reviewed(physical / patch_row["path"], patch_row["sha256"])
    patch = json.loads((physical / patch_row["path"]).read_bytes())
    receipts = [patch["receipts"]["native_probe"], patch["receipts"]["analytics_worker"],
        *patch["receipts"]["runtime_images"].values()]
    require(len(receipts) == 6 and set(patch["receipts"]["runtime_images"])
            == {"deepstream", "savant", "openvino_gva", "gstreamer_custom"}, "fresh receipt coverage drifted")
    for value in receipts:
        row = descriptor(value)
        require(row["path"].startswith(BASE + "/"), "fresh receipt outside repair namespace")
        prior = copies.setdefault(row["path"], row)
        require(prior == row, "fresh receipt conflicts with audited descriptor")
        require(plain(physical / row["path"]).st_size == row["size_bytes"], "fresh receipt size drifted")
        reviewed(physical / row["path"], row["sha256"])
    selected = dict(copies[BASE + "/runtime_images/gstreamer_custom.runtime.freeze.json"],
        path=BASE + "/selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json")
    tracked[selected["path"]] = selected
    for path, row in tracked.items():
        require(plain(host / path).st_size == row["size_bytes"], "fresh committed-copy size drifted")
        reviewed(host / path, row["sha256"])
    require(len(copies) == 2473 and len(tracked) == 8, "exact additive fresh catalog count drifted")
    # Bulk tensor bytes were already independently rehashed; the copier must rehash again before admission.
    for path, row in copies.items():
        require(plain(physical / path).st_size == row["size_bytes"], "audited source no longer plain/exact-size")
    fixture_observations = []
    for name, sha in sorted(OBSERVATIONS.items()):
        path = BASE + "/consumer-runtime-observations-02/" + name
        info = plain(physical / path)
        reviewed(physical / path, sha)
        fixture_observations.append(descriptor({"path": path, "size_bytes": info.st_size, "sha256": sha}))
    result = {"schema_version": 1, "artifact_kind": "vast_fresh_check_input_catalog_v1",
        "physical_build_commit": BUILD_COMMIT,
        "source_commit_at_catalog_preparation": source_commit,
        "audit": {"path": str(audit_path.relative_to(physical)), "size_bytes": audit_path.stat().st_size, "sha256": audit_sha},
        "copy_files": [copies[path] for path in sorted(copies)],
        "tracked_cross_checks": [tracked[path] for path in sorted(tracked)],
        "asset_cross_checks": [assets[path] for path in sorted(assets)],
        "fixture_observation_files": fixture_observations,
        "fixture_observations_parity_audited": False,
        "copy_file_count": len(copies), "copy_total_bytes": sum(row["size_bytes"] for row in copies.values()),
        "historical_catalog_modified": False, "policy_pilot_attempts_included": False,
        "copy_confers_qualification_authority": False}
    print(json.dumps(result, sort_keys=True, indent=1))


if __name__ == "__main__":
    require(sys.flags.optimize == 0, "unoptimized Python required")
    main()
