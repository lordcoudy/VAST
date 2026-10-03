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
    "verification-plan.md", "preparation-plan.md", "implementation-validation.md",
    "image-invalidation.md", "conformance-progress.md")]
names += ["BENCHMARK_RECOVERY_PLAN.md"]
names += ["artifacts/benchmark_recovery_20260930/" + path for path in (
    "byte-freeze.minimum-proposed.gitattributes.v1.txt", "byte-freeze-readonly-observations.v1.json",
    "checkout-byte-freeze-recommendation.v1.md", "packaging-source-rollforward.v4.json",
    "decoder-causality-research-recipe.v1.md")]
names += [".gitattributes", "scripts/materialize_runtime_build_context_v3.py",
    "deploy/native_gst_probe/checkpoint_source_coordinator.cpp",
    "deploy/native_gst_probe/checkpoint_admission_transport.hpp"]
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
source_text = documents["deploy/native_gst_probe/checkpoint_source_coordinator.cpp"].decode("utf-8")
event_start = source_text.index("std::ostringstream event;")
event_write = source_text.index("write_exact(admission_fd_, event.str());")
ack_read = source_text.index("read_line(ack_fd_)")
enqueue = source_text.index("enqueue_for_all_consumers(frame);")
advance = source_text.index("const std::uint64_t schedule_step_ns =")
assert event_start < event_write < ack_read < enqueue < advance
event_fields = source_text[event_start:event_write]
assert "access_unit_dts_ns" not in event_fields and "duration_ns" not in event_fields
proof = {
    "schema_version": 3,
    "artifact_kind": "vast_exact_planning_byte_freeze_review_v3",
    "reviewed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "change": "fix-benchmark-preparations-spec",
    "source_commit": head,
    "scope": "Final planning decisions16-17, core proposal/spec/design/tasks, verification/preparation runbooks and four current-status pointers; ten-file coherence and concrete source-byte verification review.",
    "reviewer": "/root/architecture_review",
    "disposition": "approved_for_exact_commit_planning_record",
    "supersedes_v2_review": {"path": "artifacts/benchmark_recovery_20260930/planning-byte-freeze-review.v2.json",
        "sha256": "ce6f247884d62b6d17db70091cb25ad70a464c0fc3990ce78d0f8e8f99feceb4",
        "reason": "Root caught original admission-event -> enablingACK -> binaryenqueue ordering: current event lacksDTS/duration and consumer cannot await currentbinary beforeACK. Final design/verification now separate preACK declarations/precedingpacket from postACK currentbinary validation, and classify flush by actualdecoder-sinkEOS event. Earlier immutable review remains historical."},
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
        {"severity": "none", "subject": "All ancillary mappings and current pointers", "assessment": "verification-plan now names/maps every new reproducibility/alias/saturation/decoder scenario; preparation gate1R cites decisions16-17 and actual order. Three current checkpoint prefaces and durable plan identify pusheda5b source, real packaged10 gate, pending amendments and original historical scopes. Current next action is the reviewed byte-freeze/research gate, not an already completed build. No past pass is promoted to model/qualification/full acceptance."},
        {"severity": "none", "subject": "Finite isolated research and clock rules", "assessment": "Decision17 now freezes120s preflight,120s/run with45s startup+2s future start+31.5s admission+10s EOS+15s cleanup within103.5s,600s total;512x16KiB events,1MiB/channel,128MiB packet aggregate,256MiB/run namespace,4x256MiB+32MiB=1107296256 total and one mappedframe64MiB. Limits must be checked before allocation/writing/ACK; protocol64MiB and actual999999600ns cadence remain. These are isolated research admission bounds, not new publication constructor/RSS claims. GI route is observed package-only, appsink asyncfalse retained, decoder sink/src use sameguestmonotonicclock, source realtime is separately labelled/quantized; central EOS-only outputs cannot be pooled into steady-state timing. No new positive-effect guarantee, cohort search or silent bound increase is allowed."}
        ,{"severity": "none", "subject": "Original event/ACK/binary causal control and actual EOS", "assessment": "Pinned stock source673-684 writes currentadmission event, blocks for exact1 ACK sequence, then enqueues currentbinary and advances using max(duration,1). Event declaration includes sequence/run/dataset/stream/admission/key/sourcecycle/access-unitPTS/payloadhash/size/schedule/realtimestamp, notDTS or duration. Final planning correctly checks declarations/caps/precedingvalidatedbinary before enablingACK, persists actualevent/ACK, then cross-matches currentheader/payload/fullhash/actualPTSDTSduration before appsrc or any furtherACK. First duration cannot be observed preACK. Invalid/zero/shortduration fails the original attempt and stops its source without a secondACK. Flush classification uses actualdecoder-sinkEOS event, not sourceEOF or hostEOSsubmission. This corrects a deadlock-producing assumption from earlierreview; no source mutation is required."}
    ],
    "recommended_narrow_implementation": [
        "After exact amended planning commit and delegated PR review are recorded, reread all165 physical source descriptors and preserve unrelated preexisting staged/dirty work. Append only the reviewed156-rule block after existing root attributes. Inspect effective attributes for every165 member.",
        "Explicitly stage root attributes plus only22original raw source paths. A narrowly scoped git add --renormalize -- <exact22paths> can force existing index entries through the new approved -text rules; never use --renormalize . or blanket add. Before source commit, stream all165 index blobs via one git cat-file --batch and require exact original size/SHA/aggregate, not ignored-CR or filename-only diff.",
        "Use one artifact-only verification driver, no production runner. In two new canonical ext4 checkout roots, run git clone --no-checkout --no-hardlinks -- /mnt/e/STUDY/VAST/.git <new-root> using the resolved common Git directory, configure core.autocrlf false or true BEFORE initial checkout, then checkout --detach <exact-source-commit>. The Windows worktree .git text cannot be interpreted as a Linux gitdir without resolution. Verify original child terminal and actual configured mode; a later refreshed checkout is insufficient.",
        "From each fresh checkout, hold/open each165 original path as a regular nonalias file, stream SHA/size, retain actual seven-field epochs/root identities and recheck before receipt-last. Require source aggregatef7e2b75bf6eaf847b810fedc417782af3bb1238f4b23ab030463219690667ecc; check all156 attributes unsettext/unspecifiedeol and the9retainedLF attributes; reject transforming filter/ident/encoding or higher-precedence overrides. Require clean status for declared source paths.",
        "Invoke existing four source-closure validators and recompute current actual three-manifest native runtime contexts, native3/worker2 build-plan hash scopes and host _discover_sources exact78 bytes from each checkout using the frozen Python with -B. These are source/metadata checks only; do not rebuild images, invoke Docker or run models merely to verify unchanged bytes.",
        "Write one immutable nonauthorizing verification receipt binding exact source/planning commit, snapshot descriptors, two original clone/check/validator command outcomes, new root/file epochs, effective attrs and raw manifest/context equality. Record limits and independent review. Fresh stock host custody receipts are required if either new checkout later becomes an execution root; never copy an old accepted receipt into it as current inode authority."
    ],
    "research_budget_arithmetic": {"per_run_phase_sum_seconds": 45 + 2 + 31.5 + 10 + 15,
        "per_run_limit_seconds": 120, "overall_limit_seconds": 120 + 4 * 120,
        "event_bytes_per_run": 512 * 16 * 1024,
        "retained_namespace_and_metadata_bytes": 4 * 256 * 1024 * 1024 + 32 * 1024 * 1024,
        "one_mapped_frame_bytes": 64 * 1024 * 1024, "publication_or_total_RSS_budget_claim": False},
    "actual_source_causal_order": {"source_path": "deploy/native_gst_probe/checkpoint_source_coordinator.cpp",
        "lines": {"admission_event_write": 673, "expected_ACK": 674, "ACK_read": 675,
            "binary_enqueue": 678, "duration_schedule_step": 679},
        "event_DTS_duration_absent": True, "current_packet_requires_enabling_ACK": True,
        "preACK_current_event_and_preceding_binary_validation": True,
        "postACK_current_binary_before_appsrc_or_furtherACK": True,
        "EOS_output_classification_authority": "actual_guest_decoder_sink_EOS_event"},
    "checks": {"OpenSpec_strict_validation_passed": True, "OpenSpec_format_validation_not_behavior_acceptance": True,
        "planning_diff_check_passed": True, "final_planning_and_current_pointer_file_count": 10,
        "proposal_rule_count": 156, "exact_original_source_inventory_count": 165,
        "explicit_LF_rules_retained": 9, "raw_source_stage_candidates": 22, "mixed_ending_candidates": 17,
        "source_production_attributes_index_configuration_not_modified": True,
        "no_clone_source_stage_image_container_model_or_decoder_experiment_executed": True},
    "self_critique": "This reviewer authored the earlier byte-freeze recommendation, so this review is independent of the parent-written amendment but not an independent origin of the initial156-rule design. Independent adversarial physical audit v4 is separate. I initially treated Git filename-only ignored-CR output as semantic evidence; immutable v4 corrected that mistake using direct streamed bytes. V2 also missed the original event-before-ACK-before-binary dependency caught by root; v3 inspects/pins the actual C++ source and event field inventory and requires the corrected two-stage validation. This review checks source representation and planning limits, not image/model/experiment acceptance.",
    "official_sources": ["https://git-scm.com/docs/gitattributes", "https://git-scm.com/docs/git-config", "https://git-scm.com/docs/git-hash-object", "https://git-scm.com/docs/git-cat-file"]
}
for pin in pins:
    path = root / pin["path"]
    assert epoch(path.lstat()) == pin["epoch"] and hashlib.sha256(path.read_bytes()).hexdigest() == pin["sha256"]
canonical = lambda value: json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
proof["sha256"] = hashlib.sha256(canonical(proof)).hexdigest()
raw = canonical(proof) + b"\n"
target = root / base / "planning-byte-freeze-review.v3.json"
with target.open("xb") as result:
    result.write(raw)
    result.flush()
    os.fsync(result.fileno())
print(json.dumps({"path": target.relative_to(root).as_posix(), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}, sort_keys=True))
