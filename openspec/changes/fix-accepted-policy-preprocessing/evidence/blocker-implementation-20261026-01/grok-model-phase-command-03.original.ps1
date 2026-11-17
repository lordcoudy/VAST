# Frozen from reviewed proposed main28391B/af58d11ede0217af74bf24c8cd28bcfd714baac70137c5728d1e029f64ae1c68
# Product605eb02733fe256ad5ef14f358eaa81ee1a0ae44. Only diagnostic04/Attempt03 may be released by the next admission.
param(
 [Parameter(Mandatory)][ValidateSet('diagnostic04','preflight04','preflight05','review05')][string]$Mode,
 [Parameter(Mandatory)][ValidateRange(1,32768)][int]$PreparationBytes,
 [Parameter(Mandatory)][ValidatePattern('\A[a-f0-9]{64}\z')][string]$PreparationSha,
 [Parameter(Mandatory)][string]$LinuxGuardJson,
 [ValidateSet('01','02','03')][string]$Attempt='01',
 [ValidateRange(0,16384)][int]$PreflightBytes=0,
 [string]$PreflightSha=''
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$taskRoot='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
$taskBase=Join-Path $taskRoot 'openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskReview=($Mode -ceq 'review05')
$taskDiagnostic=($Mode -ceq 'diagnostic04')
$taskIndex=$(if($Mode -cin @('diagnostic04','preflight04')){'04'}else{'05'})
$taskClock=[Diagnostics.Stopwatch]::StartNew()
$taskObservationSeconds=$(if($taskReview){585}else{45})
$taskDeadline=[Environment]::TickCount64+$(if($taskReview){600000}else{60000})
$taskSources=[Collections.Generic.List[object]]::new(16)
$taskRuntime=[Collections.Generic.List[object]]::new(4)
$taskCauses=[Collections.Generic.List[object]]::new(32)
$taskCauseState=@{Overflow=$false}
$taskState=$null;$taskResult=$null;$taskFinished=$false;$taskFailure=$null;$taskPostChecksComplete=$false
$taskModelNodes=[Collections.Generic.List[object]]::new(3)
$taskModelWriters=[Collections.Generic.List[object]]::new(3)
$taskNewRootAttempted=$false;$taskNewRootCreated=$false;$taskRawSealed=$false
$taskDurableAdmitted=$false;$taskStage='entry';$taskControllerExit=$null
$taskLiteralWrite=$null;$taskControllerWrite=$null;$taskReceiptWrite=$null
$taskControllerUnparsed=$null
$taskNamePrefix='grok-model-'+$Mode+'-'+$Attempt
$taskNativePin='3af24f1fb5324c96050310526724a46a4283008918cf7e4a990271beab331c5c'
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
 if($Bytes -lt 0 -or $Bytes -gt 131072 -or $taskClock.ElapsedMilliseconds -ge ($taskObservationSeconds*1000)){throw 'public source bound'}
 $taskStream=[IO.File]::Open((Join-Path $taskBase $Name),'Open','Read','Read')
 $taskSources.Add($taskStream)
 if($taskStream.Length -ne $Bytes){throw 'public source extent differs'}
 $taskRaw=[byte[]]::new($Bytes);$taskOffset=0
 while($taskOffset -lt $Bytes){
  if($taskClock.ElapsedMilliseconds -ge ($taskObservationSeconds*1000)){throw 'source capture deadline'}
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

function Hold-Pr9ExistingSnapshot {
 param($Roster,$Preparation,[string]$Sid)
 $taskTree=Get-Pr9GrokProfileExpectedTree $Roster $taskState
 foreach($taskPath in @('C:\','C:\Users','C:\Users\s-a-balashov','C:\Users\s-a-balashov\.codex','C:\Users\s-a-balashov\.codex\worktrees',$taskState.SourceRoot)){
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState $taskPath
  if(($taskNode.Info.Attributes -band 0x10) -eq 0){throw 'physical source parent'}
 }
 foreach($taskRel in $taskTree.Directories){
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState ([IO.Path]::Combine($taskState.SourceRoot,$taskRel))
  if(($taskNode.Info.Attributes -band 0x10) -eq 0){throw 'source directory'}
 }
 foreach($taskRow in $Roster.rows){
  Assert-Pr9GrokPreparationClock $taskClock
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState ([IO.Path]::Combine($taskState.SourceRoot,$taskRow.path.Replace('/','\'))) -Access 2147614720
  if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or $taskNode.Info.Size -ne $taskRow.observed_bytes){throw 'original member extent'}
  $taskSource=[pscustomobject]@{Node=$taskNode;Stream=$null;Relative=$taskRow.path;Role=$taskRow.private_role;Fingerprint=$null}
  $taskState.Sources.Add($taskSource)
  $taskSource.Stream=[IO.FileStream]::new($taskNode.Handle,[IO.FileAccess]::Read,4096,$false)
  $taskSource.Fingerprint=Get-Pr9GrokPrivateFingerprint $taskSource.Stream $taskNode.Info.Size $taskClock
 }
 $taskDirectories=@($taskState.BaseRoot,([IO.Path]::GetDirectoryName($taskState.ProfileRoot)),$taskState.ProfileRoot,$taskState.OutputRoot)
 $taskDirectories+=@($taskTree.Directories|ForEach-Object {[IO.Path]::Combine($taskState.ProfileRoot,$_)})
 $taskDirectories+=@('_deny','_deny\dir-child','_deny\dir-rename','tmp-denied','logs'|ForEach-Object {[IO.Path]::Combine($taskState.ProfileRoot,$_)})
 $taskDirectories+=@([IO.Path]::Combine($taskState.BaseRoot,'_custody'),[IO.Path]::Combine($taskState.BaseRoot,'_custody','child'))
 foreach($taskPath in $taskDirectories){
  Assert-Pr9GrokPreparationClock $taskClock
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState $taskPath
  if(($taskNode.Info.Attributes -band 0x10) -eq 0){throw 'sealed snapshot directory'}
  $taskState.Created.Add($taskPath);$taskState.DirectoryNodes.Add($taskNode);$taskState.ExtraDenied.Add($taskNode)
 }
 foreach($taskSource in $taskState.Sources){
  $taskPath=[IO.Path]::Combine($taskState.ProfileRoot,$taskSource.Relative.Replace('/','\'))
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState $taskPath -Access 2147614720
  if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or $taskNode.Info.Size -ne $taskSource.Node.Info.Size -or
     $taskNode.Info.CreationLow -ne $taskSource.Node.Info.CreationLow -or $taskNode.Info.CreationHigh -ne $taskSource.Node.Info.CreationHigh -or
     $taskNode.Info.WriteLow -ne $taskSource.Node.Info.WriteLow -or $taskNode.Info.WriteHigh -ne $taskSource.Node.Info.WriteHigh){throw 'snapshot member metadata'}
  $taskHeld=[pscustomobject]@{Node=$taskNode;Stream=$null;Copy=[pscustomobject]@{Bytes=$taskNode.Info.Size;PrivateFingerprint=$taskSource.Fingerprint}}
  $taskState.Destinations.Add($taskHeld);$taskState.Created.Add($taskPath)
  $taskHeld.Stream=[IO.FileStream]::new($taskNode.Handle,[IO.FileAccess]::Read,4096,$false)
 }
 foreach($taskPath in @(@('write','delete','rename','replace-source','replace-target')|ForEach-Object {[IO.Path]::Combine($taskState.ProfileRoot,'_deny',$_)})+@(@('source4','copy4')|ForEach-Object {[IO.Path]::Combine($taskState.BaseRoot,'_custody',$_)})){
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState $taskPath
  if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or $taskNode.Info.Size -ne 4){throw 'retained control extent'}
  $taskState.Created.Add($taskPath);$taskState.ExtraDenied.Add($taskNode)
 }
 $taskModes=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
 foreach($taskReturned in $Preparation.returned_controller_facts){
  if($taskReturned.mode -cnotin @('inspect','plugin','mcp') -or -not $taskModes.Add($taskReturned.mode) -or
     -not $taskReturned.complete -or -not $taskReturned.capture.complete -or $taskReturned.capture.channels.Count -ne 2){throw 'prior capture roster'}
  for($taskI=0;$taskI -lt 2;$taskI++){
   $taskSize=$taskReturned.capture.channels[$taskI].written_prefix_bytes
   if(($taskSize -isnot [long] -and $taskSize -isnot [int]) -or $taskSize -lt 0 -or $taskSize -gt 262144){throw 'prior private extent'}
   $taskPath=[IO.Path]::Combine($taskState.OutputRoot,$taskReturned.mode+'.'+@('stdout','stderr')[$taskI]+'.private')
   $taskNode=Open-Pr9GrokProfileHeldNode $taskState $taskPath
   if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or $taskNode.Info.Size -ne $taskSize){throw 'retained raw extent'}
   $taskState.Created.Add($taskPath);$taskState.ExtraDenied.Add($taskNode)
  }
 }
 if($taskModes.Count -ne 3 -or $taskState.Created.Count -ne 62 -or $taskState.ExtraDenied.Count -ne 30 -or $taskState.Destinations.Count -ne 32){throw 'sealed snapshot census'}
 [void](Test-Pr9ClosedGrokProfile $taskState $Sid $taskClock)
}
function Test-Pr9ModelOriginals {
 foreach($taskSource in $taskState.Sources){
  Test-Pr9ReadOnlyGrokNodeIdentity $taskSource.Node -File
  $taskDigest=Get-Pr9GrokPrivateFingerprint $taskSource.Stream $taskSource.Node.Info.Size $taskClock
  if(-not [Pr9ReadOnlyGrokNativeV1]::SameBytes($taskDigest,$taskSource.Fingerprint)){throw 'original member changed'}
 }
}
function Seal-Pr9ModelRaw {
 if($null -eq $taskResult -or $null -eq $taskResult.capture){throw 'model capture unavailable'}
 foreach($taskNode in $taskModelNodes){Test-Pr9ReadOnlyGrokNodeIdentity $taskNode}
 for($taskI=0;$taskI -lt 2;$taskI++){
  $taskPath=[IO.Path]::Combine('C:\Users\s-a-balashov\.gm1',@('stdout','stderr')[$taskI]+'.private')
  $taskNode=Open-Pr9ReadOnlyGrokNode $taskPath
  $taskModelNodes.Add($taskNode)
  $taskExpected=$taskResult.capture.channels[$taskI].written_prefix_bytes
  if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or $taskNode.Info.Size -gt 524288 -or $taskNode.Info.Size -ne $taskExpected){throw 'model raw extent'}
 }
 foreach($taskNode in $taskModelNodes){
  $taskWriter=Open-Pr9ReadOnlyGrokNode $taskNode.Path -Access 0x00060080
  $taskModelWriters.Add($taskWriter.Handle)
  if($taskWriter.Info.Volume -ne $taskNode.Info.Volume -or $taskWriter.Info.Index -ne $taskNode.Info.Index){throw 'model seal identity'}
 }
 try{
  for($taskI=0;$taskI -lt 3;$taskI++){
   [Pr9ReadOnlyGrokNativeV1]::DenyWrites($taskModelWriters[$taskI],$taskSid,(($taskModelNodes[$taskI].Info.Attributes -band 0x10) -ne 0))
  }
 }finally{foreach($taskWriter in $taskModelWriters){Close-Pr9PreparationResource 'model_writer_close' $taskWriter}}
 foreach($taskNode in $taskModelNodes){
  if(-not [Pr9ReadOnlyGrokNativeV1]::DenialMatches($taskNode.Handle,$taskSid,(($taskNode.Info.Attributes -band 0x10) -ne 0))){throw 'model seal mismatch'}
 }
 $taskExpected=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
 $taskExpected.Add('C:\Users\s-a-balashov\.gm1\stdout.private')|Out-Null
 $taskExpected.Add('C:\Users\s-a-balashov\.gm1\stderr.private')|Out-Null
 $taskIterator=$null
 try{
  $taskIterator=[IO.Directory]::EnumerateFileSystemEntries('C:\Users\s-a-balashov\.gm1').GetEnumerator();$taskCount=0
  while($taskIterator.MoveNext()){
   if($taskCount -ge 2 -or -not $taskExpected.Remove($taskIterator.Current)){throw 'model raw inventory'};$taskCount++
  }
  if($taskCount -ne 2 -or $taskExpected.Count){throw 'model raw inventory incomplete'}
 }finally{Close-Pr9PreparationResource 'model_inventory_close' $taskIterator}
}
function Get-Pr9ModelNumericFailure {
 param([Exception]$Failure)
 $taskCurrent=$Failure;$taskChosen=$Failure;$taskCode=$null
 for($taskI=0;$taskI -lt 8 -and $null -ne $taskCurrent;$taskI++){
  if($taskCurrent -is [ComponentModel.Win32Exception]){$taskChosen=$taskCurrent;$taskCode=$taskCurrent.NativeErrorCode;break}
  if($taskCurrent -is [UnauthorizedAccessException]){$taskChosen=$taskCurrent;$taskCode=5;break}
  if($taskCurrent -is [IO.IOException]){$taskChosen=$taskCurrent;$taskCode=($taskCurrent.HResult -band 65535);break}
  $taskCurrent=$taskCurrent.InnerException
 }
 if($null -eq $taskChosen){return $null}
 $taskType=$taskChosen.GetType().FullName
 if($taskType.Length -gt 128 -or $taskType -cnotmatch '\A[A-Za-z0-9_.+]{1,128}\z'){$taskType='bounded_unknown_type'}
 return [ordered]@{exception_type=$taskType;hresult=$taskChosen.HResult;win32_code=$taskCode}
}

try{
 if($Attempt -cne '01' -and -not $taskDiagnostic){throw 'attempt scope'}
 if((Get-Location).Path -cne $taskRoot -or $PSVersionTable.PSVersion.ToString() -cne '7.5.5' -or
    [Runtime.InteropServices.RuntimeInformation]::FrameworkDescription -cne '.NET 9.0.14'){throw 'qualified runtime'}
 foreach($taskName in @('admission','literal','controller','receipt')){
  if(Test-Path -LiteralPath (Join-Path $taskBase ($taskNamePrefix+'-'+$taskName+'.original.json'))){throw 'phase namespace consumed'}
 }
 $taskGuard=Read-Pr9PreparationSource 'grok_readonly_preparation_guard_v1.proposed.ps1' 4692 '02054a54d2be0ae8615b66b1d820abd037d1f0883a13e251196403e253c6f8d8'
 . ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskGuard)))
 $taskBoundary=Assert-Pr9ReadOnlyPreparationBoundary $LinuxGuardJson $taskClock
 foreach($taskPin in @(
  @('grok_readonly_native_support_v2.proposed.ps1',15878,'3af24f1fb5324c96050310526724a46a4283008918cf7e4a990271beab331c5c'),
  @('grok_readonly_model_data_v1.proposed.ps1',12224,'049eb82e99655bd5f9a36898ccd72314588715486d57bc5183f01cfd83a10e99'),
  @('grok_readonly_profile_support_v4.proposed.ps1',24723,'6949d3dad61a7dbac6857a92c89200dc4cac1eac3f0da3aeef66a1944e6a485a'),
  @('grok_readonly_model_invocation_v1.proposed.ps1',8402,'401b39ab9e561ab8e57623d50c33a1b3a7cd1a9d23bf341f50152e7b1c85623a')
 )){
  $taskBytes=Read-Pr9PreparationSource $taskPin[0] $taskPin[1] $taskPin[2]
  . ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskBytes)))
 }
 foreach($taskPin in @(
  @('grok_reviewed_job_definitions_v1.proposed.py',7981,'54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3'),
  @('grok_windows_model_capture_v1.proposed.py',28548,'5780f41dc09c6e8279646f0cff9ad4eed3554cf5b9908febcf1e1dfd4b517b5a'),
  @('grok_readonly_model_driver_v1.proposed.py',25710,'f5c99a05c3458a7d5456dc68887578097e2d4d0f29874cc326a59b627fd76738')
 )){[void](Read-Pr9PreparationSource $taskPin[0] $taskPin[1] $taskPin[2])}
 $taskPreparationRaw=Read-Pr9PreparationSource ('grok-readonly-preparation-'+$taskIndex+'.original.json') $PreparationBytes $PreparationSha
 $taskPreparation=[Text.UTF8Encoding]::new($false,$true).GetString($taskPreparationRaw)|ConvertFrom-Json -DateKind String
 if($taskPreparation.capture_preparation_complete -isnot [bool] -or -not $taskPreparation.capture_preparation_complete -or
    $taskPreparation.source_commit -cne '605eb02733fe256ad5ef14f358eaa81ee1a0ae44' -or
    $taskPreparation.actual_new_private_nodes -ne 62 -or -not $taskPreparation.private_raw_channels_sealed -or
    $taskPreparation.model_request_admitted -or $taskPreparation.effective_configuration_accepted){throw 'successful retained preparation required'}
 if($taskReview){
  if($PreflightBytes -le 0 -or $PreflightSha -cnotmatch '\A[a-f0-9]{64}\z'){throw 'reviewed preflight pin required'}
  $taskPreflightRaw=Read-Pr9PreparationSource 'grok-model-preflight05-01-receipt.original.json' $PreflightBytes $PreflightSha
  $taskPreflight=[Text.UTF8Encoding]::new($false,$true).GetString($taskPreflightRaw)|ConvertFrom-Json -DateKind String
  if($taskPreflight.mode -cne 'preflight05' -or -not $taskPreflight.complete -or
     $taskPreflight.preparation_sha256 -cne $PreparationSha -or -not $taskPreflight.returned_controller.complete -or
     $taskPreflight.returned_controller.grok_performed -or -not $taskPreflight.returned_controller.preflight_complete){throw 'independently reviewed preflight required'}
 }
 $taskPrompt=Read-Pr9PreparationSource 'B3-B4-current-source-grok-prompt-03.original.txt' 110539 'e59bd457dca8028aaf1e25fdab087495f5351a83a9a2fcc134e82fecc9780aa7'
 $taskRosterRaw=Read-Pr9PreparationSource 'B3-grok-readonly-roster-04.proposed.json' 6124 '6c1f965668524d2fff7a3175bf2e843398077155e655600927db97517aba77ff'
 $taskRoster=[Text.UTF8Encoding]::new($false,$true).GetString($taskRosterRaw)|ConvertFrom-Json -DateKind String
 Add-Pr9ReadOnlyGrokNativeSupport
 if([Runtime.InteropServices.Marshal]::SizeOf([type][Pr9ReadOnlyGrokNativeV1+Info]) -ne 52){throw 'native ABI'}
 $taskToken=Get-Pr9ReadOnlyGrokPrimaryIdentity;$taskSid=$taskToken.UserSid
 $taskState=New-Pr9GrokProfileState
 $taskState.BaseRoot='C:\Users\s-a-balashov\.g'+$(if($taskIndex -ceq '04'){'4'}else{'5'})
 $taskState.ProfileRoot=[IO.Path]::Combine($taskState.BaseRoot,'a','p')
 $taskState.OutputRoot=$taskState.ProfileRoot+'-results'
 $taskStage='snapshot_custody'
 Hold-Pr9ExistingSnapshot $taskRoster $taskPreparation $taskSid
 foreach($taskPath in @('C:\Python314','C:\Python314\DLLs','C:\Python314\Lib','C:\Python314\Lib\asyncio','C:\Users\s-a-balashov\.grok\bin')){
  $taskNode=Open-Pr9GrokProfileHeldNode $taskState $taskPath
  if(($taskNode.Info.Attributes -band 0x10) -eq 0){throw 'runtime parent directory'}
 }
 Hold-Pr9PreparationRuntime 'C:\Python314\python.exe' 106208 '4942b86a6597e5aee0128daa00050ed79bc21f6e709a78eb19cbfeb0c2f39ac9'
 Hold-Pr9PreparationRuntime 'C:\Python314\Lib\asyncio\windows_utils.py' 5651 '2af1aaa042e4a0ab1d3c06db7aa8fd8b288ab280f5dbee066a4cc3274459bd30'
 Hold-Pr9PreparationRuntime 'C:\Python314\DLLs\_overlapped.pyd' 58080 '1d7028683e6ec50c159139238f90a6c8431ece139a4764900ca11c941ba05d46'
 Hold-Pr9PreparationRuntime 'C:\Users\s-a-balashov\.grok\bin\grok.exe' 172906128 '86c6c766b7961597c2a327f77e43a7b73cbc44f5cee9da6dd74ba73b45ae8b68'
 if($taskReview){
  $taskAuth=@($taskState.Destinations|Where-Object {$_.Node.Path -ceq ([IO.Path]::Combine($taskState.ProfileRoot,'auth.json'))})
  if($taskAuth.Count -ne 1){throw 'credential identity'}
  $taskPrivateAuth=Read-Pr9GrokHeldSmallBytes -Stream $taskAuth[0].Stream -Length $taskAuth[0].Node.Info.Size -Maximum 65536 -Clock $taskClock
  try{[void](Get-Pr9GrokCredentialExpiry $taskPrivateAuth)}finally{[Array]::Clear($taskPrivateAuth,0,$taskPrivateAuth.Length)}
 }
 $taskDurableAdmitted=$true
 $taskAdmission=[ordered]@{scope='one_fixed_configured_review_phase';mode=$Mode;source_commit='605eb02733fe256ad5ef14f358eaa81ee1a0ae44';preparation_sha256=$PreparationSha;preflight_sha256=$PreflightSha;deadline_tick_ms=$taskDeadline;model_forms_reservation_bytes=5242880;review_permitted_by_phase=$taskReview;model_or_whole_chain_accepted=$false}
 $taskAdmitWrite=Write-Pr9PreparationPublic ($taskNamePrefix+'-admission.original.json') ([Text.Encoding]::UTF8.GetBytes(($taskAdmission|ConvertTo-Json -Depth 5 -Compress)+[char]10)) 8192
 if(-not $taskAdmitWrite.complete){throw 'admission persistence'}
 if($taskReview){
  $taskStage='new_model_output_root'
  $taskNewRootAttempted=$true
  [Pr9ReadOnlyGrokNativeV1]::MakePrivateDirectory('C:\Users\s-a-balashov\.gm1',$taskSid)
  $taskNewRootCreated=$true
  $taskModelNodes.Add((Open-Pr9ReadOnlyGrokNode 'C:\Users\s-a-balashov\.gm1'))
 }
 $taskInvocation=New-Pr9ReadOnlyModelInvocation -DeadlineTickMs $taskDeadline -Mode $Mode
 $taskLiteral=[ordered]@{executable=$taskInvocation.Executable;arguments=$taskInvocation.Arguments;source_pins=$taskInvocation.SourcePins;mode=$Mode;deadline_tick_ms=$taskDeadline}
 $taskLiteralWrite=Write-Pr9PreparationPublic ($taskNamePrefix+'-literal.original.json') ([Text.Encoding]::UTF8.GetBytes(($taskLiteral|ConvertTo-Json -Depth 6 -Compress)+[char]10)) 32768
 if(-not $taskLiteralWrite.complete){throw 'literal persistence'}
 $taskTokenNow=Get-Pr9ReadOnlyGrokPrimaryIdentity
 if($taskTokenNow.UserSid -cne $taskSid){throw 'primary identity drift'}
 Assert-Pr9GrokPreparationClock $taskClock
 $taskStage='fixed_controller'
 $PSNativeCommandArgumentPassing='Standard';$PSNativeCommandUseErrorActionPreference=$false
 $taskReply=@(& $taskInvocation.Executable @($taskInvocation.Arguments) 2>&1)
 $taskControllerExit=$LASTEXITCODE
 $taskReplyText=$taskReply -join [string][char]10
 if([Text.Encoding]::UTF8.GetByteCount($taskReplyText) -gt 8192){throw 'controller result ceiling'}
 try{$taskResult=$taskReplyText|ConvertFrom-Json -DateKind String}
 catch{$taskControllerUnparsed=[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($taskReplyText));Add-Pr9PreparationCause 'controller_parse' $_.Exception}
 $taskControllerWrite=Write-Pr9PreparationPublic ($taskNamePrefix+'-controller.original.json') ([Text.Encoding]::UTF8.GetBytes($taskReplyText+[char]10)) 16384
 if($null -eq $taskResult -or -not $taskControllerWrite.complete){throw 'controller persistence or shape'}
 $taskExpectedScope=$(if($taskReview){'model_capture_only'}elseif($taskDiagnostic){'readonly_route_diagnostic_only'}else{'readonly_route_preflight_only'})
 if($taskResult.scope -cne $taskExpectedScope -or $taskResult.mode -cne $Mode -or $taskResult.source_commit -cne '605eb02733fe256ad5ef14f358eaa81ee1a0ae44' -or $taskResult.independent_verdict_accepted -or $taskResult.effective_configuration_accepted){throw 'controller scope'}
 if($taskReview -and $null -ne $taskResult.capture){$taskStage='seal_model_raw';Seal-Pr9ModelRaw;$taskRawSealed=$true}
 $taskStage='post_comparison'
 [void](Test-Pr9ClosedGrokProfile $taskState $taskSid $taskClock)
 Test-Pr9ModelOriginals
 $taskPostChecksComplete=$true
 if($taskControllerExit -ne 0 -or -not $taskResult.complete -or (-not $taskDiagnostic -and -not $taskResult.preflight_complete)){throw 'fixed phase refused'}
 if($taskDiagnostic -and $taskResult.preflight_complete){throw 'diagnostic claimed preflight'}
 if($taskReview -and (-not $taskRawSealed -or -not $taskResult.capture.complete -or $null -eq $taskResult.response_checks)){throw 'review capture unavailable'}
 if(-not $taskReview -and ($taskResult.grok_performed -or $null -ne $taskResult.capture)){throw 'preflight crossed into model'}
 $taskFinished=$true
}catch{
 $taskFailure=$_.Exception
 if($null -ne $taskState){foreach($taskCause in $taskState.Causes){Add-Pr9PreparationCause $taskCause.code $taskCause.failure}}
 Add-Pr9PreparationCause $taskStage $taskFailure
}finally{
 foreach($taskItem in $taskRuntime){Close-Pr9PreparationResource 'runtime_stream_close' $taskItem.Stream}
 foreach($taskWriter in $taskModelWriters){Close-Pr9PreparationResource 'model_writer_close' $taskWriter}
 for($taskI=$taskModelNodes.Count-1;$taskI -ge 0;$taskI--){Close-Pr9PreparationResource 'model_custody_close' $taskModelNodes[$taskI].Handle}
 if($null -ne $taskState){
  try{Close-Pr9ClosedGrokProfile $taskState}catch{Add-Pr9PreparationCause 'profile_outer_close' $_.Exception}
  foreach($taskCause in $taskState.Causes){Add-Pr9PreparationCause $taskCause.code $taskCause.failure}
  if($taskState.CauseOverflow){$taskCauseState.Overflow=$true}
 }
 foreach($taskStream in $taskSources){Close-Pr9PreparationResource 'public_source_close' $taskStream}
}
$taskLate=[Environment]::TickCount64 -ge $taskDeadline
$taskReceipt=[ordered]@{
 scope='configured_review_phase_collection_only';mode=$Mode;attempt=$Attempt;post_comparison_complete=$taskPostChecksComplete;source_commit='605eb02733fe256ad5ef14f358eaa81ee1a0ae44'
 complete=($taskFinished -and -not $taskLate -and -not $taskCauses.Count -and -not $taskCauseState.Overflow)
 preparation_sha256=$PreparationSha;preflight_sha256=$PreflightSha;returned_controller=$taskResult
 controller_exit_code=$taskControllerExit;controller_unparsed_base64=$taskControllerUnparsed
 literal_write=$taskLiteralWrite;controller_write=$taskControllerWrite
 deadline_tick_ms=$taskDeadline;deadline_exceeded=$taskLate;phase=$taskStage
 new_private_root_attempted=$taskNewRootAttempted;new_private_root_created=$taskNewRootCreated;private_model_raw_sealed=$taskRawSealed
 primary_code=$(if($taskCauses.Count){$taskCauses[0].code}else{$null})
 secondary_codes=@($taskCauses|Select-Object -Skip 1|ForEach-Object {$_.code});cause_overflow=$taskCauseState.Overflow
 initiating_numeric_failure=(Get-Pr9ModelNumericFailure $(if($taskCauses.Count){$taskCauses[0].failure}else{$null}))
 private_scalar_values_or_hashes_emitted=$false;schema_identifier_disclosure_permitted=$taskDiagnostic;independent_verdict_accepted=$false;whole_chain_accepted=$false
}
$taskBodyRaw=[Text.Encoding]::UTF8.GetBytes(($taskReceipt|ConvertTo-Json -Depth 12 -Compress)+[char]10)
$taskBodyCount=$taskCauses.Count
$taskBodyBound=($taskBodyRaw.Length -le 14336)
if($taskDurableAdmitted -and $taskBodyBound){$taskReceiptWrite=Write-Pr9PreparationPublic ($taskNamePrefix+'-receipt.original.json') $taskBodyRaw 14336}
$taskOuter=[ordered]@{scope='configured_review_phase_external_witness_required';mode=$Mode;complete=$false;receipt_bytes=$taskBodyRaw.Length;receipt_sha256=$null;receipt_write=$taskReceiptWrite;fallback_public_receipt=$null;delivery_codes=@($taskCauses|Select-Object -Skip $taskBodyCount|ForEach-Object {$_.code});body_bound=$taskBodyBound;deadline_exceeded=([Environment]::TickCount64 -ge $taskDeadline);independent_verdict_accepted=$false}
if($taskBodyBound){
 $taskOuter.receipt_sha256=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskBodyRaw)).ToLowerInvariant()
 if($null -eq $taskReceiptWrite -or -not $taskReceiptWrite.complete){$taskOuter.fallback_public_receipt=$taskReceipt}
}
$taskOuter.complete=($taskReceipt.complete -and $null -ne $taskReceiptWrite -and $taskReceiptWrite.complete -and -not $taskOuter.deadline_exceeded -and -not $taskCauses.Count)
$taskOuterJson=$taskOuter|ConvertTo-Json -Depth 20 -Compress
if([Text.Encoding]::UTF8.GetByteCount($taskOuterJson) -gt 16382){Write-Output '{"scope":"configured_review_outer_refused","complete":false}';exit 1}
Write-Output $taskOuterJson
if(-not $taskOuter.complete){exit 1}
exit 0
