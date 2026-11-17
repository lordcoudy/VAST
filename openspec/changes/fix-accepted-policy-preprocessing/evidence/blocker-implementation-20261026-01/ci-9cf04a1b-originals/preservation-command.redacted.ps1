# Evidence copy of the executed preservation script. Only the temporary download URL is replaced.
# This file requires a fresh authorized URL and is not a reusable execution admission.

$ErrorActionPreference='Stop'
$taskBase='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
$taskPhase='ci-9cf-preservation-01'
foreach($taskFreshName in @('ci-9cf04a1b-originals','prep-ci-9cf-preservation-01-admission.original.json')){if(Test-Path -LiteralPath (Join-Path $taskBase $taskFreshName)){throw 'CI preservation namespace consumed'}}
$taskLinux=@'
{"chunk_id":"41452f","wall_time_seconds":1.1521246,"exit_code":0,"original_token_count":142,"output":"{\"allocation_units\":{\"c\":4096,\"e\":4096,\"temporary\":4096},\"boot_id\":\"df4955d9-4762-42b4-a55b-0106ba3786f8\",\"free_bytes\":{\"c\":240963866624,\"e\":257020780544,\"temporary\":880666419200},\"root_device\":\"/dev/sdf\",\"root_mounts\":[[\"/dev/sdf\",\"/\",\"ext4\",\"rw,relatime,discard,errors=remount-ro,data=ordered\",\"0\",\"0\"]],\"root_uuid\":\"c3d3247e-154c-43c0-a9fe-2b91d6db7666\",\"temporary_same_device_as_root\":true,\"vm_memory_bytes\":{\"MemTotal\":25196363776,\"SwapTotal\":6442450944},\"wslconfig_sha256\":\"6efea9e209212784c22240a6019c17cee3bd31011840250c76c3bb31e2c7eea1\",\"wslconfig_size\":21}\n"}
'@ | ConvertFrom-Json
$taskHead=& git -c gc.auto=0 -c maintenance.auto=false rev-parse HEAD
if($LASTEXITCODE -ne 0 -or $taskHead -ne 'c1ec2a111edcfc5a8157e04d3475029c61fc8fbe'){throw 'reviewed product head differs'}
& git -c gc.auto=0 -c maintenance.auto=false diff --quiet HEAD -- tests/fixtures/accepted_policy_fixture_compiler_admission_v1.py tests/fixtures/accepted_policy_fixture_compiler_v1.py tests/fixtures/accepted_policy_original_custody_fixture_v1.py tests/fixtures/accepted_policy_physical_fixture_v1.py tests/fixtures/accepted_policy_controlled_compiler_v1.py tests/test_accepted_policy_fixture_preflight_v1.py tests/test_accepted_policy_fixture_compiler_admission_v1.py
if($LASTEXITCODE -ne 0){throw 'reviewed product bytes differ'}
$taskRunner=Join-Path $taskBase 'preparatory_checks.py'
if((Get-FileHash -LiteralPath $taskRunner -Algorithm SHA256).Hash -ne '64458f6bbfd4ea913262cde8154a001e05999fa1ff33de328907a0c420ac0a2a'){throw 'reviewed runner differs'}

$taskQuantityTest='tests/test_accepted_policy_fixture_quantity_v1.py'
$taskQuantityTestSha='546af4ff73d86bbfccce707fc7d0ec58633eb0ac76430353c55054c27b2b998d'
$taskNative='tests/fixtures/accepted_policy_native_fixture_v2.py'
$taskNativeSha='ee829f4156f064e439f085bcc18fc96bec446a4ecba9df64b2f38836cdccb119'
$taskPhysical='tests/fixtures/accepted_policy_physical_fixture_v2.py'
$taskPhysicalSha='457df99000878f3b9741aff7aba3f9074759ae05d67a45b4c2874aa75c27b7e5'
if((Get-FileHash -LiteralPath $taskQuantityTest -Algorithm SHA256).Hash -ne $taskQuantityTestSha -or (Get-FileHash -LiteralPath $taskNative -Algorithm SHA256).Hash -ne $taskNativeSha -or (Get-FileHash -LiteralPath $taskPhysical -Algorithm SHA256).Hash -ne $taskPhysicalSha){throw 'reviewed quantity source bytes differ'}

$taskBindingTest='tests/test_accepted_policy_fixture_binding_bounds_v1.py'
$taskBindingTestSha='474875e54982db201557b67cb3424d4c32a399d0d5e6e6c1b64cb1d9714982b6'
if((Get-FileHash -LiteralPath $taskBindingTest -Algorithm SHA256).Hash -ne $taskBindingTestSha){throw 'reviewed binding test differs'}
$taskSidecarTest='tests/test_accepted_policy_fixture_sidecar_bounds_v1.py'
$taskSidecarTestSha='c02e21d7781fd72146f38d9db23b2f207a752aa4c682d5a3495a0d015f477f11'
if((Get-FileHash -LiteralPath $taskSidecarTest -Algorithm SHA256).Hash -ne $taskSidecarTestSha){throw 'reviewed sidecar test differs'}
$taskSidecarEdgesTest='tests/test_accepted_policy_fixture_sidecar_edges_v1.py'
$taskSidecarEdgesTestSha='53923d82fbb3edf399b4e80b29fd85caaa93c63522195546aa40953752dffacc'
if((Get-FileHash -LiteralPath $taskSidecarEdgesTest -Algorithm SHA256).Hash -ne $taskSidecarEdgesTestSha){throw 'reviewed sidecar edge test differs'}
$taskReaderTest='tests/test_accepted_policy_fixture_reader_bounds_v1.py'
$taskReaderTestSha='57db27d19e263c3dc2233a54a8e639b2b6be246e427d78c5a9640ed4e44aa25d'
$taskConsumer='tests/fixtures/accepted_policy_consumer_fixture_v2.py'
$taskConsumerSha='0597a2b55b7429d8bb04c0ffa87fc304a1ac232b6822810d8933e27c10683fd7'
$taskAssertions='tests/fixtures/accepted_policy_consumer_assertions_v1.py'
$taskAssertionsSha='7d9a5dae76383ac1c38502b714b21b36f2126e83b00e41e2e06d22a461f924a2'
$taskJournal='tests/fixtures/accepted_policy_guardian_journal_fixture_v1.py'
$taskJournalSha='5cffe02d773ac6eeb247015a1d83dc3d7848ce64c3cb119dc581864dc6f9dc4a'
if((Get-FileHash -LiteralPath $taskReaderTest -Algorithm SHA256).Hash -ne $taskReaderTestSha -or (Get-FileHash -LiteralPath $taskConsumer -Algorithm SHA256).Hash -ne $taskConsumerSha -or (Get-FileHash -LiteralPath $taskAssertions -Algorithm SHA256).Hash -ne $taskAssertionsSha -or (Get-FileHash -LiteralPath $taskJournal -Algorithm SHA256).Hash -ne $taskJournalSha){throw 'reviewed reader adapter source differs'}
$taskWriteFactsTest='tests/test_accepted_policy_fixture_sidecar_write_facts_v1.py'
$taskWriteFactsTestSha='a4b2eb3fde66073e93ec9990702612ec68b961a0c66441641489daa1160e3a74'
if((Get-FileHash -LiteralPath $taskWriteFactsTest -Algorithm SHA256).Hash -ne $taskWriteFactsTestSha){throw 'reviewed write-facts test differs'}
$taskHeaderTest='tests/test_accepted_policy_fixture_journal_header_v1.py'
$taskHeaderTestSha='ee262eae31a73e8adb2eb25b669d2443dea9454580c2ace05888c6acb591a1f6'
if((Get-FileHash -LiteralPath $taskHeaderTest -Algorithm SHA256).Hash -ne $taskHeaderTestSha){throw 'reviewed header test differs'}
$taskArtifactTest='tests/test_accepted_policy_fixture_artifact_reads_v1.py'
$taskArtifactTestSha='2fbe138736df76ed9c750f4db5a437a88b6bb72e0f06189f59d770e4cd6351f7'
if((Get-FileHash -LiteralPath $taskArtifactTest -Algorithm SHA256).Hash -ne $taskArtifactTestSha){throw 'reviewed artifact read test differs'}
$taskEnginePinTest='tests/test_accepted_policy_fixture_engine_pin_v2.py'
$taskEnginePinTestSha='ab69034bcb760f377827973c849121a4e2a9361037c09f97e918ff3fb1273037'
if((Get-FileHash -LiteralPath $taskEnginePinTest -Algorithm SHA256).Hash -ne $taskEnginePinTestSha){throw 'reviewed engine pin test differs'}
$taskFinalizerTest='tests/test_accepted_policy_fixture_finalizer_bounds_v2.py'
$taskFinalizerTestSha='78fa73de664ca4232a623264a961baf6b0dd39cc6092c6f1eb297031604f58c9'
if((Get-FileHash -LiteralPath $taskFinalizerTest -Algorithm SHA256).Hash -ne $taskFinalizerTestSha){throw 'reviewed finalizer test differs'}
$taskConsumerClockTest='tests/test_accepted_policy_fixture_consumer_deadline_v2.py'
$taskConsumerClockTestSha='a2f917b68c8e565737e4564f95787ead38669bcf54847b4cb2ac226c0200bff2'
$taskReaderOwner='tests/fixtures/accepted_policy_standalone_reader_fixture_v2.py'
$taskReaderOwnerSha='7fc7e536f4366fcc575240d1b81232bc8b9c3851bd13868c5d9981d40496507f'
if((Get-FileHash -LiteralPath $taskConsumerClockTest -Algorithm SHA256).Hash -ne $taskConsumerClockTestSha -or (Get-FileHash -LiteralPath $taskReaderOwner -Algorithm SHA256).Hash -ne $taskReaderOwnerSha){throw 'reviewed consumer clock sources differ'}
$taskExecutionTest='tests/test_accepted_policy_fixture_execution_arguments_v2.py'
$taskExecutionTestSha='92fd3d2f04ab2efb1ba735c2c0d592ac5507cc8ea510f81d5af5ceca91e04638'
$taskLiteralDriver='openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_production_fixture_v2.py'
$taskLiteralDriverSha='34d0a264d735209aa96ae281e47b938ce48d55e747769a6f40658a0cbedfeed6'
$taskAdmissionGate='tests/fixtures/accepted_policy_fixture_compiler_admission_v1.py'
$taskAdmissionGateSha='dea1b0fefc99e160cada5e9937412ad3d4489cb30783bb169db26505c6bb6610'
if((Get-FileHash -LiteralPath $taskExecutionTest -Algorithm SHA256).Hash -ne $taskExecutionTestSha -or (Get-FileHash -LiteralPath $taskLiteralDriver -Algorithm SHA256).Hash -ne $taskLiteralDriverSha -or (Get-FileHash -LiteralPath $taskAdmissionGate -Algorithm SHA256).Hash -ne $taskAdmissionGateSha){throw 'reviewed literal execution sources differ'}
$taskNegativeTest='tests/test_accepted_policy_fixture_refusal_arguments_v1.py'
$taskNegativeTestSha='b09e205085a8a2357bc40fe0c911a9e06243946152249b2dd7ed2f7ebad70cac'
$taskNegativeDriver='openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01/build_per_cell_minimum_refusal_v1.py'
$taskNegativeDriverSha='c5a09a16b8d430b95d42ec6bcb9f427333b5ffc391d14cb95f464559a231069e'
if((Get-FileHash -LiteralPath $taskNegativeTest -Algorithm SHA256).Hash -ne $taskNegativeTestSha -or (Get-FileHash -LiteralPath $taskNegativeDriver -Algorithm SHA256).Hash -ne $taskNegativeDriverSha){throw 'reviewed negative caller sources differ'}
$taskCleanupTest='tests/test_accepted_policy_fixture_preparation_cleanup_v2.py'
$taskCleanupTestSha='691f82c8668bda0b25a0d6f9a4ceeb820d7e757d4d1f623d4b415342ab1b699f'
if((Get-FileHash -LiteralPath $taskCleanupTest -Algorithm SHA256).Hash -ne $taskCleanupTestSha){throw 'reviewed socket-cleanup test differs'}
$taskReplyPreflightTest='tests/test_accepted_policy_fixture_reply_preflight_v2.py'
$taskReplyPreflightTestSha='367eb92c72f7a531c59a85f9e784502165d6538bfb606893aff8a57df876f4d2'
if((Get-FileHash -LiteralPath $taskReplyPreflightTest -Algorithm SHA256).Hash -ne $taskReplyPreflightTestSha){throw 'reviewed complete reply-map test differs'}
$taskProbeBindingTest='tests/test_accepted_policy_fixture_probe_binding_v2.py'
$taskProbeBindingTestSha='df0b70224ba06d11a3f7694bf1c5504afd2f7a50990e8d7a7a9d2b1ea2251a9c'
if((Get-FileHash -LiteralPath $taskProbeBindingTest -Algorithm SHA256).Hash -ne $taskProbeBindingTestSha){throw 'reviewed fixed probe roster source differs'}
$taskConfig='C:\Users\s-a-balashov\.wslconfig'
if((Get-Item -LiteralPath $taskConfig).Length -ne 21 -or (Get-FileHash -LiteralPath $taskConfig -Algorithm SHA256).Hash -ne '6efea9e209212784c22240a6019c17cee3bd31011840250c76c3bb31e2c7eea1'){throw 'VM configuration differs'}
$taskDistros=@(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss'|Get-ItemProperty|Where-Object DistributionName -eq 'Ubuntu')
$taskVhdBase='C:\Users\s-a-balashov\AppData\Local\wsl\{733a6524-960b-47be-ac8d-deaf948be3c7}'
if($taskDistros.Count -ne 1 -or $taskDistros[0].DefaultUid -ne 1000 -or $taskDistros[0].BasePath.TrimEnd('\') -ine $taskVhdBase){throw 'Ubuntu registry identity differs'}
$taskVhd=Get-Item -LiteralPath (Join-Path $taskVhdBase 'ext4.vhdx')
$taskVolumes=@(Get-Volume -DriveLetter C,E|Select-Object DriveLetter,SizeRemaining,Size,AllocationUnitSize)
$taskC=@($taskVolumes|Where-Object DriveLetter -eq 'C');$taskE=@($taskVolumes|Where-Object DriveLetter -eq 'E')
if($taskC.Count -ne 1 -or $taskE.Count -ne 1 -or $taskC[0].SizeRemaining -lt 128849018880 -or $taskE[0].SizeRemaining -lt 70866960384 -or @($taskVolumes|Where-Object { $_.AllocationUnitSize -le 0 -or $_.AllocationUnitSize -gt 4096 }).Count){throw 'Windows physical floors differ'}
$taskPages=@(Get-CimInstance Win32_PageFileUsage|Select-Object Name,AllocatedBaseSize,CurrentUsage,PeakUsage)
$taskPageSettings=@(Get-CimInstance Win32_PageFileSetting|Select-Object Name,InitialSize,MaximumSize)
if($taskPages.Count -ne 1 -or $taskPages[0].Name -ine 'E:\pagefile.sys' -or $taskPages[0].AllocatedBaseSize -gt 65536 -or $taskPageSettings.Count -ne 1 -or $taskPageSettings[0].Name -ine 'E:\pagefile.sys' -or $taskPageSettings[0].MaximumSize -ne 65536){throw 'pagefile geometry differs'}
$taskUsnC=@(& fsutil usn queryjournal C: 2>&1);$taskUsnCExit=$LASTEXITCODE
$taskUsnE=@(& fsutil usn queryjournal E: 2>&1);$taskUsnEExit=$LASTEXITCODE
if($taskUsnCExit -ne 0 -or ($taskUsnC -join "`n") -notmatch 'Maximum Size\s+: 0x0000000002000000' -or ($taskUsnC -join "`n") -notmatch 'Allocation Delta\s+: 0x0000000000800000' -or $taskUsnEExit -ne 1 -or ($taskUsnE -join "`n") -notmatch 'Error 1179'){throw 'USN geometry differs'}
$taskRecord=[ordered]@{schema_version=1;phase=$taskPhase;scope='CI original preservation, no test execution';artifact=@{id=12704774553;size_bytes=3278561;sha256='a5576129cb2fe37dab9ddfbcc7bfe5c8c25515bc4e4dcdb0e9dd2075c64607a6';head_revision='9cf04a1b22dcea6e24b0f1be33a2ce8b8ec395ff';workflow_run=40436076275;job=121964936115};observed_utc=[DateTime]::UtcNow.ToString('o');product_commit=$taskHead;quantity_test_sha256=$taskQuantityTestSha;binding_test_sha256=$taskBindingTestSha;sidecar_test_sha256=$taskSidecarTestSha;sidecar_edges_test_sha256=$taskSidecarEdgesTestSha;reader_test_sha256=$taskReaderTestSha;write_facts_test_sha256=$taskWriteFactsTestSha;header_test_sha256=$taskHeaderTestSha;artifact_test_sha256=$taskArtifactTestSha;engine_pin_test_sha256=$taskEnginePinTestSha;finalizer_test_sha256=$taskFinalizerTestSha;consumer_clock_test_sha256=$taskConsumerClockTestSha;execution_arguments_test_sha256=$taskExecutionTestSha;literal_driver_sha256=$taskLiteralDriverSha;negative_caller_sha256=$taskNegativeDriverSha;negative_test_sha256=$taskNegativeTestSha;socket_cleanup_test_sha256=$taskCleanupTestSha;reply_preflight_test_sha256=$taskReplyPreflightTestSha;admission_gate_sha256=$taskAdmissionGateSha;reader_owner_sha256=$taskReaderOwnerSha;consumer_sha256=$taskConsumerSha;assertions_sha256=$taskAssertionsSha;journal_sha256=$taskJournalSha;native_sha256=$taskNativeSha;physical_sha256=$taskPhysicalSha;direct_file_allowance_bytes=1912602624;reviewed_method_count=0;reviewed_call_count=0;probe_binding_test_sha256=$taskProbeBindingTestSha;runner_sha256='64458f6bbfd4ea913262cde8154a001e05999fa1ff33de328907a0c420ac0a2a';independent_recipe_verdict='conditional CLEAR, /root/provider_route_review';agent_execution_admission='released after fresh checks for this one controlled phase only';c_additional_bytes=85899345920;e_additional_bytes=69793218560;whole_chain_admitted=$false;volumes=$taskVolumes;pagefiles=$taskPages;pagefile_settings=$taskPageSettings;usn_c=@{exit_code=$taskUsnCExit;lines=$taskUsnC};usn_e=@{exit_code=$taskUsnEExit;lines=$taskUsnE};vhd=@{path=$taskVhd.FullName;length=$taskVhd.Length;last_write_utc=$taskVhd.LastWriteTimeUtc.ToString('o')};linux_tool_return=$taskLinux}
$taskRaw=[Text.Encoding]::UTF8.GetBytes(($taskRecord|ConvertTo-Json -Depth 9 -Compress)+"`n")
if($taskRaw.Length -gt 16384){throw 'admission record bound'}
$taskAdmission=Join-Path (Get-Location) (Join-Path $taskBase ('prep-'+$taskPhase+'-admission.original.json'))
$taskStream=[IO.File]::Open($taskAdmission,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
try{$taskStream.Write($taskRaw,0,$taskRaw.Length);$taskStream.Flush($true)}finally{$taskStream.Dispose()}

$taskDestination=Join-Path (Get-Location) (Join-Path $taskBase 'ci-9cf04a1b-originals')
[void](New-Item -ItemType Directory -Path $taskDestination -ErrorAction Stop)
$taskZipPath=Join-Path $taskDestination 'cpu-checks.original.zip'
$taskErrors=[Collections.Generic.List[object]]::new()
$taskHandler=[Net.Http.HttpClientHandler]::new()
$taskHandler.AllowAutoRedirect=$false
$taskHandler.AutomaticDecompression=[Net.DecompressionMethods]::None
$taskHandler.MaxResponseHeadersLength=64
$taskHttp=[Net.Http.HttpClient]::new($taskHandler)
$taskHttp.Timeout=[TimeSpan]::FromSeconds(60)
$taskCancel=[Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(60))
$taskWatch=[Diagnostics.Stopwatch]::StartNew()
$taskResponse=$null;$taskInput=$null;$taskFile=$null
$taskWritten=0L;$taskExtentUnknown=$false;$taskFsync=$false;$taskClosed=$false
$taskBodyComplete=$false;$taskTimedOut=$false;$taskNetworkMs=$null;$taskStatus=$null
$taskStage='http_headers'
try {
 $taskResponse=$taskHttp.GetAsync('ARTIFACT_DOWNLOAD_URL_NOT_RETAINED',[Net.Http.HttpCompletionOption]::ResponseHeadersRead,$taskCancel.Token).GetAwaiter().GetResult()
 $taskStatus=[int]$taskResponse.StatusCode
 if($taskStatus -ne 200 -or $taskResponse.Content.Headers.ContentLength -ne 3278561){throw 'artifact header binding differs'}
 $taskInput=$taskResponse.Content.ReadAsStreamAsync($taskCancel.Token).GetAwaiter().GetResult()
 $taskFile=[IO.File]::Open($taskZipPath,'CreateNew','Write','Read')
 $taskBuffer=[byte[]]::new(65536)
 while($true){
  $taskStage='content_read'
  $taskCount=$taskInput.ReadAsync($taskBuffer,0,$taskBuffer.Length,$taskCancel.Token).GetAwaiter().GetResult()
  if($taskCount -eq 0){break}
  if($taskWritten+$taskCount -gt 4194304){throw 'artifact prewrite cap exceeded'}
  $taskStage='payload_write'
  $taskFile.Write($taskBuffer,0,$taskCount)
  $taskWritten+=$taskCount
 }
 $taskBodyComplete=$true
 $taskNetworkMs=[Math]::Round($taskWatch.Elapsed.TotalMilliseconds,3)
} catch {
 if($taskStage -eq 'payload_write'){$taskExtentUnknown=$true}
 $taskTimedOut=$taskCancel.IsCancellationRequested -and -not $taskBodyComplete
 $taskErrors.Add(@{stage=$taskStage;type=$_.Exception.GetType().FullName;hresult=$_.Exception.HResult})
} finally {
 if($taskFile){
  try{$taskFile.Flush($true);$taskFsync=$true}catch{$taskErrors.Add(@{stage='file_fsync';type=$_.Exception.GetType().FullName;hresult=$_.Exception.HResult})}
  try{$taskFile.Dispose();$taskClosed=$true}catch{$taskErrors.Add(@{stage='file_close';type=$_.Exception.GetType().FullName;hresult=$_.Exception.HResult})}
 }
 foreach($taskCleanup in @(@('http_content_close',$taskInput),@('http_response_close',$taskResponse),@('http_client_close',$taskHttp),@('http_cancel_close',$taskCancel))){
  if($taskCleanup[1]){try{$taskCleanup[1].Dispose()}catch{$taskErrors.Add(@{stage=$taskCleanup[0];type=$_.Exception.GetType().FullName;hresult=$_.Exception.HResult})}}
 }
}
$taskActualSize=$null;$taskActualSha=$null
if(Test-Path -LiteralPath $taskZipPath){
 $taskActualSize=(Get-Item -LiteralPath $taskZipPath).Length
 if($taskActualSize -le 4194304){$taskActualSha=(Get-FileHash -LiteralPath $taskZipPath -Algorithm SHA256).Hash.ToLowerInvariant()}
}
$taskAccepted=$taskErrors.Count -eq 0 -and $taskBodyComplete -and -not $taskTimedOut -and -not $taskExtentUnknown -and $taskFsync -and $taskClosed -and $taskWritten -eq 3278561 -and $taskActualSize -eq 3278561 -and $taskActualSha -eq 'a5576129cb2fe37dab9ddfbcc7bfe5c8c25515bc4e4dcdb0e9dd2075c64607a6'
$taskReceipt=@{schema_version=1;scope='exact CI artifact preservation only';artifact_id=12704774553;workflow_run=40436076275;job=121964936115;artifact_head='9cf04a1b22dcea6e24b0f1be33a2ce8b8ec395ff';expected_size_bytes=3278561;expected_sha256='a5576129cb2fe37dab9ddfbcc7bfe5c8c25515bc4e4dcdb0e9dd2075c64607a6';actual_size_bytes=$taskActualSize;actual_sha256=$taskActualSha;written_bytes=$taskWritten;write_extent_unknown=$taskExtentUnknown;body_eof=$taskBodyComplete;network_timed_out=$taskTimedOut;network_elapsed_ms=$taskNetworkMs;file_fsync_completed=$taskFsync;file_close_completed=$taskClosed;elapsed_before_receipt_ms=[Math]::Round($taskWatch.Elapsed.TotalMilliseconds,3);causes=@($taskErrors.ToArray());accepted=[bool]$taskAccepted;whole_chain_admitted=$false;report_inspection_performed=$false}
$taskReceiptRaw=[Text.Encoding]::UTF8.GetBytes(($taskReceipt|ConvertTo-Json -Depth 8 -Compress)+"`n")
if($taskReceiptRaw.Length -gt 16384){throw 'preservation receipt cap'}
$taskReceiptStream=[IO.File]::Open((Join-Path $taskDestination 'artifact-preservation.original.json'),'CreateNew','Write','Read')
$taskReceiptFsync=$false;$taskReceiptClosed=$false
try{$taskReceiptStream.Write($taskReceiptRaw,0,$taskReceiptRaw.Length);$taskReceiptStream.Flush($true);$taskReceiptFsync=$true}finally{$taskReceiptStream.Dispose();$taskReceiptClosed=$true}
@{accepted=[bool]$taskAccepted;artifact_id=12704774553;bytes=$taskActualSize;sha256=$taskActualSha;receipt_fsync=$taskReceiptFsync;receipt_close=$taskReceiptClosed;causes=@($taskErrors.ToArray())}|ConvertTo-Json -Depth 6 -Compress
if(-not $taskAccepted){exit 1}

