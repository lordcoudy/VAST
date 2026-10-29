# B3 selected-source metadata RED/GREEN — separate128MiB

This adds exactly two commands, `metadata-red` then `metadata-green`, each once,
for the same six-method module `tests.test_accepted_policy_fixture_metadata_v1`.
The earlier five B2 phases remain consumed. Production code is unchanged before
RED. No real compiler, Docker, runtime, coordinator, socket or consumer is called.

Cases cover the256-record exact boundary and257th refusal, a selected source path
over512safeASCII bytes, four escaping/nonASCII module identities, a2MiB+1sparse
source with an assertion sentinel preventing payload read, source drift during
hashing, and unchanged complete descriptor fields/hash for a valid small source.
Each method has one controlled temporary root: six per invocation,12cumulative.
Inputs include a deliberately overlong path below1024bytes and a sparse logical
2MiB+1file. Do not treat those deliberate negative inputs as valid fixture paths.

Reserve8MiB per root including all failed forms:96MiB; two captures stdout/stderr
1MiB each plus one complete copy:8MiB; source/Git/intermediates4MiB; bounded
result/outer/review records and copies4MiB; directories/allocation8MiB. Total120MiB,
sealed at **134,217,728B**. Add it to the earlier640MiB without cleanup credit:
cumulative **805,306,368B**. All allocation units must be <=4096B.

Fresh Windows physical C: and actual Linux views must show C: available at least
**43,754,979,328B** (40GiB+allallowances), selected ext4 **1,879,048,192B**
(1GiB+allallowances), before namespace allocation. The existing amended literal
runner checks those floors, one300second deadline including15seconds closing,
unchanged D16channel ceilings,32KiB result and2KiB outer persistence protocol.

Expected exit1 alone is not RED. Independently inspect retained verbose output
for all six named methods, intended missing bounds/drift failures and the valid
preservation case, with no import/runner failure substitution, before GREEN.
GREEN additionally needs exact implementation-source review and fresh admission.
Keep failed originals/actual statuses; no retry, source-roster expansion or local
positive compiler case is funded. This proves portable metadata behavior only;
the complete B3 metadata ledger, outer-reader work and task1.5 remain incomplete.
