from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

from checkpoint_deepstream_protocol_bridge import DeepStreamProtocolBridge  # noqa: E402
from checkpoint_savant_protocol_bridge import (  # noqa: E402
    SAVANT_BRIDGE_IMPLEMENTATION_STATUS,
    SAVANT_FRAME_IDENTITY_KIND,
    SavantProtocolBridge,
    SavantProtocolBridgeError,
)
from test_checkpoint_deepstream_protocol_bridge import (  # noqa: E402
    ANALYTICS_BRANCHES,
    FakePolicyExchange,
    StepClock,
    admission,
    endpoints,
    nvds_identity,
    tensor,
)
from topology_contract import INDEPENDENT_PROCESSES, SHARED_VIDEO_DAG  # noqa: E402


def savant_identity(
    admitted: dict[str, object],
    *,
    module_id: str,
) -> dict[str, object]:
    deepstream = nvds_identity(admitted)
    return {
        "schema_version": 1,
        "artifact_kind": SAVANT_FRAME_IDENTITY_KIND,
        "savant_version": "0.5.17",
        "module_id": module_id,
        "module_frame_id": deepstream["frame_id"],
        "event_origin": "savant_native_frame_callback",
        **{
            key: value
            for key, value in deepstream.items()
            if key not in {"schema_version", "artifact_kind"}
        },
    }


class SavantProtocolBridgeTests(unittest.TestCase):
    def test_shared_module_closes_one_live_protocol_v3_join(self) -> None:
        run_id, module_id = "run-savant-shared", "savant-stream-0-shared-video-dag"
        admitted = admission(run_id)
        placements = {
            branch: ("cpu" if index % 2 == 0 else "gpu")
            for index, branch in enumerate(ANALYTICS_BRANCHES)
        }
        policy = FakePolicyExchange(placements)
        raw_events: list[dict[str, object]] = []

        def sink(line: str) -> None:
            raw_events.append(json.loads(line))

        delegate = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-savant-shared",
            worker_id=module_id,
            topology_kind=SHARED_VIDEO_DAG,
            stream_id=0,
            branch_id=None,
            event_sink=sink,
            policy_exchange=policy,
            analytics_endpoints=endpoints(tuple(ANALYTICS_BRANCHES)),
            clock_ms=StepClock(),
        )
        bridge = SavantProtocolBridge(
            module_id=module_id,
            stream_id=0,
            topology_kind=SHARED_VIDEO_DAG,
            delegate=delegate,
        )
        identity = savant_identity(admitted, module_id=module_id)
        bridge.admit_access_unit(json.dumps(admitted))
        bridge.observe_decoded_frame(identity)
        bridge.observe_preprocessed_frame(identity)
        payloads: dict[str, bytes] = {}
        for branch in ANALYTICS_BRANCHES:
            spec, payloads[branch] = tensor(branch)
            bridge.observe_fanout(identity, branch=branch, tensor_spec=spec)
        for branch in ANALYTICS_BRANCHES:
            result = bridge.execute_branch(
                str(admitted["input_frame_key"]),
                branch,
                tensor_payload=payloads[branch],
                queue_depths={"cpu": 0, "gpu": 0},
                deadline_monotonic_ns=10_000_000_000,
            )
            self.assertEqual(result.selected_resource, placements[branch])

        self.assertEqual(sum(row["event_kind"] == "source_read" for row in raw_events), 1)
        self.assertEqual(sum(row["event_kind"] == "fanout" for row in raw_events), 4)
        self.assertEqual(sum(row["event_kind"] == "branch_complete" for row in raw_events), 4)
        terminal_branches = {
            str(row["branch_id"])
            for row in raw_events
            if row["event_kind"] == "branch_complete"
        }
        self.assertEqual(terminal_branches, set(ANALYTICS_BRANCHES))
        self.assertTrue(
            all(
                row["protocol_version"] == 3
                for row in raw_events
                if row["event_kind"] == "branch_complete"
            )
        )
        self.assertFalse(bridge.publication_ready)
        self.assertFalse(bridge.accepted_evidence_written)
        self.assertEqual(bridge.implementation_status, SAVANT_BRIDGE_IMPLEMENTATION_STATUS)

    def test_baseline_module_is_bound_to_one_branch_and_module_identity(self) -> None:
        run_id = "run-savant-baseline"
        branch = ANALYTICS_BRANCHES[0]
        module_id = f"savant-stream-0-branch-{branch}"
        admitted = admission(run_id)
        delegate = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-savant-baseline",
            worker_id=module_id,
            topology_kind=INDEPENDENT_PROCESSES,
            stream_id=0,
            branch_id=branch,
            event_sink=lambda _line: None,
            policy_exchange=FakePolicyExchange({item: "cpu" for item in ANALYTICS_BRANCHES}),
            analytics_endpoints=endpoints((branch,)),
            clock_ms=StepClock(),
        )
        bridge = SavantProtocolBridge(
            module_id=module_id,
            stream_id=0,
            topology_kind=INDEPENDENT_PROCESSES,
            delegate=delegate,
        )
        identity = savant_identity(admitted, module_id=module_id)
        spec, payload = tensor(branch)
        bridge.admit_access_unit(json.dumps(admitted))
        bridge.observe_decoded_frame(identity)
        bridge.observe_preprocessed_frame(identity, tensor_spec=spec)
        result = bridge.execute_branch(
            str(admitted["input_frame_key"]),
            branch,
            tensor_payload=payload,
            queue_depths={"cpu": 0, "gpu": 0},
            deadline_monotonic_ns=10_000_000_000,
        )
        self.assertEqual(result.selected_resource, "cpu")

    def test_savant_metadata_cannot_relabel_module_frame_or_origin(self) -> None:
        run_id, module_id = "run-savant-negative", "savant-stream-0-shared-video-dag"
        admitted = admission(run_id)
        delegate = DeepStreamProtocolBridge(
            run_id=run_id,
            arm_id="arm-savant-negative",
            worker_id=module_id,
            topology_kind=SHARED_VIDEO_DAG,
            stream_id=0,
            branch_id=None,
            event_sink=lambda _line: None,
            policy_exchange=FakePolicyExchange({item: "cpu" for item in ANALYTICS_BRANCHES}),
            analytics_endpoints=endpoints(tuple(ANALYTICS_BRANCHES)),
            clock_ms=StepClock(),
        )
        bridge = SavantProtocolBridge(
            module_id=module_id,
            stream_id=0,
            topology_kind=SHARED_VIDEO_DAG,
            delegate=delegate,
        )
        bridge.admit_access_unit(json.dumps(admitted))
        identity = savant_identity(admitted, module_id=module_id)
        for field, value in (
            ("module_id", "generic-peoplenet-module"),
            ("module_frame_id", 99),
            ("event_origin", "posthoc_reconstruction"),
            ("savant_version", "0.6.0"),
            ("decoder_factory", "avdec_h264"),
        ):
            bad = copy.deepcopy(identity)
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(SavantProtocolBridgeError):
                bridge.observe_decoded_frame(bad)

    def test_bridge_and_delegate_topology_or_stream_drift_is_rejected(self) -> None:
        delegate = DeepStreamProtocolBridge(
            run_id="run-savant-binding",
            arm_id="arm-savant-binding",
            worker_id="savant-stream-0-shared-video-dag",
            topology_kind=SHARED_VIDEO_DAG,
            stream_id=0,
            branch_id=None,
            event_sink=lambda _line: None,
            policy_exchange=FakePolicyExchange({item: "cpu" for item in ANALYTICS_BRANCHES}),
            analytics_endpoints=endpoints(tuple(ANALYTICS_BRANCHES)),
            clock_ms=StepClock(),
        )
        with self.assertRaises(SavantProtocolBridgeError):
            SavantProtocolBridge(
                module_id="savant-stream-0-shared-video-dag",
                stream_id=1,
                topology_kind=SHARED_VIDEO_DAG,
                delegate=delegate,
            )
        with self.assertRaises(SavantProtocolBridgeError):
            SavantProtocolBridge(
                module_id="savant-stream-0-shared-video-dag",
                stream_id=0,
                topology_kind=INDEPENDENT_PROCESSES,
                delegate=delegate,
            )


if __name__ == "__main__":
    unittest.main()
