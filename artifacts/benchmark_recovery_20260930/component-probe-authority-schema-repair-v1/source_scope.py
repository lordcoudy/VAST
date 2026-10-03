from pathlib import Path
import sys,json,hashlib
ROOT=Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
sys.path.insert(0,str(ROOT/"scripts"))
import publication_qualification_image_refreeze_v1 as refreeze
import publication_image_build_v1 as images
base=Path(__file__).parent
modified="scripts/publication_gstreamer_component_authority_v1.py"
old=hashlib.sha256((base/"before/publication_gstreamer_component_authority_v1.py").read_bytes()).hexdigest()
new=hashlib.sha256((ROOT/modified).read_bytes()).hexdigest()
registry=refreeze.load_refreeze_registry(project_root=ROOT,registry_path=ROOT/refreeze.REGISTRY_RELATIVE_PATH)
baseline=json.loads((ROOT/"artifacts/benchmark_recovery_20260930/decision25-sibling-packaging-v1/current-scope.v1.json").read_bytes())["runtime_source_identities"]
identities={s["system"]:refreeze._source_identity(ROOT,s) for s in registry["systems"]}
rows={}
for system in registry["systems"]:
 name=system["system"];sources=images._read_allowlist(ROOT,system["source_allowlist"])
 assert modified in sources and modified in (ROOT/system["dockerfile"]).read_text()
 old_aggregate=hashlib.sha256(b"".join(((old if path==modified else hashlib.sha256((ROOT/path).read_bytes()).hexdigest())+"  "+path+"\n").encode() for path in sorted(sources))).hexdigest()
 assert old_aggregate==baseline[name]["runtime_source_sha256"]
 assert identities[name]["runtime_source_sha256"]!=baseline[name]["runtime_source_sha256"]
 assert all(identities[name][k]==baseline[name][k] for k in baseline[name] if k!="runtime_source_sha256")
 rows[name]={"previous":baseline[name],"current":identities[name],"exactly_one_member_hash_changed":True,"module_in_copy_and_allowlist":True,"rebuild_required_for_current_execution":True}
plan=images.publication_image_build_plan(project_root=ROOT,registry_path=ROOT/images.REGISTRY_RELATIVE_PATH)
image_registry=images.load_publication_image_registry(project_root=ROOT,registry_path=ROOT/images.REGISTRY_RELATIVE_PATH)
config_rows={x["name"]:x for x in image_registry["images"]}
expected=[]
for name in ("native-a/native_probe.freeze.json","worker_images/analytics-worker.freeze.json"):
 expected.extend(json.loads((ROOT/"artifacts/fix_benchmark_preparations_20260928g"/name).read_bytes())["images"])
actual={row["name"]:row for row in plan["images"]};same={}
for row in expected:
 current=actual[row["name"]];same[row["name"]]={key:current[key] for key in ("source_set_sha256","dependency_set_sha256","build_context_sha256")}
 assert all(row[key]==current[key] for key in same[row["name"]])
 assert modified not in images._read_allowlist(ROOT,config_rows[row["name"]]["source_allowlist"])
assert len(same)==5
value={"schema_version":1,"artifact_kind":"vast_component_probe_schema_finite_image_source_audit_v1","modified_module":modified,"previous_source_sha256":old,"current_source_sha256":new,"runtime_scopes":rows,"native_three_worker_two_unchanged":same,"method":"Actual stock publication_image_build_plan and _source_identity; physical hashes only, no engine query/build/model command","selected_887_is_historical_after_this_edit":True,"required_next_execution":"reviewed selected deterministic build/capture, real host wrapper EXPECTED renewal, fresh host execution closurev5","sibling_images_still_historical_ineligible":True,"image_builds_or_queries_executed":False,"hardware_accepted":False}
raw=(json.dumps(value,sort_keys=True,indent=2)+"\n").encode();out=base/"source-image-scope.v1.json";out.open("xb").write(raw)
print(json.dumps({"receipt":str(out),"size_bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"changed_runtime_scopes":len(rows),"native_worker_unchanged":5}))
