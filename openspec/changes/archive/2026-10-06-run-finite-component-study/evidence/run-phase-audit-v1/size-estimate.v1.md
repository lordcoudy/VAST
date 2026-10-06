# Worst-case per-arm size estimate (independent read-only audit, 2026-10-05, source b0234fc7)

Method: Python in WSL /tmp only, repo writers/serializers on synthetic in-memory data. Real `build_study_plan`
on a synthetic 442-AU intake (dataset `finite-kpp-original-442-v1`), real topology/process/worker ids from
`build_finite_study_runtime_plan_v1`, run_id `finite-<16hex>-<arm_id>`; native rows copied field-for-field from
the C++ writers; `arm.original.json` = real `dataclasses.asdict(RuntimeRunResult)` + runtime `json.dumps`;
guardian rows with `original_header` already replaced. Worst case: no drops, all 4 branches complete,
421 admitted AUs/stream at rate 2 (10104 requests), 211 at rate 1 (5064). Uncertainty about ±5%.

| Item (cap) | Cap | Rate2 baseline | Rate2 shared | Rate1 pilot |
|---|---|---|---|---|
| arm.original.json (runtime :3160, driver :1080) | 64 MiB | 66.96 MiB (over) | 55.4 | 33.8 |
| native-protocol raw (runtime :3130) | 64 MiB | 52.1 | 41.1 | 26.3 |
| topology capture (runtime :3123) | 64 MiB | 48.3 | 38.3 | 24.4 |
| native domain / decoded native_terminals | 64 MiB | 58.1 | 57.4 | 29.3 |
| closure.original.json (reducer MAX_DOCUMENT_BYTES) | 4 MiB | 3.88 | 3.86 | 1.96 |
| decoded waits | 64 MiB | 37.3 | 37.3 | 18.7 |
| decoded guardian (header removed) | 64 MiB | 30.0 | 29.8 | 15.1 |
| decoded source_events | 64 MiB | 29.6 | 11.6 | 14.9 |
| arm-dir total (MAX_RAW_ARM) | 256 MiB | 445 (over) | 375 (over) | 224 |
| reducer per-arm decoded total (max_raw_bytes_per_arm) | 256 MiB | 161 | 142 | 81 |
| campaign 24 arms + 8 pilots (MAX_RAW_CAMPAIGN) | 8 GiB | ~6.99 GiB total (excl. CSV/logs) | | |

Per-row: largest decoded row ~6.1 KB (native record) vs 9216 B record cap (1.5x); native event line 1136 B vs 2048 (1.8x).
Without the guardian header fix the decoded guardian role would be ~100 MB (rate 1) / ~200 MB (rate 2).

## Final results document (third audit pass, source 78a9fc2d)

`study-results.original.json` embeds pilots (4, or 8 with the switch; each a full `reduce_arm` result, ~0.43 MiB), the 24-arm/12-pair reduction with per-frame key lists (~110 B per key, fractional latencies), pool closure descriptors and command records (~0.25 MiB; real `failed.original.json` files are 16–29 KB). Key/latency payload: 14.09 MiB without, 15.77 MiB with the switch; other fields ~0.5 MiB; totals ~14.6 / ~16.3 MiB vs the generic 16 MiB control bound. Other control documents: prepared receipt a few MiB (R1 `source-gate-plan.original.json` 1.2 MB), closure 3.88 MiB worst case, closed-inputs descriptors only.
