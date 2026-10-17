$ErrorActionPreference = 'Stop'
$base = 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012'
$controls = Join-Path $base 'repair-source06-preparation-01'
if (Test-Path -LiteralPath $controls) { throw 'Refuse existing preparation controls.' }
if ((Get-PSDrive C).Free -lt 85899345920) { throw 'Physical C capacity below reviewed 80 GiB target.' }
$program = @'
set -euo pipefail
SHA=06c828ce798d3454f1d4b8a992aed7133882b5a1
ROOT=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA
BUNDLE=/mnt/e/STUDY/VAST/tmp/host-cache-cleanup-20261012/repair-source-06c828ce.v1.bundle
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
[[ "$(id -u)" == 1000 && "$(id -g)" == 1000 && "$HOME" == /home/s-a-balashov ]]
[[ "$(findmnt -rn -T /home/s-a-balashov/work -o FSTYPE)" == ext4 ]]
[[ ! -e "$ROOT" && ! -L "$ROOT" ]]
[[ "$(sha256sum "$BUNDLE" | cut -d ' ' -f 1)" == 34cfcc2fb3820f1c2f115d195daa38ea2df39d4ff989304eb330cf37f35a8b7a ]]
date -u +%FT%TZ
git clone --no-checkout --no-hardlinks "$BUNDLE" "$ROOT"
git -C "$ROOT" config core.autocrlf false
git -C "$ROOT" checkout --detach "$SHA"
[[ "$(realpath -e "$ROOT")" == "$ROOT" ]]
[[ "$(git -C "$ROOT" rev-parse HEAD)" == "$SHA" ]]
[[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]]
[[ ! -e "$ROOT/.git/objects/info/alternates" ]]
export VAST_REPAIR_CHECK_ROOT="$ROOT"
E="$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01"
[[ "$(sha256sum "$E/prepare_source_inputs.sh" | cut -d ' ' -f 1)" == 3d05bb038738b158f80af6ed7baad2ffdd8f02789095853969c5adb378596a5b ]]
source "$E/recipe_common.sh"
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
bash "$E/prepare_source_inputs.sh" "$SHA" \
  8b9111ab5855bf73b0bac2532599b1a77d36235e05a544d0a08c47cdbcaac0e7 \
  b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d \
  9b38ca696ee662bcd26f78a293f899fb6333b581670f486a5c9cfae4f9e48d45
assert_frozen_root "$SHA"
assert_committed_bytes "$ROOT"
date -u +%FT%TZ
printf 'SOURCE_PREPARATION_COMPLETE\n'
'@
[void](New-Item -ItemType Directory -Path $controls)
$started = [DateTime]::UtcNow.ToString('o')
@{ started_utc=$started; program=$program; source_commit='06c828ce798d3454f1d4b8a992aed7133882b5a1'; c_free_before=(Get-PSDrive C).Free } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $controls 'command.v1.json') -Encoding utf8NoBOM
& wsl.exe --distribution Ubuntu --user s-a-balashov --exec bash -c $program 1> (Join-Path $controls 'original.stdout.raw') 2> (Join-Path $controls 'original.stderr.raw')
$code = $LASTEXITCODE
@{ started_utc=$started; finished_utc=[DateTime]::UtcNow.ToString('o'); original_exit_code=$code; c_free_after=(Get-PSDrive C).Free } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Encoding utf8NoBOM
Get-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Raw
exit $code
