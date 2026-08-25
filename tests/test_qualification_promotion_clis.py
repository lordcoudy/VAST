from __future__ import annotations

import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import full_resource_qualification as resource  # noqa: E402
import publication_policy_qualification as policy  # noqa: E402


class QualificationPromotionCliTests(unittest.TestCase):
    def test_policy_cli_invokes_physical_promotion_and_prints_redacted_result(self) -> None:
        argv = [
            "publication_policy_qualification.py",
            "--project-root",
            "/repo",
            "--index-path",
            "policy-index.json",
            "--output-dir",
            "accepted/policy",
        ]
        promoted = {
            "passed": True,
            "status": "promoted",
            "receipt": {"sha256": "a" * 64},
            "output_dir": "/repo/accepted/policy",
        }
        stream = io.StringIO()
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(policy, "promote_policy_qualification", return_value=promoted) as call,
            redirect_stdout(stream),
        ):
            self.assertEqual(policy.main(), 0)
        call.assert_called_once_with(
            project_root=Path("/repo"),
            index_path=Path("policy-index.json"),
            output_dir=Path("accepted/policy"),
        )
        self.assertEqual(json.loads(stream.getvalue()), promoted)

    def test_resource_cli_invokes_physical_promotion_and_prints_redacted_result(self) -> None:
        argv = [
            "full_resource_qualification.py",
            "--project-root",
            "/repo",
            "--index-path",
            "resource-index.json",
            "--output-dir",
            "accepted/resource",
        ]
        promoted = {
            "passed": True,
            "status": "promoted",
            "receipt": {"sha256": "b" * 64},
            "output_dir": "/repo/accepted/resource",
        }
        stream = io.StringIO()
        with (
            mock.patch.object(sys, "argv", argv),
            mock.patch.object(resource, "promote_full_resource_qualification", return_value=promoted) as call,
            redirect_stdout(stream),
        ):
            self.assertEqual(resource.main(), 0)
        call.assert_called_once_with(
            project_root=Path("/repo"),
            index_path=Path("resource-index.json"),
            output_dir=Path("accepted/resource"),
        )
        self.assertEqual(json.loads(stream.getvalue()), promoted)


if __name__ == "__main__":
    unittest.main()
