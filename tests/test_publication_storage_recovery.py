from __future__ import annotations

import hashlib
import http.client
import io
import json
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import full_publication_runtime as runtime_module
import full_publication_entrypoint as entrypoint_module
from benchmark_contract import ContractError
from publication_q4_runtime_registry_materializer_v4 import (
    build_publication_q4_runtime_launcher_input_wrapper_v3,
)
from full_publication_runner import CallbackDecision, FullPublicationRunner
from full_publication_runtime import FullPublicationRuntime
from full_publication_entrypoint import ProductionEntrypoint
from publication_cloud_transaction import verify_cloud_ledger
from seafile_artifact_store import ArtifactStoreError, ArtifactIntegrityError
from tests.test_full_publication_runner import CallbackHarness, small_matrix_factory
from tests.test_full_publication_runtime import (
    PreflightStore, pair_context, accepted_arm_runner, accepted_article_statistics_sealer,
)
from tests.test_full_publication_entrypoint import FakeRunner
from tests.test_seafile_artifact_store_security import FakeOpener, FixtureStore
from tests.test_publication_q4_runtime_contract_v4 import runtime_template

GIB = 1024**3

class PublicationStorageRecoveryTests(unittest.TestCase):
    def runtime(self, root, **kwargs):
        return FullPublicationRuntime(run_root=root, config={'benchmark': {}},
            cloud_store=PreflightStore(), arm_runner=lambda *_: None,
            readiness_validator=lambda _: {'passed': True, 'blockers': []},
            capacity_confirmed_gib=500, **kwargs)

    def runner(self, root, callbacks):
        return FullPublicationRunner(root, config={'test': True},
            identity_inputs={'source_sha256': 'source-a'}, callbacks=callbacks,
            matrix_builder=small_matrix_factory)

    def test_full_host_drive_blocks_even_with_free_results_drive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'run'
            runtime = self.runtime(root)
            original_is_dir = Path.is_dir
            def is_dir(path):
                return True if path == Path('/mnt/c') else original_is_dir(path)
            def disk_usage(path):
                return SimpleNamespace(free=0 if Path(path) == Path('/mnt/c') else 100*GIB)
            with patch.object(Path, 'is_dir', is_dir), patch.object(runtime_module.shutil, 'disk_usage', disk_usage):
                decision = runtime.preflight(pair_context(root).run)
            self.assertFalse(decision.accepted)
            self.assertTrue(decision.retryable)
            self.assertIn('/mnt/c', str(decision.details).replace('\\', '/'))

    def test_actual_scratch_and_temp_are_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'run'
            root.mkdir()
            scratch = Path(tmp)/'native-scratch'
            scratch.mkdir()
            for full in (scratch, Path(tmp)):
                with self.subTest(full=full):
                    runtime = self.runtime(root, scratch_roots=(scratch,))
                    def usage(path):
                        return SimpleNamespace(free=1 if Path(path) == full else 100*GIB)
                    with patch.object(runtime_module.tempfile, 'gettempdir', return_value=tmp), patch.object(runtime_module.shutil, 'disk_usage', usage):
                        decision = runtime.preflight(pair_context(root).run)
                    self.assertFalse(decision.accepted)
                    self.assertTrue(decision.retryable)

    def test_space_exhaustion_between_pairs_never_starts_next_pair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'run'
            harness = CallbackHarness()
            available = True
            checked = []
            def before_pair(context):
                checked.append(context.sequence)
                return CallbackDecision.passed() if available else CallbackDecision.rejected('disk full', retryable=True)
            def cloud(context, acceptance):
                nonlocal available
                receipt = harness.cloud_transaction(context, acceptance)
                available = False
                return receipt
            callbacks = replace(harness.callbacks(), before_pair=before_pair, cloud_transaction=cloud)
            result = self.runner(root, callbacks).run()
            checkpoint = json.loads((root/'checkpoint.json').read_text())
            self.assertEqual((result.exit_code, result.completed_pairs), (75, 1))
            self.assertEqual(checked, [0, 1])
            self.assertIsNone(checkpoint['inflight'])
            self.assertEqual(len(harness.arm_attempts), 2)

    def test_accepted_pair_recovers_offload_before_disk_gate_without_reexecution(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'run'
            harness = CallbackHarness()
            harness.cloud_transient_once = small_matrix_factory({'test':True})['pairs'][0]['pair_id']
            runtime = self.runtime(root)
            callbacks = replace(harness.callbacks(), preflight=runtime.preflight, before_pair=runtime.before_pair)
            runner = self.runner(root, callbacks)
            with patch.object(runtime_module.shutil, 'disk_usage', return_value=SimpleNamespace(free=100*GIB)):
                self.assertEqual(runner.run().exit_code, 75)
            attempts = dict(harness.arm_attempts)
            with patch.object(runtime_module.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)):
                recovered = runner.run()
            self.assertEqual((recovered.exit_code, recovered.completed_pairs), (75, 1))
            self.assertEqual(harness.arm_attempts, attempts)
            self.assertIsNone(json.loads((root/'checkpoint.json').read_text())['inflight'])

    def test_external_preflight_allows_only_accepted_recovery_on_full_disk(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'run'
            root.mkdir()
            for name in ('checkpoint.json', 'run_manifest.json'):
                (root/name).write_text('{}\n')
            runner = FakeRunner(root)
            base_status = runner.status()
            # Empty cloud prefix is checked normally: use sequence zero for this fixture.
            base_status['completed_pairs'] = 0
            runtime = self.runtime(root)
            app = ProductionEntrypoint(runner=runner, runtime=runtime)
            for phase, expected in (('accepted', 0), ('executing', 75)):
                status = {**base_status, 'inflight': {'phase': phase, 'sequence': 0}}
                (root/'checkpoint.json').write_text(json.dumps({
                    'verified_prefix_length': 0, 'inflight': status['inflight'],
                }))
                with self.subTest(phase=phase), patch.object(runner, 'status', return_value=status), patch.object(runtime_module.shutil, 'disk_usage', return_value=SimpleNamespace(free=0)) as usage:
                    self.assertEqual(app.dispatch('preflight')[0], expected)
                    if phase == 'accepted':
                        usage.assert_not_called()

    def test_production_scratch_paths_come_from_bound_runtime_projections(self):
        template = runtime_template('savant', 'cpu_only', 'h264')
        template['scratch_root'] = '/var/tmp/native-production'
        wrapper = build_publication_q4_runtime_launcher_input_wrapper_v3(
            system='savant', policy='cpu_only',
            qualification_runtime_input_template=template,
            production_runtime_input_template=template,
        )
        content_sha = entrypoint_module._sha256_bytes(entrypoint_module._canonical_json(wrapper))
        record = {'system': 'savant', 'policy': 'cpu_only', 'artifact': {
            'system_specific_launcher_input': {
                'content': wrapper, 'content_identity_sha256': content_sha,
            },
        }}
        identity = {'bindings': {'backend_runtime_qualification': {'systems': {
            'savant': {'runtime_authorities': [record, record]},
        }}}}
        self.assertEqual(entrypoint_module._production_scratch_roots(identity),
                         (Path('/var/tmp/native-production'),))
        wrapper['production_projection']['runtime_input_template']['scratch_root'] = '/elsewhere'
        with self.assertRaises(ContractError):
            entrypoint_module._production_scratch_roots(identity)

    def test_unavailable_temp_storage_is_transient(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'run'
            runtime = self.runtime(root)
            with patch.object(runtime_module.tempfile, 'gettempdir', side_effect=FileNotFoundError('no writable temp')):
                decision = runtime.before_pair(pair_context(root))
            self.assertFalse(decision.accepted)
            self.assertTrue(decision.retryable)

class SeafileReadbackTransportTests(unittest.TestCase):
    def test_real_cloud_commit_preserves_raw_then_recovers_without_remeasurement(self):
        for error_type in (TimeoutError, ConnectionResetError, http.client.IncompleteRead, 'wrong_size', 'wrong_sha'):
            with self.subTest(error_type=str(error_type)), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)/'run'
                opener = FakeOpener()
                normal_open = opener.open
                fail_read = True
                def open_request(request, *, timeout):
                    nonlocal fail_read
                    response = normal_open(request, timeout=timeout)
                    if '/d/readtoken/files/' in request.full_url and fail_read:
                        fail_read = False
                        if isinstance(error_type, str):
                            payload = response.read()
                            payload = payload[:-1] if error_type == 'wrong_size' else bytes([payload[0] ^ 1]) + payload[1:]
                            response.read = io.BytesIO(payload).read
                            return response
                        first = response.read(1)
                        error = error_type(b'x', 1) if error_type is http.client.IncompleteRead else error_type('transport interrupted')
                        reads = iter((first, error))
                        def read(_size=-1):
                            value = next(reads)
                            if isinstance(value, BaseException):
                                raise value
                            return value
                        response.read = read
                    return response
                opener.open = open_request
                attempts = []
                def execute(context, arm_root):
                    attempts.append(context.arm['arm_id'])
                    return accepted_arm_runner(context, arm_root)
                runtime = FullPublicationRuntime(
                    run_root=root, config={'benchmark': {}}, cloud_store=FixtureStore(opener),
                    arm_runner=execute, readiness_validator=lambda _: {'passed': True, 'blockers': []},
                    article_statistics_sealer=accepted_article_statistics_sealer,
                    capacity_confirmed_gib=500, minimum_free_bytes=1,
                )
                matrix = {**small_matrix_factory({}), 'expected_pairs': 1, 'expected_arms': 2,
                          'pairs': [pair_context(root).pair]}
                runner = FullPublicationRunner(root, config={'test': True},
                    identity_inputs={'source_sha256': 'source-a'}, callbacks=runtime.callbacks(),
                    matrix_builder=lambda _: matrix)
                first_result = runner.run()
                expected_exit = 78 if isinstance(error_type, str) else 75
                self.assertEqual(first_result.exit_code, expected_exit, first_result.message)
                self.assertEqual(json.loads((root/'checkpoint.json').read_text())['inflight']['phase'], 'accepted')
                self.assertTrue(runtime.attempt_root(pair_context(root)).is_dir())
                self.assertEqual(
                    [entry['state'] for entry in verify_cloud_ledger(root/'cloud_ledger.jsonl')],
                    ['accepted', 'archive_ready'],
                )
                self.assertEqual(len(attempts), 2)
                if expected_exit == 78:
                    self.assertEqual(json.loads((root/'checkpoint.json').read_text())['state'], 'failed_permanent')
                    continue
                recovered = runner.run()
                self.assertEqual(recovered.exit_code, 0, recovered.message)
                self.assertEqual(recovered.completed_pairs, 1)
                self.assertEqual(len(attempts), 2)
                self.assertFalse(runtime.attempt_root(pair_context(root)).exists())
                self.assertTrue((root/'cloud_ledger.jsonl').is_file())
                self.assertEqual(verify_cloud_ledger(root/'cloud_ledger.jsonl')[-1]['state'], 'local_pruned')

    def test_partial_transport_failures_are_retryable_and_hide_capabilities(self):
        for error in (TimeoutError('readtoken timeout'), ConnectionResetError('readtoken reset'), http.client.IncompleteRead(b'ab', 4)):
            with self.subTest(error=type(error).__name__):
                opener = FakeOpener()
                opener.stored['pair.bin'] = b'abcdef'
                store = FixtureStore(opener)
                response = io.BytesIO(b'ab')
                with patch.object(store, 'list_remote_files', return_value={'pair.bin': {'size': 6}}), patch.object(store, '_open_request', return_value=response), patch.object(response, 'read', side_effect=[b'ab', error]):
                    with self.assertRaises(ArtifactStoreError) as caught:
                        store.verify_remote('pair.bin', expected_size=6, expected_sha256=hashlib.sha256(b'abcdef').hexdigest())
                self.assertNotIsInstance(caught.exception, ArtifactIntegrityError)
                self.assertNotIn('readtoken', str(caught.exception))

    def test_completed_wrong_size_or_sha_remains_permanent(self):
        for payload in (b'ab', b'abcdeg'):
            with self.subTest(payload=payload):
                opener = FakeOpener()
                opener.stored['pair.bin'] = b'abcdef'
                store = FixtureStore(opener)
                with patch.object(store, 'list_remote_files', return_value={'pair.bin': {'size': 6}}), patch.object(store, '_open_request', return_value=io.BytesIO(payload)):
                    with self.assertRaises(ArtifactIntegrityError):
                        store.verify_remote('pair.bin', expected_size=6, expected_sha256=hashlib.sha256(b'abcdef').hexdigest())
