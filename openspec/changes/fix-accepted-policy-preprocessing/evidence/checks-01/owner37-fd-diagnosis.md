# Original591 FD Diagnosis

This is diagnosis, not qualification authority, a full-suite pass, or a retry of
the failed full suite. Original session 44214 remains failed: 3291 tests,
2 failures, 1 error, 86 exact approved skips. No source or CI policy changed.

The reviewed helper `measure_owner37_fd_v1.py` at SHA256
`dc3d9eb3eee4530a6afa98752b31843f8c66531b587695f18b413d14ae4bfc1a`
ran once as UID 1000 in original session 79893. Outputs are exclusively
`/var/tmp/vast-repair-owner37-fd-591a93e7-01`. It ran the unchanged genuine
37-operation owner test with actual class setup and cleanup in two fresh
interpreters, no validator/provider replacement, and parent-side `/proc` FD
sampling. Local limits were 1024/1048576 and 10240/1048576; no system limits changed.

- Soft 1024: original child exit 1, one test, zero skips, one EMFILE error in the
  actual cold original native-transfer reader. Observed peak 1007 is a lower
  bound; short transient peaks are not guaranteed to be sampled.
- Soft 10240: original child exit 0, one test, zero skips, no failures/errors.
  Observed peak 1193 is a lower bound, already above 1024.
- Both paths: before-import 3 FDs, after-setup 10, after-test 10, after-class-cleanup 8.
  Thus the complete cold join restored its entry count on both paths.
- The successful peak contained 666 process/container record FDs, 138 native
  transfer metadata FDs, 78 capture-plan document FDs, 125 source-input FDs,
  111 measured-output FDs, 32 bundles, 11 guardian FDs, one socket and 31 other FDs.
  This corresponds to concurrent complete-plan and whole-join custody.
- Five residual FDs are the evidence sink's directory chain for the retained
  test class fixture. `ProductionLifecycleEvidenceSink.__del__` eventually
  closes it; `_OwnerFixture.close` does not explicitly close the sink. This is
  a separate fixture-lifetime warning, not evidence of cold-join accumulation.
  It is left unchanged; removing five would not make 1193 fit within 1024.

The ordinary WSL UID 1000 caller currently has soft 10240/hard 1048576. The root
`runuser` entry resets the soft limit to 1024. The failed original full-suite
artifacts did not capture RLIMIT or a complete FD census, so the historical
limit cannot be asserted retrospectively. The fresh controlled experiment
establishes that the unchanged test alone fails at 1024 and succeeds at the
observed ordinary limit, independently of earlier suite tests.

Stock raw-source verification before and after covered all 11757 tracked paths
in exact source 591; HEAD and tracked status were unchanged. Parent diagnostic
exit 0 means these observations were recorded, not that both child tests passed.

## Scoped Recipe Correction

The managed external recipe observes the actual UID 1000 caller's limits,
requires 10240/1048576, and passes only that observed soft limit through the
private mount launcher. After `runuser`, the unprivileged child records UID,
capabilities and limits, restores that observed soft limit while preserving
the inherited hard limit, records the result, and refuses any mismatch before
executing unchanged CI. This is child-local environment restoration.

The temporary base is the stock canonical ext4 `/tmp` for the existing
AF_UNIX symlink test. Its previous `/var/tmp` alias made the constructed path
108 bytes, exceeding the unchanged 107-byte production limit before the
intended symlink-parent refusal. No test or production predicate was weakened.

The original global mount comparison remains unequal and is retained. All 255
preexisting rows were unchanged; four DockerDesktop bind rows appeared during
the separately owned live-Docker integration windows. Their `private-project`
and `analytics.sock` shape matches the real OpenVINO held-copy test; exact
temporary-name-to-container-event mapping is not retained and is an inference.
The canonical runtime's global covering mount row stayed byte-identical, while
the runtime read-only binds were recorded only in the distinct private mount
namespace. The next full suite must begin after all live-Docker integration
work ends. Exact whole-global-mount comparison remains required, unchanged.
