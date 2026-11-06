"""Controlled gate-2 comparisons. No Docker, compiler or fixture execution."""
import copy
import hashlib
import json
from pathlib import Path, PureWindowsPath
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as component
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as gate
from tests.fixtures import accepted_policy_fixture_compiler_gate2_setup_v1 as setup

WINDOWS_REPO = PureWindowsPath(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return component.canonical_json_v1(value)


def elf():
    raw = bytearray(96)
    raw[:7] = b"\x7fELF\x02\x01\x01"
    raw[16:18] = (3).to_bytes(2, "little")
    raw[18:20] = (62).to_bytes(2, "little")
    raw[20:24] = (1).to_bytes(4, "little")
    return bytes(raw)


def outcome(stage, adopted=False):
    source = component.component_source_v1("c1" if stage == "C6" else stage.lower())
    code = 0 if stage in ("C1", "C6") else 1 if stage in ("C2", "C3") else -15
    pub = [] if stage in ("C1", "C6") else ["compiler_exit_nonzero"]
    if stage in ("C4", "C5"):
        pub = ["stderr_overflow" if stage == "C4" else "compiler_deadline", "compiler_term_attempted"]
        if adopted:
            pub.append("descendant_exit_nonzero")
        pub.append("compiler_exit_nonzero")
    data = {"stdout": b"", "stderr": b"x" * 1048576 if stage == "C4" else b"as: File size limit exceeded\n" if stage == "C3" else b"diagnostic\n" if stage == "C2" else b"",
            "elf": elf() if stage in ("C1", "C6") else b""}
    channels = {name: {"size_bytes": len(data[name]), "sha256": sha(data[name]), "eof": True,
                "observed_bytes": len(data[name]) + (17 if stage == "C4" and name == "stderr" else 0),
                "discarded_bytes": 17 if stage == "C4" and name == "stderr" else 0}
                for name in ("stdout", "stderr")}
    header = {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_export_v1",
              "source": {"size_bytes": len(source), "sha256": sha(source)},
              "runtime": {"pid": 1, "core": [1, 1], "fsize": [16777216, 16777216],
                          "interpreter_elf64_amd64": True, "compiler_elf64_amd64": True},
              "compiler": {"returncode": code, "started": True, "reaped": True, **channels},
              "elf": {"size_bytes": len(data["elf"]), "sha256": sha(data["elf"]), "available": bool(data["elf"])},
              "causes": pub, "descendants_reaped": True}
    encoded = canonical(header)
    framed = b"VASTCE1\n" + struct.pack("!I", len(encoded)) + encoded
    members = {name: {"size_bytes": len(raw), "persisted": True, "complete": True, "sha256": sha(raw),
                     "observed_bytes": len(raw), "observed_sha256": sha(raw), "close_completed": True}
               for name, raw in data.items()}
    captured = {"complete": True, "header": header, "members": members, "client_stdout_eof": True,
                "header_close_completed": True, "observed_bytes": len(framed) + sum(map(len, data.values()))}
    causes = [] if stage == "C1" else ["owner_wait_status"] if stage != "C6" else ["export_OSError", "attach_incomplete"]
    owner = {"causes": causes, "cid": "a" * 64, "accepted": False, "forced": False,
             "normal_closed": stage == "C1", "receipt_persisted": True, "promotion": None,
             "creation_unknown": False, "start_unknown": False, "start_attempted": True,
             "signal_handlers_restored": True, "live": {"boot_id": "boot", "mounts_sha256": "b" * 64},
             "rpc": {"attempts": 1, "metadata_bytes": 100, "causes": [], "controlled_socket": False, "controlled_clock": False, "rpc": [
                 {"number": 1, "status": 200, "complete": True, "causes": [], "upgraded": False,
                  "peer": {"pid": 9, "uid": 0, "gid": 0},
                  "epoch_before": ((1, 2, 0, 0, 0o40755, None), (1, 3, 0, 0, 0o40755, None), (1, 4, 0, 999, 0o140660, 17)),
                  "epoch_after": ((1, 2, 0, 0, 0o40755, None), (1, 3, 0, 0, 0o40755, None), (1, 4, 0, 999, 0o140660, 17)),
                  "request_persisted": True, "reply_persisted": True, "request_send_complete": True,
                  "request_close_completed": True, "reply_close_completed": True,
                  "request_write_extent_unknown": False, "reply_write_extent_unknown": False,
                  "reply_eof": True, "socket_closed": True}]}}
    closure = {"closed": True, "populated": 0, "procs": [], "init_absent": True}
    owner["closed" if stage == "C1" else "containment_native"] = closure
    if stage == "C6":
        captured.update(complete=False, client_stdout_eof=False)
        captured["members"]["elf"].update(size_bytes=None, sha256=None, persisted=False, complete=False)
        owner["failed_operation"] = captured
        owner["containment_close_wait"] = True
        data["elf"] = b""
    else:
        owner["export"] = captured
    final = {"Id": "a" * 64, "RestartCount": 0, "SizeRw": 12288,
             "State": {"Running": False, "Restarting": False, "Paused": False, "Dead": False,
                       "OOMKilled": False, "Pid": 0, "ExitCode": 0 if stage in ("C1", "C6") else 1, "Error": ""}}
    observation = {"header_original": framed, "members": data, "final_inspect": final,
                   "wait_replies": [{"StatusCode": 0 if stage in ("C1", "C6") else 1, "Error": None}],
                   "owner_call_elapsed_ns": 45_000_000_000 if stage == "C5" else 1_000_000_000,
                   "published_exists": False, "boot_id": "boot", "mounts_sha256": "b" * 64,
                   "owner_receipt": {"export_binding": None if stage == "C6" else {
                       "header_sha256": sha(encoded), "members": members, "complete": True}},
                   "c3_sigxfsz_attributable": stage == "C3", "owner_signal_requests": []}
    return owner, observation


class ComparisonTests(unittest.TestCase):
    def test_all_six_exact_mappings_and_both_adopted_variants(self):
        for stage in gate.STAGES:
            for adopted in (False, True) if stage in ("C4", "C5") else (False,):
                with self.subTest(stage=stage, adopted=adopted):
                    owner, seen = outcome(stage, adopted)
                    result = gate.evaluate_c_v1(stage, owner, seen)
                    self.assertTrue(result["passed"], result)
                    self.assertFalse(result["whole_chain_authority"])

    def test_nonzero_owner_cause_does_not_hide_independent_failed_facts(self):
        mutations = (("final_inspect", "RestartCount", 1), ("final_inspect", "Id", "c" * 64))
        for stage in ("C2", "C3", "C4", "C5"):
            for parent, key, value in mutations:
                owner, seen = outcome(stage)
                seen[parent][key] = value
                self.assertFalse(gate.evaluate_c_v1(stage, owner, seen)["passed"])
            for key, value in (("OOMKilled", True), ("Running", True), ("Restarting", True),
                               ("Paused", True), ("Dead", True), ("Pid", 4), ("ExitCode", 0), ("Error", "bad")):
                owner, seen = outcome(stage)
                seen["final_inspect"]["State"][key] = value
                self.assertFalse(gate.evaluate_c_v1(stage, owner, seen)["passed"], (stage, key))

    def test_every_runtime_source_and_reap_drift_refuses(self):
        for field, value in (("pid", 2), ("core", [0, 1]), ("fsize", [1, 1]),
                             ("interpreter_elf64_amd64", False), ("compiler_elf64_amd64", False)):
            owner, seen = outcome("C2")
            owner["export"]["header"]["runtime"][field] = value
            encoded = canonical(owner["export"]["header"])
            seen["header_original"] = b"VASTCE1\n" + struct.pack("!I", len(encoded)) + encoded
            self.assertFalse(gate.evaluate_c_v1("C2", owner, seen)["passed"], field)
        for field in ("reaped", "started"):
            owner, seen = outcome("C4")
            owner["export"]["header"]["compiler"][field] = False
            self.assertFalse(gate.evaluate_c_v1("C4", owner, seen)["passed"])

    def test_member_and_channel_unknowns_never_pass(self):
        for field, value in (("eof", False), ("discarded_bytes", None), ("observed_bytes", 1), ("sha256", "c" * 64)):
            owner, seen = outcome("C5")
            owner["export"]["header"]["compiler"]["stderr"][field] = value
            self.assertFalse(gate.evaluate_c_v1("C5", owner, seen)["passed"], field)
        for field, value in (("complete", False), ("persisted", False), ("close_completed", False),
                             ("size_bytes", None), ("sha256", None), ("observed_sha256", "c" * 64)):
            owner, seen = outcome("C2")
            owner["export"]["members"]["stderr"][field] = value
            self.assertFalse(gate.evaluate_c_v1("C2", owner, seen)["passed"], field)

    def test_cause_order_extra_kill_and_partial_c6_are_refused(self):
        for stage in ("C4", "C5"):
            for causes in (["compiler_kill_attempted"], ["descendant_exit_nonzero", "compiler_term_attempted"],
                           list(reversed(outcome(stage)[0]["export"]["header"]["causes"]))):
                owner, seen = outcome(stage)
                owner["export"]["header"]["causes"] = causes
                self.assertFalse(gate.evaluate_c_v1(stage, owner, seen)["passed"])
        owner, seen = outcome("C6")
        owner["failed_operation"]["members"]["elf"]["size_bytes"] = 0
        self.assertFalse(gate.evaluate_c_v1("C6", owner, seen)["passed"])

    def test_rpc_upgrade_is_closed_without_requiring_handshake_eof(self):
        owner, seen = outcome("C1")
        owner["rpc"]["rpc"][0].update(status=101, upgraded=True, reply_eof=False)
        self.assertTrue(gate.evaluate_c_v1("C1", owner, seen)["passed"])
        owner["rpc"]["rpc"][0]["socket_closed"] = False
        self.assertFalse(gate.evaluate_c_v1("C1", owner, seen)["passed"])

    def test_evaluator_accepts_actual_transport_peer_and_epoch_facts(self):
        from tests.test_accepted_policy_fixture_compiler_transport_v1 import FakeSocket, reply
        with tempfile.TemporaryDirectory() as tmp:
            owner, seen = outcome("C1")
            epoch = owner["rpc"]["rpc"][0]["epoch_before"]
            client = gate.compiler._DockerClientV1(Path(tmp).resolve(), 20_000_000_000,
                socket_factory=lambda: FakeSocket(reply()), clock=lambda: 1_000_000_000)
            with patch.object(client, "_observe_endpoint", return_value=epoch):
                client.request("GET", "/info")
            self.assertEqual(client.facts["rpc"][0]["peer"], {"pid": 40, "uid": 0, "gid": 0})
            self.assertIsInstance(client.facts["rpc"][0]["epoch_before"], tuple)
            owner["rpc"] = client.facts
            self.assertFalse(gate.evaluate_c_v1("C1", owner, seen)["passed"])
            # Reuse the authentic row SHAPE as a native-shaped controlled test
            # vector; this mutation does not make this physical evidence.
            owner["rpc"].update(controlled_socket=False, controlled_clock=False)
            self.assertTrue(gate.evaluate_c_v1("C1", owner, seen)["passed"])

    def test_every_closure_and_owner_outcome_drift_refuses(self):
        for key, value in (("accepted", True), ("forced", True), ("receipt_persisted", False),
                           ("normal_closed", True), ("creation_unknown", True), ("start_unknown", True)):
            owner, seen = outcome("C2")
            owner[key] = value
            self.assertFalse(gate.evaluate_c_v1("C2", owner, seen)["passed"], key)
        for key, value in (("closed", False), ("populated", 1), ("procs", [7]), ("init_absent", False)):
            owner, seen = outcome("C2")
            owner["containment_native"][key] = value
            self.assertFalse(gate.evaluate_c_v1("C2", owner, seen)["passed"], key)

    def test_c5_cannot_claim_cutoff_before_actual_minimum_elapsed_time(self):
        owner, seen = outcome("C5")
        seen["owner_call_elapsed_ns"] = 1
        self.assertFalse(gate.evaluate_c_v1("C5", owner, seen)["passed"])

    def test_nonzero_wait_cause_does_not_accept_wrong_wait_status_or_error(self):
        for reply in ({"StatusCode": 0}, {"StatusCode": 1, "Error": {"Message": "daemon error"}},
                      {"StatusCode": True}, None):
            owner, seen = outcome("C2")
            seen["wait_replies"] = [reply]
            self.assertFalse(gate.evaluate_c_v1("C2", owner, seen)["passed"])

    def test_crash_guard_pins_the_actual_wsl_crashes_directory(self):
        self.assertEqual(str(gate.CRASH_DIRECTORY), "/mnt/c/Users/s-a-balashov/AppData/Local/Temp/wsl-crashes")


class ResumeInfoTests(unittest.TestCase):
    def native_shaped_info(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
        from tests.test_accepted_policy_fixture_compiler_transport_v1 import FakeSocket, reply
        info = json.loads((ROOT / 'openspec/changes/fix-accepted-policy-preprocessing/evidence/'
                           'compiler-component-01/observations-01/engine-info.v1_55.original.json').read_bytes())
        info.update(Containers=3, ContainersRunning=0, ContainersPaused=0, ContainersStopped=3)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve()
            client = d._DInfoClientV1(directory, 2_000_000_000,
                socket_factory=lambda: FakeSocket(reply(canonical(info))), clock=lambda: 1_000_000_000)
            epochs = ((2112, 128, 0, 0, 0o40755, None), (2112, 1844674, 0, 0, 0o40755, None),
                      (2112, 4294967295, 0, 999, 0o140660, 1792155560629153438))
            with patch.object(client, '_observe_endpoint', return_value=epochs):
                actual = client.request('GET', '/info')
            request_raw = (directory / 'RPC01.request.original').read_bytes()
            reply_raw = (directory / 'RPC01.reply.original').read_bytes()
            facts = copy.deepcopy(client.facts)
        self.assertTrue(facts['controlled_socket'] and facts['controlled_clock'])
        # Replay authentic transport fields in native shape; this controlled
        # test creates no native observation or external acceptance authority.
        facts.update(controlled_socket=False, controlled_clock=False)
        return actual, facts, request_raw, reply_raw

    def test_resume_info_binds_actual_transport_raws_and_exact_identity(self):
        info, facts, request_raw, reply_raw = self.native_shaped_info()
        value = gate.resume_info_v1(info=info, rpc_facts=facts, request_raw=request_raw, reply_raw=reply_raw)
        self.assertEqual(set(value), {'request', 'reply', 'identity', 'status', 'epoch_sha256',
                                     'rpc_sha256', 'rpc_summary'})
        self.assertEqual(value['reply'], {'size_bytes': len(reply_raw), 'sha256': sha(reply_raw)})
        self.assertEqual([value['identity'][key] for key in ('containers', 'containers_running',
                         'containers_paused', 'containers_stopped')], [3, 0, 0, 3])
        row = gate._rpc_json_facts_v1(facts)['rpc'][0]
        self.assertEqual(value['epoch_sha256'], sha(canonical(row['epoch_before'])))
        self.assertEqual(value['rpc_sha256'], sha(canonical(row)))
        self.assertEqual(value['rpc_summary']['metadata_bytes'], 2 * (len(request_raw) + len(reply_raw)))
        self.assertEqual(value['rpc_summary']['peer'], facts['rpc'][0]['peer'])

    def test_resume_info_rejects_controlled_unknown_or_typed_transport_facts(self):
        info, original, request_raw, reply_raw = self.native_shaped_info()
        mutations = [lambda f: f.update(controlled_socket=True), lambda f: f.update(controlled_clock=True),
                     lambda f: f.update(attempts=True), lambda f: f.update(metadata_bytes=float(f['metadata_bytes'])),
                     lambda f: f['rpc'][0].update(status=200.0),
                     lambda f: f['rpc'][0]['peer'].update(uid=False),
                     lambda f: f['rpc'][0].update(epoch_after=[[1] * 6] * 3)]
        true_fields = ('complete', 'request_persisted', 'reply_persisted', 'request_close_completed',
                       'reply_close_completed', 'request_send_complete', 'reply_eof', 'socket_closed')
        false_fields = ('request_write_extent_unknown', 'reply_write_extent_unknown',
                        'request_persistence_failed', 'reply_persistence_failed', 'upgraded')
        for field in true_fields + false_fields:
            mutations.append(lambda f, key=field: f['rpc'][0].update({key: not f['rpc'][0][key]}))
        for mutate in mutations:
            facts = copy.deepcopy(original)
            mutate(facts)
            with self.subTest(mutation=mutate), self.assertRaises(gate.Gate2Refusal):
                gate.resume_info_v1(info=info, rpc_facts=facts, request_raw=request_raw, reply_raw=reply_raw)

    def test_resume_info_refuses_wire_identity_and_raw_drift_before_acceptance(self):
        info, facts, request_raw, reply_raw = self.native_shaped_info()
        for field, value in (('Containers', 4), ('ContainersStopped', 3.0), ('ContainersRunning', False),
                             ('ID', 'foreign-engine'), ('DockerRootDir', '/other')):
            changed = copy.deepcopy(info)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(gate.Gate2Refusal):
                gate.resume_info_v1(info=changed, rpc_facts=facts, request_raw=request_raw, reply_raw=reply_raw)
        with self.assertRaises(gate.Gate2Refusal):
            gate.resume_info_v1(info=info, rpc_facts=facts, request_raw=request_raw, reply_raw=reply_raw + b'x')
        with patch.object(gate, '_http_json_v1', side_effect=AssertionError('parsed oversized wire')), \
                self.assertRaises(gate.Gate2Refusal):
            gate.resume_info_v1(info=info, rpc_facts=facts, request_raw=request_raw, reply_raw=b'x' * 16385)


class ResumePacketTests(unittest.TestCase):
    def setUp(self):
        from collections import namedtuple
        version=namedtuple('version_info','major minor micro releaselevel serial')(3,12,3,'final',0)
        for name in ('getuid','geteuid','getgid','getegid'):
            effect=patch.object(gate.os,name,return_value=1000,create=True)
            effect.start()
            self.addCleanup(effect.stop)
        effect=patch.object(gate.sys,'version_info',version)
        effect.start()
        self.addCleanup(effect.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.repo = Path(self.tmp.name).resolve() / 'repo'
        self.owner = Path(self.tmp.name).resolve() / 'owner465'
        self.root = self.owner / 'r1'
        self.aux = self.owner / 'r1.operator-originals'
        self.repo.mkdir()
        self.root.mkdir(parents=True)
        self.aux.mkdir()
        for target, value in ((gate, ('RESUME_OWNER_ROOT_V1', self.owner)),
                              (gate, ('RESUME_ROOT_V1', self.root)),
                              (component, ('REVIEW_REPO_ROOT_LINUX_V1', self.repo))):
            effect = patch.object(target, *value)
            effect.start()
            self.addCleanup(effect.stop)
        self.code = {}
        for name in gate.CODE_PATHS + (gate.RESUME_OPERATOR_V1,):
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            raw = b'# reviewed controlled bytes\n'
            path.write_bytes(raw)
            self.code[name] = self.blob(raw)
        operator = self.code.pop(gate.RESUME_OPERATOR_V1)
        self.plan = self.repo / (component.RETENTION_INDEX_REL_V1.rsplit('/',1)[0]+'/component-admission-plan.v8.md')
        self.plan.parent.mkdir(parents=True, exist_ok=True)
        self.plan.write_bytes(b'# CURRENT reviewed plan\n')
        self.plan_desc = gate._descriptor(self.plan, self.plan.read_bytes())
        self.prior = {'git_observation': {'component': self.code[gate.CODE_PATHS[1]],
            'index': dict(size_bytes=9637,sha256=component.RETENTION_INDEX_SHA256_V1,git_blob='d'*40),
            'old_git_sha256': 'a'*64}, 'native': {'index_sha256':component.RETENTION_INDEX_SHA256_V1,
                'source_rows_sha256':'a'*64,'node_count':28,'native_quote_bytes':633856,'windows_quote_bytes':32768,
                'transcript_quote_bytes':12288,'owned_upper_bytes':2102272,'old_f2_upper_bytes':333056,'physical_acceptance':False}}
        index_descriptor=self.blob(b'new historical index')
        self.retention = {'schema': 'vast_gate2_resume_retention_receipt_v1', 'index_sha256': index_descriptor['sha256'],
            'source_versions_sha256': 'c'*64, 'prior': self.prior['native'],
            'native': {'node_count':70,'native_code_quote_bytes':586240,'parent_growth_bytes':0,
                'f2_quote_bytes':4372992,'aux_quote_bytes':39424,'windows_capture_quote_bytes':32768,
                'diagnostic_quote_bytes':16384,'diagnostic_sha256':'c10bf42d132f92692ce72a37a6f3d64a944e2a90c6fa3fcc608a1e1cd4aa6780',
                'manifest_sha256':'e62f218cc56caaa5726804d22a348a42fa45d1c06645b955ba5457831a7fc757',
                'physical_acceptance':False}, 'physical_acceptance': False}
        info, facts, request, reply = ResumeInfoTests.native_shaped_info(self)
        self.pre_info = gate.resume_info_v1(info=info, rpc_facts=facts, request_raw=request, reply_raw=reply)
        (self.aux / 'RPC01.request.original').write_bytes(request)
        (self.aux / 'RPC01.reply.original').write_bytes(reply)
        self.context = {'schema_version': 1, 'producer_commit': gate.RESUME_PRODUCER_COMMIT_V1,
            'producer_plan': {'size_bytes': 25355, 'sha256': 'f024bfccb48e26be34b05b05fbc16082791b134f82967613177ad81a916d2d94',
                'git_blob': '4194c90dcfbc3dd4b44b71a4ce05c70192967397'},
            'owner_project_root': str(self.owner), 'project_root': str(self.root),
            'retention_index': index_descriptor, 'operator': operator,
            'retention': self.retention, 'prior_retention': self.prior,
            'baseline': {'c_free_bytes': 100_000_000_000, 'ext4_used_bytes': 300_000_000_000,
                         'project_free_bytes': 20_000_000_000, 'fragment_bytes': 4096,
                         'backing_device': self.root.stat().st_dev},
            'boot_id': '11111111-2222-3333-4444-555555555555', 'consumer_commit': 'e'*40,
            'consumer_plan': self.blob(self.plan.read_bytes()), 'pre_info': self.pre_info}
        self.review = {'commit': 'e'*40, 'approval_reference': 'PR9 independent CURRENT approval', 'evidence_sha256': 'a'*64}
        self.evidence = {key:{'path':str(path),'size_bytes':0,'sha256':sha(b'')}
            for key,path in gate._resume_evidence_paths_v1().items()}
        self.admitted = {'environment_keys': ['PATH'], 'accounting': {'physical_charge_bytes': 5050368,
            'reserved_control_bytes': 262144, 'reserved_rounding_bytes': 8192, 'reserved_metadata_bytes': 24576,
            'last': {'c_free_bytes': 1, 'ext4_used_bytes': 1}}}
        self.authority = self.authority_for(self.context)
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as resume
        effect = patch.object(resume, 'native_program_hashes_v1', return_value=dict.fromkeys(('PRE','PACKET','FINAL'),'d'*64), create=True)
        effect.start()
        self.addCleanup(effect.stop)
        command = {'schema_version': 1, 'code_commit': self.review['commit'], 'approval_reference': self.review['approval_reference'],
            'operator_sha256': operator['sha256'], 'phase_program_sha256': dict.fromkeys(('PRE','PACKET','FINAL'),'d'*64)}
        (self.aux/'operator.command.original.json').write_bytes(canonical(command))
        p0 = self.root/'p0/p0-completion.v1.json'
        p0.parent.mkdir()
        p0.write_bytes(b'{}')
        proof = dict(open_completed=True, written_bytes=2, fsync_completed=True, close_completed=True,
            late=False, extent_unknown=False, completed=True, prefix_sha256=sha(b'{}'))
        returned = {'code_commit': self.review['commit'], 'accepted': True, 'causes': [], 'controlled': False,
            'physical_acceptance': False, 'reviewed_operator_sha256': operator['sha256'],
            'kernel_preemption_claimed': False, 'external_invocation_status_and_eof_required': True,
            'completion_record': {'relative_path': p0.name, 'encoded_bytes':2, 'sha256':sha(b'{}'),
                'claims_self_persistence':False,'write_proof':proof}}
        (self.aux/'p0.return.original.json').write_bytes(canonical(returned))
        self.kwargs = dict(project_root=self.root, review=self.review, physical_plan_descriptor=self.plan_desc,
            code=self.code, evidence=self.evidence, p0_descriptor=gate._descriptor(p0,b'{}'),
            boot_id=self.context['boot_id'], initial_charged_bytes=29323264,
            initial_measurement={key: self.context['baseline'][key] for key in ('c_free_bytes','ext4_used_bytes')},
            operator_authority_descriptor=self.authority, prior_retention=self.prior, resume_context=self.context)
        for name, value in (('resume_code_forms_quote_v1', 991232), ('verify_resume_retention_v1', self.retention)):
            effect = patch.object(component, name, return_value=value)
            effect.start()
            self.addCleanup(effect.stop)
        effect = patch.object(gate, '_authenticate_evidence', return_value=self.admitted)
        self.evidence_mock = effect.start()
        self.addCleanup(effect.stop)
        effect = patch.object(gate, '_validate_p0')
        self.p0_mock = effect.start()
        self.addCleanup(effect.stop)

    @staticmethod
    def blob(raw):
        return {'size_bytes': len(raw), 'sha256': sha(raw),
            'git_blob': hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()}

    def authority_for(self, context):
        authority = setup.authority_record_v1(code_commit=self.review['commit'],
            approval_reference=self.review['approval_reference'], operator_sha256=context['operator']['sha256'],
            helper_code={gate.RESUME_OPERATOR_V1: dict(context['operator'], path=str(WINDOWS_REPO/gate.RESUME_OPERATOR_V1))},
            context=context, context_sha256=sha(canonical(context)))
        raw = canonical(authority)
        path = self.aux/'operator.authority.original.json'
        path.write_bytes(raw)
        self.review['evidence_sha256'] = sha(raw)
        return gate._descriptor(path, raw)

    def test_packet_separates_historical_producer_current_consumer_and_fresh_boot(self):
        packet = gate.build_packet_v1(**self.kwargs)
        self.assertEqual(packet['resume_context'], self.context)
        self.assertEqual(packet['initial_charged_bytes'], 29323264)
        self.assertEqual(packet['current_code_forms_quote_bytes'], 991232)
        self.assertEqual(self.evidence_mock.call_args.args[1]['commit'], gate.RESUME_PRODUCER_COMMIT_V1)
        self.assertEqual(self.evidence_mock.call_args.args[2], self.context['producer_plan']['sha256'])
        self.p0_mock.assert_called_with(self.kwargs['p0_descriptor'], self.root, 'e'*40, self.context['boot_id'])
        self.assertFalse((self.root/'outputs').exists())
        desc = gate.write_record_v1(self.root/'gate2.packet.original.json', packet, cap=32768)
        self.assertEqual(gate.validate_packet_v1(project_root=self.root, packet_descriptor=desc,
            expected_packet_sha256=desc['sha256'], expected_code_commit='e'*40), packet)

    def test_closed_roles_typed_baseline_info_and_fixed_charge_refuse(self):
        mutations = (lambda c: c.update(schema_version=True), lambda c: c.update(extra=0),
            lambda c: c.update(producer_commit='e'*40), lambda c: c.update(consumer_commit='f'*40),
            lambda c: c.update(owner_project_root=str(self.root)), lambda c: c.update(project_root=str(self.owner)),
            lambda c: c['producer_plan'].update(sha256='f'*64), lambda c: c['consumer_plan'].update(size_bytes=1.0),
            lambda c: c['baseline'].update(fragment_bytes=4096.0), lambda c: c['baseline'].update(backing_device=True),
            lambda c: c.update(boot_id='old-boot'), lambda c: c['pre_info']['rpc_summary'].update(complete=False),
            lambda c: c['pre_info']['rpc_summary'].update(metadata_bytes=float(c['pre_info']['rpc_summary']['metadata_bytes'])),
            lambda c: c['prior_retention']['git_observation']['component'].update(size_bytes=1.0))
        for mutate in mutations:
            context = copy.deepcopy(self.context)
            mutate(context)
            authority = self.authority_for(context)
            with self.subTest(mutation=mutate), self.assertRaises(gate.Gate2Refusal):
                gate.build_packet_v1(**dict(self.kwargs, resume_context=context, operator_authority_descriptor=authority))
        for charge in (29323263,29323265,29323264.0):
            with self.subTest(charge=charge), self.assertRaises(gate.Gate2Refusal):
                gate.build_packet_v1(**dict(self.kwargs, initial_charged_bytes=charge))

    def test_info_original_authority_and_operator_drift_refuse(self):
        for name in ('RPC01.request.original','RPC01.reply.original','operator.authority.original.json',
                     'operator.command.original.json','p0.return.original.json'):
            path = self.aux/name
            raw = path.read_bytes()
            path.write_bytes(raw+b'x')
            with self.subTest(path=name), self.assertRaises(gate.Gate2Refusal):
                gate.build_packet_v1(**self.kwargs)
            path.write_bytes(raw)
        (self.repo/gate.RESUME_OPERATOR_V1).write_bytes(b'# altered reviewed operator\n')
        with self.assertRaises(gate.Gate2Refusal):
            gate.build_packet_v1(**self.kwargs)

    def test_resume_namespace_rejects_unowned_names_links_and_future_stages(self):
        packet = {'resume_context': self.context}
        gate._resume_namespace_v1(self.root)
        for relative in ('unknown', 'outputs/foreign', 'outputs/C7', 'p0/foreign'):
            path = self.root/relative
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b'foreign')
            with self.subTest(relative=relative), self.assertRaises(gate.Gate2Refusal):
                gate._resume_namespace_v1(self.root)
            path.unlink()
        (self.root/'outputs/C1').mkdir()
        (self.root/'outputs/C1/controls').mkdir()
        with self.assertRaises(gate.Gate2Refusal):
            gate._resume_namespace_v1(self.root)
        gate._resume_namespace_v1(self.root, 'C1')
        for future in ('C2','C6','D'):
            path = self.root/'outputs'/future
            path.mkdir()
            with self.subTest(future=future), self.assertRaises(gate.Gate2Refusal):
                gate._resume_namespace_v1(self.root, 'C1')
            path.rmdir()
        path = self.root/'outputs/C1/controls/arbitrary.original'
        path.write_bytes(b'foreign')
        with self.assertRaises(gate.Gate2Refusal):
            gate._resume_namespace_v1(self.root, 'C1')
        path.unlink()
        target = self.root/'outputs/C1/engine.c'
        target.write_bytes(b'known source')
        alias = self.root/'outputs/C1/run.result.original.json'
        alias.symlink_to(target)
        with self.assertRaises(gate.Gate2Refusal):
            gate._resume_namespace_v1(self.root, 'C1')
        alias.unlink()
        gate.os.link(target, alias)
        with self.assertRaises(gate.Gate2Refusal):
            gate._resume_namespace_v1(self.root, 'C1')
        alias.unlink()
        self.assertEqual(gate._owner_project_root_v1(self.root, packet), self.owner)

    def test_d_binding_checks_fresh_pre_boot_before_chain_replay(self):
        packet = {'resume_context': self.context, 'boot_id': self.context['boot_id']}
        with patch.object(gate, 'validate_packet_v1', return_value=packet), \
                patch.object(gate.compiler, '_compiler_proc_read_v1', return_value=b'other-boot\n'), \
                patch.object(gate, '_previous_v1', side_effect=AssertionError('replayed after boot mismatch')):
            with self.assertRaisesRegex(gate.Gate2Refusal, 'resume_boot_drift'):
                gate.validated_c1_binding_v1(project_root=self.root, packet_descriptor={},
                    expected_packet_sha256='a'*64, expected_code_commit='e'*40, completion_authorities={})

    def test_resume_pre_refuses_existing_scope_before_any_allocation_or_info(self):
        with patch.object(gate, '_resume_measure_v1', return_value=self.context['baseline']), \
                patch.object(component, 'verify_resume_retention_v1', side_effect=AssertionError('verified after existing scope')), \
                patch.object(Path, 'mkdir', side_effect=AssertionError('allocated before refusal')):
            with self.assertRaisesRegex(gate.Gate2Refusal, 'resume_scope_exists'):
                gate.resume_pre_v1(code=self.code, plan=self.context['consumer_plan'], operator=self.context['operator'],
                    index_descriptor=self.context['retention_index'], git_observation=self.prior['git_observation'],
                    absolute_deadline_ns=gate.time.monotonic_ns()+15_000_000_000)

    def test_resume_phase_actor_refuses_every_wrong_identity_before_measurement(self):
        for field in ('getuid','geteuid','getgid','getegid'):
            with self.subTest(field=field), patch.object(gate.os,field,return_value=1001), \
                    patch.object(gate,'_resume_measure_v1',side_effect=AssertionError('measured wrong actor')):
                with self.assertRaisesRegex(gate.Gate2Refusal,'resume_actor'):
                    gate.resume_pre_v1(code=self.code,plan=self.context['consumer_plan'],operator=self.context['operator'],
                        index_descriptor=self.context['retention_index'],git_observation=self.prior['git_observation'],
                        absolute_deadline_ns=gate.time.monotonic_ns()+15_000_000_000)

    def test_resume_final_charges_interval_and_outstanding_tail_after_max_once(self):
        events = gate.write_record_v1(self.aux/'resume.events.original.json', {'phase': 'controlled'})
        packet = gate.write_record_v1(self.root/'gate2.packet.original.json', {'phase': 'controlled packet'})
        measured = dict(self.context['baseline'], c_free_bytes=self.context['baseline']['c_free_bytes']-1_000_000)
        with patch.object(gate, '_resume_measure_v1', return_value=measured), \
                patch.object(gate.compiler, '_compiler_proc_read_v1', return_value=self.context['boot_id'].encode()), \
                patch.object(gate, 'validate_packet_v1', return_value={'resume_context': self.context}):
            value = gate.resume_final_v1(context=self.context, packet_descriptor=packet, events_descriptor=events,
                absolute_deadline_ns=gate.time.monotonic_ns()+5_000_000_000)
            self.assertEqual(value['fresh_interval_N'], 1_000_000+45312)
            self.assertEqual(value['active_f2_debit'], 5345280+value['fresh_interval_N'])
            self.assertLessEqual(value['native_bytes'],1048576)
            self.assertLessEqual(value['outside_bytes'],524288)
            measured['c_free_bytes'] = self.context['baseline']['c_free_bytes']-2650112+45312
            self.assertEqual(gate.resume_final_v1(context=self.context,packet_descriptor=packet,events_descriptor=events,
                absolute_deadline_ns=gate.time.monotonic_ns()+5_000_000_000)['fresh_interval_N'],2650112)
            measured['c_free_bytes'] -= 1
            with self.assertRaisesRegex(gate.Gate2Refusal,'resume_interval_bound'):
                gate.resume_final_v1(context=self.context, packet_descriptor=packet, events_descriptor=events,
                    absolute_deadline_ns=gate.time.monotonic_ns()+5_000_000_000)

    def test_resume_pre_actual_transport_and_declared_parent_growth(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
        from tests.test_accepted_policy_fixture_compiler_transport_v1 import FakeSocket
        _, _, _, reply = ResumeInfoTests.native_shaped_info(self)
        owner = Path(self.tmp.name).resolve()/'pre-owned'
        owner.mkdir()
        root = owner/'r1'
        real_client = d._DInfoClientV1
        def client(directory, deadline):
            value = real_client(directory, deadline, socket_factory=lambda: FakeSocket(reply), clock=lambda: 1_000_000_000)
            value._observe_endpoint = lambda: ((2112,1,0,0,16877,None),(2112,2,0,0,16877,None),(2112,3,0,999,49584,1792155560629153438))
            value.facts.update(controlled_socket=False,controlled_clock=False)
            return value
        retained = [copy.deepcopy(self.retention),copy.deepcopy(self.retention)]
        retained[1]['native']['parent_growth_bytes'] = 4096
        with patch.object(gate,'RESUME_OWNER_ROOT_V1',owner), patch.object(gate,'RESUME_ROOT_V1',root), \
                patch.object(gate,'_resume_measure_v1',return_value=self.context['baseline']), \
                patch.object(gate.compiler,'_compiler_proc_read_v1',return_value=self.context['boot_id'].encode()), \
                patch.object(component,'verify_resume_retention_v1',side_effect=retained), \
                patch.object(d,'_DInfoClientV1',side_effect=client):
            value = gate.resume_pre_v1(code=self.code,plan=self.context['consumer_plan'],operator=self.context['operator'],
                index_descriptor=self.context['retention_index'],git_observation=self.prior['git_observation'],
                absolute_deadline_ns=gate.time.monotonic_ns()+15_000_000_000)
            self.assertEqual(value['retention']['native']['parent_growth_bytes'],4096)
            self.assertEqual(value['pre_info']['identity']['containers'],3)
            self.assertEqual(value['rpc_facts']['attempts'],1)
            self.assertEqual(set((owner/'r1.operator-originals').iterdir()),
                {owner/'r1.operator-originals/RPC01.request.original',owner/'r1.operator-originals/RPC01.reply.original'})
            self.assertEqual(list(root.iterdir()),[])

    def test_pre_actual_transport_failure_preserves_initiating_and_distinct_close_causes(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
        from tests.test_accepted_policy_fixture_compiler_transport_v1 import FakeSocket
        owner=Path(self.tmp.name).resolve()/'failed-pre-owned'
        owner.mkdir()
        root=owner/'r1'
        real=d._DInfoClientV1
        def client(directory,deadline):
            value=real(directory,deadline,socket_factory=lambda:FakeSocket(b'',fail_send=True,fail_close=True),
                clock=lambda:1_000_000_000)
            value._observe_endpoint=lambda:[[2112,1,0,0,16877,None],[2112,2,0,0,16877,None],
                [2112,3,0,999,49584,1792155560629153438]]
            return value
        with patch.object(gate,'RESUME_OWNER_ROOT_V1',owner),patch.object(gate,'RESUME_ROOT_V1',root), \
                patch.object(gate,'_resume_measure_v1',return_value=self.context['baseline']), \
                patch.object(gate.compiler,'_compiler_proc_read_v1',return_value=self.context['boot_id'].encode()), \
                patch.object(d,'_DInfoClientV1',side_effect=client):
            with self.assertRaises(gate.Gate2Refusal) as caught:
                gate.resume_pre_v1(code=self.code,plan=self.context['consumer_plan'],operator=self.context['operator'],
                    index_descriptor=self.context['retention_index'],git_observation=self.prior['git_observation'],
                    absolute_deadline_ns=gate.time.monotonic_ns()+15_000_000_000)
        original=caught.exception.facts
        raw=gate.native_failure_bytes_v1(caught.exception)
        projected=json.loads(raw)
        causes=original['rpc_facts']['rpc'][0]['causes']
        self.assertGreaterEqual(len(causes),2)
        self.assertIn(causes[0],projected['causes'])
        self.assertIn('docker_socket_close_OSError',projected['causes'])
        self.assertLess(projected['causes'].index(causes[0]),projected['causes'].index('docker_socket_close_OSError'))
        self.assertEqual(projected['facts_sha256'],sha(canonical(original)))

    def test_pre_and_read_wrapper_keep_actual_component_read_and_close_failure_facts(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
        owner=Path(self.tmp.name).resolve()/'component-pre-owned';owner.mkdir()
        root=owner/'r1';path=owner/'owned-input';path.write_bytes(b'known input')
        fdopen=component.os.fdopen;errors=[]
        class Reader:
            def __init__(self,file):self.file=file
            def fileno(self):return self.file.fileno()
            def read(self,count):raise OSError('initiating read failure')
            def close(self):self.file.close();raise OSError('distinct close failure')
        def read_failure(*args,**kwargs):
            try:return component._retention_read_v1(path,4096)
            except component.ComponentRecipeError as error:errors.append(error);raise
        with patch.object(component.os,'fdopen',side_effect=lambda fd,*a,**kw:Reader(fdopen(fd,*a,**kw))), \
                patch.object(gate,'RESUME_OWNER_ROOT_V1',owner),patch.object(gate,'RESUME_ROOT_V1',root), \
                patch.object(gate,'_resume_measure_v1',return_value=self.context['baseline']), \
                patch.object(gate.compiler,'_compiler_proc_read_v1',return_value=self.context['boot_id'].encode()), \
                patch.object(component,'verify_resume_retention_v1',side_effect=read_failure), \
                patch.object(d,'_DInfoClientV1',side_effect=AssertionError('dependent API')):
            with self.assertRaises(component.ComponentRecipeError) as phase:
                gate.resume_pre_v1(code=self.code,plan=self.context['consumer_plan'],operator=self.context['operator'],
                    index_descriptor=self.context['retention_index'],git_observation=self.prior['git_observation'],
                    absolute_deadline_ns=gate.time.monotonic_ns()+15_000_000_000)
            with self.assertRaises(gate.Gate2Refusal) as wrapped:gate._read(path,4096)
        self.assertFalse(root.exists());self.assertFalse((owner/'r1.operator-originals').exists())
        self.assertEqual(phase.exception.facts,errors[0].facts)
        self.assertEqual(wrapped.exception.facts['causes'],errors[0].causes)
        for error in (phase.exception,wrapped.exception):
            value=json.loads(gate.native_failure_bytes_v1(error))
            self.assertLess(value['causes'].index('retention_read_OSError'),value['causes'].index('retention_close_OSError'))
            self.assertTrue(any(row[1]=='unknown_closure' and row[2] is True for row in value['observations']))

    def test_resume_packet_helper_writes_fixed_original_under_original_deadline(self):
        real_read = gate._read
        def read(path, cap):
            return real_read(path,cap) if Path(path).is_relative_to(Path(self.tmp.name)) and Path(path).exists() else b'controlled old original'
        with patch.object(gate,'_read',side_effect=read), \
                patch.object(gate,'_resume_measure_v1',return_value=self.context['baseline']):
            value = gate.resume_packet_v1(context=self.context,code=self.code,review=self.review,
                authority_descriptor=self.authority,p0_descriptor=self.kwargs['p0_descriptor'],
                absolute_deadline_ns=gate.time.monotonic_ns()+15_000_000_000)
            self.assertEqual(value['packet']['path'],str(self.root/'gate2.packet.original.json'))
            self.assertTrue(value['packet_write_facts']['complete'])
            packet = json.loads((self.root/'gate2.packet.original.json').read_bytes())
            self.assertEqual(packet['initial_charged_bytes'],29323264)
            self.assertEqual(set(packet['resume_originals']),{'command','p0_return'})
            with self.assertRaisesRegex(gate.Gate2Refusal,'resume_phase_deadline'):
                gate.resume_packet_v1(context=self.context,code=self.code,review=self.review,
                    authority_descriptor=self.authority,p0_descriptor=self.kwargs['p0_descriptor'],absolute_deadline_ns=0)

    def test_actual_native_phase_entry_uses_bounded_boot_and_fixed_local_dispatch(self):
        import io
        from types import SimpleNamespace
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_resume_v1 as r
        payload = {'global_deadline_ns':200,'phase_deadline_ns':200,'context':self.context,
            'current':dict(self.code,**{r.PLAN:self.context['consumer_plan'],r.OPERATOR:self.context['operator']}),
            'index':self.context['retention_index'],'git_observation':self.prior['git_observation'],
            'review':self.review,'authority':self.authority,'p0':self.kwargs['p0_descriptor'],'packet':{},'events':{}}
        for phase in ('PRE','PACKET','FINAL'):
            writes=[]
            ack=canonical(dict(global_deadline_ns=200,phase_deadline_ns=200,boot_id=self.context['boot_id']))+b'\n'
            with self.subTest(phase=phase), patch.object(gate.time,'monotonic_ns',return_value=100), \
                    patch.object(gate.compiler,'_compiler_proc_read_v1',return_value=self.context['boot_id'].encode()) as boot, \
                    patch.object(gate.os,'write',side_effect=lambda fd,raw:writes.append((fd,raw)) or len(raw)), \
                    patch.object(gate.sys,'stdin',SimpleNamespace(buffer=io.BytesIO(ack))), \
                    patch.object(gate.select,'select',return_value=([0],[],[])), \
                    patch.object(gate,'resume_pre_v1',return_value={'phase':phase}), \
                    patch.object(gate,'resume_packet_v1',return_value={'phase':phase}), \
                    patch.object(gate,'resume_final_v1',return_value={'phase':phase}):
                gate.resume_native_entry_v1(phase,payload)
                self.assertEqual(json.loads(writes[-1][1]),{'phase':phase})
                self.assertTrue(all(fd==1 for fd,_ in writes))
                boot.assert_called_with('/proc/sys/kernel/random/boot_id',64)

    def test_terminal_unicode_cycles_and_max_known_facts_never_erase_failure(self):
        facts = {'returned_p0':{'spawn':{'pid':55916,'returncode':None,'stdout_eof':True,'stderr_eof':True,
            'unknown_closure':True,'write_extent_unknown':True},'completion':{'completed':True}},
            'causes':['first_'+chr(0x1f4a5)*80,'close_failed'],chr(0x1f4a5)*80:
            [{'pid':i,'returncode':None,'stdout_eof':True,'stderr_eof':True} for i in range(4)]}
        error = gate.Gate2Refusal(chr(0x1f4a5)*100,facts)
        for body in (facts,dict(facts,opaque=object()),dict(facts,extra='x'*(gate.CONTROL_LIMIT+1))):
            error.facts=body
            raw=gate.resume_terminal_v1(error=error)
            self.assertLessEqual(len(raw)+1,2048)
            value=json.loads(raw)
            self.assertFalse(value['completed'])
            self.assertFalse(value['physical_acceptance'])
            self.assertTrue(value['omitted_or_unknown'])
            self.assertEqual(value['native_raw_originals_retained'],0)
            self.assertTrue(any(row['path'].endswith('/returncode') and row['value'] is None for row in value['known']))
        facts['cycle']=facts
        self.assertTrue(json.loads(gate.resume_terminal_v1(error=gate.Gate2Refusal('cycle',facts)))['facts_unknown'])

    def test_terminal_preserves_actual_p0_producer_completion_and_pending_child_shapes(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_p0_v1 as p0
        result=p0._result_shell({},['command_deadline'],controlled=False,reviewed_code_commit='e'*40)
        command=p0._public_command(p0._blank_command('id',p0.command_phase_deadlines(100,30_000_000_100)))
        command.update(pid=55916,returncode=None,eof_stdout=True,eof_stderr=True,linux_child_closure='unknown',late=True)
        result['commands']=[command]
        proof=p0._empty_persistence()
        proof.update(open_completed=True,written_bytes=1081,fsync_completed=True,close_completed=True,completed=True)
        result['control_record']['write_proof']=dict(proof,written_bytes=2538)
        result['completion_record']={'relative_path':p0.COMPLETION_NAME,'encoded_bytes':1081,
            'sha256':'a'*64,'claims_self_persistence':False,'write_proof':proof}
        value=json.loads(gate.resume_terminal_v1(error=gate.Gate2Refusal('p0_refused',{'returned_p0':result})))
        known={row['path']:row['value'] for row in value['known']}
        for role in ('control_record','completion_record'):
            for field in ('written_bytes','fsync_completed','close_completed','extent_unknown','completed'):
                self.assertTrue(any(key.endswith('/'+role+'/write_proof/'+field) for key in known),field)
        self.assertIsNone(known['/returned_p0/commands/0/returncode'])
        self.assertTrue(known['/returned_p0/commands/0/eof_stdout'])
        self.assertTrue(known['/returned_p0/commands/0/eof_stderr'])

    def test_terminal_keeps_actual_process_input_uncertainty_and_ordered_failures(self):
        facts={'pid':1448,'returncode':-9,'stdout_eof':True,'stderr_eof':True,'stdin_closed':False,
            'stdin_extent_unknown':True,'causes':['stdin_write_failed','stdin_close_failed','native_nonzero']}
        value=json.loads(gate.resume_terminal_v1(error=gate.Gate2Refusal('native_failed',facts)))
        known={row['path']:row['value'] for row in value['known']}
        self.assertEqual(known['/returncode'],-9)
        self.assertFalse(known['/stdin_closed'])
        self.assertTrue(known['/stdin_extent_unknown'])
        self.assertEqual(value['causes'],['native_failed','stdin_write_failed','stdin_close_failed','native_nonzero'])

    def test_terminal_keeps_actual_process_channel_prefix_counts_and_complete_digests(self):
        import base64
        stdout=b'{"observed":"bounded output before process refusal"}'
        stderr=b'{"causes":["first_failure","distinct_close_failure"]}'
        for returncode, eof in ((None,False),(-9,True)):
            facts={channel+'_'+field:sha(raw) if field=='sha256' else
                len(raw) if field=='bytes' else eof
                for channel,raw in (('stdout',stdout),('stderr',stderr))
                for field in ('eof','bytes','sha256')}
            facts.update(pid=1448,returncode=returncode,argv_sha256='a'*64,
                stdin_sha256='b'*64,stdin_bytes=128,stdin_closed=False,
                stdin_extent_unknown=True,unknown_closure=True,native_raw_originals_retained=0,
                causes=['stdin_write_failed','stdin_close_failed','process_deadline'],
                stdout_prefix_base64=base64.b64encode(stdout[:48]).decode(),
                stderr_prefix_base64=base64.b64encode(stderr[:48]).decode(),omitted_or_unknown=True)
            raw=gate.resume_terminal_v1(error=gate.Gate2Refusal('process_refused',facts))
            self.assertLessEqual(len(raw)+1,2048)
            value=json.loads(raw)
            known={row['path']:row['value'] for row in value['known']}
            for channel,data in (('stdout',stdout),('stderr',stderr)):
                self.assertEqual(known['/'+channel+'_bytes'],len(data))
                self.assertEqual(known['/'+channel+'_sha256'],sha(data))
                self.assertEqual(known['/'+channel+'_prefix_base64'],facts[channel+'_prefix_base64'])
                self.assertEqual(known['/'+channel+'_eof'],eof)
            self.assertEqual(known['/returncode'],returncode)
            self.assertFalse(known['/stdin_closed'])
            self.assertTrue(known['/stdin_extent_unknown'])
            self.assertTrue(known['/unknown_closure'])
            self.assertTrue(value['omitted_or_unknown'])
            self.assertEqual(value['native_raw_originals_retained'],0)
            self.assertEqual(value['causes'],['process_refused','stdin_write_failed','stdin_close_failed','process_deadline'])

    def test_native_phase_short_emit_and_postreturn_late_cannot_complete(self):
        payload={'global_deadline_ns':200,'phase_deadline_ns':200,'context':self.context,'packet':{},'events':{}}
        for fault in ('short','late'):
            writes=[]
            now=[100]
            def phase(**kwargs):
                if fault=='late':now[0]=201
                return {'native_pid':123,'returncode':None,'stdout_eof':True,'write_extent_unknown':True}
            def emit(fd,raw):
                writes.append((fd,raw))
                return len(raw)-1 if fd==1 and fault=='short' else len(raw)
            with self.subTest(fault=fault), patch.object(gate.time,'monotonic_ns',side_effect=lambda:now[0]), \
                    patch.object(gate.compiler,'_compiler_proc_read_v1',return_value=self.context['boot_id'].encode()), \
                    patch.object(gate,'resume_final_v1',side_effect=phase), patch.object(gate.os,'write',side_effect=emit):
                with self.assertRaises(SystemExit) as caught:gate.resume_native_entry_v1('FINAL',payload)
                self.assertEqual(caught.exception.code,1)
                failure=json.loads(writes[-1][1])
                self.assertEqual(writes[-1][0],2)
                self.assertFalse(failure['physical_acceptance'])
                if fault=='late':
                    self.assertTrue(any(row[1]=='returncode' and row[2] is None for row in failure.get('observations',[])) or
                                    failure.get('facts_sha256')==sha(canonical(phase())))
                    self.assertFalse(any(fd==1 for fd,_ in writes))

    def test_real_code_and_full_descriptor_packet_geometry_at_98_character_child(self):
        import shutil
        base=Path(self.tmp.name).resolve()
        owner=base/('n'*(95-len(str(base))-1))
        self.assertEqual(len(str(owner/'r1')),98)
        shutil.copytree(self.owner,owner)
        aux=owner/'r1.operator-originals'
        self.owner,self.root,self.aux=owner,owner/'r1',aux
        with patch.object(gate,'RESUME_OWNER_ROOT_V1',owner), patch.object(gate,'RESUME_ROOT_V1',self.root):
            context=copy.deepcopy(self.context)
            context.update(owner_project_root=str(owner),project_root=str(self.root))
            for relative in gate.CODE_PATHS+(gate.RESUME_OPERATOR_V1,):
                raw=(ROOT/relative).read_bytes()
                (self.repo/relative).write_bytes(raw)
                if relative==gate.RESUME_OPERATOR_V1:context['operator']=self.blob(raw)
                else:self.code[relative]=self.blob(raw)
            plan_raw=(ROOT/(component.RETENTION_INDEX_REL_V1.rsplit('/',1)[0]+'/component-admission-plan.v8.md')).read_bytes()
            self.plan.write_bytes(plan_raw)
            context['consumer_plan']=self.blob(plan_raw)
            context['prior_retention']['git_observation']['component']=self.code[gate.CODE_PATHS[1]]
            context['retention']['prior']=context['prior_retention']['native']
            authority=self.authority_for(context)
            command=json.loads((aux/'operator.command.original.json').read_bytes())
            command['operator_sha256']=context['operator']['sha256']
            (aux/'operator.command.original.json').write_bytes(canonical(command))
            returned=json.loads((aux/'p0.return.original.json').read_bytes())
            returned['reviewed_operator_sha256']=context['operator']['sha256']
            (aux/'p0.return.original.json').write_bytes(canonical(returned))
            evidence={key:{'path':str(path),'size_bytes':1048576,'sha256':'f'*64}
                for key,path in gate._resume_evidence_paths_v1().items()}
            packet=gate.build_packet_v1(**dict(self.kwargs,project_root=self.root,code=self.code,
                resume_context=context,prior_retention=context['prior_retention'],evidence=evidence,
                physical_plan_descriptor=gate._descriptor(self.plan,plan_raw),
                operator_authority_descriptor=authority,p0_descriptor=gate._descriptor(self.root/'p0/p0-completion.v1.json',b'{}')))
            encoded=canonical(packet)
            logical=sum(row['size_bytes'] for row in self.code.values())+context['operator']['size_bytes']+len(encoded)+self.plan.stat().st_size+len(canonical(packet['seed']))
            self.assertLessEqual(len(encoded),32768)
            self.assertLessEqual(gate.compiler._json_bound(packet),32768)
            self.assertLessEqual(logical,655360)
            self.assertLessEqual(self.code[gate.CODE_PATHS[0]]['size_bytes'],131072)
            self.assertLessEqual(context['operator']['size_bytes'],32768)
            self.assertEqual(set(packet['proofs']),set(gate.PROOF_SOURCES))
            print(json.dumps({'resume_packet_geometry':{'root_chars':98,'encoded_bytes':len(encoded),
                'preencode_bound':gate.compiler._json_bound(packet),'logical_bytes':logical}}))


class BoundTests(unittest.TestCase):
    def prior_authority(self, root, code, review):
        helpers = {}
        for relative in ("tests/fixtures/accepted_policy_fixture_compiler_gate2_setup_v1.py",
                         "tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py"):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            data = b"# controlled authenticated setup helper\n"
            path.write_bytes(data)
            helpers[relative] = {"path": str(WINDOWS_REPO / relative), "size_bytes": len(data), "sha256": sha(data),
                "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}
        native = {"index_sha256": component.RETENTION_INDEX_SHA256_V1, "source_rows_sha256": "c" * 64,
            "node_count": 28, "native_quote_bytes": 633856, "windows_quote_bytes": 32768,
            "transcript_quote_bytes": 12288, "owned_upper_bytes": 2102272, "old_f2_upper_bytes": 333056,
            "physical_acceptance": False}
        prior = {"git_observation": {"component": code[gate.CODE_PATHS[1]],
            "index": {"size_bytes": 9637, "sha256": component.RETENTION_INDEX_SHA256_V1, "git_blob": "d" * 40},
            "old_git_sha256": "c" * 64}, "native": native}
        context = {"code_commit": review["commit"], "boot_id": "controlled-boot", "retention": prior,
            "helper_code": helpers, "capture_source_sha256": helpers[
                "tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py"]["sha256"]}
        authority = setup.authority_record_v1(code_commit=review["commit"],
            approval_reference=review["approval_reference"], operator_sha256=helpers[
                setup.SETUP_REL]["sha256"], helper_code=helpers,
            context=context, context_sha256=sha(canonical(context)))
        aux = Path(str(root) + ".operator-originals")
        aux.mkdir()
        descriptor = gate.write_record_v1(aux / "operator.authority.original.json", authority, cap=8192)
        review["evidence_sha256"] = descriptor["sha256"]
        return descriptor, prior, native

    def test_ledger_charges_largest_measure_and_refuses_floors_or_reserve(self):
        before = {"c_free_bytes": 100_000_000_000, "ext4_used_bytes": 300_000_000_000}
        after = {"c_free_bytes": before["c_free_bytes"] - 9000,
                 "ext4_used_bytes": before["ext4_used_bytes"] + 12000}
        self.assertEqual(gate.interval_charge_v1(before, after, retained_bytes=4000, size_rw=1000), 12000)
        with self.assertRaises(gate.Gate2Refusal):
            gate.reserve_v1(charged=gate.SEAL_BYTES - 100, liability=101, c_free_bytes=100_000_000_000)
        with self.assertRaises(gate.Gate2Refusal):
            gate.reserve_v1(charged=0, liability=1, c_free_bytes=43_620_761_599)

    def test_record_reads_reject_nonregular_links_before_open_and_close_kind_change_races(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            fifo = root / "fifo"
            gate.os.mkfifo(fifo)
            directory = root / "directory"
            directory.mkdir()
            regular = root / "regular"
            regular.write_bytes(b"original")
            linked = root / "hardlink"
            gate.os.link(regular, linked)
            for path in (fifo, directory, linked):
                with self.subTest(path=path.name), \
                        patch.object(Path, "open", side_effect=AssertionError("opened nonregular/link input")):
                    with self.assertRaises(gate.Gate2Refusal):
                        gate._read(path, 32)
            linked.unlink()
            real_open, opened = gate.os.open, []
            def changed_kind(path, flags, *args, **kwargs):
                self.assertTrue(flags & gate.os.O_NONBLOCK)
                self.assertTrue(flags & gate.os.O_NOFOLLOW)
                fd = real_open(fifo, flags)
                opened.append(fd)
                return fd
            with patch.object(gate.os, "open", changed_kind):
                with self.assertRaises(gate.Gate2Refusal):
                    gate._read(regular, 32)
            self.assertEqual(len(opened), 1)
            with self.assertRaises(OSError):
                gate.os.fstat(opened[0])
            self.assertEqual(regular.read_bytes(), b"original")

    def test_record_preencoding_bound_and_exclusive_persistence(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp).resolve() / "one.json"
            descriptor = gate.write_record_v1(path, {"a": 1}, cap=4096)
            self.assertEqual(descriptor["sha256"], sha(path.read_bytes()))
            with self.assertRaises(FileExistsError):
                gate.write_record_v1(path, {"a": 2}, cap=4096)
            with patch.object(component, "canonical_json_v1", side_effect=AssertionError("encoded huge input")):
                with self.assertRaises(gate.Gate2Refusal):
                    gate.write_record_v1(Path(tmp).resolve() / "big", {"x": "a" * 5000}, cap=100)

    def test_packet_refuses_self_authority_and_changed_code_or_seed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "project"
            root.mkdir()
            files = {}
            for name in gate.CODE_PATHS:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"# reviewed controlled bytes\n")
                raw = path.read_bytes()
                files[name] = {"size_bytes": len(raw), "sha256": sha(raw),
                               "git_blob": hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()}
            plan = root / "physical-plan.md"
            plan.write_bytes(b"fixed controlled physical plan\n")
            historical = component.retained_source_bindings_v1(ROOT)
            working_plan = root / historical["sources"][10]["path"]
            working_plan.parent.mkdir(parents=True, exist_ok=True)
            working_plan.write_bytes(plan.read_bytes())
            review = {"commit": "a" * 40, "approval_reference": "PR9 code approval", "evidence_sha256": "b" * 64}
            evidence = {name: {"path": str(root / name), "size_bytes": 0, "sha256": sha(b"")}
                        for name in gate.EVIDENCE_NAMES}
            f2 = {"environment_keys": ["PATH"], "accounting": {"physical_charge_bytes": 4194304,
                "reserved_control_bytes": 524288, "reserved_rounding_bytes": 8192, "reserved_metadata_bytes": 8192,
                "last": {"c_free_bytes": 100_000_000_000, "ext4_used_bytes": 300_000_000_000}}}
            authority, prior, native = self.prior_authority(root, files, review)
            with patch.object(gate, "_authenticate_evidence", return_value=f2), patch.object(gate, "_validate_p0"), \
                    patch.object(component, "REVIEW_REPO_ROOT_LINUX_V1", root), \
                    patch.object(component, "retained_source_bindings_v1", return_value=historical), \
                    patch.object(component, "verify_prior_retention_v1", return_value=native) as fresh:
                # The failed attempt is additive even when the new F2 charge
                # already dominates every measured new-operation delta.
                with self.assertRaisesRegex(gate.Gate2Refusal, "initial_charge_omitted_forms"):
                    gate.build_packet_v1(project_root=root, review=review,
                        physical_plan_descriptor={"path": str(plan), "size_bytes": plan.stat().st_size,
                                                  "sha256": sha(plan.read_bytes())},
                        code=files, evidence=evidence, p0_descriptor={}, boot_id="controlled-boot",
                        operator_authority_descriptor=authority, prior_retention=prior,
                        initial_charged_bytes=20 * 1048576,
                        initial_measurement={"c_free_bytes": 100_000_000_000, "ext4_used_bytes": 300_000_000_000})
                packet = gate.build_packet_v1(project_root=root, review=review,
                    physical_plan_descriptor={"path": str(plan), "size_bytes": plan.stat().st_size,
                                              "sha256": sha(plan.read_bytes())},
                    code=files, evidence=evidence, p0_descriptor={}, boot_id="controlled-boot", initial_charged_bytes=26 * 1048576,
                    operator_authority_descriptor=authority, prior_retention=prior,
                    initial_measurement={"c_free_bytes": 100_000_000_000, "ext4_used_bytes": 300_000_000_000})
                packet_path = root / "gate2.packet.v1.json"
                descriptor = gate.write_record_v1(packet_path, packet, cap=gate.PACKET_LIMIT)
                with self.assertRaises(gate.Gate2Refusal):
                    gate.validate_packet_v1(project_root=root, packet_descriptor=descriptor,
                        expected_packet_sha256=None, expected_code_commit="a" * 40)
                checked = gate.validate_packet_v1(project_root=root, packet_descriptor=descriptor,
                    expected_packet_sha256=descriptor["sha256"], expected_code_commit="a" * 40)
                self.assertEqual(set(checked["seed"]["proofs"]), set(gate.PROOF_SOURCES))
                self.assertTrue(all(checked["seed"]["proofs"].values()))
                self.assertIsNone(checked["seed"].get("component_seed"))
                self.assertEqual(checked["operator_authority"], authority)
                self.assertEqual(checked["prior_retention"], prior)
                self.assertEqual(checked["current_code_forms_quote_bytes"], 180224)
                # A changed working counterpart must refuse even while the
                # exported plan, packet and its external SHA remain intact.
                working_plan.write_bytes(b"changed current working plan\n")
                with self.assertRaisesRegex(gate.Gate2Refusal, "current_code_forms_unavailable"):
                    gate.validate_packet_v1(project_root=root, packet_descriptor=descriptor,
                        expected_packet_sha256=descriptor["sha256"], expected_code_commit="a" * 40)
                working_plan.write_bytes(plan.read_bytes())
                self.assertGreaterEqual(fresh.call_count, 3)
                with patch.object(component, "verify_prior_retention_v1",
                                  side_effect=component.ComponentRecipeError("changed retained original")):
                    with self.assertRaisesRegex(gate.Gate2Refusal, "prior_retention_unavailable"):
                        gate.validate_packet_v1(project_root=root, packet_descriptor=descriptor,
                            expected_packet_sha256=descriptor["sha256"], expected_code_commit="a" * 40)
                self.assertFalse((root / "outputs").exists())
                # Independent concrete boundaries: carry is never inside the
                # maximum, including when the new interval has 12 MiB noise.
                for gap, charge, accepted in ((0, 25014272, False), (0, 25538559, False),
                        (0, 25538560, True), (12582912, 29716480, False),
                        (12582912, 36007936, False), (12582912, 36532223, False),
                        (12582912, 36532224, True)):
                    args = dict(project_root=root, review=review, physical_plan_descriptor=packet["physical_plan"],
                        code=files, evidence=evidence, p0_descriptor={}, boot_id="controlled-boot",
                        operator_authority_descriptor=authority, prior_retention=prior, initial_charged_bytes=charge,
                        initial_measurement={"c_free_bytes": 100_000_000_000-gap, "ext4_used_bytes": 300_000_000_000})
                    with self.subTest(gap=gap, charge=charge):
                        if accepted:
                            self.assertEqual(gate.build_packet_v1(**args)["initial_charged_bytes"], charge)
                        else:
                            with self.assertRaisesRegex(gate.Gate2Refusal, "initial_charge_omitted_forms"):
                                gate.build_packet_v1(**args)
                old_charge = f2["accounting"]["physical_charge_bytes"]
                f2["accounting"]["physical_charge_bytes"] = component.ACTIVE_F2_LIMIT_V1 - 540672 + 1
                with self.assertRaisesRegex(gate.Gate2Refusal, "active_f2_bound"):
                    gate.build_packet_v1(**dict(args, initial_charged_bytes=40*1048576))
                f2["accounting"]["physical_charge_bytes"] = old_charge
                for index, mutate in enumerate((
                    lambda p: p["seed"]["proofs"].update(toolchain=None),
                    lambda p: p["proofs"]["abi"].update(kind="toolchain"),
                    lambda p: p["source_sha256"].update(c1="0" * 64),
                    lambda p: p["seed"].update(artifact_kind="vast_fixture_compiler_qualification_v1"),
                    lambda p: p["operator_authority"].update(sha256="0" * 64),
                    lambda p: p["prior_retention"]["native"].update(physical_acceptance=True),
                    lambda p: p["prior_retention"]["git_observation"].update(old_git_sha256="0" * 64),
                    lambda p: p.update(current_code_forms_quote_bytes=p["current_code_forms_quote_bytes"] + 1),
                    lambda p: p.update(current_code_forms_quote_bytes=float(p["current_code_forms_quote_bytes"])),
                )):
                    changed = copy.deepcopy(packet)
                    mutate(changed)
                    changed_desc = gate.write_record_v1(root / ("changed-%d.json" % index), changed, cap=gate.PACKET_LIMIT)
                    with self.assertRaises(gate.Gate2Refusal):
                        gate.validate_packet_v1(project_root=root, packet_descriptor=changed_desc,
                            expected_packet_sha256=changed_desc["sha256"], expected_code_commit="a" * 40)
                (root / gate.CODE_PATHS[0]).write_bytes(b"# modified helper\n")
                with self.assertRaises(gate.Gate2Refusal):
                    gate.validate_packet_v1(project_root=root, packet_descriptor=descriptor,
                        expected_packet_sha256=descriptor["sha256"], expected_code_commit="a" * 40)

    def test_prior_authority_requires_completed_bound_receipt_and_unchanged_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "project"
            root.mkdir()
            data = b"# controlled bootstrap\n"
            code = {gate.CODE_PATHS[1]: {"size_bytes": len(data), "sha256": sha(data),
                "git_blob": hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()}}
            review = {"commit": "a"*40, "approval_reference": "controlled review", "evidence_sha256": "b"*64}
            descriptor, prior, native = self.prior_authority(root, code, review)
            authority_path = Path(descriptor["path"])
            original = authority_path.read_bytes()
            with patch.object(component, "REVIEW_REPO_ROOT_LINUX_V1", root), \
                    patch.object(component, "verify_prior_retention_v1", return_value=native) as fresh:
                returned = gate._authenticate_prior_retention_v1(root, review, code, "controlled-boot", descriptor, prior)
                self.assertEqual(returned, native)
                fresh.assert_called_once_with(root, git_observation=prior["git_observation"])
                for field in ("retention", "helper_code"):
                    candidate = json.loads(original)
                    if field == "retention":
                        candidate["context"]["retention"]["native"]["owned_upper_bytes"] = 2102272.0
                    else:
                        item = next(iter(candidate["context"]["helper_code"].values()))
                        item["size_bytes"] = float(item["size_bytes"])
                    candidate["context_sha256"] = sha(canonical(candidate["context"]))
                    body = canonical(candidate)
                    authority_path.write_bytes(body)
                    desc = {"path": str(authority_path), "size_bytes": len(body), "sha256": sha(body)}
                    with self.subTest(typed_binding=field), self.assertRaises(gate.Gate2Refusal):
                        gate._authenticate_prior_retention_v1(root, dict(review, evidence_sha256=sha(body)),
                            code, "controlled-boot", desc, prior)
                mutations = (
                    lambda a: a.update(schema_version=True),
                    lambda a: a.update(unreviewed=True),
                    lambda a: a.update(code_commit="f"*40),
                    lambda a: a.update(approval_reference="another review"),
                    lambda a: a.update(external_approval_required=False),
                    lambda a: a["context"].update(boot_id="another boot"),
                    lambda a: a["context"].update(capture_source_sha256="0"*64),
                    lambda a: a["context"]["retention"]["native"].update(physical_acceptance=True),
                    lambda a: a["context"]["retention"]["native"].update(owned_upper_bytes=True),
                    lambda a: a["context"]["retention"]["native"].update(old_f2_upper_bytes=393217),
                    lambda a: a["context"]["retention"]["native"].update(unreviewed=0),
                    lambda a: a["context"]["retention"]["native"].update(source_rows_sha256="0"*64),
                    lambda a: a["context"]["retention"]["git_observation"]["component"].update(sha256="0"*64),
                    lambda a: a["helper_code"][setup.SETUP_REL].update(path=str(WINDOWS_REPO / "foreign.py")),
                    lambda a: a["helper_code"][setup.CAPTURE_REL].pop("path"),
                    lambda a: a["helper_code"][setup.SETUP_REL].update(size_bytes=38.0),
                )
                for number, mutate in enumerate(mutations):
                    candidate = json.loads(original)
                    mutate(candidate)
                    candidate["context_sha256"] = sha(canonical(candidate["context"]))
                    body = canonical(candidate)
                    authority_path.write_bytes(body)
                    desc = {"path": str(authority_path), "size_bytes": len(body), "sha256": sha(body)}
                    changed_review = dict(review, evidence_sha256=desc["sha256"])
                    with self.subTest(number=number), self.assertRaises(gate.Gate2Refusal):
                        gate._authenticate_prior_retention_v1(root, changed_review, code, "controlled-boot",
                            desc, candidate["context"]["retention"])
                for body in (json.dumps(json.loads(original)).encode(),
                             b'{"schema_version":1,' + original[1:]):
                    authority_path.write_bytes(body)
                    desc = {"path": str(authority_path), "size_bytes": len(body), "sha256": sha(body)}
                    with self.assertRaises(gate.Gate2Refusal):
                        gate._authenticate_prior_retention_v1(root, dict(review, evidence_sha256=sha(body)),
                            code, "controlled-boot", desc, prior)
                authority_path.write_bytes(original)
                foreign = dict(descriptor, path=str(root / "foreign-authority.json"))
                with self.assertRaisesRegex(gate.Gate2Refusal, "operator_authority_path"):
                    gate._authenticate_prior_retention_v1(root, review, code, "controlled-boot", foreign, prior)
                helper = root / "tests/fixtures/accepted_policy_fixture_compiler_gate2_capture_v1.py"
                helper.write_bytes(b"# changed after packet approval\n")
                with self.assertRaises(gate.Gate2Refusal):
                    gate._authenticate_prior_retention_v1(root, review, code, "controlled-boot", descriptor, prior)
                self.assertFalse((root / "outputs").exists())

    def test_prior_retention_is_bounded_before_encoding_or_authority_reads(self):
        with patch.object(component, "canonical_json_v1", side_effect=AssertionError("encoded oversized prior")), \
                patch.object(gate, "_bound_descriptor", side_effect=AssertionError("read authority before bound")):
            with self.assertRaisesRegex(gate.Gate2Refusal, "prior_retention_bound"):
                gate._authenticate_prior_retention_v1(Path("/unused"), {}, {}, "unused", {}, {"x": "x"*4096})

    def test_evidence_footer_private_bound_refuses_before_reading_the_oversized_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            evidence = {}
            for name in gate.EVIDENCE_NAMES:
                data = b"x"*16385 if name == "f2_accounting" else b""
                path = root / name
                path.write_bytes(data)
                evidence[name] = {"path": str(path), "size_bytes": len(data), "sha256": sha(data)}
            with patch.object(gate, "_read", wraps=gate._read) as read:
                with self.assertRaisesRegex(gate.Gate2Refusal, "^descriptor$"):
                    gate._authenticate_evidence(evidence, {}, "a"*64)
                self.assertNotIn(root / "f2_accounting", [Path(call.args[0]) for call in read.call_args_list])
            self.assertEqual((root / "f2_accounting").read_bytes(), b"x"*16385)

    def test_corrected_b2_index_never_trusts_stale_self_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "runs").mkdir()
            (root / "outputs/B2").mkdir(parents=True)
            raw_member = b"original before/after\n"
            member = root / "outputs/B2/member.original"
            member.write_bytes(raw_member)
            manifest = root / "runs/B2.originals.sha256"
            manifest.write_bytes((sha(raw_member) + "  outputs/B2/member.original\n" +
                                  "0" * 64 + "  runs/B2.originals.sha256\n").encode("ascii"))
            with patch.dict(gate.B_ORIGINAL_SHA256, {"b2_manifest": sha(manifest.read_bytes())}):
                descriptor = gate.build_b2_index_v1(b_root=root, output_path=root / "corrected.json")
                value = json.loads(Path(descriptor["path"]).read_bytes())
                self.assertEqual(value["files"]["runs/B2.originals.sha256"]["sha256"], sha(manifest.read_bytes()))
                self.assertNotIn("corrected.json", value["files"])
                member.write_bytes(b"drift\n")
                with self.assertRaises(gate.Gate2Refusal):
                    gate.build_b2_index_v1(b_root=root, output_path=root / "second.json")


class FixedEffectsTests(unittest.TestCase):
    def test_native_guard_is_fixed_bounded_and_preserves_overflow_prefix(self):
        import io
        class Stream(io.BytesIO):
            def fileno(self):
                return 18
        class Process:
            pid = 88
            returncode = 0
            def __init__(self):
                self.stdout, self.stderr = Stream(b"123456"), Stream(b"")
            def poll(self):
                return 0
            def wait(self, timeout=None):
                return 0
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate.subprocess, "Popen", return_value=Process()) as spawn, \
                 patch.object(gate.os, "set_blocking"), \
                 patch.object(gate.select, "select", side_effect=lambda readers, *_: (readers, [], [])), \
                 patch.object(gate.time, "monotonic_ns", return_value=100):
                with self.assertRaises(gate.Gate2Refusal) as found:
                    gate.capture_guard_v1("gpu", output_dir=root, absolute_deadline_ns=10_000_000_000,
                                          stdout_limit=4)
                self.assertEqual((root / "gpu.stdout.original").read_bytes(), b"1234")
                self.assertIn("guard_stdout_overflow", found.exception.facts["causes"])
                self.assertEqual(spawn.call_args.args[0][0], "/usr/lib/wsl/lib/nvidia-smi")
                self.assertTrue(spawn.call_args.kwargs["start_new_session"])
            with patch.object(gate.subprocess, "Popen", side_effect=AssertionError("must not spawn")):
                with self.assertRaises(gate.Gate2Refusal):
                    gate.capture_guard_v1("arbitrary", output_dir=root, absolute_deadline_ns=10_000_000_000)

    def test_identity_refuses_drift_before_owner_and_records_only_four_gets(self):
        image = {"Id": gate.compiler.PROVIDER_ID, "RepoDigests": [gate.compiler.PROVIDER],
                 "Size": gate.EXPECTED["provider_size"], "RootFS": {"Type": "layers", "Layers": []},
                 "Config": {"Env": ["PATH=/usr/bin:/bin"], "Volumes": None},
                 "Manifests": [{"ID": gate.compiler.PROVIDER_PLATFORM_MANIFEST, "Available": True,
                                  "ImageData": {"Size": {"Unpacked": gate.EXPECTED["unpacked_bytes"]}}}]}
        version = {"Version": "29.7.2", "MinAPIVersion": "1.40", "ApiVersion": "1.55"}
        info = {"ID": gate.EXPECTED["engine_id"], "DockerRootDir": "/var/lib/docker", "Driver": "overlayfs",
                "CgroupDriver": "systemd", "CgroupVersion": "2", "KernelVersion": gate.EXPECTED["kernel"],
                "SecurityOptions": gate.EXPECTED["security_options"], "Runtimes": {"runc": {}}}
        calls = []
        class Client:
            def __init__(self, *_):
                self.facts = outcome("C1")[0]["rpc"]
            def request(self, method, path, **kwargs):
                calls.append((method, path))
                return version if path == "/version" else info if path == "/info" else image if "/images/" in path else [
                    {"Id": cid, "State": "exited"} for cid in gate.B_CIDS]
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate.compiler, "_DockerClientV1", Client), \
             patch.dict(gate.EXPECTED, {"rootfs_sha256": sha(canonical(image["RootFS"])),
                 "env_keys_sha256": sha(canonical(["PATH"])), "runtimes_sha256": sha(canonical(info["Runtimes"]))}):
            result = gate.observe_identity_v1(output_dir=Path(tmp).resolve(), expected_cids=list(gate.B_CIDS),
                                              absolute_deadline_ns=10**18)
            self.assertEqual(len(calls), 4)
            self.assertTrue(all(method == "GET" for method, _ in calls))
            self.assertIsInstance(result["rpc"]["rpc"][0]["epoch_before"], list)
            gate.write_record_v1(Path(tmp).resolve() / "identity.json", result, cap=gate.RECORD_LIMIT)
            info["Driver"] = "foreign"
            with self.assertRaises(gate.Gate2Refusal):
                gate.observe_identity_v1(output_dir=Path(tmp).resolve(), expected_cids=list(gate.B_CIDS),
                                          absolute_deadline_ns=10**18)

    def test_c6_fault_is_exact_first_elf_write_and_restores_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            original = gate.compiler._export_member_open
            with gate.c6_export_fault_v1(root):
                with gate.compiler._export_member_open(root / "compiler.stdout.original") as file:
                    file.write(b"unaffected")
                with gate.compiler._export_member_open(root / "engine.unaccepted") as file:
                    with self.assertRaisesRegex(OSError, "synthetic C6"):
                        file.write(b"actual ELF chunk")
            self.assertIs(gate.compiler._export_member_open, original)
            self.assertEqual((root / "compiler.stdout.original").read_bytes(), b"unaffected")
            self.assertEqual((root / "engine.unaccepted").read_bytes(), b"")

    def test_kernel_delta_accepts_only_attributable_sig25_assembler_dump(self):
        before = b"[ 1.0] boot complete\n"
        lines = (b"[ 2.0] as: potentially unexpected fatal signal 25.\n"
                 b"[ 2.1] CPU: 1 PID: 22 Comm: as Not tainted 6.6.87.2-microsoft-standard-WSL2 #1\n"
                 b"[ 2.2] RIP: 0033:0x401007\n"
                 b"[ 2.3] Process 12(as) has RLIMIT_CORE set to 1\n[ 2.4] Aborting core\n")
        self.assertTrue(gate.kernel_delta_v1("C3", before, before + lines, b"as: File size limit exceeded\n")["passed"])
        self.assertFalse(gate.kernel_delta_v1("C1", before, before + lines, b"")["passed"])
        self.assertFalse(gate.kernel_delta_v1("C3", before, before + lines + b"[ 3.0] unrelated crash\n",
                                             b"as: File size limit exceeded\n")["passed"])
        self.assertFalse(gate.kernel_delta_v1("C3", before, before + lines.replace(b"signal 25", b"signal 31"),
                                             b"as: File size limit exceeded\n")["passed"])
        # B2 originals prove CPU PID is host-native (1120) while the core
        # diagnostic uses container PID (12); equality would be a false gate.
        self.assertTrue(gate.kernel_delta_v1("C3", before, before + lines,
                                            b"as: File size limit exceeded\n")["passed"])
        audit = b'[ 2.5] audit: type=1701 audit(1.2:3): auid=4294967295 uid=1000 gid=1000 pid=22 comm="as" exe="/usr/bin/as" sig=25 res=1\n'
        self.assertTrue(gate.kernel_delta_v1("C3", before, before + lines + audit,
                                            b"as: File size limit exceeded\n")["passed"])
        self.assertFalse(gate.kernel_delta_v1("C3", before, before + lines + audit.replace(b"pid=22", b"pid=99"),
                                             b"as: File size limit exceeded\n")["passed"])

    def test_d_binding_cannot_use_only_c1_or_arbitrary_elf(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate, "validate_packet_v1", return_value={}):
            with self.assertRaises(gate.Gate2Refusal):
                gate.validated_c1_binding_v1(project_root=Path(tmp).resolve(), packet_descriptor={},
                    expected_packet_sha256="a" * 64, expected_code_commit="b" * 40, completion_authorities={})

    def test_fixed_runner_keeps_outer_facts_and_refuses_any_repeat(self):
        self._fixed_runner_replay(False)

    def test_resume_runner_keeps_owner_parent_relative_admission_and_full_replay(self):
        self._fixed_runner_replay(True)

    def _fixed_runner_replay(self, resume):
        with tempfile.TemporaryDirectory() as tmp:
            owner_root = Path(tmp).resolve()
            root = owner_root/'r1' if resume else owner_root
            if resume:
                root.mkdir()
                self.enterContext(patch.object(gate, 'RESUME_OWNER_ROOT_V1', owner_root))
                self.enterContext(patch.object(gate, 'RESUME_ROOT_V1', root))
                self.enterContext(patch.object(gate.compiler, '_compiler_proc_read_v1', return_value=b'boot\n'))
            review = {"commit": "c" * 40, "approval_reference": "controlled", "evidence_sha256": "d" * 64}
            seed = component.component_seed_v1(review=review, bindings={"host_sha256": "1" * 64,
                "publisher_sha256": "2" * 64, "profile_sha256": "3" * 64},
                engine={"driver": "overlayfs", "cgroup_driver": "systemd", "security_options": [], "runtimes_sha256": "4" * 64},
                provider={"rootfs_sha256": "5" * 64, "size_bytes": 1}, environment_keys=["PATH"],
                mounts_sha256=gate.MOUNTS_SHA256, proofs=dict.fromkeys(gate.PROOF_SOURCES, "6" * 64))
            packet = {"initial_charged_bytes": 11890688, "boot_id": "boot", "seed": seed,
                      "initial_measurement": {"c_free_bytes": 100_000_000_000, "ext4_used_bytes": 300_000_000_000},
                      "seed_sha256": sha(canonical(seed)), "code_review": review, "physical_plan": {"sha256": "7" * 64}}
            if resume:
                packet['resume_context'] = {'owner_project_root': str(owner_root), 'project_root': str(root)}
            seen_by_cid = {}
            kernel_now = [b"[ 1.0] boot\n"]
            monotonic_now = [1_000_000_000]
            authorities = {}
            operation = [None, 0]
            measurement_now = {"c_free_bytes": 99_000_000_000, "ext4_used_bytes": 300_000_000_000}
            def measurement():
                if operation[0] is not None:
                    output = root / "outputs" / operation[0]
                    position = operation[1]
                    if position == 0:
                        self.assertFalse(output.exists(), "entry measurement must precede the first allocation")
                    else:
                        self.assertTrue((output / "run.result.original.json").exists())
                        self.assertEqual((output / "run.accounting.original.json").exists(), position >= 2)
                        self.assertEqual((output / "outer.invocation.original.json").exists(), position >= 4)
                    operation[1] += 1
                return dict(measurement_now)
            def guards(output, deadline, *, gpu):
                output.mkdir(mode=0o700)
                if output.parent.parent.name == "C3" and not gpu:
                    kernel_now[0] += (b"[ 2.0] as: potentially unexpected fatal signal 25.\n"
                        b"[ 2.1] CPU: 1 PID: 22 Comm: as Not tainted 6.6.87.2-microsoft-standard-WSL2 #1\n"
                        b"[ 2.2] RIP: 0033:0x401007\n[ 2.3] Process 12(as) has RLIMIT_CORE set to 1\n[ 2.4] Aborting core\n")
                path = output / "kernel.txt"
                path.write_bytes(kernel_now[0])
                crash = gate.write_record_v1(output / "crashes.json", [])
                return {"boot_id": "boot", "measure": {"c_free_bytes": 100_000_000_000,
                    "ext4_used_bytes": 300_000_000_000}, "crashes": crash,
                    "dmesg": {"stdout": {"path": str(path), "size_bytes": path.stat().st_size, "sha256": sha(path.read_bytes())}}}
            def compile(**kwargs):
                expected_owner = owner_root if resume else root
                self.assertEqual(kwargs['project_root'], expected_owner)
                admission = json.loads(Path(kwargs['admission']['path']).read_bytes())
                self.assertEqual(admission['project_root'], str(expected_owner))
                self.assertEqual(admission['source']['relative_path'],
                    ('r1/' if resume else '')+'outputs/'+kwargs['source_path'].parent.name+'/engine.c')
                stage = kwargs["source_path"].parent.name
                if stage == "C5":
                    monotonic_now[0] += 45_000_000_000
                owner, seen = outcome(stage)
                owner["cid"] = "%064x" % (gate.STAGES.index(stage) + 20)
                seen["final_inspect"]["Id"] = owner["cid"]
                owner["live"]["mounts_sha256"] = gate.MOUNTS_SHA256
                seen_by_cid[owner["cid"]] = seen
                output = root / "outputs" / stage / "engine.compiler-originals"
                output.mkdir()
                (output / "export.header.original").write_bytes(seen["header_original"])
                for name, filename in (("stdout", "compiler.stdout.original"), ("stderr", "compiler.stderr.original"), ("elf", "engine.unaccepted")):
                    (output / filename).write_bytes(seen["members"][name])
                (output / "owner.result.original.json").write_bytes(canonical(seen["owner_receipt"]))
                request = ("POST /v1.55/containers/" + owner["cid"] + "/wait?condition=not-running HTTP/1.1\r\n\r\n").encode()
                reply_body = canonical(seen["wait_replies"][0])
                reply = b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(reply_body)).encode() + b"\r\n\r\n" + reply_body
                (output / "RPC01.request.original").write_bytes(request)
                (output / "RPC01.reply.original").write_bytes(reply)
                if stage != "C1":
                    error = gate.compiler.FixtureCompilerError(*owner["causes"])
                    error.facts = owner
                    raise error
                return owner
            def inspect(cid, output, deadline):
                output.mkdir()
                seen = seen_by_cid[cid]
                body = canonical(seen["final_inspect"])
                request = b"GET /v1.55/containers/" + cid.encode() + b"/json?size=1 HTTP/1.1\r\n\r\n"
                reply = b"HTTP/1.1 200 OK\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
                (output / "request").write_bytes(request)
                (output / "reply").write_bytes(reply)
                return {"value": seen["final_inspect"], "request": gate._descriptor(output / "request", request),
                        "reply": gate._descriptor(output / "reply", reply), "rpc": {}}
            with patch.object(gate, "validate_packet_v1", return_value=packet), \
                 patch.object(gate.time, "monotonic_ns", side_effect=lambda: monotonic_now[0]), \
                 patch.object(gate, "_measure_v1", side_effect=measurement) as measure, \
                 patch.object(gate, "_guard_snapshot_v1", side_effect=guards), \
                 patch.object(gate, "observe_identity_v1", return_value={}), \
                 patch.object(gate, "_post_inspect_v1", side_effect=inspect), \
                 patch.object(gate.compiler, "_compile_fixture_component_v1", side_effect=compile), \
                 patch.object(gate.os, "getuid", return_value=1000, create=True), \
                 patch.object(gate.os, "getgid", return_value=1000, create=True), \
                 patch.object(gate.os, "geteuid", return_value=1000, create=True), \
                 patch.object(gate.os, "getegid", return_value=1000, create=True):
                for stage in gate.STAGES:
                    operation[:] = [stage, 0]
                    # Large idle host changes between bounded operations do
                    # not erase earlier charges and do not become a new run.
                    measurement_now["c_free_bytes"] -= 1_000_000_000
                    result = gate.run_c_v1(stage, project_root=root, packet_descriptor={},
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities=authorities)
                    self.assertTrue(result["passed"], result)
                    footer_path = root / "outputs" / stage / "run.accounting.original.json"
                    footer = json.loads(footer_path.read_bytes())
                    self.assertEqual(footer["interval_before_measurement"], measurement_now)
                    self.assertEqual(footer["idle_gap_charged_bytes"], 0)
                    self.assertTrue(footer["comparison_complete"])
                    self.assertLessEqual(footer["control_all_forms_upper_bytes"], gate.CONTROL_LIMIT)
                    completion = gate.complete_c_invocation_v1(stage, project_root=root, returned_result=result,
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40)
                    self.assertFalse(completion["external_approval"])
                    self.assertTrue(completion["write_facts"]["complete"])
                    self.assertEqual(operation[1], 5)
                    # Only this explicit controlled vector simulates the
                    # trusted caller's independent native/write review.
                    authorities[stage] = completion["descriptor"]
                self.assertEqual(measure.call_count, 30)
                operation[0] = None
                outer = root / "outputs/C1/outer.owner.original.json"
                self.assertEqual(json.loads(outer.read_bytes())["receipt_persisted"], True)
                self.assertIsInstance(json.loads(outer.read_bytes())["rpc"]["rpc"][0]["epoch_before"], list)
                self.assertIsInstance(json.loads(outer.read_bytes())["rpc"]["rpc"][0]["peer"], dict)
                with self.assertRaises(gate.Gate2Refusal):
                    gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                binding = gate.validated_c1_binding_v1(project_root=root, packet_descriptor={},
                    expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities=authorities)
                self.assertEqual(len(set(binding["all_cids"])), 9)
                self.assertEqual(binding["last_tail_credit_bytes"], 0)
                self.assertEqual(binding["elf_sha256"], sha(elf()))
                for bad_authorities in ({}, {k: v for k, v in authorities.items() if k != "C6"},
                                        dict(authorities, C7=authorities["C6"])):
                    with self.subTest(authority_keys=list(bad_authorities)), self.assertRaises(gate.Gate2Refusal):
                        gate.validated_c1_binding_v1(project_root=root, packet_descriptor={},
                            expected_packet_sha256="a" * 64, expected_code_commit="c" * 40,
                            completion_authorities=bad_authorities)
                c6_completion = root / "outputs/C6/outer.invocation.original.json"
                saved_completion = c6_completion.read_bytes()
                original_completion = json.loads(saved_completion)
                for key, value in (("previous_completion_sha256", "0" * 64), ("returned_successfully", False),
                                   ("schema_version", True), ("returned_successfully", 1),
                                   ("code_commit", "f" * 40), ("packet_sha256", "f" * 64),
                                   ("result_sha256", "f" * 64), ("stage", "C5")):
                    bad_raw = canonical(dict(original_completion, **{key: value}))
                    c6_completion.write_bytes(bad_raw)
                    rebound = dict(authorities, C6=gate._descriptor(c6_completion, bad_raw))
                    with self.subTest(completion_field=key), self.assertRaises(gate.Gate2Refusal):
                        gate.validated_c1_binding_v1(project_root=root, packet_descriptor={},
                            expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities=rebound)
                c6_completion.write_bytes(saved_completion)
                c6_result = root / "outputs/C6/run.accounting.original.json"
                saved_result = c6_result.read_bytes()
                original_footer = json.loads(saved_result)
                for mutation in (
                    {"charge_bytes": 0, "ledger_after": original_footer["ledger_before"]},
                    {"retained_data_bytes": 0, "future_copy_upper_bytes": original_footer["retained_metadata_upper_bytes"]},
                    {"control_all_forms_upper_bytes": 0}, {"tail_reserved_bytes": 0},
                    {"nonoutput_growth_bytes": gate.RUNTIME_STOP + 1}, {"comparison_complete": False},
                    {"result": dict(original_footer["result"], sha256="0" * 64)},
                ):
                    with self.subTest(mutation=mutation):
                        changed_result = dict(original_footer, **mutation)
                        changed_footer_raw = canonical(changed_result)
                        c6_result.write_bytes(changed_footer_raw)
                        # A rebound outer descriptor still cannot bypass the
                        # independent allocation/ledger/originals evaluation.
                        rebound_completion = canonical(dict(original_completion, accounting_sha256=sha(changed_footer_raw)))
                        c6_completion.write_bytes(rebound_completion)
                        rebound = dict(authorities, C6=gate._descriptor(c6_completion, rebound_completion))
                        with self.assertRaises(gate.Gate2Refusal):
                            gate.validated_c1_binding_v1(project_root=root, packet_descriptor={},
                                expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities=rebound)
                c6_result.write_bytes(saved_result)
                c6_completion.write_bytes(saved_completion)
                for relative in ("engine.c", "component.seed.original.json", "component.admission.original.json"):
                    original_input = root / "outputs/C1" / relative
                    saved_input = original_input.read_bytes()
                    original_input.write_bytes(b"{}")
                    with self.subTest(drifted_input=relative), self.assertRaises(gate.Gate2Refusal):
                        gate.validated_c1_binding_v1(project_root=root, packet_descriptor={},
                            expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities=authorities)
                    original_input.write_bytes(saved_input)
                (root / "outputs/C4/engine.compiler-originals/compiler.stderr.original").write_bytes(b"changed")
                with self.assertRaises(gate.Gate2Refusal):
                    gate.validated_c1_binding_v1(project_root=root, packet_descriptor={},
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities=authorities)
                if resume:
                    # The complete six-stage/replay vector above uses the fixed
                    # child. Remaining legacy cases create arbitrary new roots.
                    return
                # A final accounting reserve denial must not start a new
                # refusal persistence operation after that denial.
                root = root / "final-accounting-refusal"
                root.mkdir()
                real_reserve, reserve_calls = gate.reserve_v1, []
                def denied_final_reserve(**kwargs):
                    reserve_calls.append(kwargs)
                    if len(reserve_calls) == 3:
                        raise gate.Gate2Refusal("ledger_reserve")
                    return real_reserve(**kwargs)
                with patch.object(gate, "reserve_v1", side_effect=denied_final_reserve):
                    with self.assertRaises(gate.Gate2Refusal):
                        gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                            expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                self.assertTrue((root / "outputs/C1/run.result.original.json").exists())
                self.assertFalse((root / "outputs/C1/run.refusal.original.json").exists())
                fault_parent = root
                real_open = Path.open
                class LateClose:
                    def __init__(self, file):
                        self.file = file
                    def close(self):
                        self.file.close()
                        monotonic_now[0] += gate.RUN_NS + 1
                    def __getattr__(self, name):
                        return getattr(self.file, name)
                for fault in ("footer_close", "final_measure", "completion_close", "completion_final_measure"):
                    with self.subTest(late_fault=fault):
                        root = fault_parent / fault
                        root.mkdir()
                        def opener(path, *args, **kwargs):
                            file = real_open(path, *args, **kwargs)
                            target = "run.accounting.original.json" if fault == "footer_close" else "outer.invocation.original.json"
                            return LateClose(file) if path.name == target and args and args[0] == "xb" else file
                        measure_calls = []
                        def late_measure():
                            measure_calls.append(None)
                            if len(measure_calls) == (3 if fault == "final_measure" else 2):
                                monotonic_now[0] += gate.RUN_NS + 1
                            return measurement()
                        if fault.startswith("completion"):
                            returned = gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                                expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                            effect = patch.object(Path, "open", opener) if fault == "completion_close" else patch.object(gate, "_measure_v1", side_effect=late_measure)
                            with effect, self.assertRaises(gate.Gate2Refusal) as found:
                                gate.complete_c_invocation_v1("C1", project_root=root, returned_result=returned,
                                    expected_packet_sha256="a" * 64, expected_code_commit="c" * 40)
                            self.assertFalse(found.exception.facts["external_approval"])
                            completion_raw = (root / "outputs/C1/outer.invocation.original.json").read_bytes()
                            self.assertTrue(json.loads(completion_raw)["returned_successfully"])
                            if fault == "completion_final_measure":
                                self.assertTrue(found.exception.facts["write_facts"]["complete"])
                        else:
                            effect = patch.object(Path, "open", opener) if fault == "footer_close" else patch.object(gate, "_measure_v1", side_effect=late_measure)
                            with effect, self.assertRaises(gate.Gate2Refusal):
                                gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                                    expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                        self.assertTrue(json.loads((root / "outputs/C1/run.accounting.original.json").read_bytes())["comparison_complete"])
                        # A leftover comparison or invocation claim cannot
                        # generate its own independently reviewed authority.
                        with self.assertRaises(gate.Gate2Refusal):
                            gate.run_c_v1("C2", project_root=root, packet_descriptor={},
                                expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                        self.assertFalse((root / "outputs/C2").exists())

    def test_allocation_controls_include_root_receipts_and_rpc_but_exclude_only_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "engine.compiler-originals").mkdir()
            for name in ("engine.c", "engine.compiler-originals/compiler.stdout.original",
                         "engine.compiler-originals/compiler.stderr.original", "engine.compiler-originals/engine.unaccepted"):
                (root / name).write_bytes(b"p" * 8192)
            for name in ("outer.owner.original.json", "observations.original.json", "evaluation.original.json",
                         "run.result.original.json", "engine.compiler-originals/RPC01.reply.original",
                         "engine.compiler-originals/export.header.original", "engine.compiler-originals/owner.result.original.json"):
                (root / name).write_bytes(b"c" * 4096)
            actual = gate._allocation_summary_v1(root)
            payload_allocation = sum((root / name).stat().st_blocks * 512 for name in
                ("engine.c", "engine.compiler-originals/compiler.stdout.original",
                 "engine.compiler-originals/compiler.stderr.original", "engine.compiler-originals/engine.unaccepted"))
            self.assertEqual(actual["data_bytes"] - actual["control_data_bytes"], payload_allocation)
            self.assertGreaterEqual(actual["control_data_bytes"], 7 * 4096)
            self.assertEqual(actual["metadata_upper_bytes"], actual["entries"] * 4096)

    def test_metadata_deadline_after_fsync_preserves_incomplete_facts_and_does_not_open_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            now = [100]
            def late_fsync(_):
                now[0] = 1000
            with patch.object(gate.time, "monotonic_ns", side_effect=lambda: now[0]), \
                 patch.object(gate.os, "fsync", side_effect=late_fsync):
                with self.assertRaises(gate.Gate2Refusal) as found:
                    gate.write_record_v1(root / "late.json", {"value": 1}, absolute_deadline_ns=500)
                facts = found.exception.facts
                self.assertTrue(facts["fsync_completed"])
                self.assertTrue(facts["close_completed"])
                self.assertTrue(facts["deadline_failed"])
                self.assertFalse(facts["complete"])
                with self.assertRaises(gate.Gate2Refusal):
                    gate.write_record_v1(root / "later.json", {"value": 1}, absolute_deadline_ns=500)
                self.assertFalse((root / "later.json").exists())

    def test_c_failure_after_original_deadline_preserves_facts_without_new_refusal_write(self):
        now = [100]
        original_facts = {"written_bytes": 1, "write_extent_unknown": True}
        def late_guard(*args, **kwargs):
            now[0] += gate.RUN_NS + 1
            raise gate.Gate2Refusal("controlled_late_guard", original_facts)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate.time, "monotonic_ns", side_effect=lambda: now[0]), \
                 patch.object(gate, "validate_packet_v1", return_value={"initial_charged_bytes": 11890688}), \
                 patch.object(gate, "_measure_v1", return_value={"c_free_bytes": 99_000_000_000,
                     "ext4_used_bytes": 300_000_000_000}), \
                 patch.object(gate, "_guard_snapshot_v1", side_effect=late_guard), \
                 patch.object(gate.os, "getuid", return_value=1000), patch.object(gate.os, "getgid", return_value=1000), \
                 patch.object(gate.os, "geteuid", return_value=1000), patch.object(gate.os, "getegid", return_value=1000), \
                 patch.object(gate, "write_record_v1", side_effect=AssertionError("late fresh write")):
                with self.assertRaises(gate.Gate2Refusal) as found:
                    gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                self.assertEqual(found.exception.facts["failure_facts"], original_facts)
                self.assertFalse((root / "outputs/C1/run.refusal.original.json").exists())

    def test_c_floor_loss_before_owner_starts_no_new_refusal_persistence(self):
        def guards(path, *_args, **_kwargs):
            path.mkdir()
            return {"boot_id": "boot", "measure": {"c_free_bytes": 1, "ext4_used_bytes": 300_000_000_000}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate.time, "monotonic_ns", return_value=100), \
                 patch.object(gate, "validate_packet_v1", return_value={"initial_charged_bytes": 11890688, "boot_id": "boot"}), \
                 patch.object(gate, "_measure_v1", return_value={"c_free_bytes": 99_000_000_000,
                     "ext4_used_bytes": 300_000_000_000}), \
                 patch.object(gate, "_guard_snapshot_v1", side_effect=guards), \
                 patch.object(gate.os, "getuid", return_value=1000), patch.object(gate.os, "getgid", return_value=1000), \
                 patch.object(gate.os, "geteuid", return_value=1000), patch.object(gate.os, "getegid", return_value=1000), \
                 patch.object(gate, "write_record_v1", side_effect=AssertionError("write after floor denial")):
                with self.assertRaises(gate.Gate2Refusal) as found:
                    gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                self.assertEqual(found.exception.facts["cause"], "capacity_floor")
                self.assertFalse((root / "outputs/C1/run.refusal.original.json").exists())

    def test_outer_receipt_write_and_close_faults_preserve_actual_owner_in_exception(self):
        real_open = Path.open
        class BrokenOwnerReceipt:
            def __init__(self, file):
                self.file = file
            def write(self, raw):
                self.file.write(raw[:1])
                raise OSError("controlled unknown write extent")
            def close(self):
                self.file.close()
                raise OSError("controlled distinct close failure")
            def __getattr__(self, name):
                return getattr(self.file, name)
        def opener(path, *args, **kwargs):
            file = real_open(path, *args, **kwargs)
            return BrokenOwnerReceipt(file) if path.name == "outer.owner.original.json" else file
        def guards(path, *_args, **_kwargs):
            path.mkdir()
            return {"boot_id": "boot", "measure": {"c_free_bytes": 99_000_000_000,
                "ext4_used_bytes": 300_000_000_000}}
        actual_owner = outcome("C1")[0]
        packet = {"initial_charged_bytes": 11890688, "boot_id": "boot", "seed": {"bindings": {}}, "seed_sha256": sha(canonical({"bindings": {}})),
                  "code_review": {}, "physical_plan": {"sha256": "7" * 64}}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.object(gate.time, "monotonic_ns", return_value=100), \
                 patch.object(Path, "open", opener), \
                 patch.object(gate, "validate_packet_v1", return_value=packet), \
                 patch.object(gate, "_measure_v1", return_value={"c_free_bytes": 99_000_000_000,
                     "ext4_used_bytes": 300_000_000_000}), \
                 patch.object(gate, "_guard_snapshot_v1", side_effect=guards), \
                 patch.object(gate, "observe_identity_v1", return_value={}), \
                 patch.object(gate.component, "component_admission_v1", return_value={}), \
                 patch.object(gate.compiler, "_compile_fixture_component_v1", return_value=actual_owner), \
                 patch.object(gate.os, "getuid", return_value=1000), patch.object(gate.os, "getgid", return_value=1000), \
                 patch.object(gate.os, "geteuid", return_value=1000), patch.object(gate.os, "getegid", return_value=1000):
                with self.assertRaises(gate.Gate2Refusal) as found:
                    gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
            facts = found.exception.facts
            self.assertEqual(facts["owner_facts"]["cid"], actual_owner["cid"])
            self.assertEqual(facts["owner_facts"]["export"], actual_owner["export"])
            self.assertTrue(facts["failure_facts"]["write_extent_unknown"])
            self.assertFalse(facts["failure_facts"]["close_completed"])
            self.assertIn("record_write_OSError", facts["failure_facts"]["failure_causes"])
            self.assertIn("record_close_OSError", facts["failure_facts"]["failure_causes"])
            refusal = (root / "outputs/C1/run.refusal.original.json").read_bytes()
            self.assertLessEqual(len(refusal), 4096)
            self.assertNotIn("owner_facts", json.loads(refusal))

    def test_actor_effective_ids_and_fragment_backing_refuse_before_packet_or_output(self):
        import types
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            for bad in ("geteuid", "getegid"):
                with self.subTest(bad=bad), patch.object(gate, "validate_packet_v1", side_effect=AssertionError("too late")), \
                     patch.object(gate.os, "getuid", return_value=1000), patch.object(gate.os, "getgid", return_value=1000), \
                     patch.object(gate.os, "geteuid", return_value=1001 if bad == "geteuid" else 1000), \
                     patch.object(gate.os, "getegid", return_value=1001 if bad == "getegid" else 1000):
                    with self.assertRaises(gate.Gate2Refusal):
                        gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                            expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                    self.assertFalse((root / "outputs").exists())
            with patch.object(gate, "validate_packet_v1", side_effect=AssertionError("too late")), \
                 patch.object(gate.os, "getuid", return_value=1000), patch.object(gate.os, "getgid", return_value=1000), \
                 patch.object(gate.os, "geteuid", return_value=1000), patch.object(gate.os, "getegid", return_value=1000), \
                 patch.object(gate.os, "statvfs", return_value=types.SimpleNamespace(f_frsize=8192)):
                with self.assertRaises(gate.Gate2Refusal):
                    gate.run_c_v1("C1", project_root=root, packet_descriptor={},
                        expected_packet_sha256="a" * 64, expected_code_commit="c" * 40, completion_authorities={})
                self.assertFalse((root / "outputs").exists())

    def test_failed_native_read_still_contains_owned_child_within_same_deadline(self):
        class Stream:
            def fileno(self):
                return 18
            def read(self, count):
                raise OSError("controlled pipe failure")
            def close(self):
                pass
        class Process:
            pid = 88
            stdout, stderr = Stream(), Stream()
            returncode = None
            def poll(self):
                return self.returncode
            def wait(self, timeout=None):
                self.returncode = -15
                return self.returncode
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate.subprocess, "Popen", return_value=Process()), \
             patch.object(gate.os, "set_blocking"), patch.object(gate.os, "killpg") as kill, \
             patch.object(gate.select, "select", side_effect=lambda readers, *_: (readers, [], [])), \
             patch.object(gate.time, "monotonic_ns", return_value=100):
            with self.assertRaises(gate.Gate2Refusal):
                gate.capture_guard_v1("gpu", output_dir=Path(tmp).resolve(), absolute_deadline_ns=10_000_000_000)
            kill.assert_called_once_with(88, gate.signal.SIGTERM)

    def test_guard_failed_write_cannot_be_repaired_by_later_fsync_or_optional_record(self):
        import io
        class Stream(io.BytesIO):
            def fileno(self):
                return 18
        class Process:
            pid = 88
            returncode = 0
            def __init__(self):
                self.stdout, self.stderr = Stream(b"123456"), Stream(b"")
            def poll(self):
                return 0
        original_open = Path.open
        class BrokenWrite:
            def __init__(self, file, unknown):
                self.file, self.unknown = file, unknown
            def write(self, data):
                self.file.write(data[:1])
                if self.unknown:
                    raise OSError("partial write with unreturned extent")
                return 1
            def __getattr__(self, name):
                return getattr(self.file, name)
        for unknown in (False, True):
            with self.subTest(unknown=unknown), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                def opener(path, *args, **kwargs):
                    file = original_open(path, *args, **kwargs)
                    return BrokenWrite(file, unknown) if path.name == "gpu.stdout.original" else file
                with patch.object(Path, "open", opener), patch.object(gate.subprocess, "Popen", return_value=Process()), \
                     patch.object(gate.os, "set_blocking"), \
                     patch.object(gate.select, "select", side_effect=lambda readers, *_: (readers, [], [])), \
                     patch.object(gate.time, "monotonic_ns", return_value=100):
                    with self.assertRaises(gate.Gate2Refusal) as found:
                        gate.capture_guard_v1("gpu", output_dir=root, absolute_deadline_ns=10_000_000_000,
                                              record_original=False)
                facts = found.exception.facts
                self.assertFalse(facts["persisted"])
                self.assertTrue(facts["files"]["stdout"]["fsync_completed"])
                self.assertTrue(facts["files"]["stdout"]["close_completed"])
                self.assertEqual(facts["stdout"]["size_bytes"], None if unknown else 1)
                self.assertEqual(facts["stdout"]["sha256"], None if unknown else sha(b"1"))
                self.assertFalse((root / "gpu.capture.original.json").exists())

    def test_guard_late_fsync_starts_no_following_fsync_directory_sync_or_record(self):
        import io
        class Stream(io.BytesIO):
            def fileno(self):
                return 18
        class Process:
            pid = 88
            returncode = 0
            def __init__(self):
                self.stdout, self.stderr = Stream(b""), Stream(b"")
            def poll(self):
                return 0
        now = [100]
        def late_fsync(_):
            now[0] = 20_000_000_000
        with tempfile.TemporaryDirectory() as tmp, patch.object(gate.subprocess, "Popen", return_value=Process()), \
             patch.object(gate.os, "set_blocking"), \
             patch.object(gate.select, "select", side_effect=lambda readers, *_: (readers, [], [])), \
             patch.object(gate.time, "monotonic_ns", side_effect=lambda: now[0]), \
             patch.object(gate.os, "fsync", side_effect=late_fsync) as fsync, \
             patch.object(gate.compiler, "_compiler_directory_sync_v1", side_effect=AssertionError("late directory sync")):
            with self.assertRaises(gate.Gate2Refusal) as found:
                gate.capture_guard_v1("gpu", output_dir=Path(tmp).resolve(), absolute_deadline_ns=10_000_000_000,
                                      record_original=False)
            self.assertEqual(fsync.call_count, 1)
            self.assertTrue(found.exception.facts["files"]["stdout"]["close_completed"])
            self.assertFalse(found.exception.facts["files"]["stderr"]["fsync_completed"])
            self.assertIn("guard_deadline", found.exception.facts["causes"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
