"""Amendment 8 diagnostic (non-qualifying, read-only): validate every attempt-4 pilot acceptance with the
stock validator used by both promotions. usage: python -B diag_a8_pilots.py"""
import json
import sys
from pathlib import Path

ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
sys.path.insert(0, str(ROOT / "scripts"))
from checkpoint_qualification_pilot_acceptance_v1 import validate_checkpoint_qualification_pilot_acceptance_v1  # noqa: E402

PILOTS = ROOT / "artifacts/publication_policy_qualification_pilot_v2_qfb_20261008e"
rows = []
for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
    for resource in ("cpu", "gpu"):
        for codec in ("h264", "h265"):
            for topology in ("independent_processes", "shared_video_dag"):
                path = PILOTS / system / resource / codec / topology / "checkpoint_qualification_pilot_acceptance.json"
                try:
                    value = validate_checkpoint_qualification_pilot_acceptance_v1(
                        project_root=ROOT, acceptance_path=path, expected_system=system,
                        expected_resource=resource, expected_codec=codec, expected_topology_kind=topology)
                    rows.append({"cell": f"{system}/{resource}/{codec}/{topology}", "status": "accepted",
                                 "run_id": value.get("run_id")})
                except Exception as error:
                    rows.append({"cell": f"{system}/{resource}/{codec}/{topology}", "status": "refused",
                                 "error": f"{type(error).__name__}: {error}"[:300]})
print(json.dumps({"accepted": sum(r["status"] == "accepted" for r in rows), "total": len(rows), "rows": rows}, indent=1))
