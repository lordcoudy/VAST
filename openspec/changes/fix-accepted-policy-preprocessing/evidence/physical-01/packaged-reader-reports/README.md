# Actual Packaged Reader Results

Status: PASS for four actual fresh runtime images at initial frozen repair source `aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795`. Execution was performed by the integration owner in session `21704`, which completed exit 0. This evidence author inspected the completed files read-only and ran no Docker commands.

Original logs: `/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a/artifacts/accepted_policy_repair_20261011a/packaged-reader-control`. Recorded wrapper interval: `2026-10-11T19:56:14Z` to `2026-10-11T19:56:33Z`. The four portable stdout reports in this directory are byte-identical to those fresh originals. Summary, image IDs, runtime receipt identities and all report hashes are in `../packaged-reader-results.v1.json`.

## Exact Interpreter and Sources

All actual interpreters were `/usr/bin/python3 -B`; no host production script directory was mounted and no project `sys.path` fallback was inserted. The default image environment was preserved:

- DeepStream: Python 3.10.12, `PYTHONPATH=/opt/vast/checkpoint`, exactly 73 packaged project Python files.
- Savant: Python 3.10.12, `PYTHONPATH=/opt/vast/checkpoint:/opt/savant`, exactly 81 packaged project Python files.
- OpenVINO GVA: Python 3.12.3, `PYTHONPATH=/opt/vast/checkpoint:/opt/vast/python`, exactly 68 packaged project Python files.
- GStreamer Custom: Python 3.12.3, `PYTHONPATH=/opt/vast/checkpoint:/opt/vast/python`, exactly 68 packaged project Python files.

Each image verified the complete exact packaged project `.py` file set and every source SHA256 against the frozen inventory, including all 67 shared guardian/leaf closure modules. Additional files were only the existing explicitly inventoried runtime entry/provider modules. All host-only F1/original-builder/executor/owner module names were absent from image import discovery and from loaded module sets.

The exact source inventory hash was `f395d0dd84be03232939f8aeb5c927d51b2e5a3aedaaea8836b05f0b83bd9bcc`; checker hash `64b9872ad75dcf8bfafab42333d349f5d0f2d89ecad4c900f9c221909a9c3974`; fixture inventory hash `065c45da24c2390da58af2db4f0d727793198e1a414f4b9341e942481fa694ba`. All three were equal before and after the entire wrapper execution. Individual literal source paths/hashes and all four COPY/allowlist classifications are retained in `../packaged-closure.aca94dd0.inventory.v1.json`.

## Actual Cases

Each image passed seven separately launched fresh interpreters: standalone transaction leaf, standalone fragment leaf, standalone pilot leaf, leaves-first then sidecar/guardian, sidecar-first then leaves/guardian, real cold descriptors without custody, and real cold descriptors with held POSIX root custody. Total: 28/28 modes across four images, with four per-image exit codes 0. Standalone leaves did not eagerly import either guardian or sidecar; loaded project module origins were the actual packaged path.

Each cold mode executed two valid cold loads, independently compared all 18 physical descriptor outputs, and rejected four cases with exact expected errors: drifted descriptor hash, wrong transaction kind, incomplete fragment coverage and noncanonical JSON. Totals: 16 valid cold loads, 144 explicit physical descriptor comparisons and 32 exact refusal cases. All four held modes opened actual Linux dirfd-backed custody and restored its shared ContextVar afterwards. The kernel reported the fixture bind mount read-only, and every fixture payload hash/file set was verified before execution.

## Limits

The purpose-built fixture uses entirely new artificial descriptor payloads. It proves real canonical/descriptor/custody cold-reader mechanics only, not semantic fragment/pilot eligibility, accepted calibration or actual qualification acceptance. Historical campaign/G9/attempt-4 bytes were not inputs.

Promotion-first is unsupported as an **actual image** order under the reviewed host-only F1 scope; F1 and the original builders were not mounted to simulate it. Their promotion-first/sidecar-first/builder-first orders passed separately on the host, as recorded in `../packaged-readers.preflight.verification.md`.

These reader checks launched no Q1 pilot, promoter, materializer, campaign guardian or full publication workload. They validate the initial ACA packaged source and captured runtime identities, not a later final pinned input commit, final CI, archive, final review or launch authorization. No claim of overall repair completion or publication readiness is made here.
