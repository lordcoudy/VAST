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

import backend_runtime_qualification_v4_input_index as q4  # noqa: E402
from backend_publication_launcher_runtime_authority import (  # noqa: E402
    ARTIFACT_KIND,
    ASSESSMENT_KIND,
    CLOSURE_MANIFEST_KIND,
    LAUNCHER_INVOCATION_V3_KIND,
    BackendPublicationLauncherRuntimeAuthorityError,
    assess_backend_publication_launcher_runtime_authority,
    build_backend_publication_launcher_runtime_authority,
    validate_backend_publication_launcher_runtime_authority,
)


SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")


def canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha(value: object) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class LauncherRuntimeAuthorityFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.abi_sha = sha("publication-launcher-invocation-v3")
        files = {
            "runtime/python.exe": b"project-relative-python-runtime\n",
            "runtime/lib/core.bin": b"native-runtime-core\n",
            "runtime/lib/policy.py": b"POLICY_RUNTIME_VERSION = 1\n",
        }
        for system in SYSTEMS:
            files[f"scripts/checkpoint_{system}_publication_launcher_v3.py"] = (
                f"SYSTEM = {system!r}\n".encode("utf-8")
            )
        for relative, payload in files.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)

    def descriptor(self, relative: str) -> dict[str, object]:
        payload = (self.root / relative).read_bytes()
        return {
            "path": relative,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }

    def file_ref(self, relative: str) -> dict[str, object]:
        descriptor = self.descriptor(relative)
        return {
            "descriptor": descriptor,
            "content_identity_sha256": descriptor["sha256"],
        }

    def prepare(self, system: str = "deepstream") -> dict[str, object]:
        interpreter = self.file_ref("runtime/python.exe")
        launcher_path = f"scripts/checkpoint_{system}_publication_launcher_v3.py"
        launcher = self.file_ref(launcher_path)
        leaves = [
            self.file_ref("runtime/lib/core.bin"),
            self.file_ref("runtime/lib/policy.py"),
        ]
        leaves.sort(key=lambda item: (
            item["descriptor"]["path"].casefold(),
            item["descriptor"]["path"],
        ))
        set_material = {
            "schema_version": 1,
            "artifact_kind": "vast_backend_publication_launcher_runtime_closure_set",
            "python_executable": interpreter,
            "publication_launcher": launcher,
            "runtime_leaves": leaves,
        }
        set_sha = canonical_sha(set_material)
        manifest = {
            "schema_version": 1,
            "artifact_kind": CLOSURE_MANIFEST_KIND,
            "system": system,
            "python_executable": interpreter,
            "publication_launcher": launcher,
            "runtime_leaves": leaves,
            "runtime_closure_set_sha256": set_sha,
            "publication_launcher_invocation_v3_sha256": self.abi_sha,
        }
        manifest["closure_manifest_sha256"] = canonical_sha(manifest)
        manifest_path = f"runtime/{system}/launcher-runtime-closure.json"
        physical_manifest = self.root / manifest_path
        physical_manifest.parent.mkdir(parents=True, exist_ok=True)
        physical_manifest.write_bytes(canonical_bytes(manifest) + b"\n")
        manifest_ref = {
            "descriptor": self.descriptor(manifest_path),
            "content_identity_sha256": manifest["closure_manifest_sha256"],
        }
        authority = {
            "schema_version": 1,
            "artifact_kind": ARTIFACT_KIND,
            "system": system,
            "runtime_closure_manifest": manifest_ref,
            "runtime_closure_manifest_content": manifest,
            "python_executable": interpreter,
            "publication_launcher": launcher,
            "runtime_leaves": leaves,
            "runtime_closure_set_sha256": set_sha,
            "publication_launcher_invocation_v3_sha256": self.abi_sha,
        }
        authority["launcher_runtime_authority_sha256"] = canonical_sha(authority)
        return {
            "authority": authority,
            "manifest_path": manifest_path,
            "interpreter_path": "runtime/python.exe",
            "launcher_path": launcher_path,
            "leaf_paths": [
                "runtime/lib/policy.py", "runtime/lib/core.bin",
            ],
            "expected_authority_sha256": authority[
                "launcher_runtime_authority_sha256"
            ],
            "expected_system": system,
            "expected_publication_launcher_invocation_v3_sha256": self.abi_sha,
            "expected_closure_manifest_sha256": manifest[
                "closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": set_sha,
        }


def reseal(value: dict[str, object]) -> dict[str, str]:
    set_material = {
        "schema_version": 1,
        "artifact_kind": "vast_backend_publication_launcher_runtime_closure_set",
        "python_executable": value["python_executable"],
        "publication_launcher": value["publication_launcher"],
        "runtime_leaves": value["runtime_leaves"],
    }
    set_sha = canonical_sha(set_material)
    value["runtime_closure_set_sha256"] = set_sha
    manifest = value["runtime_closure_manifest_content"]
    manifest.update({
        "system": value["system"],
        "python_executable": copy.deepcopy(value["python_executable"]),
        "publication_launcher": copy.deepcopy(value["publication_launcher"]),
        "runtime_leaves": copy.deepcopy(value["runtime_leaves"]),
        "runtime_closure_set_sha256": set_sha,
        "publication_launcher_invocation_v3_sha256": value[
            "publication_launcher_invocation_v3_sha256"
        ],
    })
    manifest.pop("closure_manifest_sha256", None)
    manifest["closure_manifest_sha256"] = canonical_sha(manifest)
    value["runtime_closure_manifest"]["content_identity_sha256"] = manifest[
        "closure_manifest_sha256"
    ]
    payload = canonical_bytes(manifest) + b"\n"
    value["runtime_closure_manifest"]["descriptor"]["size_bytes"] = len(payload)
    value["runtime_closure_manifest"]["descriptor"]["sha256"] = hashlib.sha256(
        payload
    ).hexdigest()
    value.pop("launcher_runtime_authority_sha256", None)
    value["launcher_runtime_authority_sha256"] = canonical_sha(value)
    return {
        "expected_authority_sha256": value["launcher_runtime_authority_sha256"],
        "expected_system": value["system"],
        "expected_publication_launcher_invocation_v3_sha256": value[
            "publication_launcher_invocation_v3_sha256"
        ],
        "expected_closure_manifest_sha256": manifest[
            "closure_manifest_sha256"
        ],
        "expected_runtime_closure_set_sha256": set_sha,
    }


class BackendPublicationLauncherRuntimeAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.fixture = LauncherRuntimeAuthorityFixture(self.root)
        self.prepared = self.fixture.prepare()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def expected(self, prepared: dict[str, object] | None = None) -> dict[str, object]:
        source = prepared or self.prepared
        return {key: source[key] for key in (
            "expected_authority_sha256", "expected_system",
            "expected_publication_launcher_invocation_v3_sha256",
            "expected_closure_manifest_sha256",
            "expected_runtime_closure_set_sha256",
        )}

    def build(self, prepared: dict[str, object] | None = None,
              **overrides: object) -> dict[str, object]:
        source = prepared or self.prepared
        arguments = {
            "project_root": self.root,
            "system": source["expected_system"],
            "runtime_closure_manifest_path": source["manifest_path"],
            "python_executable_path": source["interpreter_path"],
            "publication_launcher_path": source["launcher_path"],
            "runtime_leaf_paths": source["leaf_paths"],
            **self.expected(source),
        }
        arguments.update(overrides)
        return build_backend_publication_launcher_runtime_authority(**arguments)

    def test_build_validate_assess_all_four_systems(self) -> None:
        for system in SYSTEMS:
            prepared = self.fixture.prepare(system)
            authority = self.build(prepared)
            with self.subTest(system=system):
                self.assertEqual(authority, prepared["authority"])
                self.assertEqual(
                    validate_backend_publication_launcher_runtime_authority(
                        authority, **self.expected(prepared)
                    ), authority,
                )
                assessment = assess_backend_publication_launcher_runtime_authority(
                    authority, project_root=self.root, **self.expected(prepared),
                )
                self.assertEqual(assessment["artifact_kind"], ASSESSMENT_KIND)
                self.assertEqual(assessment["status"], "physically_valid")
                self.assertEqual(assessment["checked_artifact_count"], 5)
                self.assertEqual(assessment["blockers"], [])
                for field in (
                    "authority_pin_validated", "exact_system_validated",
                    "publication_launcher_invocation_v3_pin_validated",
                    "closure_manifest_physically_reconstructed",
                    "individual_artifact_reads_handle_bound",
                    "all_artifact_physical_identities_distinct",
                ):
                    self.assertIs(assessment[field], True, field)
                for field in (
                    "atomic_runtime_closure_snapshot_validated",
                    "atomic_execution_lease_established",
                    "interpreter_execution_validated",
                    "launcher_execution_validated",
                    "launcher_abi_v3_behavior_validated",
                    "publication_capable_validated", "execution_authorized",
                ):
                    self.assertIs(assessment[field], False, field)

    @unittest.skipUnless(os.name == "posix", "POSIX atime regression")
    def test_posix_physical_read_accepts_forced_old_atime(self) -> None:
        old_atime_ns = 946684800 * 1_000_000_000
        for path in self.root.rglob("*"):
            if path.is_file():
                observed = path.stat()
                os.utime(
                    path,
                    ns=(old_atime_ns, int(observed.st_mtime_ns)),
                    follow_symlinks=False,
                )

        authority = self.build()
        assessment = assess_backend_publication_launcher_runtime_authority(
            authority,
            project_root=self.root,
            **self.expected(),
        )
        self.assertEqual(assessment["status"], "physically_valid")

    def test_all_external_pins_are_required_and_builder_never_self_pins(self) -> None:
        expected_names = tuple(self.expected())
        for function in (
            validate_backend_publication_launcher_runtime_authority,
            assess_backend_publication_launcher_runtime_authority,
            build_backend_publication_launcher_runtime_authority,
        ):
            signature = inspect.signature(function)
            for name in expected_names:
                self.assertIn(name, signature.parameters)
                self.assertIs(signature.parameters[name].default,
                              inspect.Signature.empty)
        for name in expected_names:
            changed = self.expected()
            changed[name] = "savant" if name == "expected_system" else sha(
                "wrong:" + name
            )
            with self.subTest(pin=name), self.assertRaises(
                BackendPublicationLauncherRuntimeAuthorityError
            ):
                build_backend_publication_launcher_runtime_authority(
                    project_root=self.root, system="deepstream",
                    runtime_closure_manifest_path=self.prepared["manifest_path"],
                    python_executable_path=self.prepared["interpreter_path"],
                    publication_launcher_path=self.prepared["launcher_path"],
                    runtime_leaf_paths=self.prepared["leaf_paths"], **changed,
                )

    def test_q4_typed_reference_contract_and_abi_v3_kind_are_exact(self) -> None:
        authority = self.build()
        reference = {
            "artifact_schema_version": 1,
            "artifact_kind": ARTIFACT_KIND,
            "descriptor": {
                "path": "qualification/q4/launcher-deepstream.json",
                "size_bytes": 1, "sha256": sha("authority-file"),
            },
            "content_identity_sha256": authority[
                "launcher_runtime_authority_sha256"
            ],
        }
        self.assertEqual(q4.LAUNCHER_RUNTIME_AUTHORITY_SCHEMA_VERSION, 1)
        self.assertEqual(q4.LAUNCHER_RUNTIME_AUTHORITY_KIND, ARTIFACT_KIND)
        self.assertEqual(q4.PUBLICATION_LAUNCHER_INVOCATION_V3_KIND,
                         LAUNCHER_INVOCATION_V3_KIND)
        self.assertEqual(reference["artifact_kind"],
                         "vast_backend_publication_launcher_runtime_authority")

    def test_closed_schema_crossbindings_roles_and_self_hashes(self) -> None:
        authority = self.build()
        mutations = []
        changed = copy.deepcopy(authority)
        changed["downstream_record_sha256"] = sha("forbidden")
        mutations.append((changed, self.expected()))
        changed = copy.deepcopy(authority)
        changed["system"] = "savant"
        reseal(changed)
        mutations.append((changed, self.expected()))
        changed = copy.deepcopy(authority)
        changed["python_executable"], changed["publication_launcher"] = (
            changed["publication_launcher"], changed["python_executable"]
        )
        reseal(changed)
        mutations.append((changed, self.expected()))
        changed = copy.deepcopy(authority)
        changed["runtime_closure_manifest_content"]["runtime_leaves"].pop()
        changed["launcher_runtime_authority_sha256"] = canonical_sha({
            key: item for key, item in changed.items()
            if key != "launcher_runtime_authority_sha256"
        })
        mutations.append((changed, {
            **self.expected(),
            "expected_authority_sha256": changed[
                "launcher_runtime_authority_sha256"
            ],
        }))
        for changed, expected in mutations:
            with self.assertRaises(
                BackendPublicationLauncherRuntimeAuthorityError
            ):
                validate_backend_publication_launcher_runtime_authority(
                    changed, **expected,
                )

    def test_casefold_path_alias_and_duplicate_file_or_content_identity_rejected(self) -> None:
        authority = self.build()
        for mutation in ("casefold", "file", "content", "full"):
            changed = copy.deepcopy(authority)
            source = changed["publication_launcher"]
            target = changed["runtime_leaves"][0]
            if mutation == "casefold":
                target["descriptor"]["path"] = source["descriptor"]["path"].upper()
            elif mutation == "file":
                target["descriptor"]["sha256"] = source["descriptor"]["sha256"]
            elif mutation == "content":
                target["content_identity_sha256"] = source[
                    "content_identity_sha256"
                ]
            else:
                changed["runtime_leaves"][0] = copy.deepcopy(source)
            expected = reseal(changed)
            with self.subTest(mutation=mutation), self.assertRaises(
                BackendPublicationLauncherRuntimeAuthorityError
            ):
                validate_backend_publication_launcher_runtime_authority(
                    changed, **expected,
                )

    def test_abi_cycle_abi_v2_pin_and_unsafe_paths_are_rejected(self) -> None:
        authority = self.build()
        changed = copy.deepcopy(authority)
        changed["runtime_leaves"][0]["descriptor"]["sha256"] = self.fixture.abi_sha
        changed["runtime_leaves"][0]["content_identity_sha256"] = self.fixture.abi_sha
        expected = reseal(changed)
        with self.assertRaises(BackendPublicationLauncherRuntimeAuthorityError):
            validate_backend_publication_launcher_runtime_authority(
                changed, **expected,
            )
        with self.assertRaises(BackendPublicationLauncherRuntimeAuthorityError):
            self.build(
                expected_publication_launcher_invocation_v3_sha256=sha("abi-v2")
            )
        for path in (
            str(Path(sys.executable).resolve()), "../python.exe", "C:python.exe",
            "runtime\\python.exe", "runtime/python.exe:ads", "CON.exe",
            "runtime/python.exe.", "runtime/python.exe ",
        ):
            with self.subTest(path=path), self.assertRaises(
                BackendPublicationLauncherRuntimeAuthorityError
            ):
                self.build(python_executable_path=path)

    def test_semantic_trust_domain_pins_are_pairwise_distinct(self) -> None:
        changed = copy.deepcopy(self.build())
        collision = changed["runtime_closure_set_sha256"]
        changed["publication_launcher_invocation_v3_sha256"] = collision
        manifest = changed["runtime_closure_manifest_content"]
        manifest["publication_launcher_invocation_v3_sha256"] = collision
        manifest.pop("closure_manifest_sha256")
        manifest["closure_manifest_sha256"] = canonical_sha(manifest)
        changed["runtime_closure_manifest"]["content_identity_sha256"] = (
            manifest["closure_manifest_sha256"]
        )
        changed.pop("launcher_runtime_authority_sha256")
        changed["launcher_runtime_authority_sha256"] = canonical_sha(changed)
        expected = {
            "expected_authority_sha256": changed[
                "launcher_runtime_authority_sha256"
            ],
            "expected_system": changed["system"],
            "expected_publication_launcher_invocation_v3_sha256": collision,
            "expected_closure_manifest_sha256": manifest[
                "closure_manifest_sha256"
            ],
            "expected_runtime_closure_set_sha256": collision,
        }
        with self.assertRaisesRegex(
            BackendPublicationLauncherRuntimeAuthorityError,
            "semantic trust pins alias",
        ):
            validate_backend_publication_launcher_runtime_authority(
                changed, **expected,
            )

    def test_manifest_requires_canonical_json_and_exactly_one_trailing_lf(self) -> None:
        manifest_path = self.root / self.prepared["manifest_path"]
        manifest = self.prepared["authority"]["runtime_closure_manifest_content"]
        invalid_payloads = (
            canonical_bytes(manifest),
            canonical_bytes(manifest) + b"\n\n",
            json.dumps(manifest, indent=2).encode("utf-8") + b"\n",
        )
        for payload in invalid_payloads:
            manifest_path.write_bytes(payload)
            with self.subTest(payload=payload[-10:]), self.assertRaises(
                BackendPublicationLauncherRuntimeAuthorityError
            ):
                self.build()

    def test_physical_tamper_symlink_and_hardlink_block_without_claims(self) -> None:
        authority = self.build()
        (self.root / "runtime/lib/core.bin").write_bytes(b"tampered\n")
        assessment = assess_backend_publication_launcher_runtime_authority(
            authority, project_root=self.root, **self.expected(),
        )
        self.assertEqual(assessment["status"], "blocked")
        self.assertTrue(assessment["blockers"])
        self.assertIs(assessment["atomic_execution_lease_established"], False)
        self.assertIs(assessment["execution_authorized"], False)

        prepared = self.fixture.prepare()
        alias = self.root / "runtime/lib/core-alias.bin"
        os.link(self.root / "runtime/lib/core.bin", alias)
        with self.assertRaises(BackendPublicationLauncherRuntimeAuthorityError):
            self.build(prepared, runtime_leaf_paths=["runtime/lib/core.bin"])
        alias.unlink()
        link = self.root / "runtime/lib/core-link.bin"
        try:
            link.symlink_to(self.root / "runtime/lib/core.bin")
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"symlink unavailable: {error}")
        with self.assertRaises(BackendPublicationLauncherRuntimeAuthorityError):
            self.build(prepared, runtime_leaf_paths=["runtime/lib/core-link.bin"])

    def test_source_has_no_process_execution_or_downstream_surface(self) -> None:
        path = ROOT / "scripts" / "backend_publication_launcher_runtime_authority.py"
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree) if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            (node.module or "").split(".", 1)[0]
            for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        }
        self.assertFalse(imported & {"subprocess", "socket", "requests"})
        lowered = source.lower()
        for forbidden in (
            "backend_runtime_grant", "publication_matrix", "popen(",
            "os.system", "shell=true", "validation_record",
        ):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
