"""Native publication images must ship every local header their compiled sources include.

PR5 added ``checkpoint_study_reference.hpp`` to the probe; the DeepStream and
Savant native Dockerfiles/allowlists did not copy it, so the stock legacy native
build failed with a missing-header compile error.  This stdlib check follows
quoted ``#include`` directives from every COPY'd ``.cpp`` and requires each
reachable repository header to be both COPY'd by the Dockerfile and listed in
the image source allowlist.
"""
from __future__ import annotations

from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "deploy/native_gst_probe"
IMAGES = {"Dockerfile.deepstream": "deepstream", "Dockerfile.openvino": "openvino", "Dockerfile.savant": "savant"}
COPY = re.compile(r"^COPY\s+(?!--from)(\S+)\s+\S+", re.MULTILINE)
INCLUDE = re.compile(r'^\s*#\s*include\s+"([^"]+)"', re.MULTILINE)


def reachable_headers(source: Path, seen: set[str]) -> set[str]:
    for name in INCLUDE.findall(source.read_text(encoding="utf-8", errors="replace")):
        path = (source.parent / name).resolve()
        if path.is_file() and path.is_relative_to(ROOT):
            relative = path.relative_to(ROOT).as_posix()
            if relative not in seen:
                seen.add(relative)
                reachable_headers(path, seen)
    return seen


def include_closure_gaps(dockerfile_text: str, allowlist_text: str) -> list[str]:
    copied = set(COPY.findall(dockerfile_text))
    listed = {line.strip() for line in allowlist_text.splitlines() if line.strip() and not line.startswith("#")}
    needed: set[str] = set()
    for source in sorted(path for path in copied if path.endswith(".cpp")):
        reachable_headers(ROOT / source, needed)
    return sorted([f"not copied: {path}" for path in needed - copied] +
                  [f"not allowlisted: {path}" for path in needed - listed])


class NativeImageIncludeClosureTests(unittest.TestCase):
    def test_every_reachable_local_header_is_copied_and_allowlisted(self):
        for dockerfile, image in IMAGES.items():
            with self.subTest(image=image):
                gaps = include_closure_gaps((NATIVE / dockerfile).read_text(encoding="utf-8"),
                                            (NATIVE / "publication" / f"{image}-source-allowlist.txt").read_text(encoding="utf-8"))
                self.assertEqual(gaps, [])

    def test_checker_reports_a_missing_header(self):
        text = (NATIVE / "Dockerfile.openvino").read_text(encoding="utf-8")
        allow = (NATIVE / "publication/openvino-source-allowlist.txt").read_text(encoding="utf-8")
        line = "deploy/native_gst_probe/checkpoint_study_reference.hpp"
        stripped = "\n".join(row for row in text.splitlines() if line not in row)
        self.assertIn(f"not copied: {line}", include_closure_gaps(stripped, allow))


if __name__ == "__main__":
    unittest.main()
