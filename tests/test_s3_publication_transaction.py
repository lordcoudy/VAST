from __future__ import annotations
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
from publication_cloud_transaction import PublicationCloudTransaction, verify_cloud_ledger, LedgerIntegrityError, _entry_hash
from s3_artifact_store import S3ArtifactStore
from s3_destination import S3Destination
from tests.test_s3_artifact_store import FakeS3
from tests.test_publication_cloud_transaction import prepare_pair, MATRIX_SHA256, SimulatedCrash


class S3TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client = FakeS3()
        destination = S3Destination.from_file(Path(__file__).parents[1] / 'configs/artifact-storage.yaml')
        self.store = S3ArtifactStore(destination, client=self.client, intent_root=self.root/'s3_intents')
        self.store.bind_run(MATRIX_SHA256, 'full-run-001')
        self.pair, self.acceptance = prepare_pair(self.root)

    def tearDown(self):
        self.temp.cleanup()

    def commit(self, **kwargs):
        return PublicationCloudTransaction(store=self.store, run_root=self.root, **kwargs).commit_pair(
            pair_dir=self.pair, acceptance_manifest=self.acceptance, matrix_sha256=MATRIX_SHA256,
            run_id='full-run-001', pair_sequence=1, pair_id='pair-0001')

    def test_s3_ledger_receipt_and_restore(self):
        result = self.commit()
        ledger = verify_cloud_ledger(self.root/'cloud_ledger.jsonl')
        self.assertEqual(ledger[-1]['schema_version'], 'vast-s3-cloud-ledger/v1')
        self.assertEqual(ledger[-1]['storage_binding'], self.store.storage_binding)
        self.assertEqual(ledger[-1]['archive_object']['version_id'], 'v1')
        self.assertFalse(self.pair.exists())
        receipt = json.loads(self.client.objects[self.store.prefix+result['receipt_remote_name']])
        self.assertEqual(receipt['schema_version'], 'vast-s3-cloud-pair-receipt/v1')
        self.assertEqual(receipt['archive']['object'], ledger[-1]['archive_object'])
        restored = PublicationCloudTransaction(store=self.store, run_root=self.root).materialize_pair(
            pair_sequence=1, pair_id='pair-0001', destination_root=self.root/'restored')
        self.assertTrue((self.root/'restored'/self.pair.name/self.acceptance.name).is_file())

    def test_unknown_keys_and_mixed_backend_fail_closed(self):
        self.commit()
        path = self.root/'cloud_ledger.jsonl'
        rows = verify_cloud_ledger(path)
        rows[0]['unknown'] = 'foreign'
        unsigned = {k:v for k,v in rows[0].items() if k != 'entry_sha256'}
        rows[0]['entry_sha256'] = _entry_hash(unsigned)
        path.write_text(json.dumps(rows[0])+'\n')
        with self.assertRaises(LedgerIntegrityError):
            verify_cloud_ledger(path)

    def test_checkpoint_backend_change_is_rejected(self):
        self.commit()
        from tests.test_publication_cloud_transaction import FakeStore
        with self.assertRaises(LedgerIntegrityError):
            PublicationCloudTransaction(store=FakeStore(), run_root=self.root)._load_entries()

    def test_crash_keeps_raw_and_recovers_without_measurement(self):
        def crash(state):
            if state == 'remote_archive_verified':
                raise SimulatedCrash()
        with self.assertRaises(SimulatedCrash):
            self.commit(transition_hook=crash)
        self.assertTrue(self.pair.exists())
        self.commit()
        self.assertFalse(self.pair.exists())
        self.assertEqual(len(self.client.objects), 2)


if __name__ == '__main__':
    unittest.main()
