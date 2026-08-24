from __future__ import annotations

import hashlib
import os
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "deploy" / "openvino" / "checkpoint"))

from analytics_execution_protocol import ProtocolError, create_sealed_memfd  # noqa: E402
from checkpoint_openvino_gva_launcher import (  # noqa: E402
    ENGINEERING_BLOCKERS,
    GVAWorkerSpec,
    INDEPENDENT_PROCESSES,
    SHARED_VIDEO_DAG,
    audit_openvino_gva_run,
    build_dispatch_contexts,
    build_openvino_gva_worker_specs,
    dispatch_verified_tensor,
)
from checkpoint_openvino_gva_container_smoke import _fixture_command  # noqa: E402
from openvino_gva_gst_adapter import build_gst_pipeline  # noqa: E402


BRANCHES = ("plate_number", "vehicle_type", "damage", "foreign_object")
GVA_SDK_BINDING = "intel_dl_streamer_gva_verified_preprocess_gst_buffer_v1"
GVA_TENSOR_ORIGIN = "verified_preprocess_src_pad"
GVA_PTS_ORIGIN = "GST_BUFFER_PTS"
PAYLOAD = bytes(range(48))
PAYLOAD_SHA = hashlib.sha256(PAYLOAD).hexdigest()
PREPROCESS_SHA = hashlib.sha256(b"gva-preprocess").hexdigest()


class _CapturingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[dict[str, object], bytes, dict[str, object]]] = []

    def execute(self, *, context, tensor, tensor_descriptor):
        payload = bytes(tensor)
        self.calls.append((dict(context), payload, dict(tensor_descriptor)))
        return {
            "schema_version": 1,
            "artifact_kind": "vast_openvino_gva_execution_bridge_result",
            "claim_status": "engineering_runtime_terminal_nonpublication",
            "branch": context["branch"],
            "selected_resource": context["selected_resource"],
            "publication_ready": False,
            "accepted_evidence_written": False,
            "terminal_event": {
                "protocol_version": 3,
                "worker_id": context["topology_worker_id"],
                "event_kind": "branch_complete",
                "branch_id": context["branch"],
                "admission_id": context["admission_id"],
                "payload_sha256": context["payload_sha256"],
            },
        }


def _ready(spec: GVAWorkerSpec, pid: int) -> dict[str, object]:
    shared = spec.topology_kind == SHARED_VIDEO_DAG
    return {
        "schema_version": 1,
        "message_type": "openvino_gva_worker_ready",
        "worker_id": spec.worker_id,
        "topology_kind": spec.topology_kind,
        "stream_id": spec.stream_id,
        "branches": list(spec.branches),
        "pid": pid,
        "pipeline": {
            "fresh_pipeline_count": 1,
            "decoder_count": 1,
            "tee_count": 1 if shared else 0,
            "tensor_convert_count": 4 if shared else 1,
            "appsink_count": 4 if shared else 1,
            "post_preprocess_binding": "dlstreamer_tensor_convert_src_to_appsink_v1",
        },
    }


def _drained(spec: GVAWorkerSpec, pid: int) -> dict[str, object]:
    return {
        "schema_version": 1,
        "message_type": "openvino_gva_worker_drained",
        "worker_id": spec.worker_id,
        "pid": pid,
        "terminal_branches": list(spec.branches),
        "reset": {
            "fresh_pipeline_count": 1,
            "start_state": "NULL",
            "pre_start_queue_depths": {branch: 0 for branch in spec.branches},
            "admission_stopped_before_drain": True,
            "terminal_state": "DRAINED",
            "post_stop_state": "NULL",
            "post_stop_queue_depths": {branch: 0 for branch in spec.branches},
        },
    }


def _terminal(context: dict[str, object]) -> dict[str, object]:
    return {
        "terminal_event": {
            "protocol_version": 3,
            "worker_id": context["topology_worker_id"],
            "sequence": context["event_sequence"],
            "run_id": context["run_id"],
            "trace_id": context["topology_worker_trace_id"],
            "stream_id": context["stream_id"],
            "frame_id": context["frame_id"],
            "input_frame_key": context["input_frame_key"],
            "topology_kind": context["topology_kind"],
            "event_kind": "branch_complete",
            "stage": context["branch"],
            "branch_id": context["branch"],
            "execution_id": context["terminal_execution_id"],
            "parent_execution_ids": [context["parent_execution_id"]],
            "timestamp_ms": 1000,
            "admission_id": context["admission_id"],
            "payload_sha256": context["payload_sha256"],
            "terminal_reason": "engineering_test_completed",
            "objects": 0,
            "detector": "engineering-test",
            "backend": "engineering-test",
        },
        "publication_ready": False,
        "accepted_evidence_written": False,
    }


class OpenVINOGVATopologyLauncherTests(unittest.TestCase):
    def test_full_topology_specs_are_exact_24_processes_or_6_graphs(self) -> None:
        baseline = build_openvino_gva_worker_specs(INDEPENDENT_PROCESSES)
        shared = build_openvino_gva_worker_specs(SHARED_VIDEO_DAG)

        self.assertEqual(len(baseline), 24)
        self.assertEqual(len(shared), 6)
        self.assertEqual(len({item.worker_id for item in baseline}), 24)
        self.assertEqual(len({item.worker_id for item in shared}), 6)
        for stream_id in range(6):
            stream_baseline = [item for item in baseline if item.stream_id == stream_id]
            self.assertEqual({item.branches for item in stream_baseline}, {(branch,) for branch in BRANCHES})
            stream_shared = [item for item in shared if item.stream_id == stream_id]
            self.assertEqual(len(stream_shared), 1)
            self.assertEqual(stream_shared[0].branches, BRANCHES)

    def test_container_smoke_fixture_commands_are_bounded_raw_access_units(self) -> None:
        h264 = _fixture_command("h264", Path("/tmp/synthetic.264"), width=32, height=32)
        h265 = _fixture_command("h265", Path("/tmp/synthetic.265"), width=32, height=32)

        self.assertEqual(h264[0], "ffmpeg")
        self.assertEqual(h265[0], "ffmpeg")
        self.assertIn("libx264", h264)
        self.assertIn("libx265", h265)
        self.assertEqual(h264[h264.index("-f") + 1], "lavfi")
        self.assertEqual(h264[-2:], ["-y", "/tmp/synthetic.264"])
        self.assertEqual(h265[-2:], ["-y", "/tmp/synthetic.265"])
        self.assertNotIn("http", " ".join(h264 + h265))

    def test_real_pipeline_text_has_one_decode_per_process_and_shared_tee_only(self) -> None:
        baseline = build_gst_pipeline(
            topology_kind=INDEPENDENT_PROCESSES,
            codec="h264",
            branches=("plate_number",),
        )
        shared = build_gst_pipeline(
            topology_kind=SHARED_VIDEO_DAG,
            codec="h265",
            branches=BRANCHES,
        )

        self.assertEqual(baseline.count("avdec_h264 name=gva_decoder"), 1)
        self.assertNotIn("tee name=gva_shared_tee", baseline)
        self.assertEqual(baseline.count("tensor_convert name=gva_tensor_convert_"), 1)
        self.assertEqual(baseline.count("appsink name=gva_tensor_sink_"), 1)
        self.assertEqual(shared.count("avdec_h265 name=gva_decoder"), 1)
        self.assertEqual(shared.count("tee name=gva_shared_tee"), 1)
        self.assertEqual(shared.count("tensor_convert name=gva_tensor_convert_"), 4)
        self.assertEqual(shared.count("appsink name=gva_tensor_sink_"), 4)
        self.assertNotIn("! other/tensors", baseline)
        self.assertNotIn("! other/tensors", shared)

    def test_dispatch_contexts_bind_one_common_admission_per_stream_without_relabel(self) -> None:
        specs = build_openvino_gva_worker_specs(INDEPENDENT_PROCESSES)
        contexts = build_dispatch_contexts(
            specs=specs,
            run_id="run-gva-launcher-0001",
            arm_id="arm-gva-launcher-h264-baseline",
            codec="h264",
            payload_sha256=PAYLOAD_SHA,
            preprocessing_contract_sha256=PREPROCESS_SHA,
            transport_pts_ns=333_333_333,
        )

        self.assertEqual(len(contexts), 24)
        for stream_id in range(6):
            values = [
                context
                for (worker_id, _), context in contexts.items()
                if context["stream_id"] == stream_id and worker_id.startswith(f"gva-stream-{stream_id}-")
            ]
            self.assertEqual(len(values), 4)
            self.assertEqual(len({value["admission_id"] for value in values}), 1)
            self.assertEqual({value["payload_sha256"] for value in values}, {PAYLOAD_SHA})
            self.assertEqual({value["branch"] for value in values}, set(BRANCHES))
            self.assertEqual({value["sdk_binding"] for value in values}, {GVA_SDK_BINDING})
            self.assertEqual({value["tensor_origin"] for value in values}, {GVA_TENSOR_ORIGIN})
            self.assertEqual({value["pts_origin"] for value in values}, {GVA_PTS_ORIGIN})
        self.assertEqual(
            {context["selected_resource"] for context in contexts.values()},
            {"cpu", "gpu"},
        )

    @unittest.skipUnless(hasattr(os, "memfd_create"), "Linux sealed memfd is required")
    def test_verified_gst_tensor_is_owned_and_dispatched_to_ready_bridge(self) -> None:
        spec = build_openvino_gva_worker_specs(INDEPENDENT_PROCESSES, stream_count=1)[0]
        context = build_dispatch_contexts(
            specs=(spec,),
            run_id="run-gva-launcher-0001",
            arm_id="arm-gva-launcher-h264-baseline",
            codec="h264",
            payload_sha256=PAYLOAD_SHA,
            preprocessing_contract_sha256=PREPROCESS_SHA,
            transport_pts_ns=333_333_333,
        )[(spec.worker_id, spec.branches[0])]
        message = {
            "schema_version": 1,
            "message_type": "openvino_gva_verified_tensor",
            "worker_id": spec.worker_id,
            "topology_kind": spec.topology_kind,
            "stream_id": spec.stream_id,
            "branch": spec.branches[0],
            "context": context,
            "tensor_descriptor": {
                "name": "input",
                "dtype": "uint8",
                "layout": "NHWC",
                "shape": [1, 4, 4, 3],
                "preprocessing_contract_sha256": PREPROCESS_SHA,
                "contiguous": True,
                "read_only": True,
            },
            "tensor": {"byte_length": len(PAYLOAD), "sha256": PAYLOAD_SHA},
            "gst_evidence": {
                "caps": "other/tensors, num_tensors=(uint)1, types=(string)uint8",
                "buffer_pts_ns": 333_333_333,
                "buffer_size": len(PAYLOAD),
                "map_mode": "GST_MAP_READ_copied_before_unmap",
                "origin_element": f"gva_tensor_convert_{spec.branches[0]}",
            },
        }
        bridge = _CapturingBridge()
        fd = create_sealed_memfd("gva-launcher-test", PAYLOAD)
        result = dispatch_verified_tensor(
            bridge=bridge,
            spec=spec,
            message=message,
            fds=[fd],
            expected_context=context,
        )

        self.assertEqual(len(bridge.calls), 1)
        self.assertEqual(bridge.calls[0][1], PAYLOAD)
        self.assertEqual(result["terminal_event"]["event_kind"], "branch_complete")
        self.assertFalse(result["publication_ready"])
        with self.assertRaises(OSError):
            os.fstat(fd)

        relabelled = {**message, "branch": "damage"}
        fd = create_sealed_memfd("gva-launcher-relabel", PAYLOAD)
        with self.assertRaisesRegex(ProtocolError, "branch"):
            dispatch_verified_tensor(
                bridge=bridge,
                spec=spec,
                message=relabelled,
                fds=[fd],
                expected_context=context,
            )

        drifted = {**message, "context": {**context, "admission_id": "forged-admission"}}
        fd = create_sealed_memfd("gva-launcher-context-drift", PAYLOAD)
        with self.assertRaisesRegex(ProtocolError, "launcher-owned dispatch context"):
            dispatch_verified_tensor(
                bridge=bridge,
                spec=spec,
                message=drifted,
                fds=[fd],
                expected_context=context,
            )
        self.assertEqual(len(bridge.calls), 1)

    def test_exact_terminal_and_reset_closure_is_engineering_only(self) -> None:
        specs = build_openvino_gva_worker_specs(SHARED_VIDEO_DAG)
        pids = {spec.worker_id: 5000 + index for index, spec in enumerate(specs)}
        contexts = build_dispatch_contexts(
            specs=specs,
            run_id="run-gva-audit-0001",
            arm_id="arm-gva-audit-h264-shared",
            codec="h264",
            payload_sha256=PAYLOAD_SHA,
            preprocessing_contract_sha256=PREPROCESS_SHA,
            transport_pts_ns=333_333_333,
        )
        terminals = {
            (spec.worker_id, branch): _terminal(contexts[(spec.worker_id, branch)])
            for spec in specs
            for branch in spec.branches
        }
        audit = audit_openvino_gva_run(
            specs=specs,
            ready_records=[_ready(spec, pids[spec.worker_id]) for spec in specs],
            drained_records=[_drained(spec, pids[spec.worker_id]) for spec in specs],
            terminal_results=terminals,
            peer_pids=pids,
            dispatch_contexts=contexts,
        )

        self.assertTrue(audit["engineering_runtime_complete"])
        self.assertEqual(audit["physical_process_count"], 6)
        self.assertEqual(audit["terminal_count"], 24)
        self.assertTrue(audit["common_admission_required"])
        self.assertTrue(audit["reset_and_terminal_closure_verified"])
        self.assertFalse(audit["publication_ready"])
        self.assertFalse(audit["accepted_evidence_written"])
        self.assertEqual(audit["publication_blockers"], list(ENGINEERING_BLOCKERS))
        self.assertIn(
            "openvino_gva_topology_engineering_runtime_not_accepted",
            audit["publication_blockers"],
        )
        self.assertTrue(
            all("not_implemented" not in blocker for blocker in audit["publication_blockers"])
        )

        terminals.pop(next(iter(terminals)))
        with self.assertRaisesRegex(ProtocolError, "terminal coverage"):
            audit_openvino_gva_run(
                specs=specs,
                ready_records=[_ready(spec, pids[spec.worker_id]) for spec in specs],
                drained_records=[_drained(spec, pids[spec.worker_id]) for spec in specs],
                terminal_results=terminals,
                peer_pids=pids,
                dispatch_contexts=contexts,
            )

    def test_audit_requires_full_six_stream_inventory_and_contexts(self) -> None:
        partial = build_openvino_gva_worker_specs(SHARED_VIDEO_DAG, stream_count=5)
        pids = {spec.worker_id: 7000 + index for index, spec in enumerate(partial)}
        contexts = build_dispatch_contexts(
            specs=partial,
            run_id="run-gva-partial-0001",
            arm_id="arm-gva-partial-h265-shared",
            codec="h265",
            payload_sha256=PAYLOAD_SHA,
            preprocessing_contract_sha256=PREPROCESS_SHA,
            transport_pts_ns=333_333_333,
        )
        terminals = {
            key: _terminal(context) for key, context in contexts.items()
        }
        with self.assertRaisesRegex(ProtocolError, "exactly six streams"):
            audit_openvino_gva_run(
                specs=partial,
                ready_records=[_ready(spec, pids[spec.worker_id]) for spec in partial],
                drained_records=[_drained(spec, pids[spec.worker_id]) for spec in partial],
                terminal_results=terminals,
                peer_pids=pids,
                dispatch_contexts=contexts,
            )

        full = build_openvino_gva_worker_specs(SHARED_VIDEO_DAG)
        full_pids = {spec.worker_id: 8000 + index for index, spec in enumerate(full)}
        full_contexts = build_dispatch_contexts(
            specs=full,
            run_id="run-gva-full-0001",
            arm_id="arm-gva-full-h265-shared",
            codec="h265",
            payload_sha256=PAYLOAD_SHA,
            preprocessing_contract_sha256=PREPROCESS_SHA,
            transport_pts_ns=333_333_333,
        )
        full_terminals = {
            key: _terminal(context) for key, context in full_contexts.items()
        }
        with self.assertRaisesRegex(ProtocolError, "dispatch context"):
            audit_openvino_gva_run(
                specs=full,
                ready_records=[_ready(spec, full_pids[spec.worker_id]) for spec in full],
                drained_records=[_drained(spec, full_pids[spec.worker_id]) for spec in full],
                terminal_results=full_terminals,
                peer_pids=full_pids,
                dispatch_contexts=None,
            )


if __name__ == "__main__":
    unittest.main()
