from pathlib import Path
import sys,unittest,json,hashlib
ROOT=Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/"scripts"))
from ci_test_selection_v1 import select_portable_suite_v1
suite=unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern="test_*.py")
portable,report=select_portable_suite_v1(suite,project_root=ROOT)
assert report["counts"]["discovered"]==report["counts"]["portable"]+report["counts"]["integration"]
raw=(json.dumps(report,sort_keys=True,indent=2)+"\n").encode();p=Path(__file__).parent/"current-inventory.v1.json";p.open("xb").write(raw)
print(json.dumps({"counts":report["counts"],"size_bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest(),"tests_executed":False}))
