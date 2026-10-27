# Retained build inputs and remaining S96 capacity terms

Independent source/retained-record audit by /root/capacity_review did not execute
Docker, builds, restores or probes. These are historical/source quantities, not
fresh admission. Usable 96 GiB fit remains unproved.

Bind the actual route first. Standalone OpenVINO/GStreamer defaults use native
fc26a96..., and Savant's native builder defaults to 314d4a.... The approved
build_publication_runtime_images_after_refreeze_v1.py handoff lines 223-242 and
280-289 instead overlays selected native-receipt values. Retained current-plan/
native-v6 receipts bind OpenVINO 65b49d... and Savant-native 955712....
Their quantities must not be substituted for the standalone defaults.

Known retained quantities:

- DeepStream c11bef... native packed 10469582904 B and historical native unpacked
  18930790400 B. Together with the proposed 10 GiB archive: 40137791544 B.
  Desktop's combined observation is separately 29400323407 B. Preserve the
  unresolved unpacked/accounting distinction; do not silently equate these.
- Savant base 3c0ef6... observed combined 22705487749 B.
- Receipt-backed OpenVINO 65b49d... observed combined 3169134535 B.
- Receipt-backed Savant-native 955712... observed combined 22706847496 B.
- The latter three lack exact retained packed/unpacked splits in this audit.

The retained rootfs.original.jsonl proves historical runtime-to-base prefixes,
including Savant runtime to its base. It lacks Savant-native 955712...'s chain,
so it does not prove base/native-builder sharing. A base label or inspect hash
does not substitute for that chain, compressed digests or store/snapshot binding.
The snapshot is tmp/pr9-verification-20261025/runtime-storage-metadata-01/rootfs.original.jsonl.

Fixed forms independently recomputed from literal manifests/wheel central dirs:

- Four contexts: 377 files, 139040089 logical B, 139825152 B rounded to 4 KiB,
  plus 28 descendant directories and four roots.
- Eight builds: 247691592 B of retained wheel COPY inputs, 854618672 B
  uncompressed wheel inputs and 27044 entries.
- OpenVINO/GStreamer's final cross-stage COPY adds another 401271032 B of wheel
  payload. Installed/copied input payload totals 1255889704 B before generated
  files, temporaries, old-package copy-up and provider-native assets.
- The schedule has 20 RUN instructions, eight pip installations, four g++
  invocations, 92 COPY instructions and six verification containers.

Close these concrete writer terms: pip-generated metadata/temp trees and
DeepStream/Savant existing-package uninstall/copy-up; DeepStream compiler
temporaries and two native outputs; copied provider binaries/plugins/registry;
BuildKit intermediate snapshots/content/cache; rewritten exporter/load staging;
verification-container writable state and backend retirement. Savant's literal
pip call lacks --no-deps; its existing no-index/hash flags remain required.

The four independent Desktop-style combined input observations sum 77981793187 B.
Adding 139825152 B rounded context payload, 85675469 B apparent original-store
copy and the 10 GiB DS archive leaves 14134503056 B against raw 103079215104 B.
This arithmetic excludes filesystem overhead and new build state and does not
prove usable capacity or qualify the native accounting discrepancy.

Price the maximum at each serial position: prior retained successes plus the
current active/failed forms and every unretired temporary. A failure holds the
sequence; do not charge eight failed exports. Do not reclaim a temporary without
retirement proof, credit unsupported sharing, prune/offload images or treat the
96 GiB physical ceiling as fit. Protected originals and all 227 images remain.

Source anchors: scripts/materialize_runtime_build_context_v3.py:129,
scripts/build_deepstream_publication_runtime_v3.sh:74,
deploy/deepstream/checkpoint/Dockerfile.runtime:135, and the four literal
build_*_publication_runtime_v3.sh scripts. No operator or physical authority
follows from this audit.
