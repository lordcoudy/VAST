# Fresh Physical Repair Recipes

Status: prepared and statically checked only. No asset copies, Docker commands, physical builds, parity runs or Q1 launches were executed by the recipe author. This is not final repair readiness.

## Inputs and Custody

- Fresh physical root: `/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a`. The integration owner creates it from an exact committed repair source before executing these recipes.
- Historical root `/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a` remains read-only. Its HEAD is not changed and its attempts, G9 diagnostics and pilot/promotion outputs are never execution inputs.
- `asset-copy.inventory.v1.json` contains exactly 37 files: OMZ FP16 eight, parity models sixteen, the exact ten-file frozen publication-v3 KPP corpus, and three byte-identical native-a/native-b/worker receipts. All source sizes and SHA256 values were verified against the explicit model hash catalog, pinned corpus manifest/descriptors and physical receipt bytes. Total copy size: 2,772,820,877 bytes.
- Reviewed catalog SHA256: `b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d`.
- The twelve wheel files are already tracked and present, so they arrive through the fresh source checkout rather than an ignored-input copy.
- `copy_assets.sh` checks the reviewed catalog hash, exact frozen destination commit, physical resolved boundaries, single-link source files, all source hashes, and absence of every target before copying. It uses byte copies, not hardlinks or symlinks, and rechecks source/destination hashes. Failed partial copies are not silently resumed.

## Native and Worker Reuse

Read-only `publication_image_build_v1.py plan` confirmed that the current repair working tree's registry and all five native/worker source, dependency and context hashes equal the retained base receipts. The derived inventory is `native-worker-inputs.pre-freeze.inventory.v1.json`; it explicitly does not claim final SHA or live-image readiness.

Native-a and native-b each have SHA256 `57f1a9f30c345c930a1ddff06dc51fdfebfa570c1651971d468d115d91d6ece0` (6094 bytes). Worker receipt SHA256 is `5509b370821e8881f65f78dd1f61714fd908780eb50220a1d32c2d8936f5b554` (3963 bytes). The runtime recipe revalidates receipt self-hashes, repeats all five hash comparisons on the exact frozen build commit, and verifies the live native, worker, base and builder image IDs. A changed hash or missing live image blocks reuse; it must not be relabeled as an unchanged base.

## Exact Invocation Order

Run from WSL as the existing user after the integration owner reviews these recipes and freezes the source. `SHA` is the actual 40-character initial repair build commit, not the planning commit.

```bash
E=/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/physical-01
SHA=<reviewed-exact-repair-build-commit>
bash "$E/copy_assets.sh" b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d "$SHA"
bash "$E/run_runtime_build.sh" "$SHA"
bash "$E/run_refreeze.sh" "$SHA"
bash "$E/run_model_parity.sh" "$SHA"
```

The build preflight refuses any running Docker container, GPU compute process, or detected qualification/runtime worker or verifier. It records process/container/GPU observations, Docker engine data and disk headroom. The integration owner must also review actual host gates and monitor the host during physical work; these snapshots are not a concurrency lock.

All four runtime builders already support fresh references through `VAST_DEEPSTREAM_RUNTIME_IMAGE`, `VAST_SAVANT_RUNTIME_IMAGE`, `VAST_OPENVINO_GVA_RUNTIME_IMAGE` and `VAST_GSTREAMER_RUNTIME_IMAGE`. The handoff forwards these environment variables. Fresh final tags use `:accepted-policy-repair-20261011a`, with matching `-determinism-a/b` suffixes. `capture --candidate-final-reference` is a supported CLI override that requires the same repository and disjoint canonical/fresh references. Therefore no refreeze registry substitutions are necessary. The build snapshots all twelve canonical materialized tags before/after and requires unchanged identities.

Each existing builder performs deterministic A/B builds, exact context/source/dependency validation, equal image ID comparison and smoke checks. Capture validates the matching A/B identities and records physical receipts. The assembled patch is expected to carry exactly the two retained worker-image parity-refresh blockers; runtime receipts themselves must be eligible. The patch is not falsely required to be candidate-eligible before the new patch-bound parity refresh. The materializer must subsequently produce the required 480/32 parity evidence; its own successful exit and independent acceptance revalidation are required.

## Output and Pin Handoff

The artifact base is `artifacts/accepted_policy_repair_20261011a`: `runtime_images/*.runtime.freeze.json`, `qualification_image_identity_patch.json`, `model_parity_v4/acceptance_binding.v4.json`, `model_parity_v4/runtime_probes/{cpu,gpu}_runtime_probe.json`, and `model_parity_v4/bindings/`. Accepted config outputs use the fresh `accepted-policy-repair-20261011a` namespace under `configs/`.

After independent physical verification, inventory exact old-to-new pin changes from paired JSON receipts and paired file size/hash descriptors. Copy newly generated accepted configs and required portability receipts with an explicit hash catalog. Review the complete plan and apply only its exact reviewed SHA, preserving unrelated and historical pins. The historical `software-v11-repin-20261008e` inventory/plan/render/apply sequence is a reference, not an executable fresh-root recipe: its root, old namespace, selected receipt paths, file list and nonadjacent size site are hardcoded and require a newly reviewed repair plan. Historical CI fixtures remain historical; newly bound fixtures are materialized from validated fresh physical receipts rather than string-edited.

Recheck all four source/Docker COPY closures after pin changes. Regenerate affected qualification source/executable closures and downstream inputs. Final ext4 checks, specification conformance, repair archive and final review remain required. Only a separate, newly reviewed qualification change can authorize a later Q1; PR7 attempt5 stays unstarted.

## Static Checks

All five shell files pass `bash -n`. All four embedded Python blocks pass AST parsing. The asset catalog's source hashes have been checked; native/worker plan comparisons pass on the pre-freeze working tree. These static checks do not substitute for executing and verifying the physical recipes on the frozen repair source.

## Packaged Reader Checks at ACA

`packaged-closure.aca94dd0.inventory.v1.json` records exact frozen source commit `aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795`, the 67-source literal guardian/shared-leaf closure, the 93-source full qualification seed closure, per-file sizes/hashes, all four source validators, and exact local Docker COPY/dependency membership. All four validators pass. Build-only source exclusions are explicit; OpenVINO's copied manifest self-file is separately classified. No original builder, executor or host F1 is admitted as a new packaged dependency. The inventory SHA256 is `f395d0dd84be03232939f8aeb5c927d51b2e5a3aedaaea8836b05f0b83bd9bcc`.

`run_packaged_reader_checks.sh` is an integration-owner-run recipe, not an already executed image check. It requires the exact ACA frozen root, completed runtime build, all four eligible fresh runtime capture receipts, matching final/A/B image IDs and no competing Docker container. It uses each actual image's `python3 -B` and default `PYTHONPATH`; it never mounts host production scripts or changes `sys.path` in the image. Only the evidence checker, hash-pinned inventory and purpose-built fixture are mounted read-only. Logs are written outside the containers under `artifacts/accepted_policy_repair_20261011a/packaged-reader-control`.

```bash
bash "$E/run_packaged_reader_checks.sh" aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795
```

Each image runs seven fresh interpreters: standalone transaction/fragment/pilot leaf imports, leaves-first then sidecar, sidecar-first then leaves, and real cold descriptor validation without/with POSIX held-root custody. Exact packaged module sets and source hashes are checked, including all 67 shared modules, and host-only module absence is enforced. Third-party dependencies remain the image's existing dependencies.

F1 promotion-first is intentionally **not an actual image import order** because F1 is host-only under the reviewed design. It is neither mounted nor falsely reported as packaged execution. `verify_host_import_orders.py` separately checks promotion-first, sidecar-first, original transaction-builder-first and original fragment-builder-first in fresh host interpreters, preserving re-export function/class/default-dependency/ContextVar object identities.

`cold-descriptor-fixture/` contains 18 entirely new artificial payload descriptors, one valid transaction receipt, four specifically refused receipts, and a hash catalog. No historical campaign bytes were used. This proves the real cold descriptor reader and POSIX held-root execution, not full transaction/pilot semantic eligibility, promotion or Q1 acceptance. Fixture catalog SHA256 is `065c45da24c2390da58af2db4f0d727793198e1a414f4b9341e942481fa694ba`. The four host import-order checks and both cold fixture host smoke modes passed; exact commands and limits are in `packaged-readers.preflight.verification.md`. Actual image outcomes must come from the integration owner's fresh logs.

### Actual Packaged Execution Result

The integration owner subsequently executed the exact ACA recipe in session `21704`, completed exit 0. Fresh control timestamps are `2026-10-11T19:56:14Z` through `2026-10-11T19:56:33Z`. Independent read-only inspection of its four actual reports found all 28 fresh interpreter modes passing, with every per-image exit code 0 and unchanged helper/inventory/fixture catalog hashes before/after. These actual results do not alter the earlier statement that the recipe author did not run Docker.

Portable, byte-identical copies of each fresh stdout report are under `packaged-reader-reports/`; their SHA256 values were verified against the original fresh-root files. `packaged-reader-results.v1.json` binds those reports to actual fresh image references/IDs, capture receipt identities, default image Python paths and counts. `packaged-reader-reports/README.md` records factual results and limits. This is a packaged import/physical cold-descriptor result only, not semantic qualification acceptance or final repair/Q1 readiness.
