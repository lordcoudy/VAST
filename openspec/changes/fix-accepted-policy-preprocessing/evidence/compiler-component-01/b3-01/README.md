# B3 host container TERM/KILL stall: third component container

This run follows the B2→B3 gate approval (PR #9 comment 6213031979, evidence
at `2453ab9e`). It used the unchanged gate-1 runner and the same component
root. The only allowed prior CIDs were B1 (`4df593e1...`) and B2
(`9b5c3961...`). The VM was pre-warmed and given a 40 s settle in the same
session, starting at 65.5 s uptime. The boot ID `50b2b360-...` was the same
before and after the run.

- **Container:** `90f8ebb69bd83cbb02067a831cc2ace5efe78fc6b568a665bd93333d7b4b6e87`.
- **Timing:** started 2026-10-16T10:02:41.68Z; KILLed and finished 10:04:21.90Z.
- **State:** the container is retained, stopped.

## Results against the pinned values (`../b2-01/gate-b2-b3-disposition.v1.md`)

| # | Pinned value | Observed |
|---|---|---|
| 1 | Pre-warmed VM; same boot ID; guard list = the B1 and B2 CIDs, both stopped | yes; `50b2b360` before and after; guard list `[B1, B2]` exited |
| 2 | Probe reads the request, ignores SIGTERM, writes nothing | no export bytes; `export` null; capture incomplete |
| 3 | `normal_close_wait` timeout → `kill_SIGTERM` 204 → `wait_after_SIGTERM` timeout → `kill_SIGKILL` 204 → `wait_after_SIGKILL` `{"StatusCode":137}` → `final_inspect` | exactly this sequence. The RPC status lines are 200/200/200/200/201/101/204/200/200/204/200/204/200/200 |
| 3 | 14 RPCs, no 409, no `docker_sticky_failure` | 14 attempts; no 409; no sticky failure |
| 4 | Causes ⊆ {`docker_attach_TimeoutError`, `docker_deadline`, `attach_incomplete`, `docker_io_TimeoutError`}, including one of the first two | exactly those four, in that order |
| 5 | ExitCode 137, `OOMKilled` false, incomplete export, no ELF | ExitCode 137, `OOMKilled` false, no `engine.unaccepted` |
| 6 | Init absent, cgroup unpopulated | yes |
| 7 | dmesg delta: zero fatal-signal, RLIMIT_CORE, Aborting core, `type=1326`/`1701` and `wsl-capture-crash` lines | zero of each |
| 8 | Crash-directory listings before and after identical | identical (10 entries) |
| 9 | Charge ≤ 16 MiB | max(ext4 +417,792 B; outputs + `SizeRw`; C: −4,128,768 B) = 4,128,768 B; cumulative 11,890,688 B |

## Deviation D3 (literal; disposition pending gate-2 review)

Rule 7 also allowed only `misc dxg:` lines. The delta instead holds two
`systemd-journald` lines:
- `Received SIGTERM from PID 1 (systemd).`
- `Collecting audit messages is disabled.`

The cause was host-side and concurrent with the run.
`apt-daily-upgrade.timer` fired at 13:04:03 MSK (10:04:03 UTC), and
unattended-upgrade installed Ubuntu updates between 13:04:07 and 13:04:16.
Among them was systemd 255.4-1ubuntu8.17 → 8.18, whose post-install step
re-executes systemd and restarts journald. The other updates were curl,
openssh, python3-urllib3 and python3-jwt (`run-records/B3.concurrent-*.log`).
journald's on-disk use went from 808.0 MiB to 800.0 MiB, because it replaced
an uncleanly closed journal on restart.

The pinned platform is unchanged: Docker 29.7.2, containerd v2.3.3, runc
1.4.3, docker-init 0.19.0, and the same engine ID and kernel
(`run-records/B3.platform-after.txt`). The per-run identity guards would
catch any later drift.

## Operator risk for later stages

The WSL Ubuntu runs unattended-upgrades on a timer. A future update could
change pinned host software, for example the canonical WSL Python 3.12.3 or
systemd's cgroup handling, in the middle of a qualification. Changing that
setting is the user's decision. Until then, every run's guards refuse on any
pinned-identity drift.

The host dmesg dumps before and after stay in the component root.
`originals.sha256` was written last and excludes itself; it lists
component-root paths: `outputs/B3/` is `outputs/` here, and `runs/` is
`run-records/`.
