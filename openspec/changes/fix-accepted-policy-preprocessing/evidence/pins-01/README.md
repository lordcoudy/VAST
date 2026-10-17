# Fresh Identity Pin Review

Build/input authority: `aca94dd0a57566d5a9ecc27d8dac1ca71ca0e795`.
Fresh physical root: `/mnt/e/STUDY/VAST/tmp/accepted-policy-repair-20261011a`.
Fresh namespace: `accepted-policy-repair-20261011a`.

The byte-copy recipe retained five generated configuration originals and the
selected GStreamer freeze receipt without changing historical receipts. The
inventory and literal plan use the previously reviewed qualification planner;
`repair_pin_plan.py` supplies the fresh identities and guards its application.

The exact reviewed plan SHA-256 is
`9faf81a6ade677afd6db3af947b3895ab286b43a93a8076602eaf5c173c3b311`.
The complete rendered patch SHA-256 is
`60cfff8597aa53692f749c6070e7869f95c3d5a4598e5b98c3d0860a87b8198b`.
Root and an independent subagent read the complete eight-file patch before
application. It contains 76 literal/token replacements, with unchanged non-pin
AST structure. The guard also rechecked the current 805-file source/configuration
inventory, saved plan and review bytes, exact changed-line set and paired hashes.
The original `run_pin_plan.sh apply <plan-sha>` invocation exited zero.
`host-pin-rebind.applied.v1.json` retains its structured result.

Two render refusals were resolved before application, not waived: undeclared
inventory-only matches, then an incomplete current untracked-source inventory.
The retained first inventory and `render-attempt-01.stdout.log` are not successful
review evidence. The successful review inventories cached and untracked relevant
source/configuration files, rather than only the build commit's file list.

Exactly sixteen matches are unchanged generic build defaults: twelve canonical
registry references and four environment-overridable build-script references.
They are not fresh qualification pins. Stock refreeze capture requires fresh
candidate references to be disjoint from the canonical registry references;
changing those defaults would invalidate the new capture's registry binding.
The classifier verifies exact file/line/value triples, registry structure,
byte equality with the build commit and the before/after twelve-tag observation.
All other eligible inventory matches must equal the declared replacement set.

The GStreamer runtime test already has a byte-preserving CRLF contract in
`.gitattributes`. Its three replaced CRLF lines are reported by plain Git
`diff --check` as trailing whitespace. Their endings were intentionally preserved;
`git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`
passes. No source normalization or Git attribute change was made.

After staging raw evidence, the two original BuildKit whitespace lines and
the unified patch's blank context lines also trigger Git's whitespace check.
The final staged authored-source/document check passes with only those two
byte-bound raw files excluded. Neither their bytes nor the reviewed patch
digest were changed to suppress these diagnostics.

These are literal-plan/application checks, not final CI, semantic consumer
acceptance, regenerated execution closure, archive, final human approval or Q1.
Those remain separate task gates.
