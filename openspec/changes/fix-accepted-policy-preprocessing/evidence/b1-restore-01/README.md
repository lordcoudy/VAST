# B1 restore, run 01: stopped by the containment guard (consumed)

This was the one guarded invocation approved in PR #9 comment 6658920465. It ran helper commit `f8f4310b` (helper sha256 `d92929b2…ad7b`, guard sha256 `9bfb670a…d3b9`) as root in Ubuntu WSL, from 2026-11-05T13:14:51Z to 13:17:24Z.

The original records are `b1.json` (sha256 `96f394db4484c7ce2e0ec58c3f97c74955fa44ff7863fc42662cae37c8fda26c`) and `guard.json` (sha256 `b078b79cb6e67d20e7af03d72b864845370db370446ade53bf638607bfc15ae7`). The run directory is `/root/vast-pr9-b1-run-01/`.

## What happened

| Step | Time (s) | Result |
|---|---|---|
| Preflight | 2.1 | passed: Desktop `aa8f3d33`, native `1e493309`, containerd v2.3.3/`aad11006`, provider absent |
| Save | 2.1 → 118.5 | `docker image save` wrote 10,469,630,464 B in 114.9 s |
| Membership | 118.5 → 150.0 | passed: 55 members, 50 blobs, 10,469,582,904 B of content; anonymous child annotated only `containerd.io/distribution.source.nvcr.io: nvidia/deepstream` |
| Import | from 150.0 | the reviewed `ctr ... images import` started |
| Guard breach | about 151 | a shared C:/E: statvfs sample did not finish inside its 0.5 s budget, and both values came back unknown |
| Stop | about 151.9 | SIGTERM to the owned group; the helper recorded `interrupted`, native state unknown |

- **Guard record:**
  - breach `{"volume": "C:", "kind": "unknown", "reason": "sample timed out"}`;
  - 152 samples; the largest gap between samples was 1.938 s;
  - no containers were involved, and no stop failures.
- **Capacity was never short:** C: was about 261–272 GB free throughout, against a breach line of 94.5 GB. The breach is the guard's fail-closed rule that an unknown sample counts as a breach. The sample timed out while the import began reading the 10 GB archive and writing native ingest, both on `ext4.vhdx` on C:.

## Native state afterwards (read-only, 13:17:59Z)
- The `moby` namespace has no image, no reference and no committed content.
- There is one abandoned active ingest, `tar-blobs/sha256/0874059c…`, of 339.7 MB.
- There is one `ctr --local` lease, `124685930-FsqA`, with `containerd.io/gc.expire` set to 2026-11-06T13:17:22Z.
- Docker reports no such image. The three stopped B containers are unchanged.
- The archive `/var/lib/vast-pr9-b1/deepstream-c11befa8.docker-save.tar` (10,469,630,464 B, sha256 `a55b6e0c…aa9b1`) is retained, and so are the run records.
- Free space: C: 261,978,419,200 B; E: 159,462,608,896 B.

Nothing was pruned, removed, retried or overwritten, and Desktop was only read. B1 is **not** restored. This invocation is consumed, and any further attempt needs a new decision.
