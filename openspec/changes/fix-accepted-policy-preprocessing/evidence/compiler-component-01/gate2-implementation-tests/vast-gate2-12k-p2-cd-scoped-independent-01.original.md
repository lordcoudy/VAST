**Scoped CLEAR_WITH_NOTES for `CD_FACTORY_SOURCE`: 12,596 bytes, SHA-256 `3846857b1fc7796bbb5ec570c947f2c6832b4a2c4f9dee34d0a27a2ce33ea208`.**

The author confirmed the changed pin. I independently reversed its exact 54-byte delta—capturing `cdPrepared`, checking its identity and passing it to saved `setupView`—and recovered the requested **12,542-byte / `d053aa69796808c850207705ad936cd78af308de11276ba2891b8138d3120cca`** literal.

The current literal satisfies the scoped contract:

- C1 requires the closed eight-key receipt and three-key approval binding.
- Receipt context binds the actual arguments and selected/core/factory pins.
- Saved `setupView(cdPrepared)` checks actual prepared commit, packet size and SHA.
- The external authority becomes an immutable canonical string/digest, avoiding retained mutable caller references.
- Later stages require the frozen digest and existing packet/pin continuity.
- Function and prepared-snapshot replacement refuse before imports/spawn.
- Validation failures leave the stage non-successful; no new clock or retry is granted.

Approval-body authenticity still belongs to the trusted external receiver/review procedure. This factory validates its supplied binding; it does not independently fetch or authenticate the approval body.

The proposed **seven-field P0 `verifyReturn`** is faithful strengthening of the existing causal/context proof, not a material amendment. Require an exact typed context tuple derived from validated setup facts and actual held pins, update every consumer, and reject the former six-field form. No native API, MCP count, file or time allowance changes.

A separately bounded executor-chain hash is also appropriate: **65,536 remains the record-only limit**. Hash the complete actual chain without dropping fields; do not force chain-plus-record into that limit through omission.

Receiver implementation, approval helper, seven-field propagation and complete final geometry remain pending review. I ran no tests or project code and made no edits. This is not whole-candidate or physical clearance.
