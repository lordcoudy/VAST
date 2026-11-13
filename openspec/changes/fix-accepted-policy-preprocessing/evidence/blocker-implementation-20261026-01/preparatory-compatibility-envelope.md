# Finite compatibility recipe — independent conditional CLEAR

Product source7efaa5227c981658d314c1cfec722df6053ee91f received independent exact
source CLEAR and configured Grok source CLEAR. Both exclude execution admission,
CI success and physical acceptance. The later floor-only runner8611B/SHA256
11f2cab5aa519e8c1be2f4211b12f99196c4f5ca25e1787c557119054d94b7de received
independent capacity/source review by /root/capacity_review: conditional CLEAR
for this closed recipe, pending fresh facts before each invocation.

Only fresh phases compat-current-01 (89 controlled methods) and compat-legacy-01
(nine unchanged historical failures) are selected. The three host-cc positives
are excluded. D25/D26/D27 inspect retained data; the controlled-main test mocks
P0/process/socket effects. This is no operational D27 replay. The total150
temporary roots count131 existing controlled,12 new and7 historical roots.
The largest clone is730355B/16files/9directories;32nodes*4096B makes861427B,
below1MiB/root. Failures stay charged regardless of ordinary test cleanup.

The new cumulative file tranche is239MiB within256MiB:150MiB roots;16MiB
source/Git;16MiB raw captures/copies;1MiB result/status/copies;16MiB review
captures/copies;16MiB ZIP/copy;8MiB CI ZIP/copy;16MiB for<=1024 outer nodes.
This adds to the consumed768MiB file allowance, making1GiB. No automatic retry,
extra invocation, source expansion, Git auto-GC/repack or cleanup credit is
included. Future Git commands use process-scoped gc.auto=0/maintenance.auto=false.

## Actual physical backing, distinct from file sizes

Independently derived C: subtotal69.521484375GiB, reserved within80GiB:

- 37.5GiB:150MiB guest allocation maximally scattered into separate1MiB blocks.
- 17.072265625GiB: all17482MiB fixed ext4 metadata payload ranges, including
 every already-backed range and the complete journal, with no allocation credit.
- 4.6875GiB: one extra scattered metadata page for each of4800 possible nodes.
- 6GiB: full guest swap, plus1GiB for its container controls.
- 1GiB: all cumulative direct-C forms, including the prior768MiB.
- 268MiB: Ubuntu VHD12MiB controls and all256 possible bitmap slots.
- 2GiB host bookkeeping:80GiB/4KiB clusters*32B/run*3 live/undo/redo forms is
 1.875GiB; complete C-USN max+delta40MiB and outer metadata16MiB fit the balance.

Unused reservation is headroom, not permission for more operations. E: reserves
65GiB: the full64GiB pagefile maximum plus816MiB mapping forms
(64GiB/4KiB*17B*3),192MiB cumulative source/Git/proof forms and16MiB outer
metadata. E-USN must remain inactive. No existing pagefile allocation is credited.

The independent VHD reader's facts below are a DERIVED REVIEW REPORT, not an
original tool receipt or coherent active-disk snapshot. It read the explicit
C:/Users/s-a-balashov/AppData/Local/wsl/{733a6524-960b-47be-ac8d-deaf948be3c7}/ext4.vhdx,
length153849167872B, virtual GUID9ecc1fe8-4990-4c33-8703-109651fbd2fb,
1TiB virtual/1MiB payload/512B logical/4096B physical geometry. Metadata region
offset2097152/length1048576; BAT3145728/9437184; log1048576/1048576.
The active header has a nonzero log GUID, so EVERY fixed range is funded.

Ext4 UUIDc3d3247e-154c-43c0-a9fe-2b91d6db7666 has8192groups,8192inodes/group,
256B/inode and512inode-table blocks/group. Journal inode8 is1GiB in eight
initialized128MiB extents and one tree leaf. The GDT/BAT scan's union of inode
tables, bitmaps, primary super/GDT and journal is17482distinct payload blocks;
1386present/16096nonpresent is diagnostic only, not a baseline credit. The root
read-only CLI corroborated UUID/journal geometry. Its actual returns and the
USN queries are in compat-backing-observations.original.json. Get-VHD was refused
by the ordinary caller's permissions; no elevation/retry or setting change ran.

## Fresh conditions before EACH phase

C: and Linux/mnt/c free>=128849018880B (40GiB floor+80GiB).
E: and Linux/mnt/e free>=70866960384B (1GiB floor+65GiB).
Temporary ext4 available>=2147483648B; all allocation units<=4096B.
Confirm actual mount/VHD identity, C-USN32MiB/max+8MiB/delta, E-USN inactive,
only E pagefile/max65536MiB, and unchanged .wslconfig21B/SHA256
6efea9e209212784c22240a6019c17cee3bd31011840250c76c3bb31e2c7eea1.
Actual MemTotal<=24GiB and SwapTotal==6GiB are checked by the runner before mkdir.
Windows physical observations remain required; guest virtual free is no credit.

The existing one300s deadline includes5s TERM+5s KILL+5s final; D16 stdout/stderr
remain1MiB each, result32KiB, outer status2KiB. One-use fresh paths, normal child/
descendant closure, both EOFs, no forcing/unknown/overflow and complete raw/result
write/fsync/close proof are required. Any changed fact, cap, unknown extent,
failure or incomplete persistence holds further work. Stop for source repair and
a separately reviewed fresh invocation; never replay a consumed name.

This funds only local controlled compatibility checks. Task1.5/compiler2.10/
reader2.12, real Docker probes, runtime renewal, genuine consumers, final CI,
archive and merge remain open. No image action or physical workload is admitted.
