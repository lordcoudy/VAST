"""Packaged byte/transport fixtures only; no model or benchmark acceptance."""
import hashlib,importlib,json,sys,tempfile,unittest
from pathlib import Path
sys.path[:0]=['/opt/vast/checkpoint','/opt/vast/python','/mnt/vast-tests']
expectations=json.loads(Path('/mnt/vast-expectations.json').read_bytes())
observed={}
for name,sha in expectations['files'].items():
    path=Path(name);assert path.is_file() and not path.is_symlink(),name
    raw=path.read_bytes();actual=hashlib.sha256(raw).hexdigest();assert actual==sha,(name,actual,sha)
    observed[name]={'size_bytes':len(raw),'sha256':actual}
fixture=Path(tempfile.mkdtemp(prefix='vast-packaged-fixtures-'))
# These fixture-only symlinks provide test imports/paths. They are not physical
# component/source authority and are never evidence of actual model acceptance.
(fixture/'scripts').symlink_to('/opt/vast/checkpoint',target_is_directory=True)
(fixture/'tests').symlink_to('/mnt/vast-tests',target_is_directory=True)
(fixture/'configs').symlink_to('/mnt/vast-configs',target_is_directory=True)
(fixture/'deploy').mkdir()
(fixture/'deploy/native_gst_probe').symlink_to('/mnt/vast-native-source',target_is_directory=True)
names=['test_checkpoint_gstreamer_analytics_sidecar','test_checkpoint_native_policy_runtime',
    'test_publication_guardian_runtime_expectations_v1','test_publication_operational_boundary_v1',
    'test_publication_guardian_component_preprocessing_contract_v1']
modules={name:importlib.import_module(name) for name in names}
for module in modules.values():module.ROOT=fixture
for name in expectations['python_modules']:
    if name in sys.modules:
        path=Path(sys.modules[name].__file__).resolve(strict=True)
        assert path==Path('/opt/vast/checkpoint')/(name+'.py'),(name,str(path))
for name in ('yaml','numpy'):
    path=Path(importlib.import_module(name).__file__).resolve(strict=True)
    assert Path('/opt/vast/python') in path.parents,(name,str(path))
component=modules['test_publication_guardian_component_preprocessing_contract_v1']
boundary=modules['test_publication_operational_boundary_v1']
suite=unittest.TestSuite()
for case in (component.ComponentPreprocessingTests,component.ComponentFrontTests,boundary.PublicationOperationalBoundaryTests):
    for test in unittest.defaultTestLoader.loadTestsFromTestCase(case):
        if test._testMethodName=='test_original_long_stock_cell_ids_remain_accepted_without_a_new_clamp':continue
        suite.addTest(test)
assert suite.countTestCases()==19,suite.countTestCases()
print(json.dumps({'packaged_files':observed,'packaged_files_count':len(observed),'runtime_source_input_count':73,
    'test_count':19,'selection':['9 component fixtures','10 original real-front fixtures'],
    'excluded_host_only_constructor':'test_original_long_stock_cell_ids_remain_accepted_without_a_new_clamp',
    'inference':'local fixture only','accepted':False,'publication_ready':False}),flush=True)
result=unittest.TextTestRunner(verbosity=2).run(suite)
for name in expectations['python_modules']:
    if name in sys.modules:
        path=Path(sys.modules[name].__file__).resolve(strict=True)
        assert path==Path('/opt/vast/checkpoint')/(name+'.py'),(name,str(path))
assert not result.skipped,result.skipped
sys.exit(0 if result.wasSuccessful() else 1)
