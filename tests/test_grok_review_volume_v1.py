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

if __name__ == "__main__":
    unittest.main()
