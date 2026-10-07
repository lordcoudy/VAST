#!/usr/bin/env python3
"""Sanity-check the saved plan against the saved inventory (coverage both ways)."""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
inventory = json.loads((HERE / "inventory.v1.json").read_bytes())
plan = json.loads((HERE / "host-pin-rebind.plan.v1.json").read_bytes())
mapping = {row["old"]: row["new"] for row in inventory["mapping"]}
inv_sites = {(row["file"], row["line"]) for row in inventory["sites"] + inventory["size_sites"]}
plan_sites = {(row["file"], edit["line"]) for row in plan["files"] for edit in row["edits"]}
problems = {
    "inventory_sites_not_planned": sorted(inv_sites - plan_sites),
    "planned_sites_outside_inventory": sorted(plan_sites - inv_sites),
    "planned_keys_not_in_mapping": sorted({key for row in plan["files"] for edit in row["edits"]
                                           for key in edit["keys"] if key not in mapping
                                           and not edit["kind"].endswith("size_literal")
                                           and "size" not in edit["kind"]}),
    "old_values_unpaired_or_unknown": [row for row in inventory["hex_literal_classification"]
                                       if row["status"] == "old_value_without_pair_ERROR"],
    "inventory_sites_outside_pin_files": sorted({row["file"] for row in inventory["sites"]}
                                                - {row["file"] for row in plan["files"]}),
}
result = {"status": "ok" if not any(problems.values()) else "failed", **problems,
          "inventory_sites": len(inv_sites), "planned_sites": len(plan_sites),
          "mapping_size": len(mapping),
          "hex_literals_not_in_any_receipt_left_unchanged": [
              row for row in inventory["hex_literal_classification"]
              if row["status"] == "not_in_any_old_or_new_receipt"]}
print(json.dumps(result, indent=1, sort_keys=True))
sys.exit(0 if result["status"] == "ok" else 1)
