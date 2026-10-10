#!/usr/bin/env bash
# Read-only part of q1_00_preflight (attempt 4): every check up to and including q1__absent; no mkdir/cp/chmod.
source /mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/docs/full-qualification-runbook-commands.sh
q1_00_preflight_readonly() (
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
    q1__sha "$EXEC_CONFIG" 788908832d73678b94c9c8e6cdf67858091e3f456e3de998cbe8d1463f5bc605
    q1__sha "$PARITY.yaml" c125e54be4a3ec701c8840285fc0cafbf7549de29db27fd3029f1abbd2d26dbe
    q1__sha "$PARITY.assessment.json" aea90088d3c60f35a5925004ed420ca094ad72bf68209022d02f1240fdfbefa1
    q1__sha "$PARITY.acceptance_receipt.json" de62d6f97b966c38d3a1f6394394e087c488837ac17b2fa303a429572df3cb6a
    q1__sha "$BINDING_SET/index.json" 45ce0c4a43cf7de91a9fd14902fe0047bb35fb78f5d2e2dc8d70062bc43b0d30
    q1__sha "$RCPT/model_parity_v4/acceptance_binding.v4.json" 639644170f3697655f7e119e2dd9f54b4a729f13e094009bfca3e2cb11c11146
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
    echo "READONLY PREFLIGHT PASS"
)
q1_00_preflight_readonly
