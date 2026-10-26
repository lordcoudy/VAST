# Bounded fixture I/O adapters

Existing PhysicalRootCustodyV1 now hashes consumer/assertion descriptors without
whole-file capture, keeping the original path/size/SHA fields. Consumer decision
and ingress roles explicitly pass64MiB/1MiB. Runtime probe JSON and duplicate
receipt/calibration reads capture under64MiB; probes require JSON objects.
Guardian companion hashing uses its existing1MiB file role, independently of
the256MiB lifetime group cap, and preserves size AND digest checks. Production
custody/reader/predicate/recorder implementations are unchanged; no new loader.

Independent test review added a same-length digest-drift control before RED;
source9149B/SHA57db27d19e263c3dc2233a54a8e639b2b6be246e427d78c5a9640ed4e44aa25d
was copied/authenticated before execution. Source/capacity reviews accepted the
literal9methods and finite allowance before fresh physical admission. RED ran
once against original3b324/3e89/6cb055modules:7intended subcase failures and
3passing control methods,0.017s,no errors/skips. Both reviewers accepted the
retained exact failures before implementation.

Independent corrected-source review accepted consumer15753B/SHA
f40b77e53dfa4b1a3b2034508fb5eb14ae29d6728c0f532ca7947fa187794bb3,
assertions7700B/7d9a5dae76383ac1c38502b714b21b36f2126e83b00e41e2e06d22a461f924a2,
journal6407B/842dfb9df87019b80b51a46949b7283077736dddd133da4c2f4d8663d88bd069.
The same nine methods passed9/9,0.004s,no errors/skips. These use tiny custody,
coverage predicate, recorder and writer doubles: they check I/O adapter wiring
and preserved outputs, not actual custody,21genuine refusals or whole consumers.

Both phase names are consumed. Normal D16 owned closure/EOF, no forcing,
overflow/discard/unknown/signal or deadline overrun, complete raw persistence.
Outer returns prove2172B/2175B result writes/fsync/close; result SHA256:
71c913078df0e58a3bee11d9359e22daa08a4f4821ef36c090e8ccac5197face;
091a98cd0898f6338953e56efa1b40af7d55bcb83ff7a30d7dcaf9f1fe5e61e7.
The13-member ZIP/manifest preserves exact raw channels/results/admissions/outer
returns and pre-run source. Reader runner11735B/e377... was recovered AFTER
outcomes by reversing only the next literal extension; it matches its earlier
admitted hash/size exactly and is marked recovery, not a pre-run capture.
No original was normalized or removed.

Fresh Windows/Linux source/floor/runtime/config/pagefile/USN/mount/UUID/boot
checks preceded EACH invocation. The reviewed57/64MiB tranche brought then-
cumulative direct forms to1424MiB, derived C69.912109375GiB inside80GiB above
40GiB floor; E65GiB/full64GiB pagefile and192MiB source/Git cap remain. No
test files/roots/realFD/payload were generated and no cleanup credit was used.

Real custody capture still has chunks+join+raw JSON+decoded-object costs, with
exact selected inputs and full VM24GiB/6GiB swap to be admitted. Native-header,
physical fixture hashes/reads, caller Git/failure/persistence/clocks, authority
forwarding and predecessor reads remain open. The independent complete remaining
audit is retained separately. Exact-commit/Grok/CI review, full B3/task1.5 and
actual compiler/reader/Docker/runtime/genuine validation remain open;46/24 stays.
