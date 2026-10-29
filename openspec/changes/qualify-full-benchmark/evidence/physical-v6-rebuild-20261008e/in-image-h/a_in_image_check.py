"""D(a): compile every allowlisted Python source and import every packaged module
inside a runtime image with the image's own python3 (Amendment 6, task 6C.5).

Run inside the image:  python3 -B /work/tools/a_in_image_check.py <system>
Root (read-only) is mounted at /work/root for SHA comparison only; nothing is
imported from it.  Output: one JSON document on stdout.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

SYSTEM = sys.argv[1]
ROOT = Path("/work/root")
ALLOWLIST = Path("/opt/vast/runtime-source-allowlist.txt")
PACKAGE_DIR = Path("/opt/vast/checkpoint")
SEARCH_DIRS = (Path("/opt/vast"), Path("/usr/local/bin"))
API_CLASS = ("AttributeError", "ImportError", "NameError", "SyntaxError", "TypeError")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_python(path):
    if path.suffix == ".py":
        return True
    try:
        with path.open("rb") as handle:
            first = handle.readline()
    except OSError:
        return False
    return first.startswith(b"#!") and b"python" in first


def locate(entry):
    name = Path(entry).name
    if entry.startswith("scripts/"):
        candidate = PACKAGE_DIR / name
        return candidate if candidate.is_file() else None
    for base in SEARCH_DIRS:
        for dirpath, _dirs, files in os.walk(base):
            if name in files:
                return Path(dirpath) / name
    return None


entries = [
    line.strip()
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines()
    if line.strip() and not line.strip().startswith("#")
]
report = {
    "system": SYSTEM,
    "python": sys.version,
    "executable": sys.executable,
    "pythonpath": os.environ.get("PYTHONPATH"),
    "cwd": os.getcwd(),
    "allowlist_sha256_image": sha(ALLOWLIST),
    "allowlist_entries": len(entries),
    "compile": [],
    "imports": [],
}
python_entries = []
for entry in entries:
    root_copy = ROOT / entry
    if not (entry.endswith(".py") or (root_copy.is_file() and is_python(root_copy))):
        continue
    python_entries.append(entry)
    image_copy = locate(entry)
    row = {"entry": entry, "image_path": str(image_copy) if image_copy else None}
    if root_copy.is_file():
        row["root_sha256"] = sha(root_copy)
    if image_copy is None:
        row["status"] = "not_packaged"
        report["compile"].append(row)
        continue
    row["image_sha256"] = sha(image_copy)
    row["matches_root"] = row.get("root_sha256") == row["image_sha256"]
    try:
        compile(image_copy.read_bytes(), str(image_copy), "exec", dont_inherit=True)
        row["status"] = "compiled"
    except SyntaxError as error:
        row["status"] = "syntax_error"
        row["error"] = f"{error.__class__.__name__}: {error.msg} at {error.lineno}"
    report["compile"].append(row)

modules = sorted(path.stem for path in PACKAGE_DIR.glob("*.py"))
for module in modules:
    completed = subprocess.run(
        [sys.executable, "-B", "-c", f"import {module}"],
        capture_output=True,
        timeout=300,
        env=os.environ.copy(),
    )
    stderr = completed.stderr.decode("utf-8", "replace")
    last = [line for line in stderr.strip().splitlines() if line.strip()]
    error_line = last[-1] if completed.returncode else ""
    row = {"module": module, "returncode": completed.returncode}
    if completed.returncode:
        row["error"] = error_line
        row["error_type"] = error_line.split(":", 1)[0]
        row["stderr_tail"] = "\n".join(last[-12:])
    report["imports"].append(row)

report["summary"] = {
    "python_entries": len(python_entries),
    "compiled": sum(r["status"] == "compiled" for r in report["compile"]),
    "syntax_errors": [r["entry"] for r in report["compile"] if r["status"] == "syntax_error"],
    "not_packaged": [r["entry"] for r in report["compile"] if r["status"] == "not_packaged"],
    "sha_mismatch_vs_root": [
        r["entry"] for r in report["compile"] if r.get("matches_root") is False
    ],
    "modules": len(modules),
    "imported_ok": sum(r["returncode"] == 0 for r in report["imports"]),
    "import_failures": {r["module"]: r["error"] for r in report["imports"] if r["returncode"]},
}
print(json.dumps(report, indent=1, sort_keys=True))
