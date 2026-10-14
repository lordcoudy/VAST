from __future__ import annotations
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from artifact_store import ArtifactPermanentError
from s3_credentials import resolve_credentials
from s3_artifact_store import S3ArtifactStore
from s3_destination import S3Destination


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.root.chmod(0o700)
        self.path = self.root/'credentials.ini'
        self.path.write_text('[vast-s3]\naws_access_key_id=vast\naws_secret_access_key=test-secret\n')
        self.path.chmod(0o600)

    def tearDown(self):
        self.temp.cleanup()

    def test_explicit_profile_and_repr_hide_values(self):
        with patch.dict(os.environ, {'AWS_ACCESS_KEY_ID':'ambient','AWS_SECRET_ACCESS_KEY':'ambient',
                                    'AWS_PROFILE':'foreign','AWS_ENDPOINT_URL':'http://foreign'}, clear=True):
            credentials = resolve_credentials(self.path)
        self.assertEqual(credentials.access_key, 'vast')
        self.assertEqual(credentials.secret_key, 'test-secret')
        self.assertNotIn('test-secret', repr(credentials))

    def test_private_unique_physical_source_is_mandatory(self):
        for mode in (0o644,0o777):
            self.path.chmod(mode)
            with self.assertRaises(ArtifactPermanentError):
                resolve_credentials(self.path)
        self.path.chmod(0o600)
        os.link(self.path, self.root/'alias')
        with self.assertRaises(ArtifactPermanentError):
            resolve_credentials(self.path)

    def test_sdk_api_and_config_have_one_attempt_and_fixed_endpoint(self):
        destination = S3Destination.from_file(Path(__file__).parents[1]/'configs/artifact-storage.yaml')
        with patch.dict(os.environ, {'AWS_ACCESS_KEY_ID':'ambient','AWS_SECRET_ACCESS_KEY':'ambient',
                    'AWS_ENDPOINT_URL':'http://foreign','AWS_MAX_ATTEMPTS':'99'}, clear=True):
            store = S3ArtifactStore(destination, credentials_file=self.path, intent_root=self.root/'intents')
        self.assertEqual(store.client.meta.endpoint_url, destination.endpoint)
        self.assertEqual(store.client.meta.config.retries['total_max_attempts'], 1)
        self.assertEqual(store.client.meta.config.s3['addressing_style'], 'path')
        self.assertEqual(store.client._request_signer._credentials.access_key, 'vast')
        self.assertEqual(store.credential_source, {'path':str(self.path),'profile':'vast-s3',
                                                'principal':'vast','user_uid':os.getuid()})
        self.assertNotIn('test-secret',str(store.credential_source))
        for operation in ('PutObject','CompleteMultipartUpload'):
            self.assertIn('IfNoneMatch', store.client.meta.service_model.operation_model(operation).input_shape.members)


if __name__ == '__main__':
    unittest.main()
