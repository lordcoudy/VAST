"""Controlled Stage-D tests; no ELF, Docker or native command is executed."""
import copy
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch
from contextlib import nullcontext
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from tests.fixtures import accepted_policy_fixture_compiler_component_v1 as recipe
from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_v1 as stage


def proof(**changes):
    value = {"pid": 321, "uid": 1000, "euid": 1000, "gid": 1000,
             "egid": 1000, "pgid": 321, "sid": 321,
             "core": [1, 1], "fsize": [1048576, 1048576]}
    value.update(changes)
    return recipe.canonical_json_v1(value) + b"\n"


def facts():
    return {"schema_version": 1, "stage": "D", "controlled": False,
            "started_ns": 0, "absolute_deadline_ns": 10000000000,
            "finished_ns": 1000000000, "handlers_restored": True,
            "source_sha256": recipe.SOURCE_SHA256["c1"],
            "command_sha256": recipe.D_COMMAND_SHA256,
            "reply_sha256": recipe.D_REPLY_SHA256,
            "copy": {"size_bytes": 8192, "sha256": "a" * 64,
                     "source_sha256": "a" * 64, "mode": 0o700,
                     "persisted": True, "closed": True, "nlink": 1},
            "child": {"pid": 321, "identity_verified": True,
                      "proof": proof().decode("ascii"), "proof_eof": True,
                      "returncode": 0, "wait_status": 0, "reaped": True,
                      "stdout": recipe.D_REPLY.decode("ascii"), "stderr": "",
                      "stdout_eof": True, "stderr_eof": True,
                      "stdin_written_bytes": len(recipe.D_COMMAND),
                      "stdin_closed": True, "signals": [], "forced": False,
                      "unknown_closure": False, "late": False,
                      "capture_persisted": True, "capture_closed": True},
            "state": {"bytes": "ok\n", "size_bytes": 3, "nlink": 1,
                      "regular": True}, "boot_unchanged": True,
            "dmesg_unchanged": True, "crashes_unchanged": True,
            "identity_verified": True, "floors_preserved": True,
            "control_bytes": 32768, "aggregate_reserved_bytes": 2097152,
            "external_capture_allocation_bytes":16384,"later_index_allocation_bytes":4352,
            "within_deadline": True, "causes": []}


class ProofTests(unittest.TestCase):
    def test_exact_actual_child_proof(self):
        self.assertEqual(stage.validate_preexec_proof_v1(proof(), 321)["core"], [1, 1])

    def test_each_identity_and_limit_field_refuses_independently(self):
        cases = {"pid": 322, "uid": 0, "euid": 0, "gid": 0, "egid": 0,
                 "pgid": 322, "sid": 322, "core": [1, 1024],
                 "fsize": [1024, 1024]}
        for key, value in cases.items():
            with self.subTest(key=key), self.assertRaises(stage.StageDRefusal):
                stage.validate_preexec_proof_v1(proof(**{key: value}), 321)

    def test_noncanonical_duplicate_truncated_extra_and_oversized_proof(self):
        for raw in (proof()[:-1], proof() + b"x", b"{}\n", b"x" * 1025,
                    proof().replace(b'"uid":1000', b'"uid":true'),
                    proof().replace(b'{', b'{"uid":1000,', 1)):
            with self.subTest(raw=raw[:30]), self.assertRaises(stage.StageDRefusal):
                stage.validate_preexec_proof_v1(raw, 321)


class EvaluationTests(unittest.TestCase):
    def test_exact_result_passes_and_is_component_only(self):
        result = stage.evaluate_d_v1(facts())
        self.assertTrue(result["passed"])
        self.assertFalse(result["campaign_authority"])

    def test_every_required_top_level_predicate_refuses(self):
        mutations = {"source_sha256": "b" * 64, "command_sha256": "b" * 64,
                     "reply_sha256": "b" * 64, "boot_unchanged": False,
                     "dmesg_unchanged": False, "crashes_unchanged": False,
                     "identity_verified": False, "floors_preserved": False,
                     "within_deadline": False, "causes": ["capture_failed"],
                     "control_bytes": 524289, "aggregate_reserved_bytes": 2097153}
        for key, value in mutations.items():
            value_facts = facts()
            value_facts[key] = value
            with self.subTest(key=key):
                self.assertFalse(stage.evaluate_d_v1(value_facts)["passed"])

    def test_actual_status_closure_and_proof_are_separate(self):
        mutations = {"returncode": -15, "wait_status": 0x80, "reaped": False,
                     "proof_eof": False, "proof": proof(uid=0).decode("ascii"),
                     "identity_verified": False, "stdout_eof": False,
                     "stderr_eof": False, "stdin_closed": False,
                     "stdin_written_bytes": 0, "stdout": "wrong\n",
                     "stderr": "error", "forced": True,
                     "unknown_closure": True, "late": True,
                     "signals": ["TERM"], "capture_persisted": False,
                     "capture_closed": False}
        for key, value in mutations.items():
            value_facts = facts()
            value_facts["child"][key] = value
            with self.subTest(key=key):
                self.assertFalse(stage.evaluate_d_v1(value_facts)["passed"])

    def test_copy_and_state_are_exclusive_authenticated_and_bounded(self):
        for section, key, value in (("copy", "size_bytes", 524289),
                                    ("copy", "sha256", "b" * 64),
                                    ("copy", "mode", 0o755),
                                    ("copy", "persisted", False),
                                    ("copy", "closed", False),
                                    ("state", "bytes", "old\n"),
                                    ("state", "size_bytes", 4),
                                    ("state", "nlink", 2),
                                    ("state", "regular", False)):
            value_facts = facts()
            value_facts[section][key] = value
            with self.subTest(section=section, key=key):
                self.assertFalse(stage.evaluate_d_v1(value_facts)["passed"])

    def test_controlled_success_cannot_qualify_a_physical_run(self):
        value = facts()
        value["controlled"] = True
        result = stage.evaluate_d_v1(value)
        self.assertTrue(result["passed"])
        self.assertFalse(result["physical_acceptance"])

    def test_boolean_status_and_size_are_not_integers(self):
        value = facts()
        value["child"]["returncode"] = False
        self.assertFalse(stage.evaluate_d_v1(value)["passed"])

    def test_forged_within_deadline_and_handler_claims_refuse(self):
        for key, value in (('finished_ns', 10000000001),
                           ('absolute_deadline_ns', 20000000000),
                           ('handlers_restored', False)):
            result = facts()
            result[key] = value
            with self.subTest(key=key):
                self.assertFalse(stage.evaluate_d_v1(result)['passed'])
        value = facts()
        value["copy"]["size_bytes"] = True
        self.assertFalse(stage.evaluate_d_v1(value)["passed"])

    def test_oversized_reported_proof_is_refused_before_ascii_encoding_and_parse(self):
        value = facts()
        value['child']['proof'] = 'x' * (stage.PROOF_LIMIT + 1)
        with patch.object(stage, 'validate_preexec_proof_v1', wraps=stage.validate_preexec_proof_v1) as validate:
            self.assertFalse(stage.evaluate_d_v1(value)['passed'])
        validate.assert_not_called()

    def test_execution_comparison_alone_never_qualifies_physical_finalization(self):
        value = facts()
        value['receipt_persisted'] = False
        result = stage.evaluate_d_v1(value)
        self.assertTrue(result['passed'])
        self.assertFalse(result['physical_acceptance'])
        value.update(receipt_persisted=True,
            aggregate_accounted_bytes=1200000,
            control_bytes=37120,
            control_allocation_after_receipt={'dmesg':0,'crashes':0,'other':16384,'total':16384,'files':16},
            receipt_descriptor={'persisted': True, 'closed': True, 'extent_unknown': False,
                'size_bytes': 1000, 'sha256': 'c' * 64},
            final_measurement_after_receipt=FakeObserver().measure(),
            ledger_after_receipt={'remaining_before': 10000000, 'charge_bytes': 100000,
                                  'remaining_after': 9900000})
        self.assertTrue(stage.evaluate_d_v1(value)['physical_acceptance'])
        for usage in (None,[],{}, {'dmesg':0,'crashes':0,'other':-1,'total':16384,'files':16},
                {'dmesg':0,'crashes':0,'other':16384,'total':16385,'files':16},
                {'dmesg':0,'crashes':0,'other':98304,'total':98304,'files':16},
                {'dmesg':393217,'crashes':0,'other':0,'total':393217,'files':16},
                {'dmesg':0,'crashes':32769,'other':0,'total':32769,'files':16},
                {'dmesg':0,'crashes':0,'other':16384,'total':16384,'files':True}):
            with self.subTest(usage=usage):
                bad=copy.deepcopy(value);bad['control_allocation_after_receipt']=usage
                evaluated=stage.evaluate_d_v1(bad)
                self.assertFalse(evaluated['finalization_complete']);self.assertFalse(evaluated['physical_acceptance'])
        absent=copy.deepcopy(value);absent.pop('control_allocation_after_receipt')
        self.assertFalse(stage.evaluate_d_v1(absent)['finalization_complete'])
        self.assertFalse(stage.evaluate_d_v1(absent)['physical_acceptance'])
        for section, key, changed in (('receipt_descriptor', 'closed', False),
                                      ('ledger_after_receipt', 'remaining_after', 9900001),
                                      ('final_measurement_after_receipt', 'c_free_bytes', 0)):
            mutated = copy.deepcopy(value)
            mutated[section][key] = changed
            with self.subTest(section=section):
                self.assertFalse(stage.evaluate_d_v1(mutated)['physical_acceptance'])


class PhaseTests(unittest.TestCase):
    def test_four_phases_share_one_absolute_deadline(self):
        self.assertEqual(stage.phase_limits_v1(10_000_000_000),
                         {"work": 7_000_000_000, "term": 8_000_000_000,
                          "kill": 9_000_000_000, "final": 10_000_000_000})

    def test_fixed_environment_replaces_loader_hooks(self):
        env = stage.child_environment_v1("/fresh/D")
        self.assertEqual(env, {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C",
                               "HOME": "/fresh/D", "TMPDIR": "/fresh/D",
                               "TMP": "/fresh/D", "TEMP": "/fresh/D"})


def elf():
    raw = bytearray(4096)
    raw[:7] = b'\x7fELF\x02\x01\x01'
    struct.pack_into('<HHI', raw, 16, 3, 62, 1)
    struct.pack_into('<Q', raw, 32, 64)
    struct.pack_into('<HHH', raw, 52, 64, 56, 1)
    struct.pack_into('<I', raw, 64, 3)
    struct.pack_into('<Q', raw, 72, 256)
    interpreter = b'/lib64/ld-linux-x86-64.so.2\0'
    struct.pack_into('<Q', raw, 96, len(interpreter))
    raw[256:256 + len(interpreter)] = interpreter
    return bytes(raw)


class OriginalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.source = self.root / 'outputs/C1/engine.compiler-originals/engine.unaccepted'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(elf())
        self.destination = self.root / 'copy'
        self.binding = {'elf_path': str(self.source), 'elf_size_bytes': len(elf()),
                        'elf_sha256': hashlib.sha256(elf()).hexdigest(),
                        'source_sha256': recipe.SOURCE_SHA256['c1']}

    def copy_elf(self):
        return stage._copy_c1_elf_v1(self.root, self.binding, self.destination,
                                    clock=lambda: 1, deadline=100)

    def test_exact_c1_copy_is_exclusive_hash_verified_and_0700(self):
        result = self.copy_elf()
        self.assertEqual(self.destination.read_bytes(), elf())
        self.assertEqual(self.destination.stat().st_mode & 0o777, 0o700)
        self.assertEqual(result['interpreter'], '/lib64/ld-linux-x86-64.so.2')
        self.assertTrue(result['persisted'] and result['closed'])
        self.assertEqual(self.source.read_bytes(), elf())

    def test_size_hash_source_and_abi_drift_refuse_before_copy(self):
        for key, value in (('elf_size_bytes', len(elf()) + 1),
                           ('elf_sha256', 'b' * 64),
                           ('source_sha256', recipe.SOURCE_SHA256['c2']),
                           ('elf_path', str(self.root / 'foreign'))):
            binding = copy.deepcopy(self.binding)
            binding[key] = value
            with self.subTest(key=key), self.assertRaises(stage.StageDRefusal):
                stage._copy_c1_elf_v1(self.root, binding, self.destination,
                                      clock=lambda: 1, deadline=100)
            self.assertFalse(self.destination.exists())
        wrong = bytearray(elf())
        wrong[18:20] = (3).to_bytes(2, 'little')
        self.source.write_bytes(wrong)
        self.binding['elf_sha256'] = hashlib.sha256(wrong).hexdigest()
        with self.assertRaises(stage.StageDRefusal):
            self.copy_elf()
        self.assertFalse(self.destination.exists())

    def test_oversized_source_and_alias_refuse_without_overwriting(self):
        self.source.write_bytes(b'x' * (stage.ELF_LIMIT + 1))
        with self.assertRaises(stage.StageDRefusal):
            self.copy_elf()
        self.assertFalse(self.destination.exists())
        self.source.write_bytes(elf())
        self.destination.write_bytes(b'original')
        with self.assertRaises(stage.StageDRefusal):
            self.copy_elf()
        self.assertEqual(self.destination.read_bytes(), b'original')

    def test_original_write_exception_retains_unknown_extent(self):
        path = self.root / 'failed.original'
        with patch.object(stage.os, 'write', side_effect=OSError('synthetic first-write fault')):
            with self.assertRaises(stage.StageDRefusal) as caught:
                stage._write_original_v1(path, b'abcd', 4, clock=lambda: 1, deadline=100)
        self.assertTrue(caught.exception.facts['extent_unknown'])
        self.assertFalse(caught.exception.facts['persisted'])
        self.assertTrue(caught.exception.facts['closed'])
        self.assertIsNone(caught.exception.facts['size_bytes'])
        self.assertTrue(path.exists())

    def test_crash_listing_is_complete_and_prebounded(self):
        (self.root / 'unrelated').write_bytes(b'x')
        (self.root / 'wsl-crash-test.dmp').write_bytes(b'old')
        value = json.loads(stage._crash_listing_v1(self.root))
        self.assertEqual(len(value), 1)
        self.assertEqual(value[0][:2], ['wsl-crash-test.dmp', 3])
        for index in range(64):
            (self.root / ('wsl-crash-%02d.dmp' % index)).write_bytes(b'')
        with self.assertRaises(stage.StageDRefusal):
            stage._crash_listing_v1(self.root)

    def test_control_rounding_and_symlinks_are_charged(self):
        controls = self.root / 'controls'
        controls.mkdir()
        (controls / 'small').write_bytes(b'x')
        usage = stage._controls_usage_v1(controls)
        self.assertGreaterEqual(usage['other'], 8192)
        (controls / 'alias').symlink_to(controls / 'small')
        with self.assertRaises(stage.StageDRefusal):
            stage._controls_usage_v1(controls)


class FakeObserver:
    def measure(self):
        return {'c_free_bytes': 70 * 1024 ** 3,
                'project_free_bytes': 100 * 1024 ** 3,
                'ext4_used_bytes': 300 * 1024 ** 3}

    def identity(self, directory, cids, deadline):
        return {'engine_id': 'controlled', 'containers': len(cids)}

    def snapshot(self, directory, deadline, *, phase):
        return {'metrics': {'c_free_bytes': 70 * 1024 ** 3,
                            'project_free_bytes': 100 * 1024 ** 3,
                            'ext4_used_bytes': 300 * 1024 ** 3},
                'boot_id': 'controlled-boot', 'dmesg_sha256': 'a' * 64,
                'crashes_sha256': 'b' * 64, 'captures': {}, 'journal': 'controlled'}


class OuterTests(unittest.TestCase):
    def setUp(self):
        OriginalTests.setUp(self)
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
        self.c = c
        self.binding.update(receipt_sha256='d' * 64,
                            all_cids=['%064x' % n for n in range(1, 10)],
                            remaining_seal_bytes=400 * 1024 ** 2,
                            last_after_measurement=FakeObserver().measure(), last_tail_credit_bytes=0)
        self.calls = []

    def child(self, **kwargs):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_d_child_v1 as child_module
        from tests.test_accepted_policy_fixture_compiler_gate2_d_child_v1 import World
        self.calls.append(kwargs)
        (kwargs['directory'] / 'engine.state').write_bytes(b'ok\n')
        world = World()
        world.now = kwargs['started_ns']
        result = child_module.run_child_v1(**kwargs, _effects=world.effects())
        for name in ('stdout', 'stderr', 'preexec'):
            path = kwargs['output_dir'] / ('d.' + name + '.original')
            raw = world.files[path.name].saved
            with path.open('xb') as file:
                file.write(raw)
        return result

    def run_d(self, **kwargs):
        with patch.multiple(stage.os, getuid=lambda:1000, geteuid=lambda:1000,
                            getgid=lambda:1000, getegid=lambda:1000), \
             patch.object(self.c, 'validated_c1_binding_v1', side_effect=kwargs.get('binding'),
                          return_value=self.binding):
            return stage.run_d_v1(project_root=self.root,
                                  packet_descriptor={'controlled': True},
                                  expected_packet_sha256='c' * 64,
                                  expected_code_commit='e' * 40,
                                  completion_authorities=kwargs.get('completion_authorities', {}),
                                  _observer=kwargs.get('observer', FakeObserver()),
                                  _child_runner=kwargs.get('child_runner', self.child),
                                  _clock=kwargs.get('clock', lambda: 1000000000))

    def test_controlled_complete_outer_flow_and_self_persistence_boundary(self):
        result = self.run_d()
        self.assertTrue(result['evaluation']['passed'])
        self.assertFalse(result['evaluation']['physical_acceptance'])
        self.assertEqual(len(self.calls), 1)
        self.assertTrue(result['receipt_persisted'])
        inner = json.loads(Path(result['receipt_descriptor']['path']).read_bytes())
        self.assertFalse(inner['receipt_persisted'])
        self.assertEqual(result['ledger_after_receipt']['remaining_before'], 400 * 1024 ** 2)
        self.assertEqual(self.calls[0]['absolute_deadline_ns'], 11000000000)
        self.assertEqual(self.calls[0]['started_ns'], 1000000000)

    def test_controlled_outer_helper_is_independent_of_hosted_runner_actor(self):
        with patch.multiple(stage.os,getuid=lambda:1001,geteuid=lambda:1001,
                            getgid=lambda:1001,getegid=lambda:1001):
            result=self.run_d()
            self.assertEqual((stage.os.getuid(),stage.os.geteuid(),stage.os.getgid(),stage.os.getegid()),
                             (1001,1001,1001,1001))
        self.assertTrue(result['evaluation']['passed'])
        self.assertTrue(result['controlled'])
        self.assertFalse(result['evaluation']['physical_acceptance'])

    def test_native_host_identity_rejects_each_wrong_actor_before_binding_or_allocation(self):
        for wrong in ('getuid','geteuid','getgid','getegid'):
            actors={name:(lambda:1000) for name in ('getuid','geteuid','getgid','getegid')}
            actors[wrong]=lambda:1001
            observer=FakeObserver()
            with self.subTest(actor=wrong),patch.multiple(stage.os,**actors), \
                 patch.object(self.c,'validated_c1_binding_v1') as binding, \
                 patch.object(observer,'measure') as measure, \
                 patch.object(stage,'_copy_c1_elf_v1') as copied,patch.object(self,'child') as child:
                with self.assertRaises(stage.StageDRefusal) as caught:
                    stage.run_d_v1(project_root=self.root,packet_descriptor={'controlled':True},
                        expected_packet_sha256='c'*64,expected_code_commit='e'*40,
                        completion_authorities={},_observer=observer,_child_runner=child,
                        _clock=lambda:1000000000)
                self.assertEqual(caught.exception.cause,'d_host_identity')
                binding.assert_not_called();measure.assert_not_called()
                copied.assert_not_called();child.assert_not_called()
                self.assertFalse((self.root/'outputs/D').exists())

    def test_external_c_completion_authorities_are_frozen_for_both_binding_checks(self):
        authorities = {name: {'path': str(self.root / 'outputs' / name / 'outer.invocation.original.json'),
                             'size_bytes': 1024, 'sha256': '%064x' % index}
                       for index, name in enumerate(self.c.STAGES, 1)}
        frozen = copy.deepcopy(authorities)
        observed = []
        def binding(**kwargs):
            observed.append(copy.deepcopy(kwargs['completion_authorities']))
            kwargs['completion_authorities']['C1']['sha256'] = '0' * 64
            return copy.deepcopy(self.binding)
        def child(**kwargs):
            authorities['C1']['sha256'] = 'f' * 64
            authorities['unreviewed'] = {'path': 'unreviewed'}
            return self.child(**kwargs)
        result = self.run_d(completion_authorities=authorities, binding=binding, child_runner=child)
        self.assertEqual(observed, [frozen, frozen])
        expected = hashlib.sha256(recipe.canonical_json_v1(frozen)).hexdigest()
        self.assertEqual(result['c_completion_authorities_sha256'], expected)
        original = json.loads(Path(result['receipt_descriptor']['path']).read_bytes())
        self.assertEqual(original['c_completion_authorities_sha256'], expected)
        self.assertNotIn('completion_authorities', original)

    def test_missing_external_c_completion_refusal_cannot_create_d_or_launch_child(self):
        def missing(**kwargs):
            self.assertEqual(kwargs['completion_authorities'], {})
            raise self.c.Gate2Refusal('controlled_external_completion_missing')
        with self.assertRaises(self.c.Gate2Refusal):
            self.run_d(binding=missing)
        self.assertFalse((self.root / 'outputs/D').exists())
        self.assertEqual(self.calls, [])

    def test_completion_authority_input_is_prebounded_before_binding_or_d_allocation(self):
        descriptor = {'path': '/fixed', 'size_bytes': 1024, 'sha256': 'a' * 64}
        invalid = [None, [], {'unexpected': descriptor}, {'C1': {**descriptor, 'extra': True}},
                   {'C1': {**descriptor, 'path': 'x' * 4097}}, {'C1': {**descriptor, 'size_bytes': True}},
                   {'C1': {**descriptor, 'size_bytes': 8193}}, {'C1': {**descriptor, 'sha256': 'A' * 64}}]
        for value in invalid:
            with self.subTest(value=str(value)[:100]):
                with self.assertRaises(stage.StageDRefusal):
                    self.run_d(completion_authorities=value)
                self.assertFalse((self.root / 'outputs/D').exists())
                self.assertEqual(self.calls, [])

    def test_insufficient_global_reserve_refuses_before_output_creation(self):
        self.binding['remaining_seal_bytes'] = stage.AGGREGATE_LIMIT - 1
        with self.assertRaises(stage.StageDRefusal):
            self.run_d()
        self.assertFalse((self.root / 'outputs/D').exists())
        self.assertEqual(self.calls, [])

    def test_repeat_preserves_original_and_never_executes_again(self):
        self.run_d()
        original = (self.root / 'outputs/D/engine').read_bytes()
        with self.assertRaises(stage.StageDRefusal):
            self.run_d()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual((self.root / 'outputs/D/engine').read_bytes(), original)

    def test_oversized_precapture_refuses_before_child(self):
        with patch.object(stage, '_controls_usage_v1', side_effect=stage.StageDRefusal('synthetic cap')):
            with self.assertRaises(stage.StageDRefusal):
                self.run_d()
        self.assertEqual(self.calls, [])

    def test_post_kernel_drift_is_failure_with_retained_receipt(self):
        observer = FakeObserver()
        original = observer.snapshot
        count = [0]
        def snapshot(*args, **kwargs):
            row = original(*args, **kwargs)
            count[0] += 1
            if count[0] == 2:
                row['dmesg_sha256'] = 'f' * 64
            return row
        observer.snapshot = snapshot
        with self.assertRaises(stage.StageDRefusal) as caught:
            self.run_d(observer=observer)
        self.assertFalse(caught.exception.facts['evaluation']['passed'])
        self.assertTrue(caught.exception.facts['receipt_persisted'])
        self.assertTrue(Path(caught.exception.facts['receipt_descriptor']['path']).exists())

    def test_receipt_fsync_and_close_failures_keep_child_and_both_causes(self):
        original_sync, original_close = stage.os.fsync, stage.os.close
        failed_fd = [None]
        def sync(fd):
            if os.readlink('/proc/self/fd/%d' % fd).endswith('/d.result.original.json'):
                failed_fd[0] = fd
                raise OSError('synthetic receipt fsync failure')
            return original_sync(fd)
        def close(fd):
            original_close(fd)
            if fd == failed_fd[0]:
                raise OSError('synthetic receipt close failure')
        with patch.object(stage.os, 'fsync', side_effect=sync), patch.object(stage.os, 'close', side_effect=close):
            with self.assertRaises(stage.StageDRefusal) as caught:
                self.run_d()
        result = caught.exception.facts
        self.assertEqual(result['child']['returncode'], 0)
        self.assertTrue(result['child']['reaped'])
        self.assertEqual(result['child']['proof'], proof().decode('ascii'))
        self.assertIn('d_original_fsync_OSError', result['causes'])
        self.assertIn('d_original_close_OSError', result['causes'])
        self.assertFalse(result['receipt_persisted'])
        self.assertFalse(result['failed_operation']['persisted'])
        self.assertTrue((self.root / 'outputs/D/controls/d.result.original.json').exists())

    def test_postrun_packet_code_and_elf_drift_keep_original_child_outcome(self):
        def changed_binding(**kwargs):
            if not self.calls:
                return copy.deepcopy(self.binding)
            value = copy.deepcopy(self.binding)
            value['receipt_sha256'] = 'f' * 64
            return value
        with self.assertRaises(stage.StageDRefusal) as caught:
            self.run_d(binding=changed_binding)
        self.assertIn('d_packet_post_drift', caught.exception.facts['causes'])
        self.assertEqual(caught.exception.facts['child']['returncode'], 0)
        self.assertTrue(caught.exception.facts['receipt_persisted'])

    def test_postrun_reviewed_code_validation_failure_preserves_receipt(self):
        def changed_binding(**kwargs):
            if self.calls:
                raise self.c.Gate2Refusal('packet_file_binding')
            return copy.deepcopy(self.binding)
        with self.assertRaises(stage.StageDRefusal) as caught:
            self.run_d(binding=changed_binding)
        self.assertIn('packet_file_binding', caught.exception.facts['causes'])
        self.assertEqual(caught.exception.facts['child']['wait_status'], 0)
        self.assertTrue(caught.exception.facts['receipt_persisted'])

    def test_postrun_copied_elf_drift_refuses(self):
        def changed_child(**kwargs):
            value = self.child(**kwargs)
            with kwargs['executable_path'].open('ab') as file:
                file.write(b'changed')
            return value
        with self.assertRaises(stage.StageDRefusal) as caught:
            self.run_d(child_runner=changed_child)
        self.assertIn('d_copy_post_drift', caught.exception.facts['causes'])
        self.assertEqual(caught.exception.facts['child']['returncode'], 0)

    def test_child_raw_original_tamper_refuses_independently_of_reported_bytes(self):
        def changed_child(**kwargs):
            value = self.child(**kwargs)
            (kwargs['output_dir'] / 'd.stdout.original').write_bytes(b'forged')
            return value
        with self.assertRaises(stage.StageDRefusal) as caught:
            self.run_d(child_runner=changed_child)
        self.assertIn('d_child_capture_binding', caught.exception.facts['causes'])
        self.assertEqual(caught.exception.facts['child']['stdout'], recipe.D_REPLY.decode('ascii'))

    def test_postreceipt_meter_growth_is_charged_and_can_refuse(self):
        observer, count = FakeObserver(), [0]
        original = observer.measure
        def measure():
            value = original()
            count[0] += 1
            if count[0] == 2:
                value['ext4_used_bytes'] += self.binding['remaining_seal_bytes'] + 1
            return value
        observer.measure = measure
        with self.assertRaises(stage.StageDRefusal) as caught:
            self.run_d(observer=observer)
        result = caught.exception.facts
        self.assertIn('d_global_allocation', result['causes'])
        self.assertTrue(result['receipt_persisted'])
        self.assertLess(result['ledger_after_receipt']['remaining_after'], 0)
        self.assertEqual(result['child']['returncode'], 0)

    def test_idle_c6_gap_is_not_charged_but_actual_d_interval_growth_is(self):
        observer, count = FakeObserver(), [0]
        original = observer.measure
        self.binding['last_after_measurement'] = original()
        self.binding['last_after_measurement']['c_free_bytes'] += 3 * 1024 ** 3
        self.binding['last_after_measurement']['ext4_used_bytes'] -= 3 * 1024 ** 3
        self.binding['last_tail_credit_bytes'] = 1048576
        def measure():
            value = original()
            count[0] += 1
            if count[0] == 2:
                value['c_free_bytes'] -= 1048576
                value['ext4_used_bytes'] += 524288
            return value
        observer.measure = measure
        result = self.run_d(observer=observer)
        self.assertTrue(result['evaluation']['passed'])
        self.assertEqual(result['ledger_after_receipt'], {
            'remaining_before': 400 * 1024 ** 2, 'charge_bytes': 1048576 + 20736,
            'remaining_after': 400 * 1024 ** 2 - 1048576 - 20736})
        self.assertEqual(result['gap_charge_bytes'], 0)

    def test_clock_regression_after_child_preserves_status_and_cannot_accept(self):
        def clock():
            return 999999999 if self.calls else 1000000000
        with self.assertRaises(stage.StageDRefusal) as caught:
            self.run_d(clock=clock)
        self.assertEqual(caught.exception.facts['child']['returncode'], 0)
        self.assertIn('d_clock_regressed', caught.exception.facts['causes'])
        self.assertFalse(caught.exception.facts['evaluation']['passed'])

    def test_final_charge_keeps_the_reserved_later_git_index_form(self):
        result = self.run_d()
        directory = self.root / 'outputs/D'
        physical = result['control_allocation_after_receipt']['total'] + 4096
        physical += stage._allocated_v1(directory / 'engine') + stage._allocated_v1(directory / 'engine.state')
        self.assertGreaterEqual(result['ledger_after_receipt']['charge_bytes'], physical + 4352 + 16384)
        self.assertEqual(result['external_capture_allocation_bytes'],16384)
        self.assertEqual(result['later_index_allocation_bytes'],4352)
        self.assertEqual(result['control_bytes'],result['control_allocation_after_receipt']['total']+4352+16384)

    def test_host_noise_cannot_swallow_future_capture_or_index_liabilities(self):
        observer,count=FakeObserver(),[0]
        original=observer.measure
        def measure():
            value=original(); count[0]+=1
            if count[0]==2: value['ext4_used_bytes']+=1048576
            return value
        observer.measure=measure
        result=self.run_d(observer=observer)
        self.assertEqual(result['ledger_after_receipt']['charge_bytes'],1048576+16384+4352)

    def test_full_aggregate_reserve_denial_does_not_start_receipt_copy_or_child(self):
        with patch.object(stage,'_reserve_aggregate_v1',side_effect=stage.StageDRefusal('d_aggregate_reserve',{'aggregate_bytes':2097153})), \
             patch.object(stage,'_copy_c1_elf_v1') as copied:
            with self.assertRaises(stage.StageDRefusal) as caught: self.run_d()
        copied.assert_not_called();self.assertEqual(self.calls,[])
        self.assertIn('d_aggregate_reserve',caught.exception.facts['causes'])
        self.assertEqual(caught.exception.facts['failed_operation'],{'aggregate_bytes':2097153})
        self.assertFalse((self.root/'outputs/D/controls/d.result.original.json').exists())

    def test_post_child_floor_loss_preserves_closure_without_fresh_receipt(self):
        observer=FakeObserver();original=observer.snapshot
        def snapshot(*args,**kwargs):
            value=original(*args,**kwargs)
            if kwargs['phase']=='after': value['metrics']['c_free_bytes']=0
            return value
        observer.snapshot=snapshot
        with self.assertRaises(stage.StageDRefusal) as caught:self.run_d(observer=observer)
        value=caught.exception.facts
        self.assertEqual(value['child']['returncode'],0);self.assertTrue(value['child']['reaped'])
        self.assertTrue(value['receipt_skipped_after_budget_denial'])
        self.assertFalse((self.root/'outputs/D/controls/d.result.original.json').exists())

    def test_post_child_native_floor_read_error_preserves_closure_without_fresh_receipt(self):
        observer=FakeObserver();original=observer.snapshot
        native=stage._NativeObserverV1(self.root,lambda:1000000000)
        def snapshot(*args,**kwargs):
            return native.snapshot(*args,**kwargs) if kwargs['phase']=='after' else original(*args,**kwargs)
        observer.snapshot=snapshot
        with patch.object(stage.os,'statvfs',side_effect=OSError('controlled unavailable floor')):
            with self.assertRaises(stage.StageDRefusal) as caught:self.run_d(observer=observer)
        value=caught.exception.facts
        self.assertEqual(caught.exception.cause,'d_floor_measurement_unknown')
        self.assertEqual(value['child']['returncode'],0);self.assertTrue(value['child']['reaped'])
        self.assertTrue(value['receipt_skipped_after_budget_denial'])
        self.assertTrue((self.root/'outputs/D/controls/d.stdout.original').exists())
        self.assertFalse((self.root/'outputs/D/controls/d.result.original.json').exists())

    def test_transient_allocation_stat_error_cannot_start_fresh_receipt(self):
        observer=FakeObserver();original=observer.identity
        prefix=self.root/'outputs/D/controls/before.prefix.original'
        def identity(*args,**kwargs):
            prefix.write_bytes(b'retained known prefix')
            return original(*args,**kwargs)
        observer.identity=identity
        actual_lstat=Path.lstat;failed=[False]
        def lstat(path,*args,**kwargs):
            if path==prefix and not failed[0]:
                failed[0]=True
                raise OSError('controlled unavailable allocation')
            return actual_lstat(path,*args,**kwargs)
        with patch.object(Path,'lstat',lstat),patch.object(stage,'_copy_c1_elf_v1') as copied:
            with self.assertRaises(stage.StageDRefusal) as caught:self.run_d(observer=observer)
        copied.assert_not_called();self.assertEqual(self.calls,[])
        self.assertEqual(caught.exception.cause,'d_control_allocation_unknown')
        self.assertTrue(caught.exception.facts['receipt_skipped_after_budget_denial'])
        self.assertEqual(prefix.read_bytes(),b'retained known prefix')
        self.assertFalse((self.root/'outputs/D/controls/d.result.original.json').exists())

    def test_transient_allocation_walk_error_cannot_be_silently_omitted(self):
        actual_scandir=stage.os.scandir;failed=[False]
        controls=self.root/'outputs/D/controls'
        def scandir(path):
            if Path(path)==controls and not failed[0]:
                failed[0]=True
                raise OSError('controlled unavailable inventory')
            return actual_scandir(path)
        with patch.object(stage.os,'scandir',side_effect=scandir),patch.object(stage,'_copy_c1_elf_v1') as copied:
            with self.assertRaises(stage.StageDRefusal) as caught:self.run_d()
        copied.assert_not_called();self.assertEqual(self.calls,[])
        self.assertEqual(caught.exception.cause,'d_control_allocation_unknown')
        self.assertTrue(caught.exception.facts['receipt_skipped_after_budget_denial'])
        self.assertFalse((controls/'d.result.original.json').exists())

    def test_post_child_external_ledger_denial_is_sticky_without_receipt(self):
        def binding(**kwargs):
            if self.calls: raise self.c.Gate2Refusal('ledger_unknown',{'known_ledger':False})
            return copy.deepcopy(self.binding)
        with self.assertRaises(stage.StageDRefusal) as caught:self.run_d(binding=binding)
        self.assertIn('ledger_unknown',caught.exception.facts['causes'])
        self.assertEqual(caught.exception.facts['child']['returncode'],0)
        self.assertFalse((self.root/'outputs/D/controls/d.result.original.json').exists())

    def native_shaped_controls(self, *, gpu_empty, refusal):
        from tests.test_accepted_policy_fixture_compiler_transport_v1 import FakeSocket, reply
        info = json.loads((ROOT / 'openspec/changes/fix-accepted-policy-preprocessing/evidence/'
                           'compiler-component-01/observations-01/engine-info.v1_55.original.json').read_bytes())
        info.update(Containers=9, ContainersRunning=0, ContainersPaused=0)
        transport = stage._DInfoClientV1
        class ControlledInfoClient(transport):
            def __init__(self, output, deadline):
                super().__init__(output, deadline,
                    socket_factory=lambda: FakeSocket(reply(recipe.canonical_json_v1(info))),
                    clock=lambda: 1000000000)
        captures = []
        class Pipe(io.BytesIO):
            def fileno(self): return 123
        class Process:
            pid=777
            def __init__(self,raw): self.stdout,self.stderr=Pipe(raw),Pipe()
            def poll(self): return 0
            def wait(self,timeout=None): return 0
        def native(argv,**kwargs):
            kind = 'dmesg' if argv[0]=='/usr/bin/dmesg' else 'journal' if argv[0]=='/usr/bin/journalctl' else 'gpu'
            captures.append(kind)
            self.assertEqual(kwargs['env'],{'PATH':'/usr/bin:/bin','LC_ALL':'C','LANG':'C'})
            limit={'dmesg':stage.DMESG_LIMIT,'journal':512,'gpu':4096}[kind]
            raw=b'' if kind=='gpu' and gpu_empty else (b' ' if kind=='gpu' else b'x')*limit
            return Process(raw)
        crashes = recipe.canonical_json_v1([['wsl-crash-%02d-' % n + 'x' * 490, 3, 1] for n in range(31)])
        self.assertLessEqual(len(crashes), stage.CRASH_LIMIT)
        observer = stage._NativeObserverV1(self.root, lambda: 1000000000)
        with patch.object(stage, '_DInfoClientV1', ControlledInfoClient), \
             patch.object(stage.compiler._DockerClientV1, '_observe_endpoint', return_value=tuple((1,n,0,0,0o140660,17) for n in (2,3,4))), \
             patch.object(stage, '_floor_metrics_v1', side_effect=lambda root: FakeObserver().measure()), \
             patch.object(stage.compiler, '_compiler_proc_read_v1', return_value=b'00000000-0000-0000-0000-000000000001\n'), \
             patch.object(self.c.subprocess,'Popen',side_effect=native), \
             patch.object(self.c.os,'set_blocking'), \
             patch.object(self.c.select,'select',side_effect=lambda reads,*args:(reads,[],[])), \
             patch.object(self.c.time,'monotonic_ns',return_value=1000000000), \
             patch.object(stage, '_crash_listing_v1', return_value=crashes):
            if refusal:
                with self.assertRaises(stage.StageDRefusal) as caught:
                    self.run_d(observer=observer)
                self.assertIn('d_control_reserve',caught.exception.facts['causes'])
                self.assertEqual(self.calls,[])
                self.assertFalse((self.root/'outputs/D/engine').exists())
                self.assertTrue((self.root/'outputs/D/controls/before.gpu.stdout.original').exists())
                self.assertFalse((self.root/'outputs/D/controls/d.result.original.json').exists())
                return caught.exception.facts
            result = self.run_d(observer=observer)
        self.assertTrue(result['evaluation']['passed'])
        usage = result['control_allocation_after_receipt']
        self.assertLessEqual(usage['total'], stage.CONTROL_LIMIT)
        self.assertLessEqual(usage['other'] + stage.LATER_INDEX_ALLOCATION + stage.EXTERNAL_CAPTURE_ALLOCATION, stage.OTHER_CONTROL_LIMIT)
        self.assertEqual(usage['dmesg'], 2 * stage.DMESG_LIMIT)
        self.assertEqual(usage['crashes'], 2 * stage.CRASH_LIMIT)
        self.assertEqual(captures, ['dmesg', 'journal', 'gpu'] * 2)
        self.assertEqual(usage['files'], 20)
        self.assertFalse(list((self.root / 'outputs/D/controls').rglob('*.capture.original.json')))
        inner = json.loads(Path(result['receipt_descriptor']['path']).read_bytes())
        # Exercise the finalization predicate without the controlled marker
        # masking an otherwise native-shaped pre-receipt evidence record.
        inner['controlled'] = False
        self.assertFalse(stage.evaluate_d_v1(inner)['physical_acceptance'])
        return result

    def test_old_maximum_whitespace_gpu_case_refuses_before_copy_or_execution(self):
        # The earlier PASS is preserved in the historical measurement logs.
        # Its full 4KiB whitespace prefix consumes the new outer-proof margin.
        self.native_shaped_controls(gpu_empty=False,refusal=True)

    def test_native_path_maximum_controls_with_actual_empty_gpu_fit_private_20k_receipt(self):
        previous=self.root
        target='/home/s-a-balashov/work/vast-fixture-compiler-gate2-'+'a'*40+'-01'
        padded=previous/('native-root-'+'x'*max(1,len(target)-len(str(previous))-1-len('native-root-')))
        padded.mkdir()
        self.root=padded
        source=self.root/'outputs/C1/engine.compiler-originals/engine.unaccepted'
        source.parent.mkdir(parents=True);source.write_bytes(elf())
        self.binding['elf_path']=str(source)
        self.assertGreaterEqual(len(str(self.root)),len(target))
        result=self.native_shaped_controls(gpu_empty=True,refusal=False)
        raw=Path(result['receipt_descriptor']['path']).read_bytes()
        self.assertLessEqual(len(raw),20480)
        self.assertLessEqual(stage.compiler._json_bound(json.loads(raw)),20480)
        self.assertEqual(list((self.root/'outputs/D/controls').glob('*/')),[])


class ReservationTests(unittest.TestCase):
    def test_next_before_write_has_outer_reserve_but_preexec_keeps_every_remaining_form(self):
        with tempfile.TemporaryDirectory() as temporary:
            controls=Path(temporary).resolve()
            usage=stage._controls_usage_v1(controls)
            single=stage._reserve_controls_v1(controls,'before-dmesg')
            self.assertEqual(single['other'],usage['other']+512+16384)
            full=stage._reserve_controls_v1(controls,'child',all_remaining=True)
            suffix=stage._D_TASKS[[row[0] for row in stage._D_TASKS].index('child'):]
            self.assertEqual(full['other'],usage['other']+sum(row[1] for row in suffix)+16384)
            self.assertGreater(full['other'],single['other'])

    def test_aggregate_reserves_parent_elf_and_full_child_file_before_copy(self):
        quote = {'other': 95488, 'dmesg': 2 * stage.DMESG_LIMIT, 'crashes': 2 * stage.CRASH_LIMIT}
        with patch.object(stage, '_reserve_controls_v1', return_value=quote):
            with self.assertRaises(stage.StageDRefusal) as caught:
                stage._reserve_aggregate_v1(Path('/controlled/controls'), stage.ELF_LIMIT)
            self.assertEqual(caught.exception.cause, 'd_aggregate_reserve')
            small = stage._reserve_aggregate_v1(Path('/controlled/controls'), 16384)
        self.assertLessEqual(small['aggregate_bytes'], stage.AGGREGATE_LIMIT)
        self.assertEqual(small['child_file_bytes'], stage.CHILD_FILE_LIMIT + 256)
        self.assertEqual(small['parent_directory_bytes'], 4096)

    def test_rpc_rounding_and_two_inode_reserves_are_precharged(self):
        with tempfile.TemporaryDirectory() as temporary:
            controls = Path(temporary).resolve()
            proposed = stage._reserve_controls_v1(controls, 'identity')
            self.assertEqual(proposed['other'], 4096 + 20992 + 16384)

    def test_prewrite_reservation_refuses_before_outstanding_output_can_cross_96_kib(self):
        with tempfile.TemporaryDirectory() as temporary:
            controls = Path(temporary).resolve()
            (controls / 'existing').write_bytes(b'x' * 65536)
            with self.assertRaises(stage.StageDRefusal) as caught:
                stage._reserve_controls_v1(controls, 'identity')
            self.assertEqual(caught.exception.cause, 'd_control_reserve')

    def test_exact_crash_directory_pin_is_used_by_default(self):
        expected = Path('/mnt/c/Users/s-a-balashov/AppData/Local/Temp/wsl-crashes')
        self.assertEqual(stage.CRASH_DIRECTORY, expected)
        with patch.object(stage.os, 'scandir', return_value=nullcontext([])) as scan:
            self.assertEqual(stage._crash_listing_v1(), b'[]')
        scan.assert_called_once_with(expected)


class SnapshotTests(unittest.TestCase):
    def test_flat_phase_collision_preserves_existing_original_and_stops(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
        with tempfile.TemporaryDirectory() as temporary:
            controls=Path(temporary).resolve();original=controls/'before.dmesg.stdout.original'
            original.write_bytes(b'retained original')
            def guard(kind,*,output_dir,_phase_prefix,**kwargs):
                self.assertEqual(_phase_prefix,'before')
                with (output_dir/(_phase_prefix+'.'+kind+'.stdout.original')).open('xb'):
                    raise AssertionError('exclusive open must refuse')
            observer=stage._NativeObserverV1(controls,lambda:1)
            with patch.object(stage,'_floor_metrics_v1',return_value=FakeObserver().measure()), \
                 patch.object(stage.compiler,'_compiler_proc_read_v1',return_value=b'00000000-0000-0000-0000-000000000001\n'), \
                 patch.object(c,'capture_guard_v1',side_effect=guard) as captured:
                with self.assertRaises(FileExistsError): observer.snapshot(controls,100,phase='before')
            self.assertEqual(original.read_bytes(),b'retained original')
            self.assertEqual(captured.call_count,1)
            self.assertEqual(list(controls.iterdir()),[original])

    def test_invalid_phase_refuses_before_capture_or_allocation(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
        with tempfile.TemporaryDirectory() as temporary,patch.object(c,'capture_guard_v1') as guard:
            controls=Path(temporary).resolve()
            observer=stage._NativeObserverV1(controls,lambda:1)
            with self.assertRaises(stage.StageDRefusal): observer.snapshot(controls,100,phase='other')
            self.assertFalse(list(controls.iterdir()));guard.assert_not_called()

    def test_empty_stderr_original_is_bound_in_every_native_capture(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
        empty_sha = hashlib.sha256(b'').hexdigest()
        for mutation in ('raw', 'hash', 'extent', 'close'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                controls = Path(temporary).resolve()
                def guard(kind, *, output_dir, **kwargs):
                    result = {'returncode': 0, 'stdout_eof': True, 'stderr_eof': True,
                        'persisted': True, 'closed': True, 'forced': False, 'causes': [], 'files': {}}
                    for name in ('stdout', 'stderr'):
                        path = output_dir / (kwargs['_phase_prefix'] + '.' + kind + '.' + name + '.original')
                        path.write_bytes(b'')
                        result[name] = {'path': str(path), 'size_bytes': 0, 'sha256': empty_sha}
                        result[name + '_observed_bytes'] = 0
                        result[name + '_confirmed_prefix_sha256'] = empty_sha
                        result['files'][name] = {'open_completed': True, 'write_failed': False,
                            'write_extent_unknown': False, 'written_bytes': 0, 'persisted_bytes': 0,
                            'flush_completed': True, 'fsync_completed': True, 'close_completed': True}
                    if kind == 'dmesg':
                        if mutation == 'raw':
                            Path(result['stderr']['path']).write_bytes(b'forged')
                        elif mutation == 'hash':
                            result['stderr']['sha256'] = 'f' * 64
                        elif mutation == 'extent':
                            result['files']['stderr']['write_extent_unknown'] = True
                        else:
                            result['files']['stderr']['close_completed'] = False
                    return result
                observer = stage._NativeObserverV1(controls, lambda: 1)
                with patch.object(stage, '_floor_metrics_v1', return_value=FakeObserver().measure()), \
                     patch.object(stage.compiler, '_compiler_proc_read_v1', return_value=b'00000000-0000-0000-0000-000000000001\n'), \
                     patch.object(stage, '_crash_listing_v1', return_value=b'[]'), \
                     patch.object(c, 'capture_guard_v1', side_effect=guard):
                    with self.assertRaises(stage.StageDRefusal):
                        observer.snapshot(controls, 100, phase='before')


class NativeEntryTests(unittest.TestCase):
    def setUp(self):
        from tests.fixtures import accepted_policy_fixture_compiler_gate2_c_v1 as c
        self.c=c
        self.commit='a'*40;self.root='/home/s-a-balashov/work/vast-fixture-compiler-gate2-'+self.commit+'-01'
        self.args=[self.commit,'131072','b'*64,','.join('8192:'+('%064x'%n) for n in range(1,7))]
        self.kw={'project_root':self.root,'packet_descriptor':{},'expected_code_commit':self.commit,
            'expected_packet_sha256':'b'*64,'completion_authorities':{}}
        self.value={'stage':'D','controlled':False,'receipt_persisted':True,
            'receipt_descriptor':{'path':self.root+'/outputs/D/controls/d.result.original.json',
                'size_bytes':20480,'sha256':'c'*64,'persisted':True,'closed':True,'extent_unknown':False},
            'final_measurement_after_receipt':{'c_free_bytes':100000000000,'ext4_used_bytes':313000000000,'project_free_bytes':100000000000},
            'ledger_after_receipt':{'remaining_before':400000000,'charge_bytes':2097152,'remaining_after':397902848},
            'absolute_deadline_ns':10000010000000000,'finished_ns':10000000000000000,
            'control_bytes':524288,'aggregate_accounted_bytes':2097152,
            'evaluation':{'passed':True,'finalization_complete':True}}

    def test_fixed_native_entry_outputs_only_bounded_final_summary(self):
        emitted=[]
        with patch.object(self.c,'parse_native_invocation_v1',return_value=self.kw,create=True) as parse, \
             patch.object(self.c,'emit_native_bytes_v1',side_effect=lambda raw,deadline:emitted.append((raw,deadline)),create=True), \
             patch.object(stage,'run_d_v1',return_value=self.value) as run:
            self.assertEqual(stage.native_main_v1(self.args),0)
        parse.assert_called_once_with(self.args,stage='D');run.assert_called_once_with(**self.kw)
        self.assertEqual(len(emitted),1);raw,deadline=emitted[0]
        self.assertLessEqual(len(raw),768);self.assertEqual(deadline,self.value['absolute_deadline_ns'])
        value=json.loads(raw);self.assertEqual(value['receipt_sha256'],'c'*64)
        self.assertTrue(value['external_return_required']);self.assertFalse(value['controlled'])
        for name in ('child','before','after','receipt_descriptor','project_root','code_commit','packet_sha256'):
            self.assertNotIn(name,value)
        self.summary=raw

    def test_native_failure_preserves_bounded_diagnostic_without_traceback_or_receipt_duplicate(self):
        error=stage.StageDRefusal('controlled_failure',{'pid':321,'unknown_closure':True,'causes':['first','close']})
        failure=b'{"cause":"controlled_failure","unknown":true}\n'
        with patch.object(self.c,'parse_native_invocation_v1',return_value=self.kw,create=True), \
             patch.object(stage,'run_d_v1',side_effect=error), \
             patch.object(self.c,'native_failure_bytes_v1',return_value=failure,create=True) as detail, \
             patch.object(stage.os,'write',return_value=len(failure)) as write:
            self.assertEqual(stage.native_main_v1(self.args),1)
        detail.assert_called_once_with(error);write.assert_called_once_with(2,failure)

    def test_controlled_or_incomplete_return_cannot_become_native_success(self):
        for changed in ({'controlled':True},{'evaluation':{'passed':True,'finalization_complete':False}}):
            with self.subTest(changed=changed),patch.object(self.c,'parse_native_invocation_v1',return_value=self.kw,create=True), \
                 patch.object(stage,'run_d_v1',return_value=dict(self.value,**changed)), \
                 patch.object(self.c,'native_failure_bytes_v1',return_value=b'{}\n',create=True), \
                 patch.object(self.c,'emit_native_bytes_v1',create=True) as emit,patch.object(stage.os,'write',return_value=3):
                self.assertEqual(stage.native_main_v1(self.args),1);emit.assert_not_called()

    def test_command_and_maximum_native_output_tool_envelope_fit_one_4k_form(self):
        script=self.root+'/tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py'
        command='& C:/Windows/System32/wsl.exe -d Ubuntu -u s-a-balashov --cd / --exec /usr/bin/python3 -I -S -B '+script+' '+self.args[0]+' '+self.args[1]+' '+self.args[2]+" '"+self.args[3]+"'"
        envelope={'command':command,'native':{'pid':4194304,'returncode':-2147483648,'stdout_eof':True,'stderr_eof':True,
            'stdout_bytes':768,'stderr_bytes':768,'stdout_sha256':'a'*64,'stderr_sha256':'b'*64,
            'stdout':'"'*767+'\n','stderr':'"'*767+'\n','unknown_closure':False},
            'tool':{'chunk_id':'a'*8,'wall_time_seconds':99999.999999,'exit_code':-2147483648,'original_token_count':2147483647}}
        # A byte cap alone is insufficient; actual producer grammar must be
        # used for the positive envelope bound below. Keep this counterexample.
        self.assertGreater(len(recipe.canonical_json_v1(envelope)),4096)
        self.assertEqual(2*(4096+4096),16384)

    def test_actual_both_channel_poststdout_failure_frame_fits_one_4k_form(self):
        outputs={1:b'',2:b''}
        deadline=self.value['absolute_deadline_ns']
        def write(fd,raw):
            self.assertIn(fd,(1,2));outputs[fd]+=raw;return len(raw)
        # The real emitter writes the successful returned summary, then its
        # original-deadline check fails. The real refusal producer must retain
        # that known write extent and emit bounded stderr, with no retry.
        with patch.object(stage,'run_d_v1',return_value=self.value),patch.object(stage.os,'write',side_effect=write), \
             patch.object(self.c.time,'monotonic_ns',side_effect=[deadline-1,deadline]):
            self.assertEqual(stage.native_main_v1(self.args),1)
        self.assertGreater(len(outputs[1]),0);self.assertGreater(len(outputs[2]),0)
        self.assertLessEqual(len(outputs[1]),768);self.assertLessEqual(len(outputs[2]),768)
        diagnostic=json.loads(outputs[2]);self.assertEqual(diagnostic['cause'],'native_stdout_deadline')
        self.assertFalse(diagnostic['facts_unknown']);self.assertTrue(diagnostic['facts_remainder_unknown'])
        script=self.root+'/tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py'
        command="& C:/Windows/System32/wsl.exe -d Ubuntu -u s-a-balashov --cd / --exec /usr/bin/python3 -I -S -B '"+script+"' '"+"' '".join(self.args)+"'; exit $LASTEXITCODE"
        frame={'schema_version':1,'tool':'exec_command','call':{'cmd':command,
            'workdir':'C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST',
            'login':False,'yield_time_ms':30000,'max_output_tokens':1024},
            'native':{'pid':4294967295,'returncode':-2147483648,'stdout_eof':True,'stderr_eof':True,
                'stdout_bytes':len(outputs[1]),'stderr_bytes':len(outputs[2]),
                'stdout_sha256':hashlib.sha256(outputs[1]).hexdigest(),'stderr_sha256':hashlib.sha256(outputs[2]).hexdigest(),
                'stdout':outputs[1].decode('ascii'),'stderr':outputs[2].decode('ascii'),'unknown_closure':False},
            'result':{'chunk_id':'a'*64,'wall_time_seconds':99999.999999,'exit_code':-2147483648,
                'original_token_count':2147483647,'session_id':None},'external_review_required':True}
        encoded=recipe.canonical_json_v1(frame)
        self.assertLessEqual(len(command),900)
        self.assertLessEqual(len(encoded),3200)
        self.assertLessEqual(len(encoded),4096)
        self.assertNotIn('output',frame['result'])
        # One captured Windows form and one copy: no third raw tool JSON form.
        self.assertEqual(2*(4096+4096),stage.EXTERNAL_CAPTURE_ALLOCATION)

    def test_bootstrap_missing_source_is_bounded_refusal_without_project_import(self):
        source=ast.parse(Path(stage.__file__).read_bytes())
        block=next(node for node in source.body if isinstance(node,ast.If))
        namespace={'__name__':'__main__','__file__':self.root+'/tests/fixtures/accepted_policy_fixture_compiler_gate2_d_v1.py',
            'sys':sys,'os':os,'Path':Path,'re':__import__('re')}
        with patch.object(sys,'argv',['script']+self.args),patch.object(Path,'resolve',side_effect=FileNotFoundError), \
             patch.object(stage.os,'write',return_value=1) as write:
            with self.assertRaises(SystemExit) as exit_status:
                exec(compile(ast.Module(body=[block],type_ignores=[]),'<controlled-bootstrap>','exec'),namespace)
        self.assertEqual(exit_status.exception.code,1)
        self.assertEqual(write.call_count,1);self.assertLessEqual(len(write.call_args.args[1]),768)

    def test_native_project_import_failure_is_bounded_without_traceback(self):
        source=ast.parse(Path(stage.__file__).read_bytes())
        block=next(node for node in source.body if isinstance(node,ast.Try) and
            any(isinstance(child,ast.ImportFrom) and child.module=='tests.fixtures' for child in node.body))
        original=__import__
        def importing(name,*args,**kwargs):
            if name=='tests.fixtures': raise ModuleNotFoundError('controlled exported import failure')
            return original(name,*args,**kwargs)
        for actor in ('__main__','controlled_module_import'):
            namespace={'__name__':actor,'sys':sys,'os':os}
            with self.subTest(actor=actor),patch('builtins.__import__',side_effect=importing), \
                 patch.object(stage.os,'write',return_value=1) as write:
                if actor=='__main__':
                    with self.assertRaises(SystemExit) as stopped:
                        exec(compile(ast.Module(body=[block],type_ignores=[]),'<controlled-project-import>','exec'),namespace)
                    self.assertEqual(stopped.exception.code,1)
                    self.assertEqual(write.call_count,1);self.assertLessEqual(len(write.call_args.args[1]),768)
                else:
                    with self.assertRaises(ModuleNotFoundError):
                        exec(compile(ast.Module(body=[block],type_ignores=[]),'<controlled-project-import>','exec'),namespace)
                    write.assert_not_called()

    def test_native_entry_c_import_failure_is_bounded_before_any_api_action(self):
        original=__import__
        def importing(name,*args,**kwargs):
            fromlist=kwargs.get('fromlist',args[2] if len(args)>2 else ())
            if name=='tests.fixtures' and 'accepted_policy_fixture_compiler_gate2_c_v1' in fromlist:
                raise ImportError('controlled C native dependency failure')
            return original(name,*args,**kwargs)
        with patch('builtins.__import__',side_effect=importing),patch.object(stage,'run_d_v1') as run, \
             patch.object(stage.os,'write',return_value=1) as write:
            self.assertEqual(stage.native_main_v1(self.args),1)
        run.assert_not_called();self.assertEqual(write.call_count,1)
        self.assertEqual(write.call_args.args[0],2);raw=write.call_args.args[1]
        self.assertLessEqual(len(raw),768);self.assertTrue(json.loads(raw)['unknown'])

    def test_native_entry_unavailable_failure_producer_uses_bounded_fallback(self):
        with patch.object(self.c,'parse_native_invocation_v1',side_effect=ValueError('controlled parse refusal')), \
             patch.object(self.c,'native_failure_bytes_v1',side_effect=ImportError('controlled producer unavailable')), \
             patch.object(stage,'run_d_v1') as run,patch.object(stage.os,'write',return_value=1) as write:
            self.assertEqual(stage.native_main_v1(self.args),1)
        run.assert_not_called();self.assertEqual(write.call_count,1)
        self.assertLessEqual(len(write.call_args.args[1]),768)
        self.assertTrue(json.loads(write.call_args.args[1])['unknown'])


class InfoTests(unittest.TestCase):
    def test_fresh_code_closure_needs_no_unexported_probe_module(self):
        original = json.loads((ROOT / 'openspec/changes/fix-accepted-policy-preprocessing/evidence/'
                               'compiler-component-01/observations-01/engine-info.v1_55.original.json').read_bytes())
        original.update(Containers=9, ContainersRunning=0, ContainersPaused=0)
        cids = ['%064x' % n for n in range(1, 10)]
        with patch.dict(sys.modules, {'tests.fixtures.accepted_policy_fixture_compiler_probe_v1': None}):
            self.assertEqual(stage._info_identity_v1(original, cids)['running'], 0)

    def test_floor_metrics_require_known_four_kib_ext4_allocation_unit(self):
        for fragment in (8192, True):
            value = SimpleNamespace(f_frsize=fragment, f_bavail=20000000, f_blocks=40000000, f_bfree=10000000)
            with self.subTest(fragment=fragment), patch.object(stage.os, 'statvfs', return_value=value), \
                 patch.object(Path, 'stat', return_value=SimpleNamespace(st_dev=1)):
                with self.assertRaises(stage.StageDRefusal) as caught:
                    stage._floor_metrics_v1(Path('/controlled'))
                self.assertEqual(caught.exception.cause, 'd_ext4_rounding')
        value = SimpleNamespace(f_frsize=4096, f_bavail=20000000, f_blocks=40000000, f_bfree=10000000)
        with patch.object(stage.os, 'statvfs', return_value=value), \
             patch.object(Path, 'stat', return_value=SimpleNamespace(st_dev=1)):
            measured = stage._floor_metrics_v1(Path('/controlled'))
        self.assertEqual(measured['ext4_used_bytes'], 30000000 * 4096)

    def test_fresh_engine_counts_and_every_identity_pin(self):
        original = json.loads((ROOT / 'openspec/changes/fix-accepted-policy-preprocessing/evidence/'
                               'compiler-component-01/observations-01/engine-info.v1_55.original.json').read_bytes())
        original.update(Containers=9, ContainersRunning=0, ContainersPaused=0)
        cids = ['%064x' % n for n in range(1, 10)]
        self.assertEqual(stage._info_identity_v1(original, cids)['running'], 0)
        for key in ('ID', 'ServerVersion', 'KernelVersion', 'Driver', 'CgroupDriver',
                    'CgroupVersion', 'DockerRootDir', 'SecurityOptions', 'Runtimes',
                    'Containers', 'ContainersRunning', 'ContainersPaused'):
            row = copy.deepcopy(original)
            row[key] = None
            with self.subTest(key=key), self.assertRaises(stage.StageDRefusal):
                stage._info_identity_v1(row, cids)


if __name__ == "__main__":
    unittest.main()
