$ErrorActionPreference = 'Stop'
$controls = 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\consumer10-11-admission-01'
if (Test-Path -LiteralPath $controls) { throw 'Fresh admission controls occupied.' }
$free = (Get-PSDrive C).Free
if ($free - 10GB -lt 40GB) { throw 'Entire-pair physical backing budget refused.' }
$full = Get-Content -LiteralPath 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\repair-source06-full-ext4-01\result.v1.json' -Raw | ConvertFrom-Json
$sampler = Get-Content -LiteralPath 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\repair-source06-full-ext4-01\capacity-sampler-result.v1.json' -Raw | ConvertFrom-Json
if ($full.original_exit_code -ne 0 -or -not $sampler.original_outer_result_observed -or -not $sampler.capacity_floor_40_gib_observed) { throw 'Full/sampler closure guard refused.' }
[void](New-Item -ItemType Directory -Path $controls)
$observation = @'
set -euo pipefail
SHA=06c828ce798d3454f1d4b8a992aed7133882b5a1
ROOT=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA
CI=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-ci-$SHA
BASE=$ROOT/artifacts/accepted_policy_repair_20261011a
[[ "$(id -u)" == 1000 && "$(id -g)" == 1000 && "$HOME" == /home/s-a-balashov ]]
[[ -z "$(docker ps --all -q)" ]]
[[ -z "$(nvidia-smi --query-compute-apps=pid --format=csv,noheader)" ]]
[[ "$(docker info --format '{{.ID}}')" == aa8f3d33-e1dc-4ed2-ad06-488b46b332d0 ]]
for R in "$ROOT" "$CI"; do
 [[ "$(realpath -e "$R")" == "$R" ]]
 [[ "$(git -C "$R" rev-parse HEAD)" == "$SHA" ]]
 [[ -z "$(git -C "$R" status --porcelain --untracked-files=no)" ]]
done
for name in consumer-complete-10-controls consumer-fixture-10-minimum30 consumer-fixture-11-larger31; do
 [[ ! -e "$BASE/$name" && ! -L "$BASE/$name" ]]
done
for prefix in /var/tmp/.apf10 /var/tmp/.apf11 /tmp/.apf10 /tmp/.apf11; do
 compgen -G "$prefix*" >/dev/null && exit 47
done
df -B1 "$ROOT" /var/tmp
findmnt -rn -T "$ROOT" -o TARGET,FSTYPE,SOURCE
findmnt -rn -T /var/tmp -o TARGET,FSTYPE,SOURCE
ps -eo pid,user,args | awk '/vast-accepted-policy-repair-20261011a-(source|ci)-/ && $0 !~ /awk|bash -c|ps -eo/ {print; found=1} END {exit found ? 48 : 0}'
printf 'FRESH_IDLE_NAMESPACE_OBSERVATIONS_PASSED\n'
'@
$started = [DateTime]::UtcNow.ToString('o')
@{ started_utc=$started; physical_c_free_before=$free; pair_planning_allowance_bytes=10GB;
   allowance_is_not_peak_measurement_or_quota=$true; observation_program=$observation } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $controls 'command.v1.json') -Encoding utf8NoBOM
& wsl.exe --distribution Ubuntu --user s-a-balashov --exec bash -c $observation 1> (Join-Path $controls 'observation.stdout.raw') 2> (Join-Path $controls 'observation.stderr.raw')
$observationCode = $LASTEXITCODE
if ($observationCode -ne 0) {
    @{ original_exit_code=$observationCode; finished_utc=[DateTime]::UtcNow.ToString('o'); execution_clearance_granted=$false } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Encoding utf8NoBOM
    exit $observationCode
}
$python = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
$wrapper = '/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-06c828ce798d3454f1d4b8a992aed7133882b5a1/openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/run_complete_consumers_v4.py'
& wsl.exe --distribution Ubuntu --user s-a-balashov --exec $python -B $wrapper --expected-source-commit 06c828ce798d3454f1d4b8a992aed7133882b5a1 --reviewed-wrapper-sha256 f4f146e29f3f040909e2889af0d57db284e1d6907c5f5df9c6eb69bb1b079b76 --check-only 1> (Join-Path $controls 'preflight.stdout.raw') 2> (Join-Path $controls 'preflight.stderr.raw')
$code = $LASTEXITCODE
$report = Get-Content -LiteralPath (Join-Path $controls 'preflight.stdout.raw') -Raw | ConvertFrom-Json
@{ started_utc=$started; finished_utc=[DateTime]::UtcNow.ToString('o'); original_exit_code=$code;
   observation_exit_code=$observationCode; preflight_passed=$report.preflight_passed;
   preflight_execution_authorized=$report.execution_authorized; physical_c_free_after=(Get-PSDrive C).Free;
   root_execution_clearance_granted=$false } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Encoding utf8NoBOM
Get-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Raw
if ($code -ne 0 -or -not $report.preflight_passed -or $report.execution_authorized) { exit 1 }
