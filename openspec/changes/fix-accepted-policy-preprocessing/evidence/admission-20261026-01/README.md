# Default-path admission checkpoint, 2026-10-26

Task 1.5: **HOLD**. Compiler 2.10 and reader 2.12 remain open. No controller
worker/probe, runtime build, compiler stage, reader cohort or genuine consumer
was launched in this continuation. The 3,840-sample milestone is incomplete.
The software input remains `35d28fe7b3eb2bab754e55de1639feb1680c1b9c`.

The human's revised sequence is recorded in `docs/pr9-repair-execution-plan.md`.
The C: worktree, branch, PR9, OpenSpec change and parked D27/Native57 disposition
remain the same. No production code, tests, CI, pins, task checkboxes or historical
receipts were changed by this checkpoint.

## Environment restoration

Ubuntu was stopped but its VHD was attached to Windows as read-only RAW
`PhysicalDrive2`. Starting Ubuntu returned `ERROR_SHARING_VIOLATION`. The human
confirmed that maintenance was finished and asked for diagnosis. An ordinary
`Dismount-DiskImage` did not release the attachment. The checked elevated
operation detached only the exact diagnosed VHD after rechecking Ubuntu stopped,
the disk path, read-only state and RAW type. Its original 283-byte result is
`stale-ubuntu-detach.original.json`. Ubuntu then started successfully; the
existing C: checkout's `.venv` reported Python 3.12.3.

On Ubuntu startup, native `docker.service` was running, but Desktop's integration
proxy had replaced the native `/run/docker.sock` path. Read-only attribution
showed the native engine-id file still named `1e493309-3767-45fb-9078-05b838bdfd80`;
the three retained B containers were stopped with restart policy `no`, and native
containerd had no tasks. Independent reviewer `/root/capacity_review` supported
restoring the existing service/socket contract without a design amendment.

Before restarting the two native units, a fresh exclusive hardlink
`/run/vast-pr9-desktop-api.sock` retained Desktop's existing socket inode with the
same root:docker ownership and mode 0660. An owned-socket check first demonstrated
that a hardlink remains connectable after removal of the original name. Desktop
Info through the real alias was then verified as ordinary UID 1000. The alias
introduced no listener, privilege grant, proxy process or configuration edit.

Only native `docker.socket` and `docker.service` were restarted. Subsequent
read-only checks established:

- `/run/docker.sock`: native `1e493309-3767-45fb-9078-05b838bdfd80`, Docker 29.7.2,
  counts total/running/paused/stopped = 3/0/0/3, the same three retained B IDs.
- `/run/vast-pr9-desktop-api.sock`: Desktop
  `aa8f3d33-e1dc-4ed2-ad06-488b46b332d0`, Docker 29.8.2, counts 0/0/0/0,
  193 registered images and 433 build-cache entries.

Future Desktop operations must explicitly select its alias and verify that
daemon identity; the ordinary default socket now reaches native Docker. The
alias retains an inode, not service availability. Proxy replacement, stale alias
or native-path reclamation requires a fresh hold, not another implicit restart
or endpoint fallback. Restarted process/socket epochs and this boot cannot reuse
old execution admissions.

## Fresh blocker and capacity limits

At 08:58:11 UTC (11:58:11 Moscow), `observations.original.json` records:

- Physical C: available 239,943,577,600 B; physical E: available 258,472,050,688 B.
  Both Windows volumes were separately observed with 4,096-byte allocation units.
  The C: floor remains 42,949,672,960 B. Ubuntu's 880,667,168,768 B virtual free
  space supplies no additional physical backing.
- Native Docker reports **zero registered images**. Inspecting the exact selected
  compiler provider returns exit 1 / `No such image`.
- Desktop can inspect that same pinned provider reference: ID
  `sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759`,
  reported size 29,400,323,407 B and 47 layers. Its presence on Desktop does not
  qualify the native provider, authorize a fallback or establish restoration.
- Desktop reports 65.03 GB of images and 26.17 GB of build cache already present.
  These are current observations, not reclaimable headroom credits or bounds on
  future layer/cache/VHD growth. No image or cache was deleted or offloaded.

Zero registered native images does not establish deletion of underlying content.
No historical image-loss cause, content-store reconstruction or provider transfer
is claimed. A concrete offline restoration, if selected, needs its own exact
manifest/config/RootFS/Size checks and prospective copy/unpack/cache/backing
liabilities before allocation. No pull, alternate provider or old ELF was used.

Independent read-only source review returned HOLD for whole-chain capacity:

1. `accepted_policy_original_custody_fixture_v1.py:148-167` still constructs
   unbounded source/reply material and invokes host `cc` with unbounded capture,
   no timeout and no compiler temporary/output quota. The approved D15 bounded
   compiler exists separately; it is not wired into this constructor. Its source
   builder and usable entry require actual fresh bindings, complete qualification
   and a current whole-chain admission. A later ELF reader ceiling does not bound
   an earlier compilation peak.
2. The retained 20,037,997,204-byte subtotal remains conditional on metadata
   geometry. The 512-ASCII-byte identity/path assumptions, descriptor/file counts,
   parity inventory and encoding allowances require exact current inputs or
   enforced bounds. It is not an admitted whole-chain figure.
3. Current runtime context unions total 139,040,089 logical bytes across four
   systems. Offline A/B still executes pip, native compilation and BuildKit
   export. Context bytes or historical layer deltas alone do not bound scratch,
   unpack/export/cache and physical VHD growth, including retained failed builds.
4. D16's implemented reader payload limits are 4 MiB per reader / 16 MiB across
   four complete fixtures. Enclosing logs, proof/result copies, exact inherited
   deadlines and actual ownership/EOF/persistence qualification remain separate
   liabilities and admission gates.

The remedy is to finish the approved bounded-compiler integration/qualification,
resolve the exact selected provider availability, close metadata and surrounding
reader output terms, and fund the complete build/cache/VHD and retained-failure
peak against fresh physical capacity. Existing retained bytes are already in the
free-space baseline; no prospective cleanup credit is assumed. Missing terms are
unknown, not zero. The additional 128 KiB ceiling for this small admission record
does not authorize the dependent chain.

## Evidence scope and verification

The six fresh Docker metadata commands used the already-approved bounded
observation function: at most 8 KiB stdout and 1 KiB stderr per command, each with
a 10-second deadline. Their complete returned stdout/stderr/statuses, explicit
endpoints, source hashes, UID, kernel and boot ID are retained in the 5,076-byte
`observations.original.json`, SHA256
`336719b9e4b1d03dcd336600fdada1ae3890331d58a5b4a77151f13eb252e357`.
Its head was supplied and rechecked by Windows Git at the same C: worktree.

The first metadata collection failed before creating its evidence directory:
Linux Git could not interpret this Windows worktree's `E:/...` gitdir pointer.
No successful capture or qualification is attributed to that failure. A later
fresh read-only collection used the enclosing Windows Git result. Separately,
supported Linux Git with explicit `--git-dir /mnt/e/STUDY/VAST/.git/worktrees/VAST8`
and this C: `--work-tree` returned the same exact head. The worktree metadata was
not rewritten. Future Linux Git users need an explicit supported resolution.

This checkpoint supplies environment/access and missing-input evidence only.
It does not approve compiler/reader execution, source changes, physical controller
acceptance, image renewal, genuine consumers, archive or merge. Dedicated semantic
conformance CI remains absent; CI was not redesigned. Q1, Q4 and the full campaign
remain separate later stages. All existing untracked files and failed evidence
retain their original disposition.
