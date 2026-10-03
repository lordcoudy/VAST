from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = ROOT / (
    "deploy/windows_replay_broker/"
    "replay_broker_artifact_bytes_observation_v4.hpp"
)
SOURCE = ROOT / (
    "deploy/windows_replay_broker/"
    "replay_broker_artifact_bytes_observation_v4.cpp"
)
CPP_TEST = ROOT / "tests/cpp/replay_broker_artifact_bytes_observation_v4_test.cpp"
CMAKE = ROOT / "CMakeLists.txt"


class ReplayBrokerArtifactBytesObservationV4Tests(unittest.TestCase):
    def production_text(self) -> str:
        self.assertTrue(HEADER.is_file())
        self.assertTrue(SOURCE.is_file())
        return HEADER.read_text(encoding="utf-8") + SOURCE.read_text(encoding="utf-8")

    def test_default_off_windows_x64_target_is_dependency_closed(self) -> None:
        self.assertTrue(CPP_TEST.is_file())
        cmake = CMAKE.read_text(encoding="utf-8")
        self.assertIn(
            "option(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION", cmake
        )
        self.assertIn(
            "option(VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTS",
            cmake,
        )
        self.assertIn(
            "VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION requires "
            "VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES",
            cmake,
        )
        self.assertIn(
            "VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION_TESTS requires "
            "VAST_BUILD_REPLAY_BROKER_ARTIFACT_BYTES_OBSERVATION",
            cmake,
        )
        self.assertIn(
            "add_library(vast_replay_broker_artifact_bytes_observation_v4 STATIC",
            cmake,
        )
        self.assertIn(
            "add_test(NAME vast_replay_broker_artifact_bytes_observation_v4_test",
            cmake,
        )
        self.assertRegex(
            cmake,
            re.compile(
                r"target_link_libraries\("
                r"vast_replay_broker_artifact_bytes_observation_v4\s+"
                r"PUBLIC\s+vast_replay_broker_prepared_handles_v4\s+"
                r"PRIVATE\s+bcrypt\s*\)",
                re.MULTILINE,
            ),
        )

    def test_scope_is_synchronous_handle_relative_observation_only(self) -> None:
        text = self.production_text()
        for required in (
            "observe_artifact_bytes",
            "ArtifactBytesObservedPreparedOsHandleSet",
            "ReOpenFile",
            "FILE_READ_DATA | FILE_READ_ATTRIBUTES | SYNCHRONIZE",
            "FILE_SHARE_READ",
            "FILE_FLAG_SEQUENTIAL_SCAN",
            "SetFilePointerEx",
            "ReadFile",
            "BCryptOpenAlgorithmProvider",
            "BCRYPT_SHA256_ALGORITHM",
            "MS_PRIMITIVE_PROVIDER",
            "BCryptHashData",
            "BCryptFinishHash",
            "GetFileInformationByHandleEx",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "NtQueryInformationFile",
            "FilePositionInformation",
            "FileModeInformation",
            "IO_STATUS_BLOCK",
            "FILE_FLAG_OVERLAPPED",
            "OVERLAPPED",
            "ReadFileEx",
            "CreateFileW",
            "DuplicateHandle",
            "CreateProcessW",
            "CreateProcessAsUser",
            "ResumeThread",
            "publication_matrix",
            "launcher_output_receipt_protocol_ready",
            "PUBLICATION_READY",
        ):
            self.assertNotIn(forbidden, text)

    def test_claims_are_exactly_point_in_time_and_nonauthorizing(self) -> None:
        text = self.production_text()
        for claim in (
            "artifact_file_bytes_sha256_point_in_time_validated",
            "all_six_expected_length_byte_sequences_observed",
            "handle_relative_reopen_used",
            "separate_reopened_file_objects_used_for_reads",
            "pre_post_identity_metadata_stable_point_in_time",
            "results_published_all_or_none",
            "prepared_handle_custody_retained",
        ):
            self.assertRegex(text, rf"static constexpr bool {claim}\s*=\s*true;")
        for claim in (
            "artifact_semantic_identity_validated",
            "source_bytes_immutable_validated",
            "atomic_six_artifact_snapshot_validated",
            "coherent_cross_artifact_snapshot_validated",
            "mutation_impossible_validated",
            "digest_binds_future_child_consumption",
            "bounded_completion_latency_validated",
            "inherited_handle_allowlist_validated",
            "ambient_inheritable_handles_absent_validated",
            "process_created",
            "process_executed",
            "execution_authorized",
        ):
            self.assertRegex(text, rf"static constexpr bool {claim}\s*=\s*false;")

    def test_no_production_consumer_or_readiness_path_exists(self) -> None:
        allowed = {
            HEADER.resolve(),
            SOURCE.resolve(),
            CPP_TEST.resolve(),
            pathlib.Path(__file__).resolve(),
            CMAKE.resolve(),
        }
        needles = (
            "replay_broker_artifact_bytes_observation_v4",
            "observe_artifact_bytes",
        )
        unexpected: list[str] = []
        for candidate in ROOT.rglob("*"):
            if not candidate.is_file() or candidate.resolve() in allowed:
                continue
            if any(part in {".git", "build", "__pycache__", ".pytest_cache"}
                   for part in candidate.parts):
                continue
            try:
                content = candidate.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            if any(needle in content for needle in needles):
                unexpected.append(str(candidate.relative_to(ROOT)))
        self.assertEqual(unexpected, [])


if __name__ == "__main__":
    unittest.main()
