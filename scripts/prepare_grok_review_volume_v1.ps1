# Support-only orchestrator for the approved PR9 review-volume boundary.
# Planning44e8; delegated specification approval PR9/6468280643.
# Definitions have no native storage effects. A separately authenticated native
# boundary/caller, qualified full peak and execution admission are mandatory.
# Dot-source from the reviewed caller; direct invocation only describes the plan.
Set-StrictMode -Version Latest

function Get-Pr9GrokReviewVolumePlan {
    [ordered]@{
        schema_version=1
        planning_commit='44e8cef19d70f555e2f37dd4ea07651bd9b8125f'
        backing_path='E:/VAST-pr9/grok-bounded-review-20261028-07.vhd'
        virtual_bytes=134217728L
        file_bytes=134218240L
        allocated_bytes=134221824L
        drive='V:'
        caller_sid='S-1-5-21-3110146144-1192974603-3912567380-24130'
        maximum_ms=180000L
        maximum_disks=64
        maximum_job_polls=1800
        minimum_usable_bytes=67108864L
        capacity_accepted=$false
        application_authority=$false
    }
}

function Stop-Pr9GrokVolume([string]$Code) {
    $errorValue=[InvalidOperationException]::new('bounded review-volume admission or operation refused')
    $errorValue.Data['pr9_volume_code']=$Code
    throw $errorValue
}

function Get-Pr9GrokVolumeCode([Exception]$ErrorValue,[string]$Default) {
    $allowed=@('authority','privilege','deadline','letter','target','capacity','backend_unknown','backend_failure','disk','backing','partition','volume')
    if ($ErrorValue.Data.Contains('pr9_volume_code')) {
        $value=$ErrorValue.Data['pr9_volume_code']
        if ($value -is [string] -and $value.Length -le 32 -and $value -cin $allowed) { return $value }
    }
    return $Default
}

function Test-Pr9GrokVolumeInteger($Value,[long]$Maximum) {
    if ($null -eq $Value -or $Value.GetType() -notin @([byte],[sbyte],[uint16],[int16],[uint32],[int32],[uint64],[int64])) { return $false }
    return $Value -ge 0 -and $Value -le $Maximum
}

function Test-Pr9GrokVolumeBoolean($Value,[bool]$Expected) {
    return ($Value -is [bool]) -and ($Value -ceq $Expected)
}

function Test-Pr9GrokVolumeText($Value,[int]$Maximum) {
    return ($Value -is [string]) -and ($Value.Length -gt 0) -and ($Value.Length -le $Maximum)
}

function Copy-Pr9GrokVolumeAdmission([Collections.IDictionary]$Admission) {
    $names=@('schema_version','planning_commit','source_sha256','execution_approval','independent_reviews','ordinary_sid','boot','deadline_tick_ms','ordinary_v_absent','ordinary_check_tick_ms','c_peak_bytes','e_peak_bytes','e_metadata_bytes','native_writers_qualified','source_reviewed')
    if ($Admission.Count -ne $names.Count) { Stop-Pr9GrokVolume 'authority' }
    $copy=@{}
    foreach ($name in $Admission.Keys) {
        if ($name -isnot [string] -or $name -cnotin $names) { Stop-Pr9GrokVolume 'authority' }
        $value=$Admission[$name]
        if ($name -ceq 'independent_reviews') {
            if ($value -isnot [array] -or $value.Count -ne 2 -or
                -not (Test-Pr9GrokVolumeInteger $value[0] 9223372036854775807L) -or
                -not (Test-Pr9GrokVolumeInteger $value[1] 9223372036854775807L)) { Stop-Pr9GrokVolume 'authority' }
            $copy[$name]=@($value[0],$value[1])
        } else {
            if ($null -eq $value -or ($value -is [string] -and $value.Length -gt 256) -or
                ($value -isnot [string] -and $value -isnot [bool] -and
                 -not (Test-Pr9GrokVolumeInteger $value 9223372036854775807L))) { Stop-Pr9GrokVolume 'authority' }
            $copy[$name]=$value
        }
    }
    return $copy
}

function Add-Pr9GrokVolumeExceptionIdentity([Collections.Generic.List[Exception]]$Seen,[Exception]$Value) {
    foreach ($prior in $Seen) { if ([object]::ReferenceEquals($prior,$Value)) { return $false } }
    $Seen.Add($Value)
    return $true
}

function Assert-Pr9GrokVolumeClock($Boundary,$Admission) {
    $now=& $Boundary.Now
    if ($now -isnot [long] -and $now -isnot [int]) { Stop-Pr9GrokVolume 'deadline' }
    if ($now -lt 0 -or ($Admission.deadline_tick_ms -isnot [long] -and $Admission.deadline_tick_ms -isnot [int]) -or
        $now -ge $Admission.deadline_tick_ms) { Stop-Pr9GrokVolume 'deadline' }
    return [long]$now
}

function Assert-Pr9GrokVolumeAdmission($Admission,$HostFacts,$Plan,[long]$Now) {
    $authority=$false
    try {
        if ($Admission.Count -gt 32 -or $Admission.independent_reviews -isnot [array] -or
            $Admission.independent_reviews.Count -ne 2) { Stop-Pr9GrokVolume 'authority' }
        $reviews=$Admission.independent_reviews
        $authority=(
            (Test-Pr9GrokVolumeInteger $Admission.schema_version 1) -and $Admission.schema_version -eq 1 -and
            $Admission.planning_commit -ceq $Plan.planning_commit -and
            (Test-Pr9GrokVolumeText $Admission.planning_commit 40) -and
            $Admission.source_sha256 -is [string] -and $Admission.source_sha256 -cmatch '^[0-9a-f]{64}$' -and
            $Admission.source_sha256 -ceq $HostFacts.SourceSha256 -and
            (Test-Pr9GrokVolumeInteger $Admission.execution_approval 9223372036854775807L) -and $Admission.execution_approval -gt 0 -and
            (Test-Pr9GrokVolumeBoolean $Admission.source_reviewed $true) -and
            $reviews.Count -eq 2 -and (Test-Pr9GrokVolumeInteger $reviews[0] 9223372036854775807L) -and
            (Test-Pr9GrokVolumeInteger $reviews[1] 9223372036854775807L) -and
            $reviews[0] -gt 0 -and $reviews[1] -gt 0 -and $reviews[0] -ne $reviews[1] -and
            (Test-Pr9GrokVolumeText $Admission.boot 256) -and (Test-Pr9GrokVolumeText $HostFacts.Boot 256) -and $Admission.boot -ceq $HostFacts.Boot -and
            (Test-Pr9GrokVolumeText $Admission.ordinary_sid 184) -and (Test-Pr9GrokVolumeText $HostFacts.Sid 184) -and
            (Test-Pr9GrokVolumeText $HostFacts.SourceSha256 64) -and
            $Admission.ordinary_sid -ceq $Plan.caller_sid -and $HostFacts.Sid -ceq $Plan.caller_sid -and
            (Test-Pr9GrokVolumeBoolean $HostFacts.CommandsQualified $true)
        )
    } catch { $authority=$false }
    if (-not $authority) { Stop-Pr9GrokVolume 'authority' }
    if (-not (Test-Pr9GrokVolumeBoolean $HostFacts.Elevated $true)) { Stop-Pr9GrokVolume 'privilege' }
    if (-not (Test-Pr9GrokVolumeInteger $Admission.ordinary_check_tick_ms 9223372036854775807L)) { Stop-Pr9GrokVolume 'deadline' }
    if ($Admission.deadline_tick_ms - $Now -gt $Plan.maximum_ms -or
        $Admission.ordinary_check_tick_ms -gt $Now -or
        $Now - $Admission.ordinary_check_tick_ms -gt 10000) { Stop-Pr9GrokVolume 'deadline' }
    if (-not (Test-Pr9GrokVolumeBoolean $Admission.ordinary_v_absent $true) -or -not (Test-Pr9GrokVolumeBoolean $HostFacts.VAbsent $true)) { Stop-Pr9GrokVolume 'letter' }
    if (-not (Test-Pr9GrokVolumeBoolean $HostFacts.TargetAbsent $true) -or -not (Test-Pr9GrokVolumeBoolean $HostFacts.ParentSafe $true)) { Stop-Pr9GrokVolume 'target' }
    $capacity=$false
    try {
        # Exterior metadata/native-writer claims must be independently qualified
        # in the sealed admission. A proposed allowance or free-space observation
        # never turns these claims true.
        $capacity=(
            (Test-Pr9GrokVolumeBoolean $Admission.native_writers_qualified $true) -and
            $Admission.c_peak_bytes -is [long] -and $Admission.c_peak_bytes -ge 85899345920L -and
            $Admission.e_peak_bytes -is [long] -and $Admission.e_peak_bytes -ge 70866960384L -and
            ($Admission.e_metadata_bytes -is [long] -or $Admission.e_metadata_bytes -is [int]) -and $Admission.e_metadata_bytes -gt 0 -and
            $HostFacts.CFree -is [long] -and $HostFacts.EFree -is [long] -and
            (Test-Pr9GrokVolumeInteger $HostFacts.AllocationUnitC 4294967295L) -and
            (Test-Pr9GrokVolumeInteger $HostFacts.AllocationUnitE 4294967295L) -and
            $HostFacts.AllocationUnitC -eq 4096 -and $HostFacts.AllocationUnitE -eq 4096 -and
            $HostFacts.CFree -ge 42949672960L + $Admission.c_peak_bytes -and
            $HostFacts.EFree -ge $Admission.e_peak_bytes + $Plan.allocated_bytes + $Admission.e_metadata_bytes
        )
    } catch { $capacity=$false }
    if (-not $capacity) { Stop-Pr9GrokVolume 'capacity' }
}

function Get-Pr9GrokVolumeJobIdentity($Job) {
    if ($null -eq $Job -or $Job.Path -isnot [string] -or $Job.Path.Length -lt 1 -or $Job.Path.Length -gt 2048 -or
        -not (Test-Pr9GrokVolumeText $Job.Class 32) -or $Job.Class -cne 'Msvm_ConcreteJob' -or $Job.Namespace -isnot [string] -or $Job.Namespace.Length -gt 128 -or
        $Job.Server -isnot [string] -or $Job.Server.Length -gt 256 -or
        $Job.Namespace.Replace('\','/').ToLowerInvariant() -cne 'root/virtualization/v2' -or
        $Job.Server -notin @('local','localhost','.',[Environment]::MachineName) -or
        $Job.Keys -isnot [Collections.IDictionary] -or $Job.Keys.Count -gt 8 -or
        $Job.KeyTypes -isnot [Collections.IDictionary] -or $Job.KeyTypes.Count -ne $Job.Keys.Count) { Stop-Pr9GrokVolume 'backend_unknown' }
    $keys=[ordered]@{};$types=[ordered]@{}
    foreach ($name in @($Job.Keys.Keys | Sort-Object)) {
        if ($name -isnot [string] -or $name.Length -lt 1 -or $name.Length -gt 64) { Stop-Pr9GrokVolume 'backend_unknown' }
        $value=$Job.Keys[$name]
        $type=$Job.KeyTypes[$name]
        $typesAllowed=@{String=[string];Boolean=[bool];UInt8=[byte];SInt8=[sbyte];UInt16=[uint16];SInt16=[int16];UInt32=[uint32];SInt32=[int32];UInt64=[uint64];SInt64=[int64];Char16=[char];DateTime=[datetime]}
        if ($type -isnot [string] -or $type -cnotin $typesAllowed.Keys) { Stop-Pr9GrokVolume 'backend_unknown' }
        if (($null -ne $value) -and ($value.GetType() -ne $typesAllowed[$type])) { Stop-Pr9GrokVolume 'backend_unknown' }
        if (($value -is [string]) -and ($value.Length -gt 256)) { Stop-Pr9GrokVolume 'backend_unknown' }
        $keys[$name]=$value
        $types[$name]=$type
    }
    # The actual reference/path is decisive. Do not invent a nonnull InstanceID.
    [ordered]@{path=$Job.Path;server=$Job.Server;namespace=$Job.Namespace;class=$Job.Class;keys=$keys;key_types=$types}
}

function Complete-Pr9GrokVolumeBackend($Result,$Boundary,$Admission,$Report,[string]$Operation) {
    $row=[ordered]@{operation=$Operation;return_value=$null;kind='unknown';identity=$null;polls=0;state=$null;error_code=$null;complete=$false}
    $Report.backends.Add($row)
    if ($null -eq $Result -or -not (Test-Pr9GrokVolumeInteger $Result.ReturnValue 4294967295L)) { Stop-Pr9GrokVolume 'backend_unknown' }
    $row.return_value=[long]$Result.ReturnValue
    if ($row.return_value -eq 0) {
        $row.kind='synchronous'
        if ($null -ne $Result.Job) { $row.identity=Get-Pr9GrokVolumeJobIdentity $Result.Job }
        $row.complete=$true
        return
    }
    if ($row.return_value -ne 4096) { $row.kind='failure';Stop-Pr9GrokVolume 'backend_failure' }
    $original=$Result.Job
    $identity=Get-Pr9GrokVolumeJobIdentity $original
    $row.kind='original_job';$row.identity=$identity
    $pinned=$identity | ConvertTo-Json -Depth 5 -Compress
    for ($count=0;$count -lt 1800;$count++) {
        try { $null=Assert-Pr9GrokVolumeClock $Boundary $Admission }
        catch { Stop-Pr9GrokVolume 'backend_unknown' }
        # ONLY the original returned object is ever supplied to refresh.
        $current=& $Boundary.Job $original
        $row.polls++
        $observed=Get-Pr9GrokVolumeJobIdentity $current
        if (($observed | ConvertTo-Json -Depth 5 -Compress) -cne $pinned) { Stop-Pr9GrokVolume 'backend_unknown' }
        if (-not (Test-Pr9GrokVolumeInteger $current.State 65535) -or
            -not (Test-Pr9GrokVolumeInteger $current.ErrorCode 65535)) { Stop-Pr9GrokVolume 'backend_unknown' }
        $row.state=[int]$current.State;$row.error_code=[int]$current.ErrorCode
        if ($row.state -eq 7) {
            if ($row.error_code -ne 0) { Stop-Pr9GrokVolume 'backend_failure' }
            $null=Assert-Pr9GrokVolumeClock $Boundary $Admission
            $row.complete=$true
            return
        }
        if ($row.state -in @(8,9,10)) { Stop-Pr9GrokVolume 'backend_failure' }
        if ($row.state -notin @(2,3,4,5,6,11)) { Stop-Pr9GrokVolume 'backend_unknown' }
        $null=& $Boundary.Pause 100
    }
    Stop-Pr9GrokVolume 'backend_unknown'
}

function Get-Pr9GrokVolumeDisks($Boundary,$Plan) {
    $value=& $Boundary.Disks
    if ($value -isnot [array] -or $value.Count -gt $Plan.maximum_disks) { Stop-Pr9GrokVolume 'disk' }
    $seen=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($disk in $value) {
        if ($disk.Path -isnot [string] -or $disk.Path.Length -lt 1 -or $disk.Path.Length -gt 2048 -or
            -not $seen.Add($disk.Path)) { Stop-Pr9GrokVolume 'disk' }
    }
    return ,$value
}

function Assert-Pr9GrokVolumeBacking($Boundary,$Plan,[string]$Identity,[string]$VhdId) {
    $value=& $Boundary.Backing
    if ($null -eq $value -or $value.Path -isnot [string] -or
        $value.Path.Replace('\','/') -cne $Plan.backing_path -or
        $value.Identity -isnot [string] -or $value.Identity.Length -lt 1 -or $value.Identity.Length -gt 256 -or
        $value.VhdId -isnot [string] -or $value.VhdId.Length -lt 1 -or $value.VhdId.Length -gt 64 -or
        -not (Test-Pr9GrokVolumeBoolean $value.Normal $true) -or -not (Test-Pr9GrokVolumeBoolean $value.FooterValid $true) -or
        -not (Test-Pr9GrokVolumeInteger $value.Length $Plan.file_bytes) -or
        -not (Test-Pr9GrokVolumeInteger $value.Allocation $Plan.allocated_bytes) -or
        -not (Test-Pr9GrokVolumeInteger $value.Size $Plan.virtual_bytes) -or
        -not (Test-Pr9GrokVolumeText $value.Type 16) -or -not (Test-Pr9GrokVolumeText $value.Format 8) -or
        $value.Length -ne $Plan.file_bytes -or $value.Allocation -ne $Plan.allocated_bytes -or
        $value.Size -ne $Plan.virtual_bytes -or $value.Type -cne 'Fixed' -or $value.Format -cne 'VHD' -or
        ($Identity -and $value.Identity -cne $Identity) -or ($VhdId -and $value.VhdId -cne $VhdId)) { Stop-Pr9GrokVolume 'backing' }
    return $value
}

function Assert-Pr9GrokVolumeDiskEligibility($Disk,$Plan,[string]$Style,[string]$PinnedPath,[string]$PinnedUniqueId) {
    if ($null -eq $Disk -or -not (Test-Pr9GrokVolumeText $Disk.Path 2048) -or
        -not (Test-Pr9GrokVolumeText $Disk.UniqueId 256) -or $Disk.Path -cne $PinnedPath -or $Disk.UniqueId -cne $PinnedUniqueId -or
        -not (Test-Pr9GrokVolumeInteger $Disk.Size $Plan.virtual_bytes) -or
        -not (Test-Pr9GrokVolumeText $Disk.PartitionStyle 16) -or
        $Disk.Size -ne $Plan.virtual_bytes -or $Disk.PartitionStyle -cne $Style -or
        -not (Test-Pr9GrokVolumeBoolean $Disk.IsBoot $false) -or -not (Test-Pr9GrokVolumeBoolean $Disk.IsSystem $false) -or
        -not (Test-Pr9GrokVolumeBoolean $Disk.IsClustered $false)) { Stop-Pr9GrokVolume 'disk' }
    if ($Style -ceq 'RAW') {
        if (-not (Test-Pr9GrokVolumeInteger $Disk.PartitionCount 4294967295L) -or $Disk.PartitionCount -ne 0) { Stop-Pr9GrokVolume 'disk' }
    }
}

function Assert-Pr9GrokVolumeDisk($Disk,$Boundary,$Plan,[string]$Identity,[string]$VhdId,[string]$Style,[string]$PinnedPath,[string]$PinnedUniqueId) {
    $null=Assert-Pr9GrokVolumeBacking $Boundary $Plan $Identity $VhdId
    Assert-Pr9GrokVolumeDiskEligibility $Disk $Plan $Style $PinnedPath $PinnedUniqueId
    $fresh=Get-Pr9GrokVolumeDisks $Boundary $Plan
    $matches=@($fresh | Where-Object {$_.Path -ceq $Disk.Path -and $_.UniqueId -ceq $Disk.UniqueId})
    if ($matches.Count -ne 1) { Stop-Pr9GrokVolume 'disk' }
    Assert-Pr9GrokVolumeDiskEligibility $matches[0] $Plan $Style $PinnedPath $PinnedUniqueId
    $reverse=& $Boundary.Reverse $Disk
    if (-not (Test-Pr9GrokVolumeText $reverse.Identity 256) -or -not (Test-Pr9GrokVolumeText $reverse.VhdId 64) -or
        $reverse.Identity -cne $Identity -or $reverse.VhdId -cne $VhdId) { Stop-Pr9GrokVolume 'disk' }
    # Recheck every eligibility field after the last I/O callback, without a
    # further callback that could replace the validated packet.
    Assert-Pr9GrokVolumeDiskEligibility $Disk $Plan $Style $PinnedPath $PinnedUniqueId
}

function Assert-Pr9GrokVolumePartitionPin($Partition,$Pin) {
    if (-not (Test-Pr9GrokVolumeText $Partition.Guid 128) -or -not (Test-Pr9GrokVolumeText $Partition.DiskPath 2048) -or
        -not (Test-Pr9GrokVolumeText $Partition.DiskUniqueId 256) -or
        -not (Test-Pr9GrokVolumeInteger $Partition.Offset 134217728L) -or
        -not (Test-Pr9GrokVolumeInteger $Partition.Size 134217728L) -or
        $Partition.Guid -cne $Pin.guid -or $Partition.DiskPath -cne $Pin.disk_path -or
        $Partition.DiskUniqueId -cne $Pin.disk_id -or $Partition.Offset -ne $Pin.offset -or
        $Partition.Size -ne $Pin.bytes) { Stop-Pr9GrokVolume 'partition' }
}

function Assert-Pr9GrokVolumePartition($Partition,$Disk,$Plan) {
    if ($null -eq $Partition -or -not (Test-Pr9GrokVolumeText $Partition.DiskPath 2048) -or
        -not (Test-Pr9GrokVolumeText $Partition.DiskUniqueId 256) -or
        -not (Test-Pr9GrokVolumeText $Partition.Type 16) -or
        -not (Test-Pr9GrokVolumeInteger $Partition.Offset $Plan.virtual_bytes) -or
        -not (Test-Pr9GrokVolumeInteger $Partition.Size $Plan.virtual_bytes) -or $Partition.DiskPath -cne $Disk.Path -or
        $Partition.DiskUniqueId -cne $Disk.UniqueId -or $Partition.Guid -isnot [string] -or
        $Partition.Guid.Length -lt 1 -or $Partition.Guid.Length -gt 128 -or
        $Partition.Type -cne 'basic' -or $Partition.Offset -lt 1048576 -or
        $Partition.Offset % 1048576 -ne 0 -or $Partition.Size -lt $Plan.minimum_usable_bytes -or
        $Partition.Offset + $Partition.Size -gt $Plan.virtual_bytes) { Stop-Pr9GrokVolume 'partition' }
}

function Assert-Pr9GrokReviewVolume($Volume,$Partition,$Disk,$Plan) {
    if ($null -eq $Volume -or -not (Test-Pr9GrokVolumeText $Volume.DiskPath 2048) -or
        -not (Test-Pr9GrokVolumeText $Volume.PartitionGuid 128) -or
        -not (Test-Pr9GrokVolumeText $Volume.FileSystem 16) -or
        -not (Test-Pr9GrokVolumeInteger $Volume.AllocationUnit 4294967295L) -or
        -not (Test-Pr9GrokVolumeInteger $Volume.Size $Plan.virtual_bytes) -or
        -not (Test-Pr9GrokVolumeInteger $Volume.Free $Plan.virtual_bytes) -or $Volume.DiskPath -cne $Disk.Path -or
        $Volume.PartitionGuid -cne $Partition.Guid -or $Volume.Guid -isnot [string] -or
        $Volume.Guid.Length -lt 1 -or $Volume.Guid.Length -gt 128 -or
        $Volume.Serial -isnot [string] -or $Volume.Serial.Length -ne 8 -or
        $Volume.FileSystem -cne 'NTFS' -or $Volume.AllocationUnit -ne 4096 -or
        $Volume.Size -gt $Partition.Size -or $Volume.Free -lt $Plan.minimum_usable_bytes -or
        $Volume.Free -gt $Volume.Size) { Stop-Pr9GrokVolume 'volume' }
}

function Invoke-Pr9GrokReviewVolumeSetup {
    param([AllowNull()][Collections.IDictionary]$Admission=$null,[AllowNull()]$Boundary=$null)
    $plan=Get-Pr9GrokReviewVolumePlan
    if ($null -eq $Admission -and $null -eq $Boundary) { return [ordered]@{status='described';plan=$plan} }
    $report=[ordered]@{
        schema_version=1;status='refused';primary=$null;secondary=[Collections.Generic.List[string]]::new()
        backends=[Collections.Generic.List[object]]::new();started=$false;closed=$false
        backing=$null;disk=$null;partition=$null;volume=$null
        application_authority=$false;capacity_acceptance=$false
    }
    $phase='authority';$primaryError=$null;$seenErrors=[Collections.Generic.List[Exception]]::new()
    try {
        if ($null -eq $Admission -or $null -eq $Boundary) { Stop-Pr9GrokVolume 'authority' }
        # Copy the closed scalar protocol before the FIRST callback. The caller's
        # mutable map/array can no longer renew this operation's original clock.
        $Admission=Copy-Pr9GrokVolumeAdmission $Admission
        $phase='deadline';$now=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='authority';$facts=& $Boundary.Host
        Assert-Pr9GrokVolumeAdmission $Admission $facts $plan $now
        $phase='disk';$before=Get-Pr9GrokVolumeDisks $Boundary $plan
        $beforeIds=@($before | ForEach-Object {$_.Path})
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='create';$report.started=$true
        $result=& $Boundary.Create
        Complete-Pr9GrokVolumeBackend $result $Boundary $Admission $report 'create'
        $phase='backing';$file=Assert-Pr9GrokVolumeBacking $Boundary $plan '' ''
        # Pin scalar values BEFORE any subsequent boundary callback can mutate.
        $fileId=[string]$file.Identity;$vhdId=[string]$file.VhdId
        $report.backing=[ordered]@{identity=$fileId;vhd_id=$vhdId;bytes=$file.Length;allocated_bytes=$file.Allocation}
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='backing';$null=Assert-Pr9GrokVolumeBacking $Boundary $plan $fileId $vhdId
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='attach';$result=& $Boundary.Attach
        Complete-Pr9GrokVolumeBackend $result $Boundary $Admission $report 'attach'
        $phase='disk';$after=Get-Pr9GrokVolumeDisks $Boundary $plan
        $new=@($after | Where-Object {$_.Path -cnotin $beforeIds})
        if ($new.Count -ne 1 -or $after.Count -ne $before.Count+1) { Stop-Pr9GrokVolume 'disk' }
        $disk=$new[0]
        $diskPath=[string]$disk.Path;$diskId=[string]$disk.UniqueId
        if ($disk.PartitionCount -ne 0) { Stop-Pr9GrokVolume 'disk' }
        Assert-Pr9GrokVolumeDisk $disk $Boundary $plan $fileId $vhdId 'RAW' $diskPath $diskId
        $report.disk=[ordered]@{path=$disk.Path;unique_id=$disk.UniqueId;size=$disk.Size}
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='disk';Assert-Pr9GrokVolumeDisk $disk $Boundary $plan $fileId $vhdId 'RAW' $diskPath $diskId
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='initialize';$initialized=& $Boundary.Initialize $disk
        if ($initialized.Path -cne $diskPath -or $initialized.UniqueId -cne $diskId) { Stop-Pr9GrokVolume 'disk' }
        $phase='disk';Assert-Pr9GrokVolumeDisk $initialized $Boundary $plan $fileId $vhdId 'GPT' $diskPath $diskId
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='partition';$partition=& $Boundary.Partition $initialized
        Assert-Pr9GrokVolumePartition $partition $initialized $plan
        $partitionPin=[ordered]@{guid=[string]$partition.Guid;disk_path=$diskPath;disk_id=$diskId;offset=$partition.Offset;bytes=$partition.Size}
        $report.partition=[ordered]@{guid=$partitionPin.guid;offset=$partitionPin.offset;bytes=$partitionPin.bytes}
        $phase='disk';Assert-Pr9GrokVolumeDisk $initialized $Boundary $plan $fileId $vhdId 'GPT' $diskPath $diskId
        $phase='partition';Assert-Pr9GrokVolumePartitionPin $partition $partitionPin
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='format';$volume=& $Boundary.Format $partition
        Assert-Pr9GrokVolumePartitionPin $partition $partitionPin
        Assert-Pr9GrokReviewVolume $volume $partition $initialized $plan
        $phase='volume';$volume=& $Boundary.Volume $partition
        Assert-Pr9GrokVolumePartitionPin $partition $partitionPin
        Assert-Pr9GrokReviewVolume $volume $partition $initialized $plan
        $volumeGuid=[string]$volume.Guid;$volumeSerial=[string]$volume.Serial
        $report.volume=[ordered]@{guid=$volumeGuid;serial=$volumeSerial;bytes=$volume.Size;free=$volume.Free}
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='protect';$null=& $Boundary.Protect
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='disk';Assert-Pr9GrokVolumeDisk $initialized $Boundary $plan $fileId $vhdId 'GPT' $diskPath $diskId
        $phase='volume';$freshVolume=& $Boundary.Volume $partition
        Assert-Pr9GrokReviewVolume $freshVolume $partition $initialized $plan
        Assert-Pr9GrokVolumePartitionPin $partition $partitionPin
        if ($freshVolume.Guid -cne $volumeGuid -or $freshVolume.Serial -cne $volumeSerial) { Stop-Pr9GrokVolume 'volume' }
        $phase='letter'
        if (-not (Test-Pr9GrokVolumeBoolean (& $Boundary.VAbsent) $true)) { Stop-Pr9GrokVolume 'letter' }
        $phase='partition';Assert-Pr9GrokVolumePartitionPin $partition $partitionPin
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $phase='assign';$null=& $Boundary.Assign $partition
        $phase='deadline';$null=Assert-Pr9GrokVolumeClock $Boundary $Admission
        $report.status='ready'
    } catch {
        $primaryError=$_.Exception
        $null=Add-Pr9GrokVolumeExceptionIdentity $seenErrors $primaryError
        $report.primary=Get-Pr9GrokVolumeCode $primaryError $phase
        $report.status=if($report.started){'held'}else{'refused'}
    } finally {
        if ($null -ne $Boundary) {
            try {
                $null=& $Boundary.Close
                $report.closed=$true
            } catch {
                if ($null -eq $primaryError) {
                    $primaryError=$_.Exception;$report.primary='close'
                    $null=Add-Pr9GrokVolumeExceptionIdentity $seenErrors $primaryError
                } elseif (Add-Pr9GrokVolumeExceptionIdentity $seenErrors $_.Exception) {
                    $report.secondary.Add('close')
                }
                $report.status=if($report.started){'held'}else{'refused'}
            }
        }
        if ($null -ne $Boundary -and $null -ne $Admission) {
            try { $null=Assert-Pr9GrokVolumeClock $Boundary $Admission }
            catch {
                if ($null -eq $primaryError) {
                    $primaryError=$_.Exception;$report.primary='deadline'
                    $null=Add-Pr9GrokVolumeExceptionIdentity $seenErrors $primaryError
                } elseif (Add-Pr9GrokVolumeExceptionIdentity $seenErrors $_.Exception) { $report.secondary.Add('deadline') }
                $report.status=if($report.started){'held'}else{'refused'}
            }
        }
    }
    # Only fixed, bounded projections escape; no raw native/private error text.
    return $report
}

if ($MyInvocation.InvocationName -ne '.') {
    Invoke-Pr9GrokReviewVolumeSetup | ConvertTo-Json -Depth 8 -Compress
}
