"""Fixed task-2.10 C1--C6 admission and independent comparison.

Nothing happens on import. The caller supplies the packet SHA from the separately
recorded independent evidence approval; a packet's own review strings are not an
authority. No image lifecycle, retry, alternate source or whole-chain admission
is exposed here. Stage D is a separate fixed consumer of validated C1 evidence.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager, nullcontext
import json
import os
from pathlib import Path
import re
import select
import signal
import stat
import struct
import subprocess
import time

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
from tests.fixtures import accepted_policy_fixture_compiler_v1 as compiler

STAGES = ("C1", "C2", "C3", "C4", "C5", "C6")
SEAL_BYTES = 536870912
C_LIMIT = 67108864
CONTROL_LIMIT = 4194304
RUNTIME_STOP = 16777216
RUN_NS = 150_000_000_000
COMPLETION_RESERVE_NS = 1_000_000_000
PACKET_LIMIT = 131072
RECORD_LIMIT = 524288
CRASH_DIRECTORY = Path("/mnt/c/Users/s-a-balashov/AppData/Local/Temp/wsl-crashes")
B_CIDS = (
    "4df593e12ca362e69f0594b2035197335f335d3ceae3c71894b31db9f197a09f",
    "9b5c396109909a8a091a0fc6bb6529f887233df77ab314435ce85ab05e22fbc5",
    "90f8ebb69bd83cbb02067a831cc2ace5efe78fc6b568a665bd93333d7b4b6e87",
)
MOUNTS_SHA256 = "3da03bbba33c8c86f2935cfcfcc07f16bb4020337d8d130deb5d8595851ff470"
EXPECTED = {
    "engine_id": "1e493309-3767-45fb-9078-05b838bdfd80", "server_version": "29.7.2",
    "kernel": "6.6.87.2-microsoft-standard-WSL2", "driver": "overlayfs", "cgroup_driver": "systemd",
    "security_options": ["name=seccomp,profile=builtin", "name=cgroupns"],
    "runtimes_sha256": "b480bc9619d585079ca9926e520ee190fc971f2e7c2c6c01b5256ac058c4a5d1",
    "provider_size": 10469582904,
    "rootfs_sha256": "1e0fe0c49e48962dc125b19e5b1936c564f1c6a3e00006d5e5cca7dc7ebfd981",
    "env_keys_sha256": "6785bc7c38e52df3c99c3856d0619875fc1a1f44aab077baa550da820b8f1db9",
    "platform_manifest": compiler.PROVIDER_PLATFORM_MANIFEST, "unpacked_bytes": 18930790400,
}
CODE_PATHS = (
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_component_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_publisher_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json",
    "scripts/publication_operational_request_domain_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_recovery_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_p0_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_child_v1.py",
)
PROOF_SOURCES = {
    "baseline": ("b1_result", "b1_report", "b2_index"),
    "toolchain": ("b1_report", "f2_supplement", "f2_index"),
    "abi": ("b1_report", "b2_report", "b2_result", "b2_index"),
    "limits": ("b1_report", "b1_result", "b2_report", "b2_index"),
    "closure": ("b1_result", "b2_result", "b3_result", "b2_index"),
}
B_ORIGINAL_SHA256 = {
    "b1_result": "9e722bd6b79d326c049da1083a7be14f8258e1a93ff04a18ed7c224756e118c5",
    "b1_report": "4f7dfcabe66e93326b454bb8a4ff0a38136b698da8de042086740b8486d10e90",
    "b2_result": "89fb2dd2ec3b1d0f4702ab6c0b15431147db4e64f38326b266665d3e351c2bd4",
    "b2_report": "ef203c57e1797bbf2556a494a2a0f22730f007638be5916b6bd1045831457535",
    "b3_result": "04fe470728acf9083b818a18a7620a45c52acb8a49f3ba12dcf13ecb045d1f18",
    "b2_manifest": "87c50e14f1a9ce3f5b0ff8ca2e4589e747ceb7ae5561671406e3da7a0c8f76d4",
}
EVIDENCE_NAMES = tuple(B_ORIGINAL_SHA256) + ("b2_index", "f2_supplement", "f2_index", "f2_accounting")
OPTIONAL_CODE_PATHS = (
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_child_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_recovery_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_p0_v1.py",
)


class Gate2Refusal(RuntimeError):
    def __init__(self, cause, facts=None):
        super().__init__(cause)
        self.cause, self.facts = cause, {} if facts is None else facts


def _require(condition, cause):
    if not condition:
        raise Gate2Refusal(cause)


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _sha_shape(value):
    return type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None


def _json(raw, cap=RECORD_LIMIT, *, canonical=True):
    _require(type(raw) is bytes and 0 < len(raw) <= cap, "json_bound")
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate key")
            value[key] = item
        return value
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=unique,
                           parse_constant=lambda value: (_ for _ in ()).throw(ValueError("nonfinite")))
        _require(compiler._json_bound(value) <= cap * 2, "json_shape")
        _require(not canonical or component.canonical_json_v1(value) == raw, "json_canonical")
        return value
    except (ValueError, UnicodeError, RecursionError, TypeError) as error:
        raise Gate2Refusal("json_invalid") from error


def _read(path, cap):
    path = Path(path)
    _require(path.is_absolute() and path.resolve(strict=True) == path, "physical_file")
    with path.open("rb") as file:
        before = os.fstat(file.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and 0 <= before.st_size <= cap, "file_bound")
        raw = file.read(cap + 1)
        after = os.fstat(file.fileno())
        _require(len(raw) == before.st_size and (before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns) == (after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns), "file_drift")
    return raw


def _descriptor(path, raw):
    return {"path": str(path), "size_bytes": len(raw), "sha256": _sha(raw)}


def _rpc_json_facts_v1(value):
    """Normalize only the fixed native endpoint tuples, before JSON bounding.

    The shared transport retains three six-field stat tuples for /, /run and
    /run/docker.sock. Preserve these values as JSON arrays without changing the
    transport's in-memory schema or allowing arbitrary tuple serialization.
    """
    if value is None:
        return None
    _require(type(value) is dict and type(value.get("rpc")) is list and len(value["rpc"]) <= 23, "rpc_fact_shape")
    result, rows = dict(value), []
    for original in value["rpc"]:
        _require(type(original) is dict and len(original) <= 64, "rpc_fact_row")
        row = dict(original)
        for name in ("epoch_before", "epoch_after"):
            epoch = row.get(name)
            if epoch is None:
                continue
            _require(type(epoch) in (tuple, list) and len(epoch) == 3 and all(
                type(item) in (tuple, list) and len(item) == 6 and all(
                    type(number) is int and number >= 0 or number is None for number in item) for item in epoch), "rpc_epoch_shape")
            row[name] = [list(item) for item in epoch]
        rows.append(row)
    result["rpc"] = rows
    return result


def _bound_descriptor(value, *, root=None, cap=RECORD_LIMIT):
    _require(type(value) is dict and set(value) == {"path", "size_bytes", "sha256"}
             and type(value["size_bytes"]) is int and 0 <= value["size_bytes"] <= cap
             and _sha_shape(value["sha256"]), "descriptor")
    path = Path(value["path"])
    if root is not None:
        _require(path.is_absolute() and path.is_relative_to(root), "descriptor_root")
    raw = _read(path, cap)
    _require(len(raw) == value["size_bytes"] and _sha(raw) == value["sha256"], "descriptor_drift")
    return raw


def write_record_v1(path, value, *, cap=RECORD_LIMIT, absolute_deadline_ns=None, return_facts=False):
    """Bound before encoding, exclusively persist and close one new original."""
    path = Path(path)
    _require(type(return_facts) is bool, "record_return_facts")
    _require(path.is_absolute() and path.parent.resolve(strict=True) == path.parent, "record_parent")
    facts = {"path": str(path), "open_completed": False, "written_bytes": 0, "write_extent_unknown": False,
             "flush_completed": False, "fsync_completed": False, "close_completed": False,
             "directory_persisted": False, "complete": False, "deadline_failed": False, "failure_causes": []}
    file, raw, failure = None, None, None
    phase = "bound"
    def check():
        if absolute_deadline_ns is not None:
            if type(absolute_deadline_ns) is not int or time.monotonic_ns() >= absolute_deadline_ns:
                facts["deadline_failed"] = True
                raise Gate2Refusal("record_deadline")
    try:
        check()
        _require(compiler._json_bound(value) <= cap, "record_bound")
        check()
        raw = component.canonical_json_v1(value)
        _require(len(raw) <= cap, "record_bound")
        check()
        phase = "open"
        file = path.open("xb", buffering=0)
        facts["open_completed"] = True
        check()
        phase = "write"
        try:
            written = file.write(raw)
        except (OSError, ValueError):
            facts["write_extent_unknown"] = True
            raise
        if type(written) is not int or not 0 <= written <= len(raw):
            facts["write_extent_unknown"] = True
            raise Gate2Refusal("record_write_contract")
        facts["written_bytes"] = written
        check()
        _require(written == len(raw), "record_short_write")
        phase = "flush"
        file.flush()
        facts["flush_completed"] = True
        check()
        phase = "fsync"
        os.fsync(file.fileno())
        facts["fsync_completed"] = True
        check()
    except FileExistsError:
        raise
    except (Gate2Refusal, OSError, ValueError, TypeError, RecursionError) as error:
        failure = error
        facts["failure_causes"].append("record_" + phase + "_" + type(error).__name__)
    finally:
        if file is not None:
            try:
                phase = "close"
                file.close()
                facts["close_completed"] = True
                check()
            except (Gate2Refusal, OSError, ValueError) as error:
                facts["failure_causes"].append("record_close_" + type(error).__name__)
                failure = failure or error
    if failure is None:
        try:
            check()
            phase = "directory_sync"
            compiler._compiler_directory_sync_v1(path.parent)
            facts["directory_persisted"] = True
            check()
        except (Gate2Refusal, OSError, ValueError) as error:
            facts["failure_causes"].append("record_" + phase + "_" + type(error).__name__)
            failure = error
    if failure is not None:
        cause = failure.cause if isinstance(failure, Gate2Refusal) else "record_" + type(failure).__name__
        raise Gate2Refusal(cause, facts) from failure
    facts["complete"] = True
    descriptor = _descriptor(path, raw)
    return {"descriptor": descriptor, "write_facts": facts} if return_facts else descriptor


def reserve_v1(*, charged, liability, c_free_bytes):
    _require(all(type(value) is int and value >= 0 for value in (charged, liability, c_free_bytes)), "ledger_unknown")
    _require(charged + liability <= SEAL_BYTES, "ledger_reserve")
    _require(c_free_bytes >= component.C_BYTES + component.ADDITIONAL_DISK_UPPER_BYTES, "capacity_floor")
    return charged + liability


def interval_charge_v1(before, after, *, retained_bytes, size_rw=0):
    names = ("c_free_bytes", "ext4_used_bytes")
    _require(type(before) is dict and type(after) is dict and all(
        type(row.get(name)) is int and row[name] >= 0 for row in (before, after) for name in names), "measurement_unknown")
    _require(type(retained_bytes) is int and retained_bytes >= 0 and type(size_rw) is int and size_rw >= 0, "measurement_unknown")
    return max(0, before["c_free_bytes"] - after["c_free_bytes"],
               after["ext4_used_bytes"] - before["ext4_used_bytes"], retained_bytes + size_rw)


def _b2_index_value(b_root):
    b_root = Path(b_root)
    _require(b_root.is_absolute() and b_root.resolve(strict=True) == b_root, "b_root")
    manifest_path = b_root / "runs/B2.originals.sha256"
    raw = _read(manifest_path, 16384)
    _require(_sha(raw) == B_ORIGINAL_SHA256["b2_manifest"], "b2_manifest_authentication")
    files = {}
    for line in raw.decode("ascii").splitlines():
        matched = re.fullmatch(r"([0-9a-f]{64})  ((?:outputs/B2/|runs/B2\.)[A-Za-z0-9_.-]+)", line)
        _require(matched is not None and matched[2] not in files, "b2_manifest_entry")
        expected, relative = matched.groups()
        value = _read(b_root / relative, 1048576)
        # The immutable manifest's stale self-entry is explicitly not authority.
        if relative == "runs/B2.originals.sha256":
            expected = B_ORIGINAL_SHA256["b2_manifest"]
        _require(_sha(value) == expected, "b2_original_drift")
        files[relative] = _descriptor(b_root / relative, value)
    _require("runs/B2.originals.sha256" in files, "b2_manifest_missing")
    return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_b2_corrected_index_v1",
            "b_root": str(b_root), "original_manifest_sha256": _sha(raw), "files": files}


def build_b2_index_v1(*, b_root, output_path):
    """Fresh no-self index; preserve every B original and verify the full manifest."""
    return write_record_v1(Path(output_path), _b2_index_value(b_root), cap=65536)


def _relative_original(root, descriptor, cap):
    _require(type(descriptor) is dict and set(descriptor) == {"relative_path", "size_bytes", "sha256"}, "relative_descriptor")
    relative = descriptor["relative_path"]
    _require(type(relative) is str and not Path(relative).is_absolute() and
             "\\" not in relative and all(part not in ("", ".", "..") for part in relative.split("/")), "relative_path")
    return _bound_descriptor({"path": str(root / relative), "size_bytes": descriptor["size_bytes"],
                              "sha256": descriptor["sha256"]}, root=root, cap=cap)


def _authenticate_evidence(evidence, review, plan_sha):
    _require(type(evidence) is dict and set(evidence) == set(EVIDENCE_NAMES), "proof_sources")
    actual = {name: _bound_descriptor(desc, cap=1048576) for name, desc in evidence.items()}
    for name, expected in B_ORIGINAL_SHA256.items():
        _require(_sha(actual[name]) == expected, "b_original_authentication_" + name)
    for name, cid in zip(("b1_result", "b2_result", "b3_result"), B_CIDS):
        original = _json(actual[name], 1048576)
        _require(original.get("cid") == cid and (original.get("closure") or {}).get("closed") is True, "b_identity_closure")
    corrected = _json(actual["b2_index"], 65536)
    _require(corrected == _b2_index_value(corrected.get("b_root")), "b2_index_drift")
    supplement = _json(actual["f2_supplement"], 262144)
    _require(supplement.get("artifact_kind") == "vast_fixture_compiler_toolchain_recovery_v1" and
             supplement.get("complete") is True and supplement.get("causes") == [] and
             supplement.get("controlled") is False and supplement.get("cid") == B_CIDS[0] and
             supplement.get("provider_id") == compiler.PROVIDER_ID, "f2_complete_identity")
    f2_review = supplement.get("review") or {}
    _require(f2_review.get("commit") == review["commit"] and
             f2_review.get("physical_plan_sha256") == plan_sha, "f2_review_binding")
    f2_root = Path(evidence["f2_supplement"]["path"]).parent
    index_raw = _relative_original(f2_root, supplement["originals_index"], 262144)
    _require(index_raw == actual["f2_index"] and Path(evidence["f2_index"]["path"]) == f2_root / "f2.originals.v1.json", "f2_index_binding")
    # F2's fixed verifier authenticates framing, members and the raw index. It
    # performs no recovery or Docker action; there is no decoder fallback.
    from tests.fixtures import accepted_policy_fixture_compiler_recovery_v1 as recovery
    _require(hasattr(recovery, "validate_supplement_v1"), "f2_verifier_missing")
    recovery.validate_supplement_v1(output_dir=f2_root, supplement=supplement)
    _require(Path(evidence["f2_accounting"]["path"]) == f2_root / "f2.final-accounting.v1.json" and
             actual["f2_accounting"] == _read(f2_root / "f2.final-accounting.v1.json", 262144), "f2_accounting_binding")
    b1 = _json(actual["b1_report"], 1048576)
    environment = ((b1.get("report") or {}).get("environment") or {}).get("environment")
    _require(type(environment) is dict and _sha(component.canonical_json_v1(sorted(environment))) == EXPECTED["env_keys_sha256"], "b_environment")
    return {"environment_keys": sorted(environment), "accounting": _json(actual["f2_accounting"], 262144)["accounting"]}


def _proof_envelopes(evidence):
    return {kind: {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_component_proof_v1",
                   "kind": kind, "provider_id": compiler.PROVIDER_ID, "b_cids": list(B_CIDS),
                   "sources": {name: evidence[name] for name in names}}
            for kind, names in PROOF_SOURCES.items()}


def _verify_code(root, code):
    _require(type(code) is dict and set(CODE_PATHS) <= set(code) <= set(CODE_PATHS + OPTIONAL_CODE_PATHS), "packet_code_set")
    total = 0
    for relative, desc in code.items():
        _require(type(desc) is dict and set(desc) == {"size_bytes", "sha256", "git_blob"}, "code_descriptor")
        raw = _bound_descriptor({"path": str(root / relative), "size_bytes": desc["size_bytes"],
                                 "sha256": desc["sha256"]}, root=root, cap=262144)
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
        _require(type(desc["git_blob"]) is str and desc["git_blob"] == blob, "reviewed_git_blob_drift")
        total += len(raw)
    _require(total <= 640 * 1024, "code_allocation")


def _validate_p0(descriptor, root, commit, boot_id):
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_p0_v1 as p0
    _bound_descriptor(descriptor, root=root, cap=65536)
    p0.validate_p0_originals_v1(descriptor, project_root=root, expected_code_commit=commit,
                              expected_engine_id=EXPECTED["engine_id"], expected_boot_id=boot_id)


def build_packet_v1(*, project_root, review, physical_plan_descriptor, code, evidence, p0_descriptor,
                    boot_id, initial_charged_bytes, initial_measurement):
    """Materialize after F2. Independent approval of its SHA is a later step.

    `code` contains descriptors obtained independently from the reviewed commit's
    git ls-tree/show blobs. The trusted operator checks that provenance BEFORE
    export/invocation. Recomputing a Git blob ID alone cannot establish approval.
    """
    root = Path(project_root)
    _require(root.is_absolute() and root.resolve(strict=True) == root, "packet_root")
    review = component._review(review)
    plan_raw = _bound_descriptor(physical_plan_descriptor, cap=65536)
    _verify_code(root, code)
    _require(type(boot_id) is str and 1 <= len(boot_id) <= 64 and
             type(initial_charged_bytes) is int and 11890688 <= initial_charged_bytes < SEAL_BYTES, "packet_physical")
    interval_charge_v1(initial_measurement, initial_measurement, retained_bytes=0)
    admitted = _authenticate_evidence(evidence, review, _sha(plan_raw))
    accounting = admitted["accounting"]
    f2_tail = accounting["reserved_control_bytes"] + accounting["reserved_rounding_bytes"] + accounting["reserved_metadata_bytes"]
    _require(all(type(value) is int and value >= 0 for value in (accounting["physical_charge_bytes"], f2_tail)), "initial_f2_charge")
    gap = interval_charge_v1(accounting["last"], initial_measurement, retained_bytes=0)
    minimum = 11890688 + 2 * 1048576 + accounting["physical_charge_bytes"] + f2_tail + max(0, gap - f2_tail - 1048576)
    _require(initial_charged_bytes >= minimum, "initial_charge_omitted_forms")
    _validate_p0(p0_descriptor, root, review["commit"], boot_id)
    proofs = _proof_envelopes(evidence)
    seed = component.component_seed_v1(review=review,
        bindings={"host_sha256": code[CODE_PATHS[2]]["sha256"], "publisher_sha256": code[CODE_PATHS[3]]["sha256"],
                  "profile_sha256": code[CODE_PATHS[4]]["sha256"]},
        engine={"driver": EXPECTED["driver"], "cgroup_driver": EXPECTED["cgroup_driver"],
                "security_options": EXPECTED["security_options"], "runtimes_sha256": EXPECTED["runtimes_sha256"]},
        provider={"rootfs_sha256": EXPECTED["rootfs_sha256"], "size_bytes": EXPECTED["provider_size"]},
        environment_keys=admitted["environment_keys"], mounts_sha256=MOUNTS_SHA256,
        proofs={kind: _sha(component.canonical_json_v1(value)) for kind, value in proofs.items()})
    seed_raw = component.canonical_json_v1(seed)
    _require(len(seed_raw) <= 4096, "seed_bound")
    packet = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_packet_v1",
            "project_root": str(root), "code_commit": review["commit"], "code_review": review,
            "physical_plan": physical_plan_descriptor, "code": code, "source_sha256": component.SOURCE_SHA256,
            "evidence": evidence, "proofs": proofs, "seed": seed, "seed_sha256": _sha(seed_raw), "p0": p0_descriptor,
            "boot_id": boot_id, "initial_charged_bytes": initial_charged_bytes, "initial_measurement": initial_measurement}
    _require(compiler._json_bound(packet) <= PACKET_LIMIT, "packet_bound")
    _require(sum(desc["size_bytes"] for desc in code.values()) + len(component.canonical_json_v1(packet)) +
             len(plan_raw) + len(seed_raw) <= 640 * 1024, "code_packet_allocation")
    return packet


def validate_packet_v1(*, project_root, packet_descriptor, expected_packet_sha256, expected_code_commit):
    _require(_sha_shape(expected_packet_sha256) and type(expected_code_commit) is str and
             re.fullmatch("[0-9a-f]{40}", expected_code_commit) is not None, "external_packet_authority")
    root = Path(project_root)
    raw = _bound_descriptor(packet_descriptor, root=root, cap=PACKET_LIMIT)
    _require(_sha(raw) == expected_packet_sha256, "external_packet_hash")
    packet = _json(raw, PACKET_LIMIT)
    _require(packet.get("code_commit") == expected_code_commit and packet.get("project_root") == str(root), "external_commit_root")
    rebuilt = build_packet_v1(project_root=root, review=packet.get("code_review"),
        physical_plan_descriptor=packet.get("physical_plan"), code=packet.get("code"), evidence=packet.get("evidence"),
        p0_descriptor=packet.get("p0"),
        boot_id=packet.get("boot_id"), initial_charged_bytes=packet.get("initial_charged_bytes"),
        initial_measurement=packet.get("initial_measurement"))
    _require(packet == rebuilt, "packet_content_drift")
    return packet


def capture_guard_v1(kind, *, output_dir, absolute_deadline_ns, stdout_limit=None, stderr_limit=4096, record_original=True):
    """Capture one of three fixed read-only commands, with one absolute budget.

    The final 200 ms are reserved for at most one TERM and one KILL. Any forced
    closure/overflow is a refusal. No communicate()/unbounded pipe is used.
    """
    recipes = {
        "dmesg": (["/usr/bin/dmesg", "--color=never"], 192 * 1024),
        "journal": (["/usr/bin/journalctl", "--disk-usage"], 512),
        "gpu": (["/usr/lib/wsl/lib/nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"], 4096),
    }
    _require(kind in recipes, "guard_kind")
    argv, maximum = recipes[kind]
    stdout_limit = maximum if stdout_limit is None else stdout_limit
    _require(type(stdout_limit) is int and 0 < stdout_limit <= maximum and
             type(stderr_limit) is int and 0 <= stderr_limit <= 4096 and type(record_original) is bool, "guard_capture_bound")
    output = Path(output_dir)
    _require(output.is_absolute() and output.resolve(strict=True) == output and output.is_dir(), "guard_output")
    start = time.monotonic_ns()
    _require(type(absolute_deadline_ns) is int and absolute_deadline_ns - start > 300_000_000, "guard_deadline")
    work_end, term_end = absolute_deadline_ns - 200_000_000, absolute_deadline_ns - 100_000_000
    facts = {"argv": argv, "pid": None, "returncode": None, "stdout_eof": False, "stderr_eof": False,
             "persisted": False, "closed": False, "forced": False, "causes": [], "stdout": None, "stderr": None, "files": {}}
    streams, files, kept, observed, digests = {}, {}, {}, {}, {}
    process = None
    def fail(cause):
        if cause not in facts["causes"]:
            facts["causes"].append(cause)
    def within_deadline():
        if time.monotonic_ns() >= absolute_deadline_ns:
            fail("guard_deadline")
            return False
        return True
    try:
        for name in ("stdout", "stderr"):
            _require(within_deadline(), "guard_deadline")
            files[name] = (output / (kind + "." + name + ".original")).open("xb", buffering=0)
            kept[name], observed[name], digests[name] = 0, 0, hashlib.sha256()
            facts["files"][name] = {"open_completed": True, "write_failed": False, "write_extent_unknown": False,
                "written_bytes": 0, "persisted_bytes": 0, "flush_completed": False, "fsync_completed": False, "close_completed": False}
        _require(within_deadline(), "guard_deadline")
        process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            start_new_session=True, close_fds=True, bufsize=0, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "LANG": "C"})
        facts["pid"] = process.pid
        _require(type(process.pid) is int and process.pid > 1, "guard_pid")
        for name in ("stdout", "stderr"):
            streams[name] = getattr(process, name)
            os.set_blocking(streams[name].fileno(), False)
        active = dict(streams)
        while active:
            now = time.monotonic_ns()
            if now >= work_end:
                fail("guard_deadline")
                break
            ready, _, _ = select.select(list(active.values()), [], [], min(.02, (work_end - now) / 1e9))
            for name, stream in list(active.items()):
                if stream not in ready:
                    continue
                cap = stdout_limit if name == "stdout" else stderr_limit
                try:
                    raw = stream.read(min(65536, cap - kept[name] + 1))
                except BlockingIOError:
                    continue
                _require(type(raw) is bytes, "guard_read_contract")
                if not raw:
                    facts[name + "_eof"] = True
                    del active[name]
                    continue
                observed[name] += len(raw)
                prefix = raw[:cap - kept[name]]
                _require(within_deadline(), "guard_deadline")
                try:
                    written = files[name].write(prefix)
                except (OSError, ValueError):
                    facts[name + "_write_extent_unknown"] = True
                    facts["files"][name].update(write_failed=True, write_extent_unknown=True)
                    fail("guard_" + name + "_write")
                    raise
                if type(written) is not int or not 0 <= written <= len(prefix):
                    facts[name + "_write_extent_unknown"] = True
                    facts["files"][name].update(write_failed=True, write_extent_unknown=True)
                    raise Gate2Refusal("guard_write_contract")
                digests[name].update(prefix[:written])
                kept[name] += written
                facts["files"][name]["written_bytes"] = kept[name]
                if written != len(prefix):
                    facts["files"][name]["write_failed"] = True
                    fail("guard_" + name + "_short_write")
                _require(written == len(prefix), "guard_short_write")
                if len(raw) > len(prefix):
                    fail("guard_" + name + "_overflow")
            if facts["causes"]:
                break
        if not facts["causes"] and process.poll() is None and time.monotonic_ns() < work_end:
            try:
                process.wait(timeout=max(0, work_end - time.monotonic_ns()) / 1e9)
            except subprocess.TimeoutExpired:
                fail("guard_deadline")
    except (OSError, ValueError, TypeError, Gate2Refusal) as error:
        fail(error.cause if isinstance(error, Gate2Refusal) else "guard_" + type(error).__name__)
    finally:
        if process is not None:
            for label, until in (("TERM", term_end), ("KILL", absolute_deadline_ns)):
                try:
                    if process.poll() is not None:
                        break
                    facts["forced"] = True
                    fail("guard_forced")
                    if time.monotonic_ns() >= until:
                        fail("guard_closure_unknown")
                        continue
                    facts[label.lower() + "_attempted"] = True
                    try:
                        os.killpg(process.pid, signal.SIGTERM if label == "TERM" else signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    try:
                        process.wait(timeout=max(0, until - time.monotonic_ns()) / 1e9)
                    except subprocess.TimeoutExpired:
                        pass
                except (OSError, ValueError):
                    fail("guard_containment_unknown")
            facts["returncode"] = process.poll()
            if type(facts["returncode"]) is not int:
                fail("guard_closure_unknown")
            elif facts["returncode"] != 0:
                fail("guard_status")
        pipe_closed = True
        for stream in streams.values():
            try:
                stream.close()
            except OSError:
                pipe_closed = False
                fail("guard_pipe_close")
        persisted, closed = True, pipe_closed
        for name, file in files.items():
            row = facts["files"][name]
            if within_deadline():
                try:
                    file.flush()
                    row["flush_completed"] = True
                except OSError:
                    fail("guard_" + name + "_flush")
            if within_deadline():
                try:
                    os.fsync(file.fileno())
                    row["fsync_completed"] = True
                except OSError:
                    fail("guard_" + name + "_fsync")
            try:
                file.close()
                row["close_completed"] = True
            except OSError:
                closed = False
                fail("guard_" + name + "_close")
            unknown = facts.get(name + "_write_extent_unknown", False)
            facts[name + "_observed_bytes"] = observed[name]
            facts[name + "_confirmed_prefix_sha256"] = digests[name].hexdigest()
            facts[name] = {"path": str(output / (kind + "." + name + ".original")),
                           "size_bytes": None if unknown else kept[name], "sha256": None if unknown else digests[name].hexdigest()}
            file_persisted = not row["write_failed"] and row["flush_completed"] and row["fsync_completed"] and not unknown
            if file_persisted:
                row["persisted_bytes"] = kept[name]
            persisted = persisted and file_persisted
        facts["persisted"], facts["closed"] = persisted, closed
        if within_deadline():
            try:
                compiler._compiler_directory_sync_v1(output)
            except OSError:
                facts["persisted"] = False
                fail("guard_directory_sync")
        else:
            facts["persisted"] = False
    if not facts["stdout_eof"] or not facts["stderr_eof"]:
        fail("guard_eof_unknown")
    if time.monotonic_ns() >= absolute_deadline_ns:
        fail("guard_deadline")
    if record_original:
        try:
            write_record_v1(output / (kind + ".capture.original.json"), facts, cap=8192, absolute_deadline_ns=absolute_deadline_ns)
        except (Gate2Refusal, OSError, ValueError) as error:
            fail("guard_record_incomplete")
            facts["record_failure"] = getattr(error, "facts", {})
            raise Gate2Refusal("guard_record_incomplete", facts)
    if facts["causes"]:
        raise Gate2Refusal("guard_refused", facts)
    return facts


def observe_identity_v1(*, output_dir, expected_cids, absolute_deadline_ns, rpc_timeout_ns=1_000_000_000):
    """Exactly four read-only GETs; never create, start, signal or reconcile."""
    _require(type(expected_cids) is list and 3 <= len(expected_cids) <= 9 and
             len(set(expected_cids)) == len(expected_cids) and all(type(cid) is str and
             re.fullmatch("[0-9a-f]{64}", cid) for cid in expected_cids) and set(B_CIDS) <= set(expected_cids), "guard_expected_cids")
    _require(type(rpc_timeout_ns) is int and 0 < rpc_timeout_ns <= 5_000_000_000, "guard_rpc_deadline")
    client = compiler._DockerClientV1(Path(output_dir), absolute_deadline_ns)
    client.RPC_LIMIT = 4
    def get(path):
        now = time.monotonic_ns()
        _require(now < absolute_deadline_ns, "guard_deadline")
        return client.request("GET", path, deadline_ns=min(absolute_deadline_ns, now + rpc_timeout_ns))
    version, info = get("/version"), get("/info")
    image = get("/images/" + compiler.PROVIDER_ID + "/json?manifests=1")
    containers = get("/containers/json?all=1")
    _require(all(type(value) is dict for value in (version, info, image)) and type(containers) is list, "guard_api_shape")
    config = image.get("Config") or {}
    environment = config.get("Env")
    _require(type(environment) is list and all(type(v) is str and "=" in v for v in environment), "guard_environment")
    keys = sorted(value.split("=", 1)[0] for value in environment)
    amd64 = [row for row in (image.get("Manifests") or []) if type(row) is dict and row.get("ID") == compiler.PROVIDER_PLATFORM_MANIFEST]
    identity = {"engine_id": info.get("ID"), "server_version": version.get("Version"),
                "kernel": info.get("KernelVersion"), "driver": info.get("Driver"), "cgroup_driver": info.get("CgroupDriver"),
                "security_options": info.get("SecurityOptions"), "runtimes_sha256": _sha(component.canonical_json_v1(info.get("Runtimes"))),
                "provider_size": image.get("Size"), "rootfs_sha256": _sha(component.canonical_json_v1(image.get("RootFS"))),
                "env_keys_sha256": _sha(component.canonical_json_v1(keys)),
                "platform_manifest": amd64[0].get("ID") if len(amd64) == 1 else None,
                "unpacked_bytes": (((amd64[0].get("ImageData") or {}).get("Size") or {}).get("Unpacked"))
                    if len(amd64) == 1 and amd64[0].get("Available") is True else None}
    _require(identity == EXPECTED and info.get("DockerRootDir") == "/var/lib/docker" and info.get("CgroupVersion") == "2" and
             image.get("Id") == compiler.PROVIDER_ID and image.get("RepoDigests") == [compiler.PROVIDER] and
             config.get("Volumes") in (None, {}) and len(set(keys)) == len(keys), "guard_identity_drift")
    try:
        _require(tuple(map(int, version["MinAPIVersion"].split("."))) <= (1, 55) <= tuple(map(int, version["ApiVersion"].split("."))), "guard_api_version")
    except (KeyError, TypeError, ValueError) as error:
        raise Gate2Refusal("guard_api_version") from error
    _require(len(containers) == len(expected_cids) and all(type(row) is dict and row.get("State") == "exited" for row in containers)
             and {row.get("Id") for row in containers} == set(expected_cids), "guard_container_set")
    return {"version": version, "info": info, "image": image, "containers": containers,
            "rpc": _rpc_json_facts_v1(client.facts), "identity": identity}


@contextmanager
def c6_export_fault_v1(output):
    """The sole C6 seam: one first-write exception at the exact retained ELF."""
    output = Path(output)
    original = compiler._export_member_open
    seen = [False]
    class FirstWriteFault:
        def __init__(self, file):
            self.file = file
        def write(self, data):
            _require(not seen[0], "c6_multiple_writes")
            seen[0] = True
            raise OSError("labelled synthetic C6 first ELF write fault")
        def __getattr__(self, name):
            return getattr(self.file, name)
        def __enter__(self):
            return self
        def __exit__(self, *details):
            return self.file.__exit__(*details)
    def opener(path):
        file = original(path)
        return FirstWriteFault(file) if Path(path) == output / "engine.unaccepted" else file
    compiler._export_member_open = opener
    try:
        yield
    finally:
        compiler._export_member_open = original


def kernel_delta_v1(stage, before, after, compiler_stderr):
    """Operational C3 attribution; this is not direct as-PID cgroup sampling."""
    if not all(type(raw) is bytes and len(raw) <= 192 * 1024 for raw in (before, after)) or not after.startswith(before):
        return {"passed": False, "delta_sha256": None, "direct_pid_cgroup_observation": False}
    delta = after[len(before):]
    if stage != "C3":
        return {"passed": not delta, "delta_sha256": _sha(delta), "direct_pid_cgroup_observation": False}
    try:
        lines = [re.sub(r"^\[\s*[0-9.]+\]\s*", "", line) for line in delta.decode("ascii").splitlines()]
        banners = [line for line in lines if re.fullmatch(r"(?:[^\s:]+/)?as(?:: as)?: potentially unexpected fatal signal 25\.", line)]
        cpu = [line for line in lines if re.fullmatch(r"CPU: [0-9]+ PID: [0-9]+ Comm: as +Not tainted 6\.6\.87\.2-microsoft-standard-WSL2 #1", line)]
        core = [line for line in lines if re.fullmatch(r"Process [0-9]+\(as\) has RLIMIT_CORE set to 1", line)]
        audit = [line for line in lines if re.fullmatch(r'audit: type=1701 audit\([0-9.:]+\): .*\buid=1000\b.*\bgid=1000\b.*\bcomm="as" .*\bsig=25\b.*', line)]
        def allowed(line):
            if line in banners + cpu + core or line == "Aborting core":
                return True
            if re.fullmatch(r"(?:RIP|RSP|RAX|RDX|RBP|R10|R13|FS): [0-9A-Fa-fx: ]+(?:[A-Z_0-9]+: [0-9A-Fa-fx: ]+)*", line):
                return True
            if re.fullmatch(r"Code: (?:[0-9a-fA-F<> ]+|Unable to access opcode bytes at 0x[0-9a-fA-F]+\.)", line):
                return True
            return line in audit
        host_pid = int(re.search(r"\bPID: ([0-9]+)\b", cpu[0])[1]) if len(cpu) == 1 else 0
        namespace_pid = int(re.search(r"^Process ([0-9]+)\(", core[0])[1]) if len(core) == 1 else 0
        audit_pids = re.findall(r"\bpid=([0-9]+)\b", audit[0]) if len(audit) == 1 else []
        # The immutable B2 original has host CPU PID1120 and namespace core
        # PID12 (and host1126/core18). A CPU/core equality check is wrong.
        # Audit pid, when present, is host-native and MUST match CPU PID.
        audit_bound = not audit or len(audit) == 1 and len(audit_pids) == 1 and int(audit_pids[0]) == host_pid
        passed = (len(banners) == len(cpu) == len(core) == 1 and lines.count("Aborting core") == 1 and
                  host_pid > 0 and namespace_pid > 0 and audit_bound and
                  b"File size limit exceeded" in compiler_stderr and all(allowed(line) for line in lines))
    except (UnicodeError, TypeError):
        passed = False
    return {"passed": passed, "delta_sha256": _sha(delta), "direct_pid_cgroup_observation": False}


def _measure_v1():
    c = os.statvfs("/mnt/c")
    ext4 = os.statvfs("/")
    return {"c_free_bytes": c.f_bavail * c.f_frsize,
            "ext4_used_bytes": (ext4.f_blocks - ext4.f_bfree) * ext4.f_frsize}


def _allocated_v1(root):
    total, count = 0, 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            count += 1
            _require(count <= 1024, "retained_entry_bound")
            row = os.lstat(Path(directory) / name)
            _require(not stat.S_ISLNK(row.st_mode), "retained_symlink")
            total += row.st_blocks * 512
    return total + os.lstat(root).st_blocks * 512


def _allocation_summary_v1(root):
    """All forms: charge payloads and every control outside controls/ too."""
    root = Path(root)
    payloads = {"engine.c", "engine.compiler-originals/compiler.stdout.original",
                "engine.compiler-originals/compiler.stderr.original", "engine.compiler-originals/engine.unaccepted"}
    paths = [root]
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            _require(len(paths) < 1024, "retained_entry_bound")
            paths.append(Path(directory) / name)
    data, control = 0, 0
    for path in paths:
        info = path.lstat()
        _require(not stat.S_ISLNK(info.st_mode), "retained_symlink")
        allocated = info.st_blocks * 512
        data += allocated
        if path == root or path.relative_to(root).as_posix() not in payloads:
            control += allocated
    # One entire allocation unit per inode is a conservative metadata quote;
    # actual ext4/C-free deltas remain independently binding.
    return {"data_bytes": data, "control_data_bytes": control, "entries": len(paths),
            "metadata_upper_bytes": len(paths) * 4096}


def _crash_listing_v1(path, deadline):
    rows = []
    with os.scandir(CRASH_DIRECTORY) as entries:
        for index, entry in enumerate(entries):
            _require(index < 16384 and time.monotonic_ns() < deadline, "crash_listing_bound")
            if not entry.name.startswith("wsl-crash-"):
                continue
            info = entry.stat(follow_symlinks=False)
            _require(stat.S_ISREG(info.st_mode), "crash_listing_kind")
            rows.append([entry.name, info.st_size, info.st_mtime_ns])
            _require(len(rows) <= 128, "crash_listing_bound")
    return write_record_v1(path, sorted(rows), cap=16384, absolute_deadline_ns=deadline)


def _guard_snapshot_v1(output, deadline, *, gpu):
    output.mkdir(mode=0o700)
    result = {"boot_id": compiler._compiler_proc_read_v1("/proc/sys/kernel/random/boot_id", 64).decode("ascii").strip(),
              "measure": _measure_v1(), "crashes": _crash_listing_v1(output / "crashes.original.json", deadline)}
    for kind in ("dmesg", "journal", "gpu") if gpu else ("dmesg", "journal"):
        directory = output / kind
        directory.mkdir(mode=0o700)
        result[kind] = capture_guard_v1(kind, output_dir=directory, absolute_deadline_ns=deadline)
    if gpu:
        _require(_bound_descriptor(result["gpu"]["stdout"], cap=4096).strip() == b"", "gpu_busy")
    return result


def _http_json_v1(raw):
    """Re-evaluate a retained ordinary reply; no sockets or permissive fallback."""
    _require(type(raw) is bytes and len(raw) <= 262144, "inspect_http_bound")
    head, separator, body = raw.partition(b"\r\n\r\n")
    _require(separator and len(head) <= 8192, "inspect_http_header")
    lines, fields = head.split(b"\r\n"), {}
    _require(re.fullmatch(rb"HTTP/1\.[01] 200 [\x20-\x7e]*", lines[0]) is not None, "inspect_http_status")
    for line in lines[1:]:
        name, colon, value = line.partition(b":")
        name = name.lower()
        _require(colon and name not in fields, "inspect_http_header")
        fields[name] = value.strip()
    _require(b"content-encoding" not in fields and not (b"content-length" in fields and b"transfer-encoding" in fields), "inspect_http_header")
    if fields.get(b"transfer-encoding") == b"chunked":
        decoded = bytearray()
        while True:
            length, separator, body = body.partition(b"\r\n")
            _require(separator and re.fullmatch(rb"[0-9A-Fa-f]{1,16}", length), "inspect_http_chunk")
            size = int(length, 16)
            if size == 0:
                _require(body == b"\r\n", "inspect_http_chunk")
                break
            _require(size <= 262144 - len(decoded) and len(body) >= size + 2 and body[size:size + 2] == b"\r\n", "inspect_http_chunk")
            decoded.extend(body[:size])
            body = body[size + 2:]
        body = bytes(decoded)
    else:
        length = fields.get(b"content-length", b"")
        _require(re.fullmatch(rb"[0-9]{1,10}", length) is not None and int(length) == len(body) and
                 b"transfer-encoding" not in fields, "inspect_http_length")
    return _json(body, 262144, canonical=False)


def _post_inspect_v1(cid, output, deadline):
    output.mkdir(mode=0o700)
    client = compiler._DockerClientV1(output, deadline)
    client.RPC_LIMIT = 1
    actual = client.request("GET", "/containers/" + cid + "/json?size=1", deadline_ns=min(deadline, time.monotonic_ns() + 5_000_000_000))
    raw = _read(output / "RPC01.reply.original", 262144)
    _require(actual == _http_json_v1(raw), "inspect_original_binding")
    return {"value": actual, "request": _descriptor(output / "RPC01.request.original", _read(output / "RPC01.request.original", 8192)),
            "reply": _descriptor(output / "RPC01.reply.original", raw), "rpc": _rpc_json_facts_v1(client.facts)}


def _load_observations_v1(root, stage, original):
    output = root / "outputs" / stage
    owner = _json(_bound_descriptor(original["owner"], root=output, cap=RECORD_LIMIT))
    retained = output / "engine.compiler-originals"
    header = _bound_descriptor(original["header"], root=retained, cap=65536)
    actual = {name: _bound_descriptor(desc, root=retained, cap=16777216 if name == "elf" else 1048576)
              for name, desc in original["members"].items()}
    receipt = _json(_bound_descriptor(original["receipt"], root=retained, cap=8192))
    inspect = original["inspect"]
    reply = _bound_descriptor(inspect["reply"], root=output, cap=262144)
    request = _bound_descriptor(inspect["request"], root=output, cap=8192)
    _require(request.startswith(("GET /v1.55/containers/" + owner["cid"] + "/json?size=1 HTTP/1.1\r\n").encode("ascii")), "inspect_request_binding")
    final = _http_json_v1(reply)
    _require(final == inspect["value"], "inspect_value_drift")
    signals, wait_replies, rpc_raws = [], [], {}
    _require(type(owner.get("rpc")) is dict and type(owner["rpc"].get("attempts")) is int, "rpc_original_inventory")
    expected_files = {"RPC%02d.%s.original" % (number, role) for number in range(1, owner["rpc"]["attempts"] + 1)
                      for role in ("request", "reply")}
    _require(set(original["owner_rpc_originals"]) == expected_files, "rpc_original_inventory")
    for name, desc in original["owner_rpc_originals"].items():
        raw = _bound_descriptor(desc, root=retained, cap=262144)
        rpc_raws[name] = raw
        if name.endswith("request.original") and b"/kill?" in raw.split(b"\r\n", 1)[0]:
            signals.append(raw.split(b"\r\n", 1)[0].decode("ascii"))
    for number in range(1, owner["rpc"]["attempts"] + 1):
        request = rpc_raws["RPC%02d.request.original" % number].split(b"\r\n", 1)[0]
        if request == ("POST /v1.55/containers/" + owner["cid"] + "/wait?condition=not-running HTTP/1.1").encode("ascii"):
            wait_replies.append(_http_json_v1(rpc_raws["RPC%02d.reply.original" % number]))
    before, after = original["before"], original["after"]
    kernel = kernel_delta_v1(stage, _bound_descriptor(before["dmesg"]["stdout"], root=output, cap=192 * 1024),
                            _bound_descriptor(after["dmesg"]["stdout"], root=output, cap=192 * 1024), actual["stderr"])
    _require(kernel == original["kernel"] and kernel["passed"], "kernel_delta")
    _require(_bound_descriptor(before["crashes"], root=output, cap=16384) ==
             _bound_descriptor(after["crashes"], root=output, cap=16384), "crash_listing_drift")
    _require(before["boot_id"] == after["boot_id"] == original["boot_id"], "boot_drift")
    return owner, {"header_original": header, "members": actual, "final_inspect": final,
                   "owner_call_elapsed_ns": original["owner_call_elapsed_ns"],
                   "published_exists": os.path.lexists(output / "engine"), "boot_id": original["boot_id"],
                   "mounts_sha256": MOUNTS_SHA256, "owner_receipt": receipt,
                   "owner_signal_requests": signals, "wait_replies": wait_replies,
                   "c3_sigxfsz_attributable": kernel["passed"]}


def _invocation_record_v1(stage, commit, packet_sha, result_sha, accounting_sha, previous_completion_sha):
    return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_invocation_v1", "stage": stage,
            "code_commit": commit, "packet_sha256": packet_sha, "result_sha256": result_sha,
            "accounting_sha256": accounting_sha, "previous_completion_sha256": previous_completion_sha,
            "returned_successfully": True}


def complete_c_invocation_v1(stage, *, project_root, returned_result, expected_packet_sha256, expected_code_commit):
    """Trusted caller only, immediately after run_c_v1 actually returns.

    This writes no authority. Independent review must verify the actual native
    return/status/EOF AND this helper's completed write/close before supplying
    its descriptor in completion_authorities. Leftover bytes cannot substitute
    for either review. The caller has only the original stage deadline.
    """
    _require(stage in STAGES and os.getuid() == os.getgid() == os.geteuid() == os.getegid() == 1000, "completion_actor_stage")
    _require(type(returned_result) is dict and compiler._json_bound(returned_result) <= 65536 and
             _sha_shape(expected_packet_sha256) and type(expected_code_commit) is str and
             re.fullmatch("[0-9a-f]{40}", expected_code_commit), "completion_input")
    root = Path(project_root)
    _require(root.is_absolute() and root.resolve(strict=True) == root and root.stat().st_dev == Path("/").stat().st_dev and
             os.statvfs(root).f_frsize == 4096, "completion_root_backing")
    output = root / "outputs" / stage
    persisted, measurements = None, []
    try:
        result_path = output / "run.result.original.json"
        result_raw = _read(result_path, 65536)
        result = _json(result_raw, 65536)
        _require(set(returned_result) == set(result) | {"accounting", "ledger_after", "final_measurement", "tail_growth_bytes"} and
                 all(returned_result[key] == value for key, value in result.items()) and result.get("stage") == stage and
                 result.get("passed") is True and result.get("accounting_pending") is True and
                 result.get("packet_sha256") == expected_packet_sha256 and result.get("code_commit") == expected_code_commit,
                 "completion_return_binding")
        deadline = result.get("completion_deadline_ns")
        _require(type(deadline) is int and time.monotonic_ns() < deadline, "completion_deadline")
        footer_path = output / "run.accounting.original.json"
        footer_raw = _bound_descriptor(returned_result["accounting"], root=output, cap=8192)
        _require(returned_result["accounting"]["path"] == str(footer_path), "completion_accounting_path")
        footer = _json(footer_raw, 8192)
        _require(footer.get("comparison_complete") is True and footer.get("stage") == stage and
                 footer.get("packet_sha256") == expected_packet_sha256 and footer.get("result") == _descriptor(result_path, result_raw) and
                 footer.get("previous_sha256") == result.get("previous_sha256") and
                 footer.get("ledger_after") == returned_result["ledger_after"] and
                 footer.get("tail_reserved_bytes") == RECORD_LIMIT, "completion_accounting_binding")
        def budget(*, prospective):
            _require(time.monotonic_ns() < deadline, "completion_deadline")
            measure = _measure_v1()
            measurements.append(measure)
            retained = _allocation_summary_v1(output)
            prefix = footer["retained_data_bytes"] + footer["retained_metadata_upper_bytes"]
            tail_retained = max(0, retained["data_bytes"] + retained["metadata_upper_bytes"] - prefix)
            tail_growth = interval_charge_v1(footer["interval_after_measurement"], measure, retained_bytes=tail_retained)
            # Fixed future record <=8KiB, rounding/inode/directory growth and
            # one permitted copy, plus a still-reserved small failure/control
            # form. Both were funded before C under the existing 512KiB tail.
            future = (32768 if prospective else 0) + 32768
            _require(tail_growth + tail_retained + future <= RECORD_LIMIT, "completion_tail_bound")
            _require(2 * (retained["data_bytes"] + retained["metadata_upper_bytes"]) + future <= C_LIMIT and
                     2 * (retained["control_data_bytes"] + retained["metadata_upper_bytes"]) + future <= CONTROL_LIMIT,
                     "completion_retained_cap")
            reserve_v1(charged=footer["ledger_after"], liability=2097152, c_free_bytes=measure["c_free_bytes"])
            _require(time.monotonic_ns() < deadline, "completion_deadline")
        budget(prospective=True)
        record = _invocation_record_v1(stage, expected_code_commit, expected_packet_sha256,
            _sha(result_raw), _sha(footer_raw), result["previous_completion_sha256"])
        persisted = write_record_v1(output / "outer.invocation.original.json", record, cap=8192,
                                    absolute_deadline_ns=deadline, return_facts=True)
        budget(prospective=False)
        return dict(persisted, completion_deadline_ns=deadline, external_approval=False)
    except (Gate2Refusal, OSError, ValueError, TypeError, KeyError) as error:
        raise Gate2Refusal("c_completion_stopped", {"stage": stage, "cause": getattr(error, "cause", type(error).__name__),
            "failure_facts": getattr(error, "facts", {}), "returned_result": returned_result, "measurements": measurements,
            "write_facts": None if persisted is None else persisted["write_facts"],
            "descriptor": None if persisted is None else persisted["descriptor"], "external_approval": False}) from error


def _previous_v1(root, packet, packet_sha, count, completion_authorities):
    _require(type(packet.get("initial_charged_bytes")) is int, "packet_ledger")
    _require(type(completion_authorities) is dict and set(completion_authorities) == set(STAGES[:count]), "completion_authority_set")
    # These descriptors are external authority inputs, like expected_packet_sha256.
    # The caller obtains them from independent actual native-return/write review;
    # discovering or hashing a leftover completion file does not authorize it.
    _require(compiler._json_bound(completion_authorities) <= 65536, "completion_authority_bound")
    authorities = {stage: dict(desc) for stage, desc in completion_authorities.items() if type(desc) is dict}
    _require(len(authorities) == count, "completion_authority_descriptor")
    previous, charged, cids, rows = None, packet["initial_charged_bytes"], list(B_CIDS), []
    previous_completion = None
    for stage in STAGES[:count]:
        path = root / "outputs" / stage / "run.result.original.json"
        try:
            _require(not os.path.lexists(path.parent / "run.refusal.original.json"), "prior_stage_refused")
            raw = _read(path, 65536)
            row = _json(raw, 65536)
            _require(row["stage"] == stage and row["passed"] is True and row["packet_sha256"] == packet_sha and
                     row["previous_sha256"] == previous and row["accounting_pending"] is True and
                     row["ledger_before"] == charged and row.get("code_commit") == packet["code_review"]["commit"] and
                     row.get("previous_completion_sha256") == previous_completion and
                     type(row.get("completion_deadline_ns")) is int and row["completion_deadline_ns"] > COMPLETION_RESERVE_NS,
                     "stage_chain")
            original = _json(_bound_descriptor(row["observations"], root=path.parent, cap=RECORD_LIMIT))
            source_path = path.parent / "engine.c"
            source = component.component_source_v1("c1" if stage == "C6" else stage.lower())
            _require(_read(source_path, component.SOURCE_LIMIT) == source and
                     row.get("source_sha256") == original.get("source_sha256") == _sha(source), "prior_source_drift")
            seed_raw = _read(path.parent / "component.seed.original.json", 4096)
            _require(seed_raw == component.canonical_json_v1(packet["seed"]) and _sha(seed_raw) == packet["seed_sha256"], "prior_seed_drift")
            admission_raw = _read(path.parent / "component.admission.original.json", 4096)
            admission = _json(admission_raw, 4096)
            expires = admission.get("expires_unix_ns")
            _require(type(expires) is int and expires >= component.ADMISSION_LIFETIME_NS, "prior_admission_time")
            expected_admission = component.component_admission_v1(project_root=root, review=packet["code_review"],
                seed_sha256=packet["seed_sha256"], bindings=packet["seed"]["bindings"],
                source_relative=str(source_path.relative_to(root)), source=source,
                executable_relative=str((path.parent / "engine").relative_to(root)),
                physical_plan_sha256=packet["physical_plan"]["sha256"], boot_id=packet["boot_id"],
                now_unix_ns=expires - component.ADMISSION_LIFETIME_NS)
            _require(admission == expected_admission, "prior_admission_drift")
            owner, observations = _load_observations_v1(root, stage, original)
            evaluated = evaluate_c_v1(stage, owner, observations)
            _require(evaluated["passed"] and evaluated == _json(_bound_descriptor(row["evaluation"], root=path.parent, cap=8192)), "prior_comparison")
            footer_path = path.parent / "run.accounting.original.json"
            footer_raw = _read(footer_path, 8192)
            footer = _json(footer_raw, 8192)
            _require(footer.get("artifact_kind") == "vast_fixture_compiler_gate2_c_accounting_v1" and
                     footer.get("comparison_complete") is True and footer.get("stage") == stage and
                     footer.get("packet_sha256") == packet_sha and footer.get("previous_sha256") == previous and
                     footer.get("result") == _descriptor(path, raw) and footer.get("ledger_before") == charged and
                     footer.get("interval_before_measurement") == original["interval_before_measurement"] and
                     footer.get("idle_gap_charged_bytes") == 0 and footer.get("tail_reserved_bytes") == RECORD_LIMIT,
                     "stage_accounting_binding")
            completion_path = path.parent / "outer.invocation.original.json"
            _require(authorities[stage].get("path") == str(completion_path), "completion_authority_path")
            completion_raw = _bound_descriptor(authorities[stage], root=path.parent, cap=8192)
            completion = _json(completion_raw, 8192)
            _require(type(completion.get("schema_version")) is int and completion.get("returned_successfully") is True and
                completion == _invocation_record_v1(stage, packet["code_review"]["commit"], packet_sha,
                _sha(raw), _sha(footer_raw), previous_completion), "completion_authority_binding")
            actual = _allocation_summary_v1(path.parent)
            footer_allocated = footer_path.stat().st_blocks * 512
            completion_allocated = completion_path.stat().st_blocks * 512
            stage_directory_allocated = path.parent.stat().st_blocks * 512
            _require(2 * (footer_allocated + completion_allocated + stage_directory_allocated + 8192) + 32768 <= RECORD_LIMIT and
                     2 * (actual["data_bytes"] + actual["metadata_upper_bytes"]) + 32768 <= C_LIMIT and
                     2 * (actual["control_data_bytes"] + actual["metadata_upper_bytes"]) + 32768 <= CONTROL_LIMIT,
                     "prior_completion_tail_bounds")
            prefix_upper = actual["data_bytes"] - footer_allocated - completion_allocated
            prefix_lower = max(0, prefix_upper - stage_directory_allocated)
            metadata = (actual["entries"] - 2) * 4096
            control_upper = actual["control_data_bytes"] - footer_allocated - completion_allocated
            control_lower = max(0, control_upper - stage_directory_allocated)
            _require(footer.get("retained_metadata_upper_bytes") == metadata and
                     type(footer.get("retained_data_bytes")) is int and prefix_lower <= footer["retained_data_bytes"] <= prefix_upper and
                     type(footer.get("control_data_bytes")) is int and control_lower <= footer["control_data_bytes"] <= control_upper,
                     "prior_retained_accounting")
            size_rw = observations["final_inspect"].get("SizeRw")
            _require(type(size_rw) is int and 0 <= size_rw <= RUNTIME_STOP, "prior_size_rw")
            before, after = footer["interval_before_measurement"], footer["interval_after_measurement"]
            minimum_charge = interval_charge_v1(before, after, retained_bytes=prefix_lower + metadata,
                size_rw=size_rw) + prefix_lower + metadata + RECORD_LIMIT
            maximum_charge = interval_charge_v1(before, after, retained_bytes=prefix_upper + metadata,
                size_rw=size_rw) + prefix_upper + metadata + RECORD_LIMIT
            gross = interval_charge_v1(before, after, retained_bytes=0)
            nonoutput_lower, nonoutput_upper = max(0, gross - prefix_upper), max(0, gross - prefix_lower)
            _require(footer.get("future_copy_upper_bytes") == footer["retained_data_bytes"] + metadata and
                     footer.get("retained_all_forms_upper_bytes") == 2 * (footer["retained_data_bytes"] + metadata) + RECORD_LIMIT <= C_LIMIT and
                     footer.get("control_all_forms_upper_bytes") == 2 * (footer["control_data_bytes"] + metadata) + RECORD_LIMIT <= CONTROL_LIMIT,
                     "prior_retained_bounds")
            _require(type(footer.get("nonoutput_growth_bytes")) is int and
                     nonoutput_lower <= footer["nonoutput_growth_bytes"] <= min(RUNTIME_STOP, nonoutput_upper), "prior_nonoutput_growth")
            _require(type(footer["charge_bytes"]) is int and minimum_charge <= footer["charge_bytes"] <= maximum_charge and
                     footer["ledger_after"] == charged + footer["charge_bytes"] <= SEAL_BYTES and owner["cid"] not in cids, "stage_ledger")
        except (OSError, KeyError, TypeError, ValueError) as error:
            raise Gate2Refusal("prior_stage_incomplete") from error
        previous, charged = _sha(footer_raw), footer["ledger_after"]
        previous_completion = _sha(completion_raw)
        cids.append(owner["cid"])
        rows.append((row, original, observations, footer))
    return previous, charged, cids, rows, previous_completion


def validated_c1_binding_v1(*, project_root, packet_descriptor, expected_packet_sha256, expected_code_commit, completion_authorities):
    """D's only ELF authority: actual C1 plus all six successful C comparisons."""
    root = Path(project_root)
    packet = validate_packet_v1(project_root=root, packet_descriptor=packet_descriptor,
        expected_packet_sha256=expected_packet_sha256, expected_code_commit=expected_code_commit)
    _, charged, cids, rows, _ = _previous_v1(root, packet, expected_packet_sha256, 6, completion_authorities)
    _require(len(cids) == len(set(cids)) == 9 and SEAL_BYTES - charged >= 2097152, "d_chain_reserve")
    first, original, observations, _ = rows[0]
    raw = observations["members"]["elf"]
    _require(_native_elf(raw) and original["source_sha256"] == component.SOURCE_SHA256["c1"], "d_c1_binding")
    return {"elf_path": str(root / "outputs/C1/engine.compiler-originals/engine.unaccepted"),
            "elf_size_bytes": len(raw), "elf_sha256": _sha(raw), "source_sha256": component.SOURCE_SHA256["c1"],
            "receipt_sha256": original["owner"]["sha256"], "all_cids": cids, "remaining_seal_bytes": SEAL_BYTES - charged,
            "last_after_measurement": rows[-1][3]["interval_after_measurement"], "last_tail_credit_bytes": 0}


def run_c_v1(stage, *, project_root, packet_descriptor, expected_packet_sha256, expected_code_commit, completion_authorities):
    """Run exactly one fresh C stage. Any mismatch permanently stops this path.

    This entry point is physical work and is called only after implemented-code
    approval and the separate actual packet/evidence approval. Tests replace its
    effect boundaries; no test result is a physical acceptance.
    """
    _require(stage in STAGES and os.getuid() == os.getgid() == os.geteuid() == os.getegid() == 1000, "c_actor_stage")
    root = Path(project_root)
    _require(root.is_absolute() and root.resolve(strict=True) == root and root.is_dir() and
             root.stat().st_dev == Path("/").stat().st_dev and os.statvfs(root).f_frsize == 4096, "c_root_backing")
    started = time.monotonic_ns()
    completion_deadline = started + RUN_NS
    # The trusted caller's enclosing completion write shares the original
    # 150s deadline. Reserve its final second before any physical operation.
    deadline = completion_deadline - COMPLETION_RESERVE_NS
    # The approved ledger covers bounded operations. Arbitrary idle planning
    # periods between them are outside this interval; prior charges and fully
    # funded tails remain cumulative and never credit new unrelated growth.
    interval_before = _measure_v1()
    packet = validate_packet_v1(project_root=root, packet_descriptor=packet_descriptor,
        expected_packet_sha256=expected_packet_sha256, expected_code_commit=expected_code_commit)
    number = STAGES.index(stage)
    previous, charged, cids, prior_rows, previous_completion = _previous_v1(root, packet, expected_packet_sha256, number, completion_authorities)
    _require(all(not os.path.lexists(root / "outputs" / later) for later in STAGES[number:]), "c_stage_already_attempted")
    reserve_v1(charged=charged, liability=C_LIMIT + 4194304 + 2097152,
               c_free_bytes=interval_before["c_free_bytes"])
    _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
    outputs = root / "outputs"
    if not outputs.exists():
        outputs.mkdir(mode=0o700)
    _require(outputs.resolve(strict=True) == outputs and outputs.is_dir(), "c_outputs")
    output = outputs / stage
    output.mkdir(mode=0o700)
    controls = output / "controls"
    controls.mkdir(mode=0o700)
    owner = None
    try:
        before = _guard_snapshot_v1(controls / "before", min(started + 5_000_000_000, deadline), gpu=True)
        _require(before["boot_id"] == packet["boot_id"], "c_boot_drift")
        if prior_rows:
            prior_dmesg = prior_rows[-1][1]["after"]["dmesg"]["stdout"]
            _require(_bound_descriptor(prior_dmesg, cap=192 * 1024) ==
                     _bound_descriptor(before["dmesg"]["stdout"], cap=192 * 1024), "interstage_kernel_drift")
        reserve_v1(charged=charged, liability=C_LIMIT + 4194304 + 2097152,
                   c_free_bytes=before["measure"]["c_free_bytes"])
        identity_dir = controls / "identity"
        identity_dir.mkdir(mode=0o700)
        identity = observe_identity_v1(output_dir=identity_dir, expected_cids=cids,
                                        absolute_deadline_ns=min(started + 10_000_000_000, deadline))
        write_record_v1(controls / "identity.original.json", identity, cap=RECORD_LIMIT, absolute_deadline_ns=deadline)
        source = component.component_source_v1("c1" if stage == "C6" else stage.lower())
        source_path = output / "engine.c"
        _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
        with source_path.open("xb") as file:
            _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
            _require(file.write(source) == len(source), "source_short_write")
            _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
            file.flush()
            _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
            os.fsync(file.fileno())
        _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
        seed_desc = write_record_v1(output / "component.seed.original.json", packet["seed"],
                                    cap=4096, absolute_deadline_ns=deadline)
        _require(seed_desc["sha256"] == packet["seed_sha256"], "seed_drift")
        admission = component.component_admission_v1(project_root=root, review=packet["code_review"],
            seed_sha256=seed_desc["sha256"], bindings=packet["seed"]["bindings"],
            source_relative=str(source_path.relative_to(root)), source=source,
            executable_relative=str((output / "engine").relative_to(root)),
            physical_plan_sha256=packet["physical_plan"]["sha256"], boot_id=packet["boot_id"])
        admission_desc = write_record_v1(output / "component.admission.original.json", admission,
                                         cap=4096, absolute_deadline_ns=deadline)
        retained = output / "engine.compiler-originals"
        owner_entry_ns = time.monotonic_ns()
        try:
            with c6_export_fault_v1(retained) if stage == "C6" else nullcontext():
                owner = compiler._compile_fixture_component_v1(project_root=root, source_path=source_path,
                    executable_path=output / "engine", admission=admission_desc,
                    qualification=seed_desc, absolute_deadline_ns=deadline)
        except compiler.FixtureCompilerError as error:
            _require(hasattr(error, "facts") and type(error.facts) is dict, "owner_facts_missing")
            owner = error.facts
            _require(owner.get("causes") == error.causes, "owner_exception_binding")
        owner_elapsed_ns = time.monotonic_ns() - owner_entry_ns
        owner = dict(owner)
        owner["rpc"] = _rpc_json_facts_v1(owner.get("rpc"))
        owner_desc = write_record_v1(output / "outer.owner.original.json", owner, cap=RECORD_LIMIT, absolute_deadline_ns=deadline)
        _require(type(owner.get("cid")) is str and re.fullmatch("[0-9a-f]{64}", owner["cid"]), "c_actual_cid")
        actual_inspect = _post_inspect_v1(owner["cid"], controls / "final-inspect", deadline)
        after = _guard_snapshot_v1(controls / "after", deadline, gpu=False)
        _require(after["boot_id"] == packet["boot_id"], "c_boot_drift")
        raw_header = _read(retained / "export.header.original", 65536)
        member_names = {"stdout": "compiler.stdout.original", "stderr": "compiler.stderr.original", "elf": "engine.unaccepted"}
        members = {name: _descriptor(retained / filename, _read(retained / filename,
                    16777216 if name == "elf" else 1048576)) for name, filename in member_names.items()}
        originals = {}
        for path in sorted(retained.glob("RPC*.original")):
            _require(len(originals) < 46, "owner_rpc_inventory")
            originals[path.name] = _descriptor(path, _read(path, 262144))
        _require(len(originals) == 2 * owner["rpc"]["attempts"], "owner_rpc_inventory")
        kernel = kernel_delta_v1(stage, _bound_descriptor(before["dmesg"]["stdout"], cap=192 * 1024),
                                 _bound_descriptor(after["dmesg"]["stdout"], cap=192 * 1024),
                                 _bound_descriptor(members["stderr"], cap=1048576))
        original = {"stage": stage, "owner": owner_desc, "boot_id": packet["boot_id"],
                    "interval_before_measurement": interval_before,
                    "owner_call_elapsed_ns": owner_elapsed_ns,
                    "header": _descriptor(retained / "export.header.original", raw_header), "members": members,
                    "receipt": _descriptor(retained / "owner.result.original.json", _read(retained / "owner.result.original.json", 8192)),
                    "inspect": actual_inspect, "owner_rpc_originals": originals, "before": before, "after": after,
                    "kernel": kernel, "source_sha256": _sha(source), "packet_sha256": expected_packet_sha256,
                    "c6_synthetic_only": stage == "C6", "whole_chain_authority": False}
        observations_desc = write_record_v1(output / "observations.original.json", original, cap=RECORD_LIMIT, absolute_deadline_ns=deadline)
        reloaded_owner, observations = _load_observations_v1(root, stage, original)
        comparison = evaluate_c_v1(stage, reloaded_owner, observations)
        evaluation_desc = write_record_v1(output / "evaluation.original.json", comparison, cap=8192, absolute_deadline_ns=deadline)
        validate_packet_v1(project_root=root, packet_descriptor=packet_descriptor,
            expected_packet_sha256=expected_packet_sha256, expected_code_commit=expected_code_commit)
        _require(_read(source_path, component.SOURCE_LIMIT) == source, "c_source_post_drift")
        result = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_result_v1", "stage": stage,
                  "passed": comparison["passed"], "packet_sha256": expected_packet_sha256, "previous_sha256": previous,
                  "observations": observations_desc, "evaluation": evaluation_desc, "ledger_before": charged,
                  "code_commit": expected_code_commit, "previous_completion_sha256": previous_completion,
                  "completion_deadline_ns": completion_deadline,
                  "accounting_pending": True, "source_sha256": _sha(source), "cid": owner["cid"],
                  "c6_synthetic_only": stage == "C6", "whole_chain_authority": False}
        result_desc = write_record_v1(output / "run.result.original.json", result, cap=65536, absolute_deadline_ns=deadline)
        # This measurement follows all actual work, guard captures and result
        # persistence. Only the <=8KiB footer and bounded failure/copy tail are
        # still prospective, funded within the existing 512KiB reservation.
        interval_after = _measure_v1()
        retained = _allocation_summary_v1(output)
        data, metadata, control = retained["data_bytes"], retained["metadata_upper_bytes"], retained["control_data_bytes"]
        retained_all_forms = 2 * (data + metadata) + RECORD_LIMIT
        control_all_forms = 2 * (control + metadata) + RECORD_LIMIT
        _require(retained_all_forms <= C_LIMIT and control_all_forms <= CONTROL_LIMIT, "c_retained_cap")
        size_rw = actual_inspect["value"].get("SizeRw")
        _require(type(size_rw) is int and 0 <= size_rw <= RUNTIME_STOP, "c_size_rw")
        gross = interval_charge_v1(interval_before, interval_after, retained_bytes=0)
        nonoutput = max(0, gross - data)
        _require(nonoutput <= RUNTIME_STOP, "c_runtime_growth")
        # Future Git/report copies are additive even when independent host
        # noise is the largest observed allocation delta.
        charge = interval_charge_v1(interval_before, interval_after, retained_bytes=data + metadata,
                                     size_rw=size_rw) + data + metadata + RECORD_LIMIT
        reserve_v1(charged=charged, liability=charge + 2097152, c_free_bytes=interval_after["c_free_bytes"])
        footer = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_accounting_v1",
                  "comparison_complete": comparison["passed"], "stage": stage, "packet_sha256": expected_packet_sha256,
                  "previous_sha256": previous, "result": result_desc, "ledger_before": charged,
                  "interval_before_measurement": interval_before, "interval_after_measurement": interval_after,
                  "idle_gap_charged_bytes": 0, "tail_reserved_bytes": RECORD_LIMIT,
                  "retained_data_bytes": data, "retained_metadata_upper_bytes": metadata,
                  "control_data_bytes": control, "future_copy_upper_bytes": data + metadata,
                  "retained_all_forms_upper_bytes": retained_all_forms, "control_all_forms_upper_bytes": control_all_forms,
                  "nonoutput_growth_bytes": nonoutput, "charge_bytes": charge, "ledger_after": charged + charge}
        footer_desc = write_record_v1(output / "run.accounting.original.json", footer, cap=8192, absolute_deadline_ns=deadline)
        final_measure = _measure_v1()
        # The footer's own allocation and planned copy, failure receipt and
        # their metadata remain well inside the existing tail, never a new cap.
        tail_growth = interval_charge_v1(interval_after, final_measure, retained_bytes=0)
        _require(tail_growth + 65536 <= RECORD_LIMIT, "c_final_tail_bound")
        reserve_v1(charged=charged, liability=charge + 2097152, c_free_bytes=final_measure["c_free_bytes"])
        _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
        if not comparison["passed"]:
            raise Gate2Refusal("c_comparison_deviation", result)
        return dict(result, accounting=footer_desc, ledger_after=footer["ledger_after"],
                    final_measurement=final_measure, tail_growth_bytes=tail_growth)
    except (Gate2Refusal, OSError, ValueError, TypeError, KeyError, compiler.FixtureCompilerError) as error:
        refusal = {"stage": stage, "cause": error.cause if isinstance(error, Gate2Refusal) else type(error).__name__,
                   "owner_observed": owner is not None, "whole_chain_authority": False,
                   "preserve_originals": True, "retry_authorized": False}
        budget_denied = refusal["cause"] in {"ledger_unknown", "ledger_reserve", "capacity_floor", "c_retained_cap",
            "c_runtime_growth", "c_final_tail_bound", "retained_entry_bound", "retained_symlink"}
        if not budget_denied and not os.path.lexists(output / "run.refusal.original.json") and time.monotonic_ns() < deadline:
            try:
                # A fresh failure receipt is a fresh operation. Prior floor
                # admission cannot authorize it after a reservation failure or
                # an unknown/insufficient current physical budget.
                failed_measure = _measure_v1()
                failed_retained = _allocation_summary_v1(output)
                retained_upper = failed_retained["data_bytes"] + failed_retained["metadata_upper_bytes"]
                control_upper = failed_retained["control_data_bytes"] + failed_retained["metadata_upper_bytes"]
                _require(2 * retained_upper + RECORD_LIMIT <= C_LIMIT and
                         2 * control_upper + RECORD_LIMIT <= CONTROL_LIMIT, "c_refusal_retained_cap")
                failed_charge = interval_charge_v1(interval_before, failed_measure,
                    retained_bytes=retained_upper, size_rw=RUNTIME_STOP) + retained_upper + RECORD_LIMIT
                reserve_v1(charged=charged, liability=failed_charge + 2097152,
                           c_free_bytes=failed_measure["c_free_bytes"])
                _require(time.monotonic_ns() < deadline, "c_absolute_deadline")
                write_record_v1(output / "run.refusal.original.json", refusal, cap=4096, absolute_deadline_ns=deadline)
            except (Gate2Refusal, OSError, ValueError) as write_error:
                refusal["refusal_write_failure"] = getattr(write_error, "facts", {})
        refusal["failure_facts"] = getattr(error, "facts", {})
        refusal["owner_facts"] = owner
        raise Gate2Refusal("c_stage_stopped", refusal) from error


def _native_elf(raw):
    return (len(raw) >= 64 and raw[:7] == b"\x7fELF\x02\x01\x01" and
            int.from_bytes(raw[16:18], "little") in (2, 3) and int.from_bytes(raw[18:20], "little") == 62
            and int.from_bytes(raw[20:24], "little") == 1)


def evaluate_c_v1(stage, owner, observations):
    """Pure comparison of actual originals; expected refusal never grants an ELF."""
    errors = []
    def check(ok, cause):
        if not ok and cause not in errors:
            errors.append(cause)
    try:
        _require(stage in STAGES and type(owner) is dict and type(observations) is dict, "comparison_input")
        success = stage == "C1"
        expected_causes = [] if success else ["export_OSError", "attach_incomplete"] if stage == "C6" else ["owner_wait_status"]
        check(owner.get("causes") == expected_causes, "owner_causes")
        for key, expected in (("accepted", False), ("forced", False), ("normal_closed", success),
                              ("receipt_persisted", True), ("creation_unknown", False),
                              ("start_unknown", False), ("start_attempted", True), ("signal_handlers_restored", True)):
            check(owner.get(key) is expected, "owner_" + key)
        check(owner.get("promotion") is None and observations.get("published_exists") is False, "published_executable")
        cid = owner.get("cid")
        check(type(cid) is str and re.fullmatch("[0-9a-f]{64}", cid) is not None, "cid")
        final = observations.get("final_inspect") or {}
        state = final.get("State") or {}
        check(final.get("Id") == cid and type(final.get("RestartCount")) is int and final["RestartCount"] == 0, "final_identity")
        for name in ("Running", "Restarting", "Paused", "Dead", "OOMKilled"):
            check(state.get(name) is False, "final_" + name)
        check(type(state.get("Pid")) is int and state["Pid"] == 0 and state.get("Error") == "", "final_process")
        exitcode = 0 if stage in ("C1", "C6") else 1
        check(type(state.get("ExitCode")) is int and state["ExitCode"] == exitcode, "container_status")
        waited = observations.get("wait_replies")
        check(type(waited) is list and len(waited) == 1 and type(waited[0]) is dict and
              type(waited[0].get("StatusCode")) is int and waited[0]["StatusCode"] == exitcode and
              waited[0].get("Error") in (None, {}), "wait_reply_status_error")
        closure = owner.get("closed" if success else "containment_native") or {}
        check(closure.get("closed") is True and type(closure.get("populated")) is int and
              closure["populated"] == 0 and closure.get("procs") == [] and closure.get("init_absent") is True, "native_closure")
        live = owner.get("live") or {}
        check(live.get("boot_id") == observations.get("boot_id") and
              live.get("mounts_sha256") == observations.get("mounts_sha256"), "native_binding")
        check(observations.get("owner_signal_requests") == [], "owner_signals")
        rpc = owner.get("rpc") or {}
        check(rpc.get("causes", []) == [] and rpc.get("controlled_socket") is False and rpc.get("controlled_clock") is False and
              type(rpc.get("attempts")) is int and
              1 <= rpc["attempts"] <= 23 and type(rpc.get("metadata_bytes")) is int and
              0 <= rpc["metadata_bytes"] <= 262144 and type(rpc.get("rpc")) is list and
              len(rpc["rpc"]) == rpc.get("attempts"), "owner_rpc")
        for row in rpc.get("rpc", []):
            check(row.get("causes") == [] and row.get("complete") is True and
                  all(row.get(key) is True for key in ("request_persisted", "reply_persisted", "request_send_complete",
                  "request_close_completed", "reply_close_completed", "socket_closed")) and
                  all(row.get(key) is False for key in ("request_write_extent_unknown", "reply_write_extent_unknown")), "rpc_persistence")
            peer = row.get("peer")
            check(type(peer) is dict and set(peer) == {"pid", "uid", "gid"} and
                  type(peer.get("pid")) is int and peer["pid"] > 0 and type(peer.get("uid")) is int and peer["uid"] == 0 and
                  type(peer.get("gid")) is int and peer["gid"] >= 0 and
                  row.get("epoch_before") and row.get("epoch_before") == row.get("epoch_after"), "rpc_peer_epoch")
            check(row.get("status") == 101 if row.get("upgraded") is True else
                  type(row.get("status")) is int and 200 <= row["status"] < 300 and row.get("reply_eof") is True, "rpc_status_eof")
        captured = owner.get("failed_operation" if stage == "C6" else "export") or {}
        framed = observations.get("header_original")
        _require(type(framed) is bytes and 12 < len(framed) <= 65536 and framed[:8] == b"VASTCE1\n" and
                 struct.unpack("!I", framed[8:12])[0] == len(framed) - 12, "header_frame")
        header = _json(framed[12:], 65524)
        check(header == captured.get("header") and header.get("schema_version") == 1 and
              type(header.get("schema_version")) is int and header.get("artifact_kind") == "vast_fixture_compiler_export_v1", "header_binding")
        source = component.component_source_v1("c1" if stage == "C6" else stage.lower())
        check(header.get("source") == {"size_bytes": len(source), "sha256": _sha(source)}, "source_binding")
        runtime, child = header.get("runtime") or {}, header.get("compiler") or {}
        check(type(runtime.get("pid")) is int and runtime["pid"] == 1 and
              runtime.get("core") == [1, 1] and all(type(v) is int for v in runtime["core"]) and
              runtime.get("fsize") == [16777216, 16777216] and all(type(v) is int for v in runtime["fsize"]) and
              runtime.get("interpreter_elf64_amd64") is True and runtime.get("compiler_elf64_amd64") is True, "runtime_limits_abi")
        code = 0 if stage in ("C1", "C6") else 1 if stage in ("C2", "C3") else -15
        check(type(child.get("returncode")) is int and child["returncode"] == code and
              child.get("started") is True and child.get("reaped") is True and header.get("descendants_reaped") is True, "compiler_status_reap")
        expected = [[]] if stage in ("C1", "C6") else [["compiler_exit_nonzero"]]
        if stage in ("C4", "C5"):
            trigger = "stderr_overflow" if stage == "C4" else "compiler_deadline"
            expected = [[trigger, "compiler_term_attempted", "compiler_exit_nonzero"],
                        [trigger, "compiler_term_attempted", "descendant_exit_nonzero", "compiler_exit_nonzero"]]
        check(header.get("causes") in expected, "publisher_causes")
        check(captured.get("header_close_completed") is True, "header_close")
        members = captured.get("members") or {}
        check(set(members) == {"stdout", "stderr", "elf"}, "export_member_set")
        actual = observations.get("members") or {}
        for name in ("stdout", "stderr", "elf"):
            row = members.get(name) or {}
            raw = actual.get(name)
            _require(type(raw) is bytes and len(raw) <= (16777216 if name == "elf" else 1048576), "member_bound")
            if stage == "C6" and name == "elf":
                check(row.get("size_bytes") is None and row.get("sha256") is None and
                      row.get("persisted") is False and row.get("complete") is False and
                      row.get("close_completed") is True and type(row.get("observed_bytes")) is int and
                      0 < row["observed_bytes"] <= 65536, "c6_unknown_extent")
                continue
            desc = header.get("elf") if name == "elf" else child.get(name)
            check(type(desc) is dict and type(desc.get("size_bytes")) is int and desc["size_bytes"] == len(raw) and desc.get("sha256") == _sha(raw), "member_header_" + name)
            check(type(row.get("size_bytes")) is int and row["size_bytes"] == len(raw) and row.get("sha256") == _sha(raw) and
                  type(row.get("observed_bytes")) is int and row["observed_bytes"] == len(raw) and row.get("observed_sha256") == _sha(raw) and
                  all(row.get(key) is True for key in ("complete", "persisted", "close_completed")), "member_capture_" + name)
        for name in ("stdout", "stderr"):
            row = child.get(name) or {}
            check(row.get("eof") is True and type(row.get("observed_bytes")) is int and
                  type(row.get("size_bytes")) is int and type(row.get("discarded_bytes")) is int and
                  row["observed_bytes"] == row.get("size_bytes", -1) + row["discarded_bytes"], "channel_" + name)
            check(row.get("discarded_bytes", -1) > 0 and row.get("size_bytes") == 1048576 if stage == "C4" and name == "stderr"
                  else row.get("discarded_bytes") == 0, "channel_discard_" + name)
            if stage in ("C1", "C5", "C6") or stage == "C4" and name == "stdout":
                check(row.get("size_bytes") == 0 and row.get("observed_bytes") == 0, "channel_empty_" + name)
        elf = header.get("elf") or {}
        if stage in ("C1", "C6"):
            check(elf.get("available") is True and type(elf.get("size_bytes")) is int and
                  64 <= elf["size_bytes"] <= 16777216 and _sha_shape(elf.get("sha256")), "elf_available")
            if success:
                check(_native_elf(actual["elf"]), "elf_abi")
        else:
            check(elf == {"available": False, "size_bytes": 0, "sha256": _sha(b"")}, "negative_elf")
        receipt = observations.get("owner_receipt") or {}
        check(receipt.get("export_binding") is None if stage == "C6" else receipt.get("export_binding") == {
            "header_sha256": _sha(framed[12:]), "members": members, "complete": True}, "receipt_export_binding")
        check(captured.get("complete") is False and captured.get("client_stdout_eof") is False and
              owner.get("containment_close_wait") is True if stage == "C6" else
              captured.get("complete") is True and captured.get("client_stdout_eof") is True, "capture_completion")
        if stage == "C3":
            check(observations.get("c3_sigxfsz_attributable") is True, "c3_sigxfsz")
        if stage == "C5":
            check(type(observations.get("owner_call_elapsed_ns")) is int and
                  45_000_000_000 <= observations["owner_call_elapsed_ns"] < RUN_NS, "c5_elapsed_minimum")
    except (Gate2Refusal, KeyError, TypeError, ValueError, AttributeError, OverflowError) as error:
        check(False, error.cause if isinstance(error, Gate2Refusal) else "comparison_malformed")
    return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_c_comparison_v1",
            "stage": stage, "passed": not errors, "causes": errors, "whole_chain_authority": False}
