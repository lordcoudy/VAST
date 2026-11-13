# Fixed read-only ADMINHOST source. Default is a description with no entry authority.
$Pr9ReadonlyController = @'
"""Fixed elevated read-only owner. Definitions only; ordinary source authentication is external."""
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import types
import zlib

ROOT=Path(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST")
HERE=ROOT/"openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01"
INVOCATION=HERE/"grok_bounded_model_invocation_v1.proposed.ps1"
CONTRACT=HERE/"grok_bounded_source_contract_v1.proposed.json"
DRIVER=HERE/"grok_bounded_model_driver_v1.proposed.py"
PYTHON_ROOT=Path(r"C:\Python314")

def notice(state, phase, error):
    if any(error is prior for _,prior in state["errors"]):
        return
    state["error_count"]+=1
    if len(state["errors"])<16:
        state["errors"].append((phase,error))
    else:
        state["cause_overflow"]=True

def own_qualification(driver, admission, sources, custody, tick, prepare=None):
    state={"box":{"capture":None,"document_original":None,"attestation":None},
           "errors":[],"error_count":0,"cause_overflow":False,
           "returned_envelope":None,"remaining_runtime_handles":None,
           "final_runtime_close_causes":None,"final_runtime_close_count":None,
           "final_runtime_close_cause_bound_exceeded":None,"final_runtime_retired":None,
           "final_runtime_close_observed_causes":None,"final_runtime_observed_fields":[],
           "final_runtime_close_return_available":False}
    try:
        if prepare is not None:
            prepare()
        state["returned_envelope"]=driver.run_qualification(
            admission,sources,now_tick=tick(),custody=custody,enclosing_result=state["box"])
    except BaseException as error:
        notice(state,"qualification",error)
    finally:
        try:
            if not custody.retired or custody.handles:
                returned=custody.retire()
                state["final_runtime_close_causes"]=returned
                state["final_runtime_close_return_available"]=True
        except BaseException as error:
            notice(state,"runtime_finalizer",error)
        # Observe each owned field independently even if retire() raised.
        fields=(("close_causes","final_runtime_close_observed_causes"),
                ("close_failure_count","final_runtime_close_count"),
                ("close_cause_bound_exceeded","final_runtime_close_cause_bound_exceeded"),
                ("retired","final_runtime_retired"),("remaining_handles","remaining_runtime_handles"))
        for field,target in fields:
            try:
                value=len(custody.handles) if field=="remaining_handles" else getattr(custody,field)
            except AttributeError:
                continue
            except BaseException as error:
                notice(state,"runtime_observation_"+field,error)
            else:
                state[target]=value
                state["final_runtime_observed_fields"].append(field)
    return state

def pin(value):
    if (type(value) is not dict or set(value)!={"bytes","sha256"} or
        type(value["bytes"]) is not int or not 0<value["bytes"]<=65536 or
        type(value["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}",value["sha256"])):
        raise ValueError("closed bounded input pin required")
    return value

def file_identity(value):
    return (value.st_dev,value.st_ino,value.st_size,value.st_mtime_ns,value.st_birthtime_ns,
            getattr(value,"st_file_attributes",0),value.st_nlink)

def read_original(path, expected):
    pin(expected)
    before=path.lstat()
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or
        getattr(before,"st_file_attributes",0)&0x400 or before.st_size!=expected["bytes"] or
        path.resolve(strict=True)!=path):
        raise ValueError("literal ordinary bounded input")
    descriptor=os.open(path,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT)
    primary=None
    raw=None
    try:
        opened=file_identity(os.fstat(descriptor))
        if opened!=file_identity(before):
            raise ValueError("opened input identity")
        chunks=[]
        count=0
        while True:
            part=os.read(descriptor,min(65536,expected["bytes"]-count+1))
            if not part:
                break
            count+=len(part)
            if count>expected["bytes"]:
                raise ValueError("input grew")
            chunks.append(part)
        raw=b"".join(chunks)
        if (count!=expected["bytes"] or hashlib.sha256(raw).hexdigest()!=expected["sha256"] or
            file_identity(os.fstat(descriptor))!=opened or file_identity(path.lstat())!=opened):
            raise ValueError("input pin or identity changed")
    except BaseException as error:
        primary=error
    try:
        os.close(descriptor)
    except BaseException as closing:
        if primary is None:
            raise
        if closing is not primary:
            raise BaseExceptionGroup("input read and close",[primary,closing])
    if primary is not None:
        raise primary
    return raw

def runtime_census(contract_raw, source_pins):
    contract=json.loads(contract_raw)
    capsule=contract["python314_runtime_census"]
    if type(capsule) is not dict or set(capsule)!={"raw_bytes","sha256","gzip_base64"}:
        raise ValueError("closed runtime capsule")
    if (type(capsule["raw_bytes"]) is not int or not 0<capsule["raw_bytes"]<=65536 or
        type(capsule["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}",capsule["sha256"]) or
        type(capsule["gzip_base64"]) is not str or len(capsule["gzip_base64"])>65536):
        raise ValueError("runtime capsule bound")
    compressed=base64.b64decode(capsule["gzip_base64"],validate=True)
    if base64.b64encode(compressed).decode("ascii")!=capsule["gzip_base64"]:
        raise ValueError("canonical runtime capsule required")
    decoder=zlib.decompressobj(31)
    raw=decoder.decompress(compressed,65537)
    if (len(raw)!=capsule["raw_bytes"] or not decoder.eof or decoder.unconsumed_tail or
        decoder.unused_data or hashlib.sha256(raw).hexdigest()!=capsule["sha256"]):
        raise ValueError("complete bounded runtime capsule")
    value=json.loads(raw)
    if (value.get("scope")!="python314_runtime_census_v1" or value.get("complete") is not True or
        value.get("capacity_accepted") is not False or value.get("application_authority") is not False or
        value.get("loaded_memory_identity_proved") is not False or value.get("source_pins")!=source_pins or
        value.get("file_columns")!=["kind","relative_path_or_source_role","bytes","sha256","identity","close_complete"] or
        value.get("identity_columns")!=["device","inode","mtime_ns","birthtime_ns","attributes","links"]):
        raise ValueError("runtime observation source/schema binding")
    return value

def prepare_inputs(driver, admission, sources, custody, contract_raw, invocation_pin, contract_pin):
    census=runtime_census(contract_raw,admission["source_pins"])
    flags={key:getattr(sys.flags,key) for key in ("isolated","no_site","no_user_site","dont_write_bytecode")}
    if (flags!=census["flags"] or any(value!=1 for value in flags.values()) or
        list(sys.version_info[:3])!=census["python"]["version"] or
        Path(sys.executable)!=PYTHON_ROOT/"python.exe" or
        sys.prefix!=census["python"]["prefix"] or sys.base_prefix!=census["python"]["base_prefix"]):
        raise ValueError("actual isolated interpreter differs")
    if list(sys.getwindowsversion().platform_version)!=census["os_base"]["version"][:3]:
        raise ValueError("trusted Windows build differs")
    if list(sys.path)!=census["python"]["search_paths"] or sys.flags.utf8_mode!=census["python"]["utf8_mode"]:
        raise ValueError("runtime loader inputs differ")
    rows=census["files"]
    if type(rows) is not list or not 5<=len(rows)<=1024:
        raise ValueError("runtime file roster")
    paths=[]
    aggregate=0
    for row in rows:
        if (type(row) is not list or len(row)!=6 or row[0] not in ("source","python") or
            type(row[1]) is not str or not 0<len(row[1])<=512 or
            type(row[2]) is not int or not 0<=row[2]<=67108864 or
            type(row[3]) is not str or not re.fullmatch("[0-9a-f]{64}",row[3]) or
            type(row[4]) is not list or len(row[4])!=6 or row[5] is not True):
            raise ValueError("runtime file row")
        aggregate+=row[2]
        if aggregate>536870912:
            raise ValueError("runtime total byte extent")
        if row[0]=="source":
            if row[1] not in driver.SOURCE_PATHS:
                raise ValueError("unknown source role")
            path=driver.SOURCE_PATHS[row[1]]
            if {"bytes":row[2],"sha256":row[3]}!=admission["source_pins"][row[1]]:
                raise ValueError("runtime source row differs")
        else:
            relative=Path(row[1])
            if relative.is_absolute() or relative.drive or ".." in relative.parts or relative.as_posix()!=row[1]:
                raise ValueError("runtime relative path")
            path=PYTHON_ROOT/relative
            if path.resolve(strict=True)!=path or not path.is_relative_to(PYTHON_ROOT):
                raise ValueError("runtime path origin")
        if path in paths:
            raise ValueError("duplicate runtime path")
        paths.append(path)
    if aggregate!=census["aggregate_file_bytes"] or not set(driver.SOURCE_PATHS.values()).issubset(paths):
        raise ValueError("complete runtime input inventory")
    for path,expected in [(INVOCATION,invocation_pin),(CONTRACT,contract_pin)]+[
            (driver.SOURCE_PATHS[role],admission["source_pins"][role]) for role in ("capture","driver","guard","jobs")]:
        custody.hold_ancestors(path)
        custody.hold(path)
        driver.snapshot(path,expected["bytes"],expected["sha256"])
    for path,row in zip(paths,rows):
        custody.hold_ancestors(path)
        custody.hold(path)
        driver.snapshot(path,row[2],row[3])
        actual=path.lstat()
        identity=[str(actual.st_dev),str(actual.st_ino),str(actual.st_mtime_ns),str(actual.st_birthtime_ns),
                  getattr(actual,"st_file_attributes",0),actual.st_nlink]
        if identity!=row[4]:
            raise ValueError("runtime object differs from observed census")
    configuration=[str(PYTHON_ROOT/"python._pth"),str(PYTHON_ROOT/"python314._pth"),
                   str(PYTHON_ROOT/"pyvenv.cfg"),r"C:\pyvenv.cfg"]
    if census["absent_configuration"]!=configuration:
        raise ValueError("closed configuration absence roster")
    for path in configuration:
        try:
            Path(path).lstat()
        except FileNotFoundError:
            pass
        else:
            raise ValueError("runtime configuration appeared")

def run_operator(admission, contract_pin, invocation_pin, tick):
    if type(admission) is not dict or type(admission.get("source_pins")) is not dict:
        raise ValueError("closed ordinary reviewed admission required")
    for value in admission["source_pins"].values():
        pin(value)
    pin(contract_pin);pin(invocation_pin)
    driver_raw=read_original(DRIVER,admission["source_pins"]["driver"])
    driver=types.ModuleType("pr9_authenticated_operator_driver")
    exec(compile(driver_raw,"authenticated-operator-driver","exec"),driver.__dict__)
    driver.validate_admission(admission,tick())
    if Path.cwd()!=ROOT:
        raise ValueError("literal operator working directory")
    parent=driver.qualify_parent(sample_floors=False)
    if parent["boot_filetime"]!=admission["boot_filetime"]:
        raise ValueError("ordinary boot differs")
    sources={}
    custody=driver.RuntimeCustody()
    def prepare():
        for role in ("capture","driver","guard","jobs"):
            sources[role]=read_original(driver.SOURCE_PATHS[role],admission["source_pins"][role])
        contract_raw=read_original(CONTRACT,contract_pin)
        prepare_inputs(driver,admission,sources,custody,contract_raw,invocation_pin,contract_pin)
        if not 15000<admission["deadline_tick_ms"]-tick()<=180000:
            raise ValueError("original deadline expired before metadata entry")
    state=own_qualification(driver,admission,sources,custody,tick,prepare)
    state["parent"]=parent
    return state

def public_cause(phase,error):
    name=type(error).__name__
    return {"phase":phase,"type":name if re.fullmatch("[A-Za-z0-9_]{1,128}",name) else "unavailable"}

def encode(value,limit):
    raw=json.dumps(value,ensure_ascii=True,separators=(",",":"),allow_nan=False).encode("ascii")
    if len(raw)>limit:
        raise ValueError("complete operator frame exceeds ceiling")
    return raw

def make_frame(state,admission,bootstrap_close,tick):
    try:
        late=tick()>=admission["deadline_tick_ms"]
    except BaseException as error:
        notice(state,"outer_completion_clock",error)
        late=None
    box=state["box"]
    original=box["document_original"]
    attestation=box["attestation"]
    outer={"errors":[public_cause(*item) for item in state["errors"]],
           "error_count":state["error_count"],"cause_overflow":state["cause_overflow"],
           "remaining_runtime_handles":state["remaining_runtime_handles"],
           "final_runtime_close_causes":state["final_runtime_close_causes"],
           "final_runtime_close_count":state["final_runtime_close_count"],
           "final_runtime_close_observed_causes":state["final_runtime_close_observed_causes"],
           "final_runtime_close_cause_bound_exceeded":state["final_runtime_close_cause_bound_exceeded"],
           "final_runtime_retired":state["final_runtime_retired"],
           "final_runtime_observed_fields":state["final_runtime_observed_fields"],
           "final_runtime_close_return_available":state["final_runtime_close_return_available"],
           "bootstrap_source_close":bootstrap_close,"deadline_exceeded":late}
    frame={"scope":"actual_operator_readonly_metadata_output_v1","parent":state.get("parent"),
           "entry_approval":admission.get("entry_approval"),"attestation":attestation,"outer":outer,
           "controller_retirement_proved":False,"qualification_accepted":False,
           "capacity_accepted":False,"application_authority":False}
    persistence=None if attestation is None else attestation.get("persistence")
    if (original is not None and persistence is not None and persistence.get("complete") is True and
        state["error_count"]==0 and state["remaining_runtime_handles"]==0 and
        bootstrap_close is True and late is False):
        frame.update({"witness_original_bytes":len(original),"witness_original_sha256":hashlib.sha256(original).hexdigest()})
        try:
            return encode(frame,4095)
        except BaseException as error:
            notice(state,"normal_frame_encoding",error)
            outer["errors"]=[public_cause(*item) for item in state["errors"]]
            outer["error_count"]=state["error_count"]
    frame["witness_original_base64"]=None if original is None else base64.b64encode(original).decode("ascii")
    captured=box["capture"]
    if original is None and captured is not None:
        frame["unencoded_capture"]={"facts":captured["facts"],
            "prefixes_base64":[None if raw is None else base64.b64encode(raw).decode("ascii")
                               for raw in captured["private_channel_bytes"]],
            "causes":([] if captured["private_primary"] is None else [public_cause(*captured["private_primary"])])+
                     [public_cause(*row) for row in captured["private_secondary"]]}
    return encode(frame,65535)

def emit_frame(raw):
    if type(raw) is not bytes or not 0<len(raw)<=65535:
        raise ValueError("operator output pre-write bound")
    errors=[]
    written=0
    try:
        view=memoryview(raw+b"\n")
        while view:
            count=sys.stdout.buffer.write(view)
            if type(count) is not int or not 0<count<=len(view):
                raise OSError("operator output stalled")
            written+=count
            view=view[count:]
    except BaseException as error:
        errors.append(("operator_stdout_write",error))
    try:
        sys.stdout.buffer.flush()
    except BaseException as error:
        if not any(error is prior for _,prior in errors):
            errors.append(("operator_stdout_flush",error))
    if errors:
        fallback=encode({"scope":"operator_output_failed_hold","known_stdout_bytes":written,
                         "original_frame_bytes":len(raw),"original_frame_sha256":hashlib.sha256(raw).hexdigest(),
                         "causes":[public_cause(*item) for item in errors],"qualification_accepted":False},4095)+b"\n"
        try:
            view=memoryview(fallback)
            while view:
                count=sys.stderr.buffer.write(view)
                if type(count) is not int or not 0<count<=len(view):
                    break
                view=view[count:]
        finally:
            sys.stderr.buffer.flush()
        return 1
    return 0
'@

$Pr9ReadonlyBootstrap = @'
import base64,ctypes,hashlib,json,os,re,stat,struct,sys
from ctypes import wintypes
from pathlib import Path
path=Path(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST\openspec\changes\fix-accepted-policy-preprocessing\evidence\grok-runtime-boundary-20261028-01\grok_bounded_model_invocation_v1.proposed.ps1")
kernel=ctypes.WinDLL("kernel32",use_last_error=True)
tick=kernel.GetTickCount64
tick.argtypes=[];tick.restype=ctypes.c_ulonglong
close=kernel.CloseHandle
close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
handle=None
closed=None
namespace=None
state=None
errors=[]
admission={}
def failed(phase,error):
    if not any(error is old for _,old in errors):
        errors.append((phase,error))
def kind(error):
    name=type(error).__name__
    return name if re.fullmatch("[A-Za-z0-9_]{1,128}",name) else "unavailable"
try:
    text=os.environ.get("PR9_OPERATOR_ADMISSION","")
    if not 0<len(text)<=8192: raise ValueError("admission text bound")
    decoded=base64.b64decode(text,validate=True)
    if len(decoded)>6144 or base64.b64encode(decoded).decode("ascii")!=text:
        raise ValueError("canonical admission")
    admission=json.loads(decoded)
    pins=[]
    for key in ("PR9_INVOCATION_PIN","PR9_CONTRACT_PIN"):
        text=os.environ.get(key,"")
        if not 0<len(text)<=256: raise ValueError("pin text bound")
        value=json.loads(text)
        if type(value) is not dict or set(value)!={"bytes","sha256"} or type(value["bytes"]) is not int or not 0<value["bytes"]<=65536 or type(value["sha256"]) is not str or not re.fullmatch("[0-9a-f]{64}",value["sha256"]):
            raise ValueError("source pin shape")
        pins.append(value)
    invocation_pin,contract_pin=pins
    before=path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1 or getattr(before,"st_file_attributes",0)&0x400 or before.st_size!=invocation_pin["bytes"] or path.resolve(strict=True)!=path:
        raise ValueError("literal source identity")
    create=kernel.CreateFileW
    create.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    create.restype=wintypes.HANDLE
    opened=create(str(path),0x80000000,1,None,3,0x02200000,None)
    if opened in (None,ctypes.c_void_p(-1).value): raise ctypes.WinError(ctypes.get_last_error())
    handle=opened
    basic=ctypes.create_string_buffer(52)
    query=kernel.GetFileInformationByHandle
    query.argtypes=[wintypes.HANDLE,ctypes.c_void_p];query.restype=wintypes.BOOL
    identity=ctypes.create_string_buffer(24)
    query_id=kernel.GetFileInformationByHandleEx
    query_id.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD];query_id.restype=wintypes.BOOL
    if not query(handle,basic) or not query_id(handle,18,identity,24): raise ctypes.WinError(ctypes.get_last_error())
    fields=struct.unpack("<13I",basic.raw)
    if fields[0]&0x410 or fields[10]!=1 or (fields[8]<<32)|fields[9]!=invocation_pin["bytes"] or (int.from_bytes(identity.raw[:8],"little"),int.from_bytes(identity.raw[8:],"little"))!=(before.st_dev,before.st_ino):
        raise ValueError("opened source identity differs")
    read=kernel.ReadFile
    read.argtypes=[wintypes.HANDLE,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD),ctypes.c_void_p];read.restype=wintypes.BOOL
    raw=bytearray()
    buffer=ctypes.create_string_buffer(16384)
    count=wintypes.DWORD()
    while True:
        maximum=min(len(buffer),invocation_pin["bytes"]-len(raw)+1)
        if not read(handle,buffer,maximum,ctypes.byref(count),None): raise ctypes.WinError(ctypes.get_last_error())
        if count.value==0: break
        if count.value>maximum or count.value>invocation_pin["bytes"]-len(raw): raise ValueError("source grew")
        raw.extend(buffer.raw[:count.value])
    after=path.lstat()
    if len(raw)!=invocation_pin["bytes"] or hashlib.sha256(raw).hexdigest()!=invocation_pin["sha256"] or (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns):
        raise ValueError("source pin changed")
    normalized=bytes(raw).replace(b"\r\n",b"\n")
    marker=b"$Pr9ReadonlyController = @'\n"
    if normalized.count(marker)!=1: raise ValueError("unique controller literal")
    suffix=normalized.split(marker,1)[1]
    controller,separator,remainder=suffix.partition(b"\n'@")
    if not separator or not 0<len(controller)<=32768: raise ValueError("complete controller literal bound")
    namespace={"__name__":"pr9_authenticated_adminhost_controller"}
    exec(compile(controller.decode("utf-8"),"authenticated-readonly-controller","exec"),namespace)
    state=namespace["run_operator"](admission,contract_pin,invocation_pin,tick)
except BaseException as error:
    failed("operator_entry",error)
finally:
    if handle is not None:
        original=handle;handle=None
        try:
            if not close(original): raise ctypes.WinError(ctypes.get_last_error())
            closed=True
        except BaseException as error:
            closed=False
            failed("bootstrap_source_close",error)
try:
    if state is not None:
        for phase,error in errors: namespace["notice"](state,phase,error)
        raw=namespace["make_frame"](state,admission,closed,tick)
        status=namespace["emit_frame"](raw)
    else:
        raw=json.dumps({"scope":"operator_entry_failed_hold","causes":[{"phase":p,"type":kind(e)} for p,e in errors],
                        "bootstrap_source_close":closed,"qualification_accepted":False},separators=(",",":")).encode("ascii")
        if len(raw)>4095: raise ValueError("entry failure encoding bound")
        status=1
        os.write(1,raw+b"\n")
except BaseException as error:
    # Sink/encoding failure makes complete evidence unavailable; never infer success.
    failed("operator_terminal",error)
    raw=json.dumps({"scope":"operator_terminal_failed_hold","causes":[{"phase":p,"type":kind(e)} for p,e in errors],
                    "bootstrap_source_close":closed,"qualification_accepted":False},separators=(",",":")).encode("ascii")
    try:
        if len(raw)<=4095: os.write(2,raw+b"\n")
    except BaseException:
        pass
    status=1
sys.exit(status)
'@

function Invoke-Pr9ReadonlyMetadata {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$AdmissionBase64,
        [Parameter(Mandatory)][int]$InvocationBytes,
        [Parameter(Mandatory)][string]$InvocationSha256,
        [Parameter(Mandatory)][int]$ContractBytes,
        [Parameter(Mandatory)][string]$ContractSha256,
        [Parameter(Mandatory)][long]$OriginalDeadlineTickMs
    )
    $pr9Errors=[Collections.Generic.List[object]]::new()
    $pr9Seen=[Collections.Generic.List[object]]::new()
    $pr9Overflow=$false
    $pr9ErrorCount=0
    $pr9Process=$null
    $pr9Started=$false
    $pr9Pid=$null
    $pr9Creation=$null
    $pr9Exited=$null
    $pr9ExitCode=$null
    $pr9Killed=$false
    $pr9ProcessClosed=$null
    $pr9Deadline=$OriginalDeadlineTickMs
    function Add-Pr9OperatorFailure([string]$Phase,[Exception]$Problem) {
        if ($pr9Seen.Contains($Problem)) { return }
        $pr9Seen.Add($Problem)
        if ($pr9Errors.Count -lt 16) {
            $name=$Problem.GetType().Name
            if ($name -notmatch '^[A-Za-z0-9_]{1,128}$') { $name='unavailable' }
            $pr9Errors.Add([ordered]@{phase=$Phase;type=$name})
        }
    }
    try {
        $pr9Remaining=$pr9Deadline-[Environment]::TickCount64
        if ($pr9Deadline -le 0L -or $pr9Remaining -le 15000L -or $pr9Remaining -gt 180000L) {
            throw 'inherited original operator deadline required'
        }
        if ($AdmissionBase64.Length -lt 1 -or $AdmissionBase64.Length -gt 8192 -or
            $InvocationBytes -lt 1 -or $InvocationBytes -gt 65536 -or
            $ContractBytes -lt 1 -or $ContractBytes -gt 65536 -or
            $InvocationSha256 -cnotmatch '^[0-9a-f]{64}$' -or $ContractSha256 -cnotmatch '^[0-9a-f]{64}$') {
            throw 'closed operator parameters required'
        }
        $admissionRaw=[Convert]::FromBase64String($AdmissionBase64)
        if ($admissionRaw.Length -gt 6144 -or [Convert]::ToBase64String($admissionRaw) -cne $AdmissionBase64) {
            throw 'canonical bounded operator admission required'
        }
        $admission=([Text.UTF8Encoding]::new($false,$true).GetString($admissionRaw) | ConvertFrom-Json -AsHashtable -Depth 8)
        if ($admission['deadline_tick_ms'] -isnot [long] -and $admission['deadline_tick_ms'] -isnot [int]) {
            throw 'integer original deadline placeholder required'
        }
        if ($admission['deadline_tick_ms'] -ne 0) { throw 'unused zero original deadline placeholder required' }
        $admission['deadline_tick_ms']=$pr9Deadline
        $admissionText=$admission | ConvertTo-Json -Depth 8 -Compress
        $encoded=[Text.Encoding]::UTF8.GetBytes($admissionText)
        if ($encoded.Length -gt 6144) { throw 'bounded launch admission required' }
        $info=[Diagnostics.ProcessStartInfo]::new()
        $info.FileName='C:\Python314\python.exe'
        $info.UseShellExecute=$false
        $info.WorkingDirectory='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
        $info.Environment.Clear()
        $info.Environment['SystemRoot']='C:\Windows'
        $info.Environment['WINDIR']='C:\Windows'
        $info.Environment['USERPROFILE']='C:\Users\s-a-balashov'
        $info.Environment['TEMP']='C:\Users\s-a-balashov\AppData\Local\Temp'
        $info.Environment['TMP']='C:\Users\s-a-balashov\AppData\Local\Temp'
        $info.Environment['PR9_OPERATOR_ADMISSION']=[Convert]::ToBase64String($encoded)
        $info.Environment['PR9_INVOCATION_PIN']=(@{bytes=$InvocationBytes;sha256=$InvocationSha256}|ConvertTo-Json -Compress)
        $info.Environment['PR9_CONTRACT_PIN']=(@{bytes=$ContractBytes;sha256=$ContractSha256}|ConvertTo-Json -Compress)
        foreach ($argument in @('-I','-B','-S','-c',$Pr9ReadonlyBootstrap)) { $info.ArgumentList.Add($argument) }
        if ($Pr9ReadonlyBootstrap.Length -gt 16000) { throw 'fixed bootstrap native argument ceiling' }
        $pr9Process=[Diagnostics.Process]::new()
        $pr9Process.StartInfo=$info
        if ([Environment]::TickCount64 -ge $pr9Deadline-15000L) { throw 'original deadline expired before controller start' }
        if (-not $pr9Process.Start()) { throw 'original controller did not start' }
        $pr9Started=$true
        $pr9Pid=$pr9Process.Id
        $pr9Creation=$pr9Process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString([Globalization.CultureInfo]::InvariantCulture)
    } catch { Add-Pr9OperatorFailure 'controller_start' $_.Exception }
    finally {
        if ($pr9Process -and $pr9Started) {
            try {
                $remaining=[Math]::Max(0L,$pr9Deadline-[Environment]::TickCount64-1000L)
                $pr9Exited=$pr9Process.WaitForExit([int][Math]::Min(180000L,$remaining))
                if (-not $pr9Exited) {
                    $pr9Process.Kill($false)
                    $pr9Killed=$true
                    $remaining=[Math]::Max(0L,$pr9Deadline-[Environment]::TickCount64)
                    $pr9Exited=$pr9Process.WaitForExit([int][Math]::Min(1000L,$remaining))
                }
                if ($pr9Exited) { $pr9ExitCode=$pr9Process.ExitCode }
            } catch { Add-Pr9OperatorFailure 'controller_retirement' $_.Exception }
        }
        if ($pr9Process) {
            try { $pr9Process.Dispose();$pr9ProcessClosed=$true }
            catch { $pr9ProcessClosed=$false;Add-Pr9OperatorFailure 'controller_handle_close' $_.Exception }
        }
    }
    $pr9ErrorCount=$pr9Seen.Count
    $pr9Overflow=$pr9ErrorCount -gt 16
    $receipt=[ordered]@{
        scope='actual_operator_controller_retirement_v1'
        original_pid=$pr9Pid
        original_creation_filetime=$pr9Creation
        started=$pr9Started
        exited=$pr9Exited
        exit_code=$pr9ExitCode
        forced_original_controller=$pr9Killed
        child_backend_retirement_inferred_from_controller=$false
        ambient_console_input_owned=$false
        process_handle_close_completed=$pr9ProcessClosed
        original_deadline_tick_ms=$pr9Deadline
        deadline_exceeded=([Environment]::TickCount64 -ge $pr9Deadline)
        causes=$pr9Errors.ToArray()
        cause_count=$pr9ErrorCount
        cause_bound_exceeded=$pr9Overflow
        qualification_accepted=$false
        capacity_accepted=$false
    }
    $receiptText=$receipt | ConvertTo-Json -Depth 6 -Compress
    if ([Text.Encoding]::ASCII.GetByteCount($receiptText) -gt 4094) { throw 'controller receipt pre-write bound' }
    [Console]::Out.WriteLine($receiptText)
}

if ($MyInvocation.InvocationName -ne '.') {
    '{"scope":"readonly_operator_definitions_v1","execution_authority":false,"capacity_accepted":false}'
}
