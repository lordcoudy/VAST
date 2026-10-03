"""Stage only reviewed planning and closed original failure evidence."""
import argparse
import hashlib
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--review', required=True)
parser.add_argument('--review-sha256', required=True)
args = parser.parse_args()
root = Path.cwd()
head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
assert head == 'a045b8874ad15b2fa05f1a5d7fc9f331e8b04a47'
assert not subprocess.check_output(['git', 'diff', '--cached', '--name-only'], text=True).strip()
change = 'openspec/changes/fix-benchmark-preparations-spec/'
docs = ['BENCHMARK_RECOVERY_PLAN.md', *[change + name for name in (
    'proposal.md', 'design.md', 'tasks.md', 'specs/benchmark-launch-preparation/spec.md',
    'verification-plan.md', 'preparation-plan.md', 'implementation-validation.md',
    'conformance-progress.md', 'image-invalidation.md')]]
evidence_root = root / 'artifacts/benchmark_recovery_20260930'
review = (root / args.review).resolve(strict=True)
assert review.parent == evidence_root and review.is_file()
assert hashlib.sha256(review.read_bytes()).hexdigest() == args.review_sha256
evidence = [review, Path(__file__).resolve()]
for name in ('decoder-research-attempt-01', 'decoder-research-attempt-01-original-controller',
             'decoder-research-attempt-01-post-terminal-observation',
             'decoder-research-attempt-01-owned-cleanup', 'decoder-independent-cold-v1',
             'decoder-research-setup-repair-source-review'):
    directory = evidence_root / name
    assert directory.is_dir()
    evidence.extend(path for path in directory.rglob('*')
                    if path.is_file() and '__pycache__' not in path.parts and path.suffix != '.pyc')
for name in ('decoder-independent-failed-setup-review.v1.json',
             'controller-lf-scope-gap.v1.json', 'controller-lf-scope-proposed-amendment.v1.md',
             'controller-lf-scope-proposed.gitattributes.v1.txt',
             'committed-byte-freeze-independent-review.v3.json',
             'byte-freeze-tiny-git-controller-regression.v1.json',
             'byte-freeze-v5-guard-regression.v1.json',
             'verify_checkout_byte_freeze_v5.py', 'verify_checkout_byte_freeze_v6.py',
             'verify_checkout_byte_freeze_v7.py'):
    evidence.append(evidence_root / name)
for version in (4, 5, 6):
    evidence.extend(evidence_root.glob(f'byte-freeze-fresh-checkouts.v{version}.*.json'))
evidence.extend(evidence_root.glob('byte-freeze-fresh-checkouts.attempt-*.stderr.log'))
paths = sorted(set(docs + [path.relative_to(root).as_posix() for path in evidence]))
assert all((root / name).is_file() and not (root / name).is_symlink() for name in paths)
pins = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
subprocess.run(['git', 'add', '--', *docs], check=True)
subprocess.run(['git', 'add', '-f', '--', *[name for name in paths if name not in docs]], check=True)
staged = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], text=True).splitlines()
assert set(staged) <= set(paths)
assert set(docs) <= set(staged)
assert '.gitattributes' not in staged
assert not any(name.startswith(('scripts/', 'deploy/', 'tests/', '.github/')) for name in staged)
for name, expected in pins.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected
    raw = subprocess.check_output(['git', 'show', ':' + name])
    assert hashlib.sha256(raw).hexdigest() == expected, 'index bytes differ: ' + name
subprocess.run(['git', 'diff', '--cached', '--check', '--', *docs], check=True)
print(f'Planning-only stage: {len(staged)} paths; {len(docs)} documents; all physical/index pins equal.')
