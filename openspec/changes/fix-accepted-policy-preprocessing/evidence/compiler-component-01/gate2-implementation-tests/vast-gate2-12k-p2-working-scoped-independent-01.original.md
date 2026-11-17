**Scoped CLEAR_WITH_NOTES for the frozen P2 helpers and proof propagation. No required defect found.**

Both files matched their targets before and after review:

- Main: **182,690 bytes**, SHA-256 `c7edd00c6a0e27b46eb56941ab486e3d2a4c6b797c2b957840b7027f8f8e5909`.
- Caller: **125,086 bytes**, SHA-256 `fb0d558b412a055cf59ef4ce8a52c5174343de11da55e72ce1c9c961c1185d84`.

The reviewed implementation satisfies the scoped P2 contract:

1. **Known executor source is independently required.** `gate2Receive` requires `expectedExecutorSourceSHA` and compares it with the exact initial executor arguments. Profile parsing and an observed-chain hash cannot substitute for that binding.

2. **Complete actual delivery is checked.** The receiver validates the ordered initial exec/same-cell waits, their explicit output allowances, complete terminal wrapper and exact concatenated output. It hashes the actual canonical ASCII record, including one LF, separately from the complete chain. Record and chain bounds remain **65,536** and **262,144** bytes respectively.

3. **Metadata is retained.** Required content semantics are checked without imposing an exact `{type,text}` keyset. Safe annotations and `_meta` remain inside the complete record and its hash.

4. **The seven-field proof binds actual setup context.** The context tuple comes from validated `setupView` facts and actual selected/core/C-D factory pins, between the existing clock checks. Root and receiver require seven fields; successful six-field proofs refuse. Failed retained setups carry null context and cannot obtain C1 delivery authority.

5. **Approval remains closed and acyclic.** `gate2Approve` checks the exact thirteen-field canonical body, receipt/context/current bindings, delegated-agent approval type and distinct prior independent-review reference. It hashes the observed body. The body does not contain the later external-object hash.

6. **C1 enforces the handback.** The previously reviewed factory requires actual prepared commit/packet agreement, canonical external authority and immutable later-stage digest continuity before imports/spawn.

I inspected the positive and negative test code covering source substitution, incomplete delivery, profiles, context/causal changes, old six-field proofs, metadata preservation, approval bindings and SHA padding vectors. **I did not run those tests.**

The remaining trust boundary is explicit: the expected executor hash must genuinely predate execution; the supplied chain must be the actual host observation; and the approval observation must come from the real independently reviewed record. The helper does not establish wire authenticity or fetch approval records.

Actual full-output qualification, final integrated evidence/conformance and manifest02 review remain pending. This is not whole-candidate, exact-commit, CI or physical clearance. No edits, project execution or physical actions performed.
