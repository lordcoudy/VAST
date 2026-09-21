from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from model_parity_grant import (
    GRANT_STATUS_V4,
    ModelParityGrantError,
    model_parity_grant_from_identity_artifacts,
    validate_pre_run_model_parity_grant,
)
from tests.test_checkpoint_model_parity_acceptance_v4 import _refresh
from tests.test_model_parity_grant import descriptor, identity, sha


def identity_v4() -> dict[str, object]:
    result = identity()
    parity = result["bindings"]["analytics_model_parity"]
    parity["schema_version"] = 4
    parity["artifact_kind"] = "vast_verified_model_parity_acceptance_binding_v4"
    refresh = _refresh()
    parity["refresh_authority"] = refresh
    authority_files = [
        {key: refresh["image_identity_patch"][key] for key in ("path", "size_bytes", "sha256")},
        {key: refresh["execution_config"][key] for key in ("path", "size_bytes", "sha256")},
        refresh["binding_set"]["index"],
        *(
            {key: refresh["runtime_probes"][resource][key] for key in ("path", "size_bytes", "sha256")}
            for resource in ("cpu", "gpu")
        ),
        *refresh["binding_set"]["bindings"].values(),
        descriptor("configs/checkpoint_analytics_model_parity.yaml"),
    ]
    parity["files"] = sorted([*parity["files"], *authority_files], key=lambda item: item["path"])
    parity["files_sha256"] = sha(parity["files"])
    parity["binding_sha256"] = sha({key: value for key, value in parity.items() if key != "binding_sha256"})
    known = {item["path"]: item for item in result["files"]}
    for item in parity["files"]:
        known[item["path"]] = item
    result["files"] = sorted(known.values(), key=lambda item: item["path"])
    result["files_sha256"] = sha(result["files"])
    result["binding_sha256"] = sha({key: value for key, value in result.items() if key != "binding_sha256"})
    return result


class ModelParityGrantV4Test(unittest.TestCase):
    def test_v4_binding_derives_v4_status_grant(self) -> None:
        grant = model_parity_grant_from_identity_artifacts(identity_v4())
        self.assertEqual(grant["status"], GRANT_STATUS_V4)
        self.assertEqual(validate_pre_run_model_parity_grant(grant), grant)

    def test_v4_refresh_tamper_fails_without_v3_fallback(self) -> None:
        value = identity_v4()
        parity = value["bindings"]["analytics_model_parity"]
        parity["refresh_authority"]["workers"]["gpu"]["image_id"] = "sha256:" + "0" * 64
        parity["binding_sha256"] = sha({key: item for key, item in parity.items() if key != "binding_sha256"})
        value["binding_sha256"] = sha({key: item for key, item in value.items() if key != "binding_sha256"})
        with self.assertRaisesRegex(ModelParityGrantError, "v4 refresh"):
            model_parity_grant_from_identity_artifacts(value)


if __name__ == "__main__":
    unittest.main()
