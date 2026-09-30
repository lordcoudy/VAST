"""One bounded read-only inspection of the five original retained images.

Artifact observer only: no build, tag, pull, run, stop, model or authority grant.
Uses original stock projection/validators and separately retained source proof.
"""
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import stat
import subprocess
import sys
import time

sys.dont_write_bytecode = True
ROOT = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
HERE = ROOT / "artifacts/benchmark_recovery_20260930"
sys.path.insert(0, str(HERE))
from verify_checkout_byte_freeze_v9 import Held, canonical, epoch, process_observation, require, write_new

OUT = HERE / "unchanged-native-worker-live-inspection-v1"
ENGINE = Path("/usr/bin/docker")
SOCKET = Path("/run/docker.sock")
REPORT = {
    "schema_version": 1,
    "artifact_kind": "vast_unchanged_native_worker_live_inspection_v1",
    "classification": "bounded original daemon image metadata; no benchmark or model acceptance",
    "accepted": False,
    "command_limits": {"seconds_per_command": 20, "stdout_bytes": 1048576, "stderr_bytes": 65536},
    "commands": [],
    "controller": process_observation(os.getpid()),
    "source_commit": "caea5419c0302fc60183544de86f4e879346b7d0",
    "planning_commit": "47e432f2b5c09f750a55f7eb0164d84cc4d7e658",
    "review_reference": "https://github.com/lordcoudy/VAST/pull/2#issuecomment-5903081964",
}


def raw_new(path, raw):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(fd, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def group_members(pgid):
    rows = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            observed = process_observation(int(entry.name))
            if observed.get("pgid") == pgid:
                rows.append(observed)
    return rows


def query(engine_fd, arguments):
    ordinal = len(REPORT["commands"]) + 1
    argv = [str(ENGINE), *arguments]
    actual_argv = [f"/proc/self/fd/{engine_fd}", *arguments]
    child = subprocess.Popen(actual_argv, executable=actual_argv[0], pass_fds=(engine_fd,),
        cwd=ROOT, env={"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
        "DOCKER_HOST": "unix://" + str(SOCKET)}, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    row = {"ordinal": ordinal, "argv": argv, "executed_argv": actual_argv,
        "cwd": str(ROOT), "environment": {"PATH": "/usr/bin:/bin", "LANG": "C",
        "LC_ALL": "C", "DOCKER_HOST": "unix://" + str(SOCKET)},
        "child": process_observation(child.pid), "started_at_ns": time.time_ns()}
    REPORT["commands"].append(row)
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    selector = selectors.DefaultSelector()
    for channel, stream in (("stdout", child.stdout), ("stderr", child.stderr)):
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ, channel)
    deadline, failure = time.monotonic() + 20, None
    try:
        while selector.get_map():
            if time.monotonic() >= deadline:
                failure = "command_timeout"
                break
            for key, _ in selector.select(min(0.05, max(0, deadline - time.monotonic()))):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                channel = key.data
                limit = 1048576 if channel == "stdout" else 65536
                available = limit - len(buffers[channel])
                buffers[channel].extend(chunk[:available])
                if len(chunk) > available:
                    failure = "capture_limit_exceeded"
                    break
            if failure:
                break
        if failure:
            os.killpg(child.pid, signal.SIGKILL)
        child.wait(timeout=5)
    finally:
        if child.poll() is None:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=5)
        selector.close()
        child.stdout.close()
        child.stderr.close()
        row.update(returncode=child.returncode, terminal_at_ns=time.time_ns(),
            failure=failure, terminal_group_members=group_members(child.pid))
        for channel, raw in buffers.items():
            row[channel] = raw_new(OUT / f"command-{ordinal:02d}.{channel}.log", bytes(raw))
        write_new(OUT / f"command-{ordinal:02d}.v1.json", dict(row))
    require(failure is None and child.returncode == 0, "original read-only query failed")
    require(not row["terminal_group_members"], "original query group remains")
    return bytes(buffers["stdout"])


def socket_identity():
    require(SOCKET.resolve(strict=True) == SOCKET, "socket path alias")
    value = SOCKET.lstat()
    require(stat.S_ISSOCK(value.st_mode), "actual socket is absent")
    return [value.st_dev, value.st_ino, value.st_mode, value.st_uid, value.st_gid]


def main():
    require(ROOT.resolve(strict=True) == ROOT and OUT.parent.resolve(strict=True) == OUT.parent,
        "aliased observer namespace")
    OUT.mkdir(mode=0o755, exist_ok=False)
    with Held(ROOT) as held, Held(Path("/")) as external:
        script = held.pin(Path(__file__).relative_to(ROOT).as_posix())
        require(held.pin("artifacts/benchmark_recovery_20260930/verify_checkout_byte_freeze_v9.py")
            ["sha256"] == "0ef86e6fbd54d297d23ea1d4a0cf2ff7794ab2da15501f9ef2e2e77e6473aa2c",
            "original finite verifier drift")
        audit_path = "artifacts/benchmark_recovery_20260930/packaging-source-rollforward.v4.json"
        require(held.pin(audit_path)["sha256"] ==
            "6199d98a4496a7c54d5a45ff80687786f5bf7ad43c90f0d2a1129cf2ba007c31", "audit drift")
        audit = json.loads(held.raw(audit_path))
        proof_path = "artifacts/benchmark_recovery_20260930/byte-freeze-fresh-checkouts.v7.source.json"
        require(held.pin(proof_path)["sha256"] ==
            "7def15c706a49ed03ff6b87d4900873c129eb4d9ba4b29b9ce5aa409d1f76104", "source proof drift")
        report = json.loads(held.raw(proof_path))
        require(report["sha256"] == hashlib.sha256(canonical({k: v for k, v in report.items()
            if k != "sha256"})).hexdigest(), "source proof seal")
        REPORT["observer"] = script
        REPORT["source_and_checkout_proof"] = held.pin(proof_path)
        REPORT["original_packaging_audit"] = held.pin(audit_path)
        require(held.pin("scripts/publication_image_build_v1.py")["sha256"] ==
            "a27c2daaebb8fe8cad0fecfbcc60dc29f041835f8ae01e673dd321b3df1ea50e", "stock validator drift")
        held.pin("scripts/materialize_runtime_build_context_v3.py")
        sys.path.insert(0, str(ROOT / "scripts"))
        import publication_image_build_v1 as stock
        registry_path = "configs/publication_image_build_v1.json"
        require(held.pin(registry_path)["sha256"] ==
            "c13f12001048471e20400e5a0bb37df5efa01e6c936772ae9aaea5de548a6b22", "registry drift")
        registry = stock.load_publication_image_registry(project_root=ROOT, registry_path=ROOT / registry_path)
        for image in registry["images"]:
            held.pin(image["source_allowlist"])
            held.pin(image["dependency_allowlist"])
        plan = stock.publication_image_build_plan(project_root=ROOT, registry_path=ROOT / registry_path)
        planned = {image["name"]: image for image in plan["images"]}
        originals = {}
        original_refs = {}
        for previous in audit["unchanged_native_and_worker_contexts"]:
            ref = previous["original_freeze_receipt"]
            require(held.pin(ref["path"]) == ref, "original freeze physical identity")
            receipt = stock.load_publication_image_freeze_receipt(ROOT / ref["path"])
            require(receipt["registry_sha256"] == held.pin(registry_path)["sha256"], "original registry")
            frozen = next(image for image in receipt["images"] if image["name"] == previous["name"])
            actual = {key: planned[previous["name"]][key] for key in previous["original_hashes"]}
            require(actual == previous["original_hashes"] == previous["current_hashes"], "original context changed")
            require([held.pin(name) for name in planned[previous["name"]]["relative_paths"]]
                == previous["current_context_members"], "original source member changed")
            require(all(frozen[key] == value for key, value in actual.items()), "freeze context mismatch")
            originals[previous["name"]], original_refs[previous["name"]] = frozen, ref
        prefix = "artifacts/benchmark_recovery_20260930/gstreamer-decoder-fresh-registry-inspection/"
        baseline = json.loads(held.raw(prefix + "version.prelaunch.v1.json"))
        baseline_info = json.loads(held.raw(prefix + "engine_01.v1.json"))
        require(baseline["engine"] == {"path": str(ENGINE), "size_bytes": 45570705,
            "sha256": "a429e235ef670ea83357a5c8c7451f0a69d485a6fee49f9032fd938a0ab4969d"}
            and baseline["socket_identity"] == [61, 1944, 49584, 0, 1001],
            "original recorded engine/socket scope changed")
        stdout_ref = baseline_info["stdout"]
        baseline_stdout_path = Path(stdout_ref["path"]).relative_to(ROOT).as_posix()
        require(held.pin(baseline_stdout_path) == dict(stdout_ref, path=baseline_stdout_path),
            "original daemon stdout physical pin")
        require(stdout_ref["size_bytes"] == 39 and stdout_ref["sha256"] ==
            "406a38b0d978a01b1e5fbb7b6d4f5194161c01404c8226898e29bfdad449f523",
            "original recorded daemon raw observation changed")
        require(baseline_info["returncode"] == 0 and baseline_info["argv"] ==
            [str(ENGINE), "info", "--format", "{{json .ID}}"], "original daemon command")
        daemon_id = json.loads(held.raw(baseline_stdout_path))
        require(daemon_id == "aa8f3d33-e1dc-4ed2-ad06-488b46b332d0", "original daemon ID drift")
        engine_ref = external.pin("usr/bin/docker")
        require(dict(engine_ref, path=str(ENGINE)) == baseline["engine"], "original engine bytes differ")
        REPORT["engine"] = dict(engine_ref, path=str(ENGINE))
        REPORT["engine_epoch_before"] = external.files["usr/bin/docker"][1]
        REPORT["socket_identity_before"] = socket_identity()
        require(REPORT["socket_identity_before"] == baseline["socket_identity"], "original socket changed")
        fd = external.files["usr/bin/docker"][0]
        require(json.loads(query(fd, ["info", "--format", "{{json .ID}}"])) == daemon_id,
            "original daemon unavailable")
        targets = [originals[image["name"]]["target_reference"] for image in registry["images"]]
        raw_records = json.loads(query(fd, ["image", "inspect", *targets]))
        require(isinstance(raw_records, list) and len(raw_records) == 5, "original live image cardinality")
        REPORT["images"] = []
        for image, record in zip(registry["images"], raw_records, strict=True):
            frozen = originals[image["name"]]
            projection = stock._inspect_projection(record)
            require(projection["id"] == frozen["image_id"] and projection["repo_digests"] == frozen["repo_digests"],
                "original image ID/digest changed: " + image["name"])
            projection_sha = hashlib.sha256(stock._canonical_json(projection)).hexdigest()
            require(projection_sha == frozen["image_inspect_sha256"], "original inspect projection changed")
            stock._validate_built_image(record=record, image=image, base_id=frozen["base_image_id"],
                build_id=frozen["build_image_id"], context=planned[image["name"]])
            require(all(projection["config"]["labels"].get(key) == value for key, value in frozen["labels"].items()),
                "original labels changed")
            REPORT["images"].append({"name": image["name"], "original_freeze_receipt": original_refs[image["name"]],
                "original_receipt_image": frozen, "actual_inspect_projection": projection,
                "actual_inspect_projection_sha256": projection_sha,
                "actual_source_dependency_context": {key: planned[image["name"]][key]
                    for key in ("source_set_sha256", "dependency_set_sha256", "build_context_sha256")},
                "same_original_id_repo_digests_projection_labels_and_source_context": True})
        require(json.loads(query(fd, ["info", "--format", "{{json .ID}}"])) == daemon_id,
            "original daemon drift after inspect")
        held.verify()
        external.verify()
        REPORT["engine_epoch_after"] = epoch(ENGINE.lstat())
        REPORT["socket_identity_after"] = socket_identity()
        require(REPORT["socket_identity_after"] == REPORT["socket_identity_before"], "socket drift")
        REPORT["original_daemon_id"] = daemon_id
        REPORT["validated_inputs"] = held.witnesses()
        REPORT["external_witnesses"] = external.witnesses()
        REPORT["passed_finite_live_metadata_validation"] = True
        REPORT["terminal_at_ns"] = time.time_ns()
        print(json.dumps(write_new(OUT / "inspection.v1.json", REPORT), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        REPORT["passed_finite_live_metadata_validation"] = False
        REPORT["failure"] = {"type": type(error).__name__, "message": str(error)}
        REPORT["terminal_at_ns"] = time.time_ns()
        if OUT.is_dir() and not (OUT / "failed.v1.json").exists():
            print(json.dumps(write_new(OUT / "failed.v1.json", REPORT), sort_keys=True))
        raise
