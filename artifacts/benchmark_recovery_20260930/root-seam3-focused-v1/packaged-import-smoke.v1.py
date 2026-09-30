"""Import actual selected packaged Python copies, without source/hardware work."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / "artifacts/benchmark_recovery_20260930/component-packaged-import-smoke-v1"
OUTPUT.mkdir(exist_ok=False)
paths = [line for line in (ROOT / "deploy/gstreamer_custom/publication/runtime-source-allowlist.txt").read_text().splitlines()
         if line.startswith("scripts/")]


def facts(path):
    raw = path.read_bytes()
    return {"size_bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


before = {name: facts(ROOT / name) for name in paths}
with tempfile.TemporaryDirectory(prefix="vast-selected-import-") as directory:
    temporary = Path(directory)
    for name in paths:
        shutil.copyfile(ROOT / name, temporary / Path(name).name)
    code = ("import sys;sys.path.insert(0," + repr(directory) + ");"
            "import checkpoint_gstreamer_custom_container_coordinator_v3;"
            "import checkpoint_gstreamer_analytics_bridge;import checkpoint_gstreamer_analytics_sidecar;"
            "import publication_gstreamer_component_authority_v1;"
            "import publication_guardian_component_preprocessing_contract_v1;"
            "assert 'publication_gstreamer_component_inputs_v1' not in sys.modules;"
            "assert 'publication_policy_qualification_runtime_inputs_v2' not in sys.modules;"
            "print('selected packaged imports passed; host factories not loaded')")
    with (OUTPUT / "stdout.bin").open("xb") as stdout, (OUTPUT / "stderr.bin").open("xb") as stderr:
        result = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=temporary,
                                stdout=stdout, stderr=stderr, timeout=60, check=False)
after = {name: facts(ROOT / name) for name in paths}
receipt = {"schema_version": 1, "artifact_kind": "vast_local_selected_packaged_import_smoke_v1",
           "returncode": result.returncode, "before": before, "after": after,
           "source_before_after_equal": before == after, "module_count": len(paths),
           "scope": "local_actual_allowlisted_python_copies_only",
           "container_image_build": False, "hardware_acceptance": False,
           "raw_channels": {name: facts(OUTPUT / name) for name in ("stdout.bin", "stderr.bin")}}
with (OUTPUT / "execution.v1.json").open("x") as output:
    json.dump(receipt, output, sort_keys=True, separators=(",", ":")); output.write("\n")
print(json.dumps({key: receipt[key] for key in ("returncode", "source_before_after_equal", "module_count")}))
raise SystemExit(result.returncode != 0 or before != after)
