from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from full_publication_runner import (  # noqa: E402
    ArmContext,
    PairContext,
    RunContext,
    TransientRunError,
)
from full_publication_runtime import FullPublicationRuntime  # noqa: E402
from publication_acceptance_evidence import accepted_arm_evidence_files  # noqa: E402
from publication_article_statistics_v1 import (  # noqa: E402
    build_article_statistics_pair_record_v1,
    persist_article_statistics_pair_record_v1,
)


class SyntheticPairAcceptanceCrash(BaseException):
    pass


from tests.test_publication_article_statistics_v1 import _descriptive  # noqa: E402
from tests.test_publication_cloud_transaction import FakeStore  # noqa: E402
from checkpoint_acceptance_metadata_binding import (  # noqa: E402
    bind_checkpoint_acceptance_to_durable_metadata,
)
from tests.test_checkpoint_acceptance_metadata_binding import (  # noqa: E402
    metadata as binding_metadata,
)


MATRIX_SHA = "a" * 64
RUN_SHA = "b" * 64


def pair_context(
    run_root: Path,
    *,
    attempt: int = 1,
    policy: str = "cpu_only",
) -> PairContext:
    pair = {
        "pair_id": "gstreamer_custom--h264--cpu_only--d100--r01",
        "system": "gstreamer_custom",
        "codec": "h264",
        "dataset": "kpp_real_h264",
        "policy": policy,
        "deadline_ms": 100.0,
        "repeat": 1,
        "arms": [
            {
                "arm_id": "gstreamer_custom--h264--cpu_only--d100--r01--a1",
                "arm_position": 1,
                "system": "gstreamer_custom",
                "scenario": "checkpoint_independent_processes_baseline",
                "codec": "h264",
                "dataset": "kpp_real_h264",
                "policy": policy,
                "deadline_ms": 100.0,
                "repeat": 1,
                "streams": 6,
                "seed": 20260323,
                "warmup_s": 30,
                "measurement_s": 180,
            },
            {
                "arm_id": "gstreamer_custom--h264--cpu_only--d100--r01--a2",
                "arm_position": 2,
                "system": "gstreamer_custom",
                "scenario": "checkpoint_video_dag_shared",
                "codec": "h264",
                "dataset": "kpp_real_h264",
                "policy": policy,
                "deadline_ms": 100.0,
                "repeat": 1,
                "streams": 6,
                "seed": 20260323,
                "warmup_s": 30,
                "measurement_s": 180,
            },
        ],
    }
    return PairContext(
        run=RunContext(
            run_root=run_root,
            matrix_identity={"schema_version": 2, "sha256": MATRIX_SHA},
            run_identity={"schema_version": 1, "sha256": RUN_SHA},
            next_sequence=0,
            total_pairs=1,
        ),
        sequence=0,
        pair=pair,
        attempt=attempt,
    )


class PreflightStore(FakeStore):
    def preflight(self) -> dict[str, object]:
        return {
            "status": "ready",
            "origin": "https://seafile.example",
            "remote_file_count": len(self.remote),
            "remote_size_bytes": sum(len(value) for value in self.remote.values()),
        }

    def list_remote_files(self) -> dict[str, dict[str, object]]:
        return {
            name: {"file_name": name, "size": len(value), "is_dir": False}
            for name, value in self.remote.items()
        }


def accepted_arm_runner(
    context: ArmContext,
    arm_root: Path,
    *,
    parity_acceptance_identity_sha256: str | None = None,
) -> dict[str, object]:
    arm_root.mkdir(parents=True, exist_ok=True)
    execution_binding = {
        "schema_version": 1,
        "artifact_kind": "vast_full_publication_arm_execution_binding",
        "run_identity_sha256": str(
            context.pair_context.run.run_identity["sha256"]
        ),
        "sequence": context.sequence,
        "pair_id": str(context.pair_context.pair["pair_id"]),
        "attempt": context.attempt,
        "arm_id": str(context.arm["arm_id"]),
    }
    metadata = binding_metadata(
        execution_binding,
        arm_root,
        parity_acceptance_identity_sha256=(
            parity_acceptance_identity_sha256
        ),
    )
    evidence_hashes = {}
    for name in accepted_arm_evidence_files(
        context.arm["policy"],
        full_resource=True,
    ):
        path = arm_root / name
        if not path.exists():
            path.write_text(f"{name}\n", encoding="utf-8")
        evidence_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    full_resource_hashes = {
        name: evidence_hashes[name]
        for name in (
            "resource_intervals.csv",
            "hardware_resource_samples.csv",
            "fanout_work_counters.csv",
        )
    }
    schedule = "c" * 64
    acceptance = {
        "schema_version": 2,
        "artifact_kind": "checkpoint_publication_runtime_acceptance",
        "status": "accepted_native_checkpoint_arm",
        "run_id": context.arm["arm_id"],
        "system": context.arm["system"],
        "scenario": context.arm["scenario"],
        "codec": context.arm["codec"],
        "policy": context.arm["policy"],
        "deadline_ms": context.arm["deadline_ms"],
        "measurement_schedule_fingerprint_sha256": schedule,
        "summary": {
            "ingress_ledger_complete": True,
            "ingress_cohort_closed": True,
            "branch_terminal_trace_complete": True,
            "checkpoint_frame_aggregation_complete": True,
            "stage_semantic_contract_complete": True,
            "decoder_placement_verified": True,
            "resource_attribution_complete": True,
            "reset_state_verified": True,
            "full_resource_evidence_accepted": True,
            "full_resource_coverage_complete": True,
            "resource_contract_version": 2,
        },
        "evidence_sha256": evidence_hashes,
        "full_resource_evidence_sha256": full_resource_hashes,
        "full_resource_summary": {
            "resource_contract_version": 2,
            "evidence_accepted": True,
            "publication_bundle_bound": True,
            "full_resource_coverage_complete": True,
        },
        "acceptance_finalization": {
            "hardware_collector_stopped": True,
            "validation": "full_resource_evidence_v2_passed",
        },
    }
    metadata["run_seed"] = 123456
    metadata["result"] = {
        "status": "completed",
        "system": context.arm["system"],
        "scenario": context.arm["scenario"],
        "policy": context.arm["policy"],
        "dataset": context.arm["dataset"],
        "deadline_ms": context.arm["deadline_ms"],
        "repeat": context.arm["repeat"],
        "streams": context.arm["streams"],
        "seed": context.arm["seed"],
        "run_seed": 123456,
    }
    metadata_path = arm_root / "run_metadata.json"
    metadata_path.write_text(
        json.dumps(
            metadata,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    acceptance = bind_checkpoint_acceptance_to_durable_metadata(
        acceptance,
        run_metadata_path=metadata_path,
        expected_execution_binding=execution_binding,
    )
    (arm_root / "checkpoint_publication_acceptance.json").write_text(
        json.dumps(acceptance, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return {"status": "completed", "arm_id": context.arm["arm_id"]}


def accepted_article_statistics_sealer(**kwargs: object) -> dict[str, object]:
    run_root = Path(kwargs["run_root"])
    pair_dir = Path(kwargs["pair_dir"])
    pair = kwargs["pair"]
    arm_records = kwargs["arm_records"]
    assert isinstance(pair, dict)
    assert isinstance(arm_records, list)
    materials = []
    for arm_index, (expected, arm_record) in enumerate(
        zip(pair["arms"], arm_records, strict=True)
    ):
        arm_root = (
            run_root / str(arm_record["runtime_acceptance_relative_path"])
        ).parent
        descriptors = []
        names = {
            *arm_record["evidence_sha256"],
            "checkpoint_publication_acceptance.json",
            "run_metadata.json",
        }
        for name in sorted(names):
            path = arm_root / name
            payload = path.read_bytes()
            descriptors.append(
                {
                    "relative_path": path.relative_to(pair_dir).as_posix(),
                    "size_bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        materials.append(
            {
                "arm_index": arm_index,
                "arm_id": expected["arm_id"],
                "coordinate": {
                    "arm_position": expected["arm_position"],
                    "system": expected["system"],
                    "scenario": expected["scenario"],
                    "codec": expected["codec"],
                    "dataset": expected["dataset"],
                    "policy": expected["policy"],
                    "deadline_ms": expected["deadline_ms"],
                    "repeat": expected["repeat"],
                    "streams": expected["streams"],
                    "seed": expected["seed"],
                    "warmup_s": expected["warmup_s"],
                    "measurement_s": expected["measurement_s"],
                    "run_seed": arm_record["run_seed"],
                    "deployment_mode": "test",
                    "host_topology": "test",
                    "run_mode": "benchmark",
                    "telemetry_source": "native",
                },
                "evidence_files": descriptors,
                "descriptive_statistics": _descriptive(),
                "primary_architecture_run_metric": None,
            }
        )
    record = build_article_statistics_pair_record_v1(
        pair_identity={
            "matrix_sha256": kwargs["matrix_sha256"],
            "run_id": kwargs["run_id"],
            "pair_sequence": kwargs["pair_sequence"],
            "pair_id": kwargs["pair_id"],
            "pair_sha256": kwargs["pair_sha256"],
            "attempt": kwargs["attempt"],
        },
        arms=materials,
        primary_architecture_pair_metric=None,
    )
    return persist_article_statistics_pair_record_v1(
        record,
        run_root=run_root,
        pair_dir=pair_dir,
    )


class FullPublicationRuntimeTests(unittest.TestCase):
    def make_runtime(
        self,
        root: Path,
        *,
        readiness: dict[str, object] | None = None,
        arm_runner=accepted_arm_runner,
        article_statistics_sealer=accepted_article_statistics_sealer,
        pair_acceptance_physical_fault=None,
    ) -> FullPublicationRuntime:
        return FullPublicationRuntime(
            run_root=root,
            config={"benchmark": {}},
            cloud_store=PreflightStore(),
            arm_runner=arm_runner,
            readiness_validator=lambda _config: readiness
            or {"passed": True, "blockers": []},
            minimum_free_bytes=1,
            capacity_confirmed_gib=500,
            article_statistics_sealer=article_statistics_sealer,
            pair_acceptance_physical_fault=pair_acceptance_physical_fault,
        )

    def test_pair_flows_from_two_arms_to_cloud_receipt_and_remote_verify(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root)
            runtime = self.make_runtime(root)
            callbacks = runtime.callbacks()

            preflight = callbacks.preflight(context.run)
            results = tuple(
                callbacks.execute_arm(
                    ArmContext(
                        pair_context=context,
                        arm_index=index,
                        arm=arm,
                    )
                )
                for index, arm in enumerate(context.pair["arms"])
            )
            acceptance = callbacks.accept_pair(context, results)
            receipt = callbacks.cloud_transaction(context, acceptance)
            verified = callbacks.verify_cloud(context, receipt)
            resumed_receipt = callbacks.cloud_transaction(context, acceptance)

            self.assertTrue(preflight.accepted)
            self.assertTrue(acceptance.accepted)
            self.assertRegex(
                str(acceptance.details["acceptance_manifest_sha256"]),
                r"^[0-9a-f]{64}$",
            )
            self.assertTrue(receipt.verified)
            self.assertEqual(receipt.details["state"], "local_pruned")
            self.assertEqual(verified.details, receipt.details)
            self.assertEqual(resumed_receipt.details, receipt.details)
            self.assertFalse(runtime.attempt_root(context).exists())
            compact_path = (
                root
                / str(acceptance.details["compact_acceptance_relative_path"])
            )
            self.assertTrue(compact_path.is_file())
            compact = json.loads(compact_path.read_text(encoding="utf-8"))
            self.assertEqual(len(compact["arms"]), 2)
            self.assertEqual(
                {arm["result"]["status"] for arm in compact["arms"]},
                {"completed"},
            )

    def test_pair_acceptance_rejects_article_statistics_bound_to_other_matrix(self) -> None:
        def wrong_matrix_sealer(**kwargs: object) -> dict[str, object]:
            changed = dict(kwargs)
            changed["matrix_sha256"] = "f" * 64
            return accepted_article_statistics_sealer(**changed)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root)
            callbacks = self.make_runtime(
                root, article_statistics_sealer=wrong_matrix_sealer
            ).callbacks()
            results = tuple(
                callbacks.execute_arm(
                    ArmContext(
                        pair_context=context,
                        arm_index=index,
                        arm=arm,
                    )
                )
                for index, arm in enumerate(context.pair["arms"])
            )
            decision = callbacks.accept_pair(context, results)

            self.assertFalse(decision.accepted)
            self.assertFalse(decision.retryable)
            self.assertIn("pair identity differs", decision.reason)

    def test_compact_acceptance_redirect_is_rejected_before_acceptance_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root)
            runtime = self.make_runtime(root)
            callbacks = runtime.callbacks()
            results = tuple(
                callbacks.execute_arm(
                    ArmContext(
                        pair_context=context,
                        arm_index=index,
                        arm=arm,
                    )
                )
                for index, arm in enumerate(context.pair["arms"])
            )
            outside = Path(tmp) / "outside"
            outside.mkdir()
            redirect = root / "accepted_pairs"
            try:
                redirect.symlink_to(outside, target_is_directory=True)
            except (NotImplementedError, OSError) as error:
                self.skipTest(f"directory symlinks are unavailable: {error}")

            decision = callbacks.accept_pair(context, results)

            self.assertFalse(decision.accepted)
            self.assertFalse(decision.retryable)
            self.assertIn("physical namespace rejected", decision.reason)
            self.assertFalse(
                (runtime.attempt_root(context) / "acceptance.json").exists()
            )
            self.assertEqual(list(outside.iterdir()), [])

    def test_preexisting_acceptance_leaf_is_never_replaced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root)
            runtime = self.make_runtime(root)
            callbacks = runtime.callbacks()
            results = tuple(
                callbacks.execute_arm(
                    ArmContext(
                        pair_context=context,
                        arm_index=index,
                        arm=arm,
                    )
                )
                for index, arm in enumerate(context.pair["arms"])
            )
            acceptance_path = runtime.attempt_root(context) / "acceptance.json"
            attacker_payload = b"attacker-owned\n"
            acceptance_path.write_bytes(attacker_payload)

            decision = callbacks.accept_pair(context, results)

            self.assertFalse(decision.accepted)
            self.assertFalse(decision.retryable)
            self.assertIn("immutable pair acceptance collision", decision.reason)
            self.assertEqual(acceptance_path.read_bytes(), attacker_payload)
            self.assertEqual(list((root / "accepted_pairs").iterdir()), [])

    def test_pair_acceptance_recovers_every_atomic_window_for_both_copies(
        self,
    ) -> None:
        steps = (
            "mid_write",
            "post_fsync_pre_publish",
            "post_publish_pre_parent_fsync",
        )
        for copy_name in ("attempt", "compact"):
            for step in steps:
                with self.subTest(copy=copy_name, step=step), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp) / "run"
                    context = pair_context(root)
                    faulted: list[Path] = []

                    def crash(observed_step: str, path: Path) -> None:
                        is_attempt = path.name == "acceptance.json"
                        selected = is_attempt if copy_name == "attempt" else not is_attempt
                        if selected and observed_step == step and not faulted:
                            faulted.append(path)
                            raise SyntheticPairAcceptanceCrash()

                    runtime = self.make_runtime(
                        root, pair_acceptance_physical_fault=crash
                    )
                    callbacks = runtime.callbacks()
                    results = tuple(
                        callbacks.execute_arm(
                            ArmContext(
                                pair_context=context,
                                arm_index=index,
                                arm=arm,
                            )
                        )
                        for index, arm in enumerate(context.pair["arms"])
                    )
                    with self.assertRaises(SyntheticPairAcceptanceCrash):
                        callbacks.accept_pair(context, results)
                    self.assertEqual(len(faulted), 1)
                    faulted_path = faulted[0]
                    published_identity = (
                        (faulted_path.stat().st_dev, faulted_path.stat().st_ino)
                        if faulted_path.exists()
                        else None
                    )

                    resumed = self.make_runtime(root).callbacks().accept_pair(
                        context, results
                    )
                    self.assertTrue(resumed.accepted, resumed.reason)
                    attempt_path = runtime.attempt_root(context) / "acceptance.json"
                    compact_path = root / str(
                        resumed.details["compact_acceptance_relative_path"]
                    )
                    self.assertEqual(
                        attempt_path.read_bytes(), compact_path.read_bytes()
                    )
                    self.assertEqual(attempt_path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(compact_path.stat().st_mode & 0o777, 0o600)
                    self.assertEqual(attempt_path.stat().st_nlink, 1)
                    self.assertEqual(compact_path.stat().st_nlink, 1)
                    if published_identity is not None:
                        self.assertEqual(
                            (
                                faulted_path.stat().st_dev,
                                faulted_path.stat().st_ino,
                            ),
                            published_identity,
                        )

    def test_interrupted_arm_is_offered_same_attempt_root_for_safe_resume(self) -> None:
        calls: list[tuple[int, Path, bool]] = []

        def resumable_runner(
            context: ArmContext, arm_root: Path
        ) -> dict[str, object]:
            calls.append((context.attempt, arm_root, arm_root.exists()))
            if len(calls) == 1:
                arm_root.mkdir(parents=True)
                (arm_root / "parent-owned-resume-marker").write_text(
                    "durable\n", encoding="ascii"
                )
                raise TransientRunError("interrupted before transaction commit")
            self.assertEqual(
                (arm_root / "parent-owned-resume-marker").read_text(
                    encoding="ascii"
                ),
                "durable\n",
            )
            return accepted_arm_runner(context, arm_root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root, attempt=7)
            callbacks = self.make_runtime(
                root, arm_runner=resumable_runner
            ).callbacks()
            arm_context = ArmContext(context, 0, context.pair["arms"][0])
            with self.assertRaisesRegex(TransientRunError, "interrupted"):
                callbacks.execute_arm(arm_context)
            result = callbacks.execute_arm(arm_context)

        self.assertEqual(result["status"], "completed")
        self.assertEqual([value[0] for value in calls], [7, 7])
        self.assertEqual(calls[0][1], calls[1][1])
        self.assertEqual([value[2] for value in calls], [False, True])

    def test_pair_acceptance_rejects_schedule_or_evidence_drift(self) -> None:
        def drifted_runner(context: ArmContext, arm_root: Path) -> dict[str, object]:
            result = accepted_arm_runner(context, arm_root)
            if context.arm_index == 1:
                path = arm_root / "checkpoint_publication_acceptance.json"
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["measurement_schedule_fingerprint_sha256"] = "d" * 64
                path.write_text(
                    json.dumps(payload, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            return result

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root)
            runtime = self.make_runtime(root, arm_runner=drifted_runner)
            callbacks = runtime.callbacks()
            results = tuple(
                callbacks.execute_arm(
                    ArmContext(context, index, arm)
                )
                for index, arm in enumerate(context.pair["arms"])
            )

            decision = callbacks.accept_pair(context, results)

            self.assertFalse(decision.accepted)
            self.assertIn("schedule", decision.reason)
            self.assertTrue(runtime.attempt_root(context).is_dir())

    def test_pair_acceptance_requires_exact_policy_aware_evidence_set(self) -> None:
        mutations = (
            ("cpu_only", lambda evidence: evidence.pop("publication_policy_decisions.jsonl")),
            ("cpu_only", lambda evidence: evidence.__setitem__("policy_feedback.csv", "a" * 64)),
            ("adaptive_weights", lambda evidence: evidence.pop("publication_policy_feedback.jsonl")),
        )
        for policy, mutate in mutations:
            def runner(context: ArmContext, arm_root: Path) -> dict[str, object]:
                result = accepted_arm_runner(context, arm_root)
                if context.arm_index == 1:
                    path = arm_root / "checkpoint_publication_acceptance.json"
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    mutate(payload["evidence_sha256"])
                    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
                return result

            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "run"
                context = pair_context(root, policy=policy)
                callbacks = self.make_runtime(root, arm_runner=runner).callbacks()
                results = tuple(
                    callbacks.execute_arm(ArmContext(context, index, arm))
                    for index, arm in enumerate(context.pair["arms"])
                )
                decision = callbacks.accept_pair(context, results)
                self.assertFalse(decision.accepted)
                self.assertIn("evidence hash set", decision.reason)

    def test_pair_acceptance_accepts_exact_static_and_adaptive_sets(self) -> None:
        for policy in ("cpu_only", "adaptive_weights"):
            with self.subTest(policy=policy), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "run"
                context = pair_context(root, policy=policy)
                callbacks = self.make_runtime(root).callbacks()
                results = tuple(
                    callbacks.execute_arm(ArmContext(context, index, arm))
                    for index, arm in enumerate(context.pair["arms"])
                )
                self.assertTrue(callbacks.accept_pair(context, results).accepted)

    def test_pair_acceptance_rejects_individually_valid_split_grant_families(
        self,
    ) -> None:
        def split_family_runner(
            context: ArmContext, arm_root: Path
        ) -> dict[str, object]:
            return accepted_arm_runner(
                context,
                arm_root,
                parity_acceptance_identity_sha256=(
                    "9" * 64 if context.arm_index == 1 else None
                ),
            )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root)
            callbacks = self.make_runtime(
                root, arm_runner=split_family_runner
            ).callbacks()
            results = tuple(
                callbacks.execute_arm(ArmContext(context, index, arm))
                for index, arm in enumerate(context.pair["arms"])
            )

            decision = callbacks.accept_pair(context, results)

            self.assertFalse(decision.accepted)
            self.assertIn("qualification authorities", decision.reason)

    def test_preflight_fails_closed_on_readiness_capacity_or_owned_namespace_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            context = pair_context(root)
            blocked = self.make_runtime(
                root,
                readiness={"passed": False, "blockers": ["native_binding_missing"]},
            )
            decision = blocked.preflight(context.run)
            self.assertFalse(decision.accepted)
            self.assertFalse(decision.retryable)
            self.assertIn("native_binding_missing", decision.reason)

            low_capacity = FullPublicationRuntime(
                run_root=root,
                config={"benchmark": {}},
                cloud_store=PreflightStore(),
                arm_runner=accepted_arm_runner,
                readiness_validator=lambda _config: {"passed": True, "blockers": []},
                minimum_free_bytes=1,
                capacity_confirmed_gib=499,
            )
            self.assertFalse(low_capacity.preflight(context.run).accepted)

            foreign_store = PreflightStore()
            foreign_store.remote["foreign.bin"] = b"data"
            foreign = FullPublicationRuntime(
                run_root=root,
                config={"benchmark": {}},
                cloud_store=foreign_store,
                arm_runner=accepted_arm_runner,
                readiness_validator=lambda _config: {"passed": True, "blockers": []},
                minimum_free_bytes=1,
                capacity_confirmed_gib=500,
            )
            self.assertTrue(foreign.preflight(context.run).accepted)

            run_key = hashlib.sha256(RUN_SHA.encode("utf-8")).hexdigest()[:16]
            owned_prefix = f"{MATRIX_SHA}_{run_key}_"
            foreign_store.remote[f"{owned_prefix}malformed.bin"] = b"collision"
            corrupted = foreign.preflight(context.run)
            self.assertFalse(corrupted.accepted)
            self.assertFalse(corrupted.retryable)
            self.assertIn("namespace", corrupted.reason)

    def test_resume_preflight_requires_exact_remote_prefix_and_allows_durable_inflight(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            root.mkdir()
            run_key = hashlib.sha256(RUN_SHA.encode("utf-8")).hexdigest()[:16]
            prefix = f"{MATRIX_SHA}_{run_key}_"

            def remote_name(sequence: int, kind: str, digest: str) -> str:
                suffix = ".tar.zst" if kind == "archive" else ".receipt.json"
                return f"{prefix}{sequence:04d}_{'c' * 16}_{digest}{suffix}"

            store = PreflightStore()
            store.remote[remote_name(0, "archive", "d" * 64)] = b"archive"
            store.remote[remote_name(0, "receipt", "e" * 64)] = b"receipt"
            checkpoint = {
                "verified_prefix_length": 1,
                "inflight": {
                    "phase": "accepted",
                    "sequence": 1,
                },
            }
            (root / "checkpoint.json").write_text(
                json.dumps(checkpoint), encoding="utf-8"
            )
            context = RunContext(
                run_root=root,
                matrix_identity={"schema_version": 2, "sha256": MATRIX_SHA},
                run_identity={"schema_version": 1, "sha256": RUN_SHA},
                next_sequence=1,
                total_pairs=2,
            )
            runtime = FullPublicationRuntime(
                run_root=root,
                config={"benchmark": {}},
                cloud_store=store,
                arm_runner=accepted_arm_runner,
                readiness_validator=lambda _config: {"passed": True, "blockers": []},
                minimum_free_bytes=1,
                capacity_confirmed_gib=500,
            )
            self.assertTrue(runtime.preflight(context).accepted)

            receipt_name = remote_name(0, "receipt", "e" * 64)
            receipt_payload = store.remote.pop(receipt_name)
            mismatched_receipt = (
                f"{prefix}0000_{'b' * 16}_{'e' * 64}.receipt.json"
            )
            store.remote[mismatched_receipt] = receipt_payload
            pair_key_drift = runtime.preflight(context)
            self.assertFalse(pair_key_drift.accepted)
            self.assertFalse(pair_key_drift.retryable)
            self.assertIn("pair key", pair_key_drift.reason)
            del store.remote[mismatched_receipt]
            store.remote[receipt_name] = receipt_payload

            duplicate_archive = remote_name(0, "archive", "a" * 64)
            store.remote[duplicate_archive] = b"duplicate"
            collision = runtime.preflight(context)
            self.assertFalse(collision.accepted)
            self.assertFalse(collision.retryable)
            self.assertIn("duplicate", collision.reason)
            del store.remote[duplicate_archive]

            inflight_archive = remote_name(1, "archive", "f" * 64)
            store.remote[inflight_archive] = b"inflight"
            self.assertTrue(runtime.preflight(context).accepted)

            del store.remote[inflight_archive]
            inflight_receipt = remote_name(1, "receipt", "9" * 64)
            store.remote[inflight_receipt] = b"invalid-order"
            invalid_partial = runtime.preflight(context)
            self.assertFalse(invalid_partial.accepted)
            self.assertFalse(invalid_partial.retryable)
            self.assertIn("inflight", invalid_partial.reason)
            del store.remote[inflight_receipt]
            store.remote[inflight_archive] = b"inflight"

            del store.remote[remote_name(0, "receipt", "e" * 64)]
            missing = runtime.preflight(context)
            self.assertFalse(missing.accepted)
            self.assertFalse(missing.retryable)
            self.assertIn("continuity", missing.reason)

    def test_resume_preflight_rejects_empty_rotated_share_after_committed_pair(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "run"
            root.mkdir()
            (root / "checkpoint.json").write_text(
                json.dumps({"verified_prefix_length": 1, "inflight": None}),
                encoding="utf-8",
            )
            context = RunContext(
                run_root=root,
                matrix_identity={"schema_version": 2, "sha256": MATRIX_SHA},
                run_identity={"schema_version": 1, "sha256": RUN_SHA},
                next_sequence=1,
                total_pairs=2,
            )
            runtime = FullPublicationRuntime(
                run_root=root,
                config={"benchmark": {}},
                cloud_store=PreflightStore(),
                arm_runner=accepted_arm_runner,
                readiness_validator=lambda _config: {"passed": True, "blockers": []},
                minimum_free_bytes=1,
                capacity_confirmed_gib=500,
            )
            decision = runtime.preflight(context)
            self.assertFalse(decision.accepted)
            self.assertFalse(decision.retryable)
            self.assertIn("continuity", decision.reason)


if __name__ == "__main__":
    unittest.main()
