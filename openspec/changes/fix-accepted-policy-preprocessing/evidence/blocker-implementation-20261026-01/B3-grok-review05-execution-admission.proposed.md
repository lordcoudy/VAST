# Prospective exact review05 external collector and admission

Definitions only; no model or filesystem action on evaluation. The literal function below validates and losslessly encodes every actual exec/poll return before any64KiB public-record creation. It accepts at most one exec and15polls, preserves tool metadata, refuses continuation/foreign sessions/extent or malformed records, and never grants model/product acceptance. At source use, compare Function.prototype.toString bytes/SHA against this exact fence, then apply existing CreateNew/fsync/close writer. Full review05 source/collector/frozen/admission and fresh prerequisites still precede execution.

```javascript
function buildPr9Review05ExternalRecord(invocation, records, fixed) {
  const fail = code => { throw new Error("review05_external_" + code); };
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
    if (source.name !== "grok-model-phase-command-review05.original.ps1" ||
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
    scope: "configured_review05_original_external_tool_returns_only",
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

## Once-only external persistence and polling integration

The fixed caller makes ONE exec start (yield<=10000ms) for the reviewed frozen review05 command, retains its exact actualreturn, and uses only its returned original tool session ID for at most15write_stdin polls (emptychars,yield<=45000ms). Each return is retained before deciding whether another poll is needed; stop onexit,foreign/malformedsession,transporterror or16returns. No new command/continuation/fallback. Exhaustion/transportfailure retains completionunknown and grants no model approval. The source600s deadline is never reset. Actual command, all tool requests/returns and frozen parameters are reviewed before launch.

Instantiate both literal functions from their exact reviewed fences and verify their Function.prototype.toString byte/SHA bindings beforeuse. Supply only owned plain launch metadata and actualtoolrecords. Keep originals in the calling tool store until the64KiB record and separately funded witness/preservation originals are durable. Never include private modelchannels inthisrecord.

```javascript
async function persistPr9Review05ExternalRecord(fs, crypto, invocation, records, fixed) {
  const built = buildPr9Review05ExternalRecord(invocation, records, fixed);
  if (built.raw.length > 65536) throw new Error("review05_external_prewrite_extent");
  const recordSha256 = crypto.createHash("sha256").update(built.raw).digest("hex");
  const path = "C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/grok-model-review05-01-outer-tool.original.json";
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
  return { scope: "review05_external_record_local_persistence_only",
    record_bytes: built.raw.length,
    record_sha256: recordSha256,
    facts, primary_cause: causes[0] || null, secondary_causes: causes.slice(1),
    external_collection_ended: built.value.external_collection_ended,
    completion_unknown: built.value.completion_unknown, model_or_product_accepted: false };
}
```

## Exact fixed review05 invocation template

Source/main28583B/f8cf7453; Mode=review05/Attempt01; Preparation14890/ae66bd90 and independentlyacceptedPreflight2209/6a8e9ec0; callerCWDexactCworktree. ReplaceONLYthefreshguardliteral with the current typedexit0/nativeJSONstdout/completeexactnotice, preserving originalguardcapture in namedpreservation/witness. Assertactualcommand<=4096bytes printableASCII+CRLFTAB beforecall. Execyield1000ms/max_output_tokens24000; subsequentemptywrite_stdinpollsyield45000ms sameoriginalsession(max15). Keep everyactualreturn. Fixedcollectorbindingssource605,promptsha e59bd457,actualadmissioncomment,frozen{name,bytes,sha},prep/preflightSHA; no otherdynamicsettings. Fresh>900sauth/fullguardsandsourcereviews/recordedadmissionstillrequired. Noexecutioninthisdocument.

```powershell
$ErrorActionPreference='Stop'
$taskSourcePath='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/grok-model-phase-command-review05.original.ps1'
$taskSourceStream=[IO.File]::Open($taskSourcePath,'Open','Read','Read')
try{
 $taskSourceRaw=[byte[]]::new(28583);$taskOffset=0
 while($taskOffset -lt $taskSourceRaw.Length){$taskN=$taskSourceStream.Read($taskSourceRaw,$taskOffset,$taskSourceRaw.Length-$taskOffset);if($taskN -le 0){throw 'frozen source shrank'};$taskOffset+=$taskN}
 if($taskSourceStream.ReadByte() -ne -1 -or [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskSourceRaw)).ToLowerInvariant() -cne 'f8cf7453d8d34cd56a893297c1fc53ddcae89bda33dcff951674b4ede98592c1'){throw 'frozen source differs'}
 & ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskSourceRaw))) -Mode review05 -Attempt 01 -PreparationBytes 14890 -PreparationSha ae66bd90dc18d005d54b88ff8089a54b2d02d14ab5ff9a5ef8a6296cc5be619d -PreflightBytes 2209 -PreflightSha 6a8e9ec040c251383bb3abd9ca3dea691f3c904dd1ebfd5fec0930694468a55a -LinuxGuardJson '__FRESH_TYPED_GUARD__'
}finally{$taskSourceStream.Dispose()}
```
