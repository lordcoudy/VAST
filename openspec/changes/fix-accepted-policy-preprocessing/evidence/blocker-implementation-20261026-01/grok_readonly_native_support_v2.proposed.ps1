# Proposed native support for the fixed B3 read-only Grok preparation.
# Definitions only. No copy, ACL change, probe or Grok invocation occurs on load.
Set-StrictMode -Version Latest

function Add-Pr9ReadOnlyGrokNativeSupport {
    if ($PSVersionTable.PSVersion.Major -lt 7) { throw 'PowerShell7 is required' }
    if ('Pr9ReadOnlyGrokNativeV1' -as [type]) { throw 'native support namespace consumed' }
    $taskDefinition = @'
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Text;
using Microsoft.Win32.SafeHandles;

public static class Pr9ReadOnlyGrokNativeV1 {
    public static bool SameBytes(byte[] left, byte[] right) {
        if (left == null || right == null || left.Length != right.Length) return false;
        int difference=0;
        for (int index=0; index<left.Length; index++) difference |= left[index] ^ right[index];
        return difference == 0;
    }
    [StructLayout(LayoutKind.Sequential)]
    public struct Info {
        public uint Attributes, CreationLow, CreationHigh, AccessLow, AccessHigh;
        public uint WriteLow, WriteHigh, Volume, SizeHigh, SizeLow, Links, IndexHigh, IndexLow;
        public ulong Size { get { return ((ulong)SizeHigh << 32) | SizeLow; } }
        public ulong Index { get { return ((ulong)IndexHigh << 32) | IndexLow; } }
    }
    [StructLayout(LayoutKind.Sequential)]
    private struct FileTime { public uint Low, High; }
    [StructLayout(LayoutKind.Sequential)]
    private struct SecurityAttributes {
        public int Length;
        public IntPtr Descriptor;
        [MarshalAs(UnmanagedType.Bool)] public bool Inherit;
    }
    public sealed class TokenFacts {
        public string UserSid;
        public string[] Privileges;
        public bool Elevated;
    }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern SafeFileHandle CreateFileW(string path, uint access, uint sharing,
        IntPtr security, uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool CreateDirectoryW(string path, ref SecurityAttributes security);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool GetFileInformationByHandle(SafeFileHandle handle, out Info info);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool SetFileTime(SafeFileHandle handle,
        ref FileTime creation, ref FileTime access, ref FileTime write);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern bool FlushFileBuffers(SafeFileHandle handle);
    [DllImport("kernel32.dll", SetLastError=true)]
    private static extern uint GetFileType(SafeFileHandle handle);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern uint GetFinalPathNameByHandleW(SafeFileHandle handle,
        StringBuilder path, uint length, uint flags);
    [DllImport("kernel32.dll")] private static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll")] private static extern IntPtr LocalFree(IntPtr memory);
    [DllImport("advapi32.dll", SetLastError=true)]
    private static extern bool OpenProcessToken(IntPtr process, uint access, out SafeFileHandle token);
    [DllImport("advapi32.dll", SetLastError=true)]
    private static extern bool GetTokenInformation(SafeFileHandle token, int kind,
        IntPtr buffer, uint length, out uint needed);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool LookupPrivilegeNameW(string system, ref long luid,
        StringBuilder name, ref uint length);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool ConvertSidToStringSidW(IntPtr sid, out IntPtr text);
    [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    private static extern bool ConvertStringSecurityDescriptorToSecurityDescriptorW(
        string text, uint revision, out IntPtr descriptor, out uint size);
    [DllImport("advapi32.dll", SetLastError=true)]
    private static extern uint SetSecurityInfo(SafeFileHandle handle, int kind,
        uint information, IntPtr owner, IntPtr group, IntPtr dacl, IntPtr sacl);
    [DllImport("advapi32.dll", SetLastError=true)]
    private static extern uint GetSecurityInfo(SafeFileHandle handle, int kind,
        uint information, out IntPtr owner, out IntPtr group, out IntPtr dacl,
        out IntPtr sacl, out IntPtr descriptor);
    [DllImport("advapi32.dll", SetLastError=true)]
    private static extern uint GetSecurityDescriptorLength(IntPtr descriptor);
    [DllImport("advapi32.dll", SetLastError=true)]
    private static extern bool GetSecurityDescriptorDacl(IntPtr descriptor,
        [MarshalAs(UnmanagedType.Bool)] out bool present, out IntPtr acl,
        [MarshalAs(UnmanagedType.Bool)] out bool defaulted);
    [DllImport("advapi32.dll", SetLastError=true)]
    private static extern bool GetSecurityDescriptorControl(IntPtr descriptor,
        out ushort control, out uint revision);

    private static void Fail() { throw new Win32Exception(Marshal.GetLastWin32Error()); }
    public static void PreserveTimes(SafeFileHandle handle, Info source) {
        FileTime creation = new FileTime { Low=source.CreationLow, High=source.CreationHigh };
        FileTime access = new FileTime { Low=source.AccessLow, High=source.AccessHigh };
        FileTime write = new FileTime { Low=source.WriteLow, High=source.WriteHigh };
        if (!SetFileTime(handle, ref creation, ref access, ref write)) Fail();
        if (!FlushFileBuffers(handle)) Fail();
        Info after = Describe(handle);
        if (after.CreationLow != source.CreationLow || after.CreationHigh != source.CreationHigh ||
            after.WriteLow != source.WriteLow || after.WriteHigh != source.WriteHigh) {
            throw new InvalidOperationException("private copy timestamps differ");
        }
    }

    public static SafeFileHandle Open(string path, uint access) {
        SafeFileHandle handle = CreateFileW(path, access, 1, IntPtr.Zero, 3,
            0x02200000, IntPtr.Zero); // OPEN_REPARSE_POINT | BACKUP_SEMANTICS.
        if (handle.IsInvalid) { int error = Marshal.GetLastWin32Error(); handle.Dispose(); throw new Win32Exception(error); }
        return handle; // ShareRead only; handle is not inheritable.
    }
    public static Info Describe(SafeFileHandle handle) {
        Info info;
        if (GetFileType(handle) != 1 || !GetFileInformationByHandle(handle, out info)) {
            throw new InvalidOperationException("physical disk identity unavailable");
        }
        if ((info.Attributes & 0x400) != 0) {
            throw new InvalidOperationException("reparse object refused");
        }
        return info;
    }
    public static string FinalPath(SafeFileHandle handle) {
        StringBuilder text = new StringBuilder(1025);
        uint length = GetFinalPathNameByHandleW(handle, text, 1025, 0);
        if (length == 0 || length >= 1025) {
            throw new InvalidOperationException("canonical path unavailable");
        }
        string value = text.ToString();
        if (!value.StartsWith(@"\\?\", StringComparison.Ordinal) ||
            value.StartsWith(@"\\?\UNC\", StringComparison.OrdinalIgnoreCase)) {
            throw new InvalidOperationException("local canonical path required");
        }
        return value.Substring(4);
    }
    private static void CheckSid(string sid) {
        if (sid == null || sid.Length > 184 ||
            !System.Text.RegularExpressions.Regex.IsMatch(sid, @"^S-1(-[0-9]{1,10}){2,15}$")) {
            throw new InvalidOperationException("user identity unavailable");
        }
    }
    private static string Initial(string sid) {
        CheckSid(sid);
        return "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;" + sid + ")";
    }
    private static string Denied(string sid, bool directory) {
        CheckSid(sid);
        return "D:P(D;;0x000D0156;;;" + sid + ")(D;;0x000C0000;;;OW)" +
            "(A;;FA;;;SY)(A;;" + (directory ? "0x001200A9" : "0x00120089") + ";;;" + sid + ")";
    }
    private static IntPtr Descriptor(string text) {
        IntPtr descriptor;
        uint size;
        if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(text, 1, out descriptor, out size)) Fail();
        if (size > 4096) { LocalFree(descriptor); throw new InvalidOperationException("ACL record bound"); }
        return descriptor;
    }
    public static void MakePrivateDirectory(string path, string sid) {
        IntPtr descriptor = Descriptor(Initial(sid));
        try {
            SecurityAttributes attributes = new SecurityAttributes {
                Length = Marshal.SizeOf<SecurityAttributes>(), Descriptor = descriptor, Inherit = false
            };
            if (!CreateDirectoryW(path, ref attributes)) Fail(); // Collision is never accepted.
        } finally { LocalFree(descriptor); }
    }
    private static byte[] DaclBytes(IntPtr descriptor) {
        bool present, defaulted;
        IntPtr acl;
        if (!GetSecurityDescriptorDacl(descriptor, out present, out acl, out defaulted) ||
            !present || acl == IntPtr.Zero || defaulted) {
            throw new InvalidOperationException("explicit DACL unavailable");
        }
        ushort size = unchecked((ushort)Marshal.ReadInt16(acl, 2));
        if (size < 8 || size > 4096) throw new InvalidOperationException("ACL record bound");
        byte[] bytes = new byte[size];
        Marshal.Copy(acl, bytes, 0, size);
        return bytes;
    }
    public static void DenyWrites(SafeFileHandle handle, string sid, bool directory) {
        IntPtr descriptor = Descriptor(Denied(sid, directory));
        try {
            bool present, defaulted;
            IntPtr acl;
            if (!GetSecurityDescriptorDacl(descriptor, out present, out acl, out defaulted) ||
                !present || defaulted || acl == IntPtr.Zero) throw new InvalidOperationException("DACL unavailable");
            uint result = SetSecurityInfo(handle, 1, 0x80000004, IntPtr.Zero, IntPtr.Zero, acl, IntPtr.Zero);
            if (result != 0) throw new Win32Exception(unchecked((int)result));
        } finally { LocalFree(descriptor); }
    }
    public static bool DenialMatches(SafeFileHandle handle, string sid, bool directory) {
        IntPtr actual = IntPtr.Zero;
        IntPtr expected = Descriptor(Denied(sid, directory));
        try {
            uint revision;
            ushort control;
            IntPtr owner, group, acl, sacl;
            uint result = GetSecurityInfo(handle, 1, 4, out owner, out group, out acl, out sacl, out actual);
            if (result != 0) throw new Win32Exception(unchecked((int)result));
            if (actual == IntPtr.Zero || GetSecurityDescriptorLength(actual) > 4096 ||
                !GetSecurityDescriptorControl(actual, out control, out revision) ||
                (control & 0x1000) == 0) return false;
            byte[] left = DaclBytes(actual), right = DaclBytes(expected);
            if (left.Length != right.Length) return false;
            for (int index=0; index<left.Length; index++) if (left[index] != right[index]) return false;
            return true;
        } finally { if (actual != IntPtr.Zero) LocalFree(actual); LocalFree(expected); }
    }
    public static TokenFacts PrimaryToken() {
        SafeFileHandle token;
        if (!OpenProcessToken(GetCurrentProcess(), 8, out token)) Fail();
        using (token) {
            IntPtr buffer = Marshal.AllocHGlobal(16384);
            try {
                uint needed;
                if (!GetTokenInformation(token, 20, buffer, 4, out needed) || needed != 4) Fail();
                bool elevated = Marshal.ReadInt32(buffer) != 0;
                if (!GetTokenInformation(token, 1, buffer, 16384, out needed) || needed > 16384) Fail();
                IntPtr sid = Marshal.ReadIntPtr(buffer), text;
                if (!ConvertSidToStringSidW(sid, out text)) Fail();
                string user;
                try { user = Marshal.PtrToStringUni(text); } finally { LocalFree(text); }
                CheckSid(user);
                if (!GetTokenInformation(token, 3, buffer, 16384, out needed) || needed > 16384) Fail();
                int count = Marshal.ReadInt32(buffer);
                if (count < 0 || count > 128 || 4 + count*12 > needed) {
                    throw new InvalidOperationException("privilege roster bound");
                }
                List<string> names = new List<string>();
                for (int index=0; index<count; index++) {
                    long luid = Marshal.ReadInt64(buffer, 4 + index*12);
                    StringBuilder name = new StringBuilder(129);
                    uint length = 128;
                    if (!LookupPrivilegeNameW(null, ref luid, name, ref length) || length > 128) Fail();
                    names.Add(name.ToString());
                }
                return new TokenFacts { UserSid=user, Elevated=elevated, Privileges=names.ToArray() };
            } finally { Marshal.FreeHGlobal(buffer); }
        }
    }
}
'@
    if ([Text.Encoding]::UTF8.GetByteCount($taskDefinition) -gt 32768) { throw 'native source bound' }
    Add-Type -TypeDefinition $taskDefinition -Language CSharp -ErrorAction Stop
}

function Get-Pr9ReadOnlyGrokPrimaryIdentity {
    $taskToken = [Pr9ReadOnlyGrokNativeV1]::PrimaryToken()
    $taskExpected = @('SeShutdownPrivilege','SeChangeNotifyPrivilege','SeUndockPrivilege',
        'SeIncreaseWorkingSetPrivilege','SeTimeZonePrivilege')
    if ($taskToken.Elevated -or $taskToken.UserSid -ne
            [Security.Principal.WindowsIdentity]::GetCurrent().User.Value -or
        $taskToken.Privileges.Count -ne $taskExpected.Count -or
        @($taskToken.Privileges | Where-Object { $_ -notin $taskExpected }).Count) {
        throw 'ordinary primary token required'
    }
    return $taskToken
}

function Open-Pr9ReadOnlyGrokNode {
    param([Parameter(Mandatory)][string]$Path,[uint32]$Access=0x00020081)
    $taskFull = [IO.Path]::GetFullPath($Path)
    if ($taskFull.Length -gt 1024 -or $taskFull -notmatch '^[Cc]:\\' -or
        $taskFull -ne $Path) { throw 'canonical literal C path required' }
    $taskHandle = [Pr9ReadOnlyGrokNativeV1]::Open($taskFull,$Access)
    try {
        $taskInfo = [Pr9ReadOnlyGrokNativeV1]::Describe($taskHandle)
        $taskFinal = [Pr9ReadOnlyGrokNativeV1]::FinalPath($taskHandle)
        if (-not [string]::Equals($taskFinal,$taskFull,[StringComparison]::OrdinalIgnoreCase)) {
            throw 'node path identity mismatch'
        }
        return [pscustomobject]@{Path=$taskFull;Handle=$taskHandle;Info=$taskInfo}
    } catch { $taskHandle.Dispose(); throw }
}

function Test-Pr9ReadOnlyGrokNodeIdentity {
    param([Parameter(Mandatory)]$Node,[switch]$File)
    $taskNow = [Pr9ReadOnlyGrokNativeV1]::Describe($Node.Handle)
    if ($taskNow.Volume -ne $Node.Info.Volume -or $taskNow.Index -ne $Node.Info.Index -or
        $taskNow.Attributes -ne $Node.Info.Attributes -or
        ($File -and (($taskNow.Attributes -band 0x10) -ne 0 -or $taskNow.Links -ne 1 -or $taskNow.Size -ne $Node.Info.Size -or
            $taskNow.WriteLow -ne $Node.Info.WriteLow -or $taskNow.WriteHigh -ne $Node.Info.WriteHigh))) {
        throw 'held node identity drift'
    }
    $taskNamed = Open-Pr9ReadOnlyGrokNode -Path $Node.Path
    try {
        if ($taskNamed.Info.Volume -ne $taskNow.Volume -or $taskNamed.Info.Index -ne $taskNow.Index) {
            throw 'named node identity drift'
        }
    } finally { $taskNamed.Handle.Dispose() }
}

# This file deliberately defines support only. The literal closed preparation
# driver, actual denial controls and process admission must be reviewed separately.
