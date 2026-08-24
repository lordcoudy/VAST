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
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_runtime_replay_runner_authority_v2 as target  # noqa: E402
import backend_runtime_replay_runner_invocation_protocol_v3 as protocol  # noqa: E402
import backend_runtime_validation_runner_authority as base  # noqa: E402
import backend_runtime_validator_authority_v4 as q4  # noqa: E402


def canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("utf-8")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def drifted_stat(value: os.stat_result, field: str) -> os.stat_result:
    sequence = list(value)
    nanoseconds = {
        "st_atime_ns": int(value.st_atime_ns),
        "st_mtime_ns": int(value.st_mtime_ns),
        "st_ctime_ns": int(value.st_ctime_ns),
    }
    if field in ("atime_ns", "mtime_ns", "ctime_ns"):
        nanoseconds[f"st_{field}"] += 1
    else:
        sequence_index = {
            "mode": 0, "ino": 1, "dev": 2, "nlink": 3, "size": 6,
        }[field]
        sequence[sequence_index] += 1
    return os.stat_result(sequence, nanoseconds)


class Fixture:
    def __init__(self, root: Path, *,
                 q4_schema_mismatch_field: str | None = None,
                 q4_implementation_path: str =
                 "runtime/q4/validator.py") -> None:
        self.root = root
        self.q4_schema_mismatch_field = q4_schema_mismatch_field
        self.q4_implementation_path = q4_implementation_path
        self.files = {
            "runtime/replay/python.exe": b"replay-python\n",
            "runtime/replay/worker.py": b"REPLAY_WORKER = 3\n",
            "runtime/replay/lib/core.bin": b"replay-core\n",
            "runtime/replay/lib/policy.py": b"REPLAY_POLICY = 3\n",
            "runtime/base/python.exe": b"base-python\n",
            "runtime/base/validator.py": b"BASE_RUNNER = 1\n",
            "runtime/base/lib.bin": b"base-lib\n",
            "runtime/q4/validator.py": b"Q4_VALIDATOR = 4\n",
        }
        for relative, payload in self.files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        self._prepare_base()
        self._prepare_q4()
        self._prepare_protocol()
        self._prepare_authority()

    def desc(self, relative: str) -> dict[str, object]:
        payload = (self.root / relative).read_bytes()
        return {"path": relative, "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest()}

    def file_ref(self, relative: str) -> dict[str, object]:
        descriptor = self.desc(relative)
        return {"descriptor": descriptor,
                "content_identity_sha256": descriptor["sha256"]}

    def typed(self, relative: str, schema: int, kind: str,
              semantic: str) -> dict[str, object]:
        return {"artifact_schema_version": schema, "artifact_kind": kind,
                "descriptor": self.desc(relative),
                "content_identity_sha256": semantic}

    def write_json(self, relative: str, value: object) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(canonical_bytes(value) + b"\n")

    def _prepare_base(self) -> None:
        interpreter = self.file_ref("runtime/base/python.exe")
        runner = self.file_ref("runtime/base/validator.py")
        leaves = [self.file_ref("runtime/base/lib.bin")]
        manifest = {
            "schema_version": 1,
            "artifact_kind": base.BUNDLE_MANIFEST_KIND,
            "python_executable": interpreter, "runner": runner,
            "runtime_leaves": leaves,
            "runtime_leaf_set_sha256": canonical_sha(leaves),
        }
        manifest["bundle_manifest_sha256"] = canonical_sha(manifest)
        self.base_manifest_path = "runtime/base/manifest.json"
        self.write_json(self.base_manifest_path, manifest)
        authority = {
            "schema_version": 1, "artifact_kind": base.ARTIFACT_KIND,
            "runner_id": "base-validation-runner-v1",
            "runtime_bundle_manifest": {
                "descriptor": self.desc(self.base_manifest_path),
                "content_identity_sha256": manifest["bundle_manifest_sha256"],
            },
            "runtime_bundle_manifest_content": manifest,
            "runtime_leaves": leaves,
            "runtime_leaf_set_sha256": canonical_sha(leaves),
            "python_executable": interpreter, "runner": runner,
            "invocation_contract": base.runner_invocation_contract(),
            "supported_validator_authority_schema_version": 1,
            "validation_protocol_identity_sha256": sha("base-protocol"),
            "input_schema_identity_sha256": sha("base-input"),
            "output_schema_identity_sha256": sha("base-output"),
            "deterministic": True,
        }
        authority["runner_authority_sha256"] = canonical_sha(authority)
        base.validate_backend_runtime_validation_runner_authority(
            authority,
            expected_runner_authority_sha256=authority[
                "runner_authority_sha256"
            ],
        )
        self.base_value = authority
        self.base_sha = authority["runner_authority_sha256"]
        self.base_path = "qualification/replay-v2/base-runner-authority.json"
        self.write_json(self.base_path, authority)

    def _prepare_q4(self) -> None:
        pins = {name: sha(name) for name in q4.IDENTITY_FIELDS}
        compatible = {
            "validation_protocol_identity_sha256":
                self.base_value["validation_protocol_identity_sha256"],
            "validation_input_schema_identity_sha256":
                self.base_value["input_schema_identity_sha256"],
            "validation_output_schema_identity_sha256":
                self.base_value["output_schema_identity_sha256"],
        }
        pins.update(compatible)
        if self.q4_schema_mismatch_field is not None:
            if self.q4_schema_mismatch_field not in compatible:
                raise ValueError("unknown Q4 schema mismatch field")
            pins[self.q4_schema_mismatch_field] = sha(
                f"mismatch-{self.q4_schema_mismatch_field}"
            )
        descriptor = self.desc(self.q4_implementation_path)
        candidate = q4.build_backend_runtime_validator_authority_v4(
            validator_id="q4-validator-v1",
            implementation_descriptor=descriptor,
            expected_authority_sha256="0" * 64, **pins,
        ) if False else None
        value = {
            "schema_version": 1, "artifact_kind": q4.ARTIFACT_KIND,
            "validator_id": "q4-validator-v1",
            "implementation": {"descriptor": descriptor,
                               "content_identity_sha256": descriptor["sha256"]},
            "supported_qualification_schema_version": 4,
            **pins, "deterministic": True, "execution_authorized": False,
            "validation_records_authenticated": False,
        }
        value["authority_sha256"] = canonical_sha(value)
        q4.validate_backend_runtime_validator_authority_v4(
            value, expected_authority_sha256=value["authority_sha256"]
        )
        self.q4_value = value
        self.q4_sha = value["authority_sha256"]
        self.q4_path = "qualification/replay-v2/q4-validator-authority.json"
        self.write_json(self.q4_path, value)

    def _prepare_protocol(self) -> None:
        self.protocol_value = protocol.replay_runner_invocation_protocol_v3_contract()
        self.protocol_sha = self.protocol_value["protocol_sha256"]
        self.protocol_path = "qualification/replay-v2/invocation-protocol-v3.json"
        self.write_json(self.protocol_path, self.protocol_value)
        abi_domain = {
            "schema_version": 3,
            "artifact_kind": protocol.SESSION_LEASE_CHALLENGE_ABI_KIND,
            "content": self.protocol_value["session_lease_challenge_abi"],
        }
        self.abi_sha = canonical_sha(abi_domain)

    def _prepare_authority(self) -> None:
        self.runner_id = "replay-runner-authority-v2"
        self.interpreter = self.file_ref("runtime/replay/python.exe")
        self.runner = self.file_ref("runtime/replay/worker.py")
        self.leaves = sorted([
            self.file_ref("runtime/replay/lib/core.bin"),
            self.file_ref("runtime/replay/lib/policy.py"),
        ], key=lambda item: item["descriptor"]["path"])
        self.base_ref = self.typed(self.base_path, 1, base.ARTIFACT_KIND,
                                   self.base_sha)
        self.q4_ref = self.typed(self.q4_path, 1, q4.ARTIFACT_KIND,
                                 self.q4_sha)
        self.protocol_ref = self.typed(
            self.protocol_path, 3, protocol.ARTIFACT_KIND, self.protocol_sha,
        )
        closure = {
            "schema_version": 2, "artifact_kind": target.CLOSURE_SET_KIND,
            "python_executable": self.interpreter,
            "replay_runner": self.runner, "runtime_leaves": self.leaves,
            "base_runner_authority_ref": self.base_ref,
            "q4_validator_authority_ref": self.q4_ref,
            "replay_invocation_protocol_ref": self.protocol_ref,
        }
        self.set_sha = canonical_sha(closure)
        common = {
            "runner_id": self.runner_id,
            "python_executable": self.interpreter,
            "replay_runner": self.runner, "runtime_leaves": self.leaves,
            "runtime_closure_set_sha256": self.set_sha,
            "base_runner_authority_ref": self.base_ref,
            "q4_validator_authority_ref": self.q4_ref,
            "replay_invocation_protocol_ref": self.protocol_ref,
            "supported_concrete_invocation_schema_version": 3,
            "supported_concrete_invocation_kind":
                protocol.CONCRETE_INVOCATION_KIND,
            "supported_request_schema_version": 2,
            "supported_request_kind": protocol.REQUEST_KIND,
            "supported_record_schema_version": 2,
            "supported_record_kind": protocol.RECORD_KIND,
            "session_lease_challenge_abi": copy.deepcopy(
                self.protocol_value["session_lease_challenge_abi"]
            ),
            "session_lease_challenge_abi_sha256": self.abi_sha,
        }
        manifest = {"schema_version": 2,
                    "artifact_kind": target.MANIFEST_KIND, **common}
        manifest["manifest_sha256"] = canonical_sha(manifest)
        self.manifest_sha = manifest["manifest_sha256"]
        self.manifest_path = "runtime/replay/authority-manifest.json"
        self.write_json(self.manifest_path, manifest)
        authority = {
            "schema_version": 2, "artifact_kind": target.ARTIFACT_KIND,
            "runtime_bundle_manifest": {
                "descriptor": self.desc(self.manifest_path),
                "content_identity_sha256": self.manifest_sha,
            },
            "runtime_bundle_manifest_content": manifest,
            **common,
            "replay_invocation_protocol_content": copy.deepcopy(
                self.protocol_value
            ),
            **{field: False for field in target.FALSE_CLAIMS},
        }
        authority["replay_runner_authority_sha256"] = canonical_sha(authority)
        self.authority = authority
        self.authority_sha = authority["replay_runner_authority_sha256"]

    def expected(self) -> dict[str, object]:
        return {
            "expected_authority_sha256": self.authority_sha,
            "expected_manifest_sha256": self.manifest_sha,
            "expected_runtime_closure_set_sha256": self.set_sha,
            "expected_base_runner_authority_sha256": self.base_sha,
            "expected_q4_validator_authority_sha256": self.q4_sha,
            "expected_replay_invocation_protocol_sha256": self.protocol_sha,
            "expected_session_lease_challenge_abi_sha256": self.abi_sha,
        }

    def build(self, **overrides):
        args = {
            "project_root": self.root, "runner_id": self.runner_id,
            "runtime_bundle_manifest_path": self.manifest_path,
            "runtime_leaf_paths": ["runtime/replay/lib/policy.py",
                                   "runtime/replay/lib/core.bin"],
            "python_executable_path": "runtime/replay/python.exe",
            "replay_runner_path": "runtime/replay/worker.py",
            "base_runner_authority_path": self.base_path,
            "q4_validator_authority_path": self.q4_path,
            "replay_invocation_protocol_path": self.protocol_path,
            **self.expected(),
        }
        args.update(overrides)
        return target.build_backend_runtime_replay_runner_authority_v2(**args)


class ReplayRunnerAuthorityV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.f = Fixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_build_validate_assess_exact_authority(self) -> None:
        value = self.f.build()
        self.assertEqual(value, self.f.authority)
        self.assertEqual(target.validate_backend_runtime_replay_runner_authority_v2(
            value, **self.f.expected()), value)
        assessment = target.assess_backend_runtime_replay_runner_authority_v2(
            value, project_root=self.root, **self.f.expected())
        self.assertEqual(assessment["status"], "physically_valid")
        self.assertEqual(assessment["blockers"], [])
        self.assertEqual(assessment["checked_artifact_count"], 8)
        for field in target.FALSE_CLAIMS:
            self.assertIs(value[field], False)
            self.assertIs(assessment[field], False)
        self.assertIn("runtime_closure_completeness_validated",
                      target.FALSE_CLAIMS)
        self.assertIn("protocol_schema_identity_crossbinding_complete",
                      target.FALSE_CLAIMS)
        for field in ("authority_pin_validated", "manifest_physically_validated",
                      "base_runner_authority_physically_validated",
                      "q4_validator_authority_physically_validated",
                      "replay_protocol_physically_validated",
                      "individual_artifact_reads_handle_bound",
                      "top_level_authority_reference_physical_identities_distinct"):
            self.assertIs(assessment[field], True, field)
        self.assertEqual(
            assessment["physical_validation_scope"],
            "top_level_sequential_listed_closure_and_independent_nested_authority_assessments",
        )
        self.assertIs(
            assessment[
                "transitive_runtime_artifact_physical_identities_distinct"
            ], False,
        )
        self.assertNotIn("all_artifact_physical_identities_distinct", assessment)
        self.assertNotIn("transitive_authority_graph_not_single_snapshot",
                         assessment["blockers"])

    def test_protocol_and_domain_separated_abi_are_exact(self) -> None:
        value = self.f.build()
        self.assertEqual(value["replay_invocation_protocol_ref"],
                         self.f.protocol_ref)
        self.assertEqual(value["replay_invocation_protocol_content"],
                         self.f.protocol_value)
        self.assertEqual(value["session_lease_challenge_abi"],
                         self.f.protocol_value["session_lease_challenge_abi"])
        self.assertEqual(value["session_lease_challenge_abi_sha256"],
                         self.f.abi_sha)
        self.assertNotEqual(self.f.abi_sha, self.f.protocol_sha)
        self.assertNotIn("concrete_invocation_ref", value)

    def test_old_relabel_unknown_true_claim_and_type_smuggling_fail(self) -> None:
        with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
            target.validate_backend_runtime_replay_runner_authority_v2(
                self.f.base_value, **self.f.expected())
        cases = (
            (("schema_version",), 1),
            (("artifact_kind",), base.ARTIFACT_KIND),
            (("base_runner_authority_ref", "artifact_schema_version"), True),
            (("supported_concrete_invocation_schema_version",), 3.0),
            (("runtime_closure_completeness_validated",), True),
            (("protocol_schema_identity_crossbinding_complete",), True),
            (("execution_authorized",), True),
            (("process_executed",), 0),
        )
        for path, replacement in cases:
            changed = copy.deepcopy(self.f.authority)
            node = changed
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = replacement
            changed["replay_runner_authority_sha256"] = canonical_sha({
                key: item for key, item in changed.items()
                if key != "replay_runner_authority_sha256"
            })
            expected = self.f.expected()
            expected["expected_authority_sha256"] = changed[
                "replay_runner_authority_sha256"
            ]
            with self.subTest(path=path), self.assertRaises(
                target.ReplayRunnerAuthorityV2Error
            ):
                target.validate_backend_runtime_replay_runner_authority_v2(
                    changed, **expected)
        changed = copy.deepcopy(self.f.authority)
        changed["dispatch_receipt"] = {}
        with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
            target.validate_backend_runtime_replay_runner_authority_v2(
                changed, **self.f.expected())

    def test_all_pins_mandatory_distinct_and_protocol_source_hash_rejected(self):
        for name in self.f.expected():
            args = self.f.expected()
            args[name] = True
            with self.subTest(pin=name), self.assertRaises(
                target.ReplayRunnerAuthorityV2Error
            ):
                target.validate_backend_runtime_replay_runner_authority_v2(
                    self.f.authority, **args)
        source_sha = hashlib.sha256((ROOT / "scripts" /
            "backend_runtime_replay_runner_invocation_protocol_v3.py"
        ).read_bytes()).hexdigest()
        self.assertNotEqual(source_sha, self.f.protocol_sha)
        with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
            self.f.build(expected_replay_invocation_protocol_sha256=source_sha)
        with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
            self.f.build(expected_q4_validator_authority_sha256=self.f.base_sha)

    def test_base_q4_semantic_schema_identity_mismatch_fails(self) -> None:
        bindings = (
            ("validation_protocol_identity_sha256",
             "validation_protocol_identity_sha256"),
            ("input_schema_identity_sha256",
             "validation_input_schema_identity_sha256"),
            ("output_schema_identity_sha256",
             "validation_output_schema_identity_sha256"),
        )
        for base_field, q4_field in bindings:
            with self.subTest(q4_field=q4_field), \
                    tempfile.TemporaryDirectory() as temporary:
                mismatched = Fixture(
                    Path(temporary).resolve(),
                    q4_schema_mismatch_field=q4_field,
                )
                self.assertNotEqual(
                    mismatched.base_value[base_field],
                    mismatched.q4_value[q4_field],
                )
                with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
                    mismatched.build()
                assessment = (
                    target.assess_backend_runtime_replay_runner_authority_v2(
                        mismatched.authority,
                        project_root=mismatched.root,
                        **mismatched.expected(),
                    )
                )
                self.assertEqual(assessment["status"], "blocked")
                self.assertTrue(assessment["blockers"])
                self.assertTrue(any(
                    q4_field in blocker
                    for blocker in assessment["blockers"]
                ))

    def test_nested_q4_implementation_alias_is_not_globally_distinct(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            aliased = Fixture(
                Path(temporary).resolve(),
                q4_implementation_path="runtime/replay/worker.py",
            )
            value = aliased.build()
            self.assertEqual(
                aliased.q4_value["implementation"]["descriptor"]["path"],
                value["replay_runner"]["descriptor"]["path"],
            )
            assessment = (
                target.assess_backend_runtime_replay_runner_authority_v2(
                    value, project_root=aliased.root, **aliased.expected(),
                )
            )
            self.assertEqual(assessment["status"], "physically_valid")
            self.assertIs(
                assessment[
                    "top_level_authority_reference_physical_identities_distinct"
                ], True,
            )
            self.assertIs(
                assessment[
                    "transitive_runtime_artifact_physical_identities_distinct"
                ], False,
            )
            self.assertNotIn(
                "all_artifact_physical_identities_distinct", assessment,
            )

    def test_casefold_path_alias_and_physical_tamper_fail(self) -> None:
        with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
            self.f.build(runtime_leaf_paths=[
                "runtime/replay/lib/core.bin", "RUNTIME/REPLAY/LIB/CORE.BIN",
            ])
        value = self.f.build()
        (self.root / "runtime/replay/worker.py").write_bytes(b"tampered\n")
        assessment = target.assess_backend_runtime_replay_runner_authority_v2(
            value, project_root=self.root, **self.f.expected())
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(assessment["blockers"])
        for field in target.FALSE_CLAIMS:
            self.assertIs(assessment[field], False)

    def test_hardlink_and_symlink_artifacts_fail_closed(self) -> None:
        hardlink = self.root / "runtime/replay/lib/core-hard.bin"
        os.link(self.root / "runtime/replay/lib/core.bin", hardlink)
        with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
            self.f.build(runtime_leaf_paths=[
                "runtime/replay/lib/core.bin", "runtime/replay/lib/core-hard.bin",
            ])
        link = self.root / "runtime/replay/lib/link.bin"
        try:
            link.symlink_to(self.root / "runtime/replay/lib/policy.py")
        except OSError:
            return
        with self.assertRaises(target.ReplayRunnerAuthorityV2Error):
            self.f.build(runtime_leaf_paths=["runtime/replay/lib/link.bin"])

    def _read_posix_with_stat_drift(
        self, *, drift_target: tuple[str, str, str | None], field: str,
    ) -> tuple[dict[str, object], tuple[object, ...], bytes]:
        relative = target.PurePosixPath("runtime/replay/worker.py")
        root_info = os.stat(self.root)
        root_identity = (int(root_info.st_dev), int(root_info.st_ino))
        real_open = target.os.open
        real_read = target.os.read
        real_fstat = target.os.fstat
        reading_started = [False]
        roles: dict[int, tuple[str, str, str | None]] = {}

        def observed_open(path: object, flags: int, *args: object,
                          **kwargs: object) -> int:
            fd = real_open(path, flags, *args, **kwargs)
            name = os.fspath(path)
            phase = "reopened" if reading_started[0] else "held"
            if name == os.fspath(self.root):
                roles[fd] = (phase, "root", None)
            elif name == relative.parts[-1]:
                roles[fd] = (phase, "final", None)
            else:
                roles[fd] = (phase, "component", name)
            return fd

        def observed_read(fd: int, size: int) -> bytes:
            reading_started[0] = True
            return real_read(fd, size)

        def changed_fstat(fd: int) -> os.stat_result:
            observed = real_fstat(fd)
            return (drifted_stat(observed, field)
                    if reading_started[0] and roles.get(fd) == drift_target
                    else observed)

        with mock.patch.object(
            target.os, "open", side_effect=observed_open,
        ) as mocked_open:
            supports_dir_fd = set(target.os.supports_dir_fd)
            supports_dir_fd.add(mocked_open)
            with mock.patch.object(
                target.os, "supports_dir_fd", supports_dir_fd,
            ), mock.patch.object(
                target.os, "read", side_effect=observed_read,
            ), mock.patch.object(
                target.os, "fstat", side_effect=changed_fstat,
            ):
                self.assertIn(target.os.open, target.os.supports_dir_fd)
                return target._read_posix(
                    self.root, relative, root_identity,
                )

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor semantics")
    def test_posix_read_accepts_atime_drift_for_every_traversal_node(
        self,
    ) -> None:
        targets = (
            ("held", "root", None),
            ("held", "component", "runtime"),
            ("held", "component", "replay"),
            ("held", "final", None),
            ("reopened", "root", None),
            ("reopened", "component", "runtime"),
            ("reopened", "component", "replay"),
            ("reopened", "final", None),
        )
        expected = self.f.files["runtime/replay/worker.py"]
        for drift_target in targets:
            with self.subTest(drift_target=drift_target):
                descriptor, identity, payload = self._read_posix_with_stat_drift(
                    drift_target=drift_target, field="atime_ns",
                )
                self.assertEqual(payload, expected)
                self.assertEqual(descriptor["size_bytes"], len(payload))
                self.assertEqual(identity[0], os.stat(self.root).st_dev)

    @unittest.skipUnless(os.name == "posix", "POSIX descriptor semantics")
    def test_posix_read_rejects_stable_stat_drift_for_every_traversal_node(
        self,
    ) -> None:
        targets = (
            (("held", "root", None),
             "project root changed while reading"),
            (("held", "component", "runtime"),
             "replay runner artifact held path component changed while reading"),
            (("held", "component", "replay"),
             "replay runner artifact held path component changed while reading"),
            (("held", "final", None),
             "replay runner artifact changed while reading"),
            (("reopened", "root", None),
             "project root changed while reading"),
            (("reopened", "component", "runtime"),
             "replay runner artifact path component changed"),
            (("reopened", "component", "replay"),
             "replay runner artifact path component changed"),
            (("reopened", "final", None),
             "replay runner artifact path changed while reading"),
        )
        for drift_target, expected_reason in targets:
            for field in ("size", "mtime_ns", "ctime_ns", "dev", "ino",
                          "mode", "nlink"):
                with self.subTest(drift_target=drift_target, field=field):
                    with self.assertRaises(
                        target.ReplayRunnerAuthorityV2Error,
                    ) as raised:
                        self._read_posix_with_stat_drift(
                            drift_target=drift_target, field=field,
                        )
                    self.assertEqual(str(raised.exception), expected_reason)

    def test_protocol_base_q4_physical_tamper_block_assessment(self) -> None:
        for relative in (self.f.protocol_path, self.f.base_path, self.f.q4_path):
            with self.subTest(relative=relative):
                fresh = Fixture(self.root / relative.replace("/", "_").replace(".", "_"))
                value = fresh.build()
                (fresh.root / relative).write_bytes(b"{}\n")
                result = target.assess_backend_runtime_replay_runner_authority_v2(
                    value, project_root=fresh.root, **fresh.expected())
                self.assertEqual(result["status"], "blocked")

    def test_source_has_no_process_network_write_or_downstream_consumers(self):
        source = inspect.getsource(target)
        tree = ast.parse(source)
        imports = {alias.name.split(".", 1)[0] for node in ast.walk(tree)
                   if isinstance(node, ast.Import) for alias in node.names}
        self.assertNotIn("subprocess", imports)
        self.assertNotIn("socket", imports)
        lowered = source.lower()
        for forbidden in ("requests", "urlopen", "readiness", "dispatch",
                          "grant", "benchmark", "open(\"w", "write_bytes"):
            self.assertNotIn(forbidden, lowered)
        self.assertFalse(any("replay_runner_authority_v2" in path.read_text(
            encoding="utf-8", errors="ignore") for path in
            (ROOT / "scripts").glob("*.py") if path.name !=
            "backend_runtime_replay_runner_authority_v2.py" and path.name !=
            "backend_runtime_replay_runner_invocation_protocol_v3.py" and
            path.name !=
            "backend_runtime_replay_runner_invocation_protocol_v4.py"))


if __name__ == "__main__":
    unittest.main()
