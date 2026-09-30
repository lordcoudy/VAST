from pathlib import Path
import hashlib,json,subprocess
root=Path.cwd();base="artifacts/benchmark_recovery_20260930/";git=["git","-c","core.longpaths=true"]
assert subprocess.check_output(git+["rev-parse","HEAD"],text=True).strip()=="bec47b794ef9183fe9e3ce4cb1ec15541070f96f"
assert not subprocess.check_output(git+["diff","--cached","--name-only"])
review=json.loads((root/base/"component-cli-relative-source-independent-review-v1/review.v1.json").read_bytes())
assert review["disposition"]=="approved_source_scope"
for row in review["source_pins"]:
 raw=(root/row["path"]).read_bytes();assert len(raw)==row["size_bytes"] and hashlib.sha256(raw).hexdigest()==row["sha256"]
owned=["scripts/publication_gstreamer_component_cli_v1.py","tests/test_publication_gstreamer_component_cli_v1.py","BENCHMARK_RECOVERY_PLAN.md","openspec/changes/fix-benchmark-preparations-spec/tasks.md",base+"capture_selected_host_closure_v3.py",base+"stage_component_cli_relative_repair_v1.py"]
for name in ("component-cli-relative-source-repair-v1","component-cli-relative-source-independent-review-v1","selected-gstreamer-cpu02-controller-preparation-v1"):
 owned.extend(p.relative_to(root).as_posix() for p in sorted((root/base/name).rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.suffix!=".pyc")
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
subprocess.run(git+["-c","core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol","diff","--cached","--check","--",*owned],check=True)
receipt=root/base/"component-cli-relative-repair-freeze.v1.json";assert not receipt.exists()
receipt.write_bytes((json.dumps({"previous_head":"bec47b794ef9183fe9e3ce4cb1ec15541070f96f","independent_review_sha256":"a0734e4c15e5456853b9ef3c5b1e2a57b20b2fe2996390bbd93195e579e769b0","physical_index_equal":True,"owned_files":{p:{"sha256":hashlib.sha256(b).hexdigest(),"size_bytes":len(b)} for p,b in physical.items()},"unfiltered_original_artifact_imports":carriers,"cpu02_executed":False,"hostclosure_v3_executed":False,"hardware_accepted":False},sort_keys=True,separators=(",",":"))+"\n").encode())
subprocess.run(git+["add","-f","--",receipt.relative_to(root).as_posix()],check=True)
print(json.dumps({"staged":len(owned)+1,"physical_index_equal":True,"carriers":carriers}))
