## Why

PR #2 completed the selected GStreamer component recovery, but the current plan and progress still advertise completed actions as pending. All four real arms largely miss the 100 ms deadline; their existing raw evidence must explain where latency accumulates before another expensive campaign or speculative runtime change.

## What Changes

- Reconcile PLAN.md, progress.md, BENCHMARK_RECOVERY_PLAN.md and the component runbook with the actual merged release, preserving every earlier dated snapshot and failure.
- Provide a small public offline diagnostic command for retained frame events and optional native policy evidence. Report completed-frame critical-path envelopes, absolute deadline/coverage/drop populations and available policy-path timings.
- Explicitly distinguish recorded zero queue spans produced by promotion from unobserved true queue wait and worker service; report missing information as unknown.
- Execute and independently review diagnostics on all four accepted CPU08/GPU02 arms without rerunning the benchmark or modifying original evidence.
- Retain the full 32-cell qualification, Q4/1,120-operation and 5,600-arm/2,800-pair campaign as distinct incomplete obligations with concrete prerequisite gates.

## Capabilities

### New Capabilities
- `component-latency-diagnostics`: Read-only, reproducible explanation of completed-frame latency envelopes and their observation limits, with truthful current roadmap/status.

### Modified Capabilities
None. The existing benchmark-launch-preparation scientific, physical, campaign and acceptance requirements remain unchanged.

## Impact

A new standard-library-only Python CLI and focused unit tests; current documentation and a compact diagnostic report. No engine/model calls, runtime image rebuild, benchmark rerun, dependency upgrade, workload/deadline change, original-evidence rewriting or new qualification/publication authority. Existing mandatory CI discovery/build/native checks apply. One new change/branch/PR follows the completed PR2. The user's standing carte-blanche and explicit instruction to verify then execute authorize continuation after an independent exact-commit planning review recorded in that PR.
