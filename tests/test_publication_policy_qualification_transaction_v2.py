from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "publication_policy_qualification_transaction_v2.py"
if str(SCRIPT.parent) not in sys.path:
    sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location(
    "publication_policy_qualification_transaction_v2", SCRIPT
)
assert SPEC is not None and SPEC.loader is not None
target = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = target
SPEC.loader.exec_module(target)


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        + b"\n"
    )


def write_json(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))
    return path


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.events: list[str] = []
        self.hardware_collector = root / target.HARDWARE_RESOURCE_COLLECTOR_PATH
        self.hardware_collector.parent.mkdir(parents=True, exist_ok=True)
        self.hardware_collector.write_bytes(b"# qualification collector fixture\n")
        self.patch_path = write_json(
            root / "artifacts/images/qualification_image_identity_patch.v1.json",
            {"artifact_kind": "patch", "patch_sha256": "a" * 64},
        )
        self.accepted_manifest = write_json(
            root / "accepted/parity.yaml", {"artifact_kind": "accepted-manifest"}
        )
        self.accepted_assessment = write_json(
            root / "accepted/parity.assessment.json",
            {"artifact_kind": "accepted-assessment"},
        )
        self.accepted_receipt = write_json(
            root / "accepted/parity.receipt.json",
            {"artifact_kind": "accepted-receipt", "receipt_sha256": "b" * 64},
        )
        self.output = root / "artifacts/qualification-v2"
        self.patch = {
            "artifact_kind": target.PATCH_KIND,
            "patch_sha256": "a" * 64,
            "candidate_binding_eligible": True,
            "blockers": [],
            "workers": {
                "cpu": {"image_id": "sha256:" + "1" * 64},
                "gpu": {"image_id": "sha256:" + "2" * 64},
            },
            "systems": {
                system: {
                    "fragment_identity": {"image_id": "sha256:" + str(index) * 64}
                }
                for index, system in enumerate(target.SYSTEMS, start=3)
            },
        }

    def dependencies(self) -> target.TransactionDependencies:
        def load_patch(**kwargs):
            self.events.append("patch")
            if kwargs.get("require_candidate_eligible") is not False:
                raise AssertionError("transaction must inspect exact patch blockers")
            return json.loads(json.dumps(self.patch))

        def load_parity(**_kwargs):
            self.events.append("parity")
            return {
                "schema_version": 2,
                "artifact_kind": "vast_verified_model_parity_acceptance_binding",
                "receipt": target.file_descriptor(self.root, self.accepted_receipt),
                "accepted_manifest": target.file_descriptor(
                    self.root, self.accepted_manifest
                ),
                "accepted_assessment": target.file_descriptor(
                    self.root, self.accepted_assessment
                ),
                "binding_sha256": "c" * 64,
            }

        def materialize_fragments(**kwargs):
            self.events.append("fragments")
            destination = Path(kwargs["fragments_root"])
            result = {}
            for system in target.SYSTEMS:
                binding = write_json(
                    destination / system / "binding.json",
                    {"system": system, "authority": "nonauthorizing-test-binding"},
                )
                result[system] = write_json(
                    destination / system / "qualification_fragment.json",
                    {
                        "schema_version": 1,
                        "artifact_kind": (
                            "vast_publication_qualification_system_fragment_v1"
                        ),
                        "system": system,
                        "policy_bindings": [],
                        "resource_bindings": [
                            {
                                "path": binding.relative_to(self.root).as_posix(),
                                "sha256": hashlib.sha256(binding.read_bytes()).hexdigest(),
                            }
                        ],
                        "pilots": [],
                    },
                )
            return result

        def validate_fragments(**kwargs):
            self.events.append("validate-fragments")
            return {
                system: target.file_descriptor(self.root, path)
                for system, path in kwargs["fragment_paths"].items()
            }

        def build_index(**kwargs):
            self.events.append("candidate")
            output = Path(kwargs["output_dir"])
            output.mkdir(parents=True, exist_ok=True)
            values = {
                target.INDEX_FILENAME: {"kind": "index"},
                target.CANDIDATE_MANIFEST_FILENAME: {"kind": "candidate"},
                target.CANDIDATE_RECEIPT_FILENAME: {"kind": "candidate-receipt"},
            }
            for name, value in values.items():
                path = output / name
                payload = canonical(value)
                if path.exists():
                    if path.read_bytes() != payload:
                        raise AssertionError(f"candidate collision: {name}")
                else:
                    path.write_bytes(payload)
            return {
                "index_path": output / target.INDEX_FILENAME,
                "candidate_manifest_path": output / target.CANDIDATE_MANIFEST_FILENAME,
                "candidate_receipt_path": output / target.CANDIDATE_RECEIPT_FILENAME,
            }

        def build_bootstrap(**kwargs):
            self.events.append("bootstrap")
            output = Path(kwargs["output_dir"])
            output.mkdir(parents=True)
            calibrations = {
                system: write_json(
                    output / target.CALIBRATION_FILENAME.format(system=system),
                    {"system": system},
                )
                for system in target.SYSTEMS
            }
            return {
                "mapping_path": write_json(
                    output / target.MAPPING_FILENAME, {"kind": "mapping"}
                ),
                "calibration_paths": calibrations,
                "receipt_path": write_json(
                    output / target.BOOTSTRAP_RECEIPT_FILENAME,
                    {"kind": "bootstrap-receipt"},
                ),
            }

        def validate_complete(**_kwargs):
            self.events.append("validate-complete")
            return object()

        return target.TransactionDependencies(
            load_identity_patch=load_patch,
            load_parity_acceptance=load_parity,
            materialize_fragments=materialize_fragments,
            validate_fragments=validate_fragments,
            build_index=build_index,
            build_bootstrap=build_bootstrap,
            validate_complete=validate_complete,
        )

    def run(self, dependencies=None, **overrides):
        return target.materialize_publication_policy_qualification_transaction_v2(
            project_root=self.root,
            identity_patch_path=self.patch_path,
            accepted_model_parity_manifest_path=self.accepted_manifest,
            accepted_model_parity_assessment_path=self.accepted_assessment,
            accepted_model_parity_receipt_path=self.accepted_receipt,
            output_root=self.output,
            dependencies=dependencies or self.dependencies(),
            **overrides,
        )


class SyntheticAtomicCrash(BaseException):
    pass


class QualificationTransactionV2Tests(unittest.TestCase):
    def test_transaction_receipt_accepts_drvfs_0555_projection(self) -> None:
        root = Path("/project")
        path = root / target.TRANSACTION_RECEIPT_FILENAME
        payload = b"{}\n"
        descriptor = {
            "path": target.TRANSACTION_RECEIPT_FILENAME,
            "size_bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
        }
        identity = (119, 844424932099895)
        custody = mock.Mock(root=root)
        custody.commit_or_adopt_exact_identity.return_value = (
            descriptor,
            identity,
            "adopted",
        )
        custody.stat_regular_identity.return_value = (0o555, identity)
        custody.read_descriptor_identity.return_value = (
            descriptor,
            payload,
            identity,
        )
        token = target._ACTIVE_CUSTODY.set(custody)
        try:
            target._commit_receipt_atomic(path, payload)
        finally:
            target._ACTIVE_CUSTODY.reset(token)

    def test_bootstrap_calibration_filename_matches_real_producer_contract(self) -> None:
        bootstrap_script = (
            ROOT / "scripts" / "publication_policy_qualification_bootstrap_v2.py"
        )
        bootstrap_spec = importlib.util.spec_from_file_location(
            "publication_policy_qualification_bootstrap_v2_contract_test",
            bootstrap_script,
        )
        assert bootstrap_spec is not None and bootstrap_spec.loader is not None
        bootstrap = importlib.util.module_from_spec(bootstrap_spec)
        bootstrap_spec.loader.exec_module(bootstrap)
        self.assertEqual(target.CALIBRATION_FILENAME, bootstrap.CALIBRATION_FILENAME)

    def test_exact_order_receipt_last_and_resume_without_rewriting(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory).resolve())
            dependencies = fixture.dependencies()
            result = fixture.run(dependencies)
            self.assertEqual(
                fixture.events,
                [
                    "patch",
                    "parity",
                    "fragments",
                    "validate-fragments",
                    "candidate",
                    "bootstrap",
                    "validate-complete",
                    "patch",
                    "parity",
                    "validate-fragments",
                    "validate-complete",
                ],
            )
            receipt_path = Path(result["transaction_receipt_path"])
            self.assertEqual(receipt_path.name, target.TRANSACTION_RECEIPT_FILENAME)
            receipt = json.loads(receipt_path.read_bytes())
            self.assertEqual(receipt["artifact_kind"], target.TRANSACTION_KIND)
            self.assertFalse(receipt["accepted"])
            self.assertFalse(receipt["publication_ready"])
            self.assertFalse(receipt["authorization_eligible"])
            self.assertEqual(receipt["cell_count"], 32)
            self.assertEqual(
                receipt["image_patch_resolution"]["resolution"],
                "unchanged_v3_parity",
            )
            self.assertEqual(receipt["systems"], list(target.SYSTEMS))
            self.assertEqual(
                receipt["hardware_resource_collector"],
                target.file_descriptor(fixture.root, fixture.hardware_collector),
            )
            self.assertEqual(
                receipt["image_identity_patch"]["path"],
                fixture.patch_path.relative_to(fixture.root).as_posix(),
            )
            first_bytes = receipt_path.read_bytes()
            first_events = len(fixture.events)
            resumed = fixture.run(dependencies)
            self.assertEqual(Path(resumed["transaction_receipt_path"]).read_bytes(), first_bytes)
            self.assertNotIn("fragments", fixture.events[first_events:])
            self.assertNotIn("candidate", fixture.events[first_events:])
            self.assertNotIn("bootstrap", fixture.events[first_events:])

    def test_candidate_receipt_last_prefixes_resume_via_candidate_producer(self) -> None:
        prefixes = (
            (target.INDEX_FILENAME,),
            (target.INDEX_FILENAME, target.CANDIDATE_MANIFEST_FILENAME),
        )
        values = {
            target.INDEX_FILENAME: {"kind": "index"},
            target.CANDIDATE_MANIFEST_FILENAME: {"kind": "candidate"},
        }
        for prefix in prefixes:
            with self.subTest(prefix=prefix), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(Path(directory).resolve())
                candidate_root = fixture.output / target.CANDIDATE_DIRNAME
                for name in prefix:
                    write_json(candidate_root / name, values[name])

                result = fixture.run()

                self.assertIn("candidate", fixture.events)
                self.assertTrue(Path(result["candidate_receipt_path"]).is_file())
                self.assertEqual(
                    {path.name for path in candidate_root.iterdir()},
                    {
                        target.INDEX_FILENAME,
                        target.CANDIDATE_MANIFEST_FILENAME,
                        target.CANDIDATE_RECEIPT_FILENAME,
                    },
                )

    def test_candidate_nonprefix_partial_states_remain_fail_closed(self) -> None:
        states = (
            (target.CANDIDATE_MANIFEST_FILENAME,),
            (target.CANDIDATE_RECEIPT_FILENAME,),
            (target.INDEX_FILENAME, target.CANDIDATE_RECEIPT_FILENAME),
        )
        for state in states:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(Path(directory).resolve())
                candidate_root = fixture.output / target.CANDIDATE_DIRNAME
                for name in state:
                    write_json(candidate_root / name, {"unexpected": name})

                with self.assertRaisesRegex(
                    target.QualificationTransactionV2Error,
                    "not a valid receipt-last prefix",
                ):
                    fixture.run()
                self.assertNotIn("candidate", fixture.events)

    def test_receipt_recovers_every_atomic_physical_window_same_path(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(Path(directory).resolve())
                dependencies = fixture.dependencies()
                fired = False

                def crash(observed_step: str, path: Path) -> None:
                    nonlocal fired
                    if (
                        not fired
                        and path.name == target.TRANSACTION_RECEIPT_FILENAME
                        and observed_step == step
                    ):
                        fired = True
                        raise SyntheticAtomicCrash(step)

                with self.assertRaises(SyntheticAtomicCrash):
                    fixture.run(
                        dependencies,
                        after_physical_commit_step=crash,
                    )
                self.assertTrue(fired)
                receipt = fixture.output / target.TRANSACTION_RECEIPT_FILENAME
                published_identity = (
                    (receipt.stat().st_dev, receipt.stat().st_ino)
                    if step == "post_publish_pre_parent_fsync"
                    else None
                )
                resumed = fixture.run(dependencies)
                self.assertEqual(
                    Path(resumed["transaction_receipt_path"]), receipt
                )
                self.assertEqual(receipt.stat().st_mode & 0o777, 0o444)
                if published_identity is not None:
                    self.assertEqual(
                        (receipt.stat().st_dev, receipt.stat().st_ino),
                        published_identity,
                    )

    def test_ineligible_patch_fails_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory).resolve())
            dependencies = fixture.dependencies()

            def reject_patch(**_kwargs):
                raise target.QualificationTransactionV2Error(
                    "worker identity changed; physical parity refresh required"
                )

            with self.assertRaisesRegex(
                target.QualificationTransactionV2Error, "physical parity refresh"
            ):
                fixture.run(replace(dependencies, load_identity_patch=reject_patch))
            self.assertFalse(fixture.output.exists())

    def test_exact_refresh_only_patch_requires_cross_bound_v4_acceptance(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory).resolve())
            fixture.patch["candidate_binding_eligible"] = False
            fixture.patch["blockers"] = list(target.REFRESH_ONLY_BLOCKERS)
            dependencies = fixture.dependencies()

            def load_v4(**_kwargs):
                return {
                    "schema_version": 4,
                    "artifact_kind": target.V4_PARITY_BINDING_KIND,
                    "receipt": target.file_descriptor(
                        fixture.root, fixture.accepted_receipt
                    ),
                    "accepted_manifest": target.file_descriptor(
                        fixture.root, fixture.accepted_manifest
                    ),
                    "accepted_assessment": target.file_descriptor(
                        fixture.root, fixture.accepted_assessment
                    ),
                    "refresh_authority": {
                        "image_identity_patch": {
                            **target.file_descriptor(
                                fixture.root, fixture.patch_path
                            ),
                            "patch_sha256": fixture.patch["patch_sha256"],
                            "refresh_blockers": list(
                                target.REFRESH_ONLY_BLOCKERS
                            ),
                            "resolved_blockers": [],
                        },
                        "workers": json.loads(
                            json.dumps(fixture.patch["workers"])
                        ),
                    },
                    "binding_sha256": "d" * 64,
                }

            result = fixture.run(
                replace(dependencies, load_parity_acceptance=load_v4)
            )
            receipt = json.loads(Path(result["transaction_receipt_path"]).read_bytes())
            self.assertEqual(receipt["model_parity_acceptance_schema_version"], 4)
            self.assertEqual(
                receipt["image_patch_resolution"]["resolution"],
                "physical_patch_bound_v4_parity_refresh",
            )

            fixture2 = Fixture(Path(directory).resolve() / "cross")
            fixture2.patch["candidate_binding_eligible"] = False
            fixture2.patch["blockers"] = list(target.REFRESH_ONLY_BLOCKERS)
            deps2 = fixture2.dependencies()

            def stale_v4(**_kwargs):
                value = load_v4()
                value["receipt"] = target.file_descriptor(
                    fixture2.root, fixture2.accepted_receipt
                )
                value["accepted_manifest"] = target.file_descriptor(
                    fixture2.root, fixture2.accepted_manifest
                )
                value["accepted_assessment"] = target.file_descriptor(
                    fixture2.root, fixture2.accepted_assessment
                )
                value["refresh_authority"]["image_identity_patch"].update(
                    target.file_descriptor(fixture2.root, fixture2.patch_path)
                )
                value["refresh_authority"]["image_identity_patch"][
                    "patch_sha256"
                ] = "0" * 64
                value["refresh_authority"]["workers"] = fixture2.patch["workers"]
                return value

            with self.assertRaisesRegex(
                target.QualificationTransactionV2Error,
                "stale or cross-bound",
            ):
                fixture2.run(replace(deps2, load_parity_acceptance=stale_v4))
            self.assertFalse(fixture2.output.exists())

    def test_committed_receipt_tamper_is_rejected_on_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory).resolve())
            dependencies = fixture.dependencies()
            result = fixture.run(dependencies)
            receipt_path = Path(result["transaction_receipt_path"])
            receipt_path.chmod(0o600)
            receipt_path.write_bytes(receipt_path.read_bytes().replace(b'"cell_count":32', b'"cell_count":31'))
            with self.assertRaisesRegex(
                target.QualificationTransactionV2Error, "transaction receipt"
            ):
                fixture.run(dependencies)

    def test_hardware_collector_missing_or_tampered_is_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory).resolve())
            fixture.hardware_collector.unlink()
            with self.assertRaisesRegex(
                target.QualificationTransactionV2Error,
                "hardware resource collector is missing",
            ):
                fixture.run()
            self.assertFalse(fixture.output.exists())

        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory).resolve())
            dependencies = fixture.dependencies()
            fixture.run(dependencies)
            fixture.hardware_collector.write_bytes(b"# tampered collector\n")
            with self.assertRaisesRegex(
                target.QualificationTransactionV2Error,
                "transaction receipt",
            ):
                fixture.run(dependencies)

    def test_source_contains_no_production_authority_or_overwrite_path(self) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("os.replace(receipt", source)
        self.assertNotIn("production_ready", source)
        self.assertNotIn("grant_sha256", source)

    def test_resume_cold_rechecks_fragment_candidate_and_bootstrap_payloads(self) -> None:
        for phase, relative in (
            ("fragment", "fragments/deepstream/qualification_fragment.json"),
            ("candidate", f"candidate/{target.INDEX_FILENAME}"),
            ("bootstrap", f"bootstrap/{target.MAPPING_FILENAME}"),
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(Path(directory).resolve())
                dependencies = fixture.dependencies()
                result = fixture.run(dependencies)
                receipt = Path(result["transaction_receipt_path"])
                receipt_before = receipt.read_bytes()
                artifact = fixture.output / relative
                artifact.chmod(0o600)
                artifact.write_bytes(canonical({"tampered_phase": phase}))
                with self.assertRaises(target.QualificationTransactionV2Error):
                    fixture.run(dependencies)
                self.assertEqual(receipt.read_bytes(), receipt_before)


if __name__ == "__main__":
    unittest.main()
