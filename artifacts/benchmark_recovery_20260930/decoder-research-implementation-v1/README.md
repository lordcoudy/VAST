Artifact-only decoder mechanism experiment for reviewed planning commit
`b1ad01c09b4e21f542f971b9dc794548245719b0` (PR comment5901895914).
No production runtime source, image, model, guardian or benchmark authority is changed.
The first original source/GPU attempt has not been started. Root and independent
controller review must finish before executing this command once:

```
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -I -B /mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decoder-research-implementation-v1/controller.py --project-root /mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec --output-dir /mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec/artifacts/benchmark_recovery_20260930/decoder-research-attempt-01
```

The exclusively created output directory consumes that attempt. An existing directory
is rejected; there is no restart, resume, retry, replacement container or alternative
prefix. One original container owns four sequential fresh source children and decoder
pipelines: front_gate/default, front_gate/zero, underbody/zero, underbody/default.
The actual image is
`sha256:70696f057232acd382f60beaaf12cd9279b317b0ba9a7ade29f0b955ce90481a`.
The exact original container remains available for terminal inspection, then only its
verified nonrunning64hexCID is removed. Positive original terminal state, actual CLI
return and exact absence are separate recorded facts.

The original output layout is fixed:

```
decoder-research-attempt-01/
  controller/
    execution-plan.v1.json
    reservation.v1.json
    launch-intent.v1.json
    process-start.v1.json
    original.cid
    original.stdout
    original.stderr
    engine-NN.stdout
    engine-NN.stderr
    engine-NN.v1.json
    closed-controller-leaves.v1.json
    terminal.v1.json
  guest/
    metadata/
      events.jsonl
      registry.stdout
      registry.stderr
      prelaunch.v1.json
      final-package-pins.v1.json
      paired-timing.v1.json
      research-terminal.v1.json
    run-01-front_gate-default/
    run-02-front_gate-zero/
    run-03-underbody-zero/
    run-04-underbody-default/
```

Every original run directory contains `events.jsonl`, `run-started.v1.json`,
`startup-completed.v1.json`, `source-admission.raw`, `source-status.raw`,
`source-ack.raw`, `source-control.raw`, `source-transport.raw`, `source.stdout`,
`source.stderr`, `source-transport-eof.v1.json`,
`decoder-drain-completed.v1.json`, `observations.v1.json` and receipt-last
`terminal.v1.json`. Failed runs retain only the prefix/stages actually reached; missing
stages are not fabricated. Later settings are not executed after a failed original run.

JSON documents have a standard self seal: SHA256 of canonical ASCII JSON with sorted
keys, compact separators, `ensure_ascii=True`, `allow_nan=False`, excluding `sha256`.
Their physical descriptors hash the actual complete file bytes, including the final
newline. JSONL event rows are canonical, consecutive one-based `event_seq`, bounded
to512 rows and16KiB each. They carry the original guest monotonic observe timestamp.
Source admission milliseconds remain original realtime evidence; no admission/decoder
cross-clock subtraction is reported. Host clocks are controller bounds only.

Each per-run terminal binds `closed_original_leaves`: physical descriptors of every
completed or failed-prefix file observed after raw streams close. It separately binds
the observations document. Guest descriptors under `/opt/vast/output/` map only to
the original attempt's `guest/` mount on the host; do not resolve them as host-global
paths. Package/media descriptors name actual guest inputs, not output-leaf authority.
The outer controller terminal binds its closed leaf manifest and the original guest
terminal. It marks completion provisional: `independent_cold_recomputed=false` and
`research_conclusion_authorized=false`. A zero original controller exit establishes
only original process/container completion and guest-reported checks.

Final leaf hashes obey the original deadlines, and each owner checks its clock again
immediately after final streams and pins close. If the last append/fsync crosses the
120s run,15s cleanup or600s whole bound, an immutable
`receipt-time-limit-failure.v1.json` retains the earlier terminal as a pre-crossing
observation. The owner returns nonzero and starts no later setting. Cold review must
reject that failure companion, even if the earlier provisional terminal reported
success. Two16KiB final/failure slots are reserved before ordinary output writes.

Independent cold recomputation must hold and stream-hash every physical descriptor,
recheck epochs across the join, and reconstruct observations from the original leaves:

- Read exact32 original admission JSON lines, original status lifecycle, exact ACK1–32
  and original START/STOP commands. Bind actual source launch PID/PPID/startticks/boot,
  source ELF/media descriptors, original dataset/stream/run identities, window and
  source parameters. The source's JSON event declares payload length/hash and native
  PTS; it does not declare DTS or duration.
- Stream `source-transport.raw` using the original80-byte big-endian header
  `>8sHHQQQQQQIIIQ`, then its three length-delimited UTF8 text fields and payload.
  Check exact32 frames/no trailing bytes, consecutive sequence/cycle0, magic/version/
  keyframe flags, declared sizes/text/identity, actual full payload SHA, native and600
  scaled transportPTS, original unsigned/missing DTS and duration. Recompute raw
  aggregate, exact duration-driven schedule steps and the reviewed minimum cadence.
- Join decoder sink/src/RGB journal rows by actual unique transportPTS. Require all32
  complete PTS multisets; retain presentation order. Recompute sink→src monotonic
  residence and original-sequence cohorts1–8,9–24,25–32. The actual decoder-sink EOS
  event, not the sourceEOF/appsrc request, determines which outputs are flush-only.
  Any central flush-only output marks that pair insufficient for steady-state timing.
- Compare original per-PTS observed RGB pixel hashes, dimensions, RGB format, caps/
  features, full output multiplicity/order and original AU metadata/hash across each
  clip's two settings. Pixel hashes remain the actual consumer's observed active-row
  hashes; cold checking does not re-decode or independently recreate the pixels.
- Recompute paired latency differences from these original rows, including all startup
  and tail records. Keep hold/hash and appsrc-blocking observations as limitations.
  Neither timing differences nor full correctness establishes hardware utilization,
  model/parity results, six-stream100ms feasibility or publication acceptance.

Research admission remains one shared120s prelaunch,45s startup per run,31.5s source
window,10s sourceEOF-through-feeder/decoder drain,15s cleanup,120s per run and600s
whole controller. Raw original packets are at most128MiB/run, with80B reserved within
that cap for a failed next header. Original stdout/stderr are1MiB/channel; mapped RGB
and per-payload are64MiB; appsrc/appsink one buffer. Run namespaces are256MiB each.
Guest and controller metadata each admit at most16MiB, giving32MiB combined. No
additional CPU/PID/memory cgroup limits or production properties are applied.

Synthetic test receipt `decoder-research-controller-tests/attempt-05/terminal.v1.json`
records the final20 focused tests with stable four-file source hashes. These
tests exercise real pipes, bounded parser/prefix preservation, active RGB row layout,
fixed cohort/EOS joins, a post-receipt deadline crossing and small actual Python-child EOF/timeout fixtures. They do not
import GI or execute the packaged source, Docker daemon or decoder, and do not grant
engine/socket or research acceptance. Historical test attempts and prerequisite ledger
v1 remain unchanged.
