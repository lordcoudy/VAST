# B1 provider diagnosis — no transfer admitted

Actual read-only returns are retained in `B1.tool-returns.original.json` and the
selected reconciliation in `B1.identity-reconciliation.original.json`. The first
overlong configuration read was refused at its existing bound and is retained;
the subsequent selected-fields read did not enlarge that bound. No compiler or
image operation ran. Metadata source/record allowance was 2 MiB with fresh C:
243,188,940,800 B and allocation unit 4096 B; retained records total under 64 KiB.

Native engine `1e493309-3767-45fb-9078-05b838bdfd80`, Docker29.7.2, now owns
`/run/docker.sock`. Its containerd process/config/defaults agree on
`/var/lib/containerd`; all three pinned metadata blobs are absent in that active
store. Zero image registrations is corroborative, not the evidence for global
content loss. All three retained B containers remain stopped. No claim is made
about other stores or the cause of the prior maintenance state.

Desktop engine `aa8f3d33-e1dc-4ed2-ad06-488b46b332d0`, Docker29.8.2, is reached
only through `/run/vast-pr9-desktop-api.sock`. Its authenticated source has:

- index/image ID `sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759`, 745 B;
- amd64 manifest `sha256:34e56b46f00a2c79acb42bfd4f3a977753607a99179520744389ce40ce96eb59`, 10,184 B;
- config `sha256:fcdeffe3fbac262b2f2760eba8dcc3243a5edf9bdb09b490dd5a00ac1ea56121`, 47,088 B;
- 47 ordered diffIDs, canonical RootFS SHA256
  `1e0fe0c49e48962dc125b19e5b1936c564f1c6a3e00006d5e5cca7dc7ebfd981`;
- exact RepoDigest
  `nvcr.io/nvidia/deepstream@sha256:c11befa808af8270e8ea0d0d7cc7cabbda08a2f496ee30b95f7acba5dce81759`.

The metadata blobs were checked for root ownership, size, single-link counts and hashes under
the actual Desktop containerd process root; sizes and hashes match. Full config
history/environment values are not copied into Git. Only the amd64 platform is
available; the index's arm64 descriptor is not evidence that its content exists.

The size discrepancy reconciles exactly:

`10,469,524,887 layers + 47,088 config + 10,184 manifest + 745 index = 10,469,582,904 B`.

Desktop's manifest summary instead reports
`10,469,582,159 content + 18,930,741,248 unpacked = 29,400,323,407 B`.

Docker's [29.7.2 implementation](https://raw.githubusercontent.com/moby/moby/docker-v29.7.2/daemon/containerd/image_inspect.go)
measures packed content; its [29.8.2 implementation](https://raw.githubusercontent.com/moby/moby/docker-v29.8.2/daemon/containerd/image_inspect.go)
uses total manifest size including unpacked data. These version-specific formulas
explain the observations without changing identity pins. The old native unpacked
expectation 18,930,790,400 B differs from Desktop's snapshot accounting by 49,152 B;
native post-restore observation must still meet the native recipe. It is not waived.

## Selected route for review, held behind B4/B5

Restore offline from the already-local exact Desktop source, preserving its OCI
metadata bytes. Select ordinary digest-specific `docker image save` **without
`--platform`**: a platform-specific export changes its top-level target to the
amd64 manifest in the [installed Docker exporter](https://raw.githubusercontent.com/moby/moby/docker-v29.8.2/daemon/containerd/image_exporter.go).
The digest-specific archive is anonymous; ordinary load alone does not establish
the required RepoDigest.

Native installed containerd is v2.3.3 (actual return retained separately),
`aad11006b869517fcd3009450b6f82da282e1a9b`. Its supported local importer can create
the digest reference using a fixed base name, keep original OCI blob digests and
unpack just amd64. The selected import command, after archive verification, is:

```text
ctr --address /run/containerd/containerd.sock --namespace moby images import --local --base-name nvcr.io/nvidia/deepstream --digests --platform linux/amd64 --snapshotter overlayfs --sync-fs <verified-archive>
```

Docker's archive dependency is containerd v2.3.6. Its exporter generates an
enclosing OCI `index.json`, whose child points to the unchanged original
`blobs/sha256/c11bef...` provider index. The new archive wrapper is not the pinned
provider index and need not hash to `c11bef...`. The import's digest-reference
translation selects the wrapper's child, retaining the original provider target.

The [version-pinned command](https://raw.githubusercontent.com/containerd/containerd/v2.3.3/cmd/ctr/commands/images/import.go)
and [OCI importer](https://raw.githubusercontent.com/containerd/containerd/v2.3.3/core/images/archive/importer.go)
provide the route's source basis. This is an intended operation, not a successful
import result. Independently review it and the complete archive membership before
mutation. Reject missing/extra/unfunded members, transformed metadata or index,
non-amd64 execution, or any post-import RepoDigest/ID/RootFS/Size drift. Do not try
another format on failure. No pull, flattened import, retag substitute, manual
metadata edit, alternate daemon/provider or new B is authorized.

The future transfer recipe must enforce a pre-write archive ceiling (proposed
10 GiB, subject to complete membership verification), finite channel and result
ceilings, one absolute deadline, and retained failures. B4 must separately price
archive, ingest/content, unpacked snapshots, metadata/journal/cache/VHD growth and
copies. The 2 MiB diagnostic allowance and the old 512 MiB component seal cover
none of that transfer. All original/provider images remain preserved.

Independent source review found no identity-route blocker. Its conditional
no-referrer archive calculation is 50 unique blobs, 10,469,596,160 B tar-padded
payload; 55 headers plus bounded wrapper/compatibility metadata and tar ending
give 10,469,642,240 B. This still requires actual pre-import membership checking.
The OCI importer ingests every regular member before platform filtering; extra
members cannot be admitted by `--platform`. Archive ceiling + pinned packed bytes
+ historical native unpacked bytes total 40,137,791,544 B before other B4 forms.
