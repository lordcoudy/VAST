"""Pin an independent planning-only review; never apply source or Git changes."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[2]
gitdir = "/mnt/e/" + (root / ".git").read_text("ascii").strip().removeprefix("gitdir: E:/")
git = ["git", "--git-dir=" + gitdir, "--work-tree=" + str(root)]
head = subprocess.check_output(git + ["rev-parse", "HEAD"], cwd=root).decode("ascii").strip()
assert head == "a5b3812457cc2eddfd19eaf7687a4e868a7d085b"
epoch = lambda value: [value.st_dev, value.st_ino, value.st_mode, value.st_nlink,
    value.st_size, value.st_mtime_ns, value.st_ctime_ns]
names = ["openspec/changes/fix-benchmark-preparations-spec/" + path for path in (
    "proposal.md", "design.md", "specs/benchmark-launch-preparation/spec.md", "tasks.md",
    "verification-plan.md", "preparation-plan.md")]
names += ["artifacts/benchmark_recovery_20260930/" + path for path in (
    "byte-freeze.minimum-proposed.gitattributes.v1.txt", "byte-freeze-readonly-observations.v1.json",
    "checkout-byte-freeze-recommendation.v1.md", "packaging-source-rollforward.v4.json",
    "decoder-causality-research-recipe.v1.md")]
names += [".gitattributes", "scripts/materialize_runtime_build_context_v3.py"]
pins, documents = [], {}
for name in names:
    path = root / name
    assert path.resolve(strict=True) == path
    with path.open("rb") as source:
        before = os.fstat(source.fileno())
        raw = source.read()
        after = os.fstat(source.fileno())
    assert epoch(before) == epoch(after) == epoch(path.lstat())
    assert before.st_nlink == 1
    pins.append({"path": name, "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "epoch": epoch(before)})
    documents[name] = raw

base = "artifacts/benchmark_recovery_20260930/"
observation = json.loads(documents[base + "byte-freeze-readonly-observations.v1.json"])
audit = json.loads(documents[base + "packaging-source-rollforward.v4.json"])
proposal = documents[base + "byte-freeze.minimum-proposed.gitattributes.v1.txt"].decode("ascii")
rules = [line for line in proposal.splitlines() if line and not line.startswith("#")]
assert len(rules) == 156
expected = {"/" + name + " -text !eol" for name, value in observation["effective_attributes"].items()
    if value["text"] == "unspecified" or name == "deploy/savant/canonical_distributed_module.yml"}
assert set(rules) == expected
assert all(name not in {row["path"] for row in audit["final_actual_source_manifest"]["project_sources"]}
    for name in (".gitattributes",))
mixed = [row["path"] for row in observation["raw_stage_candidate_newline_inventory"]
    if row["CRLF_count"] and row["bare_LF_count"]]
assert len(mixed) == 17
proof = {
    "schema_version": 1,
    "artifact_kind": "vast_exact_planning_byte_freeze_review_v1",
    "reviewed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "change": "fix-benchmark-preparations-spec",
    "source_commit": head,
    "scope": "Planning decisions16-17 and corresponding proposal/spec/tasks; read-only original six-file coherence and concrete byte-freeze validation review.",
    "reviewer": "/root/architecture_review",
    "disposition": "approved_for_exact_commit_planning_record_with_nonblocking_runbook_coverage_note",
    "accepted": False,
    "publication_ready": False,
    "launch_or_publication_grant": False,
    "implementation_authorization_from_this_file": False,
    "planning_commit_and_PR_review_still_required": True,
    "reviewed_files": pins,
    "findings": [
        {"severity": "none", "subject": "Finite attributes and immutable source scope", "assessment": "156 exact rules equal all155 unspecified source members plus the single YAML conflict. Nine explicit LF paths and all165 original physical bytes remain preserved;17mixed-ending originals require raw preservation. Git -text disables newline conversion; no claim is made that it disables independent filters/encoding/ident."},
        {"severity": "none", "subject": "New checkout custody and filter precedence", "assessment": "Design requires effective nontransforming attributes and actual new checkout identities. Root exact rules override earlier root styles/global defaults but higher-precedence info/nested attributes must be checked. Every165 raw index/checkout size/hash and all current dependency contexts are verification gates. No original inode/owner witness or accepted image receipt can be relabelled."},
        {"severity": "none", "subject": "No physical source invalidation from representation-only amendment", "assessment": "Only root attributes plus22raw Git representations change. The active physical sources are not rewritten. Attributes are outside all165 executable/build inputs; current stock build-context materializer makes destination files0444 with configured source-date-epoch, independent of checkout executable modes. Unchanged byte-bound native3/worker2/runtime/host identities can remain valid only through their unchanged stock validation scopes and current required live inspection."},
        {"severity": "none", "subject": "Scientific research remains nonpromoting", "assessment": "Decision17 retains original media/cadence, exactly32AUs per run and preselected central9-24, default versus supported zero only, complete output correctness/order and bounded original custody. It does not substitute for the real diagnostic pair or qualification. Adoption, retiming, new media/deadline/metric or scheduler semantics require further exact-commit planning review. Frozen matrix/models/raw estimands are preserved; alias/saturation/partial-wall-attribution limitations are explicit."},
        {"severity": "nonblocking_documentation_coverage", "subject": "Two ancillary runbooks", "assessment": "verification-plan section5 and preparation-plan gates have not yet gained explicit decision16-17/scenario cross-references. Core proposal/design/spec/tasks give concrete complete acceptance criteria and do not conflict with those runbooks. Add concise byte-freeze and nonpromoting research coverage before final conformance; this note grants no lower bar. If the files change before planning freeze, repin/review their revised bytes."}
    ],
    "recommended_narrow_implementation": [
        "After exact amended planning commit and delegated PR review are recorded, reread all165 physical source descriptors and preserve unrelated preexisting staged/dirty work. Append only the reviewed156-rule block after existing root attributes. Inspect effective attributes for every165 member.",
        "Explicitly stage root attributes plus only22original raw source paths. A narrowly scoped git add --renormalize -- <exact22paths> can force existing index entries through the new approved -text rules; never use --renormalize . or blanket add. Before source commit, stream all165 index blobs via one git cat-file --batch and require exact original size/SHA/aggregate, not ignored-CR or filename-only diff.",
        "Use one artifact-only verification driver, no production runner. In two new canonical POSIX checkout roots, run git clone --no-checkout --no-hardlinks -- <source-repository> <new-root>, configure core.autocrlf false or true BEFORE initial checkout, then checkout --detach <exact-source-commit>. Verify original child terminal and actual configured mode; a later refreshed checkout is insufficient.",
        "From each fresh checkout, hold/open each165 original path as a regular nonalias file, stream SHA/size, retain actual seven-field epochs/root identities and recheck before receipt-last. Require source aggregatef7e2b75bf6eaf847b810fedc417782af3bb1238f4b23ab030463219690667ecc; check all156 attributes unsettext/unspecifiedeol and the9retainedLF attributes; reject transforming filter/ident/encoding or higher-precedence overrides. Require clean status for declared source paths.",
        "Invoke existing four source-closure validators and recompute current actual three-manifest native runtime contexts, native3/worker2 build-plan hash scopes and host _discover_sources exact78 bytes from each checkout using the frozen Python with -B. These are source/metadata checks only; do not rebuild images, invoke Docker or run models merely to verify unchanged bytes.",
        "Write one immutable nonauthorizing verification receipt binding exact source/planning commit, snapshot descriptors, two original clone/check/validator command outcomes, new root/file epochs, effective attrs and raw manifest/context equality. Record limits and independent review. Fresh stock host custody receipts are required if either new checkout later becomes an execution root; never copy an old accepted receipt into it as current inode authority."
    ],
    "checks": {"OpenSpec_strict_validation_passed": True, "OpenSpec_format_validation_not_behavior_acceptance": True,
        "proposal_rule_count": 156, "exact_original_source_inventory_count": 165,
        "explicit_LF_rules_retained": 9, "raw_source_stage_candidates": 22, "mixed_ending_candidates": 17,
        "source_production_attributes_index_configuration_not_modified": True,
        "no_clone_source_stage_image_container_model_or_decoder_experiment_executed": True},
    "self_critique": "This reviewer authored the earlier byte-freeze recommendation, so this review is independent of the parent-written amendment but not an independent origin of the initial156-rule design. Independent adversarial physical audit v4 is separate. I initially treated Git filename-only ignored-CR output as semantic evidence; immutable v4 corrected that mistake using direct streamed bytes. This review checks source representation and planning limits, not image/model/experiment acceptance.",
    "official_sources": ["https://git-scm.com/docs/gitattributes", "https://git-scm.com/docs/git-config", "https://git-scm.com/docs/git-hash-object", "https://git-scm.com/docs/git-cat-file"]
}
for pin in pins:
    path = root / pin["path"]
    assert epoch(path.lstat()) == pin["epoch"] and hashlib.sha256(path.read_bytes()).hexdigest() == pin["sha256"]
canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
proof["sha256"] = hashlib.sha256(canonical(proof)).hexdigest()
raw = canonical(proof) + b"\n"
target = root / base / "planning-byte-freeze-review.v1.json"
with target.open("xb") as result:
    result.write(raw)
    result.flush()
    os.fsync(result.fileno())
print(json.dumps({"path": target.relative_to(root).as_posix(), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, sort_keys=True))
