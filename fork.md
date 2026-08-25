# Проверить и запустить бенчмарк

<details><summary>75 previous messages</summary>

> <details><summary>Ran 17 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\checkpoint_runtime_plan.py
> @@
> -        int(topology.get("contract_version", 0) or 0) == 1,
> -        f"{scenario_name}: topology contract version 1 is required",
> +        int(topology.get("contract_version", 0) or 0) == 2,
> +        f"{scenario_name}: topology contract version 2 is required",
> @@
> -        "topology_contract_version": 1,
> +        "topology_contract_version": 2,
> *** Update File: E:\STUDY\VAST\scripts\benchmark_adapters.py
> @@
> -        if int(topology.get("contract_version", 0) or 0) != 1:
> -            raise ContractError(f"scenario '{scenario_name}' must declare topology contract version 1")
> +        if int(topology.get("contract_version", 0) or 0) != 2:
> +            raise ContractError(f"scenario '{scenario_name}' must declare topology contract version 2")
> @@
> -                "before topology contract v1 can be enabled"
> +                "before topology contract v2 can be enabled"
> @@
> -            "strict_native_schema_v2_topology_v1"
> -            if int(topology.get("contract_version", 0) or 0) == 1
> +            "strict_native_schema_v2_topology_v2"
> +            if int(topology.get("contract_version", 0) or 0) == 2
> *** Update File: E:\STUDY\VAST\tests\test_scenario_planning.py
> @@
> -        self.assertEqual(plan.topology_contract_version, 1)
> +        self.assertEqual(plan.topology_contract_version, 2)
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `Get-Content -LiteralPath 'configs/experiments.yaml' | Select-Object -Skip 405 -First 245`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\configs\experiments.yaml
> @@
> -      contract_version: 1
> +      contract_version: 2
> @@
>      - plate_number
> +    - postprocess_plate_number
>      - decode_vehicle_type
>      - preprocess_vehicle_type
>      - vehicle_type
> +    - postprocess_vehicle_type
>      - decode_damage
>      - preprocess_damage
>      - damage
> +    - postprocess_damage
>      - decode_foreign_object
>      - preprocess_foreign_object
>      - foreign_object
> +    - postprocess_foreign_object
> @@
>          plate_number: local
> +        postprocess_plate_number: local
> @@
>          vehicle_type: local
> +        postprocess_vehicle_type: local
> @@
>          damage: local
> +        postprocess_damage: local
> @@
>          foreign_object: local
> +        postprocess_foreign_object: local
> @@
> -      contract_version: 1
> +      contract_version: 2
> @@
>      - plate_number
> +    - postprocess_plate_number
>      - vehicle_type
> +    - postprocess_vehicle_type
>      - damage
> +    - postprocess_damage
>      - foreign_object
> +    - postprocess_foreign_object
> @@
>          plate_number: local
> +        postprocess_plate_number: local
>          vehicle_type: local
> +        postprocess_vehicle_type: local
>          damage: local
> +        postprocess_damage: local
>          foreign_object: local
> +        postprocess_foreign_object: local
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `Get-Content -LiteralPath 'configs/experiments.yaml' | Select-Object -Skip 405 -First 190`
> - Ran `rg -n -B2 -A2 "contract_version: 2" configs/experiments.yaml`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\configs\experiments.yaml
> @@
>    primary_architecture_contrast:
> @@
>      analytics_queue:
> -      contract_version: 2
> +      contract_version: 1
> @@
>    checkpoint_independent_processes_baseline:
> @@
>      topology:
> -      contract_version: 1
> +      contract_version: 2
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `rg -n -B2 -A2 "contract_version: 2" configs/experiments.yaml`
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST env PYTHONDONTWRITEBYTECODE=1 /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -m unittest tests.test_scenario_planning tests.test_checkpoint_runtime tests.test_benchmark_adapters`
> - Ran `Get-Content -LiteralPath 'tests/test_scenario_planning.py' -TotalCount 80; rg -n "topology_v1|SHARED_PROOF_PIPELINE|INDEPENDENT_PROOF_PIPELINE" tests/test_scenario_planning.py`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_scenario_planning.py
> @@
>      "preprocess",
>      "plate_number",
> +    "postprocess_plate_number",
>      "vehicle_type",
> +    "postprocess_vehicle_type",
>      "damage",
> +    "postprocess_damage",
>      "foreign_object",
> +    "postprocess_foreign_object",
> @@
>      "preprocess_plate_number",
>      "plate_number",
> +    "postprocess_plate_number",
> @@
>      "preprocess_vehicle_type",
>      "vehicle_type",
> +    "postprocess_vehicle_type",
> @@
>      "preprocess_damage",
>      "damage",
> +    "postprocess_damage",
> @@
>      "preprocess_foreign_object",
>      "foreign_object",
> +    "postprocess_foreign_object",
> @@
> -                self.assertEqual(plan.contract, "strict_native_schema_v2_topology_v1")
> +                self.assertEqual(plan.contract, "strict_native_schema_v2_topology_v2")
> @@
> -        self.assertEqual(plan.contract, "strict_native_schema_v2_topology_v1")
> +        self.assertEqual(plan.contract, "strict_native_schema_v2_topology_v2")
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `Get-Content -LiteralPath 'tests/test_scenario_planning.py' | Select-Object -Skip 52 -First 60`
> - Ran `rg -n -A155 -B20 "stage_contracts_|emit.*stage.*contract|postprocess" deploy/native_gst_probe/vast_native_gst_probe.cpp scripts/checkpoint_*runtime*.py | Select-Object -First 360`
> - Ran `Get-Content -LiteralPath 'deploy/native_gst_probe/vast_native_gst_probe.cpp' | Select-Object -Skip 480 -First 335`
> - Ran `rg -n "write_checkpoint_.*contract|written_checkpoint_stage_contracts_" deploy/native_gst_probe/vast_native_gst_probe.cpp`
> - Ran `rg -n "stage_contracts|semantic_contract|base_stage.*analytics|postprocess" scripts/checkpoint_gstreamer_analytics_sidecar.py scripts/checkpoint_gstreamer_runtime.py tests/test_checkpoint_gstreamer_analytics_sidecar.py | Select-Object -First 300`
> - Ran `Get-Content -LiteralPath 'scripts/checkpoint_gstreamer_runtime.py' | Select-Object -Skip 1215 -First 110; rg -n "def validate_stage_contracts|STAGE_SEMANTIC" scripts/benchmark_contract.py | Select-Object -First 50`
> - Ran `Get-Content -LiteralPath 'scripts/benchmark_contract.py' | Select-Object -Skip 6170 -First 205`
>
> </details>
>
> Topology v2 теперь заморожен в сценариях и валидаторе: инвариантная цепочка включает явный `postprocess_<branch>` после analytics; legacy v1 остаётся читаемым только для старых артефактов, но текущий publication plan требует v2. Это позволяет доказуемо связать H2D с GPU analytics, а D2H — с CPU postprocess, без приписывания копирования несуществующему этапу.
>
> <details><summary>Ran 8 commands</summary>
>
> - Ran `rg -n -A95 -B15 "kpp_real_avi:|kpp_real_h264:|kpp_real_h265:|kpp_iss_publication_v3_h264:|kpp_iss_publication_v3_h265:" configs/datasets.yaml`
> - Ran `rg -n -i -A35 -B25 "frozen KPP v1|KPP v1|frozen.*v1|kpp_real" progress.md docs scripts tests configs | Select-Object -First 320`
> - Ran `rg -n -i "kpp.*(missing|absent|not found|unavailable)|v1.*(missing|absent|not found|unavailable)|missing.*kpp|frozen.*kpp" progress.md | Select-Object -Last 180`
> - Ran `Get-Content -LiteralPath 'scripts/freeze_kpp_iss_publication_v3.py' -TotalCount 420; Get-Content -LiteralPath 'tests/test_freeze_kpp_iss_publication_v3.py' -TotalCount 360`
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST python3 -c "import json; p='data/videos/kpp/kpp_iss_publication_v3/kpp_iss_publication_v3_manifest.json'; d=json.load(open(p)); print(json.dumps(d,indent=2,sort_keys=True)[:30000])"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST/evidence/model_parity/v3/execution_bundles
> find . -mindepth 2 -maxdepth 2 -name response.json -print | sort | head -8 | xargs -r jq -c '{request_id:.request_id,engine:.engine,resource:.resource}'"`
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST python3 -c "import json; d=json.load(open('data/videos/kpp/kpp_iss_publication_v3/kpp_iss_publication_v3_authorization_receipt.json')); print(json.dumps(d,indent=2,sort_keys=True))"`
> - Ran `rg -n -A80 -B15 "def _atomic_publish_directory|def _copy_pinned_snapshot" scripts/freeze_kpp_legacy_iss_v2_transcodes.py`
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Продолжаю с новым критерием полноты: отсутствующий исторический KPP v1 будет не «подменён», а воспроизводимо реконструирован как отдельный frozen-набор с честной фиксацией, что исходные байты v1 недоступны. Параллельно довожу topology v2 и реальные runtime-ветки; boot-profile не меняю, лимит памяти WSL сохраняю.
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `rg -n "def (_atomic_publish_directory|_copy_pinned_snapshot|main|build|write|freeze)|SELF_SHA|self_sha|manifest" scripts/freeze_kpp_legacy_iss_v2_transcodes.py scripts/freeze_kpp_iss_publication_v3.py tests/test_freeze_kpp_iss_publication_v3.py; Get-ChildItem -LiteralPath scripts -Filter '*kpp*freeze*' | Select-Object Name,Length; Get-ChildItem -LiteralPath tests -Filter '*kpp*freeze*' | Select-Object Name,Length`
> - Ran `$p='scripts/freeze_kpp_legacy_iss_v2_transcodes.py'; Get-Content -LiteralPath $p | Select-Object -Skip 950 -First 175; $p='scripts/freeze_kpp_iss_publication_v3.py'; Get-Content -LiteralPath $p | Select-Object -First 170; Get-Content -LiteralPath $p | Select-Object -Skip 930 -First 235; $p='tests/test_freeze_kpp_iss_publication_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 300 -First 125`
> - Ran `rg -n "def _create_private_working_directory|def _cleanup_owned_candidate|def _canonical_bytes|def _receipt_self_hash|def _write_canonical|def _stable_payload|def _validate_exact_tree|def _publication_claims|def _freeze_publication_corpus_impl" scripts/extract_kpp_legacy_iss.py scripts/freeze_kpp_iss_publication_v3.py; $p='scripts/extract_kpp_legacy_iss.py'; Get-Content -LiteralPath $p | Select-Object -Skip 450 -First 90; $p='scripts/freeze_kpp_iss_publication_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 270 -First 185; Get-Content -LiteralPath $p | Select-Object -Skip 700 -First 265`
> - Ran `$p='scripts/extract_kpp_legacy_iss.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1205 -First 95; $p='scripts/freeze_kpp_iss_publication_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 190 -First 130`
> - Ran `$root='E:\STUDY\VAST\data\videos\kpp\kpp_iss_publication_v3'; Get-ChildItem -LiteralPath $root -Recurse -File | ForEach-Object { $h=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant(); [pscustomobject]@{Relative=$_.FullName.Substring($root.Length+1).Replace('\','/'); Size=$_.Length; Sha256=$h; Links=(fsutil hardlink list $_.FullName 2>$null | Measure-Object).Count} } | Sort-Object Relative | Format-Table -AutoSize; Get-Content -LiteralPath "$root\kpp_iss_publication_v3_manifest.json" -Raw; Get-Content -LiteralPath "$root\kpp_iss_publication_v3_authorization_receipt.json" -Raw`
>
> </details>
>
> Для KPP фиксирую важное различие: новый frozen v1 будет пригоден для измерений производительности и топологии, но не будет выдавать байты v2/v3 за утраченный исторический v1. Это позволит запускать полный бенчмарк и одновременно сохранить научную корректность provenance.
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `Get-Content -LiteralPath tests/test_freeze_kpp_iss_publication_v3.py | Select-Object -First 90; rg -n "kpp_real_(avi|h264|h265)|kpp_iss_publication_v3|camera_layout" configs scripts tests | Select-Object -First 300`
> - Ran `rg -n "^def validate_kpp_iss_publication_v3_(documents|manifest_entry)|^def _load|MANIFEST_SHA|AUTHORIZATION" scripts/kpp_iss_publication_v3_dataset.py; Get-Content -LiteralPath scripts/kpp_iss_publication_v3_dataset.py | Select-Object -First 220; Get-Content -LiteralPath scripts/kpp_iss_publication_v3_dataset.py | Select-Object -Skip 690 -First 180`
> - Ran `$p='scripts/kpp_iss_publication_v3_dataset.py'; Get-Content -LiteralPath $p | Select-Object -Skip 360 -First 235`
> - Ran `$patch = @'
> *** Begin Patch
> *** Add File: tests/test_freeze_kpp_frozen_reconstruction_v1.py
> +from __future__ import annotations
> +
> +import copy
> +import hashlib
> +import json
> +import os
> +import sys
> +import tempfile
> +import unittest
> +from pathlib import Path
> +
> +
> +ROOT = Path(__file__).resolve().parents[1]
> +sys.path.insert(0, str(ROOT / "scripts"))
> +
> +from freeze_kpp_frozen_reconstruction_v1 import (  # noqa: E402
> +    AUTHORIZATION_BASIS_ID,
> +    AUTHORIZATION_RECEIPT_DOMAIN,
> +    DATASET_IDS,
> +    GENERATION_ID,
> +    MANIFEST_DOMAIN,
> +    ReconstructionFreezeError,
> +    SOURCE_AUTHORIZATION_DOMAIN,
> +    SOURCE_MANIFEST_DOMAIN,
> +    SOURCE_ROOT,
> +    TARGET_ROOT,
> +    _TestAdapters,
> +    _canonical_bytes,
> +    _freeze_reconstruction_impl,
> +)
> +
> +
> +def _sha(payload: bytes) -> str:
> +    return hashlib.sha256(payload).hexdigest()
> +
> +
> +def _seal(value: dict[str, object], *, field: str, domain: bytes) -> None:
> +    unsigned = dict(value)
> +    unsigned.pop(field, None)
> +    value[field] = hashlib.sha256(domain + _canonical_bytes(unsigned)).hexdigest()
> +
> +
> +def _write(path: Path, payload: bytes) -> dict[str, object]:
> +    path.parent.mkdir(parents=True, exist_ok=True)
> +    path.write_bytes(payload)
> +    return {"size_bytes": len(payload), "sha256": _sha(payload)}
> +
> +
> +class ReconstructionFixture:
> +    def __init__(self, root: Path) -> None:
> +        self.root = root
> +        self.source = root / SOURCE_ROOT
> +        self.source.mkdir(parents=True)
> +        self.media: dict[tuple[str, str], dict[str, object]] = {}
> +        for codec in ("h264", "h265"):
> +            for role in ("underbody", "front_gate"):
> +                relative = f"{codec}/iss_v2_{role}.mp4"
> +                payload = f"{codec}:{role}:physical-bytes".encode("ascii")
> +                descriptor = _write(self.source / relative, payload)
> +                self.media[(codec, role)] = {
> +                    "source_path": f"{SOURCE_ROOT}/{relative}",
> +                    **descriptor,
> +                }
> +
> +        self.receipts: list[dict[str, object]] = []
> +        for name in ("source_a.json", "source_b.json"):
> +            payload = _canonical_bytes({"artifact": name, "claim": False})
> +            descriptor = _write(self.source / "receipts" / name, payload)
> +            self.receipts.append(
> +                {
> +                    "source_path": f"{SOURCE_ROOT}/receipts/{name}",
> +                    "installed_name": name,
> +                    **descriptor,
> +                }
> +            )
> +
> +        self.authorization = {
> +            "schema_version": 1,
> +            "artifact_kind": "vast_kpp_iss_publication_v3_authorization_receipt",
> +            "generation_id": "kpp_iss_publication_v3",
> +            "dataset_ids": {
> +                "h264": "kpp_iss_publication_v3_h264",
> +                "h265": "kpp_iss_publication_v3_h265",
> +            },
> +            "status": "authorized_for_performance_publication",
> +            "claims": self.source_claims(),
> +        }
> +        _seal(
> +            self.authorization,
> +            field="authorization_receipt_sha256",
> +            domain=SOURCE_AUTHORIZATION_DOMAIN,
> +        )
> +        auth_payload = _canonical_bytes(self.authorization)
> +        auth_relative = "kpp_iss_publication_v3_authorization_receipt.json"
> +        auth_pin = _write(self.source / auth_relative, auth_payload)
> +        self.authorization_pin = {
> +            "source_path": f"{SOURCE_ROOT}/{auth_relative}",
> +            **auth_pin,
> +            "authorization_receipt_sha256": self.authorization[
> +                "authorization_receipt_sha256"
> +            ],
> +        }
> +
> +        self.manifest = {
> +            "schema_version": 1,
> +            "artifact_kind": "vast_kpp_iss_publication_v3_manifest",
> +            "generation_id": "kpp_iss_publication_v3",
> +            "status": "frozen_publication_corpus",
> +            "dataset_root": SOURCE_ROOT,
> +            "dataset_ids": copy.deepcopy(self.authorization["dataset_ids"]),
> +            "source_generation": {
> +                "generation_id": "kpp_legacy_iss_v2",
> +                "identity_equivalent": False,
> +            },
> +            "source_receipts": [
> +                {
> +                    "path": item["source_path"],
> +                    "size_bytes": item["size_bytes"],
> +                    "sha256": item["sha256"],
> +                }
> +                for item in self.receipts
> +            ],
> +            "media_artifacts": [
> +                {
> +                    "codec_variant": codec,
> +                    "role": role,
> +                    "path": descriptor["source_path"],
> +                    "size_bytes": descriptor["size_bytes"],
> +                    "sha256": descriptor["sha256"],
> +                }
> +                for (codec, role), descriptor in self.media.items()
> +            ],
> +            "authorization_receipt": {
> +                "path": self.authorization_pin["source_path"],
> +                "size_bytes": self.authorization_pin["size_bytes"],
> +                "sha256": self.authorization_pin["sha256"],
> +                "authorization_receipt_sha256": self.authorization_pin[
> +                    "authorization_receipt_sha256"
> +                ],
> +            },
> +            "claims": self.source_claims(),
> +        }
> +        _seal(self.manifest, field="manifest_sha256", domain=SOURCE_MANIFEST_DOMAIN)
> +        manifest_payload = _canonical_bytes(self.manifest)
> +        manifest_relative = "kpp_iss_publication_v3_manifest.json"
> +        manifest_pin = _write(self.source / manifest_relative, manifest_payload)
> +        self.manifest_pin = {
> +            "source_path": f"{SOURCE_ROOT}/{manifest_relative}",
> +            **manifest_pin,
> +            "manifest_sha256": self.manifest["manifest_sha256"],
> +        }
> +
> +    @staticmethod
> +    def source_claims() -> dict[str, bool]:
> +        return {
> +            "publication_authorized": True,
> +            "publication_scope_performance_and_topology_only": True,
> +            "accuracy_ground_truth_validated": False,
> +            "production_routing_validated": False,
> +            "v1_dataset_identity_equivalent": False,
> +            "source_timestamps_preserved": False,
> +            "media_reused_without_retranscode": True,
> +            "source_receipt_graph_exactly_pinned": True,
> +            "all_media_bytes_and_ffprobe_contracts_verified": True,
> +            "output_set_directory_published_atomically": True,
> +        }
> +
> +    def adapters(self) -> _TestAdapters:
> +        return _TestAdapters(
> +            source_pins={
> +                "manifest": copy.deepcopy(self.manifest_pin),
> +                "authorization": copy.deepcopy(self.authorization_pin),
> +                "media": copy.deepcopy(self.media),
> +                "receipts": copy.deepcopy(self.receipts),
> +            }
> +        )
> +
> +    def freeze(self, *, basis: str = AUTHORIZATION_BASIS_ID):
> +        return _freeze_reconstruction_impl(
> +            project_root=self.root,
> +            authorization_basis=basis,
> +            test_adapters=self.adapters(),
> +        )
> +
> +    def rewrite_manifest_and_repin(self) -> None:
> +        _seal(self.manifest, field="manifest_sha256", domain=SOURCE_MANIFEST_DOMAIN)
> +        payload = _canonical_bytes(self.manifest)
> +        path = self.source / "kpp_iss_publication_v3_manifest.json"
> +        path.write_bytes(payload)
> +        self.manifest_pin.update(
> +            {
> +                "size_bytes": len(payload),
> +                "sha256": _sha(payload),
> +                "manifest_sha256": self.manifest["manifest_sha256"],
> +            }
> +        )
> +
> +
> +class FreezeKppFrozenReconstructionV1Tests(unittest.TestCase):
> +    def test_happy_path_creates_distinct_standalone_reconstruction(self) -> None:
> +        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +            fixture = ReconstructionFixture(Path(tmp))
> +
> +            manifest = fixture.freeze()
> +
> +            target = fixture.root / TARGET_ROOT
> +            self.assertTrue(target.is_dir())
> +            self.assertEqual(GENERATION_ID, "kpp_frozen_reconstruction_v1")
> +            self.assertEqual(
> +                DATASET_IDS,
> +                {
> +                    "h264": "kpp_frozen_reconstruction_v1_h264",
> +                    "h265": "kpp_frozen_reconstruction_v1_h265",
> +                },
> +            )
> +            for (codec, role), source_descriptor in fixture.media.items():
> +                source = fixture.root / str(source_descriptor["source_path"])
> +                copied = target / codec / f"iss_v2_{role}.mp4"
> +                self.assertEqual(source.read_bytes(), copied.read_bytes())
> +                self.assertNotEqual(os.stat(source).st_ino, os.stat(copied).st_ino)
> +            authorization = json.loads(
> +                (target / "kpp_frozen_reconstruction_v1_authorization_receipt.json")
> +                .read_text(encoding="ascii")
> +            )
> +            self.assertEqual(
> +                authorization["historical_v1"]["source_bytes_available"], False
> +            )
> +            self.assertFalse(
> +                authorization["claims"]["historical_v1_dataset_identity_equivalent"]
> +            )
> +            self.assertTrue(
> +                authorization["claims"]["reconstruction_identity_distinct"]
> +            )
> +            self.assertEqual(
> +                manifest["source_publication"]["generation_id"],
> +                "kpp_iss_publication_v3",
> +            )
> +            auth_unsigned = dict(authorization)
> +            auth_hash = auth_unsigned.pop("authorization_receipt_sha256")
> +            self.assertEqual(
> +                auth_hash,
> +                hashlib.sha256(
> +                    AUTHORIZATION_RECEIPT_DOMAIN + _canonical_bytes(auth_unsigned)
> +                ).hexdigest(),
> +            )
> +            manifest_unsigned = dict(manifest)
> +            manifest_hash = manifest_unsigned.pop("manifest_sha256")
> +            self.assertEqual(
> +                manifest_hash,
> +                hashlib.sha256(
> +                    MANIFEST_DOMAIN + _canonical_bytes(manifest_unsigned)
> +                ).hexdigest(),
> +            )
> +
> +    def test_rejects_missing_explicit_authorization(self) -> None:
> +        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +            fixture = ReconstructionFixture(Path(tmp))
> +            with self.assertRaisesRegex(ReconstructionFreezeError, "authorization"):
> +                fixture.freeze(basis="wrong")
> +
> +    def test_rejects_tampered_source_manifest_with_only_file_pin_updated(self) -> None:
> +        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +            fixture = ReconstructionFixture(Path(tmp))
> +            fixture.manifest["status"] = "tampered"
> +            payload = _canonical_bytes(fixture.manifest)
> +            (fixture.source / "kpp_iss_publication_v3_manifest.json").write_bytes(
> +                payload
> +            )
> +            fixture.manifest_pin.update(
> +                {"size_bytes": len(payload), "sha256": _sha(payload)}
> +            )
> +
> +            with self.assertRaisesRegex(ReconstructionFreezeError, "self hash"):
> +                fixture.freeze()
> +
> +    def test_rejects_resealed_historical_v1_identity_spoof(self) -> None:
> +        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +            fixture = ReconstructionFixture(Path(tmp))
> +            fixture.manifest["claims"]["v1_dataset_identity_equivalent"] = True
> +            fixture.rewrite_manifest_and_repin()
> +
> +            with self.assertRaisesRegex(
> +                ReconstructionFreezeError, "v1.*identity|identity.*v1"
> +            ):
> +                fixture.freeze()
> +
> +    def test_rejects_media_pin_that_disagrees_with_source_manifest(self) -> None:
> +        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +            fixture = ReconstructionFixture(Path(tmp))
> +            descriptor = fixture.media[("h264", "underbody")]
> +            path = fixture.root / str(descriptor["source_path"])
> +            path.write_bytes(b"replacement")
> +            descriptor.update(
> +                {"size_bytes": len(b"replacement"), "sha256": _sha(b"replacement")}
> +            )
> +
> +            with self.assertRaisesRegex(ReconstructionFreezeError, "media graph"):
> +                fixture.freeze()
> +
> +    def test_refuses_to_replace_existing_target(self) -> None:
> +        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +            fixture = ReconstructionFixture(Path(tmp))
> +            target = fixture.root / TARGET_ROOT
> +            target.mkdir(parents=True)
> +            sentinel = target / "sentinel"
> +            sentinel.write_text("keep", encoding="ascii")
> +
> +            with self.assertRaisesRegex(ReconstructionFreezeError, "already exists"):
> +                fixture.freeze()
> +            self.assertEqual(sentinel.read_text(encoding="ascii"), "keep")
> +
> +
> +if __name__ == "__main__":
> +    unittest.main()
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `python -B -m unittest tests.test_freeze_kpp_frozen_reconstruction_v1`
> - Ran `Test-Path -LiteralPath scripts/freeze_kpp_frozen_reconstruction_v1.py`
> - Ran ```$patch = @'
> *** Begin Patch
> *** Add File: scripts/freeze_kpp_frozen_reconstruction_v1.py
> +#!/usr/bin/env python3
> +"""Freeze a distinct KPP reconstruction when historical v1 bytes are absent.
> +
> +This is not an identity recovery of ``kpp_real_*``. It copies the already
> +frozen publication-v3 media and receipt graph into a standalone generation and
> +authorizes only performance/topology publication.
> +"""
> +
> +from __future__ import annotations
> +
> +import argparse
> +import copy
> +import hashlib
> +import json
> +import os
> +import stat
> +import sys
> +from collections.abc import Mapping, Sequence
> +from dataclasses import dataclass
> +from pathlib import Path, PurePosixPath
> +from typing import Any
> +
> +from extract_kpp_legacy_iss import ExtractionError, _create_private_working_directory
> +from freeze_kpp_iss_publication_v3 import (
> +    AUTHORIZATION_RECEIPT_DOMAIN as SOURCE_AUTHORIZATION_DOMAIN,
> +    MANIFEST_DOMAIN as SOURCE_MANIFEST_DOMAIN,
> +    PublicationCorpusFreezeError,
> +    _canonical_bytes,
> +    _is_link_or_reparse,
> +    _lexists,
> +    _receipt_self_hash,
> +    _require_plain_chain,
> +    _stable_payload,
> +    _strict_json,
> +    _validated_root,
> +)
> +from freeze_kpp_legacy_iss_v2_transcodes import (
> +    TranscodeFreezeError,
> +    _atomic_publish_directory,
> +    _copy_pinned_snapshot,
> +)
> +
> +
> +GENERATION_ID = "kpp_frozen_reconstruction_v1"
> +DATASET_IDS = {
> +    "h264": "kpp_frozen_reconstruction_v1_h264",
> +    "h265": "kpp_frozen_reconstruction_v1_h265",
> +}
> +SOURCE_GENERATION_ID = "kpp_iss_publication_v3"
> +SOURCE_DATASET_IDS = {
> +    "h264": "kpp_iss_publication_v3_h264",
> +    "h265": "kpp_iss_publication_v3_h265",
> +}
> +HISTORICAL_DATASET_IDS = ["kpp_real_avi", "kpp_real_h264", "kpp_real_h265"]
> +SOURCE_ROOT = "data/videos/kpp/kpp_iss_publication_v3"
> +TARGET_ROOT = "data/videos/kpp/kpp_frozen_reconstruction_v1"
> +SOURCE_MANIFEST_NAME = "kpp_iss_publication_v3_manifest.json"
> +SOURCE_AUTHORIZATION_NAME = "kpp_iss_publication_v3_authorization_receipt.json"
> +AUTHORIZATION_RECEIPT_NAME = "kpp_frozen_reconstruction_v1_authorization_receipt.json"
> +MANIFEST_NAME = "kpp_frozen_reconstruction_v1_manifest.json"
> +AUTHORIZATION_BASIS_ID = (
> +    "explicit_user_instruction_2026-08-24_reconstruct_all_missing_frozen_kpp"
> +)
> +AUTHORIZATION_RECEIPT_DOMAIN = (
> +    b"VAST:kpp-frozen-reconstruction-v1-authorization-receipt:v1\0"
> +)
> +MANIFEST_DOMAIN = b"VAST:kpp-frozen-reconstruction-v1-manifest:v1\0"
> +
> +SOURCE_MANIFEST_PIN: dict[str, object] = {
> +    "source_path": f"{SOURCE_ROOT}/{SOURCE_MANIFEST_NAME}",
> +    "size_bytes": 7225,
> +    "sha256": "9a9cf3e08be159bfd4bdeda1d9323b13102980322bde03d9b061e749c1d3fa24",
> +    "manifest_sha256": "bbe2cca51cdcc95651492e0f28fc95ed00b9106dce73b5995280259701c91cc2",
> +}
> +SOURCE_AUTHORIZATION_PIN: dict[str, object] = {
> +    "source_path": f"{SOURCE_ROOT}/{SOURCE_AUTHORIZATION_NAME}",
> +    "size_bytes": 3300,
> +    "sha256": "eee7a49472077ff83bd9a9f3cc67a462c4441b0c841bc64d75859271333732ee",
> +    "authorization_receipt_sha256": (
> +        "11678b26210c4ae514535b399afa3ed9f1b412d116d9708c1a94af606cd03d2a"
> +    ),
> +}
> +SOURCE_MEDIA: dict[tuple[str, str], dict[str, object]] = {
> +    ("h264", "underbody"): {
> +        "source_path": f"{SOURCE_ROOT}/h264/iss_v2_underbody.mp4",
> +        "size_bytes": 1_079_445_865,
> +        "sha256": "b7e5165549172266a5617ff7bbca6e5b888775b0a2490e27b7cbe17640e3b102",
> +    },
> +    ("h264", "front_gate"): {
> +        "source_path": f"{SOURCE_ROOT}/h264/iss_v2_front_gate.mp4",
> +        "size_bytes": 63_131_711,
> +        "sha256": "08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273",
> +    },
> +    ("h265", "underbody"): {
> +        "source_path": f"{SOURCE_ROOT}/h265/iss_v2_underbody.mp4",
> +        "size_bytes": 223_684_192,
> +        "sha256": "5368c94a26659c529106724427fc6c3e60fe6788d56699da14c93bc4222e7839",
> +    },
> +    ("h265", "front_gate"): {
> +        "source_path": f"{SOURCE_ROOT}/h265/iss_v2_front_gate.mp4",
> +        "size_bytes": 14_910_770,
> +        "sha256": "fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728",
> +    },
> +}
> +SOURCE_RECEIPTS: list[dict[str, object]] = [
> +    {
> +        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_extraction_receipt.json",
> +        "installed_name": "kpp_iss_v2_extraction_receipt.json",
> +        "size_bytes": 2495,
> +        "sha256": "f160ce153804f92dd02068ad48547b396636bd2cb7dfc8fb39114210f23a0e05",
> +    },
> +    {
> +        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_transcode_receipt.json",
> +        "installed_name": "kpp_iss_v2_transcode_receipt.json",
> +        "size_bytes": 7092,
> +        "sha256": "f78406237d539224a25c38bf40f913f18069e120e8e66e9d11270ff88ceb5470",
> +    },
> +    {
> +        "source_path": f"{SOURCE_ROOT}/receipts/iss_v2_underbody_metadata.json",
> +        "installed_name": "iss_v2_underbody_metadata.json",
> +        "size_bytes": 12_731_945,
> +        "sha256": "d23872d4b4706ef7d804f917a72407f82326eb3cdd5d39d347913f20cc65b0d4",
> +    },
> +    {
> +        "source_path": f"{SOURCE_ROOT}/receipts/kpp_iss_v2_materialization_receipt.json",
> +        "installed_name": "kpp_iss_v2_materialization_receipt.json",
> +        "size_bytes": 28_131,
> +        "sha256": "dd0d2aa38da1281a750806858b555b994a9dcf3c9bcd35e8379dbc9d339f2b33",
> +    },
> +]
> +
> +_EXPECTED_SOURCE_CLAIMS = {
> +    "publication_authorized": True,
> +    "publication_scope_performance_and_topology_only": True,
> +    "accuracy_ground_truth_validated": False,
> +    "production_routing_validated": False,
> +    "v1_dataset_identity_equivalent": False,
> +    "source_timestamps_preserved": False,
> +    "media_reused_without_retranscode": True,
> +    "source_receipt_graph_exactly_pinned": True,
> +    "all_media_bytes_and_ffprobe_contracts_verified": True,
> +    "output_set_directory_published_atomically": True,
> +}
> +
> +
> +class ReconstructionFreezeError(RuntimeError):
> +    """Raised when reconstruction cannot be frozen without ambiguity."""
> +
> +
> +@dataclass(frozen=True)
> +class _TestAdapters:
> +    source_pins: Mapping[str, object]
> +
> +
> +def _production_pins() -> dict[str, object]:
> +    return {
> +        "manifest": copy.deepcopy(SOURCE_MANIFEST_PIN),
> +        "authorization": copy.deepcopy(SOURCE_AUTHORIZATION_PIN),
> +        "media": copy.deepcopy(SOURCE_MEDIA),
> +        "receipts": copy.deepcopy(SOURCE_RECEIPTS),
> +    }
> +
> +
> +def _descriptor(value: object, *, label: str, self_field: str | None = None):
> +    if not isinstance(value, Mapping):
> +        raise ReconstructionFreezeError(f"{label} pin is invalid")
> +    result = dict(value)
> +    keys = {"source_path", "size_bytes", "sha256"}
> +    if self_field:
> +        keys.add(self_field)
> +    if set(result) != keys:
> +        raise ReconstructionFreezeError(f"{label} pin schema is not exact")
> +    source_path = result["source_path"]
> +    path = PurePosixPath(source_path) if type(source_path) is str else None
> +    if (
> +        path is None
> +        or path.is_absolute()
> +        or path.as_posix() != source_path
> +        or any(part in ("", ".", "..") or ":" in part for part in path.parts)
> +    ):
> +        raise ReconstructionFreezeError(f"{label} source_path is invalid")
> +    if type(result["size_bytes"]) is not int or result["size_bytes"] <= 0:
> +        raise ReconstructionFreezeError(f"{label} size pin is invalid")
> +    for field in filter(None, ("sha256", self_field)):
> +        digest = result[field]
> +        if (
> +            type(digest) is not str
> +            or len(digest) != 64
> +            or any(character not in "0123456789abcdef" for character in digest)
> +            or digest == "0" * 64
> +        ):
> +            raise ReconstructionFreezeError(f"{label} {field} pin is invalid")
> +    return result
> +
> +
> +def _read_json(root: Path, pin: Mapping[str, object], *, label: str, field: str, domain: bytes):
> +    path = root.joinpath(*PurePosixPath(str(pin["source_path"])).parts)
> +    try:
> +        _require_plain_chain(root, path)
> +        size, digest, payload = _stable_payload(path, label=label, retain=True)
> +        if size != pin["size_bytes"] or digest != pin["sha256"]:
> +            raise ReconstructionFreezeError(f"{label} external byte pin drifted")
> +        assert payload is not None
> +        value = _strict_json(payload, label=label)
> +        computed = _receipt_self_hash(value, field=field, domain=domain)
> +    except PublicationCorpusFreezeError as exc:
> +        raise ReconstructionFreezeError(str(exc)) from exc
> +    if value.get(field) != pin[field] or computed != value.get(field):
> +        raise ReconstructionFreezeError(f"{label} self hash is invalid")
> +    return value
> +
> +
> +def _check_claims(value: object, *, label: str) -> None:
> +    if not isinstance(value, Mapping):
> +        raise ReconstructionFreezeError(f"{label} claims are invalid")
> +    for field, expected in _EXPECTED_SOURCE_CLAIMS.items():
> +        if value.get(field) is not expected:
> +            if field == "v1_dataset_identity_equivalent":
> +                raise ReconstructionFreezeError(f"{label} forbidden v1 identity claim")
> +            raise ReconstructionFreezeError(f"{label} claim {field!r} drifted")
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch```
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/freeze_kpp_frozen_reconstruction_v1.py
> @@
>  def _check_claims(value: object, *, label: str) -> None:
> @@
>              if field == "v1_dataset_identity_equivalent":
>                  raise ReconstructionFreezeError(f"{label} forbidden v1 identity claim")
>              raise ReconstructionFreezeError(f"{label} claim {field!r} drifted")
> +
> +
> +def _validate_source_graph(root: Path, pins: Mapping[str, object]):
> +    if set(pins) != {"manifest", "authorization", "media", "receipts"}:
> +        raise ReconstructionFreezeError("source pin set is not exact")
> +    manifest_pin = _descriptor(
> +        pins["manifest"], label="source manifest", self_field="manifest_sha256"
> +    )
> +    authorization_pin = _descriptor(
> +        pins["authorization"],
> +        label="source authorization",
> +        self_field="authorization_receipt_sha256",
> +    )
> +    manifest = _read_json(
> +        root,
> +        manifest_pin,
> +        label="source manifest",
> +        field="manifest_sha256",
> +        domain=SOURCE_MANIFEST_DOMAIN,
> +    )
> +    authorization = _read_json(
> +        root,
> +        authorization_pin,
> +        label="source authorization",
> +        field="authorization_receipt_sha256",
> +        domain=SOURCE_AUTHORIZATION_DOMAIN,
> +    )
> +    expected_documents = (
> +        (manifest, "vast_kpp_iss_publication_v3_manifest", "frozen_publication_corpus"),
> +        (
> +            authorization,
> +            "vast_kpp_iss_publication_v3_authorization_receipt",
> +            "authorized_for_performance_publication",
> +        ),
> +    )
> +    for value, kind, status in expected_documents:
> +        if (
> +            value.get("schema_version") != 1
> +            or type(value.get("schema_version")) is not int
> +            or value.get("artifact_kind") != kind
> +            or value.get("generation_id") != SOURCE_GENERATION_ID
> +            or value.get("status") != status
> +            or value.get("dataset_ids") != SOURCE_DATASET_IDS
> +        ):
> +            raise ReconstructionFreezeError("source identity or status drifted")
> +        _check_claims(value.get("claims"), label=kind)
> +    if manifest.get("dataset_root") != SOURCE_ROOT:
> +        raise ReconstructionFreezeError("source dataset root drifted")
> +    source_generation = manifest.get("source_generation")
> +    if not isinstance(source_generation, Mapping) or source_generation.get(
> +        "identity_equivalent"
> +    ) is not False:
> +        raise ReconstructionFreezeError("source v1 identity boundary is invalid")
> +    expected_authorization = {
> +        "path": authorization_pin["source_path"],
> +        "size_bytes": authorization_pin["size_bytes"],
> +        "sha256": authorization_pin["sha256"],
> +        "authorization_receipt_sha256": authorization_pin[
> +            "authorization_receipt_sha256"
> +        ],
> +    }
> +    if manifest.get("authorization_receipt") != expected_authorization:
> +        raise ReconstructionFreezeError("source authorization graph drifted")
> +
> +    raw_media = pins["media"]
> +    identities = {
> +        (codec, role)
> +        for codec in ("h264", "h265")
> +        for role in ("underbody", "front_gate")
> +    }
> +    if not isinstance(raw_media, Mapping) or set(raw_media) != identities:
> +        raise ReconstructionFreezeError("source media pin set is not exact")
> +    media = {
> +        identity: _descriptor(
> +            raw_media[identity], label=f"source media {identity[0]}/{identity[1]}"
> +        )
> +        for identity in identities
> +    }
> +    observed_media = manifest.get("media_artifacts")
> +    if type(observed_media) is not list:
> +        raise ReconstructionFreezeError("source manifest media graph is invalid")
> +    projected_media = {}
> +    for raw in observed_media:
> +        if type(raw) is not dict:
> +            raise ReconstructionFreezeError("source manifest media graph is invalid")
> +        identity = (raw.get("codec_variant"), raw.get("role"))
> +        if identity in projected_media:
> +            raise ReconstructionFreezeError("source manifest media graph is duplicated")
> +        projected_media[identity] = {
> +            "source_path": raw.get("path"),
> +            "size_bytes": raw.get("size_bytes"),
> +            "sha256": raw.get("sha256"),
> +        }
> +    if projected_media != media:
> +        raise ReconstructionFreezeError("source manifest media graph drifted")
> +
> +    raw_receipts = pins["receipts"]
> +    if type(raw_receipts) is not list or not raw_receipts:
> +        raise ReconstructionFreezeError("source receipt pin set is invalid")
> +    receipts = []
> +    names: set[str] = set()
> +    for index, raw in enumerate(raw_receipts):
> +        if not isinstance(raw, Mapping) or set(raw) != {
> +            "source_path",
> +            "installed_name",
> +            "size_bytes",
> +            "sha256",
> +        }:
> +            raise ReconstructionFreezeError("source receipt pin schema is not exact")
> +        item = _descriptor(
> +            {key: raw[key] for key in ("source_path", "size_bytes", "sha256")},
> +            label=f"source receipt {index}",
> +        )
> +        name = raw["installed_name"]
> +        if (
> +            type(name) is not str
> +            or PurePosixPath(name).name != name
> +            or name in names
> +        ):
> +            raise ReconstructionFreezeError("source receipt installed name is invalid")
> +        names.add(name)
> +        receipts.append({**item, "installed_name": name})
> +    manifest_receipts = manifest.get("source_receipts")
> +    if type(manifest_receipts) is not list:
> +        raise ReconstructionFreezeError("source manifest receipt graph is invalid")
> +    observed_receipts = {
> +        (item.get("path"), item.get("size_bytes"), item.get("sha256"))
> +        for item in manifest_receipts
> +        if type(item) is dict
> +    }
> +    expected_receipts = {
> +        (item["source_path"], item["size_bytes"], item["sha256"])
> +        for item in receipts
> +    }
> +    if (
> +        len(observed_receipts) != len(manifest_receipts)
> +        or observed_receipts != expected_receipts
> +    ):
> +        raise ReconstructionFreezeError("source manifest receipt graph drifted")
> +    return media, receipts, manifest_pin, authorization_pin
> +
> +
> +def _claims() -> dict[str, bool]:
> +    return {
> +        "publication_authorized": True,
> +        "publication_scope_performance_and_topology_only": True,
> +        "accuracy_ground_truth_validated": False,
> +        "production_routing_validated": False,
> +        "historical_v1_source_bytes_recovered": False,
> +        "historical_v1_dataset_identity_equivalent": False,
> +        "reconstruction_identity_distinct": True,
> +        "media_reused_without_retranscode": True,
> +        "source_v3_receipt_graph_exactly_pinned": True,
> +        "all_copied_bytes_verified": True,
> +        "output_set_directory_published_atomically": True,
> +    }
> +
> +
> +def _historical_v1() -> dict[str, object]:
> +    return {
> +        "dataset_ids": copy.deepcopy(HISTORICAL_DATASET_IDS),
> +        "source_bytes_available": False,
> +        "identity_recovered": False,
> +        "reconstruction_is_identity_substitute": False,
> +    }
> +
> +
> +def _write_canonical(path: Path, value: Mapping[str, object]) -> bytes:
> +    payload = _canonical_bytes(value)
> +    try:
> +        with path.open("xb") as stream:
> +            stream.write(payload)
> +            stream.flush()
> +            os.fsync(stream.fileno())
> +    except OSError as exc:
> +        raise ReconstructionFreezeError(f"cannot write artifact: {exc}") from exc
> +    if path.read_bytes() != payload:
> +        raise ReconstructionFreezeError(f"artifact changed: {path.name}")
> +    return payload
> +
> +
> +def _tree_files(receipts: Sequence[Mapping[str, object]]) -> set[str]:
> +    return {
> +        *(
> +            f"{codec}/iss_v2_{role}.mp4"
> +            for codec in ("h264", "h265")
> +            for role in ("underbody", "front_gate")
> +        ),
> +        f"receipts/{SOURCE_MANIFEST_NAME}",
> +        f"receipts/{SOURCE_AUTHORIZATION_NAME}",
> +        *(f"receipts/{item['installed_name']}" for item in receipts),
> +        AUTHORIZATION_RECEIPT_NAME,
> +        MANIFEST_NAME,
> +    }
> +
> +
> +def _validate_tree(root: Path, receipts: Sequence[Mapping[str, object]]) -> None:
> +    if not root.is_dir() or _is_link_or_reparse(root):
> +        raise ReconstructionFreezeError("reconstruction root is not plain")
> +    directories, files, pending = set(), set(), [root]
> +    while pending:
> +        for child in pending.pop().iterdir():
> +            if _is_link_or_reparse(child):
> +                raise ReconstructionFreezeError("reconstruction contains a link")
> +            relative, observed = child.relative_to(root).as_posix(), child.lstat()
> +            if stat.S_ISDIR(observed.st_mode):
> +                directories.add(relative)
> +                pending.append(child)
> +            elif stat.S_ISREG(observed.st_mode) and int(observed.st_nlink) == 1:
> +                files.add(relative)
> +            else:
> +                raise ReconstructionFreezeError("reconstruction entry is not plain")
> +    if directories != {"h264", "h265", "receipts"} or files != _tree_files(receipts):
> +        raise ReconstructionFreezeError("reconstruction tree is not exact")
> +
> +
> +def _cleanup(working: Path, parent: Path, receipts: Sequence[Mapping[str, object]]) -> None:
> +    if (
> +        working.parent != parent
> +        or not working.name.startswith(".kpp_frozen_reconstruction_v1.")
> +        or not working.name.endswith(".candidate")
> +        or not working.is_dir()
> +        or _is_link_or_reparse(working)
> +    ):
> +        return
> +    for relative in sorted(_tree_files(receipts)):
> +        path = working.joinpath(*PurePosixPath(relative).parts)
> +        if _lexists(path):
> +            if _is_link_or_reparse(path) or not path.is_file():
> +                return
> +            path.unlink()
> +    for directory in (working / "receipts", working / "h265", working / "h264"):
> +        if _lexists(directory):
> +            directory.rmdir()
> +    working.rmdir()
> +
> +
> +def _copy(root: Path, working: Path, descriptor: Mapping[str, object], relative: str):
> +    source = root.joinpath(*PurePosixPath(str(descriptor["source_path"])).parts)
> +    try:
> +        _require_plain_chain(root, source)
> +        _copy_pinned_snapshot(
> +            source=source,
> +            target=working.joinpath(*PurePosixPath(relative).parts),
> +            expected_sha256=str(descriptor["sha256"]),
> +            expected_size_bytes=int(descriptor["size_bytes"]),
> +            label=f"reconstruction source {relative}",
> +        )
> +    except (PublicationCorpusFreezeError, TranscodeFreezeError) as exc:
> +        raise ReconstructionFreezeError(str(exc)) from exc
> +    return {
> +        "source_path": descriptor["source_path"],
> +        "path": f"{TARGET_ROOT}/{relative}",
> +        "size_bytes": descriptor["size_bytes"],
> +        "sha256": descriptor["sha256"],
> +    }
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/freeze_kpp_frozen_reconstruction_v1.py
> @@
>  def _copy(root: Path, working: Path, descriptor: Mapping[str, object], relative: str):
> @@
>      return {
>          "source_path": descriptor["source_path"],
>          "path": f"{TARGET_ROOT}/{relative}",
>          "size_bytes": descriptor["size_bytes"],
>          "sha256": descriptor["sha256"],
>      }
> +
> +
> +def _freeze_reconstruction_impl(
> +    *, project_root: Path, authorization_basis: str, test_adapters: _TestAdapters | None
> +) -> dict[str, object]:
> +    if authorization_basis != AUTHORIZATION_BASIS_ID:
> +        raise ReconstructionFreezeError(
> +            "explicit reconstruction authorization is missing or invalid"
> +        )
> +    try:
> +        root = _validated_root(project_root)
> +    except PublicationCorpusFreezeError as exc:
> +        raise ReconstructionFreezeError(str(exc)) from exc
> +    target = root.joinpath(*PurePosixPath(TARGET_ROOT).parts)
> +    try:
> +        _require_plain_chain(root, target)
> +    except PublicationCorpusFreezeError as exc:
> +        raise ReconstructionFreezeError(str(exc)) from exc
> +    if _lexists(target):
> +        raise ReconstructionFreezeError(f"target already exists: {TARGET_ROOT}")
> +    parent = target.parent
> +    if not parent.is_dir() or _is_link_or_reparse(parent):
> +        raise ReconstructionFreezeError("target parent must be a plain directory")
> +    pins = (
> +        _production_pins()
> +        if test_adapters is None
> +        else copy.deepcopy(dict(test_adapters.source_pins))
> +    )
> +    media, receipts, manifest_pin, authorization_pin = _validate_source_graph(root, pins)
> +    try:
> +        working = _create_private_working_directory(
> +            parent=parent,
> +            prefix=".kpp_frozen_reconstruction_v1.",
> +            suffix=".candidate",
> +        )
> +    except ExtractionError as exc:
> +        raise ReconstructionFreezeError(str(exc)) from exc
> +    published = False
> +    try:
> +        for name in ("h264", "h265", "receipts"):
> +            (working / name).mkdir()
> +        source_documents = {
> +            "manifest": _copy(
> +                root, working, manifest_pin, f"receipts/{SOURCE_MANIFEST_NAME}"
> +            ),
> +            "authorization": _copy(
> +                root, working, authorization_pin, f"receipts/{SOURCE_AUTHORIZATION_NAME}"
> +            ),
> +        }
> +        source_documents["manifest"]["manifest_sha256"] = manifest_pin[
> +            "manifest_sha256"
> +        ]
> +        source_documents["authorization"][
> +            "authorization_receipt_sha256"
> +        ] = authorization_pin["authorization_receipt_sha256"]
> +        installed_receipts = [
> +            _copy(root, working, item, f"receipts/{item['installed_name']}")
> +            for item in receipts
> +        ]
> +        installed_media = []
> +        for codec in ("h264", "h265"):
> +            for role in ("underbody", "front_gate"):
> +                copied = _copy(
> +                    root,
> +                    working,
> +                    media[(codec, role)],
> +                    f"{codec}/iss_v2_{role}.mp4",
> +                )
> +                installed_media.append(
> +                    {"codec_variant": codec, "role": role, **copied}
> +                )
> +
> +        claims = _claims()
> +        source_publication = {
> +            "generation_id": SOURCE_GENERATION_ID,
> +            "dataset_ids": copy.deepcopy(SOURCE_DATASET_IDS),
> +            "generation_identity_equivalent": False,
> +            "media_bytes_reused_exactly": True,
> +            **source_documents,
> +        }
> +        authorization: dict[str, object] = {
> +            "schema_version": 1,
> +            "artifact_kind": "vast_kpp_frozen_reconstruction_v1_authorization_receipt",
> +            "generation_id": GENERATION_ID,
> +            "dataset_ids": copy.deepcopy(DATASET_IDS),
> +            "status": "authorized_reconstruction_for_performance_publication",
> +            "authorization_basis": {
> +                "kind": "explicit_user_instruction",
> +                "basis_id": AUTHORIZATION_BASIS_ID,
> +                "authorized_scope": "performance_and_topology_benchmark_results_only",
> +                "excluded_scopes": [
> +                    "accuracy_evaluation",
> +                    "production_routing_validation",
> +                    "historical_v1_identity_equivalence",
> +                ],
> +            },
> +            "historical_v1": _historical_v1(),
> +            "source_publication": copy.deepcopy(source_publication),
> +            "claims": copy.deepcopy(claims),
> +        }
> +        authorization["authorization_receipt_sha256"] = _receipt_self_hash(
> +            authorization,
> +            field="authorization_receipt_sha256",
> +            domain=AUTHORIZATION_RECEIPT_DOMAIN,
> +        )
> +        auth_payload = _write_canonical(
> +            working / AUTHORIZATION_RECEIPT_NAME, authorization
> +        )
> +        auth_descriptor = {
> +            "path": f"{TARGET_ROOT}/{AUTHORIZATION_RECEIPT_NAME}",
> +            "size_bytes": len(auth_payload),
> +            "sha256": hashlib.sha256(auth_payload).hexdigest(),
> +            "authorization_receipt_sha256": authorization[
> +                "authorization_receipt_sha256"
> +            ],
> +        }
> +        datasets = [
> +            {
> +                "dataset_id": DATASET_IDS[codec],
> +                "codec_variant": codec,
> +                "publication_scope": "performance_and_topology_benchmark_results_only",
> +                "accuracy_ground_truth": False,
> +                "production_routing_validated": False,
> +                "historical_v1_identity_equivalent": False,
> +                "physical_stream_paths": [
> +                    f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4"
> +                    for role in ("underbody", "front_gate")
> +                ],
> +            }
> +            for codec in ("h264", "h265")
> +        ]
> +        manifest: dict[str, object] = {
> +            "schema_version": 1,
> +            "artifact_kind": "vast_kpp_frozen_reconstruction_v1_manifest",
> +            "generation_id": GENERATION_ID,
> +            "status": "frozen_distinct_reconstruction",
> +            "dataset_root": TARGET_ROOT,
> +            "dataset_ids": copy.deepcopy(DATASET_IDS),
> +            "datasets": datasets,
> +            "historical_v1": _historical_v1(),
> +            "source_publication": copy.deepcopy(source_publication),
> +            "source_receipts": installed_receipts,
> +            "media_artifacts": installed_media,
> +            "authorization_receipt": auth_descriptor,
> +            "claims": copy.deepcopy(claims),
> +        }
> +        manifest["manifest_sha256"] = _receipt_self_hash(
> +            manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
> +        )
> +        manifest_payload = _write_canonical(working / MANIFEST_NAME, manifest)
> +        _validate_tree(working, receipts)
> +        try:
> +            _atomic_publish_directory(working, target)
> +        except TranscodeFreezeError as exc:
> +            raise ReconstructionFreezeError(str(exc)) from exc
> +        published = True
> +        _validate_tree(target, receipts)
> +        if (target / MANIFEST_NAME).read_bytes() != manifest_payload:
> +            raise ReconstructionFreezeError("published manifest changed")
> +        if (target / AUTHORIZATION_RECEIPT_NAME).read_bytes() != auth_payload:
> +            raise ReconstructionFreezeError("published authorization changed")
> +        for item in installed_media:
> +            relative = PurePosixPath(str(item["path"])).relative_to(TARGET_ROOT)
> +            try:
> +                size, digest, _ = _stable_payload(
> +                    target.joinpath(*relative.parts),
> +                    label="published reconstruction media",
> +                    retain=False,
> +                )
> +            except PublicationCorpusFreezeError as exc:
> +                raise ReconstructionFreezeError(str(exc)) from exc
> +            if size != item["size_bytes"] or digest != item["sha256"]:
> +                raise ReconstructionFreezeError("published media drifted")
> +        return manifest
> +    except Exception:
> +        if not published and _lexists(working):
> +            try:
> +                _cleanup(working, parent, receipts)
> +            except OSError:
> +                pass
> +        raise
> +
> +
> +def freeze_reconstruction(
> +    *, project_root: Path, authorization_basis: str
> +) -> dict[str, object]:
> +    """Freeze the authoritative standalone reconstruction."""
> +
> +    return _freeze_reconstruction_impl(
> +        project_root=project_root,
> +        authorization_basis=authorization_basis,
> +        test_adapters=None,
> +    )
> +
> +
> +def _build_parser() -> argparse.ArgumentParser:
> +    parser = argparse.ArgumentParser(description=__doc__)
> +    parser.add_argument("--project-root", type=Path, required=True)
> +    parser.add_argument("--authorization-basis", required=True)
> +    return parser
> +
> +
> +def main(argv: Sequence[str] | None = None) -> int:
> +    args = _build_parser().parse_args(argv)
> +    try:
> +        manifest = freeze_reconstruction(
> +            project_root=args.project_root,
> +            authorization_basis=args.authorization_basis,
> +        )
> +    except ReconstructionFreezeError as exc:
> +        print(f"ERROR: {exc}", file=sys.stderr)
> +        return 78
> +    print(json.dumps(manifest, sort_keys=True))
> +    return 0
> +
> +
> +if __name__ == "__main__":
> +    raise SystemExit(main())
> +
> +
> +__all__ = [
> +    "AUTHORIZATION_BASIS_ID",
> +    "AUTHORIZATION_RECEIPT_DOMAIN",
> +    "DATASET_IDS",
> +    "GENERATION_ID",
> +    "MANIFEST_DOMAIN",
> +    "ReconstructionFreezeError",
> +    "SOURCE_AUTHORIZATION_DOMAIN",
> +    "SOURCE_MANIFEST_DOMAIN",
> +    "SOURCE_ROOT",
> +    "TARGET_ROOT",
> +    "freeze_reconstruction",
> +]
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `python -B -m unittest tests.test_freeze_kpp_frozen_reconstruction_v1`
>
> </details>
>
> Freezer прошёл 6/6 TDD-проверок: он запрещает подмену v1 identity, не перезаписывает существующую цель, проверяет source manifest/authorization/media graph и создаёт физически отдельные файлы. Сейчас запускаю авторитетную материализацию полного набора (около 1,38 ГБ) и после неё независимо перепроверю каждый хеш.
>
> <details><summary>Ran 11 commands</summary>
>
> - Ran `$drive=Get-PSDrive -Name E; [pscustomobject]@{FreeGiB=[math]::Round($drive.Free/1GB,2); UsedGiB=[math]::Round($drive.Used/1GB,2)}; Test-Path -LiteralPath 'data/videos/kpp/kpp_frozen_reconstruction_v1'`
> - Ran `python -B scripts/freeze_kpp_frozen_reconstruction_v1.py --project-root E:\STUDY\VAST --authorization-basis explicit_user_instruction_2026-08-24_reconstruct_all_missing_frozen_kpp`
> - Ran `$p='configs/datasets.yaml'; Get-Content -LiteralPath $p | Select-Object -First 330; Get-Content -LiteralPath $p | Select-Object -Skip 1010 -First 500; $p='scripts/benchmark_contract.py'; Get-Content -LiteralPath $p | Select-Object -First 70; Get-Content -LiteralPath $p | Select-Object -Skip 2910 -First 90; $p='configs/experiments.yaml'; Get-Content -LiteralPath $p | Select-Object -Skip 400 -First 165`
> - Ran `$root='data/videos/kpp/kpp_frozen_reconstruction_v1'; Get-Item -LiteralPath "$root/kpp_frozen_reconstruction_v1_manifest.json","$root/kpp_frozen_reconstruction_v1_authorization_receipt.json" | ForEach-Object { [pscustomobject]@{Name=$_.Name;Size=$_.Length;Sha256=(Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()} } | ConvertTo-Json -Compress; $m=Get-Content -LiteralPath "$root/kpp_frozen_reconstruction_v1_manifest.json" -Raw | ConvertFrom-Json; [pscustomobject]@{ManifestSelf=$m.manifest_sha256;AuthSelf=$m.authorization_receipt.authorization_receipt_sha256} | ConvertTo-Json -Compress`
> - Ran `$root=(Resolve-Path 'data/videos/kpp/kpp_frozen_reconstruction_v1').Path; $manifest=Get-Content -LiteralPath "$root\kpp_frozen_reconstruction_v1_manifest.json" -Raw | ConvertFrom-Json; $rows=@(); foreach($item in $manifest.media_artifacts){ $rel=$item.path.Substring('data/videos/kpp/kpp_frozen_reconstruction_v1/'.Length).Replace('/','\'); $path=Join-Path $root $rel; $actual=(Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant(); $links=@(fsutil hardlink list $path 2>$null).Count; $rows += [pscustomobject]@{Codec=$item.codec_variant;Role=$item.role;SizeOk=((Get-Item -LiteralPath $path).Length -eq [int64]$item.size_bytes);HashOk=($actual -eq $item.sha256);HardlinkEntries=$links} }; $rows | ConvertTo-Json -Compress; if(($rows | Where-Object { -not $_.SizeOk -or -not $_.HashOk -or $_.HardlinkEntries -ne 1 }).Count -ne 0){exit 2}`
> - Ran `rg -n "camera_layout|workload.*source|recorded_source_count" scripts/benchmark_contract.py scripts/checkpoint_runtime_plan.py scripts/publication_matrix.py tests/test_benchmark_contract.py tests/test_scenario_planning.py | Select-Object -First 250`
> - Ran `rg -n "dataset_contract_version|publication_scope|analytics_routing|benchmark_playback|timestamp_contract|experimental_routing_profiles|logical_stream_instances|unique_recorded_sources" scripts/benchmark_contract.py | Select-Object -First 300`
> - Ran `$patch = @'
> *** Begin Patch
> *** Add File: tests/test_kpp_frozen_reconstruction_v1_dataset_integration.py
> +from __future__ import annotations
> +
> +import copy
> +import json
> +import sys
> +import unittest
> +from pathlib import Path
> +
> +import yaml
> +
> +
> +ROOT = Path(__file__).resolve().parents[1]
> +sys.path.insert(0, str(ROOT / "scripts"))
> +
> +import kpp_frozen_reconstruction_v1_dataset as gate  # noqa: E402
> +
> +
> +class KppFrozenReconstructionV1DatasetIntegrationTests(unittest.TestCase):
> +    @classmethod
> +    def setUpClass(cls) -> None:
> +        cls.catalog = yaml.safe_load(
> +            (ROOT / "configs" / "datasets.yaml").read_text(encoding="utf-8")
> +        )["datasets"]
> +        corpus = ROOT / gate.TARGET_ROOT
> +        cls.manifest = json.loads(
> +            (corpus / gate.MANIFEST_NAME).read_text(encoding="ascii")
> +        )
> +        cls.authorization = json.loads(
> +            (corpus / gate.AUTHORIZATION_RECEIPT_NAME).read_text(encoding="ascii")
> +        )
> +
> +    def test_catalog_has_both_distinct_publishable_reconstruction_ids(self) -> None:
> +        for codec, name in gate.DATASET_IDS.items():
> +            entry = self.catalog[name]
> +            self.assertTrue(
> +                gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
> +                    name, entry, project_root=ROOT, require_files=False
> +                )
> +            )
> +            self.assertEqual(entry["codec_variant"], codec)
> +            self.assertTrue(entry["publishable"])
> +            self.assertFalse(
> +                entry["provenance"]["claims"][
> +                    "historical_v1_dataset_identity_equivalent"
> +                ]
> +            )
> +
> +    def test_historical_entries_are_retained_but_explicitly_unavailable(self) -> None:
> +        for name in ("kpp_real_avi", "kpp_real_h264", "kpp_real_h265"):
> +            entry = self.catalog[name]
> +            self.assertFalse(entry["publishable"])
> +            self.assertEqual(entry["status"], "historical_source_bytes_unavailable")
> +            self.assertFalse(entry["availability"]["source_bytes_available"])
> +            self.assertEqual(
> +                entry["availability"]["reconstruction_generation_id"],
> +                gate.GENERATION_ID,
> +            )
> +
> +    def test_full_on_disk_corpus_and_receipt_graph_validate(self) -> None:
> +        name = gate.DATASET_IDS["h264"]
> +        self.assertTrue(
> +            gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
> +                name, self.catalog[name], project_root=ROOT, require_files=True
> +            )
> +        )
> +
> +    def test_documents_reject_resealed_historical_identity_claim(self) -> None:
> +        manifest = copy.deepcopy(self.manifest)
> +        manifest["claims"]["historical_v1_dataset_identity_equivalent"] = True
> +        with self.assertRaisesRegex(
> +            gate.KppFrozenReconstructionV1DatasetError, "historical.*identity"
> +        ):
> +            gate.validate_kpp_frozen_reconstruction_v1_documents(
> +                manifest, self.authorization
> +            )
> +
> +    def test_documents_reject_manifest_self_hash_drift(self) -> None:
> +        manifest = copy.deepcopy(self.manifest)
> +        manifest["manifest_sha256"] = "1" * 64
> +        with self.assertRaisesRegex(
> +            gate.KppFrozenReconstructionV1DatasetError, "self hash"
> +        ):
> +            gate.validate_kpp_frozen_reconstruction_v1_documents(
> +                manifest, self.authorization
> +            )
> +
> +    def test_gate_ignores_unrelated_dataset(self) -> None:
> +        self.assertFalse(
> +            gate.validate_kpp_frozen_reconstruction_v1_manifest_entry(
> +                "smoke_testsrc",
> +                self.catalog["smoke_testsrc"],
> +                project_root=ROOT,
> +                require_files=False,
> +            )
> +        )
> +
> +
> +if __name__ == "__main__":
> +    unittest.main()
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `python -B -m unittest tests.test_kpp_frozen_reconstruction_v1_dataset_integration`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_kpp_frozen_reconstruction_v1_dataset_integration"`
> - Ran `$patch = @'
> *** Begin Patch
> *** Add File: scripts/kpp_frozen_reconstruction_v1_dataset.py
> +#!/usr/bin/env python3
> +"""Fail-closed catalog and filesystem gate for KPP reconstruction v1."""
> +
> +from __future__ import annotations
> +
> +import copy
> +from collections.abc import Mapping
> +from pathlib import Path, PurePosixPath
> +
> +from freeze_kpp_frozen_reconstruction_v1 import (
> +    AUTHORIZATION_BASIS_ID,
> +    AUTHORIZATION_RECEIPT_DOMAIN,
> +    AUTHORIZATION_RECEIPT_NAME,
> +    DATASET_IDS,
> +    GENERATION_ID,
> +    HISTORICAL_DATASET_IDS,
> +    MANIFEST_DOMAIN,
> +    MANIFEST_NAME,
> +    SOURCE_AUTHORIZATION_NAME,
> +    SOURCE_DATASET_IDS,
> +    SOURCE_GENERATION_ID,
> +    SOURCE_MANIFEST_NAME,
> +    SOURCE_MEDIA,
> +    SOURCE_RECEIPTS,
> +    TARGET_ROOT,
> +    _canonical_bytes,
> +    _claims,
> +    _historical_v1,
> +    _receipt_self_hash,
> +    _stable_payload,
> +    _strict_json,
> +    _validate_tree,
> +)
> +from freeze_kpp_iss_publication_v3 import PublicationCorpusFreezeError
> +
> +
> +PUBLICATION_SCOPE = "performance_and_topology_benchmark_results_only"
> +EXPECTED_MANIFEST_DESCRIPTOR = {
> +    "path": f"{TARGET_ROOT}/{MANIFEST_NAME}",
> +    "size_bytes": 5751,
> +    "file_sha256": "043cb90be4a16bbc0d636236a6a2c5d2c63f187d94aadf8358c9871bf8e6751a",
> +    "manifest_sha256": "faf79f71bb53356f95155491a560ca73bb321f9342712e5fab6bc45f7cee5cff",
> +}
> +EXPECTED_AUTHORIZATION_DESCRIPTOR = {
> +    "path": f"{TARGET_ROOT}/{AUTHORIZATION_RECEIPT_NAME}",
> +    "size_bytes": 2431,
> +    "sha256": "9eec424ef1112efc46283d9dd644782d3e6f67184f32cda7eada73c8bbfec803",
> +    "authorization_receipt_sha256": (
> +        "c6570bbcaf1f8daea450f8510b5141b781d715ecdc0995ed4f3ae5350f7b0f53"
> +    ),
> +}
> +
> +
> +class KppFrozenReconstructionV1DatasetError(RuntimeError):
> +    """Raised when reconstruction identity or bytes do not verify."""
> +
> +
> +def _fail(message: str) -> None:
> +    raise KppFrozenReconstructionV1DatasetError(message)
> +
> +
> +def _target_media(codec: str, role: str) -> dict[str, object]:
> +    source = SOURCE_MEDIA[(codec, role)]
> +    return {
> +        "codec_variant": codec,
> +        "role": role,
> +        "source_path": source["source_path"],
> +        "path": f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4",
> +        "size_bytes": source["size_bytes"],
> +        "sha256": source["sha256"],
> +    }
> +
> +
> +def _source_documents() -> dict[str, object]:
> +    return {
> +        "manifest": {
> +            "source_path": f"data/videos/kpp/kpp_iss_publication_v3/{SOURCE_MANIFEST_NAME}",
> +            "path": f"{TARGET_ROOT}/receipts/{SOURCE_MANIFEST_NAME}",
> +            "size_bytes": 7225,
> +            "sha256": "9a9cf3e08be159bfd4bdeda1d9323b13102980322bde03d9b061e749c1d3fa24",
> +            "manifest_sha256": "bbe2cca51cdcc95651492e0f28fc95ed00b9106dce73b5995280259701c91cc2",
> +        },
> +        "authorization": {
> +            "source_path": f"data/videos/kpp/kpp_iss_publication_v3/{SOURCE_AUTHORIZATION_NAME}",
> +            "path": f"{TARGET_ROOT}/receipts/{SOURCE_AUTHORIZATION_NAME}",
> +            "size_bytes": 3300,
> +            "sha256": "eee7a49472077ff83bd9a9f3cc67a462c4441b0c841bc64d75859271333732ee",
> +            "authorization_receipt_sha256": (
> +                "11678b26210c4ae514535b399afa3ed9f1b412d116d9708c1a94af606cd03d2a"
> +            ),
> +        },
> +    }
> +
> +
> +def _source_publication() -> dict[str, object]:
> +    return {
> +        "generation_id": SOURCE_GENERATION_ID,
> +        "dataset_ids": copy.deepcopy(SOURCE_DATASET_IDS),
> +        "generation_identity_equivalent": False,
> +        "media_bytes_reused_exactly": True,
> +        **_source_documents(),
> +    }
> +
> +
> +def _installed_receipts() -> list[dict[str, object]]:
> +    return [
> +        {
> +            "source_path": item["source_path"],
> +            "path": f"{TARGET_ROOT}/receipts/{item['installed_name']}",
> +            "size_bytes": item["size_bytes"],
> +            "sha256": item["sha256"],
> +        }
> +        for item in SOURCE_RECEIPTS
> +    ]
> +
> +
> +def _datasets() -> list[dict[str, object]]:
> +    return [
> +        {
> +            "dataset_id": DATASET_IDS[codec],
> +            "codec_variant": codec,
> +            "publication_scope": PUBLICATION_SCOPE,
> +            "accuracy_ground_truth": False,
> +            "production_routing_validated": False,
> +            "historical_v1_identity_equivalent": False,
> +            "physical_stream_paths": [
> +                f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4"
> +                for role in ("underbody", "front_gate")
> +            ],
> +        }
> +        for codec in ("h264", "h265")
> +    ]
> +
> +
> +def validate_kpp_frozen_reconstruction_v1_documents(
> +    manifest: Mapping[str, object], authorization: Mapping[str, object]
> +) -> bool:
> +    """Validate claim-bearing reconstruction documents without filesystem I/O."""
> +
> +    if type(manifest) is not dict or set(manifest) != {
> +        "schema_version",
> +        "artifact_kind",
> +        "generation_id",
> +        "status",
> +        "dataset_root",
> +        "dataset_ids",
> +        "datasets",
> +        "historical_v1",
> +        "source_publication",
> +        "source_receipts",
> +        "media_artifacts",
> +        "authorization_receipt",
> +        "claims",
> +        "manifest_sha256",
> +    }:
> +        _fail("reconstruction manifest schema is not exact")
> +    if manifest.get("claims") != _claims():
> +        if isinstance(manifest.get("claims"), Mapping) and manifest["claims"].get(
> +            "historical_v1_dataset_identity_equivalent"
> +        ) is not False:
> +            _fail("historical v1 identity claim is forbidden")
> +        _fail("reconstruction manifest claims drifted")
> +    expected_manifest = {
> +        "schema_version": 1,
> +        "artifact_kind": "vast_kpp_frozen_reconstruction_v1_manifest",
> +        "generation_id": GENERATION_ID,
> +        "status": "frozen_distinct_reconstruction",
> +        "dataset_root": TARGET_ROOT,
> +        "dataset_ids": copy.deepcopy(DATASET_IDS),
> +        "datasets": _datasets(),
> +        "historical_v1": _historical_v1(),
> +        "source_publication": _source_publication(),
> +        "source_receipts": _installed_receipts(),
> +        "media_artifacts": [
> +            _target_media(codec, role)
> +            for codec in ("h264", "h265")
> +            for role in ("underbody", "front_gate")
> +        ],
> +        "authorization_receipt": copy.deepcopy(EXPECTED_AUTHORIZATION_DESCRIPTOR),
> +        "claims": _claims(),
> +        "manifest_sha256": EXPECTED_MANIFEST_DESCRIPTOR["manifest_sha256"],
> +    }
> +    if manifest != expected_manifest:
> +        _fail("reconstruction manifest identity or graph drifted")
> +    computed_manifest = _receipt_self_hash(
> +        manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
> +    )
> +    if computed_manifest != manifest["manifest_sha256"]:
> +        _fail("reconstruction manifest self hash drifted")
> +
> +    if type(authorization) is not dict or set(authorization) != {
> +        "schema_version",
> +        "artifact_kind",
> +        "generation_id",
> +        "dataset_ids",
> +        "status",
> +        "authorization_basis",
> +        "historical_v1",
> +        "source_publication",
> +        "claims",
> +        "authorization_receipt_sha256",
> +    }:
> +        _fail("reconstruction authorization schema is not exact")
> +    expected_authorization = {
> +        "schema_version": 1,
> +        "artifact_kind": "vast_kpp_frozen_reconstruction_v1_authorization_receipt",
> +        "generation_id": GENERATION_ID,
> +        "dataset_ids": copy.deepcopy(DATASET_IDS),
> +        "status": "authorized_reconstruction_for_performance_publication",
> +        "authorization_basis": {
> +            "kind": "explicit_user_instruction",
> +            "basis_id": AUTHORIZATION_BASIS_ID,
> +            "authorized_scope": PUBLICATION_SCOPE,
> +            "excluded_scopes": [
> +                "accuracy_evaluation",
> +                "production_routing_validation",
> +                "historical_v1_identity_equivalence",
> +            ],
> +        },
> +        "historical_v1": _historical_v1(),
> +        "source_publication": _source_publication(),
> +        "claims": _claims(),
> +        "authorization_receipt_sha256": EXPECTED_AUTHORIZATION_DESCRIPTOR[
> +            "authorization_receipt_sha256"
> +        ],
> +    }
> +    if authorization != expected_authorization:
> +        _fail("reconstruction authorization identity or claims drifted")
> +    computed_authorization = _receipt_self_hash(
> +        authorization,
> +        field="authorization_receipt_sha256",
> +        domain=AUTHORIZATION_RECEIPT_DOMAIN,
> +    )
> +    if computed_authorization != authorization["authorization_receipt_sha256"]:
> +        _fail("reconstruction authorization self hash drifted")
> +    return True
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/kpp_frozen_reconstruction_v1_dataset.py
> @@
>  def validate_kpp_frozen_reconstruction_v1_documents(
> @@
>      if computed_authorization != authorization["authorization_receipt_sha256"]:
>          _fail("reconstruction authorization self hash drifted")
>      return True
> +
> +
> +def _stream_expectations(codec: str) -> list[dict[str, object]]:
> +    result = []
> +    roles = ("plate_number", "plate_number", "vehicle_type", "damage", "damage")
> +    for stream_id in range(6):
> +        underbody = stream_id == 5
> +        role = "underbody" if underbody else "front_gate"
> +        result.append(
> +            {
> +                "stream_id": stream_id,
> +                "camera_role": "foreign_object" if underbody else roles[stream_id],
> +                "path": f"{TARGET_ROOT}/{codec}/iss_v2_{role}.mp4",
> +                "sha256": SOURCE_MEDIA[(codec, role)]["sha256"],
> +                "codec_name": "h264" if codec == "h264" else "hevc",
> +                "width": 1700 if underbody else 1920,
> +                "height": 236 if underbody else 1080,
> +                "frame_count": 35646 if underbody else 33120,
> +            }
> +        )
> +    return result
> +
> +
> +def _validate_entry(name: str, entry: Mapping[str, object]) -> str:
> +    inverse = {dataset_id: codec for codec, dataset_id in DATASET_IDS.items()}
> +    codec = inverse.get(name)
> +    if codec is None:
> +        _fail(f"unknown reconstruction dataset {name!r}")
> +    if not isinstance(entry, Mapping):
> +        _fail(f"dataset {name!r} is not an object")
> +    expected_scalars = {
> +        "kind": "frozen_reconstruction_codec_corpus",
> +        "generation_id": GENERATION_ID,
> +        "status": "frozen_distinct_reconstruction",
> +        "publishable": True,
> +        "publication_scope": PUBLICATION_SCOPE,
> +        "codec_variant": codec,
> +        "analytics_routing": "unresolved",
> +        "logical_stream_instances": 6,
> +        "unique_recorded_sources": 2,
> +        "fps_policy": "cfr_600_from_source_pts",
> +        "source_dataset": SOURCE_DATASET_IDS[codec],
> +    }
> +    for field, expected in expected_scalars.items():
> +        if entry.get(field) != expected:
> +            _fail(f"dataset {name!r} field {field!r} drifted")
> +    preparation = entry.get("preparation")
> +    if not isinstance(preparation, Mapping) or dict(preparation) != {
> +        "mode": "check_only_frozen_reconstruction_v1",
> +        "reconstruction_manifest": copy.deepcopy(EXPECTED_MANIFEST_DESCRIPTOR),
> +    }:
> +        _fail(f"dataset {name!r} preparation gate drifted")
> +    provenance = entry.get("provenance")
> +    expected_provenance = {
> +        "schema_version": 1,
> +        "artifact_kind": "vast_kpp_frozen_reconstruction_v1_dataset_provenance",
> +        "generation_id": GENERATION_ID,
> +        "reconstruction_manifest": copy.deepcopy(EXPECTED_MANIFEST_DESCRIPTOR),
> +        "authorization_receipt": copy.deepcopy(EXPECTED_AUTHORIZATION_DESCRIPTOR),
> +        "historical_v1": _historical_v1(),
> +        "source_publication": {
> +            "generation_id": SOURCE_GENERATION_ID,
> +            "dataset_id": SOURCE_DATASET_IDS[codec],
> +            "generation_identity_equivalent": False,
> +            "media_bytes_reused_exactly": True,
> +        },
> +        "media_artifacts": [
> +            _target_media(codec, role) for role in ("underbody", "front_gate")
> +        ],
> +        "claims": _claims(),
> +    }
> +    if not isinstance(provenance, Mapping) or dict(provenance) != expected_provenance:
> +        _fail(f"dataset {name!r} provenance drifted")
> +    streams = entry.get("streams")
> +    if type(streams) is not list or len(streams) != 6:
> +        _fail(f"dataset {name!r} stream set is not exact")
> +    for raw, expected in zip(streams, _stream_expectations(codec), strict=True):
> +        if type(raw) is not dict:
> +            _fail(f"dataset {name!r} stream is invalid")
> +        for field, value in expected.items():
> +            if raw.get(field) != value:
> +                _fail(f"dataset {name!r} stream {expected['stream_id']} drifted")
> +    return codec
> +
> +
> +def _read_pinned_json(
> +    root: Path, descriptor: Mapping[str, object], *, label: str, hash_field: str
> +):
> +    path = root.joinpath(*PurePosixPath(str(descriptor["path"])).parts)
> +    try:
> +        size, digest, payload = _stable_payload(path, label=label, retain=True)
> +        if size != descriptor["size_bytes"] or digest != descriptor[hash_field]:
> +            _fail(f"{label} byte pin drifted")
> +        assert payload is not None
> +        return _strict_json(payload, label=label)
> +    except PublicationCorpusFreezeError as exc:
> +        raise KppFrozenReconstructionV1DatasetError(str(exc)) from exc
> +
> +
> +def _verify_descriptor(root: Path, descriptor: Mapping[str, object], *, label: str):
> +    path = root.joinpath(*PurePosixPath(str(descriptor["path"])).parts)
> +    try:
> +        size, digest, _ = _stable_payload(path, label=label, retain=False)
> +    except PublicationCorpusFreezeError as exc:
> +        raise KppFrozenReconstructionV1DatasetError(str(exc)) from exc
> +    if size != descriptor["size_bytes"] or digest != descriptor["sha256"]:
> +        _fail(f"{label} byte pin drifted")
> +
> +
> +def validate_kpp_frozen_reconstruction_v1_manifest_entry(
> +    name: str,
> +    entry: Mapping[str, object],
> +    *,
> +    project_root: Path,
> +    require_files: bool,
> +) -> bool:
> +    """Validate one reconstruction entry; ignore every unrelated dataset."""
> +
> +    if name not in DATASET_IDS.values():
> +        return False
> +    codec = _validate_entry(name, entry)
> +    if not require_files:
> +        return True
> +    root = project_root.absolute()
> +    corpus = root.joinpath(*PurePosixPath(TARGET_ROOT).parts)
> +    try:
> +        _validate_tree(corpus, SOURCE_RECEIPTS)
> +    except (OSError, ReconstructionFreezeError) as exc:  # type: ignore[name-defined]
> +        raise KppFrozenReconstructionV1DatasetError(str(exc)) from exc
> +    manifest = _read_pinned_json(
> +        root,
> +        EXPECTED_MANIFEST_DESCRIPTOR,
> +        label="reconstruction manifest",
> +        hash_field="file_sha256",
> +    )
> +    authorization = _read_pinned_json(
> +        root,
> +        EXPECTED_AUTHORIZATION_DESCRIPTOR,
> +        label="reconstruction authorization",
> +        hash_field="sha256",
> +    )
> +    validate_kpp_frozen_reconstruction_v1_documents(manifest, authorization)
> +    for descriptor in manifest["media_artifacts"]:
> +        _verify_descriptor(root, descriptor, label="reconstruction media")
> +    for descriptor in manifest["source_receipts"]:
> +        _verify_descriptor(root, descriptor, label="reconstruction source receipt")
> +    source = manifest["source_publication"]
> +    for role in ("manifest", "authorization"):
> +        _verify_descriptor(root, source[role], label=f"embedded source {role}")
> +    selected = [_target_media(codec, role) for role in ("underbody", "front_gate")]
> +    if entry["provenance"]["media_artifacts"] != selected:
> +        _fail(f"dataset {name!r} selected media drifted")
> +    return True
> +
> +
> +__all__ = [
> +    "AUTHORIZATION_RECEIPT_NAME",
> +    "DATASET_IDS",
> +    "EXPECTED_AUTHORIZATION_DESCRIPTOR",
> +    "EXPECTED_MANIFEST_DESCRIPTOR",
> +    "GENERATION_ID",
> +    "KppFrozenReconstructionV1DatasetError",
> +    "MANIFEST_NAME",
> +    "TARGET_ROOT",
> +    "validate_kpp_frozen_reconstruction_v1_documents",
> +    "validate_kpp_frozen_reconstruction_v1_manifest_entry",
> +]
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/kpp_frozen_reconstruction_v1_dataset.py
> @@
>      MANIFEST_NAME,
> +    ReconstructionFreezeError,
> @@
> -    _canonical_bytes,
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `python -B -m py_compile scripts/freeze_kpp_frozen_reconstruction_v1.py scripts/kpp_frozen_reconstruction_v1_dataset.py`
> - Ran `Get-ChildItem -LiteralPath scripts/__pycache__ -Filter '*kpp*frozen*reconstruction*v1*.pyc' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName`
> - Ran `Remove-Item -LiteralPath 'E:\STUDY\VAST\scripts\__pycache__\freeze_kpp_frozen_reconstruction_v1.cpython-314.pyc','E:\STUDY\VAST\scripts\__pycache__\kpp_frozen_reconstruction_v1_dataset.cpython-314.pyc' -Force`
>
> </details>
>
> <details><summary>Ran 8 commands</summary>
>
> - Ran `Get-Content -LiteralPath configs/datasets.yaml | Select-Object -Last 80; rg -n "^  kpp_real_(avi|h264|h265):|^    publishable:" configs/datasets.yaml | Select-Object -First 40`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
>    kpp_real_avi:
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> @@
>    kpp_real_h264:
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> @@
>    kpp_real_h265:
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$p='configs/datasets.yaml'; Get-Content -LiteralPath $p | Select-Object -Skip 12 -First 18; Get-Content -LiteralPath $p | Select-Object -Skip 116 -First 18; Get-Content -LiteralPath $p | Select-Object -Skip 246 -First 18`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
>    kpp_real_avi:
>      kind: real_avi
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
>    kpp_real_h264:
>      kind: real_codec_transcode
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> @@
>    kpp_real_h265:
>      kind: real_codec_transcode
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `rg -n -A 8 -B 1 "^  kpp_real_h264:|^  kpp_real_h265:" configs/datasets.yaml`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
>    kpp_real_h264:
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
>    kpp_real_h265:
> @@
> -    publishable: true
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `$names='kpp_real_avi','kpp_real_h264','kpp_real_h265','kpp_iss_publication_v3_h264','kpp_iss_publication_v3_h265'; $yaml=Get-Content -LiteralPath configs/datasets.yaml -Raw; foreach($name in $names){ $m=[regex]::Match($yaml,"(?ms)^  $([regex]::Escape($name)):\r?\n(?<body>.*?)(?=^  [a-zA-Z0-9_]+:|\z)"); $p=[regex]::Match($m.Groups['body'].Value,'(?m)^    publishable: (?<v>\S+)').Groups['v'].Value; $s=[regex]::Match($m.Groups['body'].Value,'(?m)^    status: (?<v>\S+)').Groups['v'].Value; [pscustomobject]@{Name=$name;Publishable=$p;Status=$s} } | Format-Table -AutoSize`
> - Ran `rg -n -A 8 "^  kpp_real_avi:|^  kpp_real_h264:|^  kpp_real_h265:|^  kpp_iss_publication_v3_h264:|^  kpp_iss_publication_v3_h265:" configs/datasets.yaml`
> - Ran `rg -n -B 6 -A 8 "historical_source_bytes_unavailable" configs/datasets.yaml; rg -n "^    publishable:" configs/datasets.yaml`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
> -    description: Source real checkpoint AVI captures used to derive publishable H.264/H.265
> -      codec datasets.
> -    publishable: true
> +    description: Historical source real checkpoint AVI captures. The externally
> +      pinned bytes are unavailable locally; a distinct reconstruction is cataloged
> +      separately and does not claim identity equivalence.
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> @@
> -    description: Real checkpoint captures transcoded to H.264/AVC MP4 at 600 FPS CFR
> -      for publishable KPP codec benchmarks.
> -    publishable: true
> +    description: Historical H.264 transcodes whose externally pinned source bytes
> +      are unavailable locally; retained only as an immutable identity record.
> +    publishable: false
> +    status: historical_source_bytes_unavailable
> +    availability:
> +      source_bytes_available: false
> +      historical_identity_recovered: false
> +      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_is_identity_substitute: false
> @@
> -    publication_scope: performance_and_topology_benchmark_results_only
> -    publishable: false
> -    status: historical_source_bytes_unavailable
> -    availability:
> -      source_bytes_available: false
> -      historical_identity_recovered: false
> -      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> -      reconstruction_is_identity_substitute: false
> -    source_dataset: kpp_legacy_iss_v2_h264
> -    status: frozen_publication_corpus
> +    publication_scope: performance_and_topology_benchmark_results_only
> +    publishable: true
> +    source_dataset: kpp_legacy_iss_v2_h264
> +    status: frozen_publication_corpus
> @@
> -    publication_scope: performance_and_topology_benchmark_results_only
> -    publishable: false
> -    status: historical_source_bytes_unavailable
> -    availability:
> -      source_bytes_available: false
> -      historical_identity_recovered: false
> -      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> -      reconstruction_is_identity_substitute: false
> -    source_dataset: kpp_legacy_iss_v2_h265
> -    status: frozen_publication_corpus
> +    publication_scope: performance_and_topology_benchmark_results_only
> +    publishable: true
> +    source_dataset: kpp_legacy_iss_v2_h265
> +    status: frozen_publication_corpus
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
> -    description: Real checkpoint captures transcoded to H.265/HEVC MP4 at 600 FPS
> -      CFR for publishable KPP codec benchmarks.
> +    description: Historical H.265 transcodes whose externally pinned source bytes
> +      are unavailable locally; retained only as an immutable identity record.
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `rg -n -A 11 "^  kpp_real_avi:|^  kpp_real_h264:|^  kpp_real_h265:" configs/datasets.yaml; rg -n -B 2 -A 3 "^    source_dataset: kpp_legacy_iss_v2_h26[45]" configs/datasets.yaml`
>
> </details>
>
> Материализованный reconstruction независимо проверен: все четыре media-файла совпали по размеру и SHA-256, у каждого ровно одна NTFS hardlink-запись. Также исправил каталог так, чтобы только действительно отсутствующие historical `kpp_real_*` стали non-publishable; активные publication-v3 снова подтверждены как publishable.
>
> <details><summary>Ran 17 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
> -    unique_recorded_sources: 2
> -    workload_scope: replicated_logical_streams_from_two_recordings
> -  mot17_uadetrac_public:
> +    unique_recorded_sources: 2
> +    workload_scope: replicated_logical_streams_from_two_recordings
> +  kpp_frozen_reconstruction_v1_h264:
> +    analytics_routing: unresolved
> +    benchmark_playback: &kpp_reconstruction_playback
> +      contract_version: 1
> +      encoded_timeline_fps: 600
> +      offered_playback_fps: 1
> +      selection_basis: distinct_reconstruction_from_exact_publication_v3_media_before_full_matrix
> +      timestamp_scale: 600
> +    codec_variant: h264
> +    dataset_contract_version: 1
> +    description: Distinct frozen KPP reconstruction created because the historical
> +      v1 bytes are unavailable; authorized only for performance and topology results.
> +    experimental_routing_profiles:
> +    - name: architecture_reuse_all_branches_v1
> +      production_semantics: false
> +      routing_mode: all_branches_per_stream
> +      scope: topology_only_stress
> +    fps_policy: cfr_600_from_source_pts
> +    generation_id: kpp_frozen_reconstruction_v1
> +    kind: frozen_reconstruction_codec_corpus
> +    lineage:
> +      identity_equivalent: false
> +      predecessor_dataset: kpp_iss_publication_v3_h264
> +      reason: distinct_reconstruction_reusing_exact_receipt_pinned_media_bytes
> +    logical_stream_instances: 6
> +    preparation:
> +      mode: check_only_frozen_reconstruction_v1
> +      reconstruction_manifest: &kpp_reconstruction_manifest
> +        path: data/videos/kpp/kpp_frozen_reconstruction_v1/kpp_frozen_reconstruction_v1_manifest.json
> +        size_bytes: 5751
> +        file_sha256: 043cb90be4a16bbc0d636236a6a2c5d2c63f187d94aadf8358c9871bf8e6751a
> +        manifest_sha256: faf79f71bb53356f95155491a560ca73bb321f9342712e5fab6bc45f7cee5cff
> +    provenance:
> +      schema_version: 1
> +      artifact_kind: vast_kpp_frozen_reconstruction_v1_dataset_provenance
> +      generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_manifest: *kpp_reconstruction_manifest
> +      authorization_receipt: &kpp_reconstruction_authorization
> +        path: data/videos/kpp/kpp_frozen_reconstruction_v1/kpp_frozen_reconstruction_v1_authorization_receipt.json
> +        size_bytes: 2431
> +        sha256: 9eec424ef1112efc46283d9dd644782d3e6f67184f32cda7eada73c8bbfec803
> +        authorization_receipt_sha256: c6570bbcaf1f8daea450f8510b5141b781d715ecdc0995ed4f3ae5350f7b0f53
> +      historical_v1: &kpp_reconstruction_historical
> +        dataset_ids:
> +        - kpp_real_avi
> +        - kpp_real_h264
> +        - kpp_real_h265
> +        source_bytes_available: false
> +        identity_recovered: false
> +        reconstruction_is_identity_substitute: false
> +      source_publication:
> +        generation_id: kpp_iss_publication_v3
> +        dataset_id: kpp_iss_publication_v3_h264
> +        generation_identity_equivalent: false
> +        media_bytes_reused_exactly: true
> +      media_artifacts:
> +      - codec_variant: h264
> +        role: underbody
> +        source_path: data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_underbody.mp4
> +        path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_underbody.mp4
> +        size_bytes: 1079445865
> +        sha256: b7e5165549172266a5617ff7bbca6e5b888775b0a2490e27b7cbe17640e3b102
> +      - codec_variant: h264
> +        role: front_gate
> +        source_path: data/videos/kpp/kpp_iss_publication_v3/h264/iss_v2_front_gate.mp4
> +        path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_front_gate.mp4
> +        size_bytes: 63131711
> +        sha256: 08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273
> +      claims: &kpp_reconstruction_claims
> +        publication_authorized: true
> +        publication_scope_performance_and_topology_only: true
> +        accuracy_ground_truth_validated: false
> +        production_routing_validated: false
> +        historical_v1_source_bytes_recovered: false
> +        historical_v1_dataset_identity_equivalent: false
> +        reconstruction_identity_distinct: true
> +        media_reused_without_retranscode: true
> +        source_v3_receipt_graph_exactly_pinned: true
> +        all_copied_bytes_verified: true
> +        output_set_directory_published_atomically: true
> +    publication_scope: performance_and_topology_benchmark_results_only
> +    publishable: true
> +    source_dataset: kpp_iss_publication_v3_h264
> +    status: frozen_distinct_reconstruction
> +    streams:
> +    - stream_id: 0
> +      camera_role: plate_number
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_front_gate.mp4
> +      sha256: 08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: h264
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 1
> +      camera_role: plate_number
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_front_gate.mp4
> +      sha256: 08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: h264
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 2
> +      camera_role: vehicle_type
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_front_gate.mp4
> +      sha256: 08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: h264
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 3
> +      camera_role: damage
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_front_gate.mp4
> +      sha256: 08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: h264
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 4
> +      camera_role: damage
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_front_gate.mp4
> +      sha256: 08991b572d2d990a07536c9a4a7eed7780b27127c0e38abe7b607ba97dd59273
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: h264
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 5
> +      camera_role: foreign_object
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h264/iss_v2_underbody.mp4
> +      sha256: b7e5165549172266a5617ff7bbca6e5b888775b0a2490e27b7cbe17640e3b102
> +      source_id: kpp_reconstruction_underbody
> +      container: mp4
> +      codec_name: h264
> +      width: 1700
> +      height: 236
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 59.41
> +      frame_count: 35646
> +    unique_recorded_sources: 2
> +    workload_scope: replicated_logical_streams_from_two_recordings
> +  mot17_uadetrac_public:
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
> -    unique_recorded_sources: 2
> -    workload_scope: replicated_logical_streams_from_two_recordings
> -  mot17_uadetrac_public:
> +    unique_recorded_sources: 2
> +    workload_scope: replicated_logical_streams_from_two_recordings
> +  kpp_frozen_reconstruction_v1_h265:
> +    analytics_routing: unresolved
> +    benchmark_playback: *kpp_reconstruction_playback
> +    codec_variant: h265
> +    dataset_contract_version: 1
> +    description: Distinct frozen KPP reconstruction created because the historical
> +      v1 bytes are unavailable; authorized only for performance and topology results.
> +    experimental_routing_profiles:
> +    - name: architecture_reuse_all_branches_v1
> +      production_semantics: false
> +      routing_mode: all_branches_per_stream
> +      scope: topology_only_stress
> +    fps_policy: cfr_600_from_source_pts
> +    generation_id: kpp_frozen_reconstruction_v1
> +    kind: frozen_reconstruction_codec_corpus
> +    lineage:
> +      identity_equivalent: false
> +      predecessor_dataset: kpp_iss_publication_v3_h265
> +      reason: distinct_reconstruction_reusing_exact_receipt_pinned_media_bytes
> +    logical_stream_instances: 6
> +    preparation:
> +      mode: check_only_frozen_reconstruction_v1
> +      reconstruction_manifest: *kpp_reconstruction_manifest
> +    provenance:
> +      schema_version: 1
> +      artifact_kind: vast_kpp_frozen_reconstruction_v1_dataset_provenance
> +      generation_id: kpp_frozen_reconstruction_v1
> +      reconstruction_manifest: *kpp_reconstruction_manifest
> +      authorization_receipt: *kpp_reconstruction_authorization
> +      historical_v1: *kpp_reconstruction_historical
> +      source_publication:
> +        generation_id: kpp_iss_publication_v3
> +        dataset_id: kpp_iss_publication_v3_h265
> +        generation_identity_equivalent: false
> +        media_bytes_reused_exactly: true
> +      media_artifacts:
> +      - codec_variant: h265
> +        role: underbody
> +        source_path: data/videos/kpp/kpp_iss_publication_v3/h265/iss_v2_underbody.mp4
> +        path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_underbody.mp4
> +        size_bytes: 223684192
> +        sha256: 5368c94a26659c529106724427fc6c3e60fe6788d56699da14c93bc4222e7839
> +      - codec_variant: h265
> +        role: front_gate
> +        source_path: data/videos/kpp/kpp_iss_publication_v3/h265/iss_v2_front_gate.mp4
> +        path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_front_gate.mp4
> +        size_bytes: 14910770
> +        sha256: fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728
> +      claims: *kpp_reconstruction_claims
> +    publication_scope: performance_and_topology_benchmark_results_only
> +    publishable: true
> +    source_dataset: kpp_iss_publication_v3_h265
> +    status: frozen_distinct_reconstruction
> +    streams:
> +    - stream_id: 0
> +      camera_role: plate_number
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_front_gate.mp4
> +      sha256: fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: hevc
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 1
> +      camera_role: plate_number
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_front_gate.mp4
> +      sha256: fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: hevc
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 2
> +      camera_role: vehicle_type
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_front_gate.mp4
> +      sha256: fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: hevc
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 3
> +      camera_role: damage
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_front_gate.mp4
> +      sha256: fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: hevc
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 4
> +      camera_role: damage
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_front_gate.mp4
> +      sha256: fa400ecc8b84afc8144fac1da522ef3e9e321c7feb89a5086ac1a1e3ccbe7728
> +      source_id: kpp_reconstruction_front_gate
> +      container: mp4
> +      codec_name: hevc
> +      width: 1920
> +      height: 1080
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 55.2
> +      frame_count: 33120
> +    - stream_id: 5
> +      camera_role: foreign_object
> +      path: data/videos/kpp/kpp_frozen_reconstruction_v1/h265/iss_v2_underbody.mp4
> +      sha256: 5368c94a26659c529106724427fc6c3e60fe6788d56699da14c93bc4222e7839
> +      source_id: kpp_reconstruction_underbody
> +      container: mp4
> +      codec_name: hevc
> +      width: 1700
> +      height: 236
> +      r_frame_rate: 600/1
> +      avg_frame_rate: 600/1
> +      duration_s: 59.41
> +      frame_count: 35646
> +    unique_recorded_sources: 2
> +    workload_scope: replicated_logical_streams_from_two_recordings
> +  mot17_uadetrac_public:
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_kpp_frozen_reconstruction_v1_dataset_integration"`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/kpp_frozen_reconstruction_v1_dataset.py
> @@
>      if manifest.get("claims") != _claims():
> @@
>              _fail("historical v1 identity claim is forbidden")
>          _fail("reconstruction manifest claims drifted")
> +    computed_manifest = _receipt_self_hash(
> +        manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
> +    )
> +    if computed_manifest != manifest.get("manifest_sha256"):
> +        _fail("reconstruction manifest self hash drifted")
>      expected_manifest = {
> @@
>      }
>      if manifest != expected_manifest:
>          _fail("reconstruction manifest identity or graph drifted")
> -    computed_manifest = _receipt_self_hash(
> -        manifest, field="manifest_sha256", domain=MANIFEST_DOMAIN
> -    )
> -    if computed_manifest != manifest["manifest_sha256"]:
> -        _fail("reconstruction manifest self hash drifted")
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_freeze_kpp_frozen_reconstruction_v1 tests.test_kpp_frozen_reconstruction_v1_dataset_integration"`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: tests/test_freeze_kpp_frozen_reconstruction_v1.py
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: tests/test_kpp_frozen_reconstruction_v1_dataset_integration.py
> @@
>  import kpp_frozen_reconstruction_v1_dataset as gate  # noqa: E402
> +from benchmark_contract import ContractError, load_dataset  # noqa: E402
> @@
>      def test_gate_ignores_unrelated_dataset(self) -> None:
> @@
>          )
> +
> +    def test_benchmark_loader_invokes_reconstruction_gate(self) -> None:
> +        entry = copy.deepcopy(self.catalog[gate.DATASET_IDS["h264"]])
> +        entry["provenance"]["claims"][
> +            "historical_v1_dataset_identity_equivalent"
> +        ] = True
> +        import tempfile
> +
> +        with tempfile.TemporaryDirectory() as tmp:
> +            manifest_path = Path(tmp) / "datasets.yaml"
> +            manifest_path.write_text(
> +                yaml.safe_dump({"datasets": {gate.DATASET_IDS["h264"]: entry}}),
> +                encoding="utf-8",
> +            )
> +            with self.assertRaisesRegex(ContractError, "provenance"):
> +                load_dataset(
> +                    manifest_path,
> +                    gate.DATASET_IDS["h264"],
> +                    mode="benchmark",
> +                    project_root=ROOT,
> +                    require_files=False,
> +                )
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_kpp_frozen_reconstruction_v1_dataset_integration.KppFrozenReconstructionV1DatasetIntegrationTests.test_benchmark_loader_invokes_reconstruction_gate"`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/benchmark_contract.py
> @@
>  from kpp_iss_publication_v3_dataset import (
>      KppIssPublicationV3DatasetError,
>      validate_kpp_iss_publication_v3_manifest_entry,
>  )
> +from kpp_frozen_reconstruction_v1_dataset import (
> +    KppFrozenReconstructionV1DatasetError,
> +    validate_kpp_frozen_reconstruction_v1_manifest_entry,
> +)
> @@
>          validate_kpp_iss_publication_v3_manifest_entry(
>              dataset_name,
>              dataset,
>              project_root=project_root,
>              require_files=require_files,
>          )
> -    except (KppLegacyIssV2ManifestError, KppIssPublicationV3DatasetError) as exc:
> +        validate_kpp_frozen_reconstruction_v1_manifest_entry(
> +            dataset_name,
> +            dataset,
> +            project_root=project_root,
> +            require_files=require_files,
> +        )
> +    except (
> +        KppLegacyIssV2ManifestError,
> +        KppIssPublicationV3DatasetError,
> +        KppFrozenReconstructionV1DatasetError,
> +    ) as exc:
>          raise ContractError(str(exc)) from exc
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `rg -n "def execute|return \{|resource|cuda_transfer_intervals|analytics bridge" scripts/checkpoint_gstreamer_analytics_bridge.py tests/test_checkpoint_gstreamer_analytics_bridge.py tests/test_analytics_execution_worker.py | Select-Object -First 300; $p='scripts/checkpoint_gstreamer_analytics_bridge.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1 -First 360; $p='tests/test_checkpoint_gstreamer_analytics_bridge.py'; Get-Content -LiteralPath $p | Select-Object -First 420`
> - Ran `$p='scripts/checkpoint_gstreamer_analytics_bridge.py'; Get-Content -LiteralPath $p | Select-Object -Skip 490 -First 130; $p='scripts/analytics_execution_worker.py'; rg -n "def validate.*resource|cuda_transfer_intervals|resource" $p | Select-Object -First 120; Get-Content -LiteralPath $p | Select-Object -Skip 450 -First 180`
> - Ran `$p='scripts/analytics_execution_worker.py'; Get-Content -LiteralPath $p | Select-Object -Skip 600 -First 150; rg -n "class ExecutionClient|def infer" $p`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: tests/test_checkpoint_gstreamer_analytics_bridge.py
> @@
>                  self.assertEqual(response["worker_image_id"], CPU_IMAGE if resource == "cpu" else GPU_IMAGE)
>                  self.assertEqual(response["raw_input_sha256"], hashlib.sha256(payload).hexdigest())
>                  self.assertRegex(response["output_sha256"], r"^[0-9a-f]{64}$")
> +                receipt = response["resource"]
> +                self.assertEqual(
> +                    set(receipt),
> +                    {
> +                        "process_cpu_time_ns",
> +                        "rss_before_bytes",
> +                        "rss_after_bytes",
> +                        "accelerator_memory_bytes",
> +                        "cuda_h2d_bytes",
> +                        "cuda_d2h_bytes",
> +                        "cuda_transfer_intervals",
> +                    },
> +                )
> +                if resource == "cpu":
> +                    self.assertEqual(receipt["accelerator_memory_bytes"], 0)
> +                    self.assertEqual(receipt["cuda_h2d_bytes"], 0)
> +                    self.assertEqual(receipt["cuda_d2h_bytes"], 0)
> +                    self.assertEqual(receipt["cuda_transfer_intervals"], [])
> +                else:
> +                    self.assertEqual(receipt["accelerator_memory_bytes"], 4096)
> +                    self.assertEqual(receipt["cuda_h2d_bytes"], len(payload))
> +                    self.assertEqual(receipt["cuda_d2h_bytes"], 32)
> +                    intervals = receipt["cuda_transfer_intervals"]
> +                    self.assertEqual(
> +                        [interval["direction"] for interval in intervals],
> +                        ["h2d", "d2h"],
> +                    )
> +                    self.assertTrue(
> +                        all(interval["device_id"] == GPU_UUID for interval in intervals)
> +                    )
> +                    self.assertTrue(
> +                        all(
> +                            interval["timing_source"] == "cudaEventElapsedTime"
> +                            for interval in intervals
> +                        )
> +                    )
>                  sequence += 1
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_checkpoint_gstreamer_analytics_bridge.GStreamerAnalyticsBridgeTests.test_routes_all_eight_branch_resource_bindings_through_real_memfd_worker_roundtrip"`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/checkpoint_gstreamer_analytics_bridge.py
> @@
>          provenance = response["provenance"]
>          terminal = response["terminal"]
>          timing = response["timing"]
> +        worker_resource = _exact(
> +            response["resource"],
> +            {
> +                "process_cpu_time_ns",
> +                "rss_before_bytes",
> +                "rss_after_bytes",
> +                "accelerator_memory_bytes",
> +                "cuda_h2d_bytes",
> +                "cuda_d2h_bytes",
> +                "cuda_transfer_intervals",
> +            },
> +            "GStreamer analytics bridge worker resource",
> +        )
> +        resource_receipt = {
> +            field: worker_resource[field]
> +            for field in (
> +                "process_cpu_time_ns",
> +                "rss_before_bytes",
> +                "rss_after_bytes",
> +                "accelerator_memory_bytes",
> +                "cuda_h2d_bytes",
> +                "cuda_d2h_bytes",
> +            )
> +        }
> +        resource_receipt["cuda_transfer_intervals"] = [
> +            dict(_mapping(interval, "GStreamer analytics bridge CUDA transfer interval"))
> +            for interval in worker_resource["cuda_transfer_intervals"]
> +        ]
>          _require(hashlib.sha256(output).hexdigest() == provenance["output_sha256"], "bridge output digest mismatch")
>          return {
> @@
>              "worker_completed_monotonic_ns": timing["worker_completed_monotonic_ns"],
>              "inference_latency_ns": timing["inference_latency_ns"],
> +            "resource": resource_receipt,
>          }
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_checkpoint_gstreamer_analytics_bridge tests.test_analytics_execution_worker"`
> - Ran `Get-FileHash -LiteralPath scripts/checkpoint_gstreamer_analytics_bridge.py -Algorithm SHA256 | Select-Object -ExpandProperty Hash`
>
> </details>
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_freeze_kpp_frozen_reconstruction_v1 tests.test_kpp_frozen_reconstruction_v1_dataset_integration"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_kpp_iss_publication_v3_dataset_integration tests.test_kpp_dataset_contract tests.test_kpp_legacy_iss_v2_manifest_integration"`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/datasets.yaml
> @@
> -    description: Historical source real checkpoint AVI captures. The externally
> -      pinned bytes are unavailable locally; a distinct reconstruction is cataloged
> -      separately and does not claim identity equivalence.
> -    publishable: false
> -    status: historical_source_bytes_unavailable
> -    availability:
> -      source_bytes_available: false
> -      historical_identity_recovered: false
> -      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> -      reconstruction_is_identity_substitute: false
> +    description: Source real checkpoint AVI captures used to derive publishable H.264/H.265
> +      codec datasets.
> +    publishable: true
> @@
> -    description: Historical H.264 transcodes whose externally pinned source bytes
> -      are unavailable locally; retained only as an immutable identity record.
> -    publishable: false
> -    status: historical_source_bytes_unavailable
> -    availability:
> -      source_bytes_available: false
> -      historical_identity_recovered: false
> -      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> -      reconstruction_is_identity_substitute: false
> +    description: Real checkpoint captures transcoded to H.264/AVC MP4 at 600 FPS CFR
> +      for publishable KPP codec benchmarks.
> +    publishable: true
> @@
> -    description: Historical H.265 transcodes whose externally pinned source bytes
> -      are unavailable locally; retained only as an immutable identity record.
> -    publishable: false
> -    status: historical_source_bytes_unavailable
> -    availability:
> -      source_bytes_available: false
> -      historical_identity_recovered: false
> -      reconstruction_generation_id: kpp_frozen_reconstruction_v1
> -      reconstruction_is_identity_substitute: false
> +    description: Real checkpoint captures transcoded to H.265/HEVC MP4 at 600 FPS
> +      CFR for publishable KPP codec benchmarks.
> +    publishable: true
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: tests/test_kpp_frozen_reconstruction_v1_dataset_integration.py
> @@
> -    def test_historical_entries_are_retained_but_explicitly_unavailable(self) -> None:
> +    def test_historical_entries_remain_immutable_and_receipt_records_unavailability(self) -> None:
>          for name in ("kpp_real_avi", "kpp_real_h264", "kpp_real_h265"):
>              entry = self.catalog[name]
> -            self.assertFalse(entry["publishable"])
> -            self.assertEqual(entry["status"], "historical_source_bytes_unavailable")
> -            self.assertFalse(entry["availability"]["source_bytes_available"])
> -            self.assertEqual(
> -                entry["availability"]["reconstruction_generation_id"],
> -                gate.GENERATION_ID,
> -            )
> +            self.assertTrue(entry["publishable"])
> +            self.assertNotIn("availability", entry)
> +            self.assertNotIn("status", entry)
> +        self.assertEqual(
> +            self.manifest["historical_v1"]["dataset_ids"],
> +            ["kpp_real_avi", "kpp_real_h264", "kpp_real_h265"],
> +        )
> +        self.assertFalse(self.manifest["historical_v1"]["source_bytes_available"])
> +        self.assertFalse(self.manifest["historical_v1"]["identity_recovered"])
> +        self.assertFalse(
> +            self.manifest["historical_v1"]["reconstruction_is_identity_substitute"]
> +        )
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> Смежные тесты подтвердили важную границу: старые `kpp_real_*` — immutable identity records, их YAML менять нельзя. Я восстановил их бит-в-бит; факт отсутствия исходных байтов теперь хранится только в новом подписанном reconstruction receipt. Так provenance остаётся честным, а существующие исторические идентичности не переписываются задним числом.
>
> <details><summary>Ran 8 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/experiments.yaml
> @@
>        camera_layout:
>        - stream_id: 0
>          camera_role: plate_number
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 1
>          camera_role: plate_number
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 2
>          camera_role: vehicle_type
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 3
>          camera_role: damage
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 4
>          camera_role: damage
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 5
>          camera_role: foreign_object
> -        source: data/videos/kpp/1.avi
> +        source_binding: selected_dataset_stream
> +        source_role: underbody
> @@
>        camera_layout:
>        - stream_id: 0
>          camera_role: plate_number
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 1
>          camera_role: plate_number
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 2
>          camera_role: vehicle_type
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 3
>          camera_role: damage
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 4
>          camera_role: damage
> -        source: data/videos/kpp/2.avi
> +        source_binding: selected_dataset_stream
> +        source_role: front_gate
>        - stream_id: 5
>          camera_role: foreign_object
> -        source: data/videos/kpp/1.avi
> +        source_binding: selected_dataset_stream
> +        source_role: underbody
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$p='tests/test_scenario_planning.py'; Get-Content -LiteralPath $p | Select-Object -Skip 245 -First 100; rg -n "camera_layout|pipeline|topology.*2" tests/test_scenario_planning.py`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: tests/test_scenario_planning.py
> @@
>          self.assertEqual(scenario["workload"]["routing_mode"], "all_branches_per_stream")
>          self.assertEqual(scenario["workload"]["routing_scope"], "topology_only_stress")
> +        camera_layout = scenario["workload"]["camera_layout"]
> +        self.assertEqual([item["stream_id"] for item in camera_layout], list(range(6)))
> +        self.assertTrue(
> +            all(item["source_binding"] == "selected_dataset_stream" for item in camera_layout)
> +        )
> +        self.assertEqual(
> +            [item["source_role"] for item in camera_layout],
> +            ["front_gate", "front_gate", "front_gate", "front_gate", "front_gate", "underbody"],
> +        )
> +        self.assertTrue(all("source" not in item for item in camera_layout))
>          self.assertEqual(scenario["pipeline"], SHARED_PROOF_PIPELINE)
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_freeze_kpp_frozen_reconstruction_v1 tests.test_kpp_frozen_reconstruction_v1_dataset_integration tests.test_kpp_iss_publication_v3_dataset_integration tests.test_kpp_dataset_contract tests.test_kpp_legacy_iss_v2_manifest_integration tests.test_scenario_planning"`
> - Ran `$p='tests/test_scenario_planning.py'; Get-Content -LiteralPath $p | Select-Object -Skip 625 -First 70; rg -n "resource_interval_extension|native_interval_sources|sha256" configs/experiments.yaml scripts/benchmark_contract.py scripts/checkpoint_runtime_plan.py | Select-Object -First 300`
> - Ran `Get-Content -LiteralPath configs/experiments.yaml | Select-Object -Skip 30 -First 30; Get-FileHash -LiteralPath scripts/full_resource_runtime_v2.py,scripts/checkpoint_runtime.py,scripts/checkpoint_gstreamer_analytics_bridge.py -Algorithm SHA256 | Select-Object Path,Hash`
> - Ran `Get-FileHash -LiteralPath scripts/resource_interval_contract.py,deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp,deploy/native_gst_probe/vast_native_gst_probe.cpp -Algorithm SHA256 | ForEach-Object { [pscustomobject]@{Path=$_.Path.Substring((Resolve-Path '.').Path.Length+1).Replace('\','/');Sha256=$_.Hash.ToLowerInvariant()} } | ConvertTo-Json -Compress`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/experiments.yaml
> @@
> -    fanout_emitter_sha256: aa54401630c0483713853f395e1cdfb28498aac050d5488ebcda5a11a8eaf52b
> +    fanout_emitter_sha256: cf876e2619856ea9bdbd3b4d80952e429ab398b62d3332b586942047cea72860
> @@
> -    fanout_binding_sha256: 18723aaa0a82e26ced6d88966bc87b807671b675ec875fdf8060ec1ff332babf
> +    fanout_binding_sha256: aa6dfd1600546d4382c50c648e5637414629cf814f1bd10c23f3308bc99e0e03
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> <details><summary>Ran 9 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_kpp_frozen_reconstruction_v1_dataset_integration tests.test_kpp_iss_publication_v3_dataset_integration tests.test_kpp_legacy_iss_v2_manifest_integration tests.test_scenario_planning"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -c 'from pathlib import Path; from benchmark_contract import load_config,assess_resource_interval_extension; import json; print(json.dumps(assess_resource_interval_extension(load_config(Path(\"configs/experiments.yaml\"))),indent=2,sort_keys=True))'"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -c "from pathlib import Path; from benchmark_contract import load_config,assess_resource_interval_extension; import json; print(json.dumps(assess_resource_interval_extension(load_config(Path(''configs/experiments.yaml''))),sort_keys=True))"'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -c "import sys; sys.path.insert(0,''scripts''); from pathlib import Path; from benchmark_contract import load_config,assess_resource_interval_extension; import json; print(json.dumps(assess_resource_interval_extension(load_config(Path(''configs/experiments.yaml''))),sort_keys=True))"'`
> - Ran `Get-Content -LiteralPath tests/test_scenario_planning.py | Select-Object -First 70`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -c "import sys; sys.path.insert(0,''scripts''); from pathlib import Path; from run_experiments import load_config; from benchmark_contract import assess_resource_interval_extension; import json; print(json.dumps(assess_resource_interval_extension(load_config(Path(''configs/experiments.yaml''))),sort_keys=True))"'`
> - Ran `$p='scripts/benchmark_contract.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1520 -First 140`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && sha256sum deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp deploy/native_gst_probe/vast_native_gst_probe.cpp && grep -n "fanout_.*sha256" configs/experiments.yaml'`
> - Ran `Get-FileHash -LiteralPath deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp,deploy/native_gst_probe/vast_native_gst_probe.cpp -Algorithm SHA256 | ForEach-Object { "$($_.Hash.ToLowerInvariant()) $($_.Path)" }; Get-Item -LiteralPath deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp,deploy/native_gst_probe/vast_native_gst_probe.cpp | Select-Object Name,Length,LastWriteTimeUtc`
>
> </details>
>
> <details><summary>Ran 11 commands</summary>
>
> - Ran `rg -n "class NativePolicyRuntimeCoordinator|def _derive_manifest|def materialize|runtime_identity|terminal_detector|terminal_backend|systems.*gstreamer|deepstream|savant|openvino|capability" scripts/publication_policy_qualification.py scripts/native_policy_runtime_coordinator.py scripts/backend_runtime_qualification.py tests/test_publication_policy_qualification.py tests/test_native_policy_runtime_coordinator.py tests/test_backend_runtime_qualification.py | Select-Object -First 500; Get-ChildItem -LiteralPath scripts -Filter '*policy*runtime*' | Select-Object Name,Length; Get-ChildItem -LiteralPath tests -Filter '*policy*runtime*' | Select-Object Name,Length`
> - Ran `$p='scripts/publication_policy_qualification.py'; Get-Content -LiteralPath $p | Select-Object -First 285; Get-Content -LiteralPath $p | Select-Object -Skip 285 -First 520; $p='scripts/checkpoint_native_policy_runtime.py'; rg -n "class NativePolicyRuntimeCoordinator|SYSTEMS|gstreamer|deepstream|savant|openvino|runtime_identity|terminal_detector|terminal_backend|def execute|def run" $p | Select-Object -First 350`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: configs/experiments.yaml
> @@
> -    fanout_emitter_sha256: cf876e2619856ea9bdbd3b4d80952e429ab398b62d3332b586942047cea72860
> +    fanout_emitter_sha256: bfe4acf693999a48ee0d1f6aa902d9bd9bd7390593ea7d0b0b971f14a5143ee4
> @@
> -    fanout_binding_sha256: aa6dfd1600546d4382c50c648e5637414629cf814f1bd10c23f3308bc99e0e03
> +    fanout_binding_sha256: 1422d194ed73af4737d6a462384359e355c66c7139d17865e9172114d778d571
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `rg -n "def assess_capability_manifest|runtime_identity|terminal_detector|terminal_backend|implementation_version|worker_image_digest|runtime_backend|device_api" scripts/publication_policy_contract.py | Select-Object -First 300; $p='scripts/publication_policy_contract.py'; Get-Content -LiteralPath $p | Select-Object -Skip 500 -First 300; $p='tests/test_publication_policy_qualification.py'; Get-Content -LiteralPath $p | Select-Object -First 330`
> - Ran `$p='scripts/publication_policy_contract.py'; Get-Content -LiteralPath $p | Select-Object -Skip 190 -First 170; $p='scripts/checkpoint_native_policy_runtime.py'; Get-Content -LiteralPath $p | Select-Object -Skip 320 -First 390`
> - Ran `$p='tests/test_backend_runtime_qualification.py'; Get-Content -LiteralPath $p | Select-Object -Skip 70 -First 90; $p='scripts/backend_runtime_qualification.py'; Get-Content -LiteralPath $p | Select-Object -Skip 420 -First 70; Get-Content -LiteralPath $p | Select-Object -Skip 600 -First 80; $p='tests/test_checkpoint_native_policy_runtime.py'; rg -n "capability_manifest|runtime_identity|terminal_detector|terminal_backend|savant|openvino" $p | Select-Object -First 300`
> - Ran `$p='tests/test_checkpoint_native_policy_runtime.py'; Get-Content -LiteralPath $p | Select-Object -Skip 28 -First 75; $p='scripts/checkpoint_native_policy_runtime.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1 -First 180`
> - Ran `rg -l 'vast_publication_policy_capability_manifest' tests scripts | Sort-Object`
> - Ran `$p='tests/test_publication_policy_contract.py'; rg -n "def .*capab|runtime_binding|terminal|native_evidence" $p | Select-Object -First 120; Get-Content -LiteralPath $p | Select-Object -Skip 20 -First 110; $p='tests/test_full_publication_identity_artifacts.py'; rg -n "policy_capability|runtime_identity|native_evidence" $p | Select-Object -First 100; Get-Content -LiteralPath $p | Select-Object -Skip 130 -First 70`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: tests/test_publication_policy_qualification.py
> @@
>                      "runtime_identity": {
>                          "runtime_backend": f"{system}-{resource}-native-backend-v1",
> -                        "device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
> +                        "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
> +                        "gpu_id": None if resource == "cpu" else 0,
>                          "worker_image_digest": "sha256:" + f"{len(bindings) + 1:064x}",
>                          "implementation_version": f"{system}-{branch}-{resource}-v1",
> +                        "terminal_detector": f"model-{system}-{branch}-{resource}-v1",
> +                        "terminal_backend": (
> +                            f"analytics-execution:openvino_cpu;runtime=OpenVINO;native_api=CompiledModel;device=CPU"
> +                            if resource == "cpu"
> +                            else f"analytics-execution:tensorrt_cuda;runtime=TensorRT;native_api=enqueueV3;device=NVIDIA_CUDA:0"
> +                        ),
>                      },
> @@
>              row = assessment["calibration_mapping"]["calibrations"]["deepstream"]["costs"]["plate_number"]["gpu"]
> @@
>              self.assertEqual(row["transfer_ms"], 0.5)
> +            binding = assessment["capability_manifest"]["systems"]["deepstream"]["branches"]["plate_number"]["gpu"]
> +            self.assertEqual(
> +                set(binding["runtime_identity"]),
> +                {
> +                    "runtime_backend",
> +                    "device_api",
> +                    "gpu_id",
> +                    "worker_image_digest",
> +                    "implementation_version",
> +                    "terminal_detector",
> +                    "terminal_backend",
> +                },
> +            )
> +            for field, value in binding["runtime_identity"].items():
> +                self.assertEqual(binding[field], value)
>              self.assertFalse((root / target.CAPABILITY_MANIFEST_FILENAME).exists())
> +
> +    def test_runtime_identity_requires_terminal_and_exact_cpu_gpu_coordinates(self) -> None:
> +        with tempfile.TemporaryDirectory() as tmp:
> +            root = Path(tmp)
> +            index_path, index = _fixture(root)
> +            index["bindings"][0]["runtime_identity"].pop("terminal_backend")
> +            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
> +            missing = self._assess(root, index_path)
> +            self.assertFalse(missing["passed"])
> +            self.assertIn("runtime_identity fields", " ".join(missing["blockers"]))
> +
> +            index_path, index = _fixture(root)
> +            cpu = next(item for item in index["bindings"] if item["resource"] == "cpu")
> +            cpu["runtime_identity"]["gpu_id"] = 0
> +            index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
> +            mismatched = self._assess(root, index_path)
> +            self.assertFalse(mismatched["passed"])
> +            self.assertIn("CPU runtime identity", " ".join(mismatched["blockers"]))
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B -m unittest tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_complete_matrix_is_pure_and_derives_manifest_and_balanced_calibration tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_runtime_identity_requires_terminal_and_exact_cpu_gpu_coordinates'`
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Продолжаю с текущей точки: frozen KPP v1 уже физически реконструирован и проверен по байтам; сейчас закрываю центральный fail-closed контракт runtime identity, затем сведу результаты трёх WSL-бэкендов и запущу общий барьер тестов. Boot-profile не меняю, лимит памяти WSL сохраняется как есть.
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `rg -n "_RUNTIME_IDENTITY_FIELDS|def _validate_runtime_identity|runtime_identity|def _derive_manifest" scripts/publication_policy_qualification.py tests/test_publication_policy_qualification.py`
> - Ran `git status --short`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-policy-test && TMPDIR=/tmp/vast-policy-test python3 -m unittest -v tests.test_scenario_planning.ScenarioPlanningTests.test_resource_interval_extension_is_verified_but_not_publication_bound"`
> - Ran `rg -n "gstreamer_custom|deepstream|_handle_terminal|runtime_identity|terminal_backend|terminal_detector" scripts/checkpoint_native_policy_runtime.py tests/test_checkpoint_native_policy_runtime.py`
> - Ran `$p='scripts/publication_policy_qualification.py'; Get-Content -LiteralPath $p | Select-Object -First 270`
> - Ran `$p='tests/test_publication_policy_qualification.py'; Get-Content -LiteralPath $p | Select-Object -First 245`
>
> </details>
>
> Точечный тест сценария остановился не из-за контракта, а потому что был запущен системным Python WSL без `pandas`; переключу тестовый барьер на замороженное WSL-окружение. В коде подтверждён реальный дефект: CPU `gpu_id=null` сейчас одновременно разрешён схемой и отвергается общей строковой проверкой, а терминальные поля не проецируются в manifest. Исправляю это через строгую CPU/GPU-валидацию.
>
> <details><summary>Ran 9 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\publication_policy_qualification.py
> @@
>  _SHA256_CHARS = frozenset("0123456789abcdef")
>  _RUNTIME_IDENTITY_FIELDS = {
> -    "runtime_backend", "device_api", "worker_image_digest", "implementation_version",
> +    "runtime_backend", "device_api", "gpu_id", "worker_image_digest",
> +    "implementation_version", "terminal_detector", "terminal_backend",
>  }
> @@
>  def _stable_id(value: Any) -> bool:
>      text = str(value)
>      return len(text) >= 8 and text == text.strip() and not any(ch in "\r\n\x00" for ch in text)
> +
> +
> +def _validate_runtime_identity(value: Any, *, key: tuple[str, str, str]) -> dict[str, Any]:
> +    if type(value) is not dict or set(value) != _RUNTIME_IDENTITY_FIELDS:
> +        raise QualificationError(f"binding {key} runtime_identity fields drifted")
> +    string_fields = _RUNTIME_IDENTITY_FIELDS - {"gpu_id"}
> +    if any(type(value[field]) is not str or not _stable_id(value[field]) for field in string_fields):
> +        raise QualificationError(f"binding {key} runtime_identity is incomplete")
> +    image = value["worker_image_digest"]
> +    if not image.startswith("sha256:") or not _valid_sha(image[7:]):
> +        raise QualificationError(f"binding {key} worker image digest is invalid")
> +
> +    resource = key[2]
> +    device_api = value["device_api"]
> +    gpu_id = value["gpu_id"]
> +    terminal_backend = value["terminal_backend"]
> +    if resource == "cpu":
> +        if device_api != "CPU" or gpu_id is not None or "device=CPU" not in terminal_backend or "NVIDIA_CUDA" in terminal_backend:
> +            raise QualificationError(f"binding {key} CPU runtime identity is inconsistent")
> +    elif resource == "gpu":
> +        if device_api != "NVIDIA_CUDA" or type(gpu_id) is not int or gpu_id != 0 or "device=NVIDIA_CUDA:0" not in terminal_backend:
> +            raise QualificationError(f"binding {key} GPU runtime identity is inconsistent")
> +    else:  # pragma: no cover - the policy resource domain is checked before this helper
> +        raise QualificationError(f"binding {key} runtime resource is unsupported")
> +    return dict(value)
> @@
> -        runtime_identity = raw["runtime_identity"]
> -        if type(runtime_identity) is not dict or set(runtime_identity) != _RUNTIME_IDENTITY_FIELDS:
> -            raise QualificationError(f"binding {key} runtime_identity fields drifted")
> -        if not all(_stable_id(runtime_identity[field]) for field in _RUNTIME_IDENTITY_FIELDS):
> -            raise QualificationError(f"binding {key} runtime_identity is incomplete")
> -        image = str(runtime_identity["worker_image_digest"])
> -        if not image.startswith("sha256:") or not _valid_sha(image[7:]):
> -            raise QualificationError(f"binding {key} worker image digest is invalid")
> +        runtime_identity = _validate_runtime_identity(raw["runtime_identity"], key=key)
> @@
>              "implementation_sha256": implementation["sha256"],
>              "runtime_binding": runtime_binding,
> -            "runtime_identity": dict(runtime_identity),
> +            "runtime_identity": runtime_identity,
> +            **runtime_identity,
>              "native_evidence": {
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "for p in /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python; do if [ -x \"$p\" ]; then echo FOUND:$p; \"$p\" -c 'import pandas,yaml; print(pandas.__version__)'; fi; done"`
> - Ran `$env:TEMP='E:\STUDY\VAST-test-runtime-tmp'; $env:TMP=$env:TEMP; python -B -m unittest -v tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_complete_matrix_is_pure_and_derives_manifest_and_balanced_calibration tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_runtime_identity_requires_terminal_and_exact_cpu_gpu_coordinates`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\publication_policy_qualification.py
> @@
> -    string_fields = _RUNTIME_IDENTITY_FIELDS - {"gpu_id"}
> +    string_fields = _RUNTIME_IDENTITY_FIELDS - {"device_api", "gpu_id"}
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'for p in /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python; do if [ -x "$p" ]; then echo "FOUND:$p"; "$p" -c "import pandas,yaml; print(pandas.__version__)"; fi; done'`
> - Ran `$env:TEMP='E:\STUDY\VAST-test-runtime-tmp'; $env:TMP=$env:TEMP; python -B -m unittest -v tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_complete_matrix_is_pure_and_derives_manifest_and_balanced_calibration tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_runtime_identity_requires_terminal_and_exact_cpu_gpu_coordinates`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'ls -ld /mnt/e/STUDY/VAST/.publication-runtime /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1 /home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1 2>&1; find /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1 -maxdepth 2 -type f -name "python*" -o -type l -name "python*" 2>/dev/null | head'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'ls -l /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python*; file /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12; /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -c "import pandas,yaml; print(pandas.__version__)"'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-policy-test && TMPDIR=/tmp/vast-policy-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_scenario_planning.ScenarioPlanningTests.test_resource_interval_extension_is_verified_but_not_publication_bound'`
>
> </details>
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `rg -n "def assess_capability_manifest|runtime_identity|terminal_detector|terminal_backend|device_api|worker_image" scripts/publication_policy_contract.py tests/test_publication_policy_contract.py`
> - Ran `$p='tests/test_publication_policy_contract.py'; Get-Content -LiteralPath $p | Select-Object -First 360`
> - Ran `$p='scripts/publication_policy_contract.py'; Get-Content -LiteralPath $p | Select-Object -First 360`
>
> </details>
>
> <details><summary>Ran 7 commands</summary>
>
> - Ran `rg -n -U '"runtime_identity"\s*:\s*\{|runtime_identity\s*=|terminal_backend|terminal_detector' scripts/checkpoint_*qualification_fragment*.py artifacts/*/qualification/qualification_fragment.json | Select-Object -First 240`
> - Ran `rg -n -U '"runtime_identity"\s*:\s*\{|runtime_identity\s*=|terminal_backend|terminal_detector' scripts artifacts --glob 'checkpoint_*qualification_fragment*.py' --glob 'qualification_fragment.json'`
> - Ran `rg -n 'device_api.*HOST_CPU|"device_api": "CPU"|device_api.*NVIDIA_CUDA' scripts deploy configs tests --glob '*.py' --glob '*.yaml' --glob '*.json' | Select-Object -First 260`
> - Ran `$p='scripts/checkpoint_native_policy_runtime.py'; Get-Content -LiteralPath $p | Select-Object -Skip 330 -First 360`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_publication_policy_contract.py
> @@
>              bindings: dict[str, dict] = {}
>              for resource_index, resource in enumerate(RESOURCES, start=1):
>                  marker = system_index * 100 + branch_index * 10 + resource_index
> +                runtime_identity = {
> +                    "runtime_backend": f"{system}.{resource}.native.backend.v3",
> +                    "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
> +                    "gpu_id": None if resource == "cpu" else 0,
> +                    "worker_image_digest": "sha256:" + f"{marker + 2:064x}",
> +                    "implementation_version": f"{system}-{branch}-{resource}-implementation-v3",
> +                    "terminal_detector": f"opaque-{branch}-detector-v3",
> +                    "terminal_backend": (
> +                        "analytics-execution:openvino_cpu;runtime=OpenVINO;native_api=CompiledModel;device=CPU"
> +                        if resource == "cpu"
> +                        else "analytics-execution:tensorrt_cuda;runtime=TensorRT;native_api=enqueueV3;device=NVIDIA_CUDA:0"
> +                    ),
> +                }
>                  bindings[resource] = {
>                      "status": "implemented_and_native_evidence_bound",
>                      "implementation_id": f"{system}-{branch}-{resource}-runtime-v1",
>                      "implementation_sha256": f"{marker:064x}",
>                      "runtime_binding": f"{system}:{branch}:{resource}:worker",
> +                    "runtime_identity": runtime_identity,
> +                    **runtime_identity,
>                      "native_evidence": {
> @@
>          self.assertIn(
>              "capability:openvino_gva:foreign_object:gpu:native_evidence_not_bound",
>              assessment["blockers"],
>          )
> +
> +        missing_identity = copy.deepcopy(manifest)
> +        del missing_identity["systems"]["gstreamer_custom"]["branches"]["damage"]["cpu"][
> +            "runtime_identity"
> +        ]
> +        assessment = assess_capability_manifest(missing_identity)
> +        self.assertFalse(assessment["passed"])
> +        self.assertIn(
> +            "capability:gstreamer_custom:damage:cpu:runtime_identity_fields_invalid",
> +            assessment["blockers"],
> +        )
> +
> +        projection_drift = copy.deepcopy(manifest)
> +        projection_drift["systems"]["deepstream"]["branches"]["plate_number"]["gpu"][
> +            "terminal_backend"
> +        ] += ":drift"
> +        assessment = assess_capability_manifest(projection_drift)
> +        self.assertFalse(assessment["passed"])
> +        self.assertIn(
> +            "capability:deepstream:plate_number:gpu:runtime_identity_projection_mismatch",
> +            assessment["blockers"],
> +        )
> +
> +        cpu_on_gpu = copy.deepcopy(manifest)
> +        cpu_on_gpu["systems"]["savant"]["branches"]["vehicle_type"]["cpu"][
> +            "runtime_identity"
> +        ]["gpu_id"] = 0
> +        cpu_on_gpu["systems"]["savant"]["branches"]["vehicle_type"]["cpu"]["gpu_id"] = 0
> +        assessment = assess_capability_manifest(cpu_on_gpu)
> +        self.assertFalse(assessment["passed"])
> +        self.assertIn(
> +            "capability:savant:vehicle_type:cpu:runtime_identity_resource_mismatch",
> +            assessment["blockers"],
> +        )
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$env:TEMP='E:\STUDY\VAST-test-runtime-tmp'; $env:TMP=$env:TEMP; python -B -m unittest -v tests.test_publication_policy_contract.PublicationPolicyContractTests.test_capabilities_require_every_real_cpu_gpu_binding_and_native_emitter`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-policy-test && TMPDIR=/tmp/vast-policy-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_publication_policy_contract.PublicationPolicyContractTests.test_capabilities_require_every_real_cpu_gpu_binding_and_native_emitter'`
>
> </details>
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\publication_policy_contract.py
> @@
>  _PLACEHOLDER_IDS = {
> @@
>      "placeholder",
>  }
> +_RUNTIME_IDENTITY_FIELDS = frozenset(
> +    {
> +        "runtime_backend",
> +        "device_api",
> +        "gpu_id",
> +        "worker_image_digest",
> +        "implementation_version",
> +        "terminal_detector",
> +        "terminal_backend",
> +    }
> +)
> @@
>  def _real_id(value: Any) -> bool:
>      text = str(value)
>      return bool(_REAL_ID_RE.fullmatch(text)) and text.lower() not in _PLACEHOLDER_IDS
> +
> +
> +def _stable_runtime_text(value: Any) -> bool:
> +    return (
> +        type(value) is str
> +        and len(value) >= 8
> +        and value == value.strip()
> +        and not any(character in value for character in "\r\n\x00")
> +    )
> +
> +
> +def _assess_runtime_identity(
> +    binding: Mapping[str, Any],
> +    *,
> +    resource: str,
> +    prefix: str,
> +    blockers: list[str],
> +) -> None:
> +    identity = binding.get("runtime_identity")
> +    if not isinstance(identity, Mapping) or set(identity) != _RUNTIME_IDENTITY_FIELDS:
> +        blockers.append(f"{prefix}:runtime_identity_fields_invalid")
> +        return
> +
> +    string_fields = _RUNTIME_IDENTITY_FIELDS - {"device_api", "gpu_id"}
> +    if any(not _stable_runtime_text(identity.get(field)) for field in string_fields):
> +        blockers.append(f"{prefix}:runtime_identity_value_invalid")
> +    image = str(identity.get("worker_image_digest", ""))
> +    if not image.startswith("sha256:") or not _valid_sha256(image[7:]):
> +        blockers.append(f"{prefix}:worker_image_digest_invalid")
> +    if any(field not in binding or binding.get(field) != identity.get(field) for field in _RUNTIME_IDENTITY_FIELDS):
> +        blockers.append(f"{prefix}:runtime_identity_projection_mismatch")
> +
> +    device_api = identity.get("device_api")
> +    gpu_id = identity.get("gpu_id")
> +    terminal_backend = identity.get("terminal_backend")
> +    if resource == "cpu":
> +        matches_resource = (
> +            device_api == "CPU"
> +            and gpu_id is None
> +            and type(terminal_backend) is str
> +            and "device=CPU" in terminal_backend
> +            and "NVIDIA_CUDA" not in terminal_backend
> +        )
> +    else:
> +        matches_resource = (
> +            device_api == "NVIDIA_CUDA"
> +            and type(gpu_id) is int
> +            and gpu_id == 0
> +            and type(terminal_backend) is str
> +            and "device=NVIDIA_CUDA:0" in terminal_backend
> +        )
> +    if not matches_resource:
> +        blockers.append(f"{prefix}:runtime_identity_resource_mismatch")
> @@
>                  if not _real_id(binding.get("runtime_binding")):
>                      blockers.append(f"{prefix}:runtime_binding_not_real")
> +                _assess_runtime_identity(
> +                    binding,
> +                    resource=resource,
> +                    prefix=prefix,
> +                    blockers=blockers,
> +                )
>  
>                  evidence = binding.get("native_evidence")
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-policy-test && TMPDIR=/tmp/vast-policy-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_publication_policy_contract.PublicationPolicyContractTests.test_capabilities_require_every_real_cpu_gpu_binding_and_native_emitter tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_complete_matrix_is_pure_and_derives_manifest_and_balanced_calibration tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_runtime_identity_requires_terminal_and_exact_cpu_gpu_coordinates'`
>
> </details>
>
> <details><summary>Ran 8 commands</summary>
>
> - Ran `$p='tests/test_checkpoint_native_policy_runtime.py'; Get-Content -LiteralPath $p | Select-Object -First 340`
> - Ran `rg -n "calibration\(|request_message\(|path_message\(|terminal_message\(" tests/test_checkpoint_native_policy_runtime.py`
> - Ran `$p='tests/test_checkpoint_native_policy_runtime.py'; Get-Content -LiteralPath $p | Select-Object -Skip 340 -First 150`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_native_policy_runtime.py
> @@
>              bindings: dict[str, dict] = {}
>              for resource_index, resource in enumerate(RESOURCES, start=1):
>                  marker = system_index * 100 + branch_index * 10 + resource_index
> +                runtime_identity = {
> +                    "runtime_backend": (
> +                        "openvino_dlstreamer" if resource == "cpu" else "cuda_tensorrt"
> +                    ),
> +                    "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
> +                    "gpu_id": None if resource == "cpu" else 0,
> +                    "worker_image_digest": "sha256:" + f"{marker + 2:064x}",
> +                    "implementation_version": f"{system}-{branch}-{resource}-implementation-v3",
> +                    "terminal_detector": f"{system}-{branch}-{resource}-native-detector-v1",
> +                    "terminal_backend": (
> +                        "openvino-dlstreamer:gvadetect;device=CPU"
> +                        if resource == "cpu"
> +                        else "cuda-tensorrt:nvinfer;device=NVIDIA_CUDA:0"
> +                    ),
> +                }
>                  bindings[resource] = {
> @@
> -                    "runtime_backend": (
> -                        "openvino_dlstreamer" if resource == "cpu" else "cuda_tensorrt"
> -                    ),
> -                    "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
> -                    "gpu_id": None if resource == "cpu" else 0,
> -                    "terminal_detector": (
> -                        f"{system}-{branch}-{resource}-native-detector-v1"
> -                    ),
> -                    "terminal_backend": (
> -                        "openvino-dlstreamer:gvadetect;device=CPU"
> -                        if resource == "cpu"
> -                        else "cuda-tensorrt:nvinfer;device=NVIDIA_CUDA:0"
> -                    ),
> +                    "runtime_identity": runtime_identity,
> +                    **runtime_identity,
> @@
> -def calibration(manifest: dict) -> dict:
> +def calibration(manifest: dict, system: str = "gstreamer_custom") -> dict:
> @@
> -    bindings = manifest["systems"]["gstreamer_custom"]["branches"]
> +    bindings = manifest["systems"][system]["branches"]
> @@
> -        "system": "gstreamer_custom",
> +        "system": system,
> @@
> -def request_message(*, branch: str = "plate_number", frame_id: int = 1) -> dict:
> +def request_message(
> +    *,
> +    branch: str = "plate_number",
> +    frame_id: int = 1,
> +    run_id: str = "run-native-policy-0001",
> +) -> dict:
> @@
> -        "run_id": "run-native-policy-0001",
> +        "run_id": run_id,
> @@
> -def path_message(response: dict, *, request: dict, resource: str | None = None) -> dict:
> +def path_message(
> +    response: dict,
> +    *,
> +    request: dict,
> +    resource: str | None = None,
> +    system: str = "gstreamer_custom",
> +) -> dict:
> @@
> -    binding = manifest["systems"]["gstreamer_custom"]["branches"][request["branch"]][selected]
> +    binding = manifest["systems"][system]["branches"][request["branch"]][selected]
> @@
> -def terminal_message(response: dict, *, request: dict) -> dict:
> +def terminal_message(
> +    response: dict,
> +    *,
> +    request: dict,
> +    system: str = "gstreamer_custom",
> +) -> dict:
> @@
> -    binding = capability_manifest()["systems"]["gstreamer_custom"]["branches"][
> +    binding = capability_manifest()["systems"][system]["branches"][
> @@
>  class NativePolicyRuntimeCoordinatorTests(unittest.TestCase):
> +    def test_all_four_publishable_systems_use_the_same_terminal_bound_coordinator(self) -> None:
> +        manifest = capability_manifest()
> +        for system in PUBLISHABLE_SYSTEMS:
> +            with self.subTest(system=system):
> +                run_id = f"run-{system}-policy-0001"
> +                runtime = NativePolicyRuntimeCoordinator(
> +                    run_id=run_id,
> +                    arm_id=f"arm-{system}-policy-cpu-0001",
> +                    system=system,
> +                    scenario="checkpoint_video_dag_shared",
> +                    codec="h264",
> +                    policy="cpu_only",
> +                    deadline_ms=50.0,
> +                    branches=ANALYTICS_BRANCHES,
> +                    capability_manifest=manifest,
> +                    calibration=calibration(manifest, system),
> +                )
> +                request = request_message(run_id=run_id)
> +                response = runtime.handle_message(request["worker_id"], request)
> +                runtime.handle_message(
> +                    request["worker_id"],
> +                    path_message(response, request=request, system=system),
> +                )
> +                terminal = runtime.handle_message(
> +                    request["worker_id"],
> +                    terminal_message(response, request=request, system=system),
> +                )
> +                self.assertTrue(terminal["accepted"])
> +
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-policy-test && TMPDIR=/tmp/vast-policy-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_checkpoint_native_policy_runtime.NativePolicyRuntimeCoordinatorTests.test_all_four_publishable_systems_use_the_same_terminal_bound_coordinator'`
> - Ran `$p='scripts/checkpoint_native_policy_runtime.py'; Get-Content -LiteralPath $p | Select-Object -First 90`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\checkpoint_native_policy_runtime.py
> @@
> -"""Fail-closed native scheduling bridge for the checkpoint GStreamer runtime."""
> +"""Fail-closed native scheduling bridge for all checkpoint publication runtimes."""
> @@
>      ANALYTICS_BRANCHES,
>      POLICIES,
>      POLICY_SCOPE,
> +    PUBLISHABLE_SYSTEMS,
> @@
> -        if system not in {"gstreamer_custom", "deepstream"}:
> +        if system not in PUBLISHABLE_SYSTEMS:
>              raise NativePolicyRuntimeError(
> -                "native checkpoint policy binding is implemented only for exact checkpoint SDK runtimes"
> +                "native checkpoint policy binding is outside the publishable runtime set"
>              )
> @@
>          detector = _text(message.get("detector"), "detector")
>          backend = str(message.get("backend", ""))
>          binding = self._binding(str(state.record["branch"]), selected)
> -        expected_detector = str(binding.get("terminal_detector", ""))
> -        expected_backend = str(binding.get("terminal_backend", ""))
> -        if self.system == "deepstream":
> -            if selected == "cpu":
> -                capability_matches_resource = (
> -                    binding.get("device_api") == "CPU"
> -                    and expected_backend.startswith("analytics-execution:openvino_cpu;")
> -                    and ";device=CPU:" in expected_backend
> -                )
> -            else:
> -                capability_matches_resource = (
> -                    binding.get("device_api") == "NVIDIA_CUDA"
> -                    and binding.get("gpu_id") == 0
> -                    and expected_backend.startswith("analytics-execution:tensorrt_cuda;")
> -                    and ";device=NVIDIA_CUDA:" in expected_backend
> -                )
> -        elif selected == "cpu":
> +        identity = binding.get("runtime_identity")
> +        if not isinstance(identity, Mapping):
> +            raise NativePolicyRuntimeError("selected capability has no validated runtime identity")
> +        expected_detector = str(identity.get("terminal_detector", ""))
> +        expected_backend = str(identity.get("terminal_backend", ""))
> +        identity_projection_matches = all(
> +            binding.get(field) == identity.get(field)
> +            for field in (
> +                "runtime_backend",
> +                "device_api",
> +                "gpu_id",
> +                "worker_image_digest",
> +                "implementation_version",
> +                "terminal_detector",
> +                "terminal_backend",
> +            )
> +        )
> +        if selected == "cpu":
>              capability_matches_resource = (
> -                binding.get("runtime_backend") == "openvino_dlstreamer"
> -                and binding.get("device_api") == "CPU"
> -                and expected_backend.startswith("openvino-dlstreamer:")
> -                and expected_backend.endswith(";device=CPU")
> +                identity.get("device_api") == "CPU"
> +                and identity.get("gpu_id") is None
> +                and "device=CPU" in expected_backend
> +                and "NVIDIA_CUDA" not in expected_backend
>              )
>          else:
>              capability_matches_resource = (
> -                binding.get("runtime_backend") == "cuda_tensorrt"
> -                and binding.get("device_api") == "NVIDIA_CUDA"
> -                and binding.get("gpu_id") == 0
> -                and expected_backend.startswith("cuda-tensorrt:")
> -                and expected_backend.endswith(";device=NVIDIA_CUDA:0")
> -                and not expected_backend.startswith("openvino")
> +                identity.get("device_api") == "NVIDIA_CUDA"
> +                and type(identity.get("gpu_id")) is int
> +                and identity.get("gpu_id") == 0
> +                and "device=NVIDIA_CUDA:0" in expected_backend
>              )
>          if (
> -            not capability_matches_resource
> +            not identity_projection_matches
> +            or not capability_matches_resource
>              or not expected_detector
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-policy-test && TMPDIR=/tmp/vast-policy-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_checkpoint_native_policy_runtime'`
>
> </details>
>
> Центральный runtime identity теперь замкнут: manifest обязан содержать ровно семь полей, top-level проекция должна совпадать побайтно, CPU/GPU-координаты проверяются отдельно. Native scheduler уже проходит один и тот же terminal-bound путь для DeepStream, Savant, OpenVINO GVA и GStreamer; 11/11 его тестов зелёные. Сейчас прогоняю зависимые квалификационные модули, чтобы найти все устаревшие четырёхполевые фикстуры до сборки общего индекса.
>
> <details><summary>Ran 18 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-policy-test && TMPDIR=/tmp/vast-policy-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_publication_policy_contract tests.test_publication_policy_qualification tests.test_backend_runtime_qualification tests.test_full_publication_identity_artifacts tests.test_full_resource_qualification'`
> - Ran `rg -n "contract_version|topology_contract|expected_chain|analytics.*branch_complete|postprocess" scripts/publication_policy_qualification.py tests/test_publication_policy_qualification.py`
> - Ran `$p='scripts/publication_policy_qualification.py'; Get-Content -LiteralPath $p | Select-Object -Skip 330 -First 185`
> - Ran `$p='scripts/topology_contract.py'; Get-Content -LiteralPath $p | Select-Object -First 320`
> - Ran `rg -n "contract_version.*2|expected_stage|postprocess_|stage_chain|topology.*required" scripts/topology_contract.py configs/experiments.yaml tests/test_topology_contract.py | Select-Object -First 260`
> - Ran `rg -n "validate_topology_events|contract_version|_default_pilot_validator|sidecar" tests/test_publication_policy_qualification.py`
> - Ran `$p='tests/test_publication_policy_qualification.py'; Get-Content -LiteralPath $p | Select-Object -Skip 260 -First 75`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_publication_policy_qualification.py
> @@
>          source = inspect.getsource(target._default_pilot_validator)
>          self.assertIn("accepted_arm_evidence_files", source)
>          self.assertIn("expected_identity[\"policy\"]", source)
> +        self.assertIn('"contract_version": 2', source)
>          self.assertNotIn("policy_feedback.csv", source)
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_default_validator_uses_exact_policy_aware_acceptance_set'`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\publication_policy_qualification.py
> @@
> -                "contract_version": 1,
> +                "contract_version": 2,
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `rg -n 'device_api.*HOST_CPU|HOST_CPU.*device_api|policy.*runtime_identity|runtime_identity' scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py tests/test_checkpoint_gstreamer_custom_qualification_fragment_v3.py`
> - Ran `$p='scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 430 -First 360`
> - Ran `$p='scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 790 -First 170`
> - Ran `$p='tests/test_checkpoint_gstreamer_custom_qualification_fragment_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 120 -First 80`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_gstreamer_custom_qualification_fragment_v3.py
> @@
>                  self.assertEqual(
>                      row["runtime_identity"]["worker_image_digest"],
>                      expected_worker,
>                  )
> +                self.assertEqual(
> +                    row["runtime_identity"]["device_api"],
> +                    "CPU" if row["resource"] == "cpu" else "NVIDIA_CUDA",
> +                )
> +                self.assertEqual(
> +                    row["runtime_identity"]["gpu_id"],
> +                    None if row["resource"] == "cpu" else 0,
> +                )
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-gst-qualification-test && TMPDIR=/tmp/vast-gst-qualification-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_checkpoint_gstreamer_custom_qualification_fragment_v3.GStreamerCustomQualificationFragmentV3Tests.test_exact_accepted_parity_preprocessing_and_runtime_images_are_bound'`
> - Ran `rg -n '^class ' tests/test_checkpoint_gstreamer_custom_qualification_fragment_v3.py`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-gst-qualification-test && TMPDIR=/tmp/vast-gst-qualification-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_checkpoint_gstreamer_custom_qualification_fragment_v3.GstreamerCustomQualificationFragmentV3Tests.test_exact_accepted_parity_preprocessing_and_runtime_images_are_bound'`
>
> </details>
>
> <details><summary>Ran 24 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\checkpoint_gstreamer_custom_qualification_fragment_v3.py
> @@
> -        "device_api": "HOST_CPU" if resource == "cpu" else "NVIDIA_CUDA",
> +        "device_api": "CPU" if resource == "cpu" else "NVIDIA_CUDA",
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-gst-qualification-test && TMPDIR=/tmp/vast-gst-qualification-test .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_checkpoint_gstreamer_custom_qualification_fragment_v3.GstreamerCustomQualificationFragmentV3Tests.test_exact_accepted_parity_preprocessing_and_runtime_images_are_bound'`
> - Ran `$root=(Resolve-Path -LiteralPath 'E:\STUDY\VAST\artifacts\gstreamer_publication_v3').Path; $source=(Resolve-Path -LiteralPath 'E:\STUDY\VAST\artifacts\gstreamer_publication_v3\qualification').Path; $target=Join-Path $root 'qualification.stale-policy-host-cpu-4d0260a7'; [pscustomobject]@{Root=$root;Source=$source;SourceWithinRoot=$source.StartsWith($root + [IO.Path]::DirectorySeparatorChar);Target=$target;TargetExists=(Test-Path -LiteralPath $target);FileCount=(Get-ChildItem -LiteralPath $source -File -Recurse).Count} | ConvertTo-Json -Compress`
> - Ran `Move-Item -LiteralPath 'E:\STUDY\VAST\artifacts\gstreamer_publication_v3\qualification' -Destination 'E:\STUDY\VAST\artifacts\gstreamer_publication_v3\qualification.stale-policy-host-cpu-4d0260a7'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py --project-root /mnt/e/STUDY/VAST --output-dir /mnt/e/STUDY/VAST/artifacts/gstreamer_publication_v3/qualification'`
> - Ran `rg -n "qualification_index|qualification-index|system_fragment|policy_bindings|fragment_path|build.*qualification|materialize.*qualification" scripts tests progress.md --glob '*.py' --glob '*.md' | Select-Object -First 320`
> - Ran `rg -n "checkpoint_policy_qualification|CAPABILITY_MANIFEST_FILENAME|publication_policy_qualification|checkpoint_policy_capability_manifest|policy_qualification_receipt" scripts tests configs progress.md --glob '*.py' --glob '*.yaml' --glob '*.md' | Select-Object -First 360`
> - Ran `Get-Content -LiteralPath 'E:\STUDY\VAST\progress.md' | Select-Object -Last 520`
> - Ran `Get-Content -LiteralPath 'scripts/publication_matrix.py' | Select-Object -First 360`
> - Ran `rg -n "publication_policy_qualification|full_resource_qualification|backend_runtime_qualification|seafile|5600|qualification" configs/experiments.yaml scripts/full_publication_entrypoint.py scripts/full_publication_runner.py scripts/publication_matrix.py`
> - Ran `Get-Content -LiteralPath 'scripts/full_publication_entrypoint.py' | Select-Object -First 360`
> - Ran `$p='configs/experiments.yaml'; Get-Content -LiteralPath $p | Select-Object -First 650`
> - Ran `rg -n "publication_policy_capability_manifest|validate_full_publication_readiness|identity_artifacts|resource_capability_grant|backend_runtime_grant|model_parity_grant|RealArmRunner|run_one" scripts/full_publication_entrypoint.py`
> - Ran `$p='scripts/full_publication_entrypoint.py'; Get-Content -LiteralPath $p | Select-Object -Skip 680 -First 690`
> - Ran `$p='scripts/full_publication_entrypoint.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1450 -First 310`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'df -B1 / /mnt/e /home/s-a-balashov/.local/state/vast/publication 2>/dev/null; free -b; nproc'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B scripts/full_publication_entrypoint.py plan | head -80'`
> - Ran `Get-PSDrive -Name E | Select-Object Name,Used,Free,@{N='UsedGiB';E={[math]::Round($_.Used/1GB,2)}},@{N='FreeGiB';E={[math]::Round($_.Free/1GB,2)}} | ConvertTo-Json -Compress`
> - Ran `Get-ChildItem -LiteralPath configs -File | Where-Object { $_.Name -match 'publication|qualification|binding|grant' } | Select-Object Name,Length | Sort-Object Name | Format-Table -AutoSize; if (Test-Path -LiteralPath 'configs/full_publication_identity_artifacts.yaml') { Get-Content -LiteralPath 'configs/full_publication_identity_artifacts.yaml' }`
> - Ran `rg -n "DEFAULT_MANIFEST|full_publication_identity" scripts/full_publication_identity_artifacts.py .gitignore`
> - Ran `Get-Content -LiteralPath 'scripts/checkpoint_publication_launcher_adapter_v3.py' | Select-Object -First 420`
> - Ran `Get-Content -LiteralPath 'scripts/backend_publication_output_transaction_production_v3.py' | Select-Object -First 500`
> - Ran `Get-Content -LiteralPath 'tests/test_checkpoint_publication_launcher_adapters_v3.py' | Select-Object -First 360`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && mkdir -p /tmp/vast-kpp-regression && TMPDIR=/tmp/vast-kpp-regression .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_freeze_kpp_frozen_reconstruction_v1 tests.test_kpp_frozen_reconstruction_v1_dataset_integration tests.test_freeze_kpp_iss_publication_v3 tests.test_kpp_iss_publication_v3_dataset_integration tests.test_scenario_planning'`
>
> </details>
>
> <details><summary>Ran 25 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'install -d -m 700 /tmp/vast-kpp-regression-private-20260824 && cd /mnt/e/STUDY/VAST && TMPDIR=/tmp/vast-kpp-regression-private-20260824 .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_freeze_kpp_iss_publication_v3'`
> - Ran `$p='tests/test_freeze_kpp_iss_publication_v3.py'; Get-Content -LiteralPath $p | Select-Object -First 360; $q='scripts/freeze_kpp_iss_publication_v3.py'; Get-Content -LiteralPath $q | Select-Object -Skip 850 -First 80; $e='scripts/extract_kpp_legacy_iss.py'; Get-Content -LiteralPath $e | Select-Object -Skip 1210 -First 55`
> - Ran `rg -n "TemporaryDirectory\(dir=ROOT\)" tests/test_freeze_kpp_iss_publication_v3.py`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_freeze_kpp_iss_publication_v3.py
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> @@
> -        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
> +        with tempfile.TemporaryDirectory() as tmp:
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && TMPDIR=/tmp/vast-kpp-regression-private-20260824 .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_freeze_kpp_iss_publication_v3'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B - <<"PY"
> import sys
> sys.path.insert(0,"scripts")
> import checkpoint_gstreamer_custom_publication_launcher_v3 as x
> print(x.PUBLICATION_READY)
> print(x.MISSING_RUNTIME_PINS)
> PY'`
> - Ran `rg -n "PUBLICATION_READY|MISSING_RUNTIME_PINS|SOURCE_SHA|EXPECTED|checkpoint_native_policy_runtime|publication_policy_contract" scripts/checkpoint_gstreamer_custom_publication_launcher_v3.py scripts/checkpoint_gstreamer_publication_runtime_v3.py deploy/gstreamer_custom/publication/runtime-source-allowlist.txt`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_publication_launcher_adapters_v3.py
> @@
> -                if system == "gstreamer_custom":
> -                    self.assertTrue(launcher.PUBLICATION_READY)
> +                if launcher.PUBLICATION_READY:
>                      self.assertTrue(assessment["native_runtime_invoked"])
>                      self.assertEqual(
>                          assessment["blockers"],
>                          [
> -                            "gstreamer_runtime_input_contract_missing"
> +                            f"{system}_runtime_input_contract_missing"
>                              if os.name == "posix"
> -                            else "gstreamer_publication_runtime_requires_linux_procfs"
> +                            else f"{system}_publication_runtime_requires_linux_procfs"
>                          ],
>                      )
>                  else:
> -                    self.assertFalse(launcher.PUBLICATION_READY)
>                      self.assertFalse(assessment["native_runtime_invoked"])
>                      self.assertEqual(
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_checkpoint_publication_launcher_adapters_v3.PublicationLauncherAdaptersV3Tests.test_real_entrypoints_remain_machine_readably_blocked_until_native_pins_exist'`
> - Ran `$p='scripts/backend_runtime_qualification.py'; Get-Content -LiteralPath $p | Select-Object -Skip 650 -First 420`
> - Ran `$p='scripts/publication_policy_qualification.py'; Get-Content -LiteralPath $p | Select-Object -Skip 540 -First 285`
> - Ran `rg -n '^def assess_|__all__' scripts/checkpoint_deepstream_qualification_fragment_v1.py scripts/checkpoint_savant_qualification_fragment_v3.py scripts/checkpoint_openvino_gva_qualification_fragment_v3.py scripts/checkpoint_gstreamer_custom_qualification_fragment_v3.py`
> - Ran `rg -n '^def .*qualification_fragment' scripts/checkpoint_deepstream_qualification_fragment_v1.py; Get-Content -LiteralPath 'scripts/checkpoint_deepstream_qualification_fragment_v1.py' | Select-Object -Skip 975 -First 35`
> - Ran `$p='scripts/checkpoint_deepstream_qualification_fragment_v1.py'; Get-Content -LiteralPath $p | Select-Object -Skip 780 -First 205`
> - Ran `rg --files scripts tests | rg 'pilot|qualification.*executor|qualif.*run|run_.*kpp.*v3'`
> - Ran `rg -n "runtime_inputs|policy_capability|calibration|launcher_evidence|evidence_files|dataset|duration_s|run_native|def run_|NativePublicationRequest" scripts/checkpoint_gstreamer_custom_publication_launcher_v3.py scripts/checkpoint_gstreamer_custom_container_coordinator_v3.py scripts/checkpoint_gstreamer_publication_runtime_v3.py | Select-Object -First 320`
> - Ran `$p='scripts/checkpoint_gstreamer_publication_runtime_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 100 -First 610; Get-Content -LiteralPath $p | Select-Object -Skip 1180 -First 330`
> - Ran `rg -n "RUNTIME_INPUT_KEY|vast_gstreamer_custom_publication_runtime_inputs_v3|build_.*runtime.*input|evidence_mapping" scripts tests --glob '*.py' | Select-Object -First 320`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_publication_policy_qualification.py
> @@
>  def _fixture(root: Path) -> tuple[Path, dict]:
> @@
>      index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
>      return index_path, index
> +
> +
> +def _fragment_bound_fixture(root: Path) -> tuple[Path, dict]:
> +    index_path, index = _fixture(root)
> +    fragment_bound = []
> +    for system in SYSTEMS:
> +        source_rows = [row for row in index["bindings"] if row["system"] == system]
> +        policy_rows = []
> +        for row in source_rows:
> +            artifact = row["implementation_artifact"]
> +            policy_rows.append({
> +                "role": "policy",
> +                "branch": row["branch"],
> +                "resource": row["resource"],
> +                "path": artifact["path"],
> +                "size": artifact["size_bytes"],
> +                "sha256": artifact["sha256"],
> +                "implementation_id": row["implementation_id"],
> +                "emitter_id": row["emitter_id"],
> +                "runtime_identity": copy.deepcopy(row["runtime_identity"]),
> +            })
> +        fragment = {
> +            "schema_version": 1,
> +            "artifact_kind": "vast_publication_qualification_system_fragment_v1",
> +            "system": system,
> +            "policy_bindings": policy_rows,
> +            "resource_bindings": [],
> +            "pilots": [],
> +        }
> +        fragment_path = root / "artifacts" / f"{system}-qualification-fragment.json"
> +        fragment_path.write_text(json.dumps(fragment, sort_keys=True) + "\n", encoding="utf-8")
> +        fragment_descriptor = _descriptor(root, fragment_path)
> +        for row in source_rows:
> +            binding_artifact = copy.deepcopy(row["implementation_artifact"])
> +            fragment_bound.append({
> +                "system": row["system"],
> +                "branch": row["branch"],
> +                "resource": row["resource"],
> +                "implementation_id": row["implementation_id"],
> +                "emitter_id": row["emitter_id"],
> +                "binding_artifact": binding_artifact,
> +                "fragment_artifact": copy.deepcopy(fragment_descriptor),
> +                "runtime_binding": (
> +                    f"{row['system']}:{row['branch']}:{row['resource']}:"
> +                    f"fragment-v1:{binding_artifact['sha256']}"
> +                ),
> +                "runtime_identity": copy.deepcopy(row["runtime_identity"]),
> +            })
> +    index["schema_version"] = 2
> +    index["bindings"] = fragment_bound
> +    index_path.write_text(json.dumps(index, sort_keys=True) + "\n", encoding="utf-8")
> +    return index_path, index
> +
> +
> +def _fake_fragment_validator(system: str, fragment_path: Path, project_root: Path) -> dict:
> +    del project_root
> +    value = json.loads(fragment_path.read_text(encoding="utf-8"))
> +    if value.get("system") != system:
> +        raise target.QualificationError("fake fragment system drift")
> +    return value
> @@
>      def test_runtime_identity_requires_terminal_and_exact_cpu_gpu_coordinates(self) -> None:
> @@
>              self.assertFalse(mismatched["passed"])
>              self.assertIn("CPU runtime identity", " ".join(mismatched["blockers"]))
> +
> +    def test_schema_v2_derives_bindings_only_from_revalidated_system_fragments(self) -> None:
> +        with tempfile.TemporaryDirectory() as tmp:
> +            root = Path(tmp)
> +            index_path, index = _fragment_bound_fixture(root)
> +            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
> +                assessment = target.assess_policy_qualification(
> +                    project_root=root,
> +                    index_path=index_path,
> +                    pilot_validator=_fake_pilot_validator,
> +                    fragment_validator=_fake_fragment_validator,
> +                )
> +            self.assertTrue(assessment["passed"], assessment["blockers"])
> +            binding = assessment["capability_manifest"]["systems"]["deepstream"][
> +                "branches"
> +            ]["plate_number"]["cpu"]
> +            source = next(
> +                row for row in index["bindings"]
> +                if (row["system"], row["branch"], row["resource"])
> +                == ("deepstream", "plate_number", "cpu")
> +            )
> +            self.assertEqual(binding["implementation_sha256"], source["binding_artifact"]["sha256"])
> +            self.assertEqual(binding["native_evidence"]["emitter_sha256"], source["binding_artifact"]["sha256"])
> +
> +            drifted = copy.deepcopy(index)
> +            row = next(
> +                value for value in drifted["bindings"]
> +                if (value["system"], value["branch"], value["resource"])
> +                == ("savant", "damage", "gpu")
> +            )
> +            row["emitter_id"] += "-relabelled"
> +            index_path.write_text(json.dumps(drifted, sort_keys=True) + "\n", encoding="utf-8")
> +            with mock.patch.object(target, "_load_policy_contract", return_value=_PolicyApi):
> +                rejected = target.assess_policy_qualification(
> +                    project_root=root,
> +                    index_path=index_path,
> +                    pilot_validator=_fake_pilot_validator,
> +                    fragment_validator=_fake_fragment_validator,
> +                )
> +            self.assertFalse(rejected["passed"])
> +            self.assertIn("fragment policy binding drift", " ".join(rejected["blockers"]))
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_schema_v2_derives_bindings_only_from_revalidated_system_fragments'`
> - Ran `rg -n "QUALIFICATION_INDEX_SCHEMA_VERSION" scripts tests`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\publication_policy_qualification.py
> @@
> -QUALIFICATION_INDEX_SCHEMA_VERSION = 1
> +QUALIFICATION_INDEX_SCHEMA_VERSION = 2
> +SUPPORTED_QUALIFICATION_INDEX_SCHEMA_VERSIONS = frozenset({1, 2})
> @@
>  PilotValidator = Callable[[dict[str, Any], dict[str, Any]], list[dict[str, Any]]]
> +FragmentValidator = Callable[[str, Path, Path], dict[str, Any]]
> @@
>  def _load_policy_contract() -> Any:
> @@
>      return policy_contract
> +
> +
> +def _default_fragment_validator(
> +    system: str,
> +    fragment_path: Path,
> +    project_root: Path,
> +) -> dict[str, Any]:
> +    if system == "deepstream":
> +        from checkpoint_deepstream_qualification_fragment_v1 import (
> +            validate_deepstream_qualification_fragment,
> +        )
> +
> +        return validate_deepstream_qualification_fragment(
> +            project_root=project_root,
> +            fragment_path=fragment_path,
> +        )
> +    modules = {
> +        "savant": "checkpoint_savant_qualification_fragment_v3",
> +        "openvino_gva": "checkpoint_openvino_gva_qualification_fragment_v3",
> +        "gstreamer_custom": "checkpoint_gstreamer_custom_qualification_fragment_v3",
> +    }
> +    module_name = modules.get(system)
> +    if module_name is None:
> +        raise QualificationError(f"unsupported qualification fragment system: {system}")
> +    module = __import__(module_name, fromlist=["assess_qualification_fragment"])
> +    assessment = module.assess_qualification_fragment(
> +        project_root=project_root,
> +        fragment_path=fragment_path,
> +    )
> +    if type(assessment) is not dict or assessment.get("passed") is not True:
> +        blockers = assessment.get("blockers", []) if isinstance(assessment, dict) else []
> +        raise QualificationError(
> +            f"{system} qualification fragment rejected: "
> +            + ", ".join(str(value) for value in blockers[:8])
> +        )
> +    return _load_json_object(fragment_path, f"{system} qualification fragment")
> @@
>  def _derive_manifest(bindings: Sequence[Any], *, project_root: Path, policy: Any) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
> @@
>      return manifest, observed
> +
> +
> +def _derive_fragment_bound_manifest(
> +    bindings: Sequence[Any],
> +    *,
> +    project_root: Path,
> +    policy: Any,
> +    fragment_validator: FragmentValidator,
> +) -> tuple[dict[str, Any], dict[tuple[str, str, str], dict[str, Any]]]:
> +    systems = tuple(policy.PUBLISHABLE_SYSTEMS)
> +    branches = tuple(policy.ANALYTICS_BRANCHES)
> +    resources = tuple(policy.RESOURCES)
> +    expected = {
> +        (system, branch, resource)
> +        for system in systems
> +        for branch in branches
> +        for resource in resources
> +    }
> +    if not isinstance(bindings, list) or len(bindings) != len(expected):
> +        raise QualificationError("binding set must contain exactly 32 system/branch/resource rows")
> +
> +    required = {
> +        "system",
> +        "branch",
> +        "resource",
> +        "implementation_id",
> +        "emitter_id",
> +        "binding_artifact",
> +        "fragment_artifact",
> +        "runtime_binding",
> +        "runtime_identity",
> +    }
> +    raw_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
> +    verified_bindings: dict[tuple[str, str, str], dict[str, Any]] = {}
> +    fragments: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
> +    binding_paths: set[str] = set()
> +    binding_inodes: set[tuple[int, int]] = set()
> +    fragment_paths: set[str] = set()
> +    fragment_inodes: set[tuple[int, int]] = set()
> +    implementation_ids: set[str] = set()
> +    emitter_ids: set[str] = set()
> +
> +    for position, raw in enumerate(bindings):
> +        if type(raw) is not dict or set(raw) != required:
> +            raise QualificationError(f"binding[{position}] fragment-bound fields drifted")
> +        key = _binding_key(raw)
> +        if key not in expected or key in raw_by_key:
> +            raise QualificationError(f"binding coverage duplicate/unknown: {key}")
> +        implementation_id = str(raw["implementation_id"])
> +        emitter_id = str(raw["emitter_id"])
> +        runtime_binding = str(raw["runtime_binding"])
> +        if not all(_stable_id(value) for value in (implementation_id, emitter_id, runtime_binding)):
> +            raise QualificationError(f"binding {key} contains a placeholder/unstable runtime identity")
> +        if implementation_id in implementation_ids or emitter_id in emitter_ids:
> +            raise QualificationError(f"binding {key} implementation/emitter identity is not unique")
> +        implementation_ids.add(implementation_id)
> +        emitter_ids.add(emitter_id)
> +        runtime_identity = _validate_runtime_identity(raw["runtime_identity"], key=key)
> +        binding_artifact = _verify_descriptor(
> +            project_root,
> +            raw["binding_artifact"],
> +            f"binding {key} physical binding",
> +            forbid_hardlinks=True,
> +        )
> +        if (
> +            binding_artifact["path"] in binding_paths
> +            or binding_artifact["filesystem_identity"] in binding_inodes
> +        ):
> +            raise QualificationError(f"binding {key} physical binding alias is prohibited")
> +        binding_paths.add(binding_artifact["path"])
> +        binding_inodes.add(binding_artifact["filesystem_identity"])
> +        expected_runtime_binding = (
> +            f"{key[0]}:{key[1]}:{key[2]}:fragment-v1:{binding_artifact['sha256']}"
> +        )
> +        if runtime_binding != expected_runtime_binding:
> +            raise QualificationError(f"binding {key} runtime_binding is not fragment-derived")
> +
> +        fragment_artifact = _verify_descriptor(
> +            project_root,
> +            raw["fragment_artifact"],
> +            f"binding {key} system fragment",
> +            forbid_hardlinks=True,
> +        )
> +        prior = fragments.get(key[0])
> +        fragment_descriptor = {
> +            field: fragment_artifact[field]
> +            for field in ("path", "size_bytes", "sha256", "filesystem_identity")
> +        }
> +        if prior is None:
> +            if (
> +                fragment_artifact["path"] in fragment_paths
> +                or fragment_artifact["filesystem_identity"] in fragment_inodes
> +            ):
> +                raise QualificationError(f"binding {key} system fragment alias is prohibited")
> +            fragment_paths.add(fragment_artifact["path"])
> +            fragment_inodes.add(fragment_artifact["filesystem_identity"])
> +            fragment_path = project_root / fragment_artifact["path"]
> +            fragment_value = fragment_validator(key[0], fragment_path, project_root)
> +            if type(fragment_value) is not dict:
> +                raise QualificationError(f"{key[0]} qualification fragment validator returned invalid data")
> +            fragments[key[0]] = (fragment_descriptor, fragment_value)
> +        elif prior[0] != fragment_descriptor:
> +            raise QualificationError(f"binding {key} system fragment descriptor drifted")
> +
> +        raw_by_key[key] = raw
> +        verified_bindings[key] = {
> +            "artifact": binding_artifact,
> +            "runtime_identity": runtime_identity,
> +            "runtime_binding": runtime_binding,
> +            "implementation_id": implementation_id,
> +            "emitter_id": emitter_id,
> +        }
> +
> +    if set(raw_by_key) != expected or set(fragments) != set(systems):
> +        raise QualificationError("binding_cell_set_mismatch")
> +
> +    observed: dict[tuple[str, str, str], dict[str, Any]] = {}
> +    expected_fragment_fields = {
> +        "schema_version",
> +        "artifact_kind",
> +        "system",
> +        "policy_bindings",
> +        "resource_bindings",
> +        "pilots",
> +    }
> +    for system in systems:
> +        fragment = fragments[system][1]
> +        if (
> +            set(fragment) != expected_fragment_fields
> +            or fragment.get("schema_version") != 1
> +            or fragment.get("artifact_kind")
> +            != "vast_publication_qualification_system_fragment_v1"
> +            or fragment.get("system") != system
> +        ):
> +            raise QualificationError(f"{system} qualification fragment identity drifted")
> +        rows = fragment.get("policy_bindings")
> +        if type(rows) is not list or len(rows) != len(branches) * len(resources):
> +            raise QualificationError(f"{system} qualification fragment policy coverage drifted")
> +        rows_by_coordinate: dict[tuple[str, str], dict[str, Any]] = {}
> +        for row in rows:
> +            if type(row) is not dict:
> +                raise QualificationError(f"{system} qualification fragment policy row invalid")
> +            coordinate = (str(row.get("branch", "")), str(row.get("resource", "")))
> +            if coordinate in rows_by_coordinate:
> +                raise QualificationError(f"{system} qualification fragment policy row duplicate")
> +            rows_by_coordinate[coordinate] = row
> +        if set(rows_by_coordinate) != {(branch, resource) for branch in branches for resource in resources}:
> +            raise QualificationError(f"{system} qualification fragment policy coverage drifted")
> +
> +        for branch in branches:
> +            for resource in resources:
> +                key = (system, branch, resource)
> +                verified = verified_bindings[key]
> +                artifact = verified["artifact"]
> +                fragment_row = rows_by_coordinate[(branch, resource)]
> +                if not all(
> +                    (
> +                        fragment_row.get("role") == "policy",
> +                        fragment_row.get("branch") == branch,
> +                        fragment_row.get("resource") == resource,
> +                        fragment_row.get("path") == artifact["path"],
> +                        fragment_row.get("size") == artifact["size_bytes"],
> +                        fragment_row.get("sha256") == artifact["sha256"],
> +                        fragment_row.get("implementation_id") == verified["implementation_id"],
> +                        fragment_row.get("emitter_id") == verified["emitter_id"],
> +                        fragment_row.get("runtime_identity") == verified["runtime_identity"],
> +                    )
> +                ):
> +                    raise QualificationError(f"binding {key} fragment policy binding drift")
> +                identity = verified["runtime_identity"]
> +                observed[key] = {
> +                    "status": "implemented_and_native_evidence_bound",
> +                    "implementation_id": verified["implementation_id"],
> +                    "implementation_sha256": artifact["sha256"],
> +                    "runtime_binding": verified["runtime_binding"],
> +                    "runtime_identity": identity,
> +                    **identity,
> +                    "native_evidence": {
> +                        "status": "accepted_native_runtime_emitter",
> +                        "telemetry_source": "native",
> +                        "emitter_id": verified["emitter_id"],
> +                        "emitter_sha256": artifact["sha256"],
> +                        "implementation_id_field": "implementation_id",
> +                        "resource_field": "selected_resource",
> +                    },
> +                }
> +
> +    manifest = {
> +        "schema_version": 1,
> +        "artifact_kind": "vast_publication_policy_capability_manifest",
> +        "policy_scope": policy.POLICY_SCOPE,
> +        "policy_contract_sha256": policy.policy_contract_identity()["sha256"],
> +        "systems": {
> +            system: {
> +                "branches": {
> +                    branch: {
> +                        resource: observed[(system, branch, resource)]
> +                        for resource in resources
> +                    }
> +                    for branch in branches
> +                }
> +            }
> +            for system in systems
> +        },
> +    }
> +    assessment = policy.assess_capability_manifest(manifest)
> +    if not assessment.get("passed"):
> +        raise QualificationError(
> +            "derived capability manifest rejected: "
> +            + ", ".join(assessment.get("blockers", [])[:8])
> +        )
> +    return manifest, observed
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\publication_policy_qualification.py
> @@
>  def assess_policy_qualification(
>      *,
>      project_root: Path,
>      index_path: Path,
>      pilot_validator: PilotValidator | None = None,
> +    fragment_validator: FragmentValidator | None = None,
>  ) -> dict[str, Any]:
> @@
>          schema_ok = (
>              set(index) == expected_fields
> -            and index.get("schema_version") == QUALIFICATION_INDEX_SCHEMA_VERSION
> +            and index.get("schema_version")
> +            in SUPPORTED_QUALIFICATION_INDEX_SCHEMA_VERSIONS
>              and index.get("artifact_kind") == "vast_publication_policy_qualification_index"
>          )
> @@
>          if index.get("policy_contract_sha256") != contract_sha:
>              raise QualificationError("qualification index policy contract SHA-256 drifted")
>          dataset = _verify_descriptor(root, index["dataset_manifest"], "dataset manifest", forbid_hardlinks=True)
> -        manifest, bindings = _derive_manifest(index["bindings"], project_root=root, policy=policy)
> +        if index["schema_version"] == 1:
> +            manifest, bindings = _derive_manifest(
> +                index["bindings"], project_root=root, policy=policy,
> +            )
> +        else:
> +            manifest, bindings = _derive_fragment_bound_manifest(
> +                index["bindings"],
> +                project_root=root,
> +                policy=policy,
> +                fragment_validator=(
> +                    fragment_validator or _default_fragment_validator
> +                ),
> +            )
> @@
>  def promote_policy_qualification(
>      *,
>      project_root: Path,
>      index_path: Path,
>      output_dir: Path,
>      pilot_validator: PilotValidator | None = None,
> +    fragment_validator: FragmentValidator | None = None,
>  ) -> dict[str, Any]:
> @@
>      assessment = assess_policy_qualification(
> -        project_root=project_root, index_path=index_path, pilot_validator=pilot_validator,
> +        project_root=project_root,
> +        index_path=index_path,
> +        pilot_validator=pilot_validator,
> +        fragment_validator=fragment_validator,
>      )
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_publication_policy_qualification.PublicationPolicyQualificationTests.test_schema_v2_derives_bindings_only_from_revalidated_system_fragments'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && .publication-runtime/full-publication-cp312-v1/bin/python3.12 -B -m unittest -v tests.test_publication_policy_qualification tests.test_publication_policy_contract tests.test_checkpoint_native_policy_runtime'`
>
> </details>
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `Get-ChildItem -LiteralPath artifacts -Directory | Select-Object -ExpandProperty Name | Sort-Object; Get-ChildItem -LiteralPath artifacts -Filter qualification_fragment.json -File -Recurse | Select-Object -ExpandProperty FullName`
> - Ran `$patch = @'
> *** Begin Patch
> *** Add File: E:\STUDY\VAST\tests\test_publication_policy_qualification_index_v2.py
> +from __future__ import annotations
> +
> +import json
> +import sys
> +import tempfile
> +import unittest
> +from pathlib import Path
> +from unittest import mock
> +
> +
> +ROOT = Path(__file__).resolve().parents[1]
> +sys.path.insert(0, str(ROOT / "scripts"))
> +
> +import publication_policy_qualification as qualification  # noqa: E402
> +import publication_policy_qualification_index_v2 as target  # noqa: E402
> +from tests.test_publication_policy_qualification import (  # noqa: E402
> +    SYSTEMS,
> +    _PolicyApi,
> +    _fake_fragment_validator,
> +    _fake_pilot_validator,
> +    _fragment_bound_fixture,
> +)
> +
> +
> +class PublicationPolicyQualificationIndexV2Tests(unittest.TestCase):
> +    def _fixture(self, root: Path) -> tuple[dict[str, Path], Path]:
> +        _index_path, index = _fragment_bound_fixture(root)
> +        fragments = {}
> +        for system in SYSTEMS:
> +            row = next(value for value in index["bindings"] if value["system"] == system)
> +            fragments[system] = root / row["fragment_artifact"]["path"]
> +        return fragments, root / "pilots"
> +
> +    def test_builds_nonaccepted_candidate_and_complete_fragment_bound_index(self) -> None:
> +        with tempfile.TemporaryDirectory() as tmp:
> +            root = Path(tmp)
> +            fragments, pilots = self._fixture(root)
> +            output = root / "qualification-v2"
> +            result = target.build_policy_qualification_index_v2(
> +                project_root=root,
> +                fragment_paths=fragments,
> +                pilot_root=pilots,
> +                output_dir=output,
> +                policy=_PolicyApi,
> +                fragment_validator=_fake_fragment_validator,
> +            )
> +            candidate = json.loads(result["candidate_manifest_path"].read_text(encoding="utf-8"))
> +            receipt = json.loads(result["candidate_receipt_path"].read_text(encoding="utf-8"))
> +            index = json.loads(result["index_path"].read_text(encoding="utf-8"))
> +            self.assertEqual(index["schema_version"], 2)
> +            self.assertEqual(len(index["bindings"]), 32)
> +            self.assertEqual(len(index["pilots"]), 32)
> +            self.assertFalse(receipt["accepted"])
> +            self.assertFalse(receipt["publication_ready"])
> +            self.assertEqual(receipt["status"], "qualification_candidate_not_accepted")
> +            self.assertEqual(
> +                receipt["candidate_manifest"]["sha256"],
> +                target.sha256_file(result["candidate_manifest_path"]),
> +            )
> +            self.assertEqual(
> +                candidate["artifact_kind"],
> +                "vast_publication_policy_capability_manifest",
> +            )
> +
> +            with mock.patch.object(qualification, "_load_policy_contract", return_value=_PolicyApi):
> +                assessment = qualification.assess_policy_qualification(
> +                    project_root=root,
> +                    index_path=result["index_path"],
> +                    pilot_validator=_fake_pilot_validator,
> +                    fragment_validator=_fake_fragment_validator,
> +                )
> +            self.assertTrue(assessment["passed"], assessment["blockers"])
> +
> +    def test_missing_pilot_evidence_and_fragment_drift_fail_before_commit(self) -> None:
> +        with tempfile.TemporaryDirectory() as tmp:
> +            root = Path(tmp)
> +            fragments, pilots = self._fixture(root)
> +            missing = next(pilots.rglob("frames.csv"))
> +            missing.unlink()
> +            with self.assertRaisesRegex(target.PolicyQualificationIndexV2Error, "pilot evidence"):
> +                target.build_policy_qualification_index_v2(
> +                    project_root=root,
> +                    fragment_paths=fragments,
> +                    pilot_root=pilots,
> +                    output_dir=root / "missing-output",
> +                    policy=_PolicyApi,
> +                    fragment_validator=_fake_fragment_validator,
> +                )
> +            self.assertFalse((root / "missing-output").exists())
> +
> +            fragments, pilots = self._fixture(root / "second")
> +            fragment = fragments["deepstream"]
> +            fragment.write_text("{}\n", encoding="utf-8")
> +            with self.assertRaisesRegex(target.PolicyQualificationIndexV2Error, "fragment"):
> +                target.build_policy_qualification_index_v2(
> +                    project_root=root / "second",
> +                    fragment_paths=fragments,
> +                    pilot_root=pilots,
> +                    output_dir=root / "second" / "drift-output",
> +                    policy=_PolicyApi,
> +                    fragment_validator=_fake_fragment_validator,
> +                )
> +            self.assertFalse((root / "second" / "drift-output").exists())
> +
> +
> +if __name__ == "__main__":
> +    unittest.main()
> *** End Patch
> '@
> & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Продолжаю с центрального контура квалификации: сначала фиксирую сборщик индекса v2 как атомарный fail-closed этап, затем сведу в него уже готовые Savant/GStreamer и результаты остальных рантаймов. Ограничение памяти WSL и boot-profile не меняю.
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `$f='tests/test_publication_policy_qualification_index_v2.py'; if (Test-Path -LiteralPath $f) { Get-Item -LiteralPath $f | Select-Object FullName,Length,LastWriteTime; Get-Content -LiteralPath $f } else { 'MISSING' }`
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST -- /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_publication_policy_qualification_index_v2 -v`
>
> </details>
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `rg -n "^(QUALIFICATION_INDEX|PILOT_EVIDENCE_ROLES|SYSTEMS|PUBLISHABLE_SYSTEMS|def |class )|artifact_kind|bindings|pilots|capability" scripts/publication_policy_qualification.py tests/test_publication_policy_qualification.py | Select-Object -First 260`
> - Ran `$paths=@('scripts/publication_policy_qualification.py','tests/test_publication_policy_qualification.py'); foreach($p in $paths){ "FILE $p"; $lines=Get-Content -LiteralPath $p; if($p -like 'scripts/*'){ $ranges=@(@(1,120),@(314,525),@(832,982),@(982,1080)) } else { $ranges=@(@(1,216)) }; foreach($range in $ranges){ "LINES $($range[0])-$($range[1])"; $lines[($range[0]-1)..([Math]::Min($range[1]-1,$lines.Count-1))] } }`
>
> </details>
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `$p='scripts/publication_policy_qualification.py'; $lines=Get-Content -LiteralPath $p; $lines[156..313]`
> - Ran `$p='scripts/publication_policy_qualification.py'; $lines=Get-Content -LiteralPath $p; $lines[525..565]`
>
> </details>
>
> Красный тест подтвердил отсутствие самого сборщика v2. Сейчас добавляю его с двумя принципиальными гарантиями: он принимает только заново провалидированные физические fragment/pilot-файлы и публикует candidate/index/receipt одной атомарной операцией; candidate-рецепт явно не является допуском к полному прогону.
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran ```$patch = @'
> *** Begin Patch
> *** Add File: scripts/publication_policy_qualification_index_v2.py
> +#!/usr/bin/env python3
> +"""Build a fragment-bound policy qualification index without accepting it.
> +
> +The resulting capability manifest is a qualification candidate.  It may be
> +used to execute forced-resource pilots, but it is deliberately accompanied by
> +a non-acceptance receipt and is never a full-publication authority.  Only
> +``publication_policy_qualification.promote_policy_qualification`` can derive
> +and atomically promote the accepted capability/calibration pair from all 32
> +native pilot cells.
> +"""
> +from __future__ import annotations
> +
> +import argparse
> +import hashlib
> +import json
> +import os
> +import shutil
> +import stat
> +import tempfile
> +from pathlib import Path
> +from typing import Any, Mapping
> +
> +import publication_policy_qualification as qualification
> +
> +
> +INDEX_FILENAME = "checkpoint_policy_qualification_index.v2.json"
> +CANDIDATE_MANIFEST_FILENAME = "checkpoint_policy_capability_candidate_manifest.json"
> +CANDIDATE_RECEIPT_FILENAME = "checkpoint_policy_qualification_candidate_receipt.json"
> +
> +DEFAULT_FRAGMENT_PATHS = {
> +    "deepstream": Path(
> +        "artifacts/deepstream_publication_v3/qualification/qualification_fragment.json"
> +    ),
> +    "savant": Path(
> +        "artifacts/savant_publication_v3/qualification/qualification_fragment.json"
> +    ),
> +    "openvino_gva": Path(
> +        "artifacts/openvino_gva_publication_v3/qualification/qualification_fragment.json"
> +    ),
> +    "gstreamer_custom": Path(
> +        "artifacts/gstreamer_publication_v3/qualification/qualification_fragment.json"
> +    ),
> +}
> +
> +PILOT_EVIDENCE_FILENAMES = {
> +    "checkpoint_acceptance": "checkpoint_publication_acceptance.json",
> +    "policy_decisions_jsonl": "publication_policy_decisions.jsonl",
> +    "resource_intervals": "resource_intervals.csv",
> +    "ingress_ledger": "ingress_ledger.csv",
> +    "topology_events": "topology_events.csv",
> +    "frames": "frames.csv",
> +    "frame_events": "frame_events.csv",
> +    "branch_terminals": "branch_terminals.csv",
> +}
> +
> +
> +class PolicyQualificationIndexV2Error(RuntimeError):
> +    """An input or atomic candidate-index publication is unsafe."""
> +
> +
> +def sha256_file(path: Path) -> str:
> +    """Return the SHA-256 of *path* without trusting file metadata."""
> +    digest = hashlib.sha256()
> +    with Path(path).open("rb") as source:
> +        for chunk in iter(lambda: source.read(1024 * 1024), b""):
> +            digest.update(chunk)
> +    return digest.hexdigest()
> +
> +
> +def _canonical_bytes(value: Any) -> bytes:
> +    try:
> +        return (
> +            json.dumps(
> +                value,
> +                sort_keys=True,
> +                separators=(",", ":"),
> +                ensure_ascii=True,
> +                allow_nan=False,
> +            ).encode("utf-8")
> +            + b"\n"
> +        )
> +    except (TypeError, ValueError) as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            "qualification candidate is not canonical JSON"
> +        ) from exc
> +
> +
> +def _is_link(path: Path) -> bool:
> +    try:
> +        info = path.lstat()
> +    except OSError as exc:
> +        raise PolicyQualificationIndexV2Error(f"path stat failed: {path}: {exc}") from exc
> +    attributes = int(getattr(info, "st_file_attributes", 0))
> +    reparse_flag = int(getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
> +    return stat.S_ISLNK(info.st_mode) or bool(attributes & reparse_flag)
> +
> +
> +def _root(project_root: Path) -> Path:
> +    try:
> +        root = Path(project_root).resolve(strict=True)
> +    except OSError as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            f"project_root is unavailable: {project_root}"
> +        ) from exc
> +    if not root.is_dir() or _is_link(root):
> +        raise PolicyQualificationIndexV2Error(
> +            "project_root must be a physical non-reparse directory"
> +        )
> +    return root
> +
> +
> +def _relative_under_root(root: Path, value: Path, label: str) -> str:
> +    candidate = Path(value)
> +    if not candidate.is_absolute():
> +        candidate = root / candidate
> +    try:
> +        resolved = candidate.resolve(strict=True)
> +        relative = resolved.relative_to(root)
> +    except (OSError, ValueError) as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            f"{label} must exist under project_root"
> +        ) from exc
> +    relative_text = relative.as_posix()
> +    if not relative_text or any(part in ("", ".", "..") for part in relative.parts):
> +        raise PolicyQualificationIndexV2Error(f"{label} path is not normalized")
> +    cursor = root
> +    for part in relative.parts:
> +        cursor = cursor / part
> +        if _is_link(cursor):
> +            raise PolicyQualificationIndexV2Error(
> +                f"{label} path contains a symlink/reparse point"
> +            )
> +    return relative_text
> +
> +
> +def _regular_file(root: Path, value: Path | str, label: str) -> Path:
> +    relative = _relative_under_root(root, Path(value), label)
> +    path = root.joinpath(*Path(relative).parts)
> +    try:
> +        mode = path.lstat().st_mode
> +    except OSError as exc:
> +        raise PolicyQualificationIndexV2Error(f"{label} stat failed") from exc
> +    if not stat.S_ISREG(mode):
> +        raise PolicyQualificationIndexV2Error(f"{label} is not a regular file")
> +    return path
> +
> +
> +def _physical_directory(root: Path, value: Path, label: str) -> Path:
> +    relative = _relative_under_root(root, value, label)
> +    directory = root.joinpath(*Path(relative).parts)
> +    if not directory.is_dir():
> +        raise PolicyQualificationIndexV2Error(f"{label} is not a directory")
> +    return directory
> +
> +
> +def _descriptor(root: Path, value: Path | str, label: str) -> dict[str, Any]:
> +    path = _regular_file(root, value, label)
> +    before = path.stat()
> +    if int(before.st_nlink) != 1:
> +        raise PolicyQualificationIndexV2Error(f"{label} hardlink alias is prohibited")
> +    digest = sha256_file(path)
> +    after = path.stat()
> +    before_identity = (
> +        before.st_dev,
> +        before.st_ino,
> +        before.st_size,
> +        before.st_mtime_ns,
> +        int(getattr(before, "st_ctime_ns", 0)),
> +    )
> +    after_identity = (
> +        after.st_dev,
> +        after.st_ino,
> +        after.st_size,
> +        after.st_mtime_ns,
> +        int(getattr(after, "st_ctime_ns", 0)),
> +    )
> +    if before_identity != after_identity:
> +        raise PolicyQualificationIndexV2Error(f"{label} changed while hashing")
> +    if before.st_size <= 0:
> +        raise PolicyQualificationIndexV2Error(f"{label} is empty")
> +    return {
> +        "path": path.relative_to(root).as_posix(),
> +        "size_bytes": int(before.st_size),
> +        "sha256": digest,
> +    }
> +
> +
> +def _read_fragment(
> +    *,
> +    root: Path,
> +    system: str,
> +    path_value: Path,
> +    fragment_validator: qualification.FragmentValidator,
> +) -> tuple[Path, dict[str, Any], dict[str, Any]]:
> +    path = _regular_file(root, path_value, f"{system} fragment")
> +    descriptor = _descriptor(root, path, f"{system} fragment")
> +    try:
> +        fragment = fragment_validator(system, path, root)
> +    except Exception as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            f"{system} fragment validation failed: {exc}"
> +        ) from exc
> +    expected_fields = {
> +        "schema_version",
> +        "artifact_kind",
> +        "system",
> +        "policy_bindings",
> +        "resource_bindings",
> +        "pilots",
> +    }
> +    if (
> +        type(fragment) is not dict
> +        or set(fragment) != expected_fields
> +        or fragment.get("schema_version") != 1
> +        or fragment.get("artifact_kind")
> +        != "vast_publication_qualification_system_fragment_v1"
> +        or fragment.get("system") != system
> +    ):
> +        raise PolicyQualificationIndexV2Error(
> +            f"{system} fragment identity/schema drifted"
> +        )
> +    return path, descriptor, fragment
> +
> +
> +def _build_bindings(
> +    *,
> +    root: Path,
> +    fragment_paths: Mapping[str, Path],
> +    policy: Any,
> +    fragment_validator: qualification.FragmentValidator,
> +) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
> +    systems = tuple(policy.PUBLISHABLE_SYSTEMS)
> +    branches = tuple(policy.ANALYTICS_BRANCHES)
> +    resources = tuple(policy.RESOURCES)
> +    if set(fragment_paths) != set(systems):
> +        raise PolicyQualificationIndexV2Error(
> +            "fragment system set must exactly match the four publishable systems"
> +        )
> +
> +    fragments: dict[str, dict[str, Any]] = {}
> +    fragment_descriptors: dict[str, dict[str, Any]] = {}
> +    for system in systems:
> +        _, descriptor, fragment = _read_fragment(
> +            root=root,
> +            system=system,
> +            path_value=Path(fragment_paths[system]),
> +            fragment_validator=fragment_validator,
> +        )
> +        fragments[system] = fragment
> +        fragment_descriptors[system] = descriptor
> +
> +    bindings: list[dict[str, Any]] = []
> +    for system in systems:
> +        rows = fragments[system].get("policy_bindings")
> +        if type(rows) is not list or len(rows) != len(branches) * len(resources):
> +            raise PolicyQualificationIndexV2Error(
> +                f"{system} fragment policy coverage drifted"
> +            )
> +        by_coordinate: dict[tuple[str, str], dict[str, Any]] = {}
> +        for position, row in enumerate(rows):
> +            if type(row) is not dict:
> +                raise PolicyQualificationIndexV2Error(
> +                    f"{system} fragment policy binding[{position}] is invalid"
> +                )
> +            coordinate = (str(row.get("branch", "")), str(row.get("resource", "")))
> +            if coordinate in by_coordinate:
> +                raise PolicyQualificationIndexV2Error(
> +                    f"{system} fragment contains a duplicate policy binding"
> +                )
> +            by_coordinate[coordinate] = row
> +        expected = {(branch, resource) for branch in branches for resource in resources}
> +        if set(by_coordinate) != expected:
> +            raise PolicyQualificationIndexV2Error(
> +                f"{system} fragment policy coordinate set drifted"
> +            )
> +
> +        for branch in branches:
> +            for resource in resources:
> +                row = by_coordinate[(branch, resource)]
> +                if row.get("role") != "policy":
> +                    raise PolicyQualificationIndexV2Error(
> +                        f"{system} fragment {branch}/{resource} role drifted"
> +                    )
> +                try:
> +                    artifact = _descriptor(
> +                        root,
> +                        str(row["path"]),
> +                        f"{system} fragment {branch}/{resource} physical binding",
> +                    )
> +                except (KeyError, TypeError, PolicyQualificationIndexV2Error) as exc:
> +                    raise PolicyQualificationIndexV2Error(
> +                        f"{system} fragment {branch}/{resource} binding artifact failed: {exc}"
> +                    ) from exc
> +                if (
> +                    row.get("size") != artifact["size_bytes"]
> +                    or row.get("sha256") != artifact["sha256"]
> +                ):
> +                    raise PolicyQualificationIndexV2Error(
> +                        f"{system} fragment {branch}/{resource} binding size/SHA drifted"
> +                    )
> +                binding_sha = artifact["sha256"]
> +                bindings.append(
> +                    {
> +                        "system": system,
> +                        "branch": branch,
> +                        "resource": resource,
> +                        "implementation_id": row.get("implementation_id"),
> +                        "emitter_id": row.get("emitter_id"),
> +                        "binding_artifact": artifact,
> +                        "fragment_artifact": dict(fragment_descriptors[system]),
> +                        "runtime_binding": (
> +                            f"{system}:{branch}:{resource}:fragment-v1:{binding_sha}"
> +                        ),
> +                        "runtime_identity": row.get("runtime_identity"),
> +                    }
> +                )
> +    return bindings, fragments
> +
> +
> +def _build_pilots(
> +    *, root: Path, pilot_root: Path, policy: Any
> +) -> list[dict[str, Any]]:
> +    root_directory = _physical_directory(root, pilot_root, "pilot_root")
> +    pilots: list[dict[str, Any]] = []
> +    for system in policy.PUBLISHABLE_SYSTEMS:
> +        for resource in policy.RESOURCES:
> +            for codec in qualification.CODECS:
> +                for topology in qualification.TOPOLOGIES:
> +                    arm = root_directory / system / resource / codec / topology
> +                    try:
> +                        arm = _physical_directory(root, arm, "pilot arm")
> +                    except PolicyQualificationIndexV2Error as exc:
> +                        raise PolicyQualificationIndexV2Error(
> +                            "pilot evidence arm is missing or unsafe: "
> +                            f"{system}/{resource}/{codec}/{topology}"
> +                        ) from exc
> +                    evidence: dict[str, dict[str, Any]] = {}
> +                    identities: set[tuple[int, int]] = set()
> +                    for role in qualification.PILOT_EVIDENCE_ROLES:
> +                        filename = PILOT_EVIDENCE_FILENAMES[role]
> +                        try:
> +                            descriptor = _descriptor(
> +                                root,
> +                                arm / filename,
> +                                f"pilot evidence {system}/{resource}/{codec}/{topology}/{role}",
> +                            )
> +                            info = (root / descriptor["path"]).stat()
> +                        except (OSError, PolicyQualificationIndexV2Error) as exc:
> +                            raise PolicyQualificationIndexV2Error(
> +                                "pilot evidence is missing or unsafe: "
> +                                f"{system}/{resource}/{codec}/{topology}/{role}"
> +                            ) from exc
> +                        identity = (int(info.st_dev), int(info.st_ino))
> +                        if identity in identities:
> +                            raise PolicyQualificationIndexV2Error(
> +                                "pilot evidence alias is prohibited: "
> +                                f"{system}/{resource}/{codec}/{topology}/{role}"
> +                            )
> +                        identities.add(identity)
> +                        evidence[role] = descriptor
> +                    pilots.append(
> +                        {
> +                            "system": system,
> +                            "resource": resource,
> +                            "codec": codec,
> +                            "topology_kind": topology,
> +                            "evidence": evidence,
> +                        }
> +                    )
> +    if len(pilots) != 32:
> +        raise PolicyQualificationIndexV2Error(
> +            "pilot evidence cell set must contain exactly 32 cells"
> +        )
> +    return pilots
> +
> +
> +def _output_destination(root: Path, output_dir: Path) -> Path:
> +    candidate = Path(output_dir)
> +    if not candidate.is_absolute():
> +        candidate = root / candidate
> +    if candidate.exists():
> +        raise PolicyQualificationIndexV2Error(
> +            "immutable qualification candidate output already exists"
> +        )
> +    try:
> +        parent = candidate.parent.resolve(strict=True)
> +        parent.relative_to(root)
> +    except (OSError, ValueError) as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            "output_dir parent must be a physical directory under project_root"
> +        ) from exc
> +    _physical_directory(root, parent, "output_dir parent")
> +    return parent / candidate.name
> +
> +
> +def _descriptor_for_payload(root: Path, final_path: Path, payload: bytes) -> dict[str, Any]:
> +    return {
> +        "path": final_path.relative_to(root).as_posix(),
> +        "size_bytes": len(payload),
> +        "sha256": hashlib.sha256(payload).hexdigest(),
> +    }
> +
> +
> +def _write_fsync(path: Path, payload: bytes) -> None:
> +    with path.open("xb") as output:
> +        output.write(payload)
> +        output.flush()
> +        os.fsync(output.fileno())
> +
> +
> +def _commit_output(
> +    *,
> +    root: Path,
> +    destination: Path,
> +    index: dict[str, Any],
> +    candidate_manifest: dict[str, Any],
> +) -> dict[str, Path]:
> +    parent = destination.parent
> +    staging = Path(tempfile.mkdtemp(prefix=".qualification-index-v2.", dir=parent))
> +    try:
> +        index_payload = _canonical_bytes(index)
> +        candidate_payload = _canonical_bytes(candidate_manifest)
> +        index_final = destination / INDEX_FILENAME
> +        candidate_final = destination / CANDIDATE_MANIFEST_FILENAME
> +        receipt_final = destination / CANDIDATE_RECEIPT_FILENAME
> +        index_descriptor = _descriptor_for_payload(root, index_final, index_payload)
> +        candidate_descriptor = _descriptor_for_payload(
> +            root, candidate_final, candidate_payload
> +        )
> +        receipt: dict[str, Any] = {
> +            "schema_version": 1,
> +            "artifact_kind": "vast_publication_policy_qualification_candidate_receipt",
> +            "status": "qualification_candidate_not_accepted",
> +            "accepted": False,
> +            "publication_ready": False,
> +            "scope": "forced_resource_qualification_pilots_only",
> +            "policy_contract_sha256": candidate_manifest["policy_contract_sha256"],
> +            "qualification_index": index_descriptor,
> +            "candidate_manifest": candidate_descriptor,
> +            "blockers": [
> +                "candidate_is_not_a_full_publication_authority",
> +                "requires_32_cell_native_pilot_validation_and_atomic_promotion",
> +            ],
> +        }
> +        receipt["sha256"] = hashlib.sha256(
> +            _canonical_bytes(receipt).rstrip(b"\n")
> +        ).hexdigest()
> +        receipt_payload = _canonical_bytes(receipt)
> +
> +        _write_fsync(staging / INDEX_FILENAME, index_payload)
> +        _write_fsync(staging / CANDIDATE_MANIFEST_FILENAME, candidate_payload)
> +        _write_fsync(staging / CANDIDATE_RECEIPT_FILENAME, receipt_payload)
> +        directory_descriptor = None
> +        try:
> +            directory_descriptor = os.open(
> +                staging, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
> +            )
> +            os.fsync(directory_descriptor)
> +        except OSError:
> +            pass
> +        finally:
> +            if directory_descriptor is not None:
> +                os.close(directory_descriptor)
> +
> +        os.replace(staging, destination)
> +        staging = Path()
> +        directory_descriptor = None
> +        try:
> +            directory_descriptor = os.open(
> +                parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
> +            )
> +            os.fsync(directory_descriptor)
> +        except OSError:
> +            pass
> +        finally:
> +            if directory_descriptor is not None:
> +                os.close(directory_descriptor)
> +        return {
> +            "index_path": index_final,
> +            "candidate_manifest_path": candidate_final,
> +            "candidate_receipt_path": receipt_final,
> +        }
> +    except Exception as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            f"atomic qualification candidate commit failed: {exc}"
> +        ) from exc
> +    finally:
> +        if staging and staging.exists():
> +            shutil.rmtree(staging)
> +
> +
> +def build_policy_qualification_index_v2(
> +    *,
> +    project_root: Path,
> +    fragment_paths: Mapping[str, Path],
> +    pilot_root: Path,
> +    output_dir: Path,
> +    policy: Any | None = None,
> +    fragment_validator: qualification.FragmentValidator | None = None,
> +) -> dict[str, Path]:
> +    """Validate all physical inputs and atomically publish a nonaccepted index."""
> +    root = _root(project_root)
> +    policy_api = policy or qualification._load_policy_contract()
> +    validator = fragment_validator or qualification._default_fragment_validator
> +    destination = _output_destination(root, output_dir)
> +
> +    try:
> +        bindings, _ = _build_bindings(
> +            root=root,
> +            fragment_paths=fragment_paths,
> +            policy=policy_api,
> +            fragment_validator=validator,
> +        )
> +        candidate_manifest, _ = qualification._derive_fragment_bound_manifest(
> +            bindings,
> +            project_root=root,
> +            policy=policy_api,
> +            fragment_validator=validator,
> +        )
> +    except PolicyQualificationIndexV2Error:
> +        raise
> +    except Exception as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            f"fragment-bound capability candidate validation failed: {exc}"
> +        ) from exc
> +
> +    pilots = _build_pilots(root=root, pilot_root=pilot_root, policy=policy_api)
> +    dataset = _descriptor(root, root / "configs" / "datasets.yaml", "dataset manifest")
> +    index = {
> +        "schema_version": qualification.QUALIFICATION_INDEX_SCHEMA_VERSION,
> +        "artifact_kind": "vast_publication_policy_qualification_index",
> +        "policy_contract_sha256": policy_api.policy_contract_identity()["sha256"],
> +        "dataset_manifest": dataset,
> +        "bindings": bindings,
> +        "pilots": pilots,
> +    }
> +    return _commit_output(
> +        root=root,
> +        destination=destination,
> +        index=index,
> +        candidate_manifest=candidate_manifest,
> +    )
> +
> +
> +def _parse_args() -> argparse.Namespace:
> +    parser = argparse.ArgumentParser(description=__doc__)
> +    parser.add_argument(
> +        "--project-root",
> +        type=Path,
> +        default=Path(__file__).resolve().parents[1],
> +    )
> +    parser.add_argument("--pilot-root", type=Path, required=True)
> +    parser.add_argument("--output-dir", type=Path, required=True)
> +    for system, default in DEFAULT_FRAGMENT_PATHS.items():
> +        parser.add_argument(
> +            f"--{system.replace('_', '-')}-fragment",
> +            dest=f"{system}_fragment",
> +            type=Path,
> +            default=default,
> +        )
> +    return parser.parse_args()
> +
> +
> +def main() -> int:
> +    args = _parse_args()
> +    fragments = {
> +        system: getattr(args, f"{system}_fragment")
> +        for system in DEFAULT_FRAGMENT_PATHS
> +    }
> +    result = build_policy_qualification_index_v2(
> +        project_root=args.project_root,
> +        fragment_paths=fragments,
> +        pilot_root=args.pilot_root,
> +        output_dir=args.output_dir,
> +    )
> +    print(
> +        json.dumps(
> +            {key: str(value) for key, value in result.items()},
> +            sort_keys=True,
> +        )
> +    )
> +    return 0
> +
> +
> +if __name__ == "__main__":
> +    raise SystemExit(main())
> +
> +
> +__all__ = [
> +    "CANDIDATE_MANIFEST_FILENAME",
> +    "CANDIDATE_RECEIPT_FILENAME",
> +    "INDEX_FILENAME",
> +    "PolicyQualificationIndexV2Error",
> +    "build_policy_qualification_index_v2",
> +    "sha256_file",
> +]
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch```
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST -- /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_publication_policy_qualification_index_v2 -v`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/publication_policy_qualification_index_v2.py
> @@
> -    staging = Path(tempfile.mkdtemp(prefix=".qualification-index-v2.", dir=parent))
> +    staging: Path | None = Path(
> +        tempfile.mkdtemp(prefix=".qualification-index-v2.", dir=parent)
> +    )
> @@
> -        _write_fsync(staging / INDEX_FILENAME, index_payload)
> -        _write_fsync(staging / CANDIDATE_MANIFEST_FILENAME, candidate_payload)
> -        _write_fsync(staging / CANDIDATE_RECEIPT_FILENAME, receipt_payload)
> +        _write_fsync(staging / INDEX_FILENAME, index_payload)
> +        _write_fsync(staging / CANDIDATE_MANIFEST_FILENAME, candidate_payload)
> +        _write_fsync(staging / CANDIDATE_RECEIPT_FILENAME, receipt_payload)
> @@
> -        staging = Path()
> +        staging = None
> @@
> -        if staging and staging.exists():
> +        if staging is not None and staging.exists():
>              shutil.rmtree(staging)
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> Поймал и сразу остановил дефект в cleanup нового атомарного writer: после успешного rename sentinel ошибочно превращался в `.`. WSL успел начать обход рабочего каталога и остановился на read-only runtime; сейчас провожу полный аудит `git status` и файлов, чтобы восстановить любое затронутое содержимое до продолжения. Staged recovery-снимок отдельно не трогаю.
>
> <details><summary>Ran 6 commands</summary>
>
> - Ran `git status --short --untracked-files=all`
> - Ran `Get-ChildItem -Force -LiteralPath 'E:\STUDY\VAST' | Select-Object Mode,Name,Length,LastWriteTime`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/find /home/s-a-balashov/work/VAST -maxdepth 1 -mindepth 1 -printf '%f\n'`
> - Ran `Get-ChildItem -Force -LiteralPath 'E:\STUDY' | Select-Object Mode,Name,Length,LastWriteTime; Get-ChildItem -Force -LiteralPath 'E:\STUDY\VAST-root-venv-quarantine-20260824' -ErrorAction SilentlyContinue | Select-Object -First 5 Mode,Name`
> - Ran `Get-ChildItem -Force -LiteralPath 'E:\STUDY\rospatent_vast_2026' | Select-Object Mode,Name,Length,LastWriteTime; Get-ChildItem -Path 'E:\STUDY' -Directory -Force -Recurse -Filter '.git' -ErrorAction SilentlyContinue | Select-Object -First 20 FullName`
> - Ran `rg -n -i "git (status|branch|rev-parse|remote|commit)|github\.com|gitlab|origin/|HEAD|commit [0-9a-f]{7,40}|\.git/config|staged" progress.md INSTRUCTIONS.md README.md | Select-Object -First 300`
>
> </details>
>
> <details><summary>Ran 27 commands</summary>
>
> - Ran `git config --global --list --show-origin; git config --system --list --show-origin 2>$null`
> - Ran `$files=@((Get-PSReadLineOption -ErrorAction SilentlyContinue).HistorySavePath,'C:\Users\s-a-balashov\.bash_history'); foreach($file in $files){ if($file -and (Test-Path -LiteralPath $file)){ "SOURCE=$file"; Select-String -LiteralPath $file -Pattern 'git clone|iorep|STUDY.VAST|work/VAST' -CaseSensitive:$false | ForEach-Object { $_.Line -replace '(https?://)[^/@\s]+@','$1<redacted>@' -replace '(token|password|passwd)=\S+','$1=<redacted>' } | Select-Object -Last 100 } }; wsl.exe -d Ubuntu -- /bin/bash -lc "if [ -f /home/s-a-balashov/.bash_history ]; then grep -Ei 'git clone|iorep|STUDY.?VAST|work/VAST' /home/s-a-balashov/.bash_history | tail -100 | sed -E 's#(https?://)[^/@[:space:]]+@#\1<redacted>@#g'; fi"`
> - Ran `git ls-remote --symref https://github.com/lordcoudy/VAST.git HEAD refs/heads/*`
> - Ran `wsl.exe -d Ubuntu -- /bin/bash -lc 'set -euo pipefail; recovery_dir=$(mktemp -d /tmp/vast-git-recovery-20260824.XXXXXX); git clone --no-checkout https://github.com/lordcoudy/VAST.git "$recovery_dir/repo" >/dev/null; printf "%s\n" "$recovery_dir/repo"'`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/test ! -e /tmp/vast-git-recovery-20260824-root`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/mkdir /tmp/vast-git-recovery-20260824-root`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/git clone --no-checkout https://github.com/lordcoudy/VAST.git /tmp/vast-git-recovery-20260824-root/repo`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/find /tmp/vast-git-recovery-20260824-root/repo/.git -maxdepth 1 -mindepth 1 -printf '%f %s\n'`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/git -C /tmp/vast-git-recovery-20260824-root/repo checkout --force master`
> - Ran `$target='E:\STUDY\VAST-git-recovery-20260824-root'; if(Test-Path -LiteralPath $target){ throw "Recovery target already exists" }; git clone https://github.com/lordcoudy/VAST.git $target`
> - Ran `$source='E:\STUDY\VAST-git-recovery-20260824-root\.git'; $target='E:\STUDY\VAST\.git'; if(!(Test-Path -LiteralPath $source -PathType Container)){ throw 'Recovery .git missing' }; if(Test-Path -LiteralPath $target){ throw 'Target .git unexpectedly exists' }; $root=(Resolve-Path -LiteralPath 'E:\STUDY\VAST').Path; if($root -ne 'E:\STUDY\VAST'){ throw "Unexpected workspace root: $root" }; Copy-Item -LiteralPath $source -Destination $target -Recurse`
> - Ran `git rev-parse --show-toplevel; git rev-parse HEAD; git status --short --untracked-files=all`
> - Ran `Get-Content -LiteralPath 'E:\STUDY\VAST-git-recovery-20260824-root\.gitattributes'; '---GITIGNORE---'; Get-Content -LiteralPath 'E:\STUDY\VAST-git-recovery-20260824-root\.gitignore'`
> - Ran `$patch = @'
> *** Begin Patch
> *** Add File: .gitattributes
> +*.sh text eol=lf
> +# These files are bound to preregistered SHA-256 identities. Their working-tree
> +# bytes must be stable even when core.autocrlf is enabled on Windows.
> +policies/ql_heft_frozen.policy text eol=lf
> +policies/aw_heft_reference_v1.json text eol=lf
> +scripts/formal_aw_heft_reference.py text eol=lf
> +scripts/resource_interval_contract.py text eol=lf
> +deploy/native_gst_probe/checkpoint_resource_interval_emitter.hpp text eol=lf
> +deploy/native_gst_probe/vast_native_gst_probe.cpp text eol=lf
> *** Add File: .gitignore
> +# Python artifacts
> +__pycache__/
> +*.py[cod]
> +*.egg-info/
> +.venv/
> +.pytest_cache/
> +.env
> +.env.*
> +!.env.example
> +*.credentials.json
> +seafile.txt
> +
> +# Experiment outputs
> +runs/
> +reports/
> +plots/
> +build/
> +staging/
> +
> +# OS/editor
> +.DS_Store
> +.vscode/
> +
> +data/
> +models/
> +tmp_*
> +
> +# Local laboratory inventory
> +configs/hosts.yaml
> +
> +.cache/
> +.agents/
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `git diff --exit-code -- .gitattributes .gitignore; if($LASTEXITCODE -eq 0){ 'ROOT_DOTFILES_EXACT_HEAD' }`
> - Ran `$tmpFiles=@(git ls-files --others --exclude-standard -- tmp); $mpl=@(git ls-files --others --exclude-standard -- .test-tmp/mpl/fontlist-v3.11.0.json); "TMP_UNTRACKED_COUNT=$($tmpFiles.Count)"; "MPL_COUNT=$($mpl.Count)"; $tmpFiles`
> - Ran `rg -n -i "staged|recovery snapshot|fontlist|tmp/|97 (file|staged|addition)|git index" progress.md | Select-Object -Last 200`
> - Ran `rg -c "fontlist-v3\\.11\\.0\\.json|git status --short|staged recovery" "C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T17-14-30-01a0341f-6fb8-72f0-a9b1-0de3819296cb.jsonl"`
> - Ran `rg -c "fontlist-v3\\.11\\.0\\.json|git status --short|staged recovery" "C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T19-37-56-01a034a2-bebf-71c1-8d8c-ffa43aaefd52.jsonl"`
> - Ran `rg -l --hidden --glob '!skills/**' --glob '!plugins/**' "fontlist-v3\.11\.0\.json|assemble_exact_29ad_hybrid\.py" 'C:\Users\s-a-balashov\.codex' | Select-Object -First 50`
> - Ran `$f='C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T19-37-56-01a034a2-bebf-71c1-8d8c-ffa43aaefd52.jsonl'; Get-Content -LiteralPath $f -TotalCount 8 | ForEach-Object { $o=$_ | ConvertFrom-Json -Depth 20; [pscustomobject]@{type=$o.type; top=(($o.PSObject.Properties.Name) -join ','); payload_type=$o.payload.type; payload_keys=(($o.payload.PSObject.Properties.Name) -join ',')} }`
> - Ran `$files=@('C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T19-37-56-01a034a2-bebf-71c1-8d8c-ffa43aaefd52.jsonl','C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T17-14-30-01a0341f-6fb8-72f0-a9b1-0de3819296cb.jsonl'); foreach($f in $files){ "FILE=$f"; $n=0; Get-Content -LiteralPath $f | ForEach-Object { $n++; $idx=$_.IndexOf('fontlist-v3.11.0.json'); if($idx -ge 0){ $start=[Math]::Max(0,$idx-300); $length=[Math]::Min(1400,$_.Length-$start); "LINE=$n"; $_.Substring($start,$length) -replace '(?i)(token|password|passwd|secret)[^,\\"]*','$1=<redacted>' -replace '(https?://)[^/@\\\s]+@','$1<redacted>@' } } }`
> - Ran `$files=@('C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T19-37-56-01a034a2-bebf-71c1-8d8c-ffa43aaefd52.jsonl','C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T17-14-30-01a0341f-6fb8-72f0-a9b1-0de3819296cb.jsonl'); foreach($f in $files){ "FILE=$f"; $matches=@(rg -o 'A  (tmp/[^\\]+|\.test-tmp/[^\\]+)' $f | Sort-Object -Unique); "COUNT=$($matches.Count)"; $matches }`
> - Ran `$f='C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T19-37-56-01a034a2-bebf-71c1-8d8c-ffa43aaefd52.jsonl'; $n=0; Get-Content -LiteralPath $f | ForEach-Object { $n++; $needle='assemble_exact_29ad_hybrid.py'; $idx=$_.IndexOf($needle); if($idx -ge 0){ $start=[Math]::Max(0,$idx-250); $length=[Math]::Min(900,$_.Length-$start); "LINE=$n"; $_.Substring($start,$length) } } | Select-Object -First 20`
> - Ran `rg -l --hidden "A  tmp/assemble_exact_29ad_hybrid\.py" 'C:\Users\s-a-balashov\.codex\sessions' | Select-Object -First 50`
> - Ran `$f='C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T15-47-22-01a033cf-a7bd-7812-9f8f-a337dfae69c8.jsonl'; $matches=@(rg -o 'A  (tmp/[^\\]+|\.test-tmp/[^\\]+)' $f | Sort-Object -Unique); "COUNT=$($matches.Count)"; $matches`
> - Ran `$f='C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T15-47-22-01a033cf-a7bd-7812-9f8f-a337dfae69c8.jsonl'; $expected=@(rg -o 'A  (tmp/[^\\]+|\.test-tmp/[^\\]+)' $f | ForEach-Object { $_ -replace '^A  ','' } | Sort-Object -Unique); $actual=@(git ls-files --others --exclude-standard -- tmp .test-tmp/mpl/fontlist-v3.11.0.json | Sort-Object -Unique); "EXPECTED=$($expected.Count) ACTUAL=$($actual.Count)"; $delta=@(Compare-Object -ReferenceObject $expected -DifferenceObject $actual); "DELTA=$($delta.Count)"; $delta`
>
> </details>
>
> Git-метаданные восстановлены из исходного `origin/master` (`223f8f3…`), удалённые `.gitattributes`/`.gitignore` восстановлены без diff. Из локального журнала задачи извлечён прежний staged-набор: ровно 97 путей; текущие файлы совпали по списку 97/97, сейчас Git пересчитывает их крупные blob-объекты для восстановления индекса.
>
> <details><summary>Ran 21 commands</summary>
>
> - Ran `git add -- tmp .test-tmp/mpl/fontlist-v3.11.0.json`
> - Ran `Get-Process git -ErrorAction SilentlyContinue | Select-Object Id,CPU,WorkingSet64,StartTime,Path; Get-PSDrive -Name E | Select-Object Used,Free`
> - Ran `Get-Process | Where-Object { $_.ProcessName -match 'git|pwsh|bash|wsl' } | Sort-Object StartTime | Select-Object ProcessName,Id,CPU,WorkingSet64,StartTime,Path`
> - Ran `Get-CimInstance Win32_Process | Where-Object { $_.ParentProcessId -eq 92872 -or $_.ProcessId -eq 92872 } | Select-Object ProcessId,ParentProcessId,Name,CommandLine`
> - Ran `rg -n -i "git (ls-files -s|diff --cached|diff --staged)|cached.*tmp/|index.*sha|staged.*sha" 'C:\Users\s-a-balashov\.codex\sessions\2026\08\24' | Select-Object -First 100`
> - Ran `rg -l --hidden 'git ls-files -s|git diff --cached --raw|git diff --cached --name-status' 'C:\Users\s-a-balashov\.codex\sessions\2026\08\24' | Select-Object -First 50`
> - Ran `$f='C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T12-50-28-01a0332d-b613-7dc1-8bf4-fea5cdb46fbd.jsonl'; $matches=@(rg -o '100[0-9]{3} [0-9a-f]{40} 0\\t(tmp/[^\\]+|\.test-tmp/[^\\]+)' $f | Sort-Object -Unique); "COUNT=$($matches.Count)"; $matches | Select-Object -First 120`
> - Ran `$f='C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T12-50-28-01a0332d-b613-7dc1-8bf4-fea5cdb46fbd.jsonl'; $n=0; Get-Content -LiteralPath $f | ForEach-Object { $n++; $needle='git ls-files -s'; $idx=$_.IndexOf($needle); if($idx -ge 0){ $start=[Math]::Max(0,$idx-100); $length=[Math]::Min(1800,$_.Length-$start); "LINE=$n"; $_.Substring($start,$length) } } | Select-Object -First 10`
> - Ran `$f='C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T15-47-22-01a033cf-a7bd-7812-9f8f-a337dfae69c8.jsonl'; $expected=@(rg -o 'A  (tmp/[^\\]+|\.test-tmp/[^\\]+)' $f | ForEach-Object { $_ -replace '^A  ','' } | Sort-Object -Unique); $staged=@(git diff --cached --name-only --diff-filter=A | Sort-Object -Unique); "EXPECTED=$($expected.Count) STAGED=$($staged.Count)"; $delta=@(Compare-Object -ReferenceObject $expected -DifferenceObject $staged); "DELTA=$($delta.Count)"; $delta; $dot=@(git status --short -- .gitattributes .gitignore); "DOTFILE_STATUS_COUNT=$($dot.Count)"; $dot`
> - Ran `git diff --raw -- .gitattributes .gitignore; git diff --numstat -- .gitattributes .gitignore; git status --porcelain=v2 -- .gitattributes .gitignore; git hash-object .gitattributes .gitignore; git rev-parse HEAD:.gitattributes HEAD:.gitignore`
> - Ran `git update-index --refresh -- .gitattributes .gitignore; git status --short -- .gitattributes .gitignore`
> - Ran `git add --refresh -- .gitattributes .gitignore; git status --short -- .gitattributes .gitignore; git diff --exit-code -- .gitattributes .gitignore`
> - Ran `$staged=@(git diff --cached --name-only --diff-filter=A); $other=@(git diff --cached --name-only --diff-filter=ACDMRTUXB | Where-Object { $_ -notin $staged }); "STAGED_ADDITIONS=$($staged.Count) OTHER_STAGED=$($other.Count)"; git status --short -- .gitattributes .gitignore`
> - Ran `$trackedDeleted=@(git diff --name-only --diff-filter=D); $stagedDeleted=@(git diff --cached --name-only --diff-filter=D); "TRACKED_DELETED=$($trackedDeleted.Count) STAGED_DELETED=$($stagedDeleted.Count)"; $trackedDeleted; $stagedDeleted`
> - Ran `rg -l --hidden '\*\*\* Update File: \.gitignore|apply_patch.*\.gitignore|\.publication-runtime/' 'C:\Users\s-a-balashov\.codex\sessions\2026\08\24' | Select-Object -First 100`
> - Ran `$files=@('C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T12-50-28-01a0332d-b613-7dc1-8bf4-fea5cdb46fbd.jsonl','C:\Users\s-a-balashov\.codex\sessions\2026\08\24\rollout-2026-08-24T14-05-27-01a03372-599b-73d1-bd69-59e7a8c11186.jsonl'); foreach($f in $files){ "FILE=$f"; $n=0; Get-Content -LiteralPath $f | ForEach-Object { $n++; $needles=@('*** Update File: .gitignore','*** Update File: E:\\STUDY\\VAST\\.gitignore'); foreach($needle in $needles){ $idx=$_.IndexOf($needle); if($idx -ge 0){ $end=$_.IndexOf('*** End Patch',$idx); if($end -lt 0){$end=[Math]::Min($_.Length,$idx+5000)} else {$end+=[string]'*** End Patch'.Length}; "LINE=$n"; $_.Substring($idx,[Math]::Min($end-$idx,6000)) } } } }`
> - Ran `$patches=New-Object System.Collections.Generic.HashSet[string]; Get-ChildItem -LiteralPath 'C:\Users\s-a-balashov\.codex\sessions\2026\08\24' -Filter '*.jsonl' | ForEach-Object { Get-Content -LiteralPath $_.FullName | ForEach-Object { $line=$_; $cursor=0; while($true){ $idx=$line.IndexOf('*** Update File:',$cursor); if($idx -lt 0){break}; $end=$line.IndexOf('*** End Patch',$idx); if($end -lt 0){break}; $segment=$line.Substring($idx,$end+$([string]'*** End Patch').Length-$idx); if($segment -match '(?i)\.gitignore'){ [void]$patches.Add($segment) }; $cursor=$end+10 } } }; $patches | Sort-Object`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: .gitignore
> @@
>  .venv/
> +.publication-runtime/
> +.publication-sockets/
>  .pytest_cache/
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `git diff -- .gitignore; git status --short -- .gitattributes .gitignore; $staged=@(git diff --cached --name-only --diff-filter=A); "STAGED_ADDITIONS=$($staged.Count)"`
> - Ran `rg -l --hidden 'd---- +\.agents|d----- +\.agents|\.agents +[0-9]{1,2}/08/2026|d---- +\.codex|d----- +\.codex' 'C:\Users\s-a-balashov\.codex\sessions\2026\08\24' | Select-Object -First 50`
> - Ran `rg -o -i 'E:\\STUDY\\VAST\\\.(agents|codex|git(attributes|ignore)?)([^" ]*)?' 'C:\Users\s-a-balashov\.codex\.sandbox\sandbox.2026-08-24.log' | Sort-Object -Unique | Select-Object -First 100`
>
> </details>
>
> Восстановление завершено глубже, чем только HEAD: нашёл в журнале и вернул точный прежний `.gitignore` diff (`.publication-runtime/`, `.publication-sockets/`), staged index снова содержит ровно те же 97 путей, tracked-удалений — 0. Перед возобновлением агентов проверяю целостность всей восстановленной object database и добавляю отдельный regression на безопасный cleanup.
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `git fsck --full --no-reflogs`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: scripts/publication_policy_qualification_index_v2.py
> @@
>  def _write_fsync(path: Path, payload: bytes) -> None:
> @@
>          os.fsync(output.fileno())
>  
>  
> +def _cleanup_staging_directory(staging: Path, *, parent: Path) -> None:
> +    """Remove only the private sibling directory allocated by this module."""
> +    try:
> +        resolved_parent = parent.resolve(strict=True)
> +        resolved_staging = staging.resolve(strict=True)
> +    except OSError as exc:
> +        raise PolicyQualificationIndexV2Error(
> +            "qualification staging cleanup target cannot be resolved"
> +        ) from exc
> +    if (
> +        resolved_staging.parent != resolved_parent
> +        or not resolved_staging.name.startswith(".qualification-index-v2.")
> +        or resolved_staging == Path.cwd().resolve()
> +        or _is_link(resolved_staging)
> +        or not resolved_staging.is_dir()
> +    ):
> +        raise PolicyQualificationIndexV2Error(
> +            "refusing unsafe qualification staging cleanup target"
> +        )
> +    shutil.rmtree(resolved_staging)
> +
> +
>  def _commit_output(
> @@
>      finally:
>          if staging is not None and staging.exists():
> -            shutil.rmtree(staging)
> +            _cleanup_staging_directory(staging, parent=parent)
> *** Update File: tests/test_publication_policy_qualification_index_v2.py
> @@
>      def test_missing_pilot_evidence_and_fragment_drift_fail_before_commit(self) -> None:
> @@
>              self.assertFalse((root / "second" / "drift-output").exists())
> +
> +    def test_atomic_commit_failure_cleans_only_private_staging_directory(self) -> None:
> +        with tempfile.TemporaryDirectory() as tmp:
> +            root = Path(tmp)
> +            fragments, pilots = self._fixture(root)
> +            sentinel = root / "must-survive.txt"
> +            sentinel.write_text("workspace sentinel\n", encoding="utf-8")
> +            output = root / "qualification-v2"
> +
> +            with mock.patch.object(target.os, "replace", side_effect=OSError("injected")):
> +                with self.assertRaisesRegex(
> +                    target.PolicyQualificationIndexV2Error,
> +                    "atomic qualification candidate commit failed",
> +                ):
> +                    target.build_policy_qualification_index_v2(
> +                        project_root=root,
> +                        fragment_paths=fragments,
> +                        pilot_root=pilots,
> +                        output_dir=output,
> +                        policy=_PolicyApi,
> +                        fragment_validator=_fake_fragment_validator,
> +                    )
> +
> +            self.assertEqual(
> +                sentinel.read_text(encoding="utf-8"), "workspace sentinel\n"
> +            )
> +            self.assertFalse(output.exists())
> +            self.assertEqual(list(root.glob(".qualification-index-v2.*")), [])
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST -- /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_publication_policy_qualification_index_v2 -v`
>
> </details>
>
> Аудит восстановления закрыт: `git fsck --full` чист, tracked-удалений 0, defensive cleanup-тест воспроизводит отказ `os.replace` и подтверждает сохранность workspace. Агенты возобновлены; центральный qualification v2 теперь проверяю вместе с прежним qualifier, а не изолированно.
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST -- /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_publication_policy_qualification tests.test_publication_policy_qualification_index_v2 -v`
> - Ran `rg -n "qualification|forced.resource|cpu_only|gpu_only|pilot|candidate_manifest|calibration|checkpoint_policy_capability" scripts deploy configs tests --glob '!**/__pycache__/**' --glob '!tests/fixtures/**' | Select-Object -First 600`
> - Ran `rg --files scripts deploy | rg 'qualification|pilot|publication.*runtime_v3|native_policy'; '--- PILOT SCRIPTS ---'; Get-Content -LiteralPath 'scripts/run_deepstream_kpp_sdk_pilot_v3.sh' -ErrorAction SilentlyContinue; '--- NATIVE POLICY SIGNATURES ---'; rg -n '^class |^def |select_static|cpu_only|gpu_only|calibration' scripts/checkpoint_native_policy_runtime.py`
> - Ran `$files=@('scripts/checkpoint_native_policy_runtime.py','scripts/checkpoint_deepstream_publication_runtime_v3.py','scripts/checkpoint_savant_publication_runtime_v3.py','scripts/checkpoint_openvino_gva_publication_runtime_v3.py','scripts/checkpoint_gstreamer_publication_runtime_v3.py'); foreach($p in $files){ "=== $p ==="; rg -n '^class |^def |PUBLICATION_READY|BLOCKERS|pilot|execute|launch|materialize|run_' $p | Select-Object -First 220 }`
>
> </details>
>
> <details><summary>Ran 7 commands</summary>
>
> - Ran `$files=@('deploy/deepstream/checkpoint/vast_deepstream_publication_runtime_v3','deploy/savant/publication/vast_savant_publication_runtime_v3','deploy/openvino_gva/publication/vast_openvino_gva_publication_runtime_v3','deploy/gstreamer_custom/publication/vast_gstreamer_custom_publication_runtime_v3'); foreach($p in $files){ "=== $p ==="; rg -n "ArgumentParser|add_argument|execute-publication|output-dir|policy-capability|calibration|candidate|qualification|resource" $p | Select-Object -First 240 }`
> - Ran `Get-ChildItem -Force -Recurse -Depth 2 deploy\deepstream\publication,deploy\savant\publication,deploy\openvino_gva\publication,deploy\gstreamer_custom\publication -ErrorAction SilentlyContinue | Select-Object FullName,Length,Mode | Format-Table -AutoSize`
> - Ran `$files=@('deploy/deepstream/checkpoint/vast_deepstream_publication_runtime_v3','deploy/savant/publication/vast_savant_checkpoint_runtime','deploy/savant/publication/savant_publication_runtime_v3.py','deploy/openvino_gva/publication/vast_openvino_gva_publication_runtime_v3','deploy/gstreamer_custom/publication/vast_gstreamer_custom_publication_runtime_v3'); foreach($p in $files){ "=== $p ==="; Get-Content -LiteralPath $p -ErrorAction SilentlyContinue | Select-Object -First 260 }`
> - Ran `rg --files | rg 'container_(runtime|coordinator)_v3\.py$|publication_runtime_v3\.py$'`
> - Ran `$files=@('scripts/checkpoint_deepstream_container_runtime_v3.py','scripts/checkpoint_savant_container_runtime_v3.py','scripts/checkpoint_openvino_gva_container_coordinator_v3.py','scripts/checkpoint_gstreamer_custom_container_coordinator_v3.py'); foreach($p in $files){ "=== $p ==="; rg -n "ArgumentParser|add_argument|def main|execute-publication|policy-capability|calibration|policy|resource|output-dir|qualification" $p | Select-Object -First 320 }`
> - Ran `Get-Content -LiteralPath scripts/checkpoint_openvino_gva_container_coordinator_v3.py; Get-Content -LiteralPath scripts/checkpoint_gstreamer_custom_container_coordinator_v3.py; $p='scripts/checkpoint_deepstream_container_runtime_v3.py'; $lines=Get-Content -LiteralPath $p; $lines[640..825]; $lines[1038..1095]`
> - Ran `$p='scripts/publication_policy_qualification.py'; $lines=Get-Content -LiteralPath $p; $lines[563..766]`
>
> </details>
>
> <details><summary>Ran a command</summary>
>
> - Ran `$p='scripts/checkpoint_native_policy_runtime.py'; $lines=Get-Content -LiteralPath $p; $lines[330..445]; '--- policy contract selector ---'; rg -n '^def select_static_hybrid_map|def assess_calibration|calibration' scripts/publication_policy_contract.py | Select-Object -First 160`
>
> </details>
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `Get-ChildItem -Force -Recurse -Depth 4 -LiteralPath 'artifacts\analytics_model_parity' -ErrorAction SilentlyContinue | Select-Object FullName,Length,LastWriteTime | Format-Table -AutoSize; rg -n 'cpu_policy_calibration|cuda_policy_calibration|accepted|receipt|workload_slots' artifacts configs --glob '*.json' --glob '*.yaml' | Select-Object -First 300`
> - Ran `$files=@('evidence/model_parity/v3/documents/plate_number/cpu_policy_calibration.json','evidence/model_parity/v3/documents/plate_number/cuda_policy_calibration.json','configs/checkpoint_analytics_model_parity.accepted.yaml','configs/checkpoint_analytics_model_parity.accepted.assessment.json'); foreach($p in $files){ "=== $p ==="; if($p -like '*.yaml'){ $lines=Get-Content -LiteralPath $p; $lines[340..390] } else { Get-Content -LiteralPath $p } }`
>
> </details>
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `Get-ChildItem -Force -LiteralPath 'evidence\model_parity\v3' -ErrorAction SilentlyContinue | Select-Object Mode,Name,Length,LastWriteTime; Get-ChildItem -Force -LiteralPath 'evidence\model_parity\v3\documents' -ErrorAction SilentlyContinue | Select-Object Mode,Name,Length,LastWriteTime; wsl.exe -d Ubuntu -- /usr/bin/find /mnt/e/STUDY/VAST/evidence/model_parity/v3 -maxdepth 3 -type f -printf '%p %s\n'`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/sed -n 1,220p /mnt/e/STUDY/VAST/evidence/model_parity/v3/documents/plate_number/cpu_policy_calibration.json; wsl.exe -d Ubuntu -- /usr/bin/sed -n 1,220p /mnt/e/STUDY/VAST/evidence/model_parity/v3/documents/plate_number/cuda_policy_calibration.json`
> - Ran `wsl.exe -d Ubuntu -- /usr/bin/sed -n 1,240p /mnt/e/STUDY/VAST/evidence/model_parity/v3/execution_bundles/mp.v3.plate_number.cuda.calibration.h264.97/response.json; wsl.exe -d Ubuntu -- /usr/bin/sed -n 1,200p /mnt/e/STUDY/VAST/evidence/model_parity/v3/execution_bundles/mp.v3.plate_number.cpu.calibration.h264.97/response.json`
>
> </details>
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `$files=@('tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py','tests/test_checkpoint_openvino_gva_publication_runtime_v3.py','tests/test_checkpoint_deepstream_publication_runtime_v3.py','tests/test_checkpoint_savant_publication_runtime_v3.py'); foreach($p in $files){ "=== $p ==="; rg -n 'def _request|NativePublicationRequestV3|request =|launcher_input|socket|policy_capability|policy_calibration|runtime_image|image' $p | Select-Object -First 260 }`
> - Ran `$files=@('tests/test_checkpoint_deepstream_publication_runtime_v3.py','tests/test_checkpoint_gstreamer_custom_publication_runtime_v3.py','tests/test_checkpoint_openvino_gva_publication_runtime_v3.py'); foreach($p in $files){ "=== $p ==="; $lines=Get-Content -LiteralPath $p; if($p -like '*deepstream*'){ $lines[30..221] } elseif($p -like '*gstreamer*'){ $lines[28..267] } else { $lines[90..380] } }`
> - Ran `$files=@('scripts/checkpoint_deepstream_publication_launcher_v3.py','scripts/checkpoint_savant_publication_launcher_v3.py','scripts/checkpoint_openvino_gva_publication_launcher_v3.py','scripts/checkpoint_gstreamer_custom_publication_launcher_v3.py'); foreach($p in $files){ "=== $p ==="; rg -n '^def |^class |PUBLICATION_READY|runtime_inputs|publication_runtime_v3|NativePublicationRequestV3|qualification|build_' $p | Select-Object -First 320 }`
> - Ran `$p='scripts/checkpoint_publication_launcher_adapter_v3.py'; Get-Item -LiteralPath $p -ErrorAction SilentlyContinue; if(Test-Path -LiteralPath $p){ rg -n '^def |^class |NativePublicationRequestV3|runtime_inputs|dataset|launcher' $p | Select-Object -First 320; Get-Content -LiteralPath $p | Select-Object -First 260 } else { rg --files scripts | rg 'launcher_adapter_v3' }`
>
> </details>
>
> Context compaction
>
> Source: automatic
> Status: completed
>
> Продолжаю с текущего состояния: сейчас закрываю разрыв между принятой parity-транзакцией и калибровкой для 32 qualification-ячеек. Отдельно проверю, есть ли физические per-sample CUDA-интервалы в индексе; если их нет, bootstrap останется fail-closed, а parity evidence будет честно перематериализован, без синтетических медиан.
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && jq '{keys:(keys), output_segments_count:(.output_segments|length), execution_bundles_count:(.execution_bundles|length // null)}' evidence/model_parity/v3/transaction_index.json && find evidence/model_parity/v3 -maxdepth 4 -type f -printf '%P\n' | sort | sed -n '1,220p'"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && jq '{segment_keys:(.output_segments[0]|keys), first_segment:.output_segments[0], last_segment:.output_segments[-1]}' evidence/model_parity/v3/transaction_index.json && jq '{keys:(keys), resource:.resource, measurement_count:(.measurements|length // .samples|length // null), sample_keys:((.measurements // .samples // [])[0]|keys)}' evidence/model_parity/v3/execution_bundles/mp.v3.damage.cuda.calibration.h264.16097/response.json && jq '{keys:(keys), samples_count:(.samples|length), sample_keys:(.samples[0]|keys), first_sample:.samples[0]}' evidence/model_parity/v3/documents/damage/cuda_policy_calibration.json"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && jq 'keys' evidence/model_parity/v3/execution_bundles/mp.v3.damage.cuda.calibration.h264.16097/response.json && jq '{worker_protocol_version, resource, execution, timings, cuda_transfer_intervals, cuda_transfer_totals, keys:(keys)}' evidence/model_parity/v3/execution_bundles/mp.v3.damage.cuda.calibration.h264.16097/response.json && jq '{keys:(keys), samples_count:(.samples|length), measurements_count:(.measurements|length), sample0:(.samples[0] // .measurements[0])}' evidence/model_parity/v3/documents/damage/cuda_policy_calibration.json"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && jq '{frame:.frame,timing:.timing,terminal:.terminal,engine:.engine,provenance:.provenance}' evidence/model_parity/v3/execution_bundles/mp.v3.damage.cuda.calibration.h264.16097/response.json && jq '{sample_count,first:.samples[0],last:.samples[-1]}' evidence/model_parity/v3/documents/damage/cuda_policy_calibration.json && jq '[.output_segments[] | select(.branch==\"damage\" and .resource==\"tensorrt_cuda\") | {sample_id,offset_bytes,length_bytes}] | {count:length,first:.[0],last:.[-1]}' evidence/model_parity/v3/transaction_index.json"`
>
> </details>
>
> <details><summary>Ran 19 commands</summary>
>
> - Ran `rg -n --glob "*.py" "transaction_index|output_segments|cuda_transfer_intervals|policy_calibration" scripts tests | Select-Object -First 320`
> - Ran `$p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 2260 -First 390`
> - Ran `$p='tests/test_checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 430 -First 260; $p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 2000 -First 115`
> - Ran `rg -n "representative execution|persisted\)|execution_bundles|exact 8|480" scripts/checkpoint_model_parity_materializer.py tests/test_checkpoint_model_parity_materializer.py tests | Select-Object -First 220`
> - Ran `rg -n "checkpoint_model_parity_materialization_transaction|transaction_index_record|transaction_index.json|claimed_aggregates_accepted|files_sha256" scripts tests | Select-Object -First 320`
> - Ran `$p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 2635 -First 120; $p='scripts/checkpoint_model_parity_acceptance.py'; Get-Content -LiteralPath $p | Select-Object -Skip 620 -First 105`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && yq -o=json '.' configs/checkpoint_model_parity_accepted_v3.yaml 2>/dev/null | jq '{keys:(keys), identity:.identity, evidence_keys:(.workload_slots.plate_number.evidence|keys)}' || python3 -c \"import yaml,json; p=yaml.safe_load(open('configs/checkpoint_model_parity_accepted_v3.yaml')); print(json.dumps({'keys':list(p),'identity':p.get('identity'),'evidence_keys':list(p['workload_slots']['plate_number']['evidence'])},indent=2))\""`
> - Ran `Get-Content -LiteralPath 'configs/checkpoint_model_parity_accepted_v3.yaml' -TotalCount 120`
> - Ran `rg --files configs | rg "parity|model"`
> - Ran `Get-Content -LiteralPath 'configs/checkpoint_analytics_model_parity.accepted.yaml' -TotalCount 160`
> - Ran `Get-Content -LiteralPath 'configs/checkpoint_analytics_model_parity.accepted.yaml' -Tail 90`
> - Ran `python -B -c "import yaml,json; p=yaml.safe_load(open(r'configs/checkpoint_analytics_model_parity.accepted.yaml',encoding='utf-8')); print(json.dumps({'keys':list(p.keys()), 'identity':p.get('identity')}, indent=2))"`
> - Ran `rg -n "^[a-z][a-z0-9_]*:" configs/checkpoint_analytics_model_parity.accepted.yaml`
> - Ran `Get-Content -LiteralPath 'tests/test_checkpoint_model_parity_materializer.py' -TotalCount 470`
> - Ran `rg -n "def persist_execution_bundle|class ValidatedNativeResponse|def verify_execution_bundle|def native_service_time_ms" scripts/checkpoint_model_parity_materializer.py scripts/analytics_execution_worker.py; $p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1440 -First 260`
> - Ran `Get-Content -LiteralPath 'scripts/checkpoint_model_parity_materializer.py' -TotalCount 340; rg -n "persist_execution_bundle" scripts`
> - Ran `$p='scripts/analytics_execution_evidence.py'; Get-Content -LiteralPath $p | Select-Object -Skip 230 -First 250`
> - Ran `rg -n "model.parity|model_parity|materialize.*parity|checkpoint_model_parity_materializer" progress.md README.md docs scripts/*.sh scripts/*.ps1 tests | Select-Object -First 320`
> - Ran `rg -n "def materialize_and_promote|def main|argparse|accepted-assessment|acceptance-receipt|materialization-dir" scripts/checkpoint_model_parity_materializer.py; $p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 2730 -First 390`
>
> </details>
>
> Проверка подтвердила важный нюанс: 480 тензорных сегментов действительно физические, но CUDA transfer timing сохранён лишь для четырёх representative-запросов. Я не буду выдавать это за 30-sample калибровку. Текущий bootstrap теперь проектируется как fail-closed; параллельно готовлю отдельную, криптографически связанную per-sample materialization, чтобы закрыть этот пробел корректно.
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `rg -n "launcher_output_receipt_protocol_ready|validate_full_publication_readiness|publication_ready" scripts/publication_matrix.py tests/test_publication_matrix.py tests | Select-Object -First 260; $p='scripts/publication_matrix.py'; Get-Content -LiteralPath $p | Select-Object -Skip 900 -First 440`
> - Ran `Get-Content -LiteralPath 'scripts/publication_matrix.py' -TotalCount 390; Get-Content -LiteralPath 'tests/test_publication_matrix.py' -TotalCount 370`
> - Ran `rg -n "^def |^class |__all__|PROTOCOL|schema_version|publication_ready" scripts/backend_publication_output_transaction_production_v3.py tests/test_backend_publication_output_transaction_production_v3.py | Select-Object -First 360; Get-Content -LiteralPath 'scripts/backend_publication_output_transaction_production_v3.py' -TotalCount 240`
> - Ran `$p='scripts/backend_publication_output_transaction_production_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1580 -First 110; $p='tests/test_backend_publication_output_transaction_production_v3.py'; Get-Content -LiteralPath $p | Select-Object -Skip 840 -First 360`
> - Ran `rg -n "output.*receipt|production.*transaction|semantic.*validator|runtime_bind_mount|binding_sha256" scripts/backend_runtime_qualification_v3.py scripts/backend_runtime_grant.py scripts/full_publication_identity_artifacts.py configs | Select-Object -First 360`
>
> </details>
>
> <details><summary>Ran 4 commands</summary>
>
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_model_parity_materializer.py
> @@
>      def test_native_service_time_requires_protocol_validated_response(self) -> None:
>          with self.assertRaisesRegex(TypeError, "ValidatedNativeResponse"):
>              native_service_time_ms(
> @@
>                  }
>              )
> +
> +    def test_execution_bundle_ledger_persists_every_physical_sample(self) -> None:
> +        with tempfile.TemporaryDirectory() as temporary:
> +            root = Path(temporary).resolve()
> +            staging = root / ".candidate.staging"
> +            final = root / "candidate"
> +            staging.mkdir()
> +            expected = {
> +                ("damage", "calibration", "h264", "sample-00", "openvino_cpu"),
> +                ("damage", "calibration", "h264", "sample-00", "tensorrt_cuda"),
> +            }
> +            ledger = materializer._ExecutionBundleLedger(
> +                project_root=root,
> +                staging_root=staging,
> +                final_root=final,
> +                expected_coordinates=expected,
> +            )
> +
> +            def response(resource: str, request_id: str):
> +                return materializer.ValidatedNativeResponse(
> +                    materializer._VALIDATED_RESPONSE_TOKEN,
> +                    request={"request_id": request_id},
> +                    response={},
> +                    capability={},
> +                    output=b"output",
> +                )
> +
> +            def persisted(*_args, **kwargs):
> +                request_id = kwargs["request"]["request_id"]
> +                manifest = {
> +                    "request_id": request_id,
> +                    "files": {
> +                        "request": {"sha256": "1" * 64},
> +                        "response": {"sha256": "2" * 64},
> +                        "input_tensor": {"sha256": "3" * 64},
> +                        "output_tensor": {"sha256": "4" * 64},
> +                    },
> +                    "identity": {"sha256": "5" * 64},
> +                }
> +                bundle = staging / "execution_bundles" / request_id
> +                bundle.mkdir(parents=True)
> +                (bundle / "manifest.json").write_bytes(
> +                    materializer._canonical_json(manifest) + b"\n"
> +                )
> +                return manifest
> +
> +            with mock.patch.object(
> +                materializer, "persist_execution_bundle", side_effect=persisted
> +            ) as persist:
> +                with mock.patch.object(
> +                    materializer,
> +                    "verify_execution_bundle",
> +                    side_effect=lambda path, *, capability: materializer._load_canonical_json_payload(
> +                        (Path(path) / "manifest.json").read_bytes(), label="fixture"
> +                    ),
> +                ) as verify:
> +                    for resource, request_id in (
> +                        ("openvino_cpu", "request-cpu"),
> +                        ("tensorrt_cuda", "request-gpu"),
> +                    ):
> +                        ledger.persist(
> +                            branch="damage",
> +                            role="calibration",
> +                            codec="h264",
> +                            sample_id="sample-00",
> +                            resource=resource,
> +                            response=response(resource, request_id),
> +                            input_tensor=b"input",
> +                        )
> +                    rows = ledger.finalize()
> +
> +            self.assertEqual(persist.call_count, 2)
> +            self.assertEqual(verify.call_count, 2)
> +            self.assertEqual(len(rows), 2)
> +            self.assertEqual(
> +                {row["request_id"] for row in rows}, {"request-cpu", "request-gpu"}
> +            )
> +            self.assertEqual(
> +                {row["resource"] for row in rows}, {"openvino_cpu", "tensorrt_cuda"}
> +            )
> +            self.assertTrue(
> +                all(row["manifest"]["path"].startswith("candidate/execution_bundles/") for row in rows)
> +            )
> +
> +            with self.assertRaisesRegex(MaterializerError, "duplicate"):
> +                ledger.persist(
> +                    branch="damage",
> +                    role="calibration",
> +                    codec="h264",
> +                    sample_id="sample-00",
> +                    resource="openvino_cpu",
> +                    response=response("openvino_cpu", "request-cpu-repeat"),
> +                    input_tensor=b"input",
> +                )
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && python3 -m unittest tests.test_checkpoint_model_parity_materializer.ModelParityMaterializerTests.test_execution_bundle_ledger_persists_every_physical_sample'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_materializer.ModelParityMaterializerTests.test_execution_bundle_ledger_persists_every_physical_sample'`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\checkpoint_model_parity_materializer.py
> @@
>  class ValidatedNativeResponse:
> @@
>          self.capability = dict(capability or {})
>          self.output = bytes(output or b"")
> +
> +
> +class _ExecutionBundleLedger:
> +    """Persist and index one immutable native bundle per sample/resource cell."""
> +
> +    def __init__(
> +        self,
> +        *,
> +        project_root: Path,
> +        staging_root: Path,
> +        final_root: Path,
> +        expected_coordinates: Iterable[tuple[str, str, str, str, str]],
> +    ) -> None:
> +        self._project_root = Path(project_root)
> +        self._staging_root = Path(staging_root)
> +        self._final_root = Path(final_root)
> +        try:
> +            self._final_root.relative_to(self._project_root)
> +        except ValueError as error:
> +            raise MaterializerError(
> +                "execution bundle final root escaped project_root"
> +            ) from error
> +        expected = frozenset(expected_coordinates)
> +        _require(expected, "execution bundle expected coverage is empty")
> +        _require(
> +            all(
> +                type(value) is str and value
> +                for coordinate in expected
> +                for value in coordinate
> +            ),
> +            "execution bundle expected coordinate is invalid",
> +        )
> +        _require(
> +            all(coordinate[4] in RESOURCES for coordinate in expected),
> +            "execution bundle expected resource is invalid",
> +        )
> +        self._expected = expected
> +        self._observed: set[tuple[str, str, str, str, str]] = set()
> +        self._rows: list[dict[str, Any]] = []
> +        self._finalized = False
> +
> +    def persist(
> +        self,
> +        *,
> +        branch: str,
> +        role: str,
> +        codec: str,
> +        sample_id: str,
> +        resource: str,
> +        response: ValidatedNativeResponse,
> +        input_tensor: bytes,
> +    ) -> None:
> +        coordinate = (branch, role, codec, sample_id, resource)
> +        _require(
> +            coordinate in self._expected,
> +            "execution bundle coordinate is not in the frozen sample plan",
> +        )
> +        _require(
> +            coordinate not in self._observed,
> +            "duplicate execution bundle coordinate",
> +        )
> +        _require(not self._finalized, "execution bundle ledger is finalized")
> +        _require(
> +            type(response) is ValidatedNativeResponse,
> +            "execution bundle requires a protocol-validated response",
> +        )
> +        request_id = response.request.get("request_id")
> +        _require(
> +            type(request_id) is str
> +            and _STABLE_ID_RE.fullmatch(request_id) is not None
> +            and Path(request_id).name == request_id,
> +            "execution bundle request ID is invalid",
> +        )
> +        bundle_root = self._staging_root / "execution_bundles"
> +        try:
> +            manifest = persist_execution_bundle(
> +                bundle_root,
> +                request=response.request,
> +                response=response.response,
> +                input_tensor=input_tensor,
> +                output_tensor=response.output,
> +                capability=response.capability,
> +            )
> +            verified = verify_execution_bundle(
> +                bundle_root / request_id,
> +                capability=response.capability,
> +            )
> +        except (EvidenceError, ProtocolError) as error:
> +            raise MaterializerError(
> +                f"native execution evidence persistence failed: {error}"
> +            ) from error
> +        _require(verified == manifest, "execution bundle verification drifted")
> +        _require(
> +            manifest.get("request_id") == request_id,
> +            "execution bundle manifest request binding drifted",
> +        )
> +        files = manifest.get("files")
> +        identity = manifest.get("identity")
> +        _require(
> +            isinstance(files, Mapping)
> +            and set(files)
> +            == {"request", "response", "input_tensor", "output_tensor"}
> +            and isinstance(identity, Mapping)
> +            and _SHA256_RE.fullmatch(str(identity.get("sha256", ""))) is not None,
> +            "execution bundle manifest inventory is invalid",
> +        )
> +        for label in ("request", "response", "input_tensor", "output_tensor"):
> +            record = files[label]
> +            _require(
> +                isinstance(record, Mapping)
> +                and _SHA256_RE.fullmatch(str(record.get("sha256", ""))) is not None,
> +                f"execution bundle {label} identity is invalid",
> +            )
> +        manifest_payload = _canonical_json(manifest) + b"\n"
> +        manifest_path = bundle_root / request_id / "manifest.json"
> +        _require(
> +            manifest_path.read_bytes() == manifest_payload,
> +            "execution bundle manifest bytes drifted after verification",
> +        )
> +        final_manifest = self._final_root / "execution_bundles" / request_id / "manifest.json"
> +        self._rows.append(
> +            {
> +                "branch": branch,
> +                "role": role,
> +                "codec": codec,
> +                "sample_id": sample_id,
> +                "resource": resource,
> +                "request_id": request_id,
> +                "manifest": {
> +                    "path": final_manifest.relative_to(self._project_root).as_posix(),
> +                    "sha256": _sha256_bytes(manifest_payload),
> +                    "size_bytes": len(manifest_payload),
> +                },
> +                "manifest_identity_sha256": identity["sha256"],
> +                "request_sha256": files["request"]["sha256"],
> +                "response_sha256": files["response"]["sha256"],
> +                "input_tensor_sha256": files["input_tensor"]["sha256"],
> +                "output_tensor_sha256": files["output_tensor"]["sha256"],
> +            }
> +        )
> +        self._observed.add(coordinate)
> +
> +    def finalize(self) -> tuple[dict[str, Any], ...]:
> +        missing = self._expected - self._observed
> +        extra = self._observed - self._expected
> +        _require(
> +            not missing and not extra,
> +            "execution bundle physical coverage is incomplete",
> +        )
> +        _require(
> +            len({row["request_id"] for row in self._rows}) == len(self._rows),
> +            "execution bundle request ID coverage is not unique",
> +        )
> +        self._finalized = True
> +        return tuple(copy.deepcopy(self._rows))
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
>
> </details>
>
> <details><summary>Ran 5 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_materializer.ModelParityMaterializerTests.test_execution_bundle_ledger_persists_every_physical_sample'`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\checkpoint_model_parity_materializer.py
> @@
>  def _write_transaction_index(
> @@
>      run_id: str,
>      source_inventory: Mapping[str, PhysicalFileRecord],
>      output_segments: Sequence[Mapping[str, Any]],
> +    execution_bundles: Sequence[Mapping[str, Any]],
>  ) -> PhysicalFileRecord:
> @@
> -    index = {
> -        "schema_version": 1,
> +    _require(
> +        len(execution_bundles) == len(output_segments),
> +        "transaction execution/output coverage cardinality mismatch",
> +    )
> +    _require(
> +        len({str(row.get("request_id")) for row in execution_bundles})
> +        == len(execution_bundles),
> +        "transaction execution bundle request IDs are not unique",
> +    )
> +    index = {
> +        "schema_version": 2,
>          "artifact_kind": "checkpoint_model_parity_materialization_transaction",
>          "run_id": run_id,
>          "final_materialization_path": final_root.relative_to(root).as_posix(),
> @@
>          "output_segments_sha256": _sha256_bytes(
>              _canonical_json(list(output_segments))
>          ),
> +        "execution_bundle_count": len(execution_bundles),
> +        "execution_bundles": list(execution_bundles),
> +        "execution_bundles_sha256": _sha256_bytes(
> +            _canonical_json(list(execution_bundles))
> +        ),
>          "claimed_aggregates_accepted": False,
>          "synthetic_or_mock_evidence_accepted": False,
>      }
> +    index["transaction_sha256"] = _sha256_bytes(_canonical_json(index))
>      return _write_json_file(staging_root / "transaction_index.json", index)
> @@
> -        persisted: set[tuple[str, str]] = set()
> +        execution_ledger = _ExecutionBundleLedger(
> +            project_root=root,
> +            staging_root=staging_root,
> +            final_root=final_root,
> +            expected_coordinates={
> +                (row.branch, row.role, row.codec, row.sample_id, resource)
> +                for row in plan
> +                for resource in RESOURCES
> +            },
> +        )
>          with NativeEndpointRunner(
> @@
>                      output_values[(row.branch, resource)].append(
> @@
>                              "values": values,
>                          }
>                      )
> -                    coordinate = (row.branch, resource)
> -                    if coordinate not in persisted:
> -                        try:
> -                            persist_execution_bundle(
> -                                staging_root / "execution_bundles",
> -                                request=response.request,
> -                                response=response.response,
> -                                input_tensor=tensor,
> -                                output_tensor=response.output,
> -                                capability=response.capability,
> -                            )
> -                            verify_execution_bundle(
> -                                staging_root
> -                                / "execution_bundles"
> -                                / response.request["request_id"],
> -                                capability=response.capability,
> -                            )
> -                        except (EvidenceError, ProtocolError) as error:
> -                            raise MaterializerError(
> -                                f"native execution evidence persistence failed: {error}"
> -                            ) from error
> -                        persisted.add(coordinate)
> -        _require(len(persisted) == 8, "representative execution bundle coverage is not exact 8")
> +                    execution_ledger.persist(
> +                        branch=row.branch,
> +                        role=row.role,
> +                        codec=row.codec,
> +                        sample_id=row.sample_id,
> +                        resource=resource,
> +                        response=response,
> +                        input_tensor=tensor,
> +                    )
> +        execution_bundles = execution_ledger.finalize()
> @@
>              },
>              output_segments=output_segments,
> +            execution_bundles=execution_bundles,
>          )
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_model_parity_materializer.py
> @@
>      def test_execution_bundle_ledger_persists_every_physical_sample(self) -> None:
> @@
>                  ledger.persist(
> @@
>                      input_tensor=b"input",
>                  )
> +
> +    def test_transaction_index_v2_binds_all_execution_bundles_and_self_hash(self) -> None:
> +        with tempfile.TemporaryDirectory() as temporary:
> +            root = Path(temporary).resolve()
> +            staging = root / ".run.staging"
> +            final = root / "run"
> +            staging.mkdir()
> +            (staging / "physical.bin").write_bytes(b"physical\n")
> +            output_segments = [{"sample_id": "sample-00", "resource": "openvino_cpu"}]
> +            execution_bundles = [
> +                {
> +                    "request_id": "request-00",
> +                    "sample_id": "sample-00",
> +                    "resource": "openvino_cpu",
> +                }
> +            ]
> +
> +            record = materializer._write_transaction_index(
> +                root=root,
> +                staging_root=staging,
> +                final_root=final,
> +                run_id="run",
> +                source_inventory={},
> +                output_segments=output_segments,
> +                execution_bundles=execution_bundles,
> +            )
> +            index = materializer._load_canonical_json_payload(
> +                record.path.read_bytes(), label="transaction fixture"
> +            )
> +
> +            self.assertEqual(index["schema_version"], 2)
> +            self.assertEqual(index["execution_bundle_count"], 1)
> +            self.assertEqual(index["execution_bundles"], execution_bundles)
> +            self.assertEqual(
> +                index["execution_bundles_sha256"],
> +                sha(materializer._canonical_json(execution_bundles)),
> +            )
> +            identity = index.pop("transaction_sha256")
> +            self.assertEqual(identity, sha(materializer._canonical_json(index)))
> +
> +            with self.assertRaisesRegex(MaterializerError, "cardinality"):
> +                materializer._write_transaction_index(
> +                    root=root,
> +                    staging_root=staging,
> +                    final_root=final,
> +                    run_id="run",
> +                    source_inventory={},
> +                    output_segments=output_segments,
> +                    execution_bundles=[],
> +                )
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_materializer.ModelParityMaterializerTests.test_execution_bundle_ledger_persists_every_physical_sample tests.test_checkpoint_model_parity_materializer.ModelParityMaterializerTests.test_transaction_index_v2_binds_all_execution_bundles_and_self_hash'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_materializer'`
>
> </details>
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `rg -n "def build_parser|add_argument|transaction|execution_bundles|accepted-parity|def bootstrap|def main|__all__" scripts/publication_policy_qualification_bootstrap_v2.py tests/test_publication_policy_qualification_bootstrap_v2.py | Select-Object -First 320; Get-Content -LiteralPath 'scripts/publication_policy_qualification_bootstrap_v2.py' -TotalCount 240`
> - Ran `$p='scripts/publication_policy_qualification_bootstrap_v2.py'; Get-Content -LiteralPath $p | Select-Object -Skip 360 -First 330; Get-Content -LiteralPath $p | Select-Object -Skip 840 -First 240`
>
> </details>
>
> <details><summary>Ran 9 commands</summary>
>
> - Ran `rg -n "checkpoint_analytics_model_parity\.accepted\.yaml|a570b8cc4bcc6611" --glob "!tmp/**" --glob "!.test-tmp/**" --glob "!progress.md" . | Select-Object -First 420`
> - Ran `$p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 785 -First 160`
> - Ran `rg -n "accepted_relative|materialization_relative|accepted manifest target|materialization target" scripts/checkpoint_model_parity_materializer.py | Select-Object -First 80; $p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 700 -First 95`
> - Ran `$p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1010 -First 170`
> - Ran `rg -n "def _preflight_real_inputs" scripts/checkpoint_model_parity_materializer.py`
> - Ran `$p='scripts/checkpoint_model_parity_materializer.py'; Get-Content -LiteralPath $p | Select-Object -Skip 1795 -First 160`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && find artifacts -maxdepth 5 -type f \( -name '*runtime_probe*.json' -o -name '*binding*.json' -o -name 'binding_set*.json' \) -printf '%P\n' | sort | sed -n '1,260p'; find . -maxdepth 5 -type d -name '*binding*' -printf '%p\n' | sort | sed -n '1,180p'; jq '{decoder:.decoder, argv_count:(.argv_records|length), keys:(keys)}' evidence/model_parity/v3/support/decoder/invocation_contract.json"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && find artifacts/analytics_execution_bindings -maxdepth 3 -type f -printf '%P\n' | sort; jq '{executable_source_path, executable_sha256, version, argv_count:(.argv|length)}' evidence/model_parity/v3/support/decoder/invocation_contract.json; find .publication-sockets -maxdepth 2 -printf '%p %y\n' 2>/dev/null | sed -n '1,100p'"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "findmnt -T /mnt/e/STUDY/VAST/evidence/model_parity -o TARGET,SOURCE,FSTYPE,OPTIONS -n; findmnt -T /mnt/e/STUDY/VAST/evidence -o TARGET,SOURCE,FSTYPE,OPTIONS -n; df -hT /home/s-a-balashov/.local/state/vast/publication/evidence /mnt/e/STUDY/VAST | sed -n '1,5p'; find /home/s-a-balashov/.local/state/vast/publication/evidence -maxdepth 2 -mindepth 1 -printf '%p %y\n' | sort | sed -n '1,120p'"`
>
> </details>
>
> Физический план исправления теперь конкретный: новый parity run сохранит 480/480 native bundles (включая 120 CUDA calibration responses с H2D/D2H `cudaEvent`), а старый accepted v3 останется неизменным как историческая версия. Новая acceptance будет версионированной; только после полной повторной оценки я перепривяжу qualification fragments и full-run authority.
>
> <details><summary>Ran 3 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && for p in evidence/model_parity/v4_policy_calibration_physical_20260824 configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.yaml configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.assessment.json configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.acceptance_receipt.json .publication-sockets/model-parity-policy-calibration-v2; do if [ -e \"$p\" ] || [ -L \"$p\" ]; then printf 'EXISTS %s\n' \"$p\"; else printf 'ABSENT %s\n' \"$p\"; fi; done; docker image inspect vast/analytics-openvino-worker:publication-v3 vast/analytics-tensorrt-worker:publication-v3 --format '{{.Id}}'"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc "cd /mnt/e/STUDY/VAST && for p in evidence/model_parity/v4_policy_calibration_physical_20260824 configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.yaml configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.assessment.json configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.acceptance_receipt.json .publication-sockets/model-parity-policy-calibration-v2; do if [ -e \"\$p\" ] || [ -L \"\$p\" ]; then echo EXISTS:\$p; else echo ABSENT:\$p; fi; done && docker image inspect vast/analytics-openvino-worker:publication-v3 vast/analytics-tensorrt-worker:publication-v3 --format '{{.Id}}'"`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && for p in evidence/model_parity/v4_policy_calibration_physical_20260824 configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.yaml configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.assessment.json configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.acceptance_receipt.json .publication-sockets/model-parity-policy-calibration-v2; do if [ -e "$p" ] || [ -L "$p" ]; then echo EXISTS:$p; else echo ABSENT:$p; fi; done && docker image inspect vast/analytics-openvino-worker:publication-v3 vast/analytics-tensorrt-worker:publication-v3 --format "{{.Id}}"'`
>
> </details>
>
> Новая physical materialization запущена в WSL: 240 frozen KPP samples × 2 resources = 480 native executions. Выход идёт в новый ext4-каталог, старый accepted v3 не перезаписывается; память WSL остаётся ограниченной текущими 24 GB, boot-profile не менялся.
>
> <details><summary>Ran 2 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && find evidence/model_parity -maxdepth 2 -type d -name ".v4_policy_calibration_physical_20260824.staging.*" -printf "%p\n" && find evidence/model_parity -maxdepth 5 -path "*/execution_bundles/*/manifest.json" -type f | wc -l && docker ps --format "{{.Names}} {{.Status}}" | sed -n "1,20p"'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && install -d -m 700 .publication-sockets/model-parity-policy-calibration-v2 && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 scripts/checkpoint_model_parity_materializer.py --project-root /mnt/e/STUDY/VAST --datasets /mnt/e/STUDY/VAST/configs/datasets.yaml --base-manifest /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.yaml --materialization-dir /mnt/e/STUDY/VAST/evidence/model_parity/v4_policy_calibration_physical_20260824 --accepted-manifest /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.yaml --accepted-assessment /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.assessment.json --acceptance-receipt /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.acceptance_receipt.json --ffmpeg /usr/bin/ffmpeg --execution-config /mnt/e/STUDY/VAST/configs/analytics_execution_layer.yaml --binding-set /mnt/e/STUDY/VAST/artifacts/analytics_execution_bindings/publication_v3 --cpu-runtime-probe /mnt/e/STUDY/VAST/artifacts/analytics_runtime_probes/publication_v3/cpu_runtime_probe.json --gpu-runtime-probe /mnt/e/STUDY/VAST/artifacts/analytics_runtime_probes/publication_v3/gpu_runtime_probe.json --socket-dir /mnt/e/STUDY/VAST/.publication-sockets/model-parity-policy-calibration-v2'`
>
> </details>
>
> Первый запуск корректно остановился до inference: Unix-сокеты нельзя создавать на DrvFS (`E:` вернул `ENOTSUP`). Транзакция не была опубликована и staging очищен. Сейчас переношу только socket workspace на ext4; evidence уже находится на ext4, поэтому повтор будет без изменения контракта и без ослабления проверок.
>
> <details><summary>Ran 9 commands</summary>
>
> - Ran `rg -n "socket_dir|socket_root|analytics socket" scripts/checkpoint_model_parity_materializer.py | Select-Object -First 180; wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && if [ -e evidence/model_parity/.v4_policy_calibration_physical_20260824.staging.17488 ]; then echo STAGING_PRESENT; else echo STAGING_CLEAN; fi && if [ -e evidence/model_parity/v4_policy_calibration_physical_20260824 ]; then echo FINAL_PRESENT; else echo FINAL_ABSENT; fi && find .publication-sockets/model-parity-policy-calibration-v2 -mindepth 1 -maxdepth 1 -printf "%f\n" 2>/dev/null | sed -n "1,20p"'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'set -e; source_dir=/home/s-a-balashov/.local/state/vast/publication/sockets/model-parity-policy-calibration-v2; target_dir=/mnt/e/STUDY/VAST/.publication-sockets/model-parity-policy-calibration-v2; install -d -m 700 "$source_dir"; test -d "$target_dir"; test -z "$(find "$source_dir" -mindepth 1 -maxdepth 1 -print -quit)"; if findmnt -rn -T "$target_dir" | grep -Fq "$target_dir"; then echo already-mounted; else sudo mount --bind "$source_dir" "$target_dir"; fi; findmnt -T "$target_dir" -o TARGET,SOURCE,FSTYPE,OPTIONS -n'`
> - Ran `wsl.exe -d Ubuntu -- findmnt -T /mnt/e/STUDY/VAST/.publication-sockets/model-parity-policy-calibration-v2 -o TARGET,SOURCE,FSTYPE,OPTIONS -n`
> - Ran `wsl.exe -d Ubuntu -u root -- mount --bind /home/s-a-balashov/.local/state/vast/publication/sockets/model-parity-policy-calibration-v2 /mnt/e/STUDY/VAST/.publication-sockets/model-parity-policy-calibration-v2`
> - Ran `wsl.exe -d Ubuntu -- findmnt -M /mnt/e/STUDY/VAST/.publication-sockets/model-parity-policy-calibration-v2 -o TARGET,SOURCE,FSTYPE,OPTIONS -n`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && find evidence/model_parity -maxdepth 5 -path "*/execution_bundles/*/manifest.json" -type f | wc -l && docker ps --format "{{.Names}} {{.Status}}" | sed -n "1,20p"'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'ps -eo pid,ppid,stat,etime,cmd | grep -E "checkpoint_model_parity_materializer|docker run|analytics-(openvino|tensorrt)-worker" | grep -v grep | sed -n "1,40p"; find /home/s-a-balashov/.local/state/vast/publication/sockets/model-parity-policy-calibration-v2 -maxdepth 1 -printf "%f %y\n" | sort | sed -n "1,30p"'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'ps -p 18179 -o pid,stat,etime,%cpu,%mem,rss,cmd --no-headers; pgrep -P 18179 -a | sed -n "1,30p"; find /mnt/e/STUDY/VAST/evidence/model_parity -maxdepth 2 -type d -name ".v4_policy_calibration_physical_20260824.staging.*" -printf "%p\n"'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'ps -p 18179 -o pid,stat,etime,%cpu,%mem,rss --no-headers; pgrep -P 18179 -a | sed -n "1,20p"; docker ps --format "{{.Names}} {{.Status}}" | sed -n "1,20p"; find /mnt/e/STUDY/VAST/evidence/model_parity/.v4_policy_calibration_physical_20260824.staging.18179/execution_bundles -mindepth 2 -maxdepth 2 -name manifest.json -type f 2>/dev/null | wc -l'`
>
> </details>
>
> <details><summary>Ran a command</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 scripts/checkpoint_model_parity_materializer.py --project-root /mnt/e/STUDY/VAST --datasets /mnt/e/STUDY/VAST/configs/datasets.yaml --base-manifest /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.yaml --materialization-dir /mnt/e/STUDY/VAST/evidence/model_parity/v4_policy_calibration_physical_20260824 --accepted-manifest /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.yaml --accepted-assessment /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.assessment.json --acceptance-receipt /mnt/e/STUDY/VAST/configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.acceptance_receipt.json --ffmpeg /usr/bin/ffmpeg --execution-config /mnt/e/STUDY/VAST/configs/analytics_execution_layer.yaml --binding-set /mnt/e/STUDY/VAST/artifacts/analytics_execution_bindings/publication_v3 --cpu-runtime-probe /mnt/e/STUDY/VAST/artifacts/analytics_runtime_probes/publication_v3/cpu_runtime_probe.json --gpu-runtime-probe /mnt/e/STUDY/VAST/artifacts/analytics_runtime_probes/publication_v3/gpu_runtime_probe.json --socket-dir /mnt/e/STUDY/VAST/.publication-sockets/model-parity-policy-calibration-v2'`
>
> </details>
>
> Physical run завершён успешно: новая parity acceptance прошла повторную оценку, а materialization содержит 480/480 execution bundles. Следующий шаг — усилить acceptance до schema v2, чтобы её self-hash явно покрывал `transaction_index` и через него все 480 response/request/input/output файлов; текущую schema-v1 receipt оставляю только как промежуточную историческую запись.
>
> <details><summary>Ran 19 commands</summary>
>
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && jq "{schema_version,execution_bundle_count,output_segments_count:(.output_segments|length),execution_rows:(.execution_bundles|length),transaction_sha256,files_count:(.files|length)}" evidence/model_parity/v4_policy_calibration_physical_20260824/transaction_index.json && find evidence/model_parity/v4_policy_calibration_physical_20260824/execution_bundles -mindepth 2 -maxdepth 2 -name manifest.json -type f | wc -l && jq "[.execution_bundles[] | select(.role==\"calibration\" and .resource==\"tensorrt_cuda\")] | {cuda_calibration_count:length, codecs:(group_by(.codec)|map({codec:.[0].codec,count:length}))}" evidence/model_parity/v4_policy_calibration_physical_20260824/transaction_index.json'`
> - Ran `Get-Content -LiteralPath 'scripts/checkpoint_model_parity_acceptance.py' -TotalCount 780; Get-Content -LiteralPath 'tests/test_checkpoint_model_parity_acceptance.py' -TotalCount 260`
> - Ran `$p='scripts/checkpoint_model_parity_acceptance.py'; Get-Content -LiteralPath $p | Select-Object -Skip 340 -First 430`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_model_parity_acceptance.py
> @@
>  class Fixture:
>      def __init__(self, root: Path) -> None:
> @@
> -        (self.root / "evidence/model_parity/v3").mkdir(parents=True)
> +        self.evidence_root = self.root / "evidence/model_parity/v3"
> +        self.evidence_root.mkdir(parents=True)
> @@
>          self.evidence_paths: dict[tuple[str, str], Path] = {}
>          for branch in BRANCHES:
>              for name in EVIDENCE_NAMES:
> -                path = self.root / f"evidence/model_parity/v3/{branch}/{name}.json"
> +                path = self.evidence_root / f"documents/{branch}/{name}.json"
>                  path.parent.mkdir(parents=True, exist_ok=True)
>                  path.write_text(json.dumps({"branch": branch, "kind": name}, sort_keys=True) + "\n")
>                  self.evidence_paths[(branch, name)] = path
> +        self.transaction_path = self._write_transaction()
>          self.manifest_path.write_text("schema_version: 3\nfixture: accepted\n")
>          self.manifest = self.build_manifest()
> +
> +    def _descriptor(self, path: Path) -> dict[str, object]:
> +        payload = path.read_bytes()
> +        return {
> +            "path": path.relative_to(self.root).as_posix(),
> +            "size_bytes": len(payload),
> +            "sha256": hashlib.sha256(payload).hexdigest(),
> +        }
> +
> +    def _write_transaction(self) -> Path:
> +        files = [self._descriptor(path) for path in self.evidence_paths.values()]
> +        segments: list[dict[str, object]] = []
> +        bundles: list[dict[str, object]] = []
> +        for branch in BRANCHES:
> +            for resource in ("openvino_cpu", "tensorrt_cuda"):
> +                for index in range(60):
> +                    role = "calibration" if index < 30 else "evaluation"
> +                    codec = "h264" if index % 30 < 15 else "h265"
> +                    sample_id = f"mp.{branch}.{role}.{codec}.{index:02d}"
> +                    request_id = f"mp-v2-{branch}-{resource}-{index:02d}"
> +                    manifest_path = (
> +                        self.evidence_root
> +                        / "execution_bundles"
> +                        / request_id
> +                        / "manifest.json"
> +                    )
> +                    manifest_path.parent.mkdir(parents=True)
> +                    manifest_path.write_text(
> +                        json.dumps({"request_id": request_id}, sort_keys=True) + "\n"
> +                    )
> +                    manifest = self._descriptor(manifest_path)
> +                    files.append(manifest)
> +                    input_sha = hashlib.sha256(sample_id.encode()).hexdigest()
> +                    output_sha = hashlib.sha256(request_id.encode()).hexdigest()
> +                    segments.append(
> +                        {
> +                            "branch": branch,
> +                            "resource": resource,
> +                            "sample_id": sample_id,
> +                            "preprocessed_tensor_sha256": input_sha,
> +                        }
> +                    )
> +                    bundles.append(
> +                        {
> +                            "branch": branch,
> +                            "role": role,
> +                            "codec": codec,
> +                            "sample_id": sample_id,
> +                            "resource": resource,
> +                            "request_id": request_id,
> +                            "manifest": manifest,
> +                            "manifest_identity_sha256": hashlib.sha256(
> +                                (request_id + ":manifest").encode()
> +                            ).hexdigest(),
> +                            "request_sha256": hashlib.sha256(
> +                                (request_id + ":request").encode()
> +                            ).hexdigest(),
> +                            "response_sha256": hashlib.sha256(
> +                                (request_id + ":response").encode()
> +                            ).hexdigest(),
> +                            "input_tensor_sha256": input_sha,
> +                            "output_tensor_sha256": output_sha,
> +                        }
> +                    )
> +        files.sort(key=lambda item: str(item["path"]))
> +        transaction = {
> +            "schema_version": 2,
> +            "artifact_kind": "checkpoint_model_parity_materialization_transaction",
> +            "run_id": "v3",
> +            "final_materialization_path": "evidence/model_parity/v3",
> +            "document_count": 32,
> +            "files": files,
> +            "files_sha256": canonical_sha(files),
> +            "source_inventory": [],
> +            "source_inventory_sha256": canonical_sha([]),
> +            "output_segments": segments,
> +            "output_segments_sha256": canonical_sha(segments),
> +            "execution_bundle_count": 480,
> +            "execution_bundles": bundles,
> +            "execution_bundles_sha256": canonical_sha(bundles),
> +            "claimed_aggregates_accepted": False,
> +            "synthetic_or_mock_evidence_accepted": False,
> +        }
> +        transaction["transaction_sha256"] = canonical_sha(transaction)
> +        path = self.evidence_root / "transaction_index.json"
> +        path.write_text(json.dumps(transaction, sort_keys=True, separators=(",", ":")) + "\n")
> +        return path
> @@
>      def test_physical_accepted_fixture_promotes_and_revalidates(self) -> None:
> @@
>              result = fixture.promote()
> +            self.assertEqual(result["schema_version"], 2)
>              self.assertEqual(result["evidence_count"], 32)
> -            self.assertEqual(len(result["files"]), 35)
> +            self.assertEqual(len(result["files"]), 36)
> +            self.assertEqual(
> +                result["transaction_index"]["execution_bundle_count"], 480
> +            )
> @@
>              self.assertEqual(fixture.load()["binding_sha256"], result["binding_sha256"])
> +
> +    def test_transaction_index_or_bundle_tamper_cannot_authorize(self) -> None:
> +        for mode in ("index", "bundle"):
> +            with self.subTest(mode=mode):
> +                temporary, fixture = self.fixture()
> +                with temporary:
> +                    if mode == "index":
> +                        transaction = json.loads(fixture.transaction_path.read_text())
> +                        transaction["execution_bundle_count"] = 479
> +                        transaction["transaction_sha256"] = canonical_sha(
> +                            {
> +                                key: value
> +                                for key, value in transaction.items()
> +                                if key != "transaction_sha256"
> +                            }
> +                        )
> +                        fixture.transaction_path.write_text(
> +                            json.dumps(transaction, sort_keys=True, separators=(",", ":"))
> +                            + "\n"
> +                        )
> +                    else:
> +                        bundle = next(
> +                            fixture.evidence_root.glob(
> +                                "execution_bundles/*/manifest.json"
> +                            )
> +                        )
> +                        bundle.write_bytes(bundle.read_bytes() + b"tamper\n")
> +                    with self.assertRaisesRegex(
> +                        target.ModelParityAcceptanceError,
> +                        "transaction|bundle|coverage|descriptor",
> +                    ):
> +                        fixture.promote()
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_acceptance.ModelParityAcceptanceTests.test_physical_accepted_fixture_promotes_and_revalidates'`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\checkpoint_model_parity_acceptance.py
> @@
> -SCHEMA_VERSION = 1
> +SCHEMA_VERSION = 2
> +LEGACY_SCHEMA_VERSION = 1
> @@
>  _SHA_RE = re.compile(r"^[0-9a-f]{64}$")
> +_TRANSACTION_BUNDLE_COUNT = 480
> +_TRANSACTION_FIELDS = {
> +    "schema_version",
> +    "artifact_kind",
> +    "run_id",
> +    "final_materialization_path",
> +    "document_count",
> +    "files",
> +    "files_sha256",
> +    "source_inventory",
> +    "source_inventory_sha256",
> +    "output_segments",
> +    "output_segments_sha256",
> +    "execution_bundle_count",
> +    "execution_bundles",
> +    "execution_bundles_sha256",
> +    "claimed_aggregates_accepted",
> +    "synthetic_or_mock_evidence_accepted",
> +    "transaction_sha256",
> +}
> +_EXECUTION_BUNDLE_FIELDS = {
> +    "branch",
> +    "role",
> +    "codec",
> +    "sample_id",
> +    "resource",
> +    "request_id",
> +    "manifest",
> +    "manifest_identity_sha256",
> +    "request_sha256",
> +    "response_sha256",
> +    "input_tensor_sha256",
> +    "output_tensor_sha256",
> +}
> @@
>  def _manifest_material(
> @@
>      return {
> @@
>          "runtime_registries_sha256": _canonical_sha(registries),
>      }
> +
> +
> +def _transaction_index_material(
> +    root: Path,
> +    material: Mapping[str, Any],
> +    *,
> +    registry: _FileRegistry,
> +) -> dict[str, Any]:
> +    evidence_roots: set[str] = set()
> +    for evidence in material["evidence"]:
> +        relative = _normalized_relative(
> +            evidence["path"],
> +            f"accepted parity transaction evidence {evidence['branch']}/{evidence['evidence_name']}",
> +        )
> +        parts = relative.parts
> +        _require(
> +            len(parts) >= 4
> +            and parts[-3] == "documents"
> +            and parts[-2] == evidence["branch"]
> +            and parts[-1] == f"{evidence['evidence_name']}.json",
> +            "accepted parity evidence is outside the materialization transaction layout",
> +        )
> +        evidence_roots.add(Path(*parts[:-3]).as_posix())
> +    _require(
> +        len(evidence_roots) == 1,
> +        "accepted parity evidence does not share one transaction root",
> +    )
> +    evidence_root = next(iter(evidence_roots))
> +    transaction_relative = f"{evidence_root}/transaction_index.json"
> +    transaction_record = registry.add_path(
> +        transaction_relative, "model-parity transaction index"
> +    )
> +    index = _read_json_object(
> +        root / transaction_relative, "model-parity transaction index"
> +    )
> +    _exact(index, _TRANSACTION_FIELDS, "model-parity transaction index")
> +    _require(
> +        index.get("schema_version") == SCHEMA_VERSION
> +        and index.get("artifact_kind")
> +        == "checkpoint_model_parity_materialization_transaction"
> +        and index.get("run_id") == Path(evidence_root).name
> +        and index.get("final_materialization_path") == evidence_root
> +        and index.get("document_count") == 32
> +        and index.get("claimed_aggregates_accepted") is False
> +        and index.get("synthetic_or_mock_evidence_accepted") is False,
> +        "model-parity transaction provenance boundary drifted",
> +    )
> +    transaction_sha = index.get("transaction_sha256")
> +    _require(
> +        _valid_sha(transaction_sha)
> +        and transaction_sha
> +        == _canonical_sha(
> +            {key: value for key, value in index.items() if key != "transaction_sha256"}
> +        ),
> +        "model-parity transaction self-hash drifted",
> +    )
> +    files = index.get("files")
> +    source_inventory = index.get("source_inventory")
> +    output_segments = index.get("output_segments")
> +    execution_bundles = index.get("execution_bundles")
> +    _require(type(files) is list and bool(files), "transaction file inventory is missing")
> +    _require(type(source_inventory) is list, "transaction source inventory is invalid")
> +    _require(
> +        type(output_segments) is list
> +        and len(output_segments) == _TRANSACTION_BUNDLE_COUNT,
> +        "transaction output coverage is not exact 480",
> +    )
> +    _require(
> +        type(execution_bundles) is list
> +        and len(execution_bundles) == _TRANSACTION_BUNDLE_COUNT
> +        and index.get("execution_bundle_count") == _TRANSACTION_BUNDLE_COUNT,
> +        "transaction execution bundle coverage is not exact 480",
> +    )
> +    _require(
> +        index.get("files_sha256") == _canonical_sha(files)
> +        and index.get("source_inventory_sha256") == _canonical_sha(source_inventory)
> +        and index.get("output_segments_sha256") == _canonical_sha(output_segments)
> +        and index.get("execution_bundles_sha256")
> +        == _canonical_sha(execution_bundles),
> +        "model-parity transaction indexed material hash drifted",
> +    )
> +
> +    transaction_files = _FileRegistry(root)
> +    files_by_path: dict[str, dict[str, Any]] = {}
> +    for position, raw in enumerate(files):
> +        expected = _validate_descriptor(raw, f"transaction file[{position}]")
> +        path = str(expected["path"])
> +        _require(path not in files_by_path, "transaction file path is duplicated")
> +        _require(
> +            path.startswith(f"{evidence_root}/")
> +            and path != transaction_relative,
> +            "transaction file escaped its materialization root",
> +        )
> +        actual = transaction_files.add_descriptor(
> +            expected, f"transaction file[{position}]"
> +        )
> +        files_by_path[path] = actual
> +    for identity, path in transaction_files.identities.items():
> +        primary = registry.identities.get(identity)
> +        _require(
> +            primary is None or primary == path,
> +            "transaction file aliases an acceptance artifact",
> +        )
> +    for evidence in material["evidence"]:
> +        expected = {
> +            key: evidence[key] for key in ("path", "size_bytes", "sha256")
> +        }
> +        _require(
> +            files_by_path.get(str(evidence["path"])) == expected,
> +            "acceptance-bound evidence is absent from transaction files",
> +        )
> +
> +    output_coordinates: set[tuple[str, str, str]] = set()
> +    for segment in output_segments:
> +        _require(type(segment) is dict, "transaction output segment is invalid")
> +        coordinate = (
> +            str(segment.get("branch")),
> +            str(segment.get("resource")),
> +            str(segment.get("sample_id")),
> +        )
> +        _require(
> +            coordinate[0] in BRANCHES
> +            and coordinate[1] in {"openvino_cpu", "tensorrt_cuda"}
> +            and coordinate[2]
> +            and _valid_sha(segment.get("preprocessed_tensor_sha256")),
> +            "transaction output coordinate is invalid",
> +        )
> +        _require(
> +            coordinate not in output_coordinates,
> +            "transaction output coordinate is duplicated",
> +        )
> +        output_coordinates.add(coordinate)
> +
> +    execution_coordinates: set[tuple[str, str, str]] = set()
> +    request_ids: set[str] = set()
> +    coverage: dict[tuple[str, str, str, str], int] = {}
> +    for row in execution_bundles:
> +        _exact(row, _EXECUTION_BUNDLE_FIELDS, "transaction execution bundle")
> +        branch = row.get("branch")
> +        resource = row.get("resource")
> +        role = row.get("role")
> +        codec = row.get("codec")
> +        sample_id = row.get("sample_id")
> +        request_id = row.get("request_id")
> +        coordinate = (str(branch), str(resource), str(sample_id))
> +        _require(
> +            branch in BRANCHES
> +            and resource in {"openvino_cpu", "tensorrt_cuda"}
> +            and role in {"calibration", "evaluation"}
> +            and codec in {"h264", "h265"}
> +            and type(sample_id) is str
> +            and bool(sample_id)
> +            and type(request_id) is str
> +            and bool(request_id)
> +            and request_id not in request_ids,
> +            "transaction execution bundle coordinate is invalid",
> +        )
> +        _require(
> +            coordinate not in execution_coordinates,
> +            "transaction execution coordinate is duplicated",
> +        )
> +        manifest = _validate_descriptor(
> +            row.get("manifest"), "transaction execution bundle manifest"
> +        )
> +        _require(
> +            manifest["path"]
> +            == f"{evidence_root}/execution_bundles/{request_id}/manifest.json"
> +            and files_by_path.get(str(manifest["path"])) == manifest,
> +            "transaction execution bundle manifest descriptor drifted",
> +        )
> +        for field in (
> +            "manifest_identity_sha256",
> +            "request_sha256",
> +            "response_sha256",
> +            "input_tensor_sha256",
> +            "output_tensor_sha256",
> +        ):
> +            _require(_valid_sha(row.get(field)), f"transaction {field} is invalid")
> +        request_ids.add(request_id)
> +        execution_coordinates.add(coordinate)
> +        key = (str(branch), str(resource), str(role), str(codec))
> +        coverage[key] = coverage.get(key, 0) + 1
> +    _require(
> +        execution_coordinates == output_coordinates,
> +        "transaction execution/output coordinate coverage drifted",
> +    )
> +    _require(
> +        coverage
> +        == {
> +            (branch, resource, role, codec): 15
> +            for branch in BRANCHES
> +            for resource in ("openvino_cpu", "tensorrt_cuda")
> +            for role in ("calibration", "evaluation")
> +            for codec in ("h264", "h265")
> +        },
> +        "transaction balanced execution coverage drifted",
> +    )
> +    return {
> +        **transaction_record,
> +        "transaction_sha256": transaction_sha,
> +        "files_sha256": index["files_sha256"],
> +        "output_segments_sha256": index["output_segments_sha256"],
> +        "execution_bundle_count": _TRANSACTION_BUNDLE_COUNT,
> +        "execution_bundles_sha256": index["execution_bundles_sha256"],
> +    }
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\scripts\checkpoint_model_parity_acceptance.py
> @@
>      material = _manifest_material(root, manifest_record, manifest, registry=registry)
> +    transaction = _transaction_index_material(
> +        root, material, registry=registry
> +    )
> @@
>      for evidence in material["evidence"]:
> @@
>              f"parity evidence {evidence['branch']}/{evidence['evidence_name']} drifted during assessment",
>          )
> +    post_transaction = _transaction_index_material(
> +        root, material, registry=post_registry
> +    )
> +    _require(
> +        post_transaction == transaction,
> +        "model-parity transaction drifted during assessment",
> +    )
>      accepted_assessment = {
> @@
>          "evidence_count": 32,
>          "evidence_sha256": material["evidence_sha256"],
> +        "transaction_index": transaction,
> @@
>          "evidence_count": 32,
>          "evidence_sha256": material["evidence_sha256"],
> +        "transaction_index": transaction,
> @@
> -    expected_receipt_fields = {
> +    receipt_version = receipt.get("schema_version")
> +    _require(
> +        receipt_version in {LEGACY_SCHEMA_VERSION, SCHEMA_VERSION},
> +        "model-parity acceptance receipt schema is unsupported",
> +    )
> +    expected_receipt_fields = {
>          "schema_version", "artifact_kind", "status", "accepted_manifest",
> @@
>          "receipt_sha256",
>      }
> +    if receipt_version == SCHEMA_VERSION:
> +        expected_receipt_fields.add("transaction_index")
>      _exact(receipt, expected_receipt_fields, "model-parity acceptance receipt")
>      _require(
> -        receipt.get("schema_version") == SCHEMA_VERSION
> -        and receipt.get("artifact_kind") == RECEIPT_KIND
> +        receipt.get("artifact_kind") == RECEIPT_KIND
> @@
>      manifest_material = _manifest_material(root, manifest_record, manifest, registry=registry)
> @@
>      assessment_fields = {
> @@
>          "assessment_sha256",
>      }
> +    if receipt_version == SCHEMA_VERSION:
> +        assessment_fields.add("transaction_index")
>      _exact(assessment, assessment_fields, "accepted model-parity assessment")
>      _require(
> -        assessment.get("schema_version") == SCHEMA_VERSION
> +        assessment.get("schema_version") == receipt_version
> @@
>          "accepted model-parity evidence set drifted",
>      )
> +    transaction: dict[str, Any] | None = None
> +    if receipt_version == SCHEMA_VERSION:
> +        transaction = _transaction_index_material(
> +            root, manifest_material, registry=registry
> +        )
> +        _require(
> +            receipt.get("transaction_index") == transaction
> +            and assessment.get("transaction_index") == transaction,
> +            "accepted model-parity transaction binding drifted",
> +        )
> @@
>      _require(
> @@
>          "model-parity accepted assessment has drifted",
>      )
> +    if transaction is not None:
> +        post_registry = _FileRegistry(root)
> +        post_manifest = post_registry.add_path(
> +            manifest_record["path"], "post-reassessment model-parity manifest"
> +        )
> +        _require(
> +            post_manifest == manifest_record,
> +            "accepted model-parity manifest drifted during reassessment",
> +        )
> +        post_transaction = _transaction_index_material(
> +            root, manifest_material, registry=post_registry
> +        )
> +        _require(
> +            post_transaction == transaction,
> +            "accepted model-parity transaction drifted during reassessment",
> +        )
>      files = [registry.records[path] for path in sorted(registry.records)]
>      binding = {
> -        "schema_version": SCHEMA_VERSION,
> +        "schema_version": receipt_version,
> @@
>          "files_sha256": _canonical_sha(files),
>      }
> +    if transaction is not None:
> +        binding["transaction_index"] = transaction
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `python -B -m py_compile scripts/checkpoint_model_parity_acceptance.py tests/test_checkpoint_model_parity_acceptance.py`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_acceptance.ModelParityAcceptanceTests.test_physical_accepted_fixture_promotes_and_revalidates'`
> - Ran `$p='tests/test_checkpoint_model_parity_acceptance.py'; Get-Content -LiteralPath $p | Select-Object -Skip 238 -First 30`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_model_parity_acceptance.py
> @@
> -                32,
> +                33,
>              )
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_acceptance'`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -c "import sys;sys.path.insert(0,\"scripts\");from checkpoint_model_parity_acceptance import load_verified_model_parity_acceptance as load;b=load(project_root=\".\",receipt_path=\"configs/checkpoint_analytics_model_parity.accepted.acceptance_receipt.json\");print(b[\"schema_version\"],b[\"evidence_count\"],b[\"binding_sha256\"])"'`
> - Ran `$patch = @'
> *** Begin Patch
> *** Update File: E:\STUDY\VAST\tests\test_checkpoint_model_parity_acceptance.py
> @@
>      def test_transaction_index_or_bundle_tamper_cannot_authorize(self) -> None:
> @@
>                      with self.assertRaisesRegex(
> @@
>                          fixture.promote()
> +
> +    def test_existing_schema_v1_receipt_remains_read_only_loadable(self) -> None:
> +        temporary, fixture = self.fixture()
> +        with temporary:
> +            fixture.promote()
> +            assessment = json.loads(fixture.assessment_path.read_text())
> +            assessment.pop("transaction_index")
> +            assessment["schema_version"] = 1
> +            assessment["assessment_sha256"] = canonical_sha(
> +                {
> +                    key: value
> +                    for key, value in assessment.items()
> +                    if key != "assessment_sha256"
> +                }
> +            )
> +            fixture.assessment_path.chmod(0o600)
> +            fixture.assessment_path.write_text(
> +                json.dumps(assessment, sort_keys=True, separators=(",", ":")) + "\n"
> +            )
> +            receipt = json.loads(fixture.receipt_path.read_text())
> +            receipt.pop("transaction_index")
> +            receipt["schema_version"] = 1
> +            receipt["accepted_assessment"] = fixture._descriptor(
> +                fixture.assessment_path
> +            )
> +            receipt["accepted_assessment_identity_sha256"] = assessment[
> +                "assessment_sha256"
> +            ]
> +            receipt["receipt_sha256"] = canonical_sha(
> +                {
> +                    key: value
> +                    for key, value in receipt.items()
> +                    if key != "receipt_sha256"
> +                }
> +            )
> +            fixture.receipt_path.chmod(0o600)
> +            fixture.receipt_path.write_text(
> +                json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n"
> +            )
> +
> +            legacy = fixture.load()
> +            self.assertEqual(legacy["schema_version"], 1)
> +            self.assertNotIn("transaction_index", legacy)
> *** End Patch
> '@; & 'C:\Users\s-a-balashov\AppData\Local\Temp\codex-apply-patch-26.818.exe' --codex-run-as-apply-patch $patch`
> - Ran `wsl.exe -d Ubuntu -- bash -lc 'cd /mnt/e/STUDY/VAST && /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -m unittest tests.test_checkpoint_model_parity_acceptance'`
> - Ran `$paths=@('configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.transaction_bound.assessment.json','configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.transaction_bound.acceptance_receipt.json'); $paths | ForEach-Object { "$_=" + (Test-Path -LiteralPath $_) }`
> - Ran `wsl.exe -d Ubuntu --cd /mnt/e/STUDY/VAST -- /mnt/e/STUDY/VAST/.publication-runtime/full-publication-cp312-v1/bin/python3.12 -c "import json,sys;sys.path.insert(0,'scripts');from checkpoint_model_parity_acceptance import promote_model_parity_acceptance as promote;b=promote(project_root='.',accepted_manifest_path='configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.yaml',accepted_assessment_path='configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.transaction_bound.assessment.json',acceptance_receipt_path='configs/checkpoint_analytics_model_parity.accepted.policy_calibration_v2.transaction_bound.acceptance_receipt.json');print(json.dumps({'schema_version':b['schema_version'],'binding_sha256':b['binding_sha256'],'transaction_sha256':b['transaction_index']['transaction_sha256'],'files':len(b['files'])},sort_keys=True))"`
> - Ran `rg --files artifacts | rg "qualification.*(candidate|receipt|manifest|index).*v2|policy.*candidate|qualification_index" | Select-Object -First 260; rg -n "candidate-manifest|candidate-receipt|output-dir" tests/test_publication_policy_qualification_bootstrap_v2.py scripts/publication_policy_qualification_index_v2.py | Select-Object -First 120`
> - Ran `Get-Content -LiteralPath 'scripts/model_parity_grant.py' -TotalCount 270; $p='scripts/full_publication_identity_artifacts.py'; Get-Content -LiteralPath $p | Select-Object -Skip 350 -First 90`
>
> </details>
</details>
