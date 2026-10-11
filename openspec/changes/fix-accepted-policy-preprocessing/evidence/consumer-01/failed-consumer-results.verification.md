# Original Failed Consumer Retention

The parent independently reviewed and authorized plan SHA-256
`8da8e787cb0958629be105c5454602db19b2b93dfe2dbcca61c9fd5905415378`
and helper SHA-256
`50e7555f763ba94be32605930bb8402d69ab120350267310ec4e65cd606be915`.
The helper reuses the unchanged reviewed snapshot/strict-JSON primitives
at SHA-256 `01e4d5bfe1738167e8ec1da5b45104e349b2c5052fddc89ea71b5ba92bd4b6ed`.
This is technical approval for managed-only retention, not semantic consumer
acceptance, user approval, or campaign authority.

## Original Apply

`run_failed_consumer_retention.sh` syntax-checked and applied the exact reviewed
plan once. Its SHA-256 is
`70deabd482320cf87336180bf672a0ae7f236cecc964abd64d01e05f2064b272`.
Original return code was zero, from `2026-10-11T21:46:25Z` to
`2026-10-11T21:46:26Z`; stderr was empty. Original stdout SHA-256 is
`09a7e88123081daae642f49676b664e126f28d598e2233423a4ff5f907925020`.

The fresh managed `failed-consumer-results/` retains exactly 41 files and
96,574 bytes: 15 control files for each original attempt04/06, both original
`producer-failure.v2.json` files, and nine original before/after/check-only
readiness files. The provenance catalogue `failed-consumer-results.v1.json`
has SHA-256
`7074faf20e699030605d8b7cea6e11f08f76868507f3508f8d4ee6245661a6e4`.

An independent read-only execution subsequently rehashed all 41 destination
files against their originals and verified all 41 recorded original source
physical epochs unchanged, then rechecked exact SOURCE591 HEAD and clean
tracked state. Its original return code was zero; its saved stdout is
`failed-consumer-retention-control/independent-verification.stdout.json`,
SHA-256 `72a8bf50adfa1f355e33413ff27168f4d8c4a83388f2a930bf4263e41e8ecca9`.

No file was written into SOURCE591, a historical root, or a CI clone. Only the
managed output/control directories and documentation were created. Two narrow
active/archive `failed-consumer-retention-control/** -text !eol` rules preserve
the new original control bytes, following the parent's explicit authorization.

## Original Outcomes Remain Failed

Both original consumer commands exited 1 at exact source
`591a93e778a9a7839da6278326d215e24e91ea45`, with unchanged source state and
`both_complete_consumers_passed=false`:

- Attempt04: `original stock operational source parent directory mutated during custody`.
- Attempt06: `analytics execution endpoint is not a reachable live SOCK_SEQPACKET transport: [Errno 111] Connection refused`.

These original refusals were not overwritten or reclassified. Before/after
source-byte verifier and check-only preflight originals exited zero, but do
not establish a complete consumer positive. No measured-sample acceptance,
physical inference, or Q1 campaign acceptance is claimed.

Operational37 plans and huge input/native/runtime trees, both execution-code
closure JSONs outside the requested original-control/failure subset, live
full-suite outputs, any new source snapshot, and nonexistent larger attempts
05/07 were excluded. The original 3840 expected-count field is metadata for
the attempted 30-sample fixture, not a claim that those samples were accepted.
