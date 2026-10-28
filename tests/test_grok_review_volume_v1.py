"""Controlled orchestration checks; no Hyper-V or Storage command is exercised."""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "scripts" / "prepare_grok_review_volume_v1.ps1"
PWSH = shutil.which("pwsh")

# The production boundary is never constructed. Every effect is an in-memory
# fake, and each returned disk/partition must be the exact object passed onward.
HARNESS = r"""
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
. '__SOURCE__'
$script:trace=[Collections.Generic.List[string]]::new()
$script:tick=1000L
$script:disk=[pscustomobject]@{Path='disk:owned';UniqueId='owned';Size=134217728L;PartitionStyle='RAW';IsBoot=$false;IsSystem=$false;IsClustered=$false;PartitionCount=0}
$script:partition=[pscustomobject]@{DiskPath='disk:owned';DiskUniqueId='owned';Guid='partition:owned';Size=132120576L;Offset=1048576L;Type='basic'}
$script:volume=[pscustomobject]@{DiskPath='disk:owned';PartitionGuid='partition:owned';Guid='volume:owned';Serial='12345678';FileSystem='NTFS';AllocationUnit=4096;Size=132120576L;Free=100663296L}
$script:backing=[pscustomobject]@{Path='E:/VAST-pr9/grok-bounded-review-20261028-07.vhd';Identity='file:owned';VhdId='vhd:owned';Length=134218240L;Allocation=134221824L;Normal=$true;FooterValid=$true;Size=134217728L;Type='Fixed';Format='VHD'}
$script:env=[pscustomobject]@{Elevated=$true;Sid='S-1-5-21-3110146144-1192974603-3912567380-24130';SourceSha256=('a'*64);Boot='boot';VAbsent=$true;TargetAbsent=$true;ParentSafe=$true;CommandsQualified=$true;CFree=200GB;EFree=200GB;AllocationUnitC=4096;AllocationUnitE=4096}
$script:admission=@{schema_version=1;planning_commit='44e8cef19d70f555e2f37dd4ea07651bd9b8125f';source_sha256=('a'*64);execution_approval=123;independent_reviews=@(101,102);ordinary_sid=$script:env.Sid;boot='boot';deadline_tick_ms=181000L;ordinary_v_absent=$true;ordinary_check_tick_ms=1000L;c_peak_bytes=80GB;e_peak_bytes=66GB;e_metadata_bytes=2MB;native_writers_qualified=$true;source_reviewed=$true}
$script:job=[pscustomobject]@{Path='job:owned';Server='local';Namespace='root/virtualization/v2';Class='Msvm_ConcreteJob';Keys=@{InstanceID=$null};KeyTypes=@{InstanceID='String'};State=7;ErrorCode=0}
$script:boundary=[pscustomobject]@{
 Now={ $script:tick }
 Host={ $script:env }
 Create={ $script:trace.Add('create'); [pscustomobject]@{ReturnValue=0;Job=$null} }
 Attach={ $script:trace.Add('attach'); [pscustomobject]@{ReturnValue=4096;Job=$script:job} }
 Job={ param($original) if(-not [object]::ReferenceEquals($original,$script:job)){throw 'foreign job passed'}; $script:trace.Add('job'); $script:job }
 Pause={ param($ms) $script:tick+=$ms }
 Backing={ $script:trace.Add('backing'); $script:backing }
 Disks={ $script:trace.Add('disks'); if($script:trace.Contains('attach')){,@($script:disk)}else{,@()} }
 Reverse={ param($actual) if(-not [object]::ReferenceEquals($actual,$script:disk)){throw 'foreign disk reverse'}; $script:backing }
 Initialize={ param($actual) if(-not [object]::ReferenceEquals($actual,$script:disk)){throw 'foreign initialize'}; $script:trace.Add('initialize'); $script:disk.PartitionStyle='GPT'; $script:disk }
 Partition={ param($actual) if(-not [object]::ReferenceEquals($actual,$script:disk)){throw 'foreign partition disk'}; $script:trace.Add('partition'); $script:partition }
 Format={ param($actual) if(-not [object]::ReferenceEquals($actual,$script:partition)){throw 'foreign format partition'}; $script:trace.Add('format'); $script:volume }
 Volume={ param($actual) if(-not [object]::ReferenceEquals($actual,$script:partition)){throw 'foreign volume partition'}; $script:volume }
 VAbsent={ $script:env.VAbsent }
 Protect={ $script:trace.Add('protect') }
 Assign={ param($actual) if(-not [object]::ReferenceEquals($actual,$script:partition)){throw 'foreign assignment'}; $script:trace.Add('assign') }
 Close={ $script:trace.Add('close') }
}
__CASE__
[ordered]@{result=$result;trace=@($script:trace)} | ConvertTo-Json -Depth 16 -Compress
"""


@unittest.skipUnless(PWSH, "PowerShell runtime is required for controlled Windows setup checks")
class GrokReviewVolumeTest(unittest.TestCase):
    def run_case(self, case: str) -> dict:
        self.assertTrue(SOURCE.is_file(), "approved bounded setup implementation is absent")
        source = str(SOURCE).replace("'", "''")
        command = HARNESS.replace("__SOURCE__", source).replace("__CASE__", case)
        completed = subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
            cwd=ROOT, check=False,
        )
        self.assertLessEqual(len(completed.stdout), 32768)
        self.assertLessEqual(len(completed.stderr), 32768)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        return json.loads(completed.stdout.decode("utf-8-sig"))

    def invoke(self, before: str = "") -> dict:
        return self.run_case(before + "\n$result=Invoke-Pr9GrokReviewVolumeSetup -Admission $script:admission -Boundary $script:boundary")

    def assert_refused_without_effects(self, result: dict, code: str):
        self.assertEqual(result["result"]["status"], "refused")
        self.assertEqual(result["result"]["primary"], code)
        self.assertEqual(result["trace"], ["close"])

    def test_default_describes_without_constructing_native_boundary(self):
        result = self.run_case("$result=Invoke-Pr9GrokReviewVolumeSetup")
        self.assertEqual(result["result"]["status"], "described")
        self.assertEqual(result["trace"], [])
        self.assertEqual(result["result"]["plan"]["virtual_bytes"], 134217728)

    def test_missing_foreign_or_unreviewed_authority_has_zero_effects(self):
        for before in (
            "$script:admission.execution_approval=0",
            "$script:admission.planning_commit='foreign'",
            "$script:admission.source_sha256=('b'*64)",
            "$script:admission.source_reviewed=$false",
            "$script:admission.independent_reviews=@(101,101)",
        ):
            with self.subTest(before=before):
                self.assert_refused_without_effects(self.invoke(before), "authority")

    def test_nonadmin_has_zero_effects(self):
        self.assert_refused_without_effects(self.invoke("$script:env.Elevated=$false"), "privilege")

    def test_expired_inherited_deadline_has_zero_effects(self):
        self.assert_refused_without_effects(self.invoke("$script:admission.deadline_tick_ms=1000L"), "deadline")

    def test_occupied_ordinary_or_elevated_letter_has_zero_effects(self):
        for before in ("$script:admission.ordinary_v_absent=$false", "$script:env.VAbsent=$false"):
            with self.subTest(before=before):
                self.assert_refused_without_effects(self.invoke(before), "letter")

    def test_existing_or_aliased_target_has_zero_effects(self):
        for before in ("$script:env.TargetAbsent=$false", "$script:env.ParentSafe=$false"):
            with self.subTest(before=before):
                self.assert_refused_without_effects(self.invoke(before), "target")

    def test_insufficient_or_unknown_complete_peak_has_zero_effects(self):
        for before in (
            "$script:env.CFree=40GB", "$script:env.EFree=1GB",
            "$script:admission.native_writers_qualified=$false",
            "$script:admission.e_metadata_bytes=0",
        ):
            with self.subTest(before=before):
                self.assert_refused_without_effects(self.invoke(before), "capacity")

    def test_success_preserves_exact_objects_and_backend_completion_order(self):
        result = self.invoke()
        self.assertEqual(result["result"]["status"], "ready")
        trace = result["trace"]
        self.assertEqual([x for x in trace if x in ("create", "attach", "initialize", "partition", "format", "protect", "assign")],
                         ["create", "attach", "initialize", "partition", "format", "protect", "assign"])
        self.assertLess(trace.index("job"), trace.index("initialize"))
        self.assertEqual(trace[-1], "close")
        self.assertEqual(result["result"]["backends"][1]["kind"], "original_job")
        self.assertIsNone(result["result"]["backends"][1]["identity"]["keys"]["InstanceID"])

    def test_wrong_backing_stops_before_attachment(self):
        for before in ("$script:backing.FooterValid=$false", "$script:backing.Normal=$false", "$script:backing.Length=1"):
            with self.subTest(before=before):
                result = self.invoke(before)
                self.assertEqual(result["result"]["status"], "held")
                self.assertNotIn("attach", result["trace"])
                self.assertEqual(result["result"]["primary"], "backing")

    def test_extra_or_foreign_new_disk_prevents_initialization(self):
        for before in (
            "$script:boundary.Disks={if($script:trace.Contains('attach')){,@($script:disk,$script:disk)}else{,@()}}",
            "$script:disk.IsSystem=$true",
            "$script:boundary.Reverse={param($actual) [pscustomobject]@{Identity='foreign';VhdId='foreign'}}",
        ):
            with self.subTest(before=before):
                result = self.invoke(before)
                self.assertEqual(result["result"]["status"], "held")
                self.assertNotIn("initialize", result["trace"])

    def test_foreign_partition_or_volume_prevents_next_effect(self):
        result = self.invoke("$script:partition.DiskUniqueId='foreign'")
        self.assertEqual(result["result"]["primary"], "partition")
        self.assertIn("partition", result["trace"])
        self.assertNotIn("format", result["trace"])
        result = self.invoke("$script:volume.PartitionGuid='foreign'")
        self.assertEqual(result["result"]["primary"], "volume")
        self.assertIn("format", result["trace"])
        self.assertNotIn("assign", result["trace"])

    def test_provider_failure_retains_original_return_and_stops(self):
        result = self.invoke("$script:boundary.Create={$script:trace.Add('create');[pscustomobject]@{ReturnValue=32769;Job=$null}}")
        self.assertEqual(result["result"]["primary"], "backend_failure")
        self.assertEqual(result["result"]["backends"][0]["return_value"], 32769)
        self.assertNotIn("attach", result["trace"])

    def test_unknown_job_retains_original_identity_without_cleanup_or_retry(self):
        result = self.invoke("$script:job.State=4; $script:boundary.Pause={param($ms)$script:tick=181000L}")
        self.assertEqual(result["result"]["primary"], "backend_unknown")
        self.assertEqual(result["trace"].count("attach"), 1)
        self.assertNotIn("initialize", result["trace"])
        self.assertEqual(result["result"]["backends"][1]["identity"]["path"], "job:owned")

    def test_midstep_file_drift_or_letter_occupation_stops(self):
        result = self.invoke("$script:boundary.Reverse={param($actual)$script:backing.Identity='foreign';$script:backing}")
        self.assertEqual(result["result"]["status"], "held")
        self.assertIn("attach", result["trace"])
        self.assertNotIn("initialize", result["trace"])
        result = self.invoke("$script:boundary.Protect={$script:trace.Add('protect');$script:env.VAbsent=$false}")
        self.assertEqual(result["result"]["primary"], "letter")
        self.assertIn("protect", result["trace"])
        self.assertNotIn("assign", result["trace"])

    def test_primary_and_distinct_close_failure_are_retained(self):
        result = self.invoke("$script:boundary.Create={throw [IO.IOException]::new('first')};$script:boundary.Close={throw [IO.IOException]::new('close')}")
        self.assertEqual(result["result"]["primary"], "create")
        self.assertEqual(result["result"]["secondary"], ["close"])
        self.assertFalse(result["result"]["closed"])



    def test_late_revalidation_never_starts_next_effect(self):
        cases = (
            ("$script:n=0;$script:boundary.Backing={$script:n++;if($script:n -eq 2){$script:tick=181000L};$script:backing}", "attach"),
            ("$script:n=0;$script:boundary.Reverse={param($actual)$script:n++;if($script:n -eq 2){$script:tick=181000L};$script:backing}", "initialize"),
            ("$script:boundary.Volume={param($actual)$script:tick=181000L;$script:volume}", "protect"),
            ("$script:boundary.VAbsent={$script:tick=181000L;$true}", "assign"),
        )
        for before, effect in cases:
            with self.subTest(effect=effect):
                result = self.invoke(before)
                self.assertEqual(result["result"]["status"], "held")
                self.assertNotIn(effect, result["trace"])

    def test_mutable_disk_and_partition_aliases_cannot_replace_pins(self):
        result = self.invoke("$script:boundary.Initialize={param($actual)$script:trace.Add('initialize');$actual.UniqueId='foreign';$actual.PartitionStyle='GPT';$actual}")
        self.assertEqual(result["result"]["status"], "held")
        self.assertIn("initialize", result["trace"])
        self.assertNotIn("partition", result["trace"])
        result = self.invoke("$script:n=0;$script:boundary.Reverse={param($actual)$script:n++;if($script:n -eq 4){$script:partition.Guid='foreign'};$script:backing}")
        self.assertEqual(result["result"]["status"], "held")
        self.assertIn("partition", result["trace"])
        self.assertNotIn("format", result["trace"])

    def test_malformed_backend_numbers_and_key_types_never_become_success(self):
        cases = (
            ("$script:boundary.Create={[pscustomobject]@{ReturnValue=$false;Job=$null}}", "attach"),
            ("$script:job.State=6.9", "initialize"),
            ("$script:job.ErrorCode=$false", "initialize"),
            ("$script:job.Keys.InstanceID=1", "initialize"),
        )
        for before, effect in cases:
            with self.subTest(before=before):
                result = self.invoke(before)
                self.assertEqual(result["result"]["primary"], "backend_unknown")
                self.assertNotIn(effect, result["trace"])

    def test_refreshed_job_path_or_key_type_drift_is_unknown(self):
        for before in (
            "$script:boundary.Job={param($original)$script:job.Path='foreign';$script:job}",
            "$script:boundary.Job={param($original)$script:job.KeyTypes.InstanceID='UInt32';$script:job}",
        ):
            with self.subTest(before=before):
                result = self.invoke(before)
                self.assertEqual(result["result"]["primary"], "backend_unknown")
                self.assertNotIn("initialize", result["trace"])

    def test_arbitrary_exception_data_is_not_stringified_or_published(self):
        before = "$script:boundary.Create={$e=[IO.IOException]::new('private');$e.Data['pr9_volume_code']='PRIVATE' * 10000;throw $e}"
        result = self.invoke(before)
        self.assertEqual(result["result"]["primary"], "create")
        self.assertLess(len(json.dumps(result)), 16384)
        self.assertNotIn("PRIVATE", json.dumps(result))

    def test_late_close_cannot_publish_ready(self):
        result = self.invoke("$script:boundary.Close={$script:trace.Add('close');$script:tick=181000L}")
        self.assertEqual(result["result"]["status"], "held")
        self.assertTrue(result["result"]["closed"])
        self.assertEqual(result["result"]["primary"], "deadline")


    def test_changed_backing_flags_are_checked_again_before_attach(self):
        result = self.invoke("$script:n=0;$script:boundary.Backing={$script:n++;if($script:n -eq 2){$script:backing.Normal=$false};$script:backing}")
        self.assertEqual(result["result"]["primary"], "backing")
        self.assertNotIn("attach", result["trace"])

    def test_integer_values_do_not_masquerade_as_boolean_authority(self):
        for before, code in (
            ("$script:admission.source_reviewed=1", "authority"),
            ("$script:admission.native_writers_qualified=1", "capacity"),
            ("$script:env.Elevated=1", "privilege"),
        ):
            with self.subTest(before=before):
                self.assert_refused_without_effects(self.invoke(before), code)


    def test_void_callbacks_cannot_leak_pipeline_values(self):
        result = self.invoke("$script:boundary.Protect={'PRIVATE_CANARY'};$script:boundary.Assign={param($actual)'PRIVATE_CANARY'};$script:boundary.Close={'PRIVATE_CANARY'}")
        self.assertIsInstance(result["result"], dict)
        self.assertNotIn("PRIVATE_CANARY", json.dumps(result))
        self.assertEqual(result["result"]["status"], "ready")
        result = self.invoke("$script:job.State=4;$script:boundary.Pause={param($ms)$script:tick=181000L;'PRIVATE_CANARY'}")
        self.assertIsInstance(result["result"], dict)
        self.assertNotIn("PRIVATE_CANARY", json.dumps(result))

    def test_fresh_raw_snapshot_with_partitions_prevents_initialize(self):
        before = "$script:dn=0;$script:boundary.Disks={$script:dn++;if($script:trace.Contains('attach')){if($script:dn -ge 3){,@([pscustomobject]@{Path=$script:disk.Path;UniqueId=$script:disk.UniqueId;Size=$script:disk.Size;PartitionStyle=$script:disk.PartitionStyle;IsBoot=$false;IsSystem=$false;IsClustered=$false;PartitionCount=1})}else{,@($script:disk)}}else{,@()}}"
        result = self.invoke(before)
        self.assertEqual(result["result"]["status"], "held")
        self.assertNotIn("initialize", result["trace"])


    def metadata_case(self, case: str) -> dict:
        guard = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_volume_guard_v1.proposed.ps1"
        self.assertTrue(guard.is_file())
        return self.run_case(". '" + str(guard).replace("'", "''") + "'\n" + case)

    def test_readonly_metadata_interop_compiles_with_sdk_layout_sizes(self):
        result = self.metadata_case(
            "Initialize-Pr9GrokVolumeMetadataNative;"
            "$basic=[Pr9GrokVolumeMetadataV1].GetNestedType('Basic',[Reflection.BindingFlags]::NonPublic);"
            "$standard=[Pr9GrokVolumeMetadataV1].GetNestedType('Standard',[Reflection.BindingFlags]::NonPublic);"
            "$result=@{basic=[Runtime.InteropServices.Marshal]::SizeOf([Activator]::CreateInstance($basic));standard=[Runtime.InteropServices.Marshal]::SizeOf([Activator]::CreateInstance($standard))}"
        )
        self.assertEqual(result["result"], {"basic": 52, "standard": 24})

    @unittest.skipUnless(sys.platform == "win32", "actual Windows token refusal requires Windows")
    def test_readonly_metadata_refuses_ordinary_token_before_loading_native_code(self):
        result = self.metadata_case(
            "$id=[Security.Principal.WindowsIdentity]::GetCurrent();"
            "try{$admin=([Security.Principal.WindowsPrincipal]::new($id)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)}finally{$id.Dispose()};"
            "$refused=$false;if(-not $admin){try{$null=Get-Pr9GrokReviewVolumeMetadata -OriginalDeadlineTick ([Environment]::TickCount64+10000)}catch{$refused=$true}};"
            "$result=@{elevated=$admin;refused=$refused;native_loaded=($null -ne ('Pr9GrokVolumeMetadataV1' -as [type]))}"
        )
        if result["result"]["elevated"]:
            self.skipTest("this negative control needs the original ordinary token")
        self.assertTrue(result["result"]["refused"])
        self.assertFalse(result["result"]["native_loaded"])


    def test_metadata_late_observation_keeps_returned_facts(self):
        result = self.metadata_case(
            "$result=New-Pr9GrokVolumeMetadataObservation -Operation 'ntfs_E' -Value @{mft_valid_bytes=37} -ObservedTick 500 -OriginalDeadlineTick 400"
        )
        self.assertFalse(result["result"]["complete"])
        self.assertTrue(result["result"]["deadline_exceeded"])
        self.assertEqual(result["result"]["facts"]["mft_valid_bytes"], 37)

    def test_metadata_expired_initialization_never_loads_native(self):
        result = self.metadata_case(
            "$script:loaded=0;$ok=Invoke-Pr9GrokVolumeMetadataInitialization -OriginalDeadlineTick 400 -Now {500L} -Load {$script:loaded++};"
            "$result=@{initialized=$ok;loads=$script:loaded}"
        )
        self.assertFalse(result["result"]["initialized"])
        self.assertEqual(result["result"]["loads"], 0)


    def test_original_deadline_cannot_be_renewed_by_a_callback(self):
        result = self.invoke("$script:boundary.Create={$script:trace.Add('create');$script:admission.deadline_tick_ms=361000L;$script:tick=181001L;[pscustomobject]@{ReturnValue=0;Job=$null}}")
        self.assertEqual(result["result"]["status"], "held")
        self.assertNotIn("attach", result["trace"])

    def test_review_ids_must_be_protocol_integers(self):
        self.assert_refused_without_effects(self.invoke("$script:admission.independent_reviews=@('alpha','beta')"), "authority")

    def test_same_secondary_exception_is_retained_once(self):
        result = self.invoke(
            "$script:secondary=[IO.IOException]::new('secondary');"
            "$script:boundary.Create={throw [IO.IOException]::new('primary')};"
            "$script:boundary.Close={$script:trace.Add('close');throw $script:secondary};"
            "$script:boundary.Now={if($script:trace.Contains('close')){throw $script:secondary};1000L}"
        )
        self.assertEqual(result["result"]["primary"], "create")
        self.assertEqual(result["result"]["secondary"], ["close"])

    def test_json_roundtrip_admission_preserves_valid_integer_protocol(self):
        result = self.invoke("$script:admission=$script:admission | ConvertTo-Json -Depth 8 -Compress | ConvertFrom-Json -AsHashtable")
        self.assertEqual(result["result"]["status"], "ready")


    @unittest.skipUnless(sys.platform == "win32", "owned read-handle close fault requires Windows")
    def test_metadata_read_result_survives_an_owned_handle_close_failure(self):
        guard = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_volume_guard_v1.proposed.ps1"
        literal = str(guard).replace("'", "''")
        result = self.metadata_case(
            "Initialize-Pr9GrokVolumeMetadataNative;"
            "$flags=[Reflection.BindingFlags]'NonPublic,Static';"
            "$closeMethod=[Pr9GrokVolumeMetadataV1].GetMethod('CloseHandle',$flags);"
            "$script:closeCalls=0;$reader=[Func[IntPtr,object]]{param($ownedHandle)return @{marker=37}};"
            "$closer=[Func[IntPtr,Exception]]{param($ownedHandle)$closed=$closeMethod.Invoke($null,[object[]]@($ownedHandle));if(-not $closed){throw 'controlled close failed'};$script:closeCalls=$script:closeCalls+1;return [IO.IOException]::new('synthetic close result')};"
            "$method=[Pr9GrokVolumeMetadataV1].GetMethod('WithHandle',$flags).MakeGenericMethod([type[]]@([object]));"
            "try{$null=$method.Invoke($null,[object[]]@('" + literal + "',[uint32]0x80,[uint32]0x02200000,$reader,$closer));throw 'expected close failure'}"
            "catch{$result=Get-Pr9GrokVolumeMetadataFailure $_.Exception 'controlled_close';$result['close_invocations']=$script:closeCalls}"
        )
        self.assertFalse(result["result"]["complete"])
        self.assertEqual(result["result"].get("returned_facts"), {"marker": 37})
        self.assertEqual(result["result"]["close_invocations"], 1)
        self.assertTrue(any(c["type"] == "System.IO.IOException" for c in result["result"]["causes"]))

    def test_metadata_repeated_exception_identity_is_not_duplicated(self):
        result = self.metadata_case(
            "$same=[IO.IOException]::new('controlled');$errorValue=[AggregateException]::new([Exception[]]@($same,$same));"
            "$result=Get-Pr9GrokVolumeMetadataFailure $errorValue 'controlled_identity'"
        )
        self.assertEqual(sum(c["type"] == "System.IO.IOException" for c in result["result"]["causes"]), 1)


    def test_authority_text_and_observation_tick_have_exact_protocol_types(self):
        for before, code in (
            ("$script:admission.planning_commit=$true", "authority"),
            ("$script:admission.ordinary_sid=$true", "authority"),
            ("$script:env.Sid=$true", "authority"),
            ("$script:admission.boot='True';$script:env.Boot=$true", "authority"),
            ("$script:admission.ordinary_check_tick_ms=$true", "deadline"),
            ("$script:admission.ordinary_check_tick_ms='1000'", "deadline"),
            ("$script:env.AllocationUnitC=$true", "capacity"),
        ):
            with self.subTest(before=before):
                self.assert_refused_without_effects(self.invoke(before), code)

    def test_metadata_widths_and_identity_text_do_not_coerce(self):
        for before, effect in (
            ("$script:backing.Length=$true", "attach"),
            ("$script:backing.Type=$true", "attach"),
            ("$script:disk.Size=$true", "initialize"),
            ("$script:disk.PartitionStyle=$true", "initialize"),
            ("$script:job.Class=$true", "initialize"),
            ("$script:boundary.Reverse={param($actual)[pscustomobject]@{Identity=$true;VhdId=$true}}", "initialize"),
            ("$script:partition.Size=$true", "format"),
            ("$script:partition.DiskPath=$true", "format"),
            ("$script:partition.Type=$true", "format"),
            ("$script:volume.DiskPath=$true", "assign"),
            ("$script:volume.AllocationUnit=$true", "assign"),
            ("$script:volume.FileSystem=$true", "assign"),
        ):
            with self.subTest(before=before):
                result = self.invoke(before)
                self.assertEqual(result["result"]["status"], "held")
                self.assertNotIn(effect, result["trace"])


    def test_late_reverse_cannot_coerce_disk_identity(self):
        for member in ("Path", "UniqueId"):
            with self.subTest(member=member):
                before = "$script:n=0;$script:boundary.Reverse={param($actual)$script:n++;if($script:n -eq 2){$actual." + member + "=$true};$script:backing}"
                result = self.invoke(before)
                self.assertEqual(result["result"]["status"], "held")
                self.assertNotIn("initialize", result["trace"])


    def test_late_reverse_cannot_change_disk_eligibility(self):
        for change in ("$actual.IsSystem=$true", "$actual.IsBoot=$true", "$actual.IsClustered=$true", "$actual.PartitionCount=1", "$actual.Size=1", "$actual.PartitionStyle='GPT'"):
            with self.subTest(change=change):
                before = "$script:n=0;$script:boundary.Reverse={param($actual)$script:n++;if($script:n -eq 2){" + change + "};$script:backing}"
                result = self.invoke(before)
                self.assertEqual(result["result"]["status"], "held")
                self.assertNotIn("initialize", result["trace"])


@unittest.skipUnless(sys.platform == "win32", "Windows owned-worker transport")
class GrokReadonlyWorkerContractTest(unittest.TestCase):
    def load_worker(self):
        import importlib.util
        path = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_capture_v1.proposed.py"
        self.assertTrue(path.is_file(), "bounded read-only worker transport is absent")
        spec = importlib.util.spec_from_file_location("pr9_readonly_worker_control", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_worker_has_no_grok_or_general_command_mode(self):
        module = self.load_worker()
        self.assertEqual(set(module.STATIC_ARGUMENTS), {"metadata_qualification", "runtime_census"})
        self.assertEqual(set(module.CONTROL_PROGRAMS), {"control_normal", "control_descendant", "control_overflow"})

    def test_metadata_transport_uses_existing_isolated_python(self):
        module = self.load_worker()
        self.assertEqual(module.STATIC_ARGUMENTS["metadata_qualification"][:4], ("-I", "-B", "-S", "-c"))
        self.assertEqual(module.METADATA_EXECUTABLE, r"C:\Python314\python.exe")

    def test_fixed_payload_authenticates_driver_with_installed_python(self):
        module = self.load_worker()
        payload = module.STATIC_ARGUMENTS["metadata_qualification"][-1]
        self.assertLessEqual(len(payload), 24576)
        prefix = payload.split("\nnamespace =", 1)[0]
        # Only decompress and hash the embedded source; no driver is parsed or run.
        completed = subprocess.run([sys.executable, "-I", "-B", "-S", "-c",
            prefix + "\nprint('bound',end='')"], cwd=ROOT, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=15, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        self.assertEqual(completed.stdout, b"bound")

    def test_unknown_mode_never_constructs_a_process(self):
        from unittest import mock
        module = self.load_worker()
        with mock.patch.object(module.subprocess, "Popen", side_effect=AssertionError("process tripwire")):
            with self.assertRaises(ValueError):
                module.capture_literal(mode="model_review", executable="unapproved.exe", cwd=ROOT,
                    environment={}, deadline_tick_ms=181000, job_type=None, observation=None, private_outputs=None)

    def test_wrong_metadata_executable_refuses_before_ownership(self):
        from unittest import mock
        module = self.load_worker()
        for mode in ("metadata_qualification", "runtime_census"):
            with self.subTest(mode=mode), mock.patch.object(module.subprocess, "Popen", side_effect=AssertionError("process tripwire")):
                with self.assertRaisesRegex(ValueError, "executable"):
                    module.capture_literal(mode=mode, executable="unapproved.exe", cwd=ROOT,
                        environment={}, deadline_tick_ms=181000, job_type=None, observation=None, private_outputs=None)

    def test_metadata_deadline_binding_refuses_before_privileged_probe(self):
        from unittest import mock
        module = self.load_worker()
        for mode in ("metadata_qualification", "runtime_census"):
            with self.subTest(mode=mode), mock.patch.object(module, "require_metadata_admin", side_effect=AssertionError("privilege tripwire")):
                with self.assertRaisesRegex(ValueError, "deadline"):
                    module.capture_literal(mode=mode, executable=module.METADATA_EXECUTABLE,
                        cwd=ROOT, environment={"PR9_METADATA_DEADLINE_TICK": "renewed"},
                        deadline_tick_ms=181000, job_type=None, observation=None, private_outputs=None)

    def test_metadata_source_binding_refuses_before_privileged_probe(self):
        from unittest import mock
        module = self.load_worker()
        cases = [(mode, "b" * 64, None) for mode in ("metadata_qualification", "runtime_census")]
        cases += [("runtime_census", module.METADATA_DRIVER_SHA256, value) for value in (None, "!", "e30=")]
        for mode, sha, pins in cases:
            with self.subTest(mode=mode, pins=pins), mock.patch.object(module, "require_metadata_admin", side_effect=AssertionError("privilege tripwire")) as probe:
                with self.assertRaisesRegex(ValueError, "source"):
                    module.capture_literal(mode=mode, executable=module.METADATA_EXECUTABLE, cwd=ROOT,
                        environment={"PR9_METADATA_DEADLINE_TICK": "181000", "PR9_METADATA_DRIVER_SHA256": sha, "PR9_RUNTIME_CENSUS_PINS": pins},
                        deadline_tick_ms=181000, job_type=None, observation=None, private_outputs=None)
            probe.assert_not_called()

    def test_transient_job_accounting_after_root_exit_waits_for_retirement(self):
        import os
        module = self.load_worker()
        owner = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/grok_reviewed_job_definitions_v1.proposed.py"
        with owner.open("rb") as stream:
            job_type = module.load_reviewed_job_definitions(stream.read(7982))
        observations = []
        query_counts = {"pre_exit": 0, "post_exit": 0, "injections": 0}

        class DelayedAccounting(job_type):
            def __init__(self):
                super().__init__()
                self.original_process = None
                self.injected = False

            def assign(self, process):
                super().assign(process)
                self.original_process = process

            def active_processes(self):
                actual = super().active_processes()
                if self.original_process.returncode is None:
                    query_counts["pre_exit"] += 1
                    return actual
                query_counts["post_exit"] += 1
                returned = actual
                injected = actual == 0 and not self.injected
                if injected:
                    self.injected = True
                    query_counts["injections"] += 1
                    returned = 1  # A synthetic stale observation after actual native zero.
                row = {"actual": actual, "returned": returned, "synthetic": injected}
                if not observations or observations[-1] != row:
                    if len(observations) >= 32:
                        raise OverflowError("controlled accounting transition ceiling")
                    observations.append(row)
                return returned

        observer = module.WindowsObservation()
        result = module.capture_literal(mode="control_normal", executable=sys.executable, cwd=ROOT,
            environment={key: os.environ[key] for key in ("SystemRoot", "WINDIR") if key in os.environ},
            deadline_tick_ms=observer.tick() + 30000, job_type=DelayedAccounting,
            observation=observer, private_outputs=None)
        facts = result["facts"]
        print("CONTROLLED_JOB_ACCOUNTING", json.dumps({"observations": observations,
            "query_counts": query_counts,
            "original_pid": facts["original_pid"], "original_creation_filetime": facts["original_creation_filetime"],
            "complete": facts["complete"], "forced": facts["forced"]}, separators=(",", ":")))
        self.assertEqual(facts["active_after_retirement"], 0)
        self.assertTrue(facts["job_handle_closed"])
        self.assertTrue(facts["process_handle_closed"])
        self.assertTrue(all(row["eof"] and row["io_settled"] for row in facts["channels"]))
        self.assertEqual(query_counts["injections"], 1)
        self.assertTrue(facts["complete"], facts)
        self.assertFalse(facts["forced"])
        self.assertEqual(result["private_channel_bytes"], [b"out\n", b"err\n"])

@unittest.skipUnless(sys.platform == "win32", "Windows qualification caller")
class GrokReadonlyCallerTest(unittest.TestCase):
    def load_caller(self):
        import importlib.util
        path = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_driver_v1.proposed.py"
        self.assertTrue(path.is_file(), "fixed read-only caller is absent")
        spec = importlib.util.spec_from_file_location("pr9_readonly_caller_control", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_import_and_default_description_have_no_execution_authority(self):
        module = self.load_caller()
        result = module.describe()
        self.assertEqual(result["scope"], "ntfs_metadata_qualification_v1")
        self.assertFalse(result["execution_authority"])
        self.assertFalse(result["capacity_accepted"])

    def test_missing_admission_refuses_without_environment_or_worker_entry(self):
        from unittest import mock
        module = self.load_caller()
        with mock.patch.object(module, "qualify_parent", side_effect=AssertionError("environment tripwire")):
            with self.assertRaises(ValueError):
                module.run_qualification({}, {}, now_tick=1000)

    def test_oversize_witness_refuses_before_file_creation(self):
        from unittest import mock
        module = self.load_caller()
        with mock.patch.object(module.os, "open", side_effect=AssertionError("allocation tripwire")):
            with self.assertRaises(ValueError):
                module.persist_witness(ROOT / "unused", b"x" * 32769)

    def test_write_failure_preserves_first_cause_and_still_flushes_and_closes(self):
        from unittest import mock
        module = self.load_caller()
        write_error = OSError("controlled write")
        flush_error = OSError("controlled flush")
        close_error = OSError("controlled close")
        with mock.patch.object(module.os, "open", return_value=17), \
             mock.patch.object(module.os, "write", side_effect=[2, write_error]), \
             mock.patch.object(module.os, "fsync", side_effect=flush_error) as flush, \
             mock.patch.object(module.os, "close", side_effect=close_error) as close:
            result = module.persist_witness(ROOT / "unused", b"abcd")
        self.assertEqual(result["known_written_bytes"], 2)
        self.assertTrue(result["write_extent_unknown"])
        self.assertFalse(result["complete"])
        self.assertEqual(result["primary"]["phase"], "write")
        self.assertEqual([row["phase"] for row in result["secondary"]], ["fsync", "close"])
        flush.assert_called_once_with(17)
        close.assert_called_once_with(17)

    def test_collision_does_not_write_flush_close_or_adopt(self):
        from unittest import mock
        module = self.load_caller()
        with mock.patch.object(module.os, "open", side_effect=FileExistsError("controlled collision")), \
             mock.patch.object(module.os, "write", side_effect=AssertionError("write tripwire")), \
             mock.patch.object(module.os, "fsync", side_effect=AssertionError("flush tripwire")), \
             mock.patch.object(module.os, "close", side_effect=AssertionError("close tripwire")):
            result = module.persist_witness(ROOT / "unused", b"abcd")
        self.assertFalse(result["complete"])
        self.assertFalse(result["created"])
        self.assertEqual(result["primary"]["phase"], "create_new")

    def test_read_access_time_change_is_not_source_identity_drift(self):
        import hashlib
        from types import SimpleNamespace
        from unittest import mock
        module = self.load_caller()
        raw = b"bounded source"
        before = SimpleNamespace(st_dev=1, st_ino=2, st_size=len(raw), st_mtime_ns=4,
                                 st_atime_ns=5, st_nlink=1, st_mode=0o100600, st_file_attributes=0)
        after = SimpleNamespace(**{**before.__dict__, "st_atime_ns": 6})
        path = mock.Mock()
        path.lstat.return_value = before
        path.is_symlink.return_value = False
        with mock.patch.object(module.os, "open", return_value=17), \
             mock.patch.object(module.os, "fstat", side_effect=[before, after]), \
             mock.patch.object(module.os, "read", side_effect=[raw, b""]), \
             mock.patch.object(module.os, "close") as close:
            module.snapshot(path, len(raw), hashlib.sha256(raw).hexdigest())
        close.assert_called_once_with(17)

    def test_ps7_policy_uses_the_actual_core_registry_root(self):
        import types
        from unittest import mock
        module = self.load_caller()
        closed = []
        def open_key(hive, name, reserved, access):
            if name == r"Software\Policies\Microsoft\PowerShellCore\Transcription":
                return 17
            raise FileNotFoundError()
        registry = types.SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
            KEY_WOW64_64KEY=4, KEY_WOW64_32KEY=8, KEY_READ=16, OpenKey=open_key,
            CloseKey=lambda handle: closed.append(handle))
        with mock.patch.dict(sys.modules, {"winreg": registry}), \
             mock.patch.object(module, "PSHOME", ROOT / "absent-controlled-policy-home"), \
             mock.patch.dict(module.os.environ, {"USERPROFILE": str(ROOT / "absent-controlled-policy-user")}):
            with self.assertRaises(ValueError):
                module.check_powershell_policy()
        self.assertEqual(closed, [17])

    def test_token_close_is_attempted_after_sid_memory_free_failure(self):
        from unittest import mock
        module = self.load_caller()
        first = OSError("controlled SID release")
        second = OSError("controlled token close")
        free = mock.Mock(side_effect=first)
        close = mock.Mock(side_effect=second)
        result = module.release_parent_resources(free, close, 31, 17)
        self.assertEqual(result, [first, second])
        free.assert_called_once_with(31)
        close.assert_called_once_with(17)

    def test_runtime_custody_rejects_a_different_opened_file_identity(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.paths = set()
        custody.handles = []
        custody.close_causes = []
        custody.create = mock.Mock(return_value=17)
        custody.close = mock.Mock(return_value=True)
        custody.opened_identity = mock.Mock(return_value={"volume": 0, "file_index": 0,
            "bytes": 0, "links": 1, "attributes": 0})
        with self.assertRaises(ValueError):
            custody.hold(SOURCE)
        self.assertEqual(custody.handles, [17])
        self.assertEqual(custody.retire(), [])
        custody.close.assert_called_once_with(17)

    def test_runtime_custody_joins_and_closes_its_actual_read_handle(self):
        module = self.load_caller()
        custody = module.RuntimeCustody()
        try:
            custody.hold(SOURCE)
            self.assertEqual(len(custody.handles), 1)
            self.assertIn(SOURCE, custody.paths)
        finally:
            errors = custody.retire()
        self.assertEqual(errors, [])
        self.assertEqual(custody.handles, [])

    def test_current_user_policy_checks_the_resolved_documents_folder(self):
        import io
        import types
        from unittest import mock
        module = self.load_caller()
        documents = ROOT / "controlled-redirected-documents"
        config = documents / "PowerShell/powershell.config.json"
        registry = types.SimpleNamespace(HKEY_LOCAL_MACHINE=1, HKEY_CURRENT_USER=2,
            KEY_WOW64_64KEY=4, KEY_WOW64_32KEY=8, KEY_READ=16,
            OpenKey=mock.Mock(side_effect=FileNotFoundError()), CloseKey=mock.Mock())
        with mock.patch.dict(sys.modules, {"winreg": registry}), \
             mock.patch.object(module, "documents_directory", return_value=documents, create=True), \
             mock.patch.object(module, "PSHOME", ROOT / "absent-controlled-policy-home"), \
             mock.patch.dict(module.os.environ, {"USERPROFILE": str(ROOT / "absent-controlled-policy-user")}), \
             mock.patch.object(Path, "exists", autospec=True, side_effect=lambda path: path == config), \
             mock.patch.object(Path, "stat", return_value=types.SimpleNamespace(st_size=66)), \
             mock.patch.object(Path, "open", return_value=io.BytesIO(b'{"PowerShellPolicies":{"Transcription":{"EnableTranscripting":true}}}')):
            with self.assertRaises(ValueError):
                module.check_powershell_policy()

    def test_returned_capture_survives_witness_persistence_failure(self):
        import base64
        import hashlib
        from types import SimpleNamespace
        from unittest import mock
        module = self.load_caller()
        fake_worker = b'''METADATA_EXECUTABLE = r"C:\\Python314\\python.exe"
class WindowsObservation:
 def tick(self): return 1000
def load_reviewed_job_definitions(raw): return object
def capture_literal(**kw): return {"facts":{"complete":True,"original_pid":17},"private_channel_bytes":[b"original metadata",b""],"private_primary":None,"private_secondary":()}
_QUARANTINED_READERS=[None,None]
'''
        sources = {"capture": fake_worker, "driver": b"d", "guard": b"g", "jobs": b"j"}
        admission = {"schema_version": 1, "scope": module.SCOPE,
            "planning_commit": "44e8cef19d70f555e2f37dd4ea07651bd9b8125f",
            "reviewed_commit": "a" * 40, "entry_approval": 103, "independent_reviews": [101, 102],
            "deadline_tick_ms": 31000, "boot_filetime": "123", "ordinary_sid": module.SID,
            "source_pins": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sources.items()}}
        custody = SimpleNamespace(paths=set(module.SOURCE_PATHS.values()) | {module.PSHOME / "pwsh.exe", Path(sys.executable)},
                                  active=True, retire=mock.Mock(return_value=[]))
        box = {"capture": None, "document_original": None, "attestation": None}
        parent = {"sid": module.SID, "elevated": True, "pid": 19, "boot_filetime": "123"}
        persistence = {"complete": False, "known_written_bytes": 3, "write_extent_unknown": True,
                       "primary": {"phase": "write", "type": "OSError"}}
        with mock.patch.object(module, "qualify_parent", return_value=parent), \
             mock.patch.object(module, "persist_witness", return_value=persistence), \
             mock.patch.object(Path, "exists", return_value=False):
            result = module.run_qualification(admission, sources, now_tick=1000, custody=custody,
                                             enclosing_result=box)
        original = base64.b64decode(result["witness_original_base64"], validate=True)
        self.assertEqual(original, box["document_original"])
        self.assertEqual(json.loads(original)["prefixes_base64"], [base64.b64encode(b"original metadata").decode(), ""])
        self.assertEqual(box["capture"]["facts"]["original_pid"], 17)
        self.assertEqual(result["attestation"]["persistence"], persistence)
        self.assertFalse(result["attestation"]["qualification_accepted"])
        self.assertFalse(result["attestation"]["capacity_accepted"])
        self.assertLessEqual(len(module.bounded_json(result["attestation"], 4096)), 4096)
        self.assertLessEqual(len(module.bounded_json(result, 65536)), 65536)
        custody.retire.assert_called_once_with()

    def metadata_fixture(self, module):
        from types import SimpleNamespace
        events = []
        api = SimpleNamespace(
            v_absent=lambda: events.append("v_namespace") or True,
            ntfs_e=lambda: events.append("ntfs_E") or {"filesystem": "NTFS"},
            file_metadata=lambda path: events.append(path) or {"path": path, "allocation": 4096})
        parent = lambda: {"sid": module.SID, "elevated": True}
        return api, parent, events

    def test_python_metadata_refuses_expired_deadline_before_parent_or_api(self):
        from unittest import mock
        module = self.load_caller()
        tripwire = mock.Mock(side_effect=AssertionError("native entry tripwire"))
        with self.assertRaises(ValueError):
            module.collect_metadata(1000, now=lambda: 1000, api_factory=tripwire, parent_check=tripwire)
        tripwire.assert_not_called()

    def test_python_metadata_executes_only_the_six_fixed_read_operations(self):
        module = self.load_caller()
        api, parent, events = self.metadata_fixture(module)
        result = module.collect_metadata(31000, now=lambda: 1000, api_factory=lambda: api, parent_check=parent)
        self.assertTrue(result["complete"])
        self.assertEqual(events, ["v_namespace", "ntfs_E", r"E:\$MFT", r"E:\$LogFile", r"E:\$Secure", r"E:\VAST-pr9"])
        self.assertEqual(len(result["records"]), 6)
        self.assertFalse(result["capacity_accepted"])
        self.assertEqual(result["storage_effects"], 0)

    def test_python_metadata_preserves_the_actual_late_return_before_stopping(self):
        module = self.load_caller()
        api, parent, events = self.metadata_fixture(module)
        clock = [1000]
        marker = {"path": r"E:\$MFT", "allocation": 8192}
        def late_read(path):
            events.append(path)
            clock[0] = 31000
            return marker
        api.file_metadata = late_read
        result = module.collect_metadata(31000, now=lambda: clock[0], api_factory=lambda: api, parent_check=parent)
        self.assertFalse(result["complete"])
        self.assertTrue(result["deadline_exceeded"])
        self.assertEqual(len(result["records"]), 3)
        self.assertIs(result["records"][-1]["facts"], marker)
        self.assertEqual(events[-1], r"E:\$MFT")

    def test_python_metadata_keeps_completed_read_when_original_handle_close_fails(self):
        from unittest import mock
        module = self.load_caller()
        api = object.__new__(module.MetadataWin32)
        api.create = mock.Mock(return_value=17)
        closing = OSError("controlled close")
        api.close = mock.Mock(side_effect=closing)
        marker = {"allocation": 4096}
        try:
            api.with_handle("controlled", 0x80, 0x02200000, lambda handle: marker)
        except BaseException as error:
            result = module.metadata_failure(error, "controlled_close")
        else:
            self.fail("expected original handle close failure")
        self.assertIs(result["returned_facts"], marker)
        self.assertTrue(result["returned_facts_available"])
        self.assertFalse(result["complete"])
        api.close.assert_called_once_with(17)

    def test_python_metadata_native_abi_extents_are_exact(self):
        import ctypes
        module = self.load_caller()
        self.assertEqual(ctypes.sizeof(module.MetadataBasic), 52)
        self.assertEqual(ctypes.sizeof(module.MetadataStandard), 24)

    def test_python_metadata_clock_failure_preserves_the_completed_read(self):
        module = self.load_caller()
        api, parent, events = self.metadata_fixture(module)
        calls = [0]
        def clock():
            calls[0] += 1
            if calls[0] >= 3:
                raise OSError("controlled observation clock")
            return 1000
        result = module.collect_metadata(31000, now=clock, api_factory=lambda: api, parent_check=parent)
        self.assertFalse(result["complete"])
        self.assertIsNone(result["deadline_exceeded"])
        self.assertEqual(result["records"][0]["facts"], {"absent": True})
        self.assertEqual(events, ["v_namespace"])
        self.assertIsNone(result["finished_tick_ms"])

    def test_python_metadata_repeated_error_identity_does_not_exhaust_causes(self):
        module = self.load_caller()
        same = OSError("controlled repeated cause")
        result = module.metadata_failure(ExceptionGroup("controlled", [same] * 32), "controlled_identity")
        self.assertFalse(result["cause_bound_exceeded"])
        self.assertEqual(sum(row["type"] == "OSError" for row in result["causes"]), 1)

    def test_python_metadata_reads_only_public_source_attributes_and_closes(self):
        module = self.load_caller()
        result = module.MetadataWin32().file_metadata(str(SOURCE))
        self.assertEqual(result["eof"], SOURCE.stat().st_size)
        self.assertGreaterEqual(result["allocation"], result["eof"])
        self.assertFalse(result["directory"])
        self.assertFalse(result["delete_pending"])

    def test_python_metadata_ntfs_and_usn_buffers_and_inactive_code_are_exact(self):
        import ctypes
        from unittest import mock
        module = self.load_caller()
        api = object.__new__(module.MetadataWin32)
        api.create = mock.Mock(return_value=17)
        api.close = mock.Mock(return_value=True)
        def volume(handle, label, label_size, serial, maximum, flags, filesystem, filesystem_size):
            self.assertEqual((label_size, filesystem_size), (261, 64))
            filesystem.value = "NTFS"
            serial._obj.value = 0x12345678
            return True
        def device(handle, code, input_buffer, input_size, output, output_size, count, overlapped):
            self.assertEqual((input_buffer, input_size, overlapped), (None, 0, None))
            if code == 0x00090064:
                self.assertEqual(output_size, 96)
                count._obj.value = 96
                return True
            self.assertEqual((code, output_size), (0x000900f4, 80))
            ctypes.set_last_error(1179)
            return False
        api.volume = volume
        api.device = device
        result = api.ntfs_e()
        self.assertFalse(result["usn_active"])
        self.assertEqual(result["usn_query_error"], 1179)
        self.assertEqual(result["volume_serial"], "12345678")
        api.create.assert_called_once_with(r"\\.\E:", 0x80000000, 3, None, 3, 0, None)
        api.close.assert_called_once_with(17)

    def test_retired_runtime_custody_cannot_reuse_its_old_path_claims(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.retired = True
        custody.handles = []
        custody.paths = {SOURCE}
        custody.create = mock.Mock(side_effect=AssertionError("native reopen tripwire"))
        with self.assertRaises(ValueError):
            custody.hold(SOURCE)
        custody.create.assert_not_called()

    def test_runtime_close_failure_fanout_is_bounded_before_append(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.retired = False
        custody.handles = list(range(1, 34))
        custody.paths = set()
        custody.close_causes = []
        custody.close = mock.Mock(side_effect=OSError("controlled closure failure"))
        result = custody.retire()
        self.assertLessEqual(len(result), 16)
        self.assertEqual(custody.close_failure_count, 33)
        self.assertTrue(custody.close_cause_bound_exceeded)
        self.assertEqual(custody.close.call_count, 33)
        self.assertEqual(custody.handles, [])

    def test_persistence_facts_survive_later_retirement_and_clock_failures(self):
        import hashlib
        from types import SimpleNamespace
        from unittest import mock
        module = self.load_caller()
        for role in ("retirement", "clock"):
            with self.subTest(role=role):
                clock = b"next(ticks)" if role == "clock" else b"1000"
                code = b'''METADATA_EXECUTABLE = r"C:\\Python314\\python.exe"
ticks=iter((1000,))
class WindowsObservation:
 def tick(self): return ''' + clock + b'''
def load_reviewed_job_definitions(raw): return object
def capture_literal(**kw): return {"facts":{"complete":True},"private_channel_bytes":[b"metadata",b""],"private_primary":None,"private_secondary":()}
_QUARANTINED_READERS=[None,None]
'''
                sources = {"capture": code, "driver": b"d", "guard": b"g", "jobs": b"j"}
                admission = {"schema_version": 1, "scope": module.SCOPE, "planning_commit": "44e8cef19d70f555e2f37dd4ea07651bd9b8125f",
                    "reviewed_commit": "a" * 40, "entry_approval": 103, "independent_reviews": [101, 102],
                    "deadline_tick_ms": 31000, "boot_filetime": "123", "ordinary_sid": module.SID,
                    "source_pins": {name: {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()} for name, raw in sources.items()}}
                custody = SimpleNamespace(paths=set(module.SOURCE_PATHS.values()) | {Path(sys.executable)}, active=True,
                    retire=mock.Mock(side_effect=OSError("controlled retirement")) if role == "retirement" else mock.Mock(return_value=[]))
                box = {"capture": None, "document_original": None, "attestation": None}
                persisted = {"complete": True, "known_written_bytes": 317, "fsync_completed": True, "close_completed": True}
                with mock.patch.object(module, "qualify_parent", return_value={"boot_filetime": "123"}), \
                     mock.patch.object(module, "persist_witness", return_value=persisted), \
                     mock.patch.object(Path, "exists", return_value=False):
                    result = module.run_qualification(admission, sources, now_tick=1000, custody=custody, enclosing_result=box)
                self.assertIs(box["attestation"]["persistence"], persisted)
                self.assertFalse(result["attestation"]["qualification_accepted"])
                if role == "clock":
                    self.assertIsNone(result["attestation"]["deadline_exceeded_after_close"])
                    self.assertEqual(result["attestation"]["completion_failure"]["phase"], "completion_clock")
                else:
                    self.assertFalse(result["attestation"]["runtime_close_available"])
                    self.assertEqual(result["attestation"]["completion_failure"]["phase"], "runtime_retirement")

    def test_directory_custody_requests_real_list_access_before_claiming_custody(self):
        from unittest import mock
        module = self.load_caller()
        custody = object.__new__(module.RuntimeCustody)
        custody.retired = False
        custody.paths, custody.handles = set(), []
        before = ROOT.stat()
        custody.create = mock.Mock(return_value=17)
        custody.opened_identity = mock.Mock(return_value={"volume": before.st_dev, "file_index": before.st_ino,
            "attributes": 0x10, "bytes": before.st_size, "links": 1})
        custody.hold(ROOT, directory=True)
        self.assertEqual(custody.create.call_args.args[1:3], (0x20081, 3))

    def test_metadata_terminal_preserves_collection_after_encoding_write_and_flush_faults(self):
        import io
        module = self.load_caller()
        for role in ("encode", "write", "flush", "write_and_flush"):
            with self.subTest(role=role):
                original = {"complete": True, "records": [{"allocation": 8192}], "capacity_accepted": False}
                calls = [0]
                def encode(value, limit):
                    calls[0] += 1
                    if role == "encode" and calls[0] == 1:
                        raise OSError("controlled terminal encoding")
                    return module.bounded_json(value, limit)
                class Output(io.BytesIO):
                    def write(self, raw):
                        if role in ("write", "write_and_flush"):
                            raise OSError("controlled terminal write")
                        return super().write(raw)
                    def flush(self):
                        if role in ("flush", "write_and_flush"):
                            raise OSError("controlled terminal flush")
                        return super().flush()
                stdout, stderr = Output(), io.BytesIO()
                result = module.emit_metadata(31000, collect=lambda deadline: original, encode=encode,
                                              stdout=stdout, stderr=stderr)
                self.assertEqual(result["exit_code"], 1)
                self.assertIs(result["completed_collection"], original)
                self.assertTrue(result["fallback_completed"])
                fallback = json.loads(stderr.getvalue())
                self.assertEqual(fallback["completed_collection"], original)
                self.assertTrue(fallback["collection_returned"])
                expected = {"encode": ["encode"], "write": ["stdout_write"], "flush": ["stdout_flush"],
                            "write_and_flush": ["stdout_write", "stdout_flush"]}[role]
                self.assertEqual([row["phase"] for row in fallback["post_failures"]], expected)

    def test_real_directory_custody_denies_delete_access_with_a_working_baseline(self):
        import ctypes
        module = self.load_caller()
        directory = ROOT / "openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01"
        observer = module.RuntimeCustody()
        def delete_access_probe():
            handle = observer.create(str(directory), 0x10080, 7, None, 3, 0x02200000, None)
            if handle in (None, ctypes.c_void_p(-1).value):
                return False, ctypes.get_last_error()
            try:
                return True, observer.opened_identity(handle)
            finally:
                if not observer.close(handle):
                    raise ctypes.WinError(ctypes.get_last_error())
        baseline, baseline_identity = delete_access_probe()
        self.assertTrue(baseline, baseline_identity)
        observations = []
        for metadata_only in (True, False):
            holder = module.RuntimeCustody()
            native_create = holder.create
            if metadata_only:
                holder.create = lambda path, access, *args: native_create(path, 0x80, *args)
            try:
                holder.hold(directory, directory=True)
                opened, detail = delete_access_probe()
                observations.append({"metadata_only_counterfactual": metadata_only, "delete_access_opened": opened,
                                     "error": detail if not opened else None})
                self.assertEqual(opened, metadata_only)
                if not opened:
                    self.assertEqual(detail, 32)
            finally:
                errors = holder.retire()
            self.assertEqual(errors, [])
        print("CONTROLLED_DIRECTORY_SHARE_ACCESS", json.dumps({"baseline_identity": baseline_identity,
            "observations": observations, "directory_renamed": False, "directory_deleted": False}, separators=(",", ":")))

    def test_admission_identifiers_are_bounded_before_native_parent_entry(self):
        module = self.load_caller()
        base = {"schema_version": 1, "scope": module.SCOPE,
            "planning_commit": "44e8cef19d70f555e2f37dd4ea07651bd9b8125f", "reviewed_commit": "a" * 40,
            "entry_approval": 103, "independent_reviews": [101, 102], "deadline_tick_ms": 31000,
            "boot_filetime": "123", "ordinary_sid": module.SID,
            "source_pins": {name: {"bytes": 1, "sha256": "a" * 64} for name in module.SOURCE_PATHS}}
        for field, bad in (("entry_approval", 1 << 64), ("independent_reviews", [1 << 64, 102])):
            with self.subTest(field=field), self.assertRaises(ValueError):
                module.validate_admission({**base, field: bad}, 1000)



    def test_operator_finalizer_keeps_original_and_distinct_close_failure(self):
        import types
        path=ROOT/"openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_invocation_v1.proposed.ps1"
        self.assertTrue(path.is_file(),"fixed enclosing owner absent")
        raw=path.read_text().split("$Pr9ReadonlyController = @'\n",1)[1].split("\n'@",1)[0]
        ns={"__name__":"pr9_operator_control"}
        exec(compile(raw,"fixed-operator-control","exec"),ns)
        original=object(); first=OSError(); closing=RuntimeError()
        def run(a,b,**kw):
            kw["enclosing_result"]["capture"]=original
            raise first
        owner=types.SimpleNamespace(handles=[1],retired=False)
        def retire():
            owner.handles.pop(); owner.retired=True
            raise closing
        owner.retire=retire
        driver=types.SimpleNamespace(run_qualification=run)
        state=ns["own_qualification"](driver,{}, {},owner,lambda:1)
        self.assertIs(state["box"]["capture"],original)
        self.assertIs(state["errors"][0][1],first)
        self.assertIs(state["errors"][1][1],closing)
        self.assertEqual(state["remaining_runtime_handles"],0)

    def test_runtime_census_missing_or_bad_sources_refuse_before_io_and_import(self):
        from unittest import mock
        m=self.load_caller()
        run=getattr(m,"collect_runtime_census",None)
        self.assertTrue(callable(run),"census absent")
        p={name:{"bytes":1,"sha256":"a"*64} for name in m.SOURCE_PATHS}
        for bad in (None,{},{**p,"driver":{"bytes":True,"sha256":"a"*64}},
                    {**p,"guard":{"bytes":65537,"sha256":"a"*64}},
                    {**p,"capture":{"bytes":1,"sha256":"private"}}):
            with self.subTest(value=bad),mock.patch.object(m.os,"open",side_effect=AssertionError("file")),\
                 mock.patch("builtins.__import__",side_effect=AssertionError("import")):
                with self.assertRaisesRegex(ValueError,"source"):
                    run(bad)

    def test_runtime_census_module_overflow_refuses_before_collection_io_and_import(self):
        import types
        from unittest import mock
        m=self.load_caller()
        run=getattr(m,"collect_runtime_census",None)
        self.assertTrue(callable(run),"census absent")
        class Modules:
            def __len__(self):return 513
            def __iter__(self):raise AssertionError("collect")
        p={name:{"bytes":1,"sha256":"a"*64} for name in m.SOURCE_PATHS}
        with mock.patch.object(m,"sys",types.SimpleNamespace(modules=Modules())),\
             mock.patch.object(m.os,"open",side_effect=AssertionError("file")),\
             mock.patch("builtins.__import__",side_effect=AssertionError("import")):
            with self.assertRaisesRegex(ValueError,"m"):
                run(p)


if __name__ == "__main__":
    unittest.main()
