# Original registry stdout preservation

The original packaged gst-inspect stdout at `artifacts/benchmark_recovery_20260930/decoder-research-attempt-03/guest/metadata/registry.stdout` is retained byte-for-byte: 6020 bytes, SHA256 `d6deccb28b9cb06a780a1ca489882a146f0cf0e6bf14d734b7160bfef784673b`. Its22 trailing-space lines and final blank line are original command formatting. They are the only staged whitespace warnings. No source, planning, test or behavior check is waived; every other staged path passes `git diff --cached --check` when this one original raw stdout is excluded.
