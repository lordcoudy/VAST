"""Stage only the reviewed second setup implementation and its closed fixtures."""
from pathlib import Path
import hashlib
import subprocess
import ast

root = Path.cwd()
base = root / "artifacts/benchmark_recovery_20260930"
assert subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == "b244b5c71aaf1782f3aa54c8e1281191bb5e525a"
assert not subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).strip()
expected = {
    "controller.py":"eb03484fdf8e6d1d1b3519678888758bcb1901c7477bed3cd67450317cc78745",
    "guest_consumer.py":"29127925d99a8482d44c0fadd749594274763a14346e88dc74f64e9430e4e862",
    "research_protocol.py":"fcb8a16bbb100fa13c3ff5584913d318f25f95a8205751107790be5086b02c63",
    "test_research_protocol.py":"2dbcec646c9d641f93ccbac4b633ad3513f5e2eb37161f6f9abdb39717255a45",
    "test_setup_v2.py":"f2b44bb02e30abfa502d61dcd754900149a009d62b51f7558839c9a760a79f23",
    "README.md":"f9ff33a991f6885b9d2e0d595716df0bb6284b99401c9f6303a6d856c730e553",
}
files = [Path(__file__).resolve()]
code = base / "decoder-research-implementation-v2"
assert {path.name for path in code.iterdir() if path.is_file()} == set(expected)
for name, digest in expected.items():
    raw = (code / name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    if name.endswith(".py"): ast.parse(raw, filename=name)
    files.append(code / name)
for directory_name in ("decoder-research-v2-focused-tests", "decoder-controller-v2-independent-review", "decoder-research-v2-binding-review"):
    directory = base / directory_name
    assert directory.is_dir()
    files.extend(path for path in directory.rglob("*") if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc")
paths = sorted({path.relative_to(root).as_posix() for path in files})
assert len(paths) < 60 and all((root / name).is_file() and not (root / name).is_symlink() for name in paths)
pins = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in paths}
subprocess.run(["git","add","-f","--",*paths],check=True)
staged = subprocess.check_output(["git","diff","--cached","--name-only"],text=True).splitlines()
assert set(staged) == set(paths)
for name, digest in pins.items():
    assert hashlib.sha256((root / name).read_bytes()).hexdigest() == digest
    assert hashlib.sha256(subprocess.check_output(["git","show",":"+name])).hexdigest() == digest, name
assert not any(name.startswith(("scripts/","deploy/","tests/",".github/","openspec/")) for name in staged)
print(f"Artifact-v2 stage: {len(paths)} exact owned paths; six reviewed code hashes and every physical/index hash equal.")
