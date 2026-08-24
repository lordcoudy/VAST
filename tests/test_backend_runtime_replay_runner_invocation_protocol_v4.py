from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_runtime_replay_runner_invocation_protocol_v3 as old_v3  # noqa: E402
import backend_runtime_replay_runner_invocation_protocol_v4 as protocol  # noqa: E402
import backend_runtime_replay_runner_authority_v2 as old_authority_v2  # noqa: E402


PROTOCOL_PREFIX = (
    b"VAST:backend-runtime-replay-runner-invocation-protocol:v4"
)
PROTOCOL_DOMAIN = PROTOCOL_PREFIX + b"\x00"


def protocol_sha(value: object) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(PROTOCOL_DOMAIN + encoded).hexdigest()


def domain_digest(domain: dict[str, str], payload: bytes) -> str:
    prefix = domain["domain_prefix_ascii"].encode("ascii")
    separator = bytes.fromhex(domain["domain_separator_hex"])
    return hashlib.sha256(prefix + separator + payload).hexdigest()


class ReplayRunnerInvocationProtocolV4Tests(unittest.TestCase):
    _DEFAULT = object()

    def setUp(self) -> None:
        self.value = protocol.replay_runner_invocation_protocol_v4_contract()
        self.pin = self.value["protocol_sha256"]

    def validate(self, value=None, pin=_DEFAULT):
        return protocol.validate_replay_runner_invocation_protocol_v4_contract(
            self.value if value is None else value,
            expected_protocol_sha256=self.pin if pin is self._DEFAULT else pin,
        )

    @staticmethod
    def reseal(value):
        unsigned = {
            key: item for key, item in value.items()
            if key != "protocol_sha256"
        }
        value["protocol_sha256"] = protocol_sha(unsigned)
        return value

    def test_exact_closed_contract_and_domain_separated_identity(self) -> None:
        self.assertEqual(set(self.value), {
            "schema_version", "artifact_kind", "status",
            "supported_host_os", "supported_host_architecture",
            "concrete_invocation_header", "semantic_identity_roles",
            "placeholder_roles", "native_broker_abi",
            "child_handle_map_abi", "challenge_channel_abi",
            "acknowledgement_abi", "argv_template",
            "process_contract_template", "parent_only_expected_record_policy",
            "hash_domains", "exact_false_claims", "protocol_sha256",
        })
        self.assertEqual(self.value["schema_version"], 4)
        self.assertEqual(self.value["artifact_kind"], protocol.ARTIFACT_KIND)
        self.assertEqual(self.value["status"], "immutable_protocol_contract")
        self.assertEqual(self.value["supported_host_os"], ["nt"])
        self.assertEqual(self.value["supported_host_architecture"], ["amd64"])
        unsigned = {
            key: item for key, item in self.value.items()
            if key != "protocol_sha256"
        }
        self.assertEqual(self.pin, protocol_sha(unsigned))
        self.assertEqual(self.validate(), self.value)
        second = protocol.replay_runner_invocation_protocol_v4_contract()
        self.assertEqual(second, self.value)
        self.assertIsNot(second, self.value)
        second["argv_template"].append("--mutation")
        self.assertNotEqual(second, self.value)
        hashed = {
            name: item for name, item in self.value["hash_domains"].items()
            if "domain_prefix_ascii" in item
        }
        prefixes = [item["domain_prefix_ascii"] for item in hashed.values()]
        self.assertEqual(len(prefixes), len(set(prefixes)))
        for name, item in hashed.items():
            with self.subTest(domain=name):
                self.assertEqual(item["domain_separator_hex"], "00")
                self.assertEqual(
                    item["prefix_byte_encoding"],
                    "strict_ascii_then_single_nul",
                )
                item["domain_prefix_ascii"].encode("ascii")
                self.assertNotIn("\x00", item["domain_prefix_ascii"])
        self.assertEqual(
            hashed["protocol_identity"]["algorithm"],
            "sha256_domain_prefix_then_canonical_json_utf8",
        )
        for name in (
            "project_root_identity", "nonce_commitment", "stdout_commitment",
        ):
            self.assertEqual(
                hashed[name]["algorithm"],
                "sha256_domain_prefix_then_exact_bytes",
            )
        transcript = self.value["hash_domains"][
            "acknowledgement_transcript"
        ]
        self.assertNotIn("domain_prefix_ascii", transcript)
        self.assertEqual(transcript["frame_prefix_ascii"],
                         "VAST_REPLAY_ACK_V4")
        self.assertEqual(transcript["frame_prefix_byte_encoding"],
                         "strict_ascii")

    def test_hash_domain_known_vectors_and_ack_formula(self) -> None:
        domains = self.value["hash_domains"]
        expected_domains = {
            "project_root_identity": (
                "VAST:backend-runtime-replay-project-root-identity:v4",
                "e6c2909e558deda1dc92394287f30847a2a5aee836a44de990fc62f00749b774",
            ),
            "nonce_commitment": (
                "VAST:backend-runtime-replay-nonce-commitment:v4",
                "aefbcc4698a0e648a61b8a52ae03a27f4b8936efa265a654c7c8db9e320a71a2",
            ),
            "stdout_commitment": (
                "VAST:backend-runtime-replay-stdout-commitment:v4",
                "0184a6f5e327b7975536fbb5236c8faec60ae2191e16001c23828f8679406f88",
            ),
        }
        observed = set()
        for name, (prefix, expected) in expected_domains.items():
            domain = domains[name]
            with self.subTest(domain=name):
                self.assertEqual(domain["domain_prefix_ascii"], prefix)
                independently_computed = hashlib.sha256(
                    prefix.encode("ascii") + b"\x00" + b"abc"
                ).hexdigest()
                self.assertEqual(independently_computed, expected)
                self.assertEqual(domain_digest(domain, b"abc"), expected)
                self.assertNotEqual(expected,
                                    hashlib.sha256(b"abc").hexdigest())
                observed.add(expected)
        self.assertEqual(len(observed), 3)
        self.assertEqual(
            self.value["challenge_channel_abi"]["commitment_output"],
            "nonce_sha256_equals_sha256_domain_prefix_then_exact_bytes",
        )
        ack = self.value["acknowledgement_abi"]
        expected_computation = {
            "nonce_sha256": {
                "hash_domain": "nonce_commitment",
                "algorithm": "sha256_domain_prefix_then_exact_bytes",
                "input": "exact_32_raw_nonce_bytes",
            },
            "stdout_sha256": {
                "hash_domain": "stdout_commitment",
                "algorithm": "sha256_domain_prefix_then_exact_bytes",
                "input": "exact_collected_stdout_bytes",
            },
            "protocol_sha256": {
                "hash_domain": "protocol_identity",
                "algorithm": (
                    "sha256_domain_prefix_then_canonical_json_utf8"
                ),
                "input": "unsigned_protocol_contract",
            },
        }
        self.assertEqual(ack["producer_computation"], expected_computation)
        self.assertEqual(ack["parent_verification"], expected_computation)
        self.assertEqual(
            ack["parent_verification_mode"],
            "independently_recompute_exact_producer_computation",
        )
        for field, computation in expected_computation.items():
            with self.subTest(ack_field=field):
                domain = domains[computation["hash_domain"]]
                self.assertEqual(computation["algorithm"],
                                 domain["algorithm"])
                self.assertEqual(computation["input"], domain["input"])
        unsigned = {
            key: item for key, item in self.value.items()
            if key != "protocol_sha256"
        }
        expected_protocol_sha256 = (
            "e6c81cb0019a4103b86dfaa5585da868bd72484198e83381de7b5456e66fad88"
        )
        self.assertEqual(protocol_sha(unsigned), expected_protocol_sha256)
        self.assertEqual(self.pin, expected_protocol_sha256)
        nonce_sha256 = domain_digest(
            domains["nonce_commitment"], bytes(range(32)),
        )
        stdout_sha256 = domain_digest(domains["stdout_commitment"], b"abc")
        self.assertEqual(
            nonce_sha256,
            "3d1e2f733b1cda05fc7b9aafa3907608c7fb9e1b6016271698055f0150f5ef32",
        )
        self.assertEqual(
            stdout_sha256,
            "0184a6f5e327b7975536fbb5236c8faec60ae2191e16001c23828f8679406f88",
        )
        observed_ack = ack["template"].format(
            session_id="session-A", lease_id="lease-B",
            cell_index_decimal="559", attempt_ordinal_decimal="1",
            nonce_sha256=nonce_sha256, stdout_sha256=stdout_sha256,
            protocol_sha256=expected_protocol_sha256,
        )
        self.assertEqual(observed_ack, (
            "VAST_REPLAY_ACK_V4 session-A lease-B 559 1 "
            "3d1e2f733b1cda05fc7b9aafa3907608c7fb9e1b6016271698055f0150f5ef32 "
            "0184a6f5e327b7975536fbb5236c8faec60ae2191e16001c23828f8679406f88 "
            "e6c81cb0019a4103b86dfaa5585da868bd72484198e83381de7b5456e66fad88\n"
        ))

    def test_exact_header_child_semantic_roles_and_argv(self) -> None:
        self.assertEqual(self.value["concrete_invocation_header"], {
            "schema_version": 4,
            "artifact_kind": (
                "vast_backend_runtime_replay_runner_invocation_contract_v4"
            ),
            "status": "declarative_native_broker_invocation_candidate",
        })
        self.assertEqual(self.value["semantic_identity_roles"], {
            "runner_authority": {
                "artifact_schema_version": 3,
                "artifact_kind": (
                    "vast_backend_runtime_replay_runner_authority_v3"
                ),
            },
            "validator_authority": {
                "artifact_schema_version": 1,
                "artifact_kind": (
                    "vast_backend_runtime_validator_authority_q4"
                ),
            },
            "request": {
                "artifact_schema_version": 2,
                "artifact_kind": (
                    "vast_backend_runtime_validation_replay_request_v2"
                ),
            },
        })
        expected_argv = [
            "vast-replay-native-runner-v4",
            "--protocol-sha256", "{protocol_sha256}",
            "--project-root-identity-sha256",
            "{project_root_identity_sha256}",
            "--session-id", "{session_id}",
            "--lease-id", "{lease_id}",
            "--cell-index", "{cell_index_decimal}",
            "--attempt-ordinal", "{attempt_ordinal_decimal}",
            "--runner-authority-sha256", "{runner_authority_sha256}",
            "--validator-authority-sha256",
            "{validator_authority_sha256}",
            "--request-sha256", "{request_sha256}",
            "--handle-map", "{handle_map_descriptor}",
        ]
        self.assertEqual(self.value["argv_template"], expected_argv)
        joined = " ".join(expected_argv).lower()
        for forbidden in (
            "nonce", "challenge", "expected-record", "expected_record",
            "--project-root ", "_path", "-path",
        ):
            self.assertNotIn(forbidden, joined)
        self.assertEqual(set(self.value["placeholder_roles"]), {
            "protocol_sha256", "project_root_identity_sha256", "session_id",
            "lease_id", "cell_index_decimal", "attempt_ordinal_decimal",
            "runner_authority_sha256", "validator_authority_sha256",
            "request_sha256", "handle_map_descriptor",
        })

    def test_ephemeral_handle_map_has_no_expected_record_or_namespace(self) -> None:
        abi = self.value["child_handle_map_abi"]
        self.assertEqual(abi["schema_version"], 4)
        self.assertEqual(abi["artifact_kind"], protocol.CHILD_HANDLE_MAP_ABI_KIND)
        roles = [item["role"] for item in abi["ordered_roles"]]
        self.assertEqual(roles, [
            "runner_entrypoint_read", "runner_authority_read",
            "validator_authority_read", "validation_request_read",
            "raw_evidence_read", "runtime_closure_bundle_read",
            "challenge_read", "stdin_eof_read", "record_stdout_write",
            "acknowledgement_stderr_write",
        ])
        self.assertNotIn("expected_record_read", roles)
        self.assertFalse(any("directory" in role for role in roles))
        closure = next(
            item for item in abi["ordered_roles"]
            if item["role"] == "runtime_closure_bundle_read"
        )
        self.assertEqual(
            closure["object"],
            "single_immutable_broker_validated_bundle_artifact",
        )
        self.assertEqual(closure["namespace_semantics"], "not_a_namespace")
        representation = abi["runtime_representation"]
        self.assertEqual(representation["number_encoding"],
                         "canonical_unsigned_decimal_u64")
        self.assertTrue(representation["pairwise_distinct"])
        self.assertTrue(representation["process_local_only"])
        self.assertFalse(representation["persisted"])
        self.assertFalse(representation["semantic_hash_input"])
        self.assertEqual(representation["logging"], "forbidden")
        self.assertNotIn("expected_record", representation["grammar_template"])
        self.assertNotIn("path", representation["grammar_template"])
        self.assertEqual(representation["exact_role_count"], 10)
        self.assertEqual(abi["inheritance"]["input_handle_allowlist"],
                         "exactly_all_ten_ordered_roles")
        standard = abi["standard_handle_mapping"]
        self.assertEqual(standard, {
            "STARTF_USESTDHANDLES": True,
            "hStdInput": "stdin_eof_read",
            "hStdOutput": "record_stdout_write",
            "hStdError": "acknowledgement_stderr_write",
            "stdin_eof_parent_action": (
                "close_parent_private_complementary_writer_before_resume"
            ),
            "stdin_child_observation": "immediate_eof",
        })
        self.assertEqual(abi["parent_private_complementary_handles"], [
            "challenge_write", "stdin_eof_write", "record_stdout_read",
            "acknowledgement_stderr_read",
        ])
        self.assertEqual(
            abi["parent_private_complementary_handle_inheritance"],
            "forbidden",
        )
        self.assertEqual(
            abi["parent_private_complementary_handle_map_membership"],
            "forbidden",
        )

    def test_handle_map_descriptor_enforces_exact_roles_and_unique_u64(self) -> None:
        roles = [
            item["role"]
            for item in self.value["child_handle_map_abi"]["ordered_roles"]
        ]
        descriptor = "hmap4;" + ";".join(
            f"{role}={16 + position}" for position, role in enumerate(roles)
        )
        expected = {
            role: 16 + position for position, role in enumerate(roles)
        }
        self.assertEqual(
            protocol.validate_replay_runner_child_handle_map_v4_descriptor(
                descriptor
            ),
            expected,
        )
        malformed = {
            "missing_role": ";".join(descriptor.split(";")[:-1]),
            "role_swap": descriptor.replace(
                "stdin_eof_read=23;record_stdout_write=24",
                "record_stdout_write=24;stdin_eof_read=23",
            ),
            "duplicate_handle": descriptor.replace(
                "record_stdout_write=24", "record_stdout_write=23"
            ),
            "duplicate_role": descriptor.replace(
                "record_stdout_write=24", "stdin_eof_read=24"
            ),
            "zero": descriptor.replace("runner_entrypoint_read=16",
                                       "runner_entrypoint_read=0"),
            "leading_zero": descriptor.replace("runner_entrypoint_read=16",
                                               "runner_entrypoint_read=016"),
            "u64_overflow": descriptor.replace(
                "runner_entrypoint_read=16",
                "runner_entrypoint_read=18446744073709551616",
            ),
            "pseudo_process": descriptor.replace(
                "runner_entrypoint_read=16",
                "runner_entrypoint_read=18446744073709551615",
            ),
        }
        for label, candidate in malformed.items():
            with self.subTest(case=label), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV4Error
            ):
                protocol.validate_replay_runner_child_handle_map_v4_descriptor(
                    candidate
                )
        for invalid_type in (None, True, 1, [descriptor], {"value": descriptor}):
            with self.subTest(value=invalid_type), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV4Error
            ):
                protocol.validate_replay_runner_child_handle_map_v4_descriptor(
                    invalid_type
                )

    def test_windows_broker_state_machine_and_parent_only_policy_pins(self) -> None:
        broker = self.value["native_broker_abi"]
        self.assertEqual(broker["schema_version"], 4)
        self.assertEqual(broker["artifact_kind"], protocol.NATIVE_BROKER_ABI_KIND)
        creation = broker["process_creation"]
        self.assertEqual(creation["api"], "CreateProcessW")
        self.assertEqual(creation["creation_flags"], [
            "CREATE_SUSPENDED", "EXTENDED_STARTUPINFO_PRESENT",
        ])
        self.assertTrue(creation["bInheritHandles"])
        self.assertEqual(
            creation["attribute_handle_allowlist"],
            "exact_PROC_THREAD_ATTRIBUTE_HANDLE_LIST",
        )
        self.assertEqual(creation["attribute_handle_allowlist_members"],
                         "exactly_all_ten_ordered_handle_map_roles")
        self.assertEqual(creation["standard_handle_binding"], {
            "STARTF_USESTDHANDLES": True,
            "hStdInput": "stdin_eof_read",
            "hStdOutput": "record_stdout_write",
            "hStdError": "acknowledgement_stderr_write",
        })
        self.assertEqual(creation["ambient_inheritable_handles"], "forbidden")
        image = creation["native_image"]
        self.assertEqual(image["lpApplicationName_custody"], "parent_private")
        self.assertEqual(
            image["selection_authority"],
            "future_externally_pinned_broker_runner_authority_only",
        )
        self.assertFalse(image["logical_argv0_is_authority"])
        self.assertEqual(broker["normative_states"], [
            "PREPARED", "SEALED", "CHILD_CREATED_SUSPENDED",
            "CHALLENGE_WRITTEN", "RUNNING", "COLLECTED", "PARENT_VERIFIED",
        ])
        sealed = broker["sealed_state"]
        self.assertEqual(sealed["child_inputs"],
                         "preopened_verified_and_handle_bound")
        self.assertEqual(sealed["child_path_reopen_after_sealed"], "forbidden")
        self.assertEqual(sealed["project_root_child_visibility"],
                         "semantic_identity_sha256_only")
        pins = broker["mandatory_parent_only_external_identity_pins"]
        self.assertEqual(set(pins), {
            "broker_authority_semantic_sha256", "handle_abi_sha256",
            "wfp_policy_sha256", "filesystem_minifilter_policy_sha256",
        })
        for pin in pins.values():
            self.assertEqual(pin["source"], "mandatory_external_pin")
            self.assertEqual(pin["accepted_artifact_schema"],
                             "not_declared_by_protocol_v4")
            self.assertFalse(pin["inferred_from_protocol"])
            self.assertEqual(pin["child_exposure"], "forbidden")

    def test_post_creation_challenge_and_exact_ack(self) -> None:
        challenge = self.value["challenge_channel_abi"]
        self.assertEqual(challenge["schema_version"], 4)
        self.assertEqual(challenge["artifact_kind"],
                         protocol.CHALLENGE_CHANNEL_ABI_KIND)
        self.assertEqual(challenge["child_handle_role"], "challenge_read")
        self.assertEqual(challenge["raw_nonce_bytes"], 32)
        self.assertEqual(challenge["nonce_generation_state"],
                         "CHILD_CREATED_SUSPENDED")
        self.assertEqual(challenge["write_completion_state"],
                         "CHALLENGE_WRITTEN")
        self.assertEqual(challenge["resume_allowed_after"],
                         "CHALLENGE_WRITTEN")
        self.assertEqual(challenge["parent_writer_action"],
                         "write_exact_32_bytes_then_close")
        self.assertEqual(challenge["child_reader_action"],
                         "read_exact_32_bytes_then_require_eof")
        for field in (
            "raw_nonce_in_argv", "raw_nonce_in_environment",
            "raw_nonce_persisted", "raw_nonce_logged",
        ):
            self.assertFalse(challenge[field])
        ack = self.value["acknowledgement_abi"]
        expected = (
            "VAST_REPLAY_ACK_V4 {session_id} {lease_id} "
            "{cell_index_decimal} {attempt_ordinal_decimal} "
            "{nonce_sha256} {stdout_sha256} {protocol_sha256}\n"
        )
        self.assertEqual(ack["template"], expected)
        self.assertEqual(ack["framing"], "exact_utf8_line")
        self.assertFalse(ack["diagnostics_allowed"])
        self.assertEqual(
            ack["parent_verification"],
            self.value["acknowledgement_abi"]["parent_verification"],
        )
        self.assertNotIn("expected_record", expected)

    def test_expected_record_is_parent_only_and_stdout_is_exact(self) -> None:
        policy = self.value["parent_only_expected_record_policy"]
        self.assertEqual(policy["artifact_schema_version"], 2)
        self.assertEqual(policy["artifact_kind"],
                         "vast_backend_runtime_cell_validation_record_v2")
        self.assertEqual(policy["custody"], "parent_only")
        self.assertEqual(policy["child_visibility"], "forbidden")
        self.assertEqual(policy["parent_precondition"],
                         "opened_verified_and_held_before_child_creation")
        self.assertEqual(policy["comparison"],
                         "byte_for_byte_against_exact_collected_stdout")
        self.assertEqual(policy["comparison_state"], "PARENT_VERIFIED")
        self.assertEqual(set(policy["forbidden_child_surfaces"]), {
            "argv", "environment", "semantic_identity_roles",
            "inherited_handle_map", "acknowledgement_inputs",
        })
        process = self.value["process_contract_template"]
        self.assertEqual(process["environment"], {})
        self.assertEqual(process["stdin"], {
            "mode": "inherited_pipe_read_immediate_eof",
            "child_handle_role": "stdin_eof_read",
            "parent_action": (
                "close_parent_private_complementary_writer_before_resume"
            ),
        })
        self.assertEqual(process["stdout"]["purpose"],
                         "exact_canonical_validation_record_bytes_only")
        self.assertEqual(process["stdout"]["max_bytes"], 16 * 1024 * 1024)
        self.assertEqual(process["acknowledgement"]["max_bytes"], 512)
        self.assertEqual(process["accepted_exit_codes"], [0])
        self.assertEqual(process["timeout_ms"], 120000)
        child_surfaces = {
            "argv": self.value["argv_template"],
            "environment": process["environment"],
            "semantic": self.value["semantic_identity_roles"],
            "handles": self.value["child_handle_map_abi"]["ordered_roles"],
            "ack": self.value["acknowledgement_abi"],
        }
        for name, surface in child_surfaces.items():
            encoded = json.dumps(surface, sort_keys=True).lower()
            with self.subTest(surface=name):
                self.assertNotIn("expected_record", encoded)
                self.assertNotIn("expected-record", encoded)

    def test_all_execution_security_and_authorization_claims_are_false(self) -> None:
        self.assertEqual(self.value["exact_false_claims"], {
            "atomic_runtime_closure_snapshot_validated": False,
            "inherited_handle_allowlist_validated": False,
            "standard_handle_mapping_validated": False,
            "handle_sealing_validated": False,
            "child_path_reopen_prevented": False,
            "native_broker_implemented": False,
            "broker_state_machine_enforced": False,
            "challenge_delivery_validated": False,
            "challenge_freshness_validated": False,
            "stdout_integrity_validated": False,
            "lease_enforcement_validated": False,
            "sandbox_enforcement_validated": False,
            "process_executed": False,
            "validation_records_authenticated": False,
            "execution_authorized": False,
            "expected_record_parent_isolation_validated": False,
            "native_image_handle_binding_validated": False,
            "filesystem_write_policy_enforced": False,
            "network_policy_enforced": False,
        })

    def test_resealed_drift_unknown_fields_and_true_claims_fail(self) -> None:
        cases = (
            (("schema_version",), 3),
            (("supported_host_architecture",), ["arm64"]),
            (("concrete_invocation_header", "schema_version"), 3),
            (("argv_template", 0), "python.exe"),
            (("native_broker_abi", "process_creation", "bInheritHandles"),
             False),
            (("child_handle_map_abi", "runtime_representation", "persisted"),
             True),
            (("child_handle_map_abi", "ordered_roles", 7, "role"),
             "record_stdout_write"),
            (("child_handle_map_abi", "standard_handle_mapping", "hStdError"),
             "record_stdout_write"),
            (("challenge_channel_abi", "raw_nonce_in_argv"), True),
            (("hash_domains", "nonce_commitment", "algorithm"),
             "sha256_exact_bytes"),
            (("acknowledgement_abi", "producer_computation",
              "stdout_sha256", "hash_domain"), "nonce_commitment"),
            (("parent_only_expected_record_policy", "child_visibility"),
             "allowed"),
            (("exact_false_claims", "execution_authorized"), True),
        )
        for path, replacement in cases:
            changed = copy.deepcopy(self.value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            self.reseal(changed)
            with self.subTest(path=path), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV4Error
            ):
                self.validate(changed, changed["protocol_sha256"])
        changed = copy.deepcopy(self.value)
        changed["dispatch_receipt"] = {}
        self.reseal(changed)
        with self.assertRaises(protocol.ReplayRunnerInvocationProtocolV4Error):
            self.validate(changed, changed["protocol_sha256"])

    def test_strict_types_external_pin_cycles_and_subclasses(self) -> None:
        class DictSubclass(dict):
            pass

        class ListSubclass(list):
            pass

        cases = (
            (("schema_version",), 4.0),
            (("schema_version",), True),
            (("supported_host_os",), ("nt",)),
            (("supported_host_os",), ListSubclass(["nt"])),
            (("semantic_identity_roles",), DictSubclass()),
            (("challenge_channel_abi", "raw_nonce_bytes"), 32.0),
            (("challenge_channel_abi", "raw_nonce_in_argv"), 0),
            (("process_contract_template", "timeout_ms"), True),
            (("process_contract_template", "accepted_exit_codes"), [False]),
        )
        for path, replacement in cases:
            changed = copy.deepcopy(self.value)
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = replacement
            self.reseal(changed)
            with self.subTest(path=path), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV4Error
            ):
                self.validate(changed, changed["protocol_sha256"])
        changed = copy.deepcopy(self.value)
        changed["process_contract_template"]["environment"]["cycle"] = changed
        with self.assertRaises(protocol.ReplayRunnerInvocationProtocolV4Error):
            self.validate(changed)
        for bad in (None, True, 1, "A" * 64, "0" * 63,
                    hashlib.sha256(b"wrong").hexdigest()):
            with self.subTest(pin=bad), self.assertRaises(
                protocol.ReplayRunnerInvocationProtocolV4Error
            ):
                self.validate(pin=bad)

    def test_protocol_v3_is_bidirectionally_incompatible(self) -> None:
        old = old_v3.replay_runner_invocation_protocol_v3_contract()
        self.assertNotEqual(old["schema_version"], self.value["schema_version"])
        self.assertNotEqual(old["artifact_kind"], self.value["artifact_kind"])
        self.assertNotEqual(
            old["concrete_invocation_header"],
            self.value["concrete_invocation_header"],
        )
        self.assertIn("--expected-record", old["argv_template"])
        self.assertNotIn("--expected-record", self.value["argv_template"])
        with self.assertRaises(protocol.ReplayRunnerInvocationProtocolV4Error):
            self.validate(old, old["protocol_sha256"])
        with self.assertRaises(old_v3.ReplayRunnerInvocationProtocolV3Error):
            old_v3.validate_replay_runner_invocation_protocol_v3_contract(
                self.value, expected_protocol_sha256=self.pin,
            )

    def test_runner_authority_v2_is_incompatible_with_protocol_v4(self) -> None:
        role = self.value["semantic_identity_roles"]["runner_authority"]
        self.assertEqual(protocol.RUNNER_AUTHORITY_SCHEMA_VERSION, 3)
        self.assertEqual(
            protocol.RUNNER_AUTHORITY_KIND,
            "vast_backend_runtime_replay_runner_authority_v3",
        )
        self.assertEqual(role, {
            "artifact_schema_version": 3,
            "artifact_kind": "vast_backend_runtime_replay_runner_authority_v3",
        })
        self.assertEqual(old_authority_v2.SCHEMA_VERSION, 2)
        self.assertEqual(
            old_authority_v2.ARTIFACT_KIND,
            "vast_backend_runtime_replay_runner_authority_v2",
        )
        self.assertNotEqual(
            (old_authority_v2.SCHEMA_VERSION, old_authority_v2.ARTIFACT_KIND),
            (role["artifact_schema_version"], role["artifact_kind"]),
        )
        authority_source = inspect.getsource(old_authority_v2)
        self.assertIn(
            "import backend_runtime_replay_runner_invocation_protocol_v3 "
            "as protocol",
            authority_source,
        )
        self.assertNotIn(
            "backend_runtime_replay_runner_invocation_protocol_v4",
            authority_source,
        )

    def test_pure_source_and_closed_public_api(self) -> None:
        source = inspect.getsource(protocol)
        tree = ast.parse(source)
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        self.assertTrue(imports <= {
            "__future__", "copy", "hashlib", "json", "re", "typing",
        })
        for forbidden in (
            "subprocess", "socket", "requests", "pathlib", "open(",
            "exec(", "eval(", "readiness", "dispatch", "grant",
        ):
            self.assertNotIn(forbidden, source.lower())
        self.assertEqual(set(protocol.__all__), {
            "SCHEMA_VERSION", "ARTIFACT_KIND",
            "CONCRETE_INVOCATION_SCHEMA_VERSION", "CONCRETE_INVOCATION_KIND",
            "NATIVE_BROKER_ABI_KIND", "CHILD_HANDLE_MAP_ABI_KIND",
            "CHALLENGE_CHANNEL_ABI_KIND", "ACKNOWLEDGEMENT_ABI_KIND",
            "RUNNER_AUTHORITY_SCHEMA_VERSION", "RUNNER_AUTHORITY_KIND",
            "VALIDATOR_AUTHORITY_SCHEMA_VERSION", "VALIDATOR_AUTHORITY_KIND",
            "REQUEST_SCHEMA_VERSION", "REQUEST_KIND", "RECORD_SCHEMA_VERSION",
            "RECORD_KIND", "ReplayRunnerInvocationProtocolV4Error",
            "replay_runner_invocation_protocol_v4_contract",
            "validate_replay_runner_child_handle_map_v4_descriptor",
            "validate_replay_runner_invocation_protocol_v4_contract",
        })
        signature = inspect.signature(
            protocol.validate_replay_runner_invocation_protocol_v4_contract
        )
        self.assertEqual(list(signature.parameters),
                         ["value", "expected_protocol_sha256"])
        pin = signature.parameters["expected_protocol_sha256"]
        self.assertEqual(pin.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(pin.default, inspect.Parameter.empty)


if __name__ == "__main__":
    unittest.main()
