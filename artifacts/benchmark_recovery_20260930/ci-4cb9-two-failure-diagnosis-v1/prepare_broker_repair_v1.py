"""Preserve original bytes and explicit review authorization before the fix."""
import hashlib
import json
import os
from pathlib import Path
import time

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
OUT = ROOT / 'artifacts/benchmark_recovery_20260930/broker-terminal-owner-repair-v1'
OUT.mkdir()

def write(path, raw):
    with path.open('xb') as output:
        output.write(raw)
        output.flush()
        os.fsync(output.fileno())

originals = []
for name in ('scripts/backend_publication_process_supervisor_v3.py',
             'tests/test_backend_publication_broker_terminal_v3.py'):
    path = ROOT / name
    raw = path.read_bytes()
    target = OUT / (path.name + '.before.raw')
    write(target, raw)
    originals.append({'source_path': name, 'original_path': str(target), 'size_bytes': len(raw),
                      'sha256': hashlib.sha256(raw).hexdigest()})
assert originals[0]['sha256'] == 'acc40456cf93db8deb270f54d14b8f17555a268969e5bad0695372ddba12132d'
planning = []
for name in ('proposal.md', 'design.md', 'tasks.md', 'specs/benchmark-launch-preparation/spec.md'):
    path = ROOT / 'openspec/changes/fix-benchmark-preparations-spec' / name
    raw = path.read_bytes()
    planning.append({'path': str(path), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()})
value = {'schema_version': 1, 'artifact_kind': 'vast_broker_owner_repair_preedit_scope_v1',
    'recorded_at_ns': time.time_ns(), 'originals': originals, 'planning_context': planning,
    'source_commit': '4cb9d8313cca71256179bc3b59cc6f9137e7b8ba',
    'authorization': {'source': 'Direct parent root message under standing human autonomous recovery authorization',
        'text': 'ROOT APPROVES minimal private terminal_journal promotion only after successful _commit_durable_owner, in both existing supervisor entrypoints. No startup lock change, no new persisted/public format, no assertion/deadline changes. Preserve parent mismatch/cleanup.'},
    'proposal': 'Parsed journal is not terminal writer authority. Promote a separate private terminal_journal only after this broker successfully commits its immutable owner; early failure emits to that promoted journal, otherwise original failed stdout. Authorization/held/namespace failures of the elected owner still use the unchanged durable emitter.',
    'footprint': {'supervisor': {'host87': True, 'finite2693': True, 'selected73': False, 'all9_allowlists': []},
                  'test': {'host87': False, 'finite2693': False, 'selected73': False}},
    'required_regressions': ['Two actual pipe-gated children: elected owner stays alive while losing normal entry fails actual owner commit without terminal writes.',
                             'Same original held entrypoint; exact owner bytes preserved; elected owner alone publishes actual terminal intent/response.',
                             'Preserve all original setup/authorization/custody/emission/invalid-request methods and assertions.'],
    'limits': ['No model/engine/profile/policy/hardware workload or accepted-pair rebinding.',
               'Historical accepted 0ad pairs remain immutable; changed host87 requires future current host closure and pair renewal.'],
    'capacity': 'One unchanged instrumented unit passed locally; hosted first swallowed ValueError remains unknown. No capacity test or production process helper edit.'}
write(OUT / 'preedit-proposal-and-authorization.v1.json', (json.dumps(value, sort_keys=True, indent=2) + '\n').encode())
print(json.dumps({'path': str(OUT / 'preedit-proposal-and-authorization.v1.json'),
                  'sha256': hashlib.sha256((OUT / 'preedit-proposal-and-authorization.v1.json').read_bytes()).hexdigest()}))
