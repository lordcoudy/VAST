from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
import threading
from unittest.mock import patch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from full_publication_results import export_finalized_results  # noqa: E402
import full_publication_results as result_module  # noqa: E402
import publication_physical_io_v1 as physical_io  # noqa: E402


MATRIX_SHA = "a" * 64
RUN_SHA = "b" * 64
RESULT_NAMES = (
    "full_pairs.jsonl",
    "full_arms.jsonl",
    "full_arms.csv",
    "result_bundle_manifest.json",
)


class SyntheticResultCrash(BaseException):
    pass


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode() + b"\n"


class FakeRunner:
    def __init__(self, run_root: Path, snapshot: dict) -> None:
        self.run_root = run_root
        self.snapshot = snapshot

    def finalized_snapshot(self) -> dict:
        return self.snapshot


def fixture(root: Path) -> tuple[FakeRunner, Path]:
    pair = {
        "pair_id": "pair-0001",
        "arms": [
            {
                "arm_id": "baseline-arm",
                "scenario": "checkpoint_independent_processes_baseline",
                "system": "gstreamer_custom",
                "codec": "h264",
                "dataset": "kpp_real_h264",
                "policy": "cpu_only",
                "deadline_ms": 100.0,
                "repeat": 1,
            },
            {
                "arm_id": "shared-arm",
                "scenario": "checkpoint_video_dag_shared",
                "system": "gstreamer_custom",
                "codec": "h264",
                "dataset": "kpp_real_h264",
                "policy": "cpu_only",
                "deadline_ms": 100.0,
                "repeat": 1,
            },
        ],
    }
    accepted_arms = []
    for index, arm in enumerate(pair["arms"], start=1):
        accepted_arms.append(
            {
                "arm_id": arm["arm_id"],
                "scenario": arm["scenario"],
                "result": {
                    "status": "completed",
                    "throughput_fps": float(index * 10),
                    "latency_p95_ms": float(index * 20),
                },
                "arm_acceptance_summary": {
                    "full_resource_evidence_accepted": True
                },
                "full_resource_summary": {
                    "resource_contract_version": 2,
                    "nvdec_busy_equivalent_ns": index,
                },
                "qualification_authorities": {
                    "identity_artifact_binding_sha256": "c" * 64,
                    "resource_capability_grant_sha256": "d" * 64,
                    "backend_runtime_grant_sha256": "e" * 64,
                    "model_parity_grant_sha256": "f" * 64,
                    "model_parity_acceptance_binding_sha256": "0" * 64,
                },
            }
        )
    acceptance = {
        "schema_version": 2,
        "artifact_kind": "vast_full_publication_pair_acceptance",
        "status": "accepted",
        "matrix_sha256": MATRIX_SHA,
        "run_id": RUN_SHA,
        "pair_sequence": 0,
        "pair_id": pair["pair_id"],
        "arm_ids": ["baseline-arm", "shared-arm"],
        "qualification_authorities": copy.deepcopy(
            accepted_arms[0]["qualification_authorities"]
        ),
        "pair_gates": {
            "common_identity_and_qualification_authorities": True,
        },
        "arms": accepted_arms,
    }
    path = root / "accepted_pairs" / "0000_pair-0001.attempt-0001.acceptance.json"
    path.parent.mkdir(parents=True)
    payload = canonical(acceptance)
    path.write_bytes(payload)
    decision = {
        "acceptance_manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "compact_acceptance_relative_path": path.relative_to(root).as_posix(),
    }
    snapshot = {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_finalized_snapshot",
        "matrix_identity": {"schema_version": 2, "sha256": MATRIX_SHA},
        "run_identity": {"schema_version": 1, "sha256": RUN_SHA},
        "matrix": {
            "expected_pairs": 1,
            "expected_arms": 2,
            "pairs": [pair],
        },
        "verified_pairs": [
            {
                "sequence": 0,
                "pair_id": pair["pair_id"],
                "acceptance": decision,
            }
        ],
        "finalization": {"verified": True, "verified_pairs": 1},
    }
    return FakeRunner(root, snapshot), path


class FullPublicationResultsTests(unittest.TestCase):
    def test_exports_deterministic_compact_article_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, _ = fixture(root)
            bundle = export_finalized_results(runner)
            self.assertEqual(bundle["verified_pairs"], 1)
            self.assertEqual(bundle["verified_arms"], 2)
            with (root / "results" / "full_arms.csv").open(
                newline="", encoding="utf-8"
            ) as source:
                rows = list(csv.DictReader(source))
            self.assertEqual(len(rows), 2)
            self.assertEqual(
                {row["result_throughput_fps"] for row in rows},
                {"10.0", "20.0"},
            )
            identities = {
                name: (
                    (root / "results" / name).stat().st_dev,
                    (root / "results" / name).stat().st_ino,
                )
                for name in RESULT_NAMES
            }
            self.assertEqual(export_finalized_results(runner), bundle)
            self.assertEqual(
                {
                    name: (
                        (root / "results" / name).stat().st_dev,
                        (root / "results" / name).stat().st_ino,
                    )
                    for name in RESULT_NAMES
                },
                identities,
            )
            if os.name == "posix":
                self.assertTrue(
                    all(
                        ((root / "results" / name).stat().st_mode & 0o777)
                        == 0o444
                        for name in RESULT_NAMES
                    )
                )
            intents = list(
                (root / ".full-publication-results-intents-v1").glob("*.json")
            )
            self.assertEqual(len(intents), 1)
            intent = json.loads(intents[0].read_text(encoding="utf-8"))
            self.assertEqual(intent["destination_relative_path"], "results")
            self.assertEqual(intent["receipt_last"], "result_bundle_manifest.json")
            self.assertEqual(set(intent["files"]), set(RESULT_NAMES))

    def test_concurrent_exact_exporters_serialize_and_adopt_one_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, _ = fixture(root)
            with ThreadPoolExecutor(max_workers=2) as executor:
                futures = [
                    executor.submit(export_finalized_results, runner)
                    for _index in range(2)
                ]
                bundles = [future.result(timeout=30) for future in futures]
            self.assertEqual(bundles[0], bundles[1])
            self.assertEqual(
                set(path.name for path in (root / "results").iterdir()),
                set(RESULT_NAMES),
            )

    def test_three_physical_crash_windows_resume_exact_path_receipt_last(self) -> None:
        for step in (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        ):
            with self.subTest(step=step), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "run"
                runner, _ = fixture(root)
                observed: list[Path] = []

                def crash(observed_step: str, path: Path) -> None:
                    if (
                        observed_step == step
                        and path.name == "result_bundle_manifest.json"
                        and not observed
                    ):
                        observed.append(path)
                        raise SyntheticResultCrash()

                with self.assertRaises(SyntheticResultCrash):
                    export_finalized_results(
                        runner,
                        after_physical_commit_step=crash,
                    )
                self.assertEqual(len(observed), 1)
                output = root / "results"
                self.assertTrue(output.is_dir())
                if step != "post_publish_pre_parent_fsync":
                    self.assertFalse(
                        (output / "result_bundle_manifest.json").exists()
                    )
                published_before_retry = {
                    name: (
                        (output / name).stat().st_dev,
                        (output / name).stat().st_ino,
                    )
                    for name in RESULT_NAMES
                    if (output / name).exists()
                }
                bundle = export_finalized_results(runner)
                self.assertEqual(
                    set(path.name for path in output.iterdir()),
                    set(RESULT_NAMES),
                )
                self.assertEqual(
                    json.loads(
                        (output / "result_bundle_manifest.json").read_text(
                            encoding="utf-8"
                        )
                    ),
                    bundle,
                )
                for name, identity in published_before_retry.items():
                    current = (output / name).stat()
                    self.assertEqual((current.st_dev, current.st_ino), identity)

    def test_racing_foreign_final_is_preserved_and_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, _ = fixture(root)
            raced: list[tuple[Path, tuple[int, int]]] = []

            def inject_foreign(observed_step: str, path: Path) -> None:
                if (
                    observed_step == "post_fsync_pre_publish"
                    and path.name == "full_arms.jsonl"
                    and not raced
                ):
                    path.write_bytes(b"foreign-racer\n")
                    if os.name == "posix":
                        path.chmod(0o444)
                    info = path.stat()
                    raced.append((path, (info.st_dev, info.st_ino)))

            with self.assertRaisesRegex(
                ContractError,
                "physical namespace rejected|exact staged/final identity drifted",
            ):
                export_finalized_results(
                    runner,
                    after_physical_commit_step=inject_foreign,
                )
            self.assertEqual(len(raced), 1)
            path, identity = raced[0]
            self.assertEqual(path.read_bytes(), b"foreign-racer\n")
            info = path.stat()
            self.assertEqual((info.st_dev, info.st_ino), identity)
            with self.assertRaisesRegex(ContractError, "physical namespace rejected"):
                export_finalized_results(runner)
            self.assertEqual(path.read_bytes(), b"foreign-racer\n")
            info = path.stat()
            self.assertEqual((info.st_dev, info.st_ino), identity)

    def test_preexisting_output_without_intent_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, _ = fixture(root)
            output = root / "results"
            output.mkdir(mode=0o700)
            canary = output / "canary.txt"
            canary.write_bytes(b"foreign\n")
            identity = (canary.stat().st_dev, canary.stat().st_ino)
            with self.assertRaisesRegex(ContractError, "without its exact.*intent"):
                export_finalized_results(runner)
            self.assertEqual(canary.read_bytes(), b"foreign\n")
            self.assertEqual(
                (canary.stat().st_dev, canary.stat().st_ino),
                identity,
            )

    def test_rejects_compact_acceptance_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, path = fixture(root)
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaisesRegex(ContractError, "hash drift"):
                export_finalized_results(runner)

    def test_rejects_legacy_or_split_qualification_authorities(self) -> None:
        for case in ("legacy", "top_level", "gate", "arm"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "run"
                runner, path = fixture(root)
                acceptance = json.loads(path.read_text(encoding="utf-8"))
                if case == "legacy":
                    acceptance["schema_version"] = 1
                elif case == "top_level":
                    acceptance["qualification_authorities"].pop(
                        "model_parity_grant_sha256"
                    )
                elif case == "gate":
                    acceptance["pair_gates"][
                        "common_identity_and_qualification_authorities"
                    ] = False
                else:
                    acceptance["arms"][1]["qualification_authorities"][
                        "model_parity_grant_sha256"
                    ] = "9" * 64
                payload = canonical(acceptance)
                path.write_bytes(payload)
                runner.snapshot["verified_pairs"][0]["acceptance"][
                    "acceptance_manifest_sha256"
                ] = hashlib.sha256(payload).hexdigest()

                with self.assertRaisesRegex(
                    ContractError,
                    "identity drift|qualification authorit",
                ):
                    export_finalized_results(runner)


    def test_posix_run_root_lock_serializes_bootstrap_and_rejects_rebinding(self) -> None:
        if os.name != "posix":
            with tempfile.TemporaryDirectory() as tmp:
                runner, _ = fixture(Path(tmp) / "run")
                self.assertEqual(
                    export_finalized_results(runner), export_finalized_results(runner)
                )
            return

        real_flock = result_module.fcntl.flock
        real_close = os.close
        real_require_epochs = physical_io.PhysicalRootCustodyV1._require_epochs
        fd_count = lambda: len(os.listdir("/proc/self/fd"))
        initial_fds = fd_count()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, _ = fixture(root)
            root_identity = (root.stat().st_dev, root.stat().st_ino)
            parked = threading.Event()
            release = threading.Event()
            second_lock = threading.Event()
            actors: dict[str, int] = {}

            def require_epochs(*args, **kwargs):
                if (
                    threading.get_ident() == actors.get("first")
                    and kwargs.get("label") == "compact result intent root"
                    and not parked.is_set()
                ):
                    parked.set()
                    if not release.wait(10):
                        raise AssertionError("parked original epoch check was not released")
                return real_require_epochs(*args, **kwargs)

            def flock(descriptor, operation):
                if (
                    threading.get_ident() == actors.get("second")
                    and operation == result_module.fcntl.LOCK_EX
                ):
                    info = os.fstat(descriptor)
                    identity = (info.st_dev, info.st_ino)
                    bundle_lock = root / ".full-publication-results-intents-v1" / ".bundle.lock"
                    bundle_identity = None
                    if bundle_lock.exists():
                        named = bundle_lock.lstat()
                        bundle_identity = (named.st_dev, named.st_ino)
                    # Ignore atomic-staging locks: only the old bundle or new root counts.
                    if identity in (root_identity, bundle_identity):
                        second_lock.set()
                return real_flock(descriptor, operation)

            def export(actor):
                actors[actor] = threading.get_ident()
                bundle = export_finalized_results(runner)
                return bundle, {
                    name: (root / "results" / name).read_bytes()
                    for name in RESULT_NAMES
                }

            with patch.object(physical_io.PhysicalRootCustodyV1, "_require_epochs", staticmethod(require_epochs)), patch.object(
                result_module.fcntl, "flock", flock
            ), ThreadPoolExecutor(max_workers=2) as executor:
                first = executor.submit(export, "first")
                try:
                    self.assertTrue(parked.wait(10), "first actual epoch snapshot not observed")
                    second = executor.submit(export, "second")
                    self.assertTrue(second_lock.wait(10), "second actual coordination not observed")
                    release.set()
                    first_bundle, first_bytes = first.result(timeout=15)
                    second_bundle, second_bytes = second.result(timeout=15)
                finally:
                    release.set()
            self.assertEqual(first_bundle, second_bundle)
            self.assertEqual(first_bytes, second_bytes)
            self.assertEqual(set(first_bytes), set(RESULT_NAMES))
            self.assertEqual(
                set(path.name for path in (root / "results").iterdir()), set(RESULT_NAMES)
            )
            self.assertEqual(json.loads(first_bytes[RESULT_NAMES[-1]]), first_bundle)
            intents = list((root / ".full-publication-results-intents-v1").glob("*.json"))
            self.assertEqual(len(intents), 1)
            intent = json.loads(intents[0].read_bytes())
            self.assertEqual(intent["receipt_last"], RESULT_NAMES[-1])
            self.assertEqual(set(intent["files"]), set(RESULT_NAMES))
        self.assertEqual(fd_count(), initial_fds)

        with self.subTest(case="held root rebound"), tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            runner, _ = fixture(root)
            identity = (root.stat().st_dev, root.stat().st_ino)
            acquired: list[int] = []

            def rebind(descriptor, operation):
                info = os.fstat(descriptor)
                if operation == result_module.fcntl.LOCK_EX and (
                    info.st_dev, info.st_ino
                ) == identity:
                    acquired.append(descriptor)
                    root.rename(Path(tmp) / "original-run")
                    root.mkdir()
                    (root / "sentinel").write_bytes(b"foreign-root\n")
                return real_flock(descriptor, operation)

            with patch.object(result_module.fcntl, "flock", rebind):
                with self.assertRaisesRegex(ContractError, "physical namespace rejected|run-root"):
                    export_finalized_results(runner)
            self.assertEqual(len(acquired), 1)
            self.assertEqual((root / "sentinel").read_bytes(), b"foreign-root\n")
            self.assertEqual(set(path.name for path in root.iterdir()), {"sentinel"})
            self.assertEqual(
                set(path.name for path in (Path(tmp) / "original-run").iterdir()),
                {"accepted_pairs"},
            )
            with self.assertRaises(OSError):
                os.fstat(acquired[0])
        self.assertEqual(fd_count(), initial_fds)

        for case in ("acquisition", "cleanup_only", "primary_with_cleanup"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "run"
                runner, _ = fixture(root)
                identity = (root.stat().st_dev, root.stat().st_ino)
                root_fd: list[int] = []
                actions: list[str] = []
                primary = SyntheticResultCrash("original publication failure")

                def fault_flock(descriptor, operation):
                    info = os.fstat(descriptor)
                    is_root = (info.st_dev, info.st_ino) == identity
                    result = real_flock(descriptor, operation)
                    if is_root and operation == result_module.fcntl.LOCK_EX:
                        root_fd.append(descriptor)
                        actions.append("acquire")
                        if case == "acquisition":
                            raise OSError("injected after genuine root acquisition")
                    elif is_root and operation == result_module.fcntl.LOCK_UN:
                        actions.append("unlock")
                        if case != "acquisition":
                            raise OSError("injected after genuine root unlock")
                    return result

                def fault_close(descriptor):
                    result = real_close(descriptor)
                    if root_fd and descriptor == root_fd[0]:
                        actions.append("close")
                        if case != "acquisition":
                            raise OSError("injected after genuine root close")
                    return result

                def fail_publication(step, path):
                    if case == "primary_with_cleanup" and step == "mid_write":
                        raise primary

                with patch.object(result_module.fcntl, "flock", fault_flock), patch.object(
                    result_module.os, "close", fault_close
                ):
                    expected_error = SyntheticResultCrash if case == "primary_with_cleanup" else ContractError
                    with self.assertRaises(expected_error) as refused:
                        export_finalized_results(
                            runner, after_physical_commit_step=fail_publication
                        )
                self.assertEqual(actions, ["acquire", "unlock", "close"])
                self.assertEqual(len(root_fd), 1)
                with self.assertRaises(OSError):
                    os.fstat(root_fd[0])
                if case == "primary_with_cleanup":
                    self.assertIs(refused.exception, primary)
                    notes = getattr(primary, "__notes__", [])
                    self.assertTrue(any("unlock" in note for note in notes))
                    self.assertTrue(any("close" in note for note in notes))
                    self.assertTrue(all(len(note) <= 512 for note in notes))
                else:
                    self.assertIn("run-root lock", str(refused.exception))
            self.assertEqual(fd_count(), initial_fds)


if __name__ == "__main__":
    unittest.main()
