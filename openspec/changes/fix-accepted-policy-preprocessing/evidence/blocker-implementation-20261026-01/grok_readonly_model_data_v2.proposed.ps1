
# Proposed bounded data/copy support; definitions only, no entrypoint.
Set-StrictMode -Version Latest

function Assert-Pr9GrokPreparationClock {
    param([Parameter(Mandatory)][Diagnostics.Stopwatch]$Clock)
    if (-not $Clock.IsRunning -or $Clock.Elapsed.TotalSeconds -ge $taskObservationSeconds) {
        throw 'running preparation observation deadline required'
    }
}

function Throw-Pr9GrokPrivateFailure {
    param($Primary,[Parameter(Mandatory)][AllowEmptyCollection()][Collections.Generic.List[Exception]]$Secondary)
    $taskDistinct=[Collections.Generic.List[Exception]]::new()
    foreach ($taskCandidate in $Secondary) {
        if ($null -eq $Primary) { $Primary=$taskCandidate;continue }
        if ([Object]::ReferenceEquals($Primary,$taskCandidate)) { continue }
        $taskKnown=$false
        foreach ($taskPrior in $taskDistinct) {
            if ([Object]::ReferenceEquals($taskPrior,$taskCandidate)) { $taskKnown=$true;break }
        }
        if (-not $taskKnown) { $taskDistinct.Add($taskCandidate) }
    }
    if ($taskDistinct.Count -gt 0) {
        $taskError=[InvalidOperationException]::new('private preparation failed; cleanup causes retained',$Primary)
        $taskError.Data['private_primary']=$Primary
        $taskError.Data['private_secondary']=$taskDistinct.ToArray()
        throw $taskError
    }
    if ($null -ne $Primary) { throw $Primary }
}

function Get-Pr9GrokPrivateFingerprint {
    param([Parameter(Mandatory)][IO.FileStream]$Stream,[Parameter(Mandatory)][long]$Length,
        [Parameter(Mandatory)][Diagnostics.Stopwatch]$Clock)
    if ($Length -lt 0 -or $Length -gt 2097152) { throw 'private member bound' }
    $taskHash=[Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
    $taskBuffer=[byte[]]::new(65536);$taskRemaining=$Length
    $taskPrimary=$null;$taskSecondary=[Collections.Generic.List[Exception]]::new();$taskDigest=$null
    try {
        $Stream.Position=0
        while ($true) {
            Assert-Pr9GrokPreparationClock -Clock $Clock
            $taskCount=$Stream.Read($taskBuffer,0,[int][Math]::Min(65536,$taskRemaining+1))
            if ($taskCount -eq 0) { break }
            if ($taskCount -gt $taskRemaining) { throw 'private member growth' }
            $taskHash.AppendData($taskBuffer,0,$taskCount);$taskRemaining-=$taskCount
        }
        if ($taskRemaining -ne 0) { throw 'private member shrink' }
        $taskDigest=$taskHash.GetHashAndReset()
    } catch { $taskPrimary=$_.Exception }
    finally {
        [Array]::Clear($taskBuffer,0,$taskBuffer.Length)
        try { $taskHash.Dispose() } catch { $taskSecondary.Add($_.Exception) }
    }
    Throw-Pr9GrokPrivateFailure -Primary $taskPrimary -Secondary $taskSecondary
    return ,$taskDigest
}

function Read-Pr9GrokHeldSmallBytes {
    param([Parameter(Mandatory)][IO.FileStream]$Stream,[Parameter(Mandatory)][long]$Length,
        [Parameter(Mandatory)][int]$Maximum,[Parameter(Mandatory)][Diagnostics.Stopwatch]$Clock)
    if ($Maximum -lt 1 -or $Maximum -gt 65536 -or $Length -lt 0 -or $Length -gt $Maximum) {
        throw 'small private read bound'
    }
    $taskBytes=[byte[]]::new([int]$Length);$taskOffset=0
    $Stream.Position=0
    while ($taskOffset -lt $taskBytes.Length) {
        Assert-Pr9GrokPreparationClock -Clock $Clock
        $taskCount=$Stream.Read($taskBytes,$taskOffset,$taskBytes.Length-$taskOffset)
        if ($taskCount -le 0) { throw 'small private read shrink' }
        $taskOffset+=$taskCount
    }
    if ($Stream.ReadByte() -ne -1) { throw 'small private read growth' }
    return ,$taskBytes
}

function Copy-Pr9GrokHeldMember {
    param([Parameter(Mandatory)]$Source,[Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][Diagnostics.Stopwatch]$Clock)
    $taskLength=[long]$Source.Node.Info.Size
    if ($taskLength -lt 0 -or $taskLength -gt 2097152) { throw 'private member bound' }
    Test-Pr9ReadOnlyGrokNodeIdentity -Node $Source.Node -File
    $taskHash=[Security.Cryptography.IncrementalHash]::CreateHash([Security.Cryptography.HashAlgorithmName]::SHA256)
    $taskBuffer=[byte[]]::new(65536);$taskRemaining=$taskLength
    $taskOutput=$null;$taskComplete=$false;$taskCopiedIdentity=$null
    $taskPrimary=$null;$taskSecondary=[Collections.Generic.List[Exception]]::new()
    try {
        Assert-Pr9GrokPreparationClock -Clock $Clock
        $taskOutput=[IO.File]::Open($Destination,[IO.FileMode]::CreateNew,[IO.FileAccess]::ReadWrite,[IO.FileShare]::Read)
        $Source.Stream.Position=0
        while ($true) {
            Assert-Pr9GrokPreparationClock -Clock $Clock
            $taskCount=$Source.Stream.Read($taskBuffer,0,[int][Math]::Min(65536,$taskRemaining+1))
            if ($taskCount -eq 0) { break }
            if ($taskCount -gt $taskRemaining) { throw 'private member growth' }
            $taskHash.AppendData($taskBuffer,0,$taskCount)
            $taskOutput.Write($taskBuffer,0,$taskCount);$taskRemaining-=$taskCount
        }
        if ($taskRemaining -ne 0) { throw 'private member shrink' }
        $taskOutput.Flush($true)
        $taskCopiedIdentity=[Pr9ReadOnlyGrokNativeV1]::Describe($taskOutput.SafeFileHandle)
        Assert-Pr9GrokPreparationClock -Clock $Clock
        $taskSourceDigest=$taskHash.GetHashAndReset()
        $taskOutputDigest=Get-Pr9GrokPrivateFingerprint -Stream $taskOutput -Length $taskLength -Clock $Clock
        if (-not [Pr9ReadOnlyGrokNativeV1]::SameBytes($taskSourceDigest,$taskOutputDigest)) {
            throw 'private copy identity mismatch'
        }
        Test-Pr9ReadOnlyGrokNodeIdentity -Node $Source.Node -File
        $taskComplete=$true
    } catch { $taskPrimary=$_.Exception }
    finally {
        [Array]::Clear($taskBuffer,0,$taskBuffer.Length)
        try { $taskHash.Dispose() } catch { $taskSecondary.Add($_.Exception) }
        if ($null -ne $taskOutput) { try { $taskOutput.Dispose() } catch { $taskSecondary.Add($_.Exception) } }
    }
    Throw-Pr9GrokPrivateFailure -Primary $taskPrimary -Secondary $taskSecondary
    if (-not $taskComplete) { throw 'private copy unavailable' }
    # All data-writing handles are closed before setting final source timestamps.
    $taskStamp=$null;$taskPrimary=$null;$taskSecondary.Clear()
    try {
        Assert-Pr9GrokPreparationClock -Clock $Clock
        $taskStamp=Open-Pr9ReadOnlyGrokNode -Path $Destination -Access 3221356544
        if ($taskStamp.Info.Volume -ne $taskCopiedIdentity.Volume -or $taskStamp.Info.Index -ne $taskCopiedIdentity.Index) {
            throw 'private metadata target identity differs'
        }
        [Pr9ReadOnlyGrokNativeV1]::PreserveTimes($taskStamp.Handle,$Source.Node.Info)
        Assert-Pr9GrokPreparationClock -Clock $Clock
        Test-Pr9ReadOnlyGrokNodeIdentity -Node $Source.Node -File
    } catch { $taskPrimary=$_.Exception }
    finally {
        if ($null -ne $taskStamp) { try { $taskStamp.Handle.Dispose() } catch { $taskSecondary.Add($_.Exception) } }
    }
    Throw-Pr9GrokPrivateFailure -Primary $taskPrimary -Secondary $taskSecondary
    # Reopen after the metadata writer has closed: Windows can finalize write
    # times at last writer close. Verify creation/write times and exact extent.
    $taskFinal=$null;$taskFinalStream=$null;$taskPrimary=$null;$taskSecondary.Clear()
    try {
        Assert-Pr9GrokPreparationClock -Clock $Clock
        $taskFinal=Open-Pr9ReadOnlyGrokNode -Path $Destination -Access 2147614720
        if ($taskFinal.Info.Volume -ne $taskCopiedIdentity.Volume -or $taskFinal.Info.Index -ne $taskCopiedIdentity.Index -or
            $taskFinal.Info.Size -ne $taskLength -or $taskFinal.Info.Links -ne 1 -or
            ($taskFinal.Info.Attributes -band 0x10) -ne 0 -or
            $taskFinal.Info.CreationLow -ne $Source.Node.Info.CreationLow -or
            $taskFinal.Info.CreationHigh -ne $Source.Node.Info.CreationHigh -or
            $taskFinal.Info.WriteLow -ne $Source.Node.Info.WriteLow -or
            $taskFinal.Info.WriteHigh -ne $Source.Node.Info.WriteHigh) {
            throw 'private post-close timestamps or extent differ'
        }
        $taskFinalStream=[IO.FileStream]::new($taskFinal.Handle,[IO.FileAccess]::Read,4096,$false)
        $taskFinalDigest=Get-Pr9GrokPrivateFingerprint -Stream $taskFinalStream -Length $taskLength -Clock $Clock
        if (-not [Pr9ReadOnlyGrokNativeV1]::SameBytes($taskSourceDigest,$taskFinalDigest)) {
            throw 'private post-close content differs'
        }
        Test-Pr9ReadOnlyGrokNodeIdentity -Node $taskFinal -File
        Test-Pr9ReadOnlyGrokNodeIdentity -Node $Source.Node -File
    } catch { $taskPrimary=$_.Exception }
    finally {
        if ($null -ne $taskFinalStream) { try { $taskFinalStream.Dispose() } catch { $taskSecondary.Add($_.Exception) } }
        if ($null -ne $taskFinal) { try { $taskFinal.Handle.Dispose() } catch { $taskSecondary.Add($_.Exception) } }
    }
    Throw-Pr9GrokPrivateFailure -Primary $taskPrimary -Secondary $taskSecondary
    # Fingerprints are private controller state, never a public receipt/prompt.
    return [pscustomobject]@{Path=$Destination;Bytes=$taskLength;PrivateFingerprint=$taskSourceDigest;PrivateIdentity=$taskCopiedIdentity}
}

function Write-Pr9GrokPrivateFixedBytes {
    param([Parameter(Mandatory)][string]$Path,[Parameter(Mandatory)][byte[]]$Bytes,
        [Parameter(Mandatory)][int]$Maximum,[Parameter(Mandatory)][Diagnostics.Stopwatch]$Clock)
    if ($Maximum -lt 1 -or $Maximum -gt 65536 -or $Bytes.Length -gt $Maximum) { throw 'private fixed write bound' }
    Assert-Pr9GrokPreparationClock -Clock $Clock
    $taskOutput=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    $taskPrimary=$null;$taskSecondary=[Collections.Generic.List[Exception]]::new()
    try { $taskOutput.Write($Bytes,0,$Bytes.Length);$taskOutput.Flush($true) }
    catch { $taskPrimary=$_.Exception }
    finally { try { $taskOutput.Dispose() } catch { $taskSecondary.Add($_.Exception) } }
    Throw-Pr9GrokPrivateFailure -Primary $taskPrimary -Secondary $taskSecondary
    Assert-Pr9GrokPreparationClock -Clock $Clock
}

function Get-Pr9GrokCredentialExpiry {
    param([Parameter(Mandatory)][byte[]]$PrivateAuthBytes)
    if ($PrivateAuthBytes.Length -gt 65536) { throw 'private auth bound' }
    $taskOptions=[Text.Json.JsonDocumentOptions]::new();$taskOptions.MaxDepth=16
    $taskMemory=[ReadOnlyMemory[byte]]::new($PrivateAuthBytes)
    $taskDoc=[Text.Json.JsonDocument]::Parse($taskMemory,$taskOptions)
    try {
        $taskCredential=$taskDoc.RootElement.GetProperty('https://auth.x.ai::b1a00492-073a-47ea-816f-4c329264a828')
        $taskValue=$taskCredential.GetProperty('expires_at')
        if ($taskValue.ValueKind -ne [Text.Json.JsonValueKind]::String) { throw 'expiry unavailable' }
        $taskText=$taskValue.GetString()
        if ($taskText.Length -gt 64) { throw 'expiry bound' }
        $taskMatch=[regex]::Match($taskText,
            '\A(?<whole>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(?<fraction>\d{1,9}))?(?<offset>Z|[+-]\d{2}:\d{2})\z')
        if (-not $taskMatch.Success) {
            throw 'complete offset expiry required'
        }
        # The installed cache uses nanoseconds; floor only the decision value to
        # .NET's100ns precision. Never round expiry upward or alter auth bytes.
        $taskDecisionText=$taskMatch.Groups['whole'].Value
        $taskFraction=$taskMatch.Groups['fraction'].Value
        if ($taskFraction.Length) {
            $taskDecisionText+='.'+$taskFraction.Substring(0,[Math]::Min(7,$taskFraction.Length))
        }
        $taskDecisionText+=$taskMatch.Groups['offset'].Value
        $taskFormats=@("yyyy-MM-dd'T'HH:mm:ssK","yyyy-MM-dd'T'HH:mm:ss.FFFFFFFK")
        $taskExpiry=[DateTimeOffset]::ParseExact($taskDecisionText,[string[]]$taskFormats,
            [Globalization.CultureInfo]::InvariantCulture,[Globalization.DateTimeStyles]::None)
        if (($taskExpiry-[DateTimeOffset]::UtcNow).TotalSeconds -le 900) { throw 'fresh configured login required' }
        return $taskExpiry.ToUniversalTime()
    } finally { $taskDoc.Dispose() }
}

# Process capture is deliberately absent pending a reviewed family owner.
