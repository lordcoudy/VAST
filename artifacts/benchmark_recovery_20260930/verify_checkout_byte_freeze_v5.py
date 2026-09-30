"""Finite artifact-only verifier for reviewed source-byte tasks17.1/17.2.

prepare changes only the approved .gitattributes block. Other modes never edit
the original repository. checkouts requires a later exact source commit, uses
the common Gitdir and configures autocrlf before each clone's initial checkout.
No staging/commit/install/image/model/workload or prior-inode receipt rebinding.
"""
from contextlib import ExitStack
import argparse
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import time
import uuid
sys.dont_write_bytecode = True

PLANNING = "b1ad01c09b4e21f542f971b9dc794548245719b0"
AUDIT = ("artifacts/benchmark_recovery_20260930/packaging-source-rollforward.v4.json",
    "6199d98a4496a7c54d5a45ff80687786f5bf7ad43c90f0d2a1129cf2ba007c31")
PROPOSAL = ("artifacts/benchmark_recovery_20260930/byte-freeze.minimum-proposed.gitattributes.v1.txt",
    "650f4584f8ba6ceda86b1274ffb43c80871b6e8620f5ce5314e2c165a54b609c")
OBSERVATIONS = ("artifacts/benchmark_recovery_20260930/byte-freeze-readonly-observations.v1.json",
    "ead2b5907412e4bf5b47ffd093c482dd341a1eab0107515258b7b531a69cbb2d")
AGGREGATE = "f7e2b75bf6eaf847b810fedc417782af3bb1238f4b23ab030463219690667ecc"
ATTRIBUTES = ("text", "eol", "filter", "ident", "working-tree-encoding")
CHUNK = 1024 * 1024
COMMANDS = []


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("ascii")


def epoch(info):
    return [info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
        info.st_mtime_ns, info.st_ctime_ns]


def aggregate(rows):
    return hashlib.sha256("".join(row["sha256"] + "  " + row["path"] + "\n"
        for row in sorted(rows, key=lambda row: row["path"])).encode("ascii")).hexdigest()


class Held:
    """Hold fixed leaf bytes/epoch7; allow unrelated sibling output creation."""
    def __init__(self, root):
        self.root = Path(root)
        require(self.root.resolve(strict=True) == self.root, "aliased project root")
        self.stack, self.files, self.ancestors = ExitStack(), {}, {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        try:
            self.verify()
        finally:
            self.stack.close()

    @staticmethod
    def hash_fd(fd):
        os.lseek(fd, 0, os.SEEK_SET)
        digest, size = hashlib.sha256(), 0
        while chunk := os.read(fd, CHUNK):
            digest.update(chunk)
            size += len(chunk)
        return digest.hexdigest(), size

    def pin(self, name):
        require(name and not Path(name).is_absolute() and ".." not in Path(name).parts,
            "noncanonical fixed input")
        if name in self.files:
            return dict(self.files[name][2])
        path = self.root / name
        require(path.resolve(strict=True) == path, "source ancestor/leaf alias: " + name)
        for parent in (path.parent, *path.parent.parents):
            info = parent.lstat()
            identity = epoch(info)[:4]
            require(stat.S_ISDIR(info.st_mode) and self.ancestors.setdefault(str(parent), identity)
                == identity, "ancestor changed")
            if parent == self.root:
                break
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        self.stack.callback(os.close, fd)
        observed = epoch(os.fstat(fd))
        require(stat.S_ISREG(observed[2]) and observed[3] == 1 and observed == epoch(path.lstat()),
            "nonoriginal regular source")
        digest, size = self.hash_fd(fd)
        require(size == observed[4] and observed == epoch(os.fstat(fd))
            and observed == epoch(path.lstat()), "source read raced")
        result = {"path": name, "size_bytes": size, "sha256": digest}
        self.files[name] = (fd, observed, result)
        return dict(result)

    def raw(self, name):
        result = self.pin(name)
        require(result["size_bytes"] <= 2 * CHUNK, "metadata bound")
        fd = self.files[name][0]
        os.lseek(fd, 0, os.SEEK_SET)
        raw = bytearray()
        while chunk := os.read(fd, CHUNK):
            raw.extend(chunk)
            require(len(raw) <= 2 * CHUNK, "metadata grew")
        require(hashlib.sha256(raw).hexdigest() == result["sha256"], "metadata drift")
        return bytes(raw)

    def verify(self):
        for name, (fd, expected, pin) in self.files.items():
            path = self.root / name
            require(path.resolve(strict=True) == path and epoch(path.lstat()) == expected
                and epoch(os.fstat(fd)) == expected, "source custody changed: " + name)
            digest, size = self.hash_fd(fd)
            require(digest == pin["sha256"] and size == pin["size_bytes"]
                and epoch(os.fstat(fd)) == expected and epoch(path.lstat()) == expected,
                "source bytes changed: " + name)
        for name, expected in self.ancestors.items():
            path = Path(name)
            require(path.resolve(strict=True) == path and epoch(path.lstat())[:4] == expected,
                "source ancestor changed")

    def witnesses(self):
        return [{"descriptor": row[2], "epoch": row[1]} for _, row in sorted(self.files.items())]


def process_observation(pid):
    try:
        fields = Path(f"/proc/{pid}/stat").read_text("ascii").rpartition(") ")[2].split()
        status = Path(f"/proc/{pid}/status").read_text("ascii")
        return {"pid": pid, "start_ticks": int(fields[19]), "state": fields[0],
            "pgid": int(fields[2]), "sid": int(fields[3]),
            "uid": int(re.search(r"^Uid:\s+(\d+)", status, re.M)[1]),
            "gid": int(re.search(r"^Gid:\s+(\d+)", status, re.M)[1]),
            "boot_id": Path("/proc/sys/kernel/random/boot_id").read_text("ascii").strip()}
    except FileNotFoundError:
        return {"pid": pid, "observation": "unavailable_process_already_exited"}


def command(argv, root, *, data=None, timeout=120):
    before = time.monotonic_ns()
    child = subprocess.Popen(argv, cwd=root, stdin=subprocess.PIPE if data is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"),
        start_new_session=True)
    observed, timed_out = process_observation(child.pid), False
    try:
        stdout, stderr = child.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        # This original child created an exclusive session/process group;
        # terminate its owned transport/index-pack children as well.
        os.killpg(child.pid, signal.SIGKILL)
        stdout, stderr = child.communicate(timeout=15)
    group_members = []
    for entry in Path("/proc").iterdir():
        if entry.name.isdigit():
            try:
                fields = (entry / "stat").read_text("ascii").rpartition(") ")[2].split()
                if int(fields[2]) == child.pid:
                    group_members.append({"pid": int(entry.name), "state": fields[0], "start_ticks": int(fields[19])})
            except (FileNotFoundError, ProcessLookupError):
                pass
    COMMANDS.append({"ordinal": len(COMMANDS) + 1, "argv": list(argv), "cwd": str(root),
        "child": observed, "returncode": child.returncode, "timed_out": timed_out,
        "exclusive_original_process_group": child.pid, "terminal_group_members": group_members,
        "terminal_group_has_live_members": any(row["state"] != "Z" for row in group_members),
        "started_monotonic_ns": before, "terminal_monotonic_ns": time.monotonic_ns(),
        "stdout": {"size_bytes": len(stdout), "sha256": hashlib.sha256(stdout).hexdigest()},
        "stderr": {"size_bytes": len(stderr), "sha256": hashlib.sha256(stderr).hexdigest()}})
    require(not timed_out and len(stdout) <= CHUNK and len(stderr) <= CHUNK, "command time/capture bound")
    require(not any(row["state"] != "Z" for row in group_members), "original command left a live group member")
    require(child.returncode == 0, "original command failed: " + repr(argv) + ": "
        + stderr.decode("utf-8", "replace"))
    return stdout


def git(root):
    marker = root / ".git"
    if marker.is_dir():
        gitdir = marker
    else:
        declared = marker.read_text("ascii").strip()
        require(declared.startswith("gitdir: E:/STUDY/VAST/.git/worktrees/"), "unexpected original gitdir")
        gitdir = Path("/mnt/e/" + declared.removeprefix("gitdir: E:/"))
    require(gitdir.resolve(strict=True) == gitdir, "aliased gitdir")
    return ["git", "--git-dir=" + str(gitdir), "--work-tree=" + str(root)]


def attrs(prefix, root, names):
    raw = command(prefix + ["check-attr", "-z", "--stdin", *ATTRIBUTES], root,
        data=("\0".join(names) + "\0").encode("ascii"))
    parts = raw.decode("ascii").split("\0")
    require(parts.pop() == "" and len(parts) == len(names) * len(ATTRIBUTES) * 3, "attribute response shape")
    result = {name: {} for name in names}
    for n in range(0, len(parts), 3):
        name, attribute, value = parts[n:n + 3]
        require(attribute not in result[name], "duplicate attribute")
        result[name][attribute] = value
    return result


def desired_attrs(names, raw_paths):
    return {name: {"text": "unset" if name in raw_paths else "set",
        "eol": "unspecified" if name in raw_paths else "lf", "filter": "unspecified",
        "ident": "unspecified", "working-tree-encoding": "unspecified"} for name in names}


class CREOL:
    def __init__(self):
        self.digest, self.pending = hashlib.sha256(), b""

    def update(self, data):
        data = self.pending + data
        self.pending = b"\r" if data.endswith(b"\r") else b""
        self.digest.update((data[:-1] if self.pending else data).replace(b"\r\n", b"\n"))

    def finish(self):
        self.digest.update(self.pending)
        return self.digest.hexdigest()


def blobs(prefix, root, held, pins, revision):
    before, argv = time.monotonic_ns(), prefix + ["cat-file", "--batch"]
    child = subprocess.Popen(argv, cwd=root, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=dict(os.environ, GIT_OPTIONAL_LOCKS="0"))
    observed, results = process_observation(child.pid), []
    output_digest, output_size = hashlib.sha256(), 0
    try:
        for pin in pins:
            spec = revision + ":" + pin["path"] if revision else ":" + pin["path"]
            child.stdin.write((spec + "\n").encode("ascii"))
            child.stdin.flush()
            header = child.stdout.readline(256)
            output_digest.update(header)
            output_size += len(header)
            require(header.endswith(b"\n") and not header.endswith(b" missing\n"), "missing source blob " + spec)
            object_id, kind, size = header.decode("ascii").strip().split(" ")
            require(kind == "blob", "source not a blob")
            remaining, digest, normalized = int(size), hashlib.sha256(), CREOL()
            while remaining:
                raw = child.stdout.read(min(CHUNK, remaining))
                require(raw, "truncated blob")
                remaining -= len(raw)
                digest.update(raw)
                normalized.update(raw)
                output_digest.update(raw)
                output_size += len(raw)
            delimiter = child.stdout.read(1)
            require(delimiter == b"\n", "blob delimiter")
            output_digest.update(delimiter)
            output_size += 1
            current = CREOL()
            fd = held.files[pin["path"]][0]
            os.lseek(fd, 0, os.SEEK_SET)
            while raw := os.read(fd, CHUNK):
                current.update(raw)
            normalized_sha, physical_sha = normalized.finish(), current.finish()
            exact = int(size) == pin["size_bytes"] and digest.hexdigest() == pin["sha256"]
            results.append({"path": pin["path"], "git_spec": spec, "git_object_id": object_id,
                "size_bytes": int(size), "sha256": digest.hexdigest(), "physical": pin,
                "category": "exact" if exact else "CR_at_EOL_only" if normalized_sha == physical_sha else "semantic_difference",
                "CR_at_EOL_sha256": normalized_sha, "physical_CR_at_EOL_sha256": physical_sha})
        child.stdin.close()
        require(child.wait(timeout=120) == 0 and not child.stderr.read(CHUNK + 1), "batch command failed")
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=15)
        for pipe in (child.stdin, child.stdout, child.stderr):
            if pipe is not None and not pipe.closed:
                pipe.close()
    COMMANDS.append({"ordinal": len(COMMANDS) + 1, "argv": argv, "cwd": str(root),
        "input_specs": [row["git_spec"] for row in results], "child": observed, "returncode": child.returncode,
        "started_monotonic_ns": before, "terminal_monotonic_ns": time.monotonic_ns(),
        "stdout": {"size_bytes": output_size, "sha256": output_digest.hexdigest(),
            "capture": "streamed_one_MiB_no_raw_payload_cache"},
        "stderr": {"size_bytes": 0, "sha256": hashlib.sha256(b"").hexdigest()}})
    return results


def closures(root, held, audit):
    sys.path.insert(0, str(root / "scripts"))
    import publication_image_build_v1 as build
    import publication_qualification_image_refreeze_v1 as refreeze
    import publication_policy_qualification_execution_code_closure_v1 as host
    require(Path(build.__file__).resolve().is_relative_to(root), "foreign build validator")
    registry = refreeze.load_refreeze_registry(project_root=root,
        registry_path=root / "configs/publication_qualification_image_refreeze_v1.json")
    runtime = []
    for old, system in zip(audit["invalidated_runtime_contexts"], registry["systems"], strict=True):
        require(old["system"] == system["system"], "runtime order")
        source = refreeze._source_identity(root, system)
        require(source == old["source_identity"], "runtime source identity changed")
        paths = tuple(refreeze._read_allowlist(root, system["source_allowlist"]))
        deps = tuple(refreeze._read_allowlist(root, system["dependency_allowlist"]))
        auxiliary = tuple(refreeze._read_allowlist(root, str(Path(system["source_allowlist"]).with_name(
            "runtime-build-context-allowlist.txt")))) if system["system"] in {"gstreamer_custom", "openvino_gva"} else ()
        context = sorted(set(paths).union(deps, auxiliary))
        spec = importlib.util.spec_from_file_location("checkout_validator_" + system["system"],
            root / old["validator_source"]["path"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        closure = module.validate_runtime_source_closure(project_root=root,
            manifest_path=root / system["source_allowlist"])
        require(set(closure.get("all_sources", closure.get("declared_sources", ()))) == set(paths)
            and list(closure["python_sources"]) == old["exact_python_import_closure"], "runtime import closure drift")
        actual = {"source_set_sha256": aggregate([held.pin(path) for path in paths]),
            "dependency_set_sha256": aggregate([held.pin(path) for path in deps]),
            "build_context_sha256": aggregate([held.pin(path) for path in context]),
            "exact_context_members": [held.pin(path) for path in context]}
        require(actual == old["actual_build_context"], "actual runtime context changed")
        runtime.append({"system": system["system"], "source_identity": source,
            "actual_build_context": actual, "python_source_count": len(closure["python_sources"]),
            "Docker_COPY_sources_bound_by_unchanged_Dockerfile": old["exact_Docker_COPY_sources"]})
    plan = build.publication_image_build_plan(project_root=root, registry_path=root / build.REGISTRY_RELATIVE_PATH)
    rows, native_worker = {row["name"]: row for row in plan["images"]}, []
    for old in audit["unchanged_native_and_worker_contexts"]:
        row = rows[old["name"]]
        actual = {key: row[key] for key in old["original_hashes"]}
        members = [held.pin(path) for path in row["relative_paths"]]
        require(actual == old["original_hashes"] == old["current_hashes"]
            and members == old["current_context_members"], "native/worker original identity drift")
        native_worker.append({"name": old["name"], "hashes": actual, "current_context_members": members,
            "original_freeze_receipt": old["original_freeze_receipt"]})
    names = [path.relative_to(root).as_posix() for _, path in host._discover_sources(root)]
    require(names == audit["host_execution_code_closure"]["exact_project_source_paths"]
        and len(names) == 78 and list(host.SEED_MODULES) == audit["host_execution_code_closure"]["seeds"],
        "host closure changed")
    host_pins = [held.pin(path) for path in names]
    require(host_pins == audit["host_execution_code_closure"]["exact_project_source_pins"], "host bytes changed")
    return {"four_runtime_contexts": runtime, "native_three_worker_two": native_worker,
        "host": {"source_count": 78, "seeds": list(host.SEED_MODULES), "sources": host_pins,
            "aggregate_sha256": aggregate(host_pins)}, "images_or_models_executed": False}


def inputs(evidence_root, held):
    evidence = Held(evidence_root)
    evidence.__enter__()
    held.stack.callback(evidence.__exit__, None, None, None)
    for name, expected in (AUDIT, PROPOSAL, OBSERVATIONS):
        require(evidence.pin(name)["sha256"] == expected, "reviewed evidence changed")
    audit, observations = json.loads(evidence.raw(AUDIT[0])), json.loads(evidence.raw(OBSERVATIONS[0]))
    rules = [line for line in evidence.raw(PROPOSAL[0]).decode("ascii").splitlines()
        if line and not line.startswith("#")]
    require(len(rules) == 156 and rules == sorted(rules) and len(set(rules)) == 156
        and all(re.fullmatch(r"/[^\s*?\[\]]+ -text !eol", line) for line in rules), "finite exact rules")
    raw_paths = {line.split(" ", 1)[0][1:] for line in rules}
    pins = audit["final_actual_source_manifest"]["project_sources"]
    names = [row["path"] for row in pins]
    require(len(names) == 165 and len(set(names)) == 165 and raw_paths.issubset(names)
        and aggregate(pins) == AGGREGATE, "source inventory changed")
    lf = set(names) - raw_paths
    require(len(lf) == 9 and all(observations["effective_attributes"][name]["text"] == "set"
        and observations["effective_attributes"][name]["eol"] == "lf" for name in lf), "nine LF contracts")
    for expected in pins:
        require(held.pin(expected["path"]) == expected, "physical source drift: " + expected["path"])
    return audit, observations, rules, raw_paths, pins, evidence


def write_new(path, value):
    require(path.is_absolute() and path.parent.resolve(strict=True) == path.parent
        and not path.exists(), "nonfresh proof path")
    value["sha256"] = hashlib.sha256(canonical(value)).hexdigest()
    raw = canonical(value) + b"\n"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o444)
    with os.fdopen(fd, "wb") as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())
    return {"path": str(path), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def base_report(mode, root, evidence):
    return {"schema_version": 1, "artifact_kind": "vast_checkout_byte_freeze_verification_v1",
        "mode": mode, "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "controller": process_observation(os.getpid()), "project_root": str(root),
        "project_root_epoch": epoch(root.lstat()), "reviewed_planning_commit": PLANNING,
        "reviewed_PR_comment": 5901895914, "frozen_physical_source_audit": evidence.pin(AUDIT[0]),
        "reviewed_exact_attribute_proposal": evidence.pin(PROPOSAL[0]),
        "verifier": evidence.pin(Path(__file__).resolve().relative_to(evidence.root).as_posix()),
        "accepted": False, "publication_ready": False, "launch_or_publication_grant": False,
        "scope": "finite_source_byte_checkout_reproducibility_not_image_model_or_benchmark_acceptance"}


def prepare(args):
    root = Path(args.project_root)
    with Held(root) as held:
        audit, observations, rules, raw_paths, pins, evidence = inputs(root, held)
        prefix, names = git(root), [row["path"] for row in pins]
        head = command(prefix + ["rev-parse", "HEAD"], root).decode("ascii").strip()
        require(head == PLANNING, "planning commit changed")
        observed_attrs = attrs(prefix, root, names)
        before_attrs = observations["effective_attributes"]
        require(observed_attrs == (desired_attrs(names, raw_paths) if args.confirm_existing_attributes else before_attrs),
            "preparation attributes drift")
        index, head_blobs = blobs(prefix, root, held, pins, ""), blobs(prefix, root, held, pins, "HEAD")
        require([(row["size_bytes"], row["sha256"]) for row in index] ==
            [(row["size_bytes"], row["sha256"]) for row in head_blobs], "source index already staged")
        candidates = observations["current_22_raw_stage_candidates"]
        require(len(candidates) == 22 and {row["path"] for row in index if row["category"] != "exact"}
            == {row["path"] for row in candidates} and all(row["category"] in {"exact", "CR_at_EOL_only"}
            for row in index), "exact 143+22 precondition")
        for row in candidates:
            require(held.pin(row["path"]) == row, "raw stage candidate changed")
        closure_report = closures(root, held, audit)
        attribute_path = root / ".gitattributes"
        current = attribute_path.read_bytes()
        before = command(prefix + ["show", "HEAD:.gitattributes"], root)
        require(before.endswith(b"\n") and len(before) <= 64 * 1024, "attributes unsupported prefix")
        info = attribute_path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and attribute_path.resolve(strict=True) == attribute_path, "attributes alias")
        addition = ("\n# Exact dependency bytes for reviewed benchmark source identities.\n"
            "# Preserve the nine existing explicit LF contracts above.\n" + "\n".join(rules) + "\n").encode("ascii")
        if args.confirm_existing_attributes:
            require(current == before + addition, "existing attributes are not exact reviewed append")
        else:
            require(current == before, "attributes dirty")
            fd = os.open(attribute_path, os.O_WRONLY | os.O_APPEND | os.O_NOFOLLOW)
            try:
                require(epoch(os.fstat(fd)) == epoch(info), "attributes replaced before append")
                require(os.write(fd, addition) == len(addition), "partial attributes append")
                os.fsync(fd)
            finally:
                os.close(fd)
        after = attribute_path.read_bytes()
        require(after == before + addition, "unexpected attributes mutation")
        after_attrs = attrs(prefix, root, names)
        require(after_attrs == desired_attrs(names, raw_paths), "156 raw+nine LF effective contract")
        require(index == blobs(prefix, root, held, pins, ""), "index changed during append")
        held.verify()
        report = base_report("confirmed_exact_attributes_after_failed_metadata_receipt" if args.confirm_existing_attributes
            else "prepared_attributes_before_root_staging", root, evidence)
        report.update({"HEAD": head, "source_count": 165, "physical_source_aggregate_sha256": AGGREGATE,
            "attributes": {"path": ".gitattributes", "original_sha256": hashlib.sha256(before).hexdigest(),
                "original_size_bytes": len(before), "size_bytes": len(after), "sha256": hashlib.sha256(after).hexdigest(),
                "preserved_prefix": True, "exact_appended_rules": rules,
                "effective_before": before_attrs, "effective_after": after_attrs},
            "this_execution_mutated_attributes": not args.confirm_existing_attributes,
            "effective_before_origin": "frozen_original_observations" if args.confirm_existing_attributes else "this_original_execution",
            "prestage_index": index, "prestage_index_category_counts": {"exact": 143, "CR_at_EOL_only": 22,
                "semantic_difference": 0}, "exact_raw_stage_candidates": candidates,
            "source_index_unchanged": True, "source_physical_bytes_and_epoch7_unchanged": True,
            "closure_validation": closure_report, "source_witnesses": held.witnesses(), "commands": COMMANDS,
            "root_staging_and_source_commit_pending": True, "fresh_checkouts_executed": False,
            "source_repository_configuration_mutated": False, "unrelated_paths_staged_or_edited": False})
        result = write_new(Path(args.output), report)
        held.verify()
        print(json.dumps({"proof": result, "attributes_sha256": report["attributes"]["sha256"],
            "raw_stage_paths": [row["path"] for row in candidates], "source_count": 165}))


def verify_source(args):
    root, evidence_root = Path(args.project_root), Path(args.evidence_root or args.project_root)
    with Held(root) as held:
        audit, observations, rules, raw_paths, pins, evidence = inputs(evidence_root, held)
        prefix, names = git(root), [row["path"] for row in pins]
        head = command(prefix + ["rev-parse", "HEAD"], root).decode("ascii").strip()
        require(head == args.source_commit and re.fullmatch(r"[0-9a-f]{40}", head), "exact source commit required")
        command(prefix + ["merge-base", "--is-ancestor", PLANNING, head], root)
        effective = attrs(prefix, root, names)
        require(effective == desired_attrs(names, raw_paths), "source attributes transform")
        index, commit = blobs(prefix, root, held, pins, ""), blobs(prefix, root, held, pins, head)
        require(all(row["category"] == "exact" for row in index + commit), "physical/index/commit bytes differ")
        declared_status = command(prefix + ["status", "--porcelain=v1", "-z", "--untracked-files=no", "--",
            ".gitattributes", *names], root)
        # The original Windows worktree's Git stat cache is an observation,
        # not raw byte authority: every physical/index/commit blob above must
        # already match. Both genuinely fresh initial checkouts must be clean.
        if args.expected_autocrlf is not None:
            require(declared_status == b"", "fresh declared source paths dirty")
        attribute_raw = held.raw(".gitattributes")
        attribute_blob = command(prefix + ["show", head + ":.gitattributes"], root)
        # This file lies outside the frozen165 dependencies. A fresh autocrlf
        # checkout may convert only its CR-at-EOL. The165 raw bytes, committed
        # rule lines, effective attributes and clean declared paths stay exact.
        if args.expected_autocrlf is None:
            require(attribute_raw == attribute_blob, "original attributes blob differs")
        else:
            require(attribute_raw.replace(b"\r\n", b"\n") == attribute_blob.replace(b"\r\n", b"\n"),
                "checkout attributes changed beyond CR-at-EOL")
        for rule in rules:
            require(attribute_raw.decode("ascii").splitlines().count(rule) == 1, "raw rule missing/duplicated")
        closure_report = closures(root, held, audit)
        report = base_report("verified_exact_source_commit", root, evidence)
        report.update({"source_commit": head, "source_count": 165, "physical_source_aggregate_sha256": AGGREGATE,
            "effective_attributes": effective, "index_blobs": index, "source_commit_blobs": commit,
            "attributes": held.pin(".gitattributes"),
            "committed_attributes": {"git_spec": head + ":.gitattributes", "size_bytes": len(attribute_blob),
                "sha256": hashlib.sha256(attribute_blob).hexdigest()},
            "attribute_file_outside_frozen165": True,
            "attribute_file_byte_relation": "exact" if attribute_raw == attribute_blob else "CR_at_EOL_only",
            "declared_status": "clean" if not declared_status else "original_stat_status_nonempty_raw_bytes_exact",
            "git_status_porcelain_hex": declared_status.hex(),
            "fresh_checkout_clean_status_required": args.expected_autocrlf is not None,
            "Git_optional_locks_disabled": True, "closure_validation": closure_report,
            "source_witnesses": held.witnesses(), "commands": COMMANDS, "new_custody_only_no_prior_inode_rebinding": True,
            "source_repository_configuration_mutated": False, "workloads_executed": False})
        if args.expected_autocrlf is not None:
            actual = command(prefix + ["config", "--local", "--get", "core.autocrlf"], root).decode("ascii").strip()
            require(actual == args.expected_autocrlf, "checkout autocrlf mismatch")
            report["core_autocrlf"] = actual
        held.verify()
        result = write_new(Path(args.output), report)
        print(json.dumps({"proof": result, "source_commit": head, "source_aggregate_sha256": AGGREGATE}))


def checkouts(args):
    root = Path(args.project_root)
    require(re.fullmatch(r"[0-9a-f]{40}", args.source_commit or ""), "explicit new source commit required")
    prefix = git(root)
    common = Path(command(prefix + ["rev-parse", "--git-common-dir"], root).decode("ascii").strip())
    if not common.is_absolute():
        common = root / common
    require(common.resolve(strict=True) == common and common == Path("/mnt/e/STUDY/VAST/.git"),
        "wrong original common Gitdir")
    script = Path(__file__).resolve(strict=True)
    require(script.parent == root / "artifacts/benchmark_recovery_20260930", "foreign verifier")
    output = Path(args.output)
    source_proof_path = output.with_name(output.stem + ".source.json")
    source_raw = command([sys.executable, str(script), "verify-source", "--project-root", str(root),
        "--source-commit", args.source_commit, "--output", str(source_proof_path)], root, timeout=300)
    require(shutil.disk_usage("/var/tmp").free >= 8 * 1024**3, "insufficient fresh checkout space")
    branch = "codex/fix-benchmark-preparations-spec"
    branch_tip = command(prefix + ["rev-parse", "refs/heads/" + branch], root).decode("ascii").strip()
    require(branch_tip == args.source_commit, "original branch does not identify exact reviewed source commit")
    reports = []
    for autocrlf in ("false", "true"):
        clone_root = Path("/var/tmp") / ("vast-byte-freeze-" + args.source_commit[:12] + "-"
            + autocrlf + "-" + uuid.uuid4().hex[:12])
        require(not clone_root.exists() and clone_root.parent.resolve(strict=True) == clone_root.parent,
            "nonfresh checkout root")
        clone_ordinal = len(COMMANDS) + 1
        command(["git", "clone", "--no-checkout", "--no-local", "--depth", "1", "--single-branch",
            "--branch", branch, common.as_uri(), str(clone_root)],
            root, timeout=300)
        require(clone_root.resolve(strict=True) == clone_root and (clone_root / ".git").is_dir(), "clone identity")
        require(not (clone_root / ".git/objects/info/alternates").exists(), "borrowed Git object authority")
        require((clone_root / ".git/shallow").read_text("ascii").strip() == args.source_commit, "nonexact shallow source")
        object_files = [p for p in (clone_root / ".git/objects").rglob("*") if p.is_file()]
        require(object_files and all(p.resolve(strict=True) == p and p.stat().st_nlink == 1
            for p in object_files), "aliased or shared clone objects")
        object_identity = [{"path": p.relative_to(clone_root).as_posix(), "epoch": epoch(p.stat())}
            for p in sorted(object_files)]
        new_root_epoch = epoch(clone_root.lstat())
        require(command(["git", "-C", str(clone_root), "ls-files", "-z"], clone_root) == b"",
            "clone already initially checked out")
        config_ordinal = len(COMMANDS) + 1
        command(["git", "-C", str(clone_root), "config", "--local", "core.autocrlf", autocrlf], clone_root)
        checkout_ordinal = len(COMMANDS) + 1
        command(["git", "-C", str(clone_root), "checkout", "--detach", args.source_commit],
            clone_root, timeout=300)
        proof_path = output.with_name(output.stem + ".autocrlf-" + autocrlf + ".json")
        verifier_ordinal = len(COMMANDS) + 1
        raw = command([sys.executable, str(script), "verify-source", "--project-root", str(clone_root),
            "--evidence-root", str(root), "--source-commit", args.source_commit,
            "--expected-autocrlf", autocrlf, "--output", str(proof_path)], clone_root, timeout=300)
        require(epoch(clone_root.lstat())[:4] == new_root_epoch[:4], "new checkout root replaced")
        reports.append({"core_autocrlf": autocrlf, "checkout_root": str(clone_root),
            "before_first_checkout_epoch": new_root_epoch, "terminal_checkout_root_epoch": epoch(clone_root.lstat()),
            "clone_command_ordinal": clone_ordinal, "config_before_first_checkout_command_ordinal": config_ordinal,
            "first_checkout_command_ordinal": checkout_ordinal, "verification_command_ordinal": verifier_ordinal,
            "proof": json.loads(raw)["proof"], "no_prior_inode_custody_rebound": True,
            "object_store": {"independent_transport": True, "no_alternates": True,
                "all_original_object_links_one": True, "physical_object_witnesses": object_identity}})
    value = {"schema_version": 1, "artifact_kind": "vast_fresh_initial_checkout_byte_freeze_proof_v1",
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "controller": process_observation(os.getpid()), "source_commit": args.source_commit,
        "original_common_git_directory": str(common), "original_common_git_directory_epoch": epoch(common.lstat()),
        "original_source_commit_proof": json.loads(source_raw)["proof"], "source_count": 165,
        "source_aggregate_sha256": AGGREGATE, "checkouts": reports, "commands": COMMANDS,
        "clone_recipe": "no_checkout_no_local_depth_one_single_exact_branch_file_transport",
        "full_history_copy_failed_namespace_preserved": "/var/tmp/vast-byte-freeze-79ff17832cf7-false-5183156493a1",
        "clone_timeout_seconds": 300,
        "retained_fresh_namespaces": True, "source_repository_configuration_mutated": False,
        "accepted": False, "publication_ready": False, "launch_or_publication_grant": False,
        "scope": "exact_source_initial_checkout_reproducibility_only_no_image_model_or_benchmark_acceptance"}
    print(json.dumps({"proof": write_new(output, value), "checkouts": reports}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "verify-source", "checkouts"))
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--evidence-root")
    parser.add_argument("--source-commit")
    parser.add_argument("--expected-autocrlf", choices=("false", "true"))
    parser.add_argument("--confirm-existing-attributes", action="store_true",
        help="Reverify a previously written exact append without writing again; never treat its failed receipt as success.")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    require(Path(args.output).is_absolute(), "proof output must be absolute")
    try:
        {"prepare": prepare, "verify-source": verify_source, "checkouts": checkouts}[args.mode](args)
    except BaseException as exc:
        # Persist actual completed command terminals even when a later bound,
        # validation or subprocess fails. No success receipt is manufactured.
        failed_path = Path(args.output).with_name(Path(args.output).stem + ".failed.json")
        failed = {"schema_version": 1, "artifact_kind": "vast_checkout_verifier_failed_terminal_v1",
            "controller": process_observation(os.getpid()), "mode": args.mode, "source_commit": args.source_commit,
            "error_type": type(exc).__name__, "error": str(exc), "commands": COMMANDS,
            "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "accepted": False, "publication_ready": False, "launch_or_publication_grant": False}
        if not failed_path.exists():
            write_new(failed_path, failed)
        raise


if __name__ == "__main__":
    main()
