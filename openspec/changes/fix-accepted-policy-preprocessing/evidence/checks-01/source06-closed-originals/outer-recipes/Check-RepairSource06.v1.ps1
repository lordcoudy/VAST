$ErrorActionPreference = 'Stop'
$controls = 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\repair-source06-focused-source-plan-01'
if (Test-Path -LiteralPath $controls) { throw 'Refuse existing controls.' }
$program = @'
set -euo pipefail
SHA=06c828ce798d3454f1d4b8a992aed7133882b5a1
ROOT=/home/s-a-balashov/work/vast-accepted-policy-repair-20261011a-source-$SHA
E=$ROOT/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01
CONTROL=/mnt/e/STUDY/VAST/tmp/host-cache-cleanup-20261012/repair-source06-focused-source-plan-01
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
export VAST_REPAIR_CHECK_ROOT="$ROOT"
[[ "$(sha256sum "$E/run_focused_suite_v2.sh" | cut -d ' ' -f1)" == c6fa4bbc088db207f15dfbbbf985ea2cf7eeb97fbdcfb9bafdb5855fdf859df4 ]]
date -u +%FT%TZ
bash "$E/run_focused_suite_v2.sh" "$SHA"
printf 'FOCUSED_COMPLETE\n'
bash "$E/run_final_source_inputs_v2.sh" "$SHA"
printf 'SOURCE_COMPARISON_COMPLETE\n'
[[ ! -e "$CONTROL/reconstruction-copy-plan.v1.json" ]]
"$PY" -B "$E/copy_reconstruction_inputs_v2.py" --source-commit "$SHA" plan \
  > "$CONTROL/reconstruction-copy-plan.v1.json"
sha256sum "$CONTROL/reconstruction-copy-plan.v1.json" "$E/copy_reconstruction_inputs_v2.py"
date -u +%FT%TZ
printf 'PLAN_GENERATION_COMPLETE_NO_COPY\n'
'@
[void](New-Item -ItemType Directory -Path $controls)
$started = [DateTime]::UtcNow.ToString('o')
@{ started_utc=$started; program=$program; c_free_before=(Get-PSDrive C).Free } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $controls 'command.v1.json') -Encoding utf8NoBOM
& wsl.exe --distribution Ubuntu --user s-a-balashov --exec bash -c $program 1> (Join-Path $controls 'original.stdout.raw') 2> (Join-Path $controls 'original.stderr.raw')
$code = $LASTEXITCODE
@{ started_utc=$started; finished_utc=[DateTime]::UtcNow.ToString('o'); original_exit_code=$code; c_free_after=(Get-PSDrive C).Free } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Encoding utf8NoBOM
Get-Content -LiteralPath (Join-Path $controls 'result.v1.json') -Raw
exit $code
