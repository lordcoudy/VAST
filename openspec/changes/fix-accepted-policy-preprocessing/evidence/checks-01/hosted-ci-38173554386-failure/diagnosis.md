# Original Hosted CI Failure: Exact 591 Source

Run: https://github.com/lordcoudy/VAST/actions/runs/38173554386 (attempt 1).
The GitHub plugin verified head `591a93e778a9a7839da6278326d215e24e91ea45`,
event `workflow_dispatch`, and workflow `.github/workflows/ci.yml`.
The run completed with `failure`; no retry, rerun, cancellation, or workflow
change is represented by this record.

## Original Evidence

The `Original host prerequisite diagnostics` job (114571050809) succeeded.
The `cpu-checks` job (114571050971) failed at step 12,
`Check source, build six CPU targets and execute test discovery`.
The subsequent original artifact upload succeeded.

Artifact 11716156808 is retained unchanged as
`vast-cpu-checks.original.zip`: 2,759,587 bytes, SHA-256
`b0adadb76b8c9a64ca397bae42b9fd934ec75a28cecff93ce74c05ac1da2eabd`,
matching GitHub's digest. It contains the original report, child report,
stdout/stderr logs, lifecycle and observer traces, namespace diagnostics,
native build outputs, and model acquisition records. No extraction,
normalization, or receipt rewriting was used for the retained ZIP.

## Exact Failure

`report.json` records `successful=false`, unchanged tracked source,
`raw_checkout_bytes_match_commit=true`, and this propagated failure:
`RuntimeError: original full-suite child/observer failed; see original lifecycle/trace`.

The actual child ran 3291 tests: 1 failure, 0 errors, 88 skips, no expected
failures or unexpected successes, and no missing required successes.
The sole failed test is
`test_image_input_eol_rules_v1.ImageInputEolRulesTests.test_every_image_input_has_an_explicit_line_ending_rule`,
at `tests/test_image_input_eol_rules_v1.py:48`. Its real assertion reports
three image inputs without an explicit line-ending rule:

- `scripts/publication_policy_qualification_fragment_validation_v2.py`
- `scripts/publication_policy_qualification_pilot_validation_v2.py`
- `scripts/publication_policy_qualification_transaction_validation_v2.py`

This is a repository source predicate failure. It is not waived by artifact
retention, prior local tests, or a subsequent correction. A corrected commit
requires its own checks; this run remains failed.

## Check Boundaries

Discovery selected 3300 tests: 3291 portable tests and 9 separately identified
integration tests. `integration_executed=false` in this hosted run. The 88
audited skips comprise 10 `existing_retired_schema_migration` and 78
`platform_or_explicit_physical_prerequisite` entries; all retain
`acceptance_claim=false`. No CI selection or skip policy was changed here.

All 529 Python syntax and 16 Bash syntax entries succeeded. Native configure
and build commands exited zero and built the six targets
`vast_native_gst_probe`, `vast_checkpoint_source`, `gstadaptivescheduler`,
`gstvastanalyticsterminal`, `gstvastanalyticsqueue`, and
`gstvastcheckpointprefixqueue`. GStreamer package checks and the `appsrc`,
`queue`, and `videoconvert` factory checks exited zero. Model acquisition
completed for the eight pinned OMZ XML/BIN inputs; its original command
exited zero and it explicitly does not claim hardware acceptance.

The real observer was ready, completed 36 of 36 responses, observed EOF on
both channels, and used neither forced SIGTERM nor SIGKILL. It recorded child
return code 1 and `original suite child did not exit zero`; descendant
quiescence is explicitly `not established by original-child status`.
Negative-control signal stack traces in the original logs do not replace
this terminal observer record.

The initial namespace diagnostic recorded a permission-denied
`/proc/self/setgroups` operation and did not establish policy-denial proof.
The existing scoped profile's load and unload were both verified with
original zero return codes and released held file descriptors. These facts
do not turn the sole failed source predicate into an infrastructure success.

`hardware_acceptance=false`. Hosted CPU checks do not establish actual
NVIDIA decode, SDK runtime readiness, model parity, full policy acceptance,
Q4, qualification, or Q1 campaign authority.
