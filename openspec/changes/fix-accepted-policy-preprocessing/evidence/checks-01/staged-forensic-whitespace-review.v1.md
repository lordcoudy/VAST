# Staged Original-Capture Whitespace Review

Review scope: the 245-path staged slice based on source A16, before the next
commit. This records a warning disposition, not a green unfiltered check,
consumer acceptance, final CI, or permission to change original evidence.

The root's original unfiltered `git diff --cached --check` tool returned
outer exit1 and its display was truncated. The independent native Git read
returned exit2: 872 output lines, exactly436 warnings and436 contexts.
Every warning is trailing whitespace on an original CRLF line in the nineteen
finite JSON captures listed below. Each actual physical line ends in one CR
before LF; after removing that single CR for analysis, none has trailing
space, tab or another CR. All are plain stage0 mode100644 files, with cached
`text=unset` and `eol=unspecified`; physical raw Git-object hashes equal
their staged blobs. No unparsed, non-CR or nonforensic warning was found.

Independent `git diff --cached --check -- .` with only nineteen exact
`:(top,exclude,literal)<path>` exclusions passed native exit0 with empty
output over the remaining226 paths. That includes all normal production,
fixture, test, script and document changes and every other captured output.
The index SHA-256 stayed
`12eb0d4b30ce753b97cc2cfda4ff21b211b44e68e0ccbd2e788e750f20d1d4e8`
through that read-only review. Tool evidence: original ec44d6; independent
bf4c9e and4abb36. The subsequently added review document and final staged
state require their own ordinary whitespace/index-byte checks.

Disposition: preserve the nineteen original byte sequences. Do not normalize
them, suppress warnings through repository configuration, or exclude whole
evidence directories. The unfiltered warning remains disclosed. Previous
committed warning dispositions and all historical failures remain unchanged.

## Exact Original Paths

Paths below are relative to this evidence directory's parent (`evidence/`).
The integer is the number of original CRLF warning lines, not a line citation.

- `checks-01/a16-completed-originals-retention-control/apply-01/command.v1.json`:27
- `checks-01/a16-completed-originals-retention-control/apply-01/original.result.v1.json`:21
- `checks-01/a16-completed-originals-retention-control/independent-01/command.v1.json`:21
- `checks-01/a16-completed-originals-retention-control/independent-01/original.result.v1.json`:20
- `checks-01/a16-completed-originals-retention-control/plan.command.v1.json`:23
- `checks-01/a16-completed-originals-retention-control/plan.original.result.v1.json`:15
- `checks-01/a16-completed-originals-retention-control/planning-02/plan.command.v1.json`:23
- `checks-01/a16-completed-originals-retention-control/planning-02/plan.original.result.v1.json`:15
- `checks-01/integration-a16-original-control-01/command.v1.json`:24
- `checks-01/integration-a16-original-control-01/original.result.v1.json`:35
- `consumer-01/consumer08-retention-control/apply-01/command.v1.json`:28
- `consumer-01/consumer08-retention-control/apply-01/original.result.v1.json`:22
- `consumer-01/consumer08-retention-control/independent-01/command.v1.json`:22
- `consumer-01/consumer08-retention-control/independent-01/original.result.v1.json`:21
- `consumer-01/consumer08-retention-control/planning-01/command.v1.json`:23
- `consumer-01/consumer08-retention-control/planning-01/original.result.v1.json`:14
- `consumer-01/readonly-preflight-01/command.v1.json`:19
- `consumer-01/readonly-preflight-01/independent-readback.v1.json`:32
- `consumer-01/readonly-preflight-01/original-result.v1.json`:31
