"""Record completed checkout gates without changing reviewed requirements/design."""
from pathlib import Path
import hashlib
import json
import subprocess

root = Path.cwd()
change = root / "openspec/changes/fix-benchmark-preparations-spec"
evidence = root / "artifacts/benchmark_recovery_20260930"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == "caea5419c0302fc60183544de86f4e879346b7d0"
assert not subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).strip()
assert not (evidence / "decoder-research-attempt-02").exists()
for name, expected, disposition in (
    ("checkout-byte-freeze-independent-review.v4.json", "a76d985d0d0bbf1c2e9c100209bf4c950841b3099d3e65b229586ca776fbc3c3", "pass_checkout_reproducibility_scope"),
    ("unchanged-image-metadata-independent-review.v1.json", "1bd3c09ef9d2e6763ffb7579f44b2b2e6eb2ad8740d524daec38a6158d3b59a9", "pass_finite_task17_3_metadata_scope"),
):
    raw = (evidence / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected
    review = json.loads(raw)
    assert review["disposition"] == disposition and not review["blocking_findings"]

checkpoint = """Reviewed planning47e432f2b5c09f750a55f7eb0164d84cc4d7e658 and source caea5419c0302fc60183544de86f4e879346b7d0 close tasks17.1-17.3:31/72 checked,41 remaining. The attributes-only commit retains165 original source descriptors (aggregate f7e2b75bf6eaf847b810fedc417782af3bb1238f4b23ab030463219690667ecc) and pins ten separate canonical-LF controller inputs (aggregate7deb3d2ebda59065c162633afff3fe014d1e7142cab76e57c8e5e2d9551b0b91). Actual fresh initial autocrlf=false/true checkouts preserve both groups, effective attributes, clean175 declared inputs/attributes and unchanged stock9/78 contexts; proof byte-freeze-fresh-checkouts.v7.json SHA3c27a97f3132e84707f9849e4bf6939fd8a6de64173f2f5549251299bbdc7bf3. Closed execution6970b664dcb979217edc5a1cf74b3bf2f6719e8f3c38dfb25f5dd6e22fc4bdac and independent review a76d985d0d0bbf1c2e9c100209bf4c950841b3099d3e65b229586ca776fbc3c3 establish this finite reproducibility scope; original failed checkouts remain immutable.

Exactly three original read-only engine calls inspect the existing native3/worker2 images between same-daemon observations. Actual image IDs, RepoDigests, stock projections, labels and current source/dependency/build-context hashes match original g freezes. Inspection34219c6a5e226b0e1b18c3242f559e49694afdd1970ccf56902490f95c19b1be, closed terminal16ccee7ad55b672523adfdbf5ae8eb98a1cd7d1bc11368ffbf6c002788035df7 and independent review1bd3c09ef9d2e6763ffb7579f44b2b2e6eb2ad8740d524daec38a6158d3b59a9 close only that unchanged image-metadata scope. No new image, container, source, decoder or model workload was launched by those checks. Remaining three runtime renewals, current aggregate/parity and dependent model/qualification/Q4/full gates remain pending.

Artifact-v1/failed research attempt01 and its independent failed audit/actual owned cleanup remain unchanged. Artifact-v2 setup repair passed35 focused actual-file/process tests in35.781s; original attempt04 receipt d39ec97b8e32bf9a4a144d85fd010853fb77cebb2a63673a46a622bd9ee6d87f, with six code files stable. The tests use explicitly labelled engine/GI fixtures and prove no physical decoding. Final independent exact-code review, updated reviewed planning binding and implementation/PR freeze precede one actual fixed four32-AU attempt02. No scientific pipeline/corpus/deadline/policy/metric amendment has been adopted; HEFT/deadline-aware HEFT remain placement aliases/expected null control, and attributed decode elapsed remains wall residence rather than utilization.

Hosted CI run36656805742 reached its90-minute job cancellation at03:17:55 UTC. Its original artifact contains successful six-target CPU configure/build terminals and a partial test log with120 OK,2 skips,2 FAIL,9 ERROR and one unfinished test; no complete suite report or source-after manifest exists. Original artifact ZIP895268B SHA f58af824528480bd059d3e3f762fdbb579edd3a86f4644354a630483657c6425 and decoded job log are preserved under cpu-ci-run-36656805742/. Newer original runs remain active; no run is cancelled/restarted by this checkpoint. Final behavior/conformance, capacity, all5600 arms/2800 pairs, archive and merge remain incomplete. Requirements/design remain unchanged by this progress-only update."""

tasks = change / "tasks.md"
text = tasks.read_bytes().decode("utf8")
assert text.count("- [x] ") == 28
text = text.replace("Current planning checkpoint, 2026-09-30:28/72", "Historical planning checkpoint, 2026-09-30:28/72", 1)
for number in ("17.1", "17.2", "17.3"):
    needle = "- [ ] " + number + " "
    assert text.count(needle) == 1
    text = text.replace(needle, "- [x] " + number + " ", 1)
text = text.replace("## 1. Approved baseline and evidence ownership\n", "## Current execution checkpoint - 2026-09-30 03:34 UTC\n\n" + checkpoint + "\n\n## 1. Approved baseline and evidence ownership\n", 1)
assert text.count("- [x] ") == 31 and text.count("- [ ] ") == 41
tasks.write_bytes(text.encode("utf8"))

for name, old_heading, new_heading in (
    ("implementation-validation.md", "## Current implementation checkpoint", "## Previous implementation checkpoint"),
    ("conformance-progress.md", "## Current conformance checkpoint", "## Previous conformance checkpoint"),
    ("image-invalidation.md", "## Current affected-source checkpoint", "## Previous affected-source checkpoint"),
):
    path = change / name
    text = path.read_bytes().decode("utf8")
    assert old_heading in text
    text = text.replace(old_heading, new_heading, 1)
    first, rest = text.split("\n", 1)
    path.write_bytes((first + "\n\n## Current completed checkout scope - 2026-09-30 03:34 UTC\n\n" + checkpoint + "\n" + rest).encode("utf8"))

plan = root / "BENCHMARK_RECOVERY_PLAN.md"
text = plan.read_bytes().decode("utf8")
old = "## Current recovery checkpoint - 2026-09-30 02:36 UTC"
old = old.replace(" - ", " \u2014 ")
assert old in text
text = text.replace(old, "## Previous recovery checkpoint \u2014 2026-09-30 02:36 UTC", 1)
anchor = "## Objective and authorization\n"
assert anchor in text
text = text.replace(anchor, "## Current recovery checkpoint - 2026-09-30 03:34 UTC\n\n" + checkpoint + "\n\nNext: freeze this progress-only task/evidence update in the same PR, record the exact reviewed core-document binding, finalize independently reviewed artifact-v2 with that binding and reserve one actual attempt02. Independently recompute closed raw four-run correctness/timing before adopting any scientific change. Diagnose actual CI failures from retained artifacts without duplicating active full suites. Continue affected runtime/parity renewal, genuine forced/static pairs, qualification/Q4, factual storage and full benchmark through final CI/conformance/archive/merge. The goal remains active.\n\n" + anchor, 1)
plan.write_bytes(text.encode("utf8"))

path = change / "preparation-plan.md"
text = path.read_bytes().decode("utf8")
text = text.replace("Status, 2026-09-30:", "Historical status, 2026-09-30:", 1)
first, rest = text.split("\n", 1)
path.write_bytes((first + "\n\nCurrent status, 2026-09-30 03:34 UTC:31/72 tasks complete; tasks17.1-17.3 closed by actual fresh-checkout and unchanged image metadata evidence. BENCHMARK_RECOVERY_PLAN.md and implementation-validation.md provide exact receipts/current next action. Requirements/design remain47e432f2 scope. Decoder attempt02, remaining runtime/parity/model gates, qualification/Q4/storage/full execution and final repository checks remain pending. First CPU CI timed out with partial failures; later original runs remain active.\n" + rest).encode("utf8"))
path = change / "verification-plan.md"
text = path.read_bytes().decode("utf8")
anchor = "## 1. Benchmark recovery has explicit execution and completion gates\n"
assert anchor in text
scope = """## Executed finite checkout scope - 2026-09-30 03:34 UTC

Requirement Baselines and affected evidence are reproducible, scenarios Exact source identity depends on inherited line endings and Stock build controller requires canonical LF metadata: implementation .gitattributes at original79ff and corrected caea5419, exact ten rules at lines173-182; actual fresh false/true proof3c27a97f and independent review a76d985d pass both groups and unchanged stock9/78 contexts. Independent unchanged native3/worker2 metadata review1bd3c09e validates live identity scope without a workload. Tasks17.1-17.3 are complete. Original failed true checkouts remain failed; full current-runtime/parity and final-source test conformance are pending. New initializer/CID/cleanup scenarios require the independently reviewed final artifact-v2 and actual attempt02;35 passing focused fixtures grant no physical research or benchmark acceptance.

"""
text = text.replace(anchor, scope + anchor, 1)
path.write_bytes(text.encode("utf8"))
print(json.dumps({"updated_progress_documents": 7, "tasks_complete":31,"tasks_total":72,"requirements_design_changed":False,"production_or_test_changed_by_this_script":False}))
