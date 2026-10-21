# Closed A16 Full Check: Retention Plan Only

## Original Result

Exact source commit: `a16f243e7e80f093342ccdddf717d59d6d46f0a8`.
The original worker session `55655` completed naturally with outer exit code 0;
no termination, restart or retry occurred. The unchanged recipe is
`run_ext4_suite.sh`, SHA256
`045cdded701dfb59100ce600344079f615a7be5991778befa4123eb209cb106d`.
The byte-exact original outer eight controls remain in `full-a16-control-01`.

- Actual 3307 portable tests: 3221 successes, 0 failures, 0 errors, 86 skips.
- Every actual skip identity, exact reason and structured audit matched the
  unchanged committed manifest. No skip is qualification acceptance.
- Elapsed stock report time: 2691.150726158987 seconds.
- Exact whole global mountinfo equality: 261 rows, SHA256
  `eeba47ce95f1968cfeeef091ea908a5cfacce874ba4569190e86385611e209d7`.
- Caller `mnt:[4026532365]`; private mount namespace `mnt:[4026532405]`.
- Private UID/GID 1000, effective/permitted/inheritable/ambient capabilities
  zero; observed ordinary soft NOFILE 10240 restored from runuser's 1024,
  hard NOFILE 1048576 unchanged. Test temporary base was native ext4 `/tmp`.
- Original tracked-source inventories before/after were byte-identical;
  report raw-checkout match was true with no changed tracked paths. Current
  SOURCE and CI HEAD/clean checks also passed during plan generation.
- Native configure/build/model-acquisition commands returned 0 without
  timeout or cleanup error; six declared native targets were built.
- Python syntax checked 535 files; Bash syntax checked 16 files.
- The canonical copied WSL Python test and three native client/topology/reset
  regression tests actually succeeded. Namespace profile was not required.

Original stock report SHA256:
`31ff129bac45518957739888945c7d748a3ed1ceccc452c796a1f91cfe41e4b3`.
Outer UTC: `2026-10-11T22:58:28.434537+00:00` through
`2026-10-11T23:43:39.419964+00:00`.

The portable report explicitly excludes the nine physical integration IDs;
their separate SOURCE execution is not inferred from this result. The original
observer explicitly states that descendant quiescence is not established by
original-child status. No complete default-consumer, real 126016-sample run,
archive, Q1 or scientific hardware-acceptance claim follows from this suite.
Consumer08's preserved failure and host-backing capacity HOLD remain separate.

## Finite Plan

New helper: `retain_a16_full_originals.py`, SHA256
`ad27c8fdbd8823b20ba363bfbbe9dab1d4805e3d3b3c0508d4e300adc9fc742d`.
It imports the existing immutable A16 retention primitives at their real path,
SHA256 `65fb7ef980246e1fd5b8054a4eaad6c04e6015928523532420c9f5e37bc68941`.
It does not invoke that helper's existing 103-file plan/apply or change its
globals, source paths, original metadata or epochs.

New plan: `a16-full-originals.retention-plan.v1.json`, SHA256
`e7ed026de152f1e2f3e2472669c87db66eaa937e5b970909a82d8c846a66ee19`.
The plan is 84196 bytes and names exactly 82 original SOURCE result files:
33 top-level controls, 28 stock reports/raw outputs, 7 namespace diagnostics,
5 external-observer files and 9 model-acquisition reports. Total retained
bytes would be 13115499; largest file is 2871181 bytes. Bounds are 16 MiB per
file and 32 MiB total. All names are literal; no recursive enumeration adopts
additional files. Existing managed outer8 controls are referenced unchanged,
not recopied.

Excluded: compiled binaries/build trees, corpus/model/runtime/native/tensor
input trees, separate physical-nine/reconstruction results, historical591
results, every consumer output and absent namespace-profile files.

Proposed destination `a16-full-originals/` and catalogue
`a16-full-originals.v1.json` are absent. No retention apply/copy has run.
This new helper, plan, review and plan-control directory are outside the
parent's already reviewed 245-path stage and require separate review.

## Actual Plan Execution

Parent authorized plan-only preparation. One canonical capture was run:

```text
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/retain_a16_full_originals.py capture-plan
```

Original child argv is recorded in `a16-full-plan-control-01/command.json`:
the same interpreter/helper with `plan`, not `apply`. Its original result,
stdout and stderr are retained in that fresh control directory. Child and
outer return codes were 0. Child UTC:
`2026-10-11T23:56:27.430649+00:00` through
`2026-10-11T23:56:27.806215+00:00`. Stdout is the exact plan bytes; stderr is
empty. Tool emission `dda773` includes the benign WSL NAT/proxy warning outside
the native child streams, not an original-check failure.

An independent read-only verification rehashed all 82 originals and all 8
existing outer references, compared actual physical epochs/bytes to the plan,
checked unique bounded source/target paths and rechecked source HEAD/clean.
It returned 0, reported the bounds above and confirmed both retention
destinations still absent. Syntax AST parsing also returned 0. No SOURCE
write, clone, test rerun, mount operation or retention copy was executed.

## Review Gate

Apply is not authorized. A later bounded apply must require the exact reviewed
plan hash, rederive the complete plan before writes, reject any changed helper,
original byte or epoch, exclusively create fresh targets, rehash originals and
references after copying, and preserve the original source/head gates. Those
guards are present in the new helper but have not been executed.

## Subsequent Authorized Apply And Independent Audit

The plan-only statements above describe the earlier preparation boundary.
After root's full read and independent peer review, root explicitly authorized
one bounded apply of exact helper `ad27c8...742d` and plan `e7ed026...ee19`.
No original or sealed helper bytes were changed. The only apply executed was:

```text
/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python -B /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/retain_a16_full_originals.py apply --plan /mnt/c/Users/s-a-balashov/.codex/worktrees/fix-accepted-policy-preprocessing/VAST/openspec/changes/fix-accepted-policy-preprocessing/evidence/checks-01/a16-full-originals.retention-plan.v1.json --reviewed-plan-sha256 e7ed026de152f1e2f3e2472669c87db66eaa937e5b970909a82d8c846a66ee19
```

The reviewed capture wrapper `run_a16_full_retention_apply_v1.py` physically
hashed `c8c43968bc602a3edf02980841a1946a7526f42ab4d630809d851e74c817d928`
before invocation and after closure. It retained actual argv, original streams,
UTC and return code in `a16-full-apply-control-01/`; three enclosed sealed
subjects' before/after hashes were equal. Original and wrapper RCs were 0,
with no interruptions, retries or termination. Native child UTC:
`2026-10-12T00:03:52.949827+00:00` through
`2026-10-12T00:03:54.995580+00:00`. Original stdout is 297 bytes, SHA256
`4a00066622879376ac4c490abc2e81d17c1f77f79bd47118caac21c95803f0f0`;
stderr is empty. Completed tool emission: `da717a`.

The resulting catalogue `a16-full-originals.v1.json` has SHA256
`b114a869efddf6f75df6db4d72f5c0d2552b45246f7748572a78210c55b018c5`.
Exactly 82 literal original files / 13115499 bytes were retained mechanically.
Existing outer8 references and all original epochs/bytes were preserved.

Root also explicitly authorized one separately implemented read-only audit.
`verify_a16_full_retention_v1.py`, SHA256
`7a49e9dc281130ce8952848ab89e5459eb61a91a434d4c47d4d6aad09c9e949c`,
uses only standard-library readers, without importing/invoking the retainer.
It independently checks strict catalogue/plan equality, canonical single-link
held reads, all 82 retained file bytes, all 90 original/reference bytes and
physical epochs, exact file/directory inventory with no extras, sealed subjects,
and current SOURCE/CI HEAD plus tracked-clean before/after. The latter is
explicitly not a new live 12115-file stock raw-source acceptance gate.

One `--capture` execution completed naturally (tool `d84886`), child/wrapper
RC0, no interruptions. Child UTC:
`2026-10-12T00:06:23.659797+00:00` through
`2026-10-12T00:06:24.517868+00:00`. Original stdout is 52549 bytes, SHA256
`77843c0b5c299f6e4dd475b1cac5aa417bee0d2b47d8a612cfa5427dd75924b0`;
stderr is empty. Exact command/result/raw streams remain in the fresh
`a16-full-independent-control-01/`. The audit helper's physical hash was also
checked before and after this execution and was unchanged.

All owned workers are now closed. No tests, source clone, large input producer,
mount, consumer rerun or source modification was performed. All new retention
files remain untracked pending root's separately reviewed evidence checkpoint.
The full-suite scope and unresolved consumer/capacity limitations stated above
are unchanged; retention conveys no new qualification authority.
