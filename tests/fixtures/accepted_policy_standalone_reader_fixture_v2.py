"""Fresh-interpreter default guardian cold read with exact original evidence."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


_PROGRAM = """
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
sys.path.insert(0,str(root))
sys.path.insert(0,str(root/'scripts'))
import publication_guardian_accepted_policy_preprocessing_contract_v1 as guardian
expected_module=root/'scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py'
module_path=Path(guardian.__file__).resolve(strict=True)
module_sha256=hashlib.sha256(module_path.read_bytes()).hexdigest()
if module_path!=expected_module or module_sha256!=sys.argv[6]:
    raise ValueError('standalone default guardian module provenance drifted')
loaded=guardian.load_accepted_policy_guardian_preprocessing_contract_v1(
    project_root=root,preprocessing_contract_path=Path(sys.argv[2]),
    materialization_receipt_path=Path(sys.argv[3]),
    accepted_policy_capability_manifest_path=Path(sys.argv[4]))
semantic_sha256=guardian._semantic_sha(loaded['preprocessing_contract'])
if semantic_sha256!=loaded['receipt']['preprocessing_contract_content_sha256'] or semantic_sha256!=sys.argv[5]:
    raise ValueError('standalone default guardian contract semantic identity drifted')
from tests.fixtures.accepted_policy_fixture_provenance_v1 import loaded_fixture_production_sources_v1
print(json.dumps({'standalone_guardian_cold_reader_passed':True,
    'default_module_path':str(module_path),'default_module_sha256':module_sha256,
    'preprocessing_contract_content_sha256':semantic_sha256,
    'loaded_production_sources':loaded_fixture_production_sources_v1(project_root=root),
    'campaign_authority':False},sort_keys=True))
"""


def run_fixture_standalone_guardian_cold_reader_v2(
    *, project_root: Path, output_dir: Path, guardian: Mapping[str, Any], accepted_capability_path: Path,
) -> dict[str, Any]:
    """Keep engine custody alive in the caller; do not supply reader dependencies."""
    root = project_root.resolve(strict=True)
    module_path = root / "scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py"
    module_sha256 = hashlib.sha256(module_path.read_bytes()).hexdigest()
    outputs = {role: output_dir / name for role, name in (
        ("stdout", "standalone-guardian-cold-reader.stdout.raw"),
        ("stderr", "standalone-guardian-cold-reader.stderr.raw"),
        ("result", "standalone-guardian-cold-reader.result.v2.json"),
    )}
    if not output_dir.is_dir() or any(path.exists() or path.is_symlink() for path in outputs.values()):
        raise ValueError("fresh standalone cold reader requires exclusive evidence paths")
    command = [sys.executable, "-B", "-c", _PROGRAM, str(root), str(guardian["contract_path"]),
               str(guardian["receipt_path"]), str(accepted_capability_path),
               guardian["preprocessing_contract_sha256"], module_sha256]
    started = datetime.now(timezone.utc).isoformat()
    result = subprocess.run(command, cwd=root, capture_output=True)
    finished = datetime.now(timezone.utc).isoformat()
    for role, data in (("stdout", result.stdout), ("stderr", result.stderr)):
        with outputs[role].open("xb") as stream:
            stream.write(data)
    proof = None
    error = None
    if result.returncode != 0:
        error = "fresh standalone default guardian reader refused"
    else:
        try:
            proof = json.loads(result.stdout)
            if (type(proof) is not dict or proof.get("standalone_guardian_cold_reader_passed") is not True
                    or proof.get("default_module_path") != str(module_path)
                    or proof.get("default_module_sha256") != module_sha256
                    or proof.get("preprocessing_contract_content_sha256") != guardian["preprocessing_contract_sha256"]
                    or not proof.get("loaded_production_sources")):
                error = "fresh standalone default guardian reader proof identity drifted"
        except (ValueError, UnicodeError):
            error = "fresh standalone default guardian reader returned invalid proof JSON"
    evidence = {"command": command, "cwd": str(root), "started_at": started, "finished_at": finished,
                "original_exit_code": result.returncode, "expected_default_module_path": str(module_path),
                "expected_default_module_sha256": module_sha256,
                "expected_contract_semantic_sha256": guardian["preprocessing_contract_sha256"],
                "stdout_path": str(outputs["stdout"]), "stdout_bytes": len(result.stdout),
                "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
                "stderr_path": str(outputs["stderr"]), "stderr_bytes": len(result.stderr),
                "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
                "standalone_guardian_cold_reader_passed": error is None, "proof": proof, "error": error,
                "campaign_authority": False}
    with outputs["result"].open("x", encoding="ascii") as stream:
        stream.write(json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n")
    if error is not None:
        raise ValueError(error)
    return evidence
