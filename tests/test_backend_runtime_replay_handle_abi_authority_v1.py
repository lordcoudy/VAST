#!/usr/bin/env python3
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backend_runtime_replay_runner_invocation_protocol_v3 as protocol_v3
import backend_runtime_replay_runner_invocation_protocol_v4 as protocol_v4
import backend_runtime_replay_handle_abi_authority_v1 as target


PROJECTION_DOMAIN = b"VAST:backend-runtime-replay-handle-abi-projection:v1\0"
AUTHORITY_DOMAIN = b"VAST:backend-runtime-replay-handle-abi-authority:v1\0"
ROLE_NAMES = (
    "runner_entrypoint_read",
    "runner_authority_read",
    "validator_authority_read",
    "validation_request_read",
    "raw_evidence_read",
    "runtime_closure_bundle_read",
    "challenge_read",
    "stdin_eof_read",
    "record_stdout_write",
    "acknowledgement_stderr_write",
)
FALSE_CLAIMS = (
    "handle_abi_implemented",
    "os_handle_object_types_validated",
    "inherited_handle_set_validated",
    "handle_sealing_validated",
    "standard_handle_mapping_validated",
    "process_created",
    "process_executed",
    "execution_authorized",
)


def canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def domain_sha(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + canonical(value)).hexdigest()


def expected_projection(protocol: dict[str, object], protocol_pin: str) -> dict[str, object]:
    child = protocol["child_handle_map_abi"]
    creation = protocol["native_broker_abi"]["process_creation"]
    return {
        "schema_version": 1,
        "artifact_kind": "vast_backend_runtime_replay_handle_abi_projection_v1",
        "source_protocol_identity": {
            "artifact_schema_version": 4,
            "artifact_kind": (
                "vast_backend_runtime_replay_runner_invocation_protocol_v4"
            ),
            "content_identity_sha256": protocol_pin,
        },
        "ordered_roles": copy.deepcopy(child["ordered_roles"]),
        "handle_map_runtime_representation": copy.deepcopy(
            child["runtime_representation"]
        ),
        "handle_inheritance": copy.deepcopy(child["inheritance"]),
        "native_process_creation_handle_contract": {
            "api": creation["api"],
            "creation_flags": copy.deepcopy(creation["creation_flags"]),
            "bInheritHandles": creation["bInheritHandles"],
            "attribute_handle_allowlist": creation["attribute_handle_allowlist"],
            "attribute_handle_allowlist_members": creation[
                "attribute_handle_allowlist_members"
            ],
            "standard_handle_binding": copy.deepcopy(
                creation["standard_handle_binding"]
            ),
            "ambient_inheritable_handles": creation[
                "ambient_inheritable_handles"
            ],
        },
        "standard_handle_mapping": copy.deepcopy(
            child["standard_handle_mapping"]
        ),
        "parent_private_complementary_handles": copy.deepcopy(
            child["parent_private_complementary_handles"]
        ),
        "parent_private_complementary_handle_inheritance": child[
            "parent_private_complementary_handle_inheritance"
        ],
        "parent_private_complementary_handle_map_membership": child[
            "parent_private_complementary_handle_map_membership"
        ],
        "protocol_persistence": copy.deepcopy(child["protocol_persistence"]),
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.relative = "runtime/replay-handle-abi/protocol-v4.json"
        self.path = root / self.relative
        self.path.parent.mkdir(parents=True)
        self.protocol = protocol_v4.replay_runner_invocation_protocol_v4_contract()
        self.protocol_pin = self.protocol["protocol_sha256"]
        self.persisted = canonical(self.protocol) + b"\n"
        self.path.write_bytes(self.persisted)
        self.file_sha = hashlib.sha256(self.persisted).hexdigest()
        self.projection = expected_projection(self.protocol, self.protocol_pin)
        self.projection_pin = domain_sha(PROJECTION_DOMAIN, self.projection)
        self.unsigned = {
            "schema_version": 1,
            "artifact_kind": (
                "vast_backend_runtime_replay_handle_abi_authority_v1"
            ),
            "status": "immutable_non_authorizing_handle_abi_projection",
            "supported_host_os": ["nt"],
            "supported_host_architecture": ["amd64"],
            "replay_invocation_protocol_v4_ref": {
                "artifact_schema_version": 4,
                "artifact_kind": protocol_v4.ARTIFACT_KIND,
                "descriptor": {
                    "path": self.relative,
                    "size_bytes": len(self.persisted),
                    "sha256": self.file_sha,
                },
                "content_identity_sha256": self.protocol_pin,
            },
            "replay_invocation_protocol_v4_content": copy.deepcopy(self.protocol),
            "handle_abi_projection": copy.deepcopy(self.projection),
            "handle_abi_projection_sha256": self.projection_pin,
            **{field: False for field in FALSE_CLAIMS},
        }
        self.authority_pin = domain_sha(AUTHORITY_DOMAIN, self.unsigned)
        self.value = copy.deepcopy(self.unsigned)
        self.value["handle_abi_authority_sha256"] = self.authority_pin

    def pins(self) -> dict[str, str]:
        return {
            "expected_authority_sha256": self.authority_pin,
            "expected_replay_invocation_protocol_v4_sha256": self.protocol_pin,
            "expected_handle_abi_projection_sha256": self.projection_pin,
        }

    def build(self) -> dict[str, object]:
        return target.build_backend_runtime_replay_handle_abi_authority_v1(
            project_root=self.root,
            replay_invocation_protocol_v4_path=self.relative,
            **self.pins(),
        )


class ReplayHandleAbiAuthorityV1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_projection_vector_build_validate_and_assess(self) -> None:
        value = self.fixture.build()
        self.assertEqual(value, self.fixture.value)
        self.assertEqual(
            self.fixture.protocol_pin,
            "e6c81cb0019a4103b86dfaa5585da868bd72484198e83381de7b5456e66fad88",
        )
        self.assertRegex(self.fixture.projection_pin, r"^[0-9a-f]{64}$")
        self.assertEqual(
            self.fixture.projection_pin,
            "e5c8a3f473724e6d72fd3c1e7831edb0dbcec237874b7f1c020449e1503ad53e",
        )
        validated = target.validate_backend_runtime_replay_handle_abi_authority_v1(
            copy.deepcopy(value), **self.fixture.pins()
        )
        self.assertEqual(validated, value)
        validated["supported_host_os"].append("posix")
        self.assertEqual(value["supported_host_os"], ["nt"])
        assessment = target.assess_backend_runtime_replay_handle_abi_authority_v1(
            value, project_root=self.root, **self.fixture.pins()
        )
        self.assertEqual(assessment["status"], "protocol_v4_artifact_physically_observed")
        self.assertEqual(assessment["checked_artifact_count"], 1)
        self.assertEqual(assessment["blockers"], [])
        for field in (
            "authority_pin_validated",
            "protocol_v4_semantic_pin_validated",
            "handle_abi_projection_pin_validated",
            "protocol_v4_artifact_handle_bound",
            "protocol_v4_exact_canonical_content_matched",
            "protocol_projection_exactly_validated",
            "identity_namespace_separated",
        ):
            self.assertIs(assessment[field], True, field)
        for field in FALSE_CLAIMS:
            self.assertIs(value[field], False, field)
            self.assertIs(assessment[field], False, field)

    def test_projection_is_exact_closed_and_contains_no_process_local_numbers(self) -> None:
        projection = self.fixture.projection
        self.assertEqual(
            [item["role"] for item in projection["ordered_roles"]],
            list(ROLE_NAMES),
        )
        runtime = projection["handle_map_runtime_representation"]
        self.assertEqual(runtime["exact_role_count"], 10)
        self.assertEqual(runtime["number_encoding"], "canonical_unsigned_decimal_u64")
        self.assertEqual(runtime["minimum"], 1)
        self.assertEqual(runtime["maximum"], 18446744073709551615)
        self.assertEqual(runtime["pseudo_handles"], "forbidden")
        self.assertIs(runtime["pairwise_distinct"], True)
        self.assertIs(runtime["process_local_only"], True)
        self.assertIs(runtime["persisted"], False)
        self.assertIs(runtime["semantic_hash_input"], False)
        self.assertEqual(runtime["logging"], "forbidden")
        rendered = canonical(projection).decode("ascii")
        self.assertIn("{u64}", rendered)
        self.assertNotRegex(rendered, r"hmap4;[^\"]+=[1-9][0-9]*(?:;|\")")

    def test_redundant_protocol_surfaces_must_agree_before_projection(self) -> None:
        mutations = {}

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["ordered_roles"][0:2] = reversed(
            value["child_handle_map_abi"]["ordered_roles"][0:2]
        )
        mutations["role_order"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["ordered_roles"][1] = copy.deepcopy(
            value["child_handle_map_abi"]["ordered_roles"][0]
        )
        mutations["duplicate_role"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["runtime_representation"][
            "grammar_template"
        ] += ";unexpected={u64}"
        mutations["grammar"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["runtime_representation"][
            "pseudo_handles"
        ] = "allowed"
        mutations["pseudo_handle_policy"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["runtime_representation"][
            "pairwise_distinct"
        ] = False
        mutations["duplicate_handle_policy"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["standard_handle_mapping"][
            "hStdOutput"
        ] = "acknowledgement_stderr_write"
        mutations["child_std_swap"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["native_broker_abi"]["process_creation"][
            "standard_handle_binding"
        ]["hStdInput"] = "record_stdout_write"
        mutations["native_std_swap"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["process_contract_template"]["stdin"][
            "child_handle_role"
        ] = "challenge_read"
        mutations["ambiguous_stdin"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["inheritance"][
            "input_handle_allowlist"
        ] = "first_nine_roles_only"
        mutations["inheritance_allowlist"] = value

        value = copy.deepcopy(self.fixture.protocol)
        value["child_handle_map_abi"]["parent_private_complementary_handles"][
            1
        ] = "challenge_write"
        mutations["complementary_alias"] = value

        for label, mutated in mutations.items():
            with self.subTest(label=label), self.assertRaises(
                target.ReplayHandleAbiAuthorityV1Error
            ):
                target._normalized_projection(
                    mutated, protocol_pin=self.fixture.protocol_pin
                )

    def test_old_protocol_v3_and_pre_ten_handle_shape_are_incompatible(self) -> None:
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            target._normalized_projection(
                protocol_v3.replay_runner_invocation_protocol_v3_contract(),
                protocol_pin=self.fixture.protocol_pin,
            )
        pre_ten = copy.deepcopy(self.fixture.protocol)
        child = pre_ten["child_handle_map_abi"]
        child["ordered_roles"] = child["ordered_roles"][:7]
        child["runtime_representation"]["exact_role_count"] = 7
        child["runtime_representation"]["grammar_template"] = (
            "hmap4;" + ";".join(
                f"{role}={{u64}}" for role in ROLE_NAMES[:7]
            )
        )
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            target._normalized_projection(
                pre_ten, protocol_pin=self.fixture.protocol_pin
            )
        candidate = copy.deepcopy(self.fixture.value)
        candidate["replay_invocation_protocol_v4_content"] = (
            protocol_v3.replay_runner_invocation_protocol_v3_contract()
        )
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            target.validate_backend_runtime_replay_handle_abi_authority_v1(
                candidate, **self.fixture.pins()
            )

    def test_projection_drift_rejected_even_with_resealed_external_pins(self) -> None:
        candidate = copy.deepcopy(self.fixture.value)
        projection = candidate["handle_abi_projection"]
        projection["ordered_roles"][0:2] = reversed(projection["ordered_roles"][0:2])
        bad_projection_pin = domain_sha(PROJECTION_DOMAIN, projection)
        candidate["handle_abi_projection_sha256"] = bad_projection_pin
        unsigned = {
            key: copy.deepcopy(item) for key, item in candidate.items()
            if key != "handle_abi_authority_sha256"
        }
        bad_authority_pin = domain_sha(AUTHORITY_DOMAIN, unsigned)
        candidate["handle_abi_authority_sha256"] = bad_authority_pin
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            target.validate_backend_runtime_replay_handle_abi_authority_v1(
                candidate,
                expected_authority_sha256=bad_authority_pin,
                expected_replay_invocation_protocol_v4_sha256=(
                    self.fixture.protocol_pin
                ),
                expected_handle_abi_projection_sha256=bad_projection_pin,
            )

    def test_external_pins_types_aliases_and_identity_namespace_fail_closed(self) -> None:
        bad_pins = (
            {"expected_authority_sha256": "A" * 64},
            {"expected_authority_sha256": True},
            {"expected_handle_abi_projection_sha256": self.fixture.protocol_pin},
        )
        for changes in bad_pins:
            pins = self.fixture.pins()
            pins.update(changes)
            with self.subTest(changes=changes), self.assertRaises(
                target.ReplayHandleAbiAuthorityV1Error
            ):
                target.validate_backend_runtime_replay_handle_abi_authority_v1(
                    self.fixture.value, **pins
                )
        candidate = copy.deepcopy(self.fixture.value)
        candidate["replay_invocation_protocol_v4_ref"]["descriptor"][
            "sha256"
        ] = self.fixture.protocol_pin
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            target.validate_backend_runtime_replay_handle_abi_authority_v1(
                candidate, **self.fixture.pins()
            )

    def test_strict_types_cycles_false_claims_and_self_hash(self) -> None:
        candidates = []
        value = copy.deepcopy(self.fixture.value)
        value["schema_version"] = True
        candidates.append(value)
        value = copy.deepcopy(self.fixture.value)
        value["handle_abi_projection"]["handle_map_runtime_representation"][
            "exact_role_count"
        ] = True
        candidates.append(value)
        value = copy.deepcopy(self.fixture.value)
        value["handle_abi_implemented"] = 0
        candidates.append(value)
        value = copy.deepcopy(self.fixture.value)
        value["handle_abi_authority_sha256"] = "0" * 64
        candidates.append(value)
        value = copy.deepcopy(self.fixture.value)
        value["cycle"] = value
        candidates.append(value)
        for position, candidate in enumerate(candidates):
            with self.subTest(position=position), self.assertRaises(
                target.ReplayHandleAbiAuthorityV1Error
            ):
                target.validate_backend_runtime_replay_handle_abi_authority_v1(
                    candidate, **self.fixture.pins()
                )

    def test_nested_bool_int_smuggling_and_contradictory_descriptor_rejected(self) -> None:
        smuggled = copy.deepcopy(self.fixture.value)
        smuggled["handle_abi_projection"]["handle_map_runtime_representation"][
            "minimum"
        ] = True
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            target.validate_backend_runtime_replay_handle_abi_authority_v1(
                smuggled, **self.fixture.pins()
            )

        contradictory = copy.deepcopy(self.fixture.value)
        descriptor = contradictory["replay_invocation_protocol_v4_ref"][
            "descriptor"
        ]
        descriptor["size_bytes"] += 1
        descriptor["sha256"] = "f" * 64
        unsigned = {
            key: copy.deepcopy(item) for key, item in contradictory.items()
            if key != "handle_abi_authority_sha256"
        }
        resealed_authority = domain_sha(AUTHORITY_DOMAIN, unsigned)
        contradictory["handle_abi_authority_sha256"] = resealed_authority
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            target.validate_backend_runtime_replay_handle_abi_authority_v1(
                contradictory,
                expected_authority_sha256=resealed_authority,
                expected_replay_invocation_protocol_v4_sha256=(
                    self.fixture.protocol_pin
                ),
                expected_handle_abi_projection_sha256=(
                    self.fixture.projection_pin
                ),
            )

    def test_physical_reader_requires_canonical_single_lf_unique_plain_file(self) -> None:
        original = self.fixture.path.with_suffix(".original")
        os.replace(self.fixture.path, original)
        try:
            self.fixture.path.symlink_to(original)
        except OSError:
            os.replace(original, self.fixture.path)
        else:
            result = target.assess_backend_runtime_replay_handle_abi_authority_v1(
                self.fixture.value, project_root=self.root, **self.fixture.pins()
            )
            self.assertEqual(result["status"], "blocked")
            self.fixture.path.unlink()
            os.replace(original, self.fixture.path)

        hardlink = self.fixture.path.with_suffix(".hardlink")
        os.link(self.fixture.path, hardlink)
        result = target.assess_backend_runtime_replay_handle_abi_authority_v1(
            self.fixture.value, project_root=self.root, **self.fixture.pins()
        )
        self.assertEqual(result["status"], "blocked")
        hardlink.unlink()

        self.fixture.path.write_bytes(canonical(self.fixture.protocol) + b"\n\n")
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            self.fixture.build()
        self.fixture.path.write_bytes(
            json.dumps(self.fixture.protocol, indent=2).encode("utf-8") + b"\n"
        )
        with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
            self.fixture.build()

    def test_build_obtains_descriptor_from_disk_and_requires_successful_assess(self) -> None:
        signature = inspect.signature(
            target.build_backend_runtime_replay_handle_abi_authority_v1
        )
        self.assertNotIn("descriptor", signature.parameters)
        self.assertNotIn("protocol_content", signature.parameters)
        blocked = {
            "status": "blocked",
            "blockers": ["forced assessment failure"],
        }
        with mock.patch.object(
            target,
            "assess_backend_runtime_replay_handle_abi_authority_v1",
            return_value=blocked,
        ) as mocked:
            with self.assertRaises(target.ReplayHandleAbiAuthorityV1Error):
                self.fixture.build()
        mocked.assert_called_once()

    def test_source_is_read_only_new_only_nonauthorizing_and_has_no_consumers(self) -> None:
        source = inspect.getsource(target)
        lowered = source.lower()
        tree = ast.parse(source)
        imports = {
            alias.name for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
        }
        self.assertIn("backend_runtime_replay_runner_invocation_protocol_v4", imports)
        for forbidden in (
            "backend_runtime_replay_runner_invocation_protocol_v3",
            "backend_runtime_replay_runner_authority_v2",
            "backend_runtime_replay_runner_authority_v3",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("subprocess", imports)
        self.assertNotIn("socket", imports)
        for forbidden in (
            "requests", "urlopen", "readiness", "dispatch", "grant",
            "benchmark", "open(\"w", "write_bytes", "write_text",
            "resume_thread", "resumethread",
        ):
            self.assertNotIn(forbidden, lowered)
        consumers = []
        for path in (ROOT / "scripts").glob("*.py"):
            if path.name == "backend_runtime_replay_handle_abi_authority_v1.py":
                continue
            if target.ARTIFACT_KIND in path.read_text(
                encoding="utf-8", errors="ignore"
            ):
                consumers.append(path.name)
        self.assertEqual(consumers, [])

    def test_public_api_is_closed_and_pins_are_mandatory_keyword_only(self) -> None:
        self.assertEqual(set(target.__all__), {
            "SCHEMA_VERSION", "ARTIFACT_KIND", "ASSESSMENT_KIND",
            "ABI_PROJECTION_SCHEMA_VERSION", "ABI_PROJECTION_KIND",
            "FALSE_CLAIMS", "ReplayHandleAbiAuthorityV1Error",
            "validate_backend_runtime_replay_handle_abi_authority_v1",
            "assess_backend_runtime_replay_handle_abi_authority_v1",
            "build_backend_runtime_replay_handle_abi_authority_v1",
        })
        validate = inspect.signature(
            target.validate_backend_runtime_replay_handle_abi_authority_v1
        )
        self.assertEqual(list(validate.parameters), [
            "value", "expected_authority_sha256",
            "expected_replay_invocation_protocol_v4_sha256",
            "expected_handle_abi_projection_sha256",
        ])
        for name, parameter in list(validate.parameters.items())[1:]:
            self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY, name)
            self.assertIs(parameter.default, inspect.Parameter.empty, name)


if __name__ == "__main__":
    unittest.main()
