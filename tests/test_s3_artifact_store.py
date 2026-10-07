from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from botocore.exceptions import ClientError, EndpointConnectionError
from artifact_store import ArtifactIntegrityError, ArtifactPermanentError, ArtifactStoreError
from s3_destination import S3Destination
from s3_artifact_store import S3ArtifactStore, HeldFileRange


def failure(code, status):
    return ClientError({'Error': {'Code': code, 'Message': 'SECRET signed-url'},
                        'ResponseMetadata': {'HTTPStatusCode': status}}, 'test')


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.uploads = {}
        self.calls = []
        self.pages = None
        self.race = None
        self.complete_error = None

    def head_bucket(self, **args):
        return {}

    def list_objects_v2(self, **args):
        self.calls.append(('list', args))
        if self.pages is not None:
            return self.pages.pop(0)
        return {'IsTruncated': False, 'Contents': [
            {'Key': key, 'Size': len(body)} for key, body in self.objects.items()
            if key.startswith(args['Prefix'])]}

    def head_object(self, **args):
        if args['Key'] not in self.objects:
            raise failure('NoSuchKey', 404)
        return {'ContentLength': len(self.objects[args['Key']]), 'ETag': '"stable"',
                'VersionId': 'v1'}

    def get_object(self, **args):
        self.calls.append(('get', args))
        return {**self.head_object(**args), 'Body': io.BytesIO(self.objects[args['Key']])}

    def put_object(self, **args):
        self.calls.append(('put', {k: v for k, v in args.items() if k != 'Body'}))
        assert args['IfNoneMatch'] == '*'
        if self.race:
            self.objects[args['Key']] = self.race
        if args['Key'] in self.objects:
            raise failure('PreconditionFailed', 412)
        chunks = []
        while piece := args['Body'].read(8192):
            chunks.append(piece)
        self.objects[args['Key']] = b''.join(chunks)
        return {'VersionId': 'v1'}

    def create_multipart_upload(self, **args):
        self.calls.append(('create', args))
        uid = str(len(self.calls))
        self.uploads[uid] = {'key': args['Key'], 'parts': {}}
        return {'UploadId': uid}

    def upload_part(self, **args):
        self.calls.append(('part', {k: v for k, v in args.items() if k != 'Body'}))
        chunks = []
        while piece := args['Body'].read(8192):
            chunks.append(piece)
        self.uploads[args['UploadId']]['parts'][args['PartNumber']] = b''.join(chunks)
        return {'ETag': '"part%d"' % args['PartNumber']}

    def complete_multipart_upload(self, **args):
        self.calls.append(('complete', args))
        assert args['IfNoneMatch'] == '*'
        if self.complete_error:
            raise self.complete_error
        if self.race:
            self.objects[args['Key']] = self.race
        if args['Key'] in self.objects:
            raise failure('PreconditionFailed', 412)
        upload = self.uploads.pop(args['UploadId'])
        self.objects[args['Key']] = b''.join(upload['parts'][p['PartNumber']]
                                           for p in args['MultipartUpload']['Parts'])
        return {'VersionId': 'v1'}

    def abort_multipart_upload(self, **args):
        self.calls.append(('abort', args))
        self.uploads.pop(args['UploadId'], None)
        return {}


class S3StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.destination = S3Destination.from_file(Path(__file__).parents[1] / 'configs/artifact-storage.yaml')
        self.client = FakeS3()
        self.store = S3ArtifactStore(self.destination, client=self.client,
                                    intent_root=self.root / 'intents')
        self.store.bind_run('a' * 64, 'b' * 64)
        self.source = self.root / 'archive.bin'
        self.source.write_bytes(b'bounded payload')

    def tearDown(self):
        self.tmp.cleanup()

    def test_put_and_full_readback_with_version(self):
        result = self.store.upload_and_verify(self.source)
        self.assertEqual(result['sha256'], hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(result['object']['version_id'], 'v1')
        self.assertEqual(result['object']['key'], self.store.prefix + 'archive.bin')
        self.assertEqual(self.client.calls[-1][0], 'get')
        self.assertEqual(self.client.calls[-1][1]['VersionId'], 'v1')
        self.assertEqual(self.store.upload_and_verify(self.source)['status'], 'already_present_and_verified')

    def test_put_race_reuses_only_matching_bytes(self):
        self.client.race = self.source.read_bytes()
        self.store.upload_and_verify(self.source)
        self.client.objects.clear()
        self.client.race = b'foreign bytes'
        with self.assertRaises(ArtifactIntegrityError):
            self.store.upload_and_verify(self.source)
        self.assertEqual(self.client.objects[self.store.prefix + 'archive.bin'], b'foreign bytes')

    def test_multipart_same_fd_ranges_and_atomic_completion(self):
        self.store._multipart_threshold = 8
        self.store._part_size = 8
        self.store.upload_and_verify(self.source)
        self.assertEqual([c[1]['ContentLength'] for c in self.client.calls if c[0] == 'part'], [8, 7])
        self.assertFalse(list((self.root / 'intents').glob('*.json')))
        self.assertFalse(self.client.uploads)

    def test_multipart_collision_and_exact_owned_abort(self):
        self.store._multipart_threshold = self.store._part_size = 8
        self.client.uploads['foreign'] = {'key': 'foreign', 'parts': {}}
        self.client.race = b'foreign bytes'
        with self.assertRaises(ArtifactIntegrityError):
            self.store.upload_and_verify(self.source)
        self.assertEqual(set(self.client.uploads), {'foreign'})
        self.assertEqual(self.client.objects[self.store.prefix + 'archive.bin'], b'foreign bytes')

    def test_failed_completion_preserves_durable_intent_then_reconciles(self):
        self.store._multipart_threshold = self.store._part_size = 8
        self.client.complete_error = failure('ServiceUnavailable', 503)
        with self.assertRaises(ArtifactStoreError):
            self.store.upload_and_verify(self.source)
        self.assertEqual(len(list((self.root / 'intents').glob('*.json'))), 1)
        self.client.complete_error = None
        self.store.upload_and_verify(self.source)
        self.assertEqual(len([c for c in self.client.calls if c[0] == 'abort']), 1)

    def test_hostile_inventory(self):
        for pages in [
            [{'IsTruncated': False, 'Contents': [{'Key': 'foreign', 'Size': 1}]}],
            [{'IsTruncated': False, 'Contents': [{'Key': self.store.prefix+'x', 'Size': True}]}],
            [{'IsTruncated': True, 'NextContinuationToken': 'loop', 'Contents': []},
             {'IsTruncated': True, 'NextContinuationToken': 'loop', 'Contents': []}],
            [{'IsTruncated': False, 'Contents': [{'Key': self.store.prefix+'x', 'Size': 1}]*2}],
            [{'IsTruncated': True, 'Contents': []}],
        ]:
            with self.subTest(pages=pages):
                self.client.pages = pages
                with self.assertRaises(ArtifactPermanentError):
                    self.store.list_remote_files()

    def test_readback_rejects_etag_only_and_wrong_hash(self):
        self.client.objects[self.store.prefix+'archive.bin'] = b'wrong'
        with self.assertRaises(ArtifactIntegrityError):
            self.store.verify_remote('archive.bin', expected_sha256='a'*64, expected_size=5)

    def test_409_without_final_object_is_transient(self):
        self.client.put_object = lambda **args: (_ for _ in ()).throw(failure('ConditionalRequestConflict',409))
        with self.assertRaises(ArtifactStoreError) as captured:
            self.store.upload_and_verify(self.source)
        self.assertNotIsInstance(captured.exception, ArtifactIntegrityError)

    def test_ambiguous_completion_verifies_final_object_before_retry(self):
        self.store._multipart_threshold = self.store._part_size = 8
        complete = self.client.complete_multipart_upload
        def lost_response(**args):
            complete(**args)
            raise failure('ServiceUnavailable',503)
        self.client.complete_multipart_upload = lost_response
        result = self.store.upload_and_verify(self.source)
        self.assertEqual(result['sha256'],hashlib.sha256(self.source.read_bytes()).hexdigest())
        self.assertEqual(len([c for c in self.client.calls if c[0]=='create']),1)
        self.assertFalse(list((self.root/'intents').glob('*.json')))

    def test_http_200_embedded_error_never_becomes_verified(self):
        self.store._multipart_threshold = self.store._part_size = 8
        self.client.complete_multipart_upload = lambda **args: {'Error':{'Code':'InternalError','Message':'SECRET'}}
        with self.assertRaises(ArtifactPermanentError) as captured:
            self.store.upload_and_verify(self.source)
        self.assertNotIn('SECRET',str(captured.exception))
        self.assertFalse(self.client.objects)

    def test_expired_outer_deadline_is_never_reset(self):
        import time
        self.store.outer_deadline = time.monotonic()-1
        with self.assertRaises(ArtifactStoreError):
            with self.store.operation(time.monotonic()+120):
                self.store.preflight()
        self.assertFalse(self.client.calls)

    def test_materialize_is_no_replace_and_verified(self):
        result = self.store.upload_and_verify(self.source)
        target = self.root / 'restored.bin'
        self.store.materialize_remote('archive.bin', destination=target,
            expected_sha256=result['sha256'], expected_size=result['size_bytes'])
        self.assertEqual(target.read_bytes(), self.source.read_bytes())
        target.chmod(0o600)
        target.write_bytes(b'foreign')
        with self.assertRaises(ArtifactIntegrityError):
            self.store.materialize_remote('archive.bin', destination=target,
                expected_sha256=result['sha256'], expected_size=result['size_bytes'])
        self.assertEqual(target.read_bytes(), b'foreign')

    def test_error_sanitization_and_classification(self):
        for code, status, expected in [('AccessDenied',403,ArtifactPermanentError),
                                      ('Unknown',400,ArtifactPermanentError),
                                      ('SlowDown',503,ArtifactStoreError)]:
            def bad(**args):
                raise failure(code, status)
            self.client.head_bucket = bad
            with self.assertRaises(expected) as captured:
                self.store.preflight()
            self.assertNotIn('SECRET', str(captured.exception))

    def test_mutation_and_alias_fail_before_upload(self):
        self.store.upload_physical_fault = lambda stage, path: path.write_bytes(b'changed')
        with self.assertRaises(ArtifactIntegrityError):
            self.store.upload_and_verify(self.source)
        self.assertFalse(any(c[0] == 'put' for c in self.client.calls))
        self.store.upload_physical_fault = None
        os.link(self.source, self.root / 'alias')
        with self.assertRaises(ArtifactIntegrityError):
            self.store.upload_and_verify(self.source)

    def test_range_is_bounded_and_seekable(self):
        fd = os.open(self.source, os.O_RDONLY)
        try:
            stream = HeldFileRange(fd, 2, 4)
            self.assertEqual(stream.read(100), b'unde')
            self.assertEqual(stream.read(), b'')
            self.assertEqual(stream.seek(0), 0)
            self.assertEqual(stream.read(2), b'un')
            self.assertEqual(stream.seek(-1, 2), 3)
            self.assertEqual(stream.read(), b'e')
            with self.assertRaises(ArtifactPermanentError):
                stream.seek(5)
        finally:
            os.close(fd)

    def test_large_sparse_object_is_rejected_before_hash_or_network(self):
        with self.source.open('r+b') as source:
            source.truncate(64*1024**2*10000+1)
        with self.assertRaises(ArtifactPermanentError):
            self.store.upload_and_verify(self.source)
        self.assertFalse(self.client.calls)

    def test_crash_after_part_recovers_only_owned_upload(self):
        class Crash(BaseException):
            pass
        self.store._multipart_threshold = self.store._part_size = 8
        self.client.uploads['foreign'] = {'key':'foreign','parts':{}}
        self.store.multipart_fault = lambda *args: (_ for _ in ()).throw(Crash())
        with self.assertRaises(Crash):
            self.store.upload_and_verify(self.source)
        self.assertEqual(len(list((self.root/'intents').glob('*.json'))),1)
        self.store.multipart_fault = None
        self.store.upload_and_verify(self.source)
        self.assertEqual(set(self.client.uploads),{'foreign'})
        self.assertEqual(len([c for c in self.client.calls if c[0]=='abort']),1)

    def test_materialization_crash_resumes_and_foreign_stage_is_rejected(self):
        class Crash(BaseException):
            pass
        result = self.store.upload_and_verify(self.source)
        self.store.materialize_physical_fault = lambda stage,path: (_ for _ in ()).throw(Crash()) if stage=='mid_write' else None
        target = self.root/'restored.bin'
        with self.assertRaises(Crash):
            self.store.materialize_remote('archive.bin',destination=target,
                expected_sha256=result['sha256'],expected_size=result['size_bytes'])
        self.assertFalse(target.exists())
        stage = next((self.root/'.s3-materialization-v1').glob('*/payload.stage'))
        replacement = self.root/'foreign-stage'
        replacement.write_bytes(self.source.read_bytes())
        os.replace(replacement,stage)
        self.store.materialize_physical_fault = None
        with self.assertRaises(ArtifactIntegrityError):
            self.store.materialize_remote('archive.bin',destination=target,
                expected_sha256=result['sha256'],expected_size=result['size_bytes'])
        self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
