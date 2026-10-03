"""Record the independent planning review; do not run experiments or edit sources."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent / "scientific-checkout-planning-independent-review.v1.json"
BASE = "a5b3812457cc2eddfd19eaf7687a4e868a7d085b"
CHANGE = "openspec/changes/fix-benchmark-preparations-spec/"
FILES = [
    "BENCHMARK_RECOVERY_PLAN.md",
    *[CHANGE + p for p in (
        "proposal.md", "design.md", "tasks.md",
        "specs/benchmark-launch-preparation/spec.md", "verification-plan.md",
        "preparation-plan.md", "implementation-validation.md",
        "image-invalidation.md", "conformance-progress.md",
    )],
]


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def pin(relative: str) -> dict:
    raw = (ROOT / relative).read_bytes()
    return {"path": str(ROOT / relative), "relative_path": relative,
            "size_bytes": len(raw), "sha256": digest(raw)}


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["/usr/bin/git", "--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec",
         "--work-tree=" + str(ROOT), *args],
        cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True,
    )


assert not OUT.exists(), "Immutable review already exists"
assert git("rev-parse", "HEAD").stdout.decode().strip() == BASE
raw_docs = {p: (ROOT / p).read_bytes() for p in FILES}
docs = {p: b.decode("utf-8") for p, b in raw_docs.items()}
tasks = docs[CHANGE + "tasks.md"]
spec = docs[CHANGE + "specs/benchmark-launch-preparation/spec.md"]
verify = docs[CHANGE + "verification-plan.md"]
counts = {
    "tasks": len(re.findall(r"^- \[[ x]\]", tasks, re.M)),
    "checked_tasks": len(re.findall(r"^- \[x\]", tasks, re.M)),
    "requirements": len(re.findall(r"^### Requirement:", spec, re.M)),
    "scenarios": len(re.findall(r"^#### Scenario:", spec, re.M)),
}
assert counts == {"tasks": 72, "checked_tasks": 28, "requirements": 16, "scenarios": 69}
new_scenarios = [
    "Exact source identity depends on inherited line endings",
    "Frozen policy labels are placement aliases",
    "Deadline and attributed elapsed measurements are saturated or confounded",
    "Decoder mechanism research precedes an adopted regime",
]
for scenario in new_scenarios:
    assert "#### Scenario: " + scenario in spec
    assert scenario in verify
assert "## Gate 1R:" in docs[CHANGE + "preparation-plan.md"]
assert "at that checkpoint OpenSpec progress was 28/67" in docs["BENCHMARK_RECOVERY_PLAN.md"]
for p in ("implementation-validation.md", "image-invalidation.md", "conformance-progress.md"):
    assert "2026-09-30" in docs[CHANGE + p].splitlines()[2]

artifact_prefix = "artifacts/benchmark_recovery_20260930/"
metadata_path = artifact_prefix + "decoder-experiment-prerequisites/package_metadata.stdout"
terminal_path = artifact_prefix + "decoder-experiment-prerequisites/package_metadata.terminal.v1.json"
metadata = json.loads((ROOT / metadata_path).read_bytes())
terminal = json.loads((ROOT / terminal_path).read_bytes())
assert terminal["returncode"] == 0 and not terminal["timed_out"]
assert terminal["commit"] == BASE and terminal["container_not_found_after_rm"]
assert terminal["stdout"]["sha256"] == digest((ROOT / metadata_path).read_bytes())
assert terminal["stdout"]["size_bytes"] == (ROOT / metadata_path).stat().st_size
assert terminal["image_id"] == "sha256:70696f057232acd382f60beaaf12cd9279b317b0ba9a7ade29f0b955ce90481a"
gi = [json.loads(row["stdout_text"]) for row in metadata["gi_probes"]]
isolated = next(row for row in gi if row["route"] == "isolated")
stock = next(row for row in gi if row["route"] == "stock_path")
assert isolated["available"] and isolated["gi_version"] == "3.50.0"
assert isolated["gst_version"] == [1, 28, 2, 0] and all(isolated["api"].values())
assert not stock["available"] and stock["error_type"] == "NotInitialized"

source_paths = [
    "deploy/native_gst_probe/checkpoint_source_coordinator.cpp",
    "deploy/native_gst_probe/checkpoint_admission_transport.hpp",
    "deploy/native_gst_probe/vast_native_gst_probe.cpp",
    "scripts/publication_policy_frozen_replay_v1.py",
    "scripts/checkpoint_native_policy_runtime.py",
]
evidence_paths = [artifact_prefix + p for p in (
    "decoder-causality-research-recipe.v1.md",
    "decoder-causality-research-recipe.v1.json",
    "decoder-research-host-dependencies.v1.json",
    "scientific-operating-regime-review.v1.json",
    "policy-selection-equivalence-review.v1.json",
    "decoder-properties-review.v1.json",
    "gstreamer-decoder-fresh-registry-inspection/decoder-inspection.v1.json",
    "gstreamer-decoder-fresh-registry-inspection/nvh264dec.stdout",
    "gstreamer-decoder-fresh-registry-inspection/nvh264dec.stderr",
    "gstreamer-decoder-fresh-registry-inspection/nvh265dec.stdout",
    "gstreamer-decoder-fresh-registry-inspection/nvh265dec.stderr",
    "decoder-experiment-prerequisites/decoder-inspection.v1.json",
    "decoder-experiment-prerequisites/package_metadata.stdout",
    "decoder-experiment-prerequisites/package_metadata.terminal.v1.json",
    "byte-freeze.minimum-proposed.gitattributes.v1.txt",
    "byte-freeze-readonly-observations.v1.json",
    "packaging-source-rollforward.v4.json",
    "packaging-source-rollforward-independent-review.v4.json",
    "planning-byte-freeze-review.v2.json",
)]
sources = [pin(p) for p in source_paths]
evidence = [pin(p) for p in evidence_paths]
diff = git("diff", "--binary", "--no-ext-diff", BASE, "--", *FILES)
whitespace = git("diff", "--check", BASE, "--", *FILES)

review = {
    "schema_version": 1,
    "artifact_kind": "vast_independent_scientific_checkout_planning_review_v1",
    "accepted": False, "publication_ready": False,
    "reviewed_at_utc": datetime.now(timezone.utc).isoformat(),
    "reviewer": "/root/adversarial_review",
    "source_commit": BASE,
    "change": "fix-benchmark-preparations-spec",
    "disposition": "approved_planning_no_blocking_findings_exact_commit_PR_record_required",
    "scope": "Independent read-only review of final ten planning/current-pointer files, decisions16/17, actual packaged prerequisite metadata and source-grounded research feasibility; no experiment, source implementation, model/benchmark acceptance or GitHub APPROVE.",
    "reviewed_files": [{"path": str(ROOT / p), "relative_path": p,
                        "size_bytes": len(b), "sha256": digest(b)} for p, b in raw_docs.items()],
    "owned_diff": {"base": BASE, "paths": FILES, "size_bytes": len(diff.stdout),
                   "sha256": digest(diff.stdout), "returncode": diff.returncode,
                   "stderr_sha256": digest(diff.stderr)},
    "document_counts": counts,
    "new_scenarios_verified_in_delta_and_verification_map": new_scenarios,
    "whitespace_check": {"returncode": whitespace.returncode,
                         "stdout_sha256": digest(whitespace.stdout),
                         "stderr_sha256": digest(whitespace.stderr)},
    "source_pins": sources, "evidence_pins": evidence,
    "source_grounded_findings": [
        "The finite156-path -text !eol rule and22 raw source replacements preserve actual bytes, nine explicit LF contracts and unrelated dirty paths. Fresh initial autocrlf true/false checkouts must verify all165 raw/index descriptors and actual closures. No old inode/custody receipt is rebound; image reuse remains stock-scope and live-validation dependent.",
        "Actual packaged isolated Python/GI3.50/Gst1.28.2 exposes push/pull/video-map APIs. The separate stock-path probe retained NotInitialized, so the consumer must explicitly Gst.init(None) and pin actual loaded modules/typelibs/libraries/plugin/source ELF. Metadata is not a decoded-output test. No host substitution, compile or dependency install is justified.",
        "Original source673 emits the event,674-676 waits for exact ACK,678 enqueues binary and679 increments offsets from scaled GstBuffer duration with a1ns fallback; sender393 writes asynchronously. Current event has no DTS/duration/transportPTS/caps. Before ACK validate its declarations, consecutive schedule, byte reservation and any completed prior packet. After ACK validate the current80B header/size before allocation, then full payload/hash/PTS/DTS/duration and exact event match before appsrc/next ACK. Never wait for the current binary before its enabling ACK or fail solely because the next event precedes the previous sender's binary completion. STOP can wait behind admission locking. The31.5s window must prove exactly32 admissions and duration/schedule>=999999600ns; no publication guard is inherited.",
        "Default/zero is the only decoder property comparison. The fixed front/default,front/zero,underbody/zero,underbody/default order and first32/central9-24 cohort prevent silent reselection. Every PTS/caps/order/active-RGB-row hash is compared; classify flush against the actual decoder-sink EOS event, not host/source EOF or appsrc's EOS request. EOS-only central outputs are insufficient steady-state timing and remain separate correctness/flush observations.",
        "Guest monotonic decoder sink/src observations precede logging/hashing. Realtime source admission and host CLI time are different clocks; no cross-clock subtraction is permitted without separately labelled actual-realtime observations and quantization/clock-step limits. Hash/sample hold and backpressure remain disclosed limitations.",
        "All-finite common-deadline HEFT/DAHEFT selection equivalence holds independently of decode saturation. Seven labels and frozen matrix remain intact as provenance/expected algorithmic null controls; separate physical run noise cannot establish algorithm advantage.",
        "Original predecision expiration and worst-stream saturation make zero relative violation difference insensitive to further latency regression. C_obs is partial attributed elapsed; decode wall residence is not CPU work, NVDEC busy time, energy or model quality. Mechanism results cannot authorize new corpus/pipeline/deadline/policy formulas or a six-stream model/benchmark claim.",
    ],
    "research_budget_arithmetic": {
        "per_run_phase_seconds": {"startup": 45, "future_start": 2, "admission": 31.5,
                                  "EOS_drain": 10, "owned_cleanup": 15},
        "phase_sum_seconds": 103.5, "per_run_hard_seconds": 120,
        "preflight_hard_seconds": 120, "all_four_plus_preflight_seconds": 600,
        "events_per_run": 512, "event_bytes_max": 16384, "event_bytes_product": 8388608,
        "stdout_bytes_max": 1048576, "stderr_bytes_max": 1048576,
        "raw_AU_aggregate_bytes_max": 134217728, "namespace_bytes_max": 268435456,
        "four_namespaces_plus_metadata_bytes": 1107296256,
        "metadata_bytes_max": 33554432, "wire_payload_bytes_max": 67108864,
        "one_mapped_RGB_frame_bytes_max": 67108864,
        "appsrc_buffers_max": 1, "appsink_buffers_max": 1,
        "interpretation": "Feasible checked research admission predicates, not source constructor theorems, proof that the unobserved first32 raw AU aggregate fits, decoder-driver RSS bounds or full-benchmark storage admission. Validate current event declarations/caps before ACK; verify current binary after ACK before appsrc/next ACK with header size before payload allocation, and check applicable output/event caps before writes. Preserve failed attempts; no cgroup tuning or automatic limit increase/retry.",
    },
    "immutable_recipe_refinement": "Historical recipev1 remains unchanged. Normative design17 now narrows its conditional dependency route to observed packaged GI with explicit init, corrects original event-ACK-binary sequencing, fixes clock/backpressure/async=false/actual-decoder-sink-EOS interpretation, and freezes numeric admission bounds. Consumer implementation must follow those reviewed refinements, not infer authority from the older looser recipe.",
    "approval_limits": [
        "Exact amended planning commit must be reviewed/recorded in the same PR before dependent consumer/byte-freeze application; this file is a delegated planning review, not independent GitHub approval.",
        "No decoder experiment, consumer compile/run, model inference, qualification/Q4/full arm, checkout/staging/source application or scientific regime adoption was performed by this review.",
        "A bound/error/timeout preserves failure and stops dependents. Actual media/prefix/package pins, source events and consumer/output correctness remain launch/execution gates.",
        "Any selected production property/corpus/metric/deadline/algorithm amendment requires new coherent planning review and exact source/payload/count/string budget/invalidation proof.",
    ],
    "self_critique": "My earlier review repaired integrity/accounting but did not establish scientific information. Decoder buffering was initially plausible rather than proven, and the HEFT/DAHEFT identity is global rather than only expired requests. I also initially recommended validating current binary fields before ACK without accounting for the original source's ACK-before-enqueue ordering; the parent source reread caught that deadlock. No receipt was sealed or consumer launched under that wording. Final planning/source review binds the corrected event-first then ACK then binary validation before appsrc/next ACK. These corrections remain explicit rather than rewriting historical reviews. The narrowed mechanism experiment is the smallest physical next step; broad parity/qualification/full execution before resolving it would spend time without distinguishing the suspected mechanism.",
    "official_sources": [
        "https://git-scm.com/docs/gitattributes",
        "https://gstreamer.freedesktop.org/documentation/nvcodec/nvh264dec.html",
        "https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/read-me/index.html",
    ],
    "tests_or_workloads_run_by_this_review": [],
    "independence_disclosure": "Reviewer authored the cited scientific/alias reviews and immutable decoder recipe. Independently read parent-authored final planning bytes, actual original metadata and source; architecture review is corroboration rather than a substitute for this review.",
}
for p, raw in raw_docs.items():
    assert (ROOT / p).read_bytes() == raw, "Planning changed during review capture"
for observed in sources + evidence:
    assert pin(observed["relative_path"]) == observed, "Review source/evidence changed"
assert git("diff", "--binary", "--no-ext-diff", BASE, "--", *FILES).stdout == diff.stdout
review["sha256"] = digest(json.dumps(review, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode())
raw = (json.dumps(review, sort_keys=True, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
with OUT.open("xb") as fh:
    fh.write(raw)
print(json.dumps({"path": str(OUT), "size_bytes": len(raw), "physical_sha256": digest(raw),
                  "semantic_sha256": review["sha256"], "owned_diff_sha256": digest(diff.stdout),
                  "counts": counts, "disposition": review["disposition"]}, sort_keys=True))
