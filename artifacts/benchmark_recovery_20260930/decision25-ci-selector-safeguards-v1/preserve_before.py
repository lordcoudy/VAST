"""Preserve exact selector/test before repair; no discovery or workload."""
from pathlib import Path
import hashlib,json
ROOT=Path(__file__).resolve().parents[3]
OUT=Path(__file__).parent/'before'
OUT.mkdir()
rows={}
for name in ['scripts/ci_test_selection_v1.py','tests/test_ci_test_selection_v1.py']:
    raw=(ROOT/name).read_bytes();(OUT/Path(name).name).write_bytes(raw)
    rows[name]={'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
manifest=ROOT/'.ci/integration-test-selection.v1.json'
raw=manifest.read_bytes();rows['.ci/integration-test-selection.v1.json']={'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
(OUT/'inventory.json').write_text(json.dumps(rows,sort_keys=True)+'\n')
print(json.dumps(rows))
