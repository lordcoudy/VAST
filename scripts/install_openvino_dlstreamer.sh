#!/usr/bin/env bash
set -euo pipefail

# Install OpenVINO DL Streamer GStreamer plugins and verify gvadetect is available.
# Intended for Ubuntu/WSL Ubuntu where scripts/run_system_template.sh executes.

log() {
  echo "[openvino-dlstreamer] $*"
}

warn() {
  echo "[openvino-dlstreamer][warning] $*" >&2
}

die() {
  echo "[openvino-dlstreamer][error] $*" >&2
  exit 1
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Missing required command: $1"
  fi
}

is_ubuntu() {
  [[ -f /etc/os-release ]] || return 1
  # shellcheck source=/dev/null
  source /etc/os-release
  [[ "${ID:-}" == "ubuntu" ]]
}

install_base_gstreamer() {
  log "Installing base GStreamer packages"
  sudo apt-get update
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    ca-certificates \
    curl \
    gnupg \
    gstreamer1.0-tools \
    gstreamer1.0-libav \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly
}

has_apt_candidate() {
  local pkg="$1"
  apt-cache policy "$pkg" 2>/dev/null | awk '/Candidate:/ {print $2}' | grep -qv '(none)'
}

install_first_available_pkg() {
  local installed=1
  for pkg in "$@"; do
    if has_apt_candidate "$pkg"; then
      log "Installing package: $pkg"
      sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "$pkg"
      installed=0
      break
    fi
  done
  return "$installed"
}

verify_gvadetect() {
  if gst-inspect-1.0 gvadetect >/dev/null 2>&1; then
    log "Verification passed: gvadetect is visible to gst-inspect-1.0"
    gst-inspect-1.0 gvadetect 2>/dev/null | sed -n '1,20p'
    return 0
  fi
  if gst-inspect-1.0 object_detect >/dev/null 2>&1; then
    log "Verification passed: object_detect is visible (modern DL Streamer API)"
    gst-inspect-1.0 object_detect 2>/dev/null | sed -n '1,20p'
    return 0
  fi
  return 1
}

verify_gvadetect_with_env() {
  local gst_plugin_path="$1"
  local ld_library_path="$2"
  local gst_plugin_scanner="$3"

  if GST_PLUGIN_PATH="$gst_plugin_path${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}" \
     LD_LIBRARY_PATH="$ld_library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
     GST_PLUGIN_SCANNER="$gst_plugin_scanner" \
     gst-inspect-1.0 gvadetect >/dev/null 2>&1; then
    log "Verification passed with injected environment"
    GST_PLUGIN_PATH="$gst_plugin_path${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}" \
    LD_LIBRARY_PATH="$ld_library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    GST_PLUGIN_SCANNER="$gst_plugin_scanner" \
    gst-inspect-1.0 gvadetect 2>/dev/null | sed -n '1,20p'
    return 0
  fi

  if GST_PLUGIN_PATH="$gst_plugin_path${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}" \
     LD_LIBRARY_PATH="$ld_library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
     GST_PLUGIN_SCANNER="$gst_plugin_scanner" \
     gst-inspect-1.0 object_detect >/dev/null 2>&1; then
    log "Verification passed with injected environment (object_detect)"
    GST_PLUGIN_PATH="$gst_plugin_path${GST_PLUGIN_PATH:+:$GST_PLUGIN_PATH}" \
    LD_LIBRARY_PATH="$ld_library_path${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    GST_PLUGIN_SCANNER="$gst_plugin_scanner" \
    gst-inspect-1.0 object_detect 2>/dev/null | sed -n '1,20p'
    return 0
  fi

  return 1
}

install_from_intel_dlstreamer_image() {
  local image="${DLSTREAMER_IMAGE:-intel/dlstreamer:latest}"
  local install_root="${DLSTREAMER_INSTALL_ROOT:-/opt/vast/dlstreamer}"
  local cid profile_file

  if ! command -v docker >/dev/null 2>&1; then
    warn "Docker is unavailable; cannot use image fallback"
    return 1
  fi

  log "Trying Docker fallback from image: $image"
  docker pull "$image" >/dev/null

  cid="$(docker create "$image" bash -lc 'sleep 600')"
  trap 'docker rm -f "$cid" >/dev/null 2>&1 || true; trap - RETURN' RETURN

  sudo mkdir -p "$install_root"
  sudo rm -rf "$install_root/lib" "$install_root/gstreamer" "$install_root/opencv" "$install_root/openvino"
  sudo mkdir -p "$install_root"
  sudo rm -rf /tmp/dlstreamer_lib /tmp/dlstreamer_gstreamer /tmp/dlstreamer_opencv /tmp/dlstreamer_openvino

  # Copy runtime trees that libgstvideoanalytics.so depends on.
  docker start "$cid" >/dev/null
  docker cp "$cid:/opt/intel/dlstreamer/lib" /tmp/dlstreamer_lib
  docker cp "$cid:/opt/intel/dlstreamer/gstreamer" /tmp/dlstreamer_gstreamer
  docker cp "$cid:/opt/opencv" /tmp/dlstreamer_opencv

  if docker exec "$cid" bash -lc "mkdir -p /tmp/vast_ov && cp -a /usr/lib/libopenvino.so* /tmp/vast_ov/ 2>/dev/null || cp -a /usr/lib/x86_64-linux-gnu/libopenvino.so* /tmp/vast_ov/ 2>/dev/null || true"; then
    docker cp "$cid:/tmp/vast_ov" /tmp/dlstreamer_openvino >/dev/null 2>&1 || true
  fi

  sudo mv /tmp/dlstreamer_lib "$install_root/lib"
  sudo mv /tmp/dlstreamer_gstreamer "$install_root/gstreamer"
  sudo mv /tmp/dlstreamer_opencv "$install_root/opencv"
  sudo mkdir -p "$install_root/openvino"
  if [[ -d /tmp/dlstreamer_openvino ]]; then
    sudo cp -a /tmp/dlstreamer_openvino/. "$install_root/openvino/"
  fi

  profile_file="/etc/profile.d/vast_dlstreamer.sh"
  sudo tee "$profile_file" >/dev/null <<EOF
export GST_PLUGIN_PATH="$install_root/gstreamer/lib:$install_root/lib:\${GST_PLUGIN_PATH:-}"
export LD_LIBRARY_PATH="$install_root/lib:$install_root/gstreamer/lib:$install_root/opencv:$install_root/openvino:\${LD_LIBRARY_PATH:-}"
export GST_PLUGIN_SCANNER="$install_root/gstreamer/bin/gstreamer-1.0/gst-plugin-scanner"
EOF

  if verify_gvadetect_with_env \
    "$install_root/gstreamer/lib:$install_root/lib" \
    "$install_root/lib:$install_root/gstreamer/lib:$install_root/opencv:$install_root/openvino" \
    "$install_root/gstreamer/bin/gstreamer-1.0/gst-plugin-scanner"; then
    log "Docker fallback installation succeeded"
    log "Environment is persisted via $profile_file"
    return 0
  fi

  warn "Docker fallback extracted files but gvadetect still not visible"
  return 1
}

configure_openvino_repo() {
  local codename version_major keyring repo_file key_ok=1

  codename="$(lsb_release -cs)"
  version_major="$(lsb_release -rs | cut -d. -f1)"
  keyring="/usr/share/keyrings/intel-openvino-archive-keyring.gpg"
  repo_file="/etc/apt/sources.list.d/intel-openvino.list"

  log "Configuring Intel OpenVINO APT repository"

  if curl -fsSL "https://apt.repos.intel.com/openvino/2024/intel-openvino-2024.key" | sudo gpg --batch --yes --dearmor -o "$keyring"; then
    key_ok=0
  elif curl -fsSL "https://apt.repos.intel.com/openvino/intel-openvino-2024.key" | sudo gpg --batch --yes --dearmor -o "$keyring"; then
    key_ok=0
  fi

  if [[ "$key_ok" -ne 0 ]]; then
    warn "Could not download Intel OpenVINO APT key."
    return 1
  fi

  # Try codename-based repo first, then fallback to ubuntu<major> token.
  echo "deb [signed-by=$keyring] https://apt.repos.intel.com/openvino/2024 $codename main" | sudo tee "$repo_file" >/dev/null
  if ! sudo apt-get update; then
    warn "Repo line with codename '$codename' failed; trying ubuntu$version_major"
    echo "deb [signed-by=$keyring] https://apt.repos.intel.com/openvino/2024 ubuntu$version_major main" | sudo tee "$repo_file" >/dev/null
    sudo apt-get update
  fi

  return 0
}

main() {
  require_cmd sudo
  require_cmd apt-get
  require_cmd apt-cache
  require_cmd curl
  require_cmd gpg
  require_cmd lsb_release

  if ! is_ubuntu; then
    warn "This installer is designed for Ubuntu/WSL Ubuntu. Continuing anyway."
  fi

  install_base_gstreamer

  if verify_gvadetect; then
    log "Nothing else to do."
    exit 0
  fi

  # Common package names used by distro/repo variants.
  local -a dlstreamer_pkgs=(
    gstreamer1.0-dlstreamer
    dlstreamer
    intel-dlstreamer-gst
    openvino-gstreamer
  )

  if install_first_available_pkg "${dlstreamer_pkgs[@]}"; then
    if verify_gvadetect; then
      exit 0
    fi
  fi

  warn "DL Streamer package was not available in current apt sources."
  if [[ "${DLSTREAMER_TRY_INTEL_APT:-0}" == "1" ]]; then
    if configure_openvino_repo; then
      if install_first_available_pkg "${dlstreamer_pkgs[@]}"; then
        if verify_gvadetect; then
          exit 0
        fi
      fi
    fi
  fi

  if install_from_intel_dlstreamer_image; then
    exit 0
  fi

  if [[ "${DLSTREAMER_TRY_INTEL_APT:-0}" != "1" ]]; then
    warn "Docker fallback failed; trying Intel OpenVINO APT repository"
    if configure_openvino_repo; then
      if install_first_available_pkg "${dlstreamer_pkgs[@]}"; then
        if verify_gvadetect; then
          exit 0
        fi
      fi
    fi
  fi

  die "Neither gvadetect nor object_detect is available. Run 'apt-cache search dlstreamer' and install a package providing DL Streamer GStreamer elements for your distro."
}

main "$@"
