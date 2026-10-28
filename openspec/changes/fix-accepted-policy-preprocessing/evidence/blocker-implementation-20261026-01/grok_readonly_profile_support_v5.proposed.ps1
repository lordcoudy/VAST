# Closed profile support. Definitions only; no copy/ACL/probe on load.
Set-StrictMode -Version Latest

function New-Pr9GrokProfileState {
    return @{
        Nodes=[Collections.Generic.List[object]]::new(128)
        Sources=[Collections.Generic.List[object]]::new(32)
        Copies=[Collections.Generic.List[object]]::new(32)
        Destinations=[Collections.Generic.List[object]]::new(32)
        Created=[Collections.Generic.List[string]]::new(64)
        ExtraDenied=[Collections.Generic.List[object]]::new(32)
        DirectoryNodes=[Collections.Generic.List[object]]::new(32)
        WriteHandles=[Collections.Generic.List[object]]::new(64)
        Probes=[Collections.Generic.List[object]]::new(9)
        Causes=[Collections.Generic.List[object]]::new(32)
        CauseOverflow=$false;DeniedNodes=0;WriteOpens=0;WriteCloses=0
        OperationStage='not_started';OperationOrdinal=0;CustodyQualification=$null
        PathProjection=$null
        BaseRoot='C:\Users\s-a-balashov\.g5'
        SourceRoot='C:\Users\s-a-balashov\.grok'
        ProfileRoot='C:\Users\s-a-balashov\.g5\a\p'
        OutputRoot='C:\Users\s-a-balashov\.g5\a\p-results'
    }
}
function Set-Pr9GrokProfileOperation {
    param($State,[string]$Code)
    if($Code -cnotmatch '\A[a-z_]{1,40}\z' -or $State.OperationOrdinal -ge 512){throw 'private operation stage bound'}
    $State.OperationStage=$Code+'_'+$State.OperationOrdinal.ToString('D3')
    $State.OperationOrdinal++
}
function Add-Pr9GrokProfileCause {
    param($State,[string]$Code,[Exception]$Failure)
    foreach($taskPrior in $State.Causes){if([Object]::ReferenceEquals($Failure,$taskPrior.failure)){return}}
    if($State.Causes.Count -ge 32){$State.CauseOverflow=$true;return}
    $State.Causes.Add([pscustomobject]@{code=$Code;failure=$Failure})
}
function Close-Pr9GrokProfileResource {
    param($State,[string]$Code,$Resource)
    if($null -ne $Resource){try{$Resource.Dispose()}catch{Add-Pr9GrokProfileCause $State $Code $_.Exception}}
}
function Assert-Pr9GrokProfileNoCause {
    param($State)
    if($State.Causes.Count -or $State.CauseOverflow){throw 'private profile operation unavailable'}
}
function Open-Pr9GrokProfileHeldNode {
    param($State,[string]$Path,[uint32]$Access=0x00020081)
    if($State.Nodes.Count -ge 128){throw 'profile held-node bound'}
    Set-Pr9GrokProfileOperation $State 'held_node_open'
    $taskNode=Open-Pr9ReadOnlyGrokNode -Path $Path -Access $Access
    $State.Nodes.Add($taskNode)
    return $taskNode
}
function New-Pr9GrokProfileDirectory {
    param($State,[string]$Path,[string]$Sid,[Diagnostics.Stopwatch]$Clock,[switch]$Deny)
    if($State.Created.Count -ge 64){throw 'private new-node ceiling'}
    Assert-Pr9GrokPreparationClock $Clock
    Set-Pr9GrokProfileOperation $State 'directory_create'
    [Pr9ReadOnlyGrokNativeV1]::MakePrivateDirectory($Path,$Sid)
    $State.Created.Add($Path)
    Assert-Pr9GrokPreparationClock $Clock
    Set-Pr9GrokProfileOperation $State 'directory_open'
    $taskNode=Open-Pr9GrokProfileHeldNode $State $Path
    if(($taskNode.Info.Attributes -band 0x10) -eq 0){throw 'private physical directory required'}
    $State.DirectoryNodes.Add($taskNode)
    if($Deny){$State.ExtraDenied.Add($taskNode)}
    return $taskNode
}
function Add-Pr9GrokProjectedNativePath {
    param($Projection,[string]$Literal,[bool]$Directory)
    if($Literal.Length -gt 1024){throw 'native projected input path bound'}
    $taskFull=[IO.Path]::GetFullPath($Literal)
    if($taskFull -cnotmatch '\A[Cc]:\\'){throw 'native projected literal C path required'}
    if(-not $Directory){
        if($taskFull.Length -gt 259 -or $Projection.Directories.Contains($taskFull)){throw 'native projected file path limit'}
        [void]$Projection.Files.Add($taskFull)
        if($Projection.Files.Count -gt 96){throw 'native projected file census'}
        $Projection.MaximumFile=[Math]::Max($Projection.MaximumFile,$taskFull.Length)
        $taskFull=[IO.Path]::GetDirectoryName($taskFull)
    }
    $taskDepth=0
    while(-not [string]::IsNullOrEmpty($taskFull)){
        if(++$taskDepth -gt 16 -or $taskFull.Length -gt 247 -or $Projection.Files.Contains($taskFull)){
            throw 'native projected directory path limit'
        }
        if(-not $Projection.Directories.Add($taskFull)){break}
        if($Projection.Directories.Count -gt 64){throw 'native projected directory census'}
        $Projection.MaximumDirectory=[Math]::Max($Projection.MaximumDirectory,$taskFull.Length)
        $taskFull=[IO.Path]::GetDirectoryName($taskFull)
    }
}
function Get-Pr9GrokNativePathProjection {
    param($State,$Roster,[string[]]$RelativeDirectories)
    $taskProjection=@{
        Files=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        Directories=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
        MaximumFile=0;MaximumDirectory=0
    }
    $taskSourceMax=0;$taskDestinationMax=0
    foreach($taskRow in $Roster.rows){
        $taskRelative=([string]$taskRow.path).Replace('/','\')
        $taskSource=[IO.Path]::GetFullPath([IO.Path]::Combine($State.SourceRoot,$taskRelative))
        $taskDestination=[IO.Path]::GetFullPath([IO.Path]::Combine($State.ProfileRoot,$taskRelative))
        Add-Pr9GrokProjectedNativePath $taskProjection $taskSource $false
        Add-Pr9GrokProjectedNativePath $taskProjection $taskDestination $false
        $taskSourceMax=[Math]::Max($taskSourceMax,$taskSource.Length)
        $taskDestinationMax=[Math]::Max($taskDestinationMax,$taskDestination.Length)
    }
    foreach($taskRelative in $RelativeDirectories){
        Add-Pr9GrokProjectedNativePath $taskProjection ([IO.Path]::Combine($State.SourceRoot,$taskRelative)) $true
        Add-Pr9GrokProjectedNativePath $taskProjection ([IO.Path]::Combine($State.ProfileRoot,$taskRelative)) $true
    }
    foreach($taskPath in @('C:\Python314','C:\Python314\DLLs','C:\Python314\Lib','C:\Python314\Lib\asyncio',
        'C:\Users\s-a-balashov\.codex','C:\Users\s-a-balashov\.codex\worktrees',
        $State.SourceRoot,([IO.Path]::Combine($State.SourceRoot,'bin')),$State.BaseRoot,
        ([IO.Path]::GetDirectoryName($State.ProfileRoot)),$State.ProfileRoot,$State.OutputRoot,
        ([IO.Path]::Combine($State.BaseRoot,'_custody')),([IO.Path]::Combine($State.BaseRoot,'_custody','child')))){
        Add-Pr9GrokProjectedNativePath $taskProjection $taskPath $true
    }
    foreach($taskRelative in @('_deny','_deny\dir-child','_deny\dir-rename','_deny\dir-renamed','_deny\new-directory','tmp-denied','logs')){
        Add-Pr9GrokProjectedNativePath $taskProjection ([IO.Path]::Combine($State.ProfileRoot,$taskRelative)) $true
    }
    foreach($taskRelative in @('_deny\write','_deny\delete','_deny\rename','_deny\renamed','_deny\new-file','_deny\replace-source','_deny\replace-target')){
        Add-Pr9GrokProjectedNativePath $taskProjection ([IO.Path]::Combine($State.ProfileRoot,$taskRelative)) $false
    }
    foreach($taskName in @('source4','copy4')){
        Add-Pr9GrokProjectedNativePath $taskProjection ([IO.Path]::Combine($State.BaseRoot,'_custody',$taskName)) $false
    }
    foreach($taskMode in @('inspect','plugin','mcp')){
        foreach($taskLabel in @('stdout','stderr')){
            Add-Pr9GrokProjectedNativePath $taskProjection ([IO.Path]::Combine($State.OutputRoot,$taskMode+'.'+$taskLabel+'.private')) $false
        }
    }
    foreach($taskPath in @('C:\Python314\python.exe','C:\Python314\Lib\asyncio\windows_utils.py',
        'C:\Python314\DLLs\_overlapped.pyd','C:\Users\s-a-balashov\.grok\bin\grok.exe')){
        Add-Pr9GrokProjectedNativePath $taskProjection $taskPath $false
    }
    return [pscustomobject]@{
        scope='complete_constructed_native_path_preflight_before_creation';complete=$true
        file_count=$taskProjection.Files.Count;directory_count=$taskProjection.Directories.Count
        maximum_source_member_utf16=$taskSourceMax;maximum_destination_member_utf16=$taskDestinationMax
        maximum_file_utf16=$taskProjection.MaximumFile;maximum_directory_utf16=$taskProjection.MaximumDirectory
        file_limit_utf16=259;directory_limit_utf16=247;private_creation_performed=$false
    }
}
function Get-Pr9GrokProfileExpectedTree {
    param($Roster,$State)
    if($Roster.schema_version -ne 1 -or $Roster.rows.Count -ne 32 -or
       $Roster.max_files -ne 32 -or $Roster.max_member_bytes -ne 2097152 -or
       $Roster.max_copy_bytes -ne 8388608 -or $Roster.max_new_nodes -ne 64){
        throw 'closed profile roster differs'
    }
    $taskNames=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $taskDirs=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $taskTotal=0
    foreach($taskRow in $Roster.rows){
        $taskRel=[string]$taskRow.path
        if($taskRel.Length -gt 512 -or $taskRel -notmatch '\A[A-Za-z0-9_./%\-]+\z' -or
           $taskRel.StartsWith('/') -or -not $taskNames.Add($taskRel)){
            throw 'private relative path shape'
        }
        $taskParts=$taskRel.Split('/')
        if($taskParts.Count -gt 8){throw 'private relative depth'}
        foreach($taskPart in $taskParts){
            if($taskPart -in @('','.','..') -or $taskPart.Length -gt 255 -or $taskPart.EndsWith('.')){
                throw 'private path component'
            }
        }
        if($taskRow.observed_bytes -lt 0 -or $taskRow.observed_bytes -gt 2097152){throw 'private member ceiling'}
        $taskTotal+=$taskRow.observed_bytes
        if($taskTotal -gt 8388608){throw 'private aggregate ceiling'}
        for($taskI=1;$taskI -lt $taskParts.Count;$taskI++){
            [void]$taskDirs.Add(($taskParts[0..($taskI-1)] -join '\'))
        }
    }
    if($taskDirs.Count -ne 6 -or $taskTotal -ne 5209749){throw 'closed private census differs'}
    $State.PathProjection=Get-Pr9GrokNativePathProjection -State $State -Roster $Roster -RelativeDirectories @($taskDirs)
    return [pscustomobject]@{Directories=@($taskDirs|Sort-Object Length);Bytes=$taskTotal}
}
function Copy-Pr9ClosedGrokProfile {
    param($State,$Roster,[string]$Sid,[Diagnostics.Stopwatch]$Clock)
    $taskTree=Get-Pr9GrokProfileExpectedTree $Roster $State
    if([IO.Path]::GetFullPath($Roster.source_root) -cne $State.SourceRoot -or
       [IO.Path]::GetFullPath($Roster.destination_root) -cne $State.ProfileRoot){
        throw 'literal profile roots required'
    }
    # Existing physical ancestors stay in custody. No original ACL is changed.
    foreach($taskPath in @('C:\','C:\Users','C:\Users\s-a-balashov','C:\Users\s-a-balashov\.codex',
        'C:\Users\s-a-balashov\.codex\worktrees',$State.SourceRoot)){
        Assert-Pr9GrokPreparationClock $Clock
        $taskNode=Open-Pr9GrokProfileHeldNode $State $taskPath
        if(($taskNode.Info.Attributes -band 0x10) -eq 0){throw 'physical source ancestor required'}
    }
    foreach($taskRel in $taskTree.Directories){
        $taskNode=Open-Pr9GrokProfileHeldNode $State ([IO.Path]::Combine($State.SourceRoot,$taskRel))
        if(($taskNode.Info.Attributes -band 0x10) -eq 0){throw 'physical source parent required'}
    }
    $taskStreamCount=0
    foreach($taskRow in $Roster.rows){
        Assert-Pr9GrokPreparationClock $Clock
        $taskPath=[IO.Path]::Combine($State.SourceRoot,([string]$taskRow.path).Replace('/','\'))
        $taskNode=Open-Pr9GrokProfileHeldNode $State $taskPath -Access 2147614720
        if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Links -ne 1 -or
           $taskNode.Info.Size -ne $taskRow.observed_bytes){throw 'source member identity/extent'}
        $taskSource=[pscustomobject]@{Node=$taskNode;Stream=$null;Relative=[string]$taskRow.path;Role=[string]$taskRow.private_role}
        $State.Sources.Add($taskSource)
        $taskSource.Stream=[IO.FileStream]::new($taskNode.Handle,[IO.FileAccess]::Read,4096,$false)
        $taskStreamCount++
    }
    if($taskStreamCount -ne 32){throw 'source held roster incomplete'}
    $taskAuth=@($State.Sources|Where-Object Relative -ceq 'auth.json')
    if($taskAuth.Count -ne 1){throw 'single credential source required'}
    $taskCredentialBytes=Read-Pr9GrokHeldSmallBytes -Stream $taskAuth[0].Stream -Length 1764 -Maximum 65536 -Clock $Clock
    try{$taskExpiry=Get-Pr9GrokCredentialExpiry -PrivateAuthBytes $taskCredentialBytes}
    finally{[Array]::Clear($taskCredentialBytes,0,$taskCredentialBytes.Length)}
    Assert-Pr9GrokPreparationClock $Clock
    # All32 source extents/parents and fresh expiry precede destination creation.
    foreach($taskPath in @('C:\Users\s-a-balashov\.g5',
        'C:\Users\s-a-balashov\.g5\a',$State.ProfileRoot)){
        [void](New-Pr9GrokProfileDirectory $State $taskPath $Sid $Clock -Deny)
    }
    [void](New-Pr9GrokProfileDirectory $State $State.OutputRoot $Sid $Clock)
    $State.CustodyQualification=Test-Pr9GrokReadonlyCustodyQualification $State $Sid $Clock
    foreach($taskRel in $taskTree.Directories){
        [void](New-Pr9GrokProfileDirectory $State ([IO.Path]::Combine($State.ProfileRoot,$taskRel)) $Sid $Clock -Deny)
    }
    foreach($taskSource in $State.Sources){
        Assert-Pr9GrokPreparationClock $Clock
        $taskPath=[IO.Path]::Combine($State.ProfileRoot,$taskSource.Relative.Replace('/','\'))
        if($State.Created.Count -ge 64){throw 'private node ceiling'}
        Set-Pr9GrokProfileOperation $State 'member_copy'
        $taskCopy=Copy-Pr9GrokHeldMember -Source $taskSource -Destination $taskPath -Clock $Clock
        $State.Created.Add($taskPath)
        $State.Copies.Add($taskCopy)
        $taskNode=Open-Pr9GrokProfileHeldNode $State $taskPath -Access 2147614720
        if($taskNode.Info.Volume -ne $taskCopy.PrivateIdentity.Volume -or $taskNode.Info.Index -ne $taskCopy.PrivateIdentity.Index -or
           $taskNode.Info.CreationLow -ne $taskSource.Node.Info.CreationLow -or $taskNode.Info.CreationHigh -ne $taskSource.Node.Info.CreationHigh -or
           $taskNode.Info.WriteLow -ne $taskSource.Node.Info.WriteLow -or $taskNode.Info.WriteHigh -ne $taskSource.Node.Info.WriteHigh){
            throw 'copied member custody identity differs'
        }
        $taskHeld=[pscustomobject]@{Node=$taskNode;Stream=$null;Copy=$taskCopy}
        $State.Destinations.Add($taskHeld)
        $taskHeld.Stream=[IO.FileStream]::new($taskNode.Handle,[IO.FileAccess]::Read,4096,$false)
    }
    foreach($taskRel in @('_deny','_deny\dir-child','_deny\dir-rename','tmp-denied','logs')){
        [void](New-Pr9GrokProfileDirectory $State ([IO.Path]::Combine($State.ProfileRoot,$taskRel)) $Sid $Clock -Deny)
    }
    foreach($taskName in @('write','delete','rename','replace-source','replace-target')){
        $taskPath=[IO.Path]::Combine($State.ProfileRoot,'_deny',$taskName)
        if($State.Created.Count -ge 64){throw 'private node ceiling'}
        Set-Pr9GrokProfileOperation $State 'sentinel_create'
        Write-Pr9GrokPrivateFixedBytes -Path $taskPath -Bytes ([byte[]](65,66,67,10)) -Maximum 4 -Clock $Clock
        $State.Created.Add($taskPath)
        $taskNode=Open-Pr9GrokProfileHeldNode $State $taskPath
        if(($taskNode.Info.Attributes -band 0x10) -ne 0 -or $taskNode.Info.Size -ne 4 -or $taskNode.Info.Links -ne 1){
            throw 'single-link sentinel extent differs'
        }
        $State.ExtraDenied.Add($taskNode) # Denial list also carries fixed sentinels.
    }
    $taskDeny=@($State.ExtraDenied)+@($State.Destinations|ForEach-Object{$_.Node})
    if($taskDeny.Count -ne 55){throw 'denied node census differs'}
    foreach($taskNode in $taskDeny){
        Assert-Pr9GrokPreparationClock $Clock
        try{
            Set-Pr9GrokProfileOperation $State 'denial_writer_open'
            $taskWriter=Open-Pr9ReadOnlyGrokNode -Path $taskNode.Path -Access 0x00060080
            $State.WriteHandles.Add($taskWriter.Handle);$State.WriteOpens++
            if($taskWriter.Info.Volume -ne $taskNode.Info.Volume -or $taskWriter.Info.Index -ne $taskNode.Info.Index -or
               (($taskWriter.Info.Attributes -band 0x10) -eq 0 -and $taskWriter.Info.Links -ne 1)){
                throw 'denial target custody differs'
            }
            Assert-Pr9GrokPreparationClock $Clock
        }catch{
            Add-Pr9GrokProfileCause $State 'denial_writer_preopen' $_.Exception
            throw
        }
    }
    # Parent ACL propagation can remove inherited child grants. All55 writer
    # handles are already authorized and identity-joined before any ACL change.
    if($State.WriteOpens -ne 55){throw 'preopened writer census incomplete'}
    try{
        for($taskI=0;$taskI -lt $taskDeny.Count;$taskI++){
            Assert-Pr9GrokPreparationClock $Clock
            Set-Pr9GrokProfileOperation $State 'denial_apply'
            [Pr9ReadOnlyGrokNativeV1]::DenyWrites($State.WriteHandles[$taskI],$Sid,(($taskDeny[$taskI].Info.Attributes -band 0x10) -ne 0))
            $State.DeniedNodes++
        }
    }catch{
        Add-Pr9GrokProfileCause $State 'denial_apply' $_.Exception
        throw
    }finally{
        foreach($taskHandle in $State.WriteHandles){
            try{$taskHandle.Dispose();$State.WriteCloses++}
            catch{Add-Pr9GrokProfileCause $State 'write_dac_close' $_.Exception}
        }
    }
    Assert-Pr9GrokProfileNoCause $State
    if($State.WriteOpens -ne 55 -or $State.WriteCloses -ne 55 -or
       @($State.WriteHandles|Where-Object{-not $_.IsClosed}).Count){throw 'write-capable custody remains'}
    return [pscustomobject]@{Members=32;LogicalBytes=$taskTree.Bytes;DeniedNodes=55;Expiry=$taskExpiry}
}
function Test-Pr9ClosedGrokProfile {
    param($State,[string]$Sid,[Diagnostics.Stopwatch]$Clock)
    foreach($taskNode in $State.Nodes){
        Assert-Pr9GrokPreparationClock $Clock
        Test-Pr9ReadOnlyGrokNodeIdentity -Node $taskNode
    }
    foreach($taskDestination in $State.Destinations){
        Test-Pr9ReadOnlyGrokNodeIdentity -Node $taskDestination.Node -File
        $taskDigest=Get-Pr9GrokPrivateFingerprint -Stream $taskDestination.Stream -Length $taskDestination.Copy.Bytes -Clock $Clock
        if(-not [Pr9ReadOnlyGrokNativeV1]::SameBytes($taskDigest,$taskDestination.Copy.PrivateFingerprint)){
            throw 'private copy changed'
        }
    }
    $taskDeny=@($State.ExtraDenied)+@($State.Destinations|ForEach-Object{$_.Node})
    foreach($taskNode in $taskDeny){
        if(-not [Pr9ReadOnlyGrokNativeV1]::DenialMatches($taskNode.Handle,$Sid,(($taskNode.Info.Attributes -band 0x10) -ne 0))){
            throw 'protected denial differs'
        }
    }
    foreach($taskSource in $State.Sources){Test-Pr9ReadOnlyGrokNodeIdentity -Node $taskSource.Node -File}
    if($State.Created.Count -gt 64){throw 'private node count'}
    $taskExpected=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($taskPath in $State.Created){[void]$taskExpected.Add($taskPath)}
    $taskSeen=[Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach($taskDirectory in $State.DirectoryNodes){
        $taskIterator=$null
        try{
            $taskIterator=[IO.Directory]::EnumerateFileSystemEntries($taskDirectory.Path).GetEnumerator()
            while($taskIterator.MoveNext()){
                Assert-Pr9GrokPreparationClock $Clock
                if($taskSeen.Count -ge 64 -or -not $taskExpected.Contains($taskIterator.Current) -or
                   -not $taskSeen.Add($taskIterator.Current)){throw 'private directory inventory differs'}
            }
        }catch{
            Add-Pr9GrokProfileCause $State 'directory_inventory' $_.Exception
            throw
        }finally{Close-Pr9GrokProfileResource $State 'directory_iterator_close' $taskIterator}
        Assert-Pr9GrokProfileNoCause $State
    }
    # The new top-level VAST root is pinned rather than found in its old parent.
    if($taskSeen.Count -ne $taskExpected.Count-1){throw 'private directory census incomplete'}
    return [pscustomobject]@{HeldNodes=$State.Nodes.Count;MembersUnchanged=32;DenialsUnchanged=$taskDeny.Count}
}
function Get-Pr9SentinelDenialCode {
    param([Exception]$Failure)
    $taskCurrent=$Failure
    for($taskI=0;$taskI -lt 5 -and $null -ne $taskCurrent;$taskI++){
        if($taskCurrent -is [ComponentModel.Win32Exception]){return $taskCurrent.NativeErrorCode}
        if($taskCurrent -is [UnauthorizedAccessException]){return 5}
        if($taskCurrent -is [IO.IOException]){return ($taskCurrent.HResult -band 65535)}
        $taskCurrent=$taskCurrent.InnerException
    }
    return $null
}
function Invoke-Pr9FixedSentinelDenial {
    param($State,[ValidateSet('write','append','new-file','new-directory','delete','replace','rename-file','rename-directory','write-dac')][string]$Kind,
        [string]$Sid,[Diagnostics.Stopwatch]$Clock)
    Assert-Pr9GrokPreparationClock $Clock
    if($State.Probes.Count -ge 9){throw 'sentinel result ceiling'}
    Set-Pr9GrokProfileOperation $State 'sentinel_probe'
    $taskFact=[pscustomobject]@{
        kind=$Kind;attempted=$false;operation_returned=$false;observed_code=$null;denied_code=$null
        exception_type=$null;hresult=$null;unexpected_success=$false
        close_attempted=$false;close_completed=$null;complete=$false
    }
    $State.Probes.Add($taskFact)
    $taskBase=[IO.Path]::Combine($State.ProfileRoot,'_deny')
    $taskOpened=$null;$taskPrimary=$null;$taskClose=$null;$taskDenied=$null
    try{
        $taskFact.attempted=$true
        switch($Kind){
            'write'{$taskOpened=[Pr9ReadOnlyGrokNativeV1]::Open([IO.Path]::Combine($taskBase,'write'),0x40000000)}
            'append'{$taskOpened=[Pr9ReadOnlyGrokNativeV1]::Open([IO.Path]::Combine($taskBase,'write'),4)}
            'new-file'{$taskOpened=[IO.File]::Open([IO.Path]::Combine($taskBase,'new-file'),'CreateNew','Write','Read')}
            'new-directory'{[Pr9ReadOnlyGrokNativeV1]::MakePrivateDirectory([IO.Path]::Combine($taskBase,'new-directory'),$Sid)}
            'delete'{[IO.File]::Delete([IO.Path]::Combine($taskBase,'delete'))}
            'replace'{[IO.File]::Replace([IO.Path]::Combine($taskBase,'replace-source'),[IO.Path]::Combine($taskBase,'replace-target'),[NullString]::Value)}
            'rename-file'{[IO.File]::Move([IO.Path]::Combine($taskBase,'rename'),[IO.Path]::Combine($taskBase,'renamed'))}
            'rename-directory'{[IO.Directory]::Move([IO.Path]::Combine($taskBase,'dir-rename'),[IO.Path]::Combine($taskBase,'dir-renamed'))}
            'write-dac'{$taskOpened=[Pr9ReadOnlyGrokNativeV1]::Open([IO.Path]::Combine($taskBase,'write'),0x00040000)}
        }
        $taskFact.operation_returned=$true;$taskFact.unexpected_success=$true
        $taskPrimary=[InvalidOperationException]::new('sentinel unexpectedly permitted')
    }catch{
        $taskCode=Get-Pr9SentinelDenialCode $_.Exception
        $taskFact.observed_code=$taskCode
        $taskType=$_.Exception.GetType().FullName
        if($taskType.Length -gt 128 -or $taskType -cnotmatch '\A[A-Za-z0-9_.+]{1,128}\z'){$taskType='bounded_unknown_exception_type'}
        $taskFact.exception_type=$taskType;$taskFact.hresult=$_.Exception.HResult
        if($taskCode -in @(5,32) -and ($Kind -ne 'write-dac' -or $taskCode -eq 5)){
            $taskDenied=$taskCode;$taskFact.denied_code=$taskCode
        }else{$taskPrimary=$_.Exception}
    }finally{
        if($null -ne $taskOpened){
            $taskFact.close_attempted=$true
            try{$taskOpened.Dispose();$taskFact.close_completed=$true}
            catch{$taskClose=$_.Exception;$taskFact.close_completed=$false}
        }
    }
    if($null -eq $taskPrimary -and $null -ne $taskClose){$taskPrimary=$taskClose;$taskClose=$null}
    if($null -ne $taskPrimary){
        Add-Pr9GrokProfileCause $State ('denial_'+$Kind) $taskPrimary
        if($null -ne $taskClose){Add-Pr9GrokProfileCause $State 'probe_close' $taskClose}
        throw 'fixed denial probe refused'
    }
    if($null -eq $taskDenied){throw 'denial unavailable'}
    Assert-Pr9GrokPreparationClock $Clock
    $taskFact.complete=$true
}
function Close-Pr9ClosedGrokProfile {
    param($State)
    foreach($taskSource in $State.Sources){Close-Pr9GrokProfileResource $State 'source_stream_close' $taskSource.Stream}
    foreach($taskDestination in $State.Destinations){Close-Pr9GrokProfileResource $State 'copy_stream_close' $taskDestination.Stream}
    foreach($taskHandle in $State.WriteHandles){Close-Pr9GrokProfileResource $State 'write_dac_close' $taskHandle}
    for($taskI=$State.Nodes.Count-1;$taskI -ge 0;$taskI--){
        Close-Pr9GrokProfileResource $State 'custody_close' $State.Nodes[$taskI].Handle
    }
}
# Private fingerprints, expiry and paths are controller state, never JSON output.
