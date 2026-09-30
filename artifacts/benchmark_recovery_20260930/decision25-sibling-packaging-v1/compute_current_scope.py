from pathlib import Path
import sys,json,hashlib
ROOT=Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
sys.path.insert(0,str(ROOT/"scripts"))
import publication_qualification_image_refreeze_v1 as refreeze
import publication_image_build_v1 as images
base=Path(__file__).parent
registry=refreeze.load_refreeze_registry(project_root=ROOT,registry_path=ROOT/refreeze.REGISTRY_RELATIVE_PATH)
identities={s["system"]:refreeze._source_identity(ROOT,s) for s in registry["systems"]}
original=json.loads((ROOT/"artifacts/benchmark_recovery_20260930/component-cli-relative-source-repair-v1/selected-source-scope.v1.json").read_bytes())["observed_source_identity"]
assert identities["gstreamer_custom"]==original
plan=images.publication_image_build_plan(project_root=ROOT,registry_path=ROOT/images.REGISTRY_RELATIVE_PATH)
expected=[]
for name in ("native-a/native_probe.freeze.json","worker_images/analytics-worker.freeze.json"):
 expected.extend(json.loads((ROOT/"artifacts/fix_benchmark_preparations_20260928g"/name).read_bytes())["images"])
actual={row["name"]:row for row in plan["images"]};same={}
for row in expected:
 current=actual[row["name"]];same[row["name"]]={key:current[key] for key in ("source_set_sha256","dependency_set_sha256","build_context_sha256")}
 assert all(row[key]==current[key] for key in same[row["name"]])
assert len(same)==5
value={"selected_original_887_source_identity_unchanged":True,"runtime_source_identities":identities,"native_three_worker_two_unchanged":same,"sibling_images_still_historical_ineligible":True,"image_builds_or_queries_executed":False,"hardware_accepted":False}
raw=(json.dumps(value,sort_keys=True,indent=2)+"\n").encode();out=base/"current-scope.v1.json";out.open("xb").write(raw)
print(json.dumps({"receipt":str(out),"size_bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"selected_unchanged":True,"native_worker_unchanged":5}))
