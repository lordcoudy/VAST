"""Bounded read-only analysis of one original hosted CI artifact; no test execution."""
import collections
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent
ORIGINAL = ROOT / "artifacts/benchmark_recovery_20260930/cpu-ci-run-36676456718"
SOURCES = (
    "scripts/backend_publication_process_supervisor_v3.py",
    "scripts/backend_publication_output_transaction_production_v3.py",
    "tests/test_backend_publication_output_transaction_production_v3.py",
    "scripts/run_ci_checks.py",
)

def epoch(info):
    return [int(getattr(info, key)) for key in
            ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")]

def read_original(path, limit):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        assert stat.S_ISREG(before.st_mode) and before.st_nlink == 1 and before.st_size <= limit
        chunks = []
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            chunks.append(chunk)
            assert sum(map(len, chunks)) <= limit
        raw = b"".join(chunks)
        assert len(raw) == before.st_size
        assert epoch(before) == epoch(os.fstat(fd)) == epoch(path.lstat())
        return raw, {"path": str(path.relative_to(ROOT)), "size_bytes": len(raw),
                     "sha256": hashlib.sha256(raw).hexdigest(), "epoch": epoch(before)}
    finally:
        os.close(fd)

zip_raw, zip_pin = read_original(ORIGINAL / "original-artifact.zip", 2 * 1024 * 1024)
assert zip_pin["sha256"] == "ec02be0dd68e1ac5876278d06c8edf5484b4941a280495f673fb195fc21bae3e"
decoded, decoded_pin = read_original(ORIGINAL / "original-decoded-job.log", 1024 * 1024)
assert decoded_pin["sha256"] == "0b07ff9ad00f362d0709fbe58901cc18f745859d6595f1dc03771e885c478a30"
with zipfile.ZipFile(ORIGINAL / "original-artifact.zip") as archive:
    members = archive.infolist()
    assert len(members) <= 512 and len({m.filename for m in members}) == len(members)
    assert sum(m.file_size for m in members) <= 64 * 1024 * 1024
    for member in members:
        path = PurePosixPath(member.filename)
        assert not path.is_absolute() and ".." not in path.parts
        assert "\\" not in member.filename and ":" not in member.filename
        assert not stat.S_ISLNK(member.external_attr >> 16)
        assert member.file_size <= 8 * 1024 * 1024
    assert archive.testzip() is None
    source_before = json.loads(archive.read("tracked-source.before.json"))
    current_sources = {}
    for name in SOURCES:
        _, pin = read_original(ROOT / name, 1024 * 1024)
        assert {key: pin[key] for key in ("size_bytes", "sha256")} == source_before[name]
        current_sources[name] = pin
    unit_raw = archive.read("unittest.original.log")
    stack_raw = archive.read("unittest-stacks.original.log")
    events = [json.loads(line) for line in unit_raw.decode("utf8").splitlines() if line.startswith("{")]
    started = [e for e in events if e.get("event") == "test_started"]
    terminal = [e for e in events if e.get("event") == "test_terminal"]
    terminal_ids = {e["test_id"] for e in terminal}
    unfinished = [e for e in started if e["test_id"] not in terminal_ids]
    assert len(started) == 121 and len(terminal) == 120 and len(unfinished) == 1
    selected_members = {}
    for name in ("unittest.original.log", "unittest-stacks.original.log", "tracked-source.before.json",
                 "host-facts.original.json", "native-configure.json", "native-build.json"):
        raw = archive.read(name)
        selected_members[name] = {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
    report = {
        "schema_version": 1,
        "classification": "original hosted failure inspection; no executed tests, namespaces, containers or models",
        "hosted_commit": "065fb8dbb9df914d8a6e50300533dfc55d99b892",
        "run_id": 36676456718,
        "job_id": 109762366332,
        "original_zip": zip_pin,
        "original_decoded_job": decoded_pin,
        "zip_members": len(members), "zip_crc_pass": True,
        "member_paths_contained_unique_without_symlinks": True,
        "selected_member_pins": selected_members,
        "inspected_physical_sources_equal_original_hosted_before_inventory": current_sources,
        "test_events": {"starts": len(started), "terminals": len(terminal),
                        "outcomes": dict(collections.Counter(e["outcome"] for e in terminal)),
                        "unfinished": unfinished},
        "original_stack": {"timeout_banners": stack_raw.count(b"Timeout (0:01:00)!"),
                           "complete_wait3045_occurrences": stack_raw.count(b"line 3045"),
                           "literal_incomplete_tail": stack_raw[-390:].decode("utf8"),
                           "tail_ends_in_file_prefix": stack_raw.endswith(b"  File ")},
        "missing_final_artifacts": [name for name in ("tracked-source.after.json", "unittest-report.json")
                                    if name not in archive.namelist()],
        "original_native_commands": {name: json.loads(archive.read(name + ".json"))
                                     for name in ("native-configure", "native-build")},
        "original_host_facts": json.loads(archive.read("host-facts.original.json")),
        "decoded_fatal_lines": [line for line in decoded.decode("utf8-sig").splitlines()
                                if "Segmentation fault" in line or "exit code 139" in line],
        "source_path_findings": [
            {"source": SOURCES[0], "lines": [2684, 2711],
             "fact": "Held broker commits owner, awaits authorization and enters namespace; setup exception writes failed frame to stdout and returns zero without committing durable terminal response."},
            {"source": SOURCES[0], "lines": [3259, 3282],
             "fact": "After non-timeout capture, rc0, empty stderr and quiescence, durable parent ignores stdout frame and waits for journal response."},
            {"source": SOURCES[0], "lines": [2973, 3048],
             "fact": "Absent terminal-response.frame returns None; parent polls every20ms for existing615000ms ABI. Invalid present journal throws rather than polls."},
            {"source": SOURCES[0], "lines": [2544, 2586],
             "fact": "Namespace-init completion commits terminal intent then durable response; persistence failure returns74 rather than zero."},
            {"source": SOURCES[2], "lines": [1201, 1222],
             "fact": "Collision fixture calls real original process supervisor before writing attacker-owned parent receipt; its own mock does not fabricate broker success."},
            {"source": SOURCES[3], "lines": [222, 227],
             "fact": "Repeat60s faulthandler watchdog is active during full suite and canceled on ordinary suite return."},
        ],
        "interpretation": {
            "source_demonstrated_gap": "Early setup failure can exit rc0 with only stdout while durable parent awaits an absent journal; no changed timeouts are needed to explain this control-flow stall.",
            "hosted_setup_failure": "Plausible, not proven: original stdout failed frame, durable owner/request/response and broker terminal were not retained by this artifact.",
            "segfault_cause": "Unidentified. Final malformed/incomplete watchdog dump is observed; timing association does not establish watchdog, namespace, or journal causality.",
            "host_namespace_policy": "AppArmor userns restriction and unprivileged UID/GID1001 are observed. They are not a recorded unshare failure.",
            "full_ci_pass": False,
        },
        "minimal_next_reviewed_diagnostic": "Retain bounded original broker stdout/stderr, terminal rc and setup-stage exception/errno plus journal leaf presence. Unit-inject setup failure before namespaces to show durable-mode failed response cannot wait; preserve600000ms/615000ms ABI and namespace containment. Investigate139 separately from original fatal evidence; no speculative watchdog disable.",
        "local_read_query_correction": "One PowerShell hash-display query had parser error before any read or mutation; corrected query confirmed all four exact source sizes/hashes.",
    }

for pin in (zip_pin, decoded_pin, *current_sources.values()):
    _, after = read_original(ROOT / pin["path"], 2 * 1024 * 1024)
    assert after == pin
report["original_inputs_unchanged_after_inspection"] = True
raw = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode("utf8")
assert len(raw) <= 16 * 1024
with (OUT / "source-bound-forensic.v1.json").open("xb") as output:
    output.write(raw)
    output.flush()
    os.fsync(output.fileno())
print(json.dumps({"path": str((OUT / "source-bound-forensic.v1.json").relative_to(ROOT)),
                  "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}))
