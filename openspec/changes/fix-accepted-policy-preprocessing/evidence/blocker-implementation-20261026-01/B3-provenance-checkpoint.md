# Narrow B3 provenance checkpoint

Selected production-source provenance now has explicit bounds: at most8192
module entries scanned,256selected records,512safeASCII bytes per identity/path,
2MiB per source, and2KiB per complete five-field record. Hashing streams64KiB
chunks and joins held/named before/after identities. Valid descriptor fields and
hashes remain unchanged. This touches fixture provenance only; no production
reader, standalone `_PROGRAM`, receipt schema or consumer predicate changes.

The six-method RED ran against the old helper: one preservation case passed,
eight missing-bound/drift assertions failed, and the oversized-source sentinel
blocked payload copying. Independent review accepted that intended RED, with
childexit1 preserved and complete bounded capture. Afterward, the drift fixture
was made deterministic with an atomic same-length replacement rather than an
in-place update dependent on timestamp granularity. The original RED is unchanged;
the distinct corrected test hash was reviewed before GREEN.

GREEN ran once: six methods passed in0.049s, childexit0, bothEOFs, normal closure,
no forcing/overflow/unknown remainder, raw persistence and returned2072-byte
result write/fsync/close completed. Independently verified hashes:

- provenance8d951ab5ba4e26efe01cc9045556595edb6ae7433c80a98f298b55c05f1e529d;
- GREEN testsdef6a3ea8f0faa813f9bc30157260a252d9f2df3982e661dbc8b0d66275de5e5;
- GREEN stderrb6d89d94d8b5edd54de1d50b11c7b7493ce5889fe56a8d28bdd5f1285bea33d5;
- GREEN result74480b13f6a1b54ac878bb6bb239e7b79f28476bdb8beb578d688adc6616caab.

Both invocations are consumed. Their separate128MiB allowance adds to the prior
640MiB, cumulative768MiB, without cleanup credit. Fresh actual floors and source
review/admission dispositions are retained alongside original channels/results.
The complete B3 metadata/report/outer-reader ledger remains OPEN; this establishes
only one finite term. Exact-source Grok/new-head CI and physical gates remain.

Separately, B2CI atd78b7b18 failed6errors/3failures due to frozen compiler-v1
formatter/source-slot pins. All six CPU targets built and all three real-ELF
default-custody/probe positives passed in that CI; overallCI remains FAILED.
The retained original artifact is3245707B/SHA256
afcfeac3f8972ab44a35034e76976da5422fded514ac9d0d64e70f742a8d1fe3,
artifact12647802119 ofrun40313370100. No physical or task acceptance follows.
The compatibility remedy is a separate prospective amendment; no historical pin,
protected method, old C/D source or qualification receipt has been changed.
