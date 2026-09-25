from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform.startswith("linux"), "native memfd regression requires Linux")
class CheckpointAnalyticsExecutionClientCppTest(unittest.TestCase):
    def _compile_and_run(self, source_name: str, packages: tuple[str, ...]) -> None:
        compiler = shutil.which("c++") or shutil.which("g++")
        pkg_config = shutil.which("pkg-config")
        self.assertIsNotNone(compiler, "a C++17 compiler is required")
        self.assertIsNotNone(pkg_config, "pkg-config is required")
        flags = subprocess.run(
            [pkg_config, "--cflags", "--libs", *packages],
            check=True,
            capture_output=True,
            text=True,
        )
        source = ROOT / "tests" / "cpp" / source_name
        include_dir = ROOT / "deploy" / "native_gst_probe"
        with tempfile.TemporaryDirectory(prefix="vast-native-client-test-") as build_dir:
            binary = Path(build_dir) / source.stem
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O2",
                    "-pthread",
                    "-I",
                    str(include_dir),
                    str(source),
                    *shlex.split(flags.stdout),
                    "-o",
                    str(binary),
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(
                compile_result.returncode,
                0,
                compile_result.stdout + compile_result.stderr,
            )
            run_result = subprocess.run(
                [str(binary)], capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(
                run_result.returncode,
                0,
                run_result.stdout + run_result.stderr,
            )

    def test_native_client_regression(self) -> None:
        self._compile_and_run("checkpoint_analytics_execution_client_test.cpp", ("glib-2.0",))

    def test_native_policy_topology_regression(self) -> None:
        self._compile_and_run(
            "checkpoint_native_policy_topology_test.cpp",
            ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-rtp-1.0", "gstreamer-video-1.0"),
        )

    def test_native_reset_queue_level_regression(self) -> None:
        self._compile_and_run(
            "checkpoint_native_reset_queue_level_test.cpp",
            ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-rtp-1.0", "gstreamer-video-1.0"),
        )


if __name__ == "__main__":
    unittest.main()
