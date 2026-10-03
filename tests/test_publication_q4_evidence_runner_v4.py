from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import backend_runtime_validation_records_v2 as records  # noqa: E402
import backend_runtime_validation_runner_authority as runner_authority  # noqa: E402
import publication_q4_evidence_runner_v4 as runner  # noqa: E402
import publication_q4_evidence_validator_v4 as validator  # noqa: E402
from tests.test_publication_q4_evidence_validator_v4 import (  # noqa: E402
    EvidenceFixture,
    canonical,
    write_json,
)


def sha(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def descriptor(root: Path, relative: str) -> dict[str, object]:
    payload = (root / relative).read_bytes()
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def artifact(root: Path, relative: str) -> dict[str, object]:
    item = descriptor(root, relative)
    return {"descriptor": item, "content_identity_sha256": item["sha256"]}


def typed_ref(
    root: Path, relative: str, *, schema_version: int, artifact_kind: str,
    semantic_sha256: str,
) -> dict[str, object]:
    return {
        "artifact_schema_version": schema_version,
        "artifact_kind": artifact_kind,
        "descriptor": descriptor(root, relative),
        "content_identity_sha256": semantic_sha256,
    }


def sealed(value: dict[str, object], field: str) -> dict[str, object]:
    result = copy.deepcopy(value)
    result[field] = validator.canonical_sha256(result)
    return result


@unittest.skipIf(os.name == "nt", "isolated copied interpreter is exercised in pinned WSL")
class PublicationQ4EvidenceRunnerV4Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        for relative in ("authority", "runtime"):
            (self.root / relative).mkdir(parents=True, exist_ok=True)

        runtime_value = sealed(
            {
                "schema_version": 2,
                "artifact_kind": "vast_backend_publication_runtime_authority_v2",
                "coordinate": {
                    "system": "deepstream", "codec": "h264",
                    "topology_kind": "independent_processes", "policy": "cpu_only",
                },
                "dataset": {}, "source_runtime_artifacts": [],
                "backend_runtime_artifacts": [], "analytics_authority": {},
                "policy_authority": {}, "cohort_topology_plan": {},
                "resource_contract": {}, "system_specific_launcher_input": {},
                "upstream_identities": {},
            },
            "authority_sha256",
        )
        write_json(self.root / "authority/runtime-authority.json", runtime_value)
        self.runtime_authority = runtime_value
        self.evidence = EvidenceFixture(
            self.root,
            runtime_authority_sha=str(runtime_value["authority_sha256"]),
        )

        shutil.copy2(
            Path(sys.executable).resolve(), self.root / "runtime/python"
        )
        shutil.copy2(
            SCRIPTS / "publication_q4_evidence_runner_v4.py",
            self.root / "runtime/runner.py",
        )
        shutil.copy2(
            SCRIPTS / "publication_q4_evidence_validator_v4.py",
            self.root / "runtime/validator.py",
        )
        leaves = [artifact(self.root, "runtime/validator.py")]
        manifest = {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_validation_bundle_manifest",
            "python_executable": artifact(self.root, "runtime/python"),
            "runner": artifact(self.root, "runtime/runner.py"),
            "runtime_leaves": leaves,
            "runtime_leaf_set_sha256": validator.canonical_sha256(leaves),
        }
        manifest["bundle_manifest_sha256"] = validator.canonical_sha256(manifest)
        write_json(self.root / "runtime/bundle-manifest.json", manifest)

        self.protocol_sha = sha("q4-validation-protocol-v4")
        self.input_sha = sha("q4-validation-request-wire-v4")
        self.output_sha = sha("q4-validation-result-wire-v4")
        self.runner_authority = runner_authority.build_backend_runtime_validation_runner_authority(
            project_root=self.root,
            runner_id="publication-q4-evidence-runner-v4",
            runtime_bundle_manifest_path="runtime/bundle-manifest.json",
            runtime_leaf_paths=["runtime/validator.py"],
            python_executable_path="runtime/python",
            runner_path="runtime/runner.py",
            validation_protocol_identity_sha256=self.protocol_sha,
            input_schema_identity_sha256=self.input_sha,
            output_schema_identity_sha256=self.output_sha,
        )
        write_json(
            self.root / "authority/runner-authority.json", self.runner_authority
        )

        implementation = artifact(self.root, "runtime/validator.py")
        self.validator_authority = {
            "schema_version": 1,
            "artifact_kind": "vast_backend_runtime_validator_authority_q4",
            "validator_id": "publication-q4-evidence-validator-v4",
            "implementation": implementation,
            "supported_qualification_schema_version": 4,
            "qualification_input_schema_identity_sha256": sha("q4-input-schema"),
            "validation_system_context_schema_identity_sha256": sha("context-schema"),
            "validation_request_schema_identity_sha256": sha("request-schema"),
            "validation_record_schema_identity_sha256": sha("record-schema"),
            "validation_system_shard_schema_identity_sha256": sha("shard-schema"),
            "validation_record_set_index_schema_identity_sha256": sha("index-schema"),
            "validation_protocol_identity_sha256": self.protocol_sha,
            "validation_input_schema_identity_sha256": self.input_sha,
            "validation_output_schema_identity_sha256": self.output_sha,
            "deterministic": True,
            "execution_authorized": False,
            "validation_records_authenticated": False,
        }
        self.validator_authority["authority_sha256"] = validator.canonical_sha256(
            self.validator_authority
        )
        write_json(
            self.root / "authority/validator-authority.json",
            self.validator_authority,
        )

        q4_input = sealed(
            {
                "schema_version": 4,
                "artifact_kind": "vast_backend_runtime_qualification_v4_input_index",
                "status": "physically_bound_non_authorizing_q4_input",
            },
            "input_index_sha256",
        )
        invocation = sealed(
            {
                "schema_version": 3,
                "artifact_kind": "vast_backend_publication_launcher_invocation_v3",
                "status": "pinned_non_authorizing_invocation",
            },
            "invocation_sha256",
        )
        launcher = sealed(
            {
                "schema_version": 1,
                "artifact_kind": "vast_backend_publication_launcher_runtime_authority",
                "status": "pinned_non_authorizing_launcher",
            },
            "authority_sha256",
        )
        write_json(self.root / "authority/q4-input.json", q4_input)
        write_json(self.root / "authority/launcher-invocation.json", invocation)
        write_json(self.root / "authority/launcher-authority.json", launcher)

        self.runtime_ref = typed_ref(
            self.root, "authority/runtime-authority.json", schema_version=2,
            artifact_kind="vast_backend_publication_runtime_authority_v2",
            semantic_sha256=str(runtime_value["authority_sha256"]),
        )
        self.runner_ref = typed_ref(
            self.root, "authority/runner-authority.json", schema_version=1,
            artifact_kind="vast_backend_runtime_validation_runner_authority",
            semantic_sha256=str(self.runner_authority["runner_authority_sha256"]),
        )
        self.validator_ref = typed_ref(
            self.root, "authority/validator-authority.json", schema_version=1,
            artifact_kind="vast_backend_runtime_validator_authority_q4",
            semantic_sha256=str(self.validator_authority["authority_sha256"]),
        )
        self.q4_ref = typed_ref(
            self.root, "authority/q4-input.json", schema_version=4,
            artifact_kind="vast_backend_runtime_qualification_v4_input_index",
            semantic_sha256=str(q4_input["input_index_sha256"]),
        )
        self.invocation_ref = typed_ref(
            self.root, "authority/launcher-invocation.json", schema_version=3,
            artifact_kind="vast_backend_publication_launcher_invocation_v3",
            semantic_sha256=str(invocation["invocation_sha256"]),
        )
        self.launcher_ref = typed_ref(
            self.root, "authority/launcher-authority.json", schema_version=1,
            artifact_kind="vast_backend_publication_launcher_runtime_authority",
            semantic_sha256=str(launcher["authority_sha256"]),
        )
        self.binding_sha = sha("deepstream-runtime-binding-v4")
        self.set_sha = sha("deepstream-runtime-authority-set-v4")
        self.invocation_identity = str(
            self.runner_authority["invocation_contract"]["invocation_sha256"]
        )

        context = records.build_backend_runtime_validation_system_context_v2(
            system="deepstream",
            q4_input_ref=self.q4_ref,
            q4_input_sha256=str(q4_input["input_index_sha256"]),
            q4_validator_authority_ref=self.validator_ref,
            q4_validator_authority_sha256=str(
                self.validator_authority["authority_sha256"]
            ),
            runner_authority_ref=self.runner_ref,
            runner_authority_sha256=str(
                self.runner_authority["runner_authority_sha256"]
            ),
            publication_launcher_invocation_v3_ref=self.invocation_ref,
            publication_launcher_invocation_v3_sha256=str(
                invocation["invocation_sha256"]
            ),
            runner_invocation_identity_sha256=self.invocation_identity,
            runtime_binding_identity_v4_sha256=self.binding_sha,
            runtime_authority_set_sha256=self.set_sha,
            launcher_runtime_authority_ref=self.launcher_ref,
            launcher_runtime_authority_sha256=str(launcher["authority_sha256"]),
        )
        write_json(self.root / "authority/context.json", context)
        self.context_ref = typed_ref(
            self.root, "authority/context.json", schema_version=2,
            artifact_kind="vast_backend_runtime_validation_system_context_v2",
            semantic_sha256=str(context["context_sha256"]),
        )

        contract_path = self.evidence.contract_path
        contract = json.loads(contract_path.read_bytes())
        graph = contract["native_graph_contract"]
        graph.update({
            "runtime_authority_ref": self.runtime_ref,
            "runtime_authority_sha256": runtime_value["authority_sha256"],
            "runtime_authority_set_sha256": self.set_sha,
            "runtime_binding_identity_v4_sha256": self.binding_sha,
            "launcher_runtime_authority_ref": self.launcher_ref,
            "launcher_runtime_authority_sha256": launcher["authority_sha256"],
            "publication_launcher_invocation_v3_ref": self.invocation_ref,
            "publication_launcher_invocation_v3_sha256": invocation["invocation_sha256"],
            "q4_validator_authority_ref": self.validator_ref,
            "q4_validator_authority_sha256": self.validator_authority["authority_sha256"],
            "runner_authority_ref": self.runner_ref,
            "runner_authority_sha256": self.runner_authority["runner_authority_sha256"],
            "runner_invocation_identity_sha256": self.invocation_identity,
        })
        graph.pop("graph_contract_sha256", None)
        graph["graph_contract_sha256"] = validator.canonical_sha256(graph)
        contract["native_graph_contract"] = graph
        contract.pop("contract_sha256", None)
        contract["contract_sha256"] = validator.canonical_sha256(contract)
        write_json(contract_path, contract)

        raw_manifest = self.evidence.manifest()
        write_json(self.root / "authority/raw-evidence.json", raw_manifest)
        self.raw_ref = {
            "descriptor": descriptor(self.root, "authority/raw-evidence.json"),
            "content_identity_sha256": raw_manifest[
                "raw_evidence_manifest_sha256"
            ],
        }
        request = records.build_backend_runtime_validation_request_v2(
            **self.evidence.coordinate,
            context_ref=self.context_ref,
            runtime_authority_ref=self.runtime_ref,
            runtime_authority_sha256=str(runtime_value["authority_sha256"]),
            raw_evidence_ref=self.raw_ref,
            q4_input_ref=self.q4_ref,
            q4_input_sha256=str(q4_input["input_index_sha256"]),
            q4_validator_authority_ref=self.validator_ref,
            q4_validator_authority_sha256=str(
                self.validator_authority["authority_sha256"]
            ),
            runner_authority_ref=self.runner_ref,
            runner_authority_sha256=str(
                self.runner_authority["runner_authority_sha256"]
            ),
            publication_launcher_invocation_v3_ref=self.invocation_ref,
            publication_launcher_invocation_v3_sha256=str(
                invocation["invocation_sha256"]
            ),
            runner_invocation_identity_sha256=self.invocation_identity,
            runtime_binding_identity_v4_sha256=self.binding_sha,
            runtime_authority_set_sha256=self.set_sha,
            launcher_runtime_authority_ref=self.launcher_ref,
            launcher_runtime_authority_sha256=str(launcher["authority_sha256"]),
        )
        write_json(self.root / "authority/request.json", request)
        self.request = request
        self.argv = [
            "--project-root", str(self.root),
            "--runner-authority", str(self.root / "authority/runner-authority.json"),
            "--runner-authority-file-sha256", descriptor(
                self.root, "authority/runner-authority.json"
            )["sha256"],
            "--runner-authority-sha256", self.runner_authority[
                "runner_authority_sha256"
            ],
            "--validator-authority", str(
                self.root / "authority/validator-authority.json"
            ),
            "--validator-authority-file-sha256", descriptor(
                self.root, "authority/validator-authority.json"
            )["sha256"],
            "--validator-authority-sha256", self.validator_authority[
                "authority_sha256"
            ],
            "--request", str(self.root / "authority/request.json"),
            "--request-file-sha256", descriptor(
                self.root, "authority/request.json"
            )["sha256"],
            "--request-sha256", request["request_sha256"],
        ]

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def invoke(self, argv: list[str] | None = None) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(
            [
                str(self.root / "runtime/python"), "-I", "-S", "-B", "-X",
                "utf8", str(self.root / "runtime/runner.py"),
                *(self.argv if argv is None else argv),
            ],
            cwd=self.root, env={}, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
            close_fds=True, timeout=30,
        )

    def test_exact_isolated_empty_env_read_only_success(self) -> None:
        before = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }
        completed = self.invoke()
        self.assertEqual(completed.returncode, 0, completed.stderr.decode())
        self.assertEqual(completed.stderr, b"")
        result = json.loads(completed.stdout)
        self.assertEqual(completed.stdout, canonical(result) + b"\n")
        checked = validator.validate_publication_q4_evidence_validation_result_v4(
            result,
            expected_coordinate=self.evidence.coordinate,
            expected_request_sha256=self.request["request_sha256"],
            expected_raw_evidence_manifest_sha256=self.raw_ref[
                "content_identity_sha256"
            ],
        )
        self.assertEqual(checked["replay_result"], records.QUALIFIED_REPLAY_RESULT)
        after = {
            path.relative_to(self.root).as_posix(): path.read_bytes()
            for path in self.root.rglob("*") if path.is_file()
        }
        self.assertEqual(after, before)

    def test_authority_protocol_drift_and_argv_drift_fail_closed(self) -> None:
        changed = copy.deepcopy(self.validator_authority)
        changed["validation_protocol_identity_sha256"] = sha("wrong-protocol")
        changed.pop("authority_sha256")
        changed["authority_sha256"] = validator.canonical_sha256(changed)
        write_json(self.root / "authority/validator-authority.json", changed)
        argv = list(self.argv)
        argv[11] = descriptor(
            self.root, "authority/validator-authority.json"
        )["sha256"]
        argv[13] = changed["authority_sha256"]
        completed = self.invoke(argv)
        self.assertEqual(completed.returncode, runner.EXIT_REJECTED)
        self.assertIn(b"protocol or wire-schema", completed.stderr)
        self.assertLessEqual(len(completed.stderr), runner.MAX_DIAGNOSTIC_BYTES)
        self.assertEqual(completed.stdout, b"")

        malformed = list(self.argv)
        malformed[0] = "--abbreviated"
        completed = self.invoke(malformed)
        self.assertEqual(completed.returncode, runner.EXIT_USAGE)
        self.assertEqual(completed.stdout, b"")

    def test_read_only_network_fence_denies_mutations(self) -> None:
        target = self.root / "must-not-exist"
        with runner._ReadOnlyNetworkFence():
            with self.assertRaises(runner.PublicationQ4EvidenceRunnerV4Error):
                target.write_text("forbidden", encoding="utf-8")
            with self.assertRaises(runner.PublicationQ4EvidenceRunnerV4Error):
                os.mkdir(target)
            with self.assertRaises(runner.PublicationQ4EvidenceRunnerV4Error):
                socket.socket()
            with self.assertRaises(runner.PublicationQ4EvidenceRunnerV4Error):
                os.system("true")
            with self.assertRaises(runner.PublicationQ4EvidenceRunnerV4Error):
                subprocess.run(["true"], check=False)
            with self.assertRaisesRegex(
                runner.PublicationQ4EvidenceRunnerV4Error,
                "could not be loaded.*creation denied",
            ):
                runner._load_validator_module(
                    self.root / "runtime/import-side-effect.py",
                    b"import os\nos.system('true')\n",
                )
            with self.assertRaisesRegex(
                runner.PublicationQ4EvidenceRunnerV4Error,
                "stdout/stderr writes denied",
            ):
                runner._load_validator_module(
                    self.root / "runtime/import-output.py",
                    b"print('forbidden')\n",
                )
        self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
