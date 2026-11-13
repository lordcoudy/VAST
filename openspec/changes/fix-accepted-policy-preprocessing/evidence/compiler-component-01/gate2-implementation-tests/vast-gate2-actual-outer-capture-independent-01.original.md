**The exact root journal preserves actual outer arguments and responses. It also reveals a receiver-schema mismatch that must be resolved before qualification.**

Located by the supplied UUID:

[C:/Users/s-a-balashov/.codex/sessions/2026/10/16/rollout-2026-10-16T13-15-45-01a14435-e720-7402-ba8d-9bff4e96bdfe.jsonl](C:/Users/s-a-balashov/.codex/sessions/2026/10/16/rollout-2026-10-16T13-15-45-01a14435-e720-7402-ba8d-9bff4e96bdfe.jsonl)

Its `session_meta.id` exactly matches `01a14435-e720-7402-ba8d-9bff4e96bdfe`.

The correlated public records are:

- **Exec**, lines 22882/22884, `03:10:11.134Z`/`.188Z`, call ID `call_ff8e9134a8224584b38d013008e78576`.
  - Actual source argument: **192 UTF-8 bytes**, SHA `44d6be9b9b3b59c3fc49347464b7d26c888fbb3bc9158c2fb680883ebf8f0881`.
  - Actual pragma: `yield_time_ms:1`, `max_output_tokens:100000`.
  - Actual wrapper reports running cell **1368**.
- **Wait**, lines 22886/22888, `03:10:14.497Z`/`.578Z`, call ID `call_b75b2a4aacc048fba4082f32a48df26e`.
  - Actual argument string: **59 bytes**, SHA `740c003c0417a9f52cd96c941fa8cd11f0fa344bffbda4c12f8fc25b5460cd5c`.
  - Parsed values: cell1368, `max_tokens:100000`, `yield_time_ms:1000`.
  - Actual wrapper reports completed.

Each actual response is an ordered **two-block `input_text` array**:

1. Status wrapper ending `Output:\n`, with an **empty embedded body**.
2. The exact sentinel text, **30 bytes without LF**.

Sentinel block hashes:

- Fragment1: `ba1c8fa3733ad9e3ff1496b0c401344181b50523d0bfe69e24cb07e484828282`.
- Fragment2: `cccf8125e07fb058c5cd920e0498f1f50f44ee63e4cea55f0a944c053df32b23`.

Current `ROOT_RECEIVER` instead expects one result string containing wrapper plus embedded payload, and a wait-arguments object. Those are **not the recorded representations**. Preserve the actual result blocks and original wait argument string; parse validation views without presenting concatenated/re-serialized values as originals.

This establishes small-probe capture availability, not full-size delivery, journal durability, timing qualification or raw JSON-RPC wire authenticity. No files, large emissions, reasoning dumps or physical actions were created.
