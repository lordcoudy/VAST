from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import run_experiments as target  # noqa: E402


class RunExperimentsProjectRootTests(unittest.TestCase):
    def test_backend_grant_without_explicit_project_root_fails_before_dispatch(
        self,
    ) -> None:
        execution_context = target.ExecutionContext(
            run_kind="heterogeneous",
            deployment_mode="heterogeneous",
            host_topology="single_host",
            distributed_enabled=False,
            hosts_config={},
            hosts_config_path=Path("<local-heterogeneous>"),
            sync_project=False,
        )
        with (
            mock.patch.object(target, "validate_pre_run_backend_runtime_grant") as validate,
            self.assertRaisesRegex(
                target.ContractError,
                "requires an explicit caller project_root",
            ),
        ):
            target.run_one(
                config={},
                dataset={},
                system_key="gstreamer_custom",
                scenario={},
                streams=6,
                min_objects=0,
                max_objects=20,
                duration_s=180,
                repeat_index=1,
                run_root=Path("unused"),
                execution_context=execution_context,
                mode="benchmark",
                policy="cpu_only",
                deadline_ms=100.0,
                base_seed=20260323,
                dry_run_plan=False,
                backend_runtime_grant={"present": True},
            )
        validate.assert_not_called()

    def test_publication_spawn_uses_explicit_caller_root_and_closed_process_abi(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            caller_root = (Path(tmp) / "caller-project").resolve()
            caller_root.mkdir()
            video = caller_root / "data" / "video.mp4"
            video.parent.mkdir()
            video.write_bytes(b"video")
            run_root = caller_root / "runs" / "publication"
            identity_sha = "1" * 64
            parity_sha = "2" * 64
            backend_grant = {
                "identity_artifact_binding_sha256": identity_sha,
                "upstream_identities": {
                    "model_parity_acceptance_binding_sha256": parity_sha,
                },
            }
            parity_grant = {
                "identity_artifact_binding_sha256": identity_sha,
                "parity_acceptance_binding_sha256": parity_sha,
            }
            resource_grant = {
                "identity_artifact_binding_sha256": identity_sha,
            }
            identity_artifacts = {"binding_sha256": identity_sha}
            execution_binding = {"verified": True}
            resolution = {
                "system": "gstreamer_custom",
                "topology_kind": "shared_video_dag",
                "codec": "h264",
                "policy": "cpu_only",
                "deadline_ms": 100.0,
                "launcher": {"path": "scripts/publication_launcher.py"},
            }
            config = {
                "protocol": {"metric_interval_s": 1.0, "warmup_s": 0},
                "benchmark": {},
                "systems": {
                    "gstreamer_custom": {
                        "detector": "detector",
                        "backend": "backend",
                        "supports_distributed": False,
                    }
                },
            }
            dataset = {
                "name": "kpp_real_h264",
                "codec_variant": "h264",
                "streams": [{"absolute_path": str(video)}],
            }
            scenario = {
                "name": "checkpoint_video_dag_shared",
                "topology": {"kind": "shared_video_dag"},
                "workload": {"seed_group": "checkpoint"},
                "pipeline": [],
            }
            execution_context = target.ExecutionContext(
                run_kind="heterogeneous",
                deployment_mode="heterogeneous",
                host_topology="single_host",
                distributed_enabled=False,
                hosts_config={},
                hosts_config_path=Path("<local-heterogeneous>"),
                sync_project=False,
            )
            collector = mock.Mock()
            hardware_collector = mock.Mock()
            hardware_collector.is_alive.return_value = False
            command = [str(Path(sys.executable).resolve()), "launcher.py"]

            with (
                mock.patch.object(
                    target,
                    "validate_pre_run_backend_runtime_grant",
                    return_value=backend_grant,
                ),
                mock.patch.object(
                    target,
                    "backend_runtime_grant_from_identity_artifacts",
                    return_value=backend_grant,
                ),
                mock.patch.object(
                    target,
                    "validate_pre_run_model_parity_grant",
                    return_value=parity_grant,
                ),
                mock.patch.object(
                    target,
                    "model_parity_grant_from_identity_artifacts",
                    return_value=parity_grant,
                ),
                mock.patch.object(
                    target,
                    "validate_full_publication_execution_binding",
                    return_value=execution_binding,
                ),
                mock.patch.object(target, "BackendPublicationDispatchResolver") as resolver,
                mock.patch.object(target, "validate_benchmark_adapter", return_value=None),
                mock.patch.object(target, "validate_checkpoint_workload"),
                mock.patch.object(
                    target,
                    "scenario_contract_identity",
                    return_value={"schema_version": 1, "sha256": "3" * 64},
                ),
                mock.patch.object(target, "MetricsCollector", return_value=collector),
                mock.patch.object(
                    target,
                    "make_hardware_resource_collector",
                    return_value=hardware_collector,
                ),
                mock.patch.object(
                    target,
                    "build_backend_publication_arm_contract",
                    return_value={"contract": "closed"},
                ),
                mock.patch.object(
                    target,
                    "write_immutable_backend_publication_arm_contract",
                    return_value={"authority": "closed"},
                ),
                mock.patch.object(
                    target,
                    "build_backend_publication_command",
                    return_value=command,
                ) as build_command,
                mock.patch.object(
                    target.subprocess,
                    "run",
                    return_value=subprocess.CompletedProcess(command, 73),
                ) as spawn,
                mock.patch.object(target, "measured_metrics_duration_s", return_value=0.0),
                mock.patch.dict(
                    target.os.environ,
                    {"EXPERIMENT_CMD_TIMEOUT_S": "41"},
                    clear=True,
                ),
                self.assertRaisesRegex(RuntimeError, "exit code 73"),
            ):
                resolver.return_value.resolve.return_value = resolution
                target.run_one(
                    config=config,
                    dataset=dataset,
                    system_key="gstreamer_custom",
                    scenario=scenario,
                    streams=6,
                    min_objects=0,
                    max_objects=20,
                    duration_s=180,
                    repeat_index=1,
                    run_root=run_root,
                    execution_context=execution_context,
                    mode="benchmark",
                    policy="cpu_only",
                    deadline_ms=100.0,
                    base_seed=20260323,
                    dry_run_plan=False,
                    resource_capability_grant=resource_grant,
                    backend_runtime_grant=backend_grant,
                    model_parity_grant=parity_grant,
                    full_publication_execution_binding=execution_binding,
                    full_publication_identity_artifacts=identity_artifacts,
                    project_root=caller_root,
                )

            resolver.return_value.resolve.assert_called_once()
            build_command.assert_called_once()
            self.assertEqual(build_command.call_args.kwargs["project_root"], caller_root)
            self.assertEqual(
                build_command.call_args.kwargs["identity_artifacts"],
                identity_artifacts,
            )
            spawn.assert_called_once_with(
                command,
                shell=False,
                check=False,
                timeout=41,
                env={},
                cwd=caller_root,
            )
            self.assertNotEqual(caller_root, target.PROJECT_ROOT)


if __name__ == "__main__":
    unittest.main()
