# Bounded Fixture Transport Readiness

This evidence repairs fixture setup only. It does not establish complete
guardian, F1, identity-policy, campaign, or Q1 qualification acceptance.

The immutable source-591 isolated minimum run 06 completed with original exit
code 1 at 2026-10-11T21:29:16.509930Z. Its stock 37-operation planner completed,
but the actual runtime-input materializer refused the analytics front socket
because it was bound and not listening. Larger run 07 was not launched. Frozen
source and all failed outputs are preserved.

The production runtime materializer performs two actual front transport probes,
before and after materialization. Each creates a real AF_UNIX/SOCK_SEQPACKET
client, connects, checks the exact listening transport and physical socket pin,
then closes without a request. The managed fixture correction listens before
the actual materializer and accepts/closes exactly those two pending clients
before handoff. It restores blocking mode. The later guardian lifecycle and
control responder are unchanged; no new thread or validator override is added.

The focused regression uses explicitly identified spies for expensive setup
providers only. Its physical sockets, production socket pin reader and
production live transport predicate are actual. It proves the early ordering,
unchanged socket pin, empty accept queue at handoff, and repeated probe/drain
cycles. This is not a substitute for the full physical-input producer.

- `red.*`: original exit 1, two tests, one error. The prepared fixture is refused
  by the actual production transport predicate with ConnectionRefusedError 111.
- `green.*`: preserved original exit 1 from the test spy's missing nested engine
  asset directory. This is not passing evidence.
- `green02.*`: original exit 0, two tests passing in 0.010 seconds, after only the
  test spy's asset parent creation was corrected. The fixture helper remained
  unchanged between the two green attempts.

Each result retains the exact command, start/finish times, original stdout and
stderr, exit code, source hashes and explicit scope. The tests execute with the
canonical Python 3.12 runtime, `-B`, `PYTHONDONTWRITEBYTECODE=1`, and native
`TMPDIR=/var/tmp`. No Docker, GPU or physical inference is executed.

After the original run 06, the actual frozen source's stock
`run_ci_checks.verify_committed_bytes` independently verified all 11,757 tracked
paths with original exit 0. Its exclusive raw outputs remain outside that
source at `/var/tmp/apf06-readiness-591a93e778a9a7839da6278326d215e24e91ea45/after.*`.

Complete consumer positives and negative-run authorization remain pending.
No source-591 retry or edit is implied by this bounded test result.
