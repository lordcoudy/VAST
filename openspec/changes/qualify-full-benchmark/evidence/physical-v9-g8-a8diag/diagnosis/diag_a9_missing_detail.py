import csv, json
from pathlib import Path
P = Path("/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/publication_policy_qualification_pilot_v2_qfb_20261008e")
for cell in ("deepstream/gpu/h264/independent_processes", "openvino_gva/gpu/h264/independent_processes", "savant/gpu/h265/shared_video_dag"):
    arm = P / cell
    tr = {}
    rows_by_trace = {}
    for r in csv.DictReader((arm / "resource_intervals.csv").open(newline="")):
        rows_by_trace.setdefault(r["trace_id"], []).append((r["component"], r["branch_id"], r.get("resource"), r["duration_ns"]))
        if r["component"] == "transfer":
            tr[(r["trace_id"], r["branch_id"])] = tr.get((r["trace_id"], r["branch_id"]), 0) + float(r["duration_ns"])
    term = {}
    for r in csv.DictReader((arm / "branch_terminals.csv").open(newline="")):
        term[(r["trace_id"], r["branch_id"])] = r["terminal_status"]
    ingress = {}
    for r in csv.DictReader((arm / "ingress_ledger.csv").open(newline="")):
        ingress[r["trace_id"]] = (r["terminal_status"], r["stream_id"], r["frame_id"])
    dec = [json.loads(l) for l in (arm / "publication_policy_decisions.jsonl").read_text().splitlines() if l.strip()]
    print("==", cell, "decisions", len(dec), "ingress", len(ingress), "completed ingress", sum(v[0] == "completed" for v in ingress.values()))
    for d in dec:
        k = (str(d["trace_id"]), str(d["branch"]))
        if d.get("selected_resource") == "gpu" and tr.get(k, 0) <= 0:
            print(" missing", k, "terminal", term.get(k), "ingress", ingress.get(k[0]), "intervals_for_trace", rows_by_trace.get(k[0], [])[:6])
