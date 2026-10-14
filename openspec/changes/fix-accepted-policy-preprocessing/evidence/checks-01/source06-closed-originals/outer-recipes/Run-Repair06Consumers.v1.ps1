$ErrorActionPreference = 'Stop'
$controls = 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\consumer10-11-execution-01'
if (Test-Path -LiteralPath $controls) { throw 'Exclusive execution controls occupied.' }
$admission = Get-Content -LiteralPath 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\consumer10-11-admission-01\result.v1.json' -Raw | ConvertFrom-Json
if ($admission.original_exit_code -ne 0 -or $admission.observation_exit_code -ne 0 -or -not $admission.preflight_passed -or $admission.preflight_execution_authorized) { throw 'Read-only admission refused.' }
$free = (Get-PSDrive C).Free
if ($free - 10GB -lt 40GB) { throw 'Complete-pair backing budget no longer available.' }
[void](New-Item -ItemType Directory -Path $controls)
$python = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
$wrapper = '/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-06c828ce798d3454f1d4b8a992aed7133882b5a1/openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/run_complete_consumers_v4.py'
$started = [DateTime]::UtcNow.ToString('o')
@{ started_utc=$started; source_commit='06c828ce798d3454f1d4b8a992aed7133882b5a1'; wrapper=$wrapper;
   reviewed_wrapper_sha256='f4f146e29f3f040909e2889af0d57db284e1d6907c5f5df9c6eb69bb1b079b76';
   physical_c_free_before=$free; entire_pair_planning_allowance_bytes=10GB;
   allowance_is_not_measured_peak_or_quota=$true; orchestration_clearance_confirmed=$true;
   campaign_authority=$false; hardware_inference_observed=$false; no_automatic_retry=$true } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $controls 'command.v1.json') -Encoding utf8NoBOM
& wsl.exe --distribution Ubuntu --user s-a-balashov --exec $python -B $wrapper --expected-source-commit 06c828ce798d3454f1d4b8a992aed7133882b5a1 --reviewed-wrapper-sha256 f4f146e29f3f040909e2889af0d57db284e1d6907c5f5df9c6eb69bb1b079b76 --orchestration-clearance-confirmed 1> (Join-Path $controls 'original.stdout.raw') 2> (Join-Path $controls 'original.stderr.raw')
$code = $LASTEXITCODE
@{ started_utc=$started; finished_utc=[DateTime]::UtcNow.ToString('o'); original_outer_exit_code=$code;
   physical_c_free_after=(Get-PSDrive C).Free; complete_consumers_asserted_by_this_capture=$false } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Encoding utf8NoBOM
Get-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Raw
exit $code
