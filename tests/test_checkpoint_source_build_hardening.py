from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class CheckpointSourceBuildHardeningTests(unittest.TestCase):
    def test_release_hardening_is_target_scoped_and_exact(self) -> None:
        source = (ROOT / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn(
            'option(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE\n'
            '  "Build a fail-closed hardened checkpoint source trust candidate" OFF)',
            source,
        )
        self.assertIn(
            "if(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE AND\n"
            "   NOT VAST_BUILD_NATIVE_GST_PROBE)",
            source,
        )
        self.assertIn(
            '"VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE requires '
            'VAST_BUILD_NATIVE_GST_PROBE"',
            source,
        )
        self.assertIn(
            "if(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE)\n"
            "      message(FATAL_ERROR\n"
            '        "checkpoint source trust candidate requires GStreamer development packages")',
            source,
        )
        match = re.search(
            r"add_executable\(vast_checkpoint_source\b(?P<body>.*?)"
            r"target_link_libraries\(vast_checkpoint_source\b(?P<tail>.*?)\n\s*\)",
            source,
            re.DOTALL,
        )
        self.assertIsNotNone(match)
        checkpoint_block = match.group(0)
        for required in (
            "if(VAST_BUILD_CHECKPOINT_SOURCE_TRUST_CANDIDATE)",
            "CMAKE_CONFIGURATION_TYPES",
            'CMAKE_BUILD_TYPE STREQUAL "Release"',
            "single-config Release",
            'CMAKE_SYSTEM_NAME STREQUAL "Linux"',
            'CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|amd64|AMD64)$"',
            'CMAKE_CXX_COMPILER_ID STREQUAL "GNU"',
            'CMAKE_CXX_COMPILER_VERSION VERSION_GREATER_EQUAL "13.0"',
            'CMAKE_CXX_COMPILER_VERSION VERSION_LESS "14.0"',
            "check_cxx_compiler_flag",
            "check_linker_flag",
            "checkpoint source hardening requires",
            "target_compile_options(vast_checkpoint_source PRIVATE",
            "$<$<CONFIG:Release>:-O2>",
            "$<$<CONFIG:Release>:-fstack-protector-strong>",
            "$<$<CONFIG:Release>:-D_FORTIFY_SOURCE=3>",
            "$<$<CONFIG:Release>:-fPIE>",
            "$<$<CONFIG:Release>:-fcf-protection=full>",
            "target_link_options(vast_checkpoint_source PRIVATE",
            "$<$<CONFIG:Release>:-Wl,-z,relro>",
            "$<$<CONFIG:Release>:-Wl,-z,now>",
            "$<$<CONFIG:Release>:-Wl,-z,noexecstack>",
            "$<$<CONFIG:Release>:-pie>",
        ):
            self.assertIn(required, checkpoint_block)

        for weakening in (
            "-fno-stack-protector",
            "-U_FORTIFY_SOURCE",
            "-fcf-protection=none",
            "-no-pie",
            "-Wl,-z,lazy",
            "-Wl,-z,norelro",
            "-Wl,-z,execstack",
        ):
            self.assertNotIn(weakening, checkpoint_block)

        prefix = source[: match.start()]
        self.assertNotIn("CMAKE_CXX_FLAGS", prefix)
        self.assertNotIn("CMAKE_EXE_LINKER_FLAGS", prefix)


if __name__ == "__main__":
    unittest.main()
