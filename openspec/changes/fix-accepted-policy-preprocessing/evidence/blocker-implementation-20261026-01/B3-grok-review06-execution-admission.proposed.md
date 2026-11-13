# One review06/Attempt01 external collection proposal

Product605eb02733fe256ad5ef14f358eaa81ee1a0ae44, same change/branch/PR9.
Authoring6464092305; plan7153B/0b3c0b987482f8a7ce2de80a65cfa54c311e9827f3e708495fe4d1f1c218f99e.
This proposal does not admit execution. Require separately accepted actual pref06,
exact frozen main28583/6ef3a1d4060e103ecb8c1ad6e8a026347a8b1a629b606edd4aef9c94443e9dc9,
new .gm2/public namespaces absent, fresh full boundary/auth>900s, source/runtime/
snapshot comparisons, exact independent CODE/capacity/frozen-parameter CLEAR and
recorded delegated AGENT release. No new snapshot/static CLI/override/replay.

Use the exact literal functions below as declarations in persistent Node. No eval
or dynamic code imports. Verify Function.prototype.toString bytes/SHA beforeentry:
collector6574/c153385ae700e8de9b5ec58f85e8222b586c4de117c28c89654219c3dcf20434;
writer2606/c382680b9fd0c371c67211d881095e82c129487a1347104adf4a1fdb46837245.
They differ from archived05 only by namespace/name replacement, checked exactly.
Current27collector controls, two writer identity/prehash controls and fresh-path
CreateNew/write-sync-close mock pass. Prior nine writer composed controls remain
retained at unchanged behavior in failed05 archive; no actual I/O in pure controls.

One exec only, initialyield10000, actual command ASCII<=4096; store complete returned
object. If it yields a session, at most15 polls,45000ms each, always that original
session. Never resend command. Preserve each complete result and requested wait,
kind and exact session. Exit_code presence ends collection, even on failure.
Unknown completion grants no acceptance and still preserves partial original.
Native output aggregate<=16384B; at most16 returns, each metadata<=1024B and all
outputs Base64lossless; final external record<=65536B beforeCreateNew. No re-escaping
or extracting only a selected JSON result. Bind fixed sourcecommit/prompt/admission,
frozen main name/bytes/SHA, prep05SHA and actual accepted pref06SHA.

The exact writer prehashes before open, captures distinct error identities and
attempts fsync/close independently after write failure. Return complete persistence
facts/cause summaries only afterclose, preserving original raw tool text in fixed
public external-record path. The writer does not accept a model verdict.
Private .gm2 channels stay sealed/outsideGit/ZIP; model response controls, full
ownership/retirement/EOF/I/O/postcomparison and independent findings disposition
are still required. Use original integer FILETIME or decimal strings.

The preflight size/SHA below are now fixed to the actual06 receipt; only the
fresh typedguard remains variable. Fixed-pref pin/hash syntax and4KiB geometry must be checked before
entry; all other template bytes and source must remain exact.

```powershell
$ErrorActionPreference='Stop'
$taskSourcePath='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/grok-model-phase-command-review06.original.ps1'
$taskSourceStream=[IO.File]::Open($taskSourcePath,'Open','Read','Read')
try{
 $taskSourceRaw=[byte[]]::new(28583);$taskOffset=0
 while($taskOffset -lt $taskSourceRaw.Length){$taskN=$taskSourceStream.Read($taskSourceRaw,$taskOffset,$taskSourceRaw.Length-$taskOffset);if($taskN -le 0){throw 'frozen source shrank'};$taskOffset+=$taskN}
 if($taskSourceStream.ReadByte() -ne -1 -or [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskSourceRaw)).ToLowerInvariant() -cne '6ef3a1d4060e103ecb8c1ad6e8a026347a8b1a629b606edd4aef9c94443e9dc9'){throw 'frozen source differs'}
 & ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskSourceRaw))) -Mode review06 -Attempt 01 -PreparationBytes 14890 -PreparationSha ae66bd90dc18d005d54b88ff8089a54b2d02d14ab5ff9a5ef8a6296cc5be619d -PreflightBytes 2209 -PreflightSha 088313e135ec6b4b8b7edfbad6fef0321541cbcdd6257e31d392e40a870621ce -LinuxGuardJson '__FRESH_TYPED_GUARD__'
}finally{$taskSourceStream.Dispose()}
```

```javascript
function buildPr9Review06ExternalRecord(invocation, records, fixed) {
  const fail = code => { throw new Error("review06_external_" + code); };
  const own = (value, allowed, code) => {
    if (!value || Object.getPrototypeOf(value) !== Object.prototype) fail(code);
    const copy = {};
    for (const key of Reflect.ownKeys(value)) {
      const descriptor = Object.getOwnPropertyDescriptor(value, key);
      if (typeof key !== "string" || !allowed.has(key) || !descriptor ||
          !("value" in descriptor) || !descriptor.enumerable) fail(code);
      copy[key] = descriptor.value;
    }
    return copy;
  };
  const unicode = (text, maximum) => {
    if (typeof text !== "string" || text.length > maximum) fail("string_extent");
    for (let i = 0; i < text.length; i++) {
      const n = text.charCodeAt(i);
      if (n >= 0xd800 && n <= 0xdbff) {
        const next = text.charCodeAt(++i);
        if (!(next >= 0xdc00 && next <= 0xdfff)) fail("unicode");
      } else if (n >= 0xdc00 && n <= 0xdfff) fail("unicode");
    }
    const encoded = Buffer.from(text, "utf8");
    if (encoded.length > maximum) fail("utf8_extent");
    return encoded;
  };
  const bytes = unicode(invocation, 4096);
  if (bytes.length > 4096 || !/^[\x20-\x7e\r\n\t]*$/.test(invocation)) fail("invocation");
  if (!Array.isArray(records) || Object.getPrototypeOf(records) !== Array.prototype) fail("return_count");
  const lengthDescriptor = Object.getOwnPropertyDescriptor(records, "length");
  if (!lengthDescriptor || !("value" in lengthDescriptor)) fail("return_count");
  const count = lengthDescriptor.value;
  if (!Number.isSafeInteger(count) || count < 1 || count > 16) fail("return_count");
  const recordDescriptors = Object.getOwnPropertyDescriptors(records);
  if (Reflect.ownKeys(recordDescriptors).length !== count + 1) fail("return_count");
  const fixedSnapshot = own(fixed, new Set(["source_commit", "prompt_sha256", "admission_comment",
    "frozen_source", "preparation_sha256", "preflight_sha256"]), "fixed_shape");
  for (const key of ["preparation_sha256", "preflight_sha256"])
    if (key in fixedSnapshot && (typeof fixedSnapshot[key] !== "string" ||
        !/^[a-f0-9]{64}$/.test(fixedSnapshot[key]))) fail("fixed_hash");
  if ("admission_comment" in fixedSnapshot &&
      (!Number.isSafeInteger(fixedSnapshot.admission_comment) || fixedSnapshot.admission_comment < 1))
    fail("fixed_admission");
  if ("frozen_source" in fixedSnapshot) {
    const source = own(fixedSnapshot.frozen_source, new Set(["name", "bytes", "sha256"]), "fixed_source");
    if (source.name !== "grok-model-phase-command-review06.original.ps1" ||
        !Number.isSafeInteger(source.bytes) || source.bytes < 1 || source.bytes > 28672 ||
        typeof source.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(source.sha256))
      fail("fixed_source");
    fixedSnapshot.frozen_source = source;
  }
  if (fixedSnapshot.source_commit !== "605eb02733fe256ad5ef14f358eaa81ee1a0ae44" ||
      fixedSnapshot.prompt_sha256 !== "e59bd457dca8028aaf1e25fdab087495f5351a83a9a2fcc134e82fecc9780aa7")
    fail("source_binding");
  const fixedJson = JSON.stringify(fixedSnapshot);
  if (Buffer.byteLength(fixedJson, "utf8") > 4096) fail("fixed_extent");
  const allowed = new Set(["chunk_id", "exit_code", "original_token_count", "session_id", "wall_time_seconds", "output"]);
  const encoded = [];
  let outputBytes = 0, base64Bytes = 0, metadataBytes = 0, session = null, ended = false;
  for (let i = 0; i < count; i++) {
    const descriptor = recordDescriptors[String(i)];
    if (!descriptor || !("value" in descriptor) || !descriptor.enumerable) fail("row");
    const row = own(descriptor.value, new Set(["kind", "yield_time_ms",
      "requested_session_id", "actual_return"]), "row");
    if (row.kind !== (i === 0 ? "exec" : "poll") || ended) fail("sequence");
    if (!Number.isSafeInteger(row.yield_time_ms) || row.yield_time_ms < 0 ||
        row.yield_time_ms > (i === 0 ? 10000 : 45000)) fail("poll_wait");
    if (i && (!Number.isSafeInteger(session) || row.requested_session_id !== session)) fail("session");
    const result = own(row.actual_return, allowed, "return_shape");
    const meta = {};
    for (const [key, descriptor] of Object.entries(Object.getOwnPropertyDescriptors(result))) {
      if (!allowed.has(key) || !("value" in descriptor) || !descriptor.enumerable) fail("return_key");
      if (key !== "output") meta[key] = descriptor.value;
    }
    if (typeof result.output !== "string") fail("output_type");
    if (typeof meta.wall_time_seconds !== "number" || !Number.isFinite(meta.wall_time_seconds) ||
        meta.wall_time_seconds < 0 || meta.wall_time_seconds > 700) fail("duration");
    for (const key of ["session_id", "exit_code", "original_token_count"])
      if (key in meta && (!Number.isSafeInteger(meta[key]) ||
          (key !== "exit_code" && meta[key] < 0))) fail("metadata_number");
    if ("chunk_id" in meta && (typeof meta.chunk_id !== "string" ||
        unicode(meta.chunk_id, 256).length > 256)) fail("chunk_id");
    const hasSession = "session_id" in meta, hasExit = "exit_code" in meta;
    if (hasSession === hasExit) fail("completion_shape");
    if (hasSession) {
      if (i && meta.session_id !== session) fail("session");
      session = meta.session_id;
    } else ended = true;
    const metaRaw = JSON.stringify(meta);
    const metaCount = Buffer.byteLength(metaRaw, "utf8");
    if (metaCount > 1024) fail("metadata_extent");
    const output = unicode(result.output, 16384 - outputBytes);
    outputBytes += output.length;
    if (outputBytes > 16384) fail("output_extent");
    const base64 = output.toString("base64");
    base64Bytes += base64.length;
    metadataBytes += metaCount;
    encoded.push({
      kind: row.kind, yield_time_ms: row.yield_time_ms,
      requested_session_id: i ? row.requested_session_id : null,
      actual_return_metadata: meta, output_codec: "base64-utf8",
      output_utf8_bytes: output.length, output_base64: base64
    });
  }
  if (base64Bytes > 32768 || metadataBytes > 16384) fail("aggregate_extent");
  const value = {
    scope: "configured_review06_original_external_tool_returns_only",
    fixed: fixedSnapshot, invocation, returns: encoded,
    external_collection_ended: ended, completion_unknown: !ended,
    returned_output_utf8_bytes: outputBytes, encoded_output_bytes: base64Bytes,
    model_or_product_accepted: false
  };
  const raw = Buffer.from(JSON.stringify(value) + "\n", "utf8");
  if (raw.length > 65536) fail("serialized_extent");
  return { value, raw };
}
```

```javascript
async function persistPr9Review06ExternalRecord(fs, crypto, invocation, records, fixed) {
  const built = buildPr9Review06ExternalRecord(invocation, records, fixed);
  if (built.raw.length > 65536) throw new Error("review06_external_prewrite_extent");
  const recordSha256 = crypto.createHash("sha256").update(built.raw).digest("hex");
  const path = "C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/grok-model-review06-01-outer-tool.original.json";
  const facts = { attempted: false, created: false, written_prefix_bytes: 0,
    write_extent_unknown: false, fsync_attempted: false, fsync_completed: false,
    close_attempted: false, close_completed: false, complete: false };
  const causes = [];
  const seenErrors = new Set();
  const note = (stage, error) => {
    if (seenErrors.has(error)) return;
    seenErrors.add(error);
    let code = null;
    try {
    if (error && (typeof error === "object" || typeof error === "function")) {
      const descriptor = Object.getOwnPropertyDescriptor(error, "code");
      if (descriptor && "value" in descriptor && typeof descriptor.value === "string" &&
          /^[A-Z0-9_]{1,32}$/.test(descriptor.value)) code = descriptor.value;
    }
    } catch { code = null; }
    causes.push({ stage, code });
  };
  let handle = null;
  facts.attempted = true;
  try {
    handle = await fs.open(path, "wx");
    facts.created = true;
  } catch (error) { note("open", error); }
  if (handle) {
    try {
      facts.write_extent_unknown = true;
      await handle.writeFile(built.raw);
      facts.written_prefix_bytes = built.raw.length;
      facts.write_extent_unknown = false;
    } catch (error) { note("write", error); }
    facts.fsync_attempted = true;
    try { await handle.sync(); facts.fsync_completed = true; }
    catch (error) { note("fsync", error); }
    facts.close_attempted = true;
    try { await handle.close(); facts.close_completed = true; }
    catch (error) { note("close", error); }
  }
  facts.complete = facts.created && facts.fsync_completed && facts.close_completed &&
    !facts.write_extent_unknown && causes.length === 0;
  return { scope: "review06_external_record_local_persistence_only",
    record_bytes: built.raw.length,
    record_sha256: recordSha256,
    facts, primary_cause: causes[0] || null, secondary_causes: causes.slice(1),
    external_collection_ended: built.value.external_collection_ended,
    completion_unknown: built.value.completion_unknown, model_or_product_accepted: false };
}
```


## Output-capture procedure closure

Set max_output_tokens=24000 explicitly on the one exec AND EVERY poll, preserving
the reviewed05 parameter. Retain the exact original return even on reported
truncation; it prevents acceptance. No truncated output is treated as a complete
receipt/model response. All count/aggregate/64KiB writer limits remain unchanged.


## Actual preflight dependency for final review

Pref06/01 under6464736781 exited0/3.2948717s, no Grok/newroot. Receipt2209B/
088313e135ec6b4b8b7edfbad6fef0321541cbcdd6257e31d392e40a870621ce;
outcome5147B/ea866b482c3e65165d7ca9a1b0270a7e8a15e7c0c422b6ec6de4b3cc174feb87.
All six route checks/postcomparison true. Independent actualoutcome approval and
fresh model admission/guard/auth/runtime function hashes remain required.
