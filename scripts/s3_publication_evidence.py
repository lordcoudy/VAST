"""Exact S3 evidence schemas, separate from immutable legacy Seafile schemas."""
from __future__ import annotations
import re
from s3_destination import S3Destination, _EXPECTED


class S3EvidenceError(ValueError):
    pass


def validate_storage_binding(value, *, matrix_sha256, run_id):
    selected = S3Destination.from_mapping(dict(_EXPECTED))
    if (type(value) is not dict or set(value) != {'backend','destination','run_prefix'}
            or value['backend'] != 's3' or value['destination'] != selected.identity
            or value['run_prefix'] != selected.run_prefix(matrix_sha256, run_id)):
        raise S3EvidenceError('S3 storage binding drifted')


def validate_object(value, *, binding, remote_name, size, sha256):
    if (type(value) is not dict or set(value) != {'key','size_bytes','sha256','version_id'}
            or value['key'] != binding['run_prefix'] + remote_name
            or type(value['size_bytes']) is not int or value['size_bytes'] != size
            or value['sha256'] != sha256 or re.fullmatch(r'[0-9a-f]{64}', sha256) is None
            or (value['version_id'] is not None and (type(value['version_id']) is not str
                or not value['version_id'] or len(value['version_id']) > 1024))):
        raise S3EvidenceError('S3 verified object descriptor drifted')


def validate_ledger_entry(entry, states):
    index = states.get(entry.get('state'))
    if index is None:
        raise S3EvidenceError('S3 ledger state is invalid')
    fields = {'schema_version','entry_seq','previous_entry_sha256','entry_sha256','state',
              'matrix_sha256','run_id','pair_sequence','pair_id','pair_dir_name','pair_attempt',
              'pair_relative_path','acceptance_relative_path','acceptance_sha256',
              'acceptance_size_bytes','article_statistics_binding','storage_binding'}
    if index >= states['archive_ready']:
        fields |= {'local_archive_path','archive_remote_name','archive_sha256','archive_size_bytes',
                   'archive_member_count','archive_format'}
    if index >= states['remote_archive_verified']:
        fields.add('archive_object')
    if index >= states['remote_receipt_verified']:
        fields |= {'local_receipt_path','receipt_remote_name','receipt_sha256','receipt_size_bytes','receipt_object'}
    if index >= states['prune_started']:
        fields |= {'prune_tombstone_relative_path','prune_directory_identity'}
    if set(entry) != fields:
        raise S3EvidenceError('S3 ledger fields are invalid')
    validate_storage_binding(entry['storage_binding'], matrix_sha256=entry['matrix_sha256'], run_id=entry['run_id'])
    for category, minimum in [('archive', 'remote_archive_verified'),('receipt','remote_receipt_verified')]:
        if index >= states[minimum]:
            validate_object(entry[category+'_object'], binding=entry['storage_binding'],
                remote_name=entry[category+'_remote_name'], size=entry[category+'_size_bytes'],
                sha256=entry[category+'_sha256'])


def validate_pair_receipt(value, entry):
    if (type(value) is not dict or set(value) != {'schema_version','matrix_sha256','run_id',
            'pair_sequence','pair_id','pair_dir_name','acceptance','archive','remote_archive_status',
            'article_statistics','storage_binding'} or value['schema_version'] != 'vast-s3-cloud-pair-receipt/v1'):
        raise S3EvidenceError('S3 pair receipt schema is invalid')
    for field in ('matrix_sha256','run_id','pair_sequence','pair_id','pair_dir_name','storage_binding'):
        if value[field] != entry[field]:
            raise S3EvidenceError('S3 pair receipt identity drifted')
    if (value['acceptance'] != {'sha256':entry['acceptance_sha256'],'size_bytes':entry['acceptance_size_bytes']}
            or value['archive'] != {'remote_name':entry['archive_remote_name'],'sha256':entry['archive_sha256'],
                'size_bytes':entry['archive_size_bytes'],'member_count':entry['archive_member_count'],
                'format':entry['archive_format'],'object':entry['archive_object']}
            or value['remote_archive_status'] != 'verified' or value['article_statistics'] != entry['article_statistics_binding']):
        raise S3EvidenceError('S3 pair receipt evidence drifted')
