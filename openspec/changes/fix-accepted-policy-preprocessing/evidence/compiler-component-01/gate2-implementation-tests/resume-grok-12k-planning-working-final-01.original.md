**CLEAR_WITH_NOTES.** Working-hash planning review only. HEAD stayed `69c2c35f3d51c8d4ef047e7050fe82bfc3b79eae`. The five-file set matched at the start and again at the end. This review does not approve the amendment, CI, a planning commit, cap/index/test edits, source, or physical admission.

| Path | Bytes | SHA-256 |
|---|---:|---|
| `openspec/changes/fix-accepted-policy-preprocessing/proposal.md` | 24499 | `e0d0a935441dc1acbaa01ffa16ae38224e8338f4fdb12e7314f6924831cba0e8` |
| `openspec/changes/fix-accepted-policy-preprocessing/design.md` | 97284 | `ad0602c0eed1d23b7fd71364636fff6982e67fbe65c929a2ac56acf3eb027397` |
| `openspec/changes/fix-accepted-policy-preprocessing/tasks.md` | 63840 | `7819e35329552fddb0f1c2807c8f5565b59192524fce2ead3b206809b5c202bd` |
| `openspec/changes/fix-accepted-policy-preprocessing/specs/benchmark-launch-preparation/spec.md` | 47148 | `03435da132c4217f0033943c1dbd6fbb068900c081b9403961cb53e5f2efe0c0` |
| `openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/component-admission-plan.v8.md` | 40901 | `dc130a657a7c582c084f364425773f17e2487afb95cd65825e2e815041cf83d6` |

Provenance report `vast-gate2-resume-frozen-caller-bookkeeping-96.original.txt` is 4515 bytes, SHA-256 `a250a34d7302727bb99bd75153cc365b4f09fe0eba2adee436200a592b4e4bd1`.

## Findings

No blocking defect. The five documents describe the same amendment, and the stated accounts close.

The measured caller remains an 8 KiB failure. The report records whole selections of 9629, 9449, 9457, and 9445 bytes, each with `approved_8k_refused: true`, each rounding to 12288 at a 4096 quantum, and each with `physical_acceptance: false`. Raw Node is 16883 bytes, the carrier is 7553, and the four producer bodies are 1635 / 1338 / 1469 / 1336 with distinct SHA-256 values. The report’s component row `da997d0a…` (32730) and operator row `f11eece4…` (32738) match the current working files. Proposal, design, spec, tasks, and V8 all say 9629 is above 8192 and that this is a bound amendment. V8 §8.5 still says that a producer bound which cannot fit stops for amendment and review. The first 25355 bytes of V8 are unchanged and still SHA-256 `f024bfccb48e26be34b05b05fbc16082791b134f82967613177ad81a916d2d94`. The first differing byte versus HEAD is offset 34559.

Canonical escaped selection is 12288 on the one repository path `evidence/compiler-component-01/gate2-p0-exception.outer-tool.original.json`, with working plus Git at 32768 and no third Temp form. That pair is `2 × (12288 + 4096)`. Logical membership stays runtime10, operator, plan, packet, and embedded seed. The caller is priced on the selected transcript row. Deadlines stay 150 / 140 / 10 seconds, with at most six actual frames, sole operator stdout 2048, events 8192, Info whole-wire 16384, native row 1019136 inside 1048576, packet 32768, and C/D 4096 frames. Unavailable, truncated, or non-JSON results stop before the writer. The writer result and the same-Node post-return clock check stay outside the file they verify.

ACK arithmetic holds for the canonical four-key writer object (`remaining_ms`, `selected_base64`, `sha256`, `size_bytes`), sorted, compact separators, plus one LF. A 12288-byte selection is 16384 bytes of base64. With a 6-digit `remaining_ms` (the existing maximum is 150000), the ACK is 16524 bytes. The documents set the input ceiling at 24576 before decode, EOF, and source authentication. Setup’s empty-selection ACK is left unchanged. The 8192 selection guard and the 24576 transcript pair stay the implementation bounds until a later approval; these planning files do not change them.

Closed accounts, recomputed:

- Outside: `399872 + 32768 + 29952 + 20992 + 32768 = 516352`, remainder `524288 − 516352 = 7936`. The 8192 increase is the transcript pair moving from 24576 to 32768 inside the already funded 524288 row.
- Global: `535785472 + 1032192 + 16384 = 536834048`, remainder `536870912 − 536834048 = 36864`. The only global delta is the source-cap increase `1032192 − 983040 = 49152`.
- Initial debit `29323264 = 29274112 + 49152`. Future liabilities stay `402653184 + 25165824 + 77594624 + 2097152 = 507510784`. Available future is `536870912 − 29323264 = 507547648`, remainder 36864.
- Source: prior sum through the superseded 465 Git forms is 946176. Adding the retained 69 plan Git form 45056 gives 991232. `1032192 − 991232 = 40960`. One further 45056 form reaches `1036288 > 1032192`. Plan two-forms 90112 equals `2 × 45056`. C, component, and operator caps stay 128 KiB / 32 KiB / 32 KiB, with the same form charges 270336 / 73728 / 73728.
- Tail after the maximum: `32768 + 12544 = 45312`. N stays `≤ 2650112`, old F2 `5345280 + N ≤ 7995392`, combined F2 `8388608`.

Index seam holds. Four historical roles and 69 row 16 stay. The approved plan blob is appended as version index 21 only after planning approval. `current_bindings[10]` is null, and the current plan comes from outside the index. There is no fifth role, no index self-hash, and no future-consumer hash. The new index is still required to fit 12288 encoded and 32768 for the working/Git pair. The old derived index stays development evidence, with no extra active Git form.

Scope holds. The spec still has 9 requirements and 46 scenarios. All 46 scenario titles match HEAD. The only scenario-body change is scenario 41, `escaped8` to `escaped12`. The other 45 bodies are byte-identical to HEAD. All 46 task IDs and checkbox states match HEAD: 24 checked, 22 unchecked. Task 2.10 remains `[ ]`. The source-inventory alias sentence is in the proposal, design, spec, and tasks: frozen pre-implementation versions only, an unchanged-byte alias grants no current approval, and external authority binds the current runtime, operator, plan, index, and approval.

## Notes

V8 is 40901 bytes. The 40960 cap leaves 59 bytes. Any further V8 wording has to stay inside that spare. The source margin of 40960 is one V8 file cap and is smaller than one more 45056 plan-Git form, so a second distinct planning Git variant overflows 1032192. The documents already say to retain that variant and refuse it. Working corrections belong in this tree before the one planning commit.

The planning sentences cite the 9629-byte success selection. The report’s failure, Unicode, and late selections are also above 8192 and also round to 12288. They support the same 12 KiB row.

## Evidence limits

No project import, test, native call, worker, or probe was run. The 9629-byte figure and the other three selections were taken from the hashed provenance report, not remeasured here. The canonical ACK size was recomputed with the standard library from the four-key shape. No new index was built, so the future 12288/32768 index fit is a requirement, not a measured result. Same-FD allocation was not queried. Task 2.10, whole 1.5, genuine 2.8/5.3, renewal, archive, and merge stay open.