"""Every image build input must carry an explicit line-ending rule (R5/S5).

A fresh ``core.autocrlf=true`` checkout converted four new image inputs to CRLF
because they had no exact-path rule, so the rebuilt images were not
reproducible from such a checkout.  Each file listed by an image allowlist,
every image Dockerfile and the two image registries must resolve to either
``text eol=lf`` or ``-text`` through ``.gitattributes``.
"""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
REGISTRIES = ("configs/publication_image_build_v1.json", "configs/publication_qualification_image_refreeze_v1.json")


def image_inputs() -> list[str]:
    paths = set(REGISTRIES)
    for allow in ROOT.glob("deploy/**/*allowlist*.txt"):
        paths.add(allow.relative_to(ROOT).as_posix())
        for line in allow.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and (ROOT / line).is_file():
                paths.add(line)
    paths.update(path.relative_to(ROOT).as_posix() for path in ROOT.glob("deploy/**/Dockerfile*"))
    return sorted(paths)


def unprotected(paths: list[str]) -> list[str]:
    result = subprocess.run(["git", "-C", str(ROOT), "check-attr", "text", "eol", "--", *paths],
                            capture_output=True, text=True, check=True)
    attrs: dict[str, dict[str, str]] = {}
    for line in result.stdout.splitlines():
        path, name, value = line.rsplit(": ", 2)
        attrs.setdefault(path, {})[name] = value
    return [path for path in paths
            if not (attrs[path].get("text") == "unset" or (attrs[path].get("text") == "set" and attrs[path].get("eol") == "lf"))]


@unittest.skipIf(shutil.which("git") is None or not (ROOT / ".git").exists(), "git checkout unavailable")
class ImageInputEolRulesTests(unittest.TestCase):
    def test_every_image_input_has_an_explicit_line_ending_rule(self):
        paths = image_inputs()
        self.assertGreater(len(paths), 100)
        self.assertEqual(unprotected(paths), [])


if __name__ == "__main__":
    unittest.main()
