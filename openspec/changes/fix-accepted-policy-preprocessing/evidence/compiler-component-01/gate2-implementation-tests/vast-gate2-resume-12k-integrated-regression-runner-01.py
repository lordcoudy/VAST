import sys,os,hashlib,json,platform,subprocess,unittest
from pathlib import Path
root=Path.cwd()
modules=['tests.'+p.stem for p in sorted((root/'tests').glob('test_accepted_policy_fixture_compiler*.py'))]
paths=sorted(set([str(p.relative_to(root)) for p in (root/'tests').glob('test_accepted_policy_fixture_compiler*.py')]+[str(p.relative_to(root)) for p in (root/'tests/fixtures').glob('accepted_policy_fixture_compiler*.py')]))
def pin():
 return {p:{'size_bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for p in paths for b in [(root/p).read_bytes()]}
before=pin()
print('CONTROLLED complete compiler regression; no live Gate2/P0/C-D/API or physical admission.',flush=True)
print(json.dumps({'python':sys.version,'platform':platform.platform(),'os_name':os.name,'modules':modules,'source_before':before},sort_keys=True),flush=True)
suite=unittest.TestLoader().loadTestsFromNames(modules)
result=unittest.TextTestRunner(stream=sys.stdout,verbosity=2).run(suite)
after=pin()
print(json.dumps({'source_after':after,'source_unchanged':before==after,'testsRun':result.testsRun,'errors':len(result.errors),'failures':len(result.failures),'skipped':len(result.skipped),'expectedFailures':len(result.expectedFailures),'unexpectedSuccesses':len(result.unexpectedSuccesses),'successful':result.wasSuccessful(),'physical_acceptance':False},sort_keys=True),flush=True)
raise SystemExit(0 if result.wasSuccessful() and before==after else 1)
