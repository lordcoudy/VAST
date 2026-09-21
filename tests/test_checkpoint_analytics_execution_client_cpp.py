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
    def test_native_client_regression(self) -> None:
        compiler = shutil.which("c++") or shutil.which("g++")
        pkg_config = shutil.which("pkg-config")
        self.assertIsNotNone(compiler, "a C++17 compiler is required")
        self.assertIsNotNone(pkg_config, "pkg-config is required")
        glib = subprocess.run(
            [pkg_config, "--cflags", "--libs", "glib-2.0"],
            check=True,
            capture_output=True,
            text=True,
        )
        source = ROOT / "tests" / "cpp" / "checkpoint_analytics_execution_client_test.cpp"
        include_dir = ROOT / "deploy" / "native_gst_probe"
        with tempfile.TemporaryDirectory(prefix="vast-native-client-test-") as build_dir:
            binary = Path(build_dir) / "checkpoint_analytics_execution_client_test"
            compile_result = subprocess.run(
                [
                    compiler,
                    "-std=c++17",
                    "-O2",
                    "-pthread",
                    "-I",
                    str(include_dir),
                    str(source),
                    *shlex.split(glib.stdout),
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


if __name__ == "__main__":
    unittest.main()
