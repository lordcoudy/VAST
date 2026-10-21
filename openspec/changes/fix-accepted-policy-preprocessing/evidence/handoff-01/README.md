# Repair To New Qualification Handoff

Status: incomplete technical handoff. This records existing approved task5.5,
not a new qualification specification, source acceptance, launch authorization
or final repair review. Pending identities must be replaced only by observed
results and exact human-reviewed commits, never inferred from this document.

## Integration Boundary

- Repair change: `fix-accepted-policy-preprocessing`, Draft PR #9,
  https://github.com/lordcoudy/VAST/pull/9. Human specification approval is at
  `299c9c0eefb83fe3031096b0e96527236678a4d2` and recorded before implementation
  in PR comment6112617121.
- Current implementation/check source: `a16f243e7e80f093342ccdddf717d59d6d46f0a8`.
  Final archived repair commit, its exact-head checks and explicit acceptance:
  PENDING. A16 is not a substitute for those final gates.
- Repair base is retained `codex/qualify-full-benchmark`, closeout commit
  `4219f3e5ed818a508b3fb032b8310181bab16ce5`. PR #7 is closed/unmerged;
  inherited implementation is absent from master and has not received merge
  authorization through this repair-only review. A future integration must
  disclose and review that inherited code and its actual target.
- Stopped PR #7 root remains
  `/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a` at
  `d1a78805dd41f9f946e3f6c4ca673bfeced228b5`. Attempts1-4 failed; attempt5 is
  unstarted. Its old tasks6.2,7.1-7.6,8.1-8.2 remain incomplete. Do not restart
  attempt5, reopen that PR, edit its stopped runbook, or archive it as complete.
- After repair implementation/checks/conformance, archive and final exact-head
  review, create a distinct qualification branch, OpenSpec change and Draft PR
  from the explicitly accepted repaired baseline. Its specification must be
  approved at an exact commit before implementation or launch. This handoff
  does not supply that approval. Merge requires separate authorization.
- Completion of repair section6 (tasks6.1-6.2), including committed/pushed
  sync/archive, exact archived-head checks and conformance, resolved warnings
  and final approval, is required before Q1.

## Preserved Build Authorities

Actual immutable physical build root:
`/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a`, build commit
`aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795`.

Fresh runtime tags use `:accepted-policy-repair-20261011a`. Their actual A/B
image IDs are:

- DeepStream: `sha256:c41fa1c967cf43e1d10f95a64205cf6ec3de79ec7a3802aa9e6a395718425046`.
- Savant: `sha256:4f073ad30b6e0588cbb0675ed3b53fb7f17a182759d5f8ade94361bf01c790cb`.
- OpenVINO/GVA: `sha256:61bfedeb4f6e74dfde3650375fb3f048c5ded32b5b252497394c44f098afd2ce`.
- GStreamer/custom: `sha256:8208fb4ee35f14cfc1d191baf5c9b35b213fdfbc955697b6d6b6cdd9b304d60e`.

Exact physical receipts, commands and controls are retained in
`../physical-01/physical-results/` and `physical-results.v1.json`. Twelve
canonical/materialized/determinism tags remained unchanged. The derived
qualification image patch retains `candidate_binding_eligible=false` and its
two worker-identity refresh blockers; it is not acceptance authority.

Fresh model parity completed 480 executions / 32 groups and independent
revalidation of 1,920 execution members and 960 tensor files. Actual acceptance
receipt physical SHA-256 is
`394acefdaafbe202e2efea62f36a6da393f62555950fccd466772f5d5edc9e64`;
its distinct semantic identity is
`67cb06e0e1a922d63085966988b4100813119749358c6433e85b57df06645398`.
Independent audit physical SHA-256 is
`75922812dde1281dc57f7969d5cd5bd3d32fa6cd10e34a6638b8e54ce51fb95b`.
The unchanged physical graph remains under
`artifacts/accepted_policy_repair_20261011a/model_parity_v4/`.

A16's independent source comparison proves all 128 runtime build inputs and
all five native/worker input contexts unchanged from the retained build,
67 guardian sources and 93 qualification sources. Actual host-only changed
closure paths are the GStreamer and OpenVINO runtime pin modules, not every
member of the four-path allowed set. Native/worker builds were not silently
rebuilt or rebound. Repeat the same input comparison at the final commit;
any actual package/native change invalidates dependent readiness and requires
new builds and authorities.

A16's newly produced 93-source execution-code closure has semantic identity
`5c70c1265e3eaf0fb7742c39d391c5c756c5131495e29a3ac9da084b6727c6ac`
and physical file SHA-256
`7eb06189ccbd194a626bb60722262e3a5d8e4fbbfa32efe30aefe85a1dc4a444`.
Both actual producer and cold CLI succeeded. A subsequent qualification input
commit requires its own regenerated source/executable/downstream authorities;
do not reuse A16's source closure as if it described another commit.

## Check Evidence And Current Timings

- Deterministic runtime x4 A/B: approximately133 seconds. Physical parity:
  approximately706 seconds, plus independent rehashing. These are repair
  measurements, not a Q1 wall-time prediction.
- A16 focused: 212 tests in131.755 seconds, no failures/errors and one explicit
  live-preflight skip. The separate physical lane executed that test.
- A16 hosted run38179553996: exact head, both jobs successful, CPU runner
  elapsed1523.466 seconds; 3,307 run/3,219 successful/88 exact audited skips.
  All six native targets,535 Python syntax files,16 Bash syntax files and
  three GStreamer factories passed. Hardware acceptance remains false.
- A16 physical lane:9/9, zero skips/failures/errors; outer observation
  `2026-10-11T22:54:50.3465727Z` to `2026-10-11T22:55:21.7606781Z`.
- A16 full ext4: original outer exit0, 3,307 run/3,221 successful/86 exact
  audited skips, zero failures/errors, elapsed2691.151 seconds. Canonical WSL
  runtime, six native targets,535 Python/16 Bash syntax files, stock committed
  bytes and exact whole-mount equality passed. This is A16 only, not final
  archived-head acceptance. Earlier source591's failures remain preserved.
- Complete default consumer fixtures: minimum08 FAILED during fixture-only
  OpenVINO probe setup, before native observations; larger09 was not started.
  The held artificial engine's system-keyed response map does not match the
  stock probe command's image-ID token. Both retained-ELF postmortem calls
  observed exit52 with empty streams; this is a disclosed physical-path
  substitution, not a reconstruction of the original held-FD invocation.
  The fixture-only correction passed a real-ELF/default-probe RED/GREEN and
  independent review:19 bounded tests, zero skips,4.142 seconds. Expensive
  upstream setup providers are explicit spies in that bounded test, not in
  complete consumer runs. No production validator is weakened; a new frozen
  source and complete default consumer acceptance are still required.
  Required minimum3,840,
  larger3,968, genuine126,016 and underfilled-branch refusal, plus default
  lineage/count/decision/reset negative cohorts, must have actual results.
  Artificial test observations and accepted fixture outputs must never enter
  campaign authority. Full identity loading does not replay pilots.
- Final archived-head hosted/focused/ext4/nine integrations, full conformance
  and human review: PENDING. No dedicated automated requirement-to-behavior
  CI gate exists; the local scenario report does not create one.

Original failures and capture limits are explicit in `../checks-01/` and
`../conformance-01/scenario-review.md`. A16 source-comparison inner RC/reports
exist but its original outer tool emission was lost; independent current-state
proof is retained without inventing that emission. Failed evidence readers
and original full/consumer failures remain separate from later checks.

## New Qualification Requirements

The new approved change must record exact inherited baseline, accepted repair
and archive/integration commit, and its own final runbook/input commit. Allocate
new ordinary native-ext4 source/input/run/control/output namespaces; every
required path must be canonical, disjoint and absent before first write.
Verify original physical receipts and tensors through their actual authority
loaders. Historical hashes, source epochs, receipt roots and image tags remain
immutable. Never feed failed attempt-4/G9 raw pilots into promotion or
materialization, and never relabel the126,016 diagnostic as new qualification.

Before launch, repeat required checks on the exact pinned input SHA and stock
host checks, then independently observe zero unrelated containers, VAST
workers and GPU compute jobs; correct Docker daemon and runtime images;
sufficient free space on every required Windows, WSL, temporary and output
volume, including actual Windows backing volumes for sparse Ubuntu/Docker
VHDs, not only their virtual guest free-space reports; disabled AC sleep and
hibernation; and Windows Update pause covering
the refreshed complete estimate plus an explicit margin of at least six hours.
For the historical29-hour estimate, the minimum is35 hours remaining, not
the stopped runbook's12 hours. Refresh the estimate from actual new timings;
do not treat old build-time idle, space or power observations as current.

Current storage blocker: observed C free41,370,685,440 bytes (about38.5 GiB)
backs both Ubuntu and Docker, below the126,016 fixture's40-GiB guard before
additional frozen inputs. Guest virtual free space is not physical capacity.
No large source copy, consumer preflight or launch proceeds until the user
selects storage provisioning and actual backing capacity is rechecked. The
pending options are freeing C to at least80 GiB or reviewing E-backed native
ext4 storage after all current workers close; neither authorizes deleting
historical evidence, migrating existing roots or changing mounts implicitly.

The new runbook must preserve single-attempt failure handling, natural original
exit/retention and no automatic retry. It owns Q1 result acceptance, its own
conformance, archive and final review. Q4, capacity and full-publication
eligibility remain outside this repair; no receipt or check here grants them.
