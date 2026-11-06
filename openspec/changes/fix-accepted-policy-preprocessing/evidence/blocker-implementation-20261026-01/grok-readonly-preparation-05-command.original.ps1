param([Parameter(Mandatory)][string]$LinuxGuardJson)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$taskRoot='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
$taskBase=Join-Path $taskRoot 'openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskClock=[Diagnostics.Stopwatch]::StartNew()
$taskDeadline=[Environment]::TickCount64+180000
$taskApproval='AGENT delegated execution admission PR9 exact frozen preparation05'
$taskSourceVerdict='Independent provider_route_review CLEAR a3695c79 metadata32 sum5209749'
$taskCapacityVerdict='Independent capacity_review CLEAR a3695c79 direct2430MiB C73.33203125'
$taskStage='entry';$taskFailure=$null;$taskFailureStage=$null
$taskState=$null;$taskBoundary=$null;$taskSetup=$null;$taskPost=$null
$taskSources=[Collections.Generic.List[object]]::new(16)
$taskRuntime=[Collections.Generic.List[object]]::new(4)
$taskCauses=[Collections.Generic.List[object]]::new(32);$taskCauseState=[pscustomobject]@{Overflow=$false}
$taskResults=[Collections.Generic.List[object]]::new(3)
$taskSites=[Collections.Generic.List[object]]::new(8)
$taskControllerReturns=[Collections.Generic.List[object]]::new(3)
$taskCommands=@('inspect','plugin','mcp')
$taskPersistence=$null;$taskReceiptBytes=$null;$taskReceiptHash=$null
$taskFinished=$false;$taskLate=$null
$taskDurableAdmitted=$false

function Add-Pr9PreparationCause {
 param([string]$Code,[Exception]$Failure)
 foreach($taskPrior in $taskCauses){if([Object]::ReferenceEquals($taskPrior.failure,$Failure)){return}}
 if($taskCauses.Count -ge 32){$taskCauseState.Overflow=$true;return}
 $taskCauses.Add([pscustomobject]@{code=$Code;failure=$Failure})
}
function Close-Pr9PreparationResource {
 param([string]$Code,$Resource)
 if($null -ne $Resource){try{$Resource.Dispose()}catch{Add-Pr9PreparationCause $Code $_.Exception}}
}
function Read-Pr9PreparationSource {
 param([string]$Name,[int]$Bytes,[string]$Sha256)
 if($Bytes -lt 0 -or $Bytes -gt 32768 -or $taskClock.ElapsedMilliseconds -ge 165000){throw 'public source bound'}
 $taskStream=[IO.File]::Open((Join-Path $taskBase $Name),'Open','Read','Read')
 $taskSources.Add($taskStream)
 if($taskStream.Length -ne $Bytes){throw 'public source extent differs'}
 $taskRaw=[byte[]]::new($Bytes);$taskOffset=0
 while($taskOffset -lt $Bytes){
  if($taskClock.ElapsedMilliseconds -ge 165000){throw 'source capture deadline'}
  $taskN=$taskStream.Read($taskRaw,$taskOffset,$Bytes-$taskOffset)
  if($taskN -le 0){throw 'public source shrink'}
  $taskOffset+=$taskN
 }
 if($taskStream.ReadByte() -ne -1 -or [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskRaw)).ToLowerInvariant() -cne $Sha256){throw 'public source identity differs'}
 return ,$taskRaw
}
function Write-Pr9PreparationPublic {
 param([string]$Name,[byte[]]$Bytes,[int]$Maximum)
 if(-not $taskDurableAdmitted -or $Maximum -gt 32768 -or $Bytes.Length -gt $Maximum -or [Environment]::TickCount64 -ge $taskDeadline-1000){throw 'public result prewrite bound'}
 $taskFile=$null;$taskPrimary=$null;$taskClose=$null
 $taskFacts=[ordered]@{attempted=$false;created=$false;written_prefix_bytes=0;write_extent_unknown=$false;fsync_completed=$false;close_completed=$false;post_write_clock_known=$false;deadline_exceeded=$null;complete=$false}
 try{
  $taskFacts.attempted=$true
  $taskFile=[IO.File]::Open((Join-Path $taskBase $Name),'CreateNew','Write','Read')
  $taskFacts.created=$true
  try{$taskFile.Write($Bytes,0,$Bytes.Length);$taskFacts.written_prefix_bytes=$Bytes.Length}
  catch{$taskFacts.write_extent_unknown=$true;throw}
  $taskFile.Flush($true);$taskFacts.fsync_completed=$true
 }catch{$taskPrimary=$_.Exception}
 finally{if($null -ne $taskFile){try{$taskFile.Dispose();$taskFacts.close_completed=$true}catch{$taskClose=$_.Exception}}}
 if($null -eq $taskPrimary -and $null -ne $taskClose){$taskPrimary=$taskClose;$taskClose=$null}
 if($null -ne $taskPrimary){
  Add-Pr9PreparationCause 'public_persistence' $taskPrimary
  if($null -ne $taskClose){Add-Pr9PreparationCause 'public_close' $taskClose}
 }
 try{$taskFacts.deadline_exceeded=[Environment]::TickCount64 -ge $taskDeadline;$taskFacts.post_write_clock_known=$true}
 catch{Add-Pr9PreparationCause 'persistence_completion_clock' $_.Exception}
 $taskFacts.complete=($null -eq $taskPrimary -and $taskFacts.fsync_completed -and $taskFacts.close_completed -and $taskFacts.post_write_clock_known -and $taskFacts.deadline_exceeded -eq $false)
 return [pscustomobject]$taskFacts
}
function Hold-Pr9PreparationRuntime {
 param([string]$Path,[long]$Bytes,[string]$Sha256)
 Assert-Pr9GrokPreparationClock $taskClock
 $taskNode=Open-Pr9GrokProfileHeldNode $taskState $Path -Access 2147614720
 if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or $taskNode.Info.Size -ne $Bytes){throw 'runtime physical extent differs'}
 $taskItem=[pscustomobject]@{Node=$taskNode;Stream=$null}
 $taskRuntime.Add($taskItem)
 $taskItem.Stream=[IO.FileStream]::new($taskNode.Handle,[IO.FileAccess]::Read,4096,$false)
 $taskHash=[Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
 $taskBuffer=[byte[]]::new(65536);$taskRemaining=$Bytes
 try{
  while($true){
   Assert-Pr9GrokPreparationClock $taskClock
   $taskN=$taskItem.Stream.Read($taskBuffer,0,[int][Math]::Min(65536,$taskRemaining+1))
   if($taskN -eq 0){break}
   if($taskN -gt $taskRemaining){throw 'runtime grew'}
   $taskHash.AppendData($taskBuffer,0,$taskN);$taskRemaining-=$taskN
  }
  if($taskRemaining -ne 0 -or [Convert]::ToHexString($taskHash.GetHashAndReset()).ToLowerInvariant() -cne $Sha256){throw 'installed runtime identity differs'}
 }catch{
  Add-Pr9PreparationCause 'runtime_hash' $_.Exception
  throw
 }finally{Close-Pr9PreparationResource 'runtime_hash_close' $taskHash}
 if($taskCauses.Count){throw 'runtime source operation failed'}
}
function Assert-Pr9PreparationCredential {
 $taskAuth=@($taskState.Sources|Where-Object Relative -ceq 'auth.json')
 if($taskAuth.Count -ne 1){throw 'single credential source required'}
 $taskRaw=Read-Pr9GrokHeldSmallBytes -Stream $taskAuth[0].Stream -Length 1764 -Maximum 65536 -Clock $taskClock
 try{[void](Get-Pr9GrokCredentialExpiry -PrivateAuthBytes $taskRaw)}
 finally{[Array]::Clear($taskRaw,0,$taskRaw.Length)}
 Assert-Pr9GrokPreparationClock $taskClock
}
function Register-Pr9PrivateStaticOutputs {
 param([string]$Mode,$Capture)
 if(-not $Capture.complete -or $Capture.channels.Count -ne 2){throw 'complete static capture required'}
 for($taskI=0;$taskI -lt 2;$taskI++){
  $taskLabel=@('stdout','stderr')[$taskI]
  $taskPath=[IO.Path]::Combine($taskState.OutputRoot,$Mode+'.'+$taskLabel+'.private')
  if($taskState.Created.Count -ge 64){throw 'private output node bound'}
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState $taskPath
  if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or
     $taskNode.Info.Size -gt 262144 -or $taskNode.Info.Size -ne $Capture.channels[$taskI].written_prefix_bytes){
   throw 'private output extent/identity differs'
  }
  $taskState.Created.Add($taskPath)
 }
}
function Seal-Pr9PrivateStaticOutputs {
 $taskTargets=[Collections.Generic.List[object]]::new(7)
 foreach($taskNode in $taskState.Nodes){
  if($taskNode.Path -ceq $taskState.OutputRoot){$taskTargets.Add($taskNode)}
 }
 foreach($taskMode in $taskCommands){
  foreach($taskLabel in @('stdout','stderr')){
   $taskPath=[IO.Path]::Combine($taskState.OutputRoot,$taskMode+'.'+$taskLabel+'.private')
   $taskMatches=@($taskState.Nodes|Where-Object Path -ceq $taskPath)
   if($taskMatches.Count -ne 1){throw 'single private raw output required'}
   $taskTargets.Add($taskMatches[0])
  }
 }
 if($taskTargets.Count -ne 7){throw 'private seal roster'}
 $taskNewWriters=[Collections.Generic.List[object]]::new(7)
 try{
  foreach($taskTarget in $taskTargets){
   Assert-Pr9GrokPreparationClock $taskClock
   $taskWriter=Open-Pr9ReadOnlyGrokNode -Path $taskTarget.Path -Access 0x00060080
   $taskState.WriteHandles.Add($taskWriter.Handle);$taskNewWriters.Add($taskWriter.Handle);$taskState.WriteOpens++
   if($taskWriter.Info.Volume -ne $taskTarget.Info.Volume -or $taskWriter.Info.Index -ne $taskTarget.Info.Index){throw 'raw seal identity differs'}
  }
  for($taskI=0;$taskI -lt 7;$taskI++){
   Assert-Pr9GrokPreparationClock $taskClock
   [Pr9ReadOnlyGrokNativeV1]::DenyWrites($taskNewWriters[$taskI],$taskSid,(($taskTargets[$taskI].Info.Attributes -band 0x10) -ne 0))
   $taskState.DeniedNodes++
  }
 }catch{
  Add-Pr9PreparationCause 'private_raw_seal' $_.Exception
  throw
 }finally{
  foreach($taskHandle in $taskNewWriters){
   try{$taskHandle.Dispose();$taskState.WriteCloses++}catch{Add-Pr9PreparationCause 'raw_writer_close' $_.Exception}
  }
 }
 $taskOutputNode=@($taskTargets|Where-Object Path -ceq $taskState.OutputRoot)[0]
 foreach($taskTarget in $taskTargets){$taskState.ExtraDenied.Add($taskTarget)}
 if($taskState.WriteOpens -ne 62 -or $taskState.WriteCloses -ne 62 -or $taskState.DeniedNodes -ne 62 -or
    @($taskState.WriteHandles|Where-Object{-not $_.IsClosed}).Count -or $taskCauses.Count){throw 'private seal unavailable'}
}
function Get-Pr9PreparationNumericFailure {
 param([Exception]$Failure)
 $taskChain=[Collections.Generic.List[object]]::new(8)
 $taskCurrent=$Failure;$taskReason=$null
 while($null -ne $taskCurrent -and $taskChain.Count -lt 8){
  $taskType=$taskCurrent.GetType().FullName
  if($taskType.Length -gt 128 -or $taskType -cnotmatch '\A[A-Za-z0-9_.+]{1,128}\z'){$taskType='bounded_unknown_exception_type'}
  $taskNative=$null
  if($taskCurrent -is [ComponentModel.Win32Exception]){$taskNative=$taskCurrent.NativeErrorCode}
  if($taskCurrent.Message -ceq 'canonical literal C path required'){$taskReason='canonical_literal_c_path_required'}
  if($taskCurrent.Message -ceq 'node path identity mismatch'){$taskReason='node_path_identity_mismatch'}
  $taskChain.Add([pscustomobject]@{type=$taskType;hresult=$taskCurrent.HResult;win32_code=$taskNative})
  $taskCurrent=$taskCurrent.InnerException
 }
 return [pscustomobject]@{chain=@($taskChain);chain_truncated=($null -ne $taskCurrent);allowlisted_wrapper_reason=$taskReason}
}
try{
 if((Get-Location).Path -cne $taskRoot -or $taskApproval -ceq 'PENDING' -or
    $taskSourceVerdict -ceq 'PENDING' -or $taskCapacityVerdict -ceq 'PENDING'){throw 'preparation admission required'}
 if($PSVersionTable.PSVersion.ToString() -cne '7.5.5' -or
    [Runtime.InteropServices.RuntimeInformation]::FrameworkDescription -cne '.NET 9.0.14'){throw 'qualified PowerShell runtime required'}
 [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
 foreach($taskName in @('grok-readonly-preparation-05-admission.original.json','grok-readonly-preparation-05.original.json',
   'grok-readonly-inspect-05-literal.original.json','grok-readonly-plugin-05-literal.original.json','grok-readonly-mcp-05-literal.original.json',
   'grok-readonly-inspect-05-controller.original.json','grok-readonly-plugin-05-controller.original.json','grok-readonly-mcp-05-controller.original.json')){
  if(Test-Path -LiteralPath (Join-Path $taskBase $taskName)){throw 'preparation namespace consumed'}
 }
 $taskStage='source_capture'
 $taskGuard=Read-Pr9PreparationSource 'grok_readonly_preparation_guard_v1.proposed.ps1' 4692 '02054a54d2be0ae8615b66b1d820abd037d1f0883a13e251196403e253c6f8d8'
 . ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskGuard)))
 $taskBoundary=Assert-Pr9ReadOnlyPreparationBoundary -LinuxGuardJson $LinuxGuardJson -Clock $taskClock
 $taskDurableAdmitted=$true
 foreach($taskPin in @(
  @('grok_readonly_native_support_v2.proposed.ps1',15878,'3af24f1fb5324c96050310526724a46a4283008918cf7e4a990271beab331c5c'),
  @('grok_readonly_data_support_v1.proposed.ps1',12204,'1bf3f7b5234db64806ee644931edcac42c5c1da06069823b32552971c2fea8d2'),
  @('grok_readonly_profile_support_v5.proposed.ps1',24723,'d2e817dd8fd8f054f548e2ca6b064d8174fcab70ee55564a3f989eb7c470b8b3'),
  @('grok_readonly_static_invocation_v5.proposed.ps1',8295,'71a42d3f1a53f04ee9703ddd83c2afd04fa65046d1deb46c7c04c9c287e8a029'),
  @('grok_readonly_custody_qualification_v1.proposed.ps1',10235,'4171724ed78aba87b7a84281f74906c42ed522ee724b4ee42cedbfdfb905c98a')
 )){
  $taskRaw=Read-Pr9PreparationSource $taskPin[0] $taskPin[1] $taskPin[2]
  . ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskRaw)))
 }
 $taskRosterRaw=Read-Pr9PreparationSource 'B3-grok-readonly-roster-05.proposed.json' 6124 '56ab539d361e5204bf6bd542b2f4f2d21138664978e1e4732fec401d8c60f3bc'
 $taskRoster=[Text.Encoding]::UTF8.GetString($taskRosterRaw)|ConvertFrom-Json -DateKind String
 foreach($taskPin in @(
  @('grok_windows_family_capture_v2.proposed.py',27125,'3f9c2ac13b64a2329fa060d922f81b86420da4eb065e56af86fb4dd4901ac864'),
  @('grok_reviewed_job_definitions_v1.proposed.py',7981,'54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3'),
  @('grok_readonly_static_driver_v5.proposed.py',11774,'09a0c1a774186e9f2ae891d0fd1b5efae5fb8b2d348150b760b5956ae919d794')
 )){[void](Read-Pr9PreparationSource $taskPin[0] $taskPin[1] $taskPin[2])}
 $taskStage='native_runtime'
 Add-Pr9ReadOnlyGrokNativeSupport
 if([Runtime.InteropServices.Marshal]::SizeOf([type][Pr9ReadOnlyGrokNativeV1+Info]) -ne 52){throw 'native info ABI differs'}
 $taskToken=Get-Pr9ReadOnlyGrokPrimaryIdentity;$taskSid=$taskToken.UserSid
 $taskState=New-Pr9GrokProfileState
 foreach($taskPath in @('C:\Python314','C:\Python314\DLLs','C:\Python314\Lib','C:\Python314\Lib\asyncio',
   'C:\Users\s-a-balashov\.grok','C:\Users\s-a-balashov\.grok\bin')){
  [void](Open-Pr9GrokProfileHeldNode $taskState $taskPath)
 }
 $taskStage='runtime_hashes'
 Hold-Pr9PreparationRuntime 'C:\Python314\python.exe' 106208 '4942b86a6597e5aee0128daa00050ed79bc21f6e709a78eb19cbfeb0c2f39ac9'
 Hold-Pr9PreparationRuntime 'C:\Python314\Lib\asyncio\windows_utils.py' 5651 '2af1aaa042e4a0ab1d3c06db7aa8fd8b288ab280f5dbee066a4cc3274459bd30'
 Hold-Pr9PreparationRuntime 'C:\Python314\DLLs\_overlapped.pyd' 58080 '1d7028683e6ec50c159139238f90a6c8431ece139a4764900ca11c941ba05d46'
 Hold-Pr9PreparationRuntime 'C:\Users\s-a-balashov\.grok\bin\grok.exe' 172906128 '86c6c766b7961597c2a327f77e43a7b73cbc44f5cee9da6dd74ba73b45ae8b68'
 $taskStage='admission_persistence'
 $taskAdmission=[ordered]@{
  schema_version=1;scope='one_private_readonly_profile_and_three_static_captures_only';source_commit='605eb02733fe256ad5ef14f358eaa81ee1a0ae44'
  inherited_deadline_tick_ms=$taskDeadline;existing_preparation_reservation_bytes=33554432
  cumulative_direct_bytes=2548039680;c_additional_quote_gib=73.33203125;cumulative_ext4_scatter_bytes=2617245696
  windows_linux_boundary=$taskBoundary;source_verdict=$taskSourceVerdict;capacity_verdict=$taskCapacityVerdict;delegated_agent_admission=$taskApproval
  model_request_admitted=$false;effective_config_accepted=$false;genuine_or_whole_chain_admitted=$false
 }
 $taskAdmitRaw=[Text.Encoding]::UTF8.GetBytes(($taskAdmission|ConvertTo-Json -Depth 12 -Compress)+[char]10)
 $taskAdmitWrite=Write-Pr9PreparationPublic 'grok-readonly-preparation-05-admission.original.json' $taskAdmitRaw 16384
 $taskSites.Add([pscustomobject]@{site='admission';persistence=$taskAdmitWrite})
 if(-not $taskAdmitWrite.complete){throw 'preparation admission persistence refused'}
 $taskStage='source_hold_copy_denial'
 $taskSetup=Copy-Pr9ClosedGrokProfile -State $taskState -Roster $taskRoster -Sid $taskSid -Clock $taskClock
 [void](Test-Pr9ClosedGrokProfile -State $taskState -Sid $taskSid -Clock $taskClock)
 foreach($taskKind in @('write','append','new-file','new-directory','delete','replace','rename-file','rename-directory','write-dac')){
  $taskStage='denial_'+$taskKind
  Invoke-Pr9FixedSentinelDenial -State $taskState -Kind $taskKind -Sid $taskSid -Clock $taskClock
 }
 if($taskState.Probes.Count -ne 9 -or @($taskState.Probes|Where-Object {-not $_.complete -or -not $_.attempted -or $_.unexpected_success -or $_.denied_code -notin @(5,32) -or ($_.kind -ceq 'write-dac' -and $_.denied_code -ne 5)}).Count){throw 'nine fixed denials required'}
 [void](Test-Pr9ClosedGrokProfile -State $taskState -Sid $taskSid -Clock $taskClock)
 foreach($taskMode in $taskCommands){
  $taskStage='static_'+$taskMode
  Assert-Pr9PreparationCredential
  $taskTokenNow=Get-Pr9ReadOnlyGrokPrimaryIdentity
  if($taskTokenNow.UserSid -cne $taskSid){throw 'primary caller identity changed'}
  $taskInvocation=New-Pr9ReadOnlyStaticInvocation -DeadlineTickMs $taskDeadline -Mode $taskMode
  $taskLiteral=[ordered]@{executable=$taskInvocation.Executable;arguments=$taskInvocation.Arguments;source_pins=$taskInvocation.SourcePins;deadline_tick_ms=$taskDeadline;mode=$taskMode;model_request_admitted=$false}
  $taskLiteralRaw=[Text.Encoding]::UTF8.GetBytes(($taskLiteral|ConvertTo-Json -Depth 6 -Compress)+[char]10)
  $taskLiteralWrite=Write-Pr9PreparationPublic ('grok-readonly-'+$taskMode+'-05-literal.original.json') $taskLiteralRaw 32768
  $taskSites.Add([pscustomobject]@{site=($taskMode+'_literal');persistence=$taskLiteralWrite})
  if(-not $taskLiteralWrite.complete){throw 'literal persistence refused'}
  $PSNativeCommandArgumentPassing='Standard'
  $PSNativeCommandUseErrorActionPreference=$false
  $taskReply=@(& $taskInvocation.Executable @($taskInvocation.Arguments) 2>&1)
  $taskExit=$LASTEXITCODE
  $taskReplyText=($taskReply -join [string][char]10)
  if([Text.Encoding]::UTF8.GetByteCount($taskReplyText) -gt 8192){throw 'closed controller status bound'}
  $taskResult=$null;$taskParseFailure=$null
  $taskReturnFact=[pscustomobject]@{mode=$taskMode;exit_code=$taskExit;returned_utf8_bytes=[Text.Encoding]::UTF8.GetByteCount($taskReplyText);unparsed_return_base64=$null}
  $taskControllerReturns.Add($taskReturnFact)
  try{
   $taskResult=$taskReplyText|ConvertFrom-Json -DateKind String
   if($taskResult.scope -cne 'static_capture_only' -or $taskResult.mode -cne $taskMode){throw 'static returned status shape'}
   $taskResults.Add($taskResult)
  }catch{
   $taskParseFailure=$_.Exception
   $taskReturnFact.unparsed_return_base64=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($taskReplyText))
   Add-Pr9PreparationCause ($taskMode+'_controller_parse') $taskParseFailure
  }
  $taskReplyRaw=[Text.Encoding]::UTF8.GetBytes($taskReplyText+[char]10)
  $taskControllerWrite=Write-Pr9PreparationPublic ('grok-readonly-'+$taskMode+'-05-controller.original.json') $taskReplyRaw 16384
  $taskSites.Add([pscustomobject]@{site=($taskMode+'_controller');exit_code=$taskExit;returned_bytes=$taskReplyRaw.Length;parsed_retained=($null -eq $taskParseFailure);persistence=$taskControllerWrite})
  if($null -ne $taskParseFailure){throw $taskParseFailure}
  if(-not $taskControllerWrite.complete){throw 'controller status persistence refused'}
  if($taskExit -ne 0){throw 'static controller refused'}
  if($taskResult.scope -cne 'static_capture_only' -or $taskResult.mode -cne $taskMode -or
     -not $taskResult.complete -or $taskResult.ready_for_model -or $taskResult.effective_configuration_accepted){
   throw 'static status contract differs'
  }
  Register-Pr9PrivateStaticOutputs -Mode $taskMode -Capture $taskResult.capture
  [void](Test-Pr9ClosedGrokProfile -State $taskState -Sid $taskSid -Clock $taskClock)
 }
 $taskStage='final_profile_seal'
 Seal-Pr9PrivateStaticOutputs
 $taskPost=Test-Pr9ClosedGrokProfile -State $taskState -Sid $taskSid -Clock $taskClock
 Assert-Pr9PreparationCredential
 if($taskResults.Count -ne 3 -or $taskState.Created.Count -ne 62){throw 'complete static/private census required'}
 $taskFinished=$true
}catch{
 $taskFailure=$_.Exception;$taskFailureStage=$taskStage
 if($null -ne $taskState){foreach($taskCause in $taskState.Causes){Add-Pr9PreparationCause $taskCause.code $taskCause.failure}}
 Add-Pr9PreparationCause $taskFailureStage $taskFailure
}
finally{
 foreach($taskItem in $taskRuntime){Close-Pr9PreparationResource 'runtime_stream_close' $taskItem.Stream}
 if($null -ne $taskState){
  try{Close-Pr9ClosedGrokProfile $taskState}catch{Add-Pr9PreparationCause 'profile_outer_close' $_.Exception}
  foreach($taskCause in $taskState.Causes){Add-Pr9PreparationCause $taskCause.code $taskCause.failure}
  if($taskState.CauseOverflow){$taskCauseState.Overflow=$true}
 }
 if($null -ne $taskFailure){Add-Pr9PreparationCause $taskFailureStage $taskFailure}
 foreach($taskStream in $taskSources){Close-Pr9PreparationResource 'public_source_close' $taskStream}
}
try{$taskLate=[Environment]::TickCount64 -ge $taskDeadline}catch{Add-Pr9PreparationCause 'completion_clock' $_.Exception}
$taskComplete=$taskFinished -and -not $taskLate -and -not $taskCauses.Count -and -not $taskCauseState.Overflow
$taskReceipt=[ordered]@{
 schema_version=1;scope='private_readonly_profile_and_static_capture_only';source_commit='605eb02733fe256ad5ef14f358eaa81ee1a0ae44'
 capture_preparation_complete=$taskComplete;model_request_admitted=$false;ready_for_model=$false
 effective_configuration_accepted=$false;configuration_interpretation='pending_offline_schema_and_independent_review'
 completed_static_commands=@($taskResults|Where-Object complete|ForEach-Object{$_.mode});not_completed=@($taskCommands|Where-Object{$_ -notin @($taskResults|Where-Object complete|ForEach-Object{$_.mode})})
 returned_controller_facts=@($taskResults);site_persistence=@($taskSites)
 returned_controller_metadata=@($taskControllerReturns)
 path_projection=$(if($null -ne $taskState){$taskState.PathProjection}else{$null})
 private_operation_stage=$(if($null -ne $taskState){$taskState.OperationStage}else{$null})
 initiating_numeric_failure=(Get-Pr9PreparationNumericFailure $(if($taskCauses.Count){$taskCauses[0].failure}else{$taskFailure}))
 custody_qualification=$(if($null -ne $taskState){$taskState.CustodyQualification}else{$null})
 deadline_tick_ms=$taskDeadline;deadline_exceeded=$taskLate;phase=$taskStage
 primary_code=$(if($taskCauses.Count){$taskCauses[0].code}else{$null});secondary_codes=@($taskCauses|Select-Object -Skip 1|ForEach-Object{$_.code});cause_overflow=$taskCauseState.Overflow
 profile_members=$(if($null -ne $taskSetup){$taskSetup.Members}else{$null})
 profile_logical_bytes=$(if($null -ne $taskSetup){$taskSetup.LogicalBytes}else{$null})
 registered_new_private_nodes=$(if($null -ne $taskState){$taskState.Created.Count}else{0})
 actual_new_private_nodes=$(if($taskFinished -and $null -ne $taskState){$taskState.Created.Count}else{$null})
 private_node_extent_unknown=(-not $taskFinished)
 completed_denial_operations=$(if($null -ne $taskState){$taskState.DeniedNodes}else{0})
 denial_probes=$(if($null -ne $taskState){@($taskState.Probes)}else{@()})
 private_files_or_hashes_in_public_evidence=$false;private_raw_channels_sealed=($null -ne $taskPost)
}
try{
 if($taskDurableAdmitted){
 $taskReceiptRaw=[Text.Encoding]::UTF8.GetBytes(($taskReceipt|ConvertTo-Json -Depth 8 -Compress)+[char]10)
 $taskReceiptBytes=$taskReceiptRaw.Length
 $taskReceiptHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskReceiptRaw)).ToLowerInvariant()
 $taskPersistence=Write-Pr9PreparationPublic 'grok-readonly-preparation-05.original.json' $taskReceiptRaw 32768
 }
}catch{Add-Pr9PreparationCause 'receipt_persistence' $_.Exception}
$taskFinalLate=$null
try{$taskFinalLate=[Environment]::TickCount64 -ge $taskDeadline}catch{Add-Pr9PreparationCause 'final_clock' $_.Exception}
$taskCarrier=[ordered]@{attempted=$false;raw_bytes=$null;base64_characters=$null;planned_frame_bytes=$null;local_write_returned=$false;local_flush_returned=$false;written_prefix_bytes=$null;write_extent_unknown=$false;delivery_available=$null;external_witness_required=$true}
if($taskDurableAdmitted -and ($null -eq $taskPersistence -or -not $taskPersistence.complete)){
 try{
  $taskBundle=[ordered]@{
   scope='preparation_complete_public_refusal_facts';source_commit='605eb02733fe256ad5ef14f358eaa81ee1a0ae44'
   receipt_snapshot=$taskReceipt;final_receipt_persistence=$taskPersistence
   primary_code=$(if($taskCauses.Count){$taskCauses[0].code}else{$null})
   secondary_codes=@($taskCauses|Select-Object -Skip 1|ForEach-Object{$_.code})
   cause_overflow=$taskCauseState.Overflow;phase=$taskStage;deadline_exceeded=$taskFinalLate
   registered_new_private_nodes=$(if($null -ne $taskState){$taskState.Created.Count}else{0})
   actual_private_extent_known=$taskFinished;ready_for_model=$false;model_request_admitted=$false
  }
  $taskBundleRaw=[Text.Encoding]::UTF8.GetBytes(($taskBundle|ConvertTo-Json -Depth 12 -Compress -EscapeHandling Default))
  $taskCarrier.raw_bytes=$taskBundleRaw.Length
  if($taskBundleRaw.Length -gt 40960){throw 'complete refusal raw bound'}
  $taskPayload=[Convert]::ToBase64String($taskBundleRaw)
  $taskCarrier.base64_characters=$taskPayload.Length
  if($taskPayload.Length -gt 54616){throw 'complete refusal encoded bound'}
  $taskCapsule=[ordered]@{scope='preparation_refusal_capsule';encoding='base64-json';raw_bytes=$taskBundleRaw.Length;sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskBundleRaw)).ToLowerInvariant();payload=$taskPayload}
  $taskCapsuleText=$taskCapsule|ConvertTo-Json -Depth 3 -Compress -EscapeHandling Default
  $taskCapsuleBytes=[Text.Encoding]::UTF8.GetByteCount($taskCapsuleText)
  if($taskCapsuleBytes-$taskPayload.Length -gt 512){throw 'complete refusal header bound'}
  $taskCarrier.planned_frame_bytes=$taskCapsuleBytes+1
  $taskCarrier.attempted=$true
  # ConsolePal.Windows(.NET9.0.14) ignores native byte counts and treats some
  # broken-pipe errors as success. Local returns never establish receipt.
  $taskCarrier.write_extent_unknown=$true
  try{
   [Console]::Out.Write($taskCapsuleText+[char]10)
   $taskCarrier.local_write_returned=$true
   [Console]::Out.Flush();$taskCarrier.local_flush_returned=$true
  }catch{
   throw
  }
 }catch{Add-Pr9PreparationCause 'refusal_capsule' $_.Exception}
}
try{$taskFinalLate=[Environment]::TickCount64 -ge $taskDeadline}catch{Add-Pr9PreparationCause 'post_capsule_clock' $_.Exception;$taskFinalLate=$null}
$taskStatus=[ordered]@{
 scope='preparation_parent_terminal'
 capture_preparation_complete=($taskComplete -and $null -ne $taskPersistence -and $taskPersistence.complete -and $taskFinalLate -eq $false -and -not $taskCauses.Count -and -not $taskCauseState.Overflow)
 ready_for_model=$false;model_request_admitted=$false;receipt_bytes=$taskReceiptBytes;receipt_sha256=$taskReceiptHash
 receipt_persistence=$taskPersistence;refusal_capsule_delivery=[pscustomobject]$taskCarrier;deadline_exceeded=$taskFinalLate
 primary_code=$(if($taskCauses.Count){$taskCauses[0].code}else{$null})
 secondary_codes=@($taskCauses|Select-Object -Skip 1|ForEach-Object{$_.code});cause_overflow=$taskCauseState.Overflow
}
$taskOut=$taskStatus|ConvertTo-Json -Depth 5 -Compress -EscapeHandling Default
if([Text.Encoding]::UTF8.GetByteCount($taskOut) -gt 4096){[Console]::Out.Write('preparation_parent_status_bound'+[char]10);exit 1}
try{[Console]::Out.Write($taskOut+[char]10);[Console]::Out.Flush()}catch{exit 1}
if($taskStatus.capture_preparation_complete){exit 0}
exit 1

