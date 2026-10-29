"""Fixed read-only qualification caller. Definitions only; default has no authority."""
from __future__ import annotations

import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
import sys
import types

ROOT = Path(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST")
BASE = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence"
HERE = BASE / "grok-runtime-boundary-20261028-01"
PSHOME = Path(r"C:\Program Files\PowerShell\7")
SID = "S-1-5-21-3110146144-1192974603-3912567380-24130"
SCOPE = "ntfs_metadata_qualification_v1"
WITNESS = HERE / "setup-witness.derived.json"
SOURCE_PATHS = {
    "capture": HERE / "grok_bounded_model_capture_v1.proposed.py",
    "driver": HERE / "grok_bounded_model_driver_v1.proposed.py",
    "guard": HERE / "grok_bounded_volume_guard_v1.proposed.ps1",
    "jobs": BASE / "blocker-implementation-20261026-01/grok_reviewed_job_definitions_v1.proposed.py",
}


def describe():
    return {"scope": SCOPE, "execution_authority": False, "capacity_accepted": False,
            "application_authority": False, "storage_operations": 0,
            "configuration_changes": 0, "witness_limit": 32768, "attestation_limit": 4096}


def bounded_json(value, limit):
    # Callers construct only fixed schemas with already bounded channel/scalar inputs.
    raw = json.dumps(value, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(raw) > limit:
        raise ValueError("complete record encoding exceeds its fixed ceiling")
    return raw


def cause(phase, error):
    name = type(error).__name__
    return {"phase": phase, "type": name if re.fullmatch(r"[A-Za-z0-9_]{1,128}", name) else "unavailable"}


def persist_witness(path, raw):
    if type(raw) is not bytes or not 0 < len(raw) <= 32768:
        raise ValueError("witness pre-write ceiling")
    descriptor = None
    result = {"created": False, "known_written_bytes": 0, "write_extent_unknown": False,
              "fsync_completed": False, "close_completed": False, "primary": None,
              "secondary": [], "complete": False, "sha256": hashlib.sha256(raw).hexdigest(),
              "encoded_bytes": len(raw)}
    errors = []

    def failed(phase, error):
        if any(error is previous for previous in errors):
            return
        errors.append(error)
        row = cause(phase, error)
        if result["primary"] is None:
            result["primary"] = row
        else:
            result["secondary"].append(row)

    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY | os.O_NOINHERIT, 0o600)
        result["created"] = True
    except BaseException as error:
        failed("create_new", error)
    if descriptor is not None:
        try:
            view = memoryview(raw)
            while view:
                count = os.write(descriptor, view)
                if type(count) is not int or not 0 < count <= len(view):
                    raise OSError("witness write stalled")
                result["known_written_bytes"] += count
                view = view[count:]
        except BaseException as error:
            result["write_extent_unknown"] = True
            failed("write", error)
        try:
            os.fsync(descriptor)
            result["fsync_completed"] = True
        except BaseException as error:
            failed("fsync", error)
        try:
            os.close(descriptor)
            result["close_completed"] = True
        except BaseException as error:
            failed("close", error)
    result["complete"] = bool(result["primary"] is None and not result["secondary"]
        and result["created"] and result["known_written_bytes"] == len(raw)
        and not result["write_extent_unknown"] and result["fsync_completed"] and result["close_completed"])
    return result


def validate_admission(value, now_tick):
    fields = {"schema_version", "scope", "planning_commit", "reviewed_commit", "entry_approval",
              "independent_reviews", "deadline_tick_ms", "boot_filetime", "ordinary_sid", "source_pins"}
    if type(value) is not dict or set(value) != fields:
        raise ValueError("closed reviewed metadata admission required")
    if type(now_tick) is not int or not 0 <= now_tick < (1 << 63) or type(value["deadline_tick_ms"]) is not int or not 0 < value["deadline_tick_ms"] < (1 << 63) or not 15000 < value["deadline_tick_ms"] - now_tick <= 180000:
        raise ValueError("original inherited metadata deadline required")
    if type(value["schema_version"]) is not int or value["schema_version"] != 1 or type(value["scope"]) is not str or value["scope"] != SCOPE:
        raise ValueError("metadata admission scope")
    if type(value["planning_commit"]) is not str or type(value["ordinary_sid"]) is not str or value["planning_commit"] != "44e8cef19d70f555e2f37dd4ea07651bd9b8125f" or value["ordinary_sid"] != SID:
        raise ValueError("planning/principal authority")
    if type(value["reviewed_commit"]) is not str or re.fullmatch(r"[0-9a-f]{40}", value["reviewed_commit"]) is None:
        raise ValueError("reviewed commit authority")
    reviews = value["independent_reviews"]
    if type(reviews) is not list or len(reviews) != 2 or any(type(item) is not int or not 0 < item < (1 << 64) for item in reviews) or len(set(reviews)) != 2:
        raise ValueError("two independent source reviews required")
    if type(value["entry_approval"]) is not int or not 0 < value["entry_approval"] < (1 << 64):
        raise ValueError("separate finite entry approval required")
    if type(value["boot_filetime"]) is not str or re.fullmatch(r"[0-9]{1,20}", value["boot_filetime"]) is None:
        raise ValueError("actual boot identity required")
    pins = value["source_pins"]
    if type(pins) is not dict or set(pins) != set(SOURCE_PATHS):
        raise ValueError("closed source inventory required")
    for pin in pins.values():
        if type(pin) is not dict or set(pin) != {"bytes", "sha256"} or type(pin["bytes"]) is not int or not 0 < pin["bytes"] <= 65536 or type(pin["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is None:
            raise ValueError("bounded source pin required")
    return value["deadline_tick_ms"]


class RuntimeCustody:
    """Deny write/delete of qualified runtime files and deletion of their ancestors."""
    def __init__(self):
        from ctypes import wintypes
        if os.name != "nt":
            raise ValueError("Windows runtime custody")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.create = self.kernel.CreateFileW
        self.create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                               ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.create.restype = wintypes.HANDLE
        self.close = self.kernel.CloseHandle
        self.close.argtypes = [wintypes.HANDLE]
        self.close.restype = wintypes.BOOL
        self.handles = []
        self.paths = set()
        self.close_causes = []
        self.close_failure_count = 0
        self.close_cause_bound_exceeded = False
        self.retired = False

    @property
    def active(self):
        return not self.retired and bool(self.handles) and len(self.handles) == len(self.paths)

    def opened_identity(self, handle):
        from ctypes import wintypes
        class Information(ctypes.Structure):
            _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]
        query = self.kernel.GetFileInformationByHandle
        query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Information)]
        query.restype = wintypes.BOOL
        info = Information()
        if ctypes.sizeof(info) != 52 or not query(handle, ctypes.byref(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        class FileIdInformation(ctypes.Structure):
            _fields_ = [("volume", ctypes.c_ulonglong), ("file_id", ctypes.c_ubyte * 16)]
        query_id = self.kernel.GetFileInformationByHandleEx
        query_id.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        query_id.restype = wintypes.BOOL
        identity = FileIdInformation()
        if ctypes.sizeof(identity) != 24 or not query_id(handle, 18, ctypes.byref(identity), ctypes.sizeof(identity)):
            raise ctypes.WinError(ctypes.get_last_error())
        return {"volume": int(identity.volume), "file_index": int.from_bytes(bytes(identity.file_id), "little"),
            "bytes": (int(info.size_high) << 32) | int(info.size_low),
            "links": int(info.links), "attributes": int(info.attributes)}

    def hold(self, path, directory=False):
        if getattr(self, "retired", False):
            raise ValueError("retired runtime custody cannot be reused")
        path = Path(path)
        if not path.is_absolute() or path.resolve(strict=True) != path:
            raise ValueError("literal runtime path required")
        if path in self.paths:
            return
        if len(self.paths) >= 1024:
            raise ValueError("runtime custody inventory ceiling")
        before = path.lstat()
        if path.is_symlink() or getattr(before, "st_file_attributes", 0) & 0x400 or (directory and not stat.S_ISDIR(before.st_mode)) or (not directory and (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1)):
            raise ValueError("runtime path custody")
        handle = self.create(str(path), 0x20081 if directory else 0x80000000,
                             3 if directory else 1, None, 3, 0x02200000, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles.append(handle)
        opened = self.opened_identity(handle)
        if (opened["volume"], opened["file_index"]) != (before.st_dev, before.st_ino) or opened["attributes"] & 0x400 or bool(opened["attributes"] & 0x10) != directory or (not directory and (opened["bytes"] != before.st_size or opened["links"] != 1)):
            raise ValueError("opened runtime object is not the observed file/directory")
        after = path.lstat()
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise ValueError("runtime path changed during custody")
        self.paths.add(path)

    def hold_ancestors(self, path):
        for parent in reversed(Path(path).parents):
            self.hold(parent, directory=True)

    def retire(self):
        # Exactly one attempt for every original handle; retain distinct close failures.
        self.retired = True
        while self.handles:
            handle = self.handles.pop()  # Remove custody before any ambiguous close; never retry it.
            try:
                if not self.close(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
            except BaseException as error:
                self.close_failure_count = getattr(self, "close_failure_count", 0) + 1
                if len(self.close_causes) < 16:
                    self.close_causes.append(cause("runtime_handle_close", error))
                else:
                    self.close_cause_bound_exceeded = True
        self.handles.clear()
        return self.close_causes


def snapshot(path, size, pin):
    before = path.lstat()
    if before.st_size != size or before.st_nlink != 1 or not stat.S_ISREG(before.st_mode) or path.is_symlink() or getattr(before, "st_file_attributes", 0) & 0x400:
        raise ValueError("source snapshot custody")
    descriptor = os.open(path, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns):
            raise ValueError("opened source identity")
        digest = hashlib.sha256()
        count = 0
        while True:
            part = os.read(descriptor, min(65536, size - count + 1))
            if not part:
                break
            if len(part) > size - count:
                raise ValueError("source grew")
            count += len(part)
            digest.update(part)
        after = os.fstat(descriptor)
        if count != size or digest.hexdigest() != pin or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns):
            raise ValueError("source pin or identity drift")
    finally:
        os.close(descriptor)


def documents_directory():
    from ctypes import wintypes
    if os.name != "nt":
        raise ValueError("Windows Documents known folder required")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    resolve = shell.SHGetFolderPathW
    resolve.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR]
    resolve.restype = ctypes.c_long
    buffer = ctypes.create_unicode_buffer(260)
    # CSIDL_PERSONAL, current user/current path; no CREATE flag or fallback.
    if resolve(None, 5, None, 0, buffer) != 0 or not buffer.value:
        raise ValueError("actual Documents known folder unavailable")
    path = Path(buffer.value)
    if not path.is_absolute():
        raise ValueError("actual Documents folder must be absolute")
    return path


def check_powershell_policy():
    import winreg
    checked = 0
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for view in (winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for policy_root in (r"Software\Policies\Microsoft\Windows\PowerShell", r"Software\Policies\Microsoft\PowerShellCore"):
                for leaf in ("Transcription", "ScriptBlockLogging", "ModuleLogging"):
                    name = policy_root + "\\" + leaf
                    try:
                        handle = winreg.OpenKey(hive, name, 0, winreg.KEY_READ | view)
                    except FileNotFoundError:
                        checked += 1
                    else:
                        winreg.CloseKey(handle)
                        raise ValueError("PowerShell policy writer requires separate qualification")
    configs = (PSHOME / "powershell.config.json", documents_directory() / "PowerShell/powershell.config.json")
    config_rows = []
    for path in configs:
        if not path.exists():
            config_rows.append({"present": False})
            continue
        if path.stat().st_size > 65536:
            raise ValueError("PowerShell configuration bound")
        with path.open("rb") as stream:
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise ValueError("PowerShell configuration grew")
        value = json.loads(raw.decode("utf-8-sig"))
        pending = [(value, 0)]
        visited = 0
        while pending:
            current, depth = pending.pop()
            visited += 1
            if visited > 512 or depth > 8:
                raise ValueError("PowerShell configuration structure bound")
            if type(current) is dict:
                for key, item in current.items():
                    if re.search("transcription|scriptblocklogging|modulelogging", key, re.I):
                        raise ValueError("PowerShell configuration logging requires separate qualification")
                    if type(item) in (dict, list):
                        pending.append((item, depth + 1))
            elif type(current) is list:
                pending.extend((item, depth + 1) for item in current)
                if len(pending) > 512:
                    raise ValueError("PowerShell configuration structure bound")
        config_rows.append({"present": True, "bytes": len(raw), "logging_keys_present": False})
    return {"absent_registry_policy_keys": checked, "configs": config_rows}


def release_parent_resources(free_sid, close_token, sid_pointer, token):
    errors = []
    if sid_pointer:
        try:
            free_sid(sid_pointer)
        except BaseException as error:
            errors.append(error)
    try:
        close_token(token)
    except BaseException as error:
        if not any(error is previous for previous in errors):
            errors.append(error)
    return errors


def qualify_parent(*, powershell_policy=False, sample_floors=True):
    from ctypes import wintypes
    if os.name != "nt":
        raise ValueError("Windows parent required")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    admin = shell.IsUserAnAdmin
    admin.argtypes = []
    admin.restype = wintypes.BOOL
    if not admin():
        raise ValueError("actual elevated parent required")
    current = kernel.GetCurrentProcess
    current.argtypes = []
    current.restype = wintypes.HANDLE
    token = wintypes.HANDLE()
    opener = advapi.OpenProcessToken
    opener.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    opener.restype = wintypes.BOOL
    close = kernel.CloseHandle
    close.argtypes = [wintypes.HANDLE]
    close.restype = wintypes.BOOL
    if not opener(current(), 8, ctypes.byref(token)):
        raise ctypes.WinError(ctypes.get_last_error())
    sid_pointer = wintypes.LPWSTR()
    primary = None
    try:
        query = advapi.GetTokenInformation
        query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        query.restype = wintypes.BOOL
        needed = wintypes.DWORD()
        query(token, 1, None, 0, ctypes.byref(needed))
        if not 0 < needed.value <= 65536:
            raise ValueError("token information bound")
        buffer = ctypes.create_string_buffer(needed.value)
        if not query(token, 1, buffer, len(buffer), ctypes.byref(needed)):
            raise ctypes.WinError(ctypes.get_last_error())
        convert = advapi.ConvertSidToStringSidW
        convert.argtypes = [ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR)]
        convert.restype = wintypes.BOOL
        if not convert(ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.byref(sid_pointer)):
            raise ctypes.WinError(ctypes.get_last_error())
        if sid_pointer.value != SID:
            raise ValueError("same original elevated SID required")
    except BaseException as error:
        primary = error
    free = kernel.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    def free_sid(pointer):
        if free(ctypes.cast(pointer, ctypes.c_void_p)):
            raise ctypes.WinError(ctypes.get_last_error())
    def close_token(handle):
        if not close(handle):
            raise ctypes.WinError(ctypes.get_last_error())
    close_errors = release_parent_resources(free_sid, close_token, sid_pointer, token)
    all_errors = [] if primary is None else [primary]
    all_errors.extend(error for error in close_errors if not any(error is previous for previous in all_errors))
    if all_errors:
        raise BaseExceptionGroup("parent token qualification/closure failed", all_errors)
    times = kernel.GetProcessTimes
    times.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
    times.restype = wintypes.BOOL
    stamps = [wintypes.FILETIME() for _ in range(4)]
    if not times(current(), *(ctypes.byref(stamp) for stamp in stamps)):
        raise ctypes.WinError(ctypes.get_last_error())
    creation_filetime = str((int(stamps[0].dwHighDateTime) << 32) | int(stamps[0].dwLowDateTime))
    nt = ctypes.WinDLL("ntdll").NtQuerySystemInformation
    nt.argtypes = [ctypes.c_int, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
    nt.restype = ctypes.c_long
    boot = ctypes.create_string_buffer(48)
    length = wintypes.ULONG()
    if nt(3, boot, 48, ctypes.byref(length)) != 0 or length.value != 48:
        raise ValueError("original boot information unavailable")
    floors = {}
    free_space = kernel.GetDiskFreeSpaceExW
    free_space.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong), ctypes.c_void_p, ctypes.c_void_p]
    free_space.restype = wintypes.BOOL
    for drive, minimum in ((("C:\\", 120 * 1024**3), ("E:\\", 66 * 1024**3)) if sample_floors else ()):
        available = ctypes.c_ulonglong()
        if not free_space(drive, ctypes.byref(available), None, None) or available.value < minimum:
            raise ValueError("fresh retained-peak capacity floor")
        floors[drive] = available.value
    return {"sid": SID, "elevated": True, "pid": os.getpid(),
            "creation_filetime": creation_filetime,
            "boot_filetime": str(int.from_bytes(boot.raw[:8], "little")),
            "free_bytes": floors, "powershell_policy": check_powershell_policy() if powershell_policy else None}


class MetadataBasic(ctypes.Structure):
    _pack_ = 4
    _fields_ = [(name, ctypes.c_uint32) for name in (
        "attributes", "creation_low", "creation_high", "access_low", "access_high",
        "write_low", "write_high", "serial", "size_high", "size_low", "links", "id_high", "id_low")]


class MetadataStandard(ctypes.Structure):
    _fields_ = [("allocation", ctypes.c_int64), ("eof", ctypes.c_int64), ("links", ctypes.c_uint32),
               ("delete_pending", ctypes.c_ubyte), ("directory", ctypes.c_ubyte)]


class MetadataReadCloseError(Exception):
    def __init__(self, value, closing):
        super().__init__("read completed but original handle close failed")
        self.returned_value = value
        self.__cause__ = closing


class MetadataWin32:
    """Literal read-only APIs, widths and targets from the retained C# qualifier."""
    def __init__(self):
        from ctypes import wintypes
        if os.name != "nt" or ctypes.sizeof(MetadataBasic) != 52 or ctypes.sizeof(MetadataStandard) != 24:
            raise ValueError("Windows metadata ABI required")
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.create = self.kernel.CreateFileW
        self.create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.create.restype = wintypes.HANDLE
        self.close = self.kernel.CloseHandle
        self.close.argtypes = [wintypes.HANDLE]
        self.close.restype = wintypes.BOOL
        self.basic = self.kernel.GetFileInformationByHandle
        self.basic.argtypes = [wintypes.HANDLE, ctypes.POINTER(MetadataBasic)]
        self.basic.restype = wintypes.BOOL
        self.standard = self.kernel.GetFileInformationByHandleEx
        self.standard.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.standard.restype = wintypes.BOOL
        self.volume = self.kernel.GetVolumeInformationByHandleW
        self.volume.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
            wintypes.LPWSTR, wintypes.DWORD]
        self.volume.restype = wintypes.BOOL
        self.device = self.kernel.DeviceIoControl
        self.device.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.device.restype = wintypes.BOOL
        self.dos = self.kernel.QueryDosDeviceW
        self.dos.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        self.dos.restype = wintypes.DWORD

    def with_handle(self, path, access, flags, reader):
        handle = self.create(path, access, 3, None, 3, flags, None)
        if handle in (None, ctypes.c_void_p(-1).value):
            raise ctypes.WinError(ctypes.get_last_error())
        primary = closing = None
        value = None
        try:
            value = reader(handle)
        except BaseException as error:
            primary = error
        try:
            if not self.close(handle):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as error:
            closing = error
        if primary is not None:
            if closing is not None and closing is not primary:
                raise BaseExceptionGroup("metadata read and original handle close failed", [primary, closing])
            raise primary
        if closing is not None:
            raise MetadataReadCloseError(value, closing)
        return value

    def v_absent(self):
        target = ctypes.create_unicode_buffer(4096)
        if self.dos("V:", target, len(target)):
            return False
        error = ctypes.get_last_error()
        if error == 2:
            return True
        raise ctypes.WinError(error)

    def file_metadata(self, path):
        def read(handle):
            basic, standard = MetadataBasic(), MetadataStandard()
            if not self.basic(handle, ctypes.byref(basic)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not self.standard(handle, 1, ctypes.byref(standard), ctypes.sizeof(standard)):
                raise ctypes.WinError(ctypes.get_last_error())
            if standard.eof < 0 or standard.allocation < 0 or standard.links != basic.links or standard.eof != (int(basic.size_high) << 32) | int(basic.size_low):
                raise ValueError("inconsistent metadata")
            return {"path": path, "volume_serial": f"{basic.serial:08x}",
                "file_id": f"{((int(basic.id_high) << 32) | int(basic.id_low)):016x}",
                "attributes": int(basic.attributes), "links": int(standard.links),
                "eof": int(standard.eof), "allocation": int(standard.allocation),
                "delete_pending": bool(standard.delete_pending), "directory": bool(standard.directory)}
        return self.with_handle(path, 0x80, 0x02200000, read)

    def ntfs_e(self):
        from ctypes import wintypes
        def read(handle):
            label, filesystem = ctypes.create_unicode_buffer(261), ctypes.create_unicode_buffer(64)
            serial, maximum, flags = wintypes.DWORD(), wintypes.DWORD(), wintypes.DWORD()
            if not self.volume(handle, label, len(label), ctypes.byref(serial), ctypes.byref(maximum), ctypes.byref(flags), filesystem, len(filesystem)):
                raise ctypes.WinError(ctypes.get_last_error())
            if filesystem.value != "NTFS":
                raise ValueError("NTFS required")
            ntfs, count = ctypes.create_string_buffer(96), wintypes.DWORD()
            if not self.device(handle, 0x00090064, None, 0, ntfs, 96, ctypes.byref(count), None):
                raise ctypes.WinError(ctypes.get_last_error())
            if count.value != 96:
                raise ValueError("NTFS metadata extent")
            result = {"volume_serial": f"{serial.value:08x}", "filesystem": filesystem.value}
            for name, offset, fmt in (
                ("ntfs_serial", 0, "Q"), ("sectors", 8, "q"), ("clusters", 16, "q"),
                ("free_clusters", 24, "q"), ("reserved_clusters", 32, "q"),
                ("bytes_per_sector", 40, "I"), ("bytes_per_cluster", 44, "I"),
                ("bytes_per_file_record", 48, "I"), ("clusters_per_file_record", 52, "I"),
                ("mft_valid_bytes", 56, "q"), ("mft_start_lcn", 64, "q"),
                ("mft_mirror_lcn", 72, "q"), ("mft_zone_start", 80, "q"), ("mft_zone_end", 88, "q")):
                value = struct.unpack_from("<" + fmt, ntfs.raw, offset)[0]
                result[name] = f"{value:016x}" if name == "ntfs_serial" else value
            usn = ctypes.create_string_buffer(80)
            if self.device(handle, 0x000900f4, None, 0, usn, 80, ctypes.byref(count), None):
                if not 56 <= count.value <= 80:
                    raise ValueError("USN metadata extent")
                result.update(usn_active=True, usn_maximum_bytes=struct.unpack_from("<Q", usn.raw, 40)[0],
                              usn_allocation_delta_bytes=struct.unpack_from("<Q", usn.raw, 48)[0])
            else:
                error = ctypes.get_last_error()
                if error != 1179:
                    raise ctypes.WinError(error)
                result.update(usn_active=False, usn_query_error=error)
            return result
        return self.with_handle(r"\\.\E:", 0x80000000, 0, read)


def metadata_failure(error, operation):
    pending, seen, causes = [error], [], []
    returned = None
    returned_available = False
    overflow = False
    visits = 0
    while pending:
        current = pending.pop(0)
        if any(current is prior for prior in seen):
            continue
        if len(seen) >= 16:
            overflow = True
            break
        seen.append(current)
        if isinstance(current, MetadataReadCloseError):
            returned, returned_available = current.returned_value, True
        native = getattr(current, "winerror", None)
        native = native if type(native) is int and 0 <= native <= 0xffffffff else None
        name = type(current).__name__
        causes.append({"type": name if re.fullmatch(r"[A-Za-z0-9_]{1,128}", name) else "unavailable", "native_error": native})
        children = current.exceptions if isinstance(current, BaseExceptionGroup) else (() if current.__cause__ is None else (current.__cause__,))
        for child in children:
            visits += 1
            if visits > 64:
                overflow = True
                break
            if any(child is prior for prior in seen) or any(child is queued for queued in pending):
                continue
            if len(seen) + len(pending) >= 16:
                overflow = True
                break
            pending.append(child)
    return {"operation": operation, "complete": False, "cause_bound_exceeded": overflow, "causes": causes,
            "returned_facts_available": returned_available, "returned_facts": returned}


def collect_metadata(original_deadline, *, now=None, api_factory=None, parent_check=None):
    if now is None:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        now = kernel.GetTickCount64
        now.argtypes = []
        now.restype = ctypes.c_ulonglong
    def tick():
        value = now()
        if type(value) is not int or not 0 <= value < (1 << 63):
            raise ValueError("known original monotonic tick required")
        return value
    start = tick()
    if type(original_deadline) is not int or type(start) is not int or not 0 < original_deadline - start <= 180000:
        raise ValueError("original metadata deadline required")
    parent = (parent_check or qualify_parent)()
    if type(parent) is not dict or parent.get("sid") != SID or parent.get("elevated") is not True:
        raise ValueError("actual elevated original principal required")
    api = (api_factory or MetadataWin32)()
    operations = (("v_namespace", lambda: {"absent": api.v_absent()}), ("ntfs_E", api.ntfs_e),
        ("E_MFT", lambda: api.file_metadata(r"E:\$MFT")),
        ("E_logfile", lambda: api.file_metadata(r"E:\$LogFile")),
        ("E_secure", lambda: api.file_metadata(r"E:\$Secure")),
        ("E_parent", lambda: api.file_metadata(r"E:\VAST-pr9")))
    records = []
    complete, late = True, False
    clock_failed = False
    for name, read in operations:
        try:
            before = tick()
        except BaseException as error:
            records.append(metadata_failure(error, "observation_clock"))
            complete, late, clock_failed = False, None, True
            break
        if before >= original_deadline:
            complete, late = False, True
            break
        try:
            value = read()
        except BaseException as error:
            complete = False
            records.append(metadata_failure(error, name))
            continue
        try:
            observed = tick()
        except BaseException as error:
            records.append({"operation": name, "complete": False, "deadline_exceeded": None,
                "facts": value, "clock_failure": metadata_failure(error, "observation_clock")})
            complete, late, clock_failed = False, None, True
            break
        operation_late = observed >= original_deadline
        records.append({"operation": name, "complete": not operation_late,
                        "deadline_exceeded": operation_late, "facts": value})
        if operation_late:
            complete, late = False, True
            break
    finish = None
    if not clock_failed:
        try:
            finish = tick()
        except BaseException as error:
            records.append(metadata_failure(error, "completion_clock"))
            complete, late = False, None
    if finish is not None and finish >= original_deadline:
        complete, late = False, True
    return {"scope": "read_only_review_volume_metadata", "sid": parent["sid"], "elevated": True,
        "collector_pid": parent.get("pid"), "collector_creation_filetime": parent.get("creation_filetime"),
        "boot_filetime": parent.get("boot_filetime"), "fresh_free_bytes": parent.get("free_bytes"),
        "complete": complete, "records": records, "original_deadline_tick_ms": original_deadline,
        "finished_tick_ms": finish, "deadline_exceeded": late, "storage_effects": 0,
        "configuration_changes": 0, "capacity_accepted": False, "application_authority": False}


def _metadata_channel_write(stream, raw, label):
    if type(raw) is not bytes or len(raw) > 8192:
        raise ValueError("metadata channel pre-write ceiling")
    facts = {"known_written_bytes": 0, "write_extent_unknown": False,
             "write_completed": False, "flush_completed": False}
    errors = []
    try:
        view = memoryview(raw)
        while view:
            count = stream.write(view)
            if type(count) is not int or not 0 < count <= len(view):
                raise OSError("metadata terminal write stalled")
            facts["known_written_bytes"] += count
            view = view[count:]
        facts["write_completed"] = True
    except BaseException as error:
        facts["write_extent_unknown"] = True
        errors.append((label + "_write", error))
    try:
        stream.flush()
        facts["flush_completed"] = True
    except BaseException as error:
        errors.append((label + "_flush", error))
    return facts, errors


def emit_metadata(original_deadline, *, collect=None, encode=None, stdout=None, stderr=None):
    """Keep the completed collection through independent encoding/write/flush faults."""
    collect, encode = collect or collect_metadata, encode or bounded_json
    stdout = sys.stdout.buffer if stdout is None else stdout
    stderr = sys.stderr.buffer if stderr is None else stderr
    completed = None
    collection_returned = False
    collection_failure = None
    try:
        completed = collect(original_deadline)
        collection_returned = True
        value = completed
    except BaseException as error:
        collection_failure = metadata_failure(error, "metadata_worker")
        value = collection_failure
    post_errors = []
    encoded = b""
    try:
        # The six fixed native records leave room for the terminal-failure wrapper
        # in the independently bounded8KiB second channel.
        encoded = encode(value, 6144)
    except BaseException as error:
        post_errors.append(("encode", error))
    stdout_facts, stdout_errors = _metadata_channel_write(stdout, encoded, "stdout")
    post_errors.extend(stdout_errors)
    if not post_errors:
        return {"exit_code": 0 if collection_returned else 1, "completed_collection": completed,
                "stdout": stdout_facts, "fallback_completed": None}
    seen, post_failures = [], []
    for phase, error in post_errors:
        if not any(error is prior for prior in seen):
            seen.append(error)
            post_failures.append(cause(phase, error))
    fallback = {"scope": "metadata_terminal_failure", "collection_returned": collection_returned,
        "completed_collection": completed, "collection_failure": collection_failure,
        "post_failures": post_failures, "stdout": stdout_facts, "complete": False,
        "capacity_accepted": False, "application_authority": False}
    fallback_errors = []
    fallback_bytes = b""
    try:
        fallback_bytes = encode(fallback, 8192)
    except BaseException as error:
        fallback_errors.append(("fallback_encode", error))
    stderr_facts, stderr_errors = _metadata_channel_write(stderr, fallback_bytes, "stderr")
    fallback_errors.extend(stderr_errors)
    return {"exit_code": 1, "completed_collection": completed, "stdout": stdout_facts,
        "stderr": stderr_facts, "post_failures": post_failures,
        "fallback_failures": [cause(phase, error) for phase, error in fallback_errors],
        "fallback_completed": bool(not fallback_errors and stderr_facts["write_completed"] and stderr_facts["flush_completed"])}


def run_qualification(admission, authenticated_sources, *, now_tick, custody=None, enclosing_result=None):
    deadline = validate_admission(admission, now_tick)
    if type(enclosing_result) is not dict or set(enclosing_result) != {"capture", "document_original", "attestation"} or any(value is not None for value in enclosing_result.values()):
        raise ValueError("fresh enclosing original-result custody required")
    # E-volume calls, including floor sampling, execute inside the owned child.
    parent = qualify_parent(sample_floors=False)
    if parent["boot_filetime"] != admission["boot_filetime"] or Path.cwd() != ROOT:
        raise ValueError("original boot/caller directory")
    if type(authenticated_sources) is not dict or set(authenticated_sources) != set(SOURCE_PATHS):
        raise ValueError("complete immutable source snapshot required")
    for name, raw in authenticated_sources.items():
        pin = admission["source_pins"][name]
        if type(raw) is not bytes or len(raw) != pin["bytes"] or hashlib.sha256(raw).hexdigest() != pin["sha256"]:
            raise ValueError("authenticated source binding")
    if custody is None or getattr(custody, "active", False) is not True or not set(SOURCE_PATHS.values()).issubset(custody.paths) or Path(sys.executable) not in custody.paths:
        raise ValueError("original immutable runtime/source custody required")
    if WITNESS.exists():
        raise ValueError("existing qualification witness refuses reuse")
    worker = types.ModuleType("pr9_authenticated_readonly_worker")
    exec(compile(authenticated_sources["capture"], "authenticated-readonly-worker", "exec"), worker.__dict__)
    observer = worker.WindowsObservation()
    if not 15000 < deadline - observer.tick() <= 180000:
        raise ValueError("original deadline expired before worker entry")
    job_type = worker.load_reviewed_job_definitions(authenticated_sources["jobs"])
    environment = {name: os.environ[name] for name in ("SystemRoot", "WINDIR", "USERPROFILE", "TEMP", "TMP") if name in os.environ}
    environment.update({"PR9_METADATA_DEADLINE_TICK": str(deadline),
                        "PR9_METADATA_DRIVER_SHA256": admission["source_pins"]["driver"]["sha256"]})
    captured = worker.capture_literal(mode="metadata_qualification", executable=worker.METADATA_EXECUTABLE,
        cwd=ROOT, environment=environment, deadline_tick_ms=deadline, job_type=job_type,
        observation=observer, private_outputs=None)
    # The caller owns this exact returned object before any validation, encoding,
    # persistence or clock operation can fail. Its outer finalizer retains it.
    enclosing_result["capture"] = captured
    channels = captured["private_channel_bytes"]
    if len(channels) != 2 or any(raw is not None and (type(raw) is not bytes or len(raw) > 8192) for raw in channels):
        raise ValueError("owned worker channel shape")
    causes = []
    if captured["private_primary"] is not None:
        causes.append(cause(*captured["private_primary"]))
    causes.extend(cause(*row) for row in captured["private_secondary"])
    document = {"scope": SCOPE, "admission": admission, "parent": parent,
        "capture": captured["facts"], "prefixes_base64": [None if raw is None else base64.b64encode(raw).decode("ascii") for raw in channels],
        "causes": causes, "capacity_accepted": False, "application_authority": False,
        "storage_operations": 0, "configuration_changes": 0}
    raw = bounded_json(document, 32768)
    enclosing_result["document_original"] = raw
    # Register each returned observation BEFORE the next fallible operation.
    attestation = {"scope": SCOPE, "persistence": None, "runtime_close_causes": None,
        "runtime_close_available": None, "runtime_close_failure_count": None,
        "runtime_close_cause_bound_exceeded": None, "completion_failure": None, "completion_secondary": [],
        "deadline_exceeded_after_close": None, "worker_complete": captured["facts"]["complete"],
        "qualification_accepted": False, "capacity_accepted": False, "application_authority": False,
        "pending_readers": any(row is not None for row in worker._QUARANTINED_READERS)}
    enclosing_result["attestation"] = attestation
    persistence = persist_witness(WITNESS, raw)
    attestation["persistence"] = persistence
    completion_errors = []
    def completion_failed(phase, error):
        if any(error is previous for previous in completion_errors):
            return
        completion_errors.append(error)
        row = cause(phase, error)
        if attestation["completion_failure"] is None:
            attestation["completion_failure"] = row
        else:
            attestation["completion_secondary"].append(row)
    try:
        custody_errors = custody.retire()
        attestation["runtime_close_causes"] = custody_errors
        attestation["runtime_close_available"] = True
    except BaseException as error:
        attestation["runtime_close_available"] = False
        completion_failed("runtime_retirement", error)
    attestation["runtime_close_failure_count"] = getattr(custody, "close_failure_count", None)
    attestation["runtime_close_cause_bound_exceeded"] = getattr(custody, "close_cause_bound_exceeded", None)
    try:
        attestation["deadline_exceeded_after_close"] = observer.tick() >= deadline
    except BaseException as error:
        completion_failed("completion_clock", error)
    bounded_json(attestation, 4096)
    # Independent post-close attestation stays <=4KiB. The outer <=64KiB frame
    # also carries the <=32KiB original, even if its sole file write was partial.
    envelope = {"witness_original_base64": base64.b64encode(raw).decode("ascii"), "attestation": attestation}
    bounded_json(envelope, 65536)
    return envelope


if __name__ == "__main__":
    print(bounded_json(describe(), 4096).decode("ascii"))


def collect_runtime_census(source_pins):
    """Observe this isolated interpreter; no worker, metadata query or write authority."""
    roles = ("capture", "driver", "guard", "jobs")
    if type(source_pins) is not dict or len(source_pins) != 4 or set(source_pins) != set(roles):
        raise ValueError("runtime census source roster")
    for role in roles:
        pin = source_pins[role]
        if (type(pin) is not dict or len(pin) != 2 or set(pin) != {"bytes", "sha256"}
                or type(pin["bytes"]) is not int or not 1 <= pin["bytes"] <= 65536
                or type(pin["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is None):
            raise ValueError("runtime census source pin")
    # Refuse before a collection, file open or late native-module import.
    if len(sys.modules) > 512 or type(sys.modules) is not dict:
        raise ValueError("runtime census module count")
    flag_names = ("isolated", "no_site", "no_user_site", "dont_write_bytecode")
    flags = {name: getattr(sys.flags, name) for name in flag_names}
    if (sys.platform != "win32" or sys.version_info[:2] != (3, 14)
            or ctypes.sizeof(ctypes.c_void_p) != 8 or any(value != 1 for value in flags.values())):
        raise ValueError("runtime census isolated Python314 required")
    python_root = Path(r"C:\Python314")
    windows_root = Path(r"C:\Windows")
    if (python_root.resolve(strict=True) != python_root
            or Path(sys.executable).resolve(strict=True) != python_root / "python.exe"):
        raise ValueError("runtime census executable")

    def scalar(value, limit=512):
        if type(value) is not str or not 1 <= len(value) <= limit or not value.isascii() or "\x00" in value:
            raise ValueError("runtime census scalar bound")
        return value

    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
                value.st_birthtime_ns, getattr(value, "st_file_attributes", 0), value.st_nlink)

    def metadata(path):
        value = path.lstat()
        if not stat.S_ISREG(value.st_mode) or getattr(value, "st_file_attributes", 0) & 0x400:
            raise ValueError("runtime census regular non-reparse input required")
        if not 0 <= value.st_size <= 64 * 1024 * 1024:
            raise ValueError("runtime census file extent")
        return identity(value)

    def read_bound(path, before, expected=None, capture=False):
        primary = None
        value = None
        total = 0
        captured = bytearray() if capture else None
        digest = hashlib.sha256()
        descriptor = os.open(path, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
        try:
            if identity(os.fstat(descriptor)) != before:
                raise ValueError("runtime census opened identity")
            while True:
                part = os.read(descriptor, min(65536, before[2] - total + 1))
                if not part:
                    break
                if len(part) > before[2] - total:
                    raise ValueError("runtime census input grew")
                total += len(part)
                digest.update(part)
                if capture:
                    captured.extend(part)
            if (total != before[2] or identity(os.fstat(descriptor)) != before
                    or metadata(path) != before):
                raise ValueError("runtime census input identity or extent changed")
            observed = digest.hexdigest()
            if expected is not None and observed != expected:
                raise ValueError("runtime census source hash")
            value = {"bytes": total, "sha256": observed, "close_complete": True}
        except BaseException as error:
            primary = error
        try:
            os.close(descriptor)
        except BaseException as closing:
            if primary is not None:
                if closing is primary:
                    raise primary
                raise BaseExceptionGroup("runtime census read and close", [primary, closing])
            # The completed read remains available; no ambiguous descriptor retry.
            value["close_complete"] = False
            raise MetadataReadCloseError(value, closing)
        if primary is not None:
            raise primary
        return value, bytes(captured) if capture else None

    raw_sources, source_meta, source_values = {}, {}, {}
    for role in roles:
        path = SOURCE_PATHS[role]
        if not path.is_absolute() or path.drive.upper() != "C:" or path.resolve(strict=True) != path:
            raise ValueError("runtime census source path")
        before = metadata(path)
        if before[2] != source_pins[role]["bytes"]:
            raise ValueError("runtime census source extent")
        value, raw = read_bound(path, before, source_pins[role]["sha256"], True)
        source_meta[role], source_values[role], raw_sources[role] = before, value, raw

    capture_namespace = {"__name__": "pr9_runtime_census_capture_definitions"}
    driver_namespace = {"__name__": "pr9_runtime_census_driver_definitions"}
    exec(compile(raw_sources["capture"], "authenticated-census-capture", "exec"), capture_namespace)
    exec(compile(raw_sources["driver"], "authenticated-census-driver", "exec"), driver_namespace)
    capture_namespace["load_reviewed_job_definitions"](raw_sources["jobs"])
    # Imports only: never construct a Job/Popen/observer or call any E/admin API.
    # _overlapped initialization includes an unconnected discovery socket.
    for name in ("_overlapped", "_winapi", "msvcrt", "asyncio.windows_utils", "ctypes.wintypes", "zlib"):
        __import__(name, fromlist=("*",))
    codecs = __import__("codecs")
    codec_names = {"utf-8"}
    for stream in (sys.__stdin__, sys.__stdout__, sys.__stderr__):
        name = getattr(stream, "encoding", None)
        if name is not None:
            codec_names.add(scalar(name, 128))
    if len(codec_names) > 4:
        raise ValueError("runtime census codec count")
    for name in sorted(codec_names):
        codecs.lookup(name)
    wintypes = sys.modules["ctypes.wintypes"]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    ntdll = ctypes.WinDLL("ntdll", use_last_error=True)
    get_process = kernel.GetCurrentProcess
    get_process.argtypes, get_process.restype = [], wintypes.HANDLE
    enumerate_modules = kernel.K32EnumProcessModules
    enumerate_modules.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.HMODULE), wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD)]
    enumerate_modules.restype = wintypes.BOOL
    module_name = kernel.GetModuleFileNameW
    module_name.argtypes = [wintypes.HMODULE, wintypes.LPWSTR, wintypes.DWORD]
    module_name.restype = wintypes.DWORD
    handles = (wintypes.HMODULE * 1024)()
    needed = wintypes.DWORD()
    if not enumerate_modules(get_process(), handles, ctypes.sizeof(handles), ctypes.byref(needed)):
        raise ctypes.WinError(ctypes.get_last_error())
    if needed.value > ctypes.sizeof(handles) or needed.value % ctypes.sizeof(wintypes.HMODULE):
        raise ValueError("runtime census native module count")
    class OSVersion(ctypes.Structure):
        _fields_ = [(name, wintypes.DWORD) for name in ("size", "major", "minor", "build", "platform")]
        _fields_ += [("service_pack", wintypes.WCHAR * 128)]
    version = OSVersion()
    version.size = ctypes.sizeof(version)
    get_version = ntdll.RtlGetVersion
    get_version.argtypes, get_version.restype = [ctypes.POINTER(OSVersion)], ctypes.c_long
    if get_version(ctypes.byref(version)) != 0:
        raise ValueError("runtime census OS build query")

    file_rows, file_meta, file_paths, indices = [], [], [], {}
    aggregate = 0
    def register(path, role=None):
        nonlocal aggregate
        canonical = path.resolve(strict=True)
        if role is None:
            if not canonical.is_relative_to(python_root):
                raise ValueError("runtime census non-Python file origin")
            kind, label = "python", scalar(canonical.relative_to(python_root).as_posix())
        else:
            if canonical != SOURCE_PATHS[role]:
                raise ValueError("runtime census source identity")
            kind, label = "source", role
        key = str(canonical).casefold()
        if key in indices:
            return indices[key]
        if len(file_rows) >= 1024:
            raise ValueError("runtime census file count")
        before = metadata(canonical)
        aggregate += before[2]
        if aggregate > 512 * 1024 * 1024:
            raise ValueError("runtime census aggregate extent")
        if role is not None and before != source_meta[role]:
            raise ValueError("runtime census authenticated source changed")
        index = len(file_rows)
        indices[key] = index
        file_paths.append(canonical)
        file_meta.append(before)
        # Decimal strings preserve Windows identity precision in JSON consumers.
        rendered = [str(before[0]), str(before[1]), str(before[3]), str(before[4]), before[5], before[6]]
        file_rows.append([kind, label, before[2], "0" * 64, rendered, True])
        if role is not None:
            file_rows[-1][3] = source_values[role]["sha256"]
        return index

    for role in roles:
        register(SOURCE_PATHS[role], role)
    register(python_root / "python.exe")
    native_rows = []
    for offset in range(needed.value // ctypes.sizeof(wintypes.HMODULE)):
        buffer = ctypes.create_unicode_buffer(513)
        length = module_name(handles[offset], buffer, len(buffer))
        if not 0 < length < len(buffer) - 1:
            raise ValueError("runtime census native path extent")
        path = Path(scalar(buffer.value)).resolve(strict=True)
        if path.is_relative_to(python_root):
            native_rows.append(["python", register(path)])
        elif path.is_relative_to(windows_root):
            native_rows.append(["trusted_os", scalar(path.relative_to(windows_root).as_posix())])
        else:
            raise ValueError("runtime census native origin outside trusted bases")
    dll_key = str(python_root / "python314.dll").casefold()
    if dll_key not in indices:
        raise ValueError("runtime census python314.dll not loaded")

    absent_configuration = []
    for path in (python_root / "python._pth", python_root / "python314._pth",
                 python_root / "pyvenv.cfg", Path(r"C:\pyvenv.cfg")):
        try:
            path.lstat()
        except FileNotFoundError:
            absent_configuration.append(str(path))
        else:
            raise ValueError("runtime census path configuration present")
    zip_path = python_root / "python314.zip"
    try:
        zip_path.lstat()
    except FileNotFoundError:
        optional_zip = None
    else:
        optional_zip = register(zip_path)
    zip_prefix = str(zip_path).replace("\\", "/").casefold() + "/"
    def module_file(value, optional=False):
        path_text = scalar(value)
        normalized = path_text.replace("\\", "/")
        if normalized.casefold().startswith(zip_prefix):
            if optional_zip is None:
                raise ValueError("runtime census missing module ZIP")
            return optional_zip
        path = Path(path_text)
        if not path.is_absolute() or not path.is_relative_to(python_root):
            raise ValueError("runtime census module origin")
        if optional:
            try:
                path.lstat()
            except FileNotFoundError:
                return None
        return register(path)

    if len(sys.modules) > 512:
        raise ValueError("runtime census module count after imports")
    modules = tuple(sys.modules.items())
    module_rows = []
    for name, module in modules:
        scalar(name, 256)
        if module is None:
            module_rows.append([name, "unavailable", None, None])
            continue
        if type(module) is not types.ModuleType:
            raise ValueError("runtime census module type")
        attributes = vars(module)
        spec = attributes.get("__spec__")
        origin = vars(spec).get("origin") if spec is not None else None
        file_value, cached = attributes.get("__file__"), attributes.get("__cached__")
        kind = origin if origin in ("built-in", "frozen") else "file" if file_value is not None else "namespace"
        file_index = module_file(file_value, optional=kind == "frozen") if file_value is not None else None
        cache_index = module_file(cached, optional=True) if cached is not None else None
        if kind == "namespace" and name != "__main__":
            # A namespace must have only public Python search locations.
            locations = attributes.get("__path__", ())
            if type(locations) not in (list, tuple) or len(locations) > 32:
                raise ValueError("runtime census namespace locations")
            for location in locations:
                if not Path(scalar(location)).resolve(strict=True).is_relative_to(python_root):
                    raise ValueError("runtime census namespace origin")
        module_rows.append([name, kind, file_index, cache_index])
    paths = []
    if len(sys.path) > 32:
        raise ValueError("runtime census search path count")
    for value in sys.path:
        path = Path(scalar(value))
        if not path.is_absolute() or not path.resolve(strict=False).is_relative_to(python_root):
            raise ValueError("runtime census search path origin")
        paths.append(str(path))
    prefix, base_prefix = scalar(sys.prefix), scalar(sys.base_prefix)
    if Path(prefix) != python_root or Path(base_prefix) != python_root:
        raise ValueError("runtime census prefix")
    result = {"scope": "python314_runtime_census_v1", "complete": True,
        "capacity_accepted": False, "application_authority": False, "loaded_memory_identity_proved": False,
        "flags": flags, "python": {"version": list(sys.version_info[:3]), "executable": str(python_root / "python.exe"),
            "prefix": prefix, "base_prefix": base_prefix, "search_paths": paths, "utf8_mode": sys.flags.utf8_mode},
        "os_base": {"path": str(windows_root), "version": [version.major, version.minor, version.build, version.platform],
            "native_module_paths_trusted_not_hashed": True, "system_file_link_count_assumed_one": False},
        "source_pins": {role: dict(source_pins[role]) for role in roles},
        "absent_configuration": absent_configuration, "optional_zip": optional_zip,
        "module_columns": ["name", "origin", "file", "cached"], "modules": module_rows,
        "file_columns": ["kind", "relative_path_or_source_role", "bytes", "sha256", "identity", "close_complete"],
        "identity_columns": ["device", "inode", "mtime_ns", "birthtime_ns", "attributes", "links"], "files": file_rows,
        "native_columns": ["base", "file_index_or_OS_relative_path"], "native_modules": native_rows,
        "codec_names": sorted(codec_names), "overlapped_unconnected_discovery_socket_import": True,
        "aggregate_file_bytes": aggregate,
        "limits": {"modules": 512, "native_modules": 1024, "files": 1024, "file_bytes": 67108864,
                   "aggregate_bytes": 536870912, "chunk_bytes": 65536, "json_bytes": 65536, "collection_json_bytes": 61439}}
    # Fixed hash placeholders have the exact final width. Refuse before runtime content reads.
    bounded_json(result, 61439)  # Reserve the terminal-failure frame and final LF.
    for index, path in enumerate(file_paths):
        if file_rows[index][0] == "source":
            if metadata(path) != file_meta[index]:
                raise ValueError("runtime census source changed before return")
            continue
        value, _ = read_bound(path, file_meta[index])
        file_rows[index][3] = value["sha256"]
    if len(sys.modules) != len(modules) or any(sys.modules.get(name) is not module for name, module in modules):
        raise ValueError("runtime census module set changed")
    bounded_json(result, 61439)  # Reserve the terminal-failure frame and final LF.
    return result


def emit_runtime_census(source_pins, original_deadline, *, collect=None, now=None,
                        encode=None, stdout=None, stderr=None):
    """Deliver a census before the post-return clock; failures remain unaccepted."""
    collect = collect_runtime_census if collect is None else collect
    encode = bounded_json if encode is None else encode
    stdout = sys.stdout.buffer if stdout is None else stdout
    stderr = sys.stderr.buffer if stderr is None else stderr
    completed = collection_failure = collection_exception = None
    returned = initial_checked = False
    clock = now
    post_errors = []
    post_overflow = False
    def fail(phase, error):
        nonlocal post_overflow
        if not any(error is prior for _, prior in post_errors):
            if len(post_errors) < 4:
                post_errors.append((phase, error))
            else:
                post_overflow = True
    def channel(stream, raw, label):
        facts = {"known_written_bytes": 0, "write_extent_unknown": False,
                 "write_attempted": raw is not None, "write_completed": False,
                 "flush_attempted": True, "flush_completed": False}
        errors = []
        if raw is not None:
            try:
                if type(raw) is not bytes or len(raw) > 65536:
                    raise ValueError("census channel bound")
                view = memoryview(raw)
                while view:
                    count = stream.write(view)
                    if type(count) is not int or not 0 < count <= len(view):
                        raise OSError("census terminal stalled")
                    facts["known_written_bytes"] += count
                    view = view[count:]
                facts["write_completed"] = True
            except BaseException as error:
                facts["write_extent_unknown"] = True
                errors.append((label + "_write", error))
        try:
            stream.flush()
            facts["flush_completed"] = True
        except BaseException as error:
            errors.append((label + "_flush", error))
        return facts, errors
    phase = "initial_deadline"
    try:
        if type(original_deadline) is not int or not 0 < original_deadline <= (1 << 64) - 1:
            raise ValueError("census original deadline")
        if clock is None:
            clock = ctypes.WinDLL("kernel32", use_last_error=True).GetTickCount64
            clock.argtypes, clock.restype = [], ctypes.c_ulonglong
        tick = clock()
        if type(tick) is not int or not 0 <= tick <= (1 << 64) - 1 or not 0 < original_deadline - tick <= 180000:
            raise ValueError("census initial deadline")
        initial_tick = tick
        initial_checked = True
        phase = "runtime_census"
        completed = collect(source_pins)
        returned = True
    except BaseException as error:
        collection_exception = error
        try:
            collection_failure = metadata_failure(error, phase)
        except BaseException as projecting:
            fail("failure_projection", projecting)
    encoded = None
    if returned:
        try:
            encoded = encode(completed, 61439)
            if type(encoded) is not bytes or len(encoded) > 61439:
                raise ValueError("census collection encoding bound")
            encoded += b"\n"
        except BaseException as error:
            encoded = None
            fail("encode", error)
    stdout_facts, stdout_errors = channel(stdout, encoded, "stdout")
    for item in stdout_errors:
        fail(*item)
    # Every stdout write/flush attempt precedes the first post-return clock.
    if initial_checked:
        try:
            tick = clock()
            if type(tick) is not int or tick < initial_tick or tick >= original_deadline:
                raise TimeoutError("census post-return deadline")
        except BaseException as error:
            fail("clock", error)
    result = {"exit_code": 1, "complete": False, "capacity_accepted": False,
        "application_authority": False, "completed_collection": completed,
        "collection_returned": returned, "collection_failure": collection_failure,
        "collection_exception": collection_exception, "stdout": stdout_facts,
        "post_errors": post_errors, "post_failure_bound_exceeded": post_overflow}
    if returned and not post_errors and not post_overflow:
        result.update(exit_code=0, complete=True, fallback_completed=None)
        return result
    post_failures = [cause(label, error) for label, error in post_errors]
    fallback = {"scope": "runtime_census_terminal_failure", "complete": False,
        "capacity_accepted": False, "application_authority": False,
        "collection_returned": returned, "completed_collection": completed if returned else None,
        "collection_failure": collection_failure if not returned else None,
        "post_failures": post_failures, "post_failure_bound_exceeded": post_overflow,
        "stdout": stdout_facts}
    fallback_errors = []
    fallback_bytes = None
    try:
        fallback_bytes = encode(fallback, 65535)
        if type(fallback_bytes) is not bytes or len(fallback_bytes) > 65535:
            raise ValueError("census fallback encoding bound")
        fallback_bytes += b"\n"
    except BaseException as error:
        fallback_bytes = None
        fallback_errors.append(("fallback_encode", error))
    stderr_facts, stderr_errors = channel(stderr, fallback_bytes, "stderr")
    for label, error in stderr_errors:
        if not any(error is prior for _, prior in fallback_errors):
            fallback_errors.append((label, error))
    result.update(stderr=stderr_facts, post_failures=post_failures,
        fallback_errors=fallback_errors,
        fallback_failures=[cause(label, error) for label, error in fallback_errors],
        fallback_completed=bool(not fallback_errors and stderr_facts["write_completed"] and stderr_facts["flush_completed"]))
    return result
