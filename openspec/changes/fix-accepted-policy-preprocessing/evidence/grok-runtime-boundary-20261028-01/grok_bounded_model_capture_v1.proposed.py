"""Metadata-only owned Windows worker. Definitions only; no execution authority."""
from __future__ import annotations

import ast
import base64
import json
import copy
import ctypes
import hashlib
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
from typing import Any

SUPERVISOR_BYTES = 124707
SUPERVISOR_SHA256 = "99f772665d0d271b24d98f2393a50a0f9e0bbfe5c2840e5ccce65d89a84ed13e"
OWNER_DEFINITION_BYTES = 7981
OWNER_DEFINITION_SHA256 = "54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3"
METADATA_EXECUTABLE = r"C:\Python314\python.exe"
METADATA_DRIVER_BYTES = 65441
METADATA_DRIVER_SHA256 = "11282e873d7f580a6165c6c7a561ed75e88db42b2e98de89b9866418b01348ed"
STATIC_ARGUMENTS = {
    "metadata_qualification": ("-I", "-B", "-S", "-c", "import hashlib,json,os,stat,sys\nfrom pathlib import Path\npath=Path(\"C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_driver_v1.proposed.py\")\nbefore=path.lstat()\nif not stat.S_ISREG(before.st_mode) or path.is_symlink() or getattr(before,'st_file_attributes',0)&0x400 or before.st_nlink!=1 or before.st_size!=65441: raise ValueError('metadata source custody')\ndescriptor=os.open(path,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT)\nprimary=None\nraw=bytearray()\ntry:\n    opened=os.fstat(descriptor)\n    if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns): raise ValueError('metadata opened source identity')\n    while True:\n        part=os.read(descriptor,min(16384,65441-len(raw)+1))\n        if not part: break\n        if len(part)>65441-len(raw): raise ValueError('metadata source grew')\n        raw.extend(part)\n    after=os.fstat(descriptor)\n    if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns) or after.st_nlink!=1: raise ValueError('metadata source drift')\nexcept BaseException as error:\n    primary=error\nfinally:\n    try: os.close(descriptor)\n    except BaseException as closing:\n        if primary is not None and closing is not primary: raise BaseExceptionGroup('metadata source read and close',[primary,closing])\n        raise\nif primary is not None: raise primary\nif len(raw)!=65441 or hashlib.sha256(raw).hexdigest()!='11282e873d7f580a6165c6c7a561ed75e88db42b2e98de89b9866418b01348ed': raise ValueError('metadata source extent/hash')\nnamespace = {'__name__':'pr9_metadata_execution_snapshot'}\nif os.environ.get('PR9_METADATA_DRIVER_SHA256')!='11282e873d7f580a6165c6c7a561ed75e88db42b2e98de89b9866418b01348ed': raise ValueError('metadata source admission')\nexec(compile(bytes(raw),'authenticated-readonly-metadata','exec'),namespace)\ntext=os.environ.get('PR9_METADATA_DEADLINE_TICK','')\nif not text.isascii() or not text.isdecimal() or len(text)>15: raise ValueError('deadline scalar')\nterminal=namespace['emit_metadata'](int(text))\nsys.exit(terminal['exit_code'])\n"),
    "runtime_census": ("-I", "-B", "-S", "-c", "import os,sys\ntry:\n    import base64,ctypes,hashlib,json,re,stat\n    from pathlib import Path\n    METADATA_DRIVER_BYTES=65441\n    METADATA_DRIVER_SHA256=\"11282e873d7f580a6165c6c7a561ed75e88db42b2e98de89b9866418b01348ed\"\n    \n    \n    def _runtime_census_source_pins(value):\n        \"\"\"Closed public source authority; canonical Base64, no path/command override.\"\"\"\n        if type(value) is not str or not 1 <= len(value) <= 4096 or not value.isascii():\n            raise ValueError(\"runtime census source encoding\")\n        try:\n            raw = base64.b64decode(value, validate=True)\n        except (ValueError, TypeError) as error:\n            raise ValueError(\"runtime census source encoding\") from error\n        if len(raw) > 2048 or base64.b64encode(raw).decode(\"ascii\") != value:\n            raise ValueError(\"runtime census source encoding bound\")\n        def pairs(rows):\n            if len(rows) > 4 or len({key for key, _ in rows}) != len(rows):\n                raise ValueError(\"runtime census source duplicate or field bound\")\n            return dict(rows)\n        def invalid_constant(value):\n            raise ValueError(\"runtime census source nonfinite constant\")\n        try:\n            pins = json.loads(raw.decode(\"utf-8\", \"strict\"), object_pairs_hook=pairs, parse_constant=invalid_constant)\n        except (ValueError, RecursionError) as error:\n            raise ValueError(\"runtime census source JSON\") from error\n        if type(pins) is not dict or set(pins) != {\"capture\", \"driver\", \"guard\", \"jobs\"}:\n            raise ValueError(\"runtime census source roster\")\n        for pin in pins.values():\n            if (type(pin) is not dict or set(pin) != {\"bytes\", \"sha256\"}\n                    or type(pin[\"bytes\"]) is not int or not 1 <= pin[\"bytes\"] <= 65536\n                    or type(pin[\"sha256\"]) is not str or re.fullmatch(r\"[0-9a-f]{64}\", pin[\"sha256\"]) is None):\n                raise ValueError(\"runtime census source pin\")\n        if pins[\"driver\"] != {\"bytes\": METADATA_DRIVER_BYTES, \"sha256\": METADATA_DRIVER_SHA256}:\n            raise ValueError(\"runtime census source driver binding\")\n        return pins\n    \n    def _runtime_census_refusal_location(terminal):\n        \"\"\"Return only bounded locations from the authenticated census source.\"\"\"\n        if type(terminal) is not dict or terminal.get(\"fallback_completed\") is not True:\n            return None\n        failure = terminal.get(\"collection_failure\")\n        error = terminal.get(\"collection_exception\")\n        facts = terminal.get(\"stderr\")\n        if (type(failure) is not dict or failure.get(\"operation\") != \"runtime_census\"\n                or not isinstance(error, BaseException) or type(facts) is not dict\n                or facts.get(\"write_extent_unknown\") is not False\n                or facts.get(\"write_completed\") is not True or facts.get(\"flush_completed\") is not True):\n            return None\n        count = facts.get(\"known_written_bytes\")\n        if type(count) is not int or not 0 <= count <= 60928:\n            return None\n        allowed = {\"emit_runtime_census\", \"collect_runtime_census\", \"scalar\", \"identity\",\n                   \"metadata\", \"read_bound\", \"register\", \"module_file\", \"bounded_json\"}\n        frames = []\n        hops = 0\n        matched = 0\n        unavailable = False\n        traceback = error.__traceback__\n        while traceback is not None and hops < 32:\n            hops += 1\n            code = traceback.tb_frame.f_code\n            if code.co_filename == \"authenticated-runtime-census-driver\":\n                name = code.co_name\n                line = traceback.tb_lineno\n                if name in allowed and type(line) is int and 1 <= line <= 2000:\n                    matched += 1\n                    if len(frames) == 8:\n                        frames.pop(0)\n                    frames.append({\"function\": name, \"line\": line})\n                else:\n                    unavailable = True\n            traceback = traceback.tb_next\n        record = {\"scope\": \"runtime_census_refusal_location_v1\", \"driver_sha256\": METADATA_DRIVER_SHA256,\n                  \"frames\": frames, \"location_unavailable\": unavailable or not frames,\n                  \"truncated\": traceback is not None or matched > 8, \"complete\": False,\n                  \"capacity_accepted\": False, \"application_authority\": False}\n        raw = json.dumps(record, ensure_ascii=True, separators=(\",\", \":\"), allow_nan=False).encode(\"ascii\")\n        if len(raw) > 4095:\n            return None\n        return raw + b\"\\n\"\n    \n    \n    def _emit_runtime_census_refusal_location(terminal, *, write=None):\n        \"\"\"One unbuffered append; a failed/partial write is never retried.\"\"\"\n        facts = {\"attempted\": False, \"known_written_bytes\": 0, \"write_extent_unknown\": False,\n                 \"write_completed\": False, \"error\": None}\n        terminal[\"refusal_location\"] = facts\n        try:\n            raw = _runtime_census_refusal_location(terminal)\n        except BaseException as error:\n            facts[\"error\"] = error\n            return facts\n        if raw is None:\n            return facts\n        facts[\"attempted\"] = True\n        try:\n            count = (os.write if write is None else write)(2, raw)\n            if type(count) is not int or not 0 <= count <= len(raw):\n                facts[\"write_extent_unknown\"] = True\n                raise OSError(\"diagnostic write extent\")\n            facts[\"known_written_bytes\"] = count\n            facts[\"write_completed\"] = count == len(raw)\n        except BaseException as error:\n            facts[\"write_extent_unknown\"] = True\n            facts[\"error\"] = error\n        return facts\n    if os.environ.get(\"PR9_METADATA_DRIVER_SHA256\") != METADATA_DRIVER_SHA256:\n        raise ValueError(\"runtime census original source binding\")\n    text=os.environ.get(\"PR9_METADATA_DEADLINE_TICK\", \"\")\n    if not text.isascii() or not text.isdecimal() or len(text)>15 or text!=str(int(text)):\n        raise ValueError(\"runtime census original deadline scalar\")\n    deadline=int(text)\n    pins=_runtime_census_source_pins(os.environ.get(\"PR9_RUNTIME_CENSUS_PINS\"))\n    tick=ctypes.WinDLL(\"kernel32\",use_last_error=True).GetTickCount64\n    tick.argtypes=[]\n    tick.restype=ctypes.c_ulonglong\n    def require_deadline():\n        if not 0 < deadline-tick() <= 180000:\n            raise ValueError(\"runtime census inherited deadline\")\n    require_deadline()\n    path=Path(\"C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_driver_v1.proposed.py\")\n    before=path.lstat()\n    if not stat.S_ISREG(before.st_mode) or path.is_symlink() or getattr(before,\"st_file_attributes\",0)&0x400 or before.st_nlink!=1 or before.st_size!=65441:\n        raise ValueError(\"runtime census source custody\")\n    raw=bytearray()\n    primary=None\n    descriptor=os.open(path,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT)\n    try:\n        opened=os.fstat(descriptor)\n        if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns):\n            raise ValueError(\"runtime census opened source identity\")\n        while True:\n            part=os.read(descriptor,min(16384,65441-len(raw)+1))\n            if not part: break\n            if len(part)>65441-len(raw): raise ValueError(\"runtime census source grew\")\n            raw.extend(part)\n        after=os.fstat(descriptor)\n        if (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns) or after.st_nlink!=1:\n            raise ValueError(\"runtime census source drift\")\n    except BaseException as error:\n        primary=error\n    finally:\n        try: os.close(descriptor)\n        except BaseException as closing:\n            if primary is not None and closing is not primary:\n                raise BaseExceptionGroup(\"runtime census source read and close\",[primary,closing])\n            raise\n    if primary is not None: raise primary\n    if len(raw)!=65441 or hashlib.sha256(raw).hexdigest()!=\"11282e873d7f580a6165c6c7a561ed75e88db42b2e98de89b9866418b01348ed\":\n        raise ValueError(\"runtime census source extent/hash\")\n    require_deadline()\n    namespace={\"__name__\":\"pr9_runtime_census_execution_snapshot\"}\n    exec(compile(bytes(raw),\"authenticated-runtime-census-driver\",\"exec\"),namespace)\n    require_deadline()\n    terminal=namespace[\"emit_runtime_census\"](pins,deadline)\n    _emit_runtime_census_refusal_location(terminal)\nexcept BaseException as error:\n    name=type(error).__name__\n    if not name.isascii() or not name.isidentifier() or len(name)>128: name=\"unavailable\"\n    diagnostic=b'{\"scope\":\"runtime_census\",\"complete\":false,\"error_type\":\"'+name.encode(\"ascii\")+b'\"}\\n'\n    try: os.write(2,diagnostic)\n    except BaseException: pass\n    sys.exit(1)\nsys.exit(terminal[\"exit_code\"])\n"),
}
CONTROL_PROGRAMS = {
    "control_normal": "import os;os.write(1,b'out\\n');os.write(2,b'err\\n')",
    "control_descendant": (
        "import os,subprocess,sys;"
        "subprocess.Popen([sys.executable,'-I','-B','-S','-c',"
        "'import time;time.sleep(30)'],stdout=sys.stdout,stderr=sys.stderr,close_fds=True);"
        "os.write(1,b'parent\\n')"
    ),
    "control_overflow": "import os;os.write(1,b'x'*2048)",
}


def _runtime_census_source_pins(value):
    """Closed public source authority; canonical Base64, no path/command override."""
    if type(value) is not str or not 1 <= len(value) <= 4096 or not value.isascii():
        raise ValueError("runtime census source encoding")
    try:
        raw = base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as error:
        raise ValueError("runtime census source encoding") from error
    if len(raw) > 2048 or base64.b64encode(raw).decode("ascii") != value:
        raise ValueError("runtime census source encoding bound")
    def pairs(rows):
        if len(rows) > 4 or len({key for key, _ in rows}) != len(rows):
            raise ValueError("runtime census source duplicate or field bound")
        return dict(rows)
    def invalid_constant(value):
        raise ValueError("runtime census source nonfinite constant")
    try:
        pins = json.loads(raw.decode("utf-8", "strict"), object_pairs_hook=pairs, parse_constant=invalid_constant)
    except (ValueError, RecursionError) as error:
        raise ValueError("runtime census source JSON") from error
    if type(pins) is not dict or set(pins) != {"capture", "driver", "guard", "jobs"}:
        raise ValueError("runtime census source roster")
    for pin in pins.values():
        if (type(pin) is not dict or set(pin) != {"bytes", "sha256"}
                or type(pin["bytes"]) is not int or not 1 <= pin["bytes"] <= 65536
                or type(pin["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", pin["sha256"]) is None):
            raise ValueError("runtime census source pin")
    if pins["driver"] != {"bytes": METADATA_DRIVER_BYTES, "sha256": METADATA_DRIVER_SHA256}:
        raise ValueError("runtime census source driver binding")
    return pins


def _runtime_census_refusal_location(terminal):
    """Return only bounded locations from the authenticated census source."""
    if type(terminal) is not dict or terminal.get("fallback_completed") is not True:
        return None
    failure = terminal.get("collection_failure")
    error = terminal.get("collection_exception")
    facts = terminal.get("stderr")
    if (type(failure) is not dict or failure.get("operation") != "runtime_census"
            or not isinstance(error, BaseException) or type(facts) is not dict
            or facts.get("write_extent_unknown") is not False
            or facts.get("write_completed") is not True or facts.get("flush_completed") is not True):
        return None
    count = facts.get("known_written_bytes")
    if type(count) is not int or not 0 <= count <= 60928:
        return None
    allowed = {"emit_runtime_census", "collect_runtime_census", "scalar", "identity",
               "metadata", "read_bound", "register", "module_file", "bounded_json"}
    frames = []
    hops = 0
    matched = 0
    unavailable = False
    traceback = error.__traceback__
    while traceback is not None and hops < 32:
        hops += 1
        code = traceback.tb_frame.f_code
        if code.co_filename == "authenticated-runtime-census-driver":
            name = code.co_name
            line = traceback.tb_lineno
            if name in allowed and type(line) is int and 1 <= line <= 2000:
                matched += 1
                if len(frames) == 8:
                    frames.pop(0)
                frames.append({"function": name, "line": line})
            else:
                unavailable = True
        traceback = traceback.tb_next
    record = {"scope": "runtime_census_refusal_location_v1", "driver_sha256": METADATA_DRIVER_SHA256,
              "frames": frames, "location_unavailable": unavailable or not frames,
              "truncated": traceback is not None or matched > 8, "complete": False,
              "capacity_accepted": False, "application_authority": False}
    raw = json.dumps(record, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("ascii")
    if len(raw) > 4095:
        return None
    return raw + b"\n"


def _emit_runtime_census_refusal_location(terminal, *, write=None):
    """One unbuffered append; a failed/partial write is never retried."""
    facts = {"attempted": False, "known_written_bytes": 0, "write_extent_unknown": False,
             "write_completed": False, "error": None}
    terminal["refusal_location"] = facts
    try:
        raw = _runtime_census_refusal_location(terminal)
    except BaseException as error:
        facts["error"] = error
        return facts
    if raw is None:
        return facts
    facts["attempted"] = True
    try:
        count = (os.write if write is None else write)(2, raw)
        if type(count) is not int or not 0 <= count <= len(raw):
            facts["write_extent_unknown"] = True
            raise OSError("diagnostic write extent")
        facts["known_written_bytes"] = count
        facts["write_completed"] = count == len(raw)
    except BaseException as error:
        facts["write_extent_unknown"] = True
        facts["error"] = error
    return facts


def load_reviewed_job(source: Path):
    """Load only the two authenticated classes, never the supervisor module."""
    if os.name != "nt":
        raise ValueError("Windows-only support")
    before = source.lstat()
    if (
        not stat.S_ISREG(before.st_mode) or source.is_symlink()
        or getattr(before, "st_file_attributes", 0) & 0x400
        or before.st_nlink != 1 or before.st_size != SUPERVISOR_BYTES
        or source.resolve(strict=True) != source
    ):
        raise ValueError("reviewed owner source unavailable")
    descriptor = os.open(source, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
    primary = None
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ):
            raise ValueError("reviewed owner source changed")
        raw = bytearray()
        while True:
            part = os.read(descriptor, min(16384, SUPERVISOR_BYTES - len(raw) + 1))
            if not part:
                break
            if len(part) > SUPERVISOR_BYTES - len(raw):
                raise ValueError("reviewed owner source grew")
            raw.extend(part)
        if len(raw) != SUPERVISOR_BYTES or hashlib.sha256(raw).hexdigest() != SUPERVISOR_SHA256:
            raise ValueError("reviewed owner source differs")
        after = os.fstat(descriptor)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns
        ):
            raise ValueError("reviewed owner source changed")
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            os.close(descriptor)
        except BaseException as close_error:
            if primary is not None and close_error is not primary:
                raise primary from close_error
            raise
    return load_reviewed_job_bytes(bytes(raw))


def load_reviewed_job_bytes(raw: bytes):
    """Accept authenticated captured bytes for a literal, path-free bootstrap."""
    if os.name != "nt" or type(raw) is not bytes or len(raw) != SUPERVISOR_BYTES:
        raise ValueError("reviewed owner source unavailable")
    if hashlib.sha256(raw).hexdigest() != SUPERVISOR_SHA256:
        raise ValueError("reviewed owner source differs")
    return _compile_reviewed_classes(raw)


def load_reviewed_job_definitions(raw: bytes):
    """Exactly the two unchanged class spans, bound back to the frozen source."""
    if os.name != "nt" or type(raw) is not bytes or len(raw) != OWNER_DEFINITION_BYTES:
        raise ValueError("reviewed owner definitions unavailable")
    if hashlib.sha256(raw).hexdigest() != OWNER_DEFINITION_SHA256:
        raise ValueError("reviewed owner definitions differ")
    return _compile_reviewed_classes(raw)


def _compile_reviewed_classes(raw: bytes):
    tree = ast.parse(raw, filename="authenticated-publication-owner")
    names = ("BackendPublicationProcessSupervisorV3Error", "_WindowsJob")
    selected = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name in names]
    if tuple(node.name for node in selected) != names:
        raise ValueError("reviewed owner definitions unavailable")
    future = ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0)
    unit = ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[]))
    namespace = {
        "__name__": "_pr9_reviewed_windows_owner",
        "os": os, "ctypes": ctypes, "subprocess": subprocess, "copy": copy, "Any": Any,
    }
    exec(compile(unit, "authenticated-publication-owner", "exec"), namespace)
    return namespace["_WindowsJob"]


class WindowsObservation:
    def __init__(self):
        if os.name != "nt":
            raise ValueError("Windows-only support")
        from ctypes import wintypes
        self.types = wintypes
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.tick = self.kernel.GetTickCount64
        self.tick.argtypes = []
        self.tick.restype = ctypes.c_ulonglong
        self.times = self.kernel.GetProcessTimes
        self.times.argtypes = [wintypes.HANDLE, *([ctypes.POINTER(wintypes.FILETIME)] * 4)]
        self.times.restype = wintypes.BOOL

    def require_main_thread(self):
        # Asynchronous ReadFile requires no single-native-thread premise.
        if threading.current_thread() is not threading.main_thread() or threading.active_count() != 1:
            raise ValueError("closed main-thread capture required")
        return threading.get_native_id()

    def creation_time(self, process):
        rows = [self.types.FILETIME() for _ in range(4)]
        if not self.times(self.types.HANDLE(int(process._handle)), *(ctypes.byref(row) for row in rows)):
            raise ctypes.WinError(ctypes.get_last_error())
        return (int(rows[0].dwHighDateTime) << 32) | int(rows[0].dwLowDateTime)




def require_metadata_admin():
    if os.name != "nt":
        raise ValueError("Windows-only metadata qualification")
    shell = ctypes.WinDLL("shell32", use_last_error=True)
    function = shell.IsUserAnAdmin
    function.argtypes = []
    function.restype = ctypes.c_int
    if function() != 1:
        raise ValueError("metadata qualification requires an elevated parent")


def apply_metadata_job_limits(job, active_limit):
    from ctypes import wintypes
    if os.name != "nt" or type(active_limit) is not int or active_limit not in (1, 2):
        raise ValueError("metadata job policy")
    handle = getattr(job, "_handle", None)
    if type(handle) is not int or handle <= 0:
        raise ValueError("original job handle required")
    class Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]
    class Io(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    setter = kernel.SetInformationJobObject
    setter.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    setter.restype = wintypes.BOOL
    query = kernel.QueryInformationJobObject
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    query.restype = wintypes.BOOL
    information = Extended()
    information.BasicLimitInformation.LimitFlags = 0x2000 | 0x200 | 0x8
    information.BasicLimitInformation.ActiveProcessLimit = active_limit
    information.JobMemoryLimit = 512 * 1024 * 1024
    if not setter(wintypes.HANDLE(handle), 9, ctypes.byref(information), ctypes.sizeof(information)):
        raise ctypes.WinError(ctypes.get_last_error())
    actual = Extended()
    returned = wintypes.DWORD()
    if not query(wintypes.HANDLE(handle), 9, ctypes.byref(actual), ctypes.sizeof(actual), ctypes.byref(returned)):
        raise ctypes.WinError(ctypes.get_last_error())
    if returned.value != ctypes.sizeof(actual) or (
        actual.BasicLimitInformation.LimitFlags != information.BasicLimitInformation.LimitFlags
        or actual.BasicLimitInformation.ActiveProcessLimit != active_limit
        or actual.JobMemoryLimit != information.JobMemoryLimit
    ):
        raise ValueError("metadata job policy readback differs")
    return {"verified": True, "memory_limit_bytes": actual.JobMemoryLimit,
            "active_process_limit": active_limit, "kill_on_close": True}


def bounded_environment(value: dict[str, str]) -> dict[str, str]:
    if type(value) is not dict or len(value) > 64:
        raise ValueError("reviewed environment bound")
    units = 1
    for name, item in value.items():
        if (
            type(name) is not str or type(item) is not str
            or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", name) is None
            or len(item) > 4096 or "\0" in item
        ):
            raise ValueError("reviewed environment scalar")
        units += len((name + "=" + item + "\0").encode("utf-16-le")) // 2
        if units > 32768:
            raise ValueError("reviewed environment aggregate")
    return value.copy()


# Strong process-global custody: pending Overlapped destructors can wait(TRUE).
# A poisoned controller may not start another capture; the bootstrap uses os._exit.
_QUARANTINED_READERS = [None, None]


def capture_literal(
    *, mode: str, executable: str, cwd: Path, environment: dict[str, str],
    deadline_tick_ms: int, job_type, observation: WindowsObservation,
    private_outputs: tuple[Path, Path] | None,
):
    """Closed auxiliary capture. Private bytes/exception objects stay private."""
    if any(operation is not None for operation in _QUARANTINED_READERS):
        raise ValueError("controller has unsettled overlapped ownership")
    control = mode in CONTROL_PROGRAMS
    metadata = mode == "metadata_qualification"
    census = mode == "runtime_census"
    memory_capture = control or metadata or census
    if mode not in STATIC_ARGUMENTS and not control:
        raise ValueError("literal capture mode required")
    if control:
        if executable != sys.executable or private_outputs is not None:
            raise ValueError("fixed control executable and memory storage required")
        command = [sys.executable, "-I", "-B", "-S", "-c", CONTROL_PROGRAMS[mode]]
        limit = 1024
    else:
        if executable != METADATA_EXECUTABLE or private_outputs is not None:
            raise ValueError("fixed metadata executable and memory storage required")
        if (type(deadline_tick_ms) is not int or deadline_tick_ms <= 0 or type(environment) is not dict
                or environment.get("PR9_METADATA_DEADLINE_TICK") != str(deadline_tick_ms)):
            raise ValueError("metadata original deadline binding required")
        if environment.get("PR9_METADATA_DRIVER_SHA256") != METADATA_DRIVER_SHA256:
            raise ValueError("metadata original source binding required")
        if census:
            _runtime_census_source_pins(environment.get("PR9_RUNTIME_CENSUS_PINS"))
            allowed = {"SystemRoot", "WINDIR", "USERPROFILE", "TEMP", "TMP",
                       "PR9_METADATA_DEADLINE_TICK", "PR9_METADATA_DRIVER_SHA256", "PR9_RUNTIME_CENSUS_PINS"}
            if len(environment) > len(allowed) or set(environment) - allowed:
                raise ValueError("runtime census minimal environment required")
        if metadata:
            require_metadata_admin()
        command = [executable, *STATIC_ARGUMENTS[mode]]
        if len(subprocess.list2cmdline(command).encode("utf-16-le")) // 2 >= 32767:
            raise ValueError("metadata native command-line ceiling")
        limit = 65536 if census else 8192
    if type(deadline_tick_ms) is not int or not 0 < deadline_tick_ms - observation.tick() <= 180000:
        raise ValueError("inherited preparation deadline required")
    child_environment = bounded_environment(environment)
    entry_thread_id = observation.require_main_thread()
    observe_end = deadline_tick_ms - 15000
    model_poll_counts = {"collection": 0, "retirement": 0, "cancel": 0}

    def count_model_poll(role, maximum):
        if model_poll_counts is not None:
            if model_poll_counts[role] >= maximum:
                raise OverflowError("model poll count bound")
            model_poll_counts[role] += 1

    channels = [{
        "observed_bytes": 0, "written_prefix_bytes": 0, "discarded_bytes_lower_bound": 0,
        "write_extent_unknown": False, "retention_failed": False, "eof": False, "overflow": False,
        "fsync_completed": None if memory_capture else False, "close_completed": False,
        "read_starts": 0, "read_completions": 0, "pending_ever": False,
        "io_settled": False, "read_failed": False, "cancel_requested": False,
        "cancel_completed": False, "quarantined": False,
    } for _ in range(2)]
    prefixes = [bytearray(), bytearray()]
    descriptors = [None, None]
    read_handles = [None, None]
    write_handles = [None, None]
    write_fds = [None, None]
    readers = [None, None]
    pipe_closed = [False, False]
    parent_writers_closed = [False, False]
    labels = ("stdout", "stderr")
    process = job = None
    phase = "capture_setup"
    primary = None
    secondary = []
    cause_overflow = False
    forced = resumed = assigned = False
    active_after = None
    job_closed = process_handle_closed = False
    creation_time = root_pid = returncode = None
    observation_completed_tick = retirement_completed_tick = retirement_end = None
    kill_on_close = False
    job_policy = None
    modules_ready = False

    def fail(code, error):
        nonlocal primary, cause_overflow
        if primary is None:
            primary = (code, error)
        elif error is not primary[1] and not any(error is previous[1] for previous in secondary):
            if len(secondary) < 16:
                secondary.append((code, error))
            else:
                cause_overflow = True

    def require_observation_window():
        if observation.tick() >= observe_end:
            raise TimeoutError("preparation observation deadline")

    def retain(index, data):
        nonlocal phase
        row = channels[index]
        if type(data) is not bytes or len(data) > 4096:
            raise ValueError("overlapped read extent differs")
        if not data:
            row["eof"] = True
            return
        if row["observed_bytes"] > (1 << 64) - 1 - len(data):
            raise OverflowError("capture observation bound")
        row["observed_bytes"] += len(data)
        remaining = limit - row["written_prefix_bytes"]
        keep = 0 if row["write_extent_unknown"] or row["retention_failed"] else min(remaining, len(data))
        if keep:
            view = memoryview(data)[:keep]
            while view:
                count = len(view)
                if not memory_capture:
                    try:
                        phase = labels[index] + "_write"
                        count = os.write(descriptors[index], view)
                        if count <= 0 or count > len(view):
                            raise OSError("capture write stalled")
                    except BaseException:
                        row["write_extent_unknown"] = True
                        raise
                    row["written_prefix_bytes"] += count
                try:
                    phase = labels[index] + "_retain"
                    prefixes[index].extend(view[:count])
                except BaseException:
                    row["retention_failed"] = True
                    raise
                if memory_capture:
                    row["written_prefix_bytes"] += count
                view = view[count:]
        row["discarded_bytes_lower_bound"] += len(data) - keep
        if len(data) > remaining:
            row["overflow"] = True

    def read_completed(*, start=True):
        nonlocal phase
        for index in range(2):
            row = channels[index]
            if read_handles[index] is None or row["eof"] or row["read_failed"]:
                continue
            operation = readers[index]
            if operation is None:
                if not start:
                    continue
                if row["read_starts"] >= 65536:
                    raise OverflowError("overlapped start count bound")
                phase = labels[index] + "_read_start"
                operation = overlapped.Overlapped(0)
                readers[index] = operation  # Custody precedes the native call.
                _QUARANTINED_READERS[index] = operation
                row["read_starts"] += 1
                try:
                    operation.ReadFile(read_handles[index], 4096)
                except BaseException as error:
                    # CPython marks direct ReadFile109 completed; 233 does not.
                    if isinstance(error, OSError) and error.winerror == 109 and not operation.pending:
                        readers[index] = None
                        _QUARANTINED_READERS[index] = None
                        row["read_completions"] += 1
                        row["eof"] = True
                        continue
                    row["read_failed"] = True
                    raise
            phase = labels[index] + "_read_poll"
            if operation.pending:
                row["pending_ever"] = True
                continue
            phase = labels[index] + "_read_result"
            try:
                data = operation.getresult(False)
            except BaseException:
                row["read_failed"] = True
                readers[index] = None  # Completion was observed, not pending.
                _QUARANTINED_READERS[index] = None
                raise
            readers[index] = None
            _QUARANTINED_READERS[index] = None
            row["read_completions"] += 1
            retain(index, data)

    def close_writer(index):
        nonlocal phase
        if write_fds[index] is not None:
            phase = labels[index] + "_parent_writer_close"
            descriptor = write_fds[index]
            write_fds[index] = None  # Do not retry an ambiguously closed CRT fd.
            os.close(descriptor)
            parent_writers_closed[index] = True
        elif write_handles[index] is not None:
            phase = labels[index] + "_parent_raw_writer_close"
            handle = write_handles[index]
            write_handles[index] = None
            winapi.CloseHandle(handle)
            parent_writers_closed[index] = True

    try:
        phase = "reader_import"
        require_observation_window()
        # _overlapped initialization creates/closes one unconnected discovery
        # socket. It makes no connect request. No bytecode is written (-B).
        import _overlapped as overlapped
        import _winapi as winapi
        import msvcrt
        from asyncio import windows_utils
        modules_ready = True
        require_observation_window()
        for index in range(2):
            if not memory_capture:
                phase = labels[index] + "_capture_open"
                require_observation_window()
                descriptors[index] = os.open(
                    private_outputs[index], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_BINARY | os.O_NOINHERIT,
                    0o600,
                )
            phase = labels[index] + "_pipe_pair"
            require_observation_window()
            # The installed helper requests8KiB, uses one instance and <=21
            # collision attempts, and connects its own client before returning.
            read_handles[index], write_handles[index] = windows_utils.pipe(
                overlapped=(True, False), bufsize=8192,
            )
            phase = labels[index] + "_writer_fd"
            write_fds[index] = msvcrt.open_osfhandle(
                write_handles[index], os.O_WRONLY | os.O_BINARY | os.O_NOINHERIT,
            )
            write_handles[index] = None  # CRT descriptor now owns this handle.
        phase = "job_create"
        require_observation_window()
        job = job_type()
        kill_on_close = job.kill_on_close
        phase = "job_policy"
        job_policy = apply_metadata_job_limits(job, 2 if mode == "control_descendant" else 1)
        require_observation_window()
        phase = "process_create"
        require_observation_window()
        process = subprocess.Popen(
            command, cwd=cwd, env=child_environment, stdin=subprocess.DEVNULL,
            stdout=write_fds[0], stderr=write_fds[1], close_fds=True,
            creationflags=0x00000004 | subprocess.CREATE_NO_WINDOW,
        )
        root_pid = process.pid
        phase = "process_identity"
        creation_time = observation.creation_time(process)
        phase = "job_assign"
        require_observation_window()
        job.assign(process)
        assigned = True
        # EOF must depend only on child copies before the child is resumed.
        for index in range(2):
            close_writer(index)
        phase = "process_resume"
        require_observation_window()
        job.resume(process)
        resumed = True
        while True:
            count_model_poll("collection", 60000)
            phase = "capture_read"
            require_observation_window()
            read_completed()
            if any(row["overflow"] for row in channels):
                phase = "channel_overflow"
                raise OverflowError("capture channel bound")
            phase = "process_poll"
            returncode = process.poll()
            phase = "job_accounting"
            active = job.active_processes()
            if returncode is not None:
                # Root status and Job accounting can become observable at different
                # instants. Require actual zero and both EOFs under the SAME window.
                if active == 0 and all(row["eof"] for row in channels):
                    if returncode:
                        phase = "command_status"
                        raise RuntimeError("literal command returned nonzero")
                    phase = "observation_completion_clock"
                    observation_completed_tick = observation.tick()
                    if observation_completed_tick >= observe_end:
                        raise TimeoutError("preparation observation deadline")
                    break
            phase = "observation_sleep"
            time.sleep(0.01)
    except BaseException as error:
        fail(phase, error)
    finally:
        if modules_ready:
            for index in range(2):
                try:
                    close_writer(index)
                except BaseException as error:
                    fail(labels[index] + "_parent_writer_cleanup", error)
        if process is not None:
            try:
                returncode = process.poll()
                active = job.active_processes() if assigned else None
                if returncode is None or (active is not None and active > 0):
                    forced = True
                    if assigned:
                        job.terminate()
                    else:
                        process.kill()  # Original held handle, still suspended.
            except BaseException as error:
                fail("termination", error)
            try:
                phase = "retirement_clock"
                retirement_end = min(deadline_tick_ms - 7000, observation.tick() + 5000)
                while observation.tick() < retirement_end:
                    count_model_poll("retirement", 1000)
                    returncode = process.poll()
                    active_after = job.active_processes() if job is not None else None
                    read_completed()
                    if returncode is not None and active_after == 0 and all(row["eof"] for row in channels):
                        phase = "retirement_completion_clock"
                        retirement_completed_tick = observation.tick()
                        if retirement_completed_tick >= retirement_end:
                            raise TimeoutError("retirement observation deadline")
                        break
                    phase = "retirement_sleep"
                    time.sleep(0.01)
                    phase = "retirement_clock"
            except BaseException as error:
                fail("retirement_" + phase, error)
            if returncode is None or active_after != 0:
                fail("retirement_unknown", RuntimeError("owned retirement unavailable"))
        # Cancel without freeing pending storage; do not start further reads.
        if modules_ready:
            for index, operation in enumerate(readers):
                if operation is not None:
                    try:
                        if operation.pending:
                            channels[index]["cancel_requested"] = True
                            operation.cancel()
                    except BaseException as error:
                        fail(labels[index] + "_cancel", error)
            try:
                cancel_end = min(deadline_tick_ms - 5000, observation.tick() + 2000)
                while any(operation is not None for operation in readers) and observation.tick() < cancel_end:
                    count_model_poll("cancel", 1000)
                    for index, operation in enumerate(readers):
                        if operation is None or operation.pending:
                            continue
                        try:
                            data = operation.getresult(False)
                        except BaseException as error:
                            readers[index] = None
                            _QUARANTINED_READERS[index] = None
                            if isinstance(error, OSError) and error.winerror == 995 and channels[index]["cancel_requested"]:
                                channels[index]["cancel_completed"] = True
                            else:
                                fail(labels[index] + "_cancel_result", error)
                        else:
                            readers[index] = None
                            _QUARANTINED_READERS[index] = None
                            channels[index]["read_completions"] += 1
                            try:
                                retain(index, data)
                            except BaseException as error:
                                fail(labels[index] + "_cancel_retention", error)
                    if any(operation is not None for operation in readers):
                        time.sleep(0.01)
            except BaseException as error:
                fail("cancel_observation", error)
        for index, operation in enumerate(readers):
            if operation is not None:
                # Conservatively retain even if a completion check failed.
                _QUARANTINED_READERS[index] = operation
                channels[index]["quarantined"] = True
                fail(labels[index] + "_io_unsettled", RuntimeError("overlapped completion unavailable"))
            else:
                channels[index]["io_settled"] = True
        if process is not None and not all(row["eof"] for row in channels):
            fail("pipe_eof_unknown", RuntimeError("owned pipe EOF unavailable"))
        for index, descriptor in enumerate(descriptors):
            if descriptor is not None:
                try:
                    os.fsync(descriptor)
                    channels[index]["fsync_completed"] = True
                except BaseException as error:
                    fail(labels[index] + "_fsync", error)
                try:
                    os.close(descriptor)
                    channels[index]["close_completed"] = True
                except BaseException as error:
                    fail(labels[index] + "_close", error)
            elif memory_capture:
                channels[index]["close_completed"] = True
        if modules_ready:
            for index, handle in enumerate(read_handles):
                if handle is not None:
                    try:
                        winapi.CloseHandle(handle)
                        pipe_closed[index] = True
                    except BaseException as error:
                        fail(labels[index] + "_pipe_close", error)
        if process is not None:
            try:
                process._handle.Close()
                process_handle_closed = True
            except BaseException as error:
                fail("process_handle_close", error)
        if job is not None:
            try:
                job.close()
                job_closed = True
            except BaseException as error:
                fail("job_handle_close", error)
    finalized_prefixes = [None, None]
    for index in range(2):
        try:
            finalized_prefixes[index] = bytes(prefixes[index])
        except BaseException as error:
            channels[index]["retention_failed"] = True
            fail(labels[index] + "_retention_finalize", error)
    late = None
    try:
        late = observation.tick() >= deadline_tick_ms
    except BaseException as error:
        fail("completion_clock", error)
    for row in channels:
        row["remainder_unknown"] = not row["eof"]
    public = {
        "mode": mode, "storage": "memory_control" if control else "memory_metadata",
        "entry_native_thread_id": entry_thread_id, "entry_python_thread_count": 1,
        "channel_limit": limit, "channels": channels, "original_pid": root_pid,
        "original_creation_filetime": None if creation_time is None else str(creation_time), "returncode": returncode,
        "assigned_before_resume": assigned, "resumed": resumed,
        "active_after_retirement": active_after, "forced": forced,
        "job_kill_on_close": kill_on_close, "job_policy": job_policy,
        "pipe_handles_closed": pipe_closed, "parent_writers_closed": parent_writers_closed,
        "reader_mode": "overlapped_readfile_no_reader_threads",
        "process_handle_closed": process_handle_closed, "job_handle_closed": job_closed,
        "deadline_exceeded": late, "deadline_tick_ms": deadline_tick_ms,
        "observe_end_tick": observe_end, "retirement_end_tick": retirement_end,
        "observation_completed_tick": observation_completed_tick,
        "retirement_completed_tick": retirement_completed_tick,
        "primary_code": None if primary is None else primary[0],
        "secondary_codes": [row[0] for row in secondary], "cause_overflow": cause_overflow,
    }
    if model_poll_counts is not None:
        public["operation_poll_counts"] = model_poll_counts
    public["complete"] = bool(
        primary is None and not secondary and not cause_overflow and not forced and late is False
        and observation_completed_tick is not None and observation_completed_tick < observe_end
        and retirement_completed_tick is not None
        and assigned and resumed and active_after == 0 and returncode == 0
        and job_policy is not None and job_policy["verified"]
        and kill_on_close and job_closed and process_handle_closed
        and all(pipe_closed) and all(parent_writers_closed) and all(
            row["eof"] and row["io_settled"] and not row["quarantined"]
            and row["close_completed"] and not row["overflow"]
            and not row["write_extent_unknown"] and not row["retention_failed"]
            and (memory_capture or row["fsync_completed"]) for row in channels
        )
    )
    return {
        "facts": public, "private_channel_bytes": finalized_prefixes,
        "private_primary": primary, "private_secondary": tuple(secondary),
    }


# Definitions only. Controlled execution and privileged read-only admission are separate.

