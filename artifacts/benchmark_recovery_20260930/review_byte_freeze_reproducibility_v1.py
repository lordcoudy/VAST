"""Read-only checkout design observations; no source/index/object writes."""
import collections
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
out = root / "artifacts/benchmark_recovery_20260930"
audit_path = out / "packaging-source-rollforward.v4.json"
audit_raw = audit_path.read_bytes()
audit = json.loads(audit_raw)
pins = audit["final_actual_source_manifest"]["project_sources"]
names = [row["path"] for row in pins]
assert len(names) == len(set(names)) == 165
gitdir = "/mnt/e/" + (root / ".git").read_text("ascii").strip().removeprefix("gitdir: E:/")
git = ["git", "--git-dir=" + gitdir, "--work-tree=" + str(root)]

def command(args):
    child = subprocess.run(git + args, cwd=root, capture_output=True, check=True)
    return child.stdout

head = command(["rev-parse", "HEAD"]).decode("ascii").strip()
raw_attrs = command(["check-attr", "-z", "text", "eol", "filter", "ident", "working-tree-encoding", "--", *names])
tokens = raw_attrs.decode("utf-8").rstrip("\0").split("\0")
assert len(tokens) == len(names) * 5 * 3
attrs = {name: {} for name in names}
for offset in range(0, len(tokens), 3):
    name, key, value = tokens[offset:offset + 3]
    attrs[name][key] = value
assert all(row[key] == "unspecified" for row in attrs.values()
    for key in ("filter", "ident", "working-tree-encoding"))
epochs = {}
newline_rows = []
for pin in pins:
    path = root / pin["path"]
    assert path.resolve(strict=True) == path
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        raw = source.read()
        after = os.fstat(source.fileno())
    epoch = lambda value: (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
        value.st_size, value.st_mtime_ns, value.st_ctime_ns)
    assert epoch(before) == epoch(after) == epoch(path.lstat())
    assert len(raw) == pin["size_bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"]
    epochs[pin["path"]] = epoch(before)
    lf, crlf = raw.count(b"\n"), raw.count(b"\r\n")
    newline_rows.append({"path": pin["path"], "LF_count": lf, "CRLF_count": crlf,
        "bare_LF_count": lf - crlf, "bare_CR_count": raw.count(b"\r") - crlf,
        "NUL_count": raw.count(b"\0")})
del raw
cr_names = [row["current"]["path"] for row in audit["git_HEAD_vs_current_physical_bytes"]["tracked_CR_at_EOL_only"]]
assert len(cr_names) == 22
probes = []
for name in ["deploy/savant/canonical_distributed_module.yml", "scripts/checkpoint_savant_native_module.py", "scripts/publication_operational_request_domain_v1.py"]:
    raw_id = command(["hash-object", "--no-filters", name]).decode("ascii").strip()
    modes = {}
    for mode in ("true", "false"):
        modes[mode] = command(["-c", "core.autocrlf=" + mode, "hash-object", "--path=" + name, name]).decode("ascii").strip()
    probes.append({"path": name, "no_filters_blob_id": raw_id, "clean_blob_id_by_autocrlf": modes})
for name, before in epochs.items():
    value = (root / name).lstat()
    assert (value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
        value.st_size, value.st_mtime_ns, value.st_ctime_ns) == before
assert command(["rev-parse", "HEAD"]).decode("ascii").strip() == head

proposed = ("# REVIEW PROPOSAL ONLY: append after existing root .gitattributes rules.\n"
    "# Preserve exact bytes for the finite 165-member benchmark source inventory.\n"
    + "".join("/" + name + " -text !eol\n" for name in names)).encode("ascii")
proposal_name = "byte-freeze.proposed.gitattributes.v1.txt"
with (out / proposal_name).open("xb") as target:
    target.write(proposed)
    target.flush()
    os.fsync(target.fileno())
counts = collections.Counter((row["text"], row["eol"]) for row in attrs.values())
value = {"schema_version": 1, "artifact_kind": "vast_checkout_byte_freeze_readonly_design_observations_v1",
    "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "accepted": False, "publication_ready": False, "launch_or_publication_grant": False,
    "head": head, "source_count": 165,
    "physical_source_audit": {"path": audit_path.relative_to(root).as_posix(), "size_bytes": len(audit_raw), "sha256": hashlib.sha256(audit_raw).hexdigest()},
    "source_aggregate_sha256": audit["final_actual_source_manifest"]["aggregate_sha256"],
    "attribute_counts": [{"text": text, "eol": eol, "count": count} for (text, eol), count in sorted(counts.items())],
    "all_165_filter_ident_working_tree_encoding_unspecified": True,
    "effective_attributes": attrs,
    "current_22_raw_stage_candidates": [row for row in pins if row["path"] in cr_names],
    "raw_stage_candidate_newline_inventory": [row for row in newline_rows if row["path"] in cr_names],
    "read_only_hash_object_probes": probes,
    "proposed_exact_attributes": {"path": (out / proposal_name).relative_to(root).as_posix(), "size_bytes": len(proposed), "sha256": hashlib.sha256(proposed).hexdigest()},
    "native_worker_preservation": {row["name"]: [name for name in cr_names if name in {pin["path"] for pin in row["current_context_members"]}]
        for row in audit["unchanged_native_and_worker_contexts"]},
    "held_source_epochs_unchanged": True,
    "source_index_git_objects_configuration_and_workloads_not_modified": True,
    "observations_not_clean_checkout_acceptance": True,
    "official_sources": ["https://git-scm.com/docs/gitattributes", "https://git-scm.com/docs/git-config", "https://git-scm.com/docs/git-hash-object"]}
canonical = lambda document: json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
value["sha256"] = hashlib.sha256(canonical(value)).hexdigest()
result_raw = canonical(value) + b"\n"
result_name = "byte-freeze-readonly-observations.v1.json"
with (out / result_name).open("xb") as target:
    target.write(result_raw)
    target.flush()
    os.fsync(target.fileno())
print(json.dumps({"observations": {"path": result_name, "size_bytes": len(result_raw), "sha256": hashlib.sha256(result_raw).hexdigest()},
    "proposal": {"path": proposal_name, "size_bytes": len(proposed), "sha256": hashlib.sha256(proposed).hexdigest()},
    "mixed_raw_stage_paths": [row["path"] for row in newline_rows if row["path"] in cr_names and row["bare_LF_count"] and row["CRLF_count"]]}, sort_keys=True))
