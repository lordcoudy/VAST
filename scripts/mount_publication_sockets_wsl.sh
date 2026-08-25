#!/usr/bin/env bash
set -euo pipefail

usage() {
  printf '%s\n' \
    'Usage: mount_publication_sockets_wsl.sh [options]' \
    '' \
    'Create or verify the writable ext4 Unix-socket namespace used by the WSL benchmark.' \
    '' \
    'Options:' \
    '  --source-socket-dir PATH       Canonical ext4 socket directory.' \
    '  --project-root PATH            Benchmark project root.' \
    '  --project-socket-mount PATH    Project-relative mount point.' \
    '  --check-only                   Verify the existing mount without changing it.' \
    '  -h, --help                     Show this help.'
}

die() {
  printf '[publication-socket-mount][error] %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is missing: $1"
}

source_socket_dir="${VAST_PUBLICATION_SOCKET_SOURCE:-${HOME}/.local/state/vast/publication/sockets/model-parity-v3-20260824}"
project_root=""
project_socket_mount=".publication-sockets/model-parity-v3"
check_only=0

while (($#)); do
  case "$1" in
    --source-socket-dir)
      (($# >= 2)) || die '--source-socket-dir requires a value'
      source_socket_dir="$2"
      shift 2
      ;;
    --project-root)
      (($# >= 2)) || die '--project-root requires a value'
      project_root="$2"
      shift 2
      ;;
    --project-socket-mount)
      (($# >= 2)) || die '--project-socket-mount requires a value'
      project_socket_mount="$2"
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
[[ -n "$project_socket_mount" && "$project_socket_mount" != /* ]] \
  || die 'project socket mount must be a non-empty relative path'

IFS='/' read -r -a mount_parts <<<"$project_socket_mount"
for part in "${mount_parts[@]}"; do
  [[ -n "$part" && "$part" != "." && "$part" != ".." ]] \
    || die 'project socket mount is not canonical'
done

for command_name in findmnt readlink stat; do
  require_command "$command_name"
done
if ((check_only == 0)); then
  for command_name in find mount umount; do
    require_command "$command_name"
  done
  [[ "${EUID}" -eq 0 ]] || die 'socket mount materialization must run as root'
fi

[[ -d "$source_socket_dir" && ! -L "$source_socket_dir" ]] \
  || die 'source socket directory is missing or symbolic'
[[ -d "$project_root" && ! -L "$project_root" ]] \
  || die 'project root is missing or symbolic'
source_socket_dir="$(readlink -f -- "$source_socket_dir")"
project_root="$(readlink -f -- "$project_root")"
[[ -n "$source_socket_dir" && -n "$project_root" ]] \
  || die 'failed to canonicalize paths'
case "$source_socket_dir/" in
  "$project_root/"*) die 'source socket directory must be outside project root' ;;
esac
[[ "$(findmnt -rn -T "$source_socket_dir" -o FSTYPE)" == "ext4" ]] \
  || die 'source socket directory must reside on ext4'
[[ "$(stat -Lc '%a' -- "$source_socket_dir")" == "700" ]] \
  || die 'source socket directory must have mode 0700'

target="$project_root/$project_socket_mount"
cursor="$project_root"
for part in "${mount_parts[@]}"; do
  cursor="$cursor/$part"
  [[ ! -L "$cursor" ]] || die 'project socket mount ancestry contains a symbolic link'
  if [[ -e "$cursor" && ! -d "$cursor" ]]; then
    die 'project socket mount ancestry contains a non-directory'
  fi
  if ((check_only == 0)) && [[ ! -d "$cursor" ]]; then
    mkdir -- "$cursor"
  fi
done
[[ -d "$target" ]] || die 'project socket mount directory is missing'

mount_target() {
  findmnt -rn -T "$1" -o TARGET
}

is_exact_mount() {
  [[ "$(mount_target "$1")" == "$1" ]]
}

mount_is_ext4_writable() {
  local path="$1"
  local fstype options
  is_exact_mount "$path" || return 1
  fstype="$(findmnt -rn -T "$path" -o FSTYPE)"
  options="$(findmnt -rn -T "$path" -o OPTIONS)"
  [[ "$fstype" == "ext4" ]] || return 1
  case ",$options," in
    *,rw,*) return 0 ;;
    *) return 1 ;;
  esac
}

target_created=0
cleanup_partial_mount() {
  local status=$?
  if ((status != 0 && target_created == 1)); then
    umount -- "$target" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup_partial_mount EXIT

if ((check_only == 0)); then
  if is_exact_mount "$target"; then
    mount_is_ext4_writable "$target" \
      || die 'existing exact target mount is not writable ext4'
  else
    [[ -z "$(find "$target" -mindepth 1 -maxdepth 1 -print -quit)" ]] \
      || die 'unmounted project socket target is not empty'
    mount --bind "$source_socket_dir" "$target"
    target_created=1
  fi
fi

mount_is_ext4_writable "$target" \
  || die 'project socket target is not an exact writable ext4 mount'
[[ "$(stat -Lc '%d:%i:%F' -- "$source_socket_dir")" == \
   "$(stat -Lc '%d:%i:%F' -- "$target")" ]] \
  || die 'project socket target is not bound to the source socket directory'
[[ "$(stat -Lc '%a' -- "$target")" == "700" ]] \
  || die 'project socket target must have mode 0700'

if ((check_only == 1)); then
  status='verified'
else
  status='materialized'
fi
printf '{"artifact_kind":"vast_publication_socket_mount_v1","status":"%s","target_writable":true,"source_target_identity_equal":true}\n' "$status"

trap - EXIT
