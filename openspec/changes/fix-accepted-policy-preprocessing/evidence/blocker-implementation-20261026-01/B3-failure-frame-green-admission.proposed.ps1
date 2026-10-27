$ErrorActionPreference='Stop'
$taskBase='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskPhase='failureframe-green-01'
$taskLinux=@'
FRESH_LINUX_RETURN_REQUIRED
'@|ConvertFrom-Json
if($taskLinux.exit_code -ne 0){throw 'fresh Linux qualification failed'}
$taskWindows=& {
$ErrorActionPreference='Stop'
$taskVolumes=@(Get-Volume -DriveLetter C,E|Select-Object DriveLetter,SizeRemaining,Size,AllocationUnitSize)
$taskC=@($taskVolumes|Where-Object DriveLetter -eq C); $taskE=@($taskVolumes|Where-Object DriveLetter -eq E)
if($taskC.Count -ne 1 -or $taskE.Count -ne 1 -or $taskC[0].SizeRemaining -lt 128849018880 -or $taskE[0].SizeRemaining -lt 70866960384 -or @($taskVolumes|Where-Object {$_.AllocationUnitSize -ne 4096}).Count){throw 'metadata tranche floor failed'}
$taskConfig=Get-Item -LiteralPath 'C:/Users/s-a-balashov/.wslconfig'
if($taskConfig.Length -ne 21 -or (Get-FileHash -LiteralPath $taskConfig.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne '6efea9e209212784c22240a6019c17cee3bd31011840250c76c3bb31e2c7eea1'){throw 'WSL configuration changed'}
$taskDistro=Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss\{733a6524-960b-47be-ac8d-deaf948be3c7}'
if($taskDistro.DistributionName -ne 'Ubuntu' -or $taskDistro.DefaultUid -ne 1000 -or $taskDistro.BasePath.TrimEnd('\') -ine 'C:\Users\s-a-balashov\AppData\Local\wsl\{733a6524-960b-47be-ac8d-deaf948be3c7}'){throw 'Ubuntu registry changed'}
$taskPage=@(Get-CimInstance Win32_PageFileSetting|Select-Object Name,InitialSize,MaximumSize)
if($taskPage.Count -ne 1 -or $taskPage[0].Name -ine 'E:\pagefile.sys' -or $taskPage[0].MaximumSize -ne 65536){throw 'pagefile quote changed'}
$taskUsnC=@(& fsutil usn queryjournal C: 2>&1); $taskUsnCExit=$LASTEXITCODE
$taskUsnE=@(& fsutil usn queryjournal E: 2>&1); $taskUsnEExit=$LASTEXITCODE
if($taskUsnCExit -ne 0 -or ($taskUsnC -join "`n") -notmatch 'Maximum Size\s+: 0x0000000002000000' -or ($taskUsnC -join "`n") -notmatch 'Allocation Delta\s+: 0x0000000000800000' -or $taskUsnEExit -ne 1 -or ($taskUsnE -join "`n") -notmatch 'Error 1179'){throw 'USN quote changed'}
$taskHead=& git -c gc.auto=0 -c maintenance.auto=false rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $taskHead -ne '8b76aefff3a3ba0fec8222aa4af6bf86c1b15803'){throw 'metadata source head changed'}
$taskIndex=Get-Item -LiteralPath 'E:/STUDY/VAST/.git/worktrees/VAST8/index'
if($taskIndex.Length -gt 3145728 -or (Test-Path -LiteralPath 'E:/STUDY/VAST/.git/worktrees/VAST8/index.lock')){throw 'index control quote changed'}
[ordered]@{schema_version=1;scope='metadata-retention-only';utc=[DateTime]::UtcNow.ToString('o');source_commit=$taskHead;volumes=$taskVolumes;pagefile_settings=$taskPage;default_uid=$taskDistro.DefaultUid;wslconfig_size=$taskConfig.Length;index_bytes=$taskIndex.Length;index_lock_absent=$true;usn_c=@{exit_code=$taskUsnCExit;lines=$taskUsnC};usn_e=@{exit_code=$taskUsnEExit;lines=$taskUsnE};additional_tranche_bytes=100663296;cumulative_direct_bytes=2298478592;whole_chain_admitted=$false}|ConvertTo-Json -Depth 6 -Compress
}
$taskWindows=$taskWindows|ConvertFrom-Json
if(([DateTime]::UtcNow-([DateTime]$taskWindows.utc).ToUniversalTime()).TotalSeconds -gt 120){throw 'Windows observation stale'}
$taskPins=@(
 @('tests/test_accepted_policy_fixture_failure_frame_v2.py','5d055b9cff32e62e6ae5c2ccdd497612c71d39bcc306340b48eae6b04b6a2567','source-01'),
 @('tests/test_accepted_policy_fixture_report_persistence_v2.py','79e092f6cb6a5d3d3fc1e9b59eb82a27017d7c492138e33d190917e671213734','source-02'),
 @('tests/test_accepted_policy_fixture_producer_failures_v2.py','6faa99d5584d0f0fe8683236b46fa052d9b661be4685a951b8ff320d85018006','source-03'),
 @('tests/test_accepted_policy_literal_source_capture_v2.py','1ce3ea625bf7821ae98d911d661d0df3ea53b4d83f79f1afdc670c8b9985b50c','source-04'),
 @('tests/test_accepted_policy_fixture_refusal_selector_v1.py','1e663a5751257995042a3ea8441d2ef59995ebfaea2c560b3bf1f7ddab21a6c1','source-05'),
 @('tests/test_accepted_policy_fixture_sidecar_write_facts_v1.py','a4b2eb3fde66073e93ec9990702612ec68b961a0c66441641489daa1160e3a74','source-06'),
 @('tests/test_accepted_policy_fixture_sidecar_edges_v1.py','53923d82fbb3edf399b4e80b29fd85caaa93c63522195546aa40953752dffacc','source-07'),
 @('tests/test_accepted_policy_fixture_sidecar_bounds_v1.py','c02e21d7781fd72146f38d9db23b2f207a752aa4c682d5a3495a0d015f477f11','source-08'),
 @('tests/test_accepted_policy_fixture_execution_arguments_v2.py','e50d2ddb0e5bb89de530da194b9ae979861427a7f3965a0c540034696c93e411','source-09'),
 @('tests/test_accepted_policy_fixture_refusal_arguments_v1.py','857d57aaaf949b36745efca9a8a2d8cc40e7c4135e26326833a9a4ddf47bf97a','source-10'),
 @('openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py','b31ae5e92fadf01f263daef7424759b148f08702e10f09c3bc55521a4a190360','source-11'),
 @('openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_per_cell_minimum_refusal_v1.py','5023706a4d0155f415849ad9e60f001066db4904964c3c58c80444dec6c5cb54','source-12'),
 @('tests/fixtures/accepted_policy_native_fixture_v2.py','ceb066029868e9467acd8fd01efc8c465b9cf98360189afdf6ba48add6105c6a','source-13'),
 @('tests/fixtures/accepted_policy_consumer_fixture_v2.py','5a94d95d6d66f6976c43983cac58464693eb636a7061ba23003bf8d8d818384e','source-14'),
 @('openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/preparatory_checks.py','d3c6a2a56f564cb656b29bc6d4cf7554c937298d1dbc42e92125a5d920e5fdde','source-15'))
$taskCopies=@()
$taskBytes=0
foreach($taskPin in $taskPins){
 $taskInfo=Get-Item -LiteralPath $taskPin[0]
 if($taskInfo.Length -gt 65536 -or (Get-FileHash -LiteralPath $taskInfo.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskPin[1]){throw 'reviewed failure-frame source differs'}
 $taskBytes+=$taskInfo.Length
 $taskCopies+=,[ordered]@{source=$taskPin[0];bytes=$taskInfo.Length;sha256=$taskPin[1];original=('failureframe-'+$taskPhase.Split('-')[1]+'-'+$taskPin[2]+'-source.original.py')}
}
if($taskBytes -gt 524288){throw 'aggregate source bound'}
& git -c gc.auto=0 -c maintenance.auto=false diff --quiet HEAD -- tests/fixtures/accepted_policy_fixture_compiler_v1.py tests/fixtures/accepted_policy_standalone_reader_fixture_v2.py tests/fixtures/accepted_policy_fixture_report_v1.py
if($LASTEXITCODE -ne 0){throw 'frozen owner/compiler/encoder differs'}
foreach($taskName in @(('prep-'+$taskPhase),('temporary-'+$taskPhase),('prep-'+$taskPhase+'-admission.original.json'))+@($taskCopies|ForEach-Object {$_.original})){
 if(Test-Path -LiteralPath (Join-Path $taskBase $taskName)){throw 'failure-frame namespace consumed'}
}
$taskRecord=[ordered]@{schema_version=1;phase=$taskPhase;observed_utc=[DateTime]::UtcNow.ToString('o');product_commit=$taskWindows.source_commit;source_pins=$taskCopies;direct_file_allowance_bytes=2298478592;assigned_pair_bytes=100663296;reviewed_method_count=88;reviewed_vector_count=$null;controlled_cli_child_count=6;independent_source_verdict='CLEAR /root/blocker_plan_review';independent_capacity_verdict='CLEAR /root/capacity_review';agent_execution_admission='DELEGATED_AGENT_APPROVED_FINITE_CONTROLLED_ONLY';whole_chain_admitted=$false;windows=$taskWindows;linux_tool_return=$taskLinux}
$taskRaw=[Text.Encoding]::UTF8.GetBytes(($taskRecord|ConvertTo-Json -Depth 10 -Compress)+"`n")
if($taskRaw.Length -gt 16384){throw 'admission record bound'}
$taskStream=[IO.File]::Open((Join-Path $taskBase ('prep-'+$taskPhase+'-admission.original.json')),'CreateNew','Write','Read')
try{$taskStream.Write($taskRaw,0,$taskRaw.Length);$taskStream.Flush($true)}finally{$taskStream.Dispose()}
foreach($taskCopy in $taskCopies){
 $taskRaw=[IO.File]::ReadAllBytes((Join-Path (Get-Location) $taskCopy.source))
 $taskStream=[IO.File]::Open((Join-Path $taskBase $taskCopy.original),'CreateNew','Write','Read')
 try{$taskStream.Write($taskRaw,0,$taskRaw.Length);$taskStream.Flush($true)}finally{$taskStream.Dispose()}
}
Write-Output ('Finite admission persisted for '+$taskPhase)
& wsl.exe --distribution Ubuntu --user s-a-balashov --cd /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST --exec /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/.venv/bin/python -B /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/preparatory_checks.py $taskPhase
exit $LASTEXITCODE
