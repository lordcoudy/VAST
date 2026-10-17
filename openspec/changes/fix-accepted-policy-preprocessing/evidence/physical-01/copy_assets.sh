#!/usr/bin/env bash
# Reviewed immutable base inputs only. No campaign or historical acceptance outputs.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/recipe_common.sh"
reviewed_sha="${1:?reviewed asset catalog SHA256 required}"
expected_commit="${2:?exact frozen repair commit required}"
assert_frozen_root "$expected_commit"
[[ "$(realpath -e "$SOURCE_ROOT")" == "$SOURCE_ROOT" ]]
catalog="$RECIPE_DIR/asset-copy.inventory.v1.json"
assert_plain_file "$catalog"
[[ "$reviewed_sha" =~ ^[0-9a-f]{64}$ ]]
[[ "$(sha256sum "$catalog" | cut -d ' ' -f 1)" == "$reviewed_sha" ]]

mapfile -t rows < <("$PY" -B - "$catalog" "$SOURCE_ROOT" "$ROOT" <<'PY'
import collections, json, re, sys
from pathlib import PurePosixPath
catalog = json.load(open(sys.argv[1], encoding="utf-8"))
assert catalog["source_root"] == sys.argv[2] and catalog["destination_root"] == sys.argv[3]
files = catalog["files"]
assert len(files) == 37
assert collections.Counter(row["kind"] for row in files) == {
    "base_receipt": 3, "kpp_corpus": 10, "omz": 8, "parity_model": 16,
}
assert len({row["destination_relative"] for row in files}) == len(files)
for row in files:
    assert set(row) == {"kind", "source_relative", "destination_relative", "size_bytes", "sha256"}
    for field in ("source_relative", "destination_relative"):
        value = row[field]
        assert re.fullmatch(r"[A-Za-z0-9_.\-/]+", value)
        path = PurePosixPath(value)
        assert not path.is_absolute() and ".." not in path.parts and str(path) == value
    assert type(row["size_bytes"]) is int and row["size_bytes"] > 0
    assert re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
    src, dst = row["source_relative"], row["destination_relative"]
    if row["kind"] == "base_receipt":
        assert src.removeprefix("artifacts/qualify_full_benchmark_20261008e/") in {
            "native-a/native_probe.freeze.json", "native-b/native_probe.freeze.json",
            "worker_images/analytics-worker.freeze.json",
        }
        assert src.startswith("artifacts/qualify_full_benchmark_20261008e/")
        assert dst == src.replace("artifacts/qualify_full_benchmark_20261008e/",
                                 "artifacts/accepted_policy_repair_20261011a/", 1)
    else:
        assert src == dst
        prefix = {"omz": "models/openvino/public/intel/", "parity_model": "models/parity/",
                  "kpp_corpus": "data/videos/kpp/kpp_iss_publication_v3/"}[row["kind"]]
        assert src.startswith(prefix)
for row in files:
    print("\t".join(str(row[key]) for key in
                    ("source_relative", "destination_relative", "size_bytes", "sha256")))
PY
)
[[ "${#rows[@]}" == 37 ]]

# Preflight the entire catalog before the first copy, including existing target parents.
for row in "${rows[@]}"; do
  IFS=$'\t' read -r src_rel dst_rel bytes sha <<< "$row"
  src="$SOURCE_ROOT/$src_rel"; dst="$ROOT/$dst_rel"
  assert_plain_file "$src"
  [[ "$src" == "$SOURCE_ROOT/"* && "$dst" == "$ROOT/"* ]]
  [[ ! -e "$dst" && ! -L "$dst" && "$(realpath -m "$dst")" == "$dst" ]]
  [[ "$(stat -c %s "$src")" == "$bytes" ]]
  [[ "$(sha256sum "$src" | cut -d ' ' -f 1)" == "$sha" ]]
done
control="$BASE/asset-copy-control"
[[ ! -e "$control" ]]
mkdir -p "$BASE"
mkdir -m 700 "$control"
printf '%s\n' "$expected_commit" > "$control/expected-commit.txt"
printf '%s\n' "$reviewed_sha" > "$control/reviewed-catalog.sha256"
for row in "${rows[@]}"; do
  IFS=$'\t' read -r src_rel dst_rel bytes sha <<< "$row"
  src="$SOURCE_ROOT/$src_rel"; dst="$ROOT/$dst_rel"
  mkdir -p "$(dirname "$dst")"
  [[ "$(realpath -e "$(dirname "$dst")")" == "$(dirname "$dst")" ]]
  [[ ! -e "$dst" && ! -L "$dst" ]]
  cp --no-clobber --reflink=never -- "$src" "$dst"
  assert_plain_file "$dst"
  [[ "$(stat -c %s "$dst")" == "$bytes" ]]
  [[ "$(sha256sum "$src" | cut -d ' ' -f 1)" == "$sha" ]]
  [[ "$(sha256sum "$dst" | cut -d ' ' -f 1)" == "$sha" ]]
  printf '%s  %s\n' "$sha" "$dst_rel" >> "$control/copied-files.sha256"
done
cmp "$NATIVE" "$BASE/native-b/native_probe.freeze.json"
assert_frozen_root "$expected_commit"
printf '37 verified base assets copied; campaign evidence was not copied.\n'
