#!/usr/bin/env python3
"""Inventory, plan or apply exact old->new identity pin substitutions (qfb-20261007a).

Adapted from artifacts/fix_benchmark_preparations_20260928g/rebind_host_identity_pins.py
for OpenSpec change qualify-full-benchmark, task 5.4 (design Amendment 2, B1/B2).

OLD identities: receipts of chain 20260928g plus the decision28 GStreamer runtime
freeze (the PR pin of checkpoint_gstreamer_publication_runtime_v3.py).
NEW identities: receipts of qualify_full_benchmark_20261007a (build root, commit 3a7f799d).

The old->new mapping is derived only by walking paired JSON receipts (and by the
byte facts sha256/size of paired files). Python pin files are rewritten only inside
string-literal tokens, plus integer size literals that sit next to a paired path
literal inside the same bracket. `.ci` fixtures are NOT string-edited (B2).

Usage:
  rebind_host_identity_pins_qfb_v1.py inventory   # JSON inventory to stdout
  rebind_host_identity_pins_qfb_v1.py plan        # JSON plan to stdout (no writes)
  rebind_host_identity_pins_qfb_v1.py apply PLAN_SHA256  # apply, plan must match
"""
from __future__ import annotations

import ast
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tokenize
from pathlib import Path

ROOT = Path("/mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST")
BUILD = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
G_ROOT = Path("/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec")
OLD_DIR = "artifacts/fix_benchmark_preparations_20260928g"
NEW_DIR = "artifacts/qualify_full_benchmark_20261007a"
OLD = G_ROOT / OLD_DIR
NEW = BUILD / NEW_DIR
DECISION28_REL = ("artifacts/benchmark_recovery_20260930/"
                  "decision28-selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json")
DECISION28 = ROOT / DECISION28_REL
# Tracked byte copy of the NEW GStreamer freeze (replaces the tracked decision28 copy as the
# portable static binding receipt read by test_gstreamer_current_runtime_is_exactly_refrozen).
GSTREAMER_TRACKED_COPY_REL = ("artifacts/qualify_full_benchmark_20261007a/"
                              "selected-original-build-copy-v1/gstreamer_custom.runtime.freeze.json")
# Reviewed size literal that is not adjacent to its path literal (separate statement).
EXPLICIT_SIZE_SITES = (
    ("tests/test_publication_runtime_frozen_identity_constants_v1.py", 332, "7001", DECISION28_REL),
)
OLD_NS = "fix-benchmark-20260928g"
NEW_NS = "qfb-20261007a"
BUILD_COMMIT = "3a7f799d"

FILES = (
    "scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py",
    "scripts/checkpoint_gstreamer_publication_runtime_v3.py",
    "scripts/checkpoint_openvino_gva_publication_runtime_v3.py",
    "scripts/checkpoint_openvino_gva_qualification_fragment_v3.py",
    "tests/test_publication_runtime_frozen_identity_constants_v1.py",
    "tests/test_checkpoint_gstreamer_custom_qualification_fragment_v3.py",
    "tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py",
    "tests/test_publication_gstreamer_component_inputs_v1.py",
)
# Tracked paths that legitimately keep old values (historical receipts / B2 fixtures /
# narrative docs); reported by the inventory but never string-edited.
HISTORICAL_PREFIXES = (
    "configs/analytics_execution_layer.refreshed.v4.fix-benchmark-",
    "configs/checkpoint_analytics_model_parity.refreshed.v4.fix-benchmark-",
    ".ci/fixtures/",
    "docs/",
    "progress.md",
    "artifacts/",
    "openspec/",
)
SCAN_PREFIXES = ("scripts/", "tests/", ".ci/", "configs/", "deploy/")

CONFIG_JSON = (
    "configs/checkpoint_analytics_model_parity.refreshed.v4.{ns}.accepted.acceptance_receipt.json",
    "configs/checkpoint_analytics_model_parity.refreshed.v4.{ns}.accepted.assessment.json",
    "configs/analytics_execution_layer.refreshed.v4.{ns}.json",
)
CONFIG_YAML = (
    "configs/checkpoint_analytics_model_parity.refreshed.v4.{ns}.accepted.yaml",
    "configs/checkpoint_analytics_model_parity.refreshed.v4.{ns}.yaml",
)
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")

HEX64 = re.compile(r"[0-9a-f]{64}\Z")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
REPOSITORY_DIGEST = re.compile(r"[A-Za-z0-9_./:-]+@sha256:[0-9a-f]{64}\Z")
IMAGE_REFERENCE = re.compile(r"vast/[a-z0-9._-]+(?:/[a-z0-9._-]+)*:[A-Za-z0-9._-]+\Z")
SIZE_KEYS = {"size", "size_bytes"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def physical(path: Path) -> Path:
    require(path.is_file() and not path.is_symlink(), f"physical file required: {path}")
    return path


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def json_pairs():
    """(label, old_path, new_path) for every walked receipt pair."""
    yield "identity_patch", OLD / "qualification_image_identity_patch.json", NEW / "qualification_image_identity_patch.json"
    for template in CONFIG_JSON:
        yield (template.format(ns="<ns>"), ROOT / template.format(ns=OLD_NS),
               ROOT / template.format(ns=NEW_NS))
    for relative in ("native-a/native_probe.freeze.json", "worker_images/analytics-worker.freeze.json"):
        yield relative, OLD / relative, NEW / relative
    parity_files = ["acceptance_binding.v4.json", "runtime_probes/cpu_runtime_probe.json",
                    "runtime_probes/gpu_runtime_probe.json"]
    parity_files += sorted("bindings/" + path.name for path in (OLD / "model_parity_v4/bindings").glob("*.json"))
    for relative in parity_files:
        yield ("model_parity_v4/" + relative, OLD / "model_parity_v4" / relative,
               NEW / "model_parity_v4" / relative)
    for system in SYSTEMS:
        relative = f"runtime_images/{system}.runtime.freeze.json"
        yield relative, OLD / relative, NEW / relative
    yield "decision28:gstreamer_custom.runtime.freeze.json", DECISION28, NEW / "runtime_images/gstreamer_custom.runtime.freeze.json"


def file_pairs():
    """(old repo-relative path, new repo-relative path, old_path, new_path) for byte facts."""
    for label, old, new in json_pairs():
        if label.startswith("configs/"):
            yield (str(old.relative_to(ROOT)), str(new.relative_to(ROOT)), old, new)
        elif label.startswith("decision28:"):
            copy = physical(ROOT / GSTREAMER_TRACKED_COPY_REL)
            require(copy.read_bytes() == physical(new).read_bytes(),
                    "tracked GStreamer freeze copy differs from the build-root receipt")
            yield (DECISION28_REL, GSTREAMER_TRACKED_COPY_REL, old, copy)
        else:
            yield (str(old.relative_to(G_ROOT)), str(new.relative_to(BUILD)), old, new)
    for template in CONFIG_YAML:
        old = ROOT / template.format(ns=OLD_NS)
        new = ROOT / template.format(ns=NEW_NS)
        yield str(old.relative_to(ROOT)), str(new.relative_to(ROOT)), old, new


def identity_change(old: object, new: object) -> bool:
    if not isinstance(old, str) or not isinstance(new, str) or old == new:
        return False
    if ("20260928g" in old and "20261007a" in new):
        return True
    return any(pattern.fullmatch(old) and pattern.fullmatch(new)
               for pattern in (HEX64, IMAGE_ID, REPOSITORY_DIGEST, IMAGE_REFERENCE))


def exact_mapping():
    mapping: dict[str, str] = {}
    provenance: dict[str, list[str]] = {}
    numeric: dict[str, list] = {}
    sizes: dict[str, tuple[int, int]] = {}

    def add(old: str, new: str, source: str) -> None:
        require(old not in mapping or mapping[old] == new,
                f"ambiguous identity replacement for {old}: {mapping.get(old)} vs {new} ({source})")
        mapping[old] = new
        provenance.setdefault(old, [])
        if len(provenance[old]) < 6:
            provenance[old].append(source)

    def walk(old: object, new: object, label: str, pointer: str) -> None:
        if isinstance(old, dict) and isinstance(new, dict):
            for key in sorted(old.keys() & new.keys()):
                walk(old[key], new[key], label, f"{pointer}/{key}")
        elif isinstance(old, list) and isinstance(new, list) and len(old) == len(new):
            for index, (left, right) in enumerate(zip(old, new)):
                walk(left, right, label, f"{pointer}/{index}")
        elif identity_change(old, new):
            add(old, new, f"{label}#{pointer}")
            if IMAGE_ID.fullmatch(old):
                add(old[7:], new[7:], f"{label}#{pointer}(bare-hex)")
        elif (type(old) is int and type(new) is int and old != new):
            numeric.setdefault(f"{label}#{pointer}", [old, new])

    for label, old, new in json_pairs():
        physical(old)
        physical(new)
        walk(json.loads(old.read_bytes()), json.loads(new.read_bytes()), label, "")
    for old_rel, new_rel, old, new in file_pairs():
        old_bytes, new_bytes = old.read_bytes(), new.read_bytes()
        if sha256(old_bytes) != sha256(new_bytes):
            add(sha256(old_bytes), sha256(new_bytes), f"file-sha256:{old_rel}")
        sizes[old_rel] = (len(old_bytes), len(new_bytes))
        if old_rel != new_rel:
            add(old_rel, new_rel, f"file-path:{old_rel}")
    add(OLD_DIR + "/model_parity_v4", NEW_DIR + "/model_parity_v4", "artifact-dir")
    add(OLD_DIR, NEW_DIR, "artifact-dir")
    add(OLD_NS, NEW_NS, "namespace")
    # No chained substitution: a new value must never be an old key.
    chained = sorted(set(mapping.values()) & set(mapping))
    require(not chained, f"chained identity replacement: {chained[:3]}")
    return mapping, provenance, numeric, sizes


def check_copied_configs() -> list[dict]:
    rows = []
    for template in CONFIG_JSON + CONFIG_YAML:
        relative = template.format(ns=NEW_NS)
        left = physical(ROOT / relative).read_bytes()
        right = physical(BUILD / relative).read_bytes()
        require(left == right, f"copied config differs from build root: {relative}")
        rows.append({"path": relative, "sha256": sha256(left), "size_bytes": len(left)})
    return rows


def line_offsets(text: str) -> list[int]:
    starts = [0]
    for line in text.splitlines(keepends=True):
        starts.append(starts[-1] + len(line))
    return starts


def literal_value(token_text: str):
    try:
        value = ast.literal_eval(token_text)
    except (ValueError, SyntaxError):
        return None
    return value if isinstance(value, str) else None


def plan_file(relative: str, mapping: dict[str, str], sizes: dict[str, tuple[int, int]]):
    path = physical(ROOT / relative)
    before = path.read_bytes()
    text = before.decode("utf-8")
    ordered = sorted(mapping, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(key) for key in ordered))
    starts = line_offsets(text)
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    edits = []
    rows = []

    def span(token):
        return (starts[token.start[0] - 1] + token.start[1], starts[token.end[0] - 1] + token.end[1])

    # Implicitly concatenated two-literal paths ("a/b/" "c/d.json") whose joined value is an
    # exact mapping key: both literals are rewritten, split after the same number of '/'.
    handled = set()
    for index, token in enumerate(tokens):
        if token.type != tokenize.STRING:
            continue
        cursor = index + 1
        while cursor < len(tokens) and tokens[cursor].type in (tokenize.NL, tokenize.COMMENT):
            cursor += 1
        if cursor >= len(tokens) or tokens[cursor].type != tokenize.STRING:
            continue
        first, second = literal_value(token.string), literal_value(tokens[cursor].string)
        if first is None or second is None or first + second not in mapping:
            continue
        if (pattern.sub(lambda match: mapping[match.group(0)], first) +
                pattern.sub(lambda match: mapping[match.group(0)], second)) == mapping[first + second]:
            continue  # per-literal substitution already yields the exact new joined value
        require(first.endswith("/") and token.string[0] == tokens[cursor].string[0] and
                token.string[0] in "\"'" and not token.string.startswith(('"""', "'''")),
                f"unsupported concatenated literal in {relative}:{token.start[0]}")
        new_value = mapping[first + second]
        parts = new_value.split("/")
        cut = first.count("/")
        new_first, new_second = "/".join(parts[:cut]) + "/", "/".join(parts[cut:])
        quote = token.string[0]
        for item, old_part, new_part in ((token, first, new_first), (tokens[cursor], second, new_second)):
            require(quote not in new_part and "\\" not in new_part, "unsafe literal content")
            start, end = span(item)
            edits.append((start, end, quote + new_part + quote))
            rows.append({"line": item.start[0], "kind": "concatenated_path_literal_part",
                         "old": item.string, "new": quote + new_part + quote,
                         "keys": [first + second]})
            handled.add(id(item))
    for (file_name, line, old_text, old_rel) in EXPLICIT_SIZE_SITES:
        if file_name != relative:
            continue
        matches = [item for item in tokens if item.type == tokenize.NUMBER and
                   item.start[0] == line and item.string == old_text]
        require(len(matches) == 1 and sizes[old_rel][0] == int(old_text),
                f"explicit size site drifted: {relative}:{line}")
        start, end = span(matches[0])
        edits.append((start, end, str(sizes[old_rel][1])))
        rows.append({"line": line, "kind": "explicit_reviewed_size_literal", "old": old_text,
                     "new": str(sizes[old_rel][1]), "keys": [old_rel]})
    depth = 0
    for index, token in enumerate(tokens):
        if token.type == tokenize.OP and token.string in "([{":
            depth += 1
        elif token.type == tokenize.OP and token.string in ")]}":
            depth -= 1
        if token.type != tokenize.STRING or id(token) in handled:
            continue
        start = starts[token.start[0] - 1] + token.start[1]
        end = starts[token.end[0] - 1] + token.end[1]
        original = text[start:end]
        hits = []
        changed = pattern.sub(lambda match: (hits.append(match.group(0)), mapping[match.group(0)])[1], original)
        if changed != original:
            edits.append((start, end, changed))
            rows.append({"line": token.start[0], "kind": "string_literal", "old": original,
                         "new": changed, "keys": hits})
        value = literal_value(original)
        if value in sizes and sizes[value][0] != sizes[value][1]:
            old_size, new_size = sizes[value]
            level = depth
            cursor = index + 1
            while cursor < len(tokens):
                probe = tokens[cursor]
                if probe.type == tokenize.OP and probe.string in ")]}":
                    if level == depth:
                        break
                    level -= 1
                elif probe.type == tokenize.OP and probe.string in "([{":
                    level += 1
                elif probe.type == tokenize.STRING and literal_value(probe.string) in sizes:
                    break
                elif probe.type == tokenize.NUMBER and probe.string == str(old_size):
                    number_start = starts[probe.start[0] - 1] + probe.start[1]
                    number_end = starts[probe.end[0] - 1] + probe.end[1]
                    edits.append((number_start, number_end, str(new_size)))
                    rows.append({"line": probe.start[0], "kind": "size_literal_next_to_path",
                                 "old": probe.string, "new": str(new_size), "keys": [value]})
                    break
                cursor += 1
    edits.sort()
    for left, right in zip(edits, edits[1:]):
        require(left[1] <= right[0], f"overlapping edits in {relative}")
    for start, end, changed in reversed(edits):
        text = text[:start] + changed + text[end:]
    after = text.encode("utf-8")
    require(rows, f"no identity pin was rebound in {relative}")
    for forbidden in (OLD_NS, OLD_DIR, "20260928g", "decision28-2a6a42c9", "decision28-selected"):
        require(forbidden not in text, f"old token {forbidden} remains in {relative}")
    for old in mapping:
        if HEX64.fullmatch(old) or IMAGE_ID.fullmatch(old):
            require(old not in text, f"old identity {old} remains in {relative}")
    ast.parse(text, filename=relative)
    # Line endings must be preserved byte-for-byte.
    require(before.count(b"\r\n") == after.count(b"\r\n") and
            before.count(b"\n") == after.count(b"\n"), f"line structure changed: {relative}")
    return {"file": relative, "path": path, "before": before, "after": after, "edits": rows}


def tracked_files() -> list[str]:
    # The PR worktree is a Windows git worktree; WSL git cannot open it, so the
    # NUL-separated `git ls-files -z` listing may be supplied via QFB_TRACKED_FILES.
    listing = os.environ.get("QFB_TRACKED_FILES")
    if listing:
        output = Path(listing).read_bytes()
    else:
        output = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                                capture_output=True).stdout
    return [item.decode() for item in output.split(b"\0") if item]


def inventory(mapping, provenance, numeric, sizes) -> dict:
    keys = sorted(mapping, key=len, reverse=True)
    pattern = re.compile("|".join(re.escape(key) for key in keys))
    sites = []
    historical = {}
    for relative in tracked_files():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink():
            continue
        payload = path.read_bytes()
        if b"\0" in payload[:8192]:
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for match in pattern.finditer(line):
                old = match.group(0)
                if relative.startswith(HISTORICAL_PREFIXES) or not relative.startswith(SCAN_PREFIXES) \
                        and relative not in FILES:
                    historical[relative] = historical.get(relative, 0) + 1
                    continue
                sites.append({"file": relative, "line": number, "old": old, "new": mapping[old],
                              "source": provenance[old]})
    # Old values split over two implicitly concatenated literals are invisible per line.
    for relative in FILES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        tokens = [token for token in tokenize.generate_tokens(io.StringIO(text).readline)
                  if token.type not in (tokenize.NL, tokenize.COMMENT)]
        for left, right in zip(tokens, tokens[1:]):
            if left.type != tokenize.STRING or right.type != tokenize.STRING:
                continue
            first, second = literal_value(left.string), literal_value(right.string)
            if first is None or second is None:
                continue
            for match in pattern.finditer(first + second):
                if match.start() < len(first) < match.end():
                    old = match.group(0)
                    left_part = old[:len(first) - match.start()]
                    right_part = old[len(first) - match.start():]
                    changed = [token for token, unchanged in
                               ((left, mapping[old].startswith(left_part)),
                                (right, mapping[old].endswith(right_part))) if not unchanged]
                    for token in changed:
                        sites.append({"file": relative, "line": token.start[0], "old": old,
                                      "new": mapping[old], "source": provenance[old],
                                      "kind": "split_over_concatenated_literals"})
    size_sites = []
    old_sizes = {old: rel for rel, (old, new) in sizes.items() if old != new}
    for relative in FILES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type == tokenize.NUMBER and token.string.isdigit() and int(token.string) in old_sizes:
                rel = old_sizes[int(token.string)]
                size_sites.append({"file": relative, "line": token.start[0], "old": int(token.string),
                                   "new": sizes[rel][1], "source": f"file-size:{rel}"})
    # Classify every 64-hex literal of the pin files against old/new receipts.
    old_hex, new_hex = receipt_hex_sets()
    literals = []
    hex_any = re.compile(r"[0-9a-f]{64}")
    for relative in FILES:
        text = (ROOT / relative).read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(text).readline):
            if token.type != tokenize.STRING:
                continue
            for value in hex_any.findall(token.string):
                if value in mapping:
                    status = "changed_old_value_rebound"
                elif value in new_hex and value in old_hex:
                    status = "unchanged_in_old_and_new_receipts"
                elif value in new_hex:
                    status = "already_new_value"
                elif value in old_hex:
                    status = "old_value_without_pair_ERROR"
                else:
                    status = "not_in_any_old_or_new_receipt"
                literals.append({"file": relative, "line": token.start[0], "value": value,
                                 "status": status})
    return {"sites": sites, "size_sites": size_sites, "historical_or_excluded_occurrences": historical,
            "numeric_receipt_changes": numeric, "hex_literal_classification": literals}


def receipt_hex_sets() -> tuple[set[str], set[str]]:
    hex_any = re.compile(r"[0-9a-f]{64}")
    old_hex: set[str] = set()
    new_hex: set[str] = set()
    for old_rel, new_rel, old, new in file_pairs():
        old_bytes, new_bytes = old.read_bytes(), new.read_bytes()
        old_hex.update(hex_any.findall(old_bytes.decode("utf-8", "replace")))
        new_hex.update(hex_any.findall(new_bytes.decode("utf-8", "replace")))
        old_hex.add(sha256(old_bytes))
        new_hex.add(sha256(new_bytes))
    return old_hex, new_hex


def plan_all():
    require(ROOT.resolve(strict=True) == ROOT, "project root alias")
    mapping, provenance, numeric, sizes = exact_mapping()
    configs = check_copied_configs()
    plans = [plan_file(relative, mapping, sizes) for relative in FILES]
    return plans, mapping, provenance, numeric, sizes, configs


def report(plans, mapping, configs, status: str) -> dict:
    return {
        "status": status, "tool": "rebind_host_identity_pins_qfb_v1.py", "build_commit": BUILD_COMMIT,
        "old_ns": OLD_NS, "new_ns": NEW_NS, "old_dir": OLD_DIR, "new_dir": NEW_DIR,
        "decision28_freeze": DECISION28_REL, "mapping_size": len(mapping),
        "copied_configs": configs,
        "files": [{"file": row["file"], "before_sha256": sha256(row["before"]),
                   "after_sha256": sha256(row["after"]), "edits": row["edits"]} for row in plans],
    }


def stage_bytes(path: Path, payload: bytes) -> Path:
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.rebind-", dir=path.parent)
    staged = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(staged, stat.S_IMODE(path.stat().st_mode))
        return staged
    except BaseException:
        staged.unlink(missing_ok=True)
        raise


def apply_plans(plans) -> None:
    staged = {}
    try:
        for row in plans:
            require(row["path"].read_bytes() == row["before"], f"target changed: {row['file']}")
            staged[row["path"]] = stage_bytes(row["path"], row["after"])
        for row in plans:
            os.replace(staged.pop(row["path"]), row["path"])
        for row in plans:
            require(row["path"].read_bytes() == row["after"], f"post-apply bytes differ: {row['file']}")
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def main() -> None:
    require(sys.flags.optimize == 0, "requires unoptimized Python")
    args = sys.argv[1:]
    if args == ["inventory"]:
        mapping, provenance, numeric, sizes = exact_mapping()
        result = inventory(mapping, provenance, numeric, sizes)
        result.update({"mapping_size": len(mapping),
                       "mapping": [{"old": key, "new": mapping[key], "source": provenance[key]}
                                   for key in sorted(mapping)],
                       "file_sizes": {key: list(value) for key, value in sorted(sizes.items())}})
        print(json.dumps(result, sort_keys=True, indent=1))
        return
    if args == ["plan"]:
        plans, mapping, _, _, _, configs = plan_all()
        print(json.dumps(report(plans, mapping, configs, "planned"), sort_keys=True, indent=1))
        return
    require(len(args) == 2 and args[0] == "apply", "usage: inventory | plan | apply PLAN_SHA256")
    plans, mapping, _, _, _, configs = plan_all()
    planned = (json.dumps(report(plans, mapping, configs, "planned"), sort_keys=True, indent=1) + "\n").encode()
    require(sha256(planned) == args[1], "plan drifted from reviewed plan sha256")
    apply_plans(plans)
    print(json.dumps(report(plans, mapping, configs, "applied"), sort_keys=True, indent=1))


if __name__ == "__main__":
    main()
