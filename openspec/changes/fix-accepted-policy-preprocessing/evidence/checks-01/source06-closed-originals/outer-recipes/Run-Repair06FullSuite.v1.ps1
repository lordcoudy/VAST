$ErrorActionPreference = 'Stop'
$controls = 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\repair-source06-full-ext4-01'
if (Test-Path -LiteralPath $controls) { throw 'Refuse existing controls.' }
$free = (Get-PSDrive C).Free
if ($free - 9GB -lt 40GB) { throw 'Reviewed CI/backing-capacity planning budget refused.' }
$program = @'
set -euo pipefail
SHA=06c828ce798d3454f1d4b8a992aed7133882b5a1
ROOT=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA
E=$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01
export VAST_REPAIR_CHECK_ROOT="$ROOT"
[[ -z "$(docker ps --all -q)" ]]
[[ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]]
[[ "$(docker info --format '{{.ID}}')" == aa8f3d33-e1dc-4ed2-ad06-488b46b332d0 ]]
[[ "$(sha256sum "$E/run_ext4_suite.sh" | cut -d ' ' -f1)" == 045cdded701dfb59100ce600344079f615a7be5991778befa4123eb209cb106d ]]
date -u +%FT%TZ
bash "$E/run_ext4_suite.sh" "$SHA" \
  8b9111ab5855bf73b0bac2532599b1a77d36235e05a544d0a08c47cdbcaac0e7 \
  b0a38ba5e6a26194eb69f147a369f4851b408e541fa7eb46c703e88fdf55b28d \
  9b38ca696ee662bcd26f78a293f899fb6333b581670f486a5c9cfae4f9e48d45
date -u +%FT%TZ
printf 'FULL_EXT4_SUITE_COMPLETE\n'
'@
[void](New-Item -ItemType Directory -Path $controls)
$started = [DateTime]::UtcNow.ToString('o')
@{ started_utc=$started; program=$program; c_free_before=$free; ci_planning_allowance_bytes=9GB;
   planning_allowance_is_not_peak_measurement_or_quota=$true; no_concurrent_consumer_or_live_lane=$true } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $controls 'command.v1.json') -Encoding utf8NoBOM
& wsl.exe --distribution Ubuntu --user s-a-balashov --exec bash -c $program 1> (Join-Path $controls 'original.stdout.raw') 2> (Join-Path $controls 'original.stderr.raw')
$code = $LASTEXITCODE
@{ started_utc=$started; finished_utc=[DateTime]::UtcNow.ToString('o'); original_exit_code=$code; c_free_after=(Get-PSDrive C).Free } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Encoding utf8NoBOM
Get-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Raw
exit $code
