from pathlib import Path
import hashlib,json,subprocess
root=Path.cwd();base="artifacts/benchmark_recovery_20260930/";git=["git","-c","core.longpaths=true"]
assert subprocess.check_output(git+["rev-parse","HEAD"],text=True).strip()=="effbb5265ca724c00b5b5278827cced2a750ade4"
assert not subprocess.check_output(git+["diff","--cached","--name-only"])
review_path=base+"component-model-inspect-adapter-independent-review-v1/review.v1.json"
assert hashlib.sha256((root/review_path).read_bytes()).hexdigest()=="bc1dd50bba917e66991065c1e87ec9d5e7dbc9b23ba4ed4d9b6f1c94a9ba8828"
review=json.loads((root/review_path).read_bytes())
for row in review["source_pins"]:
 raw=(root/row["path"]).read_bytes();assert len(raw)==row["size_bytes"] and hashlib.sha256(raw).hexdigest()==row["sha256"]
owned=[row["path"] for row in review["source_pins"]]+["BENCHMARK_RECOVERY_PLAN.md",base+"stage_component_model_inspect_repair_v1.py",base+"capture_selected_host_closure_v4.py",base+"component-cli-relative-repair-commit-proof.v1.json",base+"component-cli-relative-repair-pr-body.md","artifacts/gstreamer_component_release_20260930_a3e976d0/host/execution-code-closure.v3.json"]
for directory in ("component-model-inspect-adapter-repair-v1","component-model-inspect-adapter-independent-review-v1","component-cpu02-model-rejection-diagnosis-v1","selected-gstreamer-cpu03-controller-preparation-v1","component-selected-host-closure-v3-original"):
 owned.extend(p.relative_to(root).as_posix() for p in sorted((root/base/directory).rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.suffix!=".pyc")
for directory in ("cpu-pair-02","cpu-pair-02-original-controller"):
 owned.extend(p.relative_to(root).as_posix() for p in sorted((root/"artifacts/gstreamer_component_release_20260930_a3e976d0"/directory).rglob("*")) if p.is_file())
assert len(owned)==len(set(owned));physical={p:(root/p).read_bytes() for p in owned}
subprocess.run(git+["add","-f","--",*owned],check=True)
def blobs():
 raw=subprocess.check_output(git+["cat-file","--batch"],input="".join(":"+p+"\n" for p in owned).encode());pos=0;out={}
 for p in owned:
  end=raw.index(b"\n",pos);h=raw[pos:end].split();assert len(h)==3 and h[1]==b"blob";n=int(h[2]);pos=end+1;out[p]=raw[pos:pos+n];pos+=n;assert raw[pos:pos+1]==b"\n";pos+=1
 assert pos==len(raw);return out
carriers=[]
for p,b in blobs().items():
 if b!=physical[p]:
  assert p.startswith("artifacts/"),p
  oid=subprocess.check_output(git+["hash-object","-w","--stdin"],input=physical[p]).decode().strip();subprocess.run(git+["update-index","--add","--cacheinfo","100644,"+oid+","+p],check=True);carriers.append(p)
assert blobs()==physical
assert set(subprocess.check_output(git+["diff","--cached","--name-only"],text=True).splitlines())==set(owned)
checks=[p for p in owned if not p.startswith("artifacts/")]+[base+"capture_selected_host_closure_v4.py",base+"stage_component_model_inspect_repair_v1.py",base+"selected-gstreamer-cpu03-controller-preparation-v1/run_original_cpu_component_pair_v1.py"]
subprocess.run(git+["-c","core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol","diff","--cached","--check","--",*checks],check=True)
receipt=root/base/"component-model-inspect-repair-freeze.v1.json";assert not receipt.exists();receipt.write_bytes((json.dumps({"previous_head":"effbb5265ca724c00b5b5278827cced2a750ade4","independent_review_sha256":"bc1dd50bba917e66991065c1e87ec9d5e7dbc9b23ba4ed4d9b6f1c94a9ba8828","physical_index_equal":True,"owned_files":{p:{"sha256":hashlib.sha256(b).hexdigest(),"size_bytes":len(b)} for p,b in physical.items()},"unfiltered_original_artifact_imports":carriers,"cpu03_executed":False,"hostclosure_v4_executed":False,"hardware_accepted":False},sort_keys=True,separators=(",",":"))+"\n").encode());subprocess.run(git+["add","-f","--",receipt.relative_to(root).as_posix()],check=True)
print(json.dumps({"staged":len(owned)+1,"physical_index_equal":True,"carriers":carriers}))
