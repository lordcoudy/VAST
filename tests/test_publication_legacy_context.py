import json
from pathlib import Path
import tempfile
import unittest
import sys
sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from full_publication_runner import FullPublicationRunner
from benchmark_contract import ContractError
from tests.test_full_publication_runner import small_matrix_factory

class LegacyContextTests(unittest.TestCase):
    def test_fresh_seafile_context_is_rejected_and_historical_hashes_are_checked(self):
        from publication_legacy_context import require_historical_seafile_context
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaises(ContractError):
                require_historical_seafile_context(root)
            identity = {'cloud_destination':{'schema_version':1,'transport':'https',
                'same_origin_capability_pair':True,'origin_sha256':'a'*64,
                'destination_id_sha256':'b'*64,'destination_sha256':'c'*64}}
            runner = FullPublicationRunner(root, config={}, identity_inputs=identity, matrix_builder=small_matrix_factory)
            runner._initialize_or_resume()
            require_historical_seafile_context(root)
            checkpoint = json.loads(runner.checkpoint_path.read_bytes())
            checkpoint['run_identity_sha256'] = 'f'*64
            runner.checkpoint_path.write_text(json.dumps(checkpoint))
            with self.assertRaises(ContractError):
                require_historical_seafile_context(root)
