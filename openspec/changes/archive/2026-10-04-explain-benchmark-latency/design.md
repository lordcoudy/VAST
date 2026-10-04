## Context

See proposal.md. PR2 merged as c07de9c78e3beaaf276ee54b5f414a3a4b5d035c. Measured source B a00aa57f differs from implementation D and final reviewed E2; those distinctions remain.
Read-only audits show existing status lines still pending after release. The original measured CSV is coherent for end-to-end latency/coverage. However checkpoint_publication_runtime.py assigns stage start from direct parent completion and queue-enter=start. Its zero queue span is a promoted value, not direct evidence of no queue wait. Native path_entry→terminal also contains map/hash, native client/route waits and worker execution.

## Goals / Non-Goals

Goals: a small reusable offline command plus current authoritative guidance; reproduce four accepted original populations and explain observed latency envelopes and unknowns.
Non-goals: engine/model execution, source/corpus/cadence/deadline changes, modifying stock promotion/C_obs semantics, accepting original failures, causal decoder or pure-service proof, full-campaign readiness, unsolicited cleanup.

## Decisions

1. Implement scripts/analyze_component_latency_v1.py with standard library CSV/JSON/Decimal/hashlib and tests/test_component_latency_diagnostics.py. Read exact evidence-directory files: frames.csv, ingress_ledger.csv, branch_terminals.csv, frame_events.csv; publication_policy_decisions.jsonl is optional. Require explicit finite positive --deadline-ms because the four required CSVs carry no original deadline; report its provenance as caller_parameter and corroborate supplied optional policy request deadline-minus-arrival within retained floating-point precision. Use unchanged100 for all four original analyses. No engine subprocess or third-party dependency. Bound each input at64MiB and all input at256MiB; reject symlink/nonregular files, invalid UTF-8/duplicate headers and nonfinite required values. Input hashes are provenance of this diagnostic, not acceptance receipts.
2. Infer required branches and shared/baseline decoder roles from consistent retained measurement branch/frame/stage rows. Preserve the recorded measured cohort; never recompute admission by wall-clock bounds. Join frame keys(run_id,trace_id,stream_id,frame_id), policy also branch/decision/input association. Required completed path rows must be unique and satisfy ingress<=decoder completion<=frame join and terminal/deadline agreement.
3. Critical branch is latest required postprocess completion (deterministic name tie break). Decode end uses decode_<critical branch> for baseline or decode for shared. Per-frame prefix_ms=decode_end-ingress; residual_ms=frame.egress-decode_end; their sum must equal original latency. Decoder share=prefix/latency only for positive latency. Report linear p50/p95/p99, coverage/drop/branch counts separately. Marginal medians are not additive.
4. Stage spans, recorded queue spans and native path spans remain distinct observed envelopes. True queue wait, pure model service and NVDEC busy are null/unknown. Optional native evidence is cross-joined when present; no row-order matching. Missing optional inputs are explicit; inconsistent supplied evidence fails.
5. Fresh exclusive output contains diagnostic.json, per_completed_frame.csv and report.md. File identities and all scientific limitations are retained. Failed input validation does not create a successful report. Each original arm runs once through the tool; a compact combined four-arm Markdown/JSON summary references originals without copying giant raw data.
6. Prefix current PLAN/progress/recovery documents with actual latest status and an explicit historical boundary. Preserve original suffix bytes and every archived file. Prefix runbook/README with current closure and diagnostics guidance; timestamp earlier D snapshots. Root dirty Windows checkout remains intact; publish only a scoped current-status pointer there preserving its existing raw content.
7. One branch/change/new Draft PR. Independent planning review of exact committed artifacts is recorded in that PR before implementation under explicit standing user authorization. Current implementation/test/report review, mandatory CI, conformance and supported archive precede latest-head checks/final review/authorized merge. Process transitions are recorded in the PR ledger rather than unfulfilled implementation checkboxes that cause an archive/CI cycle.

## Risks / Trade-offs

- Stage promotion loses true queue/service boundaries → state unknown and retain original artifacts/flags; no retrospective repair.
- Policy measured population differs from completed frames → label population and cross-match without silently selecting convenient frames.
- Causal source/decoder effects are confounded → report observed critical-path envelopes and list a separately controlled follow-up.
- Root Windows checkout is dirty and outdated → no reset, blanket staging or source overwrite; preserve local histories and use the clean merged-source worktree.
- Full sibling freeze source allowlists differ from current source → retain explicit renewal requirements for DeepStream, OpenVINO GVA and Savant, then original32/Q4/full gates.

## Migration Plan

Additive CLI/docs only. Existing benchmark commands and accepted raw evidence remain unchanged. Ordinary test discovery includes new focused tests without manifest/skip changes. After conformance/CI, sync/archive this new capability and merge the same PR; update current task links to the actual archive path before final checks.
