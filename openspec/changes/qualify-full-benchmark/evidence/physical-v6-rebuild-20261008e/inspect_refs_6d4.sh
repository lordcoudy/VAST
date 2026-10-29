#!/usr/bin/env bash
# Amendment 7, 6D.4: raw read-only docker image inspect of every reference in the 6C list.
set -euo pipefail
E=$(cd "$(dirname "$0")" && pwd)
old=$E/../physical-v4-rebuild-20261008d/build_prep/inspect
for f in "$old"/*.inspect.json; do
  ref=$(basename "$f" .inspect.json | sed 's#__#/#; s#__#:#')
  docker image inspect "$ref" > "$E/build_prep/inspect/$(basename "$f")"
done
ls "$E/build_prep/inspect" | wc -l
