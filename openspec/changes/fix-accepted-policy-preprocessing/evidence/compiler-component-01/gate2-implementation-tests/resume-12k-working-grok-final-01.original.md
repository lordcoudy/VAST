BLOCK

Working-tree review of `fix-accepted-policy-preprocessing` at planning HEAD `b5f64480cccddebf3656e8c17c6520d448e26d7a`. All 56 manifest entries matched size and SHA-256 before and after the reads (`END_CHECKED 56 BAD 0`). This binds those working bytes only. Implemented-commit review, implementation CI, physical admission, task 2.10, whole 1.5, archive, and merge remain open.

## P1 — fallback EOF without a confirmed stdin error listener

`tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py` line 177, inside `NODE_CONTROLLER` (`8519` bytes, SHA-256 `5996c35b5df9c447dcd9af275e8b24ec33493c5552b3eacd049224b3659dbfaf`).

`tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py` lines 1141–1142, inside `CD_FACTORY_SOURCE` (`10764` bytes, SHA-256 `61c870e380070f4c05f1f50c52d1f8a9943923a75eeb5897b1d3e824a4961d99`).

Scenario: tracking throws before a stdin `error` listener exists. The fallback then calls `emitter.on`. If `stdin` is absent, `on` is not a function, or `on` throws, the setup path records `listener_error` and the C/D path records `cd_<role>_stdin_error_handler` or skips the emitter. Both paths still call `g2.send(s,'')` or `child.stdin.end()`. A real Node `EPIPE` is an asynchronous `error` event. The `try` around `end` retains only a synchronous throw. With no listener, that event is unhandled and the retained child, PID, and first cause can be lost. Current tests emit repeated errors only after `on` has succeeded.

Fix: call the one owned EOF only after the stdin `error` listener is installed. If it is missing or installation throws, keep the first cause, a distinct listener failure, unknown closure, and unknown stdin extent, and do not call `end` or `send`. No ACK, BOOT, retry, or signal.

## P2 — external root delivery is not a C/D predicate

`tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py` lines 392–404, `ROOT_ORCHESTRATOR` (`2552` bytes, SHA-256 `0c94708f4e97a029bc79d3b75462bac5def4f0998c57dbcd631f268a7cc9b7e6`).

`tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py` lines 1170–1172.

Scenario: `gate2Complete` stores `writer_call` and `verification_call` before each await, then sets `retention_complete` and returns the root object. It takes no executor output allowance and does not require an external untruncated record. Host truncation happens after that return. `cd.begin` authorizes the next stage from in-session `retention_complete`, `setup_success`, and pins. The geometry specimen at line 1265 carries `max_output_tokens: 4096`. Conformance v2 states measured complete root records of 49714 bytes on Windows and 49690 bytes canonical, and that a token request is not delivery. A 4096-token or default 10k-token return can drop the terminal tail while the same session can still begin C/D.

Fix: before physical use, require an explicit output allowance large enough for the actual serialized external root record. Accept only an untruncated return that contains the terminal tail and the full provenance. A requested token count is non-accepting. Do not add a third owned capture file. `cd.begin` must require that external delivery proof.

## P3 — conformance v2 misstates preserved raw 124

`openspec/changes/fix-accepted-policy-preprocessing/evidence/compiler-component-01/gate2-resume-implementation-conformance.v2.md` (`42736` bytes, SHA-256 `120ab126a3a45e1e6e079d8dab2c5513d158345dc106c687636addac7245fa4f`), the raw-124 sentence.

The preserved file `vast-gate2-resume-thread-poll-green-124.original.txt` (`1034` bytes, SHA-256 `8159c5540badfab7cde6bc193235ae36933ab7c41a96983e7dd7cd7d8853ca86`) is a failed poll-path run: stdin close list `[1, 1]` versus `[1]`, `FAILED (failures=1)`. It is not a BytesIO destructor log. Raw 122 (`5484` bytes, `f112ef8a69dca60364101df4466d18fde0e3e149afae991df45c12ba49d38e21`) and raw 123 (`3817` bytes, `d63d7731e02aa3df46e43c80d2791dc1e112fb7c55188ebcea1646bcb2796949`) remain the earlier thread-start and walrus-repoll errors. Do not rename or overwrite them. Correct the conformance sentence to the preserved 124 failure.

## Bound bytes

Operator `tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py`: `32739` bytes, SHA-256 `5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670`. Its `NATIVE_BOOTSTRAP` literal is `1415` bytes, SHA-256 `7c28da7371dea8407c77fd0edc8f39218819a580eb195086c7a44a7b69c3b65a`.

Resume test: `154649` bytes, `835d5473edd935b895d6fe2f141f8cee2bbbfd3120fc3f9084a4b5a0b0d12f39`. Caller test: `113415` bytes, `ad7622b6785c8f3c06df8e362971a3c9f426bbfdd3235dc6fa4d0aecbc860b6a`.

C fixture: `130783` bytes, `5a6c4b08ce3d381c355cbf72f93057c991b4adcb9d6ca8c43a638acd64f2ecf9`. Component: `32732` bytes, `329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88`. P0: `69194` bytes, `3cb7ebf819ac8db49458ea909a08b306602fa4f45984482c020572132ce9a903`. D: `48660` bytes, `31c3a7c92ad96cc2357ebb091b666c52faa1f3a214109419f2489d89e10d1bbb`. D-child: `19404` bytes, `f230fd6fd88d0b99309d3ec5b12a942a05c6ac131062ace734033a1fe2e8c013`.

Index: `9998` bytes, `d310418f13e8a0afd287a1d774056ace70287f1d37a5841270a52e8dc5f8109c`. Literals 128: `4001` bytes, `bc0a0abc531923222eaa1f377d08825dabd91c3669d8fce2bc62365c5a713b60`. AST hashes of `NODE_CONTROLLER`, `NODE_FINISH_BODY`, `NODE_HARNESS`, `NODE_WRITER_VALIDATORS`, `ROOT_ORCHESTRATOR`, and `CD_FACTORY_SOURCE` match that literals record.

## Finding disposition

The index has four roles, 22 source versions, and `current_bindings[10] = null`. Version index 21 is the plan blob `8cf0afbf9dd122de6acb5682d9e470e4eacec358`, `40901` bytes, SHA-256 `dc130a657a7c582c084f364425773f17e2487afb95cd65825e2e815041cf83d6`. The planning role commit remains `69c2c35f3d51c8d4ef047e7050fe82bfc3b79eae`. The file does not contain its own SHA-256 or the `b5f64480` commit id. It is an untracked prototype. Current source, plan, and index equality is not approval.

`CURRENT_CODE_FORMS_V1` remains `524288`. `RESUME_CODE_FORMS_V1` remains `1032192`. `resume_final_v1` uses `future = 32768 + 12544` after the child walk and parent growth, and outside uses the 50944 AUX/Info control cap. Index limits record source candidate `991232`, outside candidate `516352`, global candidate `536834048`, native candidate `1019136`, fresh interval `2650112`, active F2 `7995392`, and logical `655360`. The live quote function was not executed, so those totals were not recomputed from a walk.

The live P0 writer is the third body: `MAX_SELECTED_BYTES=12288`, `ACK_CAP=24576`, four ACK keys, write cap `12288`. `writer_started` and `writer_attempted` are set before spawn. Track and both fallbacks record the returned child and PID before listener installation. Root `setup_success` starts `null`. A retained failed setup is setup false, retention true, completed false. `verifyReturn` samples the clock with `cdGate` before `retained` and `cdIndex`, reuses that sample, and refuses a sample equal to the stage end. Operator `Thread.start` is inside the process `try`, and the final facts reuse the last `p.poll()` value. The stale 8192 writer remains as the standalone and qualified-reuse specimens.

D and D-child hashes match the frozen manifest. P0 `c_or_d_invoked` is required false. The C/D factory narrows the later writer to 4096/16384. `physical_acceptance` stays false.

## Evidence inspected and not executed

Inspected the approved proposal, design, tasks, spec, and V8 section through the matching planning blobs; conformance v2; the index JSON; operator `process`, `write_fixed_v1`, and `NATIVE_BOOTSTRAP`; C `resume_final_v1`, `validate_resume_retention_index_v1`, and `complete_c_invocation_v1`; component `resume_code_forms_quote_v1`; both Node/root/caller modules, including the three stacked writer literals and the C/D factory; literals 128; author logs 126 and 127; raw 122–125.

No fixture entrypoint, unittest, Node harness, WSL, packet, C/D, API, or physical command was executed. The manifest’s 753-test result and logs 126, 127, and 125 were not rerun. Planning CI `38988664904` and comment `6228062438` were not rechecked and do not approve these working bytes. The 227 protected images were not touched.