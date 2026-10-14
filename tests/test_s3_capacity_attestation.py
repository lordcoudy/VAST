from __future__ import annotations
import copy
import hashlib
from pathlib import Path
import sys
import unittest
sys.path.insert(0, str(Path(__file__).parents[1]/'scripts'))
from s3_capacity_attestation import build_s3_capacity_attestation, validate_s3_capacity_attestation, S3CapacityError
from s3_destination import S3Destination, canonical_bytes
from s3_operator_preflight import source_sha256
from tests.test_seafile_capacity_attestation_v1 import rows


class S3CapacityTests(unittest.TestCase):
    def setUp(self):
        self.destination = S3Destination.from_file(Path(__file__).parents[1]/'configs/artifact-storage.yaml')
        self.now = '2026-10-07T12:00:00Z'
        self.preflight = {'artifact_kind':'vast_s3_preflight_v1','schema_version':1,'status':'write_ready',
            'destination':self.destination.identity,'run_prefix':'vast/preflight/'+'a'*32+'/',
            'observed_at_utc':self.now,'object_count':1,'quota_visibility':'not_exposed',
            'write_verified':True,'conditional_creation_verified':True,
            'verification':{'checks':{name:True for name in ('put','multipart','matching_reuse','put_collision',
                'multipart_collision','full_readback','restore')},
                'objects':[{'key':'vast/preflight/'+'a'*32+'/x','size_bytes':1,'sha256':'a'*64,'version_id':None}],
                'source_sha256':source_sha256(),'sdk_version':'1.43.62','python_version':'3.12.3',
                'elapsed_s':1.0,'uploaded_bytes':1,'readback_bytes':1,'leftover_uploads':[]}}
        self.preflight['sha256'] = hashlib.sha256(canonical_bytes(self.preflight)).hexdigest()

    def build(self, **kwargs):
        return build_s3_capacity_attestation(destination=self.destination, preflight=self.preflight,
            observed_pair_archives=rows(), sizing_source={'path':'artifacts/sizing/index.json','sha256':'c'*64,'size_bytes':1},
            source_identity={'source_sha256':source_sha256(),'sdk_version':'1.43.62'},
            operator_confirmation={'basis':'operator_explicit_guarantee',
                'available_capacity_lower_bound_bytes':500*1024**3,'confirmed_at_utc':self.now,
                'confirmation_reference':'operator-guarantee-20261007'}, observed_at_utc=self.now, **kwargs)

    def test_formula_and_destination_bindings(self):
        value = self.build()
        self.assertEqual(value['sizing_projection']['observed_cell_count'], 280)
        self.assertEqual(value['sizing_projection']['measurement_repeat_multiplier'], 10)
        self.assertEqual(validate_s3_capacity_attestation(value, destination=self.destination, now_utc=self.now), value)

    def test_missing_stale_foreign_and_tampered_guarantees_block(self):
        value = self.build()
        cases = []
        for field in ('destination','operator_capacity','preflight_observation'):
            candidate = copy.deepcopy(value)
            candidate.pop(field)
            cases.append(candidate)
        cases += [{**value, 'artifact_kind':'vast_seafile_operator_capacity_attestation_v2'},
                  {**value, 'operator_capacity':{**value['operator_capacity'],'confirmed_at_utc':'2026-10-01T12:00:00Z'}}]
        for candidate in cases:
            with self.assertRaises(S3CapacityError):
                validate_s3_capacity_attestation(candidate, destination=self.destination, now_utc=self.now)
        with self.assertRaises(S3CapacityError):
            validate_s3_capacity_attestation(value, destination=self.destination, now_utc='2026-10-09T12:00:00Z')

    def test_readonly_preflight_does_not_grant_cloud_capacity(self):
        self.preflight['write_verified'] = False
        self.preflight['sha256'] = hashlib.sha256(canonical_bytes({k:v for k,v in self.preflight.items() if k!='sha256'})).hexdigest()
        with self.assertRaises(S3CapacityError):
            self.build()

    def test_rehashed_capacity_cannot_substitute_or_outlive_adapter_source(self):
        value = self.build()
        for change_smoke_too in (False, True):
            candidate = copy.deepcopy(value)
            candidate['source_identity']['source_sha256'] = 'd'*64
            if change_smoke_too:
                preflight = candidate['preflight_observation']
                preflight['verification']['source_sha256'] = 'd'*64
                preflight['sha256'] = hashlib.sha256(canonical_bytes({k:v for k,v in preflight.items() if k!='sha256'})).hexdigest()
            candidate['sha256'] = hashlib.sha256(canonical_bytes({k:v for k,v in candidate.items() if k!='sha256'})).hexdigest()
            with self.assertRaises(S3CapacityError):
                validate_s3_capacity_attestation(candidate, destination=self.destination, now_utc=self.now)


if __name__ == '__main__':
    unittest.main()
