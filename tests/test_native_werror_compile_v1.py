"""Repository C++ sources compiled with -Werror in runtime images must compile warning-free.

The DeepStream runtime image builds ``checkpoint_source_coordinator.cpp`` with
``-Wall -Wextra -Werror``.  PR5's ``checkpoint_study_reference.hpp`` broke that
build (misleading-indentation, missing-field-initializers) although hosted CI
compiles the same sources without -Werror.  This test reads every ``g++ ...
-Werror`` RUN step of the runtime Dockerfiles, takes the repository sources it
compiles from ``/tmp/vast-source-build`` and checks them with the same warning
flags (syntax only) against the local GStreamer headers.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILES = (ROOT / "deploy/deepstream/checkpoint/Dockerfile.runtime",)
PACKAGES = ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-rtp-1.0", "gstreamer-video-1.0")


def werror_sources(text: str) -> list[tuple[str, list[str]]]:
    jobs = []
    for command in re.split(r"&&|\bRUN\b", text.replace("\\\n", " ")):
        if "g++" in command and "-Werror" in command:
            flags = [flag for flag in command.split() if flag.startswith(("-std=", "-W", "-O", "-pthread"))]
            jobs += [(source, flags) for source in re.findall(r"/tmp/vast-source-build/(\S+\.cpp)", command)]
    return jobs


class NativeWerrorCompileTests(unittest.TestCase):
    def test_runtime_dockerfiles_compile_repository_sources_with_werror(self):
        jobs = [job for dockerfile in DOCKERFILES for job in werror_sources(dockerfile.read_text(encoding="utf-8"))]
        self.assertIn("deploy/native_gst_probe/checkpoint_source_coordinator.cpp", [source for source, _ in jobs])
        if shutil.which("g++") is None or shutil.which("pkg-config") is None:
            self.skipTest("g++/pkg-config unavailable")
        cflags = subprocess.run(["pkg-config", "--cflags", *PACKAGES], capture_output=True, text=True)
        if cflags.returncode:
            self.skipTest("GStreamer development headers unavailable")
        for source, flags in jobs:
            with self.subTest(source=source):
                result = subprocess.run(["g++", *flags, "-fsyntax-only", *cflags.stdout.split(), str(ROOT / source)],
                                        capture_output=True, text=True, timeout=300)
                self.assertEqual(result.returncode, 0, result.stderr[-4000:])


if __name__ == "__main__":
    unittest.main()
