# Caller compatibility correction after independent review

Independent exact-commit review by /root/blocker_plan_review and configured Grok
both requested changes at 9cf04a1b22dcea6e24b0f1be33a2ce8b8ec395ff. The new
positive sample gate was behaviorally equivalent at the lower bound, but its
chained comparison failed the unchanged regression test's explicit AST contract.
The existing test was retained. Restore args.samples_per_branch < 30 and keep
the upper-985 guard as a separate comparison. No numerical rule is weakened.

Corrected positive caller: 14242 B, SHA256
34d0a264d735209aa96ae281e47b938ce48d55e747769a6f40658a0cbedfeed6.
The negative caller remains 12253 B, SHA256
c5a09a16b8d430b95d42ec6bcb9f427333b5ffc391d14cb95f464559a231069e.
Runner: 17241 B, SHA256
0b2db224bff06e502275c90554d2fe2f62e8346251a00d853893bb71976b5166.
Unchanged sample-count regression: 8316 B, SHA256
3f0f0169a472b166a31dc985750810c36c811bb061f1d458e3bf6eafb1c40c02.

The once-new callercompat-green-01 roster contains the eight positive argument
methods, five negative argument methods and only the named existing AST/signature
regression method. Fourteen methods passed, 0.141 s, no failures/errors/skips:
nineteen doubled driver calls plus one AST check. The sample-count module's real
native-generation method was not selected. This is caller compatibility coverage,
not genuine consumer or compiler/reader execution.

Original result 2446 B, SHA256
e761a35ae931f23c5f18b0da90f6ddb443108c7586b8959de1250eca1f5da44c.
Original parent return attests outer/child exit 0, normal owned closure, both
EOFs, raw/result write/fsync/close, known extents, no overflow/discard, forcing,
unknown remainder or deadline breach. All originals remain in place.
The 13-member NoCompression ZIP is 124543 B, SHA256
9c2688f9d77e689956d5fb6e184eaf184893087aab3154cdff6d7d5c8fe483c6.
The manifest binds all originals. Prewrite ZIP ceiling 2228224 B plus manifest
fits the 2.25 MiB archive allocation. Eight pre-run source copies total 111273 B,
below 131072 B aggregate and 65536 B individual guards.

The prospective capacity recipe was independently CLEAR before fresh execution
checks. This extra 16 MiB tranche assigns 11.75 MiB including capture, records,
copies, archive, review and Git/node tails. Cumulative direct allowance is
1744 MiB = 1828716544 B; derived C liability 70.224609375 GiB remains below the
80 GiB reservation above the 40 GiB floor. E 65 GiB/full 64 GiB pagefile and
192 MiB source/Git allowances remain unchanged. Fresh Linux/Windows physical,
configuration, boot/UUID, source/hash and collision checks preceded execution.
The namespace is consumed.

Configured Grok's initial three-turn attempt ended without a verdict and is
retained as incomplete. A one-turn continuation returned REQUEST CHANGES for
the same P2 and no other actionable finding at 9cf04a1b. This correction and
the negative caller still need final exact-commit review/Grok/latest-head CI.
No stage/whole-peak/physical/genuine/final approval or task completion is claimed.
The six review originals are retained in a NoCompression ZIP, 48636 B, SHA256
64b08dca29a20184cf4d5e73ab600518dce7c31ccce2b444f7a9d3e09c7d9d64.
The actual configured model was grok-4.7-build; no model override was supplied.
Independent provider review subsequently confirmed the exact correction/roster
and observed that the compatibility namespace was already consumed; it does not
claim a fresh execution release. Its raw source-copy sum is 111273 B and its
4 KiB file rounding is 131072 B; metadata has its separate reserved charge.

Subsequent exact-commit source/evidence review by /root/blocker_plan_review is
CLEAR at d9d5813180ad402c5efe720af65fdc88063bf2f1; all 39 members across the
three newly committed archives were verified. Configured grok-4.7-build also
returned scoped CLEAR for that exact commit in one turn, exit 0, 170.570 s.
It reviewed hash-checked source texts supplied in the 36496 B prompt; it did not
claim independent hashes, CRCs, re-execution or physical proof.
Its four retained review originals are in the correction-review ZIP, 66797 B,
SHA256 a42ed3c3baa69b86e404518e6a920d1f0c9a87cab45b3f0428b12fa283b810bb.
CI 40437647170 was still in progress when observed. No CI or delegated stage
approval is inferred from either source opinion.
