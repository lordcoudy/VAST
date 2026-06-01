#!/usr/bin/env bash
set -euo pipefail

# Full environment bootstrap for Ubuntu 22.04/24.04 on target NVIDIA hardware.
# Installs Python deps, GStreamer stack, Docker, NVIDIA Container Toolkit,
# OpenVINO (Python), and pulls DeepStream/Savant container images.

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
DEEPSTREAM_IMAGE="${DEEPSTREAM_IMAGE:-nvcr.io/nvidia/deepstream:7.0-triton-multiarch}"
SAVANT_IMAGE="${SAVANT_IMAGE:-ghcr.io/insight-platform/savant-deepstream:0.5.17-7.0}"
OPENVINO_PY_VERSION="${OPENVINO_PY_VERSION:-2024.6.0}"
INSTALL_DOCKER="${INSTALL_DOCKER:-1}"
INSTALL_GPU_STACK="${INSTALL_GPU_STACK:-1}"
INSTALL_CUDA_TOOLKIT="${INSTALL_CUDA_TOOLKIT:-1}"
INSTALL_CUDA_TOOLKIT="${INSTALL_CUDA_TOOLKIT:-1}"
INSTALL_OPENVINO="${INSTALL_OPENVINO:-1}"
INSTALL_SAVANT="${INSTALL_SAVANT:-1}"
INSTALL_DEEPSTREAM="${INSTALL_DEEPSTREAM:-1}"
PREPARE_ASSETS="${PREPARE_ASSETS:-1}"
BUILD_REFERENCE_CUSTOM_APP="${BUILD_REFERENCE_CUSTOM_APP:-1}"
CUDA_ARCHITECTURES="${CUDA_ARCHITECTURES:-86}"

log() {
  echo "[setup] $*"
}

warn() {
  echo "[warning] $*" >&2
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "[error] Required command missing: $1" >&2
    exit 1
  fi
}

run_with_timeout() {
  local timeout_secs="$1"
  shift

  if [[ "$timeout_secs" =~ ^[0-9]+$ ]] && [[ "$timeout_secs" -gt 0 ]] && command -v timeout >/dev/null 2>&1; then
    timeout "${timeout_secs}s" "$@"
  else
    "$@"
  fi
}

is_ubuntu() {
  [[ -f /etc/os-release ]] || return 1
  # shellcheck source=/dev/null
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]]
}

install_base_packages() {
  log "Installing base packages"
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    build-essential \
    ca-certificates \
    curl \
    ffmpeg \
    git \
    gnupg \
    jq \
    lsb-release \
    cmake \
    chrony \
    iperf3 \
    pkg-config \
    qt6-base-dev \
    software-properties-common \
    unzip \
    wget \
    python3 \
    python3-dev \
    python3-pip \
    python3-venv
}

install_cuda_toolkit() {
  if [[ "$INSTALL_CUDA_TOOLKIT" != "1" ]]; then
    log "Skipping CUDA toolkit installation"
    return
  fi
  if command -v nvcc >/dev/null 2>&1; then
    log "CUDA toolkit already available"
    return
  fi
  log "Installing NVIDIA CUDA toolkit"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-cuda-toolkit
}

install_gstreamer_packages() {
  log "Installing GStreamer runtime and development packages"
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    gstreamer1.0-tools \
    gstreamer1.0-libav \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-alsa \
    gstreamer1.0-gl \
    gstreamer1.0-gtk3 \
    gstreamer1.0-qt5 \
    gstreamer1.0-pulseaudio \
    libgstreamer1.0-dev \
    libgstreamer-plugins-base1.0-dev
}

install_docker() {
  if [[ "$INSTALL_DOCKER" != "1" ]]; then
    log "Skipping Docker installation"
    return
  fi

  if command -v docker >/dev/null 2>&1; then
    log "Docker already installed"
  else
    log "Installing Docker"
    curl -fsSL https://get.docker.com | sh
  fi

  if groups "$USER" | grep -q '\bdocker\b'; then
    log "User already in docker group"
  else
    sudo usermod -aG docker "$USER"
    warn "Added $USER to docker group. Log out/in or run: newgrp docker"
  fi
}

install_nvidia_container_toolkit() {
  if [[ "$INSTALL_GPU_STACK" != "1" ]]; then
    log "Skipping NVIDIA container toolkit"
    return
  fi

  if ! command -v nvidia-smi >/dev/null 2>&1; then
    warn "nvidia-smi not found. Install NVIDIA driver manually first."
    return
  fi

  log "Installing NVIDIA Container Toolkit"
  curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | \
    sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
  curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
    sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
    sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list >/dev/null

  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y nvidia-container-toolkit

  if command -v nvidia-ctk >/dev/null 2>&1; then
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker || true
  fi
}

setup_python_env() {
  log "Setting up Python virtual environment"
  cd "$PROJECT_DIR"
  if [[ ! -d .venv ]]; then
    "$PYTHON_BIN" -m venv .venv
  fi

  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip wheel setuptools
  if [[ -f requirements.txt ]]; then
    python -m pip install -r requirements.txt
  fi

  if [[ "$INSTALL_OPENVINO" == "1" ]]; then
    log "Installing OpenVINO Python packages"
    python -m pip install "openvino==${OPENVINO_PY_VERSION}" "openvino-dev==${OPENVINO_PY_VERSION}"
  fi
}

build_reference_custom_app() {
  if [[ "$BUILD_REFERENCE_CUSTOM_APP" != "1" ]]; then
    log "Skipping custom CUDA app build"
    return
  fi

  local build_dir="$PROJECT_DIR/build/cmake"
  local out_bin="$PROJECT_DIR/build/bin/adaptive_scheduler_app"

  if [[ ! -f "$PROJECT_DIR/CMakeLists.txt" ]]; then
    warn "Missing root CMakeLists.txt, cannot build custom CUDA app"
    return
  fi

  local build_dir="$PROJECT_DIR/build/cmake"
  local out_bin="$PROJECT_DIR/build/bin/adaptive_scheduler_app"

  if [[ ! -f "$PROJECT_DIR/CMakeLists.txt" ]]; then
    warn "Missing root CMakeLists.txt, cannot build custom CUDA + Qt app"
    return
  fi

  if ! command -v nvcc >/dev/null 2>&1; then
    warn "nvcc not found, cannot build custom CUDA + Qt app"
    return
  fi

  log "Building custom CUDA + Qt app -> $out_bin"
  cmake -S "$PROJECT_DIR" -B "$build_dir" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_CUDA_ARCHITECTURES="$CUDA_ARCHITECTURES"
  cmake --build "$build_dir" --target adaptive_scheduler_app --parallel "$(nproc)"
}

prepare_project_assets() {
  if [[ "$PREPARE_ASSETS" != "1" ]]; then
    log "Skipping project assets preparation"
    return
  fi

  log "Preparing input video layout and OpenVINO model assets"
  bash "$PROJECT_DIR/scripts/prepare_assets.sh"
}

pull_deepstream_image() {
  if [[ "$INSTALL_DEEPSTREAM" != "1" ]]; then
    log "Skipping DeepStream image pull"
    return
  fi

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker is unavailable. Cannot pull DeepStream image."
    return
  fi

  log "Attempting to pull DeepStream image: $DEEPSTREAM_IMAGE"
  if ! run_with_timeout "$DOCKER_PULL_TIMEOUT" docker pull "$DEEPSTREAM_IMAGE"; then
    if [[ "$DOCKER_PULL_TIMEOUT" =~ ^[0-9]+$ ]] && [[ "$DOCKER_PULL_TIMEOUT" -gt 0 ]]; then
      warn "DeepStream pull timed out after ${DOCKER_PULL_TIMEOUT}s."
    else
      warn "DeepStream pull failed."
    fi
    warn "You may need NVIDIA NGC login: docker login nvcr.io"
  fi
}

pull_savant_image() {
  if [[ "$INSTALL_SAVANT" != "1" ]]; then
    log "Skipping Savant image pull"
    return
  fi

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker is unavailable. Cannot pull Savant image."
    return
  fi

  log "Attempting to pull Savant image: $SAVANT_IMAGE"
  if ! run_with_timeout "$DOCKER_PULL_TIMEOUT" docker pull "$SAVANT_IMAGE"; then
    if [[ "$DOCKER_PULL_TIMEOUT" =~ ^[0-9]+$ ]] && [[ "$DOCKER_PULL_TIMEOUT" -gt 0 ]]; then
      warn "Savant pull timed out after ${DOCKER_PULL_TIMEOUT}s."
    else
      warn "Savant image pull failed."
    fi
    warn "Check image name/registry access."
    warn "Alternative: clone https://github.com/insight-platform/Savant and follow its docs."
  fi
}

final_checks() {
  log "Final checks"
  command -v python3 >/dev/null 2>&1 && python3 --version
  command -v gst-launch-1.0 >/dev/null 2>&1 && gst-launch-1.0 --version | head -n 1
  command -v docker >/dev/null 2>&1 && docker --version
  command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi --query-gpu=name,driver_version --format=csv,noheader || true
  log "Setup completed"
}

main() {
  require_cmd sudo
  require_cmd curl

  if ! is_ubuntu; then
    warn "This script is validated for Ubuntu. Continue at your own risk."
  fi

  install_base_packages
  install_gstreamer_packages
  install_docker
  install_nvidia_container_toolkit
  install_cuda_toolkit
  install_cuda_toolkit
  setup_python_env
  prepare_project_assets
  build_reference_custom_app
  pull_deepstream_image
  pull_savant_image
  final_checks

  cat <<'EOF'

Next actions:
1) Re-login if docker group changed.
2) Activate venv: source .venv/bin/activate
3) Verify project hardware check: python scripts/check_system.py
4) Run smoke benchmark:
   python scripts/run_experiments.py --systems deepstream --scenarios baseline --repeats 1 --warmup 0 --measurement 20

EOF
}

main "$@"
