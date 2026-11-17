# Read-only boundary derived from reviewed controls03. Definitions only.
function Assert-Pr9ReadOnlyPreparationBoundary {
    param([Parameter(Mandatory)][string]$LinuxGuardJson,
          [Parameter(Mandatory)][Diagnostics.Stopwatch]$Clock)
    if(-not $Clock.IsRunning -or $Clock.ElapsedMilliseconds -ge 165000){throw 'inherited preparation deadline'}
    $taskRoot='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
    if((Get-Location).Path -cne $taskRoot -or $LinuxGuardJson.Length -gt 8192){throw 'fixed control entry required'}
    $taskLinux=$LinuxGuardJson|ConvertFrom-Json -DateKind String
    if($taskLinux.exit_code -ne 0){throw 'fresh Linux guard failed'}
    $taskLinuxFacts=$taskLinux.output|ConvertFrom-Json -DateKind String
    $taskObserved=[DateTimeOffset]::Parse($taskLinuxFacts.observed_utc,[Globalization.CultureInfo]::InvariantCulture)
    $taskAge=([DateTimeOffset]::UtcNow-$taskObserved).TotalSeconds
    if($taskAge -lt 0 -or $taskAge -gt 120 -or
       $taskLinuxFacts.boot_id -cne 'df4955d9-4762-42b4-a55b-0106ba3786f8' -or
       $taskLinuxFacts.root_uuid -cne 'c3d3247e-154c-43c0-a9fe-2b91d6db7666' -or
       $taskLinuxFacts.root_device -cne '/dev/sdf' -or -not $taskLinuxFacts.temporary_same_device_as_root -or
       $taskLinuxFacts.free_bytes.c -lt 128849018880 -or $taskLinuxFacts.free_bytes.e -lt 70866960384 -or
       $taskLinuxFacts.free_bytes.temporary -lt 2147483648){throw 'Linux identity or floor differs'}
    $taskStage='windows_guards'
    $taskVolumes=@(Get-Volume -DriveLetter C,E|Select-Object DriveLetter,SizeRemaining,Size,AllocationUnitSize)
    $taskC=@($taskVolumes|Where-Object DriveLetter -eq C);$taskE=@($taskVolumes|Where-Object DriveLetter -eq E)
    if($taskC.Count -ne 1 -or $taskE.Count -ne 1 -or $taskC[0].SizeRemaining -lt 128849018880 -or
       $taskE[0].SizeRemaining -lt 70866960384 -or @($taskVolumes|Where-Object {$_.AllocationUnitSize -ne 4096}).Count){throw 'Windows physical floor differs'}
    $taskConfig=Get-Item -LiteralPath 'C:/Users/s-a-balashov/.wslconfig'
    if($taskConfig.Length -ne 21 -or (Get-FileHash -LiteralPath $taskConfig.FullName -Algorithm SHA256).Hash.ToLowerInvariant() -cne
       '6efea9e209212784c22240a6019c17cee3bd31011840250c76c3bb31e2c7eea1'){throw 'WSL configuration differs'}
    $taskDistro=Get-ItemProperty -LiteralPath 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss\{733a6524-960b-47be-ac8d-deaf948be3c7}'
    if($taskDistro.DistributionName -cne 'Ubuntu' -or $taskDistro.DefaultUid -ne 1000 -or
       $taskDistro.BasePath.TrimEnd('\') -ine 'C:\Users\s-a-balashov\AppData\Local\wsl\{733a6524-960b-47be-ac8d-deaf948be3c7}'){throw 'Ubuntu identity differs'}
    $taskPage=@(Get-CimInstance Win32_PageFileSetting|Select-Object Name,InitialSize,MaximumSize)
    if($taskPage.Count -ne 1 -or $taskPage[0].Name -ine 'E:\pagefile.sys' -or $taskPage[0].MaximumSize -ne 65536){throw 'pagefile quote differs'}
    $taskUsnC=@(& fsutil usn queryjournal C: 2>&1);$taskUsnCExit=$LASTEXITCODE
    $taskUsnE=@(& fsutil usn queryjournal E: 2>&1);$taskUsnEExit=$LASTEXITCODE
    if($taskUsnCExit -ne 0 -or ($taskUsnC -join "`n") -notmatch 'Maximum Size\s+: 0x0000000002000000' -or
       ($taskUsnC -join "`n") -notmatch 'Allocation Delta\s+: 0x0000000000800000' -or
       $taskUsnEExit -ne 1 -or ($taskUsnE -join "`n") -notmatch 'Error 1179'){throw 'USN quote differs'}
    $taskHead=& git -c gc.auto=0 -c maintenance.auto=false rev-parse HEAD
    if($LASTEXITCODE -ne 0 -or $taskHead -cne '605eb02733fe256ad5ef14f358eaa81ee1a0ae44'){throw 'product source head differs'}
    $taskIndex=Get-Item -LiteralPath 'E:/STUDY/VAST/.git/worktrees/VAST8/index'
    if($taskIndex.Length -gt 3145728 -or (Test-Path -LiteralPath 'E:/STUDY/VAST/.git/worktrees/VAST8/index.lock')){throw 'index quote differs'}
    & git -c gc.auto=0 -c maintenance.auto=false diff --no-ext-diff --no-textconv --quiet HEAD -- tests/fixtures/accepted_policy_fixture_compiler_v1.py tests/fixtures/accepted_policy_standalone_reader_fixture_v2.py tests/fixtures/accepted_policy_fixture_report_v1.py scripts/backend_publication_process_supervisor_v3.py
    if($LASTEXITCODE -ne 0){throw 'protected source differs'}
    $taskWindows=[ordered]@{
        observed_utc=[DateTimeOffset]::UtcNow.ToString('o');source_commit=$taskHead;volumes=$taskVolumes
        pagefile=$taskPage;uid=$taskDistro.DefaultUid;index_bytes=$taskIndex.Length
        usn_c=@{exit_code=$taskUsnCExit;lines=$taskUsnC};usn_e=@{exit_code=$taskUsnEExit;lines=$taskUsnE}
    }
    if($Clock.ElapsedMilliseconds -ge 165000){throw 'preparation boundary deadline'}
    return [pscustomobject]@{Windows=$taskWindows;Linux=$taskLinux}
}
