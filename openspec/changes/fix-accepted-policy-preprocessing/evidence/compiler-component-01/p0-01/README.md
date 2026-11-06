# P0 committed-snapshot proof (user-run, root, read-only)

The user ran these commands in the WSL Ubuntu shell on 2026-10-16 and pasted
the output into the session. They are retained verbatim, minus the `sudo`
password prompt line:

```bash
sudo ctr -n moby snapshots --snapshotter overlayfs info sha256:583abc9004877e79fd0f5d47e4c7cff085b8538fdcbff0c070e044bdb0b43c1a
```

```bash
sudo ctr -n moby snapshots --snapshotter overlayfs ls | head -60
```

- `p0-info.original.json`: `Kind` is `Committed`, and `Name` equals the
  provider's computed top chain ID. The label
  `containerd.io/snapshot/cri.manifest-digest` equals the pinned amd64
  platform manifest `sha256:34e56b46...eb59`.
- `p0-ls.head60.original.txt`: the first 60 lines only, as run. It lists the
  same chain ID as Committed, with parent `sha256:3c8de051...`, and one
  committed child snapshot from a derived image. It is not a full inventory.

Result: the committed snapshot exists, so creating a container by ID needs
no unpack. B1 may proceed under the gate-1 approval (PR #9 comment
6210515683). Nothing here removes, prunes or changes any snapshot or image.
