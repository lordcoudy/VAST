"""Bounded actual-message guardian journal contract; no publication authority."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from unittest import mock
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from publication_guardian_operational_recorder_v1 import GuardianOperationalRecorder, GuardianOperationalError, DEFAULT_BUDGETS, STUDY_BUDGET_OVERRIDES

BRANCHES=("plate_number", "vehicle_type", "damage", "foreign_object")

def headers(root: Path):
    descriptor={"path":str(root / "input.json"),"size_bytes":1,"sha256":"a"*64}
    values={}
    for branch in BRANCHES:
        for resource in ("cpu", "gpu"):
            values[(branch,resource)]={
                "schema_version":1,"artifact_kind":"vast_guardian_operational_request_journal_v1",
                "record_kind":"header","digest_algorithm":"sha256",
                "descriptors":{name:dict(descriptor) for name in ("accounting_input","service_authority","capability_manifest","execution_config","execution_code_closure","model_authority","source_plan","native_protocol_source","proxy_protocol_source")},
                "lifecycle_id":"b"*32,"owner":{"uid":1000,"gid":1000,"pid":123,"proc_stat_starttime_ticks":456},
                "route":{"branch":branch,"resource":resource},
                "protocols":[{"id":0,"schema_version":1,"message_type":"analytics_execute","transport":"unix_seqpacket_scm_rights_sealed_memfd","source_descriptor":"native_protocol_source"}],
                "contexts":[{"id":0,"protocol":0,"run_id":"frozen-run","arm_id":"a"*64,"system":"gstreamer_custom","policy":"forced_resource"}],
                "front_workers":[{"id":0,"worker_id":"checkpoint-stream-0","stream_id":0}],
                "bindings":[{"id":0,"context":0,"front_worker":0}],
                "worker_capability":{},"initial_counters":{name:0 for name in ("requests_started","requests_completed","requests_failed","unfinished_requests","connections_accepted","event_count")},
                "budgets":dict(DEFAULT_BUDGETS),"sha256":"c"*64,
            }
    return values

def message(branch="plate_number",resource="cpu"):
    return {"schema_version":1,"message_type":"analytics_execute","run_id":"frozen-run","arm_id":"a"*64,"gstreamer_worker_id":"checkpoint-stream-0","request_id":"d"*64,"frame":{"input_frame_key":"dataset:0:"+"e"*64+":0:0","stream_id":0,"frame_id":0,"transport_pts_ns":0,"branch":branch},"decision":{"decision_id":"original-decision","selected_resource":resource}}

class RecorderTests(unittest.TestCase):
    def test_study_frame_and_sequence_bounds_do_not_relax_legacy(self):
        from publication_operational_request_domain_v1 import (
            validate_guardian_event_v1, OperationalDomainError)
        scope = {"kind": "finite-component-study", "plan_sha256": "a" * 64,
                 "max_frame_id": 441, "max_requests_per_arm": 10608,
                 "max_operations": 32}
        for study in (False, True):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                hs = headers(root)
                if study:
                    for header in hs.values():
                        header["study_scope"] = scope
                        header["artifact_kind"] = "vast_finite_study_guardian_journal_v1"
                        header["budgets"].update(STUDY_BUDGET_OVERRIDES)
                rec = GuardianOperationalRecorder(root / "journal", hs)
                try:
                    msg = message()
                    msg["frame"]["frame_id"] = 441
                    if not study:
                        with self.assertRaises(GuardianOperationalError):
                            rec.begin(msg, ("plate_number", "cpu"), "gstreamer", 1, 10608)
                        self.assertEqual(rec.snapshot()["requests_started"], 0)
                    else:
                        token = rec.begin(msg, ("plate_number", "cpu"), "gstreamer", 1, 10608)
                        rec.terminal(token, None, outcome="failed", send="closed")
                finally:
                    rec.close()
                if study:
                    rows = [json.loads(line) for line in
                            (root / "journal" / "plate_number-cpu.jsonl").read_bytes().splitlines()]
                    validate_guardian_event_v1(rows[1], previous_sha256=rows[0]["sha256"],
                                               study_scope=scope)
                    with self.assertRaises(OperationalDomainError):
                        validate_guardian_event_v1(rows[1], previous_sha256=rows[0]["sha256"])
                    for field, value in (("frame_id", 442), ("local_seq", 10609)):
                        bad = dict(rows[1], **{field: value})
                        with self.assertRaises(OperationalDomainError):
                            validate_guardian_event_v1(bad, previous_sha256=rows[0]["sha256"],
                                                       study_scope=scope)

    def test_idle_study_snapshot_is_prefix_of_actual_closed_pool_without_resetting_counters(self):
        import time
        from publication_operational_request_domain_v1 import payload_with_sha256_v1
        import run_canonical_systems_study_v1 as driver
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);hs=headers(root)
            scope={"kind":"finite-component-study","plan_sha256":"a"*64,"max_frame_id":441,"max_requests_per_arm":10608,"max_operations":32}
            for route,header in hs.items():
                header.update(study_scope=scope,artifact_kind="vast_finite_study_guardian_journal_v1")
                header["budgets"].update(STUDY_BUDGET_OVERRIDES)
                second=dict(header["contexts"][0],id=1,run_id="later-run")
                header["contexts"].append(second);header["bindings"].append({"id":1,"context":1,"front_worker":0})
                header.pop("sha256");hs[route]=payload_with_sha256_v1(header)
            rec=GuardianOperationalRecorder(root/"journal",hs)
            try:
                token=rec.begin(message(),("plate_number","cpu"),"gstreamer",1,1)
                output=root/"snapshot";output.mkdir()
                with self.assertRaisesRegex(GuardianOperationalError,"idle"):rec.capture_study_arm_v1("frozen-run",output,deadline=time.monotonic()+5)
                rec.terminal(token,{"original":True},outcome="completed",send="sent")
                before=rec.snapshot();snapshot=rec.capture_study_arm_v1("frozen-run",output,deadline=time.monotonic()+5)
                self.assertEqual(rec.snapshot(),before);self.assertEqual(len(snapshot["decoded"]),1)
                later=message();later.update(run_id="later-run",request_id="9"*64)
                token=rec.begin(later,("plate_number","cpu"),"gstreamer",2,1)
                rec.terminal(token,{"later":True},outcome="completed",send="sent")
                group=rec.finish({"requests_started":2,"requests_completed":2,"requests_failed":0,"connections_accepted":2,
                    "requests_by_worker":{b+":"+r:2*int((b,r)==("plate_number","cpu")) for b in BRANCHES for r in ("cpu","gpu")}})
                pool_ref=driver.write_json(root/"pool.json",{"operational_group":group})
                commands=driver.Commands(root,time.monotonic()+60)
                driver.verify_guardian_ranges(pool_ref,snapshot["ranges"],commands)
                self.assertEqual(json.loads(Path(group["path"]).read_bytes())["counts"]["requests_started"],2)
                path=Path(snapshot["ranges"][0]["original_journal_path"])
                raw=path.read_bytes();path.write_bytes(b"X"+raw[1:])
                with self.assertRaisesRegex(ValueError,"journal descriptor drifted"):
                    driver.verify_guardian_ranges(pool_ref,snapshot["ranges"],commands)
            finally:rec.close()

    def make(self, root, **budgets):
        hs=headers(root)
        if budgets:
            for header in hs.values():header["budgets"].update(budgets)
        return GuardianOperationalRecorder(root / "journal",hs,budgets=budgets or None,clock_ns=lambda:123456789)

    def test_roundtrip_pair_and_physical_companion(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rec=self.make(root)
            token=rec.begin(message(),("plate_number","cpu"),"gstreamer",1,1)
            rec.terminal(token,{"original":True},outcome="completed",send="sent")
            descriptor=rec.finish({"requests_started":1,"requests_completed":1,"requests_failed":0,"connections_accepted":2,"requests_by_worker":{b+":"+r:int((b,r)==("plate_number","cpu")) for b in BRANCHES for r in ("cpu","gpu")}})
            raw=Path(descriptor["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(),descriptor["sha256"])
            group=json.loads(raw);self.assertEqual(len(group["journals"]),8)
            row=next(x for x in group["journals"] if x["route"]=="plate_number:cpu")
            events=[json.loads(x) for x in Path(row["path"]).read_bytes().splitlines()]
            self.assertEqual(set(events[1]),{"type","seq","request_seq","connection","local_seq","binding","request_id","input_key","frame_id","pts_ns","decision_id","control_sha256","at_ns","sha256"})
            self.assertEqual(events[2]["begin_seq"],events[1]["seq"])
            self.assertEqual(group["counts"]["connections_accepted"],2)

    def test_actual_stream_rejected_without_suffix_inference(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec=self.make(Path(tmp));msg=message();msg["frame"]["stream_id"]=1
            with self.assertRaises(GuardianOperationalError):rec.begin(msg,("plate_number","cpu"),"gstreamer",1,1)
            with self.assertRaises(GuardianOperationalError):rec.begin(message(),("plate_number","cpu"),"gstreamer",1,1)
            rec.close()

    def test_pending_exhaustion_sticky_but_original_terminal_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec=self.make(Path(tmp),max_pending=1)
            token=rec.begin(message(),("plate_number","cpu"),"gstreamer",1,1)
            with self.assertRaises(GuardianOperationalError):rec.begin(message(),("plate_number","cpu"),"gstreamer",2,1)
            rec.terminal(token,None,outcome="failed",send="closed")
            with self.assertRaises(GuardianOperationalError):rec.finish({"requests_started":1,"requests_completed":0,"requests_failed":1,"connections_accepted":2})
            self.assertIsNotNone(rec.group_descriptor)

    def test_terminal_duplicate_and_unfinished_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec=self.make(Path(tmp));token=rec.begin(message(),("plate_number","cpu"),"gstreamer",1,1)
            rec.terminal(token,None,outcome="failed",send="failed")
            with self.assertRaises(GuardianOperationalError):rec.terminal(token,None,outcome="failed",send="failed")
            rec.close()
        with tempfile.TemporaryDirectory() as tmp:
            rec=self.make(Path(tmp));rec.begin(message(),("plate_number","cpu"),"gstreamer",1,1)
            with self.assertRaises(GuardianOperationalError):rec.finish({"requests_started":1,"requests_completed":0,"requests_failed":0,"connections_accepted":1})

    def test_overlimit_field_and_local_sequence_fail_before_begin(self):
        for changes in ("input", "local"):
            with tempfile.TemporaryDirectory() as tmp:
                rec=self.make(Path(tmp));msg=message()
                if changes=="input":msg["frame"]["input_frame_key"]="x"*137
                with self.assertRaises(GuardianOperationalError):rec.begin(msg,("plate_number","cpu"),"gstreamer",1,6745 if changes=="local" else 1)
                self.assertEqual(rec.snapshot()["requests_started"],0)
                rec.close()

    def test_exact_maximum_valid_begin_and_last_terminal_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hs = headers(root)
            for header in hs.values():
                header["bindings"][0]["id"] = 221
            rec = GuardianOperationalRecorder(root / "journal", hs, clock_ns=lambda: (1 << 64) - 1)
            rec._seq = 999998
            rec._counts["requests_started"] = 499999
            msg = message()
            msg["frame"].update(input_frame_key="i" * 136, frame_id=280, transport_pts_ns=(1 << 64) - 1)
            msg["decision"]["decision_id"] = "d" * 157
            token = rec.begin(msg, ("plate_number", "cpu"), "gstreamer", 1000000, 6744)
            rec.terminal(token, {"response": True}, outcome="completed", send="sent")
            rec.close()
            raw = (root / "journal" / "plate_number-cpu.jsonl").read_bytes().splitlines(keepends=True)
            self.assertEqual(len(raw[1]), 742)
            # 'sent' is4chars; worst failed/closed is6 andcompleted9.
            self.assertEqual(len(raw[2]), 254)

    def test_proxy_uses_observed_worker_stream_and_null_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hs = headers(root)
            for header in hs.values():
                header["protocols"][0].update(message_type="infer_request", source_descriptor="proxy_protocol_source")
                header["front_workers"][0]["worker_id"] = "capability-worker"
            rec = GuardianOperationalRecorder(root / "journal", hs)
            msg = message()
            msg.pop("gstreamer_worker_id")
            msg.pop("decision")
            msg.update(message_type="infer_request", worker_id="capability-worker", engine="openvino_cpu")
            token = rec.begin(msg, ("plate_number", "cpu"), "worker", 1, 1)
            rec.terminal(token, None, outcome="failed", send="closed")
            rec.close()
            begin = json.loads((root / "journal" / "plate_number-cpu.jsonl").read_bytes().splitlines()[1])
            self.assertIsNone(begin["decision_id"])

    def test_event_terminal_reservation_rejects_before_begin(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self.make(Path(tmp), max_events=1)
            with self.assertRaises(GuardianOperationalError):
                rec.begin(message(), ("plate_number", "cpu"), "gstreamer", 1, 1)
            self.assertEqual(rec.snapshot()["requests_started"], 0)
            rec.close()

    def test_journal_substitution_fails_custody_without_appending(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            rec = self.make(root)
            path = root / "journal" / "plate_number-cpu.jsonl"
            original = path.read_bytes()
            if sys.platform == "win32":
                rec.close()
                self.skipTest("POSIX open-inode substitution contract")
            path.rename(path.with_suffix(".original"))
            path.write_bytes(original)
            with self.assertRaises(GuardianOperationalError):
                rec.begin(message(), ("plate_number", "cpu"), "gstreamer", 1, 1)
            self.assertEqual(path.read_bytes(), original)
            rec.close()

    def test_persistence_failure_is_sticky(self):
        with tempfile.TemporaryDirectory() as tmp:
            rec = self.make(Path(tmp))
            row = rec._routes[("plate_number", "cpu")]
            with mock.patch.object(rec, "_write", side_effect=OSError("injected disk failure")):
                with self.assertRaises(GuardianOperationalError):
                    rec.begin(message(), ("plate_number", "cpu"), "gstreamer", 1, 1)
            with self.assertRaises(GuardianOperationalError):
                rec.begin(message(), ("plate_number", "cpu"), "gstreamer", 1, 1)
            self.assertEqual(rec.snapshot()["requests_started"], 0)
            rec.close()

if __name__=="__main__":unittest.main()

