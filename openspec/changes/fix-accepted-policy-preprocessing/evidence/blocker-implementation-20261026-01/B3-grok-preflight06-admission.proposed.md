# One source-bound preflight06/Attempt01 proposal

Same product605eb02733fe256ad5ef14f358eaa81ee1a0ae44/change/branch/PR9.
Authoring approval6464092305; model06 capacity plan7153B/
0b3c0b987482f8a7ce2de80a65cfa54c311e9827f3e708495fe4d1f1c218f99e.
NEW2MiB preflight row, fully retained with NEW7MiB model06; cumulative2439MiB/
C73.3408203125GiB. Its10ordinary public forms/448KiBZIP and the shared single
32KiB model06 archive-helper slot are exactly named in the capacity plan.

Dependent source six-v2 authoring only; no frozen actual body or execution yet.
Main28583B/6ef3a1d4060e103ecb8c1ad6e8a026347a8b1a629b606edd4aef9c94443e9dc9
will be copied CreateNew to grok-model-phase-command-preflight06.original.ps1
AFTER independent exact source/template/capacity approval, before one invocation.

This one preflight launches the bounded reviewed Python controller ONLY; it may
privately read/compare retained prep05/.g5 and current originals. It launches
NO Grok/inspect/plugin/mcp/network operation, creates no snapshot/model root or
raw channels, changes no credentials/settings/images, and accepts no model.
Retain all original preflight06 forms and partial extents; no replay/continuation.
Same45s observation/60s total and per-form bounds, no widened read limits.
Actual tool return and invocation must be preserved losslessly in the funded
outer-tool32KiB form, retaining every returned metadata field; Base64 raw output.
At most one start and two same-session<=30s polls if yielded; unknown completion
grants no acceptance. Sum native returned output<=16KiB; ordinary outer32KiB,
fixed entry ASCII<=4KiB; full guard provenance goes in funded outcome32KiB.
The exact aggregate wrapper bound must pass before its CreateNew write.
Private strings/timestamps/hashes/raw results never enter public evidence.
Exact original uint64 FILETIME values stay in original bytes/decimal strings.

Require recorded independent source/capacity/template CLEAR and explicit
delegated AGENT execution approval, fresh full Linux/Windows guards, original
same605/protected sources/runtime hashes and unchanged sealed profile custody.
This preflight uses no freshness waiver for a later model run: review06 still
requires >900s auth, independently accepted exact preflight06 receipt and its
own frozen admission/fresh guards. No broader task1.5/physical/runtime acceptance.

Only the fresh reviewed separated native guard JSON may replace the marker:
preserve original channels, accept only empty/exact known UTF16-NUL localhost
proxy notice, bind stdout to exit_code/output and retain stderr_original.
The previously reviewed wrapper source and all other bytes remain unchanged.

```powershell
$ErrorActionPreference='Stop'
$taskSourcePath='openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/grok-model-phase-command-preflight06.original.ps1'
$taskSourceStream=[IO.File]::Open($taskSourcePath,'Open','Read','Read')
try{
 $taskSourceRaw=[byte[]]::new(28583);$taskOffset=0
 while($taskOffset -lt $taskSourceRaw.Length){$taskN=$taskSourceStream.Read($taskSourceRaw,$taskOffset,$taskSourceRaw.Length-$taskOffset);if($taskN -le 0){throw 'frozen source shrank'};$taskOffset+=$taskN}
 if($taskSourceStream.ReadByte() -ne -1 -or [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($taskSourceRaw)).ToLowerInvariant() -cne '6ef3a1d4060e103ecb8c1ad6e8a026347a8b1a629b606edd4aef9c94443e9dc9'){throw 'frozen source differs'}
 & ([ScriptBlock]::Create([Text.UTF8Encoding]::new($false,$true).GetString($taskSourceRaw))) -Mode preflight06 -Attempt 01 -PreparationBytes 14890 -PreparationSha ae66bd90dc18d005d54b88ff8089a54b2d02d14ab5ff9a5ef8a6296cc5be619d -PreflightBytes 0 -PreflightSha '' -LinuxGuardJson '@@LINUX_GUARD_JSON@@'
}finally{$taskSourceStream.Dispose()}
```


## Pre-entry fixed envelope and persistence closure

Require max_output_tokens=24000 on the exec AND each poll, retaining/refusing
acceptance on reported truncation. Exact escaped JSON invocation fragment<=4096B
beforeentry; each metadata<=1024B/aggregate3072B; Base64aggregate<=21856B for<=3
returns and<=16384B raw output; fixed/structural framing including fixed bindings
<=2048B. Thus31072B plus oneLF=31073B<32768B. Full original guard provenance goes
in funded outcome32KiB. No unbounded or callback-backed values are serialized.
The literal collector/writer below must be fingerprinted before entry/use.
Collector6980B/2641b950a01482aef0ee71430f7b0b5a5aaec2617e1e8b3aa66d8a1ae9dffadc;
writer2621B/61363291ebb4949da1eb87b9bb8499f93520944c994bd0c9b25f77b9057376a9.
They preserve the reviewed model collector/writer safety logic, tighten return/
poll/record bounds, bind the preflight06 path and measure framing before encoding.
Nine public pure controls pass, including three full-output returns with maximal
escaped invocation (30050B record), bound/session/poll refusals, CreateNew/ordered
sync+close and prehash-before-open. Private/filesystem/Grok execution is false.

```javascript
function buildPr9Preflight06ExternalRecord(invocation, records, fixed) {
  const fail = code => { throw new Error("preflight06_external_" + code); };
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
  if (!Number.isSafeInteger(count) || count < 1 || count > 3) fail("return_count");
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
    if (source.name !== "grok-model-phase-command-preflight06.original.ps1" ||
        !Number.isSafeInteger(source.bytes) || source.bytes < 1 || source.bytes > 28672 ||
        typeof source.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(source.sha256))
      fail("fixed_source");
    fixedSnapshot.frozen_source = source;
  }
  if (fixedSnapshot.source_commit !== "605eb02733fe256ad5ef14f358eaa81ee1a0ae44" ||
      fixedSnapshot.prompt_sha256 !== "e59bd457dca8028aaf1e25fdab087495f5351a83a9a2fcc134e82fecc9780aa7")
    fail("source_binding");
  const invocationFragmentBytes = Buffer.byteLength(JSON.stringify(invocation), "utf8");
  if (invocationFragmentBytes > 4096) fail("escaped_invocation_extent");
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
        row.yield_time_ms > (i === 0 ? 10000 : 30000)) fail("poll_wait");
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
  if (base64Bytes > 21856 || metadataBytes > 3072) fail("aggregate_extent");
  const value = {
    scope: "configured_preflight06_original_external_tool_returns_only",
    fixed: fixedSnapshot, invocation, returns: encoded,
    external_collection_ended: ended, completion_unknown: !ended,
    returned_output_utf8_bytes: outputBytes, encoded_output_bytes: base64Bytes,
    model_or_product_accepted: false
  };
  const envelope = { ...value, invocation: "", returns: encoded.map(row => ({ ...row,
    actual_return_metadata: {}, output_base64: "" })) };
  if (Buffer.byteLength(JSON.stringify(envelope), "utf8") > 2048) fail("envelope_extent");
  const raw = Buffer.from(JSON.stringify(value) + "\n", "utf8");
  if (raw.length > 32768) fail("serialized_extent");
  return { value, raw };
}
```

```javascript
async function persistPr9Preflight06ExternalRecord(fs, crypto, invocation, records, fixed) {
  const built = buildPr9Preflight06ExternalRecord(invocation, records, fixed);
  if (built.raw.length > 32768) throw new Error("preflight06_external_prewrite_extent");
  const recordSha256 = crypto.createHash("sha256").update(built.raw).digest("hex");
  const path = "C:/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/blocker-implementation-20261026-01/grok-model-preflight06-01-outer-tool.original.json";
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
  return { scope: "preflight06_external_record_local_persistence_only",
    record_bytes: built.raw.length,
    record_sha256: recordSha256,
    facts, primary_cause: causes[0] || null, secondary_causes: causes.slice(1),
    external_collection_ended: built.value.external_collection_ended,
    completion_unknown: built.value.completion_unknown, model_or_product_accepted: false };
}
```
