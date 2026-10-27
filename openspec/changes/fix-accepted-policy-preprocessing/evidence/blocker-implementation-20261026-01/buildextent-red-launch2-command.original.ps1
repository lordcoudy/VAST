$ErrorActionPreference='Stop'
$taskBase='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskPhase='buildextent-red-01'
$taskLinux=@'
{"chunk_id":"89baf8","wall_time_seconds":1.1824506,"exit_code":0,"original_token_count":142,"output":"{\"allocation_units\":{\"c\":4096,\"e\":4096,\"temporary\":4096},\"boot_id\":\"df4955d9-4762-42b4-a55b-0106ba3786f8\",\"free_bytes\":{\"c\":238232322048,\"e\":256672067584,\"temporary\":880666284032},\"root_device\":\"/dev/sdf\",\"root_mounts\":[[\"/dev/sdf\",\"/\",\"ext4\",\"rw,relatime,discard,errors=remount-ro,data=ordered\",\"0\",\"0\"]],\"root_uuid\":\"c3d3247e-154c-43c0-a9fe-2b91d6db7666\",\"temporary_same_device_as_root\":true,\"vm_memory_bytes\":{\"MemTotal\":25196363776,\"SwapTotal\":6442450944},\"wslconfig_sha256\":\"6efea9e209212784c22240a6019c17cee3bd31011840250c76c3bb31e2c7eea1\",\"wslconfig_size\":21}\n"}
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
if($LASTEXITCODE -ne 0 -or $taskHead -ne 'd950d8124960e82db88ae5cc08775d9683b047a4'){throw 'metadata source head changed'}
$taskIndex=Get-Item -LiteralPath 'E:/STUDY/VAST/.git/worktrees/VAST8/index'
if($taskIndex.Length -gt 3145728 -or (Test-Path -LiteralPath 'E:/STUDY/VAST/.git/worktrees/VAST8/index.lock')){throw 'index control quote changed'}
[ordered]@{schema_version=1;scope='metadata-retention-only';utc=[DateTime]::UtcNow.ToString('o');source_commit=$taskHead;volumes=$taskVolumes;pagefile_settings=$taskPage;default_uid=$taskDistro.DefaultUid;wslconfig_size=$taskConfig.Length;index_bytes=$taskIndex.Length;index_lock_absent=$true;usn_c=@{exit_code=$taskUsnCExit;lines=$taskUsnC};usn_e=@{exit_code=$taskUsnEExit;lines=$taskUsnE};additional_tranche_bytes=16777216;cumulative_direct_bytes=2181038080;whole_chain_admitted=$false}|ConvertTo-Json -Depth 6 -Compress
}
$taskWindows=$taskWindows|ConvertFrom-Json
if(([DateTime]::UtcNow-([DateTime]$taskWindows.utc).ToUniversalTime()).TotalSeconds -gt 120){throw 'Windows observation stale'}
$taskPins=@(
 @('scripts/materialize_runtime_build_context_v3.py','db4cdb5f42268e2f1eb2c75c1bb44fa25d1e30f8938e4809cd1477b1ced88d01','materializer'),
 @('tests/test_runtime_build_context_v3.py','1fc1b6d85a11911c9fdc2f992a670474a6effd1fe51bcb1a897b6732619392a0','test'),
 @('openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/preparatory_checks.py','39f7416c18e7b7d1018d1b2471d86130906a9abb716bea8a064d9495314205ea','runner'))
$taskCopies=@()
$taskBytes=0
foreach($taskPin in $taskPins){
 $taskInfo=Get-Item -LiteralPath $taskPin[0]
 if($taskInfo.Length -gt 65536 -or (Get-FileHash -LiteralPath $taskInfo.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskPin[1]){throw 'reviewed build extent source differs'}
 $taskBytes+=$taskInfo.Length
 $taskCopies+=,[ordered]@{source=$taskPin[0];bytes=$taskInfo.Length;sha256=$taskPin[1];original=('buildextent-'+$taskPhase.Split('-')[1]+'-'+$taskPin[2]+'-source.original.py')}
}
if($taskBytes -gt 131072){throw 'aggregate source bound'}
& git -c gc.auto=0 -c maintenance.auto=false diff --quiet HEAD -- tests/fixtures/accepted_policy_fixture_compiler_v1.py tests/fixtures/accepted_policy_standalone_reader_fixture_v2.py tests/fixtures/accepted_policy_fixture_report_v1.py
if($LASTEXITCODE -ne 0){throw 'frozen owner/compiler/encoder differs'}
foreach($taskName in @(('prep-'+$taskPhase),('temporary-'+$taskPhase),('prep-'+$taskPhase+'-admission.original.json'))+@($taskCopies|ForEach-Object {$_.original})){
 if(Test-Path -LiteralPath (Join-Path $taskBase $taskName)){throw 'build extent namespace consumed'}
}
$taskRecord=[ordered]@{schema_version=1;phase=$taskPhase;observed_utc=[DateTime]::UtcNow.ToString('o');product_commit=$taskWindows.source_commit;source_pins=$taskCopies;direct_file_allowance_bytes=2181038080;assigned_pair_bytes=33554432;reviewed_method_count=2;reviewed_vector_count=4;independent_source_verdict='CLEAR /root/blocker_plan_review';independent_capacity_verdict='CLEAR /root/capacity_review';agent_execution_admission='DELEGATED_AGENT_APPROVED_FINITE_CONTROLLED_ONLY';whole_chain_admitted=$false;windows=$taskWindows;linux_tool_return=$taskLinux}
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
