# Producer clock-loss source checkpoint

Same C: worktree/branch/change/PR9; base674c98636f63256c00bf38c1d72d92843605acd7.
Task1.5 stays OPEN. This corrects only two audited B3 clock losses.

Positive _fresh_json now catches the post-writer clock failure once. The existing
report-refusal wrapper retains the original returned facts object, original clock
exception as primary/__cause__, an empty secondary tuple and copied original cause
codes plus fixture_report_clock_unavailable. It neither mutates returned facts nor
calls an unavailable clock late, rewrites the file or resets the inherited deadline.
Negative finalization guards the same original observe_end query with remember/
break, preserving any body/report primary and distinct clock error while stopping
remaining source calls. Normal and expired-clock behavior stays unchanged.

Final working bytes:

- Positive19312B, SHAbadddb7bed83b4652413c1014852b725e2c288ba010bd5a4cdad916b38edf79c.
- Negative15765B, SHAe7b5fffb84e83b61ebe035fd6c89a4e3cb620a7e13b381fbbc1fc3e67b89c2ea.
- Report tests10547B, SHA79e092f6cb6a5d3d3fc1e9b59eb82a27017d7c492138e33d190917e671213734.
- Failure tests8535B, SHA74333ad95e9378c9a736fd94973bf75461c4757c18f9f00da1b2e1f8e9f44742.
- Runner23307B, SHA974afbfd4b108a8452d153e49826abac75d6f04c8b7e335bd38cf41624270be8.

Independent policy/test/finite-capacity reviews preceded each selected invocation.
RED producerclock-red-01 ran2methods/4 intended assertion failures in0.152s:
two missing actual writer-facts cases and two original-primary masking cases.
There were no errors/skips, missing APIs or mock-exhaustion failures. Actual D16
owner/EOF closure, expected child1 and2450B result persistence are complete.
GREEN producerclock-green-01 ran both modified modules:12methods/31 controlled
vectors PASS in0.203s, noerrors/skips. Actual enclosing return confirms child0,
normal complete ownership/EOF/persistence2257B and no late result. All external
effects are doubled and both case directories remain empty. This is not a real
clock/filesystem fault or compiler/reader/consumer qualification.

One24-member byte-exact ZIP retains both raw channels/results, admissions, actual
outer returns, all ten source originals and three command forms including the
unresolved proposal. No original was normalized or replayed. ZIP<=2MiB and its
manifest<=16KiB, loose originals preserved. Five pre-RED sources76911B and five
GREEN sources77466B each fit128KiB aggregate/64KiB per-file limits.
B3-producer-clock-originals.zip is206899B,
SHA256eb69df33f7fd6cc80497a99cc8578b7be58edf79ef66fa5b97c4adc945e719d0.

New16MiB direct pair brings cumulative2096MiB=2197815296B and derived C additional
quote71.005859375GiB<80GiB, retaining the40GiB floor, E65GiB/full64GiB pagefile and
source/Git192MiB reservation. No case/VHD allocation, cleanup or sharing credit.
The compiler, D16 owner/encoder and all other protected source bytes are unchanged.

Working outcome/archive review, exact commit binding, configured Grok and latest-
head CI/delegated source approval remain required. Full arbitrary-exception
pre-stringification/CLI frame transport, consumer assessment/reader-state and
sidecar-location retention, actual environment/heap/compiler/reader admission,
whole1.5 and all controller/runtime/genuine/final acceptance remain OPEN.

Independent exact-local-commit review cleared all14 committed blobs at
f40cd1b47db5911382e79e7ea4452827f62038de, including the24-member raw archive and all
unchanged working source/test/runner joins. The one configured Grok review then
completed CLEAR for that exact commit, actual grok-4.6-build, three turns/end_turn,
exit0/132.491s. It read source only and ran no tests/proofs/CI. Its62259B prompt,
18306B stdout,6372B stderr and actual outer return remain in the separate<=1.5MiB
review ZIP; no continuation was used. Fresh Windows/Linux/source guards passed.
Independent review of those final four members and latest-head CI/delegated
source approval remain required. Broader gates above are unchanged.
