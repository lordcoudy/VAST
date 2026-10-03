from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publication_qualification_image_refreeze_v1.py"
REGISTRY = ROOT / "configs" / "publication_qualification_image_refreeze_v1.json"
BUILD_REGISTRY = ROOT / "configs" / "publication_image_build_v1.json"
WRAPPER = ROOT / "scripts" / "refreeze_publication_qualification_images_v1.sh"


class InjectedCrash(RuntimeError):
    pass


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "publication_qualification_image_refreeze_v1", SCRIPT,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("refreeze module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _runtime_physical(system: str, image_id: str, digit: str) -> dict[str, object]:
    repository = {
        "deepstream": "vast/deepstream-publication-runtime-v3",
        "savant": "vast/savant-publication-runtime-v3",
        "openvino_gva": "vast/openvino-gva-publication-runtime-v3",
        "gstreamer_custom": "vast/gstreamer-custom-publication-runtime-v3",
    }[system]
    final_reference = repository + ":materialized"
    canonical = repository + "@" + image_id
    return {
        "final_reference": final_reference,
        "deterministic_references": [
            final_reference + "-determinism-a",
            final_reference + "-determinism-b",
        ],
        "image_id": image_id,
        "observed_repository_digests": [canonical],
        "canonical_repository_digest": canonical,
        "canonical_repository_digest_observed": True,
        "inspect_projection_sha256": digit * 64,
        "inspect_full_sha256": digit * 64,
        "architecture": "amd64",
        "os": "linux",
        "created": "1970-01-01T00:00:00Z",
        "entrypoint": ["/runtime"],
        "user": "root",
        "labels": {},
        "base": {"kind": "remote_digest", "image_id": "sha256:" + "a" * 64},
        "native_builder": None,
        "native_receipt": None,
        "source_identity": {
            "runtime_source_sha256": digit * 64,
            "runtime_source_count": 1,
            "dependency_set_sha256": digit * 64,
            "dependency_count": 1,
            "source_allowlist_sha256": digit * 64,
            "source_allowlist": {
                "path": "allowlist.txt", "size": 1, "sha256": digit * 64,
            },
            "native_source_sha256": None,
            "native_source_count": 0,
        },
        "embedded_files": {"/runtime": digit * 64},
        "embedded_aliases": {
            "runtime_entrypoint": {"path": "/runtime", "sha256": digit * 64},
        },
        "embedded_set_sha256": digit * 64,
    }


class PublicationQualificationImageRefreezeV1Tests(unittest.TestCase):
    def test_production_registry_is_exact_and_offline(self) -> None:
        module = _load_module()
        registry = module.load_refreeze_registry(
            project_root=ROOT, registry_path=REGISTRY,
        )
        self.assertEqual(
            [row["system"] for row in registry["systems"]],
            ["deepstream", "savant", "openvino_gva", "gstreamer_custom"],
        )
        self.assertEqual(
            {row["projection_kind"] for row in registry["systems"]},
            {"deepstream_v1", "savant_v3", "openvino_v3", "gstreamer_v3"},
        )
        for row in registry["systems"]:
            self.assertTrue(row["deterministic_references"][0].endswith("-determinism-a"))
            self.assertTrue(row["deterministic_references"][1].endswith("-determinism-b"))
            self.assertTrue(row["embedded_paths"])
            self.assertNotIn("latest", json.dumps(row))
            if row["base"]["kind"] == "remote_digest":
                self.assertIn("evidence_producer", row["base"])
                self.assertNotIn("expected_image_id", row["base"])
        source = SCRIPT.read_text(encoding="utf-8").lower()
        self.assertNotIn("shell=true", source)
        self.assertNotRegex(source, r"\(docker,\s*[\"']pull[\"']")
        self.assertNotIn('"--network", "host"', source)

    def test_wsl_wrapper_is_pinned_and_only_captures_then_assembles(self) -> None:
        source = WRAPPER.read_text(encoding="utf-8")
        self.assertIn(
            ".publication-runtime/full-publication-cp312-v1/bin/python3.12",
            source,
        )
        self.assertEqual(source.count('"$system"'), 1)
        self.assertIn("capture", source)
        self.assertIn("assemble", source)
        self.assertIn("VAST_PUBLICATION_IMAGE_PLAN_ONLY", source)
        for forbidden in ("docker build", "docker pull", ".wslconfig", "boot-profile"):
            self.assertNotIn(forbidden, source)

    def test_plan_binds_current_exact_source_dependency_and_allowlist_sets(self) -> None:
        module = _load_module()
        plan = module.qualification_image_refreeze_plan(
            project_root=ROOT, registry_path=REGISTRY,
        )
        self.assertEqual(plan["artifact_kind"], "vast_publication_qualification_image_refreeze_plan_v1")
        self.assertEqual(len(plan["systems"]), 4)
        for row in plan["systems"]:
            self.assertRegex(row["runtime_source_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["dependency_set_sha256"], r"^[0-9a-f]{64}$")
            self.assertRegex(row["source_allowlist_sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(row["runtime_source_count"], 0)
            self.assertGreater(row["dependency_count"], 0)

    def test_capture_checks_pair_and_emits_fragment_consumable_identity(self) -> None:
        module = _load_module()
        registry = module.load_refreeze_registry(
            project_root=ROOT, registry_path=REGISTRY,
        )
        openvino = next(row for row in registry["systems"] if row["system"] == "openvino_gva")
        candidate_final = openvino["repository"] + ":attempt4-test"
        candidate_references = {
            candidate_final,
            candidate_final + "-determinism-a",
            candidate_final + "-determinism-b",
        }
        plan = module.qualification_image_refreeze_plan(
            project_root=ROOT, registry_path=REGISTRY,
        )
        source = next(row for row in plan["systems"] if row["system"] == "openvino_gva")
        runtime_id = "sha256:" + "4" * 64
        base_id = "sha256:5c43c6c1f95b3fbb4a95957d1d293b1272c1db6a44a7a2063aad3aeba7c951d1"
        repository_digest = openvino["repository"] + "@" + runtime_id
        labels = module.resolved_expected_labels(
            system=openvino, source_identity=source,
            base_image_id=base_id, native_builder=None,
        )
        inspect = {
            "Id": runtime_id,
            "Architecture": "amd64",
            "Os": "linux",
            "Created": openvino["created"],
            "RepoDigests": [repository_digest],
            "Config": {
                "Entrypoint": openvino["entrypoint"],
                "User": openvino["user"],
                "Labels": labels,
            },
        }
        base_inspect = {"Id": base_id, "RepoDigests": []}
        embedded = {
            path: hashlib.sha256(path.encode("utf-8")).hexdigest()
            for path in openvino["embedded_paths"]
        }

        def runner(command):
            command = tuple(command)
            if command[1:3] == ("image", "inspect"):
                reference = command[3]
                if reference == openvino["base"]["reference"]:
                    return _canonical([base_inspect])
                self.assertIn(reference, candidate_references)
                self.assertNotIn(reference, {
                    openvino["final_reference"],
                    *openvino["deterministic_references"],
                })
                return _canonical([inspect])
            if command[5:8] == ("--entrypoint", "/usr/bin/sha256sum", runtime_id):
                rows = b"".join(
                    f"{embedded[path]}  {path}\n".encode("ascii")
                    for path in openvino["embedded_paths"]
                )
                return rows
            self.assertEqual(
                command,
                ("docker", "run", "--rm", "--network", "none", runtime_id, "--help"),
            )
            return b""

        with tempfile.TemporaryDirectory(prefix="image-refreeze-", dir=ROOT / "artifacts") as raw:
            output = Path(raw) / "openvino.runtime.freeze.json"
            receipt = module.capture_runtime_image(
                project_root=ROOT,
                registry_path=REGISTRY,
                system_name="openvino_gva",
                native_receipt=None,
                receipt_output=output,
                docker="docker",
                candidate_final_reference=candidate_final,
                command_runner=runner,
                producer_image_overrides={"native_probe_openvino": base_id},
            )
            identity = receipt["fragment_identity"]
            self.assertEqual(identity["image_id"], runtime_id)
            self.assertEqual(identity["repository_digest"], repository_digest)
            self.assertEqual(identity["base_image_id"], base_id)
            self.assertEqual(identity["runtime_source_sha256"], source["runtime_source_sha256"])
            self.assertEqual(identity["native_source_sha256"], source["native_source_sha256"])
            self.assertEqual(identity["dependency_set_sha256"], source["dependency_set_sha256"])
            self.assertEqual(identity["source_allowlist_sha256"], source["source_allowlist_sha256"])
            self.assertEqual(identity["embedded_set_sha256"], module.embedded_set_sha256(embedded, openvino["embedded_paths"]))
            self.assertEqual(receipt["physical_identity"]["final_reference"], candidate_final)
            self.assertEqual(
                receipt["physical_identity"]["deterministic_references"],
                [candidate_final + "-determinism-a", candidate_final + "-determinism-b"],
            )
            self.assertTrue(receipt["candidate_binding_eligible"])
            loaded = module.load_runtime_image_receipt(output)
            self.assertEqual(loaded, receipt)

    def test_candidate_reference_cli_fails_closed_on_wrong_repository_or_canonical_overlap(self) -> None:
        module = _load_module()
        registry = module.load_refreeze_registry(
            project_root=ROOT, registry_path=REGISTRY,
        )
        openvino = next(row for row in registry["systems"] if row["system"] == "openvino_gva")
        with tempfile.TemporaryDirectory(prefix="image-refreeze-", dir=ROOT / "artifacts") as raw:
            output = Path(raw) / "openvino.json"
            common = [
                "capture", "--project-root", str(ROOT), "--registry", str(REGISTRY),
                "--system", "openvino_gva", "--receipt-output", str(output),
            ]
            for reference, message in (
                ("vast/not-openvino:attempt4", "must use the system repository"),
                (openvino["final_reference"], "overlap canonical runtime references"),
            ):
                stderr = StringIO()
                with redirect_stdout(StringIO()), redirect_stderr(stderr):
                    result = module.main([*common, "--candidate-final-reference", reference])
                self.assertEqual(result, 2)
                self.assertIn(message, stderr.getvalue())
                self.assertFalse(output.exists())

    def test_capture_rejects_non_deterministic_pair(self) -> None:
        module = _load_module()
        registry = module.load_refreeze_registry(project_root=ROOT, registry_path=REGISTRY)
        system = next(row for row in registry["systems"] if row["system"] == "deepstream")
        base_id = "sha256:" + "a" * 64
        ids = {
            system["final_reference"]: "sha256:" + "1" * 64,
            system["deterministic_references"][0]: "sha256:" + "1" * 64,
            system["deterministic_references"][1]: "sha256:" + "2" * 64,
        }

        def runner(command):
            reference = tuple(command)[3]
            if reference == system["base"]["reference"]:
                return _canonical([{"Id": base_id, "RepoDigests": [system["base"]["reference"]]}])
            return _canonical([{"Id": ids[reference], "Config": {"Labels": {}}}])

        with tempfile.TemporaryDirectory(prefix="image-refreeze-", dir=ROOT / "artifacts") as raw:
            with self.assertRaisesRegex(ValueError, "deterministic runtime image IDs differ"):
                module.capture_runtime_image(
                    project_root=ROOT, registry_path=REGISTRY,
                    system_name="deepstream", native_receipt=None,
                    receipt_output=Path(raw) / "deepstream.json", docker="docker",
                    command_runner=runner,
                    base_image_overrides={"deepstream": base_id},
                )

    def test_patch_is_derived_evidence_and_detects_receipt_mutation(self) -> None:
        module = _load_module()
        required = {
            "schema_version": 1,
            "artifact_kind": module.RUNTIME_RECEIPT_KIND,
            "system": "deepstream",
            "build_registry_sha256": hashlib.sha256(BUILD_REGISTRY.read_bytes()).hexdigest(),
            "refreeze_registry_sha256": hashlib.sha256(REGISTRY.read_bytes()).hexdigest(),
            "candidate_binding_eligible": True,
            "blockers": [],
            "fragment_identity": {"image_id": "sha256:" + "d" * 64},
            "physical_identity": _runtime_physical(
                "deepstream", "sha256:" + "d" * 64, "d",
            ),
        }
        required["receipt_sha256"] = module.self_sha256(required, "receipt_sha256")
        with tempfile.TemporaryDirectory(prefix="image-refreeze-", dir=ROOT / "artifacts") as raw:
            receipt_path = Path(raw) / "deepstream.json"
            receipt_path.write_bytes(_canonical(required) + b"\n")
            loaded = module.load_runtime_image_receipt(receipt_path)
            self.assertEqual(loaded, required)
            required["candidate_binding_eligible"] = False
            receipt_path.chmod(0o600)
            receipt_path.write_bytes(_canonical(required) + b"\n")
            with self.assertRaisesRegex(ValueError, "self-identity drifted"):
                module.load_runtime_image_receipt(receipt_path)

    def test_runtime_receipt_rejects_incomplete_physical_identity(self) -> None:
        module = _load_module()
        value: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": module.RUNTIME_RECEIPT_KIND,
            "system": "deepstream",
            "build_registry_sha256": "1" * 64,
            "refreeze_registry_sha256": "2" * 64,
            "candidate_binding_eligible": True,
            "blockers": [],
            "fragment_identity": {"image_id": "sha256:" + "3" * 64},
            "physical_identity": {},
        }
        value["receipt_sha256"] = module.self_sha256(value, "receipt_sha256")
        with tempfile.TemporaryDirectory(prefix="image-refreeze-", dir=ROOT / "artifacts") as raw:
            path = Path(raw) / "incomplete.json"
            path.write_bytes(_canonical(value) + b"\n")
            with self.assertRaisesRegex(ValueError, "physical identity drifted"):
                module.load_runtime_image_receipt(path)

    def test_assemble_emits_one_physically_bound_non_authorizing_patch(self) -> None:
        module = _load_module()
        registry_sha = hashlib.sha256(BUILD_REGISTRY.read_bytes()).hexdigest()
        refreeze_sha = hashlib.sha256(REGISTRY.read_bytes()).hexdigest()

        def build_receipt(group: str, images: list[dict[str, object]]) -> dict[str, object]:
            value: dict[str, object] = {
                "artifact_kind": "vast_publication_image_freeze_receipt_v1",
                "schema_version": 1,
                "group": group,
                "registry_path": "configs/publication_image_build_v1.json",
                "registry_sha256": registry_sha,
                "images": images,
            }
            value["receipt_sha256"] = module.self_sha256(value, "receipt_sha256")
            return value

        native_ids = {
            "native_probe_deepstream": "sha256:" + "1" * 64,
            "native_probe_openvino": "sha256:" + "2" * 64,
            "native_probe_savant": "sha256:" + "3" * 64,
        }
        native = build_receipt(
            "native_probe",
            [{"name": name, "image_id": image_id} for name, image_id in native_ids.items()],
        )
        workers = build_receipt(
            "analytics_worker",
            [
                {
                    "name": "analytics_worker_openvino",
                    "image_id": "sha256:" + "4" * 64,
                    "base_image_id": native_ids["native_probe_openvino"],
                    "identity_changed": False,
                },
                {
                    "name": "analytics_worker_tensorrt",
                    "image_id": "sha256:" + "5" * 64,
                    "base_image_id": native_ids["native_probe_deepstream"],
                    "identity_changed": False,
                },
            ],
        )
        with tempfile.TemporaryDirectory(prefix="image-refreeze-", dir=ROOT / "artifacts") as raw:
            directory = Path(raw)
            native_path = directory / "native.json"
            worker_path = directory / "workers.json"
            native_path.write_bytes(_canonical(native) + b"\n")
            worker_path.write_bytes(_canonical(workers) + b"\n")
            runtime_paths = {}
            for index, system in enumerate(
                ("deepstream", "savant", "openvino_gva", "gstreamer_custom"),
                start=6,
            ):
                image_id = "sha256:" + str(index) * 64
                physical = _runtime_physical(system, image_id, str(index))
                receipt: dict[str, object] = {
                    "schema_version": 1,
                    "artifact_kind": module.RUNTIME_RECEIPT_KIND,
                    "system": system,
                    "build_registry_sha256": registry_sha,
                    "refreeze_registry_sha256": refreeze_sha,
                    "candidate_binding_eligible": True,
                    "blockers": [],
                    "fragment_identity": {"image_id": image_id},
                    "physical_identity": physical,
                }
                receipt["receipt_sha256"] = module.self_sha256(receipt, "receipt_sha256")
                path = directory / f"{system}.json"
                path.write_bytes(_canonical(receipt) + b"\n")
                runtime_paths[system] = path
            output = directory / "qualification_image_identity_patch.v1.json"
            patch = module.assemble_identity_patch(
                project_root=ROOT, registry_path=REGISTRY,
                native_receipt=native_path, worker_receipt=worker_path,
                runtime_receipts=runtime_paths, output=output,
            )
            self.assertEqual(patch["authority"], "derived_physical_evidence_only")
            self.assertFalse(
                patch["candidate_binding_requirements"]["patch_supersedes_acceptance"],
            )
            self.assertEqual(tuple(patch["systems"]), tuple(runtime_paths))
            self.assertEqual(
                patch["workers"]["cpu"]["image_id"], "sha256:" + "4" * 64,
            )
            self.assertEqual(
                module.load_identity_patch(
                    project_root=ROOT, patch_path=output,
                    require_candidate_eligible=True,
                ),
                patch,
            )
            runtime_paths["deepstream"].write_bytes(b"{}\n")
            with self.assertRaisesRegex(ValueError, "descriptor drifted"):
                module.load_identity_patch(project_root=ROOT, patch_path=output)

    def test_changed_worker_identity_requires_new_parity_acceptance(self) -> None:
        module = _load_module()
        rows = {
            "analytics_worker_openvino": {
                "name": "analytics_worker_openvino", "identity_changed": True,
            },
            "analytics_worker_tensorrt": {
                "name": "analytics_worker_tensorrt", "identity_changed": False,
            },
        }
        self.assertEqual(
            module.worker_acceptance_blockers(rows),
            ["analytics_worker:cpu_identity_changed_requires_parity_refresh"],
        )
        rows["analytics_worker_openvino"].pop("identity_changed")
        with self.assertRaisesRegex(ValueError, "identity_changed state is absent"):
            module.worker_acceptance_blockers(rows)


    def test_exclusive_receipt_adopts_all_three_atomic_crash_windows(self) -> None:
        module = _load_module()
        document = {"schema_version": 1, "value": "durable"}
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary).resolve()
                path = root / "receipt.json"

                def crash(observed: str) -> None:
                    if observed == step:
                        raise InjectedCrash(step)

                with self.assertRaises(InjectedCrash):
                    module._write_exclusive_json(
                        root, path, document, _fault_hook=crash
                    )
                module._write_exclusive_json(root, path, document)
                identity = (path.stat().st_dev, path.stat().st_ino)
                module._write_exclusive_json(root, path, document)
                self.assertEqual((path.stat().st_dev, path.stat().st_ino), identity)
                path.chmod(0o600)
                path.write_bytes(b"foreign\n")
                with self.assertRaisesRegex(Exception, "atomic commit/adoption"):
                    module._write_exclusive_json(root, path, document)


if __name__ == "__main__":
    unittest.main()
