from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
from s3_operator_preflight import run_smoke, build_parser
from s3_artifact_store import S3ArtifactStore
from s3_destination import S3Destination
from s3_capacity_attestation import validate_preflight
from tests.test_s3_artifact_store import FakeS3


class OperatorTests(unittest.TestCase):
    def test_bounded_smoke_keeps_existing_bytes_and_owned_namespace(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = S3Destination.from_file(Path(__file__).parents[1]/'configs/artifact-storage.yaml')
            client = FakeS3()
            client.objects['unrelated'] = b'preserved'
            store = S3ArtifactStore(destination, client=client, intent_root=Path(temp)/'intents')
            store.bind_probe('a'*32)
            report = run_smoke(store, work_root=Path(temp))
            self.assertEqual(report['status'],'write_ready')
            self.assertEqual(report['object_count'],2)
            self.assertLessEqual(report['verification']['uploaded_bytes'],64*1024**2)
            self.assertLessEqual(report['verification']['readback_bytes'],64*1024**2)
            self.assertTrue(all(report['verification']['checks'].values()))
            self.assertEqual(client.objects['unrelated'],b'preserved')
            validate_preflight(report,destination=destination,now_utc=report['observed_at_utc'])
            self.assertFalse(client.uploads)

    def test_cli_exposes_no_bucket_or_workload_mutations(self):
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(['delete-bucket'])
        with self.assertRaises(SystemExit):
            parser.parse_args(['run-benchmark'])


if __name__ == '__main__':
    unittest.main()
