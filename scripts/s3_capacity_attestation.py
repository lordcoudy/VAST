"""S3 full-cloud admission from actual Q4 sizing and a dated operator guarantee."""
from __future__ import annotations
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re

from s3_destination import S3Destination, canonical_bytes, read_physical_bytes
from seafile_capacity_attestation_v1 import build_sizing_projection, SeafileCapacityAttestationV1Error
from seafile_operator_capacity_attestation_v2 import _validate_projection, SeafileOperatorCapacityAttestationV2Error


class S3CapacityError(RuntimeError):
    pass


def _hash(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _time(value):
    try:
        if type(value) is not str or re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ', value) is None:
            raise ValueError
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        raise S3CapacityError('S3 capacity evidence UTC date is invalid') from None


def validate_preflight(value, *, destination, now_utc, require_write=True):
    fields = {'artifact_kind','schema_version','status','destination','run_prefix','observed_at_utc',
              'object_count','quota_visibility','write_verified','conditional_creation_verified','verification','sha256'}
    if (type(value) is not dict or set(value) != fields or value['artifact_kind'] != 'vast_s3_preflight_v1'
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or value['destination'] != destination.identity or value['quota_visibility'] != 'not_exposed'
            or type(value['object_count']) is not int or not 0 <= value['object_count'] <= 10000
            or value['sha256'] != _hash({k:v for k,v in value.items() if k!='sha256'})):
        raise S3CapacityError('S3 preflight schema or destination drifted')
    age = _time(now_utc) - _time(value['observed_at_utc'])
    if not timedelta(0) <= age <= timedelta(hours=24):
        raise S3CapacityError('S3 preflight evidence is stale or future dated')
    if require_write:
        if (value['status'] != 'write_ready' or value['write_verified'] is not True
                or value['conditional_creation_verified'] is not True
                or re.fullmatch(re.escape(destination.prefix)+r'preflight/[0-9a-f]{32}/', value['run_prefix']) is None):
            raise S3CapacityError('S3 capacity requires a live conditional write preflight')
        proof = value['verification']
        fields = {'checks','objects','source_sha256','sdk_version','python_version','elapsed_s',
                  'uploaded_bytes','readback_bytes','leftover_uploads'}
        checks = {'put','multipart','matching_reuse','put_collision','multipart_collision','full_readback','restore'}
        if (type(proof) is not dict or set(proof) != fields or type(proof['checks']) is not dict
                or set(proof['checks']) != checks or any(result is not True for result in proof['checks'].values())
                or proof['sdk_version'] != '1.43.62' or proof['python_version'] != '3.12.3'
                or re.fullmatch(r'[0-9a-f]{64}', str(proof['source_sha256'])) is None
                or type(proof['elapsed_s']) not in {int,float} or not 0 <= proof['elapsed_s'] <= 120
                or proof['leftover_uploads'] != [] or type(proof['objects']) is not list
                or not 1 <= len(proof['objects']) <= 4 or len(proof['objects']) != value['object_count']
                or any(type(proof[x]) is not int or not 0 <= proof[x] <= 64*1024**2
                       for x in ('uploaded_bytes','readback_bytes'))):
            raise S3CapacityError('S3 live preflight verification or bounds drifted')
        names = set()
        for item in proof['objects']:
            if (type(item) is not dict or set(item) != {'key','size_bytes','sha256','version_id'}
                    or type(item['key']) is not str or not item['key'].startswith(value['run_prefix'])
                    or item['key'] in names or '/' in item['key'][len(value['run_prefix']):]
                    or type(item['size_bytes']) is not int or item['size_bytes'] < 0
                    or re.fullmatch(r'[0-9a-f]{64}',str(item['sha256'])) is None
                    or (item['version_id'] is not None and type(item['version_id']) is not str)):
                raise S3CapacityError('S3 live preflight object descriptor drifted')
            names.add(item['key'])
    elif value['status'] != 'read_only_ready' or value['write_verified'] is not False or value['verification'] is not None:
        raise S3CapacityError('S3 read-only preflight schema drifted')
    return value


def build_s3_capacity_attestation(*, destination, preflight, observed_pair_archives, sizing_source,
                                  source_identity, operator_confirmation, observed_at_utc):
    try:
        projection = build_sizing_projection(observed_pair_archives)
    except SeafileCapacityAttestationV1Error:
        raise S3CapacityError('S3 capacity requires the original complete 280-row Q4 sizing') from None
    material = {'schema_version':1,'artifact_kind':'vast_s3_operator_capacity_attestation_v1',
        'status':'accepted_operator_capacity_lower_bound','scope':'full_publication_s3_destination_only',
        'observed_at_utc':observed_at_utc,'destination':destination.identity,'preflight_observation':preflight,
        'operator_capacity':dict(operator_confirmation),'sizing_source':dict(sizing_source),
        'source_identity':dict(source_identity),'sizing_projection':projection}
    material['sha256'] = _hash(material)
    return validate_s3_capacity_attestation(material, destination=destination, now_utc=observed_at_utc)


def validate_s3_capacity_attestation(value, *, destination, now_utc=None, project_root=None):
    fields = {'schema_version','artifact_kind','status','scope','observed_at_utc','destination',
              'preflight_observation','operator_capacity','sizing_source','source_identity','sizing_projection','sha256'}
    if (type(value) is not dict or set(value) != fields or type(value['schema_version']) is not int
            or value['schema_version'] != 1 or value['artifact_kind'] != 'vast_s3_operator_capacity_attestation_v1'
            or value['status'] != 'accepted_operator_capacity_lower_bound'
            or value['scope'] != 'full_publication_s3_destination_only' or value['destination'] != destination.identity
            or value['sha256'] != _hash({k:v for k,v in value.items() if k!='sha256'})):
        raise S3CapacityError('S3 capacity attestation schema or destination drifted')
    now = now_utc or utc_now()
    confirmation = value['operator_capacity']
    if (type(confirmation) is not dict or set(confirmation) != {'basis','available_capacity_lower_bound_bytes',
            'confirmed_at_utc','confirmation_reference'} or confirmation['basis'] != 'operator_explicit_guarantee'
            or type(confirmation['available_capacity_lower_bound_bytes']) is not int
            or confirmation['available_capacity_lower_bound_bytes'] < 500*1024**3
            or re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:-]{7,159}',str(confirmation['confirmation_reference'])) is None):
        raise S3CapacityError('S3 dated available-capacity guarantee is missing or invalid')
    confirmed, observed, current = _time(confirmation['confirmed_at_utc']), _time(value['observed_at_utc']), _time(now)
    if not confirmed <= observed <= current or current-confirmed > timedelta(hours=24):
        raise S3CapacityError('S3 available-capacity guarantee is stale or future dated')
    validate_preflight(value['preflight_observation'], destination=destination, now_utc=now)
    if _time(value['preflight_observation']['observed_at_utc']) > observed:
        raise S3CapacityError('S3 capacity predates its live preflight')
    try:
        _validate_projection(value['sizing_projection'], lower_bound=confirmation['available_capacity_lower_bound_bytes'])
    except SeafileOperatorCapacityAttestationV2Error:
        raise S3CapacityError('S3 capacity is below the unchanged Q4 sizing requirement') from None
    descriptor, source = value['sizing_source'], value['source_identity']
    if (type(descriptor) is not dict or set(descriptor) != {'path','sha256','size_bytes'}
            or type(descriptor['path']) is not str or Path(descriptor['path']).is_absolute()
            or '\\' in descriptor['path'] or any(x in {'','..','.'} for x in descriptor['path'].split('/'))
            or type(descriptor['size_bytes']) is not int or descriptor['size_bytes'] <= 0
            or re.fullmatch(r'[0-9a-f]{64}',str(descriptor['sha256'])) is None
            or type(source) is not dict or set(source) != {'source_sha256','sdk_version'}
            or source['sdk_version'] != '1.43.62' or re.fullmatch(r'[0-9a-f]{64}',str(source['source_sha256'])) is None):
        raise S3CapacityError('S3 sizing/source descriptors are invalid')
    if project_root is not None:
        from backend_pair_archive_sizing_receipts_v1 import load_operator_sizing_rows_v1
        try:
            root = Path(project_root).resolve(strict=True)
            path = root/descriptor['path']
            raw = read_physical_bytes(path, maximum=16*1024**2)
            if len(raw) != descriptor['size_bytes'] or hashlib.sha256(raw).hexdigest() != descriptor['sha256']:
                raise S3CapacityError('S3 original Q4 sizing index changed')
            rows = load_operator_sizing_rows_v1(project_root=root, index_path=path)
            if build_sizing_projection(rows) != value['sizing_projection']:
                raise S3CapacityError('S3 capacity no longer matches physical Q4 sizing')
        except S3CapacityError:
            raise
        except Exception:
            raise S3CapacityError('S3 original Q4 sizing evidence is unavailable or invalid') from None
    return value
