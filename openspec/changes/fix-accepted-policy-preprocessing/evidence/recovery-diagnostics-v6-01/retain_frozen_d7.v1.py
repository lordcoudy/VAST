"""Retain the frozen D7 diagnostic cohort once; no live/image authority."""
from pathlib import Path, PurePosixPath
import gzip
import hashlib
import io
import json
import os
import stat
import sys
import tarfile
from datetime import datetime, timezone

SOURCE = Path('E:/STUDY/VAST/tmp/completion-implementation-20261015/diagnostic-v6-01')
TARGET = Path('C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/recovery-diagnostics-v6-01')
CONTROLS = Path(__file__).resolve().parent
LIMIT = 16777216
SOURCE_BYTES = 13931754
SOURCE_FILES = 3810
RECEIPT_RESERVE = 65536
PINS = {
 'guest-outer-author-manifest.v2.json': 'b3157f62f113d0424b80599dde39f427dd9f07ffceac4165b4921e58910529a7',
 'independent-guest-outer-review.final.v1.md': 'a41beb6ace994c53cc786e5fd1ab916b51ff38ccc760f9f5e9cd05a0c90edcf2',
 'cold_restore_docker_archive_v6.py': '99e41f293e7bd0681b3e1843bdce0a528d3cb80ee4493378cc49843b53480fce',
 'Run-RecordedColdOperation.v6.ps1': '58d54248c610c243866e5084d00459c28e9b9d99bb30f968c6fc0113818414c8',
 'Run-ColdDockerRecovery.v6.ps1': '5b41a85c5ccc68c8a2f67684fa5ea9aa4248af9dd366ef79ee8fed5097f1ddac',
 'Native-ColdGuardian.v6.ps1': '7a04890c383bc50ca0d77ba4cdf99e284c64ffab2bc6ad74a0f08560cb8c5b2b',
}

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('utf-8')

def safe_info(path, directory=False):
    value = path.lstat()
    if path.is_symlink() or getattr(value, 'st_file_attributes', 0) & 1024:
        raise ValueError('Redirected path refused')
    if directory:
        if not stat.S_ISDIR(value.st_mode):
            raise ValueError('Non-directory ancestor refused')
    elif not stat.S_ISREG(value.st_mode) or value.st_nlink != 1:
        raise ValueError('Unsupported or multiply linked file refused')
    return value

def check_ancestors(path):
    for item in (path, *path.parents):
        safe_info(item, directory=True)

def snapshot():
    check_ancestors(SOURCE)
    directories = []
    members = []
    identities = {}
    for base, dirs, files in os.walk(SOURCE, followlinks=False):
        directory = Path(base)
        safe_info(directory, directory=True)
        directories.append(directory.relative_to(SOURCE).as_posix())
        for name in dirs:
            safe_info(directory / name, directory=True)
        for name in files:
            path = directory / name
            before = safe_info(path)
            raw = path.read_bytes()
            after = safe_info(path)
            identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            if identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or len(raw) != before.st_size:
                raise ValueError('Source changed during observation')
            relative = path.relative_to(SOURCE).as_posix()
            pure = PurePosixPath(relative)
            if pure.is_absolute() or '..' in pure.parts or '\\' in relative:
                raise ValueError('Unsafe source member name')
            members.append([relative, len(raw), sha(raw)])
            identities[relative] = identity
    members.sort(key=lambda row: row[0])
    directories.sort()
    if len(members) != SOURCE_FILES or sum(row[1] for row in members) != SOURCE_BYTES:
        raise ValueError('Unknown source tree writes or missing frozen member')
    lookup = {row[0]: row[2] for row in members}
    if len(lookup) != len(members) or any(lookup.get(name) != pin for name, pin in PINS.items()):
        raise ValueError('Frozen source pin mismatch')
    return members, directories, identities

class BudgetSink:
    def __init__(self, raw, budget):
        self.raw, self.budget, self.written = raw, budget, 0
    def write(self, data):
        if self.written + len(data) > self.budget:
            raise ValueError('Aggregate retention budget refused before write; partial artifact retained')
        amount = self.raw.write(data)
        self.written += amount
        return amount
    def flush(self):
        return self.raw.flush()
    def tell(self):
        return self.written


def main():
    if sys.argv[1:] != ['--retain-frozen-d7']:
        raise ValueError('Only the exact frozen retention action is supported')
    check_ancestors(CONTROLS)
    if sorted(p.name for p in CONTROLS.iterdir()) != [Path(__file__).name]:
        raise ValueError('Unknown retention control files')
    control_info = safe_info(Path(__file__))
    control_hash = sha(Path(__file__).read_bytes())
    if TARGET.exists():
        raise ValueError('Existing destination refused; no replay or overwrite')
    check_ancestors(TARGET.parent)
    before, directories, identities = snapshot()
    tree_hash = sha(canonical(before))
    directory_hash = sha(canonical(directories))
    catalog = {
      'kind': 'D7_frozen_regular_member_catalog.v1',
      'source_root': str(SOURCE), 'fixture': True, 'recovery_acceptance': False,
      'source_tree_sha256': tree_hash, 'source_directory_set_sha256': directory_hash,
      'source_files': len(before), 'source_directories': len(directories), 'source_bytes': SOURCE_BYTES,
      'zero_byte_members': sum(row[1] == 0 for row in before),
      'member_columns': ['original_relative_path', 'bytes', 'sha256'],
      'archive_member_paths': 'Exact original relative paths; all entries regular files; no path indirection.',
      'historical_disposition': 'All old candidates/failed runs are retained. Candidate8f and internal RED acceptance=true witnesses are historical BLOCK, never live authority.',
      'members': before,
    }
    catalog_raw = canonical(catalog) + b'\n'
    # Digest text and final receipt receive reserved space before archive writes.
    archive_budget = LIMIT - SOURCE_BYTES - control_info.st_size - len(catalog_raw) - 256 - RECEIPT_RESERVE
    if archive_budget <= 0:
        raise ValueError('No retention archive budget remains')
    TARGET.mkdir()
    catalog_path = TARGET / 'members.original.v1.json'
    archive_path = TARGET / 'diagnostic-cohort.original.v1.tar.gz'
    digest_path = TARGET / 'diagnostic-cohort.original.v1.tar.gz.sha256'
    receipt_path = TARGET / 'verification.original.v1.json'
    with catalog_path.open('xb') as stream:
        stream.write(catalog_raw)
    with archive_path.open('xb') as raw:
        sink = BudgetSink(raw, archive_budget)
        with gzip.GzipFile(filename='', mode='wb', fileobj=sink, mtime=0, compresslevel=9) as compressed:
            with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.PAX_FORMAT) as archive:
                for relative, length, expected in before:
                    path = SOURCE / relative
                    info = safe_info(path)
                    if (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns) != identities[relative]:
                        raise ValueError('Source identity drift before archive read')
                    data = path.read_bytes()
                    if len(data) != length or sha(data) != expected:
                        raise ValueError('Source bytes drift before archive add')
                    member = tarfile.TarInfo(relative)
                    member.type = tarfile.REGTYPE
                    member.size = length
                    member.mode = 0o600
                    member.uid = member.gid = 0
                    member.uname = member.gname = ''
                    member.mtime = 0
                    archive.addfile(member, io.BytesIO(data))
    archive_hash = sha(archive_path.read_bytes())
    digest_raw = (archive_hash + '  ' + archive_path.name + '\n').encode('ascii')
    if len(digest_raw) > 256:
        raise ValueError('Digest reservation exceeded')
    with digest_path.open('xb') as stream:
        stream.write(digest_raw)
    observed = []
    seen = set()
    with gzip.open(archive_path, "rb") as decoded:
        with tarfile.open(fileobj=decoded, mode='r|') as archive:
            for member in archive:
                pure = PurePosixPath(member.name)
                if member.type != tarfile.REGTYPE or pure.is_absolute() or '..' in pure.parts or '\\' in member.name or member.name in seen:
                    raise ValueError('Unsafe/nonregular/duplicate archive member')
                seen.add(member.name)
                value = archive.extractfile(member)
                if value is None:
                    raise ValueError('Archive member unavailable')
                digest = hashlib.sha256()
                count = 0
                with value:
                    while True:
                        block = value.read(65536)
                        if not block:
                            break
                        count += len(block)
                        if count > member.size:
                            raise ValueError('Archive member exceeded exact size')
                        digest.update(block)
                observed.append([member.name, count, digest.hexdigest()])
        # Drain the gzip footer to verify its CRC and uncompressed-size trailer.
        while decoded.read(65536):
            pass
    if observed != before:
        raise ValueError('Full archive member readback differs from frozen source')
    after, after_dirs, after_ids = snapshot()
    if after != before or after_dirs != directories or after_ids != identities:
        raise ValueError('Source changed during retention; artifact unaccepted')
    if sha(catalog_path.read_bytes()) != sha(catalog_raw):
        raise ValueError('Catalog changed during retention')
    receipt = {
      'kind': 'D7_retention_verification.v1', 'author': '/root/audit_s3_delivery',
      'recorded_utc': datetime.now(timezone.utc).isoformat(),
      'fixture': True, 'recovery_acceptance': False, 'successful': True,
      'archive_format_disposition': 'Root directed TAR.GZ instead of ZIP after ordinary full-path ZIP alone exceeded remaining allowance. Full original relative paths and every regular member are retained; no compact-ID indirection.',
      'source_root': str(SOURCE), 'target_root': str(TARGET),
      'source_tree_before_sha256': tree_hash, 'source_tree_after_sha256': sha(canonical(after)),
      'source_directory_set_before_sha256': directory_hash, 'source_directory_set_after_sha256': sha(canonical(after_dirs)),
      'source_file_identities_before_after_equal': True, 'source_before_after_equal': True,
      'full_archive_readback_equal': True, 'regular_member_count': len(observed),
      'zero_byte_member_count': sum(row[1] == 0 for row in observed),
      'originals_retained_in_place': True, 'no_intermediate_archive_or_copy': True,
      'historical_disposition': catalog['historical_disposition'],
      'artifacts': {
        archive_path.name: {'bytes': archive_path.stat().st_size, 'sha256': archive_hash},
        catalog_path.name: {'bytes': len(catalog_raw), 'sha256': sha(catalog_raw)},
        digest_path.name: {'bytes': len(digest_raw), 'sha256': sha(digest_raw)},
      },
      'control': {'path': str(Path(__file__)), 'bytes': control_info.st_size, 'sha256': control_hash},
      'review_report_sha256': PINS['independent-guest-outer-review.final.v1.md'],
      'accounting': {},
      'limits': '16MiB aggregate includes original frozen tree and every new archive/catalog/digest/receipt/control byte; no temporary archive or copy exists.',
      'scope': 'Reversible evidence retention only. No stage/CI/git mutation or backing/restore/image/capacity/package/qualification/final acceptance.',
    }
    other_added = control_info.st_size + archive_path.stat().st_size + len(catalog_raw) + len(digest_raw)
    receipt_size = 0
    for unused in range(20):
        added = other_added + receipt_size
        receipt['accounting'] = {'source_bytes': SOURCE_BYTES, 'control_bytes': control_info.st_size,
          'retention_directory_other_bytes': other_added-control_info.st_size, 'receipt_bytes': receipt_size,
          'added_bytes_including_control': added, 'aggregate_bytes': SOURCE_BYTES+added,
          'limit_bytes': LIMIT, 'residual_bytes': LIMIT-SOURCE_BYTES-added}
        payload = (json.dumps(receipt, sort_keys=True, indent=2) + '\n').encode()
        if len(payload) == receipt_size:
            break
        receipt_size = len(payload)
    else:
        raise ValueError('Receipt accounting did not converge')
    if receipt_size > RECEIPT_RESERVE or SOURCE_BYTES+other_added+receipt_size > LIMIT:
        raise ValueError('Aggregate budget exhausted; existing artifacts retained unaccepted')
    with receipt_path.open('xb') as stream:
        stream.write(payload)
    actual = SOURCE_BYTES + sum(p.stat().st_size for p in TARGET.iterdir()) + sum(p.stat().st_size for p in CONTROLS.iterdir())
    if actual != receipt['accounting']['aggregate_bytes'] or actual > LIMIT:
        raise ValueError('Actual aggregate accounting differs')
    print(json.dumps({'successful': True, 'receipt': str(receipt_path),
      'receipt_sha256': sha(receipt_path.read_bytes()), 'archive_sha256': archive_hash,
      'catalog_sha256': sha(catalog_raw), 'members': len(observed), 'empty_members': catalog['zero_byte_members'],
      'accounting': receipt['accounting'], 'recovery_acceptance': False}, indent=2))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
