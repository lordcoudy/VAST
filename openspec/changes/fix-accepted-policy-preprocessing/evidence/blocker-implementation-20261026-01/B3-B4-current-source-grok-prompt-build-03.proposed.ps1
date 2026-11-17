$ErrorActionPreference='Stop'
$taskLF=[string][char]10
$taskBase='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskRoot='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
if((Get-Location).Path -cne $taskRoot){throw 'fixed C worktree required'}
$taskPins=@{
 'tests/test_accepted_policy_fixture_failure_frame_v2.py'=@(42050,'5d055b9cff32e62e6ae5c2ccdd497612c71d39bcc306340b48eae6b04b6a2567')
 'tests/test_runtime_build_context_v3.py'=@(25544,'8779c4c1182f983bff3a3ef52ae1af53c37368c618ff5192b4aff0712f1a2d73')
 ($taskBase+'/B3-producer-failure-frame-shape.proposed.md')=@(10344,'7bc9bdb627cbd40f88a2f81b4943df52b535177ef0ee4683716a51bab2e2f992')
 ($taskBase+'/B3-producer-failure-frame-contract.proposed.md')=@(8930,'d64698794112394c3734e848e65bc03ee5f875e704a9ffdc77a58976bcda4aee')
 ($taskBase+'/B3-failure-frame-review-corrections.md')=@(3013,'0a966ec3c53c43f5764b72ab3e8dba2adcdc15cd5113fa9474d220bbb331db37')
 ($taskBase+'/B3-failure-frame-test-recipe.proposed.md')=@(6726,'6ac2ca4309accc0a39f2a4247fb5ef43d98df617d866546ab5eb7a3bf865dba4')
 ($taskBase+'/B3-failure-frame-checkpoint.md')=@(4823,'5f08131dcec78dfa011d868fd377078a83b69a25f57df7d2adfd87dc8d08e2bd')
 ($taskBase+'/B4-build-metadata-test-recipe.proposed.md')=@(5641,'746d4bbd8f0766d359339b383035bcc7835b7a98416b77b578d09d7042b0b44a')
 ($taskBase+'/B4-build-metadata-checkpoint.md')=@(7232,'46d3ac509cd4581087d4fe56047a7ced5d362a5ccc11fedc1e740c496f77ff19')
}
function Read-Pr9ExactPublicPromptInput {
 param([string]$Path)
 $taskKey=$Path.Replace('\','/')
 if(-not $taskPins.ContainsKey($taskKey)){throw 'fixed public input required'}
 $taskPin=$taskPins[$taskKey]
 if($taskPin[0] -lt 0 -or $taskPin[0] -gt 65536){throw 'public input ceiling'}
 $taskInput=$null;$taskPrimary=$null;$taskClose=$null;$taskText=$null
 try{
  $taskInput=[IO.File]::Open((Join-Path $taskRoot $taskKey),'Open','Read','Read')
  if($taskInput.Length -ne $taskPin[0]){throw 'public input extent differs'}
  $taskRaw=[byte[]]::new($taskPin[0]);$taskBuffer=[byte[]]::new(4096);$taskOffset=0
  while($true){
   $taskN=$taskInput.Read($taskBuffer,0,[int][Math]::Min(4096,$taskPin[0]-$taskOffset+1))
   if($taskN -eq 0){break}
   if($taskN -gt $taskPin[0]-$taskOffset){throw 'public input growth'}
   [Buffer]::BlockCopy($taskBuffer,0,$taskRaw,$taskOffset,$taskN);$taskOffset+=$taskN
  }
  if($taskOffset -ne $taskPin[0]){throw 'public input shrink'}
  if([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskRaw)).ToLowerInvariant() -cne $taskPin[1]){throw 'public input not exact605 bytes'}
  $taskText=[Text.UTF8Encoding]::new($false,$true).GetString($taskRaw)
 }catch{$taskPrimary=$_.Exception}
 finally{if($null -ne $taskInput){try{$taskInput.Dispose()}catch{$taskClose=$_.Exception}}}
 if($null -eq $taskPrimary -and $null -ne $taskClose){$taskPrimary=$taskClose;$taskClose=$null}
 if($null -ne $taskPrimary){
  $taskFailure=[InvalidOperationException]::new('exact public prompt input refused',$taskPrimary)
  if($null -ne $taskClose -and -not [Object]::ReferenceEquals($taskPrimary,$taskClose)){$taskFailure.Data['private_close']=$taskClose}
  throw $taskFailure
 }
 return $taskText
}

$taskHead=& git -c gc.auto=0 -c maintenance.auto=false rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $taskHead -cne '605eb02733fe256ad5ef14f358eaa81ee1a0ae44'){throw 'exact product head differs'}
$taskFiles=@(
 'openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py',
 'openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_per_cell_minimum_refusal_v1.py',
 'tests/fixtures/accepted_policy_consumer_fixture_v2.py',
 'tests/fixtures/accepted_policy_native_fixture_v2.py',
 'scripts/materialize_runtime_build_context_v3.py'
)
$taskTests=@('tests/test_accepted_policy_fixture_failure_frame_v2.py','tests/test_runtime_build_context_v3.py')
& git -c gc.auto=0 -c maintenance.auto=false diff --no-ext-diff --no-textconv --quiet HEAD -- @($taskFiles+$taskTests)
if($LASTEXITCODE -ne 0){throw 'reviewed source differs from exact head'}
$taskDiff=@(& git -c gc.auto=0 -c maintenance.auto=false diff --no-ext-diff --no-textconv --unified=1 8b76aefff3a3ba0fec8222aa4af6bf86c1b15803 $taskHead -- $taskFiles)
if($LASTEXITCODE -ne 0){throw 'public diff read failed'}
$taskCore='Complete production diff for the five named B3/B4 changed files. Packet-only source review; no filesystem tools.'+$taskLF+($taskDiff -join $taskLF)+$taskLF+'Selected exact-head test method bodies (other tests are not supplied):'+$taskLF
$taskSelections=@(
 @($taskTests[0],@('test_actual_main_failure_report_keeps_assessment_source_and_writer_refusal','test_opaque_error_projection_never_observes_custom_metadata','test_owned_error_links_preserve_order_and_identity_without_fact_duplication')),
 @($taskTests[1],@('test_manifest_size_is_refused_before_reading_or_decoding','test_union_overflow_refuses_before_member_stat_or_copy','test_output_scans_never_collect_or_recurse_into_unexpected_tree','test_success_preserves_schema_bytes_hash_and_timestamp'))
)
foreach($taskSelection in $taskSelections){
 $taskText=Read-Pr9ExactPublicPromptInput -Path $taskSelection[0]
 $taskCore+=$taskLF+'TEST MODULE '+$taskSelection[0]+$taskLF
 foreach($taskMethod in $taskSelection[1]){
  $taskMatch=[regex]::Match($taskText,'(?ms)^    def '+[regex]::Escape($taskMethod)+'\(.*?(?=^    def |^if __name__|\z)')
  if(-not $taskMatch.Success){throw 'selected method missing'}
  $taskCore+=$taskMatch.Value+$taskLF
 }
}
$taskCoreBytes=[Text.Encoding]::UTF8.GetByteCount($taskCore)
if($taskCoreBytes -gt 65536){throw 'direct source/test core cap'}
$taskContext=''
foreach($taskName in @(
 'B3-producer-failure-frame-shape.proposed.md','B3-producer-failure-frame-contract.proposed.md',
 'B3-failure-frame-review-corrections.md','B3-failure-frame-test-recipe.proposed.md','B3-failure-frame-checkpoint.md',
 'B4-build-metadata-test-recipe.proposed.md','B4-build-metadata-checkpoint.md'
)){
 $taskContext+=$taskLF+'DOCUMENT '+$taskName+$taskLF+(Read-Pr9ExactPublicPromptInput -Path ($taskBase+'/'+$taskName))
}
$taskHeader=@'
Independently review EXACT product commit605eb02733fe256ad5ef14f358eaa81ee1a0ae44 in codex/fix-accepted-policy-preprocessing/DraftPR9. The previous approved source baseline is8b76aefff3a3ba0fec8222aa4af6bf86c1b15803; the two subsequent source slices are B3 b98b4aced156784c883887910f9e481e867b8d44 and B4 605eb027. This is ONE configured-provider/model packet review of their combined current source. Use configured model/settings. No model-side tools, delegation, web/network searches, code/tests/workloads or mutation. Do not expose session or credential data. Return CLEAR or concrete actionable defects with file/line/reason. Peer reviews are evidence, not your verdict. Four turns/600s maximum, no continuation.

The packet includes the COMPLETE production diff for all five changed B3/B4 files, seven selected exact-head test methods and the approved contracts/checkpoints/actual test evidence. It does not include the full repository/test modules; qualify your verdict to this packet. No claim of full repository inspection follows. If the provided material cannot support a conclusion, identify the precise missing information. Do not request execution or weaken acceptance.

B3: verify opaque-error callbacks are avoided, canonical/__main__ owned identities, checked scalar/cause/path geometry, source/report/assessment/reader state retained before later errors, legacy cleanup transport, one global facts block, identity links, parser-origin exits versus body SystemExit0, tail wiring, one stderr attempt and nonzero on partial/failed delivery. Actual sole RED3methods/5intended assertions; GREEN88methods; six tiny CLI children;61originalZIPmember joins. Broader compiler/runtime qualification remains OPEN.

B4: verify manifest-input iterator stops at first excess, held bounded nonblocking/nofollow descriptor validation before reading/decoding,8KiB128entries per manifest, union128, ASCII256/depth8 paths,32MiB member/40MiB total limits before first destination write, metadata/result geometry preflight, lazy refusal of unexpected output entries before collection/descent, preserved success bytes/hash/schema/order/modes/timestamps and preserved read/close causes. Actual sole RED8methods/14intended assertion failures; GREEN27methods;18originalZIPmember joins. _copy_held_source is byte-unchanged. Materializer itself is included in all four build contexts, so literal context identities must later renew rather than silently replace pins.

Exact605eb027 CI40547237625/run346 SUCCESS (cpu-checks and Original host diagnostics); no annotations. Existing independent source/evidence reviews CLEAR for both slices. Compiler/D16/encoder/S3 protected bytes, planning/tasks and CI unchanged. No configured Grok approval for these slices exists yet. Whole task1.5, real Docker, compiler/reader admission, lifecycle, runtimes/parity/tensor/pins, genuine3840/3968/126016/refusals, conformance/archive/merge remain OPEN. This packet review alone closes none of those gates.
'@
$taskRaw=[Text.Encoding]::UTF8.GetBytes($taskHeader+$taskLF+$taskCore+$taskLF+$taskContext)
if($taskRaw.Length -gt 131072){throw 'review prompt cap'}
$taskPath=Join-Path $taskBase 'B3-B4-current-source-grok-prompt-03.original.txt'
$taskStream=$null;$taskPrimary=$null;$taskClose=$null
try{
 $taskStream=[IO.File]::Open($taskPath,'CreateNew','Write','Read')
 $taskStream.Write($taskRaw,0,$taskRaw.Length);$taskStream.Flush($true)
}catch{$taskPrimary=$_.Exception}
finally{if($null -ne $taskStream){try{$taskStream.Dispose()}catch{$taskClose=$_.Exception}}}
if($null -eq $taskPrimary -and $null -ne $taskClose){$taskPrimary=$taskClose;$taskClose=$null}
if($null -ne $taskPrimary){
 $taskFailure=[InvalidOperationException]::new('public prompt persistence refused',$taskPrimary)
 $taskFailure.Data['private_close']=$taskClose;throw $taskFailure
}
[ordered]@{source_commit=$taskHead;production_files=5;selected_methods=7;prompt_bytes=$taskRaw.Length;direct_core_bytes=$taskCoreBytes;prompt_sha256=(Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash.ToLowerInvariant()}|ConvertTo-Json -Compress
