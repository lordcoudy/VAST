"""Separately pinned corrected consumer of immutable failed-CLI CPU04 outputs.

This does not rerun a guardian/native workload or replace the original CLI
terminal. The original producer's physical v5 source bytes must be present.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path('/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec')
BASE = Path(__file__).parent
arguments_path = BASE / 'arguments.v1.json'
arguments = json.loads(arguments_path.read_bytes())
sys.path.insert(0, str(ROOT / 'scripts'))
reader_path = BASE / 'corrected_component_runtime_v1.py'
assert hashlib.sha256(reader_path.read_bytes()).hexdigest() == '23202bc466cd53f60cc0b78eb7902b5cdb1be4c6242c04e5ed81d13609a0d49e'
spec = importlib.util.spec_from_file_location('cpu04_corrected_cold_consumer_v1', reader_path)
reader = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = reader
spec.loader.exec_module(reader)
for key, value in arguments.items():
    if key in ('runtime_bundle_paths', 'arm_result_paths'):
        arguments[key] = [Path(path) for path in value]
    else:
        arguments[key] = Path(value)
result = reader.cold_component_pair_v1(**arguments)
assert result['receipt']['resource'] == 'cpu' and result['receipt']['component_arms'] == 2
assert all(result['receipt'][key] is False for key in
           ('qualification_eligible', 'q4_eligible', 'publication_ready', 'full_run_eligible'))
print(json.dumps({'corrected_consumer_result': result['descriptor'],
                  'original_cpu04_cli_status': 'failed_immutable',
                  'new_native_measurements': 0, 'new_guardian_launches': 0}, sort_keys=True))
