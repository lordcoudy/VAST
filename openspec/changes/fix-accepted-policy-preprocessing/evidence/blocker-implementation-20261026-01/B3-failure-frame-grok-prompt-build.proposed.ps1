$ErrorActionPreference='Stop'
$taskBase='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskHead=& git -c gc.auto=0 -c maintenance.auto=false rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $taskHead -ne 'b98b4aced156784c883887910f9e481e867b8d44'){throw 'review code head changed'}
$taskDiff=@(& git -c gc.auto=0 -c maintenance.auto=false diff --no-ext-diff --unified=4 8b76aefff3a3ba0fec8222aa4af6bf86c1b15803 b98b4aced156784c883887910f9e481e867b8d44 -- openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_per_cell_minimum_refusal_v1.py tests/fixtures/accepted_policy_consumer_fixture_v2.py tests/fixtures/accepted_policy_native_fixture_v2.py)
if($LASTEXITCODE -ne 0){throw 'review diff failed'}
$taskTestPath='tests/test_accepted_policy_fixture_failure_frame_v2.py'
if((Get-Item -LiteralPath $taskTestPath).Length -gt 65536){throw 'test source cap'}
$taskTest=[IO.File]::ReadAllText((Join-Path (Get-Location) $taskTestPath))
$taskMethods=@('test_both_main_paths_keep_actual_source_context_after_body_unwinds','test_report_state_saves_exact_return_before_a_post_write_clock_error','test_actual_main_failure_report_keeps_assessment_source_and_writer_refusal','test_opaque_error_projection_never_observes_custom_metadata','test_owned_error_links_preserve_order_and_identity_without_fact_duplication','test_consumer_retains_actual_assessment_before_constant_refusal','test_consumer_retains_actual_reader_return_before_later_refusal','test_complete_admitted_geometry_keeps_global_caps_and_worst_paths','test_cli_tails_and_positive_main_namespace_keep_owned_class_identity','test_cause_identity_and_error_graph_caps_refuse_incomplete_not_recurse','test_single_stderr_attempt_never_retries_partial_or_failed_emission','test_actual_tiny_cli_children_have_one_frame_or_originated_help_exit')
$taskCore="EXACT COMMIT production diff (read full source with allowed read tools as needed):`n"+($taskDiff -join "`n")+"`nSelected exact-test method bodies (remaining test module available to read tools):`n"
foreach($taskMethod in $taskMethods){
 $taskMatch=[regex]::Match($taskTest,'(?ms)^    def '+[regex]::Escape($taskMethod)+'\(.*?(?=^    def |^if __name__|\z)')
 if(-not $taskMatch.Success){throw 'review method missing'}
 $taskCore+=$taskMatch.Value+"`n"
}
$taskCoreBytes=[Text.Encoding]::UTF8.GetByteCount($taskCore)
if($taskCoreBytes -gt 65536){throw 'direct source/test core cap'}
$taskContext=''
foreach($taskName in @('B3-producer-failure-frame-shape.proposed.md','B3-producer-failure-frame-contract.proposed.md','B3-failure-frame-review-corrections.md','B3-failure-frame-test-recipe.proposed.md','B3-failure-frame-checkpoint.md')){
 $taskFile=Get-Item -LiteralPath (Join-Path $taskBase $taskName)
 if($taskFile.Length -gt 16384){throw 'review context member cap'}
 $taskContext+="`nDOCUMENT "+$taskName+"`n"+[IO.File]::ReadAllText($taskFile.FullName)
}
$taskHeader=@'
Independently review EXACT local commit b98b4aced156784c883887910f9e481e867b8d44, parent8b76aefff3a3ba0fec8222aa4af6bf86c1b15803, same branch codex/fix-accepted-policy-preprocessing and Draft PR9. This is the configured Grok review for the fixed B3 producer failure-frame source slice only. Use the configured model; do not delegate, use network, execute code/tests, mutate files or run workloads. Allowed read tools may inspect exact repository source/evidence. Be adversarial; peer CLEAR is evidence, not your verdict. Need CLEAR or concrete actionable defects with file/line/evidence. Do not weaken bounds or claim runtime/whole1.5 acceptance.
Review the approved implementation contract, opaque-error callback avoidance, exact canonical/__main__ identities, checked scalar/cause/path geometry, source/report/assessment/reader retention before subsequent errors, legacy cleanup-code transport, single global facts blocks and error identity links, parser-origin exits versus body SystemExit0, actual tail wiring and one stderr attempt with nonzero partial/failed delivery. Verify default in-process call shapes and original error identity remain. Compiler/D16/program/report encoder protected bytes are unchanged. Full heterogeneous compiler facts and real environment/heap/general stderr/drain/deadline/runtime qualification remain OPEN.
Retained sole RED3methods/5intended assertions .043s; sole GREEN88methods1.066s/noerrors/skips. Exactly6tinyCLIchildren with forbidden production mains (statuses1,1,1,1,0,2),7Ccase roots19files293423B. Max syntheticframe273513B SHA2ebef1dc83d55611c6dabc9b9fe0b86d6f7fbad3d904b494e292982f9b2cfbe4 preserves22worst paths/6captures/64errors/64codes+identities/11prior+1failedsidecar. Three original ZIPs61members CRC/hash/loose-original verified. Read archived/source facts rather than rerunning. Working independent source/outcome and capacity reviews CLEAR; this does not predetermine yours.
Direct core is intentionally partial to stay<=64KiB. Read the remaining tests/source at this exact clean head with bounded tools if needed. Context/prompt<=128KiB. Four-turn/600s maximum, no continuation. Stop after a concrete final verdict. No task, physical, real Docker, consumer, source-pin renewal, archive/merge approval follows.
'@
$taskPrompt=$taskHeader+"`n"+$taskCore+"`n"+$taskContext
$taskRaw=[Text.Encoding]::UTF8.GetBytes($taskPrompt)
if($taskRaw.Length -gt 131072){throw 'review prompt cap'}
$taskPath=Join-Path $taskBase 'B3-failure-frame-source-grok-prompt.original.txt'
$taskStream=[IO.File]::Open($taskPath,'CreateNew','Write','Read')
try{$taskStream.Write($taskRaw,0,$taskRaw.Length);$taskStream.Flush($true)}finally{$taskStream.Dispose()}
[ordered]@{source_commit=$taskHead;prompt_bytes=$taskRaw.Length;direct_core_bytes=$taskCoreBytes;prompt_sha256=(Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()}|ConvertTo-Json -Compress
