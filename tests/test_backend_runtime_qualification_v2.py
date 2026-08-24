from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_runtime_qualification_v2 import (  # noqa: E402
    BackendRuntimeQualificationV2Error,
    BINDING_INDEX_FILENAME,
    SYSTEMS,
    assess_backend_runtime_qualification_v2,
    promote_backend_runtime_qualification_v2,
)
from backend_publication_dispatch import (  # noqa: E402
    launcher_invocation_contract,
    runtime_binding_identity,
)


def canonical_sha(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def write_artifact(root: Path, relative: str, marker: str) -> dict[str, object]:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (marker + "\n").encode("utf-8")
    path.write_bytes(payload)
    return {
        "path": relative,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


class Fixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.upstream = {
            "dataset_manifest_sha256": hashlib.sha256(b"dataset").hexdigest(),
            "policy_contract_sha256": hashlib.sha256(b"policy").hexdigest(),
            "policy_qualification_receipt_sha256": hashlib.sha256(b"policy-receipt").hexdigest(),
            "resource_contract_identity_sha256": hashlib.sha256(b"resource").hexdigest(),
            "resource_qualification_receipt_sha256": hashlib.sha256(b"resource-receipt").hexdigest(),
            "analytics_execution_config_identity_sha256": hashlib.sha256(b"execution").hexdigest(),
            "model_parity_manifest_identity_sha256": hashlib.sha256(b"parity").hexdigest(),
            "model_parity_acceptance_binding_sha256": hashlib.sha256(
                b"parity-acceptance-binding"
            ).hexdigest(),
        }
        self.value = {
            "schema_version": 2,
            "artifact_kind": "vast_backend_runtime_qualification_v2_index",
            "upstream_identities": self.upstream,
            "systems": {
                system: self._system(system)
                for system in SYSTEMS
            },
        }
        self.index_path = root / "qualification/backend_v2_index.json"
        write_json(self.index_path, self.value)

    def _system(self, system: str) -> dict[str, object]:
        launcher = write_artifact(
            self.root,
            f"runtime/{system}/publication_launcher.py",
            f"dedicated publication launcher:{system}",
        )
        cells = []
        ordinal = 0
        for codec in ("h264", "h265"):
            for topology in ("independent_processes", "shared_video_dag"):
                for policy in (
                    "cpu_only",
                    "gpu_only",
                    "static_hybrid",
                    "heft",
                    "deadline_aware_heft",
                    "queue_aware_edf",
                    "adaptive_weights",
                ):
                    for deadline in (16.7, 33.3, 50, 100, 500):
                        cells.append(
                            {
                                "system": system,
                                "codec": codec,
                                "topology_kind": topology,
                                "policy": policy,
                                "deadline_ms": deadline,
                                "raw_evidence": write_artifact(
                                    self.root,
                                    f"accepted/backend/{system}/cells/{ordinal:03d}.json",
                                    f"raw:{system}:{codec}:{topology}:{policy}:{deadline}",
                                ),
                            }
                        )
                        ordinal += 1
        invocation = launcher_invocation_contract()
        return {
            "system": system,
            "runtime_binding_identity_sha256": runtime_binding_identity(
                system=system,
                launcher=launcher,
                launcher_invocation=invocation,
                upstream_identities=self.upstream,
            ),
            "launcher": launcher,
            "launcher_invocation": invocation,
            "launcher_kind": "dedicated_publication_runtime",
            "publication_capable": True,
            "cells": cells,
        }

    def rewrite(self) -> None:
        write_json(self.index_path, self.value)


def raw_validator(
    cell: dict[str, object], context: dict[str, object]
) -> dict[str, object]:
    raw = context["raw_evidence"]
    result = {
        "schema_version": 2,
        "artifact_kind": "vast_backend_runtime_cell_raw_evidence_validation",
        "system": cell["system"],
        "codec": cell["codec"],
        "topology_kind": cell["topology_kind"],
        "policy": cell["policy"],
        "deadline_ms": cell["deadline_ms"],
        "accepted": True,
        "synthetic": False,
        "nonpublication": False,
        "publication_capable": True,
        "runtime_binding_identity_sha256": context[
            "runtime_binding_identity_sha256"
        ],
        "launcher_sha256": context["launcher"]["sha256"],
        "launcher_invocation_sha256": context["launcher_invocation"][
            "invocation_sha256"
        ],
        "raw_evidence_sha256": raw["sha256"],
        "upstream_identities": context["upstream_identities"],
        "validator_identity_sha256": hashlib.sha256(
            b"backend-cell-raw-validator-v2"
        ).hexdigest(),
    }
    result["validation_record_sha256"] = canonical_sha(result)
    return result


class BackendRuntimeQualificationV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.fixture = Fixture(self.root)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def assess(self, validator=raw_validator) -> dict[str, object]:
        return assess_backend_runtime_qualification_v2(
            project_root=self.root,
            index_path=self.fixture.index_path,
            raw_evidence_validator=validator,
        )

    def test_exact_560_raw_evidence_backed_cells_pass(self) -> None:
        result = self.assess()
        self.assertTrue(result["passed"], result["blockers"])
        self.assertEqual(result["coverage"]["runtime_cell_count"], 560)
        for system in SYSTEMS:
            item = result["systems"][system]
            self.assertEqual(len(item["qualified_cells"]), 140)
            self.assertEqual(
                item["qualified_cells_sha256"],
                canonical_sha(item["qualified_cells"]),
            )

    def test_default_validator_always_blocks_declarations(self) -> None:
        result = assess_backend_runtime_qualification_v2(
            project_root=self.root,
            index_path=self.fixture.index_path,
        )
        self.assertFalse(result["passed"])
        self.assertIn(
            "raw backend cell evidence validator is required",
            result["blockers"][0],
        )

    def test_validator_receives_exact_coordinate_and_physical_raw_file(self) -> None:
        seen = []

        def recording(cell: dict, context: dict) -> dict:
            raw_path = context["raw_evidence_path"]
            self.assertTrue(raw_path.is_file())
            seen.append(
                (
                    cell["system"],
                    cell["codec"],
                    cell["topology_kind"],
                    cell["policy"],
                    cell["deadline_ms"],
                    hashlib.sha256(raw_path.read_bytes()).hexdigest(),
                )
            )
            return raw_validator(cell, context)

        result = self.assess(recording)
        self.assertTrue(result["passed"])
        self.assertEqual(len(seen), 560)
        self.assertEqual(len(set(seen)), 560)

    def test_missing_duplicate_relabelled_and_evidence_alias_fail_closed(self) -> None:
        cases = []
        missing = copy.deepcopy(self.fixture.value)
        missing["systems"][SYSTEMS[0]]["cells"].pop()
        cases.append(missing)
        duplicate = copy.deepcopy(self.fixture.value)
        duplicate["systems"][SYSTEMS[0]]["cells"][-1] = copy.deepcopy(
            duplicate["systems"][SYSTEMS[0]]["cells"][0]
        )
        cases.append(duplicate)
        relabelled = copy.deepcopy(self.fixture.value)
        relabelled["systems"][SYSTEMS[0]]["cells"][0]["policy"] = "generic"
        cases.append(relabelled)
        alias = copy.deepcopy(self.fixture.value)
        alias["systems"][SYSTEMS[0]]["cells"][1]["raw_evidence"] = copy.deepcopy(
            alias["systems"][SYSTEMS[0]]["cells"][0]["raw_evidence"]
        )
        cases.append(alias)

        for position, value in enumerate(cases):
            with self.subTest(position=position):
                self.fixture.value = value
                self.fixture.rewrite()
                self.assertFalse(self.assess()["passed"])

    def test_raw_file_tamper_and_hardlink_alias_fail_before_validator(self) -> None:
        first = self.fixture.value["systems"][SYSTEMS[0]]["cells"][0]["raw_evidence"]
        (self.root / first["path"]).write_bytes(b"tampered\n")
        calls = []

        def recording(cell: dict, context: dict) -> dict:
            calls.append(cell)
            return raw_validator(cell, context)

        self.assertFalse(self.assess(recording)["passed"])
        self.assertEqual(calls, [])

        self.fixture = Fixture(self.root)
        first = self.fixture.value["systems"][SYSTEMS[0]]["cells"][0]["raw_evidence"]
        second = self.fixture.value["systems"][SYSTEMS[0]]["cells"][1]["raw_evidence"]
        second_path = self.root / second["path"]
        second_path.unlink()
        try:
            os.link(self.root / first["path"], second_path)
        except OSError:
            self.skipTest("hardlinks unavailable")
        second["size_bytes"] = first["size_bytes"]
        second["sha256"] = first["sha256"]
        self.fixture.rewrite()
        self.assertFalse(self.assess()["passed"])

    def test_validator_relabel_hash_and_upstream_drift_fail_closed(self) -> None:
        mutations = (
            ("policy", "generic"),
            ("raw_evidence_sha256", "f" * 64),
            ("launcher_sha256", "e" * 64),
            ("launcher_invocation_sha256", "c" * 64),
        )
        for field, value in mutations:
            def invalid(cell: dict, context: dict, *, _field=field, _value=value) -> dict:
                result = raw_validator(cell, context)
                result[_field] = _value
                result["validation_record_sha256"] = canonical_sha(
                    {key: item for key, item in result.items() if key != "validation_record_sha256"}
                )
                return result

            with self.subTest(field=field):
                self.assertFalse(self.assess(invalid)["passed"])

        def upstream(cell: dict, context: dict) -> dict:
            result = raw_validator(cell, context)
            result["upstream_identities"] = dict(result["upstream_identities"])
            result["upstream_identities"][
                "model_parity_acceptance_binding_sha256"
            ] = "d" * 64
            result["validation_record_sha256"] = canonical_sha(
                {key: item for key, item in result.items() if key != "validation_record_sha256"}
            )
            return result

        self.assertFalse(self.assess(upstream)["passed"])

    def test_engineering_or_nonpublication_launcher_never_qualifies(self) -> None:
        for field, value in (
            ("launcher_kind", "engineering_probe"),
            ("publication_capable", False),
        ):
            self.fixture = Fixture(self.root)
            self.fixture.value["systems"][SYSTEMS[0]][field] = value
            self.fixture.rewrite()
            with self.subTest(field=field):
                self.assertFalse(self.assess()["passed"])

    def test_launcher_invocation_drift_never_qualifies(self) -> None:
        invocation = self.fixture.value["systems"][SYSTEMS[0]][
            "launcher_invocation"
        ]
        invocation["argv_template"][-1] = "{arbitrary_path}"
        invocation.pop("invocation_sha256")
        invocation["invocation_sha256"] = canonical_sha(invocation)
        self.fixture.rewrite()
        self.assertFalse(self.assess()["passed"])

    def test_promotion_emits_v2_receipts_and_commits_binding_index_last(self) -> None:
        output = self.root / "accepted/backend_v2"
        result = promote_backend_runtime_qualification_v2(
            project_root=self.root,
            index_path=self.fixture.index_path,
            output_dir=output,
            raw_evidence_validator=raw_validator,
        )
        self.assertTrue(result["passed"])
        binding = json.loads((output / BINDING_INDEX_FILENAME).read_text())
        self.assertEqual(binding["schema_version"], 2)
        self.assertEqual(binding["coverage"]["runtime_cell_count"], 560)
        self.assertEqual(
            binding["upstream_identities"][
                "model_parity_acceptance_binding_sha256"
            ],
            self.fixture.upstream["model_parity_acceptance_binding_sha256"],
        )
        for system in SYSTEMS:
            receipt = json.loads(
                (output / f"checkpoint_{system}_backend_runtime_qualification_receipt.json").read_text()
            )
            self.assertEqual(receipt["schema_version"], 2)
            self.assertEqual(len(receipt["qualified_cells"]), 140)
            self.assertEqual(
                receipt["qualified_cells_sha256"],
                canonical_sha(receipt["qualified_cells"]),
            )
            self.assertTrue(receipt["publication_capable"])
            self.assertEqual(
                receipt["upstream_identities"][
                    "model_parity_acceptance_binding_sha256"
                ],
                self.fixture.upstream["model_parity_acceptance_binding_sha256"],
            )
        repeated = promote_backend_runtime_qualification_v2(
            project_root=self.root,
            index_path=self.fixture.index_path,
            output_dir=output,
            raw_evidence_validator=raw_validator,
        )
        self.assertEqual(result["binding_index"], repeated["binding_index"])


if __name__ == "__main__":
    unittest.main()
