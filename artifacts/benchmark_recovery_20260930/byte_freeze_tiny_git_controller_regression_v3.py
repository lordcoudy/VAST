"""Authored fixture-only controls for later execution; never original authority.

Do not run during the held decoder research phase. This new artifact preserves
all prior fixture scripts/receipts. It covers actual Git shallow behavior,
directory nlink, canonical LF controller metadata, and immutable output guards.
"""
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace

sys.dont_write_bytecode = True
root = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
script = root / "artifacts/benchmark_recovery_20260930/verify_checkout_byte_freeze_v9.py"
output = root / "artifacts/benchmark_recovery_20260930/byte-freeze-tiny-git-controller-regression.v3.json"
assert not output.exists() and not output.is_symlink(), "historical fixture receipt path"
raw = script.read_bytes()
ast.parse(raw, filename=str(script))
spec = importlib.util.spec_from_file_location("reviewed_artifact_verifier_fixture_v9", script)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
parser_path = root / "scripts/publication_image_build_v1.py"
parser_raw = parser_path.read_bytes()
parser_spec = importlib.util.spec_from_file_location("stock_image_parser_fixture", parser_path)
parser = importlib.util.module_from_spec(parser_spec)
parser_spec.loader.exec_module(parser)
assert hashlib.sha256(parser_raw).hexdigest() == \
    "a27c2daaebb8fe8cad0fecfbcc60dc29f041835f8ae01e673dd321b3df1ea50e"
fixture_root = Path(tempfile.mkdtemp(prefix="vast-byte-freeze-tiny-git-v2-", dir="/var/tmp"))
source = fixture_root / "source"
source.mkdir()


def fixture_git(*args):
    return m.command(["git", "-C", str(source), "-c", "user.name=VAST artifact fixture",
        "-c", "user.email=fixture.invalid@example.invalid", "-c", "commit.gpgsign=false", *args], source)


def must_reject(fn, expected_fragment):
    try:
        fn()
    except ValueError as error:
        assert expected_fragment in str(error), str(error)
    else:
        raise AssertionError("expected original negative: " + expected_fragment)


def clone(autocrlf, commit, name):
    target = fixture_root / name
    clone_ordinal = len(m.COMMANDS) + 1
    m.command(["git", "clone", "--no-checkout", "--no-local", "--depth", "1", "--single-branch",
        "--branch", "codex/byte-freeze-fixture-v2", source.as_uri(), str(target)], fixture_root)
    before = m.epoch(target.stat())
    assert m.command(["git", "-C", str(target), "ls-files", "-z"], target) == b""
    config_ordinal = len(m.COMMANDS) + 1
    m.command(["git", "-C", str(target), "config", "--local", "core.autocrlf", autocrlf], target)
    checkout_ordinal = len(m.COMMANDS) + 1
    m.command(["git", "-C", str(target), "checkout", "--detach", commit], target)
    after = m.epoch(target.stat())
    assert before[:3] == after[:3] and before[3] != after[3]
    assert m.directory_identity(target.stat()) == before[:3]
    assert (target / ".git/shallow").read_text("ascii").strip() == commit
    assert not (target / ".git/objects/info/alternates").exists()
    objects = [path for path in (target / ".git/objects").rglob("*") if path.is_file()]
    assert objects and all(path.resolve(strict=True) == path and path.stat().st_nlink == 1 for path in objects)
    assert m.command(["git", "-C", str(target), "status", "--porcelain=v1", "-z", "--untracked-files=no"],
        target) == b""
    return target, {"core_autocrlf": autocrlf, "target": str(target),
        "clone_command_ordinal": clone_ordinal, "config_before_first_checkout_command_ordinal": config_ordinal,
        "first_checkout_command_ordinal": checkout_ordinal,
        "root_before_epoch": before, "root_after_epoch": after,
        "dev_ino_mode_identity_preserved": True, "legitimate_directory_nlink_change": True,
        "independent_object_store": True, "whole_fixture_status_clean": True}


fixture_git("init", "--initial-branch=codex/byte-freeze-fixture-v2")
(source / ".gitattributes").write_bytes(b"/raw.txt -text !eol\n/explicit.txt text eol=lf\n")
(source / "raw.txt").write_bytes(b"first\r\nsecond\nthird\r\n")
(source / "explicit.txt").write_bytes(b"explicit LF\n")
for relative in ("one/nested/payload.txt", "two/other.txt"):
    path = source / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((relative + "\n").encode("ascii"))
(source / "controller-allowlist.txt").write_bytes(b"raw.txt\n")
fixture_git("add", "--", ".gitattributes", "raw.txt", "explicit.txt", "one", "two", "controller-allowlist.txt")
fixture_git("commit", "-m", "fixture missing LF controller contract")
original = fixture_git("rev-parse", "HEAD").decode("ascii").strip()

# RED control is the actual stock parser on a genuine initial true checkout.
# Its original failure and bytes remain in this distinct fixture namespace.
red_root, red_case = clone("true", original, "original-missing-LF")
assert (red_root / "controller-allowlist.txt").read_bytes() == b"raw.txt\r\n"
must_reject(lambda: parser._read_allowlist(red_root, "controller-allowlist.txt"), "canonical LF")
red_case["actual_stock_parser_rejected_missing_LF_contract"] = True

(source / ".gitattributes").write_bytes(
    b"/raw.txt -text !eol\n/explicit.txt text eol=lf\n/controller-allowlist.txt text eol=lf\n")
fixture_git("add", "--", ".gitattributes")
fixture_git("commit", "-m", "fixture separately scoped LF controller contract")
source_commit = fixture_git("rev-parse", "HEAD").decode("ascii").strip()
fixture_git("merge-base", "--is-ancestor", original, source_commit)
cases = []
for autocrlf in ("false", "true"):
    target, case = clone(autocrlf, source_commit, "fresh-" + autocrlf)
    assert (target / "raw.txt").read_bytes() == (source / "raw.txt").read_bytes()
    assert (target / "explicit.txt").read_bytes() == b"explicit LF\n"
    assert (target / "controller-allowlist.txt").read_bytes() == b"raw.txt\n"
    assert parser._read_allowlist(target, "controller-allowlist.txt") == ("raw.txt",)
    before = case["root_before_epoch"]
    replacement = fixture_root / ("foreign-" + autocrlf)
    replacement.mkdir()
    assert m.directory_identity(replacement.stat()) != before[:3]
    must_reject(lambda: m.command(["git", "-C", str(target), "cat-file", "-e", original + "^{commit}"],
        target), "original command failed")
    assert m.COMMANDS[-1]["returncode"] != 0
    names = ["raw.txt", "explicit.txt", "controller-allowlist.txt"]
    observed_attrs = m.attrs(["git", "-C", str(target)], target, names)
    assert observed_attrs == m.desired_attrs(names, {"raw.txt"})
    with m.Held(target) as held:
        original_leaf = held.pin("raw.txt")
        leaf_epoch = list(held.files["raw.txt"][1])
        (target / "unrelated-output-directory").mkdir()
        held.verify()
        assert held.pin("raw.txt") == original_leaf and held.files["raw.txt"][1] == leaf_epoch
    case.update({"foreign_root_identity_rejected": True,
        "omitted_planning_ancestor_intentionally_absent": True,
        "raw_source_and_separate_canonical_LF_controller_bytes_preserved": True,
        "actual_stock_parser_accepted_exact_LF_manifest": True,
        "effective_attributes": observed_attrs, "held_leaf_epoch7_unchanged_after_sibling_creation": True})
    cases.append(case)

# Actual same-bytes source replacement fails original held leaf identity.
aba_root = fixture_root / "leaf-ABA"
aba_root.mkdir()
(aba_root / "leaf.txt").write_bytes(b"held\n")
held = m.Held(aba_root)
held.__enter__()
try:
    held.pin("leaf.txt")
    (aba_root / "replacement.txt").write_bytes(b"held\n")
    os.replace(aba_root / "replacement.txt", aba_root / "leaf.txt")
    must_reject(held.verify, "source custody changed")
finally:
    held.stack.close()

# Output guards reject reused main/derived names before any new command.
guard_root = fixture_root / "output-guards"
guard_root.mkdir()
guard_args = SimpleNamespace(output=str(guard_root / "proof.json"), mode="checkouts",
    source_commit=source_commit, planning_commit=original, review_reference="fixture-only-no-original-review")
reservation = m.reserve_outputs(guard_args)
command_count = len(m.COMMANDS)
reservation_bytes = Path(reservation["path"]).read_bytes()
must_reject(lambda: m.reserve_outputs(guard_args), "prior immutable")
assert len(m.COMMANDS) == command_count and Path(reservation["path"]).read_bytes() == reservation_bytes
foreign_output = guard_root / "foreign.json"
foreign_failed = foreign_output.with_name(foreign_output.stem + ".autocrlf-true.failed.json")
foreign_failed.write_bytes(b"fixture original failed marker\n")
foreign_args = SimpleNamespace(**{**vars(guard_args), "output": str(foreign_output)})
must_reject(lambda: m.reserve_outputs(foreign_args), "prior immutable")
assert foreign_failed.read_bytes() == b"fixture original failed marker\n" and len(m.COMMANDS) == command_count

sealed = {"kind": "fixture-only", "value": 1}
sealed["sha256"] = hashlib.sha256(m.canonical(sealed)).hexdigest()
assert m.sealed_document(m.canonical(sealed) + b"\n") == sealed
bad = {**sealed, "value": 2}
must_reject(lambda: m.sealed_document(m.canonical(bad) + b"\n"), "semantic seal")
must_reject(lambda: m.sealed_document(b'{"sha256":"x","sha256":"y"}\n'), "duplicate JSON")

value = {"schema_version": 1, "artifact_kind": "vast_byte_freeze_tiny_git_controller_regression_v3",
    "fixture_root": str(fixture_root), "fixture_original_commit": original, "fixture_source_commit": source_commit,
    "controller": m.process_observation(os.getpid()),
    "verifier": {"path": str(script), "size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()},
    "stock_parser": {"path": str(parser_path), "size_bytes": len(parser_raw),
        "sha256": hashlib.sha256(parser_raw).hexdigest()},
    "regression_source": {"path": str(Path(__file__).resolve()),
        "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
    "original_missing_LF_red": red_case, "cases": cases, "commands": m.COMMANDS,
    "guards": {"same_bytes_leaf_ABA_rejected": True,
        "existing_reservation_and_derived_failure_rejected_before_commands": True,
        "original_guard_bytes_unchanged": True, "semantic_reseal_and_duplicate_fields_rejected": True},
    "retained_fixture_namespaces": True, "original_repository_source_index_configuration_unchanged": True,
    "accepted": False, "publication_ready": False, "launch_or_publication_grant": False,
    "scope": "genuine_tiny_Git_controller_controls_only_not_actual165_or10_source_image_or_review_authority"}
print(json.dumps(m.write_new(output, value)))
