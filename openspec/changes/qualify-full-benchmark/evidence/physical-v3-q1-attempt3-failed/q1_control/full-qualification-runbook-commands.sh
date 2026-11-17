# shellcheck shell=bash
# Q1 qualification runbook commands (OpenSpec change qualify-full-benchmark, task 6.1).
# Companion of docs/full-qualification-runbook.md. Sourcing this file only defines
# variables and functions; it executes nothing. Each step function runs in its own
# subshell with `set -euo pipefail` and refuses to start when an input receipt is
# missing or an output already exists. Run in WSL bash as uid 1000.

# ---------------------------------------------------------------- fixed values
Q1_COMMIT=4947e35a70fcfd94cf53179f05c021f8fb9dd3d1            # C_Q1'' (Amendments 4-6; attempt 1 used 1112af0b, attempt 2 82c7a62e)
Q1_TAG=qualify_full_benchmark_20261008d
Q1_NS=qfb-20261008d
ROOT=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
# -I is not used: in 3.12 it implies -P and drops scripts/ from sys.path.
PYRUN=("$PY" -B -E -s)
DOCKER=/usr/bin/docker
DOCKER_SOCKET=/run/docker.sock                              # canonical; /var/run is a symlink
A=$ROOT/artifacts
RCPT=$A/$Q1_TAG                                             # build receipts (5.1-5.4)
CTRL=$RCPT/q1_control                                       # Q1 logs, rc files, sha manifests

# Build receipts (inputs of Q1).
PATCH=$RCPT/qualification_image_identity_patch.json
PATCH_SHA=e39e6645dfe531e1649d0f5f630f3840469b815ba940512bc4e7010c789ae351
PARITY=$ROOT/configs/checkpoint_analytics_model_parity.refreshed.v4.$Q1_NS.accepted
EXEC_CONFIG=$ROOT/configs/analytics_execution_layer.refreshed.v4.$Q1_NS.json
BINDING_SET=$RCPT/model_parity_v4/bindings
# Docker engine identity recorded in task 6A.2 (Amendments 4-5); preflight requires equality.
ENGINE_IDENTITY=$RCPT/docker-engine-identity.6A2.v1.json
ENGINE_IDENTITY_SHA=96d7c397e64ad483705caac9c66f2e254bc9230e30ac73d775dc9c161a262151

# Fresh Q1 namespaces (runbook choice; none may exist before step 0).
QUAL=$A/publication_policy_qualification_v2_qfb_20261008d
PREP_PARENT=$A/publication_guardian_inputs_v1_qfb_20261008d
PREP=$PREP_PARENT/preprocessing-contract-v1
CODE_CLOSURE=$CTRL/qualification_execution_code_closure.v1.receipt.json
OPS=$A/publication_operational_capture_v1_qfb_20261008d
CAPTURE_PLAN=$OPS/capture-plan/capture_plan_index.v1.json
GUARDIAN_CONTEXT=$OPS/capture-plan/guardian_capture_context.v1.json
GUARDIAN_OPS=$A/publication_guardian_operational_v1_qfb_20261008d
EVID=$A/publication_guardian_evidence_v1_qfb_20261008d
AUTHORITY=$EVID/service_authority.v1.json
LIFECYCLE=$EVID/service_lifecycle.v1.json
PILOTS=$A/publication_policy_qualification_pilot_v2_qfb_20261008d
CHECKPOINT=$A/publication_policy_qualification_pilot_checkpoint_v2_qfb_20261008d.json
BINDING=$A/publication_operational_execution_binding_v1_qfb_20261008d.json
CLOSURE=$A/publication_policy_qualification_execution_closure_v1_qfb_20261008d
POLICY_INDEX_DIR=$A/publication_policy_qualification_index_v2_qfb_20261008d
RESOURCE_INDEX=$A/full_resource_qualification_index_v1_qfb_20261008d.json
POLICY_PROMOTED=$A/publication_policy_qualification_promoted_qfb_20261008d
RESOURCE_PROMOTED=$A/full_resource_qualification_promoted_qfb_20261008d
HOSTTMP=/var/tmp/vqfb1008d                                  # ext4, short socket paths
RUNTIME_DIR=$HOSTTMP/r
FRONT_SOCKET=$RUNTIME_DIR/a.sock
SCRATCH=$HOSTTMP/s

# Transaction outputs (fixed names in publication_policy_qualification_transaction_v2.py).
TXN=$QUAL/qualification_input_transaction.v2.receipt.json
CAND_INDEX=$QUAL/candidate/checkpoint_policy_qualification_index.v2.json
CAND_MANIFEST=$QUAL/candidate/checkpoint_policy_capability_candidate_manifest.json
CAND_RECEIPT=$QUAL/candidate/checkpoint_policy_qualification_candidate_receipt.json
BOOT_DIR=$QUAL/bootstrap
BOOT_MAPPING=$BOOT_DIR/checkpoint_policy_qualification_bootstrap_mapping.v2.json
BOOT_RECEIPT=$BOOT_DIR/checkpoint_policy_qualification_bootstrap_receipt.v2.json
PREP_CONTRACT=$PREP/checkpoint_analytics_preprocessing_contract.v1.json
PREP_RECEIPT=$PREP/checkpoint_analytics_preprocessing_contract.v1.receipt.json
RUNTIME_RECEIPT=$BOOT_DIR/qualification-runtime-inputs-v2/qualification-runtime-inputs.materialization.v2.json
CLOSURE_RECEIPT=$CLOSURE/qualification_execution_closure.v1.receipt.json
POLICY_INDEX=$POLICY_INDEX_DIR/checkpoint_policy_qualification_index.v2.json

# Guardian bounds = PRODUCTION_*_MINIMUM in checkpoint_gstreamer_analytics_sidecar.py.
MAX_CONNECTIONS=202560
MAX_REQUESTS_PER_CONNECTION=4320000
MAX_TOTAL_REQUESTS=29168640000

# ---------------------------------------------------------------- helpers
q1__die() { printf 'Q1 REFUSED: %s\n' "$*" >&2; return 64; }

q1__absent() {
    local path
    for path in "$@"; do
        if [ -e "$path" ] || [ -L "$path" ]; then q1__die "already exists: $path"; return 64; fi
    done
}

q1__present() {
    local path
    for path in "$@"; do
        if [ ! -f "$path" ] || [ -L "$path" ]; then q1__die "missing receipt: $path"; return 64; fi
    done
}

q1__sha() {
    [ "$(sha256sum "$1" | cut -d ' ' -f 1)" = "$2" ] || { q1__die "SHA256 mismatch: $1"; return 64; }
}

# q1__inputs NAME FILE... : record input SHA256 before a step.
q1__inputs() { local name=$1; shift; q1__present "$@"; sha256sum "$@" > "$CTRL/$name.inputs.sha256"; }

# q1__verify_outputs NAME : re-check the outputs recorded by an earlier step.
q1__verify_outputs() {
    q1__present "$CTRL/$1.outputs.sha256" "$CTRL/$1.rc"
    [ "$(cat "$CTRL/$1.rc")" = 0 ] || { q1__die "step $1 did not finish with rc 0"; return 64; }
    sha256sum --quiet -c "$CTRL/$1.outputs.sha256" || { q1__die "outputs of $1 changed"; return 64; }
}

# q1__run NAME CMD... : one original invocation; logs and rc are exclusive.
q1__run() {
    local name=$1 rc; shift
    q1__absent "$CTRL/$name.stdout.log" "$CTRL/$name.stderr.log" "$CTRL/$name.rc"
    {
        printf 'started_utc=%s boot_id=%s commit=%s\n' "$(date -u +%FT%T.%NZ)" \
            "$(cat /proc/sys/kernel/random/boot_id)" "$(git -C "$ROOT" rev-parse HEAD)"
        printf 'argv=%q ' "$@"; printf '\n'
        printf 'uid=%s gid=%s cwd=%s\n' "$(id -u)" "$(id -g)" "$PWD"
        echo '--- python -VV'; "$PY" -VV
        echo '--- sys.path (-B -E -s; the script directory is prepended at run time)'
        "${PYRUN[@]}" -c 'import json,sys; print(json.dumps(sys.path))'
        echo '--- env (values of secret-like names masked)'
        env | LC_ALL=C sort | sed -E 's/^([^=]*(TOKEN|SECRET|PASS|KEY|CRED|AUTH)[^=]*)=.*/\1=<masked>/I'
    } > "$CTRL/$name.launch.txt"
    set +e
    "$@" > "$CTRL/$name.stdout.log" 2> "$CTRL/$name.stderr.log"
    rc=$?
    set -e
    printf '%s\n' "$rc" > "$CTRL/$name.rc"
    printf 'finished_utc=%s rc=%s\n' "$(date -u +%FT%T.%NZ)" "$rc" >> "$CTRL/$name.launch.txt"
    return "$rc"
}

q1__outputs() { local name=$1; shift; q1__present "$@"; sha256sum "$@" > "$CTRL/$name.outputs.sha256"; }

q1__json() { "${PYRUN[@]}" -c 'import json,sys; v=json.load(open(sys.argv[1])); print(eval(sys.argv[2],{"v":v}))' "$1" "$2"; }

q1__guardian_live() {
    q1__present "$AUTHORITY"
    q1__absent "$CTRL/guardian-status.$1.json"
    "${PYRUN[@]}" "$ROOT/scripts/checkpoint_gstreamer_analytics_sidecar.py" \
        --production-status-authority "$AUTHORITY" > "$CTRL/guardian-status.$1.json"
    # The status reply is the canonical authority; bytes must equal the file (as in g).
    cmp -s "$AUTHORITY" "$CTRL/guardian-status.$1.json" \
        || { q1__die "guardian status authority differs from service_authority.v1.json"; return 64; }
}

# q1_detach STEP_FUNCTION : start a long step in an independent Windows process (as in PR5).
q1_detach() (
    set -euo pipefail
    case "$1" in q1_06_guardian_start|q1_09_owner_execute) ;; *) q1__die "not a detached step: $1";; esac
    q1__present "$CTRL/full-qualification-runbook-commands.sh"
    q1__absent "$CTRL/$1.detach.txt"
    # Same pattern as PR5: no argument contains spaces (Start-Process joins them unquoted).
    powershell.exe -NoProfile -Command "\$p=Start-Process -FilePath wsl.exe -ArgumentList '-u','s-a-balashov','-e','/bin/bash','$CTRL/full-qualification-runbook-commands.sh','$1' -WindowStyle Hidden -PassThru; 'launched_pid='+\$p.Id" \
        | tee "$CTRL/$1.detach.txt"
)

# ---------------------------------------------------------------- step 0
q1_00_preflight() (
    set -euo pipefail
    [ "$(id -u)" = 1000 ] || q1__die "run as uid 1000"
    [ "$(realpath -e "$ROOT")" = "$ROOT" ] || q1__die "root is not canonical"
    [ "$(git -C "$ROOT" rev-parse HEAD)" = "$Q1_COMMIT" ] || q1__die "root HEAD is not C_Q1"
    [ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no -- . ':(exclude)artifacts')" ] \
        || q1__die "tracked source drift outside artifacts/"
    [ "$("${PYRUN[@]}" -c 'import platform; print(platform.python_version())')" = 3.12.3 ] || q1__die "python is not 3.12.3"
    [ "$(stat -f -c %T /var/tmp)" = ext2/ext3 ] || q1__die "/var/tmp is not ext4"
    [ "$(readlink -f "$DOCKER_SOCKET")" = "$DOCKER_SOCKET" ] && [ -S "$DOCKER_SOCKET" ] || q1__die "docker socket"
    q1__sha "$PATCH" "$PATCH_SHA"
    sha256sum --quiet -c "$RCPT/native-a/receipt-file.sha256" "$RCPT/worker_images/receipt-file.sha256" \
        "$RCPT/image_capture/patch-file.sha256"
    q1__sha "$EXEC_CONFIG" 2079f480ceacc83308b4d964c0ddf75559e898e2f07997f47d01fdc717a42316
    q1__sha "$PARITY.yaml" bad2874543baf08732794f6f2dd92d3f106cbdd83a1e3b7dad8e78af62c4405d
    q1__sha "$PARITY.assessment.json" 939215769022d4ba391fe8d7ab017a7214f683dfc350a81d66a50eef05913232
    q1__sha "$PARITY.acceptance_receipt.json" 0c0c786dbb39b4c92a224b12a7a1008427d2d3793a60d9675d60eec508112691
    q1__sha "$BINDING_SET/index.json" dafb90aa5f55198e2eea5cb40a74fad0fb4992e0be1db1c5341bd60c657031e1
    q1__sha "$RCPT/model_parity_v4/acceptance_binding.v4.json" 0a7a453465dc85176fc65eacd651efd2800c5285e6c3e2c13960d97ce45fd8c2
    local image
    for image in $(grep -ho '"image_id": *"sha256:[0-9a-f]\{64\}"' "$RCPT"/runtime_images/*.runtime.freeze.json \
            "$RCPT/worker_images/analytics-worker.freeze.json" | grep -o 'sha256:[0-9a-f]\{64\}' | sort -u); do
        "$DOCKER" image inspect --format '{{.Id}}' "$image" > /dev/null || q1__die "image missing: $image"
    done
    # Amendments 4-5: the engine recorded in task 6A.2, and live runtime/worker images equal to
    # the patch exactly as the transaction checks them (full inspect, worker projection).
    q1__sha "$ENGINE_IDENTITY" "$ENGINE_IDENTITY_SHA"
    "${PYRUN[@]}" -c "import json, subprocess, sys
def info(*argv):
    return json.loads(subprocess.run([sys.argv[2], *argv, '--format', '{{json .}}'], check=True, capture_output=True, text=True).stdout)
version, daemon = info('version'), info('info')
observed = {'platform_name': version['Server'].get('Platform', {}).get('Name'), 'server_version': version['Server']['Version'],
            'api_version': version['Server']['ApiVersion'], 'client_version': version['Client']['Version'],
            'daemon_id': daemon['ID'], 'name': daemon['Name'], 'driver': daemon['Driver'],
            'driver_type': dict(daemon.get('DriverStatus') or []).get('driver-type')}
sys.exit(0 if observed == json.load(open(sys.argv[1]))['identity'] else 3)
" "$ENGINE_IDENTITY" "$DOCKER" \
        || q1__die "docker engine identity differs from task 6A.2"
    (cd "$ROOT" && "${PYRUN[@]}" -c "import json, sys; sys.path.insert(0, 'scripts'); import publication_policy_qualification_fragments_from_authority_v2 as f; f._verify_live_images(json.load(open(sys.argv[1])), docker=sys.argv[2], inspector=f._default_inspect_image)" "$PATCH" "$DOCKER") \
        || q1__die "live images differ from the identity patch"
    q1__absent "$CTRL" "$QUAL" "$PREP_PARENT" "$OPS" "$GUARDIAN_OPS" "$EVID" "$PILOTS" "$CHECKPOINT" \
        "$BINDING" "$CLOSURE" "$POLICY_INDEX_DIR" "$RESOURCE_INDEX" "$POLICY_PROMOTED" "$RESOURCE_PROMOTED" "$HOSTTMP"
    mkdir -m 700 "$CTRL" "$PREP_PARENT" "$HOSTTMP" "$SCRATCH"
    cp "${BASH_SOURCE[0]}" "$CTRL/full-qualification-runbook-commands.sh"
    chmod 0444 "$CTRL/full-qualification-runbook-commands.sh"
    sha256sum "$CTRL/full-qualification-runbook-commands.sh" > "$CTRL/runbook-commands.sha256"
    git -C "$ROOT" status --porcelain > "$CTRL/root-git-status.before.txt"
    printf '0\n' > "$CTRL/q1_00_preflight.rc"
    echo "Q1 preflight passed"
)

# ---------------------------------------------------------------- step 1 (task 6.2, read-only)
q1_01_host_check() (
    set -euo pipefail
    q1__present "$CTRL/q1_00_preflight.rc"
    local out=$CTRL/host-check.before.txt
    q1__absent "$out"
    {
        echo "utc=$(date -u +%FT%T.%NZ) boot_id=$(cat /proc/sys/kernel/random/boot_id)"
        df -B1 / /mnt/c /mnt/e /var/tmp /home
        free -b
        nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv
        echo "compute_apps:"; nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
        echo "containers:"; "$DOCKER" ps -a --no-trunc --format '{{.ID}} {{.Image}} {{.Status}} {{.Names}}'
        echo "processes:"; pgrep -af 'checkpoint_gstreamer_analytics_sidecar|publication_qualification_operational_owner|publication_policy_qualification|run_canonical_systems_study' || true
    } > "$out"
    local volume avail
    for volume in / /mnt/c /mnt/e /var/tmp; do
        avail=$(df -B1 --output=avail "$volume" | tail -n 1 | tr -d ' ')
        [ "$avail" -ge $((20 * 1024 * 1024 * 1024)) ] || q1__die "less than 20 GiB free on $volume: $avail bytes"
    done
    [ -z "$("$DOCKER" ps -aq)" ] || q1__die "foreign containers present"
    ! pgrep -f 'checkpoint_gstreamer_analytics_sidecar|publication_qualification_operational_owner|publication_policy_qualification' > /dev/null \
        || q1__die "foreign VAST processes present"
    echo "host check recorded: $out"
)

# ---------------------------------------------------------------- step 2: inputs + bootstrap
q1_02_transaction() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__present "$CTRL/host-check.before.txt"
    q1__absent "$QUAL"
    q1__inputs q1_02_transaction "$PATCH" "$PARITY.yaml" "$PARITY.assessment.json" "$PARITY.acceptance_receipt.json"
    cd "$ROOT"
    q1__run q1_02_transaction "${PYRUN[@]}" scripts/publication_policy_qualification_transaction_v2.py \
        --project-root "$ROOT" --identity-patch "$PATCH" \
        --accepted-model-parity-manifest "$PARITY.yaml" \
        --accepted-model-parity-assessment "$PARITY.assessment.json" \
        --accepted-model-parity-receipt "$PARITY.acceptance_receipt.json" \
        --output-root "$QUAL" --docker "$DOCKER"
    q1__outputs q1_02_transaction "$TXN" "$CAND_INDEX" "$CAND_MANIFEST" "$CAND_RECEIPT" "$BOOT_MAPPING" "$BOOT_RECEIPT" \
        "$QUAL"/bootstrap/checkpoint_policy_qualification_bootstrap_calibration.*.v2.json \
        "$QUAL"/fragments/*/qualification_fragment.json
)

# ---------------------------------------------------------------- step 3: preprocessing
q1_03_preprocessing() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_02_transaction
    q1__absent "$PREP"
    q1__inputs q1_03_preprocessing "$TXN"
    cd "$ROOT"
    q1__run q1_03_preprocessing "${PYRUN[@]}" scripts/publication_guardian_preprocessing_contract_v1.py \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" --output-dir "$PREP"
    q1__outputs q1_03_preprocessing "$PREP_CONTRACT" "$PREP_RECEIPT"
)

# ---------------------------------------------------------------- step 4: execution code closure
q1_04_code_closure() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_03_preprocessing
    q1__absent "$CODE_CLOSURE"
    cd "$ROOT"
    q1__run q1_04_code_closure "${PYRUN[@]}" scripts/publication_policy_qualification_execution_code_closure_v1.py \
        --project-root "$ROOT" --receipt "$CODE_CLOSURE"
    q1__outputs q1_04_code_closure "$CODE_CLOSURE"
)

# Re-validation of the code closure (used before guardian, runtime inputs and owner).
q1__code_closure_validate() {
    q1__run "code-closure-validate.$1" "${PYRUN[@]}" "$ROOT/scripts/publication_policy_qualification_execution_code_closure_v1.py" \
        --project-root "$ROOT" --receipt "$CODE_CLOSURE" --validate-only
}

# ---------------------------------------------------------------- step 5: capture plan (37)
q1_05_capture_plan() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_02_transaction
    q1__verify_outputs q1_03_preprocessing
    q1__verify_outputs q1_04_code_closure
    q1__absent "$OPS" "$GUARDIAN_OPS"
    cd "$ROOT"
    q1__run q1_05_capture_plan "${PYRUN[@]}" scripts/publication_operational_stock_operations_v1.py \
        --project-root "$ROOT" --output-dir "$OPS" \
        --candidate-index-path "$CAND_INDEX" --candidate-manifest-path "$CAND_MANIFEST" \
        --candidate-receipt-path "$CAND_RECEIPT" --bootstrap-mapping-path "$BOOT_MAPPING" \
        --bootstrap-receipt-path "$BOOT_RECEIPT" --bootstrap-dir "$BOOT_DIR" \
        --transaction-receipt-path "$TXN" --preprocessing-contract-path "$PREP_CONTRACT" \
        --preprocessing-receipt-path "$PREP_RECEIPT" --execution-code-closure-path "$CODE_CLOSURE" \
        --pilot-root "$PILOTS" --guardian-output-dir "$GUARDIAN_OPS" \
        --container-engine-socket "$DOCKER_SOCKET" \
        --mode complete_qualification_operational_identity_v1
    q1__outputs q1_05_capture_plan "$CAPTURE_PLAN" "$GUARDIAN_CONTEXT" \
        "$OPS/capture-plan/original_operations.v1.json" "$OPS/capture-plan/source_plan_inventory.v1.json"
    [ "$(ls "$OPS"/capture-plan/native_context_*.v1.json | wc -l)" = 37 ] || q1__die "capture plan does not hold 37 native contexts"
    [ "$(ls "$OPS"/original-operations/*.original.json | wc -l)" = 37 ] || q1__die "capture plan does not hold 37 originals"
)

# ---------------------------------------------------------------- step 6: guardian (detached)
q1_06_guardian_start() (
    set -euo pipefail
    [ "$(id -u)" = 1000 ] || q1__die "guardian must run as uid 1000"
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_05_capture_plan
    q1__absent "$EVID" "$RUNTIME_DIR" "$GUARDIAN_OPS"
    [ "$(stat -c '%u:%g:%a' "$HOSTTMP")" = 1000:1000:700 ] || q1__die "host tmp custody"
    q1__inputs q1_06_guardian "$EXEC_CONFIG" "$BINDING_SET/index.json" "$CAND_MANIFEST" "$PREP_CONTRACT" \
        "$PREP_RECEIPT" "$GUARDIAN_CONTEXT" "$CODE_CLOSURE"
    q1__code_closure_validate guardian
    cd "$ROOT"
    q1__run q1_06_guardian "${PYRUN[@]}" scripts/checkpoint_gstreamer_analytics_sidecar.py \
        --production-guardian --project-root "$ROOT" --config "$EXEC_CONFIG" \
        --binding-set "$BINDING_SET" --policy-capability-manifest "$CAND_MANIFEST" \
        --preprocessing-contract "$PREP_CONTRACT" --preprocessing-contract-receipt "$PREP_RECEIPT" \
        --runtime-dir "$RUNTIME_DIR" --front-socket "$FRONT_SOCKET" --evidence-root "$EVID" \
        --operational-accounting-context "$GUARDIAN_CONTEXT" \
        --max-connections "$MAX_CONNECTIONS" --max-requests-per-connection "$MAX_REQUESTS_PER_CONNECTION" \
        --max-total-requests "$MAX_TOTAL_REQUESTS"
)

# ---------------------------------------------------------------- step 7: guardian 8/8 (read-only)
q1_07_guardian_ready() (
    set -euo pipefail
    q1__present "$CTRL/q1_06_guardian.launch.txt"
    [ ! -e "$CTRL/q1_06_guardian.rc" ] || q1__die "guardian already exited: rc=$(cat "$CTRL/q1_06_guardian.rc")"
    q1__present "$AUTHORITY"
    [ "$(q1__json "$AUTHORITY" 'v["status"]')" = live_operational_nonpublication ] || q1__die "guardian status"
    [ "$(q1__json "$AUTHORITY" 'v["worker_count"]')" = 8 ] || q1__die "guardian worker_count != 8"
    [ "$(q1__json "$AUTHORITY" 'v["attested_worker_count"]')" = 8 ] || q1__die "guardian attested_worker_count != 8"
    [ -S "$FRONT_SOCKET" ] || q1__die "front socket missing"
    q1__guardian_live ready
    q1__outputs q1_07_guardian_ready "$AUTHORITY"
    printf '0\n' > "$CTRL/q1_07_guardian_ready.rc"
)

# ---------------------------------------------------------------- step 8: runtime inputs (32 bundles)
q1_08_runtime_inputs() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_07_guardian_ready
    q1__guardian_live runtime-inputs
    q1__absent "$BOOT_DIR/qualification-runtime-inputs-v2"
    [ "$(stat -c '%u:%g:%a' "$SCRATCH")" = 1000:1000:700 ] || q1__die "scratch custody"
    q1__code_closure_validate runtime-inputs
    cd "$ROOT"
    q1__run q1_08_runtime_inputs "${PYRUN[@]}" scripts/publication_policy_qualification_runtime_inputs_v2.py \
        --project-root "$ROOT" --candidate-index "$CAND_INDEX" --candidate-manifest "$CAND_MANIFEST" \
        --candidate-receipt "$CAND_RECEIPT" --bootstrap-mapping "$BOOT_MAPPING" \
        --bootstrap-receipt "$BOOT_RECEIPT" --bootstrap-dir "$BOOT_DIR" \
        --qualification-transaction-receipt "$TXN" \
        --container-engine "$DOCKER" --container-engine-socket "$DOCKER_SOCKET" \
        --analytics-socket "$FRONT_SOCKET" --scratch-root "$SCRATCH" \
        --deadline-ms 100 --duration-s 180 --operational-capture-plan "$CAPTURE_PLAN"
    q1__outputs q1_08_runtime_inputs "$RUNTIME_RECEIPT"
)

# ---------------------------------------------------------------- step 9: 37 originals (detached)
q1_09_owner_execute() (
    set -euo pipefail
    [ "$(id -u)" = 1000 ] || q1__die "owner must run as uid 1000"
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_08_runtime_inputs
    q1__guardian_live owner
    q1__absent "$PILOTS" "$CHECKPOINT" "$OPS/process-captures" "$OPS/diagnostics"
    q1__code_closure_validate owner
    cd "$ROOT"
    q1__run q1_09_owner_execute "${PYRUN[@]}" scripts/publication_qualification_operational_owner_v1.py execute \
        --project-root "$ROOT" --capture-plan "$CAPTURE_PLAN" \
        --candidate-index-path "$CAND_INDEX" --candidate-manifest-path "$CAND_MANIFEST" \
        --candidate-receipt-path "$CAND_RECEIPT" --bootstrap-mapping-path "$BOOT_MAPPING" \
        --bootstrap-receipt-path "$BOOT_RECEIPT" --bootstrap-dir "$BOOT_DIR" \
        --transaction-receipt-path "$TXN" \
        --runtime-input-materialization-receipt-path "$RUNTIME_RECEIPT" \
        --guardian-service-authority-path "$AUTHORITY" \
        --preprocessing-contract-path "$PREP_CONTRACT" --preprocessing-contract-receipt-path "$PREP_RECEIPT" \
        --execution-code-closure-receipt-path "$CODE_CLOSURE" \
        --pilot-root "$PILOTS" --checkpoint-path "$CHECKPOINT"
    q1__outputs q1_09_owner_execute "$CHECKPOINT"
)

# Read-only progress view while step 9 runs. Never stops or touches containers.
q1_watch() (
    set -uo pipefail
    date -u +%FT%TZ
    for f in "$CTRL"/q1_06_guardian.rc "$CTRL"/q1_09_owner_execute.rc; do [ -e "$f" ] && echo "$f: $(cat "$f")"; done
    pgrep -af 'checkpoint_gstreamer_analytics_sidecar|publication_qualification_operational_owner' || true
    echo "process captures: $(find "$OPS/process-captures" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)/37"
    "$DOCKER" ps --format '{{.Names}} {{.Status}}'
    tail -n 5 "$CTRL/q1_09_owner_execute.stderr.log" 2>/dev/null || true
)

# ---------------------------------------------------------------- step 10: authenticated stop
q1_10_guardian_stop() (
    set -euo pipefail
    q1__verify_outputs q1_09_owner_execute
    [ ! -e "$CTRL/q1_06_guardian.rc" ] || q1__die "guardian already exited: rc=$(cat "$CTRL/q1_06_guardian.rc")"
    q1__present "$AUTHORITY"
    cd "$ROOT"
    q1__run q1_10_guardian_stop "${PYRUN[@]}" scripts/checkpoint_gstreamer_analytics_sidecar.py \
        --production-stop-authority "$AUTHORITY"
    [ "$(q1__json "$CTRL/q1_10_guardian_stop.stdout.log" 'v["status"]')" = clean_stop_nonpublication ] \
        || q1__die "stop lifecycle is not clean_stop_nonpublication"
)

# ---------------------------------------------------------------- step 11: guardian terminal (read-only)
q1_11_guardian_terminal() (
    set -euo pipefail
    q1__present "$CTRL/q1_10_guardian_stop.rc" "$CTRL/q1_06_guardian.rc" "$LIFECYCLE" "$GUARDIAN_OPS/operational_group.v1.json"
    [ "$(cat "$CTRL/q1_10_guardian_stop.rc")" = 0 ] || q1__die "stop rc != 0"
    [ "$(cat "$CTRL/q1_06_guardian.rc")" = 0 ] || q1__die "guardian rc != 0"
    [ "$(q1__json "$LIFECYCLE" 'v["status"]')" = clean_stop_nonpublication ] || q1__die "lifecycle status"
    # Documented guardian/runtime behavior: every worker and engine container runs
    # with `docker run --rm` and is stopped by its owner, so none remain once the
    # guardian process has exited. Any listed container is an unexpected state =
    # FAILED Q1; it is recorded once and never waited out or retried.
    "$DOCKER" ps -a --no-trunc --format '{{.ID}} {{.Image}} {{.Status}} {{.Names}}' > "$CTRL/containers-after-stop.txt"
    [ ! -s "$CTRL/containers-after-stop.txt" ] || q1__die "containers present after guardian stop: FAILED Q1"
    q1__outputs q1_11_guardian_terminal "$AUTHORITY" "$LIFECYCLE" "$GUARDIAN_OPS/operational_group.v1.json"
    printf '0\n' > "$CTRL/q1_11_guardian_terminal.rc"
)

# ---------------------------------------------------------------- step 12: execution binding
q1_12_owner_bind() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_11_guardian_terminal
    q1__absent "$BINDING"
    cd "$ROOT"
    q1__run q1_12_owner_bind "${PYRUN[@]}" scripts/publication_qualification_operational_owner_v1.py bind \
        --project-root "$ROOT" --capture-plan "$CAPTURE_PLAN" --binding-path "$BINDING"
    q1__outputs q1_12_owner_bind "$BINDING"
)

# ---------------------------------------------------------------- step 13: execution closure (37/8)
q1_13_execution_closure() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_12_owner_bind
    q1__absent "$CLOSURE"
    cd "$ROOT"
    q1__run q1_13_execution_closure "${PYRUN[@]}" scripts/publication_policy_qualification_execution_closure_v1.py \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" \
        --preprocessing-contract "$PREP_CONTRACT" --preprocessing-materialization-receipt "$PREP_RECEIPT" \
        --runtime-input-materialization-receipt "$RUNTIME_RECEIPT" \
        --guardian-service-authority "$AUTHORITY" --guardian-service-lifecycle "$LIFECYCLE" \
        --pilot-root "$PILOTS" --checkpoint "$CHECKPOINT" --output-dir "$CLOSURE" \
        --operational-accounting-binding "$BINDING"
    q1__outputs q1_13_execution_closure "$CLOSURE_RECEIPT"
)

# ---------------------------------------------------------------- step 14: indices
q1_14_indices() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_13_execution_closure
    q1__absent "$POLICY_INDEX_DIR" "$RESOURCE_INDEX"
    cd "$ROOT"
    local fragments=(
        --deepstream-fragment "$QUAL/fragments/deepstream/qualification_fragment.json"
        --savant-fragment "$QUAL/fragments/savant/qualification_fragment.json"
        --openvino-gva-fragment "$QUAL/fragments/openvino_gva/qualification_fragment.json"
        --gstreamer-custom-fragment "$QUAL/fragments/gstreamer_custom/qualification_fragment.json"
    )
    q1__run q1_14_policy_index "${PYRUN[@]}" scripts/publication_policy_qualification_index_v2.py \
        --project-root "$ROOT" --pilot-root "$PILOTS" --output-dir "$POLICY_INDEX_DIR" \
        --execution-closure-receipt "$CLOSURE_RECEIPT" "${fragments[@]}"
    q1__run q1_14_resource_index "${PYRUN[@]}" scripts/full_resource_qualification_index_v1.py \
        --project-root "$ROOT" --pilot-root "$PILOTS" --output-path "$RESOURCE_INDEX" \
        --execution-closure-receipt "$CLOSURE_RECEIPT" "${fragments[@]}"
    q1__outputs q1_14_indices "$POLICY_INDEX" "$RESOURCE_INDEX"
    printf '0\n' > "$CTRL/q1_14_indices.rc"
)

# ---------------------------------------------------------------- step 15: promotion
q1_15_promotion() (
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs q1_14_indices
    q1__absent "$POLICY_PROMOTED" "$RESOURCE_PROMOTED"
    cd "$ROOT"
    q1__run q1_15_policy_promotion "${PYRUN[@]}" scripts/publication_policy_qualification.py \
        --project-root "$ROOT" --index-path "$POLICY_INDEX" --output-dir "$POLICY_PROMOTED"
    q1__run q1_15_resource_promotion "${PYRUN[@]}" scripts/full_resource_qualification.py \
        --project-root "$ROOT" --index-path "$RESOURCE_INDEX" --output-dir "$RESOURCE_PROMOTED"
    q1__outputs q1_15_promotion \
        "$POLICY_PROMOTED/checkpoint_policy_capability_manifest.json" \
        "$POLICY_PROMOTED/checkpoint_policy_calibration_mapping.json" \
        "$POLICY_PROMOTED/checkpoint_policy_qualification_receipt.json" \
        "$RESOURCE_PROMOTED/checkpoint_full_resource_capability_manifest.json" \
        "$RESOURCE_PROMOTED/checkpoint_full_resource_qualification_receipt.json"
    printf '0\n' > "$CTRL/q1_15_promotion.rc"
)

# ---------------------------------------------------------------- step 16: final host observation
q1_16_host_after() (
    set -euo pipefail
    local out=$CTRL/host-check.after.txt
    q1__absent "$out"
    {
        echo "utc=$(date -u +%FT%T.%NZ) boot_id=$(cat /proc/sys/kernel/random/boot_id)"
        df -B1 /mnt/c /mnt/e /var/tmp /home
        echo "containers:"; "$DOCKER" ps -a --no-trunc --format '{{.ID}} {{.Image}} {{.Status}} {{.Names}}'
        echo "processes:"; pgrep -af 'checkpoint_gstreamer_analytics_sidecar|publication_qualification_operational_owner|publication_policy_qualification' || true
    } > "$out"
    git -C "$ROOT" status --porcelain > "$CTRL/root-git-status.after.txt"
    [ "$(git -C "$ROOT" rev-parse HEAD)" = "$Q1_COMMIT" ] || q1__die "root HEAD moved"
    echo "recorded: $out"
)

# ---------------------------------------------------------------- detached entry
# Only when executed as `bash <file> <step>` (q1_detach); never when sourced.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-}" in
        q1_06_guardian_start|q1_09_owner_execute) "$1" ;;
        *) printf 'usage: bash %s q1_06_guardian_start|q1_09_owner_execute\n' "$0" >&2; exit 64 ;;
    esac
fi
