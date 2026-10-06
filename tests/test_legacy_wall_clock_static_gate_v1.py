"""Static gate: legacy ordered wall stamps come only from the shared clock.

Covered runtime files must not read CLOCK_REALTIME directly (``time.time`` or
``time.time_ns``, called or passed as a default); every Dockerfile that builds
the native probe or source coordinator must copy the header that holds the
native ``NonDecreasingWallClock``.
"""

from __future__ import annotations

import ast
import os
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLOCK_MODULE = "non_decreasing_wall_clock_v1"
COVERED_RUNTIME_FILES = (
    "scripts/checkpoint_deepstream_sdk_runtime.py",
    "scripts/checkpoint_deepstream_protocol_bridge.py",
    "scripts/checkpoint_savant_sdk_runtime_v3.py",
    "scripts/publication_guardian_operational_recorder_v1.py",
)
WALL_CLOCK_NAMES = frozenset({"time", "time_ns"})
# (relative path, line) -> justification.  Only non-ordered, non-width uses
# may be listed here; none exist today.
ALLOWED_DIRECT_WALL_CLOCK: dict[tuple[str, int], str] = {}
NATIVE_SOURCES = (
    "deploy/native_gst_probe/vast_native_gst_probe.cpp",
    "deploy/native_gst_probe/checkpoint_source_coordinator.cpp",
)
NATIVE_CLOCK_HEADER = "deploy/native_gst_probe/checkpoint_admission_transport.hpp"
KNOWN_NATIVE_DOCKERFILES = frozenset({
    "deploy/deepstream/checkpoint/Dockerfile.runtime",
    "deploy/gstreamer_custom/publication/Dockerfile",
    "deploy/native_gst_probe/Dockerfile.deepstream",
    "deploy/native_gst_probe/Dockerfile.openvino",
    "deploy/native_gst_probe/Dockerfile.savant",
    "deploy/openvino_gva/publication/Dockerfile",
})


def direct_wall_clock_uses(root: Path, relative: str) -> list[str]:
    tree = ast.parse((root / relative).read_bytes(), filename=relative)
    aliases: set[str] = set()
    found: list[tuple[int, str]] = []
    imports_shared_clock = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            aliases.update(alias.asname or alias.name for alias in node.names if alias.name == "time")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "time":
                found.extend(
                    (node.lineno, f"from time import {alias.name}")
                    for alias in node.names if alias.name in WALL_CLOCK_NAMES or alias.name == "*"
                )
            elif node.module == CLOCK_MODULE and any(alias.name == "wall_time_ns" for alias in node.names):
                imports_shared_clock = True
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute) and node.attr in WALL_CLOCK_NAMES
            and isinstance(node.value, ast.Name) and node.value.id in aliases
        ):
            found.append((node.lineno, f"{node.value.id}.{node.attr}"))
    violations = [
        f"{relative}:{line}: {text}" for line, text in sorted(found)
        if (relative, line) not in ALLOWED_DIRECT_WALL_CLOCK
    ]
    if not imports_shared_clock:
        violations.append(f"{relative}: does not import wall_time_ns from {CLOCK_MODULE}")
    return violations


def _copy_sources(dockerfile: Path) -> set[str]:
    logical: list[str] = []
    pending = ""
    for line in dockerfile.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1] + " "
            continue
        logical.append(pending + stripped)
        pending = ""
    if pending:
        logical.append(pending)
    sources: set[str] = set()
    for instruction in logical:
        words = instruction.split()
        if words and words[0].upper() == "COPY":
            arguments = [word for word in words[1:] if not word.startswith("--")]
            sources.update(arguments[:-1])
    return sources


def native_dockerfiles_missing_clock_header(root: Path) -> tuple[set[str], list[str]]:
    builders: set[str] = set()
    missing: list[str] = []
    for directory, _directories, files in os.walk(root / "deploy"):
        for name in sorted(files):
            if not name.startswith("Dockerfile"):
                continue
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            text = path.read_text(encoding="utf-8")
            if not any(source in text for source in NATIVE_SOURCES):
                continue
            builders.add(relative)
            if NATIVE_CLOCK_HEADER not in _copy_sources(path):
                missing.append(relative)
    return builders, sorted(missing)


class LegacyWallClockStaticGateV1Tests(unittest.TestCase):
    def test_covered_runtimes_stamp_wall_time_only_through_the_shared_clock(self) -> None:
        violations = [
            violation
            for relative in COVERED_RUNTIME_FILES
            for violation in direct_wall_clock_uses(ROOT, relative)
        ]
        self.assertEqual(violations, [])

    def test_every_native_probe_dockerfile_copies_the_wall_clock_header(self) -> None:
        builders, missing = native_dockerfiles_missing_clock_header(ROOT)
        self.assertLessEqual(KNOWN_NATIVE_DOCKERFILES, builders)
        self.assertEqual(missing, [])

    def test_gate_reports_injected_direct_clock_and_missing_header(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = COVERED_RUNTIME_FILES[0]
            (root / relative).parent.mkdir(parents=True)
            source = (ROOT / relative).read_text(encoding="utf-8")
            (root / relative).write_text(
                source + "\nfrom time import time_ns\n\ndef _raw() -> int:\n    return time.time_ns()\n",
                encoding="utf-8",
            )
            violations = direct_wall_clock_uses(root, relative)
            self.assertEqual(len(violations), 2, violations)
            dockerfile = root / "deploy/native_gst_probe/Dockerfile.savant"
            dockerfile.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "deploy/native_gst_probe/Dockerfile.savant", dockerfile)
            self.assertEqual(native_dockerfiles_missing_clock_header(root)[1], [])
            dockerfile.write_text(
                "\n".join(
                    line for line in dockerfile.read_text(encoding="utf-8").splitlines()
                    if NATIVE_CLOCK_HEADER not in line
                ) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                native_dockerfiles_missing_clock_header(root)[1],
                ["deploy/native_gst_probe/Dockerfile.savant"],
            )


if __name__ == "__main__":
    unittest.main()
