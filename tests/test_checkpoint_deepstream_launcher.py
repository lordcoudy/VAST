from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from checkpoint_deepstream_launcher import (  # noqa: E402
    ADAPTER_CONFIG_ENV,
    build_deepstream_source_specs,
    build_deepstream_worker_specs,
    launch_deepstream_worker_processes,
)


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
ADAPTER_CONFIG = "/run/vast/deepstream-adapter.json"


def plan(topology: str) -> dict:
    processes = []
    for stream_id in range(6):
        source = {
            "stream_id": stream_id,
            "source_sha256": f"{stream_id + 1:064x}",
            "source_codec": "h264",
            "source_duration_ns": (
                33_120_000_000_000 if stream_id < 5 else 35_646_000_000_000
            ),
        }
        if topology == "independent_processes":
            for branch in BRANCHES:
                processes.append({
                    "process_id": f"deepstream-baseline-stream-{stream_id}-{branch}",
                    "stream_id": stream_id,
                    "branch": branch,
                    "branches": [branch],
                    **source,
                })
        else:
            processes.append({
                "process_id": f"deepstream-shared-stream-{stream_id}",
                "stream_id": stream_id,
                "branches": list(BRANCHES),
                **source,
            })
    return {
        "system": "deepstream",
        "scenario": (
            "checkpoint_independent_processes_baseline"
            if topology == "independent_processes"
            else "checkpoint_video_dag_shared"
        ),
        "topology_kind": topology,
        "codec": "h264",
        "dataset": "kpp_iss_publication_v3_h264",
        "policy": "heft",
        "deadline_ms": 100.0,
        "stream_count": 6,
        "required_branches": list(BRANCHES),
        "processes": processes,
    }


class DeepStreamLauncherTests(unittest.TestCase):
    def test_baseline_has_twenty_four_distinct_os_process_commands(self) -> None:
        specs = build_deepstream_worker_specs(
            plan("independent_processes"), run_id="run-baseline", arm_id="arm-baseline",
            adapter_config_path=ADAPTER_CONFIG,
        )
        self.assertEqual(len(specs), 24)
        self.assertEqual(len({spec.worker_id for spec in specs}), 24)
        self.assertTrue(all(spec.branch_id in BRANCHES for spec in specs))
        self.assertTrue(all(spec.command[0] == "/usr/local/bin/vast_deepstream_checkpoint_runtime" for spec in specs))
        self.assertTrue(all("--topology-kind" in spec.command for spec in specs))
        self.assertTrue(all("--admission-file" not in spec.command for spec in specs))
        self.assertTrue(all(spec.native_event_source for spec in specs))
        self.assertTrue(
            all(
                spec.command[spec.command.index("--callback-factory") + 1]
                == "checkpoint_deepstream_protocol_adapter:create_callbacks"
                for spec in specs
            )
        )
        self.assertTrue(all(
            spec.environment["VAST_DEEPSTREAM_SOURCE_DURATION_NS"] == "33120000000000"
            for spec in specs[:20]
        ))
        self.assertTrue(all(
            spec.environment[ADAPTER_CONFIG_ENV] == ADAPTER_CONFIG for spec in specs
        ))
        registries = {spec.environment["GST_REGISTRY"] for spec in specs}
        self.assertEqual(len(registries), 24)
        self.assertTrue(all(
            value.startswith("/tmp/vast-deepstream-gst-registry-")
            and value.endswith(".bin")
            for value in registries
        ))
        self.assertTrue(all(
            spec.environment["GST_REGISTRY_UPDATE"] == "no"
            and spec.environment["GST_REGISTRY_FORK"] == "no"
            for spec in specs
        ))

    def test_shared_has_six_os_processes_and_four_routes_per_process(self) -> None:
        specs = build_deepstream_worker_specs(
            plan("shared_video_dag"), run_id="run-shared", arm_id="arm-shared",
            adapter_config_path=ADAPTER_CONFIG,
        )
        self.assertEqual(len(specs), 6)
        self.assertTrue(all(spec.branch_id is None for spec in specs))
        self.assertTrue(all(
            spec.environment["VAST_DEEPSTREAM_BRANCHES"] == ",".join(BRANCHES)
            for spec in specs
        ))
        self.assertEqual(
            {spec.environment["VAST_DEEPSTREAM_SOURCE_DURATION_NS"] for spec in specs},
            {"33120000000000", "35646000000000"},
        )

    def test_publication_worker_specs_bind_private_output_and_declared_fds(self) -> None:
        output = Path("/opt/vast/output/native_runtime")
        specs = build_deepstream_worker_specs(
            plan("shared_video_dag"),
            run_id="run-shared",
            arm_id="arm-shared",
            adapter_config_path=ADAPTER_CONFIG,
            output_root=output,
            inherited_fds=(91, 92),
        )
        self.assertTrue(all(spec.inherited_fds == (91, 92) for spec in specs))
        for spec in specs:
            self.assertEqual(
                Path(spec.command[spec.command.index("--output-dir") + 1]),
                output / "workers" / spec.worker_id,
            )

    def test_launcher_delegates_each_spec_to_existing_fd_coordinator(self) -> None:
        captured: dict = {}

        def runner(**kwargs):
            captured.update(kwargs)
            return "sentinel"

        result = launch_deepstream_worker_processes(
            plan=plan("independent_processes"),
            run_id="run-baseline",
            arm_id="arm-baseline",
            adapter_config_path=ADAPTER_CONFIG,
            source_specs=("source-0",),
            policy_socket_handler=lambda _worker, _socket: None,
            runner=runner,
            warmup_s=1.0,
            measurement_s=2.0,
            timeout_s=10.0,
        )
        self.assertEqual(result, "sentinel")
        self.assertEqual(len(captured["specs"]), 24)
        self.assertEqual(captured["source_specs"], ("source-0",))
        self.assertTrue(captured["synchronized_lifecycle"])
        self.assertTrue(captured["require_decoder_placement_verification"])
        self.assertIsNotNone(captured["policy_socket_handler"])

    def test_source_specs_materialize_exact_scaled_playback_contract(self) -> None:
        import tempfile
        import types

        value = plan("shared_video_dag")
        value["source_coordinators"] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for stream_id in range(6):
                relative = Path("data") / f"{stream_id}.mp4"
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"fixture")
                duration = (
                    33_120_000_000_000
                    if stream_id < 5
                    else 35_646_000_000_000
                )
                value["source_coordinators"].append(
                    {
                        "process_id": f"stream-{stream_id}-source-coordinator",
                        "stream_id": stream_id,
                        "input_path": str(relative),
                        "source_sha256": f"{stream_id + 1:064x}",
                        "source_container": "mp4",
                        "source_codec": "h264",
                        "source_duration_ns": duration,
                        "playback_timestamp_scale": 600,
                    }
                )
            checkpoint_runtime = types.ModuleType("checkpoint_runtime")

            class SourceLaunchSpec:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            checkpoint_runtime.SourceLaunchSpec = SourceLaunchSpec
            previous = sys.modules.get("checkpoint_runtime")
            sys.modules["checkpoint_runtime"] = checkpoint_runtime
            try:
                specs = build_deepstream_source_specs(
                    value,
                    source_binary=Path("/usr/local/bin/vast_checkpoint_source"),
                    project_root=root,
                    run_id="run-source",
                )
            finally:
                if previous is None:
                    del sys.modules["checkpoint_runtime"]
                else:
                    sys.modules["checkpoint_runtime"] = previous
        self.assertEqual(len(specs), 6)
        self.assertTrue(all(spec.native_source for spec in specs))
        self.assertEqual(
            specs[0].environment["VAST_CHECKPOINT_SOURCE_DURATION_NS"],
            "33120000000000",
        )
        self.assertTrue(all(
            spec.environment["VAST_CHECKPOINT_PLAYBACK_TIMESTAMP_SCALE"] == "600"
            for spec in specs
        ))
        self.assertEqual(
            len({spec.environment["GST_REGISTRY"] for spec in specs}),
            6,
        )
        self.assertTrue(all(
            spec.environment["GST_REGISTRY_UPDATE"] == "no"
            and spec.environment["GST_REGISTRY_FORK"] == "no"
            for spec in specs
        ))

    def test_publication_source_specs_use_sha_bound_paths_and_declared_fds(self) -> None:
        import tempfile
        import types

        value = plan("shared_video_dag")
        value["source_coordinators"] = []
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bindings: dict[str, str] = {}
            for stream_id in range(6):
                path = root / f"pinned-{stream_id}.mp4"
                payload = f"source-{stream_id}\n".encode("ascii")
                path.write_bytes(payload)
                digest = hashlib.sha256(payload).hexdigest()
                bindings[digest] = str(path)
                value["source_coordinators"].append({
                    "process_id": f"stream-{stream_id}-source-coordinator",
                    "stream_id": stream_id,
                    "input_path": f"unused/{stream_id}.mp4",
                    "source_sha256": digest,
                    "source_container": "mp4",
                    "source_codec": "h264",
                    "source_duration_ns": 33_120_000_000_000,
                    "playback_timestamp_scale": 600,
                })
            checkpoint_runtime = types.ModuleType("checkpoint_runtime")

            class SourceLaunchSpec:
                def __init__(self, **kwargs):
                    self.__dict__.update(kwargs)

            checkpoint_runtime.SourceLaunchSpec = SourceLaunchSpec
            previous = sys.modules.get("checkpoint_runtime")
            sys.modules["checkpoint_runtime"] = checkpoint_runtime
            try:
                specs = build_deepstream_source_specs(
                    value,
                    source_binary=Path("/usr/local/bin/vast_checkpoint_source"),
                    project_root=root,
                    run_id="run-source",
                    pinned_source_paths_by_sha256=bindings,
                    inherited_fds=(93,),
                )
            finally:
                if previous is None:
                    del sys.modules["checkpoint_runtime"]
                else:
                    sys.modules["checkpoint_runtime"] = previous
        self.assertTrue(all(spec.inherited_fds == (93,) for spec in specs))
        self.assertEqual(
            {
                spec.command[spec.command.index("--source-path") + 1]
                for spec in specs
            },
            set(bindings.values()),
        )


if __name__ == "__main__":
    unittest.main()
