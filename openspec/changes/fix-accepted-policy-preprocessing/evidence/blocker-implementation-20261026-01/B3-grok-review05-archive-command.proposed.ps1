param(
 [Parameter(Mandatory)][ValidateSet('model05')][string]$Bundle,
 [Parameter(Mandatory)][string]$LinuxGuardJson
)
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$taskRoot='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
$taskBase=Join-Path $taskRoot 'openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskClock=[Diagnostics.Stopwatch]::StartNew();$taskDeadline=[Environment]::TickCount64+180000
$taskCauses=[Collections.Generic.List[object]]::new(32);$taskCauseState=@{Overflow=$false}
$taskHeld=[Collections.Generic.List[object]]::new(34)
$taskRows=[Collections.Generic.List[object]]::new(32);$taskEntries=[Collections.Generic.List[object]]::new(32)
$taskStage='entry';$taskComplete=$false;$taskBoundary=$null;$taskManifest=$null
$taskZipFile=$null;$taskZip=$null;$taskReadZip=$null;$taskMemory=$null;$taskSourceGuard=$null
$taskZipFacts=[ordered]@{attempted=$false;created=$false;write_extent_unknown=$false;observed_bytes=$null;container_close_completed=$false;fsync_attempted=$false;fsync_completed=$false;file_close_completed=$false;readback_complete=$false}
$taskManifestFacts=[ordered]@{attempted=$false;created=$false;written_prefix_bytes=0;write_extent_unknown=$false;fsync_attempted=$false;fsync_completed=$false;close_completed=$false}
function Add-Pr9ArchiveCause {
 param([string]$Code,[Exception]$Failure)
 foreach($taskPrior in $taskCauses){if([Object]::ReferenceEquals($taskPrior.failure,$Failure)){return}}
 if($taskCauses.Count -ge 32){$taskCauseState.Overflow=$true;return}
 $taskCauses.Add([pscustomobject]@{code=$Code;failure=$Failure})
}
function Close-Pr9ArchiveResource {
 param([string]$Code,$Resource)
 if($null -ne $Resource){try{$Resource.Dispose();return $true}catch{Add-Pr9ArchiveCause $Code $_.Exception;return $false}}
 return $true
}
function SyncAndClose-Pr9ArchiveFile {
 param($File,$Facts,[string]$CloseField,[string]$Code)
 if($null -eq $File){return}
 $Facts.fsync_attempted=$true
 try{$File.Flush($true);$Facts.fsync_completed=$true}
 catch{Add-Pr9ArchiveCause ($Code+'_fsync') $_.Exception}
 $Facts[$CloseField]=Close-Pr9ArchiveResource ($Code+'_close') $File
}
function Assert-Pr9ArchiveWindow {
 if([Environment]::TickCount64 -ge $taskDeadline-5000){throw 'archive operation deadline'}
 if($taskCauses.Count -or $taskCauseState.Overflow){throw 'archive retained cause'}
}
function Get-Pr9ArchiveRoster {
 param([string]$Name)
 if($Name -cne 'model05'){throw 'fixed model archive bundle'}
 return [pscustomobject]@{Prefix='grok-model-review05-01';Names=[string[]]@(
  'B3-B4-current-source-grok-prompt-03.original.txt',
  'B3-B4-current-source-grok-prompt-build-03.proposed.ps1',
  'B3-B4-current-source-grok-prompt-build-03-tool-return.original.json',
  'grok-readonly-preparation-05.original.json',
  'grok-model-preflight05-01-receipt.original.json',
  'B3-grok-readonly-roster-05.proposed.json',
  'B3-grok-preflight05-outcome.md',
  'B3-failure-frame-test-recipe.proposed.md',
  'grok_windows_model_capture_v1.proposed.py',
  'grok_readonly_model_data_v1.proposed.ps1',
  'grok_readonly_model_invocation_v1.proposed.ps1',
  'B3-grok-model-caller-disposition.proposed.md',
  'grok_readonly_model_driver_v1.proposed.py',
  'B3-grok-model-phase-command.proposed.ps1',
  'grok-model-review05-01-admission.original.json',
  'grok-model-review05-01-literal.original.json',
  'grok-model-review05-01-controller.original.json',
  'grok-model-review05-01-receipt.original.json',
  'grok-model-review05-01-outer-tool.original.json',
  'grok-model-phase-command-review05.original.ps1',
  'B3-grok-model-capacity-supplement.proposed.md',
  'B3-grok-review05-execution-admission.proposed.md',
  'B3-grok-review05-outcome-review.md',
  'B3-grok-review05-checkpoint.md',
  'grok-model-review05-01-witness.derived.json',
  'grok-model-review05-01-preservation.derived.json',
  'B3-grok-review05-archive-command.proposed.ps1',
  'B3-failure-frame-grok-prompt-build.proposed.ps1',
  'B3-failure-frame-grok-prompt-build-refused-tool-return.original.json',
  'B3-failure-frame-grok-prompt-build-02.proposed.ps1',
  'B3-failure-frame-grok-prompt-build-02-tool-return.original.json',
  'B3-failure-frame-source-grok-prompt-02.original.txt'
 );Limits=[long[]]@(131072,12288,8192,32768,16384,8192,32768,8192,28672,12288,12288,4096,28672,28672,8192,32768,16384,16384,65536,28672,32768,32768,32768,32768,32768,32768,32768,8192,4096,8192,4096,102400)}
}
function Get-Pr9ArchiveQuote {
 param([string[]]$Names,[long[]]$Sizes,[long[]]$Limits)
 if($Names.Count -ne 32 -or $Sizes.Count -ne 32 -or $Limits.Count -ne 32 -or @($Names|Select-Object -Unique).Count -ne 32){throw 'model archive member census'}
 [long]$sum=0
 for($i=0;$i -lt 32;$i++){
  if($Names[$i] -cnotmatch '\A[A-Za-z0-9_.-]{1,128}\z' -or $Limits[$i] -lt 0 -or $Limits[$i] -gt 131072 -or $Sizes[$i] -lt 0 -or $Sizes[$i] -gt $Limits[$i]){throw 'model archive member extent/name'}
  $sum+=$Sizes[$i]
 }
 if($sum -gt 888832){throw 'model aggregate input cap'}
 [long]$quote=$sum+1024*33
 if($quote -gt 1572864){throw 'whole model archive prewrite bound'}
 return $quote
}
function Read-Pr9HeldArchiveBytes {
 param([string]$Name,[int]$Maximum)
 Assert-Pr9ArchiveWindow
 $path=Join-Path $taskBase $Name
 $info=Get-Item -LiteralPath $path
 if($info.PSIsContainer -or ($info.Attributes -band 0x400)){throw 'physical public regular source required'}
 $stream=[IO.File]::Open($path,'Open','Read','Read');$taskHeld.Add($stream)
 if($stream.Length -lt 0 -or $stream.Length -gt $Maximum){throw 'archive source bound'}
 $bytes=[byte[]]::new([int]$stream.Length);$offset=0
 while($offset -lt $bytes.Length){
  Assert-Pr9ArchiveWindow
  $n=$stream.Read($bytes,$offset,$bytes.Length-$offset)
  if($n -le 0){throw 'archive source shrink'};$offset+=$n
 }
 if($stream.ReadByte() -ne -1){throw 'archive source growth'}
 return ,$bytes
}
function Get-Pr9ArchiveCrc32 {
 param([byte[]]$Bytes)
 if($Bytes.Length -gt 131072){throw 'CRC source bound'}
 [uint32]$crc=4294967295
 foreach($byte in $Bytes){$crc=($crc -shr 8) -bxor $taskCrcTable[($crc -bxor $byte) -band 255]}
 return [uint32]($crc -bxor [uint32]4294967295)
}
function Get-Pr9ArchiveSha {
 param([byte[]]$Bytes)
 return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($Bytes)).ToLowerInvariant()
}
try{
 if((Get-Location).Path -cne $taskRoot -or $PSVersionTable.PSVersion.ToString() -cne '7.5.5' -or
    [Runtime.InteropServices.RuntimeInformation]::FrameworkDescription -cne '.NET 9.0.14'){throw 'qualified archive runtime'}
 $taskRoster=Get-Pr9ArchiveRoster $Bundle
 foreach($taskSuffix in @('-originals.zip','-originals.manifest.json','-archive-actual.original.json')){
  if(Test-Path -LiteralPath (Join-Path $taskBase ($taskRoster.Prefix+$taskSuffix))){throw 'archive namespace consumed'}
 }
 $taskStage='fresh_boundary'
 $taskGuardBytes=Read-Pr9HeldArchiveBytes 'grok_readonly_preparation_guard_v1.proposed.ps1' 4692
 if($taskGuardBytes.Length -ne 4692 -or (Get-Pr9ArchiveSha $taskGuardBytes) -cne '02054a54d2be0ae8615b66b1d820abd037d1f0883a13e251196403e253c6f8d8'){throw 'archive guard source'}
 . ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskGuardBytes)))
 $taskBoundary=Assert-Pr9ReadOnlyPreparationBoundary $LinuxGuardJson $taskClock
 $taskCrcTable=[uint32[]]::new(256)
 for($i=0;$i -lt 256;$i++){[uint32]$c=$i;for($j=0;$j -lt 8;$j++){if($c -band 1){$c=($c -shr 1) -bxor [uint32]3988292384}else{$c=$c -shr 1}};$taskCrcTable[$i]=$c}
 $taskStage='hold_all_originals'
 for($i=0;$i -lt 32;$i++){
  $taskName=$taskRoster.Names[$i]
  $taskData=Read-Pr9HeldArchiveBytes $taskName $taskRoster.Limits[$i]
  $taskRows.Add([pscustomobject]@{name=$taskName;bytes=$taskData.Length;sha256=(Get-Pr9ArchiveSha $taskData);crc32=(Get-Pr9ArchiveCrc32 $taskData);raw=$taskData})
 }
 $taskQuote=Get-Pr9ArchiveQuote $taskRoster.Names @($taskRows|ForEach-Object{[long]$_.bytes}) $taskRoster.Limits
 Assert-Pr9ArchiveWindow
 $taskStage='create_zip'
 $taskZipFacts.attempted=$true
 $taskZipFile=[IO.File]::Open((Join-Path $taskBase ($taskRoster.Prefix+'-originals.zip')),'CreateNew','Write','Read')
 $taskZipFacts.created=$true;$taskZipFacts.write_extent_unknown=$true
 $taskZip=[IO.Compression.ZipArchive]::new($taskZipFile,[IO.Compression.ZipArchiveMode]::Create,$true)
 for($i=0;$i -lt 32;$i++){
  Assert-Pr9ArchiveWindow
  $taskStage='write_entry';$taskEntry=$null
  $taskEntryFacts=[ordered]@{index=$i;attempted=$true;opened=$false;written_prefix_bytes=0;write_extent_unknown=$false;close_completed=$false}
  $taskEntries.Add($taskEntryFacts)
  try{
   $taskEntry=$taskZip.CreateEntry($taskRows[$i].name,[IO.Compression.CompressionLevel]::NoCompression).Open()
   $taskEntryFacts.opened=$true;$taskEntryFacts.write_extent_unknown=$true
   $taskEntry.Write($taskRows[$i].raw,0,$taskRows[$i].bytes)
   $taskEntryFacts.written_prefix_bytes=$taskRows[$i].bytes;$taskEntryFacts.write_extent_unknown=$false
  }catch{Add-Pr9ArchiveCause 'entry_write' $_.Exception;throw}
  finally{$taskEntryFacts.close_completed=Close-Pr9ArchiveResource 'entry_close' $taskEntry}
 }
 $taskStage='finish_zip'
 $taskClosingZip=$taskZip;$taskZip=$null
 $taskZipFacts.container_close_completed=Close-Pr9ArchiveResource 'zip_container_close' $taskClosingZip
 Assert-Pr9ArchiveWindow
 $taskZipFacts.observed_bytes=$taskZipFile.Length
 if($taskZipFacts.observed_bytes -gt $taskQuote -or $taskZipFacts.observed_bytes -gt 1572864){throw 'archive extent proof differs'}
 $taskZipFacts.write_extent_unknown=$false
 $taskClosingFile=$taskZipFile;$taskZipFile=$null
 SyncAndClose-Pr9ArchiveFile $taskClosingFile $taskZipFacts 'file_close_completed' 'zip_file'
 Assert-Pr9ArchiveWindow
 $taskStage='readback_zip'
 $taskZipBytes=Read-Pr9HeldArchiveBytes ($taskRoster.Prefix+'-originals.zip') 1572864
 if($taskZipBytes.Length -ne $taskZipFacts.observed_bytes){throw 'archive changed before readback'}
 $taskMemory=[IO.MemoryStream]::new($taskZipBytes,$false)
 $taskReadZip=[IO.Compression.ZipArchive]::new($taskMemory,[IO.Compression.ZipArchiveMode]::Read,$true)
 if($taskReadZip.Entries.Count -ne 32){throw 'readback entry census'}
 for($i=0;$i -lt 32;$i++){
  Assert-Pr9ArchiveWindow
  $taskEntry=$taskReadZip.Entries[$i];$taskReadStream=$null
  if($taskEntry.FullName -cne $taskRows[$i].name -or $taskEntry.Length -ne $taskRows[$i].bytes -or
     $taskEntry.CompressedLength -ne $taskEntry.Length -or $taskEntry.Crc32 -ne $taskRows[$i].crc32){throw 'readback entry identity/CRC'}
  try{
   $taskReadStream=$taskEntry.Open();$taskData=[byte[]]::new($taskRows[$i].bytes);$taskOffset=0
   while($taskOffset -lt $taskData.Length){
    Assert-Pr9ArchiveWindow
    $taskN=$taskReadStream.Read($taskData,$taskOffset,$taskData.Length-$taskOffset)
    if($taskN -le 0){throw 'readback entry shrink'};$taskOffset+=$taskN
   }
   if($taskReadStream.ReadByte() -ne -1 -or (Get-Pr9ArchiveSha $taskData) -cne $taskRows[$i].sha256 -or
      (Get-Pr9ArchiveCrc32 $taskData) -ne $taskRows[$i].crc32){throw 'readback data differs'}
  }catch{Add-Pr9ArchiveCause 'readback_entry' $_.Exception;throw}
  finally{[void](Close-Pr9ArchiveResource 'readback_entry_close' $taskReadStream)}
 }
 $taskZipFacts.readback_complete=$true
 $taskStage='manifest'
 $taskManifest=[ordered]@{scope='lifetime_public_model_review_originals_archived_only';bundle=$Bundle;archive=($taskRoster.Prefix+'-originals.zip');bytes=$taskZipBytes.Length;sha256=(Get-Pr9ArchiveSha $taskZipBytes);prewrite_quote_bytes=$taskQuote;members=@($taskRows|ForEach-Object{[ordered]@{name=$_.name;bytes=$_.bytes;sha256=$_.sha256;crc32=$_.crc32}});originals_preserved=$true;product_acceptance=$false}
 $taskManifestBytes=[Text.Encoding]::UTF8.GetBytes(($taskManifest|ConvertTo-Json -Depth 5 -Compress)+[char]10)
 if($taskManifestBytes.Length -gt 16384){throw 'manifest prewrite bound'}
 Assert-Pr9ArchiveWindow
 $taskManifestFile=$null;$taskManifestFacts.attempted=$true
 try{
  $taskManifestFile=[IO.File]::Open((Join-Path $taskBase ($taskRoster.Prefix+'-originals.manifest.json')),'CreateNew','Write','Read')
  $taskManifestFacts.created=$true;$taskManifestFacts.write_extent_unknown=$true
  $taskManifestFile.Write($taskManifestBytes,0,$taskManifestBytes.Length)
  $taskManifestFacts.written_prefix_bytes=$taskManifestBytes.Length;$taskManifestFacts.write_extent_unknown=$false
 }catch{Add-Pr9ArchiveCause 'manifest_write' $_.Exception;throw}
 finally{SyncAndClose-Pr9ArchiveFile $taskManifestFile $taskManifestFacts 'close_completed' 'manifest'}
 Assert-Pr9ArchiveWindow
 $taskComplete=$true
}catch{Add-Pr9ArchiveCause $taskStage $_.Exception}
finally{
 if($null -ne $taskZip){$taskZipFacts.container_close_completed=Close-Pr9ArchiveResource 'zip_container_close' $taskZip}
 if($null -ne $taskZipFile){
  try{$taskZipFacts.observed_bytes=$taskZipFile.Length}catch{Add-Pr9ArchiveCause 'zip_extent_observation' $_.Exception}
  SyncAndClose-Pr9ArchiveFile $taskZipFile $taskZipFacts 'file_close_completed' 'zip_file'
 }
 [void](Close-Pr9ArchiveResource 'readback_container_close' $taskReadZip)
 [void](Close-Pr9ArchiveResource 'readback_memory_close' $taskMemory)
 for($i=$taskHeld.Count-1;$i -ge 0;$i--){[void](Close-Pr9ArchiveResource 'source_close' $taskHeld[$i])}
}
$taskLate=[Environment]::TickCount64 -ge $taskDeadline
$taskComplete=($taskComplete -and -not $taskLate -and -not $taskCauses.Count -and -not $taskCauseState.Overflow)
$taskTerminal=[ordered]@{scope='public_originals_archive_collection_only';bundle=$Bundle;complete=$taskComplete;phase=$taskStage;deadline_exceeded=$taskLate;zip=$taskZipFacts;entry_writes=@($taskEntries);manifest_write=$taskManifestFacts;manifest=$taskManifest;primary_code=$(if($taskCauses.Count){$taskCauses[0].code}else{$null});secondary_codes=@($taskCauses|Select-Object -Skip 1|ForEach-Object{$_.code});initiating_hresult=$(if($taskCauses.Count){$taskCauses[0].failure.HResult}else{$null});secondary_hresults=@($taskCauses|Select-Object -Skip 1|ForEach-Object{$_.failure.HResult});cause_overflow=$taskCauseState.Overflow;private_io_or_grok=$false;product_acceptance=$false}
$taskTerminalRaw=$taskTerminal|ConvertTo-Json -Depth 8 -Compress
if([Text.Encoding]::UTF8.GetByteCount($taskTerminalRaw) -gt 16382){Write-Output '{"scope":"public_archive_status_bound","complete":false}';exit 1}
Write-Output $taskTerminalRaw
if(-not $taskComplete){exit 1}
exit 0
