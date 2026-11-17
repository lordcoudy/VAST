# Preparation socket ownership and error preservation

Both preparation socket constructors now lie inside the existing guarded body,
with front/control initialized to None. A failed second constructor therefore
still closes the first owned socket. Both closes are attempted even if the first
raises. The initiating error remains primary; identity-distinct cleanup errors
retain their order. An error alone is raised unchanged. With secondary errors,
a private wrapper retains the original objects and chains from the primary.
Original exception .facts and the captured-engine holder are unchanged.

This slice does not report per-socket allocated/attempted/completed/unknown
closure facts and does not qualify successful physical closure. The inner
accept/connection/setblocking-restoration cleanup remains separate work.

Original physical fixture 31557 B, SHA256
6ad53880abcf884ded9546187fd1b01989f482960fd7cd561706ca5b57cc27c0.
Corrected fixture 32454 B, SHA256
77a404cd7d21abb5c2bb4fb1abf9a9d5f5703ebd4b4dd005f7c6656ccfdb902d.
Test 5710 B, SHA256
691f82c8668bda0b25a0d6f9a4ceeb820d7e757d4d1f623d4b415342ab1b699f.
Runner 17658 B, SHA256
a885d62420de7070bba2d9e5a67ef29e14b9cd7519e9ca03259cac1102c2d441.

Actual RED: 7 methods, 6 failing methods plus two original-cause control
subcalls, no errors/skips, 0.028 s. Result 2190 B, SHA256
6d95982c8090cf65a9eb15de71799570b669d5732c57c6ce2e97b3c2ab762c94.
The failures demonstrate the leaked first socket, lost initiating errors,
skipped second close and missing distinct cleanup causes. Independent exact
working-source/GREEN-recipe review by /root/provider_route_review was CLEAR.
Unchanged-test GREEN passed all 7 methods/8 calls, no errors/skips, 0.020 s.
Result 2196 B, SHA256
21a9db6b1048535572b17fabd6cc08bde68e64f0d1df09f1a5710176ab6af97d.

The tested sockets, directories, temporary-root creation, clocks, map/preflight
and engine providers are doubles. Real source-root metadata is inspected, but
no real socket/compiler/engine/native/policy/reader subject runs. Both stdout
files are empty. Original outer returns attest expected child statuses, normal
owned test-child closure, both EOFs, raw/result write/fsync/close, known extent,
no overflow/discard, forcing, unknown remainder or deadline breach.
Those are test-capture facts, not facts about mocked socket retirement.

The NoCompression ZIP and manifest preserve twenty originals, including five
pre-run source copies per phase. ZIP 225839 B, SHA256
6a9ae32e785258ca0600b5335052426756155c4805fdd43a0df69d4e635fabf5.
Originals remain. Five source copies total 98720 B for RED and 99617 B for GREEN,
both below 131072 B aggregate/65536 B individual guards; their 4 KiB file
rounding is 110592 B each, with metadata separately reserved.
The combined archive/manifest/copy ceiling is 5 MiB; its ZIP prewrite ceiling
was 4718592 B. Two 16 MiB tranches assign 24 MiB including that combined term.

Cumulative direct allowance is 1776 MiB = 1862270976 B; derived C liability
70.255859375 GiB remains below 80 GiB above the 40 GiB floor. E 65 GiB, full
64 GiB pagefile and 192 MiB source/Git allowances are unchanged. Each phase had
fresh Windows/Linux capacity/configuration/boot/UUID/source/hash/collision checks.
Both names are consumed. Final exact-commit review, configured Grok and CI remain
separate; full B3/task 1.5/B4/compiler/reader and genuine milestones remain open.

Subsequent independent exact-commit source/evidence review by
/root/provider_route_review is CLEAR at e8dcfbfd187f2d594f37f117364996f26bed00a5.
It verified both archive member sets, CRCs, hashes, original bytes and outcomes.
The configured Grok invocation returned scoped CLEAR in one turn, exit 0,
130.084 s. Its actual modelUsage records grok-4.6-build; the invocation supplied
no model or reasoning override. Preserve this observed identity separately from
the preceding caller review's grok-4.7-build identity. No configuration change
was made; post-run hash/size/write time are in the derived observation.
Grok reviewed supplied hash-checked source texts; it did not claim independent
hashes, CRCs, execution, CI or physical socket closure. Exact-head CI 40439765020
was still in progress when observed. No delegated stage approval follows yet.
The five-record source-review ZIP is 65216 B, SHA256
93e53d7f7d81f3eafa4c25bf52d7f8a20195927a80e1b6b63c9ea84d8c2b3101;
all raw originals and the labelled derived observation remain in place.
