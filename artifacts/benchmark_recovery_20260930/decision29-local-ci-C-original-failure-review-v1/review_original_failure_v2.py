"""Read/copy only exact original failure metadata; no network, retry or targets."""
import ast
import hashlib
import json
import os
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
ROOT = BASE.parents[1]
CI = BASE / 'decision29-current-ci-preparation-v1'
OUTPUT = Path(r'\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-current-source-ci-20261003-decision29-original-output')
CHECKOUT = Path(r'\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-current-source-ci-20261003-decision29')
C = '04a5d1c7b90274af71f4ff2456ec3013107c2bb3'
START = time.monotonic()
END = START + 120
copies = HERE / 'original-copies'
assert copies.is_dir()
pins = []
total = 0

def descriptor(path, raw):
    return {'path': path.as_posix(), 'size_bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}

def read(path):
    global total
    assert time.monotonic() < END
    named_before = path.stat()
    with path.open('rb') as stream:
        original_size = os.fstat(stream.fileno()).st_size
        raw = stream.read(4*1048576+1)
        assert len(raw) <= 4*1048576 and original_size == os.fstat(stream.fileno()).st_size == len(raw)
    named_after = path.stat()
    assert (named_before.st_ino, named_before.st_size, named_before.st_mtime_ns) == (named_after.st_ino, named_after.st_size, named_after.st_mtime_ns)
    total += len(raw)
    assert total <= 16*1048576
    return raw

def preserve(path, relative):
    raw = read(path)
    dest = copies / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    assert dest.is_file() and dest.read_bytes() == raw
    pins.append({'original': descriptor(path, raw), 'immutable_review_copy': descriptor(dest, raw)})
    return raw

names = ['model-assets.json', 'model-assets.stderr', 'model-assets.stdout', 'report.json', 'specification-inventory.json',
         'tracked-source.before.json', 'tracked-source.after.json',
         'model-acquisition/asset-00.dispatch.json', 'model-acquisition/asset-00.json',
         'model-acquisition/asset-00.stderr', 'model-acquisition/asset-00.stdout',
         'model-acquisition/asset-00.terminal.json', 'model-acquisition/failed.json']
assert sorted(p.name for p in OUTPUT.iterdir()) == sorted(['model-acquisition'] + [n for n in names if '/' not in n])
assert sorted(p.name for p in (OUTPUT / 'model-acquisition').iterdir()) == sorted([n.split('/',1)[1] for n in names if '/' in n])
raws = {name: preserve(OUTPUT / name, Path('stock-output') / name) for name in names}
capture_names = ['terminal.v1.json', 'dispatch.v1.json', 'stdout.raw', 'stderr.raw']
capture_raw = {name: preserve(CI / 'original-full-ci-attempt01' / name, Path('original-wrapper') / name) for name in capture_names}
controller = preserve(CI / 'capture_original_full_ci_v1.py', Path('source') / 'capture_original_full_ci_v1.py.raw')
assert len(controller) == 12429 and hashlib.sha256(controller).hexdigest() == 'a37fecbaa6fb4a560bb7c44897a39a9f3c0e294d5fb4b75c0cb2412ec465c9ac'
model_source = preserve(CHECKOUT / 'scripts/prepare_ci_model_assets.py', Path('source') / 'prepare_ci_model_assets.py.raw')
stock_source = preserve(CHECKOUT / 'scripts/run_ci_checks.py', Path('source') / 'run_ci_checks.py.raw')
assert len(model_source) == 30314 and hashlib.sha256(model_source).hexdigest() == '2f87df4f6d98239190c17b42bb7f43188fc2a12604f7b0f6aa0246f7df15b36c'
assert len(stock_source) == 29477 and hashlib.sha256(stock_source).hexdigest() == 'ce375eca51164a76ab6a88cf02b92804077f08c6b8401d68b48e293020c27a2c'
report = json.loads(raws['report.json'])
terminal = json.loads(capture_raw['terminal.v1.json'])
dispatch = json.loads(capture_raw['dispatch.v1.json'])
asset = json.loads(raws['model-acquisition/asset-00.json'])
asset_dispatch = json.loads(raws['model-acquisition/asset-00.dispatch.json'])
asset_terminal = json.loads(raws['model-acquisition/asset-00.terminal.json'])
acquisition_failed = json.loads(raws['model-acquisition/failed.json'])
model_command = json.loads(raws['model-assets.json'])
model_stderr = json.loads(raws['model-assets.stderr'])
tracking = json.loads(raws['tracked-source.before.json'])
assert report['commit'] == terminal['source_commit'] == dispatch['source_commit'] == C
assert terminal['status'] == 'failed' and terminal['returncode'] == 1 and terminal['first_error'] == {'message':'original full CI exit is failed; retain stock report','type':'AssertionError'}
assert terminal['close_errors'] == [] and terminal['signals'] == [] and terminal['eof'] == ['stderr', 'stdout']
assert terminal['source_before_after_equal'] is True and terminal['held_descriptors_released'] is True
assert len(terminal['process_scans']) == 2 and all(not s['members'] and not s['errors'] for s in terminal['process_scans'])
assert terminal['original']['pid'] == terminal['original']['pgid'] == 94012 and terminal['original']['startticks'] == 50492196
assert terminal['original']['boot_id'] == asset_terminal['boot_id'] == 'dde50e69-39bf-45bd-bdb7-bc33c9adcb0b'
assert len(capture_raw['stdout.raw']) == terminal['channel_bytes']['stdout'] == 130
assert len(capture_raw['stderr.raw']) == terminal['channel_bytes']['stderr'] == 0
assert report['successful'] is False and report['failure'] == 'RuntimeError: model-assets failed: see its original stdout/stderr'
assert report['raw_checkout_bytes_match_commit'] is True and report['changed_tracked_paths'] == []
assert raws['tracked-source.before.json'] == raws['tracked-source.after.json'] and len(tracking) == 5561
assert tracking['scripts/prepare_ci_model_assets.py'] == {'size_bytes':len(model_source),'sha256':hashlib.sha256(model_source).hexdigest()}
assert tracking['scripts/run_ci_checks.py'] == {'size_bytes':len(stock_source),'sha256':hashlib.sha256(stock_source).hexdigest()}
assert model_command['returncode'] == asset_terminal['returncode'] == 1 and model_command['timed_out'] is False and asset_terminal['timed_out'] is False
assert model_command['cleanup_error'] is None and asset_terminal['pid'] == 94035 and asset_terminal['child_pgid'] == asset_terminal['outer_pgid'] == 94034
assert asset['index'] == 0 and asset['status'] == 'failed' and asset['http_status'] == 200
assert asset['asset']['size_bytes'] == 254351 and asset['response_headers']['Content-Length'] == '254351'
assert asset['error']['type'] == 'TimeoutError' and asset['error']['message'] == 'The read operation timed out'
assert asset['error']['traceback_truncated'] is False and 'line 380, in _download' in asset['error']['traceback'] and 'block = response.read(limit)' in asset['error']['traceback']
assert model_stderr == {'status':'failed','error_type':'AssetPreparationError','error':'The read operation timed out','error_truncated':False}
assert acquisition_failed['status'] == 'failed' and acquisition_failed['completed_assets'] == [] and acquisition_failed['error_type'] == 'AssetPreparationError'
assert asset['received_bytes'] == asset['hashed_prefix_bytes'] == asset['completed_write_bytes'] == asset['original_file_observed_bytes'] == 0
assert asset['original_file_epoch'][4] == 0 and asset['partial_path_matches_original_fd'] is True
assert asset['received_prefix_sha256'] == hashlib.sha256(b'').hexdigest()
assert asset['received_prefix_sha384'] == hashlib.sha384(b'').hexdigest()
assert raws['model-assets.stdout'] == raws['model-acquisition/asset-00.stdout'] == b''
assert not any(k in report for k in ('unittest', 'observer', 'namespace_diagnostic', 'namespace_profile', 'built_targets'))
constant_nodes = {n.targets[0].id: n.value for n in ast.parse(model_source).body
                  if isinstance(n, ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id in ('CHUNK_BYTES','SOCKET_SECONDS')}
chunk = constant_nodes['CHUNK_BYTES']
assert isinstance(chunk, ast.BinOp) and isinstance(chunk.op, ast.Mult) and isinstance(chunk.left, ast.Constant) and isinstance(chunk.right, ast.Constant) and type(chunk.left.value) is int and type(chunk.right.value) is int and chunk.left.value == 64 and chunk.right.value == 1024
assert ast.literal_eval(constant_nodes['SOCKET_SECONDS']) == 15.0
for row in pins:
    path = Path(row['original']['path'])
    # descriptor round trip uses UNC POSIX representation only for reading originals.
    assert descriptor(path, read(path)) == row['original']
result = {
    'schema_version':1, 'reviewer':'/root/decision28_source_peer', 'reviewed_commit':C,
    'reviewable':True, 'blocking_findings':[], 'reviewer_handles_released':True,
    'original_attempt_status':'failed', 'original_tool_returncode':1,
    'root_reported_original_tool_closure':{'initial_tool':'cd2125','session_id':23990,'completion_tool':'159b17','returncode':1,'source':'Parent original closure, joined here to original terminal/stock report bytes.'},
    'owned_source_pins':[descriptor(CI/'capture_original_full_ci_v1.py',controller), descriptor(CHECKOUT/'scripts/prepare_ci_model_assets.py',model_source),descriptor(CHECKOUT/'scripts/run_ci_checks.py',stock_source)],
    'exact_original_metadata_and_raw_copies':pins,
    'first_original_cause':{'type':'TimeoutError','message':'The read operation timed out','operation':'first HTTPResponse.read(limit) at prepare_ci_model_assets.py:380',
                            'received_HTTP_status':200,'declared_Content_Length':254351,'recorded_elapsed_s':asset['elapsed_s'],
                            'original_socket_timeout_s':15.0,'original_CHUNK_BYTES':65536,'outer_timeout_fired':False},
    'causal_chain':['Original TLS response read TimeoutError','AssetPreparationError retained in original acquisition failed.json and model-assets.stderr','Stock full CI RuntimeError: model-assets failed','Capture AssertionError retaining original failed stock report'],
    'original_asset_descriptor':asset['asset'], 'original_asset_failure_record':asset,
    'original_acquisition_dispatch':asset_dispatch, 'original_acquisition_terminal':asset_terminal,
    'original_completed_assets':[], 'received_or_written_prefix_bytes':0,
    'original_failed_partial_file_epoch':asset['original_file_epoch'], 'current_partial_file_presence_or_epoch_not_observed':True,
    'original_raw_source_before_after_identical':True, 'tracked_source_count':5561,'raw_checkout_bytes_match_commit_reported':True,
    'original_wrapper_terminal':terminal, 'original_model_command':model_command,
    'stock_source_failure':report['failure'],
    'not_reached_in_this_original_attempt':['native configure/build','loaded GStreamer factory facts','namespace diagnostic/profile admission','full unittest discovery/selection/execution and external observer'],
    'original_report_static_syntax_file_counts':{k:len(report[k]) for k in ('python_syntax','bash_syntax','python_tests')},
    'limits':['Only the exact original C attempt metadata/raw channels and two source files were read and copied. No network, retry, setup, CI, Git, engine, model read/measurement or cleanup occurred.',
              'The original network reason beyond the recorded TLS/socket read timeout is unknown; this record does not establish server outage or a source defect.',
              'Prospective syntax/test-file lists in the report are not unittest-discovered IDs or successful test outcomes.',
              'Original wrapper provides two error-free owned PID/group/session scans and released held descriptors, but it records no numeric FD count; none is invented.',
              'Asset child94035/group94034 return1/reap metadata is preserved. No fresh absence scan for that separate group or new Linux seven-epoch custody is claimed by this Windows/UNC review.',
              'Copies preserve raw originals and their exact full hashes. The failed original remains failed, with zero completed assets; no scientific/hardware/full-CI acceptance follows.'],
    'elapsed_s':time.monotonic()-START,
}
raw = json.dumps(result,sort_keys=True,indent=2,allow_nan=False).encode()+b'\n'
assert len(raw)<=1048576 and time.monotonic()<END
path=HERE/'review.v1.json'
with path.open('xb') as stream:
    assert stream.write(raw)==len(raw)
print(json.dumps({'review':descriptor(path,raw),'first_cause':'HTTP200 then first response.read timed out; zero received/written bytes','original_status':'failed'},sort_keys=True))
