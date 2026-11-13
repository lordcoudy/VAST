"""Cold import of only the reviewed export inventory; no payload executes."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as gate


class ExportClosureTests(unittest.TestCase):
    def test_fresh_stdlib_interpreter_uses_only_fixed_exported_project_sources(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for relative in gate.CODE_PATHS:
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            # -I -S removes caller paths, environment Python hooks and installed
            # project packages. This process imports code only; no fixture entry
            # point, WSL launcher, Docker socket or retained ELF is invoked.
            program = '''
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
sys.path[:0] = [str(root), str(root / 'scripts')]
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_child_v1 as child
from tests.fixtures import accepted_policy_fixture_compiler_gate2_p0_v1 as p0
from tests.fixtures import accepted_policy_fixture_compiler_recovery_v1 as recovery
for module in (c, d, child, p0, recovery):
    assert pathlib.Path(module.__file__).is_relative_to(root)
try:
    d._info_identity_v1({}, ['%064x' % number for number in range(1, 10)])
except d.StageDRefusal:
    pass
else:
    raise AssertionError('invalid identity unexpectedly passed')
print(json.dumps({'import_only': True, 'physical_execution': False}))
'''
            result = subprocess.run([sys.executable, '-I', '-S', '-B', '-c', program, str(root)],
                                    cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    timeout=15, check=False)
            self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
            self.assertEqual(json.loads(result.stdout), {'import_only': True, 'physical_execution': False})


if __name__ == '__main__':
    unittest.main()
