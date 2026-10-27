# Complete reply-map bounds before alias expansion

The physical fixture now reuses the frozen executor's _json_bound on both
complete input maps before set/device-key or map copies. Its fixed _table_bound
checks follow the existing exact two-system probe check and precede expansion.
Image IDs and all alias lists are validated in a first pass. Selected aliases
require nonempty printable ASCII of at most 512 characters; this does not apply
512 globally to Docker metadata. A second pass inserts at most 4096 unique
aliases, refusing a new entry before insertion. Duplicate references consume no
new slots, and alias conflicts retain the prior predicate. Original objects and
the valid 774-character Config.Env value are preserved.

The frozen compiler remains byte-exact. Its combined 8 MiB source preflight
still precedes output creation. A helper-stage 4096-alias test does not claim
that those expanded values also fit the later compiler-source ceiling.
Literal observation-file reads, pre-parse allocation and whole metadata heap
remain separate open terms.

Original physical fixture 32454 B, SHA256
77a404cd7d21abb5c2bb4fb1abf9a9d5f5703ebd4b4dd005f7c6656ccfdb902d.
Corrected fixture 33148 B, SHA256
457df99000878f3b9741aff7aba3f9074759ae05d67a45b4c2874aa75c27b7e5.
Test 5141 B, SHA256
367eb92c72f7a531c59a85f9e784502165d6538bfb606893aff8a57df876f4d2.
Runner 18090 B, SHA256
64458f6bbfd4ea913262cde8154a001e05999fa1ff33de328907a0c420ac0a2a.

Actual RED: 6 methods/14 helper calls, 10 intended failures, no errors/skips,
0.025 s. Result 2195 B, SHA256
8e0f00641bec05ff89a2f6e366a589ca99813368bae3708ed70a54cf75f245c4.
Independent literal-source/RED-disposition review by /root/blocker_plan_review
was CLEAR before GREEN. The six new methods mock custody and perform no physical
I/O. GREEN also selects fourteen existing probe negative/control methods:
these make sixteen calls and create fourteen tiny temporary roots/patch files
with real bounded custody reads. No real-ELF positive is selected.

The prospective 28-call estimate was corrected before admission: GREEN is
20 methods/30 calls. Its additional fourteen-file/root allowance is 1 MiB from
unused paired headroom, making 25 MiB assigned within 32 MiB. The unchanged
probe source is 14501 B, SHA256
df0b70224ba06d11a3f7694bf1c5504afd2f7a50990e8d7a7a9d2b1ea2251a9c,
authenticated before allocation. Its fixed two-system/four-ID patch shape and
bounded mutations are below 4 KiB per file; fourteen payloads total at most
57344 B before already-funded directory/allocation/metadata tails.

GREEN passed all 20 methods/30 calls, no errors/skips, 1.074 s. Result 4276 B,
SHA256 6201030b5662fcdde68f8a0c4b4366d29d76421d4211f6ce719eb87919b7ea8f.
Both original outer returns attest expected statuses, normal owned test-child
closure, both EOFs, raw/result write/fsync/close, known extents, no overflow/
discard, forcing, unknown remainder or deadline breach. Both stdout files are
empty. No actual image/compiler/native/policy/reader operation was selected.

The twenty-member NoCompression ZIP is 238566 B, SHA256
42dfa6cd7c77f2f9085c0ca5f0e8fc701ea418d50408b7cad7296da7ef894421.
Its manifest binds every original; originals remain. Pre-run copy totals are
99480 B RED/100174 B GREEN, below 131072 aggregate/65536 individual guards;
rounded 4 KiB allocations are 110592/114688 B. The ZIP prewrite ceiling was
4718592 B; combined archive/manifest/copy ceiling remains 5 MiB.

Two 16 MiB tranches yield cumulative 1808 MiB = 1895825408 B; derived C liability
70.287109375 GiB remains below 80 GiB above the 40 GiB floor. E 65 GiB/full
64 GiB pagefile and 192 MiB source/Git allowances remain. Each phase had fresh
Windows/Linux physical/configuration/boot/UUID/source/hash/collision checks.
Both namespaces are consumed. Exact-commit review, configured Grok and latest
CI remain separate; whole B3/task 1.5/B4 and genuine acceptance remain open.
