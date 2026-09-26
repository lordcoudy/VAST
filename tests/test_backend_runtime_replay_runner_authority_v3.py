from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_runtime_replay_runner_authority_v3 as target  # noqa: E402
import backend_runtime_replay_runner_authority_v2 as old_v2  # noqa: E402
import backend_runtime_replay_runner_invocation_protocol_v4 as protocol  # noqa: E402
import backend_runtime_validator_authority_v4 as q4  # noqa: E402


PROTOCOL_PIN = (
    "e6c81cb0019a4103b86dfaa5585da868bd72484198e83381de7b5456e66fad88"
)
CLOSURE_DOMAIN = b"VAST:backend-runtime-replay-runner-closure-set:v3\0"
AUTHORITY_DOMAIN = b"VAST:backend-runtime-replay-runner-authority:v3\0"


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def domain_sha(domain: bytes, value: object) -> str:
    return hashlib.sha256(domain + canonical_bytes(value)).hexdigest()


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class Fixture:
    def __init__(self, root: Path, *, q4_implementation_path: str =
                 "runtime/q4/validator.py") -> None:
        self.root = root
        self.q4_implementation_path = q4_implementation_path
        self.files = {
            "runtime/replay-v3/native-runner.exe": b"native-runner-v3\n",
            "runtime/replay-v3/entrypoint.bin": b"entrypoint-v3\n",
            "runtime/replay-v3/closure.bundle": b"opaque-closure-v3\n",
            "runtime/q4/validator.py": b"Q4_VALIDATOR = 4\n",
        }
        for relative, payload in self.files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self._prepare_protocol()
        self._prepare_q4()
        self._prepare_authority()

    def descriptor(self, relative: str) -> dict[str, object]:
        payload = (self.root / relative).read_bytes()
        return {"path": relative, "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest()}

    def file_ref(self, relative: str) -> dict[str, object]:
        descriptor = self.descriptor(relative)
        return {"descriptor": descriptor,
                "content_identity_sha256": descriptor["sha256"]}

    def typed_ref(self, relative: str, schema: int, kind: str,
                  semantic_sha: str) -> dict[str, object]:
        return {"artifact_schema_version": schema, "artifact_kind": kind,
                "descriptor": self.descriptor(relative),
                "content_identity_sha256": semantic_sha}

    def write_json(self, relative: str, value: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_bytes(value) + b"\n")

    def _prepare_q4(self) -> None:
        pins = {name: sha(name) for name in q4.IDENTITY_FIELDS}
        descriptor = self.descriptor(self.q4_implementation_path)
        value = {
            "schema_version": q4.SCHEMA_VERSION,
            "artifact_kind": q4.ARTIFACT_KIND,
            "validator_id": "q4-validator-v1",
            "implementation": {"descriptor": descriptor,
                               "content_identity_sha256": descriptor["sha256"]},
            "supported_qualification_schema_version": 4,
            **pins, "deterministic": True, "execution_authorized": False,
            "validation_records_authenticated": False,
        }
        value["authority_sha256"] = hashlib.sha256(
            canonical_bytes(value)).hexdigest()
        q4.validate_backend_runtime_validator_authority_v4(
            value, expected_authority_sha256=value["authority_sha256"])
        self.q4_value = value
        self.q4_sha = value["authority_sha256"]
        self.q4_path = "qualification/replay-v3/q4-authority.json"
        self.write_json(self.q4_path, value)

    def _prepare_protocol(self) -> None:
        self.protocol_value = protocol.replay_runner_invocation_protocol_v4_contract()
        self.protocol_sha = self.protocol_value["protocol_sha256"]
        self.protocol_path = "qualification/replay-v3/protocol-v4.json"
        self.write_json(self.protocol_path, self.protocol_value)

    def _prepare_authority(self) -> None:
        self.runner_id = "native-replay-runner-v3"
        self.image_path = "runtime/replay-v3/native-runner.exe"
        self.entrypoint_path = "runtime/replay-v3/entrypoint.bin"
        self.bundle_path = "runtime/replay-v3/closure.bundle"
        self.image_ref = self.file_ref(self.image_path)
        self.entrypoint_ref = self.file_ref(self.entrypoint_path)
        self.bundle_ref = self.file_ref(self.bundle_path)
        self.q4_ref = self.typed_ref(
            self.q4_path, q4.SCHEMA_VERSION, q4.ARTIFACT_KIND, self.q4_sha)
        self.protocol_ref = self.typed_ref(
            self.protocol_path, protocol.SCHEMA_VERSION,
            protocol.ARTIFACT_KIND, PROTOCOL_PIN)
        closure = {
            "schema_version": 3, "artifact_kind": target.CLOSURE_SET_KIND,
            "native_runner_image": self.image_ref,
            "runner_entrypoint": self.entrypoint_ref,
            "runtime_closure_bundle": self.bundle_ref,
            "q4_validator_authority_ref": self.q4_ref,
            "replay_invocation_protocol_v4_ref": self.protocol_ref,
        }
        self.closure_sha = domain_sha(CLOSURE_DOMAIN, closure)
        value = {
            "schema_version": 3, "artifact_kind": target.ARTIFACT_KIND,
            "status": "listed_candidate_bytes_only", "runner_id": self.runner_id,
            "supported_host_os": ["nt"],
            "supported_host_architecture": ["amd64"],
            "native_runner_image": self.image_ref,
            "runner_entrypoint": self.entrypoint_ref,
            "runtime_closure_bundle": self.bundle_ref,
            "runtime_closure_set_sha256": self.closure_sha,
            "q4_validator_authority_ref": self.q4_ref,
            "replay_invocation_protocol_v4_ref": self.protocol_ref,
            "replay_invocation_protocol_v4_content": copy.deepcopy(
                self.protocol_value),
            "supported_concrete_invocation_schema_version": 4,
            "supported_concrete_invocation_kind":
                protocol.CONCRETE_INVOCATION_KIND,
            "supported_request_schema_version": 2,
            "supported_request_kind": protocol.REQUEST_KIND,
            "supported_record_schema_version": 2,
            "supported_record_kind": protocol.RECORD_KIND,
            **{field: False for field in target.FALSE_CLAIMS},
        }
        value["replay_runner_authority_sha256"] = domain_sha(
            AUTHORITY_DOMAIN, value)
        self.authority = value
        self.authority_sha = value["replay_runner_authority_sha256"]

    def pins(self) -> dict[str, str]:
        return {
            "expected_authority_sha256": self.authority_sha,
            "expected_runtime_closure_set_sha256": self.closure_sha,
            "expected_q4_validator_authority_sha256": self.q4_sha,
            "expected_replay_invocation_protocol_v4_sha256": PROTOCOL_PIN,
        }

    def build(self, **overrides):
        arguments = {
            "project_root": self.root, "runner_id": self.runner_id,
            "native_runner_image_path": self.image_path,
            "runner_entrypoint_path": self.entrypoint_path,
            "runtime_closure_bundle_path": self.bundle_path,
            "q4_validator_authority_path": self.q4_path,
            "replay_invocation_protocol_v4_path": self.protocol_path,
            **self.pins(),
        }
        arguments.update(overrides)
        return target.build_backend_runtime_replay_runner_authority_v3(
            **arguments)


class ReplayRunnerAuthorityV3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_build_validate_assess_exact_candidate_bytes(self) -> None:
        self.assertEqual(self.fixture.protocol_sha, PROTOCOL_PIN)
        value = self.fixture.build()
        self.assertEqual(value, self.fixture.authority)
        self.assertEqual(
            target.validate_backend_runtime_replay_runner_authority_v3(
                value, **self.fixture.pins()), value)
        assessment = target.assess_backend_runtime_replay_runner_authority_v3(
            value, project_root=self.root, **self.fixture.pins())
        self.assertEqual(assessment["status"],
                         "listed_candidate_bytes_physically_observed")
        self.assertEqual(assessment["checked_artifact_count"], 6)
        self.assertEqual(assessment["blockers"], [])
        for field in (
            "authority_pin_validated", "runtime_closure_set_pin_validated",
            "native_runner_image_handle_bound", "runner_entrypoint_handle_bound",
            "runtime_closure_bundle_handle_bound",
            "q4_validator_implementation_handle_bound",
            "q4_validator_authority_physically_validated",
            "replay_invocation_protocol_v4_physically_validated",
            "listed_candidate_roles_physically_distinct",
        ):
            self.assertIs(assessment[field], True, field)
        self.assertEqual(
            assessment["physical_validation_scope"],
            "six_role_sequential_handle_bound_candidate_bytes_and_independent_q4_validation")
        self.assertIs(assessment[
            "transitive_artifact_physical_identities_distinct"], False)
        for field in target.FALSE_CLAIMS:
            self.assertIs(value[field], False, field)
            self.assertIs(assessment[field], False, field)

    @unittest.skipUnless(os.name == "posix", "POSIX atime regression")
    def test_posix_closure_reads_ignore_read_driven_atime_changes(self) -> None:
        for relative in (
            self.fixture.image_path,
            self.fixture.entrypoint_path,
            self.fixture.bundle_path,
            self.fixture.q4_implementation_path,
            self.fixture.q4_path,
            self.fixture.protocol_path,
        ):
            path = self.root / relative
            observed = path.stat()
            os.utime(
                path,
                ns=(946684800 * 1_000_000_000, int(observed.st_mtime_ns)),
            )
        self.assertEqual(self.fixture.build(), self.fixture.authority)

    def test_closure_hash_is_domain_separated_and_role_bound(self) -> None:
        plain = {
            "schema_version": 3, "artifact_kind": target.CLOSURE_SET_KIND,
            "native_runner_image": self.fixture.image_ref,
            "runner_entrypoint": self.fixture.entrypoint_ref,
            "runtime_closure_bundle": self.fixture.bundle_ref,
            "q4_validator_authority_ref": self.fixture.q4_ref,
            "replay_invocation_protocol_v4_ref": self.fixture.protocol_ref,
        }
        self.assertNotEqual(self.fixture.closure_sha,
                            hashlib.sha256(canonical_bytes(plain)).hexdigest())
        changed = copy.deepcopy(self.fixture.authority)
        changed["native_runner_image"], changed["runner_entrypoint"] = (
            changed["runner_entrypoint"], changed["native_runner_image"])
        changed["replay_runner_authority_sha256"] = domain_sha(
            AUTHORITY_DOMAIN, {key: item for key, item in changed.items()
                               if key != "replay_runner_authority_sha256"})
        pins = self.fixture.pins()
        pins["expected_authority_sha256"] = changed[
            "replay_runner_authority_sha256"]
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            target.validate_backend_runtime_replay_runner_authority_v3(
                changed, **pins)

    def test_protocol_v4_pin_and_external_broker_policy_are_exact(self) -> None:
        value = self.fixture.build()
        self.assertEqual(value["replay_invocation_protocol_v4_ref"][
            "content_identity_sha256"], PROTOCOL_PIN)
        pins = value["replay_invocation_protocol_v4_content"][
            "native_broker_abi"]["mandatory_parent_only_external_identity_pins"]
        self.assertEqual(set(pins), {
            "broker_authority_semantic_sha256", "handle_abi_sha256",
            "wfp_policy_sha256", "filesystem_minifilter_policy_sha256"})
        for policy in pins.values():
            self.assertEqual(policy["source"], "mandatory_external_pin")
            self.assertEqual(policy["accepted_artifact_schema"],
                             "not_declared_by_protocol_v4")
            self.assertEqual(policy["required_binding_scopes"],
                             ["concrete_invocation", "session_lease"])
            self.assertFalse(policy["inferred_from_protocol"])
            self.assertEqual(policy["child_exposure"], "forbidden")
        self.assertLessEqual(
            set(value["replay_invocation_protocol_v4_content"][
                "exact_false_claims"
            ]),
            set(target.FALSE_CLAIMS),
        )
        for forbidden in pins:
            self.assertNotIn(forbidden, value)
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            self.fixture.build(
                expected_replay_invocation_protocol_v4_sha256=sha("wrong"))

    def test_old_authority_and_relabel_are_rejected(self) -> None:
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            target.validate_backend_runtime_replay_runner_authority_v3(
                {"schema_version": old_v2.SCHEMA_VERSION,
                 "artifact_kind": old_v2.ARTIFACT_KIND},
                **self.fixture.pins())
        for field, replacement in (
            ("schema_version", 2), ("artifact_kind", old_v2.ARTIFACT_KIND),
            ("status", "physically_valid"),
        ):
            changed = copy.deepcopy(self.fixture.authority)
            changed[field] = replacement
            changed["replay_runner_authority_sha256"] = domain_sha(
                AUTHORITY_DOMAIN, {key: item for key, item in changed.items()
                                   if key != "replay_runner_authority_sha256"})
            pins = self.fixture.pins()
            pins["expected_authority_sha256"] = changed[
                "replay_runner_authority_sha256"]
            with self.subTest(field=field), self.assertRaises(
                    target.ReplayRunnerAuthorityV3Error):
                target.validate_backend_runtime_replay_runner_authority_v3(
                    changed, **pins)

    def test_unknown_true_claim_and_json_type_smuggling_fail(self) -> None:
        for field, replacement in (
            ("execution_authorized", True), ("process_executed", 0),
            ("supported_request_schema_version", 2.0),
            ("runtime_closure_bundle_completeness_validated", True),
            ("native_broker_authority_bound", True),
            ("handle_abi_external_pin_bound", True),
        ):
            changed = copy.deepcopy(self.fixture.authority)
            changed[field] = replacement
            changed["replay_runner_authority_sha256"] = domain_sha(
                AUTHORITY_DOMAIN, {key: item for key, item in changed.items()
                                   if key != "replay_runner_authority_sha256"})
            pins = self.fixture.pins()
            pins["expected_authority_sha256"] = changed[
                "replay_runner_authority_sha256"]
            with self.subTest(field=field), self.assertRaises(
                    target.ReplayRunnerAuthorityV3Error):
                target.validate_backend_runtime_replay_runner_authority_v3(
                    changed, **pins)
        changed = copy.deepcopy(self.fixture.authority)
        changed["broker_authority_semantic_sha256"] = sha("invented")
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            target.validate_backend_runtime_replay_runner_authority_v3(
                changed, **self.fixture.pins())

    def test_all_external_pins_are_mandatory_distinct(self) -> None:
        for name in self.fixture.pins():
            pins = self.fixture.pins()
            pins[name] = True
            with self.subTest(name=name), self.assertRaises(
                    target.ReplayRunnerAuthorityV3Error):
                target.validate_backend_runtime_replay_runner_authority_v3(
                    self.fixture.authority, **pins)
        pins = self.fixture.pins()
        pins["expected_q4_validator_authority_sha256"] = PROTOCOL_PIN
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            target.validate_backend_runtime_replay_runner_authority_v3(
                self.fixture.authority, **pins)

    def test_casefold_path_file_content_and_physical_aliases_fail(self) -> None:
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            self.fixture.build(runner_entrypoint_path=self.fixture.image_path.upper())
        changed = copy.deepcopy(self.fixture.authority)
        changed["runner_entrypoint"] = copy.deepcopy(
            changed["native_runner_image"])
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            target.validate_backend_runtime_replay_runner_authority_v3(
                changed, **self.fixture.pins())

    def test_physical_tamper_blocks_without_claims(self) -> None:
        value = self.fixture.build()
        (self.root / self.fixture.bundle_path).write_bytes(b"tampered\n")
        result = target.assess_backend_runtime_replay_runner_authority_v3(
            value, project_root=self.root, **self.fixture.pins())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["checked_artifact_count"], 0)
        self.assertTrue(result["blockers"])
        for field in target.FALSE_CLAIMS:
            self.assertIs(result[field], False)

    def test_assessment_failure_exposes_no_partial_physical_success(self) -> None:
        value = self.fixture.build()
        (self.root / self.fixture.bundle_path).write_bytes(b"tampered\n")
        result = target.assess_backend_runtime_replay_runner_authority_v3(
            value, project_root=self.root, **self.fixture.pins())
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["checked_artifact_count"], 0)
        for field in (
            "native_runner_image_handle_bound", "runner_entrypoint_handle_bound",
            "runtime_closure_bundle_handle_bound",
            "q4_validator_implementation_handle_bound",
            "q4_validator_authority_physically_validated",
            "replay_invocation_protocol_v4_physically_validated",
            "listed_candidate_roles_physically_distinct",
        ):
            self.assertIs(result[field], False, field)

    def test_symlink_and_hardlink_fail_closed(self) -> None:
        hardlink = self.root / "runtime/replay-v3/hardlink.bin"
        os.link(self.root / self.fixture.bundle_path, hardlink)
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            self.fixture.build(runtime_closure_bundle_path=
                               "runtime/replay-v3/hardlink.bin")
        symlink = self.root / "runtime/replay-v3/symlink.bin"
        try:
            symlink.symlink_to(self.root / self.fixture.entrypoint_path)
        except OSError:
            return
        with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
            self.fixture.build(runner_entrypoint_path=
                               "runtime/replay-v3/symlink.bin")

    def test_q4_implementation_cannot_alias_any_candidate_role(self) -> None:
        for implementation_path in (
            "runtime/replay-v3/native-runner.exe",
            "runtime/replay-v3/entrypoint.bin",
            "runtime/replay-v3/closure.bundle",
            "qualification/replay-v3/protocol-v4.json",
        ):
            with self.subTest(implementation_path=implementation_path), \
                    tempfile.TemporaryDirectory() as temporary:
                with self.assertRaises(target.ReplayRunnerAuthorityV3Error):
                    Fixture(
                        Path(temporary).resolve(),
                        q4_implementation_path=implementation_path,
                    ).build()

    def test_q4_and_protocol_tamper_block(self) -> None:
        for relative in (self.fixture.q4_path, self.fixture.protocol_path):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as temporary:
                fixture = Fixture(Path(temporary).resolve())
                value = fixture.build()
                (fixture.root / relative).write_bytes(b"{}\n")
                result = target.assess_backend_runtime_replay_runner_authority_v3(
                    value, project_root=fixture.root, **fixture.pins())
                self.assertEqual(result["status"], "blocked")
                self.assertEqual(result["checked_artifact_count"], 0)

    def test_source_is_isolated_nonauthorizing_and_new_only(self) -> None:
        source = inspect.getsource(target)
        lowered = source.lower()
        tree = ast.parse(source)
        imports = {alias.name for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for alias in node.names} | {
            node.module for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module}
        for forbidden in (
            "backend_runtime_replay_runner_authority_v2",
            "backend_runtime_replay_runner_invocation_protocol_v3",
            "backend_runtime_replay_runner_invocation_v2",
            "backend_runtime_validation_runner_authority",
        ):
            self.assertNotIn(forbidden, source)
        self.assertNotIn("subprocess", imports)
        self.assertNotIn("socket", imports)
        for forbidden in ("requests", "urlopen", "readiness", "dispatch",
                          "grant", "benchmark", "open(\"w", "write_bytes",
                          "write_text"):
            self.assertNotIn(forbidden, lowered)
        consumers = []
        for path in (ROOT / "scripts").glob("*.py"):
            if path.name in {
                "backend_runtime_replay_runner_authority_v3.py",
                "backend_runtime_replay_runner_invocation_protocol_v4.py",
            }:
                continue
            if target.ARTIFACT_KIND in path.read_text(
                    encoding="utf-8", errors="ignore"):
                consumers.append(path.name)
        self.assertEqual(consumers, [])

    def test_public_api_is_closed_and_pins_keyword_only(self) -> None:
        self.assertEqual(set(target.__all__), {
            "SCHEMA_VERSION", "ARTIFACT_KIND", "ASSESSMENT_KIND",
            "CLOSURE_SET_KIND", "FALSE_CLAIMS",
            "ReplayRunnerAuthorityV3Error",
            "validate_backend_runtime_replay_runner_authority_v3",
            "assess_backend_runtime_replay_runner_authority_v3",
            "build_backend_runtime_replay_runner_authority_v3",
        })
        signature = inspect.signature(
            target.validate_backend_runtime_replay_runner_authority_v3)
        self.assertEqual(list(signature.parameters), [
            "value", "expected_authority_sha256",
            "expected_runtime_closure_set_sha256",
            "expected_q4_validator_authority_sha256",
            "expected_replay_invocation_protocol_v4_sha256"])
        for name, parameter in list(signature.parameters.items())[1:]:
            self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY,
                             name)
            self.assertIs(parameter.default, inspect.Parameter.empty, name)


if __name__ == "__main__":
    unittest.main()
