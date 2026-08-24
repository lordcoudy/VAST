from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from benchmark_contract import ContractError  # noqa: E402
from run_experiments import (  # noqa: E402
    benchmark_child_environment,
    resolve_checkpoint_codec,
)


class RunExperimentsSecurityTests(unittest.TestCase):
    def test_checkpoint_codec_is_explicitly_bound_to_dataset(self) -> None:
        scenario = {"name": "checkpoint_video_dag_shared"}
        self.assertEqual(
            resolve_checkpoint_codec({"codec_variant": "h264"}, scenario), "h264"
        )
        self.assertEqual(
            resolve_checkpoint_codec({"codec_variant": "hevc"}, scenario), "h265"
        )
        with self.assertRaisesRegex(ContractError, "codec_variant"):
            resolve_checkpoint_codec({}, scenario)

    def test_non_checkpoint_scenario_does_not_invent_codec(self) -> None:
        self.assertIsNone(
            resolve_checkpoint_codec(
                {"codec_variant": "h264"}, {"name": "local_multi_pipeline"}
            )
        )

    def test_benchmark_children_do_not_inherit_seafile_capability_links(self) -> None:
        with mock.patch.dict(
            os.environ,
            {
                "VAST_SEAFILE_UPLOAD_LINK": "https://cloud.invalid/u/token",
                "VAST_SEAFILE_READ_LINK": "https://cloud.invalid/d/token",
                "VAST_KEEP": "visible",
            },
            clear=True,
        ):
            child = benchmark_child_environment(
                run_seed=123,
                repeat_index=4,
            )

        self.assertNotIn("VAST_SEAFILE_UPLOAD_LINK", child)
        self.assertNotIn("VAST_SEAFILE_READ_LINK", child)
        self.assertEqual(child["VAST_KEEP"], "visible")
        self.assertEqual(child["EXPERIMENT_RUN_SEED"], "123")
        self.assertEqual(child["EXPERIMENT_REPEAT_INDEX"], "4")


if __name__ == "__main__":
    unittest.main()
