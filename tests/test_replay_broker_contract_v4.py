from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
HEADER = ROOT / "deploy/windows_replay_broker/replay_broker_contract_v4.hpp"
SOURCE = ROOT / "deploy/windows_replay_broker/replay_broker_contract_v4.cpp"
CPP_TEST = ROOT / "tests/cpp/replay_broker_contract_v4_test.cpp"
CMAKE = ROOT / "CMakeLists.txt"
PIN = "e6c81cb0019a4103b86dfaa5585da868bd72484198e83381de7b5456e66fad88"
ROLES = ("runner_entrypoint_read", "runner_authority_read",
         "validator_authority_read", "validation_request_read",
         "raw_evidence_read", "runtime_closure_bundle_read", "challenge_read",
         "stdin_eof_read", "record_stdout_write", "acknowledgement_stderr_write")
CLAIMS = ("atomic_runtime_closure_snapshot_validated",
          "inherited_handle_allowlist_validated", "standard_handle_mapping_validated",
          "handle_sealing_validated", "child_path_reopen_prevented",
          "native_broker_implemented", "broker_state_machine_enforced",
          "challenge_delivery_validated", "challenge_freshness_validated",
          "stdout_integrity_validated", "lease_enforcement_validated",
          "sandbox_enforcement_validated", "process_executed",
          "validation_records_authenticated", "execution_authorized",
          "expected_record_parent_isolation_validated",
          "native_image_handle_binding_validated",
          "filesystem_write_policy_enforced", "network_policy_enforced")

class ReplayBrokerContractV4Tests(unittest.TestCase):
    def production_text(self) -> str:
        self.assertTrue(HEADER.is_file())
        self.assertTrue(SOURCE.is_file())
        return HEADER.read_text(encoding="utf-8") + SOURCE.read_text(encoding="utf-8")

    def test_files_and_bounded_target_exist(self) -> None:
        self.assertTrue(HEADER.is_file())
        self.assertTrue(SOURCE.is_file())
        self.assertTrue(CPP_TEST.is_file())
        cmake = CMAKE.read_text(encoding="utf-8")
        self.assertIn("option(VAST_BUILD_REPLAY_BROKER_CONTRACT", cmake)
        self.assertIn("option(VAST_BUILD_REPLAY_BROKER_CONTRACT_TESTS", cmake)
        self.assertIn("add_library(vast_replay_broker_contract_v4 STATIC", cmake)
        self.assertIn("add_test(NAME vast_replay_broker_contract_v4_test", cmake)
        self.assertIn("TIMEOUT 30", cmake)
        self.assertIn("/W4 /WX /permissive- /EHsc /utf-8", cmake)

    def test_contract_is_pure_structural_and_nonauthorizing(self) -> None:
        text = self.production_text()
        for required in (PIN, "LogicalBindingCandidate", "BindingState::unvalidated",
                         "BindingState::logically_bound", "OpaqueHandleToken",
                         "std::array<std::string, 21> logical_argv_projection"):
            self.assertIn(required, text)
        self.assertNotRegex(text, re.compile(r"\bHANDLE\b"))
        for forbidden in ("BCrypt", "CreateProcess", "CreateFile", "ReadFile",
                          "WriteFile", "<filesystem>", "<fstream>", "<iostream>",
                          "std::hash", "expected_record_sha256",
                          "expected_record_bytes",
                          "broker_authority_semantic_sha256", "handle_abi_sha256",
                          "wfp_policy_sha256", "filesystem_minifilter_policy_sha256"):
            self.assertNotIn(forbidden, text)

    def test_exact_roles_and_immutable_false_claim_surface(self) -> None:
        text = self.production_text()
        self.assertEqual(10, len(ROLES))
        for role in ROLES:
            self.assertIn(f'"{role}"', text)
        for claim in CLAIMS:
            self.assertRegex(text, rf"static constexpr bool {claim}\s*=\s*false;")
        self.assertNotRegex(text, re.compile(r"set_[A-Za-z0-9_]*claim"))

    def test_only_two_logical_states_are_declared(self) -> None:
        header = HEADER.read_text(encoding="utf-8")
        match = re.search(r"enum class BindingState\s*\{([^}]*)\}", header)
        self.assertIsNotNone(match)
        states = [part.strip() for part in match.group(1).split(",") if part.strip()]
        self.assertEqual(["unvalidated", "logically_bound"], states)

if __name__ == "__main__":
    unittest.main()
