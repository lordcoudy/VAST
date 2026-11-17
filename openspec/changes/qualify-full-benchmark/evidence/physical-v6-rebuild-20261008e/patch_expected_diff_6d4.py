"""Amendment 7, 6D.4: classify every leaf difference between the 20261008d and 20261008e identity patches.

Allowed: (a) the tag in string values (20261008d -> 20261008e); (b) any value under the
DeepStream runtime image; (c) hashes that bind those (receipt/patch/runtime_images digests).
Everything else is unexpected. usage: patch_expected_diff_6d4.py <old> <new> <out.json>
"""
import json, sys

old, new = (json.load(open(p)) for p in sys.argv[1:3])

def leaves(value, path=()):
    if isinstance(value, dict):
        for key, item in value.items():
            yield from leaves(item, path + (str(key),))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from leaves(item, path + (str(index),))
    else:
        yield path, value

a, b = dict(leaves(old)), dict(leaves(new))
rows = []
for path in sorted(set(a) | set(b)):
    x, y = a.get(path, "<absent>"), b.get(path, "<absent>")
    if x == y:
        continue
    joined = "/".join(path)
    if isinstance(x, str) and isinstance(y, str) and x.replace("20261008d", "20261008e") == y:
        kind = "tag"
    elif "deepstream" in joined:
        kind = "deepstream"
    elif any(word in joined for word in ("receipt_sha256", "patch_sha256", "runtime_images", "sha256")):
        kind = "binding_hash"
    else:
        kind = "unexpected"
    rows.append({"path": joined, "kind": kind, "old": x, "new": y})
summary = {k: sum(r["kind"] == k for r in rows) for k in ("tag", "deepstream", "binding_hash", "unexpected")}
json.dump({"summary": summary, "rows": rows}, open(sys.argv[3], "w"), indent=1)
print(json.dumps(summary))
for r in rows:
    if r["kind"] in ("binding_hash", "unexpected"):
        print(r["kind"], r["path"])
sys.exit(0 if summary["unexpected"] == 0 else 3)
