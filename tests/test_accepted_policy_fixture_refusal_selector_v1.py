"""The refusal selector reads a complete, bounded roster through custody."""
from contextlib import ExitStack
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/consumer-01"))
import build_per_cell_minimum_refusal_v1 as selector
from publication_physical_io_v1 import PhysicalRootCustodyV1


def complete_input():
    rows, payloads, target = [], {}, None
    for system in ("deepstream", "gstreamer_custom", "openvino_gva", "savant"):
        for resource in ("cpu", "gpu"):
            for codec in ("h264", "h265"):
                for topology in ("independent_processes", "shared_process"):
                    operation_id = "qualification-" + str(len(rows))
                    path = ROOT / "controlled-source-plans" / (operation_id + ".json")
                    rows.append({"operation_id": operation_id, "phase": "qualification_cell",
                        "system": system, "policy": "cpu_only" if resource == "cpu" else "gpu_only",
                        "codec": codec, "descriptors": {"source_plan": {"path": str(path)}}})
                    payloads[path] = json.dumps({"topology_kind": topology}).encode("ascii")
                    if (system, resource, codec, topology) == selector.REFUSAL_COORDINATE:
                        target = operation_id
    rows.extend({"operation_id": "ancillary-" + str(i), "phase": "ancillary"} for i in range(5))
    return {"capture_plan": {"operation_manifest": {"operations": rows}}}, payloads, target


class RefusalSelectorReadTests(unittest.TestCase):
    def select(self, prepared, payloads, *, drift=None):
        with ExitStack() as stack:
            stack.enter_context(patch.object(Path, "read_bytes",
                side_effect=AssertionError("unbounded source-plan read")))
            opened = stack.enter_context(patch.object(PhysicalRootCustodyV1, "open"))
            opened.return_value.__exit__.return_value = False
            custody = opened.return_value.__enter__.return_value
            custody.read_descriptor.side_effect = lambda path, **kwargs: ({}, payloads[path])
            custody.verify.side_effect = drift
            original_loads = json.loads
            def parse(raw):
                self.assertEqual(custody.verify.call_count, custody.read_descriptor.call_count)
                self.assertEqual(custody.verify.call_count, parsed.call_count)
                return original_loads(raw)
            parsed = stack.enter_context(patch.object(selector.json, "loads", side_effect=parse))
            try:
                result = selector._select_refusal_operation(prepared)
            finally:
                self.opened, self.custody, self.parsed = opened, custody, parsed
        return result

    def test_complete_roster_selects_target_using_32_bounded_custody_reads(self):
        prepared, payloads, target = complete_input()
        self.assertEqual(self.select(prepared, payloads), target)
        self.assertEqual(self.opened.call_count, 32)
        self.assertEqual(self.custody.read_descriptor.call_count, 32)
        self.assertEqual(self.custody.verify.call_count, 32)
        for call in self.custody.read_descriptor.call_args_list:
            self.assertEqual(call.kwargs["maximum"], 16 * 1024**2)
            self.assertIs(call.kwargs["capture"], True)
            self.assertIn(call.args[0], payloads)

    def test_incomplete_or_duplicate_roster_refuses_before_any_read(self):
        prepared, payloads, _ = complete_input()
        rows = prepared["capture_plan"]["operation_manifest"]["operations"]
        missing_qualification = copy.deepcopy(rows)
        missing_qualification[0]["phase"] = "ancillary"
        duplicate_id = copy.deepcopy(rows)
        duplicate_id[1]["operation_id"] = duplicate_id[0]["operation_id"]
        ancillary_collision = copy.deepcopy(rows)
        ancillary_collision[-1]["operation_id"] = ancillary_collision[0]["operation_id"]
        excessive_metadata = copy.deepcopy(rows)
        nested = 0
        for _ in range(33):
            nested = [nested]
        excessive_metadata[0]["extra"] = nested
        for value in (tuple(rows), rows + [rows[-1]], missing_qualification, duplicate_id,
                      ancillary_collision, excessive_metadata):
            with self.subTest(shape=type(value).__name__, count=len(value)):
                prepared["capture_plan"]["operation_manifest"]["operations"] = value
                with self.assertRaises(ValueError):
                    self.select(prepared, payloads)
                self.opened.assert_not_called()

    def test_custody_drift_refuses_before_json_parsing(self):
        prepared, payloads, _ = complete_input()
        failure = RuntimeError("controlled custody drift")
        with self.assertRaises(RuntimeError) as caught:
            self.select(prepared, payloads, drift=failure)
        self.assertIs(caught.exception, failure)
        self.parsed.assert_not_called()
        self.assertEqual(self.custody.read_descriptor.call_count, 1)

    def test_malformed_source_maps_refuse_without_reading_the_next_plan(self):
        prepared, payloads, _ = complete_input()
        first = next(iter(payloads))
        for raw in (b"[]", b"{}", b'{"topology_kind":[]}',
                    json.dumps({"topology_kind": "x" * 513}).encode("ascii"),
                    b'{"topology_kind":"shared_process","extra":' + b"[" * 33 + b"0" + b"]" * 33 + b"}"):
            with self.subTest(payload_size=len(raw)):
                payloads[first] = raw
                with self.assertRaises((ValueError, KeyError)):
                    self.select(prepared, payloads)
                self.assertEqual(self.custody.read_descriptor.call_count, 1)

    def test_512_character_topology_preserves_prior_coordinate_predicates(self):
        prepared, payloads, target = complete_input()
        payloads[next(iter(payloads))] = json.dumps({"topology_kind": "x" * 512}).encode("ascii")
        self.assertEqual(self.select(prepared, payloads), target)
        self.assertEqual(self.custody.read_descriptor.call_count, 32)

    def test_duplicate_coordinate_keeps_the_original_refusal(self):
        prepared, payloads, _ = complete_input()
        first, second = list(payloads)[:2]
        payloads[second] = payloads[first]
        with self.assertRaisesRegex(ValueError, "duplicate qualification coordinates"):
            self.select(prepared, payloads)

    def test_missing_target_keeps_the_original_refusal(self):
        prepared, payloads, target = complete_input()
        for row in prepared["capture_plan"]["operation_manifest"]["operations"]:
            if row["operation_id"] == target:
                row["system"] = "controlled-other-system"
        with self.assertRaisesRegex(ValueError, "all 32 qualification coordinates"):
            self.select(prepared, payloads)


if __name__ == "__main__":
    unittest.main()
