# Fresh stock native pair: command and controller recipe

Prepared by read-only source review of commit `7f3dfa42858c85d6e3db2cb1274dd13af35696c9`, with the subsequent narrow GVA3 and pinned-Docker absence corrections pending a new reviewed source freeze. No command below has been executed by this recipe. This document grants no image, model, qualification, or publication acceptance.

The stock transaction already creates the four fragments, candidate index/manifest/receipt, bootstrap mapping, and actual calibration receipts. Do not run separate producers into the same outputs. The diagnostic consumes the stock 32-bundle input spine but executes exactly the two selected original GStreamer h264 forced-resource operations. Do not call the 32-cell pilot executor, full qualification closure CLI, Q4, or full benchmark to obtain this gate.

## Physical prerequisites and shared authority

Use the actual reviewed source root, not a bind alias or a different checkout. The current root is `/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec`; verify it physically before invocation. Current read-only observation confirms `/usr/bin/docker` is canonical, `/var/run/docker.sock` resolves to `/run/docker.sock`, and `/var/tmp` is ext4 (`ext2/ext3` statfs spelling).

All four affected runtime source/dependency/COPY closures must be rebuilt and independently packaged under the new source freeze. The original three native and two inference-worker closures remain reusable only through their unchanged, physically revalidated exact scopes. Build/package receipts and current live image inspect remain intrinsic prerequisites. An old aggregate runtime receipt or parity receipt must never be resealed to name a new patch.

The current fragment and bootstrap validators require a complete fresh aggregate four-runtime patch and new patch-bound v4 parity: 480 original physical execution bundles in 32 groups. This is an existing authority prerequisite, distinct from executing the 32 qualification cells. The current CPU pair guardian still starts all eight CPU/GPU branch workers; a CPU pair therefore does not remove the GPU hardware/model prerequisites.

The original canonical ext4 socket/evidence mounts and pinned Python runtime must be physically checked anew. Supported check-only helpers are `scripts/mount_publication_sockets_wsl.sh --source-socket-dir ACTUAL --project-root ROOT --project-socket-mount .publication-sockets/model-parity-v3 --check-only`, `scripts/mount_publication_evidence_wsl.sh --source-evidence-dir ACTUAL --project-root ROOT --project-evidence-mount evidence/model_parity --check-only`, and `scripts/mount_publication_runtime_wsl.sh --source-runtime ACTUAL --project-root ROOT --check-only`. Use observed current source directories and namespace identities; the old g scripts are references, not authority for current mount identity.

Suggested new namespace variables (create only fresh required parent/control directories, with owned 0700 ext4 socket/scratch directories):

```bash
root=/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec
base="$root/artifacts/benchmark_recovery_20260930"
py=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
patch="$base/qualification_image_identity_patch.json"
parity="$base/model_parity_v4"
pair="$base/cpu"
q="$pair/qualification"
pre="$pair/preprocessing"
plan="$pair/operation-plan/capture-plan/capture_plan_index.v1.json"
gctx="$pair/operation-plan/capture-plan/guardian_capture_context.v1.json"
gev="$pair/guardian-evidence"
gop="$pair/guardian-operational"
socketroot=/var/tmp/vbr0930cpu
gsock="$socketroot/r/a.sock"
scratch="$socketroot/s"
code="$base/control/qualification_execution_code_closure.v1.receipt.json"
```

Use the actual new build outputs as the `--runtime-receipt SYSTEM=PATH` inputs. The stock refreeze CLIs support:

```bash
"$py" -B "$root/scripts/publication_qualification_image_refreeze_v1.py" capture \
  --project-root "$root" --registry "$root/configs/publication_qualification_image_refreeze_v1.json" \
  --system SYSTEM --native-receipt ACTUAL_UNCHANGED_NATIVE_RECEIPT \
  --receipt-output NEW_RUNTIME_FREEZE_RECEIPT --docker /usr/bin/docker

"$py" -B "$root/scripts/publication_qualification_image_refreeze_v1.py" assemble \
  --project-root "$root" --registry "$root/configs/publication_qualification_image_refreeze_v1.json" \
  --native-receipt ACTUAL_UNCHANGED_NATIVE_RECEIPT --worker-receipt ACTUAL_UNCHANGED_WORKER_RECEIPT \
  --runtime-receipt deepstream=NEW_DS --runtime-receipt savant=NEW_SAVANT \
  --runtime-receipt openvino_gva=NEW_GVA --runtime-receipt gstreamer_custom=NEW_GST --output "$patch"

"$py" -B "$root/scripts/publication_qualification_image_refreeze_v1.py" verify-patch \
  --project-root "$root" --patch "$patch"
```

The uppercase receipt tokens mean actual independently validated build outputs; they are not guessed filenames. Produce the fresh shared parity authority once:

```bash
"$py" -B "$root/scripts/checkpoint_model_parity_materializer_v4.py" \
  --project-root "$root" --image-patch "$patch" \
  --source-execution-config "$root/configs/analytics_execution_layer.yaml" \
  --source-manifest "$root/configs/checkpoint_analytics_model_parity.yaml" \
  --datasets "$root/configs/datasets.yaml" \
  --runtime-probe-dir "$parity/runtime_probes" \
  --versioned-execution-config "$parity/analytics_execution_layer.v4.json" \
  --base-v4-manifest "$parity/base_manifest.v4.yaml" \
  --binding-set "$parity/bindings" --materialization-dir "$parity/materialization" \
  --accepted-manifest "$parity/accepted_manifest.v4.yaml" \
  --accepted-assessment "$parity/accepted_assessment.v4.json" \
  --acceptance-receipt "$parity/acceptance_receipt.v4.json" \
  --acceptance-binding "$parity/acceptance_binding.v4.json" \
  --ffmpeg /usr/bin/ffmpeg --socket-dir /var/tmp/vbr0930parity
```

All parity destinations and the owned socket directory must be fresh, and the fixed dataset/KPP inputs must pass the stock physical validators. The materializer supports root-relative outputs under this artifact namespace; versioned manifests need not overwrite any config file.

## Exact per-pair preparation order

1. Create and validate a fresh host execution-code closure after the final source freeze. Current source discovery is 78 project modules. The stock CLI is:

```bash
"$py" -B "$root/scripts/publication_policy_qualification_execution_code_closure_v1.py" \
  --project-root "$root" --receipt "$code"
"$py" -B "$root/scripts/publication_policy_qualification_execution_code_closure_v1.py" \
  --project-root "$root" --receipt "$code" --validate-only
```

2. Create one new complete nonaccepted transaction and preprocessing bundle:

```bash
"$py" -B "$root/scripts/publication_policy_qualification_transaction_v2.py" \
  --project-root "$root" --identity-patch "$patch" \
  --accepted-model-parity-manifest "$parity/accepted_manifest.v4.yaml" \
  --accepted-model-parity-assessment "$parity/accepted_assessment.v4.json" \
  --accepted-model-parity-receipt "$parity/acceptance_receipt.v4.json" \
  --output-root "$q" --docker /usr/bin/docker

"$py" -B "$root/scripts/publication_guardian_preprocessing_contract_v1.py" \
  --project-root "$root" --qualification-transaction-receipt "$q/qualification_input_transaction.v2.receipt.json" \
  --output-dir "$pre"
```

Actual transaction outputs are `candidate/checkpoint_policy_qualification_index.v2.json`, `candidate/checkpoint_policy_capability_candidate_manifest.json`, `candidate/checkpoint_policy_qualification_candidate_receipt.json`, `bootstrap/checkpoint_policy_qualification_bootstrap_mapping.v2.json`, `bootstrap/checkpoint_policy_qualification_bootstrap_receipt.v2.json`, four calibration JSONs, and `qualification_input_transaction.v2.receipt.json`. The preprocessing output filenames are `checkpoint_analytics_preprocessing_contract.v1.json` and `checkpoint_analytics_preprocessing_contract.v1.receipt.json`.

3. Build the separately immutable two-operation plan BEFORE starting the guardian. Use the existing Python API because its CLI does not expose the canonical engine-socket override. Its default `/var/run/docker.sock` fails the stock no-alias validator on this Ubuntu installation. From the thin artifact controller, with `scripts` on `sys.path`:

```python
from pathlib import Path
from publication_operational_stock_operations_v1 import prepare_stock_operational_capture_plan_v1
prepared = prepare_stock_operational_capture_plan_v1(
    project_root=root, output_dir=pair / "operation-plan",
    mode="bounded_native_diagnostic_operational_v1", diagnostic_resource="cpu",
    candidate_index_path=q / "candidate/checkpoint_policy_qualification_index.v2.json",
    candidate_manifest_path=q / "candidate/checkpoint_policy_capability_candidate_manifest.json",
    candidate_receipt_path=q / "candidate/checkpoint_policy_qualification_candidate_receipt.json",
    bootstrap_mapping_path=q / "bootstrap/checkpoint_policy_qualification_bootstrap_mapping.v2.json",
    bootstrap_receipt_path=q / "bootstrap/checkpoint_policy_qualification_bootstrap_receipt.v2.json",
    bootstrap_dir=q / "bootstrap",
    transaction_receipt_path=q / "qualification_input_transaction.v2.receipt.json",
    preprocessing_contract_path=pre / "checkpoint_analytics_preprocessing_contract.v1.json",
    preprocessing_receipt_path=pre / "checkpoint_analytics_preprocessing_contract.v1.receipt.json",
    execution_code_closure_path=code,
    pilot_root=pair / "unexecuted-qualification-pilots", guardian_output_dir=pair / "guardian-operational",
    container_engine_path=Path("/usr/bin/docker"), container_engine_socket_path=Path("/run/docker.sock"))
```

The API executes the original stock source-plan, candidate/parity/preprocessing/code-closure and image validators. It does not run measurement. Its result is the actual capture-plan index descriptor. It preserves original plan/source/worker/image constants and does not generate ingress keys, frame/trace IDs or wire request IDs.

4. Start ONE original sidecar guardian as an owned foreground subprocess, preserving its actual child status and separate stdout/stderr. The exact supported command is:

```bash
"$py" -B "$root/scripts/checkpoint_gstreamer_analytics_sidecar.py" \
  --production-guardian --project-root "$root" \
  --config "$parity/analytics_execution_layer.v4.json" --binding-set "$parity/bindings" \
  --policy-capability-manifest "$q/candidate/checkpoint_policy_capability_candidate_manifest.json" \
  --preprocessing-contract "$pre/checkpoint_analytics_preprocessing_contract.v1.json" \
  --preprocessing-contract-receipt "$pre/checkpoint_analytics_preprocessing_contract.v1.receipt.json" \
  --runtime-dir "$socketroot/r" --front-socket "$gsock" --evidence-root "$gev" \
  --operational-accounting-context "$gctx" \
  --max-connections 202560 --max-requests-per-connection 4320000 --max-total-requests 29168640000 \
  --startup-timeout-seconds 120 --shutdown-timeout-seconds 10
```

Those capacity numbers are unchanged stock lower bounds for the production service. The activated two-operation capture context separately imposes the reviewed journal budgets and identity domain. Do not lower the stock capacity contract or add extra traffic to exercise its limits.

Readiness is the actual persisted `$gev/service_authority.v1.json`, authenticated by `--production-status-authority "$gev/service_authority.v1.json" --control-timeout-seconds 60`. Poll only within a bounded startup deadline and retain the original guardian process returncode. File presence alone is not readiness.

5. Only after authenticated readiness, materialize the stock 32 JSON bundles. It performs live all-four image inspection plus the two native OpenVINO/GStreamer device probes, not 32 qualification executions:

```bash
"$py" -B "$root/scripts/publication_policy_qualification_runtime_inputs_v2.py" \
  --project-root "$root" \
  --candidate-index "$q/candidate/checkpoint_policy_qualification_index.v2.json" \
  --candidate-manifest "$q/candidate/checkpoint_policy_capability_candidate_manifest.json" \
  --candidate-receipt "$q/candidate/checkpoint_policy_qualification_candidate_receipt.json" \
  --bootstrap-mapping "$q/bootstrap/checkpoint_policy_qualification_bootstrap_mapping.v2.json" \
  --bootstrap-receipt "$q/bootstrap/checkpoint_policy_qualification_bootstrap_receipt.v2.json" \
  --bootstrap-dir "$q/bootstrap" \
  --qualification-transaction-receipt "$q/qualification_input_transaction.v2.receipt.json" \
  --container-engine /usr/bin/docker --container-engine-socket /run/docker.sock \
  --analytics-socket "$gsock" --scratch-root "$scratch" --deadline-ms 100 --duration-s 180 \
  --operational-capture-plan "$plan"
```

The immutable output is `$q/bootstrap/qualification-runtime-inputs-v2`, and its receipt is `qualification-runtime-inputs.materialization.v2.json`. Only the two selected original arms receive diagnostic capture activation; siblings remain ordinary unexecuted bundles.

## Execute only the two original operations, then authenticate stop

Read the held plan with `held_operational_capture_plan_v1(project_root=root,index_path=plan)` and select its two `operations_by_id` rows. Do not reconstruct IDs from guessed native traffic. CPU operation IDs, derived by the stock constructor, are `diagnostic-gstreamer_custom-cpu-h264-independent-processes` and `diagnostic-gstreamer_custom-cpu-h264-shared-video-dag`. Their stock bundle paths are `gstreamer_custom/cpu/h264/independent_processes.json` and `gstreamer_custom/cpu/h264/shared_video_dag.json` under the runtime-input root. Execute them sequentially with this supported adapter CLI, substituting the actual selected row/bundle:

```bash
"$py" -B "$root/scripts/publication_benchmark_native_diagnostic_v1.py" \
  --project-root "$root" --capture-plan-path "$plan" --operation-id ORIGINAL_OPERATION_ID \
  --runtime-bundle-path ACTUAL_SELECTED_BUNDLE \
  --candidate-index-path "$q/candidate/checkpoint_policy_qualification_index.v2.json" \
  --preprocessing-contract-path "$pre/checkpoint_analytics_preprocessing_contract.v1.json" \
  --preprocessing-receipt-path "$pre/checkpoint_analytics_preprocessing_contract.v1.receipt.json" \
  --runtime-materialization-receipt-path "$q/bootstrap/qualification-runtime-inputs-v2/qualification-runtime-inputs.materialization.v2.json" \
  --guardian-authority-path "$gev/service_authority.v1.json" \
  --transaction-receipt-path "$q/qualification_input_transaction.v2.receipt.json" \
  --bootstrap-mapping-path "$q/bootstrap/checkpoint_policy_qualification_bootstrap_mapping.v2.json" \
  --bootstrap-receipt-path "$q/bootstrap/checkpoint_policy_qualification_bootstrap_receipt.v2.json"
```

The adapter uses the actual v3 request constructor/lower GStreamer runtime, original process/container custody, host hardware collector, stock qualification finalizer and cold acceptance validators. Each output location is reserved in the original operation document; no output-directory flag is supported. Its own `native_diagnostic.execution.v1.json` remains explicitly nonpromoting. A successful individual receipt is not yet a successful pair accounting result.

The controller must request authenticated guardian stop in `finally` on both success and failure, preserve the primary operation failure, wait for the original guardian child, and require the stop command plus original child to return zero for a successful pair:

```bash
"$py" -B "$root/scripts/checkpoint_gstreamer_analytics_sidecar.py" \
  --production-stop-authority "$gev/service_authority.v1.json" --control-timeout-seconds 60
```

Do not combine control mode with lifecycle flags. This command sends the existing nonce-bound stop request, waits for persisted lifecycle, and checks its acknowledgement. It returns zero only for `clean_stop_nonpublication`. Do not fabricate a clean stop after a failed original guardian. Retain any actual failed lifecycle and exact cleanup observations, and start a fresh plan/guardian for a later attempt. Container quiescence is separately proved by the actual container-custody readers, never inferred from a killed CLI.

## Smallest stopped-pair binding and cold controller

There is no diagnostic-pair closure CLI. The thin artifact controller must compose the existing validators; the full qualification closure CLI requires all 37 originals and 32 accepted measured cells and must not be called for this pair.

Write one immutable, sealed ordinary JSON binding outside every legacy evidence namespace. Obtain every descriptor from actual physically held bytes, using streaming `PhysicalRootCustodyV1.read_descriptor(...,capture=False)` for large native files. Do not cache a full 64MiB native file while preparing descriptors. The binding's exact fields are:

```python
{
 "schema_version": 1,
 "artifact_kind": "vast_original_operational_execution_binding_v1",
 "mode": "bounded_native_diagnostic_operational_v1",
 "capture_plan": ACTUAL_INDEX_DESCRIPTOR,
 "guardian_companion": ACTUAL_DESCRIPTOR_OF_GOP_OPERATIONAL_GROUP_V1_JSON,
 "operation_outputs": [
   {"operation_id": row["operation_id"],
    "native_domain": ACTUAL_RESERVED_NATIVE_FILE_DESCRIPTOR,
    "measurement_decisions": ACTUAL_MEASUREMENT_DIR_PUBLICATION_POLICY_DECISIONS_JSONL_DESCRIPTOR,
    "accepted_ingress": ACTUAL_MEASUREMENT_DIR_INGRESS_LEDGER_CSV_DESCRIPTOR,
    "process_receipt": ACTUAL_RESERVED_PROCESS_RECEIPT_DESCRIPTOR,
    "container_receipt": ACTUAL_RESERVED_CONTAINER_RECEIPT_DESCRIPTOR}
   for row in ORIGINAL_PLAN_ORDER
 ],
 "sha256": SHA_OF_CANONICAL_UNSIGNED_OBJECT
}
```

The guardian companion path is exactly `$gop/operational_group.v1.json`. Use `payload_with_sha256_v1` and `canonical_json_v1(...) + b'\n'`; receipt-last, exclusive physical commit. Each descriptor is exactly `{path,size_bytes,sha256}`. Binding descriptors may use the exact stock root-relative form; normalize from actual held descriptors, never rebind other paths. Read each original operation document to locate its reserved `measurement_dir`, `native_domain`, `process_receipt`, and `container_receipt`. The pair rows must be in original plan order; repeated arms must not overwrite operation IDs.

Then call these existing stock cold validators with their real default dependencies:

```python
import publication_policy_qualification_execution_closure_v1 as cold
transaction = cold._validate_transaction(root, q / "qualification_input_transaction.v2.receipt.json")
preprocessing, preprocessing_receipt = cold._validate_preprocessing(
    root=root, transaction=transaction,
    contract_path_value=pre / "checkpoint_analytics_preprocessing_contract.v1.json",
    receipt_path_value=pre / "checkpoint_analytics_preprocessing_contract.v1.receipt.json",
    dependencies=cold.DEFAULT_DEPENDENCIES)
runtime, bundles32 = cold._validate_runtime_inputs(
    root=root,
    path_value=q / "bootstrap/qualification-runtime-inputs-v2/qualification-runtime-inputs.materialization.v2.json",
    cells=cold.qualification_pilot_cells_v2(), transaction=transaction)
guardian, authority_bytes, lifecycle_bytes, authority_path, lifecycle_path = cold._validate_guardian(
    root=root, authority_path_value=gev / "service_authority.v1.json",
    lifecycle_path_value=gev / "service_lifecycle.v1.json",
    runtime_socket=runtime["analytics_socket"], preprocessing=preprocessing,
    preprocessing_receipt=preprocessing_receipt, dependencies=cold.DEFAULT_DEPENDENCIES)
accounting = cold.reconcile_operational_capture_binding_v1(
    project_root=root, binding_path=actual_binding_path,
    guardian_authority_path=authority_path, preprocessing_receipt=preprocessing_receipt,
    lifecycle_counters=guardian["_request_counters"], scratch_root=actual_fresh_cold_scratch,
    expected_mode="bounded_native_diagnostic_operational_v1",
    runtime=runtime, runtime_bundles=bundles32)
```

The underscore-prefixed preparation validators are the current internal stock helpers, not independent stable public CLIs. This recipe uses them unchanged to establish the exact inputs required by the public cold reconciler. They validate current transaction/preprocessing authority, all 32 bundle bytes, original retired socket ledger, nonce-bound authenticated stop, lifecycle counters, and expected worker images. The reconciler additionally holds original context/source/model/code pins, validates genuine original engine/CLI/CID custody and transfer chains, derives measured canonical ingress identities only from stock-validated sidecars, reconstructs/replays native decisions, and checks multiplicity and every lifetime request against the guardian journal/counters. No manual ingress coordinate or wire-ID reconstruction is permitted.

The resulting accounting has `original_operation_count=2`, `qualification_cell_count=0`, and `publication_authority=False`. Persist an explicit nonpromoting controller result only after both adapter originals, authenticated clean stop/original guardian returncode, original container quiescence, and cold reconciliation succeed. Failures retain original evidence and stop the pair; they do not mint successful receipts.

For the GPU pair, use a new `$base/gpu` transaction/bootstrap/preprocessing/plan/guardian/runtime-input namespace and fresh `/var/tmp/vbr0930gpu` socket/scratch paths. The original immutable CPU 32-bundle set cannot be edited to activate GPU contexts. Reuse unchanged CURRENT shared patch/parity/code-closure authorities only after revalidation; no second parity collection is needed solely because a separate GPU diagnostic namespace is created. The diagnostic resource becomes `gpu`, and selection comes from the new held two-operation plan. This result still does not replace full qualification, Q4, the 5,600-arm matrix, CI/conformance, storage-factual gates, or OpenSpec archive.

## Source boundaries checked

- `publication_policy_qualification_transaction_v2.py:938–1040`: existing fragment/candidate/bootstrap transaction and receipt-last chain.
- `checkpoint_model_parity_materializer_v4.py:678–755`: complete patch-bound physical refresh and exact supported CLI arguments.
- `publication_operational_stock_operations_v1.py:91–217`: original stock two/37 operation selection, source/worker constructors, exact reservations; `:223–319`: held real request and execution barriers.
- `publication_operational_capture_plan_v1.py:308–325`: immutable original manifest, source inventory, native contexts, guardian context, then index without a self-hash cycle.
- `publication_policy_qualification_runtime_inputs_v2.py:398–418`: canonical socket requirement; `:3013–3347`: live input materialization and immutable 32-bundle commit.
- `checkpoint_gstreamer_analytics_sidecar.py:6687–6761,6840–6890,7038–7124`: exact lifecycle/control CLI, authenticated stop, optional capture activation, original service ownership.
- `publication_benchmark_native_diagnostic_v1.py:53–181`: real original adapter, host telemetry and stock finalization without pair/qualification grant.
- `publication_policy_qualification_execution_closure_v1.py:1327–1882,2095–2280`: stock cold transaction/runtime/guardian validators and original two/37 operational binding reconciliation.
