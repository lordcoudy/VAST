$ErrorActionPreference = 'Stop'
$controls = 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\repair-source06-reconstruction-integration-01'
if (Test-Path -LiteralPath $controls) { throw 'Refuse existing controls.' }
$free = (Get-PSDrive C).Free
$plannedCopiesAndCIAllowance = 1393960908 + 9GB
if ($free - $plannedCopiesAndCIAllowance -lt 40GB) { throw 'Conservative backing-capacity budget refused.' }
$program = @'
set -euo pipefail
SHA=06c828ce798d3454f1d4b8a992aed7133882b5a1
ROOT=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA
E=$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01
PLAN=/mnt/e/STUDY/VAST/tmp/host-cache-cleanup-20261012/repair-source06-focused-source-plan-01/reconstruction-copy-plan.v1.json
export VAST_REPAIR_CHECK_ROOT="$ROOT"
[[ -z "$(docker ps --all -q)" ]]
[[ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]]
[[ "$(docker info --format '{{.ID}}')" == aa8f3d33-e1dc-4ed2-ad06-488b46b332d0 ]]
date -u +%FT%TZ
bash "$E/run_reconstruction_input_copy_v2.sh" --source-commit "$SHA" --plan "$PLAN" \
  --reviewed-plan-sha256 27b807fddffa8977a6050b7b36f3c42489da477fbcb8e7be0466b222b440e489 \
  --reviewed-helper-sha256 d6e3fc1286fabb9127cae9417de0b6f05689c6d3e1c90951dd0149cbe4bbfbf6
printf 'RECONSTRUCTION_COPY_COMPLETE\n'
bash "$E/run_integration_lane.sh" "$SHA"
date -u +%FT%TZ
printf 'NINE_INTEGRATION_COMPLETE\n'
'@
[void](New-Item -ItemType Directory -Path $controls)
$started = [DateTime]::UtcNow.ToString('o')
@{ started_utc=$started; program=$program; c_free_before=$free; initial_80_gib_provision_passed=$true;
   reconstruction_bytes=1393960908; ci_planning_allowance_bytes=9GB;
   ci_allowance_is_projection_not_peak_measurement=$true; consumer_clearance_granted=$false } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $controls 'command.v1.json') -Encoding utf8NoBOM
& wsl.exe --distribution Ubuntu --user s-a-balashov --exec bash -c $program 1> (Join-Path $controls 'original.stdout.raw') 2> (Join-Path $controls 'original.stderr.raw')
$code = $LASTEXITCODE
@{ started_utc=$started; finished_utc=[DateTime]::UtcNow.ToString('o'); original_exit_code=$code; c_free_after=(Get-PSDrive C).Free } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Encoding utf8NoBOM
Get-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Raw
exit $code
