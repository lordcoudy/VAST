# Release process boundary

This is a preparation note, not implementation or release acceptance.

The current OpenSpec CLI context resolves this checkout as the repo-local root. Change fix-benchmark-preparations-spec uses spec-driven; all four planning artifacts are present, while 63 of 74 active tasks are checked. The only delta capability is benchmark-launch-preparation, with 20 requirements and 118 scenarios. No main specs currently exist. CLI status is planning completeness, not proof of implementation or approval.

After actual local full CI and independent current conformance close, sync will create one main specification with the delta Purpose copied verbatim, the Scope preserved, and all requirements under a canonical Requirements section. Every complete requirement body and scenario name/clause must remain equal. The original 82-scenario/72-task register remains preserved and explicitly conditional/unexecuted. No other capability is touched.

Archive will move the same change, including its original .openspec.yaml and every supporting historical file, to openspec/changes/archive/2026-10-03-fix-benchmark-preparations-spec. Exact physical bytes are preserved across that move. The five historical CRLF JSON files require exact-path Git attributes if Git filters would otherwise normalize their archived counterparts. They will not be rewritten to pass checks.

Some active task checkboxes include latest archived-commit CI, final review and merge. Those actions logically occur after archive and cannot be claimed before it. At the archive checkpoint, completed implementation/CI/conformance evidence and the remaining process snapshot will be explicit. The user's standing carte-blanche authorizes the existing required archive, checks, review and merge sequence. Final actual process closure will be recorded in the same PR, avoiding an infinite bookkeeping commit/check loop.

The final commit is a finite explicit path set. No add-all, reset, clean or unrelated deletion is allowed. Before any Git object/index mutation, each selected physical file must match its prospective raw blob under autocrlf false and true; then physical, index and committed bytes must join. Main and archive files, authored docs and finite retained evidence belong to this same branch and PR.

CI on the final archived commit must actually complete. Formatting validation remains structural; the separately reviewed 20/118 conformance report provides behavioral mapping, actual evidence scopes and manual limitations. A green OpenSpec parser is not a behavioral test. Original failures remain immutable.
