# B4 build-context metadata implementation checkpoint

Same change/branch/C: worktree/Draft PR9. Source parent is
b98b4aced156784c883887910f9e481e867b8d44. This checkpoint records a controlled
metadata slice, not task1.5 or physical/build/consumer acceptance.

## Change and conformance scope

Approved B4 design's every-selected-writer boundary requires bounded context
metadata before copying. Independent scope review confirmed this narrow repair
needs no formal amendment. `scripts/materialize_runtime_build_context_v3.py`
now admits at most3 manifests,8192 bytes/128 entries each, union128, printable
ASCII paths<=256 bytes/depth8, members<=32 MiB, sum<=40 MiB, parents<=896 and
hash/result metadata<=64 KiB before its first destination write.

The manifest reader opens O_NONBLOCK/O_NOFOLLOW where supported, immediately
validates the held descriptor, checks remaining+1 before accumulation and retains
read/close causes. Count and path checks precede collections. Incremental scandir
rejects unexpected/duplicate/unsafe entries before collection or descent.
The existing copy-helper body and all12 old test bodies remain unchanged.
Schema, ordering, same-input hash semantics, copied bytes, timestamps and modes
are preserved. The changed helper source belongs to all four contexts; their
aggregate identities necessarily renew. No identity pin was replaced here.

This supports the requirement "Validator repairs renew affected qualification
readiness" and its whole-chain-capacity scenario without accepting that scenario:
the enclosing builders, whole peak and genuine renewal remain unqualified.
The15 new tests cover manifest size/growth/truncation/nonblocking flags, descriptor
substitution, entry/path/count/union limits, member and aggregate pre-copy limits,
read/close causes, exact manifest/path boundaries, unchanged successful output
and refusal before recursive inspection of a foreign directory. The unchanged12
cover source aliases/escapes/drift, injected directories, modes/timestamps/hash,
symlinks and sealed copy extents/short writes. These are controlled helper checks;
no compiler/pip/Docker/build/storage mechanism is mocked into acceptance.

## Actual one-time RED and GREEN

RED selected8 methods/14 vectors against old11045-byte materializer
SHA256`92a6b41416f7c3497e14a47a4b10cf98d570931716585816e812bae7a6bd21dd`.
It produced exactly14 intended assertion failures,0 errors/skips,0.113s.
Old methods accepted missing limits or reached copy-time validation after prior
writes; no missing API/import or exhausted mock is claimed as meaningful RED.
Stderr15634 B/SHA`9eb31541045d750baa2dbe19e3e3471210549364647a01d826a5d92b21df92d2`;
stdout0. D16 child1/outer0, actual result write3162 B/fsync/close.

GREEN ran all27 methods once on qualified Linux /var/tmp: PASS,0 errors/skips,
0.258s. After retained RED the oversized-file method gained no-open/no-read
tripwires; this disclosed strengthening creates no new fixture. Stderr5221 B/
SHA`fec3c2ed7dc7d98c9af40afd6954d646a2f85a0e3a1b831552c0fa71b1c309af`;
stdout0. D16 child0/outer0, actual result write2169 B/fsync/close.
Both phases have complete EOF/owned closure, raw fsync/close and no forcing,
overflow, unknown remainder or exceeded deadline. No phase was replayed.

Exact GREEN/current source:

- materializer14914 B/SHA`91facc220267f6db25446e0b209e4b615dee44280bd5cd6bef1cc0b3a694ca5a`;
- tests25544 B/SHA`8779c4c1182f983bff3a3ef52ae1af53c37368c618ff5192b4aff0712f1a2d73`;
- runner25964 B/SHA`5fda9ca4e1d4fff91e22bc263f8ab7358f995c828bb0acb805e9b3415da8ba40`.
Each phase copied exactly those three reviewed source roles before execution;
RED62059 B and GREEN66422 B, each below128 KiB.

Both independent source reviewers accepted the scope, actual RED and sole GREEN
source; capacity reviewer accepted exact launchers/rosters subject to fresh guards.
Exact-commit/outcome/archive reviews, configured Grok and new-head CI remain
separate gates. No delegated source approval is asserted by this checkpoint.

## Capacity and retained originals

New32 MiB direct pair makes cumulative direct2224 MiB=2332033024 B. The extra
2 GiB physical ext4 scatter carries all old/new case creation forms without
cleanup credit: conservative225 files/217 directories,442 nodes,1395 MiB derived
liability plus653 MiB slack. Cumulative scatter2496 MiB; derived C additional
73.130859375 GiB<80 GiB above40 GiB. E65 GiB/full64 GiB pagefile, source/Git192 MiB
and all earlier journal/map/VHD terms remain charged. The proposed Grok private
profile32 MiB is NOT included or admitted.

Fresh guards preserved boot`df4955d9-4762-42b4-a55b-0106ba3786f8`, Ubuntu/root
UUID`c3d3247e-154c-43c0-a9fe-2b91d6db7666`, /dev/sdf/ext4, UID1000, original
21-byte WSL config,4 KiB units,<=24 GiB RAM/exact6 GiB swap and physical floors.
Each exact admission includes actual Windows/Linux observations and source pins.

Bounded post-run inventory retains45 roots/127 files/121 directories,30797 logical
bytes/127 file-data4 KiB units under the two /var/tmp phase roots. This is later
point inventory, not peak proof or cleanup credit; full authored creation forms
remain priced. Original fixture roots stay on ext4 and are excluded from ZIPs.

Each public ZIP has exactly9 members: command, admission,3 source copies, outer
tool return,2 raw channels and result JSON. Loose originals remain retained.

- RED93764 B/SHA`e38fdc3171f4f0ee34ac38a4e2c3ec05480eaf36eceb20e28d46b4fe21475309`.
- GREEN86784 B/SHA`a656bd31411e33e6f80aaded8514e3c69f50df6e6d6db743c8380e4891cb994c`.
Manifests bind each member. All18 CRC/SHA/size/loose-original/source joins were
independently verified by the capacity reviewer, including both actual result
persistence returns. Both ZIPs/manifests and one Git copy total367270 B.
The NoCompression/CreateNew4 MiB guard and member1 MiB caps were unchanged.

The six exact reviewed admission/archive scripts include one final blank line.
Narrow .gitattributes rules preserve their bytes and suppress only blank-at-EOF
checks for these six names and their future archived copies; all other whitespace
checks remain active. No CI configuration changed.

## Remaining gates

All four current unions fit the narrow metadata envelope:92/95/92/98 files,
32568737/36939641/32569183/36978756 B; largest member18240889 B.
This read-only sizing is not a context materialization, build or whole peak.

Builder shell mapfile/closure reads occur earlier and remain open, as do pip and
compiler scratch/output, image/cache/export/VHD growth, native/Windows diagnostic
boundaries, custody/clock qualifications, S96 fit, actual compiler/reader/controller
admissions and whole1.5. The prior failure-frame repair at b98 passed CI40522309252;
its configured Grok gate is still open. The old Grok invocation remains held for
internal persistence; proposed read-only-profile capture and fresh login are
unqualified. No Grok model or private copy/ACL/probe has run here.

Tasks remain24/46. No controller execution, real build, image operation,
runtime renewal/refreeze/parity, identity-pin replacement, genuine3840/3968/126016/
29/20/42 cohort, nine-integration acceptance, OpenSpec archive or merge occurred.
D27/Native57 remains parked; freshQ1/Q4/full campaign remain separate.
