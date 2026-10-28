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
