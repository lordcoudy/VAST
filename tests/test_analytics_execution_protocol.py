from __future__ import annotations

import hashlib
import json
import os
import socket
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from analytics_execution_protocol import (  # noqa: E402
    ENGINE_OPENVINO_CPU,
    ProtocolError,
    canonical_sha256,
    close_fds,
    create_sealed_memfd,
    receive_packet,
    send_packet,
    validate_inference_request,
    verify_sealed_memfd,
)


SHA_A = hashlib.sha256(b"a").hexdigest()
SHA_B = hashlib.sha256(b"b").hexdigest()
SHA_C = hashlib.sha256(b"c").hexdigest()


def request_for(payload: bytes) -> dict[str, object]:
    return {
        "schema_version": 1,
        "message_type": "infer_request",
        "request_id": "request-0001",
        "run_id": "run-0001",
        "arm_id": "arm-0001",
        "worker_id": "worker-plate-cpu-0001",
        "frame": {
            "input_frame_key": "dataset:stream-0:frame-7",
            "stream_id": 0,
            "frame_id": 7,
            "transport_pts_ns": 233_333_333,
            "branch": "plate_number",
        },
        "engine": ENGINE_OPENVINO_CPU,
        "deadline_monotonic_ns": 9_999_999_999_999_999,
        "model": {
            "model_id": "topology-proxy-plate-v1",
            "source_sha256": SHA_A,
            "runtime_artifact_sha256": SHA_B,
            "runtime_weights_sha256": SHA_C,
        },
        "tensor": {
            "name": "input",
            "dtype": "uint8",
            "layout": "NHWC",
            "shape": [1, 2, 2, 3],
            "byte_length": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "preprocessing_contract_sha256": SHA_A,
        },
        "expected_output_contract_sha256": SHA_B,
    }


@unittest.skipUnless(
    hasattr(socket, "SOCK_SEQPACKET") and hasattr(os, "memfd_create"),
    "Linux SOCK_SEQPACKET and memfd are required",
)
class AnalyticsExecutionProtocolTests(unittest.TestCase):
    def test_canonical_packet_round_trip_transfers_one_sealed_memfd(self) -> None:
        left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        payload = bytes(range(12))
        fd = create_sealed_memfd("vast-test-input", payload)
        try:
            request = request_for(payload)
            send_packet(left, request, fds=(fd,))
            received, received_fds = receive_packet(right, expected_fds=1)
            self.assertEqual(received, request)
            self.assertEqual(
                verify_sealed_memfd(
                    received_fds[0],
                    expected_bytes=len(payload),
                    expected_sha256=hashlib.sha256(payload).hexdigest(),
                ),
                payload,
            )
            with self.assertRaises(OSError):
                os.pwrite(received_fds[0], b"X", 0)
            close_fds(received_fds)
        finally:
            os.close(fd)
            left.close()
            right.close()

    def test_noncanonical_json_and_duplicate_keys_are_rejected(self) -> None:
        cases = (
            b'{"message_type": "hello", "message_type":"hello"}',
            b'{"message_type": "hello"}',
            b'{"message_type":"hello","value":NaN}',
        )
        for raw in cases:
            with self.subTest(raw=raw):
                left, right = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
                try:
                    left.send(raw)
                    with self.assertRaises(ProtocolError):
                        receive_packet(right)
                finally:
                    left.close()
                    right.close()

    def test_request_schema_binds_tensor_size_digest_and_cpu_weights(self) -> None:
        payload = bytes(range(12))
        request = request_for(payload)
        self.assertEqual(validate_inference_request(request), request)

        changed = json.loads(json.dumps(request))
        changed["tensor"]["byte_length"] = 11
        with self.assertRaisesRegex(ProtocolError, "tensor byte_length"):
            validate_inference_request(changed)

        changed = json.loads(json.dumps(request))
        changed["tensor"]["sha256"] = "0" * 64
        self.assertEqual(validate_inference_request(changed), changed)

        changed = json.loads(json.dumps(request))
        changed["model"]["runtime_weights_sha256"] = None
        with self.assertRaisesRegex(ProtocolError, "OpenVINO CPU.*weights"):
            validate_inference_request(changed)

        changed = json.loads(json.dumps(request))
        changed["unexpected"] = True
        with self.assertRaisesRegex(ProtocolError, "fields have drifted"):
            validate_inference_request(changed)

    def test_canonical_identity_is_stable_and_rejects_nonfinite_numbers(self) -> None:
        first = canonical_sha256({"b": 2, "a": 1})
        second = canonical_sha256({"a": 1, "b": 2})
        self.assertEqual(first, second)
        with self.assertRaises(ProtocolError):
            canonical_sha256({"invalid": float("nan")})


if __name__ == "__main__":
    unittest.main()
