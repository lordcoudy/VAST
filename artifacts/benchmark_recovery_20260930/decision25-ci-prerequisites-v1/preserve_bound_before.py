"""Preserve frozen diagnostic bytes before aggregate-bound correction."""
from pathlib import Path
import hashlib
import json
ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).with_name('aggregate-bound-before')
OUT.mkdir()
rows={}
for name in ['scripts/ci_namespace_diagnostic_v1.py','tests/test_ci_namespace_diagnostic_v1.py']:
    raw=(ROOT/name).read_bytes()
    (OUT/Path(name).name).write_bytes(raw)
    rows[name]={'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
(OUT/'inventory.json').write_text(json.dumps(rows,sort_keys=True)+'\n')
print(json.dumps(rows))
