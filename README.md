# Video Scheduling Experiment Project

This project scaffolds the experimental study described in exp.txt for the target platform:
- GPU: NVIDIA RTX 3060
- CPU: Intel Core i7-14700K
- RAM: 22 GB
- SLO deadline: 3 seconds end-to-end latency

It includes:
- Scenario and protocol configuration
- Automated experiment runner
- CPU/GPU metric collection at 1-second frequency
- Repetition handling and structured outputs
- Summary analysis and comparison plots
- Target setup scripts for Linux and Windows/WSL2

## Project layout

- `configs/experiments.yaml`: Hardware target, protocol, scenarios, and system command templates
- `scripts/check_system.py`: Prints detected hardware
- `scripts/collect_metrics.py`: CPU/GPU sampler (CSV)
- `scripts/workload_stub.py`: Synthetic workload generator (replace with real pipelines later)
- `scripts/run_experiments.py`: Main matrix execution tool
- `scripts/analyze_results.py`: Aggregation and plotting
- `scripts/setup_target.sh`: Linux full-stack bootstrap script
- `scripts/setup_target_windows.ps1`: Windows bootstrap + WSL2 preparation
- `scripts/setup_target.py`: One-command OS auto-detect launcher for installers
- `scripts/run_system_template.sh`: Real DeepStream/Savant/OpenVINO/GStreamer/C++ command templates with fallback
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
- Custom C++ reference app source: `deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cpp`

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

## 3) Run experiments

Run the complete matrix from the config:

```bash
python scripts/run_experiments.py
```

Run a quick smoke test:

```bash
python scripts/run_experiments.py --systems deepstream savant --scenarios baseline --repeats 1 --measurement 20
```

## 4) Analyze

Analyze latest run:

```bash
python scripts/analyze_results.py
```

Analyze a specific run folder:

```bash
python scripts/analyze_results.py --run runs/20260323_120000
```

## Replacing stubs with real systems

In `configs/experiments.yaml`, replace each system command with your real command line for:
- NVIDIA DeepStream SDK
- Savant
- Intel OpenVINO + GVA
- GStreamer + custom plugin
- Custom C++ + CUDA + Qt implementation

Keep placeholders in command strings:
- `{scenario}`
- `{duration_s}`
- `{streams}`
- `{min_objects}`
- `{max_objects}`
- `{output_dir}`

## Notes

- `stream_scaling` automatically expands stream count from 1 to 12.
- All run metadata, commands, and logs are stored per repetition.
- SLO violation rate is computed as percentage of frames with latency > 3000 ms.
- For complete installation and runbook details, see `INSTRUCTIONS.md`.
