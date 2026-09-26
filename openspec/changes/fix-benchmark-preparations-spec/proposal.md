## Why

VAST cannot safely begin its full benchmark while A269 qualification is failed, native payload integrity is unchecked at the producer boundary, guardian diagnostics lose request provenance, and retry defaults conflict with the agreed execution policy. This change makes preparation independently verifiable and stops before launching the full matrix.

## What Changes

- Repair the native payload/hash binding, enforce the existing 67,108,864-byte limit before copying, and execute its regression in normal Linux test discovery.
- Retain bounded integrity-failure evidence and correct request accounting without changing the historical guardian lifecycle schema or weakening rejection.
- Default full-publication service/supervisor unexpected retries to zero; preserve transient exit 75 recovery and permanent exit 78 stops.
- Integrate the OpenVINO GVA and GStreamer Custom native-probe qualification path, which has never completed a cell: type-safe reset queue reads, a 4096-task container ceiling, decode artifacts limited to real factories, identifier rules that admit every frozen branch name, native policy identities taken from the frozen qualification-v2 capability manifest for both resources, and a container-engine pin the qualification bundle can satisfy. Require nonpromoting pre-check replays of native-probe cell types before a 32-cell attempt.
- Renew affected images, parity, source identities and final exact-byte tests; then perform a fresh 32-cell qualification, Q4 560 phase-A runs/boundary/560 phase-B runs and 280 sizing pairs.
- Obtain dated cloud-capacity attestation, complete current preflight, and produce a validated, unstarted service package and launch handoff.
- Replace corrupted command examples and stale operating guidance with a checked, self-contained preparation runbook and evidence checklist.

## Capabilities

### New Capabilities

- `benchmark-launch-preparation`: Verified repairs, reproducible prerequisites, complete qualification/Q4, capacity admission, and an explicit handoff before full-run execution.

### Modified Capabilities

None. The current main-spec inventory is empty.

## Impact

Native client/header and tests; guardian/bridge attribution and failure evidence; service/supervisor defaults; affected image source closures and identity fixtures; operator documentation. No new external dependency is proposed: native hashing uses the existing GLib dependency.

The current runtime is a dirty working tree based on 168bde19ecde1d084ed339df38bd3b5befabef82. All 44 files in the prior review baseline still matched on this review. The planning PR must not include unrelated pre-existing code or imply a clean checkout reproduces this runtime.

## Scope and relationship to prior proposal

The user explicitly selected: repairs, tests, fresh qualification, Q4, capacity and preflight; stop before the 5,600-arm run. Success means preparation evidence is accepted, not that the benchmark has completed or can never fail.

The three supplied documents under prepare-repeatable-full-benchmark are reference inputs. This newly named change owns the preparation scope for the present request. Do not apply both changes to duplicate the same fixes, rename/archive the older change, or mark its full-run tasks complete. Its later full-run methodology is preserved as a downstream obligation.

The earlier benchmark-plan.md has corrupted headings/variable names (for example PROJECh_ROOh and PYhHON), introduced by the prior document-editing step. It must not be copied as executable guidance. This change supplies clean templates and checks them against current CLI contracts.

## Non-goals and gates

This proposal writes planning artifacts only. Later implementation requires spec approval in the PR at the exact reviewed commit and a separate apply request. It will not start/install an enabled full-run service, execute any of the 5,600 full-matrix arms, run final verify/finalize/export, or claim publication completion. Qualification and Q4 are included after approval.

Keep A269 retired and all failed evidence intact. Dated operator capacity remains unresolved. Repository CI configuration was not found; separately agreed CI setup and latest-commit checks remain necessary before merge. Prior public-push rejection is not resolved by creating this new change; publication needs explicit authorization.
