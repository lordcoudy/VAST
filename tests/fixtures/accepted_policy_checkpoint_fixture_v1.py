"""Completed fixture checkpoints from genuine default executor input readers.

This composes already finalized artificial native cells; it never launches a
qualification arm or repairs acceptance payloads. Full consumer acceptance must
separately validate the complete graph and retain its fixture-only limitations.
"""

import os
from pathlib import Path
from typing import Any, Mapping

import publication_policy_qualification_pilot_executor_v2 as executor


def write_complete_fixture_checkpoint_v1(*, prepared: Mapping[str, Any],
    guardian_authority_path: Path, checkpoint_path: Path | None = None) -> Path:
    root = Path(prepared["root"]).resolve(strict=True)
    checkpoint = Path(checkpoint_path or Path(prepared["output_dir"]) / "qualification_execution_checkpoint.v2.json").absolute()
    if (checkpoint.resolve(strict=False) != checkpoint or not checkpoint.is_relative_to(root)
            or os.path.lexists(checkpoint)):
        raise ValueError("checkpoint must be a fresh canonical project artifact")
    if Path(executor.__file__).resolve(strict=True) != root / "scripts/publication_policy_qualification_pilot_executor_v2.py":
        raise ValueError("checkpoint executor must come from the selected project root")
    transaction = prepared["transaction"]
    cells = executor.qualification_pilot_cells_v2()
    with executor.PhysicalRootCustodyV1.open(root, label="fixture checkpoint project_root") as custody:
        token = executor._ACTIVE_PHYSICAL_CUSTODY.set(custody)
        try:
            inputs = executor._load_qualification_inputs(project_root=root, **{
                key: transaction[key] for key in ("candidate_index_path", "candidate_manifest_path",
                    "candidate_receipt_path", "bootstrap_mapping_path", "bootstrap_receipt_path",
                    "bootstrap_dir", "transaction_receipt_path")})
            bootstrap = executor._physical_directory(root, transaction["bootstrap_dir"], label="bootstrap_dir")
            pilots = executor._physical_directory(root, prepared["pilot_root"], label="pilot_root")
            if (pilots == checkpoint or pilots in checkpoint.parents or bootstrap in checkpoint.parents
                    or checkpoint in {pin.path for pin in inputs.pins}):
                raise ValueError("fixture checkpoint overlaps input or pilot evidence namespace")
            executor._physical_directory(root, checkpoint.parent, label="fixture checkpoint parent")
            code = executor._load_execution_code_closure(root=root, receipt_path=prepared["code_closure_path"])
            operational = executor._load_operational_inputs(inputs=inputs, bootstrap_dir=bootstrap,
                cells=cells, runtime_input_materialization_receipt_path=prepared["runtime"]["receipt_path"],
                guardian_service_authority_path=guardian_authority_path,
                preprocessing_contract_path=prepared["preprocessing"]["contract_path"],
                preprocessing_contract_receipt_path=prepared["preprocessing"]["receipt_path"],
                service_authority_validator=executor._default_service_authority_validator,
                preprocessing_contract_loader=executor._default_preprocessing_contract_loader,
                runtime_expectations_loader=executor._default_runtime_expectations_loader)
            pins = (*inputs.pins, *operational.pins, *code.pins)
            if checkpoint in {pin.path for pin in pins}:
                raise ValueError("fixture checkpoint overlaps held input/code closure")
            completed = []
            for cell in cells:
                final = executor._pilot_path(pilots, cell)
                executor._validate_final_namespace(final, root=root, cell=cell,
                    expected_operational_binding=executor._expected_operational_binding(
                        inputs=inputs, operational=operational, cell=cell))
                completed.append(executor._checkpoint_entry(root=root, pilot_root=pilots, final=final, cell=cell))
            hashes = executor._input_sha256(inputs, operational=operational)
            identity = executor._input_identity(root=root, input_sha256=hashes, pins=pins, code_closure=code)
            matrix = executor._matrix_sha(cells)
            value = executor._checkpoint_payload(matrix_sha256=matrix, input_sha256=hashes,
                input_identity=identity, completed=completed)
            executor._assert_execution_barrier(root=root, pins=pins, code_closure=code)
            executor._write_checkpoint(checkpoint, value, expected_previous_identity=None, expected_completed_prefix=())
            loaded = executor._load_checkpoint(path=checkpoint, matrix_sha256=matrix,
                input_sha256=hashes, input_identity=identity, cells=cells, root=root,
                pilot_root=pilots, inputs=inputs, operational=operational)
            if loaded != completed or len(loaded) != 32:
                raise ValueError("fixture completed checkpoint did not cold-load exact 32 cells")
            executor._assert_execution_barrier(root=root, pins=pins, code_closure=code)
            custody.verify()
        finally:
            executor._ACTIVE_PHYSICAL_CUSTODY.reset(token)
    with executor.PhysicalRootCustodyV1.open(root, label="fixture checkpoint cold project_root") as cold:
        executor._cold_validate_pilot_checkpoint(root=root, checkpoint_path=checkpoint, custody=cold)
        cold.verify()
    return checkpoint
