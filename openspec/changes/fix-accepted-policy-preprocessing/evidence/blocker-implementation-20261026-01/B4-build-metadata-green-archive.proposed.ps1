$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression
$taskBase=Join-Path (Get-Location) 'openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskFiles=@('buildmeta-green-command.original.ps1','prep-buildmeta-green-01-admission.original.json','buildmeta-green-materializer-source.original.py','buildmeta-green-test-source.original.py','buildmeta-green-runner-source.original.py','buildmeta-green-outer-tool.original.json','prep-buildmeta-green-01/stdout.original','prep-buildmeta-green-01/stderr.original','prep-buildmeta-green-01/result.original.json')
$taskArchiveName='B4-build-metadata-green-originals.zip'
$taskRows=@()
$taskInputBytes=0
foreach($taskName in $taskFiles){
 $taskFile=Get-Item -LiteralPath (Join-Path $taskBase $taskName)
 if($taskFile.Length -gt 1048576){throw 'archive member cap'}
 $taskInputBytes+=$taskFile.Length
 $taskRows+=@{member=$taskName;size_bytes=$taskFile.Length;sha256=(Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$taskMaximum=4194304
if($taskInputBytes+65536*($taskFiles.Count+1) -gt $taskMaximum){throw 'archive prewrite bound including overhead'}
$taskFileStream=[IO.File]::Open((Join-Path $taskBase $taskArchiveName),'CreateNew','Write','Read')
try {
 $taskZip=[IO.Compression.ZipArchive]::new($taskFileStream,[IO.Compression.ZipArchiveMode]::Create,$true)
 try{
  foreach($taskName in $taskFiles){
   $taskEntry=$taskZip.CreateEntry($taskName,[IO.Compression.CompressionLevel]::NoCompression)
   $taskInput=[IO.File]::Open((Join-Path $taskBase $taskName),'Open','Read','Read')
   try{
    $taskOutput=$taskEntry.Open()
    try{$taskInput.CopyTo($taskOutput,65536)}finally{$taskOutput.Dispose()}
   }finally{$taskInput.Dispose()}
  }
 }finally{$taskZip.Dispose()}
 if($taskFileStream.Length -gt $taskMaximum){throw 'archive exceeded prewrite bound'}
 $taskFileStream.Flush($true)
}finally{$taskFileStream.Dispose()}
$taskArchive=Get-Item -LiteralPath (Join-Path $taskBase $taskArchiveName)
$taskManifest=@{schema_version=1;archive=$taskArchiveName;size_bytes=$taskArchive.Length;sha256=(Get-FileHash $taskArchive.FullName -Algorithm SHA256).Hash.ToLowerInvariant();original_files_preserved=$true;members=$taskRows}
$taskManifestRaw=[Text.Encoding]::UTF8.GetBytes(($taskManifest|ConvertTo-Json -Depth 6 -Compress)+"`n")
if($taskManifestRaw.Length -gt 16384){throw 'manifest prewrite cap'}
$taskManifestStream=[IO.File]::Open(($taskArchive.FullName -replace '\.zip$','.manifest.json'),'CreateNew','Write','Read')
try{$taskManifestStream.Write($taskManifestRaw,0,$taskManifestRaw.Length);$taskManifestStream.Flush($true)}finally{$taskManifestStream.Dispose()}
$taskManifest|Select-Object archive,size_bytes,sha256|ConvertTo-Json -Compress

