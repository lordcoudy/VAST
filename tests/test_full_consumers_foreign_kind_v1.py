"""R13/S6: full consumers reject foreign kinds before touching their roots.

Every full qualification, accepted-policy, promotion, Q4 and full-publication
entrypoint receives a component receipt kind, a finite-study kind and an
unknown kind through its real entry.  Each call must fail with the consumer's
own error or exit code, and the complete fresh temporary tree (inputs, output
roots and work roots) must be byte-for-byte unchanged afterwards.  The
consumer inventory is recorded in
``openspec/changes/qualify-full-benchmark/evidence/software-v1-consumers``.
"""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr
import copy
import hashlib
import io
import json
import os
import shutil
import stat
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import backend_q4_two_phase_executor_v1 as q4_executor  # noqa: E402
import canonical_systems_study_plan_v1 as study_plan  # noqa: E402
import full_publication_entrypoint as full_publication  # noqa: E402
import full_resource_qualification as resource_promotion  # noqa: E402
import publication_gstreamer_component_authority_v1 as component_authority  # noqa: E402
import publication_gstreamer_component_runtime_v1 as component_runtime  # noqa: E402
import publication_guardian_accepted_policy_preprocessing_contract_v1 as accepted_policy  # noqa: E402
import publication_guardian_component_preprocessing_contract_v1 as component_preprocessing  # noqa: E402
import publication_policy_qualification as policy_promotion  # noqa: E402
import publication_policy_qualification_execution_closure_v1 as closure  # noqa: E402
import publication_policy_qualification_pilot_executor_v2 as pilot_executor  # noqa: E402
import publication_policy_qualification_runtime_inputs_v2 as runtime_inputs  # noqa: E402
import publication_q4_authority_plan_pipeline_v1 as q4_pipeline  # noqa: E402
from full_publication_runner import ExitCode  # noqa: E402

from tests.test_backend_q4_two_phase_executor_v1 import (  # noqa: E402
    source_registry as q4_source_registry,
)
from tests.test_full_publication_entrypoint import minimal_config  # noqa: E402
from tests.test_full_resource_qualification import (  # noqa: E402
    _fixture as resource_index_fixture,
)
from tests.test_publication_guardian_accepted_policy_preprocessing_contract_v1 import (  # noqa: E402
    Fixture as AcceptedPolicyFixture,
    semantic as accepted_policy_semantic,
    write_json as accepted_policy_write_json,
)
from tests.test_publication_policy_qualification import (  # noqa: E402
    _completed_v2_fixture as policy_index_fixture,
)


COMPONENT_AUTHORITY_KIND = component_authority.KIND
COMPONENT_RUNTIME_BUNDLE_KIND = component_runtime.BUNDLE_KIND
COMPONENT_PREPROCESSING_KIND = component_preprocessing.RECEIPT_KIND
STUDY_KIND = study_plan.KIND
UNKNOWN_KIND = "vast_unknown_full_authority_kind_v1"
LINUX = os.name == "posix" and sys.platform.startswith("linux")


def foreign_kinds(component_kind: str = COMPONENT_AUTHORITY_KIND) -> tuple[tuple[str, str], ...]:
    return (
        ("component", component_kind),
        ("study", STUDY_KIND),
        ("unknown", UNKNOWN_KIND),
    )


def canonical(value: object) -> bytes:
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")


def semantic_sha(value: object) -> str:
    return hashlib.sha256(canonical(value).rstrip(b"\n")).hexdigest()


def file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite_kind(path: Path, kind: str, *, self_hash: str | None = None) -> None:
    value = json.loads(path.read_bytes())
    value["artifact_kind"] = kind
    if self_hash is not None:
        unsigned = {key: item for key, item in value.items() if key != self_hash}
        value[self_hash] = semantic_sha(unsigned)
    path.write_bytes(canonical(value))


def tree_snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    """Every entry under ``root`` with its type and, for files, exact bytes."""

    snapshot: dict[str, tuple[object, ...]] = {}
    for current, directories, files in os.walk(root, followlinks=False):
        base = Path(current)
        for name in (*directories, *files):
            path = base / name
            relative = path.relative_to(root).as_posix()
            info = path.lstat()
            if stat.S_ISDIR(info.st_mode):
                snapshot[relative] = ("dir",)
            elif stat.S_ISREG(info.st_mode):
                snapshot[relative] = ("file", info.st_size, file_sha(path))
            else:
                snapshot[relative] = ("other", stat.S_IFMT(info.st_mode))
    return snapshot


def tree_delta(
    before: dict[str, tuple[object, ...]], after: dict[str, tuple[object, ...]]
) -> dict[str, list[str]]:
    delta = {
        "created": sorted(set(after) - set(before)),
        "removed": sorted(set(before) - set(after)),
        "changed": sorted(
            path for path in set(before) & set(after) if before[path] != after[path]
        ),
    }
    return {key: value for key, value in delta.items() if value}


_TRIPWIRE: dict[str, object] = {"root": None, "events": None}


def _creation_target(event: str, args: tuple[object, ...]) -> tuple[object, object] | None:
    if event == "open":
        flags = args[2]
        if isinstance(flags, int) and flags & os.O_CREAT:
            return args[0], None
    elif event == "os.mkdir":
        return args[0], args[2]
    elif event == "os.symlink":
        return args[1], args[2]
    elif event in {"os.link", "os.rename"}:
        return args[1], args[3]
    return None


def _resolve_created(path: object, dir_fd: object) -> str | None:
    if isinstance(path, int):
        return None
    text = os.fsdecode(path)  # type: ignore[arg-type]
    if os.path.isabs(text):
        return os.path.normpath(text)
    if isinstance(dir_fd, int) and dir_fd >= 0:
        try:
            base = os.readlink(f"/proc/self/fd/{dir_fd}")
        except OSError:
            return f"<unresolved dir_fd>/{text}"
        return os.path.normpath(os.path.join(base, text))
    # os.open(..., dir_fd=...) does not expose dir_fd to audit hooks.
    return f"<relative>/{text}"


def _creation_audit_hook(event: str, args: tuple[object, ...]) -> None:
    events = _TRIPWIRE["events"]
    if events is None:
        return
    try:
        target = _creation_target(event, args)
        if target is None:
            return
        resolved = _resolve_created(*target)
        root = str(_TRIPWIRE["root"])
        if resolved is not None and (
            resolved.startswith("<")
            or resolved == root
            or resolved.startswith(root + os.sep)
        ):
            events.append(f"{event}:{resolved}")  # type: ignore[union-attr]
    except Exception:  # an audit hook must never alter the audited call
        return


sys.addaudithook(_creation_audit_hook)


@contextmanager
def creation_tripwire(root: Path):  # type: ignore[no-untyped-def]
    """Record every directory/file creation under ``root``, even if rolled back."""

    events: list[str] = []
    _TRIPWIRE.update(root=os.path.realpath(root), events=events)
    try:
        yield events
    finally:
        _TRIPWIRE.update(root=None, events=None)


class ForeignKindAssertions(unittest.TestCase):
    def assert_no_creation(self, events: list[str]) -> None:
        self.assertEqual(events, [], f"created before rejection: {events}")

    def assert_tree_unchanged(
        self, root: Path, before: dict[str, tuple[object, ...]]
    ) -> None:
        delta = tree_delta(before, tree_snapshot(root))
        self.assertEqual(delta, {}, f"side effects before rejection: {delta}")

    def assert_rejected_without_side_effects(
        self,
        root: Path,
        call: Callable[[], object],
        *,
        error: type[BaseException],
        message: str,
        absent: tuple[Path, ...] = (),
    ) -> BaseException:
        before = tree_snapshot(root)
        with creation_tripwire(root) as created:
            with self.assertRaisesRegex(error, message) as caught:
                call()
        self.assert_tree_unchanged(root, before)
        self.assert_no_creation(created)
        for path in absent:
            self.assertFalse(os.path.lexists(path), path)
        return caught.exception

    def assert_exit_without_side_effects(
        self,
        root: Path,
        call: Callable[[], int],
        *,
        exit_code: int,
        message: str,
        absent: tuple[Path, ...] = (),
    ) -> str:
        before = tree_snapshot(root)
        stderr = io.StringIO()
        with creation_tripwire(root) as created, redirect_stderr(stderr):
            observed = call()
        self.assertEqual(observed, exit_code, stderr.getvalue())
        self.assertRegex(stderr.getvalue(), message)
        self.assert_tree_unchanged(root, before)
        self.assert_no_creation(created)
        for path in absent:
            self.assertFalse(os.path.lexists(path), path)
        return stderr.getvalue()


@unittest.skipUnless(LINUX, "the qualification input fixture binds AF_UNIX sockets")
class QualificationRuntimeInputsForeignKindTests(ForeignKindAssertions):
    def fixture(self, root: Path):  # type: ignore[no-untyped-def]
        from tests.test_publication_policy_qualification_pilot_executor_v2 import (
            InputFixture,
        )

        fixture = InputFixture(root)
        self.addCleanup(fixture.close)
        output = fixture.bootstrap_dir / pilot_executor.RUNTIME_BUNDLE_DIRECTORY
        shutil.rmtree(output)
        scratch = root / "scratch"
        scratch.mkdir()
        return fixture, output, scratch

    def argv(self, fixture, scratch: Path) -> list[str]:  # type: ignore[no-untyped-def]
        return [
            "--project-root", str(fixture.root),
            "--candidate-index", str(fixture.candidate_index),
            "--candidate-manifest", str(fixture.candidate_manifest),
            "--candidate-receipt", str(fixture.candidate_receipt),
            "--bootstrap-mapping", str(fixture.bootstrap_mapping),
            "--bootstrap-receipt", str(fixture.bootstrap_receipt),
            "--bootstrap-dir", str(fixture.bootstrap_dir),
            "--qualification-transaction-receipt", str(fixture.transaction_receipt),
            "--scratch-root", str(scratch),
        ]

    def test_candidate_index_foreign_kind_is_rejected_before_bundle_output(self) -> None:
        for label, kind in foreign_kinds(COMPONENT_RUNTIME_BUNDLE_KIND):
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture, output, scratch = self.fixture(Path(tmp).resolve())
                rewrite_kind(fixture.candidate_index, kind)
                self.assert_rejected_without_side_effects(
                    fixture.root,
                    lambda: runtime_inputs.main(self.argv(fixture, scratch)),
                    error=runtime_inputs.QualificationRuntimeInputMaterializationV2Error,
                    message="candidate index is not the exact fragment-only v2 bootstrap index",
                    absent=(output,),
                )

    def test_transaction_receipt_foreign_kind_is_rejected_before_bundle_output(self) -> None:
        for label, kind in foreign_kinds(COMPONENT_RUNTIME_BUNDLE_KIND):
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture, output, scratch = self.fixture(Path(tmp).resolve())
                rewrite_kind(fixture.transaction_receipt, kind)
                self.assert_rejected_without_side_effects(
                    fixture.root,
                    lambda: runtime_inputs.main(self.argv(fixture, scratch)),
                    error=runtime_inputs.QualificationRuntimeInputMaterializationV2Error,
                    message="qualification transaction preflight failed",
                    absent=(output,),
                )


@unittest.skipUnless(LINUX, "the qualification input fixture binds AF_UNIX sockets")
class QualificationPilotExecutorForeignKindTests(ForeignKindAssertions):
    def fixture(self, root: Path):  # type: ignore[no-untyped-def]
        from tests.test_publication_policy_qualification_pilot_executor_v2 import (
            InputFixture,
        )

        fixture = InputFixture(root)
        self.addCleanup(fixture.close)
        return fixture

    def argv(self, fixture, pilots: Path, checkpoint: Path) -> list[str]:  # type: ignore[no-untyped-def]
        return [
            "--project-root", str(fixture.root),
            "--candidate-index", str(fixture.candidate_index),
            "--candidate-manifest", str(fixture.candidate_manifest),
            "--candidate-receipt", str(fixture.candidate_receipt),
            "--bootstrap-mapping", str(fixture.bootstrap_mapping),
            "--bootstrap-receipt", str(fixture.bootstrap_receipt),
            "--bootstrap-dir", str(fixture.bootstrap_dir),
            "--qualification-transaction-receipt", str(fixture.transaction_receipt),
            "--runtime-input-materialization-receipt",
            str(fixture.runtime_materialization_receipt),
            "--guardian-service-authority", str(fixture.guardian_service_authority),
            "--preprocessing-contract", str(fixture.preprocessing_contract),
            "--preprocessing-contract-receipt", str(fixture.preprocessing_receipt),
            "--execution-code-closure-receipt",
            str(fixture.execution_code_closure_receipt),
            "--pilot-root", str(pilots),
            "--checkpoint", str(checkpoint),
        ]

    def assert_rejected(self, fixture, *, message: str) -> None:  # type: ignore[no-untyped-def]
        fresh = fixture.root / "fresh"
        pilots = fresh / "pilots"
        checkpoint = fixture.root / "fresh-state" / "pilot-execution.v3.json"
        self.assert_rejected_without_side_effects(
            fixture.root,
            lambda: pilot_executor.main(self.argv(fixture, pilots, checkpoint)),
            error=pilot_executor.QualificationPilotExecutorV2Error,
            message=message,
            absent=(fresh, checkpoint.parent),
        )

    def test_candidate_index_foreign_kind_is_rejected_before_pilot_root_or_lock(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture = self.fixture(Path(tmp).resolve())
                rewrite_kind(fixture.candidate_index, kind)
                self.assert_rejected(
                    fixture,
                    message="candidate index is not the exact fragment-only v2 bootstrap index",
                )

    def test_runtime_receipt_foreign_kind_is_rejected_before_pilot_root_or_lock(self) -> None:
        for label, kind in foreign_kinds(COMPONENT_RUNTIME_BUNDLE_KIND):
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture = self.fixture(Path(tmp).resolve())
                rewrite_kind(
                    fixture.runtime_materialization_receipt,
                    kind,
                    self_hash="receipt_sha256",
                )
                self.assert_rejected(
                    fixture,
                    message="runtime-input materialization receipt binding drifted",
                )


@unittest.skipUnless(LINUX, "the execution closure fixture binds AF_UNIX sockets")
class QualificationExecutionClosureForeignKindTests(ForeignKindAssertions):
    def argv(self, fixture, output: Path) -> list[str]:  # type: ignore[no-untyped-def]
        return [
            "--project-root", str(fixture.root),
            "--qualification-transaction-receipt", str(fixture.transaction),
            "--preprocessing-contract", str(fixture.contract),
            "--preprocessing-materialization-receipt",
            str(fixture.preprocessing_receipt),
            "--runtime-input-materialization-receipt", str(fixture.runtime_receipt),
            "--guardian-service-authority", str(fixture.authority_path),
            "--guardian-service-lifecycle", str(fixture.lifecycle_path),
            "--pilot-root", str(fixture.pilot_root),
            "--checkpoint", str(fixture.checkpoint),
            "--output-dir", str(output),
        ]

    def assert_rejected(self, fixture, *, message: str) -> None:  # type: ignore[no-untyped-def]
        fresh = fixture.root / "fresh"
        output = fresh / "execution-closure"
        self.assert_exit_without_side_effects(
            fixture.root,
            lambda: closure.main(self.argv(fixture, output)),
            exit_code=78,
            message=message,
            absent=(fresh, fixture.output),
        )

    def test_transaction_receipt_foreign_kind_exits_before_output(self) -> None:
        from tests.test_publication_policy_qualification_execution_closure_v1 import Fixture

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture(Path(tmp).resolve())
                rewrite_kind(fixture.transaction, kind)
                self.assert_rejected(
                    fixture,
                    message="qualification transaction receipt identity drifted",
                )

    def test_preprocessing_receipt_foreign_kind_exits_before_output(self) -> None:
        from tests.test_publication_policy_qualification_execution_closure_v1 import Fixture

        for label, kind in foreign_kinds(COMPONENT_PREPROCESSING_KIND):
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture(Path(tmp).resolve())
                rewrite_kind(
                    fixture.preprocessing_receipt, kind, self_hash="receipt_sha256"
                )
                self.assert_rejected(
                    fixture,
                    message="guardian preprocessing transaction/contract binding drifted",
                )


class AcceptedPolicyPreprocessingForeignKindTests(ForeignKindAssertions):
    def materialize(self, fixture: AcceptedPolicyFixture) -> Callable[[], object]:
        output = fixture.root / "fresh" / "accepted-preprocessing"
        return lambda: fixture.materialize(output)

    def roots(self, fixture: AcceptedPolicyFixture) -> tuple[Path, ...]:
        return (
            fixture.root / "fresh",
            fixture.root / ".publication-guardian-materialization-intents-v1",
            fixture.root / ".publication-atomic-staging-v1",
        )

    def test_accepted_policy_receipt_foreign_kind_is_rejected_before_output(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture = AcceptedPolicyFixture(Path(tmp).resolve())
                receipt = {
                    key: value
                    for key, value in fixture.accepted_receipt.items()
                    if key != "sha256"
                }
                receipt["artifact_kind"] = kind
                receipt["sha256"] = accepted_policy_semantic(receipt)
                accepted_policy_write_json(fixture.accepted_receipt_path, receipt)
                self.assert_rejected_without_side_effects(
                    fixture.root,
                    self.materialize(fixture),
                    error=accepted_policy.AcceptedPolicyGuardianPreprocessingContractV1Error,
                    message="accepted policy qualification receipt schema/status/coverage drifted",
                    absent=self.roots(fixture),
                )

    def test_completed_qualification_index_foreign_kind_is_rejected_before_output(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture = AcceptedPolicyFixture(Path(tmp).resolve())
                index = copy.deepcopy(fixture.index)
                index["artifact_kind"] = kind
                accepted_policy_write_json(fixture.index_path, index)
                self.assert_rejected_without_side_effects(
                    fixture.root,
                    self.materialize(fixture),
                    error=accepted_policy.AcceptedPolicyGuardianPreprocessingContractV1Error,
                    message="completed qualification index",
                    absent=self.roots(fixture),
                )


class PolicyPromotionForeignKindTests(ForeignKindAssertions):
    def test_promotion_cli_rejects_foreign_index_kind_before_output(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                index_path, index = policy_index_fixture(root)
                index["artifact_kind"] = kind
                index_path.write_text(
                    json.dumps(index, sort_keys=True) + "\n", encoding="utf-8"
                )
                output = root / "fresh" / "promoted"
                argv = [
                    "publication_policy_qualification.py",
                    "--project-root", str(root),
                    "--index-path", index_path.relative_to(root).as_posix(),
                    "--output-dir", str(output),
                ]
                with mock.patch.object(sys, "argv", argv):
                    self.assert_rejected_without_side_effects(
                        root,
                        policy_promotion.main,
                        error=policy_promotion.QualificationError,
                        message="qualification index schema/fields drifted",
                        absent=(
                            root / "fresh",
                            root / ".publication-atomic-staging-v1",
                        ),
                    )


class ResourcePromotionForeignKindTests(ForeignKindAssertions):
    def test_promotion_cli_rejects_foreign_index_kind_before_output(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                index_path, index = resource_index_fixture(root)
                index["artifact_kind"] = kind
                index_path.write_text(
                    json.dumps(index, sort_keys=True) + "\n", encoding="utf-8"
                )
                output = root / "fresh" / "promoted"
                argv = [
                    "full_resource_qualification.py",
                    "--project-root", str(root),
                    "--index-path", index_path.relative_to(root).as_posix(),
                    "--output-dir", str(output),
                ]
                with mock.patch.object(sys, "argv", argv):
                    self.assert_rejected_without_side_effects(
                        root,
                        resource_promotion.main,
                        error=resource_promotion.FullResourceQualificationError,
                        message="qualification index schema/fields drifted",
                        absent=(
                            root / "fresh",
                            root / ".publication-atomic-staging-v1",
                        ),
                    )


@unittest.skipUnless(LINUX, "Q4 authority-plan custody is POSIX dirfd based")
class Q4AuthorityPlanPipelineForeignKindTests(ForeignKindAssertions):
    @staticmethod
    def document(fields: frozenset[str], kind: str) -> dict[str, object]:
        value: dict[str, object] = {field: None for field in sorted(fields)}
        value.update(
            {
                "schema_version": q4_pipeline.SCHEMA_VERSION,
                "artifact_kind": kind,
                "status": "accepted",
                "authorization_eligible": False,
                "execution_authorized": False,
            }
        )
        return value

    def test_source_spec_phase_rejects_foreign_source_material_before_output(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                material_path = root / "specs" / "q4.material.json"
                material_path.parent.mkdir()
                material = self.document(
                    q4_pipeline._SOURCE_SPEC_MATERIAL_FIELDS,  # noqa: SLF001
                    kind,
                )
                material_path.write_bytes(
                    q4_pipeline.canonical_bytes(material, newline=True)
                )
                output = root / "specs" / "q4.source-spec.json"
                argv = [
                    "source-spec",
                    "--project-root", str(root),
                    "--source-material", str(material_path),
                    "--source-material-file-sha256", file_sha(material_path),
                    "--source-material-sha256", q4_pipeline.canonical_sha256(material),
                    "--output", str(output),
                ]
                self.assert_exit_without_side_effects(
                    root,
                    lambda: q4_pipeline.main(argv),
                    exit_code=q4_pipeline.EXIT_REJECTED,
                    message="source-spec header/claims drifted",
                    absent=(output, root / ".publication-atomic-staging-v1"),
                )

    def test_phase1_rejects_foreign_source_spec_before_output(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                spec_path = root / "specs" / "q4.source-spec.json"
                spec_path.parent.mkdir()
                spec = self.document(q4_pipeline._SOURCE_SPEC_FIELDS, kind)  # noqa: SLF001
                spec["source_spec_sha256"] = "1" * 64
                spec_path.write_bytes(q4_pipeline.canonical_bytes(spec, newline=True))
                (root / "transactions").mkdir()
                output = root / "transactions" / "phase1"
                argv = [
                    "phase1",
                    "--project-root", str(root),
                    "--source-spec", str(spec_path),
                    "--source-spec-file-sha256", file_sha(spec_path),
                    "--source-spec-sha256", "1" * 64,
                    "--output-dir", str(output),
                ]
                self.assert_exit_without_side_effects(
                    root,
                    lambda: q4_pipeline.main(argv),
                    exit_code=q4_pipeline.EXIT_REJECTED,
                    message="source-spec header/claims drifted",
                    absent=(output, root / ".publication-atomic-staging-v1"),
                )

    def test_phase2_rejects_foreign_phase1_receipt_before_output(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                phase1_path = (
                    root / "transactions" / "phase1" / q4_pipeline.PHASE1_RECEIPT_FILENAME
                )
                phase1_path.parent.mkdir(parents=True)
                phase1 = self.document(q4_pipeline._PHASE1_FIELDS, kind)  # noqa: SLF001
                phase1["receipt_sha256"] = "2" * 64
                phase1_path.write_bytes(q4_pipeline.canonical_bytes(phase1, newline=True))
                result_path = root / "runtime" / "result.json"
                result_path.parent.mkdir()
                result_path.write_bytes(q4_pipeline.canonical_bytes({}, newline=True))
                output = root / "transactions" / "phase2"
                argv = [
                    "phase2",
                    "--project-root", str(root),
                    "--phase1-receipt", str(phase1_path),
                    "--phase1-receipt-file-sha256", file_sha(phase1_path),
                    "--phase1-receipt-sha256", "2" * 64,
                    "--runtime-materialization-result", str(result_path),
                    "--runtime-materialization-result-file-sha256", file_sha(result_path),
                    "--runtime-materialization-result-sha256", "3" * 64,
                    "--output-dir", str(output),
                ]
                self.assert_exit_without_side_effects(
                    root,
                    lambda: q4_pipeline.main(argv),
                    exit_code=q4_pipeline.EXIT_REJECTED,
                    message="Phase1 receipt header/claims drifted",
                    absent=(output, root / ".publication-atomic-staging-v1"),
                )


class Q4TwoPhaseExecutorForeignKindTests(ForeignKindAssertions):
    def test_cli_rejects_foreign_source_registry_before_work_dir(self) -> None:
        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                registry = q4_source_registry(root)
                rewrite_kind(registry, kind)
                work = root / "fresh" / "q4-work"
                argv = [
                    "--project-root", str(root),
                    "--source-registry", str(registry),
                    "--work-dir", str(work),
                    "--identity-manifest-output", str(work / "identity.json"),
                    "--phase1-receipt", str(root / "phase1.json"),
                    "--phase1-receipt-file-sha256", "1" * 64,
                    "--phase1-receipt-sha256", "2" * 64,
                    "--phase2-receipt", str(root / "phase2.json"),
                    "--phase2-receipt-file-sha256", "3" * 64,
                    "--phase2-receipt-sha256", "4" * 64,
                    "--source-materialization-result", str(root / "source-result.json"),
                    "--source-materialization-result-file-sha256", "5" * 64,
                    "--source-materialization-result-sha256", "6" * 64,
                    "--through-phase", "phase_b",
                ]
                self.assert_exit_without_side_effects(
                    root,
                    lambda: q4_executor.main(argv),
                    exit_code=q4_executor.EXIT_PERMANENT,
                    message="Q4 source registry schema/status drifted",
                    absent=(root / "fresh", root / ".publication-atomic-staging-v1"),
                )


class FullPublicationEntrypointForeignKindTests(ForeignKindAssertions):
    COMMANDS = ("preflight", "run", "status", "verify", "finalize", "export")

    def test_every_nonplan_command_rejects_foreign_identity_manifest_before_run_root(self) -> None:
        for label, kind in foreign_kinds():
            for command in self.COMMANDS:
                with (
                    self.subTest(kind=label, command=command),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    project_root = Path(tmp).resolve() / "repo"
                    config_path = project_root / "configs" / "experiments.yaml"
                    config_path.parent.mkdir(parents=True)
                    config_path.write_text(
                        yaml.safe_dump(minimal_config(project_root), sort_keys=False),
                        encoding="utf-8",
                    )
                    manifest_path = project_root / "configs" / "identity.json"
                    manifest_path.write_bytes(
                        canonical(
                            {
                                "schema_version": 2,
                                "artifact_kind": kind,
                                "bindings": {},
                            }
                        )
                    )
                    runs = project_root / "runs"
                    run_root = runs / "full_publication" / "foreign"
                    argv = [
                        "--project-root", str(project_root),
                        "--run-root", str(run_root),
                        "--config", str(config_path),
                        "--identity-artifacts", str(manifest_path),
                        command,
                    ]
                    output: list[str] = []
                    before = tree_snapshot(project_root)
                    with (
                        creation_tripwire(project_root) as created,
                        mock.patch.object(
                            full_publication,
                            "_consume_cloud_links",
                            side_effect=AssertionError(
                                "foreign identity consumed cloud links"
                            ),
                        ),
                    ):
                        exit_code = full_publication.main(argv, output_fn=output.append)
                    self.assert_no_creation(created)
                    self.assertEqual(exit_code, int(ExitCode.PERMANENT), output)
                    payload = json.loads(output[-1])
                    self.assertEqual(payload["error_type"], "ContractError")
                    self.assertIn(
                        "identity artifact manifest schema/kind drift",
                        payload["message"],
                    )
                    self.assert_tree_unchanged(project_root, before)
                    self.assertFalse(os.path.lexists(runs))


# Amendment 1 (task 3.3): consumers from consumers.v1.md sections B and C.


def foreign_document(kind: str, **fields: object) -> dict[str, object]:
    """A structurally plausible foreign artifact with explicit nonacceptance."""

    return {
        "schema_version": 1,
        "artifact_kind": kind,
        "status": "accepted",
        "accepted": False,
        **fields,
    }


def write_canonical(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value))


def rewrite_declared_kind(path: Path, kind: str) -> None:
    value = json.loads(path.read_bytes())
    value["artifact_kind"] = kind
    path.write_bytes(canonical(value))


PILOT_ACCEPTANCE_ARM = ("deepstream", "cpu", "h264", "independent_processes")


class PolicyQualificationIndexBuilderForeignKindTests(ForeignKindAssertions):
    def test_foreign_pilot_acceptance_kind_is_rejected_before_index_output(self) -> None:
        import publication_policy_qualification_index_v2 as index_builder
        from tests.test_publication_policy_qualification import (
            SYSTEMS as POLICY_SYSTEMS,
            _PolicyApi,
            _fake_fragment_validator,
            _fragment_bound_fixture,
        )
        from tests.test_publication_policy_qualification_index_v2 import _closure

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                _index_path, source_index = _fragment_bound_fixture(root)
                fragments = {
                    system: root
                    / next(
                        row for row in source_index["bindings"] if row["system"] == system
                    )["fragment_artifact"]["path"]
                    for system in POLICY_SYSTEMS
                }
                pilots = root / "pilots"
                write_canonical(
                    pilots.joinpath(*PILOT_ACCEPTANCE_ARM)
                    / index_builder.PILOT_EVIDENCE_FILENAMES["checkpoint_acceptance"],
                    foreign_document(kind),
                )
                closure_path, closure_loader = _closure(root, pilots, fragments)
                output = root / "fresh" / "qualification-v2"
                self.assert_rejected_without_side_effects(
                    root,
                    lambda: index_builder.build_policy_qualification_index_v2(
                        project_root=root,
                        fragment_paths=fragments,
                        pilot_root=pilots,
                        output_dir=output,
                        policy=_PolicyApi,
                        fragment_validator=_fake_fragment_validator,
                        execution_closure_receipt_path=closure_path,
                        execution_closure_loader=closure_loader,
                    ),
                    error=index_builder.PolicyQualificationIndexV2Error,
                    message="pilot acceptance .*kind",
                    absent=(root / "fresh",),
                )


class ResourceQualificationIndexBuilderForeignKindTests(ForeignKindAssertions):
    def test_foreign_pilot_acceptance_kind_is_rejected_before_index_output(self) -> None:
        import full_resource_qualification_index_v1 as index_builder
        from tests.test_full_resource_qualification_index_v1 import (
            Fixture,
            execution_closure,
            fake_fragment_validator,
        )

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = Fixture(root)
                write_canonical(
                    fixture.pilot_root.joinpath(*PILOT_ACCEPTANCE_ARM)
                    / index_builder.PILOT_EVIDENCE_FILENAMES["checkpoint_acceptance"],
                    foreign_document(kind),
                )
                closure_path, closure_loader = execution_closure(
                    root, fixture.pilot_root, fixture.fragments
                )
                output = root / "fresh" / "full-resource-qualification-index.json"
                self.assert_rejected_without_side_effects(
                    root,
                    lambda: index_builder.build_full_resource_qualification_index_v1(
                        project_root=root,
                        fragment_paths=fixture.fragments,
                        pilot_root=fixture.pilot_root,
                        output_path=output,
                        fragment_validator=fake_fragment_validator,
                        execution_closure_receipt_path=closure_path,
                        execution_closure_loader=closure_loader,
                    ),
                    error=index_builder.FullResourceQualificationIndexV1Error,
                    message="pilot acceptance .*kind",
                    absent=(root / "fresh",),
                )


@unittest.skipUnless(LINUX, "the Q4 authority fixture binds AF_UNIX sockets")
class Q4AuthoritySourceRequestForeignKindTests(ForeignKindAssertions):
    def test_foreign_accepted_policy_receipt_is_rejected_before_output(self) -> None:
        import publication_q4_authority_source_request_v1 as source_request
        from tests.test_publication_q4_authority_source_request_v1 import (
            Fixture,
            patched_production_seams,
            production_inputs_for,
        )

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = Fixture(root)
                try:
                    (root / "transactions").mkdir(exist_ok=True)
                    production_inputs, seams = production_inputs_for(fixture)
                    rewrite_declared_kind(
                        root
                        / production_inputs.accepted_source_paths[
                            "policy_qualification_receipt_path"
                        ],
                        kind,
                    )
                    with patched_production_seams(seams):
                        self.assert_rejected_without_side_effects(
                            root,
                            lambda: source_request.materialize_publication_q4_authority_source_request_v1(
                                project_root=root,
                                output_dir="transactions/fresh/request",
                                production_inputs=production_inputs,
                            ),
                            error=source_request.PublicationQ4AuthoritySourceRequestV1Error,
                            message="policy_qualification_receipt_path.*kind",
                            absent=(root / "transactions" / "fresh",),
                        )
                finally:
                    fixture.close()


@unittest.skipUnless(LINUX, "the Q4 authority fixture binds AF_UNIX sockets")
class Q4AuthoritySourceMaterialForeignKindTests(ForeignKindAssertions):
    def test_foreign_nested_accepted_source_is_rejected_before_output(self) -> None:
        import publication_q4_authority_source_material_v1 as source_material
        from tests.test_publication_q4_authority_source_material_v1 import (
            Fixture,
            PublicationQ4AuthoritySourceMaterialV1Tests as MaterialTests,
        )

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = Fixture(root)
                try:
                    rewrite_declared_kind(
                        root / str(fixture.policy_receipt["path"]), kind
                    )
                    # The helper only builds the canonical request; it never uses self.
                    request_path, request = MaterialTests.request(
                        None, root, fixture, "F"  # type: ignore[arg-type]
                    )
                    self.assert_rejected_without_side_effects(
                        root,
                        lambda: MaterialTests.materialize(
                            root, request_path, request, "F"
                        ),
                        error=source_material.PublicationQ4AuthoritySourceMaterialV1Error,
                        message="policy_qualification_receipt_path.*kind",
                        absent=(root / "transactions" / "F",),
                    )
                finally:
                    fixture.close()


class FullPublicationIdentityManifestV2ForeignKindTests(ForeignKindAssertions):
    def test_foreign_policy_receipt_is_rejected_before_private_candidate(self) -> None:
        import full_publication_identity_manifest_v2 as identity_manifest
        from tests.test_full_publication_identity_manifest_v2 import (
            Fixture,
            inputs,
            loader,
        )

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                fixture = Fixture(root)
                fixture.manifest_path.unlink()
                values = inputs(fixture)
                rewrite_declared_kind(
                    Path(values["policy_qualification"]["receipt"]),  # type: ignore[index]
                    kind,
                )
                self.assert_rejected_without_side_effects(
                    root,
                    lambda: identity_manifest.build_full_publication_identity_manifest_v2(
                        project_root=root,
                        output_path=fixture.manifest_path,
                        identity_loader=loader(fixture),
                        **values,
                    ),
                    error=identity_manifest.FullPublicationIdentityManifestV2Error,
                    message="policy qualification receipt .*kind",
                    absent=(fixture.manifest_path,),
                )


class FullPublicationSupervisorForeignKindTests(ForeignKindAssertions):
    def test_cli_rejects_foreign_identity_manifest_before_state_or_lock(self) -> None:
        import full_publication_supervisor as supervisor

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                manifest = root / "configs" / "identity.json"
                write_canonical(
                    manifest,
                    {"schema_version": 2, "artifact_kind": kind, "bindings": {}},
                )
                state = root / "fresh" / "full_publication_supervisor_state.v1.json"
                argv = [
                    "--state-path", str(state),
                    "--",
                    "--project-root", str(root),
                    "--identity-artifacts", str(manifest),
                    "--expected-matrix-sha256",
                    supervisor.FROZEN_FULL_PUBLICATION_MATRIX_SHA256,
                    "--expected-policy-contract-sha256",
                    supervisor.FROZEN_PUBLICATION_POLICY_CONTRACT_SHA256,
                ]
                stdout = io.StringIO()
                before = tree_snapshot(root)
                with (
                    creation_tripwire(root) as created,
                    mock.patch("sys.stdout", stdout),
                ):
                    exit_code = supervisor.main(argv)
                payload = json.loads(stdout.getvalue())
                self.assertEqual(exit_code, supervisor.EXIT_PERMANENT, payload)
                self.assertEqual(
                    payload["artifact_kind"], "vast_full_publication_supervisor_error"
                )
                self.assertRegex(payload["message"], "identity artifact manifest .*kind")
                self.assert_tree_unchanged(root, before)
                self.assert_no_creation(created)
                self.assertFalse(os.path.lexists(root / "fresh"))


class FullPublicationWslServiceForeignKindTests(ForeignKindAssertions):
    def test_materialize_rejects_foreign_identity_manifest_before_bundle(self) -> None:
        import full_publication_wsl_user_service_v1 as service
        from tests.test_full_publication_wsl_user_service_v1 import Fixture

        for label, kind in foreign_kinds():
            with self.subTest(kind=label), tempfile.TemporaryDirectory() as tmp:
                fixture = Fixture(Path(tmp))
                write_canonical(
                    fixture.files["identity_artifacts"],
                    {"schema_version": 2, "artifact_kind": kind, "bindings": {}},
                )
                with mock.patch.object(service.subprocess, "run") as run_process:
                    self.assert_rejected_without_side_effects(
                        fixture.root,
                        fixture.materialize,
                        error=service.ServiceContractError,
                        message="identity artifact manifest .*kind",
                        absent=(fixture.output_dir,),
                    )
                run_process.assert_not_called()


class Q4TwoPhaseExecutorPhaseReceiptForeignKindTests(ForeignKindAssertions):
    SLOTS = (
        ("phase1", "--phase1-receipt", q4_executor.PHASE1_PLAN_RECEIPT_KIND),
        ("phase2", "--phase2-receipt", q4_executor.PHASE2_PLAN_RECEIPT_KIND),
        (
            "source-result",
            "--source-materialization-result",
            q4_executor.SOURCE_MATERIALIZATION_RESULT_KIND,
        ),
    )

    def test_cli_rejects_foreign_phase_receipts_before_work_dir_or_lock(self) -> None:
        for slot, foreign_option, _expected in self.SLOTS:
            for label, kind in foreign_kinds():
                with (
                    self.subTest(slot=slot, kind=label),
                    tempfile.TemporaryDirectory() as tmp,
                ):
                    root = Path(tmp).resolve()
                    registry = q4_source_registry(root)
                    paths: dict[str, Path] = {}
                    for name, option, expected in self.SLOTS:
                        path = root / "receipts" / f"{name}.json"
                        write_canonical(
                            path,
                            foreign_document(
                                kind if option == foreign_option else expected
                            ),
                        )
                        paths[option] = path
                    work = root / "fresh" / "q4-work"
                    argv = [
                        "--project-root", str(root),
                        "--source-registry", str(registry),
                        "--work-dir", str(work),
                        "--identity-manifest-output", str(work / "identity.json"),
                        "--phase1-receipt", str(paths["--phase1-receipt"]),
                        "--phase1-receipt-file-sha256", file_sha(paths["--phase1-receipt"]),
                        "--phase1-receipt-sha256", "2" * 64,
                        "--phase2-receipt", str(paths["--phase2-receipt"]),
                        "--phase2-receipt-file-sha256", file_sha(paths["--phase2-receipt"]),
                        "--phase2-receipt-sha256", "4" * 64,
                        "--source-materialization-result",
                        str(paths["--source-materialization-result"]),
                        "--source-materialization-result-file-sha256",
                        file_sha(paths["--source-materialization-result"]),
                        "--source-materialization-result-sha256", "6" * 64,
                        "--through-phase", "phase_b",
                    ]
                    self.assert_exit_without_side_effects(
                        root,
                        lambda: q4_executor.main(argv),
                        exit_code=q4_executor.EXIT_PERMANENT,
                        message="production receipt .*kind",
                        absent=(root / "fresh", root / ".publication-atomic-staging-v1"),
                    )


if __name__ == "__main__":
    unittest.main()
