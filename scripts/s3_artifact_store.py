"""Bounded, immutable S3 export using the publication owner's held files."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import io
import json
import logging
import math
import os
from pathlib import Path
import re
import stat
import signal
import threading
import time
from typing import Any
from urllib.parse import urlsplit

from artifact_store import (
    ArtifactStoreError, ArtifactIntegrityError, ArtifactPermanentError,
    upload_and_verify as physical_upload, materialize_remote as physical_materialize,
    _hash_open_file, _regular_file_snapshot, _rename_noreplace_at,
)
from publication_physical_io_v1 import PhysicalRootCustodyV1, PublicationPhysicalIoV1Error
from s3_credentials import default_credentials_path, resolve_credentials
from s3_destination import S3Destination, S3ConfigurationError, canonical_bytes, validate_remote_name

_CHUNK = 8 * 1024 * 1024
_PART = 64 * 1024 * 1024
_INTENT_LIMIT = 2 * 1024 * 1024
_HEX = re.compile(r'[0-9a-f]{64}')


class S3TransportError(ArtifactStoreError):
    """Allowlisted transient S3 failure. Its text contains no server material."""


class HeldFileRange(io.RawIOBase):
    """Seekable bounded view of the same FD; SDK cannot reopen or buffer a part."""
    def __init__(self, descriptor: int, start: int, length: int, *, check=None):
        self.descriptor, self.start, self.length, self.position = descriptor, start, length, 0
        self.check = check or (lambda: None)

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.check()
        base = {0: 0, 1: self.position, 2: self.length}.get(whence)
        if base is None or type(offset) is not int or not 0 <= base + offset <= self.length:
            raise ArtifactPermanentError('S3 held range seek is outside its bound')
        self.position = base + offset
        return self.position

    def read(self, size=-1):
        self.check()
        amount = min(self.length - self.position, _CHUNK, size if size >= 0 else _CHUNK)
        data = os.pread(self.descriptor, amount, self.start + self.position)
        self.check()
        if amount and not data:
            raise ArtifactIntegrityError('S3 held upload source became short')
        self.position += len(data)
        return data


class S3ArtifactStore:
    backend = 's3'

    def __init__(self, destination: S3Destination, *, credentials_file: Path | None = None,
                 intent_root: Path, timeout_s: float = 120, client=None,
                 upload_physical_fault=None, materialize_physical_fault=None,
                 multipart_fault=None, outer_deadline=None):
        if not isinstance(destination, S3Destination) or not 0 < timeout_s <= 120:
            raise ArtifactPermanentError('S3 destination or timeout is invalid')
        self.destination = destination
        self.intent_root = Path(os.path.abspath(os.fspath(intent_root)))
        self.timeout_s, self.outer_deadline = float(timeout_s), outer_deadline
        self.chunk_size = _CHUNK
        self.upload_physical_fault = upload_physical_fault
        self.materialize_physical_fault = materialize_physical_fault
        self.multipart_fault = multipart_fault
        self._multipart_threshold = self._part_size = _PART
        self._deadline = None
        self._sent = 0
        self._transport_expired = False
        self._expected_versions = {}
        self._verified = {}
        self.uploaded_bytes = self.readback_bytes = 0
        self.probe_payload_limit = None
        self.prefix = None
        self.matrix_sha256 = self.run_id = None
        self.credential_source = None
        if client is None:
            from botocore.config import Config
            from botocore.session import Session
            source = Path(os.path.abspath(os.fspath(credentials_file or default_credentials_path())))
            credentials = resolve_credentials(source,
                                              profile=destination.credential_profile)
            self.credential_source = {'path':str(source), 'profile':destination.credential_profile,
                                      'principal':'vast', 'user_uid':os.getuid()}
            for name in ['botocore', 'urllib3'] + list(logging.Logger.manager.loggerDict):
                if name == 'urllib3' or name.startswith(('botocore', 'urllib3.')):
                    logger = logging.getLogger(name)
                    logger.setLevel(logging.CRITICAL + 1)
                    logger.propagate = False
            session = Session()
            session.set_credentials(credentials.access_key, credentials.secret_key, credentials.token)
            # Explicit endpoint/config/credentials prevent env, profile and IMDS fallback.
            self.client = session.create_client('s3', endpoint_url=destination.endpoint,
                region_name=destination.region, verify=True,
                config=Config(signature_version='s3v4', connect_timeout=min(10, timeout_s),
                    read_timeout=timeout_s, retries={'total_max_attempts': 1, 'mode': 'standard'},
                    s3={'addressing_style': 'path'},
                    request_checksum_calculation='when_required',
                    response_checksum_validation='when_required'))
            self.client.meta.events.register('before-send.s3', self._before_send)
            # SDK region correction is a retry too: remove it from this pinned client.
            emitter = self.client.meta.events._emitter
            for handler in list(emitter._handlers.prefix_search('needs-retry.s3')):
                if type(getattr(handler, '__self__', None)).__name__ in {'S3RegionRedirector', 'S3RegionRedirectorv2'}:
                    self.client.meta.events.unregister('needs-retry.s3', handler=handler)
            for operation in ('PutObject', 'CompleteMultipartUpload'):
                if 'IfNoneMatch' not in self.client.meta.service_model.operation_model(operation).input_shape.members:
                    raise ArtifactPermanentError('S3 SDK lacks atomic conditional creation')
        else:
            self.client = client

    def bind_run(self, matrix_sha256: str, run_id: str):
        prefix = self.destination.run_prefix(matrix_sha256, run_id)
        if self.prefix is not None and self.prefix != prefix:
            raise ArtifactPermanentError('S3 run namespace cannot be rebound')
        self.prefix, self.matrix_sha256, self.run_id = prefix, matrix_sha256, run_id

    def bind_probe(self, probe_id: str):
        """Operator-only namespace; production factory never calls this method."""
        if self.prefix is not None or re.fullmatch(r'[0-9a-f]{32}', probe_id) is None:
            raise ArtifactPermanentError('S3 probe namespace is invalid')
        self.prefix = self.destination.prefix + 'preflight/' + probe_id + '/'

    @property
    def storage_binding(self):
        if self.prefix is None:
            raise ArtifactPermanentError('S3 namespace must be bound before storage operations')
        return {'backend': 's3', 'destination': self.destination.identity, 'run_prefix': self.prefix}

    def _key(self, name):
        self._validate_remote_name(name)
        return self.storage_binding['run_prefix'] + name

    @staticmethod
    def _validate_remote_name(name):
        try:
            validate_remote_name(name)
        except S3ConfigurationError:
            raise ArtifactPermanentError('S3 remote basename is invalid') from None

    @contextmanager
    def operation(self, deadline=None):
        owner = self._deadline is None
        if owner:
            inherited = self.outer_deadline() if callable(self.outer_deadline) else self.outer_deadline
            limits = [time.monotonic() + self.timeout_s]
            if inherited is not None:
                limits.append(inherited)
            if deadline is not None:
                limits.append(deadline)
            self._deadline = min(limits)
        elif deadline is not None:
            self._deadline = min(self._deadline, deadline)
        try:
            self._remaining()
            yield
            self._remaining()
        finally:
            if owner:
                self._deadline = None

    def _remaining(self):
        remaining = self.timeout_s if self._deadline is None else self._deadline - time.monotonic()
        if remaining <= 0:
            raise S3TransportError('S3 operation deadline expired')
        return min(self.timeout_s, remaining)

    def _check_deadline(self):
        self._remaining()

    @contextmanager
    def _transport_deadline(self):
        """Interrupt even a continuously progressing blocking SDK operation."""
        if (not hasattr(signal, 'setitimer') or threading.current_thread() is not threading.main_thread()
                or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0)):
            raise ArtifactPermanentError('S3 transport requires its synchronous isolated timer context')
        previous = signal.getsignal(signal.SIGALRM)
        self._transport_expired = False
        def expired(_signum, _frame):
            self._transport_expired = True
            raise S3TransportError('S3 operation deadline expired')
        signal.signal(signal.SIGALRM, expired)
        try:
            signal.setitimer(signal.ITIMER_REAL, self._remaining())
            yield
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)

    def _validate_source_size(self, size):
        if size >= self._multipart_threshold and math.ceil(size/self._part_size) > 10000:
            raise ArtifactPermanentError('S3 object exceeds the fixed multipart part limit')

    def _before_send(self, request, **_kwargs):
        parsed, endpoint = urlsplit(request.url), urlsplit(self.destination.endpoint)
        if (parsed.scheme, parsed.netloc) != (endpoint.scheme, endpoint.netloc) or parsed.username or parsed.fragment:
            raise ArtifactPermanentError('S3 SDK attempted a foreign endpoint')
        self._sent += 1
        if self._sent > 1:
            raise ArtifactPermanentError('S3 SDK attempted an unexpected retry')
        self._remaining()

    @staticmethod
    def _error_status(error):
        response = getattr(error, 'response', {})
        status = response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        return status if type(status) is int else None

    def _call(self, operation, **kwargs):
        self._remaining()
        if operation in {'put_object','upload_part'}:
            amount = kwargs.get('ContentLength')
            if type(amount) is not int or amount < 0:
                raise ArtifactPermanentError('S3 upload length is invalid')
            if self.probe_payload_limit is not None and self.uploaded_bytes + amount > self.probe_payload_limit:
                raise ArtifactPermanentError('S3 operator upload budget exhausted')
            self.uploaded_bytes += amount
        self._sent = 0
        if hasattr(self.client, '_endpoint'):
            from urllib3.util import Timeout
            self.client._endpoint.http_session._timeout = Timeout(connect=min(10, self._remaining()), read=self._remaining())
        try:
            with self._transport_deadline():
                result = getattr(self.client, operation)(**kwargs)
            self._remaining()
            if type(result) is not dict or result.get('Error'):
                raise ArtifactPermanentError('S3 SDK returned an invalid operation result')
            return result
        except ArtifactStoreError:
            raise
        except Exception as error:
            if self._transport_expired:
                raise S3TransportError('S3 operation deadline expired') from None
            status = self._error_status(error)
            if status in {404, 409, 412}:
                # Internal control branch only; callers never expose SDK messages.
                raise _S3Status(status) from None
            from botocore.exceptions import (EndpointConnectionError, ConnectionClosedError,
                ConnectTimeoutError, ReadTimeoutError, IncompleteReadError, ResponseStreamingError)
            if status == 429 or (status is not None and 500 <= status <= 599) or isinstance(error, (
                    EndpointConnectionError, ConnectionClosedError, ConnectTimeoutError,
                    ReadTimeoutError, IncompleteReadError, ResponseStreamingError)):
                raise S3TransportError('S3 transport temporarily unavailable') from None
            raise ArtifactPermanentError('S3 operation rejected or unsupported') from None

    def list_remote_files(self):
        with self.operation():
            prefix = self.storage_binding['run_prefix']
            inventory, tokens, token, encoded = {}, set(), None, 0
            while True:
                args = {'Bucket': self.destination.bucket, 'Prefix': prefix, 'MaxKeys': 1000}
                if token is not None:
                    args['ContinuationToken'] = token
                try:
                    page = self._call('list_objects_v2', **args)
                except _S3Status:
                    raise ArtifactPermanentError('S3 run listing was rejected') from None
                rows, truncated = page.get('Contents', []), page.get('IsTruncated')
                if type(rows) is not list or len(rows) > 1000 or type(truncated) is not bool:
                    raise ArtifactPermanentError('S3 listing page is invalid')
                for row in rows:
                    if type(row) is not dict or type(row.get('Key')) is not str:
                        raise ArtifactPermanentError('S3 listing object is invalid')
                    key, size = row['Key'], row.get('Size')
                    if not key.startswith(prefix) or type(size) is not int or size < 0:
                        raise ArtifactPermanentError('S3 listing contains a foreign or invalid object')
                    name = key[len(prefix):]
                    self._validate_remote_name(name)
                    if name in inventory:
                        raise ArtifactPermanentError('S3 listing contains duplicate objects')
                    inventory[name] = {'name': name, 'key': key, 'size': size}
                    encoded += len(canonical_bytes(inventory[name])) + 1
                    if len(inventory) > 10000 or encoded > 16 * 1024 * 1024:
                        raise ArtifactPermanentError('S3 listing exceeds its bound')
                if not truncated:
                    if page.get('NextContinuationToken') is not None:
                        raise ArtifactPermanentError('S3 terminal listing has a continuation token')
                    return inventory
                token = page.get('NextContinuationToken')
                if type(token) is not str or not token or len(token) > 16384 or token in tokens:
                    raise ArtifactPermanentError('S3 listing continuation is invalid')
                tokens.add(token)
                if len(tokens) > 10000:
                    raise ArtifactPermanentError('S3 listing page bound exceeded')

    def preflight(self, *, live_upload_readback=False):
        if live_upload_readback:
            raise ArtifactPermanentError('S3 live probes require the bounded operator helper')
        with self.operation():
            try:
                self._call('head_bucket', Bucket=self.destination.bucket)
            except _S3Status:
                raise ArtifactPermanentError('S3 selected bucket is unavailable') from None
            inventory = self.list_remote_files()
            result = {'artifact_kind': 'vast_s3_preflight_v1', 'schema_version': 1,
                    'status': 'read_only_ready', 'destination': self.destination.identity,
                    'run_prefix': self.prefix, 'observed_at_utc': datetime.now(timezone.utc).isoformat(),
                    'object_count': len(inventory), 'quota_visibility': 'not_exposed',
                    'write_verified': False, 'conditional_creation_verified': False, 'verification': None}
            result['sha256'] = hashlib.sha256(canonical_bytes(result)).hexdigest()
            return result

    def _head(self, name, version=None):
        args = {'Bucket': self.destination.bucket, 'Key': self._key(name)}
        if version is not None:
            args['VersionId'] = version
        response = self._call('head_object', **args)
        size, etag, observed_version = response.get('ContentLength'), response.get('ETag'), response.get('VersionId')
        if (type(size) is not int or size < 0 or type(etag) is not str or not etag or len(etag) > 1024
                or (observed_version is not None and (type(observed_version) is not str or not observed_version or len(observed_version) > 1024))
                or (version is not None and observed_version != version)):
            raise ArtifactIntegrityError('S3 object read identity is invalid')
        return {'size': size, 'etag': etag, 'version_id': observed_version}

    @contextmanager
    def _read_remote(self, name):
        with self.operation():
            try:
                identity = self._head(name, self._expected_versions.get(name))
                args = {'Bucket': self.destination.bucket, 'Key': self._key(name)}
                if identity['version_id'] is not None:
                    args['VersionId'] = identity['version_id']
                else:
                    args['IfMatch'] = identity['etag']
                response = self._call('get_object', **args)
                if response.get('ContentLength') != identity['size'] or response.get('ETag') != identity['etag'] or response.get('VersionId') != identity['version_id']:
                    raise ArtifactIntegrityError('S3 object changed before readback')
                body = response.get('Body')
                if body is None:
                    raise ArtifactIntegrityError('S3 GET lacks a streamed body')
                reader = _BoundedBody(body, identity['size'], self)
                try:
                    yield reader
                    if reader.observed != identity['size']:
                        raise S3TransportError('S3 streamed body ended before its declared size')
                    if self._head(name, identity['version_id']) != identity:
                        raise ArtifactIntegrityError('S3 object changed during readback')
                    self._verified[name] = identity
                finally:
                    body.close()
            except _S3Status:
                raise ArtifactIntegrityError('S3 object is absent or changed') from None

    def verify_remote(self, name, *, expected_sha256, expected_size, expected_version_id=None):
        if type(expected_sha256) is not str or not _HEX.fullmatch(expected_sha256) or type(expected_size) is not int or expected_size < 0:
            raise ArtifactIntegrityError('S3 expected object digest or size is invalid')
        with self.operation():
            self._expected_versions[name] = expected_version_id
            digest, size = hashlib.sha256(), 0
            with self._read_remote(name) as reader:
                while chunk := reader.read(self.chunk_size):
                    digest.update(chunk)
                    size += len(chunk)
                    if size > expected_size:
                        raise ArtifactIntegrityError('S3 readback exceeds the expected size')
            if size != expected_size or digest.hexdigest() != expected_sha256:
                raise ArtifactIntegrityError('S3 full readback digest or size mismatch')
            descriptor = {'key': self._key(name), 'size_bytes': size, 'sha256': digest.hexdigest(),
                          'version_id': self._verified[name]['version_id']}
            return {'status': 'verified', 'remote_name': name, 'size_bytes': size,
                    'sha256': digest.hexdigest(), 'object': descriptor,
                    'storage_binding': self.storage_binding}

    def materialization_binding(self, name):
        return {**self.storage_binding, 'key': self._key(name),
                'version_id': self._expected_versions.get(name)}

    def read_verified_bytes(self, name, *, expected_sha256, expected_size,
                            expected_version_id=None, maximum=1024*1024):
        if type(expected_size) is not int or not 0 <= expected_size <= maximum:
            raise ArtifactIntegrityError('S3 verified bytes exceed the validation bound')
        if type(expected_sha256) is not str or not _HEX.fullmatch(expected_sha256):
            raise ArtifactIntegrityError('S3 expected verified-byte digest is invalid')
        with self.operation():
            self._expected_versions[name] = expected_version_id
            payload = bytearray()
            with self._read_remote(name) as reader:
                while chunk := reader.read(min(self.chunk_size, maximum+1-len(payload))):
                    payload.extend(chunk)
                    if len(payload) > expected_size:
                        raise ArtifactIntegrityError('S3 verified bytes exceed the expected size')
            if len(payload) != expected_size or hashlib.sha256(payload).hexdigest() != expected_sha256:
                raise ArtifactIntegrityError('S3 verified-byte digest or size mismatch')
            return bytes(payload)

    def materialize_remote(self, name, *, destination, expected_sha256, expected_size,
                           expected_version_id=None):
        with self.operation():
            self._expected_versions[name] = expected_version_id
            return physical_materialize(self, name, destination=destination,
                expected_sha256=expected_sha256, expected_size=expected_size,
                journal_root='.s3-materialization-v1', intent_kind='vast-s3-materialization-intent/v1',
                rename_noreplace=_rename_noreplace_at)

    def upload_and_verify(self, local_path, *, remote_name=None):
        with self.operation():
            try:
                result = physical_upload(self, Path(local_path), remote_name=remote_name)
                self._cleanup_verified_intent(result['remote_name'], result['sha256'], result['size_bytes'])
                return result
            except S3TransportError:
                raise
            except ArtifactIntegrityError:
                raise
            except (ArtifactStoreError, PublicationPhysicalIoV1Error, OSError):
                raise ArtifactIntegrityError('S3 local upload custody failed') from None

    def probe_conditional_create(self, local_path, *, remote_name):
        if self.matrix_sha256 is not None or self.prefix is None or not self.prefix.startswith(self.destination.prefix+'preflight/'):
            raise ArtifactPermanentError('S3 forced conditional creation is restricted to owned probes')
        with self.operation():
            return physical_upload(self, Path(local_path), remote_name=remote_name, check_existing=False)

    @contextmanager
    def _intent_custody(self):
        import fcntl
        self.intent_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.intent_root.resolve(strict=True) != self.intent_root:
            raise ArtifactIntegrityError('S3 multipart journal is redirected')
        root_info = self.intent_root.stat()
        if root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700:
            raise ArtifactIntegrityError('S3 multipart journal is not private to its owner')
        with PhysicalRootCustodyV1.open(self.intent_root, label='S3 multipart journal') as custody:
            lock = self.intent_root / '.lock'
            fd = os.open(lock, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
            try:
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.getuid():
                    raise ArtifactIntegrityError('S3 multipart journal lock is unsafe')
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise S3TransportError('S3 multipart journal is already owned') from None
                yield custody
                if (lock.lstat().st_dev, lock.lstat().st_ino) != (info.st_dev, info.st_ino):
                    raise ArtifactIntegrityError('S3 multipart journal lock changed')
            finally:
                os.close(fd)

    def _intent_name(self, name, digest, size):
        return hashlib.sha256(canonical_bytes({'storage': self.storage_binding, 'key': self._key(name),
                                              'sha256': digest, 'size': size})).hexdigest() + '.json'

    def _read_intent(self, custody, leaf):
        _descriptor, raw, identity = custody.read_descriptor_identity(leaf, maximum=_INTENT_LIMIT,
                                                   capture=True, label='S3 multipart intent')
        try:
            value = json.loads(raw)
            if (type(value) is not dict or set(value) != {'artifact_kind','storage_binding','key','sha256','size_bytes','source_epoch','upload_id','parts'}
                    or value['artifact_kind'] != 'vast_s3_multipart_intent_v1'
                    or value['storage_binding'] != self.storage_binding
                    or type(value['key']) is not str or not value['key'].startswith(self.prefix)
                    or not _HEX.fullmatch(value['sha256']) or type(value['size_bytes']) is not int or value['size_bytes'] < 0
                    or type(value['source_epoch']) is not list or len(value['source_epoch']) != 11
                    or any(type(x) is not int for x in value['source_epoch'])
                    or (value['upload_id'] is not None and (type(value['upload_id']) is not str or not value['upload_id'] or len(value['upload_id']) > 4096))
                    or type(value['parts']) is not list or len(value['parts']) > 10000):
                raise ValueError
            self._validate_remote_name(value['key'][len(self.prefix):])
            for number, part in enumerate(value['parts'], 1):
                if (type(part) is not dict or set(part) != {'PartNumber','ETag'} or part['PartNumber'] != number
                        or type(part['ETag']) is not str or not part['ETag'] or len(part['ETag']) > 1024):
                    raise ValueError
            return value, identity
        except (TypeError, ValueError, KeyError):
            raise ArtifactIntegrityError('S3 multipart intent is invalid') from None

    def _persist(self, custody, leaf, value):
        payload = canonical_bytes(value) + b'\n'
        if len(payload) > _INTENT_LIMIT:
            raise ArtifactIntegrityError('S3 multipart intent exceeds its bound')
        custody.replace_atomic(leaf, payload, label='S3 multipart intent', mode=0o600)

    def _remove_intent(self, custody, leaf):
        _value, identity = self._read_intent(custody, leaf)
        custody.unlink_owned_identity(leaf, identity, label='S3 multipart intent')

    def _abort(self, value):
        if value['upload_id'] is None:
            raise ArtifactPermanentError('S3 ambiguous upload creation has an unowned remote leftover')
        try:
            self._call('abort_multipart_upload', Bucket=self.destination.bucket, Key=value['key'], UploadId=value['upload_id'])
        except _S3Status as error:
            if error.status != 404:
                raise ArtifactPermanentError('S3 owned multipart cleanup was rejected') from None

    def _cleanup_verified_intent(self, name, digest, size):
        if not self.intent_root.exists():
            return
        leaf = self._intent_name(name, digest, size)
        with self._intent_custody() as custody:
            if (self.intent_root / leaf).exists():
                value, _identity = self._read_intent(custody, leaf)
                self._abort(value)
                self._remove_intent(custody, leaf)

    def _upload_held_file(self, local_path, name, *, source_fd, source_size):
        self._validate_source_size(source_size)
        size, digest = _hash_open_file(source_fd, chunk_size=self.chunk_size, check=self._check_deadline)
        if size != source_size:
            raise ArtifactIntegrityError('S3 held source size changed')
        key = self._key(name)
        if source_size < self._multipart_threshold:
            try:
                self._call('put_object', Bucket=self.destination.bucket, Key=key,
                    Body=HeldFileRange(source_fd, 0, source_size, check=self._check_deadline), ContentLength=source_size, IfNoneMatch='*')
            except (_S3Status, S3TransportError) as error:
                if isinstance(error, _S3Status) and error.status not in {409,412}:
                    raise ArtifactPermanentError('S3 conditional PUT was rejected') from None
                self._reconcile_write_error(name, digest, size, error)
            return
        count = math.ceil(source_size / self._part_size)
        if count > 10000:
            raise ArtifactPermanentError('S3 object exceeds the fixed multipart part limit')
        with self._intent_custody() as custody:
            leaves = []
            for item in self.intent_root.iterdir():
                self._check_deadline()
                if item.name == '.lock':
                    continue
                if len(leaves) >= 2 or re.fullmatch(r'[0-9a-f]{64}\.json', item.name) is None:
                    raise ArtifactIntegrityError('S3 multipart journal inventory is invalid')
                leaves.append(item.name)
            leaf = self._intent_name(name, digest, size)
            if leaf in leaves:
                previous, _identity = self._read_intent(custody, leaf)
                if previous['source_epoch'] != list(_regular_file_snapshot(os.fstat(source_fd))):
                    raise ArtifactIntegrityError('S3 multipart checkpoint source changed')
                try:
                    self._head(name)
                except _S3Status as error:
                    if error.status != 404:
                        raise ArtifactPermanentError('S3 checkpoint reconciliation was rejected') from None
                else:
                    self.verify_remote(name, expected_sha256=digest, expected_size=size)
                    self._abort(previous)
                    self._remove_intent(custody, leaf)
                    return
                self._abort(previous)
                self._remove_intent(custody, leaf)
                leaves.remove(leaf)
            if len(leaves) >= 2:
                raise ArtifactPermanentError('S3 active multipart intent limit reached')
            value = {'artifact_kind':'vast_s3_multipart_intent_v1', 'storage_binding':self.storage_binding,
                     'key':key, 'sha256':digest, 'size_bytes':size,
                     'source_epoch':list(_regular_file_snapshot(os.fstat(source_fd))), 'upload_id':None, 'parts':[]}
            self._persist(custody, leaf, value)
            phase = 'create'
            try:
                result = self._call('create_multipart_upload', Bucket=self.destination.bucket, Key=key)
                uid = result.get('UploadId')
                if type(uid) is not str or not uid or len(uid) > 4096:
                    raise ArtifactPermanentError('S3 multipart upload identity is invalid')
                value['upload_id'] = uid
                self._persist(custody, leaf, value)
                phase = 'parts'
                for number in range(1, count+1):
                    start = (number-1)*self._part_size
                    length = min(self._part_size, source_size-start)
                    part = self._call('upload_part', Bucket=self.destination.bucket, Key=key,
                        UploadId=uid, PartNumber=number, ContentLength=length,
                        Body=HeldFileRange(source_fd, start, length, check=self._check_deadline))
                    etag = part.get('ETag')
                    if type(etag) is not str or not etag or len(etag) > 1024:
                        raise ArtifactIntegrityError('S3 multipart part identity is invalid')
                    value['parts'].append({'PartNumber':number,'ETag':etag})
                    self._persist(custody, leaf, value)
                    if self.multipart_fault:
                        self.multipart_fault('part_durable', value)
                if list(_regular_file_snapshot(os.fstat(source_fd))) != value['source_epoch']:
                    raise ArtifactIntegrityError('S3 multipart source changed before completion')
                phase = 'complete'
                self._call('complete_multipart_upload', Bucket=self.destination.bucket, Key=key,
                    UploadId=uid, MultipartUpload={'Parts':value['parts']}, IfNoneMatch='*')
            except _S3Status as error:
                if error.status not in {409,412}:
                    raise ArtifactPermanentError('S3 conditional multipart completion was rejected') from None
                try:
                    self._reconcile_write_error(name, digest, size, error)
                finally:
                    self._abort(value)
                    self._remove_intent(custody, leaf)
                return
            except S3TransportError as error:
                # Keep exact owned checkpoint. Recovery verifies final bytes first.
                if phase == 'complete':
                    self._reconcile_write_error(name, digest, size, error)
                    self._abort(value)
                    self._remove_intent(custody, leaf)
                    return
                raise
            except ArtifactIntegrityError:
                if value['upload_id'] is not None:
                    self._abort(value)
                    self._remove_intent(custody, leaf)
                raise
            self.verify_remote(name, expected_sha256=digest, expected_size=size)
            self._remove_intent(custody, leaf)

    def _reconcile_write_error(self, name, digest, size, error):
        try:
            self._head(name)
        except _S3Status as missing:
            if missing.status != 404:
                raise ArtifactPermanentError('S3 final object reconciliation was rejected') from None
            if isinstance(error, _S3Status) and error.status == 412:
                raise ArtifactIntegrityError('S3 conditional conflict has no final object') from None
            raise S3TransportError('S3 final object is absent; owned checkpoint requires recovery') from None
        self.verify_remote(name, expected_sha256=digest, expected_size=size)


class _S3Status(Exception):
    def __init__(self, status):
        self.status = status


class _BoundedBody:
    def __init__(self, body, size, store):
        self.body, self.size, self.store, self.observed = body, size, store, 0

    def read(self, amount):
        remaining = self.store._remaining()
        try:
            # A complete HTTP ContentLength can release its socket before the
            # mandatory EOF read. That read still uses the absolute timer.
            if self.observed < self.size and hasattr(self.body, 'set_socket_timeout'):
                self.body.set_socket_timeout(remaining)
            with self.store._transport_deadline():
                chunk = self.body.read(min(amount, _CHUNK, max(1, self.size-self.observed+1)))
        except ArtifactStoreError:
            raise
        except Exception as error:
            if self.store._transport_expired:
                raise S3TransportError('S3 operation deadline expired') from None
            from botocore.exceptions import ReadTimeoutError, IncompleteReadError, ResponseStreamingError
            import http.client
            if isinstance(error, (OSError, http.client.IncompleteRead, ReadTimeoutError,
                                  IncompleteReadError, ResponseStreamingError)):
                raise S3TransportError('S3 streamed readback interrupted') from None
            raise ArtifactPermanentError('S3 streamed readback failed unexpectedly') from None
        self.store._remaining()
        if type(chunk) is not bytes:
            raise ArtifactIntegrityError('S3 streamed body is invalid')
        self.observed += len(chunk)
        self.store.readback_bytes += len(chunk)
        if self.store.probe_payload_limit is not None and self.store.readback_bytes > self.store.probe_payload_limit:
            raise ArtifactPermanentError('S3 operator readback budget exhausted')
        if self.observed > self.size:
            raise ArtifactIntegrityError('S3 streamed body exceeds its declared size')
        return chunk
