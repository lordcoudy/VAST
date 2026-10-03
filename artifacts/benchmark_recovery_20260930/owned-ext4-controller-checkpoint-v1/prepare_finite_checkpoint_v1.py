"""Only exact closed owned setup/review/science/CI/doc files; no Git mutation."""
from pathlib import Path
import hashlib,json,subprocess
root=Path(__file__).resolve().parents[3]
out=Path(__file__).parent
base=Path('artifacts/benchmark_recovery_20260930')
directories=[
 'component-ext4-relocation-preparation-v1',
 'component-ext4-relocation-independent-review-v1',
 'component-ext4-bind-preparation-v1',
 'component-ext4-bind-independent-review-v1',
 'component-ext4-postsetup-review-preparation-v1',
 'component-cpu05-sidecar-independent-reduction-v1',
 'component-cpu05-sidecar-independent-reduction-v2',
 'component-cpu05-sidecar-scientific-peer-review-v1',
 'ci-5bc416-original-host-retention-v1',
 'ci-5bc-gva-root-fixture-repair-v1',
]
explicit=[
 'BENCHMARK_RECOVERY_PLAN.md',
 'openspec/changes/fix-benchmark-preparations-spec/tasks.md',
 'tests/test_checkpoint_openvino_gva_qualification_fragment_v3.py',
 'artifacts/benchmark_recovery_20260930/final-conformance-mapping-skeleton-v1/mapping.v4.json',
 'artifacts/benchmark_recovery_20260930/final-conformance-mapping-skeleton-v1/prepare_mapping_v4.py',
 'artifacts/benchmark_recovery_20260930/final-conformance-mapping-skeleton-v1/task-completion-recommendation.v1.json',
 'artifacts/benchmark_recovery_20260930/final-conformance-mapping-skeleton-v1/mapping.v4-preparation-ledger.v1.json',
 'artifacts/benchmark_recovery_20260930/final-conformance-mapping-skeleton-v1/task-completion-recommendation.v1.md',
]
paths=set()
for directory in directories:
    p=root/base/directory
    assert p.is_dir(), 'closed owned directory missing: '+str(p)
    for leaf in p.rglob('*'):
        assert not leaf.is_symlink(),str(leaf)
        if leaf.is_file():
            assert '__pycache__' not in leaf.parts and leaf.suffix.lower() not in {'.onnx','.engine','.plan','.bin','.whl'},str(leaf)
            paths.add(leaf.relative_to(root).as_posix())
for relative in explicit:
    assert (root/relative).is_file(),relative
    paths.add(relative)
paths.add(Path(__file__).relative_to(root).as_posix())
rows=[]
for relative in sorted(paths):
    p=root/relative;assert p.resolve(strict=True).is_relative_to(root) and p.stat().st_nlink==1
    raw=p.read_bytes();assert len(raw)<=8*1024*1024,relative
    rows.append({'path':relative,'size_bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
gate_paths=[
 'artifacts/benchmark_recovery_20260930/component-ext4-relocation-preparation-v1/author-review.v2.json',
 'artifacts/benchmark_recovery_20260930/component-ext4-relocation-independent-review-v1/review.v1.json',
 'artifacts/benchmark_recovery_20260930/component-ext4-bind-preparation-v1/author-review.v2.json',
 'artifacts/benchmark_recovery_20260930/component-ext4-bind-independent-review-v1/review.v2.json',
 'artifacts/benchmark_recovery_20260930/ci-5bc-gva-root-fixture-repair-v1/independent-review.v1.json',
 'artifacts/benchmark_recovery_20260930/ci-5bc416-original-host-retention-v1/cpu-review.v1.json',
]
index={r['path']:r for r in rows}
assert all(p in index for p in gate_paths)
assert subprocess.check_output(['git','-c','core.longpaths=true','rev-parse','HEAD'],cwd=root,text=True).strip()=='5bc416a2beab98b6cc60229dac56332b48cc6ca2'
assert not subprocess.check_output(['git','-c','core.longpaths=true','diff','--cached','--name-only'],cwd=root)
value={'previous_head':'5bc416a2beab98b6cc60229dac56332b48cc6ca2','files':rows,
 'blocking_gates':[],'review_pins':[index[p] for p in gate_paths],
 'scope':'finite closed preparation/helpers/actual prior scientific and CI evidence/doc state; no ext4 setup or hardware acceptance',
 'unrelated_dirty_preserved':True,'benchmark_accepted':False,'full_ci_successful':False}
target=out/'inventory.v1.json';assert not target.exists()
raw=(json.dumps(value,sort_keys=True,indent=2)+'\n').encode();target.write_bytes(raw)
print(json.dumps({'owned_files':len(rows),'bytes':sum(r['size_bytes'] for r in rows),'inventory_bytes':len(raw),'inventory_sha256':hashlib.sha256(raw).hexdigest()}))
