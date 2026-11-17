# Sealed host build-context extent: controlled source checkpoint

Base commit d950d8124960e82db88ae5cc08775d9683b047a4, same C: worktree,
codex/fix-accepted-policy-preprocessing and DraftPR9. Task1.5 remains OPEN.

The materializer previously wrote chunks until EOF and only then compared the
destination extent with the source's sealed size. It now computes remaining bytes,
reads at most min(existing1MiB chunk, remaining+1), and rejects an oversized chunk
before digest/counter/write. The final size/source snapshots, exclusive creation,
short-write loop, immutable metadata and returned hash/manifest remain unchanged.
This closes one per-file copy boundary; aggregate context/manifest-reader heap,
compiler/pip/RUN temps, image/export/cache/snapshot growth and S96 fit are separate.

Reviewed working identities:

- scripts/materialize_runtime_build_context_v3.py:11045B,
  SHA25692a6b41416f7c3497e14a47a4b10cf98d570931716585816e812bae7a6bd21dd.
- tests/test_runtime_build_context_v3.py:14139B,
  SHA2561fc1b6d85a11911c9fdc2f992a670474a6effd1fe51bcb1a897b6732619392a0.
- preparatory_checks.py:22544B,
  SHA2563e16ed76f4a8e1e959c4a21286ef47029bc7e3bc63f999bce3e02618c5b81b68.
- B4-build-context-extent-recipe.proposed.md:7297B,
  SHA2564bc05d818b8c4f9a268ee706cb7b610fe1eda508a09c33843c101376a1d87c43.

Independent source/capacity reviews preceded the selected invocations. New tests
use controlled finite read streams but actual tiny file writes/retained witnesses;
they do not reproduce real concurrent source growth or a Docker build. The eight
old custody/metadata tests remain byte-identical.

1. Initial RED launch failed before admission/copies/directories/child because
   PowerShell reparsed an already converted DateTime via a localized string. Its
   original command/tool return survive. Independent review cleared only a named
   launch2 using a direct DateTime cast/UTC conversion; all six test namespaces
   were still absent. No RED test was replayed.
2. buildextent-red-01 ran2 methods/four intended assertion failures in0.054s, no
   errors/skips. Retained destinations contain1/5/5/5B against0/4/4/4B sealed sources.
   Actual D16 capture closed normally with child1, both EOFs, no overflow/forcing/
   unknown remainder, and completed2378B result write/fsync/close.
3. buildextent-green-01 ran12 methods in1.183s. All new four methods passed; the
   unchanged metadata success assertion failed0555 versus0444 on C:9p/DrvFS without
   metadata. The phase remains failed/consumed. Normal D16 capture and2173B result
   persistence are retained. All seven new roots survive; the old fixture's
   TemporaryDirectory witness was deleted by its unchanged cleanup and is unavailable.
4. After separately reviewed numeric/filesystem admission, buildextent-posix-green-01
   selected the same unchanged12 methods/15 fixture vectors/17 direct calls on
   canonical /var/tmp in the qualified Ubuntu ext4 root. It passed in0.110s, no
   errors/skips. The actual outer return confirms child0, normal complete D16 EOF/
   closure, no late result and completed2190B result persistence. The actual source
   worktree/captures stayed in C:. No mount/configuration or assertion changed.

All seven new ext4 roots remain. Bounded original reads verify14 source/destination
files of0..4B, single-link regular files and destination mode0444. The first C:
witness-export helper failed on an invalid Split-Path parameter combination after
creating only an empty directory. Its command/error/empty root remain. A corrected
GetDirectoryName export used a separately named fresh directory, read at most5B,
required exact known size/SHA before any write, and copied14 files with CreateNew,
Flush(true) and post-copy size/SHA checks. No original was moved/deleted. The extra
empty node and both export-command forms fit existing correction FS/tail maxima.

Byte-exact archives, including actual outer returns and failed originals:

- B4-build-context-extent-originals.zip:23 members,155038B,
  SHA256d7df11c923eed45c77025989259b16b2d336cf6a880ee34b08c847700ab2ddf5.
- B4-build-context-witness-originals.zip:22 C: witnesses,4385B,
  SHA256acd1d4de76323987d756bd9d848df2d9b95cce4b55f0d5a70fcaa20fdc0ea64e.
- B4-build-context-posix-originals.zip:28 members including14 copied ext4 witnesses,
  82971B, SHA256f4795c891627074a324a3b676946bf9794f66a07baeef0800dff0648f215ea80.
Each uses the existing2MiB ZIP/16KiB manifest ceilings and preserves loose originals.

The original four command forms total28851B/32768B rounded<64KiB. The correction's
three actual command forms total17763B; with one Git copy35526B raw/49152B rounded
<64KiB correction tail. The first diagnostic grouping command returned unavailable
sum fields; these totals are derived from its complete observed per-file lengths,
not from those unavailable fields. No measurement is rewritten as a successful sum.

The reviewed32MiB direct tranche reserves original20.25MiB rows plus7.5MiB from
11.75MiB slack for the single ext4 correction. Full1MiB ext4 case scattering plus
192 metadata pages conservatively adds448MiB physical VHD liability; prior fixed
ext4 metadata/journal/control charges stay. Derived C70.990234375GiB<80GiB, above
unchanged40GiB floor; E65GiB/full64GiB pagefile and source/Git192MiB remain. Cumulative
direct reservation is2080MiB=2181038080B. No sharing/cleanup credit is used.

Post-outcome archive review, exact-commit source binding, configured Grok and new
exact-head CI remain required before source acceptance. No task is newly checked.
Compiler/reader admissions, bounded producer failure transport, whole1.5, actual
controller probes, atomic lifecycle repair, runtime A/B/refreeze/parity/tensor audit,
genuine cohorts, nine integrations, conformance/archive/final review/merge stay OPEN.

Independent exact-local-commit review subsequently cleared all28 committed blobs
at f35d3b34fa940609decf3df4d0a638817704f531, including73 B4 and eight additional B3
archive members. The raw proposed PS1 remains byte-exact in its ZIP and loose
original; it was not duplicated as Git text because its extra EOF blank fails
diff-check. No original was normalized. Current committed source hashes still match.

The single configured Grok review completed CLEAR for exactf35d3b34, actual model
grok-4.6-build, one turn/end_turn, exit0/133.753s. It inspected supplied source;
it did not execute tests, proofs or runtime checks. Its64054B prompt,12765B stdout,
9240B stderr and actual enclosing tool return are preserved in the separate reviewed
<=1.5MiB ZIP. The configured max4 turns/600s/channel caps were unchanged; no
continuation was used. Fresh Windows/Linux guards passed before invocation.
Configured review does not close the open gates above. New exact-head CI and
source-stage delegated approval still remain required.
