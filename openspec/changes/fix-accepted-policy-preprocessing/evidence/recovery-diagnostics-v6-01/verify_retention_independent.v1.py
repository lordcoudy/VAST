"""Independent read-only archive/member/source comparison; no extraction."""
import hashlib
import json
import stat
import sys
import tarfile
from pathlib import Path, PurePosixPath

source, target, controls = map(Path, sys.argv[1:4])
catalog_bytes = (target / "members.original.v1.json").read_bytes()
assert hashlib.sha256(catalog_bytes).hexdigest() == "b58b0768b6519442a8aad72ffc5179c655078c5565f494cf81ec232d12e6b0b6"
catalog = json.loads(catalog_bytes)
expected = {row[0]: (row[1], row[2]) for row in catalog["members"]}
assert len(expected) == len(catalog["members"]) == 3810
assert sum(not row[0] for row in expected.values()) == 982

def inventory():
    result = {}
    for path in source.rglob("*"):
        info = path.lstat()
        assert not stat.S_ISLNK(info.st_mode)
        if stat.S_ISDIR(info.st_mode):
            continue
        assert stat.S_ISREG(info.st_mode)
        content = path.read_bytes()
        result[path.relative_to(source).as_posix()] = (len(content), hashlib.sha256(content).hexdigest())
    return result

before = inventory()
assert before == expected
archive = target / "diagnostic-cohort.original.v1.tar.gz"
assert archive.stat().st_size == 1005529
archive_sha = hashlib.sha256(archive.read_bytes()).hexdigest()
assert archive_sha == "1f030c72abb90c4d9f693682885e0642d0b93e7d8f2d083cf2a0b3f34eb27520"
observed = {}
with tarfile.open(archive, "r:gz") as bundle:
    for member in bundle:
        name = PurePosixPath(member.name)
        assert member.isfile() and not name.is_absolute() and ".." not in name.parts
        assert name.as_posix() == member.name and member.name not in observed
        stream = bundle.extractfile(member)
        assert stream is not None
        with stream:
            content = stream.read()
        assert len(content) == member.size
        observed[member.name] = (len(content), hashlib.sha256(content).hexdigest())
assert observed == expected
assert inventory() == before
source_bytes = sum(row[0] for row in expected.values())
assert source_bytes == 13931754
assert expected["independent-guest-outer-review.final.v1.md"][1] == "a41beb6ace994c53cc786e5fd1ab916b51ff38ccc760f9f5e9cd05a0c90edcf2"
retention_bytes = sum(path.stat().st_size for path in target.rglob("*") if path.is_file())
control_bytes = sum(path.stat().st_size for path in controls.rglob("*") if path.is_file())
before_report = source_bytes + retention_bytes + control_bytes
report = {"verdict": "CLEAR", "reviewer": "/root", "scope": "D7 archive retention only",
          "all_original_members_retained": True, "archive_all_members_readback_equal": True,
          "source_before_after_equal": True, "regular_members": len(expected), "zero_byte_members": 982,
          "source_bytes": source_bytes, "archive_sha256": archive_sha,
          "catalog_sha256": hashlib.sha256(catalog_bytes).hexdigest(),
          "aggregate_before_this_report_bytes": before_report, "cohort_limit_bytes": 16777216,
          "archive_extracted_or_originals_mutated": False, "recovery_acceptance": False,
          "historical_block_witnesses_retained": True}
raw = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
assert before_report + len(raw) < 16777216
with (target / "independent-retention-review.original.v1.json").open("xb") as stream:
    stream.write(raw)
print(json.dumps({"verdict": "CLEAR", "members": len(expected), "source_bytes": source_bytes,
                  "aggregate_including_report_bytes": before_report + len(raw),
                  "report_sha256": hashlib.sha256(raw).hexdigest()}, sort_keys=True))
