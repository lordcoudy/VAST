# Stock Binding Regression Originals

On2026-10-12 the twelve closed RED/GREEN capture files were copied mechanically
from E:/STUDY/VAST/tmp/host-cache-cleanup-20261012/fixture-binding-tdd-01 into
`originals/`, preserving relative red/green names. The original capture helper
was also copied, for thirteen retained files total. No capture was rerun or
converted, and no existing destination was overwritten.

The finite native copy verified expected membership, regular non-reparse files,
original byte length/mtime/hash before and after, and every copied file's exact
SHA256 equality. Both original zero-byte stdout files remain zero bytes.
This copy proof does not assert inode custody or new test execution.
Active and future-archive literal attributes preserve the captured raw bytes.

Helper SHA256:
`ff21c31e5c396af3be4ff0c868d8b4d2ff2853f64dca9feb5384891cbe367dff`.
RED result: `795d00bd72d7349f7d9d2ef4c67ac5279951c33c5df851495a31eb755d04431a`.
RED stderr: `28e8e763c30415efeb6bd4fcbbee1ccf04f3c523674f1777ad5bbe29643e13b8`.
RED source hashes before/after:
`13e21e234e7f1096cccd8b5e38a86695a71aae5b808b0b47b75165715391437f`.
GREEN result: `6a05443118b491ca83edc421ae703bfd8d379dd91fca4f189b13a4e63f0a28b3`.
GREEN stderr: `afa9ccab6dfc354aad816a7b57f3d9b78d844b71f50cfc9c0f5a41fcd8c65c8a`.
GREEN source hashes before/after:
`f703accbd8eaafb302dd57efda4a6a1e0522328cc92e2001c2735935d750a9c5`.

RED originalRC1 demonstrates the real stock binding writer's absolute-path
refusal; GREEN originalRC0 passes four bounded tests with zero skips.
Synthetic descriptor leaves and upstream spies are explicit. No complete
consumer, process/container runtime, campaign or Q1 acceptance is inferred.
