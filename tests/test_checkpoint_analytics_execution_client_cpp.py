from __future__ import annotations

import re
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

    def test_admission_transport_original_deadline(self) -> None:
        self._compile_and_run("checkpoint_admission_transport_test.cpp", ("glib-2.0",))

    def test_native_event_pipe_original_deadline(self) -> None:
        self._compile_and_run("checkpoint_runtime_emitter_deadline_test.cpp", ("glib-2.0",))

    def test_source_original_drain_and_stop_latch(self) -> None:
        self._compile_and_run("checkpoint_source_lifecycle_test.cpp",
                              ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-video-1.0"))

    def test_native_study_common_original_geometry_prefix(self) -> None:
        self._compile_and_run("checkpoint_native_study_prefix_test.cpp",
                              ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-rtp-1.0", "gstreamer-video-1.0"))

    def test_study_reference_actual_software_eos_and_deadline(self) -> None:
        self._compile_and_run("checkpoint_study_reference_test.cpp",
                              ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-video-1.0"))

    def test_native_abort_precedes_gstreamer_null(self) -> None:
        self._compile_and_run("checkpoint_native_shutdown_test.cpp",
                              ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-rtp-1.0", "gstreamer-video-1.0"))

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

    def test_native_execution_request_is_guardian_canonical_json(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from analytics_execution_protocol import parse_canonical_json

        compiler = shutil.which("c++") or shutil.which("g++")
        pkg_config = shutil.which("pkg-config")
        self.assertIsNotNone(compiler, "a C++17 compiler is required")
        self.assertIsNotNone(pkg_config, "pkg-config is required")
        flags = subprocess.run(
            [pkg_config, "--cflags", "--libs", "glib-2.0"],
            check=True, capture_output=True, text=True,
        )
        source = ROOT / "tests" / "cpp" / "checkpoint_analytics_execution_client_canonical_probe.cpp"
        with tempfile.TemporaryDirectory(prefix="vast-native-canonical-") as build_dir:
            binary = Path(build_dir) / source.stem
            compiled = subprocess.run(
                [compiler, "-std=c++17", "-O2", "-pthread",
                 "-I", str(ROOT / "deploy" / "native_gst_probe"), str(source),
                 *shlex.split(flags.stdout), "-o", str(binary)],
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(binary)], capture_output=True, timeout=120)
            self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
        request = parse_canonical_json(run.stdout)
        self.assertEqual(request["message_type"], "analytics_execute")
        self.assertEqual(request["frame"]["branch"], "damage")

    def test_native_execution_device_id_regression(self) -> None:
        self._compile_and_run("checkpoint_analytics_execution_device_id_test.cpp", ("glib-2.0",))

    def test_native_execution_deadline_is_the_deepstream_transport_bound(self) -> None:
        sys.path.insert(0, str(ROOT / "scripts"))
        from checkpoint_deepstream_protocol_adapter import (
            ANALYTICS_EXECUTION_TRANSPORT_TIMEOUT_NS,
        )

        source = (ROOT / "deploy" / "native_gst_probe" / "vast_native_gst_probe.cpp").read_text(
            encoding="utf-8"
        )
        match = re.search(
            r"constexpr std::uint64_t kCheckpointAnalyticsExecutionTransportTimeoutNs = "
            r"([0-9']+)ULL;",
            source,
        )
        self.assertIsNotNone(match)
        self.assertEqual(
            int(match.group(1).replace("'", "")), ANALYTICS_EXECUTION_TRANSPORT_TIMEOUT_NS
        )
        # The policy deadline must not become the worker's execution deadline.
        self.assertIn(
            "const std::uint64_t deadline_ns = kCheckpointAnalyticsExecutionTransportTimeoutNs;",
            source,
        )
        self.assertNotIn("self->args_.deadline_ms * 1'000'000.0", source)

    def test_native_policy_client_regression(self) -> None:
        self._compile_and_run("checkpoint_native_policy_client_test.cpp", ("glib-2.0",))

    def test_native_policy_identity_regression(self) -> None:
        self._compile_and_run(
            "checkpoint_native_policy_identity_test.cpp",
            ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-rtp-1.0", "gstreamer-video-1.0"),
        )

    def test_native_stage_artifact_regression(self) -> None:
        self._compile_and_run(
            "checkpoint_native_stage_artifact_test.cpp",
            ("gstreamer-1.0", "gstreamer-app-1.0", "gstreamer-rtp-1.0", "gstreamer-video-1.0"),
        )


if __name__ == "__main__":
    unittest.main()
