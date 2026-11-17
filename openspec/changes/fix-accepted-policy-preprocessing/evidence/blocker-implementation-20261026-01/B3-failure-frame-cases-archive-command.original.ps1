$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.IO.Compression
$taskBase=Join-Path (Get-Location) 'openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskFiles=@('temporary-failureframe-green-01/failureframe-cli-2s_xnzmj/capture.original.json','temporary-failureframe-green-01/failureframe-cli-2s_xnzmj/stderr.original','temporary-failureframe-green-01/failureframe-cli-2s_xnzmj/stdout.original','temporary-failureframe-green-01/failureframe-cli-awv3xgat/capture.original.json','temporary-failureframe-green-01/failureframe-cli-awv3xgat/stderr.original','temporary-failureframe-green-01/failureframe-cli-awv3xgat/stdout.original','temporary-failureframe-green-01/failureframe-cli-imk5610a/capture.original.json','temporary-failureframe-green-01/failureframe-cli-imk5610a/stderr.original','temporary-failureframe-green-01/failureframe-cli-imk5610a/stdout.original','temporary-failureframe-green-01/failureframe-cli-k9ykfyhw/capture.original.json','temporary-failureframe-green-01/failureframe-cli-k9ykfyhw/stderr.original','temporary-failureframe-green-01/failureframe-cli-k9ykfyhw/stdout.original','temporary-failureframe-green-01/failureframe-cli-lst86cgw/capture.original.json','temporary-failureframe-green-01/failureframe-cli-lst86cgw/stderr.original','temporary-failureframe-green-01/failureframe-cli-lst86cgw/stdout.original','temporary-failureframe-green-01/failureframe-cli-ywlfrxoo/capture.original.json','temporary-failureframe-green-01/failureframe-cli-ywlfrxoo/stderr.original','temporary-failureframe-green-01/failureframe-cli-ywlfrxoo/stdout.original','temporary-failureframe-green-01/failureframe-geometry-mm_1vbww/frame.original.json')
$taskArchiveName='B3-failure-frame-cases-originals.zip'
$taskRows=@()
$taskInputBytes=0
foreach($taskName in $taskFiles){
 $taskFile=Get-Item -LiteralPath (Join-Path $taskBase $taskName)
 if($taskFile.Length -gt 1048576){throw 'archive member cap'}
 $taskInputBytes+=$taskFile.Length
 $taskRows+=@{member=$taskName;size_bytes=$taskFile.Length;sha256=(Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$taskMaximum=16777216
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
