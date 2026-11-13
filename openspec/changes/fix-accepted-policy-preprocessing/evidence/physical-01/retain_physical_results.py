#!/usr/bin/env python3
"""Retain byte-exact fresh build/refreeze/parity logs and independent audit evidence."""
import hashlib
import json
from pathlib import Path
import stat

HERE = Path(__file__).resolve().parent
ROOT = Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a"
COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    output = HERE / "physical-results"
    groups = ("runtime-build-control", "image-capture-control", "model-parity-control")
    report = []
    for group in groups:
        directory = BASE / group
        if group != "image-capture-control":
            require((directory / "rc.txt").read_text().strip() == "0", "physical producer failed")
        else:
            require((directory / "finished.txt").is_file(), "capture did not finish")
            for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
                receipt = json.loads((BASE / "runtime_images" / (system + ".runtime.freeze.json")).read_bytes())
                require(receipt["candidate_binding_eligible"] is True and receipt["blockers"] == [],
                        "capture eligibility differs")
        require((directory / "expected-commit.txt").read_text().strip() == COMMIT,
                "physical producer commit differs")
    output.mkdir(mode=0o700, exist_ok=True)
    require(output.resolve(strict=True) == output and not list(output.iterdir()),
            "retention output must be fresh or empty")
    paths = [path for group in groups for path in sorted((BASE / group).iterdir()) if path.is_file()]
    paths.append(BASE / "independent_parity_audit_v1/audit.v1.json")
    for old in paths:
        info = old.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and old.resolve(strict=True) == old, "nonphysical result")
        payload = old.read_bytes()
        new = output / old.relative_to(BASE)
        new.parent.mkdir(parents=True, exist_ok=True)
        with new.open("xb") as stream:
            stream.write(payload)
        require(old.read_bytes() == new.read_bytes() == payload and old.lstat() == info,
                "result copy drifted")
        report.append({"source": old.relative_to(ROOT).as_posix(),
                       "retained": new.relative_to(HERE).as_posix(),
                       "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)})
    result = {"status": "retained_exactly", "build_commit": COMMIT, "files": report,
              "producer_sessions": {"runtime_build": 14682, "refreeze_capture": 96527,
                                    "model_parity": 53546, "independent_parity_audit": 57479},
              "limitations": ["These observations bind the frozen runtime build commit, not final host pins or CI.",
                              "No Q1 campaign or semantic guardian fixture acceptance is implied."]}
    payload = (json.dumps(result, sort_keys=True, indent=1) + "\n").encode()
    with (HERE / "physical-results.v1.json").open("xb") as stream:
        stream.write(payload)
    print(json.dumps({"status": result["status"], "files": len(report)}, sort_keys=True))


if __name__ == "__main__":
    main()
