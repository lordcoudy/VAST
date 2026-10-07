"""Current bounded S3 adapter source binding, shared by probes and admission."""
import hashlib
from pathlib import Path
from s3_destination import canonical_bytes, read_physical_bytes

SOURCE_FILES = ('artifact_store.py','s3_artifact_store.py','s3_credentials.py','s3_destination.py',
                's3_publication_evidence.py','s3_capacity_attestation.py','s3_operator_preflight.py',
                's3_source_identity.py','publication_cloud_environment.py','publication_physical_io_v1.py')

def source_sha256():
    return hashlib.sha256(canonical_bytes({name:hashlib.sha256(read_physical_bytes(
        Path(__file__).parent/name, maximum=1024*1024)).hexdigest() for name in SOURCE_FILES})).hexdigest()
