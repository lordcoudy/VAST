# Bounded recovery diagnostics evidence

This evidence records only the diagnostics scope approved at planning commit
4666e9e21741eda1f2f5b72d5a2de4bba6a7cd1a, PR9 comment6180355014. It grants no
backing rehearsal, restore, image upload/deletion/offload, capacity, qualification
or final PR acceptance. All original files remain in their existing locations.

`diagnostic-cohort.original.v1.tar.gz` preserves all 3,810 frozen regular files,
including 982 zero-byte files, failed runs and every source snapshot under the
original full relative paths. Archive SHA256:
1f030c72abb90c4d9f693682885e0642d0b93e7d8f2d083cf2a0b3f34eb27520.
`members.original.v1.json` maps each path to its exact size and SHA256. TAR.GZ
replaces the initially proposed ZIP because full ZIP path headers exceeded the
unchanged 16 MiB retention allowance; no member was omitted to fit.

The independent final technical review is inside the archive as
`independent-guest-outer-review.final.v1.md`, SHA256
a41beb6ace994c53cc786e5fd1ab916b51ff38ccc760f9f5e9cd05a0c90edcf2.
It clears current guest99e41f29 and unchanged native/outer helpers, the fresh
31-test reporting composition, the focused original RED/corrected GREEN and all
six diagnostic scenarios. The separate native component has 25 passing cases
and shape checks. Historical guest8f and its bad acceptance=true counterexample
remain failed synthetic evidence; they are never live authority.

`verification.original.v1.json` records the archive author's full member
readback, source before/after equality and original retention accounting.
`independent-retention-review.original.v1.json` records root's separate complete
archive/source/catalog comparison with no extraction or original mutation.
The two retained verification scripts are exact copies of their ignored controls.
Later index/script retention adds small bytes; the final scope receipt accounts
for every added file without changing those earlier original receipts.

The original failed cold03 cause remains unresolved. Real command/daemon closure,
empty-engine full archive restore, all 227 image Id/ordered RootFS/Size/tag/digest
equality, whole-chain capacity and exact human image/action confirmation remain
open. Synthetic success supplies none of those gates.
