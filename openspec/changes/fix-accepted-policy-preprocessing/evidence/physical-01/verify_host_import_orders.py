#!/usr/bin/env python3
"""Host-only fresh import/re-export checks; never an image fallback or promoter."""
from __future__ import annotations

import argparse
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path


LEAVES = (
    "publication_policy_qualification_transaction_validation_v2",
    "publication_policy_qualification_fragment_validation_v2",
    "publication_policy_qualification_pilot_validation_v2",
)
SIDECAR = "checkpoint_gstreamer_analytics_sidecar"
PROMOTION = "publication_qualification_promotion_v2"
TRANSACTION = "publication_policy_qualification_transaction_v2"
FRAGMENTS = "publication_policy_qualification_fragments_from_authority_v2"
ORDERS = {
    "promotion-first": (PROMOTION, SIDECAR, TRANSACTION, FRAGMENTS, *LEAVES),
    "sidecar-first": (SIDECAR, PROMOTION, TRANSACTION, FRAGMENTS, *LEAVES),
    "transaction-builder-first": (TRANSACTION, *LEAVES, SIDECAR, PROMOTION, FRAGMENTS),
    "fragment-builder-first": (FRAGMENTS, *LEAVES, SIDECAR, PROMOTION, TRANSACTION),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--order", choices=("all", *ORDERS), default="all")
    args = parser.parse_args()
    root = args.project_root.resolve(strict=True)
    assert os.environ.get("PYTHONPATH") == str(root / "scripts"), "explicit host PYTHONPATH must identify frozen root"
    assert sys.dont_write_bytecode
    if args.order == "all":
        runs = []
        for order in ORDERS:
            completed = subprocess.run([sys.executable, "-B", str(Path(__file__).resolve()),
                                        "--project-root", str(root), "--order", order],
                                       check=True, capture_output=True, text=True)
            runs.append(json.loads(completed.stdout))
        print(json.dumps({"host_only": True, "image_execution_claimed": False,
                          "passed": True, "fresh_interpreters": len(runs), "runs": runs}, sort_keys=True))
        return
    for name in ORDERS[args.order]:
        module = importlib.import_module(name)
        assert Path(module.__file__) == root / "scripts" / (name + ".py"), name
    txn, fragment, pilot = [sys.modules[name] for name in LEAVES]
    old_txn, old_fragment = sys.modules[TRANSACTION], sys.modules[FRAGMENTS]
    promoter = sys.modules[PROMOTION]
    for name in ("QualificationTransactionV2Error", "_ACTIVE_CUSTODY", "file_descriptor",
                 "_cold_validate_committed_transaction", "_validate_committed_receipt"):
        assert getattr(old_txn, name) is getattr(txn, name), name
    for name in ("QualificationFragmentsFromAuthorityV2Error", "FragmentAuthorityDependenciesV2",
                 "DEFAULT_DEPENDENCIES", "validate_publication_policy_qualification_fragment_from_authority_v2"):
        assert getattr(old_fragment, name) is getattr(fragment, name), name
    assert promoter.fragments_v2 is fragment
    assert promoter.transaction_v2 is old_txn
    assert promoter.policy_pilot_validator is pilot.policy_pilot_validator
    assert txn._ACTIVE_CUSTODY.get() is None
    print(json.dumps({"host_only": True, "image_execution_claimed": False, "order": args.order,
                      "import_sequence": ORDERS[args.order], "shared_reexport_object_identity": True,
                      "passed": True}, sort_keys=True))


if __name__ == "__main__":
    main()
