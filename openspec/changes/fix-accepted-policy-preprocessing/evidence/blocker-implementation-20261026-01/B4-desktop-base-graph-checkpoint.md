# Read-only Desktop base graph: retained observations

B4-desktop-base-tool-returns.original.json is 236907 B, SHA256
28e9848ab3a6d1fb04fe2e15ae3f65829dad4d2bf2ae2b58675d93dbaf65d2db.
It preserves original returned tool values and commands as UTF-8 JSON, rather
than claiming raw process bytes, D16 closure or runtime qualification.
The derived graph is 13103 B, SHA256
0e6ce399fa5cd1779acfc6b03cecbbc306ff069736acb1786355226319cbd568.
All nine selected index/manifest/config text bodies were independently hashed
against their content-addressed names before the final derived join.

The store's engine-id and bounded Docker info both identify Desktop
aa8f3d33-e1dc-4ed2-ad06-488b46b332d0. Current API image IDs, combined Size counters
and layer counts match the four retained inputs. API Ids identify manifests or
the DS index here; config IDs remain distinct. The complete ordered four-RootFS
text digest is b00bb9809029039dfd38499011779117a3b5770bc02c65643ef748790797a1b4,
matching authenticated configs with 47/50/15/51 diffIDs in the documented order.
The earlier full-image query was outer-tool truncated and is retained as such;
it supplies no complete RootFS claim.

Savant base and native share exactly the first fifty compressed digest/size
pairs and corresponding uncompressed diffIDs. Native adds the 373248 B layer
741eced2435e168d871e00b2797a5b8606fe6409f9f23d5f0414fbf5be535602
and diffID f134635c3cae10cbc0ebe739b6a80fd3f2a7e007fc00e5c4977400cc1f6309ea.
The four selected graphs contain 112 unique compressed layers, 19213473330 B,
excluding index/manifest/config metadata. The 1359747 B combined Size difference
joins 373248 B compressed, 983040 B derived snapshot difference and 3459 B
metadata: config difference +4161 B plus manifest difference -702 B. The
snapshot subtraction is arithmetic, not a fresh target allocation bound.

This closes a source graph/active Desktop API join only. Native import/build
content-store, snapshotter and parent-chain namespaces; consistent target
unpacked bytes/nodes; BuildKit representations; export/load/staging; usable S96
capacity and the remaining writer terms still require proof. The DS 49152 B
snapshot-accounting discrepancy remains recorded and unwaived. No sharing
credit across separate stores/workers or physical fit is inferred.

The independent capacity reviewer conditionally cleared this metadata-only
16 MiB tranche: 1 MiB aggregate originals/commands/derived/checkpoint, 2 MiB ZIP
plus manifest, 3 MiB Git forms, 10 MiB housekeeping including a possible
3 MiB index.lock. Roster maxima remain 24 input files, one ZIP/manifest,
26 blob objects, eight tree/commit objects, four control forms, one index lock
and 32 directories; 397312 B node-rounding slack is included. No repack/GC/retry
is funded. Fresh Windows/Linux floors/configuration/boot/UUID checks precede
retention. Actual index was 2764612 B, below 3 MiB. The tranche raises cumulative
direct liability from 1856 to 1872 MiB = 1962934272 B and C to 70.349609375 GiB,
within 80 GiB above the 40 GiB floor. E 65 GiB/full 64 GiB pagefile and cumulative
192 MiB source/Git cap remain. The separate later selector pair reserves up to
1904 MiB cumulative; it does not enlarge this metadata tranche.

A combined Node hash call exceeded the tool's 64000-byte review limit and did
not execute. A Windows inline-body hash command could not start (os error206).
Bounded Node hash groups then authenticated the complete bodies. These are
retained analysis limitations, not accepted physical failures or retries.
No service, image, container, storage or configuration mutation, allocation of
S/diagnostic VHD, import/build/runtime probe or protected-image operation ran.
