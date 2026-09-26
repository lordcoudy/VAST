from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

import publication_q4_authority_plan_pipeline_v1 as authority_pipeline  # noqa: E402
import publication_q4_authority_source_material_v1 as target  # noqa: E402
from publication_physical_io_v1 import PublicationPhysicalIoV1Error  # noqa: E402
from test_publication_q4_authority_plan_pipeline_v1 import (  # noqa: E402
    Fixture,
    canonical,
    semantic,
)


class InjectedCrash(BaseException):
    pass


class PublicationQ4AuthoritySourceMaterialV1Tests(unittest.TestCase):
    def request(
        self, root: Path, fixture: Fixture, run: str
    ) -> tuple[Path, dict[str, object]]:
        _unused_spec_path, source_spec = fixture.source_spec(run)
        accepted_source_descriptors = {
            key: fixture.descriptor(root / str(path))
            for key, path in fixture.accepted_sources().items()
            if key.endswith("_path")
        }
        dataset_source_descriptors = []
        for row in fixture.dataset_sources:
            dataset_source_descriptors.append(
                {
                    "codec_variant": row["codec_variant"],
                    "front_gate": fixture.descriptor(
                        root / str(row["front_gate_path"])
                    ),
                    "underbody": fixture.descriptor(
                        root / str(row["underbody_path"])
                    ),
                }
            )
        runtime_requests = [
            {
                "coordinate": copy.deepcopy(row["coordinate"]),
                "inputs": copy.deepcopy(row["inputs"]),
            }
            for row in fixture.runtime_builds
        ]
        request = target.build_publication_q4_authority_source_material_request_v1(
            accepted_upstream_identities=fixture.upstream,
            accepted_source_descriptors=accepted_source_descriptors,
            expected_analytics_service_identity_sha256=fixture.service_identity,
            dataset_source_descriptors=dataset_source_descriptors,
            runtime_authority_requests=runtime_requests,
            launcher_runtime_authority_builds=fixture.launcher_builds,
            publication_launcher_invocation_v3_sha256=fixture.invocation_sha,
            q4_validator_authority_build=fixture.validator_build,
            runner_authority_build=fixture.runner_build,
            planned_outputs=source_spec["planned_outputs"],
        )
        path = root / "specs" / f"{run}.request.json"
        path.write_bytes(canonical(request, newline=True))
        return path, request

    @staticmethod
    def materialize(
        root: Path,
        request_path: Path,
        request: dict[str, object],
        run: str,
        *,
        after_artifact_commit=None,
    ) -> dict[str, object]:
        return target.materialize_publication_q4_authority_source_material_v1(
            project_root=root,
            request_path=request_path,
            expected_request_file_sha256=hashlib.sha256(
                request_path.read_bytes()
            ).hexdigest(),
            expected_request_sha256=str(request["request_sha256"]),
            output_dir=f"transactions/{run}/source-material",
            after_artifact_commit=after_artifact_commit,
        )

    @staticmethod
    def identities(directory: Path) -> dict[str, tuple[int, int]]:
        return {
            item.name: (int(item.stat().st_dev), int(item.stat().st_ino))
            for item in directory.iterdir()
            if item.is_file()
        }

    def test_producer_source_spec_and_phase1_roundtrip_without_mocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request_path, request = self.request(root, fixture, "P")
                receipt = self.materialize(root, request_path, request, "P")

                output = root / "transactions" / "P" / "source-material"
                self.assertEqual(
                    sorted(path.name for path in output.iterdir()),
                    sorted((target.MATERIAL_FILENAME, target.RECEIPT_FILENAME)),
                )
                self.assertFalse(receipt["authorization_eligible"])
                self.assertFalse(receipt["execution_authorized"])
                self.assertEqual(receipt["dataset_source_count"], 2)
                self.assertEqual(receipt["runtime_authority_build_count"], 112)
                self.assertEqual(receipt["launcher_runtime_authority_build_count"], 4)

                material_path = root / str(receipt["source_material"]["path"])
                material = json.loads(material_path.read_bytes())
                self.assertNotIn("source_spec_sha256", material)
                self.assertFalse(material["authorization_eligible"])
                self.assertFalse(material["execution_authorized"])

                spec_path = root / "specs" / "P.committed.json"
                spec = authority_pipeline.materialize_publication_q4_authority_source_spec_v1(
                    project_root=root,
                    source_material_path=material_path,
                    expected_source_material_file_sha256=receipt[
                        "source_material"
                    ]["sha256"],
                    expected_source_material_sha256=receipt[
                        "source_material_sha256"
                    ],
                    output_path=spec_path,
                )
                phase1 = authority_pipeline.materialize_publication_q4_authority_plan_phase1_v1(
                    project_root=root,
                    source_spec_path=spec_path,
                    expected_source_spec_file_sha256=hashlib.sha256(
                        spec_path.read_bytes()
                    ).hexdigest(),
                    expected_source_spec_sha256=spec["source_spec_sha256"],
                    output_dir="transactions/P/phase1",
                )
                phase1_path = (
                    root
                    / "transactions"
                    / "P"
                    / "phase1"
                    / authority_pipeline.PHASE1_RECEIPT_FILENAME
                )
                loaded = authority_pipeline.load_publication_q4_authority_plan_phase1_receipt_v1(
                    project_root=root,
                    receipt_path=phase1_path,
                    expected_receipt_file_sha256=hashlib.sha256(
                        phase1_path.read_bytes()
                    ).hexdigest(),
                    expected_receipt_sha256=phase1["receipt_sha256"],
                )
                self.assertEqual(len(loaded["runtime_authorities"]), 112)
                self.assertEqual(len(loaded["launcher_runtime_authorities"]), 4)
                self.assertFalse(loaded["execution_authorized"])
            finally:
                fixture.close()

    def test_mutated_upstream_descriptor_fails_closed_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request_path, request = self.request(root, fixture, "M")
                accepted = request["accepted_source_descriptors"]
                descriptor = accepted["policy_capability_manifest_path"]
                (root / str(descriptor["path"])).write_bytes(b"tampered\n")
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthoritySourceMaterialV1Error,
                    "descriptor.*drifted",
                ):
                    self.materialize(root, request_path, request, "M")
                output = root / "transactions" / "M" / "source-material"
                self.assertEqual(list(output.iterdir()), [])
            finally:
                fixture.close()

    def test_request_rejects_authorization_claim_and_incomplete_matrix(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                _path, request = self.request(root, fixture, "R")
                authorized = copy.deepcopy(request)
                authorized["execution_authorized"] = True
                authorized["request_sha256"] = semantic(
                    {
                        key: value
                        for key, value in authorized.items()
                        if key != "request_sha256"
                    }
                )
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthoritySourceMaterialV1Error,
                    "header/claims",
                ):
                    target.validate_publication_q4_authority_source_material_request_v1(
                        authorized
                    )

                incomplete = copy.deepcopy(request)
                incomplete["runtime_authority_requests"].pop()
                incomplete["request_sha256"] = semantic(
                    {
                        key: value
                        for key, value in incomplete.items()
                        if key != "request_sha256"
                    }
                )
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthoritySourceMaterialV1Error,
                    "coverage",
                ):
                    target.validate_publication_q4_authority_source_material_request_v1(
                        incomplete
                    )

                aliased = copy.deepcopy(request)
                aliased["planned_outputs"]["source_registry_path"] = aliased[
                    "accepted_source_descriptors"
                ]["policy_qualification_receipt_path"]["path"]
                aliased["request_sha256"] = semantic(
                    {
                        key: value
                        for key, value in aliased.items()
                        if key != "request_sha256"
                    }
                )
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthoritySourceMaterialV1Error,
                    "aliases a physical source",
                ):
                    target.validate_publication_q4_authority_source_material_request_v1(
                        aliased
                    )
            finally:
                fixture.close()

    def test_nonempty_output_namespace_is_never_overwritten(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request_path, request = self.request(root, fixture, "N")
                output = root / "transactions" / "N" / "source-material"
                output.mkdir(parents=True)
                rogue = output / "untracked.json"
                rogue.write_bytes(b"preserve\n")
                with self.assertRaisesRegex(
                    target.PublicationQ4AuthoritySourceMaterialV1Error,
                    "not empty",
                ):
                    self.materialize(root, request_path, request, "N")
                self.assertEqual(rogue.read_bytes(), b"preserve\n")
                self.assertFalse((output / target.MATERIAL_FILENAME).exists())
                self.assertFalse((output / target.RECEIPT_FILENAME).exists())
            finally:
                fixture.close()

    def test_every_commit_boundary_resumes_same_path_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                boundaries = (
                    "output_directory",
                    target.MATERIAL_FILENAME,
                    target.RECEIPT_FILENAME,
                )
                for position, boundary in enumerate(boundaries):
                    run = f"C{position}"
                    request_path, request = self.request(root, fixture, run)

                    def crash(observed: str, *, expected: str = boundary) -> None:
                        if observed == expected:
                            raise InjectedCrash(expected)

                    with self.assertRaises(InjectedCrash):
                        self.materialize(
                            root,
                            request_path,
                            request,
                            run,
                            after_artifact_commit=crash,
                        )
                    output = root / "transactions" / run / "source-material"
                    before = self.identities(output)
                    receipt = self.materialize(root, request_path, request, run)
                    self.assertEqual(
                        sorted(item.name for item in output.iterdir()),
                        sorted((target.MATERIAL_FILENAME, target.RECEIPT_FILENAME)),
                    )
                    after = self.identities(output)
                    for name, identity in before.items():
                        self.assertEqual(after[name], identity)
                    second = self.materialize(root, request_path, request, run)
                    self.assertEqual(second, receipt)
                    self.assertEqual(self.identities(output), after)
            finally:
                fixture.close()

    def test_partial_tamper_foreign_entry_and_redirect_never_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                request_path, request = self.request(root, fixture, "T")

                def crash_after_material(observed: str) -> None:
                    if observed == target.MATERIAL_FILENAME:
                        raise InjectedCrash(observed)

                with self.assertRaises(InjectedCrash):
                    self.materialize(
                        root,
                        request_path,
                        request,
                        "T",
                        after_artifact_commit=crash_after_material,
                    )
                output = root / "transactions/T/source-material"
                material = output / target.MATERIAL_FILENAME
                material.chmod(0o600)
                material.write_bytes(b"tampered-partial\n")
                material.chmod(0o444)
                with self.assertRaisesRegex(
                    Exception,
                    "resumable artifact drifted|exact immutable physical file",
                ):
                    self.materialize(root, request_path, request, "T")
                self.assertEqual(material.read_bytes(), b"tampered-partial\n")
                self.assertFalse((output / target.RECEIPT_FILENAME).exists())

                request_path, request = self.request(root, fixture, "F")

                def crash_after_directory(observed: str) -> None:
                    if observed == "output_directory":
                        raise InjectedCrash(observed)

                with self.assertRaises(InjectedCrash):
                    self.materialize(
                        root,
                        request_path,
                        request,
                        "F",
                        after_artifact_commit=crash_after_directory,
                    )
                foreign_output = root / "transactions/F/source-material"
                rogue = foreign_output / "foreign.json"
                rogue.write_bytes(b"preserve\n")
                with self.assertRaisesRegex(Exception, "not empty"):
                    self.materialize(root, request_path, request, "F")
                self.assertEqual(rogue.read_bytes(), b"preserve\n")

                request_path, request = self.request(root, fixture, "R")
                with self.assertRaises(InjectedCrash):
                    self.materialize(
                        root,
                        request_path,
                        request,
                        "R",
                        after_artifact_commit=crash_after_directory,
                    )
                redirected = root / "transactions/R/source-material"
                held = root / "transactions/R/source-material-held"
                redirected.rename(held)
                redirected.symlink_to(held, target_is_directory=True)
                with self.assertRaisesRegex(Exception, "physical|link|identity"):
                    self.materialize(root, request_path, request, "R")
                self.assertEqual(list(held.iterdir()), [])
            finally:
                fixture.close()

    def test_same_invocation_exact_copy_inode_swap_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            fixture = Fixture(root)
            try:
                request_path, request = self.request(root, fixture, "A")
                output = root / "transactions/A/source-material"

                def swap(observed: str) -> None:
                    if observed != target.MATERIAL_FILENAME:
                        return
                    material = output / target.MATERIAL_FILENAME
                    payload = material.read_bytes()
                    material.unlink()
                    material.write_bytes(payload)
                    material.chmod(0o444)

                with self.assertRaisesRegex(
                    Exception,
                    "inode identity changed|namespace (?:changed|mutated)",
                ):
                    self.materialize(
                        root,
                        request_path,
                        request,
                        "A",
                        after_artifact_commit=swap,
                    )
                self.assertFalse((output / target.RECEIPT_FILENAME).exists())
            finally:
                fixture.close()

    def test_same_bytes_symlinked_upstream_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = Fixture(root)
            try:
                request_path, request = self.request(root, fixture, "S")
                descriptor = request["accepted_source_descriptors"][
                    "policy_capability_manifest_path"
                ]
                source = root / str(descriptor["path"])
                replacement = root / "accepted" / "same-bytes-copy.json"
                replacement.write_bytes(source.read_bytes())
                source.unlink()
                source.symlink_to(replacement)
                with self.assertRaisesRegex(
                    PublicationPhysicalIoV1Error, "physical file"
                ):
                    self.materialize(root, request_path, request, "S")
                output = root / "transactions" / "S" / "source-material"
                self.assertEqual(list(output.iterdir()), [])
            finally:
                fixture.close()


if __name__ == "__main__":
    unittest.main()
