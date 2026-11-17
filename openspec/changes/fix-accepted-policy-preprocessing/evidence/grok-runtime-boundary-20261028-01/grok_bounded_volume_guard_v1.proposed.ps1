# Fixed read-only Windows metadata qualifier for PR9's prospective review volume.
# No create/attach/initialize/format/mount/assign/delete/configuration operation.
# Source-only library. The separately reviewed elevated caller supplies one
# original deadline, authenticates this source before parsing and retains output.
Set-StrictMode -Version Latest

function Initialize-Pr9GrokVolumeMetadataNative {
    if ('Pr9GrokVolumeMetadataV1' -as [type]) { throw 'preloaded metadata type refused' }
    Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

public static class Pr9GrokVolumeMetadataV1 {
    public sealed class CompletedReadCloseException : Exception {
        public object ReturnedValue { get; private set; }
        internal CompletedReadCloseException(object value,Exception closing)
            : base("read completed but owned handle close failed",closing) { ReturnedValue=value; }
    }
    [StructLayout(LayoutKind.Sequential, Pack=4)]
    struct Basic { public uint Attr,C1,C2,A1,A2,W1,W2,Serial,SizeHi,SizeLo,Links,IdHi,IdLo; }
    [StructLayout(LayoutKind.Sequential)]
    struct Standard {
        public long Allocation,End;
        public uint Links;
        [MarshalAs(UnmanagedType.U1)] public bool DeletePending;
        [MarshalAs(UnmanagedType.U1)] public bool Directory;
    }
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern IntPtr CreateFileW(string path,uint access,uint share,IntPtr sa,uint disposition,uint flags,IntPtr template);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool GetFileInformationByHandle(IntPtr handle,out Basic info);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool GetFileInformationByHandleEx(IntPtr handle,int kind,out Standard info,uint size);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern bool GetVolumeInformationByHandleW(IntPtr handle,StringBuilder name,uint nameSize,out uint serial,out uint maxName,out uint flags,StringBuilder fs,uint fsSize);
    [DllImport("kernel32.dll",SetLastError=true)]
    static extern bool DeviceIoControl(IntPtr handle,uint code,IntPtr input,uint inputSize,byte[] output,uint outputSize,out uint returned,IntPtr overlapped);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]
    static extern uint QueryDosDeviceW(string name,StringBuilder target,int maximum);
    static Exception Error() { return new Win32Exception(Marshal.GetLastWin32Error()); }
    static Exception CloseOwned(IntPtr handle) {
        if(CloseHandle(handle)) return null;
        return Error();
    }
    static T WithHandle<T>(string path,uint access,uint flags,Func<IntPtr,T> read,Func<IntPtr,Exception> closer=null) {
        IntPtr handle=CreateFileW(path,access,3,IntPtr.Zero,3,flags,IntPtr.Zero);
        if(handle==new IntPtr(-1)) throw Error();
        Exception primary=null; T value=default(T);
        try { value=read(handle); } catch(Exception error) { primary=error; }
        // No retry of an ambiguously closed handle; preserve distinct causes.
        Exception closing=null;
        try { closing=(closer ?? CloseOwned)(handle); } catch(Exception error) { closing=error; }
        if(primary!=null && closing!=null) throw new AggregateException(primary,closing);
        if(primary!=null) throw primary;
        if(closing!=null) throw new CompletedReadCloseException(value,closing);
        return value;
    }
    public static bool VAbsent() {
        var target=new StringBuilder(4096);
        if(QueryDosDeviceW("V:",target,target.Capacity)!=0) return false;
        int error=Marshal.GetLastWin32Error();
        if(error==2) return true;
        throw new Win32Exception(error);
    }
    public static Dictionary<string,object> FileMetadata(string path) {
        // READ_ATTRIBUTES only; no payload access, mutation or backup privilege.
        return WithHandle(path,0x80,0x02200000,h=>{
            Basic basic; Standard standard;
            if(!GetFileInformationByHandle(h,out basic)) throw Error();
            if(!GetFileInformationByHandleEx(h,1,out standard,(uint)Marshal.SizeOf<Standard>())) throw Error();
            if(standard.End<0 || standard.Allocation<0 || standard.Links!=basic.Links ||
                (ulong)standard.End!=((ulong)basic.SizeHi<<32 | basic.SizeLo))
                throw new InvalidDataException("inconsistent metadata");
            return new Dictionary<string,object>{
                {"path",path},{"volume_serial",basic.Serial.ToString("x8")},
                {"file_id",((ulong)basic.IdHi<<32 | basic.IdLo).ToString("x16")},
                {"attributes",basic.Attr},{"links",standard.Links},
                {"eof",standard.End},{"allocation",standard.Allocation},
                {"delete_pending",standard.DeletePending},{"directory",standard.Directory}
            };
        });
    }
    public static Dictionary<string,object> NtfsE() {
        return WithHandle(@"\\.\E:",0x80000000,0,h=>{
            var label=new StringBuilder(261); var fs=new StringBuilder(64);
            uint serial,maxName,flags;
            if(!GetVolumeInformationByHandleW(h,label,(uint)label.Capacity,out serial,out maxName,out flags,fs,(uint)fs.Capacity)) throw Error();
            if(fs.ToString()!="NTFS") throw new InvalidDataException("NTFS required");
            var ntfs=new byte[96]; uint count;
            if(!DeviceIoControl(h,0x00090064,IntPtr.Zero,0,ntfs,(uint)ntfs.Length,out count,IntPtr.Zero)) throw Error();
            if(count!=96) throw new InvalidDataException("NTFS metadata extent");
            var result=new Dictionary<string,object>{
                {"volume_serial",serial.ToString("x8")},{"ntfs_serial",BitConverter.ToUInt64(ntfs,0).ToString("x16")},{"filesystem",fs.ToString()},
                {"sectors",BitConverter.ToInt64(ntfs,8)},{"clusters",BitConverter.ToInt64(ntfs,16)},
                {"free_clusters",BitConverter.ToInt64(ntfs,24)},{"reserved_clusters",BitConverter.ToInt64(ntfs,32)},
                {"bytes_per_sector",BitConverter.ToUInt32(ntfs,40)},{"bytes_per_cluster",BitConverter.ToUInt32(ntfs,44)},
                {"bytes_per_file_record",BitConverter.ToUInt32(ntfs,48)},{"clusters_per_file_record",BitConverter.ToUInt32(ntfs,52)},
                {"mft_valid_bytes",BitConverter.ToInt64(ntfs,56)},{"mft_start_lcn",BitConverter.ToInt64(ntfs,64)},
                {"mft_mirror_lcn",BitConverter.ToInt64(ntfs,72)},{"mft_zone_start",BitConverter.ToInt64(ntfs,80)},
                {"mft_zone_end",BitConverter.ToInt64(ntfs,88)}
            };
            var usn=new byte[80];
            if(DeviceIoControl(h,0x000900f4,IntPtr.Zero,0,usn,(uint)usn.Length,out count,IntPtr.Zero)) {
                if(count<56 || count>80) throw new InvalidDataException("USN metadata extent");
                result["usn_active"]=true;
                result["usn_maximum_bytes"]=BitConverter.ToUInt64(usn,40);
                result["usn_allocation_delta_bytes"]=BitConverter.ToUInt64(usn,48);
            } else {
                int error=Marshal.GetLastWin32Error();
                if(error!=1179) throw new Win32Exception(error);
                result["usn_active"]=false;result["usn_query_error"]=error;
            }
            return result;
        });
    }
}
'@
}

function Get-Pr9GrokVolumeMetadataFailure([Exception]$ErrorValue,[string]$Operation) {
    $errors=[Collections.Generic.List[object]]::new()
    $queue=[Collections.Generic.Queue[Exception]]::new()
    $queue.Enqueue($ErrorValue);$queued=1;$exceeded=$false
    $seen=[Collections.Generic.List[Exception]]::new();$returned=$null;$returnedAvailable=$false
    while ($queue.Count -gt 0) {
        if ($errors.Count -ge 16) { return [ordered]@{operation=$Operation;complete=$false;cause_bound_exceeded=$true;causes=$errors.ToArray();returned_facts_available=$returnedAvailable;returned_facts=$returned} }
        $current=$queue.Dequeue()
        $duplicate=$false
        foreach ($prior in $seen) {if([object]::ReferenceEquals($prior,$current)){$duplicate=$true;break}}
        if($duplicate){continue}
        $seen.Add($current)
        if($current.GetType().FullName -ceq 'Pr9GrokVolumeMetadataV1+CompletedReadCloseException') {
            $returned=$current.ReturnedValue;$returnedAvailable=$true
        }
        $nativeCode=if($current -is [ComponentModel.Win32Exception]){$current.NativeErrorCode}else{$null}
        $errors.Add([ordered]@{type=$current.GetType().FullName;native_error=$nativeCode})
        if ($current -is [AggregateException]) {
            foreach ($inner in $current.InnerExceptions) {
                if ($queued -ge 16) { $exceeded=$true;break }
                $queue.Enqueue($inner);$queued++
            }
        } elseif ($null -ne $current.InnerException) {
            if ($queued -ge 16) { $exceeded=$true } else {$queue.Enqueue($current.InnerException);$queued++}
        }
    }
    [ordered]@{operation=$Operation;complete=$false;cause_bound_exceeded=$exceeded;causes=$errors.ToArray();returned_facts_available=$returnedAvailable;returned_facts=$returned}
}

function New-Pr9GrokVolumeMetadataObservation {
    param([Parameter(Mandatory)][string]$Operation,[Parameter(Mandatory)]$Value,
        [Parameter(Mandatory)][long]$ObservedTick,[Parameter(Mandatory)][long]$OriginalDeadlineTick)
    $late=$ObservedTick -ge $OriginalDeadlineTick
    # Preserve the actual returned object even when its observation is late.
    [ordered]@{operation=$Operation;complete=(-not $late);deadline_exceeded=$late;facts=$Value}
}

function Invoke-Pr9GrokVolumeMetadataInitialization {
    param([Parameter(Mandatory)][long]$OriginalDeadlineTick,
        [scriptblock]$Now={[Environment]::TickCount64},
        [scriptblock]$Load={Initialize-Pr9GrokVolumeMetadataNative})
    $observed=& $Now
    if ($observed -ge $OriginalDeadlineTick) { return $false }
    $null=& $Load
    return $true
}

function Get-Pr9GrokReviewVolumeMetadata {
    param([Parameter(Mandatory)][long]$OriginalDeadlineTick)
    $start=[Environment]::TickCount64
    if ($OriginalDeadlineTick -le $start -or $OriginalDeadlineTick-$start -gt 180000) { throw 'original metadata deadline required' }
    $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
    $elevated=$false;$sid=$null
    try {
        $sid=$identity.User.Value
        $principal=[Security.Principal.WindowsPrincipal]::new($identity)
        $elevated=$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    } finally { $identity.Dispose() }
    if (-not $elevated -or $sid -cne 'S-1-5-21-3110146144-1192974603-3912567380-24130') {
        throw 'actual elevated original principal required for read-only qualification'
    }
    $records=[Collections.Generic.List[object]]::new()
    $complete=$true;$deadlineExceeded=$false
    $initialized=$false
    try {
        $initialized=Invoke-Pr9GrokVolumeMetadataInitialization -OriginalDeadlineTick $OriginalDeadlineTick
        if (-not $initialized) {
            $complete=$false;$deadlineExceeded=$true
            $records.Add([ordered]@{operation='native_initialization';complete=$false;deadline_exceeded=$true;native_loaded=$false})
        }
    } catch {
        $complete=$false
        $records.Add((Get-Pr9GrokVolumeMetadataFailure $_.Exception 'native_initialization'))
    }
    $operations=if($initialized){@('v_namespace','ntfs_E','E_MFT','E_logfile','E_secure','E_parent')}else{@()}
    foreach ($operation in $operations) {
        if ([Environment]::TickCount64 -ge $OriginalDeadlineTick) { $complete=$false;$deadlineExceeded=$true;break }
        try {
            $value=switch ($operation) {
                'v_namespace' { [ordered]@{absent=[Pr9GrokVolumeMetadataV1]::VAbsent()} }
                'ntfs_E' { [Pr9GrokVolumeMetadataV1]::NtfsE() }
                'E_MFT' { [Pr9GrokVolumeMetadataV1]::FileMetadata('E:\$MFT') }
                'E_logfile' { [Pr9GrokVolumeMetadataV1]::FileMetadata('E:\$LogFile') }
                'E_secure' { [Pr9GrokVolumeMetadataV1]::FileMetadata('E:\$Secure') }
                'E_parent' { [Pr9GrokVolumeMetadataV1]::FileMetadata('E:\VAST-pr9') }
            }
            $observation=New-Pr9GrokVolumeMetadataObservation -Operation $operation -Value $value -ObservedTick ([Environment]::TickCount64) -OriginalDeadlineTick $OriginalDeadlineTick
            $records.Add($observation)
            if ($observation.deadline_exceeded) {$complete=$false;$deadlineExceeded=$true;break}
        } catch {
            $complete=$false
            $records.Add((Get-Pr9GrokVolumeMetadataFailure $_.Exception $operation))
        }
    }
    $finish=[Environment]::TickCount64
    if ($finish -ge $OriginalDeadlineTick) {$complete=$false;$deadlineExceeded=$true}
    [ordered]@{
        scope='read_only_review_volume_metadata'
        sid=$sid;elevated=$elevated;complete=$complete;records=$records.ToArray()
        original_deadline_tick_ms=$OriginalDeadlineTick;finished_tick_ms=$finish;deadline_exceeded=$deadlineExceeded
        storage_effects=0;configuration_changes=0;capacity_accepted=$false;application_authority=$false
    }
}
