from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import benchmark_contract  # noqa: E402
import kpp_legacy_iss_v2_manifest as gate  # noqa: E402
import prepare_benchmark_dataset as prepare  # noqa: E402
from benchmark_contract import ContractError, load_dataset  # noqa: E402
from prepare_benchmark_dataset import DatasetPrepError  # noqa: E402


DATASET_NAMES = (
    "kpp_legacy_iss_v2_avi",
    "kpp_legacy_iss_v2_h264",
    "kpp_legacy_iss_v2_h265",
)
DATASET_ROOT = "data/videos/kpp/kpp_legacy_iss_v2"
RECEIPT_PATH = f"{DATASET_ROOT}/kpp_iss_v2_materialization_receipt.json"
CLAIMS = {
    "source_receipts_externally_pinned": True,
    "authoritative_receipt_graph_validated": True,
    "media_sources_derived_from_validated_receipts": True,
    "source_and_installed_bytes_stably_rehashed": True,
    "physical_artifact_bytes_assessed": True,
    "exact_output_tree_validated": True,
    "output_set_directory_published_atomically": True,
    (
        "windows_project_root_data_videos_kpp_and_working_directory_"
        "handle_custody_validated"
    ): True,
    "publishable": False,
    "publication_authorized": False,
}
MEDIA_PATHS = {
    ("avi", "underbody"): f"{DATASET_ROOT}/avi/iss_v2_underbody.avi",
    ("avi", "front_gate"): f"{DATASET_ROOT}/avi/iss_v2_front_gate.avi",
    ("h264", "underbody"): f"{DATASET_ROOT}/h264/iss_v2_underbody.mp4",
    ("h264", "front_gate"): f"{DATASET_ROOT}/h264/iss_v2_front_gate.mp4",
    ("h265", "underbody"): f"{DATASET_ROOT}/h265/iss_v2_underbody.mp4",
    ("h265", "front_gate"): f"{DATASET_ROOT}/h265/iss_v2_front_gate.mp4",
}
RECEIPT_ARTIFACT_PATHS = {
    "metadata": f"{DATASET_ROOT}/metadata/iss_v2_underbody_metadata.json",
    "extraction": f"{DATASET_ROOT}/receipts/kpp_iss_v2_extraction_receipt.json",
    "transcode": f"{DATASET_ROOT}/receipts/kpp_iss_v2_transcode_receipt.json",
}
REAL_ENTRY_CANONICAL_SHA256 = {
    "kpp_legacy_iss_v2_avi": (
        "3d8103f9889d4fe866da39f5e2e7977146712d393605bd51f40d427c3c0e2927"
    ),
    "kpp_legacy_iss_v2_h264": (
        "1c825d900d86bc0e9a569965ee9ead42f83b093b476861ae0baa77d1543b1bb5"
    ),
    "kpp_legacy_iss_v2_h265": (
        "5d09936fa103b61caff4b7b9b14e3cf013cad0202d2c809fc47b6093bff60037"
    ),
}
V1_IDENTITIES = {
    "kpp_real_avi": (
        "940cf02d9f7fd7b0179fd4eaf858fb7f095bc860df1dfb72681a4f86ca69379f"
    ),
    "kpp_real_h264": (
        "1d3b7a0c7e4b9b0a51c901371763e6f52019d69f257fd78a6c74664f4e233951"
    ),
    "kpp_real_h265": (
        "0f166e745e36ae979a3cb89fb3214636422a4a55f5255664d9b5089af7ec59db"
    ),
}


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _canonical(value: object) -> bytes:
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


def _self_hash(receipt: dict[str, object]) -> str:
    unsigned = dict(receipt)
    unsigned.pop("materialization_receipt_sha256", None)
    return hashlib.sha256(gate.MATERIALIZATION_RECEIPT_DOMAIN + _canonical(unsigned)).hexdigest()


class Fixture:
    def __init__(self, root: Path, dataset_name: str = DATASET_NAMES[1]) -> None:
        root = root.resolve()
        self.root = root
        self.dataset_name = dataset_name
        self.payloads = {
            path: f"fixture:{path}\n".encode("ascii")
            for path in (*MEDIA_PATHS.values(), *RECEIPT_ARTIFACT_PATHS.values())
        }
        for relative, payload in self.payloads.items():
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        self.entries = {
            name: self._entry(name)
            for name in DATASET_NAMES
        }
        self.receipt = self._receipt()
        self._write_receipt()
        self.manifest = root / "configs" / "datasets.yaml"
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self._write_manifest()

    def _entry(self, name: str) -> dict[str, object]:
        variant = name.rsplit("_", 1)[-1]
        streams = [
            {
                "stream_id": index,
                "path": MEDIA_PATHS[(variant, role)],
                "sha256": _sha256(self.payloads[MEDIA_PATHS[(variant, role)]]),
            }
            for index, role in enumerate(("underbody", "front_gate"))
        ]
        entry: dict[str, object] = {
            "dataset_contract_version": 2,
            "generation_id": "kpp_legacy_iss_v2",
            "status": "physically_assessed_candidate",
            "kind": "real_avi" if variant == "avi" else "real_codec_transcode",
            "publishable": False,
            "annotations": {
                "path": RECEIPT_ARTIFACT_PATHS["metadata"],
                "sha256": _sha256(self.payloads[RECEIPT_ARTIFACT_PATHS["metadata"]]),
            },
            "provenance": {
                "schema_version": 1,
                "generation_id": "kpp_legacy_iss_v2",
                "physical_artifact_bytes_assessed": True,
                "publication_authorized": False,
                "media_artifacts": [
                    {
                        "role": role,
                        "path": MEDIA_PATHS[(variant, role)],
                        "sha256": _sha256(self.payloads[MEDIA_PATHS[(variant, role)]]),
                        "size_bytes": len(self.payloads[MEDIA_PATHS[(variant, role)]]),
                    }
                    for role in ("underbody", "front_gate")
                ],
            },
            "streams": streams,
        }
        if variant != "avi":
            entry.update(
                {
                    "source_dataset": DATASET_NAMES[0],
                    "codec_variant": variant,
                    "transcode": {
                        "source_paths": [
                            MEDIA_PATHS[("avi", "underbody")],
                            MEDIA_PATHS[("avi", "front_gate")],
                        ],
                        "recipes": [{"role": "underbody"}, {"role": "front_gate"}],
                    },
                }
            )
        return entry

    def _receipt(self) -> dict[str, object]:
        installed: list[dict[str, object]] = []
        for (variant, role), path in MEDIA_PATHS.items():
            payload = self.payloads[path]
            installed.append(
                {
                    "artifact_kind": "media",
                    "codec_variant": variant,
                    "role": role,
                    "source_path": f"staging/{variant}/{role}",
                    "installed_path": path,
                    "size_bytes": len(payload),
                    "sha256": _sha256(payload),
                }
            )
        for role in ("metadata", "extraction", "transcode"):
            path = RECEIPT_ARTIFACT_PATHS[role]
            payload = self.payloads[path]
            installed.append(
                {
                    "artifact_kind": "receipt",
                    "receipt_role": role,
                    "source_path": f"staging/{role}.json",
                    "installed_path": path,
                    "size_bytes": len(payload),
                    "sha256": _sha256(payload),
                }
            )
        receipt: dict[str, object] = {
            "schema_version": 1,
            "artifact_kind": "vast_kpp_legacy_iss_v2_materialization_receipt",
            "generation_id": "kpp_legacy_iss_v2",
            "status": "physically_assessed_candidate",
            "dataset_root": DATASET_ROOT,
            "publishable": False,
            "publication_authorized": False,
            "source_receipt_external_pins": {
                role: next(
                    str(item["sha256"])
                    for item in installed
                    if item.get("receipt_role") == role
                )
                for role in ("extraction", "transcode", "metadata")
            },
            "installed_artifacts": installed,
            "dataset_entries": copy.deepcopy(self.entries),
            "claims": copy.deepcopy(CLAIMS),
        }
        receipt["materialization_receipt_sha256"] = _self_hash(receipt)
        return receipt

    def _write_receipt(self, *, canonical: bool = True) -> None:
        payload = _canonical(self.receipt)
        if not canonical:
            payload += b" \n"
        target = self.root / RECEIPT_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        self.receipt_payload = payload

    def reseal(self, *, canonical: bool = True) -> None:
        self.receipt["materialization_receipt_sha256"] = _self_hash(self.receipt)
        self._write_receipt(canonical=canonical)
        self._write_manifest()

    def _write_manifest(self) -> None:
        entry = copy.deepcopy(self.entries[self.dataset_name])
        receipt_payload = getattr(self, "receipt_payload", _canonical(self.receipt))
        entry["preparation"] = {
            "mode": "check_only_materialized_v1",
            "materialization_receipt": {
                "path": RECEIPT_PATH,
                "size_bytes": len(receipt_payload),
                "sha256": _sha256(receipt_payload),
                "materialization_receipt_sha256": self.receipt[
                    "materialization_receipt_sha256"
                ],
            },
        }
        self.manifest.write_text(
            yaml.safe_dump({"schema_version": 1, "datasets": {self.dataset_name: entry}}),
            encoding="utf-8",
        )

    @contextmanager
    def pinned(self):
        descriptor = yaml.safe_load(self.manifest.read_text(encoding="utf-8"))[
            "datasets"
        ][self.dataset_name]["preparation"]["materialization_receipt"]
        entry_sha256 = {
            name: _sha256(_canonical(entry))
            for name, entry in self.entries.items()
        }
        with (
            mock.patch.multiple(
                gate,
                EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES=descriptor["size_bytes"],
                EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256=descriptor["sha256"],
                EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256=descriptor[
                    "materialization_receipt_sha256"
                ],
            ),
            mock.patch.object(
                gate,
                "_EXPECTED_DATASET_ENTRY_CANONICAL_SHA256",
                entry_sha256,
            ),
        ):
            yield


class KppLegacyIssV2ManifestIntegrationTests(unittest.TestCase):
    def test_repository_manifest_registers_exact_real_v2_without_v1_drift(self) -> None:
        manifest_path = ROOT / "configs" / "datasets.yaml"
        config = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        datasets = config["datasets"]
        self.assertTrue(set(DATASET_NAMES).issubset(datasets))

        expected_preparation = {
            "mode": "check_only_materialized_v1",
            "materialization_receipt": {
                "path": RECEIPT_PATH,
                "size_bytes": 28131,
                "sha256": (
                    "dd0d2aa38da1281a750806858b555b994a9dcf3c9bcd35e8379dbc9d339f2b33"
                ),
                "materialization_receipt_sha256": (
                    "56e09fd82ab83d4f3e0a711d93658a1cfc69f3bee9fd381df41713ac5b42bda4"
                ),
            },
        }
        real_entries = None
        try:
            real_receipt = json.loads((ROOT / RECEIPT_PATH).read_text("ascii"))
            real_entries = real_receipt["dataset_entries"]
        except (FileNotFoundError, PermissionError):
            pass

        for dataset_name in DATASET_NAMES:
            entry = copy.deepcopy(datasets[dataset_name])
            self.assertEqual(entry.pop("preparation"), expected_preparation)
            self.assertEqual(
                _sha256(_canonical(entry)),
                REAL_ENTRY_CANONICAL_SHA256[dataset_name],
            )
            if real_entries is not None:
                self.assertEqual(entry, real_entries[dataset_name])

        with tempfile.TemporaryDirectory() as raw:
            empty_root = Path(raw).resolve()
            for dataset_name in DATASET_NAMES:
                with self.assertRaisesRegex(ContractError, "not publishable"):
                    load_dataset(
                        manifest_path,
                        dataset_name,
                        mode="benchmark",
                        project_root=empty_root,
                        require_files=False,
                    )
            for dataset_name, expected_identity in V1_IDENTITIES.items():
                dataset = load_dataset(
                    manifest_path,
                    dataset_name,
                    mode="benchmark",
                    project_root=empty_root,
                    require_files=False,
                )
                self.assertEqual(
                    dataset["manifest_identity_sha256"], expected_identity
                )

    def test_production_receipt_descriptor_is_frozen(self) -> None:
        self.assertEqual(gate.MATERIALIZATION_RECEIPT_PATH, RECEIPT_PATH)
        self.assertEqual(gate.EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES, 28131)
        self.assertEqual(
            gate.EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256,
            "dd0d2aa38da1281a750806858b555b994a9dcf3c9bcd35e8379dbc9d339f2b33",
        )
        self.assertEqual(
            gate.EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256,
            "56e09fd82ab83d4f3e0a711d93658a1cfc69f3bee9fd381df41713ac5b42bda4",
        )

    def test_smoke_accepts_assessed_nonpublishable_receipt_but_benchmark_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            with fixture.pinned():
                dataset = load_dataset(
                    fixture.manifest,
                    fixture.dataset_name,
                    mode="smoke",
                    project_root=fixture.root,
                    require_files=True,
                )
                self.assertEqual(dataset["status"], "physically_assessed_candidate")
                self.assertFalse(dataset["publishable"])
                with self.assertRaisesRegex(ContractError, "not publishable"):
                    load_dataset(
                        fixture.manifest,
                        fixture.dataset_name,
                        mode="benchmark",
                        project_root=fixture.root,
                        require_files=True,
                    )

    def test_structural_gate_works_without_local_files_and_preserves_v1(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            receipt_target = fixture.root / DATASET_ROOT
            for child in sorted(receipt_target.rglob("*"), reverse=True):
                if child.is_file():
                    child.unlink()
                elif child.is_dir():
                    child.rmdir()
            receipt_target.rmdir()
            with fixture.pinned():
                dataset = load_dataset(
                    fixture.manifest,
                    fixture.dataset_name,
                    mode="smoke",
                    project_root=fixture.root,
                    require_files=False,
                )
            self.assertEqual(dataset["generation_id"], "kpp_legacy_iss_v2")
            self.assertFalse(
                gate.validate_kpp_legacy_iss_v2_manifest_entry(
                    "kpp_real_h264",
                    {"generation_id": "legacy", "streams": [{"path": "legacy.mp4"}]},
                    project_root=fixture.root,
                    require_files=False,
                )
            )

    def test_structural_gate_rejects_unknown_key_and_float_version_without_files(self) -> None:
        for mutation in ("unknown_key", "float_version"):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                fixture = Fixture(Path(raw))
                config = yaml.safe_load(fixture.manifest.read_text(encoding="utf-8"))
                entry = config["datasets"][fixture.dataset_name]
                if mutation == "unknown_key":
                    entry["unreceipted_claim"] = True
                else:
                    entry["dataset_contract_version"] = 2.0
                fixture.manifest.write_text(yaml.safe_dump(config), encoding="utf-8")
                with fixture.pinned(), self.assertRaisesRegex(
                    ContractError, "entry|contract_version"
                ):
                    load_dataset(
                        fixture.manifest,
                        fixture.dataset_name,
                        mode="smoke",
                        project_root=fixture.root,
                        require_files=False,
                    )

    def test_wrong_descriptor_and_receipt_integrity_drift_fail_closed(self) -> None:
        mutations = (
            "missing_preparation",
            "mode",
            "descriptor",
            "canonical",
            "self",
            "claim",
            "root",
            "embedded",
        )
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as raw:
                fixture = Fixture(Path(raw))
                if mutation in {"missing_preparation", "mode", "descriptor"}:
                    config = yaml.safe_load(fixture.manifest.read_text(encoding="utf-8"))
                    entry = config["datasets"][fixture.dataset_name]
                    if mutation == "missing_preparation":
                        entry.pop("preparation")
                    elif mutation == "mode":
                        entry["preparation"]["mode"] = "legacy_ffmpeg"
                    else:
                        entry["preparation"]["materialization_receipt"][
                            "sha256"
                        ] = "f" * 64
                    fixture.manifest.write_text(yaml.safe_dump(config), encoding="utf-8")
                elif mutation == "canonical":
                    fixture._write_receipt(canonical=False)
                    fixture._write_manifest()
                elif mutation == "self":
                    fixture.receipt["materialization_receipt_sha256"] = "f" * 64
                    fixture._write_receipt()
                    fixture._write_manifest()
                elif mutation == "claim":
                    fixture.receipt["claims"]["physical_artifact_bytes_assessed"] = False
                    fixture.reseal()
                elif mutation == "root":
                    fixture.receipt["dataset_root"] = "data/videos/kpp/not-the-fixed-root"
                    fixture.reseal()
                else:
                    fixture.receipt["dataset_entries"][fixture.dataset_name]["status"] = "drifted"
                    fixture.reseal()
                pin_context = (
                    mock.patch.multiple(
                        gate,
                        EXPECTED_MATERIALIZATION_RECEIPT_SIZE_BYTES=len(
                            fixture.receipt_payload
                        ),
                        EXPECTED_MATERIALIZATION_RECEIPT_FILE_SHA256=_sha256(
                            fixture.receipt_payload
                        ),
                        EXPECTED_MATERIALIZATION_RECEIPT_SELF_SHA256=fixture.receipt[
                            "materialization_receipt_sha256"
                        ],
                    )
                    if mutation == "missing_preparation"
                    else fixture.pinned()
                )
                with pin_context, self.assertRaises(ContractError):
                    load_dataset(
                        fixture.manifest,
                        fixture.dataset_name,
                        mode="smoke",
                        project_root=fixture.root,
                        require_files=True,
                    )

    def test_require_files_rehashes_even_an_unselected_codec_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw), DATASET_NAMES[1])
            unselected = fixture.root / MEDIA_PATHS[("h265", "underbody")]
            unselected.write_bytes(b"tampered unselected codec\n")
            with fixture.pinned(), self.assertRaisesRegex(ContractError, "artifact"):
                load_dataset(
                    fixture.manifest,
                    fixture.dataset_name,
                    mode="smoke",
                    project_root=fixture.root,
                    require_files=True,
                )

    def test_require_files_rejects_an_extra_unreceipted_tree_entry(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            extra = fixture.root / DATASET_ROOT / "unreceipted.bin"
            extra.write_bytes(b"not in the exact materialization tree\n")
            with fixture.pinned(), self.assertRaisesRegex(ContractError, "tree"):
                load_dataset(
                    fixture.manifest,
                    fixture.dataset_name,
                    mode="smoke",
                    project_root=fixture.root,
                    require_files=True,
                )

    def test_require_files_rejects_a_project_root_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            parent = Path(raw).resolve()
            fixture = Fixture(parent / "project")
            alias = parent / "project-alias"
            try:
                alias.symlink_to(fixture.root, target_is_directory=True)
            except OSError as exc:
                self.skipTest(f"directory symlink is unavailable: {exc}")
            with fixture.pinned(), self.assertRaisesRegex(
                ContractError, "project_root.*link|reparse"
            ):
                load_dataset(
                    fixture.manifest,
                    fixture.dataset_name,
                    mode="smoke",
                    project_root=alias,
                    require_files=True,
                )

    def test_require_files_rejects_a_hardlinked_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            artifact = fixture.root / MEDIA_PATHS[("h265", "underbody")]
            hardlink = fixture.root / "outside-hardlink.bin"
            try:
                hardlink.hardlink_to(artifact)
            except OSError as exc:
                self.skipTest(f"hardlinks are unavailable: {exc}")
            with fixture.pinned(), self.assertRaisesRegex(
                ContractError, "hardlink|link count"
            ):
                load_dataset(
                    fixture.manifest,
                    fixture.dataset_name,
                    mode="smoke",
                    project_root=fixture.root,
                    require_files=True,
                )

    def test_require_files_rescans_after_first_exact_tree_scan(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            original_scan = gate._validate_exact_tree
            scan_count = 0

            def inject_after_first_scan(
                dataset_root: Path,
            ) -> tuple[int, int, int, int, int, int]:
                nonlocal scan_count
                snapshot = original_scan(dataset_root)
                scan_count += 1
                if scan_count == 1:
                    (dataset_root / "late-unreceipted.bin").write_bytes(b"late\n")
                return snapshot

            with (
                fixture.pinned(),
                mock.patch.object(gate, "_validate_exact_tree", inject_after_first_scan),
                self.assertRaisesRegex(ContractError, "tree"),
            ):
                load_dataset(
                    fixture.manifest,
                    fixture.dataset_name,
                    mode="smoke",
                    project_root=fixture.root,
                    require_files=True,
                )

    def test_load_dataset_rejects_nonexact_mode(self) -> None:
        with tempfile.TemporaryDirectory() as raw, self.assertRaisesRegex(
            ContractError, "mode"
        ):
            load_dataset(
                ROOT / "configs" / "datasets.yaml",
                "kpp_legacy_iss_v2_h264",
                mode="benchmark ",
                project_root=Path(raw).resolve(),
                require_files=False,
            )

    def test_check_only_prepare_skips_legacy_parser_and_ffmpeg_and_rejects_force(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            runner = mock.Mock(side_effect=AssertionError("ffmpeg must not run"))
            with fixture.pinned():
                plans = prepare.build_clip_plans(
                    manifest=fixture.manifest,
                    dataset_name=fixture.dataset_name,
                    project_root=fixture.root,
                    source_root=Path("data/videos"),
                    output_dir=Path("data/benchmark"),
                )
                self.assertEqual(plans, [])
                result = prepare.prepare_dataset(
                    manifest=fixture.manifest,
                    dataset_name=fixture.dataset_name,
                    project_root=fixture.root,
                    source_root=Path("data/videos"),
                    output_dir=Path("data/benchmark"),
                    dry_run=True,
                    runner=runner,
                )
                self.assertEqual(result, [])
                runner.assert_not_called()
                with self.assertRaisesRegex(DatasetPrepError, "--force"):
                    prepare.prepare_dataset(
                        manifest=fixture.manifest,
                        dataset_name=fixture.dataset_name,
                        project_root=fixture.root,
                        source_root=Path("data/videos"),
                        output_dir=Path("data/benchmark"),
                        force=True,
                        runner=runner,
                    )

    def test_check_only_dry_run_still_validates_materialized_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = Fixture(Path(raw))
            (fixture.root / MEDIA_PATHS[("h265", "front_gate")]).write_bytes(b"tamper\n")
            with fixture.pinned(), self.assertRaisesRegex(DatasetPrepError, "artifact"):
                prepare.prepare_dataset(
                    manifest=fixture.manifest,
                    dataset_name=fixture.dataset_name,
                    project_root=fixture.root,
                    source_root=Path("data/videos"),
                    output_dir=Path("data/benchmark"),
                    dry_run=True,
                    runner=mock.Mock(side_effect=AssertionError("ffmpeg must not run")),
                )


if __name__ == "__main__":
    unittest.main()
