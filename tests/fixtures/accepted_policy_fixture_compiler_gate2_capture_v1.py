"""Fixed capture: external approval and actual status/EOF required.
No C/D, retries or cleanup. Late/unknown stops; never copy large prefixes.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import threading
import time
from types import ModuleType
HELPER_PATHS = ("tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py",
                "tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py")
RETENTION_PATHS = ("tests/fixtures/accepted_policy_fixture_compiler_component_v1.py",
    "openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-f2-c75a-retention.v1.json")
REPO = Path(__file__).parent.parent.parent
TEMP = Path(r"C:\Users\s-a-balashov\AppData\Local\Temp")
GIT = r"C:\Program Files\Git\cmd\git.exe"
COMMIT = DRIVER = SELF = DRIVER_SHA256 = STDOUT = STDERR = STATUS = ROOT = None
PYTHON = r"C:\Python314\python.exe"
WSL = r"C:\Windows\System32\wsl.exe"
TEMP_LINUX = "/mnt/c/Users/s-a-balashov/AppData/Local/Temp/"
ENV = {"SystemRoot": r"C:\Windows", "WINDIR": r"C:\Windows", "PATH": r"C:\Windows\System32;C:\Windows",
       "GIT_OPTIONAL_LOCKS":"0","GIT_NO_REPLACE_OBJECTS":"1","GIT_CONFIG_NOSYSTEM":"1","GIT_CONFIG_GLOBAL":"NUL"}
START = DEADLINE = None
CAPTURE_END = None
FACTS = {"driver": None, "pre_meter": None, "post_meter": None, "files": {}}
def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
def sha(raw):
    return hashlib.sha256(raw).hexdigest()
class CaptureRefusal(RuntimeError):
    def __init__(self,cause,facts=None):
        super().__init__(cause)
        self.cause,self.facts=cause,{} if facts is None else facts
def require(ok, cause):
    if not ok:
        raise CaptureRefusal(cause)
def validate_arguments_v1(reviewed_commit,approval):
    require(type(reviewed_commit) is str and re.fullmatch("[0-9a-f]{40}",reviewed_commit) is not None and
        type(approval) is str and re.fullmatch(r"https://github\.com/lordcoudy/VAST/pull/9#issuecomment-[0-9]+",approval) is not None,
        "reviewed_commit_and_approval_required")
    # Syntax is not approval. The trusted operator supplies this commit only
    # after independent exact-commit review, required CI and recorded approval.
def check():
    require(DEADLINE is not None and time.monotonic_ns() < min(DEADLINE,CAPTURE_END or DEADLINE), "original_capture_150s_deadline")
def strict_json(raw, cap):
    require(type(raw) is bytes and 0 < len(raw) <= cap, "json_bound")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "json_duplicate")
            result[key] = value
        return result
    value = json.loads(raw.decode("ascii"), object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite")))
    require(type(value) is dict and raw in (canonical(value), canonical(value) + b"\n"), "canonical_json")
    return value
def read_fixed(path, cap):
    require(path.resolve(strict=True)==path,"fixed_physical_file")
    with path.open("rb") as file:
        before=os.fstat(file.fileno())
        require(stat.S_ISREG(before.st_mode) and before.st_nlink==1 and 0<=before.st_size<=cap,"fixed_file_bound")
        raw=file.read(cap+1); after=os.fstat(file.fileno())
        require(len(raw)==before.st_size and (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)==
                (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns),"fixed_file_drift")
    check()
    return raw
METER_PRELUDE = r'''
import hashlib,json,os,stat,sys,time
from pathlib import Path
from types import ModuleType
COMMIT="__REVIEWED_COMMIT__"
ROOT=Path("/home/s-a-balashov/work/vast-fixture-compiler-gate2-"+COMMIT+"-01")
F2=Path(str(ROOT)+".f2"); AUX=Path(str(ROOT)+".operator-originals")
TEMP=Path("/mnt/c/Users/s-a-balashov/AppData/Local/Temp")
assert sys.version_info[:3]==(3,12,3)
assert (os.getuid(),os.geteuid(),os.getgid(),os.getegid())==(1000,1000,1000,1000)
assert ROOT.parent.resolve(strict=True)==ROOT.parent and ROOT.parent.stat().st_dev==Path("/").stat().st_dev
def canon(v): return json.dumps(v,sort_keys=True,separators=(",",":"),ensure_ascii=True,allow_nan=False).encode("ascii")
def sha(v): return hashlib.sha256(v).hexdigest()
def integer(v): return type(v) is int and v>=0
def rounded(n): return ((n+4095)//4096)*4096
def epoch(s):
    return (s.st_dev,s.st_ino,s.st_mode,s.st_nlink,s.st_size,s.st_mtime_ns,s.st_ctime_ns,s.st_blocks)
def read(path,cap):
    assert path.is_absolute() and path.resolve(strict=True)==path
    a=path.lstat()
    assert stat.S_ISREG(a.st_mode) and a.st_nlink==1 and 0<=a.st_size<=cap and integer(a.st_blocks)
    fd=os.open(path,os.O_RDONLY|os.O_NONBLOCK|os.O_NOFOLLOW|os.O_CLOEXEC)
    try:
        f=os.fdopen(fd,"rb",buffering=0)
    except BaseException:
        os.close(fd)
        raise
    with f:
        opened=os.fstat(f.fileno()); assert epoch(opened)==epoch(a)
        raw=f.read(cap+1); b=os.fstat(f.fileno())
        assert len(raw)==a.st_size and epoch(a)==epoch(b)
    return raw,max(a.st_blocks*512,rounded(len(raw)))
def unique(pairs):
    d={}
    for k,v in pairs:
        assert k not in d; d[k]=v
    return d
def load(raw):
    v=json.loads(raw,object_pairs_hook=unique,parse_constant=lambda _:(_ for _ in ()).throw(ValueError("nonfinite")))
    assert type(v) is dict and raw==canon(v)
    return v
def metric():
    c,e=os.statvfs("/mnt/c"),os.statvfs("/")
    assert c.f_frsize==e.f_frsize==4096
    m={"c_free_bytes":c.f_bavail*c.f_frsize,"ext4_used_bytes":(e.f_blocks-e.f_bfree)*e.f_frsize}
    assert m["c_free_bytes"]>=43620761600 and e.f_bavail*e.f_frsize>=1207959552
    with Path("/proc/sys/kernel/random/boot_id").open("rb") as f: raw=f.read(65)
    assert 0<len(raw)<=64
    boot=raw.decode("ascii").strip(); assert len(boot)==36
    return m,boot,time.monotonic_ns(),e.f_bavail*e.f_frsize
def allocated(root):
    assert root.resolve(strict=True)==root
    paths=[root]; total=0
    for p in paths:
        s=p.lstat(); assert integer(s.st_blocks) and not stat.S_ISLNK(s.st_mode)
        assert stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode) and s.st_nlink==1
        total+=max(4096 if stat.S_ISDIR(s.st_mode) else 0,s.st_blocks*512)+256
        if stat.S_ISDIR(s.st_mode):
            with os.scandir(p) as entries:
                for entry in entries:
                    assert len(paths)<1024
                    child=p/entry.name; assert child.resolve(strict=True)==child
                    paths.append(child)
    return total
def retention_component(observation):
    assert type(observation) is dict and set(observation)=={"component","index","old_git_sha256"}
    repo=Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
    for key,name,cap in (("component","tests/fixtures/accepted_policy_fixture_compiler_component_v1.py",262144),
        ("index","openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-f2-c75a-retention.v1.json",12288)):
        desc=observation[key]; assert type(desc) is dict and set(desc)=={"size_bytes","sha256","git_blob"}
        raw,_=read(repo/name,cap)
        assert type(desc["size_bytes"]) is int and len(raw)==desc["size_bytes"] and sha(raw)==desc["sha256"]
        assert hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==desc["git_blob"]
        if key=="component": component_source=raw
    sys.dont_write_bytecode=True
    module=ModuleType("vast_gate2_reviewed_retention")
    module.__file__=str(repo/"tests/fixtures/accepted_policy_fixture_compiler_component_v1.py")
    exec(compile(component_source,module.__file__,"exec"),module.__dict__)
    bindings=module.retained_source_bindings_v1(repo)
    assert observation["old_git_sha256"]==bindings["source_rows_sha256"]
    return module,repo
data=sys.stdin.buffer.read(4097); assert len(data)<=4096
x=load(data)
def emit(v):
    raw=canon(v); assert len(raw)+1<=2048
    sys.stdout.buffer.write(raw+b"\n"); sys.stdout.buffer.flush()
'''
PRE_METER = METER_PRELUDE + r'''
assert set(x)=={"helper_code","retention_git_observation"}
repo=Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST")
names=("tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py","tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py")
assert set(x["helper_code"])==set(names)
quotes=[]
for name in names:
    desc=x["helper_code"][name]; assert set(desc)=={"path","size_bytes","sha256","git_blob"}
    raw,n=read(repo/name,65536)
    assert len(raw)==desc["size_bytes"] and sha(raw)==desc["sha256"]
    assert hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()==desc["git_blob"]
    quotes.append(n+4096)
component,repo=retention_component(x["retention_git_observation"])
retention={"git_observation":x["retention_git_observation"],"native":component.verify_prior_retention_v1(
    repo,git_observation=x["retention_git_observation"])}
m,b,t,p=metric()
emit({"baseline":m,"boot_id":b,"linux_monotonic_ns":t,"project_free_bytes":p,
      "capture_source_quote_bytes":quotes[0],"operator_source_quote_bytes":quotes[1],
      "helper_git_forms_quote_bytes":sum(rounded(x["helper_code"][name]["size_bytes"])+4096 for name in names),
      "c_fragment_bytes":4096,"root_fragment_bytes":4096,"retention":retention})
'''
POST_METER = METER_PRELUDE + r'''
assert set(x)=={"baseline","boot_id","linux_deadline_ns","packet","operator_sha256","operator_authority","context","approval_reference",
               "outside_preexisting_quote","funded_initial_charge_bytes","stdout","stderr"}
assert time.monotonic_ns()<x["linux_deadline_ns"]
retention=x["context"]["retention"]
assert type(retention) is dict and set(retention)=={"git_observation","native"}
component,repo=retention_component(retention["git_observation"])
component.validate_prior_retention_receipt_v1(retention["native"],source_rows_sha256=retention["git_observation"]["old_git_sha256"])
packet_path=ROOT/"gate2.packet.original.json"
assert set(x["packet"])=={"path","size_bytes","sha256"} and x["packet"]["path"]==str(packet_path)
packet_raw,_=read(packet_path,131072)
assert len(packet_raw)==x["packet"]["size_bytes"] and sha(packet_raw)==x["packet"]["sha256"]
packet=load(packet_raw)
assert packet["code_commit"]==COMMIT and packet["project_root"]==str(ROOT)
assert canon(packet["prior_retention"])==canon(retention) and canon(packet["operator_authority"])==canon(x["operator_authority"])
authority_desc=x["operator_authority"]
assert set(authority_desc)=={"path","size_bytes","sha256"} and authority_desc["path"]==str(AUX/"operator.authority.original.json")
authority_raw,_=read(AUX/"operator.authority.original.json",8192)
assert len(authority_raw)==authority_desc["size_bytes"] and sha(authority_raw)==authority_desc["sha256"]
authority=load(authority_raw)
assert set(authority)=={"schema_version","code_commit","approval_reference","operator_sha256","helper_code","context_sha256","context","external_approval_required"}
assert type(authority["schema_version"]) is int and authority["schema_version"]==1 and authority["code_commit"]==COMMIT
assert authority["approval_reference"]==x["approval_reference"] and authority["operator_sha256"]==x["operator_sha256"]
assert canon(authority["context"])==canon(x["context"]) and authority["context_sha256"]==sha(canon(x["context"]))
assert canon(authority["helper_code"])==canon(x["context"]["helper_code"]) and authority["external_approval_required"] is True
helpers=authority["helper_code"]
assert set(helpers)=={"tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py","tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py"}
assert helpers["tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py"]["sha256"]==x["operator_sha256"]
assert packet["code_review"]["evidence_sha256"]==sha(authority_raw) and packet["code_review"]["approval_reference"]==x["approval_reference"]
charged=packet["initial_charged_bytes"]; assert integer(charged) and charged==x["funded_initial_charge_bytes"]<536870912
capture=0
for name,cap in (("stdout",12288),("stderr",32768)):
    desc=x[name]; assert set(desc)=={"size_bytes","sha256"} and integer(desc["size_bytes"])
    raw,n=read(TEMP/("vast-gate2-setup-"+COMMIT+".driver."+name+".original"),cap)
    assert len(raw)==desc["size_bytes"] and sha(raw)==desc["sha256"]
    assert len(raw)<=8192 if name=="stdout" else len(raw)==0
    capture+=n+4096
capture_forms=capture+2*(4096+4096)
assert capture_forms<=32768
footer_desc=packet["evidence"]["f2_accounting"]
assert footer_desc["path"]==str(F2/"f2.final-accounting.v1.json")
footer_raw,_=read(F2/"f2.final-accounting.v1.json",component.F2_FOOTER_LIMIT_V1)
assert len(footer_raw)==footer_desc["size_bytes"] and sha(footer_raw)==footer_desc["sha256"]
account=load(footer_raw)["accounting"]
tail=sum(account[k] for k in ("reserved_control_bytes","reserved_rounding_bytes","reserved_metadata_bytes"))
assert all(integer(account[k]) for k in ("reserved_control_bytes","reserved_rounding_bytes","reserved_metadata_bytes"))
assert integer(account["physical_charge_bytes"]) and account["physical_charge_bytes"]+tail<=component.ACTIVE_F2_LIMIT_V1
root_used,f2_used,aux_used=allocated(ROOT),allocated(F2),allocated(AUX)
outside=aux_used+x["outside_preexisting_quote"]+capture_forms
assert integer(x["outside_preexisting_quote"]) and x["outside_preexisting_quote"]>=32768
assert root_used<=1048576 and outside<=524288
assert not os.path.lexists(F2/"f2.failure.v1.json")
copy_upper=0
for name in ("f2.originals.v1.json","f2.supplement.v1.json","f2.final-accounting.v1.json"):
    raw,_=read(F2/name,component.F2_CONTROL_CAPS_V1[name]); copy_upper+=2*(rounded(len(raw))+4096)
assert outside+copy_upper<=524288
assert f2_used+outside+copy_upper+tail<=component.ACTIVE_F2_LIMIT_V1
now,boot,t,project_free=metric()
assert boot==x["boot_id"] and t<x["linux_deadline_ns"]
base=x["baseline"]; assert set(base)=={"c_free_bytes","ext4_used_bytes"} and all(integer(v) for v in base.values())
growth=max(0,base["c_free_bytes"]-now["c_free_bytes"],now["ext4_used_bytes"]-base["ext4_used_bytes"])
actual=max(growth,root_used+f2_used+outside)
future=max(0,1048576-root_used)+max(0,524288-outside)+tail
required=11890688+1048576+actual+future+component.PRIOR_CARRY_BYTES_V1+component.CURRENT_CODE_FORMS_V1
assert required<=charged and time.monotonic_ns()<x["linux_deadline_ns"]
emit({"measurement":now,"boot_id":boot,"linux_monotonic_ns":t,"project_free_bytes":project_free,
      "required_charge_bytes":required,"funded_initial_charge_bytes":charged,"remaining_funded_bytes":charged-required,
      "capture_all_forms_upper_bytes":capture_forms,"root_allocated_bytes":root_used,"f2_allocated_bytes":f2_used,
      "outside_upper_bytes":outside,"status_and_one_copy_reserved_bytes":16384})
'''
def drain(process, *, limits, files=None, payload=None, until=None):
    """Only pipe I/O for the two literal meter calls and fixed driver below."""
    until = min(DEADLINE,CAPTURE_END or DEADLINE,DEADLINE if until is None else until)
    state = {"pid": process.pid, "returncode": None, "stdout_eof": False, "stderr_eof": False,"limits_bytes":dict(limits),
             "stdin_closed": payload is None, "late": False, "unknown_closure": True, "causes": []}
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    stop = threading.Event()
    def fail(cause):
        state["causes"].append(cause); stop.set()
    for name in ("stdout","stderr"):
        state[name]={"kept_bytes":0,"observed_bytes":0,"sha256":sha(b""),"confirmed_prefix_sha256":sha(b""),
            "write_extent_unknown":False,"flush_completed":False,"fsync_completed":False,"close_completed":False,"failures":[]}
    def reader(name):
        stream = getattr(process, name)
        kept, digest = 0, hashlib.sha256()
        row = state[name]
        try:
            while not stop.is_set() and time.monotonic_ns() < until:
                block = os.read(stream.fileno(), min(4096, limits[name] - kept + 1))
                if not block:
                    state[name + "_eof"] = True
                    stream.close()
                    return
                row["observed_bytes"] += len(block)
                prefix = block[:limits[name] - kept]
                require(time.monotonic_ns() < until and not stop.is_set(), "pipe_read_late")
                if files is None:
                    buffers[name].extend(prefix); written = len(prefix)
                else:
                    try:
                        written = files[name].write(prefix)
                    except BaseException:
                        row["write_extent_unknown"] = True
                        raise
                    if type(written) is not int or not 0 <= written <= len(prefix):
                        row["write_extent_unknown"]=True
                        raise RuntimeError("write_extent_contract")
                kept += written; digest.update(prefix[:written])
                row["kept_bytes"], row["sha256"] = kept, digest.hexdigest()
                row["confirmed_prefix_sha256"]=digest.hexdigest()
                require(written == len(prefix), "capture_short_write")
                require(len(block) == len(prefix), "capture_" + name + "_overflow")
                require(time.monotonic_ns() < until, "capture_write_late")
        except BaseException as error:
            fail(name + "_" + type(error).__name__ + ":" + str(error)[:96])
    def sender():
        try:
            count = 0
            while count < len(payload):
                require(time.monotonic_ns() < until, "meter_stdin_late")
                n = os.write(process.stdin.fileno(), payload[count:count + 4096])
                require(type(n) is int and 0 < n <= min(4096,len(payload)-count), "meter_stdin_extent")
                count += n
            process.stdin.close(); state["stdin_closed"] = True
        except BaseException as error:
            fail("stdin_" + type(error).__name__)
    threads = [threading.Thread(target=reader, args=(name,), daemon=True) for name in ("stdout", "stderr")]
    if payload is not None:
        threads.append(threading.Thread(target=sender, daemon=True))
    for thread in threads:
        thread.start()
    while time.monotonic_ns() < until:
        state["returncode"] = process.poll()
        if state["causes"] or state["returncode"] is not None and all(not t.is_alive() for t in threads):
            break
        time.sleep(0.005)
    state["returncode"] = process.poll()
    state["late"] = time.monotonic_ns() >= until
    state["unknown_closure"] = not (type(state["returncode"]) is int and state["stdout_eof"] and state["stderr_eof"]
                                    and all(not t.is_alive() for t in threads))
    if state["late"] or state["unknown_closure"] or state["causes"]:
        stop.set()
        for name,thread in zip(("stdout","stderr"),threads[:2]):
            if files is not None and thread.is_alive():
                state[name]["write_extent_unknown"]=True
            if state[name]["write_extent_unknown"]:
                state[name]["sha256"]=None
    return state, {k: bytes(v) for k, v in buffers.items()}
def compact_native(state):
    result={k:state[k] for k in ("pid","returncode","stdout_eof","stderr_eof","stdin_closed","late","unknown_closure","argv_sha256")}
    if "stdin_sha256" in state:
        result["stdin_sha256"]=state["stdin_sha256"]
    for name in ("stdout","stderr"):
        result[name+"_bytes"]=state[name]["kept_bytes"]
        result[name+"_sha256"]=state[name]["sha256"]
    return result
def git_v1(args,cap):
    """Only the three read-only Git forms used for the fixed two helpers."""
    allowed=(args==["rev-parse","--verify","HEAD"] or
        len(args)==6 and args[:2]==["ls-tree","-z"] and re.fullmatch("[0-9a-f]{40}",args[2]) and
            args[3:] in (["--"]+list(HELPER_PATHS),["--"]+list(RETENTION_PATHS)) or
        len(args)==3 and args[:2]==["cat-file","blob"] and re.fullmatch("[0-9a-f]{40}",args[2]))
    require(allowed and type(cap) is int and 0<cap<=262144,"fixed_git_request")
    check()
    argv=[GIT,"--no-pager","--no-replace-objects","--no-optional-locks","-C",str(REPO),"-c","core.fsmonitor=false"]+args
    started=time.monotonic_ns()
    try:
        process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
            env=ENV,shell=False,close_fds=True,bufsize=0,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    except BaseException as error:
        facts={"native":{"pid":None,"returncode":None,"stdout_eof":False,"stderr_eof":False,
            "argv_sha256":sha(canonical(argv)),"windows_start_ns":started,"start_exception":type(error).__name__},
            "retained_prefixes_base64":{"stdout":"","stderr":""}}
        FACTS["git_failure"]=facts
        raise CaptureRefusal("git_start_refused",facts) from error
    state,streams=drain(process,limits={"stdout":cap,"stderr":4096},until=started+5_000_000_000)
    state["argv_sha256"]=sha(canonical(argv))
    if state["late"] or state["unknown_closure"] or state["causes"] or state["returncode"]!=0 or streams["stderr"]:
        facts={"native":state,"retained_prefixes_base64":{k:base64.b64encode(v[:4096]).decode("ascii") for k,v in streams.items()},
            "diagnostic_prefixes":{k:{"captured_bytes":len(v),"included_prefix_bytes":min(len(v),4096),
                "omitted_captured_bytes":max(0,len(v)-4096),"known_captured_sha256":sha(v),
                "remainder_unknown":not state[k+"_eof"]} for k,v in streams.items()}}
        FACTS["git_failure"]=facts
        raise CaptureRefusal("git_native_refused",facts)
    return streams["stdout"]


def authenticate_helpers_v1(reviewed_commit):
    require(type(reviewed_commit) is str and re.fullmatch("[0-9a-f]{40}",reviewed_commit),"reviewed_commit")
    require(git_v1(["rev-parse","--verify","HEAD"],80)==(reviewed_commit+"\n").encode("ascii"),"reviewed_git_head")
    raw=git_v1(["ls-tree","-z",reviewed_commit,"--"]+list(HELPER_PATHS),4096)
    rows={}
    for entry in raw.rstrip(b"\0").split(b"\0"):
        header,path=entry.split(b"\t",1); mode,kind,blob=header.decode("ascii").split()
        relative=path.decode("ascii")
        require(mode=="100644" and kind=="blob" and re.fullmatch("[0-9a-f]{40}",blob) and
            relative in HELPER_PATHS and relative not in rows,"helper_git_tree")
        rows[relative]=blob
    require(set(rows)==set(HELPER_PATHS),"helper_git_inventory")
    result={}
    for relative in HELPER_PATHS:
        blob=rows[relative]; expected=git_v1(["cat-file","blob",blob],65536)
        actual=read_fixed(REPO/relative,65536)
        require(actual==expected and hashlib.sha1(b"blob "+str(len(actual)).encode("ascii")+b"\0"+actual).hexdigest()==blob,
            "reviewed_helper_source_drift")
        result[relative]={"path":str(REPO/relative),"size_bytes":len(actual),"sha256":sha(actual),"git_blob":blob}
    return result


def _load_authenticated_component_v1(source):
    require(type(source) is bytes and 0<len(source)<=262144,"retention_bootstrap_source_bound")
    check()
    sys.dont_write_bytecode=True
    module=ModuleType("vast_gate2_reviewed_retention")
    module.__file__=str(REPO/RETENTION_PATHS[0])
    exec(compile(source,module.__file__,"exec"),module.__dict__)
    check()
    return module


def authenticate_retention_v1(reviewed_commit):
    """Before allocation: current reviewed bootstrap and thirteen actual old blobs."""
    raw=git_v1(["ls-tree","-z",reviewed_commit,"--"]+list(RETENTION_PATHS),4096)
    rows={}
    for entry in raw.rstrip(b"\0").split(b"\0"):
        header,path=entry.split(b"\t",1); mode,kind,blob=header.decode("ascii").split()
        name=path.decode("ascii")
        require(mode=="100644" and kind=="blob" and name in RETENTION_PATHS and name not in rows and
                re.fullmatch("[0-9a-f]{40}",blob),"retention_git_tree")
        rows[name]=blob
    require(set(rows)==set(RETENTION_PATHS),"retention_git_inventory")
    observation={}
    for key,name,cap in (("component",RETENTION_PATHS[0],262144),("index",RETENTION_PATHS[1],12288)):
        expected=git_v1(["cat-file","blob",rows[name]],cap)
        actual=read_fixed(REPO/name,cap)
        require(actual==expected and hashlib.sha1(b"blob "+str(len(actual)).encode()+b"\0"+actual).hexdigest()==rows[name],
                "retention_bootstrap_git_drift")
        observation[key]={"size_bytes":len(actual),"sha256":sha(actual),"git_blob":rows[name]}
        if key=="component": component_source=actual
    module=_load_authenticated_component_v1(component_source)
    bindings=module.retained_source_bindings_v1(REPO)
    require(observation["index"]["size_bytes"]==bindings["index"]["size_bytes"] and
            observation["index"]["sha256"]==bindings["index"]["sha256"],"retention_index_binding")
    for row in bindings["sources"]:
        original=git_v1(["cat-file","blob",row["git_blob"]],262144)
        require(len(original)==row["size_bytes"] and sha(original)==row["sha256"] and
            hashlib.sha1(b"blob "+str(len(original)).encode()+b"\0"+original).hexdigest()==row["git_blob"],
            "retention_old_git_blob_drift")
    observation["old_git_sha256"]=bindings["source_rows_sha256"]
    check()
    return module,observation


def persist_raw_v1(files,state):
    persistence_ok=True
    for name,file in files.items():
        row=state[name]
        try:
            if persistence_ok:
                phase="flush"; check(); file.flush(); row["flush_completed"]=True
                phase="fsync"; check(); os.fsync(file.fileno()); row["fsync_completed"]=True
                phase="after_fsync"; check()
        except BaseException as error:
            row["failures"].append(phase+"_"+type(error).__name__)
            persistence_ok=False
        finally:
            if time.monotonic_ns()<min(DEADLINE,CAPTURE_END or DEADLINE):
                try:
                    file.close(); row["close_completed"]=True; check()
                except BaseException as error:
                    row["failures"].append("close_"+type(error).__name__)
                    persistence_ok=False
            else:
                row["failures"].append("close_not_started_deadline")
                persistence_ok=False
    require(persistence_ok,"raw_capture_persistence_refused")
    check()
    return state


def validate_pre_meter_v1(pre,native,helper_code,retention_module,git_observation):
    reserve=retention_module.CURRENT_CODE_FORMS_V1
    require(type(reserve) is int and reserve==524288 and 535785472+reserve<=536870912,"pre_meter_current_code_reservation")
    require(type(pre) is dict and set(pre)=={"baseline","boot_id","linux_monotonic_ns","project_free_bytes",
        "capture_source_quote_bytes","operator_source_quote_bytes","helper_git_forms_quote_bytes",
        "c_fragment_bytes","root_fragment_bytes","retention"},"pre_meter_shape")
    require(type(pre["retention"]) is dict and set(pre["retention"])=={"git_observation","native"} and
        canonical(pre["retention"]["git_observation"])==canonical(git_observation),"pre_meter_retention_binding")
    try:
        retention_module.validate_prior_retention_receipt_v1(pre["retention"]["native"],
            source_rows_sha256=git_observation["old_git_sha256"])
    except (ValueError,TypeError,KeyError) as error:
        raise CaptureRefusal("pre_meter_retention_receipt") from error
    require(all(type(pre[k]) is int and pre[k]>0 for k in ("linux_monotonic_ns","project_free_bytes",
        "capture_source_quote_bytes","operator_source_quote_bytes","helper_git_forms_quote_bytes",
        "c_fragment_bytes","root_fragment_bytes")) and pre["c_fragment_bytes"]==pre["root_fragment_bytes"]==4096 and
        pre["project_free_bytes"]>=1207959552,"pre_meter_allocation_readiness")
    require(type(pre["baseline"]) is dict and set(pre["baseline"])=={"c_free_bytes","ext4_used_bytes"} and
        all(type(v) is int and v>=0 for v in pre["baseline"].values()) and
        pre["baseline"]["c_free_bytes"]>=43620761600 and type(pre["boot_id"]) is str and
        re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}",pre["boot_id"]),"pre_meter_identity_floor")
    for key,relative in (("capture_source_quote_bytes",HELPER_PATHS[0]),("operator_source_quote_bytes",HELPER_PATHS[1])):
        minimum=((helper_code[relative]["size_bytes"]+4095)//4096)*4096+4096
        require(minimum<=pre[key]<=131072,"pre_meter_source_quote")
    require(pre["helper_git_forms_quote_bytes"]==sum(((helper_code[n]["size_bytes"]+4095)//4096)*4096+4096 for n in HELPER_PATHS),
        "pre_meter_git_forms_quote")
    require(sum(pre[k] for k in ("capture_source_quote_bytes","operator_source_quote_bytes","helper_git_forms_quote_bytes"))+65536+49152<=524288,
        "pre_meter_outside_reservation")
    require(type(native) is dict and type(native.get("pid")) is int and native["pid"]>0 and
        type(native.get("returncode")) is int and native["returncode"]==0 and
        all(native.get(k) is True for k in ("stdout_eof","stderr_eof","stdin_closed")) and
        native.get("late") is False and native.get("unknown_closure") is False and native.get("causes")==[],"pre_meter_native")
    require(native["stdout"]["kept_bytes"]==len(canonical(pre))+1 and native["stdout"]["sha256"]==sha(canonical(pre)+b"\n") and
        native["stderr"]["kept_bytes"]==0 and native["stderr"]["sha256"]==sha(b""),"pre_meter_native_payload")
    check()
    return pre


def validate_post_meter_v1(post,native,header,funded):
    require(type(post) is dict and set(post)=={"measurement","boot_id","linux_monotonic_ns","project_free_bytes",
        "required_charge_bytes","funded_initial_charge_bytes","remaining_funded_bytes","capture_all_forms_upper_bytes",
        "root_allocated_bytes","f2_allocated_bytes","outside_upper_bytes","status_and_one_copy_reserved_bytes"},"post_meter_shape")
    numbers=set(post)-{"measurement","boot_id"}
    require(all(type(post[k]) is int and post[k]>=0 for k in numbers) and
        type(funded) is int and 0<funded<536870912 and post["funded_initial_charge_bytes"]==funded and
        post["required_charge_bytes"]<=funded and post["remaining_funded_bytes"]==funded-post["required_charge_bytes"],
        "post_meter_funded_capacity")
    require(type(post["measurement"]) is dict and set(post["measurement"])=={"c_free_bytes","ext4_used_bytes"} and
        all(type(v) is int and v>=0 for v in post["measurement"].values()) and
        post["measurement"]["c_free_bytes"]>=43620761600 and post["project_free_bytes"]>=1207959552 and
        post["boot_id"]==header["boot_id"] and header["linux_start_ns"]<=post["linux_monotonic_ns"]<header["linux_deadline_ns"],
        "post_meter_identity_floor")
    require(post["capture_all_forms_upper_bytes"]<=32768 and post["root_allocated_bytes"]<=1048576 and
        post["outside_upper_bytes"]<=524288 and post["outside_upper_bytes"]>=post["capture_all_forms_upper_bytes"]+
            sum(header[k] for k in ("capture_source_quote_bytes","operator_source_quote_bytes","helper_git_forms_quote_bytes")) and
        post["status_and_one_copy_reserved_bytes"]==16384,"post_meter_form_bounds")
    require(type(native) is dict and type(native.get("pid")) is int and native["pid"]>0 and
        type(native.get("returncode")) is int and native["returncode"]==0 and
        all(native.get(k) is True for k in ("stdout_eof","stderr_eof","stdin_closed")) and
        native.get("late") is False and native.get("unknown_closure") is False and native.get("causes")==[],"post_meter_native")
    require(native["stdout"]["kept_bytes"]==len(canonical(post))+1 and native["stdout"]["sha256"]==sha(canonical(post)+b"\n") and
        native["stderr"]["kept_bytes"]==0 and native["stderr"]["sha256"]==sha(b""),"post_meter_native_payload")
    check()
    return post


def meter(*, after, payload):
    check()
    source = (POST_METER if after else PRE_METER).replace("__REVIEWED_COMMIT__",COMMIT)
    raw = canonical(payload); require(len(raw) <= 4096, "meter_input_bound")
    argv = [WSL,"-d","Ubuntu","-u","s-a-balashov","--cd","/","--exec","/usr/bin/python3","-I","-S","-B","-c",source]
    call_started=time.monotonic_ns()
    process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               env=ENV, shell=False, close_fds=True, bufsize=0, creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    state, streams = drain(process, limits={"stdout":2048,"stderr":2048}, payload=raw,
                           until=min(DEADLINE,call_started+5_000_000_000))
    state["argv_sha256"], state["stdin_sha256"] = sha(canonical(argv)), sha(raw)
    state["windows_start_ns"],state["windows_finish_ns"]=call_started,time.monotonic_ns()
    FACTS["post_meter" if after else "pre_meter"] = state
    try:
        require(not state["late"] and not state["unknown_closure"] and not state["causes"] and state["returncode"] == 0 and
                state["stdin_closed"] and streams["stderr"] == b"", "meter_native_refused")
        check()
        return strict_json(streams["stdout"],2048), state
    except BaseException:
        state["retained_prefixes_base64"]={k:base64.b64encode(v).decode("ascii") for k,v in streams.items()}
        raise


def run_capture_v1(reviewed_commit,approval):
    global START, DEADLINE, CAPTURE_END, COMMIT, DRIVER, SELF, DRIVER_SHA256, STDOUT, STDERR, STATUS, ROOT, FACTS
    validate_arguments_v1(reviewed_commit,approval)
    require(sys.platform=="win32","windows_capture_required")
    START=time.monotonic_ns(); DEADLINE=START+150_000_000_000
    CAPTURE_END=None
    FACTS={"driver":None,"pre_meter":None,"post_meter":None,"files":{}}
    COMMIT=reviewed_commit
    helper_code=authenticate_helpers_v1(reviewed_commit)
    SELF,DRIVER=(REPO/name for name in HELPER_PATHS)
    DRIVER_SHA256=helper_code[HELPER_PATHS[1]]["sha256"]
    STDOUT=TEMP/("vast-gate2-setup-"+reviewed_commit+".driver.stdout.original")
    STDERR=TEMP/("vast-gate2-setup-"+reviewed_commit+".driver.stderr.original")
    STATUS=TEMP/("vast-gate2-setup-"+reviewed_commit+".capture.status.original.json")
    ROOT="/home/s-a-balashov/work/vast-fixture-compiler-gate2-"+reviewed_commit+"-01"
    require(Path(__file__).resolve(strict=True)==SELF and not any(os.path.lexists(p) for p in (STDOUT,STDERR,STATUS)), "fixed_fresh_capture_paths")
    driver=read_fixed(DRIVER,65536); source=read_fixed(SELF,65536)
    require(0<len(driver)<=65536 and 0<len(source)<=65536 and sha(driver)==DRIVER_SHA256 and
        sha(source)==helper_code[HELPER_PATHS[0]]["sha256"],"reviewed_helper_hash")
    retention_module,git_observation=authenticate_retention_v1(reviewed_commit)
    check()
    pre, native = meter(after=False,payload={"helper_code":helper_code,"retention_git_observation":git_observation})
    validate_pre_meter_v1(pre,native,helper_code,retention_module,git_observation)
    check()
    header={"schema_version":1,"code_commit":COMMIT,"windows_start_ns":START,"windows_deadline_ns":DEADLINE,
        "linux_start_ns":pre["linux_monotonic_ns"],"linux_deadline_ns":pre["linux_monotonic_ns"]+DEADLINE-time.monotonic_ns(),
        "baseline":pre["baseline"],"boot_id":pre["boot_id"],"capture_source_sha256":sha(source),
        "capture_source_quote_bytes":pre["capture_source_quote_bytes"],"capture_all_forms_reserved_bytes":65536,
        "operator_source_quote_bytes":pre["operator_source_quote_bytes"],
        "helper_code":helper_code,"retention":pre["retention"],
        "helper_git_forms_quote_bytes":pre["helper_git_forms_quote_bytes"],
        "pre_meter_native":{k:native[k] for k in ("pid","returncode","stdout_eof","stderr_eof")}}
    header["pre_meter_native"].update(stdout_sha256=native["stdout"]["sha256"],stderr_sha256=native["stderr"]["sha256"])
    # The Linux observation happened after this native call began. Counting
    # the whole elapsed Windows duration gives a conservative Linux deadline
    # projection for subsequent local writes, without a third meter/window.
    CAPTURE_END=min(DEADLINE,native["windows_start_ns"]+header["linux_deadline_ns"]-header["linux_start_ns"])
    context=canonical(header); require(len(context)<=4096,"context_bound")
    files={}
    for name,path in (("stdout",STDOUT),("stderr",STDERR)):
        check(); files[name]=path.open("xb",buffering=0); FACTS["files"][name]={"path":str(path),"open_completed":True}
    check()
    argv=[PYTHON,"-I","-S","-B",str(DRIVER),reviewed_commit,approval]
    env=dict(ENV,VAST_GATE2_CAPTURE_CONTEXT_V1=context.decode("ascii"))
    process=subprocess.Popen(argv,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env,
        shell=False,close_fds=True,bufsize=0,creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0))
    state,_=drain(process,limits={"stdout":12288,"stderr":32768},files=files)
    state["argv_sha256"]=sha(canonical(argv)); FACTS["driver"]=state
    require(not state["late"] and not state["unknown_closure"] and not state["causes"],"driver_capture_unknown_or_late")
    persist_raw_v1(files,state)
    require(state["returncode"]==0 and state["stderr"]["kept_bytes"]==0 and state["stdout"]["kept_bytes"]<=8192,
            "driver_status_or_normal_capture_budget")
    require(read_fixed(DRIVER,65536)==driver and read_fixed(SELF,65536)==source,"frozen_source_post_drift")
    raw=read_fixed(STDOUT,12288)
    require(len(raw)==state["stdout"]["kept_bytes"] and sha(raw)==state["stdout"]["sha256"],"captured_stdout_drift")
    summary=strict_json(raw,12288)
    require(summary.get("setup_completed") is True and summary.get("physical_acceptance") is False and
        summary.get("external_packet_approval") is False and summary.get("c_or_d_invoked") is False and
        summary.get("code_commit")==COMMIT and summary.get("operator_sha256")==DRIVER_SHA256 and
        summary.get("context_sha256")==sha(context) and summary.get("baseline")==header["baseline"] and
        summary.get("boot_id")==header["boot_id"] and summary.get("linux_start_ns")==header["linux_start_ns"] and
        summary.get("windows_start_ns")==START and summary.get("linux_deadline_ns")==header["linux_deadline_ns"] and
        summary.get("absolute_deadline_ns")==DEADLINE and summary.get("external_driver_status_and_eof_required") is True,
        "driver_success_binding")
    require(summary.get("outside_preexisting_quote")==sum(header[k] for k in (
        "capture_source_quote_bytes","operator_source_quote_bytes","helper_git_forms_quote_bytes")) and
        type(summary.get("capture_all_forms_reserved_bytes")) is int and summary["capture_all_forms_reserved_bytes"]==65536,
        "driver_outside_source_and_capture_quote")
    require(summary["final_meter"]["funded_initial_charge_bytes"]==summary["packet"]["initial_charged_bytes"] and
        summary["final_meter"]["external_return_proof_reserve_bytes"]==65536 and
        summary["final_meter_process"]["returncode"]==0 and summary["final_meter_process"]["stdout_eof"] is True and
        summary["final_meter_process"]["stderr_eof"] is True and summary["final_meter_process"]["late"] is False and
        summary["final_meter_process"]["unknown_closure"] is False,"driver_final_meter_binding")
    packet=summary["packet"]["packet"]
    require(type(packet) is dict and set(packet)=={"path","size_bytes","sha256"} and
        packet["path"]==ROOT+"/gate2.packet.original.json" and type(packet["size_bytes"]) is int and
        0<packet["size_bytes"]<=131072 and re.fullmatch("[0-9a-f]{64}",packet["sha256"]),"packet_descriptor")
    authority=summary.get("operator_authority")
    require(type(authority) is dict and set(authority)=={"path","size_bytes","sha256"} and
        authority["path"]==ROOT+".operator-originals/operator.authority.original.json" and type(authority["size_bytes"]) is int and
        0<authority["size_bytes"]<=8192 and type(authority["sha256"]) is str and
        re.fullmatch("[0-9a-f]{64}",authority["sha256"]),"operator_authority_descriptor")
    post,post_native=meter(after=True,payload={"baseline":header["baseline"],"boot_id":header["boot_id"],
        "linux_deadline_ns":header["linux_deadline_ns"],"packet":packet,"operator_sha256":DRIVER_SHA256,
        "operator_authority":authority,"context":header,
        "approval_reference":approval,"outside_preexisting_quote":summary["outside_preexisting_quote"],
        "funded_initial_charge_bytes":summary["packet"]["initial_charged_bytes"],
        "stdout":{"size_bytes":state["stdout"]["kept_bytes"],"sha256":state["stdout"]["sha256"]},
        "stderr":{"size_bytes":state["stderr"]["kept_bytes"],"sha256":state["stderr"]["sha256"]}})
    validate_post_meter_v1(post,post_native,header,summary["packet"]["initial_charged_bytes"])
    status={"schema_version":1,"code_commit":COMMIT,"operator_sha256":DRIVER_SHA256,"capture_sha256":sha(source),
        "context_sha256":sha(context),"packet":packet,"operator_authority":authority,"driver":state,
        "pre_meter":{k:v for k,v in pre.items() if k!="retention"},"prior_retention_sha256":sha(canonical(header["retention"])),"post_meter":post,
        "pre_meter_native":header["pre_meter_native"],"post_meter_native":compact_native(FACTS["post_meter"]),
        "capture_paths":{"stdout":str(STDOUT),"stderr":str(STDERR)},
        "original_windows_deadline_ns":DEADLINE,"original_linux_deadline_ns":header["linux_deadline_ns"],
        "physical_acceptance":False,"external_packet_approval":False,"c_or_d_invoked":False,
        "external_wrapper_status_and_eof_required":True,"permitted_status_copy_upper_bytes":8192}
    encoded=canonical(status); require(len(encoded)<=4096,"status_bound")
    check()
    proof={"path":str(STATUS),"open_completed":False,"written_bytes":0,"write_extent_unknown":False,
           "confirmed_prefix_sha256":sha(b""),"flush_completed":False,"fsync_completed":False,"close_completed":False,"failures":[]}
    FACTS["status_write"]=proof
    file=None; phase="open"
    try:
        check(); file=STATUS.open("xb",buffering=0); proof["open_completed"]=True; check()
        phase="write"
        try: count=file.write(encoded)
        except BaseException:
            proof["write_extent_unknown"]=True
            raise
        if type(count) is not int or not 0<=count<=len(encoded):
            proof["write_extent_unknown"]=True
            raise RuntimeError("status_write_contract")
        proof["written_bytes"]=count
        proof["confirmed_prefix_sha256"]=sha(encoded[:count])
        require(count==len(encoded),"status_short_write"); check()
        phase="flush"; file.flush(); proof["flush_completed"]=True; check()
        phase="fsync"; os.fsync(file.fileno()); proof["fsync_completed"]=True; check()
    except BaseException as error:
        proof["failures"].append(phase+"_"+type(error).__name__)
        raise
    finally:
        if file is not None:
            if time.monotonic_ns()<min(DEADLINE,CAPTURE_END):
                try:
                    file.close(); proof["close_completed"]=True; check()
                except BaseException as error:
                    proof["failures"].append("close_"+type(error).__name__)
                    raise
            else:
                proof["failures"].append("close_not_started_deadline")
    require(proof["close_completed"] and not proof["failures"],"status_close_refused")
    check()
    output=canonical({"status":{"path":str(STATUS),"size_bytes":len(encoded),"sha256":sha(encoded)},
        "driver_returncode":state["returncode"],"driver_stdout_eof":True,"driver_stderr_eof":True,
        "status_write_facts":proof,"physical_acceptance":False,"external_packet_approval":False,
        "external_wrapper_status_and_eof_required":True})
    require(len(output)+1<=4096,"external_summary_bound")
    sys.stdout.buffer.write(output+b"\n"); sys.stdout.buffer.flush(); check()
    return strict_json(output,4096)


def failure_summary_v1(error):
    raw=canonical({"setup_evidence_valid":False,"physical_acceptance":False,"external_packet_approval":False,
        "cause":type(error).__name__,"message":str(error)[:256],"facts":FACTS,
        "external_wrapper_status_and_eof_required":True})
    # Git diagnostics retain at most 4KiB from each exact captured prefix,
    # plus full known counts/hashes and explicit omitted/remainder facts.
    require(len(raw)+1<=32768,"failure_summary_bound")
    return raw


if __name__=="__main__":
    try:
        require(len(sys.argv)==3,"reviewed_commit_and_approval_arguments")
        run_capture_v1(sys.argv[1],sys.argv[2])
    except BaseException as error:
        # No new failure file, meter, cleanup, signal, retry or time window.
        raw=failure_summary_v1(error)
        sys.stderr.buffer.write(raw+b"\n"); sys.stderr.buffer.flush()
        raise SystemExit(1)
