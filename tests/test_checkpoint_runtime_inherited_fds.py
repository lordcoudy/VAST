from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from checkpoint_runtime import (  # noqa: E402
    SourceLaunchSpec,
    WorkerLaunchSpec,
    _combined_inherited_fds,
    run_worker_processes,
)


class CheckpointRuntimeInheritedFdTests(unittest.TestCase):
    def test_worker_and_source_specs_bind_closed_unique_inherited_fds(self) -> None:
        worker = WorkerLaunchSpec(
            worker_id="worker",
            stream_id=0,
            branch_id="damage",
            command=("/proc/self/fd/10",),
            inherited_fds=(10, 11),
        )
        source = SourceLaunchSpec(
            source_process_id="source",
            stream_id=0,
            dataset_id="dataset",
            source_sha256="a" * 64,
            command=("/proc/self/fd/12",),
            inherited_fds=(12, 13),
        )
        self.assertEqual(_combined_inherited_fds(worker, (20, 21)), (10, 11, 20, 21))
        self.assertEqual(_combined_inherited_fds(source, (21, 20)), (12, 13, 20, 21))

    def test_invalid_inherited_fds_fail_closed(self) -> None:
        for value in ((1, 1), (-1,), (True,), [10]):
            with self.subTest(value=value), self.assertRaises(ValueError):
                WorkerLaunchSpec(
                    worker_id="worker",
                    stream_id=0,
                    branch_id=None,
                    command=("binary",),
                    inherited_fds=value,
                )

    @unittest.skipUnless(os.name == "posix", "pass_fds is POSIX-only")
    def test_declared_file_descriptor_reaches_the_exact_native_popen(self) -> None:
        read_fd, write_fd = os.pipe()
        observed: tuple[int, ...] = ()

        class StopBeforeExec(RuntimeError):
            pass

        def stop(_command: tuple[str, ...], **kwargs: object) -> None:
            nonlocal observed
            observed = tuple(kwargs["pass_fds"])
            raise StopBeforeExec

        spec = WorkerLaunchSpec(
            worker_id="worker",
            stream_id=0,
            branch_id="damage",
            command=("fixture-native-binary",),
            inherited_fds=(read_fd,),
        )
        try:
            with mock.patch(
                "checkpoint_runtime.subprocess.Popen", side_effect=stop
            ), self.assertRaises(StopBeforeExec):
                run_worker_processes(
                    run_id="run",
                    topology_kind="independent_processes",
                    branches=("damage",),
                    specs=(spec,),
                )
            self.assertIn(read_fd, observed)
            self.assertEqual(len(observed), len(set(observed)))
        finally:
            os.close(read_fd)
            os.close(write_fd)

    @unittest.skipUnless(os.name == "posix", "pass_fds is POSIX-only")
    def test_declared_file_descriptor_survives_real_child_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            payload = b"exact-fd-child-payload\n"
            path = Path(tmp) / "pinned.bin"
            path.write_bytes(payload)
            pinned_fd = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
            command = (
                sys.executable,
                "-c",
                (
                    "import os,sys; "
                    "fd=int(sys.argv[1]); expected=bytes.fromhex(sys.argv[2]); "
                    "observed=os.read(fd,len(expected)); "
                    "raise SystemExit(0 if observed == expected else 91)"
                ),
                str(pinned_fd),
                payload.hex(),
            )
            spec = WorkerLaunchSpec(
                worker_id="worker",
                stream_id=0,
                branch_id="damage",
                command=command,
                inherited_fds=(pinned_fd,),
            )
            try:
                result = run_worker_processes(
                    run_id="run",
                    topology_kind="independent_processes",
                    branches=("damage",),
                    specs=(spec,),
                    timeout_s=5.0,
                )
                self.assertIn("worker", result.process_ids)
                os.fstat(pinned_fd)
            finally:
                os.close(pinned_fd)


if __name__ == "__main__":
    unittest.main()
