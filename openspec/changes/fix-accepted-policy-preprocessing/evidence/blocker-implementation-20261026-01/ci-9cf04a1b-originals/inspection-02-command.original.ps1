$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression
$taskPath='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/ci-9cf04a1b-originals/cpu-checks.original.zip'
if((Get-Item -LiteralPath $taskPath).Length -ne 3278561 -or (Get-FileHash -LiteralPath $taskPath -Algorithm SHA256).Hash -ne 'a5576129cb2fe37dab9ddfbcc7bfe5c8c25515bc4e4dcdb0e9dd2075c64607a6'){throw 'CI artifact binding differs'}
$taskClock=[Diagnostics.Stopwatch]::StartNew()
$taskFile=[IO.File]::Open($taskPath,'Open','Read','Read')
try {
 $taskZip=[IO.Compression.ZipArchive]::new($taskFile,'Read',$true)
 try {
  if($taskZip.Entries.Count -gt 256 -or @($taskZip.Entries|Where-Object {$_.FullName.Length -gt 512}).Count){throw 'ZIP inventory bound'}
  $taskEntry=$taskZip.GetEntry('unittest-child.report.json')
  if(-not $taskEntry -or $taskEntry.Length -gt 8388608){throw 'CI report entry absent or oversized'}
  $taskInput=$taskEntry.Open();$taskMemory=[IO.MemoryStream]::new()
  try {
   $taskBuffer=[byte[]]::new(65536);$taskBytes=0L
   while(($taskCount=$taskInput.Read($taskBuffer,0,$taskBuffer.Length)) -gt 0){
    if($taskBytes+$taskCount -gt 8388608 -or $taskClock.Elapsed.TotalSeconds -gt 30){throw 'CI report actual read bound'}
    $taskMemory.Write($taskBuffer,0,$taskCount);$taskBytes+=$taskCount
   }
   if($taskBytes -ne $taskEntry.Length){throw 'CI report declared/actual size differs'}
   $taskMemory.Position=0
   $taskOptions=[Text.Json.JsonDocumentOptions]::new();$taskOptions.MaxDepth=32
   $taskDocument=[Text.Json.JsonDocument]::Parse($taskMemory,$taskOptions)
   try {
    $taskRoot=$taskDocument.RootElement
    if($taskRoot.ValueKind -ne [Text.Json.JsonValueKind]::Object){throw 'CI report object required'}
    $taskAllowed=@('tests_run','successful_test_ids','skips','failures','errors','expected_failures','unexpected_successes','missing_required_successes','successful','discovered_ids','selection','portable_skip_audit','profile_observation','observer_failure','child_failure')
    $taskKeys=@($taskRoot.EnumerateObject())
    if($taskKeys.Count -gt 32 -or @($taskKeys|Where-Object {$_.Name -notin $taskAllowed}).Count){throw 'CI report fixed-key schema differs'}
    foreach($taskProperty in $taskKeys){
     if($taskProperty.Value.ValueKind -eq [Text.Json.JsonValueKind]::Array -and $taskProperty.Value.GetArrayLength() -gt 20000){throw 'CI report array cardinality'}
    }
    $taskFailures=[Collections.Generic.List[object]]::new()
    foreach($taskRole in @('failures','errors')){
     $taskArray=$taskRoot.GetProperty($taskRole)
     if($taskArray.GetArrayLength() -gt 128){throw 'CI failure cardinality'}
     foreach($taskItem in $taskArray.EnumerateArray()){
      $taskItemKeys=@($taskItem.EnumerateObject())
      if($taskItemKeys.Count -ne 2 -or @($taskItemKeys|Where-Object {$_.Name -notin @('test_id','traceback')}).Count){throw 'CI failure object schema'}
      $taskId=$taskItem.GetProperty('test_id').GetString()
      $taskTrace=$taskItem.GetProperty('traceback').GetString()
      if($taskId.Length -gt 512 -or $taskTrace.Length -gt 65536){throw 'CI failure string bound'}
      $taskFailures.Add(@{kind=$taskRole;test_id=$taskId;traceback=$taskTrace})
     }
    }
    $taskSummary=@{artifact_id=12704774553;head='9cf04a1b22dcea6e24b0f1be33a2ce8b8ec395ff';zip_members=$taskZip.Entries.Count;report_bytes=$taskBytes;tests_run=$taskRoot.GetProperty('tests_run').GetInt32();successes=$taskRoot.GetProperty('successful_test_ids').GetArrayLength();skips=$taskRoot.GetProperty('skips').GetArrayLength();expected_failures=$taskRoot.GetProperty('expected_failures').GetArrayLength();unexpected_successes=$taskRoot.GetProperty('unexpected_successes').GetArrayLength();missing_required_successes=$taskRoot.GetProperty('missing_required_successes').GetArrayLength();successful=$taskRoot.GetProperty('successful').GetBoolean();failures=@($taskFailures.ToArray())}
    $taskOut=$taskSummary|ConvertTo-Json -Depth 9 -Compress
    if([Text.Encoding]::UTF8.GetByteCount($taskOut) -gt 16384){throw 'CI summary encoding bound'}
    Write-Output $taskOut
   } finally {$taskDocument.Dispose()}
  } finally {$taskInput.Dispose();$taskMemory.Dispose()}
 } finally {$taskZip.Dispose()}
} finally {$taskFile.Dispose()}
