"""A1 read-only dry run: fixed gate2_c (repo) against attempt-02 root/aux and attempt-02 descriptors. Writes nothing."""
import json, os, sys
from pathlib import Path
R = "/mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST"
sys.path[:0] = [R, R + "/scripts"]
from tests.fixtures import accepted_policy_fixture_compiler_gate2_fresh_v1 as fresh
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as gate
assert Path(gate.__file__).resolve() == Path(R) / fresh.GATE and hasattr(gate, "_b1_image_environment_keys_v1")
X = "a3c889451a5a1c1c57ba64954276c277346d4732"
root = fresh.root_v1(X); aux = root + ".operator-originals"
authority = fresh.read_once(aux + "/operator.authority.original.json", 8192)
context = json.loads(authority)["context"]
files = fresh.manifest_v1(fresh.read_once(aux + "/manifest.original.json", 8192), X)["files"]
pre = json.loads(fresh.read_once(aux + "/phase.pre.original.json", 8192))
evidence = {k: gate._descriptor(p, fresh.read_once(str(p), 16384 if k == "f2_accounting" else 1048576))
            for k, p in gate._fresh_evidence_paths_v1(Path(root)).items()}
plan = fresh.read_once(root + "/" + fresh.PLAN, 40960)
p0_raw = fresh.read_once(root + "/p0/p0-completion.v1.json", 65536)
review = {"commit": X, "approval_reference": context["approval_reference"], "evidence_sha256": fresh.sha(authority)}
charge = gate.fresh_charge_v1(pre=pre["measurement"], pre_packet=context["measurements"]["pre_packet"],
                              allocation_bytes=context["allocation_bytes"])
code = {rel: files[rel] for rel in fresh.EXPORT_CODE}
args = dict(project_root=Path(root), review=review, physical_plan_descriptor=gate._descriptor(Path(root) / fresh.PLAN, plan),
    code=code, evidence=evidence, p0_descriptor=gate._descriptor(Path(root) / "p0/p0-completion.v1.json", p0_raw),
    boot_id=pre["boot_id"], initial_charged_bytes=charge["initial_charged_bytes"], initial_measurement=pre["measurement"],
    operator_authority_descriptor=gate._descriptor(Path(aux) / "operator.authority.original.json", authority),
    prior_retention=None, fresh_context=context)
packet = gate.build_packet_v1(**args)
raw = gate.component.canonical_json_v1(packet)  # write_record_v1's encoding
decoded = gate._json(raw, gate.PACKET_LIMIT, canonical=True)
rebuilt = gate.build_packet_v1(project_root=Path(root), review=decoded["code_review"], physical_plan_descriptor=decoded["physical_plan"],
    code=decoded["code"], evidence=decoded["evidence"], p0_descriptor=decoded["p0"], boot_id=decoded["boot_id"],
    initial_charged_bytes=decoded["initial_charged_bytes"], initial_measurement=decoded["initial_measurement"],
    operator_authority_descriptor=decoded["operator_authority"], prior_retention=decoded["prior_retention"],
    resume_context=decoded.get("resume_context"), fresh_context=decoded["fresh_context"])
seed_raw = gate.component.canonical_json_v1(packet["seed"])
new_gate = os.path.getsize(R + "/" + fresh.GATE); new_plan = os.path.getsize(R + "/" + fresh.PLAN)
code_new = sum(d["size_bytes"] for d in code.values()) - code[fresh.GATE]["size_bytes"] + new_gate
total_new = code_new + len(raw) + new_plan + len(seed_raw)
total_as_run = sum(d["size_bytes"] for d in code.values()) + len(raw) + len(plan) + len(seed_raw)
print(json.dumps({"validate_equivalent": decoded == packet == rebuilt and type(packet.get("current_code_forms_quote_bytes")) is int,
  "environment_keys": len(packet["seed"]["environment_keys"]),
  "seed": [len(seed_raw), 4096, 4096 - len(seed_raw)],
  "packet_json_bound": [gate.compiler._json_bound(packet), gate.FRESH_PACKET_LIMIT_V1, gate.FRESH_PACKET_LIMIT_V1 - gate.compiler._json_bound(packet)],
  "packet_encoded": len(raw),
  "allocation_640k_as_run": [total_as_run, 655360, 655360 - total_as_run],
  "allocation_640k_new_gate_and_plan": [total_new, 655360, 655360 - total_new, {"gate2_c": new_gate, "plan": new_plan}]}, indent=1))
