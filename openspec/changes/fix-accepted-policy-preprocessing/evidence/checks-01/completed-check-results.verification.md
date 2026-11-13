# Completed Check Result Retention

The parent independently reviewed and authorized exact plan SHA-256
`58baf5eab3eda7c4d589b161b7b7c2f9b57af6d896475c036416eb9b22206625`
and unchanged helper SHA-256
`01e4d5bfe1738167e8ec1da5b45104e349b2c5052fddc89ea71b5ba92bd4b6ed`.
This authorization is limited to byte-exact copies of completed outputs from
source commit `591a93e778a9a7839da6278326d215e24e91ea45` into this managed
worktree. It is not user approval, semantic acceptance, or campaign authority.

## Original Apply

`run_completed_check_retention.sh` has SHA-256
`e6a2f486e38f961db6f267c859458d6724eaaf72facb91dc1a8b9d2aa78604e0`.
It syntax-checked successfully and invoked the canonical WSL publication
Python with `-B`, `TMPDIR=/var/tmp`, the reviewed plan, and its exact SHA.

The original command exited zero, started `2026-10-11T21:35:12Z`, and finished
`2026-10-11T21:35:14Z`. Its stderr is empty. Its stdout has SHA-256
`9d8e1f2f422f39761bd4fb5d89fa24ebe216e65537906d91ed17febdb678db93`.
All controls are in `completed-check-retention-control/`; none was written
into the selected source root or the separately running CI clone.

The guarded apply reports `retained_exactly`: 114 files in seven explicitly
listed producer groups, totaling 1,035,867 bytes. The resulting provenance
catalogue `completed-check-results.v1.json` has SHA-256
`c7d9a6686bcca0f775859d750c964db6c7ddce80317f7382b7307c787f5fd8fc`.

A subsequent independent read-only verification rehashed all 114 retained
files against their source bytes and checked all 114 recorded source
physical epochs unchanged, then rechecked the exact source HEAD and clean
tracked source. It exited zero with the same byte total and catalogue hash.

## Preserved States

- Source-input copy: complete independent before-ext4 report at exact 591;
  this producer has no fabricated finish timestamp.
- Original focused checks: return code 1, retained separately.
- Focused retry `-02`: original return code 0, retained separately.
- Final-source-input comparison/materialization/cold checks: return code 0.
- Original integration: nine return codes `[0,0,0,0,1,0,0,0,0]`.
- Integration retry `-02`: nine original return codes all zero.
- Reconstruction-input copy: original return code 0.

The original focused and integration failures remain failures. Copying their
outputs does not reinterpret them as successful checks. Huge copied input
trees, live full-suite outputs, every consumer fixture attempt, and
pre-existing retained evidence were excluded. No SOURCE data, historical
receipt, production source, CI selection, workflow, or skip rule was changed.
