$ErrorActionPreference='Stop'
$taskPrefix=Join-Path (Get-Location) 'openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/B3-producer-clock-grok'
$taskInfo=[Diagnostics.ProcessStartInfo]::new()
$taskInfo.FileName='C:/Users/s-a-balashov/.grok/bin/grok.exe'
$taskInfo.Arguments='--resume 01a17ad0-d506-76d3-95b3-ddb27d4f3f5e --permission-mode plan --no-subagents --disable-web-search --tools read_file,grep,list_dir --output-format json --max-turns 4 --prompt-file '+$taskPrefix+'-prompt.original.txt'
$taskInfo.WorkingDirectory=(Get-Location).Path
$taskInfo.UseShellExecute=$false
$taskInfo.CreateNoWindow=$true
$taskInfo.RedirectStandardOutput=$true
$taskInfo.RedirectStandardError=$true
$taskOutputs=@([IO.File]::Open($taskPrefix+'.original.json','CreateNew','Write','Read'),[IO.File]::Open($taskPrefix+'.stderr.original.log','CreateNew','Write','Read'))
$taskProcess=[Diagnostics.Process]::new()
$taskProcess.StartInfo=$taskInfo
$taskStarted=[Diagnostics.Stopwatch]::StartNew()
$taskLengths=@(0,0)
$taskComplete=@($false,$false)
$taskBuffers=@([byte[]]::new(4096),[byte[]]::new(4096))
try {
 if(-not $taskProcess.Start()){throw 'Grok start failed'}
 $taskInputs=@($taskProcess.StandardOutput.BaseStream,$taskProcess.StandardError.BaseStream)
 $taskReads=@($taskInputs[0].ReadAsync($taskBuffers[0],0,4096),$taskInputs[1].ReadAsync($taskBuffers[1],0,4096))
 while(-not($taskComplete[0] -and $taskComplete[1])) {
  for($taskIndex=0;$taskIndex -lt 2;$taskIndex++){
   if(-not $taskComplete[$taskIndex] -and $taskReads[$taskIndex].IsCompleted){
    $taskCount=$taskReads[$taskIndex].GetAwaiter().GetResult()
    if($taskCount -eq 0){$taskComplete[$taskIndex]=$true;continue}
    if($taskLengths[$taskIndex]+$taskCount -gt 524288){throw 'review channel cap before write'}
    $taskOutputs[$taskIndex].Write($taskBuffers[$taskIndex],0,$taskCount)
    $taskLengths[$taskIndex]+=$taskCount
    $taskReads[$taskIndex]=$taskInputs[$taskIndex].ReadAsync($taskBuffers[$taskIndex],0,4096)
   }
  }
  if($taskStarted.Elapsed.TotalSeconds -ge 600){throw 'review deadline'}
  Start-Sleep -Milliseconds 25
 }
 if(-not $taskProcess.WaitForExit(5000)){throw 'review closure unknown'}
 Write-Output ('Grok exit='+$taskProcess.ExitCode+' bytes='+($taskLengths -join ',')+' elapsed='+[Math]::Round($taskStarted.Elapsed.TotalSeconds,3))
} finally {
 if($taskProcess.Id -and -not $taskProcess.HasExited){$taskProcess.Kill();[void]$taskProcess.WaitForExit(5000)}
 foreach($taskOutput in $taskOutputs){$taskOutput.Flush($true);$taskOutput.Dispose()}
 $taskProcess.Dispose()
}
