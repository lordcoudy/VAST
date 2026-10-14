"""Allow Seafile selection only for a physically verified historical run."""
import json
from pathlib import Path
from benchmark_contract import ContractError
from full_publication_runner import FullPublicationRunner
from publication_physical_io_v1 import PhysicalRootCustodyV1, PublicationPhysicalIoV1Error

def require_historical_seafile_context(run_root):
    try:
        with PhysicalRootCustodyV1.open(Path(run_root), label='historical Seafile run') as custody:
            values = []
            for name in ('run_manifest.json','checkpoint.json'):
                _, raw = custody.read_descriptor(name, label='historical Seafile state', maximum=32*1024**2, capture=True)
                values.append(json.loads(raw))
            manifest, checkpoint = values
            identity = manifest['identity_inputs']
            destination = identity['cloud_destination']
            fields = {'schema_version','transport','same_origin_capability_pair','origin_sha256',
                      'destination_id_sha256','destination_sha256'}
            if (type(destination) is not dict or set(destination) != fields or 's3_storage' in identity
                    or 's3_capacity_attestation' in identity or destination['schema_version'] != 1
                    or destination['transport'] != 'https' or destination['same_origin_capability_pair'] is not True):
                raise ContractError('historical Seafile storage binding is invalid')
            reader = FullPublicationRunner(run_root, config={}, identity_inputs=identity,
                                           matrix_builder=lambda _config:manifest['matrix'])
            reader._validate_manifest(manifest, candidate=reader._candidate_manifest())
            reader._validate_checkpoint(checkpoint, manifest)
            custody.verify()
    except (PublicationPhysicalIoV1Error, OSError, ValueError, KeyError, TypeError):
        raise ContractError('Seafile requires an existing verified historical run; new runs use S3') from None
    return manifest
