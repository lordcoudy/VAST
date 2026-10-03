from __future__ import annotations
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
class SelectionContracts(unittest.TestCase):
    def setUp(self):
        spec=importlib.util.spec_from_file_location("ci_test_selection_v1",ROOT/"scripts/ci_test_selection_v1.py")
        self.api=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.api)
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/".ci").mkdir()
    def _case(self,name):
        class Case(unittest.TestCase):
            def runTest(self):pass
            def id(self):return name
        return Case()
    def manifest(self,rows=None,skips=None):
        value={"schema_version":1,"kind":"vast_ci_explicit_test_lanes_v1","default_lane":"mandatory_portable","integration_declarations":rows or [],"allowed_portable_skips":skips or []}
        (self.root/".ci/integration-test-selection.v1.json").write_text(json.dumps(value));return value
    def select(self,names):
        return self.api.select_portable_suite_v1(unittest.TestSuite(self._case(n) for n in names),project_root=self.root)
    def row(self,name):return {"test_id":name,"reason":"Actual complete media rehash","required_capabilities":["complete original corpus"]}
    def test_new_tests_remain_mandatory_and_original_cases_order_are_preserved(self):
        self.manifest([self.row("physical.Case.test_real")]);suite,report=self.select(["new.Case.test_new","physical.Case.test_real","old.Case.test_old"])
        self.assertEqual([x.id() for x in suite],["new.Case.test_new","old.Case.test_old"]);self.assertEqual(report["counts"],{"discovered":3,"portable":2,"integration":1});self.assertEqual(report["discovered_ids"],sorted(report["discovered_ids"]))
    def test_nested_default_discovery_is_flattened_without_reloading_tests(self):
        self.manifest();a=self._case("a.C.test_a");b=self._case("b.C.test_b");suite,report=self.api.select_portable_suite_v1(unittest.TestSuite([unittest.TestSuite([a]),b]),project_root=self.root);self.assertIs(list(suite)[0],a);self.assertEqual(report["counts"]["portable"],2)
    def test_duplicate_discovery_identity_is_rejected(self):
        self.manifest()
        with self.assertRaisesRegex(ValueError,"duplicate discovered"):self.select(["a.C.test_a","a.C.test_a"])
    def test_duplicate_integration_declarations_are_rejected(self):
        self.manifest([self.row("real.C.test_x"),self.row("real.C.test_x")])
        with self.assertRaisesRegex(ValueError,"duplicate integration"):self.select(["real.C.test_x"])
    def test_absent_declared_method_is_rejected(self):
        self.manifest([self.row("real.C.test_absent")])
        with self.assertRaisesRegex(ValueError,"absent from discovery"):self.select(["other.C.test_x"])
    def test_patterns_and_module_exceptions_are_rejected(self):
        for name in ("module.*","module","module.C.*"):
            with self.subTest(name=name):
                self.manifest([self.row(name)])
                with self.assertRaisesRegex(ValueError,"exact individual"):self.select(["module.C.test_a"])
    def test_missing_reason_or_real_capability_is_rejected(self):
        for field in ("reason","required_capabilities"):
            row=self.row("real.C.test_x");row[field]="" if field=="reason" else [];self.manifest([row])
            with self.assertRaisesRegex(ValueError,"reason and capabilities"):self.select(["real.C.test_x"])
    def test_native_namespace_interpreter_broker_source_safety_deferral_is_rejected(self):
        names=("test_checkpoint_analytics_execution_client_cpp.Case.test_native_client_regression","test_backend_publication_process_supervisor_v3.Case.test_namespace","test_backend_publication_runtime_authority.Case.test_identity","test_checkpoint_source_runtime_closure_authority_v1.Case.test_source","test_backend_runtime_validator_authority.Case.test_safety")
        for name in names:
            with self.subTest(name=name):
                self.manifest([self.row(name)])
                with self.assertRaisesRegex(ValueError,"mandatory contract"):self.select([name])
    def test_original_failed_import_remains_portable_failure(self):
        self.manifest();suite=unittest.defaultTestLoader.loadTestsFromName("does_not_exist_for_selection.Case.test_x");portable,report=self.api.select_portable_suite_v1(suite,project_root=self.root);self.assertEqual(portable.countTestCases(),1);self.assertEqual(report["counts"]["integration"],0)
    def test_exact_skip_identity_and_reason_are_audited_without_success_claim(self):
        row={"test_id":"win.C.test_handles","reason":"Windows handle semantics only","classification":"platform_or_explicit_physical_prerequisite","acceptance_claim":False};self.manifest(skips=[row]);_,report=self.select([row["test_id"]]);audit=self.api.validate_portable_skips_v1([{"test_id":row["test_id"],"reason":row["reason"]}],report);self.assertEqual(audit[0]["acceptance_claim"],False)
    def test_new_skip_or_changed_reason_is_rejected(self):
        self.manifest();_,report=self.select(["new.C.test_x"])
        with self.assertRaisesRegex(ValueError,"unapproved portable skip"):self.api.validate_portable_skips_v1([{"test_id":"new.C.test_x","reason":"missing fixtures"}],report)
    def test_skip_cannot_hide_deferred_native_contract(self):
        row={"test_id":"test_checkpoint_analytics_execution_client_cpp.Case.test_native_client_regression","reason":"unavailable","classification":"platform_or_explicit_physical_prerequisite","acceptance_claim":False};self.manifest(skips=[row])
        with self.assertRaisesRegex(ValueError,"mandatory contract"):self.select([row["test_id"]])
    def test_stale_or_duplicate_skip_declaration_fails_closed(self):
        row={"test_id":"gone.C.test_x","reason":"Windows only","classification":"platform_or_explicit_physical_prerequisite","acceptance_claim":False}
        self.manifest(skips=[row])
        with self.assertRaisesRegex(ValueError,"absent from discovery"):self.select(["new.C.test_x"])
    def test_manifest_unknown_version_or_default_lane_fails_closed(self):
        for field,value in (("schema_version",2),("default_lane","optional")):
            d=self.manifest();d[field]=value;(self.root/".ci/integration-test-selection.v1.json").write_text(json.dumps(d))
            with self.assertRaises(ValueError):self.select(["a.C.test_a"])
    def test_retired_schema_declaration_cannot_create_a_new_skip(self):
        row={"test_id":"new.C.test_x","reason":"schema-v1 fixture retained only as migration history","classification":"existing_retired_schema_migration","acceptance_claim":False};self.manifest(skips=[row])
        with self.assertRaisesRegex(ValueError,"existing source migration tombstone"):self.select([row["test_id"]])
    def test_existing_retired_source_decorator_is_inventory_nonexecution_only(self):
        reason="schema-v1 fixture retained only as migration history";row={"test_id":"test_checkpoint_model_parity.AssessmentTests.test_complete_common_source_contract_passes","reason":reason,"classification":"existing_retired_schema_migration","acceptance_claim":False};self.manifest(skips=[row]);case=self._case(row["test_id"]);unittest.skip(reason)(type(case));suite,report=self.api.select_portable_suite_v1(unittest.TestSuite([case]),project_root=self.root);self.assertEqual(suite.countTestCases(),1);self.assertEqual(report["counts"]["integration"],0);self.assertFalse(self.api.validate_portable_skips_v1([{"test_id":case.id(),"reason":reason}],report)[0]["acceptance_claim"])

    def test_current_broker_and_operational_custody_cannot_be_deferred(self):
        names = (
            'test_backend_publication_broker_terminal_v3.BackendPublicationBrokerTerminalV3Tests.test_normal_early_setup_failure_commits_original_failed_terminal',
            'test_publication_operational_container_custody_v1.OriginalContainerCompositionTests.test_resealed_foreign_absence_cannot_grant_quiescence',
            'test_publication_operational_request_domain_v1.OperationalRequestDomainTests.test_complete_native_occurrences_preserve_all_three_phases_and_original_hashes',
            'test_publication_gstreamer_component_runtime_v1.ComponentRuntimeFixtureTests.test_execution_cannot_opt_out_of_live_guardian',
            'test_ci_namespace_diagnostic_v1.NamespaceDiagnosticTests.test_exact_first_unshare_failure_delegates_once_and_retains_original_errno',
        )
        for name in names:
            with self.subTest(name=name):
                self.manifest([self.row(name)])
                with self.assertRaisesRegex(ValueError, 'mandatory contract'):
                    self.select([name])

    def test_new_broker_and_raw_custody_skip_declarations_are_rejected(self):
        for name in (
            'test_backend_publication_broker_terminal_v3.BackendPublicationBrokerTerminalV3Tests.test_normal_early_setup_failure_commits_original_failed_terminal',
            'test_publication_operational_boundary_v1.PublicationOperationalBoundaryTests.test_complete_cold_workload_includes_warmup_measurement_and_drain',
            'test_publication_guardian_component_preprocessing_contract_v1.ComponentPreprocessingTests.test_physically_resealed_foreign_front_workers_cannot_activate',
            'test_ci_namespace_diagnostic_v1.NamespaceDiagnosticTests.test_exact_first_unshare_failure_delegates_once_and_retains_original_errno',
        ):
            with self.subTest(name=name):
                row={'test_id':name,'reason':'invented missing prerequisite',
                     'classification':'platform_or_explicit_physical_prerequisite','acceptance_claim':False}
                self.manifest(skips=[row])
                with self.assertRaisesRegex(ValueError, 'mandatory contract'):
                    self.select([name])

    def test_foreign_decorated_class_cannot_invent_a_retired_migration(self):
        reason='schema-v1 fixture retained only as migration history'
        row={'test_id':'foreign.AssessmentTests.test_complete_common_source_contract_passes',
             'reason':reason,'classification':'existing_retired_schema_migration','acceptance_claim':False}
        self.manifest(skips=[row])
        case=self._case(row['test_id']);unittest.skip(reason)(type(case))
        with self.assertRaisesRegex(ValueError, 'existing source migration tombstone'):
            self.api.select_portable_suite_v1(unittest.TestSuite([case]),project_root=self.root)

    def test_all_original_platform_and_retired_skip_ids_remain_nonexecution(self):
        rows=json.loads((ROOT/self.api.MANIFEST).read_bytes())['allowed_portable_skips']
        self.assertEqual(len(rows),88)
        cases=[]
        for row in rows:
            case=self._case(row['test_id'])
            if row['classification']=='existing_retired_schema_migration':
                unittest.skip(row['reason'])(type(case))
            cases.append(case)
        self.manifest(skips=rows)
        suite,report=self.api.select_portable_suite_v1(unittest.TestSuite(cases),project_root=self.root)
        self.assertEqual(suite.countTestCases(),88)
        self.assertEqual(report['counts']['integration'],0)
        audit=self.api.validate_portable_skips_v1(rows,report)
        self.assertEqual(audit,sorted(rows,key=lambda row:row['test_id']))
        self.assertTrue(all(row['acceptance_claim'] is False for row in audit))
if __name__=="__main__":unittest.main()
