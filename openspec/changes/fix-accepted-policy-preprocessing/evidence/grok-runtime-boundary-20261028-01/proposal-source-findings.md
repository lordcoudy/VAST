# Bounded configured-review environment: source findings and proposed scope

This is prospective planning under PR9comment6466404177 and authoring approval6466598397.
Same OpenSpec change fix-accepted-policy-preprocessing, C:worktree/branch/PR9.
Whole task1.5 and all later milestone gates remain OPEN. No support setup/model
retry is authorized by this document. D27/Native57 and all227images stay parked.

The failed review06 stdout/stderr are private and sealed. Independent public
joins preserve CLIexit1/capturefalse/nullobservation and resource-retirement facts.
The generic LoadSession error masks all load failures, so it does not identify
an absent session, missing SQLite, or the exact earliest installed-runtime fault.

Pinned xai-org/grok-build2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8 establishes:

- Cold resume requires a durable stamp through summary.json.lock read/write/create,
  sibling temporary and replacement: headless.rs506-537, session_setup1238-1283,
  agent_ops5133-5168 and session/storage/summary_write.rs324-358. The .g5 deny-write
  ACLs and held ShareRead custody cannot satisfy that path.
- Fresh headless also invokes real persistence; chat-kind no-op is hard-off in
  public release cli.rs857-859 and mvp_agent/mod.rs296-327. No supported ephemeral
  CLI bypass was established. JSONL is the source of truth; SQLite is search.
- Normal session writes include summary/locks/temporaries, chat_history.jsonl,
  updates.jsonl, events, context/system/tool/usage/signals and conditional traces
  and compaction. Four turns/captured channels do not cap aggregate internal bytes.
- The110539B packet can be offloaded at bytes/4>25000; supported --verbatim bypasses
  that turn-path offload. This was prospective, not the actual06 startup cause.

Primary source links:

- [LoadSession](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-pager/src/headless.rs#L506)
- [Required stamp](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/session/storage/summary_write.rs#L324)
- [Prompt offload](https://github.com/xai-org/grok-build/blob/2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8/crates/codegen/xai-grok-shell/src/session/acp_session_impl/prompt_offload.rs#L459)

Propose one NEW128MiB classic fixed Windows VHD on physical E:, literal path
E:/VAST-pr9/grok-bounded-review-20261028-07.vhd, and explicit V: only if unassigned
in ordinary and elevated views. Keep the existing project S96/E16 remedies separate
and unactivated. New disk identities must be proved from the new VHD, sole new RAW
CIM disk and reverse backing-file match before initialization/format; never guess
or act on another RAW/PhysicalDrive. Bind partition/NTFS volumeGUID/serial/size/ACLs.
Copy unchanged auth/config/cache under readonly custody; permit only session
bookkeeping inside the fixed filesystem, with mutable-output custody and final
sealing/retention. Keep .g5 and all original personal files unchanged. The disk is
a hard ceiling, not proof of fit; exhaustion/unknown backend/root drift holds all
dependents, with no resize/retry/fallback or automatic cleanup.

Current capability probe sees installed Hyper-V/Storage cmdlets, but current token
is not elevated. Cmdlet availability is not authority. A concrete reviewed
privileged setup and complete finite setup peak precede any request for OS user
action. No storage operation, privilege escalation or model request has occurred.

Prospective logical file134218240B (128MiB+512Bfooter) rounds to134221824B on4KiB E:;
NEW129MiB leaves1044480B for host metadata, still unvalidated as a setup peak.
NEW16MiB authoring row is approved: planning4+source1+ordinary2+ZIP/Git8+tails1.
Cumulative2455MiB=2574254080B/C73.3564453125GiB, with every prior charge retained.
The four-artifact amendment, exact planning commit/reviews/CI/delegated approval
must precede host implementation. Setup/profile/model entries require separate
source/physical/privilege/deadline/retirement admissions; final configured Grok and
all existing application acceptance gates remain mandatory.

## Historical archive06 external persistence provenance

Both evidence archives have already been independently read back. Their outside
archive-actual records predate their own returned writer completion facts; retain
those original tool returns below as a separate funded planning input. The fixed
writer body is also preserved for review. This does not repeat any disk/archive
operation or upgrade failed model06 into acceptance.

```json
{
  "scope": "historical_archive06_external_writer_original_returns",
  "preflight": {
    "content": [
      {
        "type": "text",
        "text": "{\n  scope: 'archive_external_original_persistence_only',\n  bundle: 'preflight06',\n  bytes: 10234,\n  sha256: 'c5e9dc56a4f853832bc7f7da5754a5f11b3a9af86c6321c25a0fc560eee4a88a',\n  facts: {\n    created: true,\n    write_completed: true,\n    fsync_attempted: true,\n    fsync_completed: true,\n    close_attempted: true,\n    close_completed: true\n  },\n  causes: [],\n  product_acceptance: false\n}"
      }
    ],
    "isError": false
  },
  "failed_model": {
    "content": [
      {
        "type": "text",
        "text": "{\n  scope: 'archive_external_original_persistence_only',\n  bundle: 'review06',\n  bytes: 19523,\n  sha256: '3fcb8bcc04d39db1176e2053ac86e5144705070ce06e121a74258805323d195f',\n  facts: {\n    created: true,\n    write_completed: true,\n    fsync_attempted: true,\n    fsync_completed: true,\n    close_attempted: true,\n    close_completed: true\n  },\n  causes: [],\n  product_acceptance: false\n}"
      }
    ],
    "isError": false
  },
  "note": "These are the already-returned post-close Node tool results, retained verbatim as tool content; no archival operation is rerun and no later durability is self-asserted inside the earlier archive-actual records."
}
```

```javascript
async function persistArchiveExternal06(data,bundle){
 if(!['preflight06','review06'].includes(bundle))throw Error('fixed bundle');
 const record={...data,original_tool_returns:data.original_tool_returns.map(r=>{const{output,...metadata}=r;return{actual_return_metadata:metadata,output_codec:'base64-utf8',output_utf8_bytes:Buffer.byteLength(output),output_base64:Buffer.from(output).toString('base64')}})};
 const raw=Buffer.from(JSON.stringify(record,null,2)+'\n');const maximum=bundle==='preflight06'?32768:65536;
 if(raw.length>maximum)throw Error('archive outer prewrite cap');
 const sha=pscrypto.createHash('sha256').update(raw).digest('hex');
 let h=null,causes=[],facts={created:false,write_completed:false,fsync_attempted:false,fsync_completed:false,close_attempted:false,close_completed:false};
 try{h=await psfs.open(pb+'grok-model-'+bundle+'-01-archive-actual.original.json','wx');facts.created=true;await h.writeFile(raw);facts.write_completed=true}catch(e){causes.push({stage:'create_or_write',code:e?.code??null})}
 finally{if(h){facts.fsync_attempted=true;try{await h.sync();facts.fsync_completed=true}catch(e){causes.push({stage:'fsync',code:e?.code??null})}facts.close_attempted=true;try{await h.close();facts.close_completed=true}catch(e){causes.push({stage:'close',code:e?.code??null})}}}
 return{scope:'archive_external_original_persistence_only',bundle,bytes:raw.length,sha256:sha,facts,causes,product_acceptance:false};
}
```


## Read-only runtime bridge checkpoint, 2026-10-28

This is ancillary support evidence for task1.5, not completion of that task or of the application repair. The OpenSpec change remains fix-accepted-policy-preprocessing, schema spec-driven,24/46 checked tasks. Keep this C: worktree, codex/fix-accepted-policy-preprocessing branch and DraftPR9. D27/Native57 remains parked; no protected image was deleted/offloaded. FreshQ1/Q4/fullcampaign remain separate after repair acceptance.

Published baseline before this checkpoint is33d9d20f05df19b11ab15ef42458c1509f472452. Its CI40704026044/run348 has an inherited CPU crash-recovery ERROR, not an accepted flaky rerun: test_killed_production_coordinator_live_broker_resumes_without_rerun can kill between physicalio stage.complete/stage.intent cleanup after final publication. Six relevant source/test blobs match44e8->33. Deterministic cleanup-cut RED, provenance-preserving recovery/terminal cleanup, single-spawn/foreign-refusal controls and independent review remain required. No application repair or CI redesign is included in this bridge.

The read-only Python transport keeps the original reviewed Windows Job classes and ownership/retirement body. Fixed modes are metadata_qualification, runtime_census and three transport controls; no general command/Grok mode exists. Metadata uses actual elevated sameSID, six literal read operations and8KiB channels. Ordinary runtime census uses one active process/512MiB Job,64KiB channels, one inherited90s deadline including retirement,256KiB complete public original and1MiB outer wire. Root-controller retirement and original Job retirement remain distinct. Process exit never proves an unrelated backend retired.

Retained ordinary census attempts:
-01: admission6478397304, originals6478524480. Original root69580/134376888538163393 and Jobchild14248/134376888539614558 exited1 unforced with known full closure. ValueError returned no census. CONSUMED/HOLD.
-02: separately reviewed diagnostic, admission6479024245, originals6479196653. Root30032/134376906594423086 and Jobchild17140/134376906595579008 exited1 unforced/active0/all closure known. Exact source-location record identified read_bound894's opened identity join before source contents, ruling out a claimed JSON-size diagnosis for this attempt. CONSUMED/HOLD.
-03: source-corrected admission6479528814, originals6479689053. Root2724/134376920513817962 and Jobchild7256/134376920515043014 exited0 unforced; Jobcomplete true/active0/verified512MiB+active1+KillOnClose, bothEOF/settled/all original handles closed. Runtime custody all6 facts available/zero remaining/zero close failures/no overflow. Exact original81963B/SHA90e62508e01453e26844ff0b28f4dd48ca74ec864af039b48f5aab0d6416e51f, stdout59212B/SHAebbb646efe5ec44f6a813055e1feb0b9984b82f1f2b10cf69890bca1d73a5d59, stderr known empty. Snapshot237 files/168 Python modules/38 native modules/20858212 file bytes; all file link counts1. Actual ordinarySID matched, boot before/after134349129705086037 and external HEAD before/after33 matched.

The actual source fix is supported by pinned CPython3.14.7: Windows path stat/lstat copies birthtime into deprecated ctime while fstat retains ChangeTime separately. The census and gated operator now require st_birthtime_ns for the creation slot; all seven identity components and full before/after path/hash/extent/closure checks remain. Missing birthtime refuses. Producer and consumer label the slot birthtime_ns. Primary references:
https://github.com/python/cpython/blob/v3.14.7/Modules/posixmodule.c#L2146
https://github.com/python/cpython/blob/v3.14.7/Python/fileutils.c#L1027

Meaningful source controls are retained in PR6478174822,6478939120,6479439203: seven intended failures across six RAM methods before the loader/finalizer/emitter fixes; two diagnostic-helper RED failures before GREEN; creation-join1RED thenGREEN and strict missingbirth/operator2RED then2GREEN. The latest combined20 source controls pass:19 pure/in-memory cases and one expired-deadline PowerShell control, which reports no controller start. They are source/fixture evidence, not application validation. The syntax-only retained bad launcher had13 parser errors; corrected source had0. The unexecuted corrupted forms remain losslessly in6477260224. No source-level correction is labelled a human review or configured-Grok result.

Runtime contract grok_bounded_source_contract_v1.proposed.json is schema2,43055B/SHA0010ebd2646e45e21911d57a6170154ae211ba9c39610726d564c8cbb134cad4. It losslessly embeds the entire historical partial PowerShell document35314B/SHAe333092ce136159b486452d446b6b166df8b4ed08366d1bffe3755fa23a445f7 plus byte-exact actual03 census. All authority flags are false; loaded-memory identity remains unproved. Native Windows paths are explicitly trusted, not hashed; version[10,0,26100,2] means major10/minor0/build26100/platformID2, not a patch revision. The census records actual Python3.14.7/-I-B-S,cp1251+UTF8, exact sys.path/prefix/UTF8mode, four configuration absences and optionalZIP absence. It qualifies only its defined retained snapshot. A pure check through the actual consumer parser passes; the initial standalone data-check namespace omission is retained, not mislabelled a production defect.

Current authenticated support sources:
- capture49678B/SHAfa7ffe33b2a6d460a01074cf4e3a1a67f02cd8e6be0700adac9fa2756ccc38ca
- driver65441B/SHA11282e873d7f580a6165c6c7a561ed75e88db42b2e98de89b9866418b01348ed
- guard13365B/SHA5dee93c6b04c37144fad47aafb72153de90f9bf5e88dc5e40e7119a9c8ca963d
- unchanged original Job definitions7981B/SHA54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3
- gated invocation30754B/SHAaa2a4bc2be322dfe37f4e96e95a692ac9792a70c7dcf327fdb17df311c6ecaa4
- new operator tests20224B/SHA531aa17935a2e8cd508678e8bdf840ce9a68d04ec1ac458c5a5f7214bf697c75

The16MiB authoring row retains12 named source/test slots,64KiB per file,512KiB aggregate/1MiB source+Git,16 bounded ordinary records and one4MiB archive. The unused phase.ps1 slot was replaced by tests/test_grok_readonly_operator_v1.py with independent capacity review/delegated approval6477601679/6477764380; later source controls remain within the unchanged global ceilings. Current actual source aggregate358656B after scoped attributes and enclosing-entry corrections. Three unused slots cannot all assume independent64KiB maxima. Preserve every prior retained liability; do not claim cleanup credit.

Before an elevated read-only metadata query: finish independent cold-data review of03/contract, freeze the complete externally authenticated operator command with its actual admission/source/runtime/commit pins, publish/check the source checkpoint, obtain exact independent entry reviews and fresh separate admission, and only then request necessary sameSID Administrator host action. The user-owned ambient shell is not an owned retired process. All protected E calls, including floor sampling, must stay in the original bounded Python child. Preserve complete actual operator output and independently cold-verify witness/frame/source guard/process/Job closure. No mutable VHD/setup record slot is silently repurposed.

Still OPEN: whole1.5 image/cache/VHD/compiler/output/metadata/failure peak; compiler and reader admissions; actual receipt-backed Docker CPU/GPU probes; atomic lifecycle publication and inherited crash-recovery fix; all four runtimes A/B/import/refreeze/parity480/32/tensor/pins; genuine3840 then3968/promoted126016/underfill29/sealed20/42; nine physical integrations/regressions/scenario conformance; disclosed missing dedicated conformanceCI; samePR sync/archive/final independent+configuredGrok/latestCI/delegated approval/merge. No dedicated conformanceCI is redesigned here.

Windows exterior-growth qualification remains incomplete: E geometry and related metadata, native SetupAPI logging/backup bounds, full circular diagnostic terms and retained failures must be reconciled before any VHD allocation. The earlier image-only CDB invocation enabled gallery/update facilities; its complete command/result is retained in source-control-recipes, with gallery/cache/network/descendant effects UNKNOWN. Do not relaunch CDB or claim zero effects. No new VHD, elevation, protected E query, Grok model request, application worker or consumer has run as part of this checkpoint. The existing native stores/providers/227 images and all old profiles/failures remain preserved.


### Proposed ADMINHOST first-parse wrapper, not execution authority

This template is DATA for review only. Replace the single __ADMISSION_BASE64__ with the canonical bounded final ten-field admission after the actual source commit, independent reviews/checks and separate entry approval are issued. No placeholder is executed. Source and contract pins are literal. The original read handle authenticates complete source bytes before PowerShell parsing and stays held through controller retirement; a final bounded source-guard-close record preserves distinct failures. Python and its original Job remain separate from the user-owned ambient elevated shell. The complete composed command, including final DATA, requires exact review before OS user action.

```powershell
$ErrorActionPreference='Stop'
$pr9OriginalDeadline=[Environment]::TickCount64+180000L
$pr9Path='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST\openspec\changes\fix-accepted-policy-preprocessing\evidence\grok-runtime-boundary-20261028-01\grok_bounded_model_invocation_v1.proposed.ps1'
$pr9Guard=$null;$pr9Authenticated=$false;$pr9GuardClosed=$null
$pr9Primary=$null;$pr9CloseError=$null
try {
    if([Environment]::TickCount64 -ge $pr9OriginalDeadline-15000L){throw 'original bootstrap deadline'}
    if(([IO.File]::GetAttributes($pr9Path) -band [IO.FileAttributes]::ReparsePoint) -ne 0){throw 'source reparse refusal'}
    $pr9Guard=[IO.File]::Open($pr9Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    if($pr9Guard.Length -ne 30754){throw 'source extent refusal'}
    $pr9Raw=[byte[]]::new(30754)
    $pr9Read=0
    while($pr9Read -lt $pr9Raw.Length){
        if([Environment]::TickCount64 -ge $pr9OriginalDeadline-15000L){throw 'original source-read deadline'}
        $n=$pr9Guard.Read($pr9Raw,$pr9Read,$pr9Raw.Length-$pr9Read)
        if($n -le 0){throw 'source short read'}
        $pr9Read+=$n
    }
    if($pr9Guard.ReadByte() -ne -1){throw 'source grew'}
    if([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($pr9Raw)).ToLowerInvariant() -cne 'aa2a4bc2be322dfe37f4e96e95a692ac9792a70c7dcf327fdb17df311c6ecaa4'){throw 'source hash refusal'}
    $pr9Authenticated=$true
    $pr9Text=[Text.UTF8Encoding]::new($false,$true).GetString($pr9Raw)
    $pr9Trailer='Invoke-Pr9ReadonlyMetadata -AdmissionBase64 ''__ADMISSION_BASE64__'' -InvocationBytes 30754 -InvocationSha256 ''aa2a4bc2be322dfe37f4e96e95a692ac9792a70c7dcf327fdb17df311c6ecaa4'' -ContractBytes 43055 -ContractSha256 ''0010ebd2646e45e21911d57a6170154ae211ba9c39610726d564c8cbb134cad4'''
    if([Environment]::TickCount64 -ge $pr9OriginalDeadline-15000L){throw 'original pre-parse deadline'}
    $pr9Trailer+=' -OriginalDeadlineTickMs '+$pr9OriginalDeadline.ToString([Globalization.CultureInfo]::InvariantCulture)
    & ([scriptblock]::Create($pr9Text+([char]10)+$pr9Trailer))
} catch { $pr9Primary=$_.Exception }
finally {
    if($pr9Guard){
        try {$pr9Guard.Dispose();$pr9GuardClosed=$true}
        catch {$pr9GuardClosed=$false;$pr9CloseError=$_.Exception}
    }
}
function Get-Pr9OperatorType([Exception]$ErrorValue){
    if($null -eq $ErrorValue){return $null}
    $name=$ErrorValue.GetType().Name
    if($name -notmatch '^[A-Za-z0-9_]{1,128}$'){return 'unavailable'}
    return $name
}
$pr9BootstrapReceipt=([ordered]@{
    scope='actual_operator_source_bootstrap_close_v1'
    source_bytes=30754
    source_sha256='aa2a4bc2be322dfe37f4e96e95a692ac9792a70c7dcf327fdb17df311c6ecaa4'
    authenticated=$pr9Authenticated
    original_deadline_tick_ms=$pr9OriginalDeadline
    finished_tick_ms=[Environment]::TickCount64
    deadline_exceeded=([Environment]::TickCount64 -ge $pr9OriginalDeadline)
    original_guard_close_completed=$pr9GuardClosed
    initiating_type=(Get-Pr9OperatorType $pr9Primary)
    distinct_close_type=$(if($pr9CloseError -and -not [object]::ReferenceEquals($pr9Primary,$pr9CloseError)){Get-Pr9OperatorType $pr9CloseError}else{$null})
    qualification_accepted=$false
    capacity_accepted=$false
    application_authority=$false
}|ConvertTo-Json -Depth 5 -Compress)
if([Text.Encoding]::UTF8.GetByteCount($pr9BootstrapReceipt) -gt 4094){throw 'bootstrap receipt bound'}
[Console]::Out.WriteLine($pr9BootstrapReceipt)
```

Enclosing-entry correction: stamp the one180s deadline before bootstrap source I/O and forward it unchanged through mandatory OriginalDeadlineTickMs; no clock renewal. The expireddeadline1 refusal control reaches a bounded not-started receipt; the operator and child are not launched. Python normal4095B+LF and bothPowerShellreceipts4094B+CRLF each fit4KiB. Price COMPLETE console separately: Pythonfullframe64KiB + two possible4KiBPythonfailure records + controller4KiB + bootstrap4KiB + defaultdescriptor<=1KiB =81KiB, conservatively96KiB under the existing1MiBouter-retention allowance. Typed infra/sink failure remainsHOLD; do not call the whole console64KiB. The normal-boundary control requires a full fallback when its finalLF would cross4KiB. Allupdatedcontrols/entryDATA require exactreview before use; ordinarycensus03sourcepins remainunchanged.
