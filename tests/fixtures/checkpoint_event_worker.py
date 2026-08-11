#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "shared"), required=True)
    parser.add_argument("--branches", required=True)
    parser.add_argument("--sleep-after", type=float, default=0.0)
    parser.add_argument("--sleep-before-ready", type=float, default=0.0)
    parser.add_argument("--omit-branch", default="")
    parser.add_argument("--admission-linked", action="store_true")
    args = parser.parse_args()

    event_fd = int(os.environ["VAST_CHECKPOINT_EVENT_FD"])
    worker_id = os.environ["VAST_CHECKPOINT_WORKER_ID"]
    run_id = os.environ["VAST_CHECKPOINT_RUN_ID"]
    topology_kind = os.environ["VAST_CHECKPOINT_TOPOLOGY_KIND"]
    stream_id = int(os.environ["VAST_CHECKPOINT_STREAM_ID"])
    selected_branch = os.environ["VAST_CHECKPOINT_BRANCH_ID"]
    branches = [value for value in args.branches.split(",") if value]
    trace_id = f"{run_id}:{stream_id}:0"
    input_frame_key = f"contract-fixture:{stream_id}:pts-0"
    admission_id = ""
    payload_sha256 = ""
    protocol_version = 1
    sequence = 0
    timestamp_ms = int(time.time() * 1000)

    control = None
    status = None
    if "VAST_CHECKPOINT_CONTROL_FD" in os.environ:
        control = os.fdopen(int(os.environ["VAST_CHECKPOINT_CONTROL_FD"]), "r", encoding="utf-8")
        status = os.fdopen(
            int(os.environ["VAST_CHECKPOINT_STATUS_FD"]),
            "w",
            encoding="utf-8",
            buffering=1,
        )
        if args.sleep_before_ready > 0:
            time.sleep(args.sleep_before_ready)
        status.write(f"1 READY {worker_id} {time.monotonic_ns()}\n")
        start_fields = control.readline().strip().split()
        if len(start_fields) != 6 or start_fields[:2] != ["1", "START"]:
            raise RuntimeError("invalid fixture START command")
        start_monotonic_ns = int(start_fields[2])
        while time.monotonic_ns() < start_monotonic_ns:
            time.sleep(0.001)
        timestamp_ms = int(time.time() * 1000)
        status.write(f"1 STARTED {worker_id} {timestamp_ms}\n")
        if os.environ.get("VAST_TEST_DECODER_PLACEMENT_STATUS") == "verified":
            status.write(f"1 DECODER_PLACEMENT_VERIFIED {worker_id} {int(time.time() * 1000)}\n")

    if args.admission_linked:
        data_fd = int(os.environ["VAST_CHECKPOINT_ADMISSION_DATA_FD"])
        with os.fdopen(data_fd, "r", encoding="utf-8") as delivery:
            admitted = json.loads(delivery.readline())
        protocol_version = 2
        input_frame_key = str(admitted["input_frame_key"])
        admission_id = str(admitted["admission_id"])
        payload_sha256 = str(admitted["payload_sha256"])
        timestamp_ms = max(timestamp_ms, int(admitted["admission_timestamp_ms"]))

    with os.fdopen(event_fd, "w", encoding="utf-8", buffering=1) as output:
        def emit(event_kind: str, stage: str, branch_id: str, execution_id: str, parents: list[str]) -> None:
            nonlocal sequence, timestamp_ms
            sequence += 1
            timestamp_ms += 1
            output.write(
                json.dumps(
                    {
                        "protocol_version": protocol_version,
                        "worker_id": worker_id,
                        "sequence": sequence,
                        "run_id": run_id,
                        "trace_id": trace_id,
                        "stream_id": stream_id,
                        "frame_id": 0,
                        "input_frame_key": input_frame_key,
                        "topology_kind": topology_kind,
                        "event_kind": event_kind,
                        "stage": stage,
                        "branch_id": branch_id,
                        "execution_id": execution_id,
                        "parent_execution_ids": parents,
                        "timestamp_ms": timestamp_ms,
                        **(
                            {
                                "admission_id": admission_id,
                                "payload_sha256": payload_sha256,
                            }
                            if protocol_version == 2
                            else {}
                        ),
                    },
                    separators=(",", ":"),
                )
                + "\n"
            )

        if args.mode == "baseline":
            branch = selected_branch
            source = f"{trace_id}:{branch}:source"
            decode = f"{trace_id}:{branch}:decode"
            preprocess = f"{trace_id}:{branch}:preprocess"
            analytics = f"{trace_id}:{branch}:analytics"
            complete = f"{trace_id}:{branch}:complete"
            emit("source_read", "source", branch, source, [])
            emit("stage_complete", f"decode_{branch}", branch, decode, [source])
            emit("stage_complete", f"preprocess_{branch}", branch, preprocess, [decode])
            emit("stage_complete", branch, branch, analytics, [preprocess])
            emit("branch_complete", branch, branch, complete, [analytics])
        else:
            source = f"{trace_id}:shared:source"
            decode = f"{trace_id}:shared:decode"
            preprocess = f"{trace_id}:shared:preprocess"
            emit("source_read", "source", "shared", source, [])
            emit("stage_complete", "decode", "shared", decode, [source])
            emit("stage_complete", "preprocess", "shared", preprocess, [decode])
            for branch in branches:
                if branch == args.omit_branch:
                    continue
                fanout = f"{trace_id}:{branch}:fanout"
                analytics = f"{trace_id}:{branch}:analytics"
                complete = f"{trace_id}:{branch}:complete"
                emit("fanout", "fanout", branch, fanout, [preprocess])
                emit("stage_complete", branch, branch, analytics, [fanout])
                emit("branch_complete", branch, branch, complete, [analytics])
        if args.sleep_after > 0:
            time.sleep(args.sleep_after)
        if control is not None and status is not None:
            stop_fields = control.readline().strip().split()
            if len(stop_fields) != 3 or stop_fields[:2] != ["1", "STOP"]:
                raise RuntimeError("invalid fixture STOP command")
            stop_timestamp_ms = int(stop_fields[2])
            status.write(f"1 ADMISSION_STOPPED {worker_id} {stop_timestamp_ms}\n")
            status.write(f"1 DRAINED {worker_id} {max(stop_timestamp_ms, timestamp_ms)}\n")
            control.close()
            status.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
