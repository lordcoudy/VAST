"""Fixed invocation/prefix tests with controlled external effects only."""
import ast
import base64
import hashlib
import io
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
import zlib
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c

COMMIT = "a" * 40
SHA = "b" * 64
ROOT = "/home/s-a-balashov/work/vast-fixture-compiler-gate2-" + COMMIT + "-01"


class InvocationTests(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory()
        self.addCleanup(owned.cleanup)
        probe = patch.object(c, "RESUME_ROOT_V1", Path(owned.name).resolve() / "absent-r1", create=True)
        probe.start()
        self.addCleanup(probe.stop)

    def resume_packet(self, root):
        producer = "465ab7986939c67ae3594344ee3b6266cd2abd7a"
        return {"schema_version": 1, "artifact_kind": "vast_fixture_compiler_gate2_packet_v1",
                "project_root": str(root), "code_commit": COMMIT,
                "resume_context": {"schema_version": 1, "producer_commit": producer,
                    "owner_project_root": str(root.parent), "project_root": str(root),
                    "consumer_commit": COMMIT}}

    def test_resume_candidate_derives_only_child_completion_paths_and_existing_five_kwargs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "retained465" / "r1"
            root.mkdir(parents=True)
            raw = json.dumps(self.resume_packet(root), sort_keys=True, separators=(",", ":")).encode()
            (root / "gate2.packet.original.json").write_bytes(raw)
            with patch.object(c, "RESUME_ROOT_V1", root, create=True), \
                    patch.object(c, "RESUME_OWNER_ROOT_V1", root.parent, create=True):
                kw = c.parse_native_invocation_v1([COMMIT, str(len(raw)), hashlib.sha256(raw).hexdigest(),
                                                   ",".join(["456:" + SHA] * 6)], stage="D")
            self.assertEqual(set(kw), {"project_root", "packet_descriptor", "expected_packet_sha256",
                                     "expected_code_commit", "completion_authorities"})
            self.assertEqual(kw["project_root"], str(root))
            self.assertEqual(kw["completion_authorities"]["C6"]["path"],
                             str(root / "outputs/C6/outer.invocation.original.json"))

    def test_existing_resume_candidate_mismatch_never_falls_back_to_legacy_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "retained465" / "r1"
            root.mkdir(parents=True)
            for mutation in (lambda p: p.update(code_commit="f" * 40),
                             lambda p: p.update(project_root=str(root.parent)),
                             lambda p: p.pop("resume_context"),
                             lambda p: p["resume_context"].update(producer_commit="e" * 40),
                             lambda p: p["resume_context"].update(consumer_commit="e" * 40),
                             lambda p: p["resume_context"].update(owner_project_root=str(root)),
                             lambda p: p["resume_context"].update(schema_version=True)):
                packet = self.resume_packet(root)
                mutation(packet)
                raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
                (root / "gate2.packet.original.json").write_bytes(raw)
                with self.subTest(mutation=mutation), \
                        patch.object(c, "RESUME_ROOT_V1", root, create=True), \
                        patch.object(c, "RESUME_OWNER_ROOT_V1", root.parent, create=True), \
                        self.assertRaises(c.Gate2Refusal):
                    c.parse_native_invocation_v1([COMMIT, str(len(raw)), hashlib.sha256(raw).hexdigest(), "-"], stage="C1")
            raw = json.dumps(self.resume_packet(root), sort_keys=True, separators=(",", ":")).encode()
            (root / "gate2.packet.original.json").write_bytes(raw)
            for size, digest in ((len(raw) + 1, hashlib.sha256(raw).hexdigest()), (len(raw), "0" * 64)):
                with self.subTest(size=size, digest=digest), \
                        patch.object(c, "RESUME_ROOT_V1", root, create=True), \
                        patch.object(c, "RESUME_OWNER_ROOT_V1", root.parent, create=True), \
                        self.assertRaises(c.Gate2Refusal):
                    c.parse_native_invocation_v1([COMMIT, str(size), digest, "-"], stage="C1")

    def test_c_native_d_branch_uses_canonical_unchanged_d_and_never_c_run_or_completion(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as d
        args = [COMMIT, "1234", SHA, ",".join(["456:" + SHA] * 6)]
        with patch.object(d, "native_main_v1", return_value=7) as run_d, \
                patch.object(c, "run_c_v1") as run_c, patch.object(c, "complete_c_invocation_v1") as complete, \
                patch.object(c.os, "write"):
            self.assertEqual(c.native_main_v1(["D"] + args), 7)
        run_d.assert_called_once_with(args)
        run_c.assert_not_called()
        complete.assert_not_called()

    def test_fixed_external_args_derive_only_approved_prior_paths(self):
        kw = c.parse_native_invocation_v1([COMMIT, "1234", SHA, "-"], stage="C1")
        self.assertEqual(kw["project_root"], ROOT)
        self.assertEqual(kw["expected_code_commit"], COMMIT)
        self.assertEqual(kw["completion_authorities"], {})
        kw = c.parse_native_invocation_v1([COMMIT, "1234", SHA, ",".join(["456:" + SHA] * 6)], stage="D")
        self.assertEqual(list(kw["completion_authorities"]), list(c.STAGES))
        self.assertEqual(kw["completion_authorities"]["C6"], {
            "path": ROOT + "/outputs/C6/outer.invocation.original.json", "size_bytes": 456, "sha256": SHA})

    def test_foreign_commit_paths_counts_and_scalar_shapes_refuse(self):
        for args, stage in ((["A" * 40, "1234", SHA, "-"], "C1"),
                ([COMMIT, "true", SHA, "-"], "C1"), ([COMMIT, "0", SHA, "-"], "C1"),
                ([COMMIT, "1234", SHA, "../file"], "C2"),
                ([COMMIT, "1234", SHA, "8193:" + SHA], "C2"),
                ([COMMIT, "1234", SHA, "-"], "D"), ([COMMIT, "1234", SHA, "-"], "arbitrary")):
            with self.subTest(args=args, stage=stage), self.assertRaises(c.Gate2Refusal):
                c.parse_native_invocation_v1(args, stage=stage)

    def test_large_failure_retains_hash_ordered_causes_prefix_and_unknown(self):
        facts = {"causes": ["first", "secondary"], "write_extent_unknown": True, "payload": "x" * 60000}
        error = c.Gate2Refusal("stopped", facts)
        raw = c.native_failure_bytes_v1(error)
        self.assertLessEqual(len(raw), 768)
        value = json.loads(raw)
        self.assertEqual(value["causes"][:2], ["first", "secondary"])
        self.assertEqual(value["facts_sha256"], hashlib.sha256(c.component.canonical_json_v1(facts)).hexdigest())
        self.assertTrue(value["facts_remainder_unknown"])
        self.assertFalse(value["physical_acceptance"])
        self.assertTrue(value["external_status_eof_required"])

    def test_unserializable_failure_is_explicitly_unknown_and_still_bounded(self):
        raw = c.native_failure_bytes_v1(c.Gate2Refusal("stopped", {"opaque": object()}))
        self.assertLessEqual(len(raw), 768)
        self.assertTrue(json.loads(raw)["facts_unknown"])

    def test_adversarial_failure_labels_cycles_and_flags_remain_bounded(self):
        for facts in ({"causes": ["z" * 1000] * 20, "write_extent_unknown": True,
                "unknown_closure": True, "stdout_eof": False, "stderr_eof": False, "payload": "x" * 60000}, {}):
            if not facts:
                facts["cycle"] = facts
            raw = c.native_failure_bytes_v1(c.Gate2Refusal('\"\\\n' * 1000, facts))
            self.assertLessEqual(len(raw), 768)
            self.assertTrue(json.loads(raw)["cause_remainder_unknown"])
            self.assertTrue(json.loads(raw)["facts_remainder_unknown"])
            self.assertTrue(raw.endswith(b"\n"))

    def test_actual_c_refusal_and_completion_wrappers_project_nested_facts(self):
        for wrapper, facts in (("c_stage_stopped", {"cause": "guard_refused",
                "failure_facts": {"causes": ["guard_stdout_short_write", "guard_eof_unknown"],
                    "files": {"stdout": {"write_extent_unknown": True, "written_bytes": 7}}},
                "refusal_write_failure": {"failure_causes": ["record_deadline"], "write_extent_unknown": False}}),
                ("c_completion_stopped", {"cause": "record_short_write", "failure_facts": {
                    "write_extent_unknown": False, "written_bytes": 7, "failure_causes": ["record_short_write"]},
                    "write_facts": None})):
            raw = c.native_failure_bytes_v1(c.Gate2Refusal(wrapper, facts))
            value = json.loads(raw)
            self.assertLessEqual(len(raw), 768)
            self.assertEqual(value["causes"][0], facts["cause"])
            self.assertGreaterEqual(len(value["causes"]), 2 if wrapper == "c_stage_stopped" else 1)
            self.assertTrue(any("write_extent_unknown" == row[1] for row in value["observations"]))
            self.assertTrue(value["facts_remainder_unknown"])

    def test_bootstrap_import_and_resolution_errors_are_bounded(self):
        source = Path(c.__file__).read_text()
        prefix = source[:source.index("STAGES =")]
        args = ["program", "C1", COMMIT, "1234", SHA, "-"]
        for error in (OSError("resolve failed"), None):
            with patch.object(sys, "argv", args), patch.object(c.os, "write") as write, \
                    patch.object(Path, "resolve", side_effect=error, return_value=Path(ROOT) / "tests/fixtures/accepted_policy_fixture_compiler_gate2_c_v1.py"):
                if error is None:
                    original_import = __import__
                    def failing_import(name, *a, **kw):
                        if name == "tests.fixtures":
                            raise ImportError("damaged export")
                        return original_import(name, *a, **kw)
                    import_patch = patch("builtins.__import__", side_effect=failing_import)
                else:
                    import_patch = patch("builtins.__import__", wraps=__import__)
                with import_patch, self.assertRaises(SystemExit) as caught:
                    exec(compile(prefix, str(Path(c.__file__)), "exec"), {"__name__": "__main__", "__file__": str(Path(c.__file__))})
                self.assertEqual(caught.exception.code, 1)
                self.assertEqual(write.call_args.args, (2, b'{"cause":"c_native_bootstrap","unknown":true}\n'))

    def test_partial_and_unreturned_stdout_writes_refuse_with_truthful_extent(self):
        for effect, unknown in ((3, False), (OSError("partial unreturned"), True)):
            with self.subTest(effect=effect), patch.object(c.time, "monotonic_ns", return_value=100), \
                    patch.object(c.os, "write", side_effect=effect if isinstance(effect, Exception) else None,
                                 return_value=effect if isinstance(effect, int) else None):
                with self.assertRaises(c.Gate2Refusal) as caught:
                    c.emit_native_bytes_v1(b'{"ok":true}\n', 1000)
                self.assertIs(caught.exception.facts["write_extent_unknown"], unknown)

    def test_late_stdout_admission_does_not_write(self):
        with patch.object(c.time, "monotonic_ns", return_value=1001), patch.object(c.os, "write") as write:
            with self.assertRaises(c.Gate2Refusal):
                c.emit_native_bytes_v1(b'{}\n', 1000)
        write.assert_not_called()

    def test_flush_failure_and_late_flush_keep_confirmed_write_extent(self):
        raw = b'{}\n'
        for clock, flush in (([100, 100], OSError("pipe flush")), ([100, 100, 1001], None)):
            with patch.object(c.time, "monotonic_ns", side_effect=clock), \
                    patch.object(c.os, "write", return_value=len(raw)), patch.object(c.sys.stdout, "flush", side_effect=flush):
                with self.assertRaises(c.Gate2Refusal) as caught:
                    c.emit_native_bytes_v1(raw, 1000)
            self.assertEqual(caught.exception.facts["written_bytes"], len(raw))
            self.assertFalse(caught.exception.facts["write_extent_unknown"])
            self.assertEqual(caught.exception.facts["flush_completed"], flush is None)

    def test_isolated_cli_refuses_foreign_export_before_project_imports(self):
        source = Path(c.__file__).resolve()
        result = subprocess.run([sys.executable, "-I", "-S", "-B", str(source),
            "C1", COMMIT, "1234", SHA, "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")
        self.assertEqual(result.stderr, b'{"cause":"c_native_bootstrap","unknown":true}\n')

    def test_c_main_calls_existing_entrypoints_and_emits_only_completion(self):
        completion = {"completion": {"path": "fixed", "size_bytes": 123, "sha256": SHA},
                      "completion_deadline_ns": 1000, "external_approval": False}
        with patch.object(c, "run_c_v1", return_value={"actual": "result"}) as run, \
                patch.object(c, "complete_c_invocation_v1", return_value=completion) as complete, \
                patch.object(c, "emit_native_bytes_v1") as emit:
            self.assertEqual(c.native_main_v1(["C1", COMMIT, "1234", SHA, "-"]), 0)
        self.assertEqual(run.call_args.args, ("C1",))
        self.assertEqual(complete.call_args.kwargs["returned_result"], {"actual": "result"})
        self.assertEqual(json.loads(emit.call_args.args[0]), completion)
        self.assertEqual(emit.call_args.args[1], 1000)

    def test_c_failure_does_not_complete_and_uses_bounded_stderr(self):
        with patch.object(c, "run_c_v1", side_effect=c.Gate2Refusal("native_unknown", {"unknown_closure": True})), \
                patch.object(c, "complete_c_invocation_v1") as complete, patch.object(c.os, "write") as write:
            self.assertEqual(c.native_main_v1(["C1", COMMIT, "1234", SHA, "-"]), 1)
        complete.assert_not_called()
        self.assertEqual(write.call_args.args[0], 2)
        self.assertLessEqual(len(write.call_args.args[1]), 768)

    def test_resume_actual_completion_and_all_observed_tool_frames_fit_four_kib(self):
        repo=Path(c.__file__).resolve().parents[2]
        operator='tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py'
        source=(repo/operator).read_bytes()
        bootstrap=ast.literal_eval(next(node.value for node in ast.parse(source).body
            if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and
                target.id=='NATIVE_BOOTSTRAP' for target in node.targets)))
        packed=base64.b85encode(zlib.compress(bootstrap.encode('ascii'),9))
        carrier="import base64,zlib;exec(zlib.decompress(base64.b85decode('"+packed.decode('ascii')+"')))"
        self.assertLessEqual(len(packed),2048);self.assertLessEqual(len(bootstrap.encode('ascii')),2048)
        decoded=zlib.decompress(base64.b85decode(packed))
        self.assertEqual(decoded,bootstrap.encode('ascii'))
        self.assertEqual(hashlib.sha256(decoded).hexdigest(),hashlib.sha256(bootstrap.encode('ascii')).hexdigest())
        ast.parse(carrier,feature_version=(3,10))
        descriptor={'size_bytes':len(source),'sha256':hashlib.sha256(source).hexdigest(),
            'git_blob':hashlib.sha1(b'blob '+str(len(source)).encode()+b'\0'+source).hexdigest()}
        header=c.component.canonical_json_v1({'current':{operator:descriptor}}).decode('ascii')
        measurements=[]
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp).resolve()
            root=base/('n'*(98-len(str(base))-1))
            root.mkdir();self.assertEqual(len(str(root)),98)
            for name,count in (('C6',5),('C5',4)):
                output=root/'outputs'/name;output.mkdir(parents=True)
                record=c._invocation_record_v1(name,COMMIT,SHA,'c'*64,'d'*64,'e'*64)
                deadline=2**64-1
                completion=dict(c.write_record_v1(output/'outer.invocation.original.json',record,
                    cap=8192,absolute_deadline_ns=deadline,return_facts=True),
                    completion_deadline_ns=deadline,external_approval=False)
                args=[COMMIT,'32768',SHA,','.join('8192:'+('%064x'%n) for n in range(1,count+1))]
                outputs={1:b'',2:b''}
                def write(fd,raw):outputs[fd]+=raw;return len(raw)
                with patch.object(c,'parse_native_invocation_v1',return_value={'project_root':str(root),
                        'expected_packet_sha256':SHA,'expected_code_commit':COMMIT}), \
                     patch.object(c,'run_c_v1',return_value={}), \
                     patch.object(c,'complete_c_invocation_v1',return_value=completion), \
                     patch.object(c.os,'write',side_effect=write), \
                     patch.object(c.time,'monotonic_ns',side_effect=[deadline-1,deadline]):
                    self.assertEqual(c.native_main_v1([name]+args),1)
                self.assertTrue(outputs[1]);self.assertTrue(outputs[2])
                self.assertEqual(json.loads(outputs[1]),completion)
                self.assertEqual(json.loads(outputs[2])['cause'],'native_stdout_deadline')
                success={1:b'',2:b''}
                def write_success(fd,raw):success[fd]+=raw;return len(raw)
                with patch.object(c,'parse_native_invocation_v1',return_value={'project_root':str(root),
                        'expected_packet_sha256':SHA,'expected_code_commit':COMMIT}), \
                     patch.object(c,'run_c_v1',return_value={}), \
                     patch.object(c,'complete_c_invocation_v1',return_value=completion), \
                     patch.object(c.os,'write',side_effect=write_success), \
                     patch.object(c.time,'monotonic_ns',return_value=deadline-1):
                    self.assertEqual(c.native_main_v1([name]+args),0)
                self.assertEqual(success[1],outputs[1]);self.assertEqual(success[2],b'')
                command="$h='"+header+"'\n$h | & C:/Windows/System32/wsl.exe -d Ubuntu -u s-a-balashov --cd / --exec /usr/bin/python3 -I -S -B -c '"+carrier.replace("'","''")+"' '"+name+"' '"+"' '".join(args)+"'\nexit $LASTEXITCODE"
                arguments={'cmd':command,'workdir':'C:/','login':False,'yield_time_ms':30000}
                code="text(await tools.exec_command("+c.component.canonical_json_v1(arguments).decode('ascii')+"));"
                calls=[{'tool':'functions.exec','code':code}]
                frames=[]
                # This qualifies exactly two actual tool calls. Trustworthy
                # original-remaining-time admission is a separate physical gate.
                for elapsed in (30000,):
                    frames.append({'chunk_id':'a'*64,'wall_time_seconds':99999.999999,
                        'session_id':2147483647,'original_token_count':2147483647,'exit_code':None,'output':''})
                    remaining=150000-elapsed
                    self.assertGreaterEqual(remaining,5000)
                    poll={'session_id':2147483647,'yield_time_ms':min(120000,remaining)}
                    code="text(await tools.write_stdin("+c.component.canonical_json_v1(poll).decode('ascii')+"));"
                    calls.append({'tool':'functions.exec','code':code})
                frames.append({'chunk_id':'a'*64,'wall_time_seconds':99999.999999,'exit_code':1,
                    'original_token_count':2147483647,'session_id':None,
                    'output':(outputs[1]+outputs[2]).decode('ascii')})
                collection={'call':{'tool':'functions.exec','codes':[row['code'] for row in calls]},'frames':frames}
                expanded={'calls':[{'tool':collection['call']['tool'],'code':code}
                    for code in collection['call']['codes']],'frames':collection['frames']}
                self.assertEqual(c.component.canonical_json_v1(expanded),c.component.canonical_json_v1({'calls':calls,'frames':frames}))
                self.assertEqual(len(calls),2);self.assertEqual(len(frames),2)
                self.assertLess(len(outputs[1])+len(outputs[2]),10000) # tool defaults exceed both bounded producer channels
                raw=c.component.canonical_json_v1(collection)
                print(json.dumps({'resume_c_complete_frame_geometry':{'stage':name,
                    'call_bytes':sum(len(c.component.canonical_json_v1(row)) for row in calls),
                    'stdout_bytes':len(outputs[1]),'stderr_bytes':len(outputs[2]),
                    'frame_bytes':len(raw),'frame_count':len(frames),'physical_clock_admission_pending':True}}))
                measurements.append((name,len(raw)))
                for kind in ('success','failure','split','unicode_quotes','unknown','overbound'):
                    candidate=json.loads(c.component.canonical_json_v1(collection))
                    if kind=='success':candidate['frames'][-1].update(output=success[1].decode('ascii'),exit_code=0)
                    elif kind=='failure':candidate['frames'][-1]['output']=outputs[2].decode('ascii')
                    elif kind=='split':
                        candidate['frames'][0]['output']=outputs[1][:17].decode('ascii')
                        candidate['frames'][-1]['output']=(outputs[1][17:]+outputs[2]).decode('ascii')
                    elif kind=='unicode_quotes':candidate['frames'][-1]['output']+='"'+chr(0x1f4a5)
                    elif kind=='unknown':candidate['frames'][-1].update(exit_code=None,session_id=2147483647)
                    elif kind=='overbound':candidate['frames'][-1]['output']+='x'*4097
                    selected=c.component.canonical_json_v1(candidate)
                    combined=''.join(frame['output'] for frame in candidate['frames'])
                    status_success=(candidate['frames'][-1].get('exit_code')==0 and
                        candidate['frames'][-1].get('session_id') is None and combined==success[1].decode('ascii'))
                    self.assertEqual(status_success,kind=='success')
                    def preopen(value):
                        encoded=c.component.canonical_json_v1(value)
                        c._require(len(encoded)<=4096,'outer_complete_bound')
                        return (root/'selected.original.json').open('xb')
                    if len(selected)>4096:
                        with self.subTest(stage=name,kind=kind),patch.object(Path,'open') as opened:
                            with self.assertRaisesRegex(c.Gate2Refusal,'outer_complete_bound'):preopen(candidate)
                            opened.assert_not_called()
                    else:
                        self.assertEqual(json.loads(selected),candidate)
                        self.assertEqual(combined,
                            (outputs[1]+outputs[2]).decode('ascii') if kind=='split' else candidate['frames'][-1]['output'])
                for elapsed in (145001,149999,150000,150001):
                    with self.assertRaisesRegex(c.Gate2Refusal,'outer_deadline'):
                        c._require(150000-elapsed>=5000,'outer_deadline')
        self.assertTrue(all(size<=4096 for _,size in measurements),measurements)

    def test_resume_compressed_carrier_executes_the_same_verified_expired_bootstrap(self):
        from types import SimpleNamespace
        from tests.test_accepted_policy_fixture_compiler_gate2_resume_v1 import ResumeBoundaries,subject
        results=[]
        for compressed in (False,True):
            m=subject();repo=Path(__file__).resolve().parents[1]
            current={name:m.source_descriptor_v1((repo/name).read_bytes()) for name in m.SOURCE_PATHS}
            payload={'current':current,'global_deadline_ns':0,'phase_deadline_ns':0,'context':{'boot_id':'unused'}}
            packed=base64.b85encode(zlib.compress(m.NATIVE_BOOTSTRAP.encode('ascii'),9))
            program="import base64,zlib;exec(zlib.decompress(base64.b85decode('"+packed.decode('ascii')+"')))" if compressed else m.NATIVE_BOOTSTRAP
            saved=dict(sys.modules);writes=[]
            try:
                for module in ('tests','tests.fixtures')+tuple(name for name,_ in m.MODULES):sys.modules.pop(module,None)
                with ResumeBoundaries().native_files(m),patch.object(sys,'argv',['python','FINAL']), \
                     patch.object(sys,'stdin',SimpleNamespace(buffer=io.BytesIO(m.canonical(payload)+b'\n'))), \
                     patch.object(m.os,'write',side_effect=lambda fd,raw:writes.append((fd,raw)) or len(raw)), \
                     patch.object(m.subprocess,'Popen',side_effect=AssertionError('native process effect')):
                    with self.assertRaises(SystemExit) as stopped:exec(program,{'__name__':'controlled_carrier'})
                self.assertEqual(stopped.exception.code,1)
                self.assertEqual([fd for fd,raw in writes],[2])
                self.assertEqual(json.loads(writes[0][1])['cause'],'native_late_boot')
                results.append(writes)
            finally:
                for module in set(sys.modules)-set(saved):sys.modules.pop(module,None)
                sys.modules.update(saved)
        self.assertEqual(results[0],results[1])


class GuardPrefixTests(unittest.TestCase):
    def test_fixed_phase_files_are_distinct_and_default_names_unchanged(self):
        class Stream(io.BytesIO):
            def fileno(self): return 18
        class Process:
            pid = 88
            def __init__(self): self.stdout, self.stderr = Stream(b"12\n"), Stream(b"")
            def poll(self): return 0
            def wait(self, timeout=None): return 0
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch.object(c.subprocess, "Popen", side_effect=lambda *a, **kw: Process()), \
                    patch.object(c.os, "set_blocking"), \
                    patch.object(c.select, "select", side_effect=lambda readers, *_: (readers, [], [])), \
                    patch.object(c.time, "monotonic_ns", return_value=100):
                for phase in (None, "before", "after"):
                    result = c.capture_guard_v1("gpu", output_dir=root, absolute_deadline_ns=10_000_000_000,
                        record_original=False, _phase_prefix=phase)
                    self.assertTrue(result["closed"])
            self.assertEqual({p.name for p in root.iterdir()}, {
                "gpu.stdout.original", "gpu.stderr.original", "before.gpu.stdout.original",
                "before.gpu.stderr.original", "after.gpu.stdout.original", "after.gpu.stderr.original"})
            for prefix in ("", "before.", "after."):
                self.assertEqual((root / (prefix + "gpu.stdout.original")).read_bytes(), b"12\n")

    def test_arbitrary_prefix_refuses_before_files_or_spawn(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(c.subprocess, "Popen") as spawn:
            for value in ("../before", "before.", "arbitrary", 1):
                with self.subTest(value=value), self.assertRaises(c.Gate2Refusal):
                    c.capture_guard_v1("gpu", output_dir=Path(directory).resolve(),
                        absolute_deadline_ns=10_000_000_000, _phase_prefix=value)
            self.assertEqual(list(Path(directory).iterdir()), [])
        spawn.assert_not_called()


if __name__ == "__main__":
    unittest.main()
