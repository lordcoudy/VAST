"""Amendment 8 diagnostic (non-qualifying; run 3: fragment-only policy index, resource index with resource_v2_evidence relaxed): build the policy and resource indices in-process with the
v2 authority validator from attempt-4 inputs. usage: python -B diag_a8_index.py <project_root> <out_dir>
<project_root> is either the frozen root (read-only use; outputs must then lie outside it) or a scratch copy."""
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(sys.argv[1])
OUT = Path(sys.argv[2])
sys.path.insert(0, str(ROOT / "scripts"))
import full_resource_qualification_index_v1 as ridx  # noqa: E402
import publication_policy_qualification_fragments_from_authority_v2 as fv2  # noqa: E402
import publication_policy_qualification_index_v2 as pidx  # noqa: E402
import publication_policy_qualification as ppq  # noqa: E402
import full_resource_qualification as frq  # noqa: E402

A = ROOT / "artifacts"
QUAL = A / "publication_policy_qualification_v2_qfb_20261008e"
fragments = {s: QUAL / "fragments" / s / "qualification_fragment.json"
             for s in ("deepstream", "savant", "openvino_gva", "gstreamer_custom")}
common = dict(project_root=ROOT, fragment_paths=fragments,
              pilot_root=A / "publication_policy_qualification_pilot_v2_qfb_20261008e",
              fragment_validator=fv2.validate_publication_policy_qualification_fragment_from_authority_v2,
              execution_closure_receipt_path=A / "publication_policy_qualification_execution_closure_v1_qfb_20261008e/qualification_execution_closure.v1.receipt.json")
result = {}


def attempt(name, call):
    try:
        value = call()
        result[name] = {"status": "ok", "value": json.loads(json.dumps(value, default=str))}
    except Exception as error:
        chain, cause = [], error
        while cause is not None:
            chain.append(f"{type(cause).__name__}: {cause}")
            cause = cause.__cause__
        frames = traceback.extract_tb(error.__traceback__)
        result[name] = {"status": "refused", "chain": chain,
                        "where": [f"{Path(f.filename).name}:{f.lineno}" for f in frames][-5:]}


fragment_only = {k: v for k, v in common.items() if k != "execution_closure_receipt_path"}
attempt("policy_index", lambda: pidx.build_policy_qualification_index_v2(output_dir=OUT / "policy_index", **fragment_only))
ridx._BINDING_REQUIRED_FIELDS = ridx._BINDING_REQUIRED_FIELDS - {"resource_v2_evidence"}
attempt("resource_index", lambda: ridx.build_full_resource_qualification_index_v1(output_path=OUT / "resource_index.json", **common))
if result["policy_index"]["status"] == "ok":
    index = OUT / "policy_index" / "checkpoint_policy_qualification_index.v2.json"
    attempt("policy_promotion_default_validator", lambda: ppq.promote_policy_qualification(
        project_root=ROOT, index_path=index, output_dir=OUT / "policy_promoted_default"))
    attempt("policy_promotion_v2_validator", lambda: ppq.promote_policy_qualification(
        project_root=ROOT, index_path=index, output_dir=OUT / "policy_promoted_v2",
        fragment_validator=fv2.validate_publication_policy_qualification_fragment_from_authority_v2))
if result["resource_index"]["status"] == "ok":
    attempt("resource_promotion", lambda: frq.promote_full_resource_qualification(
        project_root=ROOT, index_path=OUT / "resource_index.json", output_dir=OUT / "resource_promoted"))
print(json.dumps(result, indent=1))
