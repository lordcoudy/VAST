#!/usr/bin/env bash
# Amendment 8, 6E.3: move the frozen root to C_B'''' with WSL git (Amendment 4 procedure;
# recipe: root_move_v1.sh of 6D.3 plus the attempt-4 code closure check). usage: root_move_v2.sh <target-sha> <out-dir> <expected-changed-receipt-bound-file>
set -euo pipefail
target=$1; out=$2; expected=$3
root=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
python=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
engine=$root/artifacts/qualify_full_benchmark_20261008e/docker-engine-identity.6A2.v1.json
lists=$(dirname "$0")/root-move
[[ "$(realpath -e "$root")" == "$root" && -d "$out" && -f "$expected" ]]
cd "$root"
[[ -z "$(git status --porcelain --untracked-files=no)" ]] || { echo "tracked changes in root" >&2; exit 3; }
git status --porcelain > "$out/root-git-status.before.txt"
git status --porcelain --untracked-files=no -- . ':(exclude)artifacts' > "$out/tracked-drift-outside-artifacts.before.txt"
before=$(git rev-parse HEAD)
git fetch https://github.com/lordcoudy/VAST codex/qualify-full-benchmark > "$out/fetch.log" 2>&1
git cat-file -e "$target^{commit}"
git merge-base --is-ancestor "$before" "$target"
git diff --name-only "$before" "$target" > "$out/changed-paths.txt"
git diff --name-only --diff-filter=A "$before" "$target" -- artifacts > "$out/added-tracked-artifacts.txt"
while read -r p; do [[ -e "$p" ]] && { echo "tracked target path already exists untracked: $p" >&2; exit 4; }; done < "$out/added-tracked-artifacts.txt"
cat "$lists/receipt-bound-inputs.txt" "$lists/receipt-bound-extra-inputs.txt" | sort -u > "$out/receipt-bound-all.txt"
grep -Fxf "$out/receipt-bound-all.txt" "$out/changed-paths.txt" > "$out/changed-receipt-bound-inputs.txt" || true
cmp "$out/changed-receipt-bound-inputs.txt" "$expected"
# Files pinned (path, bytes, physical identity) by the attempt-4 execution code closure stay untouched.
"$python" -c "import json,sys; [print(p) for p in sorted(s['path'] for s in json.load(open(sys.argv[1]))['project_sources'])]" \
    artifacts/qualify_full_benchmark_20261008e/q1_control/qualification_execution_code_closure.v1.receipt.json > "$out/attempt4-code-closure-sources.txt"
[[ "$(wc -l < "$out/attempt4-code-closure-sources.txt")" == 90 ]]
grep -Fxf "$out/attempt4-code-closure-sources.txt" "$out/changed-paths.txt" > "$out/changed-closure-sources.txt" || true
[[ ! -s "$out/changed-closure-sources.txt" ]] || { echo "closure-pinned source changes" >&2; exit 6; }
"$python" -c "import json,subprocess,sys; from datetime import datetime,timezone
o={k: subprocess.run(['docker','info' if k=='i' else 'version','--format','{{json .}}'],check=True,capture_output=True,text=True).stdout for k in 'iv'}
v,i=json.loads(o['v']),json.loads(o['i'])
obs={'platform_name':v['Server'].get('Platform',{}).get('Name'),'server_version':v['Server']['Version'],'api_version':v['Server']['ApiVersion'],'client_version':v['Client']['Version'],'daemon_id':i['ID'],'name':i['Name'],'driver':i['Driver'],'driver_type':dict(i.get('DriverStatus') or []).get('driver-type')}
eq=obs==json.load(open(sys.argv[1]))['identity']
json.dump({'observed_at_utc':datetime.now(timezone.utc).isoformat(),'boot_id':open('/proc/sys/kernel/random/boot_id').read().strip(),'observed':obs,'equal':eq},open(sys.argv[2],'w'),indent=1); sys.exit(0 if eq else 5)" "$engine" "$out/engine-identity-check.v1.json"
git checkout -q --detach "$target"
[[ "$(git rev-parse HEAD)" == "$target" ]]
git status --porcelain > "$out/root-git-status.after.txt"
git status --porcelain --untracked-files=no -- . ':(exclude)artifacts' > "$out/tracked-drift-outside-artifacts.after.txt"
[[ ! -s "$out/tracked-drift-outside-artifacts.before.txt" && ! -s "$out/tracked-drift-outside-artifacts.after.txt" ]]
df -B1 --output=target,avail / /mnt/c /mnt/e /var/tmp > "$out/disk.txt"
echo "root moved $before -> $target"
