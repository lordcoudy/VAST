# Affected evidence and renewal order

This dependency map applies to the approved runtime baseline plus the payload, guardian and retry repairs. The source allowlists and producer-receipt checks remain the executable authority.

## Images invalidated

- `deploy/native_gst_probe/checkpoint_analytics_execution_client.hpp` is packaged by the DeepStream, OpenVINO and Savant native-probe source allowlists. Rebuild all three native foundations.
- The OpenVINO and TensorRT analytics workers depend on those native foundations. Their produced-base identities must come from the new native freeze receipt. The worker build tool supplies `EXPECTED_BASE_IMAGE_ID`; changing a Dockerfile default after the build would invalidate its evidence.
- The bridge and sidecar are in all four publication runtime source allowlists: DeepStream, Savant, OpenVINO GVA and GStreamer Custom. The latter two also include the native client header directly; Savant consumes the native builder receipt. Rebuild all four runtimes.
- The reconciled analytics protocol is part of both worker and all four runtime closures. Its integrity checks remain unchanged by the focused repair, and it must be verified in the rebuilt packages.

All nine image identities therefore require current receipts. Pinned remote base images, model bytes and dataset bytes are unchanged inputs, verified physically before reuse.

## Required renewal sequence

1. Deterministic native-probe A/B builds and stock freeze receipt.
2. Deterministic worker A/B builds against that producer receipt.
3. Four deterministic publication runtime builds using the stock native-receipt handoff.
4. Packaged byte checks and regressions against immutable image IDs; capture each runtime receipt.
5. Assemble and verify the image identity patch from the new native, worker and four runtime receipts. Fresh worker identities can legitimately leave parity-refresh blockers at this point; do not claim candidate eligibility before parity.
6. Complete the physical model-parity v4 refresh: 480 executions across 32 groups, then acceptance, physical descriptor verification and comparison with unchanged frozen tensor expectations.
7. Update only affected host constants/fixtures from accepted receipts; verify that packaged source identities remain unchanged. Any packaged edit requires rebuilding its dependency closure again.
8. Run affected native tests and the final complete ext4 suite on the final source/fixture/mirror bytes, with before/after manifests and a reviewed comparison of skip identities.
9. Produce entirely fresh qualification inputs, preprocessing, guardian authority, 32 bundles/four assets, diagnostic, 32-cell qualification, clean authenticated stop/closure and promotion.
10. Renew Q4 source/material/phase registries, phase A, boundary, phase B and sizing; then dated capacity, plan replay, live preflight and unstarted service package.

A261/A262/A268 remain historical evidence. Their images/parity/test receipts cannot authorize the repaired packaged source. Failed A269 cells remain excluded. Every dependent gate stays missing or blocked until its current predecessor is accepted. The full matrix is outside this preparation sequence.

## Observed progress

On 2026-09-21 the nine deterministic rebuilds completed successfully, as did capture of the four runtime receipts and stock patch assembly/verification. Packaged regression and downstream evidence renewal are still in progress. This map is not a grant or a readiness claim.

The first packaged sweep exposed a missing final-image Python dependency in OpenVINO GVA and GStreamer Custom. Correcting their Dockerfiles invalidated only those two runtime receipts and the aggregate patch. Both were renewed, preserving the other seven image identities; packaged regressions now pass on the replacements.
