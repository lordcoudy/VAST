# Finite producer failure-preservation regression recipe

This implements the already approved B3 first/distinct-secondary requirement;
it introduces no source-capture, provider, compiler or storage policy. The
capture-policy review is separate. No local test execution follows until this
closed recipe and actual test source are independently reviewed and fresh guards
pass. Existing task statuses and physical admissions remain unchanged.

Only tests.test_accepted_policy_fixture_producer_failures_v2 is selected for RED.
Its closed roster is three methods/eight controlled cases: positive primary with
report failure (two cases: distinct error and same object); negative primary with
failure-report, after-proof, after-report or final Git failure (four cases); and
negative primary followed by expiry (two cases: after-proof/head not started).
External preparation/observation, Git/proof, file queries and report writes are
doubled; no child, temporary directory, fixture, model, Docker or provider runs.
The complete producer mains and exception/finalization control flow run unchanged
for RED. New interfaces alone are not the reproduced failure. Assertions require
the original exception object and ordered, identity-distinct secondary objects,
and prohibit final source spawns once the original observation clock expires.

GREEN selects the same module plus existing execution-argument8/11 and refusal-
argument5/8 regressions. Their existing controlled preparation/consumer doubles
remain. The three new methods/eight cases make16 methods/27 cases total. Missing
or changed roster refuses rather than silently extending this recipe. Output
retains original failures and complete statuses through the unchanged D16 owner.

Allocate a separate32 MiB pair inside the existing C80 GiB preparatory allowance:
20 MiB for two phases' complete1 MiB/channel +2 MiB result,2 MiB runner proof and
enclosing returns/parent logs;6 MiB source originals/one ZIP/manifest;1 MiB case
filesystem ceiling (expected0);1 MiB directory/allocation/copy rounding; and2 MiB
slack. Each source copy <=64 KiB, aggregate <=256 KiB per phase, at most10 copies
per phase. Commands <=32 KiB each/64 KiB combined, including the retained template;
all actual forms are measured before execution. No automatic replay or cleanup.
The source/Git192 MiB reserve remains separate and unchanged. Cumulative direct
reservation becomes1968 MiB=2063597568 B, within C80 GiB while preserving40 GiB;
E65 GiB/full64 GiB pagefile, Linux memory/swap and filesystem guards remain.

Use fresh producerfail-red-01 and producerfail-green-01 namespaces only, retaining
test/runner/both-producer/argument-test/gate/reader originals. Reuse the established
finite preparatory launcher and Python/unittest runtime; prove exact copied source
bindings, original deadline, normal ownership/EOF and returned persistence facts.
Seven intended failing cases and one unchanged same-object control, with no
errors/skips, qualify RED. GREEN must
pass all27 controlled cases, with no real-consumer claim. Source-stage independent
review, configured Grok and exact-head CI precede source approval; task1.5 and all
actual compiler/reader/controller/runtime/genuine/final gates remain OPEN.
