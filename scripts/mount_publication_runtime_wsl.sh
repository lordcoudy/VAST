#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: mount_publication_runtime_wsl.sh [options]' \
    '' \
    'Create or verify the exact read-only ext4 runtime mounts used by the WSL benchmark.' \
    '' \
    'Options:' \
    '  --source-runtime PATH          Canonical ext4 venv built with python -m venv --copies.' \
    '  --project-root PATH            Benchmark project root.' \
    '  --project-runtime-mount PATH   Project-relative mount point.' \
    '  --check-only                   Verify existing mounts without changing them.' \
    '  -h, --help                     Show this help.'
}

die() {
  printf '[publication-runtime-mount][error] %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

source_runtime="${VAST_PUBLICATION_RUNTIME_SOURCE:-${HOME}/.local/state/vast/publication/runtime/full-publication-cp312-v1}"
project_root=""
project_runtime_mount=".publication-runtime/full-publication-cp312-v1"
check_only=0

while (($#)); do
  case "$1" in
    --source-runtime)
      (($# >= 2)) || die '--source-runtime requires a value'
      source_runtime="$2"
      shift 2
      ;;
    --project-root)
      (($# >= 2)) || die '--project-root requires a value'
      project_root="$2"
      shift 2
      ;;
    --project-runtime-mount)
      (($# >= 2)) || die '--project-runtime-mount requires a value'
      project_runtime_mount="$2"
      shift 2
      ;;
    --check-only)
      check_only=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ "$(uname -s)" == "Linux" ]] || die 'this helper requires Linux/WSL'
[[ -n "$project_root" ]] || die '--project-root is required'
[[ "$project_runtime_mount" != /* ]] || die 'project runtime mount must be relative'
[[ "$project_runtime_mount" != "" ]] || die 'project runtime mount must not be empty'

IFS='/' read -r -a mount_parts <<<"$project_runtime_mount"
for part in "${mount_parts[@]}"; do
  [[ -n "$part" && "$part" != "." && "$part" != ".." ]] \
    || die 'project runtime mount is not canonical'
done

for command_name in findmnt readlink stat sha256sum; do
  require_command "$command_name"
done
if ((check_only == 0)); then
  require_command mount
  require_command umount
  [[ "${EUID}" -eq 0 ]] || die 'mount materialization must run as root'
fi

[[ -d "$source_runtime" ]] || die 'source runtime directory is missing'
[[ -d "$project_root" ]] || die 'project root directory is missing'
source_runtime="$(readlink -f -- "$source_runtime")"
project_root="$(readlink -f -- "$project_root")"
[[ -n "$source_runtime" && -n "$project_root" ]] || die 'failed to canonicalize paths'

source_python="$source_runtime/bin/python"
[[ -f "$source_python" && ! -L "$source_python" ]] \
  || die 'source Python must be a copied regular file'
[[ "$(stat -Lc '%h' -- "$source_python")" == "1" ]] \
  || die 'source Python must have one hard link'

source_parent_fstype="$(findmnt -rn -T "$source_runtime" -o FSTYPE)"
[[ "$source_parent_fstype" == "ext4" ]] || die 'source runtime must reside on ext4'

target="$project_root/$project_runtime_mount"
cursor="$project_root"
for part in "${mount_parts[@]}"; do
  cursor="$cursor/$part"
  [[ ! -L "$cursor" ]] || die 'project runtime mount ancestry contains a symbolic link'
  if [[ -e "$cursor" && ! -d "$cursor" ]]; then
    die 'project runtime mount ancestry contains a non-directory'
  fi
  if ((check_only == 0)) && [[ ! -d "$cursor" ]]; then
    mkdir -- "$cursor"
  fi
done
[[ -d "$target" ]] || die 'project runtime mount directory is missing'

mount_target() {
  findmnt -rn -T "$1" -o TARGET
}

is_exact_mount() {
  [[ "$(mount_target "$1")" == "$1" ]]
}

mount_is_ext4_read_only() {
  local path="$1"
  local fstype options
  is_exact_mount "$path" || return 1
  fstype="$(findmnt -rn -T "$path" -o FSTYPE)"
  options="$(findmnt -rn -T "$path" -o OPTIONS)"
  [[ "$fstype" == "ext4" ]] || return 1
  case ",$options," in
    *,ro,*) return 0 ;;
    *) return 1 ;;
  esac
}

source_created=0
target_created=0
cleanup_partial_mounts() {
  local status=$?
  if ((status != 0)); then
    if ((target_created == 1)); then
      umount -- "$target" >/dev/null 2>&1 || true
    fi
    if ((source_created == 1)); then
      umount -- "$source_runtime" >/dev/null 2>&1 || true
    fi
  fi
  exit "$status"
}
trap cleanup_partial_mounts EXIT

if ((check_only == 0)); then
  if is_exact_mount "$source_runtime"; then
    mount_is_ext4_read_only "$source_runtime" \
      || die 'existing exact source mount is not read-only ext4'
  else
    mount --bind "$source_runtime" "$source_runtime"
    source_created=1
    if ! mount -o remount,bind,ro "$source_runtime"; then
      die 'failed to remount the source runtime read-only'
    fi
  fi

  if is_exact_mount "$target"; then
    mount_is_ext4_read_only "$target" \
      || die 'existing exact target mount is not read-only ext4'
  else
    [[ -z "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
      || die 'unmounted project runtime target is not empty'
    mount --bind "$source_runtime" "$target"
    target_created=1
    if ! mount -o remount,bind,ro "$target"; then
      die 'failed to remount the project runtime target read-only'
    fi
  fi
fi

mount_is_ext4_read_only "$source_runtime" \
  || die 'source runtime is not an exact read-only ext4 mount'
mount_is_ext4_read_only "$target" \
  || die 'project runtime target is not an exact read-only ext4 mount'
[[ "$(stat -Lc '%d:%i:%F' -- "$source_runtime")" == "$(stat -Lc '%d:%i:%F' -- "$target")" ]] \
  || die 'project runtime target is not bound to the source runtime'
[[ "$(sha256sum "$source_runtime/bin/python" | awk '{print $1}')" == \
   "$(sha256sum "$target/bin/python" | awk '{print $1}')" ]] \
  || die 'source and target Python identities differ'

if ((check_only == 1)); then
  status='verified'
else
  status='materialized'
fi
printf '{"artifact_kind":"vast_publication_runtime_mount_v1","status":"%s","source_read_only":true,"target_read_only":true}\n' "$status"

trap - EXIT
