**Known executor-source provenance is required; the new parameter is a suitable enforcement mechanism.**

Parsing the output-budget pragma and hashing the observed chain does not authenticate its source. `text(forgedRecord)` illustrates the gap: its record could be internally consistent.

For this automated receiver, require `expectedExecutorSourceSHA` and compare it with the exact bytes of the actual initial executor arguments. The expected hash must come independently from the reviewed literal plus actual bindings **before execution**, not from the observed chain. Passing it only to the later receiver introduces no self-hash cycle, file, call, clock or receipt-schema change.

Independent packet approval could satisfy the provenance requirement instead, but only if the actual reviewed approval explicitly binds and verifies that exact executor source. A generic approval reference is insufficient. Given the intended receiver contract, I recommend treating the hash comparison as required.

It remains additional to complete delivery, terminal, context and approval checks; it proves none of those alone.

For content items, requiring exactly `{type,text}` is unnecessarily restrictive: the supplied MCP text-content definition permits `annotations` and `_meta`. Check the required type/text semantics while retaining safe metadata unchanged in the complete hashed record. Apply existing canonical/type/size checks to all fields; do not strip metadata to obtain acceptance.

P2 remains pending implementation review and tests. No execution or edits performed.
