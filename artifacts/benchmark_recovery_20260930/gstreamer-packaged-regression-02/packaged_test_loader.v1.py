import sys,os,json,hashlib,importlib,tempfile,unittest
from pathlib import Path
sys.path[:0]=['/opt/vast/checkpoint','/opt/vast/python','/mnt/vast-tests']
expected=json.loads(Path('/mnt/vast-expectations.json').read_bytes())
fixture=Path(tempfile.mkdtemp(prefix='vast-packaged-fixtures-'))
(fixture/'scripts').symlink_to('/opt/vast/checkpoint',target_is_directory=True)
(fixture/'tests').symlink_to('/mnt/vast-tests',target_is_directory=True)
(fixture/'configs').symlink_to('/mnt/vast-configs',target_is_directory=True)
(fixture/'deploy').mkdir()
(fixture/'deploy/native_gst_probe').symlink_to('/mnt/vast-native-source',target_is_directory=True)
support=[importlib.import_module(name) for name in ['test_checkpoint_gstreamer_analytics_sidecar','test_checkpoint_native_policy_runtime']]
boundary=importlib.import_module('test_publication_operational_boundary_v1')
for module in [*support,boundary]:module.ROOT=fixture
observed={}
for name,sha in expected.items():
 module=importlib.import_module(name);path=Path(module.__file__).resolve(strict=True)
 assert path.parent==Path('/opt/vast/checkpoint'),(name,str(path))
 digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==sha,(name,digest,sha)
 observed[name]={'path':str(path),'sha256':digest}
for name in ['yaml','numpy']:
 path=Path(importlib.import_module(name).__file__).resolve(strict=True)
 assert Path('/opt/vast/python') in path.parents,(name,str(path))
print(json.dumps({'packaged_runtime_modules':observed,'no_host_runtime_imports':True,'inference':'local_fixture','publication_acceptance':False}),flush=True)
suite=unittest.defaultTestLoader.loadTestsFromTestCase(boundary.PublicationOperationalBoundaryTests)
assert suite.countTestCases()==10,suite.countTestCases()
result=unittest.TextTestRunner(verbosity=2).run(suite)
assert not result.skipped,result.skipped
sys.exit(0 if result.wasSuccessful() else 1)
