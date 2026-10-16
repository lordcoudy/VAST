"""Inert on import. Require independent exact-code/SHA review, CI, recorded approval.
Args: reviewed commit, PR9 approval URL; operator verifies approval.
No C/D/retry/signal/cleanup/image action. Never reset capture context/deadline/baseline.
Caller retains actual OS status and both EOFs; no future-return self-authentication.
Native calls trusted/non-preemptible; late/unknown refuses.
"""
import base64
import ctypes
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
sys.dont_write_bytecode=True
import threading
import time
COMMIT=None
SETUP_REL="tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py"
CAPTURE_REL="tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py"
COMPONENT_REL="tests/fixtures/accepted_policy_fixture_compiler_component_v1.py"
RETENTION_REL=("openspec/changes/fix-accepted-policy-preprocessing/evidence/"
                 "compiler-component-01/gate2-f2-c75a-retention.v1.json")
REPO=str(Path(__file__).resolve().parents[2])
REPO_LINUX="/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST"
ROOT=""
BROOT="/home/s-a-balashov/work/vast-fixture-compiler-component-8c08cd30f2355a26b2e7a31b53e6f268acafda29-01"
F2ROOT=AUX=UNC=UNC_AUX=""
GIT=r"C:\Program Files\Git\cmd\git.exe"
WSL="C:/Windows/System32/wsl.exe"
PLAN="openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/component-admission-plan.v8.md"
CODE=(
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_component_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_publisher_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_seccomp_v1.json",
    "scripts/publication_operational_request_domain_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_recovery_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_p0_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py",
    "tests/fixtures/accepted_policy_fixture_compiler_gate2_d_child_v1.py",
)
P0_MAX=387328
OUTSIDE=524288
FINAL_TAIL=65536
CAPTURE_RESERVE=65536
ENV={"SystemRoot":"C:/Windows","WINDIR":"C:/Windows","PATH":"C:/Windows/System32;C:/Windows",
       "GIT_OPTIONAL_LOCKS":"0","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"NUL"}
EVENTS=[]
DEADLINE=None
FAILED_PREFIXES=None
CONTEXT_ENV="VAST_GATE2_CAPTURE_CONTEXT_V1"
PHASE_CAPS={"export":4096,"f2":4096,"p0-gate":1024,"packet":4096}
AUX_CAPS={"operator.command.original.json":4096,"operator.authority.original.json":8192,
            "p0.return.original.json":4096,"setup.native-phases.original.json":24576,
            "b2.corrected-index.v1.json":65536}
for _phase,_cap in PHASE_CAPS.items():
    AUX_CAPS[_phase+".stdout.original"]=_cap
    AUX_CAPS[_phase+".stderr.original"]=0
AUX_QUOTE=4352 + sum(((n+4095)//4096)*4096+256 for n in AUX_CAPS.values())
def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
def authority_record_v1(*,code_commit,approval_reference,operator_sha256,helper_code,context_sha256,context):
    return {"schema_version":1,"code_commit":code_commit,"approval_reference":approval_reference,
            "operator_sha256":operator_sha256,"helper_code":helper_code,"context_sha256":context_sha256,
            "context":context,"external_approval_required":True}
def require(value,cause):
    if not value:
        raise RuntimeError(cause)
def _configure_reviewed_commit_v1(commit):
    global COMMIT,ROOT,F2ROOT,AUX,UNC,UNC_AUX
    require(type(commit) is str and re.fullmatch("[0-9a-f]{40}",commit),"external_reviewed_commit")
    COMMIT=commit
    ROOT="/home/s-a-balashov/work/vast-fixture-compiler-gate2-"+commit+"-01"
    F2ROOT,AUX=ROOT+".f2",ROOT+".operator-originals"
    UNC,UNC_AUX="//wsl.localhost/Ubuntu"+ROOT,"//wsl.localhost/Ubuntu"+AUX
def check():
    require(DEADLINE is not None and time.monotonic_ns() < DEADLINE,"setup_150s_deadline")
def bounded_source(path):
    require(path.resolve(strict=True)==path,"fixed_source_path")
    expected=path.lstat()
    require(stat.S_ISREG(expected.st_mode) and expected.st_nlink==1 and 0<expected.st_size<=65536,"fixed_source_bound")
    epoch=lambda s,cross=False:(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,
        getattr(s,"st_birthtime_ns",None),None if cross and os.name=="nt" else s.st_ctime_ns,getattr(s,"st_blocks",None))
    flags=os.O_RDONLY|getattr(os,"O_NONBLOCK",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)|getattr(os,"O_BINARY",0)
    fd=os.open(path,flags)
    try:file=os.fdopen(fd,"rb",buffering=0)
    except BaseException:
        os.close(fd)
        raise
    with file:
        before=os.fstat(file.fileno())
        require(epoch(before,True)==epoch(expected,True),"fixed_source_open_identity")
        raw=file.read(65537)
        after=os.fstat(file.fileno())
        require(len(raw)==before.st_size and epoch(before)==epoch(after) and epoch(path.lstat())==epoch(expected),"fixed_source_drift")
    return raw
def capture_context():
    raw=os.environ.get(CONTEXT_ENV,"").encode("ascii")
    require(0 < len(raw) <= 4096,"inherited_capture_context_required")
    value=json.loads(raw)
    names={"schema_version","code_commit","windows_start_ns","windows_deadline_ns","linux_start_ns",
             "linux_deadline_ns","baseline","boot_id","capture_source_sha256","capture_source_quote_bytes",
             "operator_source_quote_bytes","helper_git_forms_quote_bytes",
             "capture_all_forms_reserved_bytes","pre_meter_native","helper_code","retention"}
    require(type(value) is dict and set(value) == names and canonical(value) == raw,"capture_context_shape")
    require(type(value["retention"]) is dict and set(value["retention"])=={"git_observation","native"},
            "capture_prior_retention_required")
    require(type(value["schema_version"]) is int and value["schema_version"] == 1 and value["code_commit"] == COMMIT,
            "capture_context_version_commit")
    for name in ("windows_start_ns","windows_deadline_ns","linux_start_ns","linux_deadline_ns",
                 "capture_source_quote_bytes","capture_all_forms_reserved_bytes"):
        require(type(value[name]) is int and value[name] > 0,"capture_context_integer")
    require(value["windows_deadline_ns"] - value["windows_start_ns"] == 150000000000
            and value["windows_start_ns"] <= time.monotonic_ns() < value["windows_deadline_ns"]
            and value["linux_start_ns"] < value["linux_deadline_ns"] <= value["linux_start_ns"] + 150000000000,
            "capture_original_deadline")
    baseline=value["baseline"]
    require(type(baseline) is dict and set(baseline) == {"c_free_bytes","ext4_used_bytes"}
            and all(type(n) is int and n >= 0 for n in baseline.values())
            and baseline["c_free_bytes"] >= 43620761600,"capture_baseline")
    require(type(value["boot_id"]) is str and re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",value["boot_id"]),"capture_boot")
    source=bounded_source(Path(REPO)/CAPTURE_REL)
    require(value["capture_source_sha256"] == sha(source)
            and math.ceil(len(source) / 4096) * 4096 + 4096 <= value["capture_source_quote_bytes"] <= 131072
            and value["capture_all_forms_reserved_bytes"] == CAPTURE_RESERVE,"capture_source_quote")
    operator_source=bounded_source(Path(__file__))
    require(type(value["operator_source_quote_bytes"]) is int and
        math.ceil(len(operator_source)/4096)*4096+4096<=value["operator_source_quote_bytes"]<=131072,"operator_source_quote")
    helpers=value["helper_code"]
    require(type(helpers) is dict and set(helpers)=={SETUP_REL,CAPTURE_REL},"helper_code_set")
    require(all(type(d) is dict and type(d.get("size_bytes")) is int and 0<d["size_bytes"]<=65536 for d in helpers.values()),"helper_size")
    require(type(value["helper_git_forms_quote_bytes"]) is int and value["helper_git_forms_quote_bytes"]==
        sum(math.ceil(d["size_bytes"]/4096)*4096+4096 for d in helpers.values()),"helper_git_forms_quote")
    require(sum(value[k] for k in ("operator_source_quote_bytes","capture_source_quote_bytes","helper_git_forms_quote_bytes"))
            +AUX_QUOTE+CAPTURE_RESERVE+49152<=OUTSIDE,"prospective_outside_forms")
    native=value["pre_meter_native"]
    require(type(native) is dict and set(native) == {"pid","returncode","stdout_eof","stderr_eof","stdout_sha256","stderr_sha256"}
            and type(native["pid"]) is int and 0 < native["pid"] < 2 ** 32
            and type(native["returncode"]) is int and native["returncode"] == 0
            and native["stdout_eof"] is True and native["stderr_eof"] is True
            and type(native["stdout_sha256"]) is str and re.fullmatch("[0-9a-f]{64}",native["stdout_sha256"])
            and native["stderr_sha256"] == sha(b""),"capture_pre_meter_native")
    return value,sha(raw)
DIAGNOSTIC_SOURCE=r'''
def exception_detail_v1(error,facts_cap=16384,prefix_cap=8192):
    def encode(value):
        return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
    value={"cause":type(error).__name__,"message":str(error)[:512],"causes":list(getattr(error,"causes",()))}
    facts=getattr(error,"facts",None)
    if facts is not None:
        raw=encode(facts)
        if len(raw)<=facts_cap:value["facts"]=facts
        else:
            value.update(facts_prefix_base64=base64.b64encode(raw[:prefix_cap]).decode("ascii"),
                facts_sha256=hashlib.sha256(raw).hexdigest(),facts_bytes=len(raw),facts_remainder_unknown=True)
            fields={"pid","returncode","status","wait_status","stdout_eof","stderr_eof","stdin_closed","reaped",
                "unknown_closure","extent_unknown","late","written_bytes","close_completed","fsync_completed",
                "open_completed","completed","complete","failure_record_persisted","completion_record_persisted",
                "write_extent_unknown","request_write_extent_unknown","reply_write_extent_unknown",
                "eof_stdout","eof_stderr","normal_exit","forced_parent_termination",
                "parent_termination_proves_linux_child_closure","linux_child_closure","persisted_bytes","flush_completed"}
            rows=[]; unknown=False
            def visit(item,path,depth):
                nonlocal unknown
                if depth>12:unknown=True; return
                if type(item) is dict:
                    row={}
                    for key,child in item.items():
                        if key in fields:
                            if child is None or type(child) in (bool,int) or (key=="linux_child_closure" and type(child) is str and len(child)<=128):
                                row[key]=child
                            else:unknown=True
                    causes=item.get("causes")
                    if type(causes) is list and all(type(v) is str for v in causes):row["causes"]=causes
                    if row:
                        record={"path":path,"facts":row}
                        if len(encode(rows+[record]))<=4096:rows.append(record)
                        else:unknown=True
                    for key,child in item.items():
                        if type(child) in (dict,list):visit(child,(path+"/"+str(key))[:160],depth+1)
                elif type(item) is list:
                    for index,child in enumerate(item):
                        if type(child) in (dict,list):visit(child,(path+"/"+str(index))[:160],depth+1)
            visit(facts,"",0)
            value.update(known_facts=rows,known_facts_remainder_unknown=unknown)
    return value
'''
exec(DIAGNOSTIC_SOURCE)
def failure_document_v1(error):
    value={"setup_completed":False,"physical_acceptance":False,"external_packet_approval":False,"c_or_d_invoked":False,
        "exception":exception_detail_v1(error),
        "known_processes":[{k:row.get(k) for k in ("pid","returncode","stdout_eof","stderr_eof","late","unknown_closure")}
                           for row in EVENTS],"failed_retained_prefixes":FAILED_PREFIXES,
        "external_driver_status_and_eof_required":True}
    if len(canonical(value))+1>32768:
        value["exception"]=exception_detail_v1(error,facts_cap=4096,prefix_cap=4096)
    require(len(canonical(value))+1<=32768,"failure_protocol_bound")
    return value
def failed_prefixes_v1(buffers,event,observed):
    result={"argv_sha256":event["argv_sha256"],"streams":{}}
    for name in ("stdout","stderr"):
        kept=bytes(buffers[name][:4096]); count,digest=observed[name]
        result["streams"][name]={"prefix_base64":base64.b64encode(kept).decode("ascii"),
            "observed_bytes":count,"observed_sha256":digest.hexdigest(),"retained_bytes":len(kept),
            "discarded_bytes":count-len(kept),"remainder_unknown":not event[name+"_eof"] or event["overflow"],
            "discarded":count>len(kept)}
    return result
def fixed_process(argv,payload=b"",cap=12288):
    global FAILED_PREFIXES
    check()
    event={"argv_sha256":sha(canonical(argv)),"stdin_bytes":len(payload),
             "stdin_sha256":sha(payload),"pid":None,"returncode":None,"stdout_eof":False,
             "stderr_eof":False,"stdin_closed":False,"stdin_written_bytes":0,
             "overflow":False,"unknown_closure":True,"late":False}
    EVENTS.append(event)
    process=subprocess.Popen(argv,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                               env=ENV,shell=False,close_fds=True)
    event["pid"]=process.pid
    if time.monotonic_ns() >= DEADLINE:
        event["late"]=True
        raise RuntimeError("spawn_returned_late_known_pid_unknown_closure")
    buffers={"stdout":bytearray(),"stderr":bytearray()}
    observed={name:[0,hashlib.sha256()] for name in buffers}
    prefix_lock=threading.Lock()
    failures=[]
    def read(stream,name,limit):
        try:
            while time.monotonic_ns() < DEADLINE:
                block=os.read(stream.fileno(),min(4096,limit - len(buffers[name]) + 1))
                if not block:
                    event[name + "_eof"]=True
                    return
                with prefix_lock:
                    observed[name][0]+=len(block); observed[name][1].update(block)
                    available=limit - len(buffers[name])
                    buffers[name].extend(block[:available])
                if len(block) > available:
                    event["overflow"]=True
                    return
        except BaseException as error:
            failures.append(name + "_" + type(error).__name__)
    def write():
        try:
            offset=0
            while offset < len(payload):
                check()
                count=os.write(process.stdin.fileno(),payload[offset:offset + 4096])
                require(type(count) is int and 0 < count <= min(4096,len(payload) - offset),"stdin_extent")
                offset += count
                event["stdin_written_bytes"]=offset
            check()
            process.stdin.close()
            event["stdin_closed"]=True
        except BaseException as error:
            failures.append("stdin_" + type(error).__name__)
    threads=[threading.Thread(target=read,args=(process.stdout,"stdout",cap),daemon=True),
               threading.Thread(target=read,args=(process.stderr,"stderr",131072),daemon=True),
               threading.Thread(target=write,daemon=True)]
    for thread in threads:
        thread.start()
    while time.monotonic_ns() < DEADLINE:
        event["returncode"]=process.poll()
        if all(not thread.is_alive() for thread in threads) and event["returncode"] is not None:
            break
        if failures or event["overflow"]:
            break
        time.sleep(0.005)
    event["late"]=time.monotonic_ns() >= DEADLINE
    event["unknown_closure"]=not (event["returncode"] is not None and event["stdout_eof"] and event["stderr_eof"])
    event["stdout_bytes"],event["stderr_bytes"]=len(buffers["stdout"]),len(buffers["stderr"])
    event["stdout_sha256"],event["stderr_sha256"]=sha(buffers["stdout"]),sha(buffers["stderr"])
    event["failures"]=failures
    passed=(not event["late"] and not event["unknown_closure"] and not event["overflow"] and not failures
              and event["returncode"] == 0 and event["stdin_closed"] and event["stdin_written_bytes"] == len(payload))
    if not passed:
        with prefix_lock:
            FAILED_PREFIXES=failed_prefixes_v1(buffers,event,observed)
            stderr=bytes(buffers["stderr"])
        error=RuntimeError("native_invocation_refused")
        if argv[0]==WSL and 0<len(stderr)<=32768:
            try:
                native=json.loads(stderr)
                if type(native) is dict and {"cause","message","causes"}<=set(native) and canonical(native)+b"\n"==stderr:
                    error.facts={"native_failure":native,"native_event":dict(event)}
                    error.causes=native["causes"]
            except (ValueError,TypeError):pass
        raise error
    process.stdout.close()
    process.stderr.close()
    return bytes(buffers["stdout"]),bytes(buffers["stderr"])
def git(args,cap=262144):
    raw,err=fixed_process([GIT,"--no-pager","--no-replace-objects","--no-optional-locks","-C",REPO,
                              "-c","core.fsmonitor=false"] + args,cap=cap)
    require(not err,"git_stderr")
    return raw
def _authenticate_helper_code_v1(descriptors):
    require(type(descriptors) is dict and set(descriptors)=={SETUP_REL,CAPTURE_REL},"helper_code_set")
    require(git(["rev-parse","--verify","HEAD"],cap=64)==(COMMIT+"\n").encode("ascii"),"helper_git_head")
    tree_raw=git(["ls-tree","-z",COMMIT,"--",SETUP_REL,CAPTURE_REL],cap=4096)
    rows={}
    for entry in tree_raw.rstrip(b"\0").split(b"\0"):
        header,path=entry.split(b"\t",1)
        mode,kind,blob=header.decode("ascii").split()
        name=path.decode("ascii")
        require(mode=="100644" and kind=="blob" and re.fullmatch("[0-9a-f]{40}",blob) and name not in rows,"helper_git_tree")
        rows[name]=blob
    require(set(rows)=={SETUP_REL,CAPTURE_REL},"helper_git_inventory")
    for name in (SETUP_REL,CAPTURE_REL):
        value=descriptors[name]
        require(type(value) is dict and set(value)=={"path","size_bytes","sha256","git_blob"},"helper_descriptor")
        require(value["path"]==str(Path(REPO)/name) and type(value["size_bytes"]) is int
                and 0<value["size_bytes"]<=65536 and value["git_blob"]==rows[name],"helper_descriptor_binding")
        raw=git(["cat-file","blob",rows[name]],cap=65536)
        local=bounded_source(Path(REPO)/name)
        require(raw==local and len(raw)==value["size_bytes"] and sha(raw)==value["sha256"]
            and hashlib.sha1(b"blob "+str(len(raw)).encode("ascii")+b"\0"+raw).hexdigest()==rows[name],"helper_source_drift")
    return json.loads(canonical(descriptors))
def _load_exported_p0_v1():
    sys.dont_write_bytecode=True
    sys.path[:0]=[UNC,UNC+"/scripts"]
    spec=importlib.util.spec_from_file_location("vast_gate2_exported_p0",Path(UNC)/CODE[7])
    module=importlib.util.module_from_spec(spec)
    require(sys.dont_write_bytecode is True,"bytecode_disabled_before_exported_p0_import")
    spec.loader.exec_module(module)
    check()
    require(DEADLINE-time.monotonic_ns()>=42000000000,"insufficient_original_setup_budget_after_p0_import")
    return module
def _dispatch_p0_v1(module,binding):
    check()
    require(DEADLINE-time.monotonic_ns()>=42000000000,"insufficient_original_setup_budget_immediately_before_p0")
    return module.collect_native_p0_v1(UNC+"/p0",binding,reviewed_code_commit=COMMIT)
def tree():
    raw=git(["ls-tree","-z",COMMIT,"--"] + list(CODE) + [PLAN,RETENTION_REL],cap=16384)
    rows={}
    for entry in raw.rstrip(b"\0").split(b"\0"):
        header,path=entry.split(b"\t",1)
        mode,kind,blob=header.decode("ascii").split()
        path=path.decode("ascii")
        require(mode == "100644" and kind == "blob" and re.fullmatch("[0-9a-f]{40}",blob) and path not in rows,"git_tree")
        rows[path]=blob
    require(set(rows) == set(CODE) | {PLAN,RETENTION_REL},"git_exact_source_set")
    return rows
def _validate_retention_context_v1(context,code,rows,plan):
    retention=context["retention"]; observation=retention["git_observation"]
    require(type(observation) is dict and set(observation)=={"component","index","old_git_sha256"},"retention_git_observation")
    require(canonical(observation["component"])==canonical(code[COMPONENT_REL]),"retention_component_code_binding")
    raw=bounded_source(Path(REPO)/COMPONENT_REL)
    require(len(raw)==code[COMPONENT_REL]["size_bytes"] and sha(raw)==code[COMPONENT_REL]["sha256"] and
        hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==code[COMPONENT_REL]["git_blob"],
        "retention_current_component_drift")
    index_raw=git(["cat-file","blob",rows[RETENTION_REL]],cap=12288)
    index=observation["index"]
    require(type(index) is dict and set(index)=={"size_bytes","sha256","git_blob"} and
        type(index["size_bytes"]) is int and len(index_raw)==index["size_bytes"] and sha(index_raw)==index["sha256"] and
        index["git_blob"]==rows[RETENTION_REL] and hashlib.sha1(b"blob "+str(len(index_raw)).encode()+b"\0"+index_raw).hexdigest()==index["git_blob"],
        "retention_current_index_drift")
    namespace=_component_namespace_v1(raw,Path(REPO)/COMPONENT_REL)
    bindings=namespace["retained_source_bindings_v1"](Path(REPO))
    require(bindings["index"]=={k:index[k] for k in ("size_bytes","sha256")} and
        observation["old_git_sha256"]==bindings["source_rows_sha256"],"retention_pinned_index_binding")
    namespace["validate_prior_retention_receipt_v1"](retention["native"],source_rows_sha256=bindings["source_rows_sha256"])
    namespace["current_code_forms_quote_v1"](Path(REPO),code=code,plan=plan)
    check()
    return json.loads(canonical(retention))
def _component_namespace_v1(raw,path):
    sys.dont_write_bytecode=True
    namespace={"__name__":"vast_gate2_setup_retention","__file__":str(path)}
    exec(compile(raw,str(path),"exec"),namespace)
    return namespace
WRITER_SOURCE=r'''
def owned_write_v1(path,raw,check,fsync):
    facts={"path":str(path),"open_completed":False,"write_started":False,"written_bytes":0,
           "extent_unknown":False,"flush_completed":False,"fsync_completed":False,
           "close_completed":False,"complete":False,"causes":[]}
    file=None; first=None; phase="open"
    try:
        check(); file=path.open("xb",buffering=0); facts["open_completed"]=True; check()
        phase="write"; facts["write_started"]=True; facts["extent_unknown"]=True
        count=file.write(raw)
        if type(count) is not int or not 0<=count<=len(raw):raise RuntimeError("write_count_unknown")
        facts["written_bytes"]=count; facts["extent_unknown"]=False
        if count!=len(raw):raise RuntimeError("short_write")
        check(); phase="flush"; file.flush(); facts["flush_completed"]=True; check()
        phase="fsync"; fsync(file.fileno()); facts["fsync_completed"]=True; check()
    except BaseException as error:
        first=error; facts["causes"].append(phase+"_"+type(error).__name__)
    if file is not None:
        try:
            file.close(); facts["close_completed"]=True
        except BaseException as error:
            if first is None:first=error
            facts["causes"].append("close_"+type(error).__name__)
    if first is None:
        try:check()
        except BaseException as error:
            first=error; facts["causes"].append("post_close_"+type(error).__name__)
    if first is not None:
        facts["initiating_message"]=str(first)[:512]
        first.facts=facts; first.causes=list(facts["causes"])
        raise first
    facts["complete"]=True
    return facts
'''
exec(WRITER_SOURCE)
def persist(name,raw,cap):
    check()
    require("/" not in name and "\\" not in name and len(raw) <= cap,"aux_bound")
    path=Path(UNC_AUX) / name
    facts=owned_write_v1(path,raw,check,os.fsync)
    facts["path"]=AUX+"/"+name
    return dict(facts,size_bytes=len(raw),sha256=sha(raw))
PRELUDE=WRITER_SOURCE + DIAGNOSTIC_SOURCE + r'''
import base64,hashlib,json,os,re,stat,sys,time,types
from pathlib import Path
data=sys.stdin.buffer.read(2097153); assert len(data)<=2097152
x=json.loads(data)
COMMIT=x["code_commit"]; assert type(COMMIT) is str and re.fullmatch("[0-9a-f]{40}",COMMIT)
ROOT=Path("/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + COMMIT + "-01")
BROOT=Path("/home/s-a-balashov/work/vast-fixture-compiler-component-8c08cd30f2355a26b2e7a31b53e6f268acafda29-01")
F2ROOT,AUX=Path(str(ROOT)+".f2"),Path(str(ROOT)+".operator-originals")
assert sys.version_info[:3] == (3,12,3)
assert (os.getuid(),os.geteuid(),os.getgid(),os.getegid()) == (1000,1000,1000,1000)
assert os.statvfs("/").f_frsize == 4096 and ROOT.parent.resolve(strict=True) == ROOT.parent
assert os.statvfs("/mnt/c").f_frsize == 4096
assert ROOT.parent.stat().st_dev == Path("/").stat().st_dev
def canon(v):return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
def sha(v):return hashlib.sha256(v).hexdigest()
def rounded(n):return max(4096,((n+4095)//4096)*4096)+256
def measure():
    e,c=os.statvfs("/"),os.statvfs("/mnt/c")
    return {"ext4_used_bytes":(e.f_blocks-e.f_bfree)*e.f_frsize,"c_free_bytes":c.f_bavail*c.f_frsize}
def floors(liability=0):
    assert type(liability) is int and liability>=0
    p=os.statvfs(ROOT.parent)
    assert p.f_frsize==4096 and p.f_bavail*p.f_frsize>=1073741824+liability
    assert measure()["c_free_bytes"]>=43620761600+liability
def boot():return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
def growth(a,b):return max(0,a["c_free_bytes"]-b["c_free_bytes"],b["ext4_used_bytes"]-a["ext4_used_bytes"])
def allocated(root):
    pending=[root]; total=count=0
    while pending:
        p=pending.pop(); count+=1; assert count<=1024 and p.resolve(strict=True)==p
        s=p.lstat(); assert not stat.S_ISLNK(s.st_mode)
        assert stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode) and s.st_nlink==1
        assert type(s.st_blocks) is int and s.st_blocks>=0
        total+=max(4096 if stat.S_ISDIR(s.st_mode) else 0,s.st_blocks*512)+256
        if stat.S_ISDIR(s.st_mode):
            with os.scandir(p) as entries:
                for entry in entries:
                    assert count+len(pending)<1024
                    pending.append(p/entry.name)
    return total
def outside_funded(used,copies,remaining):
    assert all(type(v) is int and v>=0 for v in (used,copies,remaining))
    assert used+copies+remaining<=524288
_limits_cache=None
def limits():
    global _limits_cache
    if _limits_cache is None:
        path=Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/tests/fixtures/accepted_policy_fixture_compiler_component_v1.py")
        desc=x["prior_retention"]["git_observation"]["component"]
        assert path.resolve(strict=True)==path
        a=path.lstat(); assert stat.S_ISREG(a.st_mode) and a.st_nlink==1 and 0<a.st_size<=262144
        epoch=lambda s:(s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns,getattr(s,"st_blocks",None))
        flags=os.O_RDONLY|getattr(os,"O_NONBLOCK",0)|getattr(os,"O_NOFOLLOW",0)|getattr(os,"O_CLOEXEC",0)
        fd=os.open(path,flags)
        try:f=os.fdopen(fd,"rb",buffering=0)
        except BaseException:
            os.close(fd)
            raise
        with f:
            assert epoch(a)==epoch(os.fstat(f.fileno()))
            raw=f.read(262145); b=os.fstat(f.fileno())
            assert epoch(a)==epoch(b)
        assert len(raw)==desc["size_bytes"] and sha(raw)==desc["sha256"]
        assert hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==desc["git_blob"]
        namespace={"__name__":"vast_gate2_setup_fixed_limits","__file__":str(path)}
        exec(compile(raw,str(path),"exec"),namespace)
        _limits_cache=types.SimpleNamespace(**namespace)
    return _limits_cache
def funded_requirement(baseline,after,root_used,f2_used,outside,f2tail):
    assert all(type(v) is int and v>=0 for v in (root_used,f2_used,outside,f2tail))
    assert root_used<=1048576 and outside<=524288
    actual=max(0,baseline["c_free_bytes"]-after["c_free_bytes"],after["ext4_used_bytes"]-baseline["ext4_used_bytes"],root_used+f2_used+outside)
    future=max(0,1048576-root_used)+max(0,524288-outside)+f2tail
    return limits().CURRENT_CODE_FORMS_V1+limits().PRIOR_CARRY_BYTES_V1+11890688+1048576+actual+future
def assert_funded(required,charged):
    assert type(required) is int and type(charged) is int and required<=charged<536870912
def gate(liability=0,reserve_ns=0):
    assert type(x["linux_deadline_ns"]) is int and time.monotonic_ns()+reserve_ns<x["linux_deadline_ns"]
    assert boot()==x["boot_id"]
    floors(liability)
    limits()
    assert time.monotonic_ns()+reserve_ns<x["linux_deadline_ns"]
def modules():
    sys.path[:0]=[str(ROOT),str(ROOT/"scripts")]
    for name,path in (("tests",ROOT/"tests"),("tests.fixtures",ROOT/"tests/fixtures")):
        package=types.ModuleType(name); package.__path__=[str(path)]; sys.modules[name]=package
    from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
    from tests.fixtures import accepted_policy_fixture_compiler_recovery_v1 as f
    return c,f
def emit(v):
    raw=canon(v); assert len(raw)+1<=12288
    sys.stdout.buffer.write(raw+b"\n"); sys.stdout.buffer.flush()
def failed(kind,error,tb):
    value=exception_detail_v1(error)
    raw=canon(value); assert len(raw)+1<=131072
    sys.stderr.buffer.write(raw+b"\n"); sys.stderr.buffer.flush()
sys.excepthook=failed
'''
EXPORT=PRELUDE + r'''
entry=time.monotonic_ns(); baseline=x["baseline"]; current_boot=boot()
gate(1048576+524288,142000000000)
local_deadline=min(x["linux_deadline_ns"],entry+10000000000)
def mutate_check():
    assert time.monotonic_ns()<local_deadline
    floors(1048576+524288)
    assert time.monotonic_ns()<local_deadline
mutate_check()
assert not os.path.lexists(ROOT) and not os.path.lexists(F2ROOT) and not os.path.lexists(AUX)
assert set(x)=={"files","code","plan_sha256","outside_preexisting_quote","baseline","boot_id","linux_deadline_ns","code_commit","aux_quote","prior_retention"}
outside_funded(x["outside_preexisting_quote"],49152,x["aux_quote"]+65536)
code=x["code"]; assert len(code)==10 and set(x["files"])==set(code)|{"physical-plan.v8.md"}
quote=sum(rounded(v["size_bytes"]) for v in code.values())+rounded(len(base64.b64decode(x["files"]["physical-plan.v8.md"])))
quote+=4*4352+rounded(4096)
packet_cap=min(131072,((655360-quote-256)//4096)*4096)
assert packet_cap>0 and quote+rounded(packet_cap)<=655360
assert quote+rounded(packet_cap)+387328<=1048576
for directory in (ROOT,AUX,ROOT/"tests",ROOT/"tests/fixtures",ROOT/"scripts"):
    mutate_check(); directory.mkdir(mode=0o700); mutate_check()
for relative,encoded in x["files"].items():
    mutate_check()
    raw=base64.b64decode(encoded,validate=True)
    assert len(raw)<=262144
    if relative in code:
        d=code[relative]
        assert len(raw)==d["size_bytes"] and sha(raw)==d["sha256"]
        assert hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==d["git_blob"]
    else:assert sha(raw)==x["plan_sha256"]
    target=ROOT/relative
    owned_write_v1(target,raw,mutate_check,os.fsync)
    mutate_check()
    with target.open("rb") as file:observed=file.read(len(raw)+1)
    mutate_check(); assert observed==raw
for directory in (ROOT/"tests/fixtures",ROOT/"tests",ROOT/"scripts",ROOT,AUX):
    mutate_check(); fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY)
    try:
        mutate_check(); os.fsync(fd); mutate_check()
    finally:os.close(fd)
    mutate_check()
mutate_check()
emit({"baseline":baseline,"after_export":measure(),"boot_id":current_boot,"linux_entry_ns":entry,
      "code_quote_bytes":quote+rounded(packet_cap),"packet_cap":packet_cap,"code":code})
'''
RECOVER=PRELUDE + r'''
gate(limits().ACTIVE_F2_LIMIT_V1,132000000000)
assert boot()==x["boot_id"]
c,f=modules()
assert tuple(x["code"])==c.CODE_PATHS or set(x["code"])==set(c.CODE_PATHS)
c._verify_code(ROOT,x["code"])
early=growth(x["baseline"],measure())
remaining=536870912-limits().CURRENT_CODE_FORMS_V1-limits().PRIOR_CARRY_BYTES_V1-11890688-2*1048576-max(0,early-1048576-524288)
outside_funded(x["outside_preexisting_quote"],49152,x["aux_quote"]+65536)
gate(limits().ACTIVE_F2_LIMIT_V1,132000000000)
r=f.recover_stopped_b1_v1(output_dir=F2ROOT,
    review={"commit":COMMIT,"approval_reference":x["approval"],"physical_plan_sha256":x["plan_sha256"]},
    b1_originals={"report":BROOT/"outputs/B1/compiler.stdout.original",
                  "inspect":BROOT/"outputs/B1/RPC10.reply.original","provider":BROOT/"outputs/B1/RPC03.reply.original"},
    remaining_seal_bytes=remaining,retained_elsewhere_upper_bytes=524288)
assert time.monotonic_ns()<x["linux_deadline_ns"]
verified=f.validate_supplement_v1(output_dir=F2ROOT,supplement=r["supplement"])
assert verified["complete"] is True and r["supplement"]["controlled"] is False
outside_funded(x["outside_preexisting_quote"],f._outside_copy_lower_bound(F2ROOT),x["aux_quote"]+65536)
before,after=r["supplement"]["identity"]["before"],r["supplement"]["identity"]["after"]
assert before==after and before["engine_id"]=="1e493309-3767-45fb-9078-05b838bdfd80"
gate(65536)
index_value=c._b2_index_value(BROOT)
gate(65536)
index_written=c.write_record_v1(AUX/"b2.corrected-index.v1.json",index_value,cap=65536,
    absolute_deadline_ns=x["linux_deadline_ns"],return_facts=True)
index=index_written["descriptor"]
assert boot()==x["boot_id"] and time.monotonic_ns()<x["linux_deadline_ns"]
emit({"engine_id":before["engine_id"],"boot_id":boot(),"b2_index":index,"b2_index_write_facts":index_written["write_facts"],"f2_verified":verified,
      "supplement_descriptor":r["supplement_descriptor"],"final_accounting_descriptor":r["final_accounting_descriptor"]})
'''
PACKET=PRELUDE + r'''
deadline=x["linux_deadline_ns"]
gate(x["packet_cap"]+65536)
c,f=modules(); c._verify_code(ROOT,x["code"])
supp=json.loads(c._read(F2ROOT/"f2.supplement.v1.json",262144))
f.validate_supplement_v1(output_dir=F2ROOT,supplement=supp)
footer=json.loads(c._read(F2ROOT/"f2.final-accounting.v1.json",limits().F2_FOOTER_LIMIT_V1)); account=footer["accounting"]
f2tail=account["reserved_control_bytes"]+account["reserved_rounding_bytes"]+account["reserved_metadata_bytes"]
assert account["physical_charge_bytes"]+f2tail<=limits().ACTIVE_F2_LIMIT_V1
def descriptor(p):
    raw=c._read(p,1048576); return {"path":str(p),"size_bytes":len(raw),"sha256":sha(raw)}
evidence={"b1_result":descriptor(BROOT/"outputs/B1/probe.result.original.json"),
 "b1_report":descriptor(BROOT/"outputs/B1/compiler.stdout.original"),
 "b2_result":descriptor(BROOT/"outputs/B2/probe.result.original.json"),
 "b2_report":descriptor(BROOT/"outputs/B2/compiler.stdout.original"),
 "b3_result":descriptor(BROOT/"outputs/B3/probe.result.original.json"),
 "b2_manifest":descriptor(BROOT/"runs/B2.originals.sha256"),
 "b2_index":descriptor(AUX/"b2.corrected-index.v1.json"),
 "f2_supplement":descriptor(F2ROOT/"f2.supplement.v1.json"),
 "f2_index":descriptor(F2ROOT/"f2.originals.v1.json"),"f2_accounting":descriptor(F2ROOT/"f2.final-accounting.v1.json")}
outside=allocated(AUX)+x["outside_preexisting_quote"]
copies=f._outside_copy_lower_bound(F2ROOT)
outside_funded(x["outside_preexisting_quote"],copies,x["aux_quote"]+65536)
assert allocated(AUX)<=x["aux_quote"]
now=measure(); root_used=allocated(ROOT); f2_used=allocated(F2ROOT)
assert root_used<=1048576
minimum=limits().CURRENT_CODE_FORMS_V1+limits().PRIOR_CARRY_BYTES_V1+11890688+2*1048576+account["physical_charge_bytes"]+f2tail+max(0,c.interval_charge_v1(account["last"],now,retained_bytes=0)-f2tail-1048576)
charged=max(minimum,funded_requirement(x["baseline"],now,root_used,f2_used,outside,f2tail))+65536
assert charged<536870912 and now["c_free_bytes"]>=43620761600
p0=descriptor(ROOT/"p0/p0-completion.v1.json")
returned_p0=json.loads(c._read(AUX/"p0.return.original.json",12288))
assert returned_p0["accepted"] is True and returned_p0["causes"]==[] and returned_p0["controlled"] is False
assert returned_p0["code_commit"]==COMMIT and returned_p0["reviewed_operator_sha256"]==x["operator_sha256"]
assert p0["sha256"]==returned_p0["completion_record"]["sha256"] and p0["size_bytes"]==returned_p0["completion_record"]["encoded_bytes"]
authority_raw=c._bound_descriptor(x["authority_descriptor"],root=AUX,cap=8192)
authority=json.loads(authority_raw)
assert authority["code_commit"]==COMMIT and authority["approval_reference"]==x["approval"]
assert authority["context_sha256"]==x["context_sha256"] and authority["operator_sha256"]==x["operator_sha256"]
packet=c.build_packet_v1(project_root=ROOT,
    review={"commit":COMMIT,"approval_reference":x["approval"],"evidence_sha256":sha(authority_raw)},
    physical_plan_descriptor=descriptor(ROOT/"physical-plan.v8.md"),code=x["code"],evidence=evidence,
    p0_descriptor=p0,boot_id=x["boot_id"],initial_charged_bytes=charged,initial_measurement=now,
    operator_authority_descriptor=x["authority_descriptor"],prior_retention=x["prior_retention"])
raw=canon(packet); seed=canon(packet["seed"])
assert len(raw)<=x["packet_cap"] and len(seed)<=4096
assert sum(rounded(d["size_bytes"]) for d in x["code"].values())+rounded((ROOT/"physical-plan.v8.md").stat().st_size)+4*4352+rounded(4096)+rounded(len(raw))<=655360
gate(rounded(len(raw))+65536)
written=c.write_record_v1(ROOT/"gate2.packet.original.json",packet,cap=x["packet_cap"],absolute_deadline_ns=deadline,return_facts=True)
assert written["write_facts"]["complete"] is True and written["write_facts"]["close_completed"] is True
after=measure(); root_after=allocated(ROOT); outside_after=allocated(AUX)+x["outside_preexisting_quote"]
outside_funded(x["outside_preexisting_quote"],copies,x["aux_quote"]+65536)
assert allocated(AUX)<=x["aux_quote"]
required_after=funded_requirement(x["baseline"],after,root_after,allocated(F2ROOT),outside_after,f2tail)
assert_funded(required_after,charged)
assert after["c_free_bytes"]>=43620761600 and time.monotonic_ns()<deadline and boot()==x["boot_id"]
emit({"packet":written["descriptor"],"packet_write_facts":written["write_facts"],"initial_charged_bytes":charged,
      "initial_measurement":now,"after_packet_measurement":after,"post_packet_required_bytes":required_after,
      "remaining_funded_tail_bytes":charged-required_after,
      "external_packet_approval":False,"c_or_d_invoked":False})
'''
FINAL=PRELUDE + r'''
gate(65536)
c,f=modules()
packet_raw=c._bound_descriptor(x["packet_descriptor"],root=ROOT,cap=131072)
packet=json.loads(packet_raw); account=json.loads(c._read(F2ROOT/"f2.final-accounting.v1.json",limits().F2_FOOTER_LIMIT_V1))["accounting"]
f2tail=account["reserved_control_bytes"]+account["reserved_rounding_bytes"]+account["reserved_metadata_bytes"]
assert account["physical_charge_bytes"]+f2tail<=limits().ACTIVE_F2_LIMIT_V1
now=measure(); root_used=allocated(ROOT); outside=allocated(AUX)+x["outside_preexisting_quote"]
outside_funded(x["outside_preexisting_quote"],f._outside_copy_lower_bound(F2ROOT),x["aux_quote"]+65536)
assert allocated(AUX)<=x["aux_quote"]
required=funded_requirement(x["baseline"],now,root_used,allocated(F2ROOT),outside,f2tail)
assert_funded(required,packet["initial_charged_bytes"])
assert now["c_free_bytes"]>=43620761600
assert time.monotonic_ns()<x["linux_deadline_ns"]
emit({"final_measurement":now,"required_charge_bytes":required,"funded_initial_charge_bytes":packet["initial_charged_bytes"],
      "funded_remaining_tail_bytes":packet["initial_charged_bytes"]-required,"external_return_proof_reserve_bytes":65536})
'''
P0_GATE=PRELUDE + r'''
gate(387328+x["packet_cap"]+65536,42000000000)
emit({"project_floor_checked":True,"c_floor_checked":True,"linux_deadline_ns":x["linux_deadline_ns"],"boot_id":boot()})
'''
def wsl_phase(name,source,payload):
    raw,err=fixed_process([WSL,"-d","Ubuntu","-u","s-a-balashov","--cd","/","--exec",
                              "/usr/bin/python3","-B","-c",source],canonical(payload),cap=PHASE_CAPS[name])
    require(not err,name + "_stderr")
    if Path(UNC_AUX).is_dir():
        persist(name + ".stdout.original",raw,PHASE_CAPS[name])
        persist(name + ".stderr.original",err,0)
    value=json.loads(raw)
    require(type(value) is dict,name + "_result")
    return value
def main():
    global DEADLINE
    require(os.name == "nt" and len(sys.argv) == 3 and
            re.fullmatch(r"https://github\.com/lordcoudy/VAST/pull/9#issuecomment-[0-9]+",sys.argv[2]),
            "reviewed_commit_and_explicit_approval_comment_required")
    _configure_reviewed_commit_v1(sys.argv[1])
    approval=sys.argv[2]
    context,context_sha=capture_context()
    started=context["windows_start_ns"]
    DEADLINE=context["windows_deadline_ns"]
    check()
    helper_code=_authenticate_helper_code_v1(context["helper_code"])
    source_raw=bounded_source(Path(__file__))
    operator_sha=sha(source_raw)
    require(len(source_raw) <= 65536,"operator_source_bound")
    rows=tree()
    files,code={},{}
    for relative in CODE + (PLAN,):
        raw=git(["cat-file","blob",rows[relative]])
        require(hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest() == rows[relative],"git_blob_bytes")
        files[relative if relative in CODE else "physical-plan.v8.md"]=base64.b64encode(raw).decode("ascii")
        if relative in CODE:
            code[relative]={"size_bytes":len(raw),"sha256":sha(raw),"git_blob":rows[relative]}
    plan_raw=base64.b64decode(files["physical-plan.v8.md"])
    retention=_validate_retention_context_v1(context,code,rows,{"size_bytes":len(plan_raw),"sha256":sha(plan_raw),"git_blob":rows[PLAN]})
    outside_preexisting=(context["operator_source_quote_bytes"] + context["capture_source_quote_bytes"]
                           + context["helper_git_forms_quote_bytes"])
    linux_deadline=context["linux_deadline_ns"]
    require(DEADLINE - time.monotonic_ns() >= 142000000000,"insufficient_original_setup_budget_before_export")
    exported=wsl_phase("export",EXPORT,{"files":files,"code":code,
        "plan_sha256":sha(base64.b64decode(files["physical-plan.v8.md"])),"outside_preexisting_quote":outside_preexisting,
        "baseline":context["baseline"],"boot_id":context["boot_id"],"linux_deadline_ns":linux_deadline,
        "code_commit":COMMIT,"aux_quote":AUX_QUOTE,"prior_retention":retention})
    def exported_unchanged():
        require(tree() == rows,"reviewed_git_tree_changed")
        for relative,descriptor in code.items():
            with (Path(UNC) / relative).open("rb") as file:
                raw=file.read(descriptor["size_bytes"] + 1)
            require(len(raw) == descriptor["size_bytes"] and sha(raw) == descriptor["sha256"],"exported_source_changed")
        check()
    exported_unchanged()
    ctypes.windll.kernel32.GetCommandLineW.restype=ctypes.c_wchar_p
    command=ctypes.windll.kernel32.GetCommandLineW()
    persist("operator.command.original.json",canonical({"command_text":command,"command_sha256":sha(command.encode("utf-8")),
        "argv":sys.argv,"python":sys.executable,"operator_sha256":operator_sha,"code_commit":COMMIT,
        "approval_reference":approval,"external_status_and_eof_required":True}),4096)
    authority=persist("operator.authority.original.json",canonical(authority_record_v1(code_commit=COMMIT,
        approval_reference=approval,operator_sha256=operator_sha,helper_code=helper_code,
        context_sha256=context_sha,context=context)),8192)
    authority_descriptor={k:authority[k] for k in ("path","size_bytes","sha256")}
    require(DEADLINE - time.monotonic_ns() >= 132000000000,"insufficient_original_setup_budget_for_f2_p0_packet")
    common={"code":code,"baseline":exported["baseline"],"boot_id":exported["boot_id"],
              "linux_deadline_ns":linux_deadline,"approval":approval,
              "plan_sha256":sha(base64.b64decode(files["physical-plan.v8.md"])),
              "outside_preexisting_quote":outside_preexisting,"operator_sha256":operator_sha,
              "packet_cap":exported["packet_cap"],"code_commit":COMMIT,"aux_quote":AUX_QUOTE,
              "authority_descriptor":authority_descriptor,"context_sha256":context_sha,"prior_retention":retention}
    recovered=wsl_phase("f2",RECOVER,common)
    exported_unchanged()
    require(DEADLINE - time.monotonic_ns() >= 42000000000,"insufficient_original_setup_budget_for_p0_packet")
    p0=_load_exported_p0_v1()
    wsl_phase("p0-gate",P0_GATE,common)
    result=_dispatch_p0_v1(p0,{
        "known_engine_id":recovered["engine_id"],"boot":{"boot_id":recovered["boot_id"]},
        "provenance":{"source":"external","observer":"ordinary_api","engine_id":recovered["engine_id"],
                       "boot_id":recovered["boot_id"]}})
    try:
        check()
        completion=result.get("completion_record")
        require(result.get("accepted") is True and result.get("causes") == [] and result.get("controlled") is False
                and result.get("physical_acceptance") is False and type(completion) is dict,"p0_native_refused")
        proof=completion["write_proof"]
        require(all(proof.get(key) is True for key in ("open_completed","fsync_completed","close_completed","completed"))
                and proof.get("late") is False and proof.get("extent_unknown") is False
                and proof.get("written_bytes") == completion["encoded_bytes"] and proof.get("prefix_sha256") == completion["sha256"],
                "p0_completion_write_refused")
        persist("p0.return.original.json",canonical({"code_commit":COMMIT,"accepted":True,"causes":[],"controlled":False,
            "physical_acceptance":False,"completion_record":completion,"reviewed_operator_sha256":operator_sha,
            "kernel_preemption_claimed":False,"external_invocation_status_and_eof_required":True}),4096)
    except BaseException as error:
        error.facts={"returned_p0":result,"post_return_failure":getattr(error,"facts",None),
                     "causes":list(getattr(error,"causes",())) or [str(error)[:512]]}
        raise
    exported_unchanged()
    packet=wsl_phase("packet",PACKET,common)
    require(DEADLINE - time.monotonic_ns() >= 1000000000,"final_small_proof_window_exhausted")
    events_raw=canonical({"operator_sha256":operator_sha,"processes":EVENTS,"code_commit":COMMIT})
    event_descriptor=persist("setup.native-phases.original.json",events_raw,24576)
    check()
    final_payload=dict(common,packet_descriptor=packet["packet"])
    final_raw,final_stderr=fixed_process([WSL,"-d","Ubuntu","-u","s-a-balashov","--cd","/","--exec",
                                            "/usr/bin/python3","-B","-c",FINAL],canonical(final_payload))
    require(not final_stderr,"final_meter_stderr")
    final_meter=json.loads(final_raw)
    summary={"setup_completed":True,"physical_acceptance":False,"external_packet_approval":False,
               "c_or_d_invoked":False,"code_commit":COMMIT,"operator_sha256":operator_sha,
               "packet":packet,"native_phase_record":event_descriptor,"elapsed_ns":time.monotonic_ns() - started,
               "operator_authority":authority_descriptor,
               "absolute_deadline_ns":DEADLINE,"windows_start_ns":started,
               "linux_start_ns":context["linux_start_ns"],"linux_deadline_ns":linux_deadline,
               "baseline":context["baseline"],"boot_id":context["boot_id"],"context_sha256":context_sha,
               "outside_preexisting_quote":outside_preexisting,"capture_all_forms_reserved_bytes":65536,
               "final_meter":final_meter,
               "final_meter_process":{key:EVENTS[-1].get(key) for key in ("argv_sha256","stdin_sha256","pid","returncode",
                   "stdout_eof","stderr_eof","late","unknown_closure","stdout_bytes","stderr_bytes","stdout_sha256","stderr_sha256")},
               "external_driver_status_and_eof_required":True}
    raw=canonical(summary)
    require(len(raw)+1 <= 8192,"final_summary_bound_including_newline")
    sys.stdout.buffer.write(raw + b"\n")
    sys.stdout.buffer.flush()
    check()
if __name__ == "__main__":
    try:
        main()
    except BaseException as error:
        detail=failure_document_v1(error)
        failure_raw=canonical(detail)
        require(len(failure_raw)+1<=32768,"failure_prefix_record_bound")
        sys.stderr.buffer.write(failure_raw + b"\n")
        sys.stderr.buffer.flush()
        raise SystemExit(1)
