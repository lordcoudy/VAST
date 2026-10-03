"""Close the original read-only image inspection without another Docker query."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
HERE = ROOT / "artifacts/benchmark_recovery_20260930"
sys.path.insert(0, str(HERE))
from verify_checkout_byte_freeze_v9 import Held, canonical, process_observation, require, write_new

with Held(ROOT) as held, Held(Path("/")) as external:
    name = "artifacts/benchmark_recovery_20260930/unchanged-native-worker-live-inspection-v1/inspection.v1.json"
    require(held.pin(name)["sha256"] ==
        "34219c6a5e226b0e1b18c3242f559e49694afdd1970ccf56902490f95c19b1be", "original receipt drift")
    original = json.loads(held.raw(name))
    require(original["sha256"] == hashlib.sha256(canonical({k: v for k, v in original.items()
        if k != "sha256"})).hexdigest(), "original receipt seal")
    observations = []
    for identity in [original["controller"], *[row["child"] for row in original["commands"]]]:
        observed = process_observation(identity["pid"])
        require(observed.get("observation") == "unavailable_process_already_exited",
            "original observer or CLI PID still present; no identity synthesis")
        observations.append({"original": identity, "actual_post_terminal_observation": observed})
    members = []
    groups = {identity["pgid"] for identity in [original["controller"],
        *[row["child"] for row in original["commands"]]]}
    for leaf in Path("/proc").iterdir():
        if leaf.name.isdigit():
            observed = process_observation(int(leaf.name))
            if observed.get("pgid") in groups:
                members.append(observed)
    require(not members, "original observer/CLI group remains")
    for witness in original["validated_inputs"]:
        descriptor = witness["descriptor"]
        require(held.pin(descriptor["path"]) == descriptor
            and held.files[descriptor["path"]][1] == witness["epoch"], "held original input drift")
    for row in original["commands"]:
        for channel in ("stdout", "stderr"):
            descriptor = row[channel]
            relative = Path(descriptor["path"]).relative_to(ROOT).as_posix()
            require(held.pin(relative) == dict(descriptor, path=relative), "original raw query log drift")
        relative = "artifacts/benchmark_recovery_20260930/unchanged-native-worker-live-inspection-v1/" \
            + f"command-{row['ordinal']:02d}.v1.json"
        document = json.loads(held.raw(relative))
        require(document["sha256"] == hashlib.sha256(canonical({k: v for k, v in document.items()
            if k != "sha256"})).hexdigest(), "individual original command seal")
    for leaf in ("unchanged-native-worker-live-inspection.v1.stdout.log",
        "unchanged-native-worker-live-inspection.v1.stderr.log"):
        held.pin("artifacts/benchmark_recovery_20260930/" + leaf)
    require(held.pin("artifacts/benchmark_recovery_20260930/unchanged-native-worker-live-inspection.v1.stderr.log")
        ["size_bytes"] == 0, "original observer stderr")
    engine = external.pin("usr/bin/docker")
    require(dict(engine, path="/usr/bin/docker") == original["engine"]
        and external.files["usr/bin/docker"][1] == original["engine_epoch_after"], "actual engine drift")
    socket = Path("/run/docker.sock").lstat()
    socket_observation = [socket.st_dev, socket.st_ino, socket.st_mode, socket.st_uid, socket.st_gid]
    require(socket_observation == original["socket_identity_after"], "actual socket drift")
    held.pin(Path(__file__).relative_to(ROOT).as_posix())
    held.verify()
    external.verify()
    report = {"schema_version": 1, "artifact_kind": "vast_unchanged_image_inspection_closed_terminal_v1",
        "accepted": False, "classification": "original read-only image CLI terminal and immutable metadata custody",
        "original_inspection": held.pin(name), "actual_original_process_observations": observations,
        "actual_original_groups": [{"pgid": group, "members": []} for group in sorted(groups)],
        "actual_socket_identity": socket_observation, "validated_inputs": held.witnesses(),
        "external_witnesses": external.witnesses(), "no_additional_Docker_query": True,
        "original_tool_terminal": {"tool": "exec_command", "chunk_id": "1883f9", "exit_code": 0,
            "wall_time_seconds": 3.7755613,
            "launcher_output": "WSL localhost proxy configuration warning outside original Linux capture files"},
        "controller": process_observation(os.getpid()), "observed_at_ns": time.time_ns()}
    print(json.dumps(write_new(HERE / "unchanged-native-worker-live-inspection.closed.v1.json", report),
        sort_keys=True))
