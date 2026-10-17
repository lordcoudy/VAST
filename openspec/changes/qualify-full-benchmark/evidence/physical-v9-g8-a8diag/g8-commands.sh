# shellcheck shell=bash
# Amendment 8, task 6E.4: non-qualifying gate G8. F1 policy/resource indices on the outputs of
# FAILED Q1 attempt 4 into diagnostic namespaces `*_a8diag`, then both assessments without
# promotion receipts. Sourcing defines functions only. Each step is one plain top-level command
# (runbook helpers, errexit probe); logs, rc and SHA256 in $CTRL = <tag>/a8diag_control.
# Run in WSL bash as uid 1000:  bash g8-commands.sh g8_all  (or source and call steps one by one).

# The root's own runbook at C_B'''' (attempt-4 constants: QUAL, PILOTS, CLOSURE_RECEIPT, TXN, ...).
source /mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/docs/full-qualification-runbook-commands.sh

G8_COMMIT=ad9bda3d6eed425fae01ba1cd65a9907ba32df8a                                       # C_B'''' (Amendment 8)
ATTEMPT4_CTRL=$RCPT/q1_control
CTRL=$RCPT/a8diag_control
DIAG_POLICY_INDEX_DIR=$A/publication_policy_qualification_index_v2_qfb_20261008e_a8diag
DIAG_POLICY_INDEX=$DIAG_POLICY_INDEX_DIR/checkpoint_policy_qualification_index.v2.json
DIAG_RESOURCE_INDEX=$A/full_resource_qualification_index_v1_qfb_20261008e_a8diag.json
F1=scripts/publication_qualification_promotion_v2.py

# Attempt-4 transaction and closure outputs are unchanged since attempt 4 (read-only check).
g8__attempt4_unchanged() {
    local step
    for step in q1_02_transaction q1_13_execution_closure; do
        sha256sum --quiet -c "$ATTEMPT4_CTRL/$step.outputs.sha256" || { q1__die "attempt-4 outputs of $step changed"; return 64; }
    done
}

g8_00_prepare() (
    q1__require_errexit
    set -euo pipefail
    [ "$(id -u)" = 1000 ] || q1__die "run as uid 1000"
    [ "$(git -C "$ROOT" rev-parse HEAD)" = "$G8_COMMIT" ] || q1__die "root HEAD is not C_B''''"
    [ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no -- . ':(exclude)artifacts')" ] \
        || q1__die "tracked source drift outside artifacts/"
    q1__present "$TXN" "$CLOSURE_RECEIPT"
    g8__attempt4_unchanged
    q1__absent "$CTRL" "$DIAG_POLICY_INDEX_DIR" "$DIAG_RESOURCE_INDEX"
    mkdir -m 700 "$CTRL"
    cp "${BASH_SOURCE[0]}" "$CTRL/g8-commands.sh"
    cp "$ROOT/docs/full-qualification-runbook-commands.sh" "$CTRL/full-qualification-runbook-commands.sh"
    chmod 0444 "$CTRL/g8-commands.sh" "$CTRL/full-qualification-runbook-commands.sh"
    sha256sum "$CTRL/g8-commands.sh" "$CTRL/full-qualification-runbook-commands.sh" > "$CTRL/commands.sha256"
    git -C "$ROOT" status --porcelain > "$CTRL/root-git-status.before.txt"
    echo "G8 prepared"
    printf '0\n' > "$CTRL/g8_00_prepare.rc"
)

g8_01_policy_index() (
    q1__require_errexit
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__present "$CTRL/g8_00_prepare.rc"
    g8__attempt4_unchanged
    q1__absent "$DIAG_POLICY_INDEX_DIR"
    cd "$ROOT"
    q1__run g8_01_policy_index "${PYRUN[@]}" "$F1" policy-index \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" --pilot-root "$PILOTS" \
        --output-dir "$DIAG_POLICY_INDEX_DIR" --execution-closure-receipt "$CLOSURE_RECEIPT" "${FRAGMENT_ARGS[@]}"
    q1__outputs g8_01_policy_index "$DIAG_POLICY_INDEX"
)

g8_02_resource_index() (
    q1__require_errexit
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs g8_01_policy_index
    g8__attempt4_unchanged
    q1__absent "$DIAG_RESOURCE_INDEX"
    cd "$ROOT"
    q1__run g8_02_resource_index "${PYRUN[@]}" "$F1" resource-index \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" --pilot-root "$PILOTS" \
        --output-path "$DIAG_RESOURCE_INDEX" --execution-closure-receipt "$CLOSURE_RECEIPT" "${FRAGMENT_ARGS[@]}"
    q1__outputs g8_02_resource_index "$DIAG_RESOURCE_INDEX"
)

# Assessments write nothing; stdout holds the full assessment, rc 78 when not passed.
g8_03_policy_assess() (
    q1__require_errexit
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs g8_02_resource_index
    q1__verify_outputs g8_01_policy_index
    cd "$ROOT"
    q1__run g8_03_policy_assess "${PYRUN[@]}" "$F1" policy-assess \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" --index-path "$DIAG_POLICY_INDEX" \
        "${FRAGMENT_ARGS[@]}"
    q1__outputs g8_03_policy_assess "$CTRL/g8_03_policy_assess.stdout.log"
)

g8_04_resource_assess() (
    q1__require_errexit
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs g8_03_policy_assess
    q1__verify_outputs g8_02_resource_index
    cd "$ROOT"
    q1__run g8_04_resource_assess "${PYRUN[@]}" "$F1" resource-assess \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" --index-path "$DIAG_RESOURCE_INDEX" \
        "${FRAGMENT_ARGS[@]}"
    q1__outputs g8_04_resource_assess "$CTRL/g8_04_resource_assess.stdout.log"
    git -C "$ROOT" status --porcelain > "$CTRL/root-git-status.after.txt"
    echo "G8 passed"
)

# Detached driver: plain top-level commands under errexit; the first failing step stops G8.
g8_all() {
    set -e
    g8_01_policy_index
    g8_02_resource_index
    g8_03_policy_assess
    g8_04_resource_assess
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-}" in
        g8_all) g8_all ;;
        *) printf 'usage: bash %s g8_all\n' "$0" >&2; exit 64 ;;
    esac
fi
