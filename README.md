# VAST Video Analytics Benchmark

This project scaffolds the experimental study described in exp.txt for the target platform:
- GPU: NVIDIA RTX 3060
- CPU: Intel Core i7-14700K
- RAM: 22 GB
- SLO deadline: 3 seconds end-to-end latency

The default `benchmark` mode is strict: publishable runs require native
per-frame telemetry schema v2. Runtime-derived synthetic rows are available
only in explicit `smoke` mode and are excluded from scientific reports.

It includes:
- Scenario and protocol configuration
- Automated experiment runner
- CPU/GPU metric collection at 1-second frequency
- Repetition handling and structured outputs
- Summary analysis and comparison plots
- Target setup scripts for Linux and Windows/WSL2

## Project layout

- `configs/experiments.yaml`: Hardware target, protocol, structured scenarios, and system command templates
- `configs/datasets.yaml`: Public benchmark and synthetic smoke dataset manifests
- `configs/hosts.yaml`: SSH host inventory used by distributed scenarios
- `scripts/check_system.py`: Prints detected hardware
- `scripts/collect_metrics.py`: CPU/GPU sampler (CSV)
- `scripts/run_experiments.py`: Main matrix execution tool
- `scripts/distributed_executor.py`: SSH/rsync/scp executor for multi-host scenarios
- `scripts/check_dataset.py`: Dataset checksum validator
- `scripts/train_ql_heft.py`: Seeded offline QL-HEFT policy trainer
- `docs/NATIVE_ADAPTERS.md`: Required native probe and distributed RTP contract
- `scripts/analyze_results.py`: Aggregation and plotting
- `scripts/setup_target.sh`: Linux full-stack bootstrap script
- `scripts/setup_target_windows.ps1`: Windows bootstrap + WSL2 preparation
- `scripts/setup_target.py`: One-command OS auto-detect launcher for installers
- `scripts/run_system_template.sh`: Real DeepStream/Savant/OpenVINO/GStreamer/C++ command templates
- `scripts/emit_runtime_frames_csv.py`: Runtime-derived per-frame CSV exporter used when system commands do not natively write frame metrics
- `scripts/prepare_assets.sh`: Builds 6-stream video layout and downloads OpenVINO model to fixed paths
- `INSTRUCTIONS.md`: Full setup and usage guide
- `runs/`: Raw run outputs (generated)
- `reports/`: Aggregated reports and figures (generated)

## 1) Setup

Preferred Linux setup:

```bash
chmod +x scripts/setup_target.sh
./scripts/setup_target.sh
```

One-command auto launcher (recommended):

```bash
python3 scripts/setup_target.py
```

Asset paths used by real templates:
- Videos: `data/videos/stream01.mp4` ... `data/videos/stream06.mp4`
- OpenVINO model: `models/openvino/public/intel/person-vehicle-bike-detection-crossroad-0078/FP16/person-vehicle-bike-detection-crossroad-0078.xml`
- Savant module: `deploy/savant/module.yml` (pinned for image `ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0`)

Pinned system defaults:
- DeepStream image: `nvcr.io/nvidia/deepstream:7.0-triton-multiarch`
- Savant image: `ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0`
- OpenVINO Python: `2024.6.0`
- Custom CUDA + Qt reference app source: `deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu`

Prepare assets manually (if needed):

```bash
bash scripts/prepare_assets.sh
```

Windows setup (run PowerShell as Administrator):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_target_windows.ps1
```

Windows one-command launcher:

```powershell
py scripts\setup_target.py
```

Manual Python-only setup (minimal):

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2) Validate hardware visibility

```bash
python scripts/check_system.py
```

Expected target:
- GPU string should include RTX 3060
- CPU string should include i7-14700K
- RAM should be close to 32 GB

## 3) Scenario schema

Scenarios in `configs/experiments.yaml` use the structured schema:
- `workload`: `streams` or `stream_range`, object density, optional burst profile, optional variants
- `pipeline`: ordered stages such as `decode`, `detect`, `track`, `classify`, `record`, `aggregate`
- `placement`: stage-to-role mapping and a placement policy label
- `network`: latency, jitter, bandwidth, and packet-loss profile for distributed runs
- `distributed`: enables SSH-based multi-host execution and artifact collection

Distributed scenarios use logical roles such as `edge`, `gpu_worker`, and `aggregator`. Map those roles to real SSH hosts in `configs/hosts.yaml`; keep SSH keys and credentials outside the repo.

## 4) Run experiments

Run the complete matrix from the config:

```bash
python scripts/run_experiments.py
```

Run a synthetic custom scheduler smoke test:

```bash
python scripts/run_experiments.py --mode smoke --run-kind local \
  --systems custom_cpp_cuda_qt --scenarios baseline --repeats 1 --warmup 0 --measurement 5
```

Preview local or distributed commands without executing them:

```bash
python scripts/run_experiments.py --mode smoke --run-kind local --dry-run-plan \
  --systems custom_cpp_cuda_qt --scenarios baseline --repeats 1 --measurement 5
python scripts/run_experiments.py --mode smoke --dry-run-plan \
  --systems custom_cpp_cuda_qt --scenarios edge_to_worker_distributed \
  --hosts-config configs/hosts.yaml --repeats 1 --measurement 5
```

Validate the public dataset and run a publishable local benchmark:

```bash
python scripts/check_dataset.py --dataset mot17_uadetrac_public
python scripts/run_experiments.py --mode benchmark --dataset mot17_uadetrac_public \
  --run-kind local --systems all --scenarios baseline --repeats 5
```

Run distributed benchmark commands after configuring the three SSH hosts:

```bash
python scripts/run_experiments.py --mode benchmark --dataset mot17_uadetrac_public \
  --run-kind distributed --systems all --scenarios edge_worker_aggregator_distributed \
  --hosts-config configs/hosts.yaml --repeats 5
```

## 5) Analyze

Analyze latest run:

```bash
python scripts/analyze_results.py
```

Analyze a specific run folder:

```bash
python scripts/analyze_results.py --run runs/20260323_120000
```

## Real system commands

In `configs/experiments.yaml`, each system points to `scripts/run_system_template.sh` for:
- NVIDIA DeepStream SDK
- Savant
- Intel OpenVINO + GVA
- GStreamer + custom plugin
- Custom C++ + CUDA + Qt implementation

Keep these placeholders in command strings:
- `{scenario}`
- `{duration_s}`
- `{streams}`
- `{min_objects}`
- `{max_objects}`
- `{output_dir}`

The runner also exports scenario context to templates:
- `EXPERIMENT_SCENARIO_JSON`
- `EXPERIMENT_DISTRIBUTED`
- `EXPERIMENT_HOST_ROLE`
- `EXPERIMENT_PIPELINE_STAGES`

## Notes

- `stream_scaling` automatically expands stream count from 1 to 16.
- Adapters intentionally use native detector models. Cross-system plots compare
  deployable stacks, not isolated scheduler overhead; reports retain detector
  and backend identity for every row.
- `benchmark` mode rejects missing, legacy, and synthetic per-frame telemetry.
- Distributed roles start in the order `aggregator -> gpu_worker -> edge`.
- Distributed benchmark adapters must provide a native `DISTRIBUTED_NATIVE_CMD`
  in host inventory; the common RTP bridge is smoke-only.
- Custom CUDA + Qt runs use `QT_QPA_PLATFORM=offscreen`; train the frozen policy
  with `python scripts/train_ql_heft.py`.
- All run metadata, commands, dataset checksums, git state, and logs are stored per repetition.
- SLO violation rate is computed as percentage of frames with latency > 3000 ms.
- For complete installation and runbook details, see `INSTRUCTIONS.md`.
