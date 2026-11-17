**Yes—with three binding conditions below. This is faithful enforcement of V8 §8.3/§8.5, not a material amendment. P2 remains blocked until implemented and independently verified.**

1. **The proposed C1/later-stage interface is appropriate.**

C1 may require:

```text
external = {
  receipt: <exact eight-key receiver receipt>,
  approval: {
    reference,
    body_sha256,
    receipt_sha256
  }
}
```

Validate exact keysets, bounded strings, strict integer ranges, hashes and canonical receipt SHA. Freeze the canonical external object and its SHA privately after successful validation. Later stages must require precisely that frozen SHA, alongside their existing packet/pin/stage checks. Missing authority, replacement authority or an in-session success flag alone must refuse before spawn.

This adds no native argument, extra MCP call, file, capture or deadline.

2. **Bind the actual prepared packet, not merely caller-supplied expectations.**

The receipt context must match `args[0:3]` and selected/core/factory pins. The actual setup packet descriptor must also match those arguments.

That comparison must occur either in the receiver against authenticated delivered setup facts, or through C1’s `setupView(last_setup)`. It is **not optional if the receiver otherwise checks only root flags**. A changed packet SHA with unchanged setup evidence must fail.

3. **Keep the approval dependency acyclic.**

The actual independently reviewed approval body should bind the receipt SHA, packet identity and source context. Its exact observed body hash belongs in `external.approval`.

Do not make that body bind `SHA256(canonical(external))`: `external` itself contains `body_sha256`, which would create a cycle. The frozen external SHA is computed afterwards and used only for later-stage continuity.

The procedure must verify the actual approval record and body bindings before constructing C1 authority. URL syntax alone remains insufficient; no approval API fetch is needed inside `begin`.

4. **Define the receiver’s byte boundary exactly.**

`ROOT_RECEIVER` must consume the actually delivered canonical ASCII document, including precisely one final LF, with the size bound including that LF. Reject trailing noise, missing LF, multiple documents, unsafe values or noncanonical representation.

It must validate the complete actual executor invocation/terminal evidence—including any ordered `functions.wait` fragments and their output profiles—not just the initial request. Hash the received bytes, never a reserialized or pre-emission object.

The receipt’s executor hash should identify the documented complete invocation profile. Actual call arguments, provider fields and terminal evidence must remain externally available without filtering.

5. **The output profile is a valid preflight, not delivery proof.**

Requiring `{max_output_tokens:100000,max_record_bytes:65536}` before work is a reasonable fixed implementation profile. Apply the 65,536-byte limit only at the external-record serialization boundary; selected setup records remain limited to 12,288 bytes.

Every actual terminal wait must use the qualified output allowance. An infrastructure cap, truncation, missing fragment or unavailable terminal result still prevents receiver authority. Neither the request nor `gate2Complete` may set an external-delivery-success flag.

6. **A bounded pure-JS ASCII SHA-256 helper is acceptable.**

It adds no process, dependency or retained form. Qualify empty/`abc`, padding-boundary and multiblock known vectors; reject non-ASCII input at this helper’s boundary. Hash comparison must cover the exact received byte sequence, including its LF.

Required regressions include swapped packet/context, wrong approval-body or receipt hashes, pre-emission-object substitution, incomplete exec/wait delivery, default/incorrect output profiles, later-stage authority replacement, and the complete C1 six-frame geometry with this authority. **If C1 exceeds 4,096 bytes, hold rather than trim bindings or raise its cap.**

No edits, tests or physical actions were performed for this assessment.
