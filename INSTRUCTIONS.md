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
  - DeepStream container image: nvcr.io/nvidia/deepstream:6.4-triton-multiarch
  - Savant container image: ghcr.io/insight-platform/savant-deepstream:latest

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

Real mode is now the default behavior. If a pipeline cannot run or does not produce `frames.csv`, the run fails.
`scripts/run_system_template.sh` now guarantees `frames.csv` export for successful/accepted runs by deriving per-frame rows from real execution time and input-video FPS when native per-frame telemetry is unavailable.

To execute real pipelines:

```bash
python scripts/run_experiments.py --systems deepstream --scenarios baseline --repeats 1 --warmup 0 --measurement 30
```

Tailored behavior in real templates:
- DeepStream: pinned to `nvcr.io/nvidia/deepstream:7.0-triton-multiarch`, uses `deepstream-test3-app` with stream URIs from `data/videos/streamXX.mp4`.
- Savant: pinned to `ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0` and uses module config at `/workspace/project/deploy/savant/module.yml`.
- OpenVINO+GVA: pinned OpenVINO Python install `2024.6.0`, uses `gvadetect` with the exact OpenVINO model XML path above.
- GStreamer custom: expects plugin in `build/lib` by default (`GST_PLUGIN_PATH`), and falls back to `identity` unless `GST_CUSTOM_STRICT=1`.
- Custom C++: uses pinned project reference binary `build/bin/adaptive_scheduler_app` built from `deploy/custom_cpp_cuda_qt/adaptive_scheduler_app.cpp`.

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


Run this on target to execute real paths:


    python3 scripts/setup_target.py


    bash scripts/prepare_assets.sh


    wsl -e bash -lc "cd /mnt/e/STUDY/VAST; source .venv/bin/activate; STARTUP_GRACE_S=60 CMD_TIMEOUT_S=240 CMD_KILL_AFTER_S=10 EXPERIMENT_CMD_TIMEOUT_S=260 python ./scripts/run_experiments.py --systems deepstream savant openvino_gva gstreamer_custom custom_cpp_cuda_qt --scenarios baseline --repeats 1 --warmup 0 --measurement 30"
