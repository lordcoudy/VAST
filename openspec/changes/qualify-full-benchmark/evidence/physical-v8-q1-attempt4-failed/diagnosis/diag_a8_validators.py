"""Amendment 8 diagnostic (non-qualifying, read-only): run the stock fragment validators that
publication_policy_qualification._default_fragment_validator uses, on the attempt-4 (qfb-20261008e)
transaction fragments. Nothing is written under the root. usage: python -B diag_a8_validators.py"""
import json
import sys
import traceback
from pathlib import Path

ROOT = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a")
sys.path.insert(0, str(ROOT / "scripts"))
import publication_policy_qualification as ppq  # noqa: E402

QUAL = ROOT / "artifacts/publication_policy_qualification_v2_qfb_20261008e"
result = {}
for system in ("deepstream", "savant", "openvino_gva", "gstreamer_custom"):
    fragment = QUAL / "fragments" / system / "qualification_fragment.json"
    try:
        value = ppq._default_fragment_validator(system, fragment, ROOT)
        result[system] = {"status": "accepted", "keys": sorted(value)[:12] if isinstance(value, dict) else str(type(value))}
    except Exception as error:  # diagnostic: record the first refusal per system
        chain, cause = [], error
        while cause is not None:
            chain.append(f"{type(cause).__name__}: {cause}")
            cause = cause.__cause__
        frames = traceback.extract_tb(error.__traceback__)
        result[system] = {"status": "refused", "chain": chain,
                          "where": [f"{Path(f.filename).name}:{f.lineno}" for f in frames][-4:]}
print(json.dumps(result, indent=1))
