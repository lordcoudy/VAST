#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import time


def main() -> int:
    source_process_id = os.environ["VAST_CHECKPOINT_WORKER_ID"]
    run_id = os.environ["VAST_CHECKPOINT_RUN_ID"]
    dataset_id = os.environ["VAST_CHECKPOINT_DATASET_ID"]
    source_sha256 = os.environ["VAST_CHECKPOINT_SOURCE_SHA256"]
    stream_id = int(os.environ["VAST_CHECKPOINT_STREAM_ID"])
    event_fd = int(os.environ["VAST_CHECKPOINT_ADMISSION_EVENT_FD"])
    ack_fd = int(os.environ["VAST_CHECKPOINT_ADMISSION_ACK_FD"])
    consumer_fds = {
        str(worker_id): int(fd)
        for worker_id, fd in json.loads(os.environ["VAST_CHECKPOINT_ADMISSION_CONSUMER_FDS_JSON"]).items()
    }
    control = os.fdopen(int(os.environ["VAST_CHECKPOINT_CONTROL_FD"]), "r", encoding="utf-8")
    status = os.fdopen(
        int(os.environ["VAST_CHECKPOINT_STATUS_FD"]),
        "w",
        encoding="utf-8",
        buffering=1,
    )
    status.write(f"1 READY {source_process_id} {time.monotonic_ns()}\n")
    start_fields = control.readline().strip().split()
    if len(start_fields) != 6 or start_fields[:2] != ["1", "START"]:
        raise RuntimeError("invalid source fixture START command")
    start_monotonic_ns = int(start_fields[2])
    while time.monotonic_ns() < start_monotonic_ns:
        time.sleep(0.001)
    status.write(f"1 STARTED {source_process_id} {int(time.time() * 1000)}\n")

    payload_sha256 = hashlib.sha256(b"compressed-access-unit").hexdigest()
    pts_ns = 90_000
    message = {
        "protocol_version": 1,
        "source_process_id": source_process_id,
        "sequence": 1,
        "run_id": run_id,
        "dataset_id": dataset_id,
        "stream_id": stream_id,
        "admission_id": f"{run_id}:{stream_id}:admission:1",
        "input_frame_key": f"{dataset_id}:{stream_id}:{source_sha256}:0:{pts_ns}",
        "source_sha256": source_sha256,
        "source_cycle": 0,
        "access_unit_pts_ns": pts_ns,
        "payload_sha256": payload_sha256,
        "payload_size_bytes": 22,
        "schedule_offset_ns": max(1, time.monotonic_ns() - start_monotonic_ns),
        "admission_timestamp_ms": int(time.time() * 1000),
        "event_provenance": "native_common_source_coordinator",
    }
    with os.fdopen(event_fd, "w", encoding="utf-8", buffering=1) as event_output:
        event_output.write(json.dumps(message, separators=(",", ":")) + "\n")
        with os.fdopen(ack_fd, "r", encoding="utf-8") as acknowledgements:
            fields = acknowledgements.readline().strip().split()
        if fields != ["1", "ACK", "1"]:
            raise RuntimeError("invalid source fixture admission ACK")
        delivery = json.dumps(message, separators=(",", ":")) + "\n"
        for fd in consumer_fds.values():
            with os.fdopen(fd, "w", encoding="utf-8", buffering=1) as consumer:
                consumer.write(delivery)

    stop_fields = control.readline().strip().split()
    if len(stop_fields) != 3 or stop_fields[:2] != ["1", "STOP"]:
        raise RuntimeError("invalid source fixture STOP command")
    stop_timestamp_ms = int(stop_fields[2])
    status.write(f"1 ADMISSION_STOPPED {source_process_id} {stop_timestamp_ms}\n")
    status.write(f"1 DRAINED {source_process_id} {stop_timestamp_ms}\n")
    control.close()
    status.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
