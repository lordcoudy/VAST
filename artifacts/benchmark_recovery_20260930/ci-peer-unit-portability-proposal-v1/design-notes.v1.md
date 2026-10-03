# Portable peer-observer unit fixture

Planning only; no implementation, unit execution, Docker or namespace work. Examined HEAD 065fb8dbb9df914d8a6e50300533dfc55d99b892 and the two physical files in source-pins.v1.json.

Hosted diagnostic 53a reproduced `WSL2 osrelease marker drifted` on Ubuntu after eight original model assets were acquired and the unchanged model test passed. The failing unit already supplies fake Docker info but reads the host's real kernel string (`tests/test_analytics_peer_identity.py:246-272`). This explains this diagnostic's peer error; it does not establish the cause of other full-suite failures or the unfinished production test.

Modify only that unit. Keep genuine `/proc/sys/kernel/osrelease` opening, real fd/path fstat checks and closing. Wrap saved real os.open/os.close to assert the exact Path and O_RDONLY|O_NOFOLLOW|O_CLOEXEC flags, one shared integer fd and exactly one close; assert os.fstat(fd) fails with EBADF after return. No fstat/stat, UID/GID, mode, nlink, platform marker, production path or observer-function mocking.

Patch only os.read results to the existing 33-byte OSRELEASE_RAW fixture followed by EOF. Prefer a tiny local side-effect that first calls saved real os.read(fd, requested_size), discards its host-dependent content and returns the explicit bounded fixture chunk. Assert exactly two calls with sizes 256 and 223 and the same actual fd. These real reads exercise the original descriptor; the returned bytes are intentionally a unit fixture, never actual-host WSL evidence. Keep the existing strict fake Docker command/kwargs and exact observation/hash assertions. This is smaller and more honest than routing to a user-owned temporary file or forging root file ownership.

Add a small direct parser negative: `_build_peercred_pid0_platform_observation(b"6.8.0-linux-generic\n", DOCKER_INFO)` must raise the actual marker error. Existing tampered-observation coverage at :198-229 can fail on changed hashes before reaching that marker; the explicit negative isolates continued non-WSL rejection.

Production remains byte-identical: exact Linux/proc path and O_NOFOLLOW (:1380-1400), root UID/GID, mode0444, single link and fd/name equality (:1401-1423), bounded payload (:1425-1437), original Docker projection (:1439-1466), final fd/name recheck (:1468-1487), strict marker/parser and unconditional close (:1489-1501). No kernel/platform relaxation, alternate observer root, namespace calls or skip.

Acceptance after decision21 review: original RED on non-WSL hosted Ubuntu retained; changed test passes there and on WSL while production source/hash and constants stay unchanged; exact fd/open/read/close assertions pass; direct non-WSL parser negative still rejects. Run only the scoped tests first, then unchanged required CI/full selection. Fixture success is no genuine Docker/WSL/worker/model acceptance claim. No dependency, runtime image, worker or model source invalidation follows from this test-only delta.
