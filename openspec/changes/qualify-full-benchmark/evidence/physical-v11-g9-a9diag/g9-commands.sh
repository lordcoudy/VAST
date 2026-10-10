# shellcheck shell=bash
# Amendment 9, task 6F.4: non-qualifying gate G9. F1 policy-assess (with the F5 policy pilot
# validator) and resource-assess on the G8 indices `*_a8diag` of attempt-4 outputs; no promotion
# receipts. Sourcing defines functions only. Each step is one plain top-level command (runbook
# helpers, errexit probe); logs, rc and SHA256 in $CTRL = <tag>/a9diag_control.
# Run in WSL bash as uid 1000:  bash g9-commands.sh g9_all  (or source and call steps one by one).
# Recipe: g8-commands.sh of 6E.4 (index steps dropped, G8 index outputs re-verified instead).

# The root's own runbook at C_B''''' (attempt-4 constants: QUAL, PILOTS, CLOSURE_RECEIPT, TXN, ...).
source /mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/docs/full-qualification-runbook-commands.sh

G9_COMMIT=d1a78805dd41f9f946e3f6c4ca673bfeced228b5                                       # C_B''''' (Amendment 9)
ATTEMPT4_CTRL=$RCPT/q1_control
G8_CTRL=$RCPT/a8diag_control
CTRL=$RCPT/a9diag_control
DIAG_POLICY_INDEX=$A/publication_policy_qualification_index_v2_qfb_20261008e_a8diag/checkpoint_policy_qualification_index.v2.json
DIAG_RESOURCE_INDEX=$A/full_resource_qualification_index_v1_qfb_20261008e_a8diag.json
F1=scripts/publication_qualification_promotion_v2.py

# Attempt-4 transaction/closure outputs and the G8 indices are unchanged (read-only check).
g9__inputs_unchanged() {
    local manifest
    for manifest in "$ATTEMPT4_CTRL/q1_02_transaction.outputs.sha256" "$ATTEMPT4_CTRL/q1_13_execution_closure.outputs.sha256" \
            "$G8_CTRL/g8_01_policy_index.outputs.sha256" "$G8_CTRL/g8_02_resource_index.outputs.sha256"; do
        sha256sum --quiet -c "$manifest" || { q1__die "inputs changed: $manifest"; return 64; }
    done
}

g9_00_prepare() (
    q1__require_errexit
    set -euo pipefail
    [ "$(id -u)" = 1000 ] || q1__die "run as uid 1000"
    [ "$(git -C "$ROOT" rev-parse HEAD)" = "$G9_COMMIT" ] || q1__die "root HEAD is not C_B'''''"
    [ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no -- . ':(exclude)artifacts')" ] \
        || q1__die "tracked source drift outside artifacts/"
    q1__present "$TXN" "$CLOSURE_RECEIPT" "$DIAG_POLICY_INDEX" "$DIAG_RESOURCE_INDEX"
    g9__inputs_unchanged
    q1__absent "$CTRL"
    mkdir -m 700 "$CTRL"
    cp "${BASH_SOURCE[0]}" "$CTRL/g9-commands.sh"
    cp "$ROOT/docs/full-qualification-runbook-commands.sh" "$CTRL/full-qualification-runbook-commands.sh"
    chmod 0444 "$CTRL/g9-commands.sh" "$CTRL/full-qualification-runbook-commands.sh"
    sha256sum "$CTRL/g9-commands.sh" "$CTRL/full-qualification-runbook-commands.sh" "$ROOT/$F1" > "$CTRL/commands.sha256"
    git -C "$ROOT" status --porcelain > "$CTRL/root-git-status.before.txt"
    echo "G9 prepared"
    printf '0\n' > "$CTRL/g9_00_prepare.rc"
)

# Assessments write nothing; stdout holds the full assessment, rc 78 when not passed.
g9_01_policy_assess() (
    q1__require_errexit
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__present "$CTRL/g9_00_prepare.rc"
    g9__inputs_unchanged
    cd "$ROOT"
    q1__run g9_01_policy_assess "${PYRUN[@]}" "$F1" policy-assess \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" --index-path "$DIAG_POLICY_INDEX" \
        "${FRAGMENT_ARGS[@]}"
    q1__outputs g9_01_policy_assess "$CTRL/g9_01_policy_assess.stdout.log"
)

g9_02_resource_assess() (
    q1__require_errexit
    set -euo pipefail
    export TMPDIR=/var/tmp
    q1__verify_outputs g9_01_policy_assess
    g9__inputs_unchanged
    cd "$ROOT"
    q1__run g9_02_resource_assess "${PYRUN[@]}" "$F1" resource-assess \
        --project-root "$ROOT" --qualification-transaction-receipt "$TXN" --index-path "$DIAG_RESOURCE_INDEX" \
        "${FRAGMENT_ARGS[@]}"
    q1__outputs g9_02_resource_assess "$CTRL/g9_02_resource_assess.stdout.log"
    git -C "$ROOT" status --porcelain > "$CTRL/root-git-status.after.txt"
    echo "G9 passed"
)

# Detached driver: plain top-level commands under errexit; the first failing step stops G9.
g9_all() {
    set -e
    g9_01_policy_assess
    g9_02_resource_assess
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    case "${1:-}" in
        g9_all) g9_all ;;
        *) printf 'usage: bash %s g9_all\n' "$0" >&2; exit 64 ;;
    esac
fi
