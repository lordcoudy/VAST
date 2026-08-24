from __future__ import annotations

import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = ROOT / "deploy/windows_replay_broker/replay_broker_prepared_handles_v4.hpp"
SOURCE = ROOT / "deploy/windows_replay_broker/replay_broker_prepared_handles_v4.cpp"
CPP_TEST = ROOT / "tests/cpp/replay_broker_prepared_handles_v4_test.cpp"
CMAKE = ROOT / "CMakeLists.txt"
OBSERVATION_BRIDGE = ROOT / (
    "deploy/windows_replay_broker/"
    "replay_broker_prepared_handles_observation_bridge_v4.hpp"
)


class ReplayBrokerPreparedHandlesV4Tests(unittest.TestCase):
    def production_text(self) -> str:
        self.assertTrue(HEADER.is_file())
        self.assertTrue(SOURCE.is_file())
        return HEADER.read_text(encoding="utf-8") + SOURCE.read_text(encoding="utf-8")

    def test_bounded_default_off_target_exists(self) -> None:
        self.assertTrue(HEADER.is_file())
        self.assertTrue(SOURCE.is_file())
        self.assertTrue(CPP_TEST.is_file())
        cmake = CMAKE.read_text(encoding="utf-8")
        self.assertIn("option(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES", cmake)
        self.assertIn("option(VAST_BUILD_REPLAY_BROKER_PREPARED_HANDLES_TESTS", cmake)
        self.assertIn("add_library(vast_replay_broker_prepared_handles_v4 STATIC", cmake)
        self.assertIn("add_test(NAME vast_replay_broker_prepared_handles_v4_test", cmake)
        self.assertIn("/W4 /WX /permissive- /EHsc /utf-8", cmake)

    def test_scope_is_prepared_only_and_never_executes(self) -> None:
        text = self.production_text()
        for required in (
            "PreparedHandleState", "prepared_os_handles_validated",
            "DuplicateHandle", "PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
            "STARTF_USESTDHANDLES", "NtQueryObject", "GrantedAccess",
            "GetFileInformationByHandleEx", "GetNamedPipeInfo",
            "pairwise_distinct_kernel_objects", "duplicate_endpoint_object",
            "artifact_file_bytes_identity_validated",
            "artifact_semantic_identity_validated",
        ):
            self.assertIn(required, text)
        for forbidden in (
            "CreateProcessW", "CreateProcessAsUser", "ResumeThread",
            "CreateJobObject", "Fwpm", "Wfp", "FilterConnectCommunicationPort",
            "minifilter", "publication_matrix", "launcher_output_receipt_protocol_ready",
        ):
            self.assertNotIn(forbidden, text)
        self.assertNotRegex(text, re.compile(r"\bsealed\b", re.IGNORECASE))

    def test_narrow_claims_do_not_authorize_or_validate_bytes(self) -> None:
        text = self.production_text()
        for claim in (
            "artifact_file_bytes_identity_validated",
            "artifact_semantic_identity_validated",
            "inherited_handle_allowlist_validated",
            "ambient_inheritable_handles_absent_validated",
            "process_created", "process_executed", "execution_authorized",
        ):
            self.assertRegex(text, rf"static constexpr bool {claim}\s*=\s*false;")
        for claim in (
            "original_handle_flags_point_in_time_validated",
            "os_handle_endpoint_shape_point_in_time_validated",
            "broker_owned_duplicate_set_point_in_time_validated",
            "prepared_standard_handle_mapping_constructed",
        ):
            self.assertRegex(text, rf"static constexpr bool {claim}\s*=\s*true;")

    def test_access_query_layout_has_compile_and_runtime_guards(self) -> None:
        text = self.production_text()
        self.assertIn("PublicObjectBasicInformation", text)
        self.assertIn("static_assert(sizeof(PublicObjectBasicInformation) == 56", text)
        self.assertIn("static_assert(offsetof(PublicObjectBasicInformation, GrantedAccess) == 4", text)
        self.assertRegex(text, r"return_length\s*!=\s*sizeof\(PublicObjectBasicInformation\)")

    def test_ownership_transfer_does_not_mutate_handle_flags(self) -> None:
        text = self.production_text()
        self.assertIn("GetHandleInformation", text)
        self.assertIn("take_exclusive", text)
        self.assertNotIn("SetHandleInformation", text)

    def test_observation_seed_has_exact_nonowning_lifetime_contract(self) -> None:
        text = OBSERVATION_BRIDGE.read_text(encoding="utf-8")
        for invariant in (
            "non-owning",
            "never call CloseHandle",
            "keep the current PreparedOsHandleSet PIMPL owner alive",
            "must not move or move-assign that owner",
            "destroys or move-assigns its PIMPL",
        ):
            self.assertIn(invariant, text)


if __name__ == "__main__":
    unittest.main()
