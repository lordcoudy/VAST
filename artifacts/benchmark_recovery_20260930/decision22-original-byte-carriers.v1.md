# Decision22 original-byte carrier exceptions

Only two owned original evidence leaves retain whitespace: the artifact-only failed inspector record has its original CRLF bytes; the unchanged original gst-inspect stdout has its original trailing spaces/EOF blank line. These are exact raw provenance, not source formatting exceptions.

- artifacts/benchmark_recovery_20260930/cpu-ci-065-source-forensics-v1/inspector-attempt-01.failed.json: 522 bytes; SHA256 3dde9653d307676350281fbec31be999c1d6ddab5a52d91d21c6a088a2391fb4.
- artifacts/benchmark_recovery_20260930/decoder-research-attempt-04/guest/metadata/registry.stdout: 6020 bytes; SHA256 d6deccb28b9cb06a780a1ca489882a146f0cf0e6bf14d734b7160bfef784673b.

Initial git add exposed CRLF normalization of the522-byte inspector failure record. The physical original was untouched and the byte-equality guard stopped before commit. Its exact bytes were then imported as an unfiltered Git blob (bc89a022651cde4b186df85b830ac6696f02a037) into only that owned index path; no attributes, source bytes or other staged paths changed. Every staged and committed owned file must equal its physical bytes. All other owned paths pass git diff --check. These exceptions grant no benchmark, full-CI or hardware acceptance.
