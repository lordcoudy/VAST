# Purpose-Built Original Custody Fixture

The new test-only producer is
`tests/fixtures/accepted_policy_original_custody_fixture_v1.py`, SHA-256
`f1b37fa796714770443d79da89e70d4b5a017b279a9591791439f2e5d2b5fd28`.
Its adjacent focused test is
`tests/test_accepted_policy_original_custody_fixture_v1.py`, SHA-256
`fe1a4cb84722bea5c78469eb8f3f3c57a2c2d8946d147822d0adeff4658b37c4`.

The constructor holds one compiled single-link Linux ELF and a genuine AF_UNIX
socket pin. Optional exact image-inspection/probe objects are encoded as
artificial command-boundary replies. Actual default runtime-input command
functions execute this ELF; unknown image inspection refuses. No custody,
runtime-input, process or container validator is mocked or replaced.

For each fresh operation, the producer calls the stock original-process capture,
measurement-container custody wrapper, held runtime child launcher, stock native
transfer, and both process/container cold validators. It returns native,
process and container physical descriptors and their real validation results.
Coordinator-produced native payload bytes are copied unchanged, without decision
projection or resealing. Complete native domain semantics remain an independent
consumer-fixture responsibility; this helper does not claim to validate them.

The focused test first failed because the helper module was absent (after fixing
the local focused-run script import path). It then passed with two fresh
GStreamer/OpenVINO operations sharing the exact same engine descriptor, dynamic
expected image metadata, observed child/terminal facts and stock transfer.
The second test executes real default inspection and both native device-probe
command boundaries and checks exact objects and unknown-image refusal. Its
first run found an incorrectly expected exception class in the new test; the
test was corrected to the actual stock runtime-input error class, not a
production validator change.

Final bounded command, canonical WSL Python 3.12.3, `TMPDIR=/var/tmp`:

```bash
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest -v tests.test_accepted_policy_original_custody_fixture_v1 tests.test_publication_operational_container_custody_v1
```

Result: **15 tests passed in 14.052 seconds**, zero skips/errors/failures.
`git diff --check` passed. All workers here are local actual Linux children;
the external engine CLI/daemon replies remain an explicitly artificial test
boundary. There were **no real Docker calls, no physical GPU/device execution,
no campaign promotion, and no real-Docker qualification claim**.

This evidence does not complete the default production consumer fixture:
complete 37-operation capture-plan/native semantics, guardian journals and
authority/lifecycle, reconciliation, default promotion/materialization/cold read,
packaged execution and current-image qualification remain separate gates.
