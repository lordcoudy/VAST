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

from backend_publication_dispatch import (  # noqa: E402
    BackendPublicationDispatchError,
    INPUT_PROTOCOL_IDENTITY_SHA256,
    OUTPUT_PROTOCOL_IDENTITY_SHA256,
    build_backend_publication_command,
    resolve_backend_publication_dispatch,
    runtime_binding_identity,
    validate_backend_publication_launcher,
)
from backend_runtime_grant import SYSTEMS, backend_runtime_grant_from_identity_artifacts  # noqa: E402
from test_backend_runtime_grant import v2_identity  # noqa: E402

SCENARIO_BY_TOPOLOGY = {
    "independent_processes": "checkpoint_independent_processes_baseline",
    "shared_video_dag": "checkpoint_video_dag_shared",
}


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    ).hexdigest()


class BackendPublicationDispatchTests(unittest.TestCase):
    def grant(self) -> dict[str, object]:
        return backend_runtime_grant_from_identity_artifacts(v2_identity())

    def test_protocol_v2_identity_preserves_closed_launcher_argv(self) -> None:
        self.assertEqual(
            INPUT_PROTOCOL_IDENTITY_SHA256,
            hashlib.sha256(
                b"vast-full-publication-arm-contract-json-v2"
            ).hexdigest(),
        )
        self.assertEqual(
            OUTPUT_PROTOCOL_IDENTITY_SHA256,
            hashlib.sha256(
                b"vast-full-publication-arm-output-receipt-json-v2"
            ).hexdigest(),
        )
        invocation = self.grant()["systems"]["deepstream"][
            "launcher_invocation"
        ]
        self.assertEqual(
            invocation["argv_template"],
            [
                "{python_executable}", "{launcher_path}", "--arm-contract",
                "{arm_contract_path}", "--output-dir", "{output_dir}",
            ],
        )
        self.assertEqual(invocation["schema_version"], 2)

    def test_exact_560_qualified_coordinates_resolve_once(self) -> None:
        grant = self.grant()
        observed = set()
        for system in SYSTEMS:
            for cell in grant["systems"][system]["qualified_cells"]:
                resolved = resolve_backend_publication_dispatch(
                    grant,
                    system=system,
                    scenario=SCENARIO_BY_TOPOLOGY[cell["topology_kind"]],
                    codec=cell["codec"],
                    policy=cell["policy"],
                    deadline_ms=float(cell["deadline_ms"]),
                )
                observed.add(tuple(resolved[key] for key in (
                    "system", "codec", "topology_kind", "policy", "deadline_ms"
                )))
                self.assertEqual(resolved["cell_identity_sha256"], cell["cell_identity_sha256"])
                self.assertEqual(resolved["schema_version"], 2)
                self.assertEqual(resolved["launcher_invocation"]["schema_version"], 2)
                self.assertEqual(
                    resolved["launcher_invocation_sha256"],
                    resolved["launcher_invocation"]["invocation_sha256"],
                )
        self.assertEqual(len(observed), 560)

    def test_missing_grant_wrong_cell_and_invocation_drift_fail_closed(self) -> None:
        with self.assertRaises(BackendPublicationDispatchError):
            resolve_backend_publication_dispatch(
                None, system="deepstream", scenario="checkpoint_video_dag_shared",
                codec="h264", policy="cpu_only", deadline_ms=50,
            )
        grant = self.grant()
        with self.assertRaisesRegex(BackendPublicationDispatchError, "coordinate"):
            resolve_backend_publication_dispatch(
                grant, system="deepstream", scenario="checkpoint_video_dag_shared",
                codec="h264", policy="cpu_only", deadline_ms=51,
            )
        drifted = copy.deepcopy(grant)
        invocation = drifted["systems"]["deepstream"]["launcher_invocation"]
        invocation["argv_template"][-1] = "{unqualified_path}"
        invocation.pop("invocation_sha256")
        invocation["invocation_sha256"] = canonical_sha(invocation)
        drifted.pop("grant_sha256")
        drifted["grant_sha256"] = canonical_sha(drifted)
        with self.assertRaises(BackendPublicationDispatchError):
            resolve_backend_publication_dispatch(
                drifted, system="deepstream", scenario="checkpoint_video_dag_shared",
                codec="h264", policy="cpu_only", deadline_ms=50,
            )

    def test_physical_launcher_and_no_shell_command_are_exact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            launcher = root / "runtime/deepstream/publication_launcher.py"
            launcher.parent.mkdir(parents=True)
            launcher.write_bytes(b"print('synthetic dedicated launcher')\n")
            identity = v2_identity()
            descriptor = {
                "path": launcher.relative_to(root).as_posix(),
                "size_bytes": launcher.stat().st_size,
                "sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
            }
            old_descriptor = identity["bindings"]["backend_runtime_qualification"][
                "systems"
            ]["deepstream"]["launcher"]
            identity["bindings"]["backend_runtime_qualification"]["systems"][
                "deepstream"
            ]["launcher"] = descriptor
            binding = identity["bindings"]["backend_runtime_qualification"][
                "systems"
            ]["deepstream"]
            binding["runtime_binding_identity_sha256"] = runtime_binding_identity(
                system="deepstream",
                launcher=descriptor,
                launcher_invocation=binding["launcher_invocation"],
                upstream_identities=identity["bindings"][
                    "backend_runtime_qualification"
                ]["upstream_identities"],
            )
            identity["files"] = [
                descriptor if item == old_descriptor else item
                for item in identity["files"]
            ]
            identity["files_sha256"] = canonical_sha(identity["files"])
            identity.pop("binding_sha256")
            identity["binding_sha256"] = canonical_sha(identity)
            grant = backend_runtime_grant_from_identity_artifacts(identity)
            resolved = resolve_backend_publication_dispatch(
                grant, system="deepstream", scenario="checkpoint_video_dag_shared",
                codec="h264", policy="cpu_only", deadline_ms=50,
            )
            self.assertEqual(
                validate_backend_publication_launcher(
                    resolved, project_root=root, identity_artifacts=identity
                ),
                launcher.resolve(),
            )
            command = build_backend_publication_command(
                resolved, project_root=root, identity_artifacts=identity,
                python_executable=Path(sys.executable),
                arm_contract_path=root / "attempt/arm-contract.json",
                output_dir=root / "attempt/output",
            )
            self.assertEqual(command[:2], [str(Path(sys.executable).resolve()), str(launcher.resolve())])
            self.assertNotIn("run_system_template.sh", " ".join(command))
            relabelled = copy.deepcopy(resolved)
            relabelled["policy"] = "gpu_only"
            relabelled.pop("resolution_sha256")
            relabelled["resolution_sha256"] = canonical_sha(relabelled)
            with self.assertRaisesRegex(
                BackendPublicationDispatchError, "differs from the exact grant cell"
            ):
                validate_backend_publication_launcher(
                    relabelled, project_root=root, identity_artifacts=identity
                )
            launcher.write_bytes(b"drift\n")
            with self.assertRaisesRegex(BackendPublicationDispatchError, "drift"):
                validate_backend_publication_launcher(
                    resolved, project_root=root, identity_artifacts=identity
                )


if __name__ == "__main__":
    unittest.main()
