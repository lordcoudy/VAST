from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
COORDINATOR = (
    ROOT / "scripts" / "checkpoint_openvino_gva_container_coordinator_v3.py"
)


class OpenVINOGVAContainerCoordinatorV3Tests(unittest.TestCase):
    def test_facade_supplies_non_cli_openvino_code_authority(self) -> None:
        callback = mock.Mock(return_value=0)
        fake = types.ModuleType("checkpoint_gstreamer_runtime")
        fake.main = callback
        spec = importlib.util.spec_from_file_location(
            "openvino_coordinator_v3_under_test", COORDINATOR
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        with mock.patch.dict(
            sys.modules, {"checkpoint_gstreamer_runtime": fake}
        ):
            spec.loader.exec_module(module)
        self.assertEqual(module.main(("--scenario", "checkpoint_video_dag_shared")), 0)
        callback.assert_called_once_with(
            ("--scenario", "checkpoint_video_dag_shared"),
            publication_system_authority="openvino_gva",
        )

    def test_generic_cli_does_not_expose_an_authority_flag(self) -> None:
        body = (ROOT / "scripts" / "checkpoint_gstreamer_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('add_argument("--publication-system-authority"', body)
        self.assertIn('publication_system_authority in {None, "openvino_gva"}', body)


if __name__ == "__main__":
    unittest.main()
