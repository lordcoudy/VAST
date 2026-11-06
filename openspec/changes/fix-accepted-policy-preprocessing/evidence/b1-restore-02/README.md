# B1 restore, attempt 02: restored and verified

This was the one invocation approved in PR #9 comment 6690605558. It ran commit `550bf89c`: guard sha256 `986590bf…2cef` at `--interval 0.5`, and helper sha256 `35643d11…67a5` in reuse mode. It ran as root in Ubuntu WSL from 2026-11-06T17:04:26Z to 17:07:21Z, with run directory `/root/vast-pr9-b1-run-02/`.

The original records are `b1.json` (sha256 `3aa8a6a391e533246320d5bece56e68180bd6c5f699e60ed3bb4f242d3c4326b`) and `guard.json` (sha256 `4054bcb459ce71a5cb9638d5bc620379539122dade72fcff1ed089f2f220dbd3`). Guard exit 0, helper outcome `restored`.

## Stages

| Stage | Time (s) | Result |
|---|---|---|
| Preflight | 2.3 | passed. Desktop `aa8f3d33`/29.8.2 source and manifests read-only; native `1e493309`/29.7.2 with no provider image; ctr client and server v2.3.3/`aad11006`; no native references; three B containers recorded |
| Reuse | 2.3 | the retained archive was the only entry, regular, root-owned 0600, nlink 1, size 10,469,630,464 B |
| Verification | 2.3 → 25.3 | full membership: 55 members, 50 blobs, 10,469,582,904 B of content; sha256 `a55b6e0c…aa9b1` equals the run-01 record; anonymous child annotated `containerd.io/distribution.source.nvcr.io` |
| Import | 25.3 → 173.8 | the reviewed `ctr … images import --local --base-name nvcr.io/nvidia/deepstream --digests --platform linux/amd64 --snapshotter overlayfs --sync-fs <archive>` returned rc 0 in 148.3 s; the archive identity was unchanged before and after |
| Native contract | 174.2 | all pins matched (see below) |

**Native contract.** Docker 29.7.2 `/images/{id}/json?manifests=1` reported:
- Id `sha256:c11befa8…`.
- RepoDigests == RepoTags == `["nvcr.io/nvidia/deepstream@sha256:c11befa8…"]`.
- Size 10,469,582,904.
- RootFS sha `1e0fe0c4…`, env-keys sha `6785bc7c…`, chain ID `583abc90…`.
- amd64 manifest Available, with Unpacked **18,930,790,400**.

The references went from `[]` to exactly the provider. The native container set is unchanged. A re-check through the Docker CLI at 17:08:01Z confirmed the Id, RepoDigests and Size.

**Guard.**
- No breach.
- 700 reads in total: 350 on C: and 350 on E:.
- The longest read took 0.016 s on each volume, and the greatest staleness was 0.502 s.
- The last values were C: 228,797,919,232 B and E: 153,417,408,512 B.

**Remnants.** Both the preflight and the pre-import snapshots, which query the `moby` namespace, show run 01's ingest `tar-blobs/sha256/0874059c…` (339.7 MB, 28 hours old) and the expired lease `124685930-FsqA` still present. After the import, both are gone; the import resumed and committed that blob, and the lease was collected. Nothing was removed by us.

**Correction.** Earlier manual checks reported these remnants as already gone, at 08:50Z and 17:03Z, and PR #9 comment 6690605558 repeated that. Those checks were wrong. The `ctr` flags were passed through a shell variable that arrived empty through `wsl.exe`, so they queried the `default` namespace instead of `moby`. The helper's own snapshots are the correct observation.

**Capacity.**
- C: fell from 258,828,886,016 B to 228,797,829,120 B, a drop of 30.0 GB. That matches packed plus unpacked, about 29.4 GB, plus metadata.
- E: fell from 174,366,334,976 B to 153,417,408,512 B, a drop of 20.9 GB, even though B1 writes nothing to E:. This is the known unexplained external E: writer (design: pagefile or decline). E: stays far above its 23.6 GB breach line.

Retained: the archive at `/var/lib/vast-pr9-b1/`, the run-01 and run-02 directories and all their records. Nothing was pruned, removed, overwritten or retried, and no protected image was touched.
