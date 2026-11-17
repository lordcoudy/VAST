# P2 implementation contract and independent design assessment

Status: implementation in progress; P2 remains BLOCKED. This note records enforcement of the approved V8 sections 8.3 and 8.5. It does not amend the five approved planning documents, authorize physical work, approve changed source, or change task completion.

The independent reviewer accepted this contract conditionally in `vast-gate2-12k-p2-design-independent-01.original.md`. That assessment is preserved byte-for-byte from the separate reviewer, with its exported terminal LF. Author checks do not replace independent implementation review.

## Required boundary

The in-session root result may establish causal setup and local retention. It cannot establish that the enclosing executor delivered its complete output. A separate receiver consumes the actually observed complete external result, including its exact canonical ASCII document and one final LF, at a fixed total bound of 65,536 bytes. Selected setup collections remain bounded at 12,288 bytes and six frames. The actual enclosing exec and every wait must explicitly request 100,000 output tokens; a requested profile alone is not delivery proof.

The receiver preserves complete actual arguments and unfiltered provider returns. It checks all ordered exec/wait output fragments and their terminal wrapper evidence. It hashes the actual received bytes including LF and the complete invocation chain. Missing, unavailable, truncated, noncanonical, oversized, incomplete, or mismatched evidence yields no authority. No in-session external-delivery-success flag is accepted.

The outer tools currently expose public text wrappers, not invented structured EOF/PID/completed metadata. An inert exec/wait during the current controlled session observed a running cell 1368 followed by complete, both using explicit 100,000 allowances. That small observation establishes only the supported wrapper shape and accepted request; it does not qualify full-size delivery, hosted Linux Node, native execution, or physical acceptance. The implementation must state its trusted host-decoded observation boundary. Unknown wrapper formats fail closed.

## Closed authority interface

C1 receives a sixth `external` argument with exactly `receipt` and `approval`. The receipt has exactly eight keys: `version:1`, `context_sha256`, `record_size_bytes` (safe integer 1..65536), `record_sha256`, `executor_call_sha256`, `max_output_tokens:100000`, `terminal:"complete_untruncated"`, and a real bounded ASCII `tool_reference` (1..96). All hashes are lowercase SHA-256.

The context is SHA-256 of canonical ASCII JSON of `["vast.gate2.external-delivery.v1", commit40, packetSizeNumber, packetSHA, selectedSHA, coreSHA, factorySHA]`. C1 also checks the actual authenticated `setupView(last_setup)` commit and packet size/SHA against its unchanged four native argument strings. Caller-supplied expected values alone do not establish that binding.

The approval has exactly `reference` (actual PR9 approval comment URL, bounded at 96 ASCII characters), `body_sha256`, and `receipt_sha256` (SHA-256 of canonical receipt). Before handback, the receiver procedure verifies the actual independently reviewed approval record/body, its receipt/context/packet/current-source bindings, and exact observed body hash. URL syntax alone is insufficient. The body binds receipt and context, never the later external-object SHA: its own hash is in that object, so reversing the dependency would be cyclic.

After successful C1 validation the canonical external authority and SHA are frozen privately. C2 through D require precisely that frozen SHA alongside unchanged stage, source-pin, and packet checks. No new native argument, MCP call, process, retained file/form, capture, or deadline is introduced. The first C/D clock read remains before admission work. Pure bounded ASCII SHA-256 in the external receiver requires standard empty/abc/padding/multiblock vectors and rejects non-ASCII.

## Required evidence before the first implementation commit

Targeted regressions cover missing authority/session-flags-only; wrong strict schemas/ranges; swapped packet/context/pins; changed actual received output; incomplete or wrong-profile exec/wait chains; invalid or mismatched actual approval bodies; failed-but-retained setup; and later authority substitution. Full C1 actual arguments plus all six frames must fit 4,096 bytes; the full setup collection must still fit 12,288. If either fails, hold rather than omit bindings/provider fields or raise limits.

Preserve all earlier red/failed/intermediate raw logs. P1 raw tests 129/130 and later-caller 60..63 establish the listener correction only and predate P2. After both author files freeze, perform stable-source controlled regression and independent peer plus Grok CLI review. Only then may the first implementation commit be created, followed by exact-commit reviews, required CI, source approval, and separate physical admission. No archive or merge is currently authorized by readiness evidence.

## Narrow context-proof implementation choice

The existing P0 Node verifyReturn result is extended from six fields to exactly seven. Its final field is the exact seven-member context tuple defined above, derived from validated actual setupView facts and the actual selected/core/CD-factory pins; failed setup has null context and cannot receive C1 authority. Every consumer must reject the former six-field form. The C/D proof schema remains unchanged.

gate2Complete also receives strict pre-call expected source pins (code_commit, core_sha256, factory_sha256). The packet is generated during setup: its size and SHA must come from the authenticated actual proof, not an invented pre-call expectation. The external receiver subsequently checks every full-context member and the actual reviewed approval body. This changes no native API, MCP count, file, or deadline. The separate reviewer confirmed this faithful strengthening in the scoped report preserved alongside this note.

The complete unfiltered executor chain has a separate finite in-memory canonical hashing bound of 262,144 ASCII bytes. The delivered root document alone retains its 65,536-byte including-LF bound. Oversized chains refuse; their argument/result fields must never be dropped to fit. No third physical capture form is created by this in-memory hash.

## Final receiver source and approval bindings

The receiver requires a separate expectedExecutorSourceSHA parameter. That hash must be rendered independently from the reviewed actual outer-executor literal and bindings BEFORE execution, then checked against the exact actual first executor argument bytes. Deriving the expected hash from the observed chain would not prove source provenance. It introduces no self-hash, receipt/context schema, native API, call, form or time change. Independent design assessment `vast-gate2-12k-p2-executor-design-independent-01.original.md` requires this binding and permits safe content annotations/_meta to remain in the complete hashed record.

The observed canonical approval body has exactly thirteen fields: version, kind, receipt_sha256, context_sha256, code_commit, core_sha256, factory_sha256, packet_sha256, packet_size_bytes, selected_sha256, decision, approval_type and independent_review_reference. The approval type is delegated_agent_self_approval. The independent-review reference is an actual prior PR9 comment distinct from the authority comment. The trusted external procedure must read its actual body and validate the independent verdict, evidence and dispositions before approval; the pure helper does not fetch or authenticate those records. Authority remains exactly receipt8/approval3. This meets the user's explicit agent-approval labelling requirement without inventing a human review.

The final source interfaces and controlled specimen identities are pinned by `vast-gate2-resume-delivery-final-literals-138.original.json`. Whole-candidate review and physical qualification are separate gates; this implementation-contract note is neither.
