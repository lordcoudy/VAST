"""Read-only actual stock source membership; no engine or namespace call."""
from pathlib import Path
import hashlib
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'scripts'))
from publication_policy_qualification_execution_code_closure_v1 import _discover_sources

OWNED = ['scripts/run_ci_checks.py', '.github/workflows/ci.yml',
         'tests/test_run_ci_checks.py', 'scripts/ci_namespace_diagnostic_v1.py',
         'tests/test_ci_namespace_diagnostic_v1.py']
def pin(path):
    raw = path.read_bytes()
    return {'size_bytes':len(raw), 'sha256':hashlib.sha256(raw).hexdigest()}

host = [path.relative_to(ROOT).as_posix() for _, path in _discover_sources(ROOT)]
allowlist = ROOT / 'deploy/gstreamer_custom/publication/runtime-source-allowlist.txt'
selected = allowlist.read_text().splitlines()
docker = ROOT / 'deploy/gstreamer_custom/publication/Dockerfile'
docker_raw = docker.read_text()
assert not set(OWNED) & set(host)
assert not set(OWNED) & set(selected)
assert all(path not in docker_raw for path in OWNED)
assert len(host) == 87 and len(selected) == 73
out = Path(__file__).with_name('source-scope.v1.json')
value = {'schema_version':1, 'scope':'Actual stock AST host graph and selected source allowlist membership only.',
         'host_count':len(host), 'host_sources':{p:pin(ROOT/p) for p in host},
         'selected_count':len(selected), 'selected_sources':{p:pin(ROOT/p) for p in selected},
         'owned':{p:pin(ROOT/p) for p in OWNED},
         'allowlist':pin(allowlist), 'dockerfile':pin(docker),
         'owned_host_intersection':[], 'owned_selected_intersection':[],
         'owned_selected_docker_copy_references':[],
         'original_final_test_pid_absent':not Path('/proc/26929').exists(),
         'actual_engine_queries':0,'actual_namespace_calls':0,'actual_model_calls':0}
with out.open('xb') as stream:
    stream.write((json.dumps(value,sort_keys=True,indent=2)+'\n').encode())
print(json.dumps({'path':str(out),**pin(out),'host_count':len(host),'selected_count':len(selected)}))
