#!/usr/bin/env bash
# Amendment 7, 6D.7: root C_B''' -> C_Q1''' (WSL git). Untracked configs/*qfb-20261008e* written by parity
# are moved into the tag dir first and must equal the committed copies byte for byte.
set -euo pipefail
target=$1; out=$2
root=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
keep=$root/artifacts/qualify_full_benchmark_20261008e/untracked-configs-before-cq1
[[ "$(realpath -e "$root")" == "$root" && -d "$out" && ! -e "$keep" ]]
cd "$root"
[[ -z "$(git status --porcelain --untracked-files=no)" ]]
git status --porcelain > "$out/root-git-status.before.txt"
git status --porcelain --untracked-files=no -- . ':(exclude)artifacts' > "$out/tracked-drift-outside-artifacts.before.txt"
before=$(git rev-parse HEAD)
git fetch https://github.com/lordcoudy/VAST codex/qualify-full-benchmark > "$out/fetch.log" 2>&1
git merge-base --is-ancestor "$before" "$target"
git diff --name-only "$before" "$target" > "$out/changed-paths.txt"
git diff --name-only --diff-filter=A "$before" "$target" -- artifacts > "$out/added-tracked-artifacts.txt"
while read -r p; do [[ ! -e "$p" ]] || { echo "exists: $p" >&2; exit 4; }; done < "$out/added-tracked-artifacts.txt"
mkdir -m 700 "$keep"
(cd configs && sha256sum *qfb-20261008e*) > "$out/untracked-configs.sha256"
mv configs/*qfb-20261008e* "$keep/"
git checkout -q --detach "$target"
[[ "$(git rev-parse HEAD)" == "$target" ]]
(cd configs && sha256sum *qfb-20261008e*) > "$out/committed-configs.sha256"
cmp "$out/untracked-configs.sha256" "$out/committed-configs.sha256"
git status --porcelain > "$out/root-git-status.after.txt"
git status --porcelain --untracked-files=no -- . ':(exclude)artifacts' > "$out/tracked-drift-outside-artifacts.after.txt"
[[ ! -s "$out/tracked-drift-outside-artifacts.before.txt" && ! -s "$out/tracked-drift-outside-artifacts.after.txt" ]]
echo "root moved $before -> $target; configs equal"
