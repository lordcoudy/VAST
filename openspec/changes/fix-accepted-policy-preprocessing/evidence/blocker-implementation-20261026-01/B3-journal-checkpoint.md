# Bounded journal header and owned cleanup, scoped B3 checkpoint

The previous journal read the first native line with unbounded `readline()` and
`json.loads` before the unchanged native iterator. Its recorder `finally` could
also replace a read/finish failure. The new purpose-specific header reader uses
the existing strict JSON/canonical form,64KiB header ceiling and64MiB native-file
ceiling. It checks the descriptor, original regular leaf, held parent custody,
non-following/nonblocking opened identity and post-read file epoch. It reads at
most65,537B before parsing, then closes its own buffer/raw FD/custody. The existing
iterator still owns full replay, final native hash/count validation and scientific
predicates; this duplicate header read is not independent authority acceptance.

The original15-method RED ran against journal6407B/SHA
842dfb9df87019b80b51a46949b7283077736dddd133da4c2f4d8663d88bd069:
16assertion/subtest failures, no errors/skips,0.026s. It reproduces unbounded reads,
missing early line/shape/custody checks and masked initiating failures. Its exact
9291B test964f55ba1201aca731b419ba8afa57e8310ad4886684687d73aa80264eaf635d
and12816B runnera33e8cc01830292e5081949228a0dd82fdcea308648776e32ae7b026b318684b
were copied before invocation. Result2173B/SHA
6fd9bc9373eb13b97e60b5e3202563e0117615b0c391491344ac4f1736377b23.

Independent source review found a P1 before GREEN: default `fdopen(closefd=True)`
can close its raw FileIO when buffered construction fails, leaving the outer
owner to close a released/reused integer. Preserve that rejected journal
627a55107c2f7835e0cfe0d805b5d3c855b16675728a891c5341321c81b1b331
and the original RED unchanged. Two added tests model partial construction and
normal explicit ownership. A separately named/priced owner RED ran only those
two:2failures/no errors/skips,0.006s, exposing two closes and zero explicit closes.
Result2429B/SHA6890ba40ca6a430a55b2a086867988dc21d3ff08091eff38f5f1e8bc2b53fe35.
The correction uses `closefd=False`, retaining raw ownership through construction,
then buffer -> raw FD -> custody closure. Original initiating objects and distinct
cleanup objects survive without formatting their messages; identical objects
are deduplicated. An enclosing recorder close retains rather than replaces them.
The source basis is [CPython fdopen](https://github.com/python/cpython/blob/v3.12.0/Lib/os.py#L1031-L1037)
and [buffered construction cleanup](https://github.com/python/cpython/blob/v3.12.0/Modules/_io/_iomodule.c#L317-L445).

Before the unused GREEN, independent review accepted exact corrected journal
10550B/SHA5cffe02d773ac6eeb247015a1d83dc3d7848ce64c3cb119dc581864dc6f9dc4a,
test10151B/SHAee262eae31a73e8adb2eb25b669d2443dea9454580c2ace05888c6acb591a1f6
and runner13363B/SHA511189f527913ca1b4b795c6d62482f32dfdfb24df32953a71322c8f3e0cae22.
GREEN passed17new+9prior reader-adapter methods=26,0.018s, no errors/failures/skips.
Result2230B/SHA2bc5f55b1df3f65b179364083063d35e8d243c00dc846052ecb61fdc70424f35;
stderr5126B/SHAd4a923f517d697403a756bb864bbe2e17ba9230bd08d42a5ada9cd6273bf4ab6;
stdout0. All three phases have normal owned closure, both EOFs, no overflow,
discard/unknown remainder, force, signal or deadline overrun and completed raw
write/fsync/close/result persistence. Every phase name is consumed, not retryable.

The24-member ZIP/manifest retains all three admissions, exact captures, outer
tool returns and nine pre-run source/test/runner copies. Archive144501B/SHA
d233fd54829e16aac402a66acede7c1ff6a86e7b316181325f9eadf8f50ebe69.
All local originals remain. NoCompression ZIP overhead was bounded before creation;
no compression/cleanup credit was used. Two16MiB tranches plus the separately
reviewed ownership16MiB tranche put cumulative direct-file allowance at1504MiB
(1,577,058,304B), derived C69.990234375GiB<80GiB above the40GiB floor.
E65GiB/full64GiB pagefile and192MiB cumulative source/Git ceiling remain. Fresh
Windows/Linux/config/pagefile/USN/root-UUID/boot/source/collision checks preceded
EACH phase; the prospective diagnostic volume was not created or funded by this
preparatory seal. No existing storage/configuration/service/image was changed.

All filesystem/FD/reader/replay/recorder effects are doubles. These tests do not
qualify unchanged helper internals, real native replay, compiler, Docker, reader
admission, physical/genuine consumer execution or whole task1.5. Exact-commit
source/outcome review, completed configured Grok and current-head CI remain
required. Full B3/preparse/caller bounds, B4 peak and other acceptance gates remain
open;46/24 task states and D27/Native57 disposition remain unchanged.
