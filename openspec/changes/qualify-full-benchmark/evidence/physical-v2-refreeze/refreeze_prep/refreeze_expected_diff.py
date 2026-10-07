"""Amendment 4, 6A.3: check that the re-freeze changed only the expected fields."""
import json, sys

ROOT = "/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/"
OLD_TAG, NEW_TAG = "qualify_full_benchmark_20261007a", "qualify_full_benchmark_20261008b"
OLD, NEW = ROOT + OLD_TAG, ROOT + NEW_TAG
SYSTEMS = ("deepstream", "savant", "openvino_gva", "gstreamer_custom")
problems, notes = [], []


def load(p):
    return json.load(open(p))


def diff(a, b, path=""):
    """Yield dotted paths where a and b differ (leaf level)."""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                yield f"{path}.{k}"
            else:
                yield from diff(a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        for i, (x, y) in enumerate(zip(a, b)):
            yield from diff(x, y, f"{path}[{i}]")
    elif a != b:
        yield path


def tag_only(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.replace(OLD_TAG, NEW_TAG) == b and a != b


def check(label, a, b, allowed_value_change, allowed_tag_change):
    for p in diff(a, b):
        va, vb = a, b
        try:
            for part in p.replace("[", ".[").split(".")[1:]:
                if part.startswith("["):
                    idx = int(part[1:-1]); va, vb = va[idx], vb[idx]
                else:
                    va, vb = va[part], vb[part]
        except (KeyError, TypeError):
            problems.append(f"{label}{p}: key added/removed"); continue
        if any(p == x or p.startswith(x + ".") for x in allowed_value_change):
            notes.append(f"{label}{p}: changed (allowed)")
        elif any(p == x for x in allowed_tag_change) and tag_only(va, vb):
            notes.append(f"{label}{p}: tag-only path change (allowed)")
        else:
            problems.append(f"{label}{p}: {str(va)[:80]!r} -> {str(vb)[:80]!r}")


for s in SYSTEMS:
    a = load(f"{OLD}/runtime_images/{s}.runtime.freeze.json")
    b = load(f"{NEW}/runtime_images/{s}.runtime.freeze.json")
    if a["fragment_identity"] != b["fragment_identity"]:
        problems.append(f"{s}: fragment_identity differs")
    check(f"receipt[{s}]", a, b,
          allowed_value_change=[".physical_identity.inspect_full_sha256", ".receipt_sha256"],
          allowed_tag_change=[".physical_identity.native_receipt.path"])

pa = load(f"{OLD}/qualification_image_identity_patch.json")
pb = load(f"{NEW}/qualification_image_identity_patch.json")
allowed_values = [".patch_sha256"] + [f".systems.{s}.physical_identity.inspect_full_sha256" for s in SYSTEMS] \
    + [f".receipts.runtime_images.{s}.sha256" for s in SYSTEMS] + [f".receipts.runtime_images.{s}.receipt_sha256" for s in SYSTEMS]
allowed_tags = [".receipts.native_probe.path", ".receipts.analytics_worker.path"] \
    + [f".receipts.runtime_images.{s}.path" for s in SYSTEMS] \
    + [f".systems.{s}.physical_identity.native_receipt.path" for s in SYSTEMS]
check("patch", pa, pb, allowed_values, allowed_tags)
expected_blockers = ["analytics_worker:cpu_identity_changed_requires_parity_refresh",
                     "analytics_worker:gpu_identity_changed_requires_parity_refresh"]
if sorted(pb.get("blockers", [])) != expected_blockers:
    problems.append(f"patch blockers: {pb.get('blockers')}")
if pa.get("workers") != pb.get("workers"):
    problems.append("patch workers differ")

result = {"old_tag": OLD_TAG, "new_tag": NEW_TAG, "ok": not problems,
          "problems": problems, "allowed_changes": notes}
print(json.dumps(result, indent=1))
sys.exit(0 if not problems else 3)
