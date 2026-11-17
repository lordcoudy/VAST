# Staged Byte Review Before The Next Source Freeze

Native Windows Git compared every staged physical file with its index blob:
366 files, zero byte mismatches. No line-ending normalization was used to make
forensic originals match. The bounded fixture suite passed 26/26, zero skips;
its separate tool streams and unchanged source hashes remain retained.

The unfiltered staged whitespace check reports 925 diagnostic lines, confined
to eight original captured files. These are formatting warnings on byte
evidence, not production-source or test-code changes:

- `ext4-original-results/original/factory-appsrc.stdout`
- `ext4-original-results/original/factory-queue.stdout`
- `ext4-original-results/original/factory-videoconvert.stdout`
- `ext4-original-results/original/native-configure.stdout`
- `../consumer-01/sample-boundaries-01/red.stderr.raw`
- `../consumer-01/standalone-reader-01/bounded.result.v1.json`
- `../consumer-01/standalone-reader-01/bounded.source-hashes.after.json`
- `../consumer-01/standalone-reader-01/bounded.source-hashes.before.json`

Disposition: preserve original command output, trace whitespace and captured
CRLF JSON byte-for-byte. Do not format these files or weaken the repository's
whitespace/CI rules. Run a separately attributed staged whitespace check with
only these eight exact forensic paths excluded; it does not make the original
unfiltered check pass. Required behavioral checks remain separate pending gates.
