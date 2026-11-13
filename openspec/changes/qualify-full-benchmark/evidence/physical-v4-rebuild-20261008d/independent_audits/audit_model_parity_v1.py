"""Audit completed g physical parity evidence without running any inference."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys

ROOT = Path('/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a')
BASE = ROOT / 'artifacts/qualify_full_benchmark_20261008d'
PARITY = BASE / 'model_parity_v4'
OUT = BASE / 'independent_audits/model_parity_v1'
RECEIPT_PATH = ROOT / 'configs/checkpoint_analytics_model_parity.refreshed.v4.qfb-20261008d.accepted.acceptance_receipt.json'
A244 = Path('/mnt/e/STUDY/VAST/artifacts/model_parity_v4_refresh_20260919_attempt244/materialization/transaction_index.json')
COMMIT = '8990a091590498ff32fc1491c2c16d6dd3adb76e'
cache = {}
descriptor_paths = set()
descriptor_count = 0


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def signature(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def physical(path):
    path = Path(path)
    require(path.is_absolute() and (path.is_relative_to(ROOT) or path == A244), f'path escapes evidence custody: {path}')
    require(path.resolve(strict=True) == path and all(not parent.is_symlink() for parent in (path, *path.parents)), f'symbolic or noncanonical path: {path}')
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 8 * 1024**3, f'file exceeds physical custody bounds: {path}')
    return info


def describe(path):
    path = Path(path)
    info = physical(path)
    if path in cache:
        require(signature(info) == cache[path]['signature'], f'file changed after hashing: {path}')
        return dict(cache[path]['descriptor'])
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        require(signature(os.fstat(stream.fileno())) == signature(info), f'file replaced at open: {path}')
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
        require(signature(os.fstat(stream.fileno())) == signature(info), f'file changed while hashing: {path}')
    require(signature(physical(path)) == signature(info), f'file changed after hashing: {path}')
    label = path.relative_to(ROOT).as_posix() if path.is_relative_to(ROOT) else str(path)
    result = {'path': label, 'sha256': digest.hexdigest(), 'size_bytes': info.st_size}
    cache[path] = {'signature': signature(info), 'descriptor': result}
    return dict(result)


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def read_json(path, seal=None):
    d = describe(path)
    require(d['size_bytes'] <= 8 * 1024 * 1024, f'JSON file exceeds 8MiB: {path}')
    raw = Path(path).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == d['sha256'], f'JSON bytes changed: {path}')
    value = json.loads(raw, object_pairs_hook=pairs)
    if seal:
        require(value[seal] == hashlib.sha256(canonical({key: item for key, item in value.items() if key != seal})).hexdigest(), f'JSON self seal differs: {path}')
    return value


def relative(value, parent=ROOT):
    require(type(value) is str and bool(value) and '\\' not in value, 'relative evidence path is invalid')
    path = PurePosixPath(value)
    require(not path.is_absolute() and '..' not in path.parts and '.' not in path.parts and path.as_posix() == value, f'noncanonical relative path: {value}')
    result = parent.joinpath(*path.parts)
    require(result.is_relative_to(ROOT), f'relative path escapes root: {value}')
    return result


def visit(value):
    global descriptor_count
    if isinstance(value, dict):
        if {'path', 'sha256', 'size_bytes'} <= value.keys():
            path = relative(value['path'])
            observed = describe(path)
            require((observed['sha256'], observed['size_bytes']) == (value['sha256'], value['size_bytes']), f'physical descriptor differs: {value["path"]}')
            descriptor_count += 1
            descriptor_paths.add(path)
        for child in value.values():
            visit(child)
    elif isinstance(value, list):
        for child in value:
            visit(child)


def exclusive(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    Path(path).chmod(0o444)
    return describe(path)


def tensor_pairs(document):
    result = {}
    for row in document['execution_bundles']:
        key = (row['branch'], row['resource'], row['role'], row['codec'], row['sample_id'])
        require(key not in result, f'execution/sample identity is duplicated: {key}')
        result[key] = (row['input_tensor_sha256'], row['output_tensor_sha256'])
    return result


def main():
    require(os.getuid() == 1000 and sys.flags.optimize == 0 and Path.cwd().resolve(strict=True) == ROOT, 'audit requires unoptimized WSL UID1000 in the canonical worktree')
    OUT.mkdir(mode=0o700, exist_ok=False)
    source = describe(Path(__file__).absolute())
    proven_source = describe(BASE / 'independent_audits/adapted_from_g_audit_model_parity_v1.py')
    sys.path.insert(0, str(ROOT / 'scripts'))
    from checkpoint_model_parity_acceptance_v4 import load_verified_model_parity_acceptance_v4
    # One original stock verifier call. This is a reader, not a materializer.
    binding = load_verified_model_parity_acceptance_v4(project_root=ROOT, receipt_path=RECEIPT_PATH)
    receipt = read_json(RECEIPT_PATH, 'receipt_sha256')
    binding_path = PARITY / 'acceptance_binding.v4.json'
    index_path = PARITY / 'materialization/transaction_index.json'
    binding_disk = read_json(binding_path, 'binding_sha256')
    index = read_json(index_path, 'transaction_sha256')
    require(binding == binding_disk, 'verified binding differs from physical binding')
    require(receipt['status'] == 'accepted_physical_model_parity_v4' and receipt['blockers'] == [] and receipt['publication_ready'] is True and receipt['evidence_count'] == 32, 'physical parity acceptance state differs')
    require(index['execution_bundle_count'] == len(index['execution_bundles']) == 480 and index['synthetic_or_mock_evidence_accepted'] is False and index['claimed_aggregates_accepted'] is False, 'physical execution authority/count differs')
    for document in (receipt, binding_disk, index):
        visit(document)
    require(sum(cache[path]['descriptor']['size_bytes'] for path in descriptor_paths) <= 64 * 1024**3, 'descriptor aggregate exceeds 64GiB')
    groups = Counter((row['branch'], row['resource'], row['role'], row['codec']) for row in index['execution_bundles'])
    require(len(groups) == 32 and set(groups.values()) == {15}, 'physical group/sample counts differ')
    nested_manifest_references = 0
    tensor_file_count = 0
    # Bind each index tensor hash to its actual physically hashed tensor file.
    for row in index['execution_bundles']:
        manifest_path = relative(row['manifest']['path'])
        manifest = read_json(manifest_path)
        unsigned = {key: value for key, value in manifest.items() if key != 'identity'}
        require(manifest['identity'] == {'algorithm': 'sha256', 'sha256': hashlib.sha256(canonical(unsigned)).hexdigest()} and manifest['identity']['sha256'] == row['manifest_identity_sha256'] and manifest['request_id'] == row['request_id'], f'execution manifest identity differs: {manifest_path}')
        require(set(manifest['files']) == {'input_tensor', 'output_tensor', 'request', 'response'}, f'execution file namespace differs: {manifest_path}')
        for kind, entry in manifest['files'].items():
            path = relative(entry['path'], manifest_path.parent)
            observed = describe(path)
            require(path in descriptor_paths, f'execution member is absent from the transaction descriptor inventory: {path}')
            require((observed['sha256'], observed['size_bytes']) == (entry['sha256'], entry['bytes']), f'execution member bytes differ: {path}')
            expected = row[kind + '_sha256']
            require(observed['sha256'] == expected, f'execution index/member hash differs: {path}')
            nested_manifest_references += 1
            tensor_file_count += int(kind in {'input_tensor', 'output_tensor'})
    require(nested_manifest_references == 1920 and tensor_file_count == 960, 'physical execution member count differs')
    current = tensor_pairs(index)
    original = tensor_pairs(read_json(A244))
    require(len(current) == len(original) == 480 and current == original, 'qfb physical tensor input/output pairs differ from A244')
    loader_sources = []
    for module in tuple(sys.modules.values()):
        filename = getattr(module, '__file__', None)
        if filename and Path(filename).is_absolute() and Path(filename).is_relative_to(ROOT / 'scripts') and Path(filename).suffix == '.py':
            loader_sources.append(describe(Path(filename)))
    loader_sources.sort(key=lambda entry: entry['path'])
    for path, entry in tuple(cache.items()):
        require(signature(physical(path)) == entry['signature'], f'file changed by audit end: {path}')
    result = {'schema_version': 1, 'artifact_kind': 'vast_g_independent_physical_model_parity_audit_v1', 'status': 'verified',
              'completed_at_utc': datetime.now(timezone.utc).isoformat(), 'uid': os.getuid(), 'python': sys.executable,
              'reviewed_source_commit': COMMIT, 'stock_loader_calls': 1, 'audit_source': source, 'adapted_proven_g_auditor': proven_source,
              'producer_original_exit_observation': {'session_id': 'bkmiw9r2h', 'exit_code': 0, 'observed_at_utc': '2026-10-08T09:21:46Z', 'source': 'Parent agent observed original process terminal; not an invented physical subprocess log.'},
              'producer_wrapper': describe(BASE / 'run_model_parity.sh'),
              'producer_stdout': describe(BASE / 'model_parity_control/stdout.log'), 'producer_stderr': describe(BASE / 'model_parity_control/stderr.log'),
              'acceptance_receipt': describe(RECEIPT_PATH), 'acceptance_identity_sha256': receipt['receipt_sha256'],
              'acceptance_binding': describe(binding_path), 'transaction_index': describe(index_path),
              'physical_execution_count': 480, 'groups': 32, 'samples_per_group': 15,
              'descriptor_count': descriptor_count, 'unique_files': len(descriptor_paths),
              'unique_bytes': sum(cache[path]['descriptor']['size_bytes'] for path in descriptor_paths),
              'execution_manifest_relative_references_rehashed': nested_manifest_references,
              'individual_physical_tensor_files_bound': tensor_file_count,
              'all_480_input_output_tensor_pairs_match_A244': True, 'a244_transaction_index': describe(A244),
              'loader_source_descriptors': loader_sources,
              'verified_physical_descriptors': sorted((cache[path]['descriptor'] for path in descriptor_paths), key=lambda entry: entry['path']),
              'limitations': ['Local independent read-only evidence validation; not CI or live policy qualification.',
                             'No builds, parity inference, native runtime entrypoint, GPU workload, guardian, Q4 or full-run arms were launched by this audit.',
                             'A244 comparison validates all physical tensor input/output hash pairs; it does not substitute historical receipts for fresh g acceptance.']}
    result['payload_sha256'] = hashlib.sha256(canonical(result)).hexdigest()
    d = exclusive(OUT / 'model-parity.audit.v1.json', result)
    print(json.dumps({'status': 'verified', 'receipt': d, 'physical_execution_count': 480, 'groups': 32,
                      'descriptor_count': descriptor_count, 'unique_files': len(descriptor_paths),
                      'unique_bytes': result['unique_bytes'], 'individual_tensor_files': tensor_file_count}, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if OUT.is_dir() and not (OUT / 'failure.json').exists():
            exclusive(OUT / 'failure.json', {'status': 'failed', 'error_type': type(error).__name__, 'error': str(error)})
        raise
