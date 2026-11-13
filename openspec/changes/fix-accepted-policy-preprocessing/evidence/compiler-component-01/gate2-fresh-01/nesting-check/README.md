# Fresh gate 2: guard/interop nesting check (no-effect run)

This run is required by component-admission-plan.v9.md section 6 before the implementation
approval. It ran on 2026-11-13 at 14:34:55Z, as uid 1000, under the containment guard with
`--interval 0.5` and no Docker options. The record directory was
`/home/s-a-balashov/work/vast-pr9-gate2-fresh-nesting-check-01/`, outside every fresh root and
sibling.

- **What ran:** the guard started `C:\Python314\python.exe -I -c` through WSL interop. That process
  ran two `wsl.exe -u s-a-balashov --exec` children:
  1. `/usr/bin/true`;
  2. `/usr/bin/sleep 20`.
  About 7 s after launch, the guard was stopped with SIGTERM.
- **Effects:** no Docker call, no root command, no repository write. The record and the client
  output stay in the record directory.

| Original | Size (B) | sha256 |
|---|---|---|
| `nesting.json` (guard record) | 786 | `4cf546d696eb515ec3679eab47480cd4e51f8dcefdeeeab0c3b80f07b7438155` |
| `client.out` | 32 | `1e604952fb23be4bc93a2274e146b54a35ed446c89fc4a9ca225f41dfc6eb7cc` |
| `client.err` (the UTF-16 WSL localhost-proxy notice only) | 520 | `516ee6b84a2c8877b1d1309ef87c4ca23732d9ec6f01ab5700d7eefd2e4f0597` |
| `nesting-check.sh` (the exact script run, including the client source and argv) | 1533 | `83de2f393977bd030fe91e0f098ee4efe00d9fa638e91053c5e411c1f47d8377` |

The client argv differs from the operator's: the operator adds `-d Ubuntu --cd /`, a stdin pipe and a
minimal environment. The record does not itself contain uid 1000 or `--interval 0.5`; the script and
the observer output below show them.

**Observer output, not a saved file.** These lines are the script's own console output, as printed in
the session and transcribed here. They were not written to a file, so they carry no hash:

```
uid=1000 start=2026-11-13T14:34:55Z
before_stop:     620       6 /usr/bin/sleep 20;
guard_rc=3
after_stop_linux:     620       7 /usr/bin/sleep 20;
after_25s_linux:
```

The `after_stop_windows` line listed every `python.exe` on the host, many of them unrelated, so it
cannot attribute a survivor.

## Results
- **Nesting works:** the nested `wsl.exe` running `/usr/bin/true` returned 0 (`true_rc 0`).
- **What the stop reached:** the guard's SIGTERM reached only the interop process
  (`child_returncode` −15, `client_signals` `["SIGTERM"]`).
  - The Linux `/usr/bin/sleep 20` started by the nested `wsl.exe` was still running 1 s after the
    stop. It was gone 25 s after launch, so it ended on its own.
  - `client.out` has no `sleep_rc` line, so the Windows process did not report the child's end.
    Whether that Windows process outlived the stop is not known: the host has many unrelated
    `python.exe` processes.
- **Guard record:**
  - the stop was a breach of kind `interrupted`, with no failures and no containers;
  - 14 reads per volume, the longest 0.001 s, the greatest staleness 0.501 s;
  - last samples: C: 185,923,481,600 B, E: 142,138,482,688 B.
- **Consequence, as V9 section 6 states:** during the packet operation, a guard stop does not reach
  the nested Linux children. Their closure is then unknown, it is recorded so, and the chain stops.
