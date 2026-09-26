from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import inspect
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from publication_policy_qualification_pilot_executor_v2 import (  # noqa: E402
    CHILD_EVIDENCE_FILES,
    RUNTIME_BUNDLE_KIND,
    RUNTIME_BUNDLE_SCOPE,
    RUNTIME_INPUT_KEY_BY_SYSTEM,
    _load_qualification_inputs,
    qualification_pilot_cells_v2,
)
from publication_policy_qualification_runtime_inputs_v2 import (  # noqa: E402
    QualificationRuntimeInputMaterializationV2Error,
    _analytics_inventory,
    _binding_document_schema,
    _bundle_value_v2,
    _canonical_sha,
    _preflight_savant_reachable_worker,
    _require_socket_transport,
    _runtime_contract_for_cell,
    _socket_record,
    _write_bundle_tree_v2,
    materialize_publication_policy_qualification_runtime_inputs_v2,
)
import publication_policy_qualification_runtime_inputs_v2 as runtime_target  # noqa: E402
import publication_policy_qualification_pilot_executor_v2 as pilot_target  # noqa: E402
import publication_policy_qualification_execution_closure_v1 as closure_target  # noqa: E402
from analytics_execution_capability import load_execution_layer_config  # noqa: E402
import checkpoint_deepstream_publication_runtime_v3 as deepstream_runtime  # noqa: E402
import checkpoint_gstreamer_publication_runtime_v3 as gstreamer_runtime  # noqa: E402
import checkpoint_openvino_gva_publication_runtime_v3 as openvino_runtime  # noqa: E402
import checkpoint_savant_publication_runtime_v3 as savant_runtime  # noqa: E402


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


def is_wsl_drvfs_workspace() -> bool:
    if os.name != "posix" or not Path("/proc/self/mountinfo").is_file():
        return False
    try:
        release = Path("/proc/sys/kernel/osrelease").read_text(
            encoding="ascii"
        )
        mount_lines = Path("/proc/self/mountinfo").read_text(
            encoding="utf-8"
        ).splitlines()
    except OSError:
        return False
    if "microsoft" not in release.lower():
        return False
    root = ROOT.resolve()
    for line in mount_lines:
        fields = line.split()
        try:
            separator = fields.index("-")
            mountpoint = Path(fields[4].replace("\\040", " "))
        except (IndexError, ValueError):
            continue
        if root != mountpoint and mountpoint not in root.parents:
            continue
        filesystem = fields[separator + 1]
        super_options = fields[separator + 3 :]
        if filesystem == "drvfs" or (
            filesystem == "9p"
            and any("aname=drvfs" in item for item in super_options)
        ):
            return True
    return False


def runtime_inputs(cell):
    runtime_key = RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
    contract = {
        "defer_full_resource_acceptance": True,
        "evidence_mapping": {name: name for name in CHILD_EVIDENCE_FILES},
    }
    return {
        "system": cell.system,
        "resource": cell.resource,
        "scenario": cell.scenario,
        "topology_kind": cell.topology_kind,
        "codec": cell.codec,
        "policy": cell.policy,
        "deadline_ms": cell.deadline_ms,
        "duration_s": cell.duration_s,
        "streams": 6,
        "run_id": cell.run_id,
        "dataset": {
            "name": f"kpp_iss_publication_v3_{cell.codec}",
            runtime_key: contract,
        },
    }


HARDWARE_COLLECTOR_DESCRIPTOR = {
    "path": "scripts/collect_metrics.py",
    "size_bytes": 1,
    "sha256": "a" * 64,
}


class QualificationRuntimeInputsV2Tests(unittest.TestCase):
    def test_device_probe_binding_round_trips_through_native_consumers(self) -> None:
        modules = {
            "openvino_gva": openvino_runtime,
            "gstreamer_custom": gstreamer_runtime,
        }
        elements = set().union(
            *(module.REQUIRED_GSTREAMER_ELEMENTS for module in modules.values())
        )
        probe = {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_checkpoint_device_probe",
            "openvino_version": "test-openvino-version",
            "available_devices": [{"device_id": "CPU"}],
            "gstreamer_elements": {
                name: {"available": True, "factory": name}
                for name in sorted(elements)
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            inventory = SimpleNamespace(
                root=root,
                nvidia={"uuid": "GPU-test", "name": "test-gpu", "driver_version": "test"},
            )
            recorded = runtime_target._probe_devices(  # noqa: SLF001
                inventory,
                {
                    system: {"contract": {"image_id": module.EXPECTED_IMAGE_ID}}
                    for system, module in modules.items()
                },
                engine=root / "docker",
                engine_socket=root / "docker.sock",
                dependencies=SimpleNamespace(probe_openvino_device=lambda *args: probe),
            )
            pins = SimpleNamespace(roles={
                "device_probe": SimpleNamespace(
                    container_path=Path("/workspace/project/probe.py")
                ),
                "container_engine": SimpleNamespace(),
            })
            for system, module in modules.items():
                with self.subTest(system=system):
                    device = runtime_target._device_binding(  # noqa: SLF001
                        inventory, probe=recorded[system],
                        capability_hashes={"cpu": "a" * 64, "gpu": "b" * 64},
                    )
                    contract = SimpleNamespace(device=device, engine_socket=root / "docker.sock")
                    materialized = SimpleNamespace(root=root)
                    kwargs = {"output_dir": root} if system == "openvino_gva" else {}
                    with mock.patch.object(
                        module, "_invoke_engine",
                        return_value=SimpleNamespace(
                            returncode=0, stdout=canonical(probe), stderr=b""
                        ),
                    ):
                        module._probe_openvino_devices(  # noqa: SLF001
                            pins, contract, materialized, **kwargs
                        )
                    self.assertEqual(
                        recorded[system]["sha256"],
                        hashlib.sha256(canonical(probe).rstrip(b"\n")).hexdigest(),
                    )
                    changed_probe = {**probe, "openvino_version": "changed-version"}
                    error_type = (
                        openvino_runtime.OpenVINOGVAPublicationRuntimeV3Error
                        if system == "openvino_gva"
                        else gstreamer_runtime.GstreamerPublicationRuntimeV3Error
                    )
                    with mock.patch.object(
                        module, "_invoke_engine",
                        return_value=SimpleNamespace(
                            returncode=0, stdout=canonical(changed_probe), stderr=b""
                        ),
                    ), self.assertRaisesRegex(error_type, "device_probe_identity_changed"):
                        module._probe_openvino_devices(  # noqa: SLF001
                            pins, contract, materialized, **kwargs
                        )

    @unittest.skipUnless(
        is_wsl_drvfs_workspace(),
        "live no-replace race requires the WSL DrvFS workspace",
    )
    def test_drvfs_runtime_directory_commit_race_has_exactly_one_winner(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory(
            prefix=".qualification-runtime-commit-race.", dir=ROOT
        ) as temporary:
            parent = Path(temporary)
            sources = (parent / "source-a", parent / "source-b")
            for index, source in enumerate(sources):
                source.mkdir()
                (source / "winner").write_text(
                    f"source-{index}\n", encoding="ascii"
                )
            destination = parent / "destination"
            barrier = threading.Barrier(3)
            outcomes: list[tuple[Path, BaseException | None]] = []
            outcome_lock = threading.Lock()

            def commit(source: Path) -> None:
                barrier.wait(timeout=10)
                error: BaseException | None = None
                try:
                    runtime_target._rename_directory_noreplace(  # noqa: SLF001
                        source, destination
                    )
                except BaseException as caught:
                    error = caught
                with outcome_lock:
                    outcomes.append((source, error))

            threads = tuple(
                threading.Thread(target=commit, args=(source,))
                for source in sources
            )
            for thread in threads:
                thread.start()
            barrier.wait(timeout=10)
            for thread in threads:
                thread.join(timeout=30)
                self.assertFalse(thread.is_alive())

            winners = [source for source, error in outcomes if error is None]
            losers = [
                (source, error) for source, error in outcomes if error is not None
            ]
            self.assertEqual(len(winners), 1, repr(outcomes))
            self.assertEqual(len(losers), 1, repr(outcomes))
            self.assertIsInstance(
                losers[0][1], pilot_target.QualificationPilotExecutorV2Error
            )
            self.assertFalse(winners[0].exists())
            self.assertTrue(losers[0][0].is_dir())
            self.assertEqual(
                (destination / "winner").read_text(encoding="ascii"),
                ("source-0\n" if winners[0] == sources[0] else "source-1\n"),
            )

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "runtime tree durability barriers require Linux/WSL",
    )
    def test_runtime_tree_postpublish_crash_exact_retry_and_tamper_rejection(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary).resolve()
            final = parent / "qualification-runtime-inputs-v2"
            parent_identity = runtime_target._directory_identity(parent)  # noqa: SLF001

            def make_staging() -> tuple[Path, tuple[int, int]]:
                staging = Path(
                    tempfile.mkdtemp(
                        prefix=".qualification-runtime-inputs-v2.",
                        dir=parent,
                    )
                )
                (staging / "nested").mkdir()
                (staging / "nested" / "bundle.json").write_bytes(b'{"bundle":1}\n')
                (staging / "receipt.json").write_bytes(b'{"receipt":1}\n')
                identity = runtime_target._directory_identity(staging)  # noqa: SLF001
                runtime_target._seal_tree(staging)  # noqa: SLF001
                return staging, identity

            first, first_identity = make_staging()

            def crash(step: str, path: Path) -> None:
                self.assertEqual(step, "post_publish_pre_parent_fsync")
                self.assertEqual(path, final)
                raise KeyboardInterrupt("simulated hard crash")

            with self.assertRaises(KeyboardInterrupt):
                runtime_target._publish_runtime_tree_noreplace(  # noqa: SLF001
                    first,
                    final,
                    parent=parent,
                    staging_identity=first_identity,
                    parent_identity=parent_identity,
                    destination_preexisted=False,
                    after_directory_publish_step=crash,
                )
            self.assertFalse(first.exists())
            directory_inode = final.stat().st_ino
            leaf_inodes = {
                path.relative_to(final).as_posix(): path.stat().st_ino
                for path in final.rglob("*")
            }

            second, second_identity = make_staging()
            self.assertEqual(
                runtime_target._publish_runtime_tree_noreplace(  # noqa: SLF001
                    second,
                    final,
                    parent=parent,
                    staging_identity=second_identity,
                    parent_identity=parent_identity,
                    destination_preexisted=True,
                    after_directory_publish_step=None,
                ),
                "adopted",
            )
            runtime_target._safe_remove_staging(  # noqa: SLF001
                second,
                parent=parent,
                expected_staging_identity=second_identity,
                expected_parent_identity=parent_identity,
            )
            self.assertEqual(final.stat().st_ino, directory_inode)
            self.assertEqual(
                {
                    path.relative_to(final).as_posix(): path.stat().st_ino
                    for path in final.rglob("*")
                },
                leaf_inodes,
            )

            attacked = final / "nested" / "bundle.json"
            attacked.chmod(0o600)
            attacked.write_bytes(b"foreign-runtime-bundle\n")
            attacked.chmod(0o444)
            foreign_inode = attacked.stat().st_ino
            third, third_identity = make_staging()
            with self.assertRaises(QualificationRuntimeInputMaterializationV2Error):
                runtime_target._publish_runtime_tree_noreplace(  # noqa: SLF001
                    third,
                    final,
                    parent=parent,
                    staging_identity=third_identity,
                    parent_identity=parent_identity,
                    destination_preexisted=True,
                    after_directory_publish_step=None,
                )
            self.assertEqual(attacked.stat().st_ino, foreign_inode)
            self.assertEqual(attacked.read_bytes(), b"foreign-runtime-bundle\n")
            runtime_target._safe_remove_staging(  # noqa: SLF001
                third,
                parent=parent,
                expected_staging_identity=third_identity,
                expected_parent_identity=parent_identity,
            )
            for path in sorted(final.rglob("*"), reverse=True):
                path.chmod(0o700 if path.is_dir() else 0o600)
            final.chmod(0o700)

    def test_cli_and_closure_share_exact_float_deadline_matrix_identity(
        self,
    ) -> None:
        runtime_argv = [
            "--project-root", "/tmp/project",
            "--candidate-index", "candidate-index.json",
            "--candidate-manifest", "candidate-manifest.json",
            "--candidate-receipt", "candidate-receipt.json",
            "--bootstrap-mapping", "mapping.json",
            "--bootstrap-receipt", "bootstrap-receipt.json",
            "--bootstrap-dir", "bootstrap",
            "--qualification-transaction-receipt", "transaction.json",
        ]
        runtime_result = {
            "runtime_input_root": Path("/tmp/project/runtime-inputs"),
            "receipt_path": Path("/tmp/project/runtime-inputs/receipt.json"),
            "bundle_count": 32,
            "matrix_sha256": "a" * 64,
        }

        def runtime_deadline(extra: list[str]) -> int | float:
            with (
                mock.patch.object(
                    runtime_target,
                    "materialize_publication_policy_qualification_runtime_inputs_v2",
                    return_value=runtime_result,
                ) as materialize,
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(runtime_target.main([*runtime_argv, *extra]), 0)
            return materialize.call_args.kwargs["deadline_ms"]

        pilot_argv = [
            "--project-root", "/tmp/project",
            "--candidate-index", "candidate-index.json",
            "--candidate-manifest", "candidate-manifest.json",
            "--candidate-receipt", "candidate-receipt.json",
            "--bootstrap-mapping", "mapping.json",
            "--bootstrap-receipt", "bootstrap-receipt.json",
            "--bootstrap-dir", "bootstrap",
            "--qualification-transaction-receipt", "transaction.json",
            "--runtime-input-materialization-receipt", "runtime-receipt.json",
            "--guardian-service-authority", "service-authority.json",
            "--preprocessing-contract", "preprocessing.json",
            "--preprocessing-contract-receipt", "preprocessing-receipt.json",
            "--execution-code-closure-receipt", "execution-code-closure.json",
            "--pilot-root", "pilots",
            "--checkpoint", "checkpoint.json",
        ]
        deadlines = (
            runtime_deadline([]),
            runtime_deadline(["--deadline-ms", "100"]),
            pilot_target._parse_args(pilot_argv).deadline_ms,  # noqa: SLF001
            pilot_target._parse_args(  # noqa: SLF001
                [*pilot_argv, "--deadline-ms", "100"]
            ).deadline_ms,
        )
        self.assertTrue(
            all(
                type(deadline) is float and deadline == 100.0
                for deadline in deadlines
            )
        )

        matrices = (
            pilot_target.qualification_pilot_cells_v2(),
            pilot_target.qualification_pilot_cells_v2(deadline_ms=100),
            *(
                pilot_target.qualification_pilot_cells_v2(deadline_ms=value)
                for value in deadlines
            ),
            closure_target.qualification_pilot_cells_v2(),
            closure_target.qualification_pilot_cells_v2(deadline_ms=100),
        )
        self.assertTrue(
            all(
                type(cell.deadline_ms) is float and cell.deadline_ms == 100.0
                for cells in matrices
                for cell in cells
            )
        )
        identities = {
            runtime_target._canonical_sha([cell.__dict__ for cell in cells])
            for cells in matrices
        }
        identities.add(closure_target.matrix_sha256(matrices[-1]))
        identities.add(pilot_target._matrix_sha(matrices[0]))  # noqa: SLF001
        self.assertEqual(
            identities,
            {
                "48b7f9d567c74d9fd0f8ce94c6b220bb212a77e952027f7ec7d6bad8894dfe45"
            },
        )

    def test_transaction_receipt_is_required_at_public_runtime_boundary_only(
        self,
    ) -> None:
        public_parameter = inspect.signature(
            materialize_publication_policy_qualification_runtime_inputs_v2
        ).parameters["transaction_receipt_path"]
        precommit_parameter = inspect.signature(
            _load_qualification_inputs
        ).parameters["transaction_receipt_path"]

        self.assertIs(public_parameter.default, inspect.Parameter.empty)
        self.assertIsNone(precommit_parameter.default)

        argv = [
            "--project-root", "/tmp/project",
            "--candidate-index", "candidate-index.json",
            "--candidate-manifest", "candidate-manifest.json",
            "--candidate-receipt", "candidate-receipt.json",
            "--bootstrap-mapping", "mapping.json",
            "--bootstrap-receipt", "bootstrap-receipt.json",
            "--bootstrap-dir", "bootstrap",
        ]
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            runtime_target.main(argv)

        argv.extend(
            [
                "--qualification-transaction-receipt",
                "qualification_input_transaction.v2.receipt.json",
            ]
        )
        result = {
            "runtime_input_root": Path("/tmp/project/runtime-inputs"),
            "receipt_path": Path("/tmp/project/runtime-inputs/receipt.json"),
            "bundle_count": 32,
            "matrix_sha256": "a" * 64,
        }
        with (
            mock.patch.object(
                runtime_target,
                "materialize_publication_policy_qualification_runtime_inputs_v2",
                return_value=result,
            ) as materialize,
            redirect_stdout(io.StringIO()) as output,
        ):
            self.assertEqual(runtime_target.main(argv), 0)
        materialize.assert_called_once()
        self.assertEqual(
            materialize.call_args.kwargs["transaction_receipt_path"],
            Path("qualification_input_transaction.v2.receipt.json"),
        )
        self.assertEqual(
            json.loads(output.getvalue()),
            {
                "bundle_count": 32,
                "matrix_sha256": "a" * 64,
                "receipt_path": "/tmp/project/runtime-inputs/receipt.json",
                "runtime_input_root": "/tmp/project/runtime-inputs",
            },
        )

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_live_socket_transport_does_not_confuse_kernel_and_node_inodes(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            for filename, socket_type, expected_type in (
                ("engine.sock", socket.SOCK_STREAM, "0001"),
                ("analytics.sock", socket.SOCK_SEQPACKET, "0005"),
            ):
                path = root / filename
                endpoint = socket.socket(socket.AF_UNIX, socket_type)
                try:
                    endpoint.bind(str(path))
                    if socket_type == socket.SOCK_SEQPACKET:
                        endpoint.listen(1)
                    record = _socket_record(path, label=filename)
                    # Linux exposes a socket-object inode in /proc/net/unix;
                    # the immutable runtime contract correctly pins the
                    # separate filesystem node inode returned by lstat(2).
                    proc_rows = [
                        row.split(maxsplit=7)
                        for row in Path("/proc/net/unix")
                        .read_text(encoding="ascii")
                        .splitlines()[1:]
                        if row.split(maxsplit=7)[-1] == str(path)
                    ]
                    self.assertEqual(len(proc_rows), 1)
                    self.assertNotEqual(int(proc_rows[0][6]), record["inode"])
                    _require_socket_transport(
                        record,
                        expected_type=expected_type,
                        label=filename,
                    )
                finally:
                    endpoint.close()

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_renamed_live_seqpacket_socket_is_validated_at_final_path(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            hidden_path = root / ".analytics.sock.pending"
            final_path = root / "analytics.sock"
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            try:
                endpoint.bind(str(hidden_path))
                endpoint.listen(4)
                os.replace(hidden_path, final_path)
                record = _socket_record(final_path, label="analytics socket")
                proc_paths = {
                    fields[7]
                    for row in Path("/proc/net/unix")
                    .read_text(encoding="ascii")
                    .splitlines()[1:]
                    if len(fields := row.split()) >= 8
                }
                self.assertIn(str(hidden_path), proc_paths)
                self.assertNotIn(str(final_path), proc_paths)

                probe = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                try:
                    probe.connect(str(final_path))
                    self.assertEqual(probe.getpeername(), str(hidden_path))
                finally:
                    probe.close()

                _require_socket_transport(
                    record,
                    expected_type="0005",
                    label="analytics socket",
                )
            finally:
                endpoint.close()

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_seqpacket_transport_cross_checks_connected_kernel_peer(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "analytics.sock"
            original_factory = socket.socket
            listener = original_factory(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            try:
                listener.bind(str(path))
                listener.listen(1)
                record = _socket_record(path, label="analytics socket")

                class MisreportingEndpoint:
                    def __init__(self, *args, **kwargs) -> None:
                        self._inner = original_factory(*args, **kwargs)

                    def settimeout(self, value: float) -> None:
                        self._inner.settimeout(value)

                    def connect(self, target: str) -> None:
                        self._inner.connect(target)

                    def getsockopt(self, *args, **kwargs):
                        return self._inner.getsockopt(*args, **kwargs)

                    def getpeername(self) -> str:
                        return str(root / "unlisted-peer.sock")

                    def close(self) -> None:
                        self._inner.close()

                with (
                    mock.patch.object(socket, "socket", MisreportingEndpoint),
                    self.assertRaisesRegex(
                        QualificationRuntimeInputMaterializationV2Error,
                        "connected peer is not the exact live Unix socket transport",
                    ),
                ):
                    _require_socket_transport(
                        record,
                        expected_type="0005",
                        label="analytics socket",
                    )
            finally:
                listener.close()

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_seqpacket_transport_rejects_wrong_socket_type(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "analytics.sock"
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                endpoint.bind(str(path))
                endpoint.listen(1)
                record = _socket_record(path, label="analytics socket")
                with self.assertRaisesRegex(
                    QualificationRuntimeInputMaterializationV2Error,
                    "reachable live SOCK_SEQPACKET",
                ):
                    _require_socket_transport(
                        record,
                        expected_type="0005",
                        label="analytics socket",
                    )
            finally:
                endpoint.close()

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_seqpacket_transport_rejects_dead_socket_node(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "analytics.sock"
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            endpoint.bind(str(path))
            endpoint.listen(1)
            record = _socket_record(path, label="analytics socket")
            endpoint.close()

            with self.assertRaisesRegex(
                QualificationRuntimeInputMaterializationV2Error,
                "reachable live SOCK_SEQPACKET",
            ):
                _require_socket_transport(
                    record,
                    expected_type="0005",
                    label="analytics socket",
                )

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_seqpacket_transport_rejects_path_replacement_during_connect(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / "analytics.sock"
            displaced_path = root / "analytics.displaced.sock"
            replacement_pending_path = root / ".analytics.replacement.pending"
            original_factory = socket.socket
            original_listener = original_factory(
                socket.AF_UNIX, socket.SOCK_SEQPACKET
            )
            replacement_listeners: list[socket.socket] = []
            try:
                original_listener.bind(str(path))
                original_listener.listen(1)
                record = _socket_record(path, label="analytics socket")

                class ReplacingEndpoint:
                    def __init__(self, *args, **kwargs) -> None:
                        self._inner = original_factory(*args, **kwargs)

                    def settimeout(self, value: float) -> None:
                        self._inner.settimeout(value)

                    def connect(self, target: str) -> None:
                        os.replace(path, displaced_path)
                        replacement = original_factory(
                            socket.AF_UNIX, socket.SOCK_SEQPACKET
                        )
                        replacement.bind(str(replacement_pending_path))
                        replacement.listen(1)
                        os.replace(replacement_pending_path, path)
                        replacement_listeners.append(replacement)
                        self._inner.connect(target)

                    def getsockopt(self, *args, **kwargs):
                        return self._inner.getsockopt(*args, **kwargs)

                    def getpeername(self) -> str:
                        return self._inner.getpeername()

                    def close(self) -> None:
                        self._inner.close()

                with (
                    mock.patch.object(socket, "socket", ReplacingEndpoint),
                    self.assertRaisesRegex(
                        QualificationRuntimeInputMaterializationV2Error,
                        "identity changed during transport validation",
                    ),
                ):
                    _require_socket_transport(
                        record,
                        expected_type="0005",
                        label="analytics socket",
                    )
            finally:
                original_listener.close()
                for listener in replacement_listeners:
                    listener.close()

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_stream_transport_keeps_exact_proc_path_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            hidden_path = root / ".engine.sock.pending"
            final_path = root / "engine.sock"
            endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                endpoint.bind(str(hidden_path))
                endpoint.listen(1)
                os.replace(hidden_path, final_path)
                record = _socket_record(final_path, label="container engine socket")
                with self.assertRaisesRegex(
                    QualificationRuntimeInputMaterializationV2Error,
                    "not the exact live Unix socket transport",
                ):
                    _require_socket_transport(
                        record,
                        expected_type="0001",
                        label="container engine socket",
                    )
            finally:
                endpoint.close()

    @unittest.skipUnless(
        os.name == "posix" and sys.platform.startswith("linux"),
        "physical AF_UNIX transport validation requires Linux/WSL",
    )
    def test_stream_transport_allows_clients_but_requires_unique_bound_endpoint(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "engine.sock"
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            accepted = None
            try:
                listener.bind(str(path))
                listener.listen(4)
                record = _socket_record(path, label="container engine socket")
                client.connect(str(path))
                accepted, _address = listener.accept()

                proc_rows = [
                    row.split()
                    for row in Path("/proc/net/unix")
                    .read_text(encoding="ascii")
                    .splitlines()[1:]
                    if len(row.split()) >= 8 and row.split()[7] == str(path)
                ]
                self.assertGreaterEqual(len(proc_rows), 2)
                self.assertEqual(
                    sum(
                        fields[4] == "0001"
                        and fields[5] == "01"
                        for fields in proc_rows
                    ),
                    1,
                )
                _require_socket_transport(
                    record,
                    expected_type="0001",
                    label="container engine socket",
                )
            finally:
                if accepted is not None:
                    accepted.close()
                client.close()
                listener.close()

    def test_versioned_binding_document_requires_its_self_identity(self) -> None:
        value = {
            "schema_version": 2,
            "artifact_kind": (
                "vast_publication_policy_qualification_authority_binding_v2"
            ),
            "system": "deepstream",
        }
        value["binding_sha256"] = _canonical_sha(value)
        self.assertEqual(
            _binding_document_schema(value, label="versioned binding"), 2
        )
        value["system"] = "savant"
        with self.assertRaisesRegex(
            QualificationRuntimeInputMaterializationV2Error,
            "versioned authority identity drifted",
        ):
            _binding_document_schema(value, label="versioned binding")

    def test_versioned_analytics_authority_selects_bound_paths_not_v3_constants(
        self,
    ) -> None:
        branches = ("plate_number", "vehicle_type", "damage", "foreign_object")
        resources = ("cpu", "gpu")
        systems = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
        engines = {"cpu": "openvino_cpu", "gpu": "tensorrt_cuda"}

        def descriptor(root: Path, path: Path) -> dict[str, object]:
            payload = path.read_bytes()
            return {
                "path": path.relative_to(root).as_posix(),
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            config_path = root / "authority/v4/execution.yaml"
            index_path = root / "authority/v4/bindings/index.json"
            config_path.parent.mkdir(parents=True)
            index_path.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / "configs/analytics_execution_layer.yaml", config_path)
            source_binding_root = (
                ROOT / "artifacts/analytics_execution_bindings/publication_v3"
            )
            shutil.copyfile(source_binding_root / "index.json", index_path)
            for branch in branches:
                for resource in resources:
                    name = f"{branch}.{engines[resource]}.json"
                    shutil.copyfile(source_binding_root / name, index_path.parent / name)
            probe_paths: dict[str, Path] = {}
            for resource in resources:
                target_probe = root / f"authority/v4/probes/{resource}.json"
                target_probe.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(
                    ROOT
                    / "artifacts/analytics_runtime_probes/publication_v3"
                    / f"{resource}_runtime_probe.json",
                    target_probe,
                )
                probe_paths[resource] = target_probe

            config = load_execution_layer_config(config_path)
            index = json.loads(index_path.read_bytes())
            execution_authority = {
                **descriptor(root, config_path),
                "content_identity_sha256": config["identity"]["sha256"],
                "worker_projection_sha256": _canonical_sha(config["workers"]),
            }
            index_authority = {
                **descriptor(root, index_path),
                "identity_sha256": index["identity"]["sha256"],
                "bindings_identity_sha256": index["bindings_identity_sha256"],
            }
            policy_bindings = {}
            for system in systems:
                for branch in branches:
                    for resource in resources:
                        binding_path = (
                            index_path.parent
                            / f"{branch}.{engines[resource]}.json"
                        )
                        probe = json.loads(probe_paths[resource].read_bytes())
                        policy_bindings[(system, branch, resource)] = {
                            "schema_version": 2,
                            "artifact_kind": (
                                "vast_publication_policy_qualification_authority_binding_v2"
                            ),
                            "execution_config": execution_authority,
                            "analytics_execution_binding_index": index_authority,
                            "analytics_execution_worker_binding": descriptor(
                                root, binding_path
                            ),
                            "analytics_runtime_probe": descriptor(
                                root, probe_paths[resource]
                            ),
                            "analytics_runtime_probe_identity_sha256": _canonical_sha(
                                probe
                            ),
                        }

            loaded = _analytics_inventory(root, policy_bindings)
            self.assertEqual(loaded[0].relative, "authority/v4/execution.yaml")
            self.assertTrue(
                all(
                    pin.relative.startswith("authority/v4/bindings/")
                    for pin in loaded[2].values()
                )
            )
            self.assertTrue(
                all(
                    pin.relative.startswith("authority/v4/probes/")
                    for pin in loaded[4].values()
                )
            )

            policy_bindings[("savant", "damage", "cpu")][
                "analytics_execution_worker_binding"
            ] = descriptor(
                root,
                index_path.parent / "plate_number.openvino_cpu.json",
            )
            with self.assertRaisesRegex(
                QualificationRuntimeInputMaterializationV2Error,
                "binding damage/cpu descriptor drifted",
            ):
                _analytics_inventory(root, policy_bindings)

    def test_reachable_savant_worker_closure_is_the_sdk_run_path(self) -> None:
        _preflight_savant_reachable_worker(ROOT)

    def test_image_material_preserves_the_physical_candidate_reference(self) -> None:
        reference = openvino_runtime.EXPECTED_IMAGE_REFERENCE
        value = runtime_target._image_material(
            {
                "openvino_gva_runtime_image": {
                    "final_reference": reference,
                    "image_id": openvino_runtime.EXPECTED_IMAGE_ID,
                    "repository_digest": openvino_runtime.EXPECTED_REPOSITORY_DIGEST,
                },
            },
            "openvino_gva",
        )
        self.assertEqual(value["final_reference"], reference)

    def test_sdk_adapter_support_is_the_exact_referenced_closure(self) -> None:
        def pin(name: str, index: int):
            return runtime_target._FilePin(
                path=ROOT / name,
                relative=name,
                size=index + 1,
                sha256=f"{index + 1:064x}",
                snapshot=(index + 1, index + 2),
            )

        binding_pins = {
            (branch, resource): pin(
                f"binding-{branch}-{resource}.json", index
            )
            for index, (branch, resource) in enumerate(
                (branch, resource)
                for branch in runtime_target.BRANCHES
                for resource in runtime_target.RESOURCES
            )
        }
        probe_pins = {
            resource: pin(f"probe-{resource}.json", 8 + index)
            for index, resource in enumerate(runtime_target.RESOURCES)
        }
        provenance_pins = (
            pin("binding-index.json", 10),
            pin("accepted-parity-assessment.json", 11),
            pin("accepted-parity-receipt.json", 12),
        )
        adapter_pins = (*binding_pins.values(), *probe_pins.values())
        inventory = SimpleNamespace(
            analytics_binding_pins=binding_pins,
            runtime_probe_pins=probe_pins,
            support_pins=(*provenance_pins[:1], *adapter_pins, *provenance_pins[1:]),
        )

        expected_adapter_paths = {item.relative for item in adapter_pins}
        for system in ("deepstream", "savant"):
            descriptors = runtime_target._support_descriptors(
                inventory, system=system
            )
            self.assertEqual(len(descriptors), 10)
            self.assertEqual(
                {item["path"] for item in descriptors}, expected_adapter_paths
            )
        for system in ("openvino_gva", "gstreamer_custom"):
            descriptors = runtime_target._support_descriptors(
                inventory, system=system
            )
            self.assertEqual(len(descriptors), 13)
            self.assertEqual(
                {item["path"] for item in descriptors},
                {item.relative for item in inventory.support_pins},
            )

    def test_bundle_value_is_exact_nonauthorizing_and_self_hashed(self) -> None:
        cell = qualification_pilot_cells_v2()[0]
        value = _bundle_value_v2(
            cell,
            runtime_inputs(cell),
            hardware_resource_collector=HARDWARE_COLLECTOR_DESCRIPTOR,
        )
        self.assertEqual(value["artifact_kind"], RUNTIME_BUNDLE_KIND)
        self.assertEqual(value["scope"], RUNTIME_BUNDLE_SCOPE)
        self.assertFalse(value["accepted"])
        self.assertFalse(value["publication_ready"])
        self.assertFalse(value["authorization_eligible"])
        self.assertEqual(
            value["hardware_resource_collector"],
            HARDWARE_COLLECTOR_DESCRIPTOR,
        )
        contract = value["runtime_inputs"]["dataset"][
            RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]
        ]
        self.assertIs(contract["defer_full_resource_acceptance"], True)
        unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
        self.assertEqual(
            value["bundle_sha256"],
            hashlib.sha256(canonical(unsigned).rstrip(b"\n")).hexdigest(),
        )

    def test_tree_writer_materializes_exact_32_and_never_overwrites(self) -> None:
        cells = qualification_pilot_cells_v2()
        with tempfile.TemporaryDirectory() as temporary:
            tree = Path(temporary) / "qualification-runtime-inputs-v2"
            tree.mkdir()
            descriptors = _write_bundle_tree_v2(
                tree,
                cells=cells,
                runtime_factory=runtime_inputs,
                hardware_resource_collector=HARDWARE_COLLECTOR_DESCRIPTOR,
            )
            self.assertEqual(len(descriptors), 32)
            files = sorted(tree.glob("*/*/*/*.json"))
            self.assertEqual(len(files), 32)
            self.assertEqual(len({row["arm_id"] for row in descriptors}), 32)
            self.assertEqual(len({row["sha256"] for row in descriptors}), 32)
            for path in files:
                value = json.loads(path.read_bytes())
                self.assertEqual(path.read_bytes(), canonical(value))
            with self.assertRaises(QualificationRuntimeInputMaterializationV2Error):
                _write_bundle_tree_v2(
                    tree,
                    cells=cells,
                    runtime_factory=runtime_inputs,
                    hardware_resource_collector=HARDWARE_COLLECTOR_DESCRIPTOR,
                )

    def test_bundle_rejects_configurable_defer_acceptance(self) -> None:
        cell = qualification_pilot_cells_v2()[0]
        value = runtime_inputs(cell)
        value["dataset"][RUNTIME_INPUT_KEY_BY_SYSTEM[cell.system]][
            "defer_full_resource_acceptance"
        ] = False
        with self.assertRaises(QualificationRuntimeInputMaterializationV2Error):
            _bundle_value_v2(
                cell,
                value,
                hardware_resource_collector=HARDWARE_COLLECTOR_DESCRIPTOR,
            )

    def test_cleanup_refuses_hardlinked_or_dangling_staging_entries(self) -> None:
        for attack in ("hardlink", "dangling"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as temporary:
                parent = Path(temporary).resolve()
                staging = parent / ".qualification-runtime-inputs-v2.attack"
                staging.mkdir()
                if attack == "hardlink":
                    source = staging / "source"
                    source.write_text("owned\n", encoding="ascii")
                    (staging / "alias").hardlink_to(source)
                else:
                    (staging / "dangling").symlink_to(staging / "missing")
                with self.assertRaises(
                    QualificationRuntimeInputMaterializationV2Error
                ):
                    runtime_target._safe_remove_staging(
                        staging,
                        parent=parent,
                        expected_staging_identity=runtime_target._directory_identity(staging),
                        expected_parent_identity=runtime_target._directory_identity(parent),
                    )
                self.assertTrue(os.path.lexists(staging))

    def test_system_contracts_match_all_four_lower_runtime_field_sets(self) -> None:
        inventory = SimpleNamespace(
            nvidia={
                "uuid": "GPU-00bb784b-60f3-8bf6-bbd3-5a0c09805266",
                "name": "NVIDIA GeForce RTX 3060",
                "driver_version": "610.47",
            },
            preprocessing_sha256="a" * 64,
        )
        modules = {
            "deepstream": deepstream_runtime,
            "savant": savant_runtime,
            "openvino_gva": openvino_runtime,
            "gstreamer_custom": gstreamer_runtime,
        }
        sockets = {
            "path": "/tmp/socket",
            "device": 1,
            "inode": 2,
            "owner_uid": 3,
            "owner_gid": 4,
        }
        descriptor = {
            "path": "input.bin",
            "container_path": "/workspace/project/input.bin",
            "size_bytes": 1,
            "sha256": "b" * 64,
        }
        cells = {cell.system: cell for cell in qualification_pilot_cells_v2()}
        for system, module in modules.items():
            files = {role: dict(descriptor) for role in module.FILE_ROLES}
            contract = _runtime_contract_for_cell(
                cells[system],
                inventory=inventory,
                files=files,
                source_files=[descriptor],
                model_files=[descriptor],
                support_files=[descriptor],
                image={"image_id": "sha256:" + "c" * 64},
                engine_socket=sockets,
                analytics_socket=sockets,
                scratch_root=Path("/tmp"),
                probe=(
                    {"sha256": "d" * 64, "value": {"available_devices": [{"device_id": "CPU"}]}}
                    if system in {"openvino_gva", "gstreamer_custom"}
                    else None
                ),
                capability_hashes={"cpu": "e" * 64, "gpu": "f" * 64},
                runtime_files=[descriptor],
            )
            self.assertEqual(set(contract), module.RUNTIME_FIELDS)
            self.assertEqual(set(contract["files"]), module.FILE_ROLES)
            self.assertIs(contract["defer_full_resource_acceptance"], True)
            self.assertEqual(
                contract["evidence_mapping"],
                {name: name for name in CHILD_EVIDENCE_FILES},
            )


if __name__ == "__main__":
    unittest.main()
