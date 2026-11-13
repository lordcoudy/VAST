#!/usr/bin/env bash
# Amendment 7, 6D.4: byte copies of native/worker receipts and the 6A.2 engine record into tag 20261008e.
set -euo pipefail
root=/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a
old=$root/artifacts/qualify_full_benchmark_20261008d
new=$root/artifacts/qualify_full_benchmark_20261008e
out=$1
[[ "$(realpath -e "$root")" == "$root" && ! -e "$new" && -d "$out" ]]
cd "$old"
sha256sum native-a/native_probe.freeze.json native-b/native_probe.freeze.json worker_images/analytics-worker.freeze.json docker-engine-identity.6A2.v1.json > "$out/copy.source.sha256"
mkdir -m 700 "$new" "$new/native-a" "$new/native-b" "$new/worker_images"
for f in native-a/native_probe.freeze.json native-b/native_probe.freeze.json worker_images/analytics-worker.freeze.json docker-engine-identity.6A2.v1.json; do
  cp "$old/$f" "$new/$f"
done
cd "$new"
sha256sum native-a/native_probe.freeze.json native-b/native_probe.freeze.json worker_images/analytics-worker.freeze.json docker-engine-identity.6A2.v1.json > "$out/copy.target.sha256"
cmp "$out/copy.source.sha256" "$out/copy.target.sha256"
sha256sum "$new/native-a/native_probe.freeze.json" > native-a/receipt-file.sha256
sha256sum "$new/worker_images/analytics-worker.freeze.json" > worker_images/receipt-file.sha256
# native3 / worker2 live IDs equal the receipts (read-only inspect).
python3 - "$new" "$out/native-worker-live-ids.v1.json" <<'PY'
import json, re, subprocess, sys
new, out = sys.argv[1], sys.argv[2]
ids = sorted(set(re.findall(r'"image_id": *"(sha256:[0-9a-f]{64})"',
    open(f"{new}/native-a/native_probe.freeze.json").read() + open(f"{new}/worker_images/analytics-worker.freeze.json").read())))
rows = [{"image_id": i, "live_id": subprocess.run(["docker", "image", "inspect", "--format", "{{.Id}}", i],
         check=True, capture_output=True, text=True).stdout.strip()} for i in ids]
ok = all(r["image_id"] == r["live_id"] for r in rows)
json.dump({"images": rows, "count": len(rows), "equal": ok}, open(out, "w"), indent=1)
print(len(rows), ok); sys.exit(0 if ok else 3)
PY
