# Finalization allocation bounds, scoped B3 checkpoint

The previous finalizer let pandas reopen unbounded frame/ingress paths, eagerly
read11evidence files per qualification cell just to hash them, and opened candidate
output before encoding its unrestricted JSON. The fixed two-table adapter now
captures frames<=512KiB and ingress<=1MiB under existing custody, verifies them,
then admits exact producer columns, positive row counts<=985/986, column counts
and conservative quoted-record bounds before pandas. Pandas receives the admitted
original bytes via BytesIO with nrows986/987. Producer-valid tables cannot be
truncated by that ceiling. The quoted-row budget is no larger than the producer's
existing conservative scalar/CRLF reservation; scientific parsing stays in pandas.

Hashing streams capture=False under the selected11fixed roles: nine sidecar CSV
caps and64MiB each for policy_decisions.csv/publication_policy_decisions.jsonl.
Unknown roles refuse. Candidate output is pre-counted/encoded by the existing
fixture report guard under8KiB including the platform newline allowance, before
exclusive open; compact ASCII JSON+LF and existing fields/hashes remain. A short
text write now refuses. This is bounded encoding, not completed durability or
enclosing-deadline qualification; those callers/writers remain open B3 work.

Initial finalbounds-red-01 used test8748B/SHA
4ebb245e6b82783e1353553a2c23ea175d2e4bf3a8965f1e8cd714c967c0c84d,
runner14525B/SHAbb98bee5096a9bc1a769643b4c99a5b840d5067d460f85ddcff861d6e9016f31
and original physical29076B/SHAa2a0fb83cb559761183b5e97a509e0bae58566553961799c75b3b4f33f3e7108.
It ran10methods with3failures+8KeyError fixture errors,0.085s. The authored row
lacked a calibration descriptor and could not reach the controlled finalizer.
This result is retained consumed/unaccepted, not counted as full meaningful RED.
Result2187B/SHA7a45b61d38060e59194bf8a65394dd086ad37dcc8d5af3e13371900576fe7089.

Only91B of test data changed: add row.descriptors.calibration.path. Corrected
test8839B/SHA78fa73de664ca4232a623264a961baf6b0dd39cc6092c6f1eb297031604f58c9
and runner14844B/SHA67398161d1aa704f7b4362ca144f8b6d09ee566fb689dcfae41c0e495651f613
were separately reviewed/priced/copied before fresh finalbounds-fixture-red-01.
Physical source stayed unchanged until that meaningful RED:10methods/10failures,
no errors/skips,0.071s; the valid canonical-candidate control passes. Result2211B/
SHAfa8890af7d4885c87634f7df76205993e61a863aa1c3dd877d003301e449bd73.
It demonstrates missing CSV/hash/candidate admission rather than broken fixture
arguments; initial errors and originals remain intact under their original names.

Independent source review accepted physical31557B/SHA
6ad53880abcf884ded9546187fd1b01989f482960fd7cd561706ca5b57cc27c0
and unchanged corrected test/runner before unused GREEN. GREEN10passed,0.051s,
no errors/failures/skips. Result2190B/SHA
0a53e0dc495d7449ffe69b085f5c7f77e1c646698fb05767fb053b8a09d5a27e;
stderr2039B/SHA98fe61a9cf18af6b4a60848d0bf0e3261e2a60a610473f9e342e16871791d25e;
stdout0. All three phases have normal owned closure, both EOFs, no forcing,
signal, overflow/discard/unknown remainder/deadline breach, and completed channel/
result write/fsync/close. Pandas parses only bounded memory data in these tests;
filesystem, finalizer and writer effects are doubled. No actual candidate file,
default finalizer, scientific qualification, compiler, Docker or real reader ran.

The24-member NoCompression ZIP/manifest retains15phase artifacts and nine pre-run
copies,224018B/SHA1e880ebb4fbb6672c40c93d764776f9ec8a47106757b4d98ed79b9cb68293007.
All originals remain; bounds were checked before ZIP creation. The initial32MiB
and separately reviewed16MiB test-correction tranches make cumulative1616MiB=
1,694,498,816B, derived C70.099609375GiB<80GiB above40GiB floor. E65GiB/full64GiB
pagefile and192MiB cumulative source/Git cap remain. Fresh Windows/Linux/config/
pagefile/USN/UUID/boot/source/collision checks preceded EACH invocation. All three
names are consumed. Independent outcome/archive review is CLEAR.

Exact-commit source review, configured Grok and latest-head CI remain separate
required checks. Candidate persistence, outer cleanup, caller clocks, metadata
heap/preparse inventory, full B3/task1.5/B4 and genuine/default3840-first gates stay
open. No protected image, service/storage configuration or46/24task state changed.

Independent exact-commit source/evidence review is CLEAR at
6fccc220c46649c690430b6c5ae5445ba7193361. Configured Grok reviewed the pin/finalizer
interaction in the same session01a17ad0-d506-76d3-95b3-ddb27d4f3f5e. Initial client
reached600s with zero captured stdout and no completed EOF/verdict; actual parent
failure and channel prefixes remain incomplete. Same-session continuation then
returned final scoped CLEAR at6fccc220, actual modelgrok-4.7-build without settings/
model override. It did not rehash sources or accept outcome/physical claims.
Seven originals including initial parent failure are retained in
B3-physical-finalization-source-grok-originals.zip,153305B/SHA
7c2eb515f90b490a346fb845a76d198498e14e5f1a11c31216d5175f6e49794e,
with manifest and local originals. Residual timing/durability/heap/helper/borrower
and physical-epoch limitations remain open as stated; no stage/final/physical
approval follows. Current-head CI and later materially changed source remain
required; new consumer-clock work is outside that exact physical-module opinion.
