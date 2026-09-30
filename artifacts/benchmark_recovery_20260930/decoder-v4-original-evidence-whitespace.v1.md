# Narrow preservation of original diagnostics and source comparison patches

The decoded hosted065 job log retains seventeen original timestamp/package-output trailing-space lines. The three source comparison patches retain their standard single-space blank context lines. These four evidence leaves are preserved byte-for-byte; changing their whitespace would invalidate their recorded hashes. This is not a production-source or test formatting exception.

- artifacts/benchmark_recovery_20260930/cpu-ci-run-36676456718/original-decoded-job.log: 77270 bytes, SHA256 0b07ff9ad00f362d0709fbe58901cc18f745859d6595f1dc03771e885c478a30.
- artifacts/benchmark_recovery_20260930/decoder-research-v4-focused-tests/attempt04-dispatch-binding.diff: 4510 bytes, SHA256 d2340e6f6d4c1dadc7b04e739ea7fffc800998308aabcb94b3af295a3f86c1b7.
- artifacts/benchmark_recovery_20260930/decoder-research-v4-focused-tests/planning-binding-only.diff: 2944 bytes, SHA256 d7de55d1634ed604e31e7739ccec9e0d680778b06df950c5bbba1748322711cd.
- artifacts/benchmark_recovery_20260930/decoder-research-v4-focused-tests/v3-v4-source.diff: 22109 bytes, SHA256 8375edfe4f0601d9fb1ca6ea8008682e578e1819fbce08f87c570946f78cf05a.

Every other owned path passes git diff --check; every staged file equals its physical bytes. Original hosted139 remains failure with incomplete discovery and no source-after/full report; source comparison patches do not grant hardware acceptance.
