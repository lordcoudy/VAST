from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from backend_pair_archive_sizing_receipts_v1 import (  # noqa: E402
    BackendPairArchiveSizingReceiptsV1Error,
    INDEX_FILENAME,
    SYSTEMS,
    load_seafile_sizing_rows_v1,
    materialize_backend_pair_archive_sizing_receipts_v1,
)


class BackendPairArchiveSizingReceiptsV1ContractTests(unittest.TestCase):
    def test_public_contract_is_exact_280_pair_closed(self) -> None:
        self.assertEqual(
            SYSTEMS,
            ("deepstream", "savant", "openvino_gva", "gstreamer_custom"),
        )
        self.assertEqual(
            INDEX_FILENAME,
            "checkpoint_backend_pair_archive_sizing_index_v1.json",
        )
        self.assertTrue(callable(materialize_backend_pair_archive_sizing_receipts_v1))
        self.assertTrue(callable(load_seafile_sizing_rows_v1))
        self.assertTrue(issubclass(
            BackendPairArchiveSizingReceiptsV1Error, RuntimeError,
        ))


if __name__ == "__main__":
    unittest.main()
