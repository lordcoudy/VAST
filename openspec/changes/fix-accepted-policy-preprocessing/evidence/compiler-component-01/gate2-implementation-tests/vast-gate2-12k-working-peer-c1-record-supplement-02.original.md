**Required for C1’s `external`, `receipt` and `approval` records under the same closed-object contract.**

I confirmed the current boundary:

- `begin` receives the object directly; no JSON parsing barrier precedes it.
- `cdSaved.keys` rejects arrays/functions but accepts boxed empty strings and custom-prototype objects with the required enumerable fields.
- `gate2Ascii` serializes those fields without rejecting their container.
- Consequently, canonicalization can succeed and native work can begin.

The intended JSON-literal handoff is a trusted procedural assumption. It would also have excluded the malformed main-helper inputs; it cannot consistently replace validation only here.

Add a **scoped ordinary/null-prototype data-record guard** for these three handback records before reading their fields, followed by the existing exact-key/type/hash checks. Preserve the established ordinary/null-prototype policy. This needs no wire-schema, native API, call, file or deadline change.

This does **not** require universal Proxy detection or changes to arbitrary provider metadata. Tests should use ordinary boxed/custom-prototype counterexamples, prove rejection before imports/spawn, and retain valid plain/null-prototype positives.

Both files remain at their frozen hashes. No execution or edits performed.
