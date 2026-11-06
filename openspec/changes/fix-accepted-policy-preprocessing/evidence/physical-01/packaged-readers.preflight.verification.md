# Packaged Reader Preflight Verification

Source baseline: `aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795`. Production source files and tests were not changed by this evidence preparation. No Docker command was executed by this subagent, and none of the following host results is claimed as actual image execution.

## Static Exact Membership

`derive_packaged_closure_inventory.py` ran read-only against the frozen checkout and used the existing literal AST closure discovery. Result: 67 guardian/shared-reader project sources, contained in the 93-source full qualification seed closure. Every recorded source has its literal project-relative path, size and SHA256. All four actual runtime closure validators passed. Exact local COPY input counts are DeepStream 90, Savant 93, OpenVINO GVA 85 and GStreamer Custom 85; project Python module counts are respectively 73, 81, 68 and 68. Existing native/dependency/build-only members are separately classified, not counted as additional shared-reader project Python sources.

```powershell
C:/Python314/python.exe -B openspec/changes/fix-accepted-policy-preprocessing/evidence/physical-01/derive_packaged_closure_inventory.py . aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795
```

The generated inventory file was saved using `apply_patch`, not by executing or modifying image machinery. Inventory SHA256: `f395d0dd84be03232939f8aeb5c927d51b2e5a3aedaaea8836b05f0b83bd9bcc`.

## Host Import Order Result

PASS: four fresh interpreters, promotion-first, sidecar-first, original transaction-builder-first and original fragment-builder-first. Each resolved project source from the explicit host root and proved identical re-exported transaction error/ContextVar/descriptors/cold reader, fragment exception/dependency/default/validator objects, F1 fragment reader module and shared F5 callable. This is a host-only import/object-identity result. No promoter, materializer, worker or semantic qualification assessment was called.

```powershell
wsl.exe -d Ubuntu -u s-a-balashov --cd /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST -- env PYTHONPATH=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/scripts /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B openspec/changes/fix-accepted-policy-preprocessing/evidence/physical-01/verify_host_import_orders.py --project-root /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST
```

## Genuine Cold Descriptor Host Smoke

PASS: the real leaf `cold_validate_committed_transaction_v2` ran twice on the new valid receipt in each of the two modes. Each mode independently compared all 18 physical `file_descriptor` results. The held mode opened actual Linux `PhysicalRootCustodyV1`, confirmed POSIX dirfd custody and restored the shared custody ContextVar after execution. Both modes rejected the deliberately drifted descriptor, wrong kind, missing fragment coverage and noncanonical JSON with the exact intended predicate. Fixture bytes were not modified.

```powershell
wsl.exe -d Ubuntu -u s-a-balashov --cd /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST -- env PYTHONPATH=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/scripts /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -c "import importlib.util,json,pathlib; p=pathlib.Path('openspec/changes/fix-accepted-policy-preprocessing/evidence/physical-01'); s=importlib.util.spec_from_file_location('host_only_checker_smoke',p/'verify_packaged_readers.py'); m=importlib.util.module_from_spec(s); s.loader.exec_module(m); fixture=(p/'cold-descriptor-fixture').resolve(strict=True); print(json.dumps({'host_only':True,'image_execution_claimed':False,'runs':[m.cold_descriptor_execution(fixture,held=False),m.cold_descriptor_execution(fixture,held=True)]},sort_keys=True))"
```

These artificial payloads establish descriptor mechanics only. They are never campaign authority, accepted policy calibration or pilot evidence. The actual image recipe additionally requires a kernel-reported read-only bind mount and verifies the entire fixture hash catalog before executing the cold reader.

## Syntax and Remaining Execution

PASS: `bash -n run_packaged_reader_checks.sh`; AST parsing of the three Python helpers and two embedded shell Python blocks; `git diff --check`. At preflight time the image recipe was unexecuted. The integration owner's subsequent actual execution is recorded separately in `packaged-reader-results.v1.json` and `packaged-reader-reports/README.md`, with byte-identical fresh stdout reports. Promotion-first cannot be an actual image sequence without violating the reviewed host-only F1 packaging scope; that unsupported sequence is explicitly reported rather than simulated with a mount.
