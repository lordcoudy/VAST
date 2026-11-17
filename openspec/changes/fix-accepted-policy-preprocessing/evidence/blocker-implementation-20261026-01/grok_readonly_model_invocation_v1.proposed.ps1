# Definitions only. Public source capture/packing is not execution admission.
Set-StrictMode -Version Latest

function New-Pr9ReadOnlyModelInvocation {
    param([Parameter(Mandatory)][long]$DeadlineTickMs,[Parameter(Mandatory)][ValidateSet('diagnostic04','preflight04','preflight05','review05')][string]$Mode)
    $taskClockRemaining=$DeadlineTickMs-[Environment]::TickCount64
    if ($taskClockRemaining -le 0 -or $taskClockRemaining -gt $(if($Mode -ceq 'review05'){600000}else{60000})) { throw 'original control deadline required' }
    $taskRoot='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
    if ((Get-Location).Path -cne $taskRoot) { throw 'fixed C worktree required' }
    $taskBase='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01'
    $taskPins=@(
        @('owner','grok_reviewed_job_definitions_v1.proposed.py',7981,'54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3'),
        @('capture','grok_windows_model_capture_v1.proposed.py',28548,'5780f41dc09c6e8279646f0cff9ad4eed3554cf5b9908febcf1e1dfd4b517b5a'),
        @('driver','grok_readonly_model_driver_v1.proposed.py',26299,'fe8b1ab9ed1bd7a4238bda882db64bda6bd7d6883fd95b418b27efa26877b505')
    )
    $taskRows=@();$taskSum=0
    foreach($taskPin in $taskPins) {
        $taskPath=Join-Path (Join-Path $taskRoot $taskBase) $taskPin[1]
        $taskStream=$null;$taskPrimary=$null;$taskCloseError=$null
        try {
            $taskStream=[IO.File]::Open($taskPath,'Open','Read','Read')
            if ($taskStream.Length -ne $taskPin[2] -or $taskStream.Length -gt 32768) { throw 'fixed public source extent differs' }
            $taskBytes=[byte[]]::new([int]$taskStream.Length)
            $taskOffset=0
            while($taskOffset -lt $taskBytes.Length) {
                if ([Environment]::TickCount64 -ge $DeadlineTickMs-15000) { throw 'source capture deadline' }
                $taskCount=$taskStream.Read($taskBytes,$taskOffset,$taskBytes.Length-$taskOffset)
                if($taskCount -le 0){throw 'public source shrink'}
                $taskOffset+=$taskCount
            }
            if($taskStream.ReadByte() -ne -1){throw 'public source growth'}
            $taskHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskBytes)).ToLowerInvariant()
            if($taskHash -cne $taskPin[3]){throw 'reviewed public source differs'}
            $taskSum+=$taskBytes.Length
            if($taskSum -gt 98304){throw 'public source aggregate bound'}
            $taskRows+=,[ordered]@{role=$taskPin[0];text=[Text.UTF8Encoding]::new($false,$true).GetString($taskBytes);bytes=$taskBytes.Length;sha256=$taskHash}
        } catch { $taskPrimary=$_.Exception }
        finally { if($null -ne $taskStream){try{$taskStream.Dispose()}catch{$taskCloseError=$_.Exception}} }
        if($null -eq $taskPrimary -and $null -ne $taskCloseError){$taskPrimary=$taskCloseError;$taskCloseError=$null}
        if($null -ne $taskPrimary -or $null -ne $taskCloseError) {
            $taskError=[InvalidOperationException]::new('public source capture refused',$taskPrimary)
            $taskError.Data['private_close']=$taskCloseError
            throw $taskError
        }
    }
    $taskRaw=[Text.Encoding]::UTF8.GetBytes(($taskRows|ConvertTo-Json -Depth 4 -Compress))
    if($taskRaw.Length -gt 262144){throw 'public literal packet bound'}
    $taskMemory=[IO.MemoryStream]::new()
    $taskZlib=$null;$taskPrimary=$null;$taskSecondary=[Collections.Generic.List[Exception]]::new();$taskCompressed=$null
    try {
        $taskZlib=[IO.Compression.ZLibStream]::new($taskMemory,[IO.Compression.CompressionLevel]::SmallestSize,$true)
        $taskZlib.Write($taskRaw,0,$taskRaw.Length)
    } catch { $taskPrimary=$_.Exception }
    finally {
        if($null -ne $taskZlib){try{$taskZlib.Dispose()}catch{$taskSecondary.Add($_.Exception)}}
    }
    try {
        if($null -eq $taskPrimary -and $taskSecondary.Count -eq 0){$taskCompressed=$taskMemory.ToArray()}
    } catch { $taskPrimary=$_.Exception }
    finally { try{$taskMemory.Dispose()}catch{$taskSecondary.Add($_.Exception)} }
    $taskDistinct=[Collections.Generic.List[Exception]]::new()
    foreach($taskCause in $taskSecondary){
        if($null -eq $taskPrimary){$taskPrimary=$taskCause;continue}
        if([Object]::ReferenceEquals($taskCause,$taskPrimary)){continue}
        $taskSeen=$false
        foreach($taskPrior in $taskDistinct){if([Object]::ReferenceEquals($taskCause,$taskPrior)){$taskSeen=$true;break}}
        if(-not $taskSeen){$taskDistinct.Add($taskCause)}
    }
    if($null -ne $taskPrimary -or $taskDistinct.Count -gt 0) {
        $taskError=[InvalidOperationException]::new('public source compression refused',$taskPrimary)
        $taskError.Data['private_secondary']=$taskDistinct.ToArray()
        throw $taskError
    }
    if($taskCompressed.Length -gt 16384){throw 'compressed literal bound'}
    $taskPayload=[Convert]::ToBase64String($taskCompressed)
    $taskPacketHash=[Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskRaw)).ToLowerInvariant()
    $taskBootstrap=@'
import base64,hashlib,json,os,sys,zlib
stage=b'decode'
try:
 p=sys.argv[1]
 if len(sys.argv)!=5 or len(p)>21848:raise ValueError()
 c=base64.b64decode(p,validate=True)
 if len(c)>16384:raise ValueError()
 z=zlib.decompressobj();r=z.decompress(c,262145)
 if len(r)>262144 or not z.eof or z.unused_data or z.unconsumed_tail:raise ValueError()
 if hashlib.sha256(r).hexdigest()!=sys.argv[3]:raise ValueError()
 stage=b'pins'
 rows=json.loads(r)
 pins=(('owner',7981,'54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3'),('capture',28548,'5780f41dc09c6e8279646f0cff9ad4eed3554cf5b9908febcf1e1dfd4b517b5a'),('driver',26299,'fe8b1ab9ed1bd7a4238bda882db64bda6bd7d6883fd95b418b27efa26877b505'))
 if type(rows)is not list or len(rows)!=3:raise ValueError()
 code=[];actual=[]
 for v,(role,size,sha) in zip(rows,pins):
  if type(v)is not dict or set(v)!=set(('role','text','bytes','sha256')):raise ValueError()
  if v['role']!=role or type(v['text'])is not str or len(v['text'])>32768:raise ValueError()
  b=v['text'].encode('utf-8')
  if type(v['bytes'])is not int or v['bytes']!=size or len(b)!=size or v['sha256']!=sha or hashlib.sha256(b).hexdigest()!=sha:raise ValueError()
  code.append(b);actual.append({'role':role,'bytes':size,'sha256':sha})
 deadline=sys.argv[2]
 if not deadline.isascii() or not deadline.isdecimal() or len(deadline)>20:raise ValueError()
 h={'__name__':'_pr9_grok_family_capture'};d={'__name__':'_pr9_grok_family_controls'}
 stage=b'helper'
 exec(compile(code[1],'authenticated-family-capture','exec'),h)
 stage=b'driver'
 exec(compile(code[2],'authenticated-family-controls','exec'),d)
 stage=b'runtime_control_receipt'
 mode=sys.argv[4]
 if mode not in ('diagnostic04','preflight04','preflight05','review05'):raise ValueError()
 os._exit(d['run_model'](h,code[0],actual,int(deadline),mode))
except BaseException:
 if stage==b'runtime_control_receipt':
  value=d.get('CONTROLLER_STAGE')
  stage=value.encode('ascii') if value in ('runtime','environment','startup','preflight','owner','capture','result') else b'driver_stage_unknown'
 try:os.write(2,b'controller_refused:'+stage+b'\n')
 except BaseException:pass
 os._exit(1)
'@
    if($taskBootstrap.Contains('"') -or $taskBootstrap.EndsWith('\')){throw 'literal quoting premise differs'}
    # Only the bootstrap needs outer quotes; Base64/decimal/hex arguments have no
    # whitespace or quote characters. Leave a conservative256-unit prefix margin.
    $taskArgvUpper=$taskBootstrap.Length+2+$taskPayload.Length+20+64+16+256
    if($taskArgvUpper -gt 30000){throw 'Windows literal command-line bound'}
    if([Environment]::TickCount64 -ge $DeadlineTickMs-15000){throw 'literal preparation deadline'}
    return [pscustomobject]@{
        Executable='C:\Python314\python.exe'
        Arguments=[string[]]@('-I','-B','-S','-c',$taskBootstrap,$taskPayload,[string]$DeadlineTickMs,$taskPacketHash,$Mode)
        SourcePins=@($taskRows|ForEach-Object{[ordered]@{role=$_.role;bytes=$_.bytes;sha256=$_.sha256}})
        SourceBytes=$taskSum;PacketBytes=$taskRaw.Length;CompressedBytes=$taskCompressed.Length
        Base64Characters=$taskPayload.Length;WindowsArgvUpperUtf16=$taskArgvUpper
        PacketSha256=$taskPacketHash;DeadlineTickMs=$DeadlineTickMs
    }
}
