#!/usr/bin/env python3
"""Bounded S3 access/write probes and capacity evidence, never a workload runner."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile
import time
import uuid

from artifact_store import ArtifactStoreError, ArtifactIntegrityError, ArtifactPermanentError, sha256_file
from publication_physical_io_v1 import PhysicalRootCustodyV1
from s3_artifact_store import S3ArtifactStore, S3TransportError
from s3_capacity_attestation import (build_s3_capacity_attestation, validate_s3_capacity_attestation,
                                     validate_preflight, utc_now, S3CapacityError)
from s3_destination import S3Destination, canonical_bytes, read_physical_bytes

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = ('artifact_store.py','s3_artifact_store.py','s3_credentials.py','s3_destination.py',
                's3_publication_evidence.py','s3_capacity_attestation.py','s3_operator_preflight.py',
                'publication_cloud_environment.py','publication_physical_io_v1.py')
LIMIT = 64*1024**2


def source_sha256():
    return hashlib.sha256(canonical_bytes({name:hashlib.sha256(read_physical_bytes(
        Path(__file__).parent/name, maximum=1024*1024)).hexdigest() for name in SOURCE_FILES})).hexdigest()


def _finish(report):
    report['sha256'] = hashlib.sha256(canonical_bytes(report)).hexdigest()
    if len(canonical_bytes(report)) > 1024*1024:
        raise ArtifactPermanentError('S3 operator report exceeds its bound')
    return report


def run_smoke(store, *, work_root):
    started = time.monotonic()
    deadline = started+120
    store.probe_payload_limit = LIMIT
    checks = {name:False for name in ('put','multipart','matching_reuse','put_collision',
                                     'multipart_collision','full_readback','restore')}
    work = Path(work_root)
    tiny, large, conflict = work/'tiny.bin', work/'multipart.bin', work/'conflicting.bin'
    tiny.write_bytes(b'VAST bounded S3 probe v1\n')
    with large.open('xb') as target:
        target.write(b'B'*(8*1024**2))
        target.write(b'!')
    original_threshold, original_part = store._multipart_threshold, store._part_size
    try:
        with store.operation(deadline):
            initial = store.preflight()
            if initial['object_count'] != 0:
                raise ArtifactPermanentError('S3 live probe namespace is not fresh')
            tiny_result = store.upload_and_verify(tiny)
            checks['put'] = True
            reused = store.probe_conditional_create(tiny, remote_name='tiny.bin')
            checks['matching_reuse'] = reused['sha256'] == tiny_result['sha256']
            conflict.write_bytes(b'conflicting probe content\n')
            try:
                store.probe_conditional_create(conflict, remote_name='tiny.bin')
            except ArtifactIntegrityError:
                store.verify_remote('tiny.bin', expected_sha256=tiny_result['sha256'],expected_size=tiny_result['size_bytes'])
                checks['put_collision'] = True
            else:
                raise ArtifactPermanentError('S3 server did not enforce conditional PUT')
            store._multipart_threshold = store._part_size = 8*1024**2
            large_result = store.upload_and_verify(large)
            checks['multipart'] = True
            with conflict.open('wb') as target:
                target.write(b'C'*(8*1024**2))
                target.write(b'?')
            try:
                store.probe_conditional_create(conflict,remote_name='multipart.bin')
            except ArtifactIntegrityError:
                store.verify_remote('multipart.bin', expected_sha256=large_result['sha256'],expected_size=large_result['size_bytes'])
                checks['multipart_collision'] = True
            else:
                raise ArtifactPermanentError('S3 server did not enforce conditional multipart completion')
            for name, result in [('tiny.bin',tiny_result),('multipart.bin',large_result)]:
                store.verify_remote(name,expected_sha256=result['sha256'],expected_size=result['size_bytes'],
                                    expected_version_id=result['object']['version_id'])
            checks['full_readback'] = True
            restored = work/'restored.bin'
            store.materialize_remote('multipart.bin',destination=restored,
                expected_sha256=large_result['sha256'],expected_size=large_result['size_bytes'],
                expected_version_id=large_result['object']['version_id'])
            checks['restore'] = sha256_file(restored) == large_result['sha256']
            inventory = store.list_remote_files()
            if set(inventory) != {'tiny.bin','multipart.bin'} or not all(checks.values()):
                raise ArtifactPermanentError('S3 live probe outcomes or inventory are invalid')
            if list(store.intent_root.glob('*.json')):
                raise ArtifactPermanentError('S3 live probe has unresolved owned multipart uploads')
        import botocore
        return _finish({'artifact_kind':'vast_s3_preflight_v1','schema_version':1,'status':'write_ready',
            'destination':store.destination.identity,'run_prefix':store.prefix,'observed_at_utc':utc_now(),
            'object_count':len(inventory),'quota_visibility':'not_exposed',
            'write_verified':True,'conditional_creation_verified':True,
            'verification':{'checks':checks,'objects':[tiny_result['object'],large_result['object']],
                'source_sha256':source_sha256(),'sdk_version':botocore.__version__,
                'python_version':platform.python_version(),'elapsed_s':round(time.monotonic()-started,3),
                'uploaded_bytes':store.uploaded_bytes,'readback_bytes':store.readback_bytes,'leftover_uploads':[]}})
    finally:
        store._multipart_threshold, store._part_size = original_threshold, original_part


def write_report(path, report):
    target = Path(os.path.abspath(os.fspath(path)))
    payload = canonical_bytes(report)+b'\n'
    if len(payload) > 1024*1024:
        raise ArtifactPermanentError('S3 operator report exceeds its bound')
    with PhysicalRootCustodyV1.open(target.parent,label='S3 report parent') as custody:
        custody.commit_or_adopt_exact_identity(target.name,payload,label='S3 immutable operator report',mode=0o444)


def materialize_capacity(*, project_root, sizing_index, preflight_report, destination,
                         available_bytes, confirmed_at_utc, confirmation_reference, output):
    from backend_pair_archive_sizing_receipts_v1 import load_operator_sizing_rows_v1
    root = Path(project_root).resolve(strict=True)
    index = Path(sizing_index)
    if not index.is_absolute():
        index = root/index
    relative = index.relative_to(root).as_posix()
    raw = read_physical_bytes(index,maximum=16*1024**2)
    rows = load_operator_sizing_rows_v1(project_root=root,index_path=index)
    preflight = json.loads(read_physical_bytes(Path(preflight_report),maximum=1024*1024))
    source = source_sha256()
    if preflight.get('verification',{}).get('source_sha256') != source:
        raise S3CapacityError('S3 live preflight source differs from the current adapter')
    value = build_s3_capacity_attestation(destination=destination,preflight=preflight,
        observed_pair_archives=rows,sizing_source={'path':relative,'sha256':hashlib.sha256(raw).hexdigest(),'size_bytes':len(raw)},
        source_identity={'source_sha256':source,'sdk_version':'1.43.62'},
        operator_confirmation={'basis':'operator_explicit_guarantee','available_capacity_lower_bound_bytes':available_bytes,
            'confirmed_at_utc':confirmed_at_utc,'confirmation_reference':confirmation_reference},observed_at_utc=utc_now())
    validate_s3_capacity_attestation(value,destination=destination,project_root=root)
    write_report(output,value)
    return value


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cloud-config-file',type=Path,default=PROJECT_ROOT/'configs/artifact-storage.yaml')
    parser.add_argument('--s3-credentials-file',type=Path)
    commands = parser.add_subparsers(dest='command',required=True)
    for name in ('preflight','smoke'):
        sub = commands.add_parser(name)
        sub.add_argument('--output',type=Path,required=True)
    capacity = commands.add_parser('capacity')
    capacity.add_argument('--project-root',type=Path,default=PROJECT_ROOT)
    capacity.add_argument('--sizing-index',type=Path,required=True)
    capacity.add_argument('--preflight-report',type=Path,required=True)
    capacity.add_argument('--available-bytes',type=int,required=True)
    capacity.add_argument('--confirmed-at-utc',required=True)
    capacity.add_argument('--confirmation-reference',required=True)
    capacity.add_argument('--output',type=Path,required=True)
    return parser


def main():
    args = build_parser().parse_args()
    store = None
    work = None
    operator_deadline = time.monotonic()+120
    try:
        destination = S3Destination.from_file(args.cloud_config_file)
        if args.command == 'capacity':
            value = materialize_capacity(project_root=args.project_root,sizing_index=args.sizing_index,
                preflight_report=args.preflight_report,destination=destination,available_bytes=args.available_bytes,
                confirmed_at_utc=args.confirmed_at_utc,confirmation_reference=args.confirmation_reference,output=args.output)
        else:
            work = tempfile.TemporaryDirectory(prefix='vast-s3-operator-')
            store = S3ArtifactStore(destination,credentials_file=args.s3_credentials_file,
                                    intent_root=Path(work.name)/'intents', outer_deadline=operator_deadline)
            store.bind_probe(uuid.uuid4().hex)
            value = run_smoke(store,work_root=Path(work.name)) if args.command == 'smoke' else store.preflight()
            write_report(args.output,value)
        print(json.dumps({'status':value['status'],'report_path':str(args.output),'sha256':value['sha256']}))
        return 0
    except Exception as error:
        leftovers = []
        if store is not None and store.intent_root.exists():
            # Only this helper's fresh private journal. No remote/global listing or deletion.
            try:
                with store.operation(min(operator_deadline,time.monotonic()+15)):
                    with store._intent_custody() as custody:
                        for path in store.intent_root.glob('*.json'):
                            value,_identity = store._read_intent(custody,path.name)
                            try:
                                store._abort(value)
                                store._remove_intent(custody,path.name)
                            except ArtifactStoreError:
                                leftovers.append({'key':value['key'],'upload_id_sha256':hashlib.sha256(str(value['upload_id']).encode()).hexdigest()})
            except Exception:
                leftovers.append({'journal':str(store.intent_root),'status':'cleanup_unavailable'})
        report = _finish({'artifact_kind':'vast_s3_operator_failure_v1','schema_version':1,'status':'blocked',
            'stage':args.command,'reason':str(error) if isinstance(error,(ArtifactStoreError,S3CapacityError)) else 'S3 operator input or execution failed',
            'run_prefix':store.prefix if store else None,'leftovers':leftovers,
            'probe_objects':([{'key':store.prefix+name,'status':'retained_or_unknown'} for name in ('tiny.bin','multipart.bin')]
                             if store is not None and args.command == 'smoke' else [])})
        try:
            write_report(args.output,report)
        except Exception:
            pass
        print(json.dumps(report))
        # An unresolved owned checkpoint must survive the temporary helper root.
        if leftovers and work is not None:
            work._finalizer.detach()
        return 75 if isinstance(error,S3TransportError) else 78
    finally:
        if work is not None and not (store and store.intent_root.exists() and list(store.intent_root.glob('*.json'))):
            work.cleanup()


if __name__ == '__main__':
    raise SystemExit(main())
