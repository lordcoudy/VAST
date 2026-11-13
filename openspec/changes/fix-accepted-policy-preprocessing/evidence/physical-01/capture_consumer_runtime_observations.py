#!/usr/bin/env python3
"""Capture actual image/device observations for explicitly artificial consumer tests."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path("/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a")
BASE = ROOT / "artifacts/accepted_policy_repair_20261011a"
COMMIT = "aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def save(directory, name, payload):
    path = directory / name
    with path.open("xb") as stream:
        stream.write(payload)
    return {"path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload)}


def encoded(value):
    return (json.dumps(value, sort_keys=True, indent=1) + "\n").encode()


def main():
    require(ROOT.resolve(strict=True) == ROOT and sys.flags.optimize == 0, "root/interpreter drift")
    require(subprocess.check_output(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                   text=True).strip() == COMMIT, "build commit drift")
    require(not subprocess.check_output(["docker", "ps", "-q"]).strip(), "competing containers")
    patch_path = BASE / "qualification_image_identity_patch.json"
    patch_bytes = patch_path.read_bytes()
    patch = json.loads(patch_bytes)
    images = {name: row["physical_identity"]["image_id"] for name, row in patch["systems"].items()}
    images.update({"worker_" + name: row["image_id"] for name, row in patch["workers"].items()})
    output = BASE / "consumer-runtime-observations-02"
    output.mkdir(mode=0o700, exist_ok=False)
    sys.path.insert(0, str(ROOT / "scripts"))
    from publication_policy_qualification_runtime_inputs_v2 import DEFAULT_DEPENDENCIES
    observations, descriptors = {}, {}
    for name, image_id in sorted(images.items()):
        raw = subprocess.check_output(["docker", "image", "inspect", image_id], timeout=60)
        value = json.loads(raw)
        require(type(value) is list and len(value) == 1 and value[0]["Id"] == image_id,
                "image inspection identity drift")
        observations[image_id] = value[0]
        descriptors[name] = save(output, name + ".image-inspect.json", raw)
    save(output, "image-inspect-map.json", encoded(observations))
    probes = {}
    for system in ("gstreamer_custom", "openvino_gva"):
        value = DEFAULT_DEPENDENCIES.probe_openvino_device(
            Path("/usr/bin/docker"), Path("/var/run/docker.sock"), ROOT, images[system], system)
        descriptors[system + "_device_probe"] = save(output, system + ".device-probe.json", encoded(value))
        require(value["schema_version"] == 1
                and value["artifact_kind"] == "vast_openvino_checkpoint_device_probe"
                and any(row.get("device_id") == "CPU" for row in value["available_devices"]),
                "device probe drift")
        probes[system] = value
    save(output, "device-probe-map.json", encoded(probes))
    require(patch_path.read_bytes() == patch_bytes, "patch changed during observations")
    report = {"status": "captured", "build_commit": COMMIT,
              "completed_at_utc": datetime.now(timezone.utc).isoformat(),
              "image_count": len(observations), "device_probe_count": len(probes),
              "patch_sha256": hashlib.sha256(patch_bytes).hexdigest(), "files": descriptors,
              "limitation": "Actual runtime observations for artificial test command boundaries; not Q1 acceptance."}
    save(output, "capture.json", encoded(report))
    print(json.dumps({"status": "captured", "image_count": len(observations),
                      "device_probe_count": len(probes), "output": str(output)}, sort_keys=True))


if __name__ == "__main__":
    main()
