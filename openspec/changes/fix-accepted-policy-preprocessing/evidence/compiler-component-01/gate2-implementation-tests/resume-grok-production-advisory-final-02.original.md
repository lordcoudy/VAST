**CLEAR_WITH_NOTES.** The two operator corrections match the source, the 12,544-byte tail is the unmaterialized P0 metadata-copy contract, and the four-document wording change preserves the approved V8 scope. These uncommitted bytes are not source approval, exact-commit CI, caller acceptance, or physical authority.

HEAD stayed `69c2c35f3d51c8d4ef047e7050fe82bfc3b79eae`. All nine manifest hashes match.

## Operator corrections

`tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py` is 32,768 B, SHA-256 `826c89fa9458792b210bf1155ab33be92780bf35c47b5a1f208d0ae77801f4bb`, inside the unchanged 32,768 B cap.

The recorded return code and known closure now come from one post-loop poll. At lines 328–331, `returncode` is `(rc:=p.poll())` and `unknown_closure` uses that same `rc is None`, together with EOF and stdin-closed. A null status and a zero status cannot be split across two fact fields. The loop at line 315 still polls as its wait predicate; that value is not the fact pair. `subprocess` caches a non-null return code, so a later fact poll cannot disagree with an exit the loop already observed.

`write_fixed_v1` line 416 is `os.lseek(fd,0,os.SEEK_SET);gate()` and line 417 reads back only after that gate. A late lseek raises before `os.read`. The same fd still does the write, fsync, readback, and allocation.

Line 16 is `ROOT,AUX=OWNER/'r1',OWNER/'r1.operator-originals'`. That is the four-byte spacing reclaim around the two slashes. Native bootstrap is unchanged: 1,415 B, SHA-256 `7c28da7371dea8407c77fd0edc8f39218819a580eb195086c7a44a7b69c3b65a`. Retained Temp names include `vast-gate2-resume-node-red-62.original.txt`, `vast-gate2-resume-lseek-red-72.original.txt`, and `vast-gate2-resume-two-fixes-green-78.original.txt`. Those logs were listed only. They were not executed, and the Node caller remains outside this review.

## Prior 12,544-byte note

The earlier child-directory-plus-parent-growth reading is withdrawn. `4,352 + 8,192` and `12,288 + 256` are the same integer. The source identity is the second sum.

`METADATA_COPY_CAP` is `12 * 1024` and `INODE_BYTES` is 256 (`gate2_p0_v1.py:37–43`). `round_up_allocation(12288) + 256 = 12544`. `_fresh_reservation` (lines 740–743) charges the directory reserve plus that copy up front. The validator at lines 630–631 adds `round_up_allocation(METADATA_COPY_CAP) + INODE_BYTES` on top of the directory and the observed file allocations. `maximum_inclusive_charge` (lines 145–151) already includes that copy inside the 387,328 B maximum. No P0 persist path writes a separate copy file; control and completion are their own smaller files.

C is unchanged at `1b981e75…`. FINAL (`gate2_c_v1.py:1191–1198`) walks the actual `r1` tree, so the child directory is inside `current`, and `growth` is the observed old parent. It then adds `future = 24576 + 12544` after that maximum: the outer transcript pair plus the still-unmaterialized P0 copy. No C edit is required for this note.

## Four-document correction

Agreed. This reconciles the delta text with V8 §8.2. It does not add behavior, a cap, a source variant, or approval.

Against HEAD, `proposal.md`, `design.md`, and `spec.md` each change one paragraph. `tasks.md` reflows the same unchecked 2.10 bullet (7/4 lines from wrapping). The new sentence limits the index source-version inventory to frozen pre-implementation versions, including c75, 465, bf2, and the reviewed planning snapshot. An unchanged current runtime or plan byte may equal a historical descriptor, and that alias grants no current approval. The index still must not embed its own hash, a future implemented-consumer commit, or mutually dependent current authority. External authority still authenticates current runtime, operator, plan, the actual index, and approval.

V8 §8.2 and the index bytes are unchanged. Row 16 remains the planning-commit plan blob `5ca1f3f3` / `254e7597…`, which is the current V8 file. Current C, component, and operator bindings stay null. Working spec markers are 9 requirements and 46 scenarios, identical to HEAD. Task markers are 24 checked and 22 unchecked, identical to HEAD. Task 2.10 stays open.

The 640 KiB logical row remains runtime10, operator, plan, packet, and embedded seed (`spec.md:151`). The trusted outer Node caller stays on the separate selected 8,192 B / 24,576 B transcript row. No extra 640 KiB debit is added. No complete caller 8 KiB fit is claimed.

## Limits

C, component, the retention index, and V8 match the prior frozen hashes. No project import, test, native child, or caller run was performed. `authenticate_v1` still requires the reviewed commit to be HEAD, so this working tree cannot authenticate until that commit exists. Actual caller 8 KiB plus new C/D 4 KiB proof, the canonical compiler suite, required exact-commit CI, and the formal final peer/Grok review remain pending.

| Path | Bytes | SHA-256 |
|---|---:|---|
| `gate2_c_v1.py` | 130781 | `1b981e75756598b3b10c7917927feb5295c69f76afcbc96b2af7147b5c14d196` |
| `component_v1.py` | 32730 | `da997d0a2a79e72778bcfd374871a1fdf9fc5173d41419ed68713dddc5650436` |
| `gate2_resume_v1.py` | 32768 | `826c89fa9458792b210bf1155ab33be92780bf35c47b5a1f208d0ae77801f4bb` |
| `gate2-p0-465-retention.v1.json` | 9829 | `ceef345a82f39c8301706ecda73ea5d12cd1cf825e321b9214e409c6a64c2ab7` |
| `component-admission-plan.v8.md` | 40421 | `254e7597e22040fd59c69363bfa826ee6f9a23e85b473255c142cf614426199a` |
| `proposal.md` | 23307 | `c495bc1e07ad24ca75317ab1425dbc8463ee9bf96bb79fdc4cd7e317980d4aa0` |
| `design.md` | 95047 | `9988afc8c768fe909c6ba871440380a37224b9c2cdc12fa4d8e011047ccd2c51` |
| `tasks.md` | 62988 | `ca812c454671cdbda8c770c485245ae2e95a8cb163b386728a38a7b3401289a8` |
| `spec.md` | 45861 | `0ec4c01a416dcb2fd63dfa3cd51b8241de70ec3ccd72c751878d4864b62426d4` |