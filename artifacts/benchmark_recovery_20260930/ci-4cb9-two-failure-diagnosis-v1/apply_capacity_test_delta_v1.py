"""Preserve original test and explicit root grant before capacity-only edit."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = Path(__file__).resolve().parent
OUT = BASE / 'capacity-fixture-repair-v1'
OUT.mkdir()
path = ROOT / 'tests/test_publication_operational_process_custody_v1.py'
raw = path.read_bytes()
assert hashlib.sha256(raw).hexdigest() == '161938214d28727a633838108b95777e363bf4c516bd4c49a37baf897d3fe95d'
with (OUT / 'test_publication_operational_process_custody_v1.py.before.raw').open('xb') as output:
    output.write(raw)
    output.flush()
    os.fsync(output.fileno())
approval = {'schema_version': 1, 'source': 'Direct parent root authorization under standing user recovery authorization',
    'instruction': 'ROOT APPROVES narrow capacity-only gated helper plus specific capacity refusal regression after controlled original probe. Keep process()/run_child() and intentionally fast/zombie behavior unchanged, all production custody scripts/source87 unchanged. No sleeps/deadline increases/skips/assertion weakening.',
    'original_source_sha256': hashlib.sha256(raw).hexdigest(),
    'original_controlled_probe_terminal_sha256': '8534547568bd8c7a34af1c46e45e8cd4e4b9203531ea7faea105b468cb6257f9',
    'scope': 'one existing test module; no production/image/host source edits',
    'limitation': 'Original hosted first swallowed ValueError is unknown; local unchanged unit passed, and controlled reaped failure is FileNotFoundError.'}
with (OUT / 'preedit-authorization.v1.json').open('xb') as output:
    output.write((json.dumps(approval, sort_keys=True, indent=2) + '\n').encode())
    output.flush()
    os.fsync(output.fileno())
nl = b'\r\n' if b'\r\n' in raw else b'\n'
old = b'''        with self.assertRaises(ValueError):
            with self.capture(output_dir=self.root / "outputs/capacity") as capture:
                for _ in range(observer.MAX_CALLS - 1):
                    self.run_child(phase="image_inspect")
                self.run_child()
                self.run_child(phase="image_inspect")'''.replace(b'\n', nl)
new = b'''        with self.assertRaisesRegex(ValueError, "original engine phase missing or call capacity exhausted"):
            with self.capture(output_dir=self.root / "outputs/capacity") as capture:
                for _ in range(observer.MAX_CALLS - 1):
                    self._run_capacity_child(phase="image_inspect")
                self._run_capacity_child()
                self._run_capacity_child(phase="image_inspect")'''.replace(b'\n', nl)
assert raw.count(old) == 1
raw = raw.replace(old, new)
anchor = b'    def test_caught_invalid_phase_remains_sticky_and_call_capacity_is_bounded(self):'
fragment = (BASE / 'capacity_test_helpers.py.fragment').read_bytes().replace(b'\n', nl)
assert raw.count(anchor) == 1
path.write_bytes(raw.replace(anchor, fragment + anchor))
print(json.dumps({'path': str(path), 'size_bytes': path.stat().st_size,
                  'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}))
