# Guardian Config TDD Originals

## Scope And Original Results

These are immutable byte copies of the closed config-loader TDD captures and the exact two-file RED/GREEN overlays. They are not a replay, a genuine complete-consumer fixture, packaged-source acceptance, hardware qualification, Q1 evidence, or proof of arbitrary descendant quiescence. The portable dependency source is exact `65c9fa91e2c396265183ec47cb090629ccdd174a`; that frozen source was not modified.

Original RED ran only `test_default_execution_config_loader_materializes_and_cold_loads_raw_config` and naturally exited 1. It started `2026-10-13T16:05:34.237925+00:00` and finished `2026-10-13T16:05:35.007127+00:00`. The original stderr records one actual error, at guardian `_source_material:778`: `AcceptedPolicyGuardianPreprocessingContractV1Error: execution config content identity drifted from v4 parity authority`. It ran one test, not an import-failure surrogate. Its stdout records actual guardian and test imports from the fresh RED overlay.

Original GREEN ran the complete focused guardian test module and naturally exited 0, from `2026-10-13T16:06:24.450193+00:00` to `2026-10-13T16:06:29.850734+00:00`. Original stderr reports 13 tests in 4.946 seconds, `OK`, with zero errors/failures/skips. Its stdout records actual imports from the separate GREEN overlay. Both original results have `capture_errors=[]`, `source_hashes_unchanged=true`, `overlay_bytes_unchanged=true`, original child started/naturally closed true, and `no_complete_consumer_or_campaign=true`. Original within-phase before/after source-hash captures are byte-identical; RED and GREEN intentionally have different guardian pins.

## What The Tests Prove And Do Not Prove

The positive regression uses the actual default execution-config loader, not a copy-returning substitute. It writes the stock seven-key raw config without physical `identity`, checks the loader's added derived canonical identity, materializes, independently cold-loads, and asserts unchanged input bytes and expected descriptor/identity. Other focused regressions exercise forbidden raw identity, loaded identity/projection drift, stale physical bytes, mutation during loading and post-load descriptor drift, including fail-before-output-write behavior.

Upstream fixture eligibility remains explicitly substituted: predecessor loading, policy assessment, execution closure/accounting, runtime probes and materialized binding-set loading use the test fixture's dependencies. The test source says that only config loading is real and that closure tests verify delegation, not physical operational accounting (`tests/test_publication_guardian_accepted_policy_preprocessing_contract_v1.py:397-471`). Loaded-drift cases explicitly wrap the real loader and then mutate its result. These are scoped unit/refusal regressions; successful GREEN does not prove genuine upstream acceptance, live native accounting, complete default guardian consumers, packaged repair correctness or a campaign.

No q1 independent review verdict was received by this retainer when this review was authored. This document does not claim that verdict or replace the separate code/spec review and required fresh general/complete-consumer checks.

## Exact Original Pins

- Capturer `run_guardian_config_tdd_v1.py`: 10721 bytes, SHA `1acd91a2fbb35905b5779ac30c1fd8a296976362d7978427be6de66efb73ebb8`.
- RED guardian: 54326 bytes, SHA `3b649aea69120fbf3968a55802ac6ed9695625bdfa2c9f729b058dc7b04283a1`.
- GREEN guardian: 54793 bytes, SHA `f7da3f9fc3ee46cc10cc7330f6c8a410ea7448c8b01793fe5e245cd5293ac586`.
- Both regression test copies: 48524 bytes each, SHA `948b2848e7b6bda3dd07e6de795ab7171a0cbb5c0e9646656b9eddee962744ce`.
- Recorded unchanged stock: `f4478804491922c3e25ab414ba8f000c1964b46633f9dfb3a5bc87212748dbde`; F5: `48fbc62494cdc40bd5f925cee6ff16dad02269feacf1803d263a9d165523f246`; actual default sidecar: `2450cd59bca86e1251ec25672ff4805d122af4408fa68fb804dc712eef68bbfc`. The retainer preserved those original source-hash records without re-executing their producer.

Original RED stderr is 2576 bytes, SHA `7fe1b9eb64cd0c479fe0c69326cd459c645a6da81c0c64b33c6efaa3bba74a79`; GREEN stderr is 3651 bytes, SHA `272e921c39fdee9ae6578808ccc6447e78ca1ff9874edfb06a08a84a17948452`. Both physical raw captures were compared with their original result descriptors before retention.

## Mechanical Retention

`originals/catalog.v1.json` records 17 original files / 233676 bytes: six closed native capture files per phase, the original capturer, and guardian/test copies from each of the two ext4 `/var/tmp/vast-guardian-config-tdd-20261013a` overlays. Native and Linux-relative groups are retained without flattening or name collisions. No unrelated fixture/runtime/source file is included.

Every entry records exact original physical source path, Linux path for overlay files, relative destination, source length/SHA256/creation and modification ticks/attributes before and after, and destination physical descriptor. Ordinary leaf type, literal absolute canonical path, non-reparse ancestry, exact native source-directory entries, closed results/pins and fresh destination were guarded. Copies used exclusive create-new byte streams, no normalization/hardlinks/overwrites, and retained files/catalog have read-only attributes. Original source bytes and recorded physical metadata remained unchanged.

The finite native retainer `E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\Retain-GuardianConfigTdd.v1.ps1` was 13256 bytes, SHA `4cd497b9b854143178816002861baecc2907ce6f87f40b6d04cbd87e59870368`, with zero PowerShell parser errors. Original mechanical copy returned 0 at `2026-10-13T16:13:39.3710630Z`, after starting `2026-10-13T16:13:38.4025760Z`; failure was null. External closeout is `E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\guardian-config-tdd-retention-01\result.v1.json`.

Catalog is **32339 bytes**, SHA **`4c26f2bc37e6b497cf4d795fc9a9b6e795ce001805d7acdee47ba2232a6882b4`**. Including it, `originals/` has 18 files / 266015 bytes. A separate bounded physical read/hash pass at `2026-10-13T16:14:05.0327498Z` verified all 17 current source/destination descriptors and hashes against the catalog and exact totals. No producer, production import, semantic validator, replay, source edit, deletion, Git index operation, commit or push was performed by retention.
