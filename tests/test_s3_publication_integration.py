from __future__ import annotations
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
import full_publication_wsl_user_service_v1 as service
from full_publication_entrypoint import build_parser, _default_command_runner
from s3_artifact_store import S3ArtifactStore
from s3_destination import S3Destination
from tests.test_s3_artifact_store import FakeS3
from tests import test_full_publication_runtime as runtime_fixtures
from tests.test_full_publication_wsl_user_service_v1 import Fixture


class S3IntegrationTests(unittest.TestCase):
    def test_entrypoint_accepts_s3_locators_and_probe_children_are_secret_free(self):
        args = build_parser().parse_args(['--cloud-config-file','configs/artifact-storage.yaml',
                                         '--s3-credentials-file','/private/credentials.ini','preflight'])
        self.assertIsNone(args.cloud_links_file)
        with patch.dict(os.environ, {'AWS_SECRET_ACCESS_KEY':'secret','AWS_PROFILE':'private'},clear=True), \
             patch('full_publication_entrypoint.subprocess.check_output',return_value='ok') as probe:
            _default_command_runner(['probe'])
        self.assertNotIn('AWS_SECRET_ACCESS_KEY', probe.call_args.kwargs['env'])
        self.assertNotIn('AWS_PROFILE', probe.call_args.kwargs['env'])

    def test_runtime_binds_run_before_s3_readonly_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            runtime = runtime_fixtures.FullPublicationRuntimeTests().make_runtime(root)
            destination = S3Destination.from_file(Path(__file__).parents[1]/'configs/artifact-storage.yaml')
            runtime.cloud_store = S3ArtifactStore(destination, client=FakeS3(), intent_root=root/'intents')
            context = runtime_fixtures.pair_context(root).run
            result = runtime.preflight(context)
            self.assertTrue(result.accepted, result)
            self.assertEqual(runtime.cloud_store.prefix, destination.run_prefix(context.matrix_identity['sha256'],context.run_identity['sha256']))

    def test_s3_service_manifest_has_no_seafile_or_secret_descriptor(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            fixture = Fixture(root/'repo', historical=False)
            config = fixture.root/'configs/artifact-storage.yaml'
            shutil.copyfile(Path(__file__).parents[1]/'configs/artifact-storage.yaml',config)
            private = root/'private'
            private.mkdir(mode=0o700)
            credentials = private/'credentials.ini'
            credentials.write_text('[vast-s3]\naws_access_key_id=vast\naws_secret_access_key=test-secret\n')
            credentials.chmod(0o600)
            result = fixture.materialize(cloud_links_file=None, cloud_destination_id=None,
                cloud_config_file=config, s3_credentials_file=credentials, user_uid=os.getuid())
            bundle = service.validate_bundle_v1(result['receipt_path'])
            self.assertEqual(bundle.manifest['schema_version'], 3)
            self.assertNotIn('cloud_links_file', bundle.manifest['sources'])
            self.assertNotIn('--cloud-links-file',bundle.manifest['entrypoint_args'])
            self.assertNotIn('test-secret',Path(result['manifest_path']).read_text())
            self.assertNotIn('sha256',bundle.manifest['cloud_storage']['credential_source'])
            credentials.chmod(0o644)
            with self.assertRaises(service.ServiceContractError):
                service.validate_bundle_v1(result['receipt_path'])

    def test_new_legacy_service_materialization_is_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temp:
            fixture = Fixture(Path(temp)/'repo', historical=False)
            with self.assertRaisesRegex(service.ServiceContractError, 'historical run'):
                fixture.materialize()
            self.assertFalse(fixture.output_dir.exists())


if __name__ == '__main__':
    unittest.main()
