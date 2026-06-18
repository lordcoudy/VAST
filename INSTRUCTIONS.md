# Project Usage Instruction

This instruction explains how to install dependencies and run the experiment project on a target device.

## Target Platform

Primary target used by the experiment design:
- GPU: NVIDIA RTX 3060
- CPU: Intel Core i7-14700K
- RAM: 22 GB

## Supported OS Paths

1. Linux (recommended): Ubuntu 22.04/24.04 for complete stack support (DeepStream, Savant, OpenVINO, GStreamer).
2. Windows (partial native + full via WSL2):
   - Native Windows path can install Python/OpenVINO/GStreamer.
   - DeepStream and Savant should be run through WSL2 Ubuntu (or native Linux).

## One-Command Auto Launcher

Use the cross-platform launcher from project root:

```bash
python3 scripts/setup_target.py
```

On Windows:

```powershell
py scripts\setup_target.py
```

It auto-detects OS and calls:
- Linux: `scripts/setup_target.sh`
- Windows: `scripts/setup_target_windows.ps1`

## Fixed Input/Model Layout Used By Real Templates

After setup, these paths are expected and used automatically:
- Video streams:
  - `data/videos/stream01.mp4`
  - `data/videos/stream02.mp4`
  - `data/videos/stream03.mp4`
  - `data/videos/stream04.mp4`
  - `data/videos/stream05.mp4`
  - `data/videos/stream06.mp4`
- OpenVINO IR model:
  - `models/openvino/public/intel/person-vehicle-bike-detection-crossroad-0078/FP16/person-vehicle-bike-detection-crossroad-0078.xml`

These are created by:

```bash
bash scripts/prepare_assets.sh
```

`scripts/setup_target.sh` runs this automatically unless `PREPARE_ASSETS=0`.

## A) Linux Full Setup (Recommended)

From project root:

```bash
chmod +x scripts/setup_target.sh
./scripts/setup_target.sh
```

What this script installs:
- Base tools: Python, pip, venv, git, ffmpeg, build dependencies
- GStreamer runtime + dev packages
- Docker
- NVIDIA Container Toolkit for GPU containers
- Python venv dependencies from requirements.txt
- OpenVINO Python packages
- Pull attempt for:
   - DeepStream container image: nvcr.io/nvidia/deepstream:7.0-triton-multiarch
   - Savant container image: ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0

Notes:
- DeepStream pull may require NGC login:
  - `docker login nvcr.io`
- If your user is newly added to the docker group, re-login is required.

Optional environment variables for setup script:
- `INSTALL_DOCKER=0` skip Docker install
- `INSTALL_GPU_STACK=0` skip NVIDIA Container Toolkit
- `INSTALL_OPENVINO=0` skip OpenVINO Python packages
- `INSTALL_DEEPSTREAM=0` skip DeepStream pull
- `INSTALL_SAVANT=0` skip Savant pull
- `DOCKER_PULL_TIMEOUT=1200` cap each image pull in seconds (0 disables the cap)
- `DEEPSTREAM_IMAGE=...` custom image
- `SAVANT_IMAGE=...` custom image

Example:

```bash
INSTALL_SAVANT=0 ./scripts/setup_target.sh
```

## B) Windows Setup

Run PowerShell as Administrator in project root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\setup_target_windows.ps1
```

What this script does:
- Installs Chocolatey if missing
- Installs core tools (git, python, docker desktop, NVIDIA display driver)
- Installs WSL2 Ubuntu (recommended path for DeepStream + Savant)
- Installs OpenVINO Python packages on Windows
- Installs GStreamer on Windows

Important:
- DeepStream is Linux-first; run full stack in WSL2 Ubuntu or native Linux.
- After WSL setup, open Ubuntu and run:

```bash
bash scripts/setup_target.sh
```

## Verify Installation

Activate venv:

```bash
source .venv/bin/activate
```

Check detected hardware:

```bash
python scripts/check_system.py
```

Expected on target device:
- GPU contains RTX 3060
- CPU contains i7-14700K
- RAM close to 22 GB

## OpenVINO GVA Plugin Install (gvadetect)

If `openvino_gva` fails with `gvadetect element is unavailable`, install DL Streamer plugins in the same Linux/WSL environment where experiments run:

```bash
bash scripts/install_openvino_dlstreamer.sh
```

For a Windows host running commands through WSL, run:

```bash
wsl -e bash -lc "cd /mnt/e/STUDY/VAST; bash scripts/install_openvino_dlstreamer.sh"
```

The script performs a verification check and exits non-zero unless `gst-inspect-1.0 gvadetect` is visible.
If apt packages are unavailable for your Ubuntu release, the script automatically falls back to extracting DL Streamer runtime from `intel/dlstreamer:latest` and configures environment variables under `/etc/profile.d/vast_dlstreamer.sh`.

## Run Experiments

Smoke test:

```bash
python scripts/run_experiments.py --systems deepstream --scenarios baseline --repeats 1 --warmup 0 --measurement 20
```

Full matrix from config:

```bash
python scripts/run_experiments.py
```

## Analyze Results

Analyze latest run:

```bash
python scripts/analyze_results.py
```

Analyze a specific run folder:

```bash
python scripts/analyze_results.py --run runs/<run_timestamp>
```

Reports are written to:
- `reports/<run_timestamp>/summary_aggregated.csv`
- `reports/<run_timestamp>/*.png`

## Run Real Pipelines

`configs/experiments.yaml` is already wired to `scripts/run_system_template.sh`, which contains real command templates for:
- DeepStream
- Savant
- OpenVINO + GVA
- GStreamer + custom plugin
- Custom C++ + CUDA + Qt

`benchmark` mode is the default behavior. It accepts only native schema-v2
`frames.csv` telemetry and fails when an adapter does not provide it.
Runtime-derived rows are synthetic and available only with `--mode smoke`.
Synthetic, skipped, and legacy rows are excluded from publishable analysis.

To execute real pipelines:

```bash
python scripts/run_experiments.py --systems deepstream --scenarios baseline --repeats 1 --warmup 0 --measurement 30
```

Tailored behavior in real templates:
- DeepStream: pinned to `nvcr.io/nvidia/deepstream:7.0-triton-multiarch`, uses `deepstream-test3-app` with stream URIs from `data/videos/streamXX.mp4`.
- Savant: pinned to `ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0` and uses module config at `/workspace/project/deploy/savant/module.yml`.
- OpenVINO+GVA: pinned OpenVINO Python install `2024.6.0`, uses `gvadetect` with the exact OpenVINO model XML path above.
- GStreamer custom: expects plugin in `build/lib` by default (`GST_PLUGIN_PATH`), and falls back to `identity` unless `GST_CUSTOM_STRICT=1`.
- Custom CUDA + Qt: builds `build/bin/adaptive_scheduler_app` from
  `deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cu` through CMake and runs
  its Qt dashboard with `QT_QPA_PLATFORM=offscreen`.

Savant module details:
- File: `deploy/savant/module.yml`
- Schema: valid for Savant v0.5.x line (pinned to v0.5.17 image)
- Pipeline: `uridecodebin -> nvinfer@detector (PeopleNet) -> devnull_sink`

Useful template environment variables:
- `DEEPSTREAM_IMAGE`, `DEEPSTREAM_CONFIG`
- `SAVANT_IMAGE`, `SAVANT_MODULE`, `SAVANT_SOURCE`
- `OPENVINO_MODEL_XML`, `OPENVINO_SOURCE`
- `OPENVINO_GVA_IMAGE` (default: `intel/dlstreamer:latest`)
- `OPENVINO_GVA_USE_CONTAINER` (`1` by default; set `0` to force host runtime path)
- `GST_CUSTOM_PLUGIN`, `GST_CUSTOM_SOURCE`
- `CUSTOM_APP_BIN`
- `EXPERIMENT_SCENARIO_JSON`, `EXPERIMENT_DISTRIBUTED`, `EXPERIMENT_HOST_ROLE`, `EXPERIMENT_PIPELINE_STAGES`
- `BENCHMARK_MODE`, `DATASET_NAME`, `DATASET_STREAMS_JSON`, `EXPERIMENT_RUN_ID`, `EXPERIMENT_RUN_SEED`
- `SCHEDULER_POLICY`, `QL_HEFT_POLICY_ARTIFACT`
- `NATIVE_PROBE_BIN`, `DEEPSTREAM_NATIVE_PROBE_IMAGE`, `SAVANT_NATIVE_PROBE_IMAGE`
- `SAVANT_CANONICAL_MODULE`, `DEEPSTREAM_PGIE_CONFIG`, `GST_CUSTOM_STRICT`
- `DISTRIBUTED_NATIVE_CMD_<SYSTEM>_<ROLE>` or `DISTRIBUTED_NATIVE_CMD` as override paths for native role-specific RTP commands

## Scenario Schema and Distributed Runs

`configs/experiments.yaml` now uses structured scenario definitions:
- `workload`: stream count/range, object density, burst profile, and optional variants
- `pipeline`: ordered video analytics stages
- `placement`: maps each stage to a logical role such as `local`, `edge`, `gpu_worker`, or `aggregator`
  - `network`: records measured-network acceptance ranges
- `distributed`: enables staged SSH orchestration with RTP endpoints

Distributed host inventory lives in `configs/hosts.yaml`. Replace the placeholder hostnames with real SSH-accessible Linux/WSL hosts:

```yaml
hosts:
  - name: edge-node
    address: edge01.example.net
    user: vast
    port: 22
    project_path: /opt/vast
    roles: [edge]
```

Do not store SSH keys, passwords, or private credentials in the repository.

Execution modes:
- `--run-kind heterogeneous`: regular one-server CPU/GPU execution; `--run-kind local` remains a deprecated alias.
- `--run-kind single-server-distributed`: launches `edge`, `gpu_worker`, and `aggregator` through SSH on one server and disables project rsync.
- `--run-kind distributed`: launches roles on the hosts from `configs/hosts.yaml`.

Prepare and validate the public benchmark dataset:

```bash
python scripts/check_dataset.py --dataset mot17_uadetrac_public
```

Preview the resolved launch plan without creating a run:

```bash
python scripts/run_experiments.py --mode smoke --run-kind heterogeneous --dry-run-plan --systems custom_cpp_cuda_qt --scenarios canonical_heterogeneous --repeats 1 --measurement 5
python scripts/run_experiments.py --mode smoke --run-kind single-server-distributed --dry-run-plan --systems custom_cpp_cuda_qt --scenarios canonical_distributed --single-server-host 127.0.0.1 --repeats 1 --measurement 5
python scripts/run_experiments.py --mode smoke --run-kind distributed --dry-run-plan --systems custom_cpp_cuda_qt --scenarios canonical_distributed --hosts-config configs/hosts.yaml --repeats 1 --measurement 5
```

Build strict native probe images for DeepStream and Savant:

```bash
scripts/build_native_probe_images.sh
```

Run on real hosts after `configs/hosts.yaml` is configured:

```bash
python scripts/run_experiments.py --mode benchmark --dataset mot17_uadetrac_public --run-kind distributed --systems deepstream savant openvino_gva gstreamer_custom --scenarios canonical_distributed --hosts-config configs/hosts.yaml --repeats 5
```

Distributed roles start as `aggregator`, `gpu_worker`, then `edge`. Multi-host
preflight requires `chronyc`, `ping`, and `iperf3`. Single-server SSH topology
writes `same_host_loopback` network metrics and skips chrony/iperf checks.
Network shaping is not applied. The degraded network scenario is skipped unless
measured values match its configured acceptance ranges.

Canonical RTP transport uses one UDP port per stream:
`edge_to_gpu_worker + stream_id * stream_port_stride` and
`gpu_worker_to_aggregator + stream_id * stream_port_stride`. The strict trace
header extension is id `1`, URI `urn:vast:rtp-trace:v1`, and contains
`stream_id`, `frame_id`, and original ingress timestamp.

Use `--run-kind local` to execute a scenario through the local path for smoke testing:

```bash
python scripts/run_experiments.py --mode smoke --run-kind local --systems custom_cpp_cuda_qt --scenarios canonical_heterogeneous --repeats 1 --warmup 0 --measurement 5
```


Run this on target to execute real paths:


    python3 scripts/setup_target.py


    bash scripts/prepare_assets.sh


    wsl -e bash -lc "cd /mnt/e/STUDY/VAST; source .venv/bin/activate; STARTUP_GRACE_S=60 CMD_TIMEOUT_S=240 CMD_KILL_AFTER_S=10 EXPERIMENT_CMD_TIMEOUT_S=260 python ./scripts/run_experiments.py --systems deepstream savant openvino_gva gstreamer_custom custom_cpp_cuda_qt --scenarios baseline --repeats 1 --warmup 0 --measurement 30"
