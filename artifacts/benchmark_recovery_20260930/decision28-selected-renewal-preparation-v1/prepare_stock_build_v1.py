"""Literal selected-build relocation; preparation does not execute an engine."""
from pathlib import Path
import ast, hashlib, json

ROOT = Path('E:/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
HERE = Path(__file__).resolve().parent
old = ROOT/'artifacts/benchmark_recovery_20260930/selected-gstreamer-image-schema-preparation-v1/run_selected_build_v1.py'
raw = old.read_bytes(); source = raw.decode()
replacements = {
    "ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')":
        "ROOT = Path('/home/s-a-balashov/work/vast-component-release-20260930-d27')",
    "COMMIT = 'a4e145b7bf32e0c870b114e303e9adb6a559d0ef'":
        "assert len(sys.argv) == 2, 'one exact reviewed source commit required'\nCOMMIT = sys.argv[1]\nassert len(COMMIT) == 40 and all(c in '0123456789abcdef' for c in COMMIT)",
    "TAG = 'vast/gstreamer-custom-publication-runtime-v3:component-release-20260930-a4e145b7'":
        "TAG = 'vast/gstreamer-custom-publication-runtime-v3:decision28-' + COMMIT[:8]",
    "DEST = ROOT / 'artifacts/benchmark_recovery_20260930/selected-gstreamer-build-a4e145b7-v1'":
        "DEST = ROOT / ('artifacts/benchmark_recovery_20260930/decision28-gstreamer-build-' + COMMIT[:8] + '-v1')",
    "'--git-dir=/mnt/e/STUDY/VAST/.git/worktrees/fix-benchmark-preparations-spec'":
        "'--git-dir=' + str(ROOT/'.git')",
}
for before, after in replacements.items():
    assert source.count(before) == 1, before
    source = source.replace(before, after)
old_functions = {n.name:ast.dump(n, include_attributes=False) for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef)}
new_functions = {n.name:ast.dump(n, include_attributes=False) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)}
assert old_functions == new_functions
new = HERE/'run_original_selected_build_ext4_v1.py'
with new.open('xb') as f:f.write(source.encode())
def pin(path):
    b=path.read_bytes();return {'path':str(path),'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()}
prep = {'status':'prepared_unexecuted_pending_exact_source_commit_and_peer_grant',
    'original':pin(old), 'source':pin(new), 'preparer':pin(Path(__file__).resolve()),
    'literal_replacements':replacements, 'all_function_ASTs_identical':sorted(old_functions),
    'source_commit_argument':None, 'future_image_receipt':None, 'future_original_owner':None,
    'bounds':{'whole_s':1200,'stock_two_build_s':900,'stock_capture_s':180,'other_engine_s':60,
              'ordinary_capture_bytes':1048576,'build_capture_bytes':16777216,'cleanup_s':15},
    'scope':'existing selected deterministic two-build and original stock image capture only; no model or scientific benchmark acceptance',
    'engine_commands_executed':0, 'selected_runtime_rebuild_required_after_Decision28':True,
    'future_host_binding_renewal_and_source_closure_required':True}
with (HERE/'preparation.v1.json').open('xb') as f:f.write((json.dumps(prep, sort_keys=True, indent=2)+'\n').encode())
print(json.dumps({'source':pin(new),'preparation':pin(HERE/'preparation.v1.json')}))
