# Exact Corrected-Input Hosted Checks

Existing workflow38251020884, attempt1, completed SUCCESS on actual source
`a2fc7f464cc71b89ff1453132bf254a0abeea5e8`. GitHub plugin independently verified
the run SHA/conclusion and both completed successful jobs114817042278/114817042668.
No CI configuration or skip policy changed and no run was retried.

Original artifact ZIPs were downloaded once through native authenticated HTTP,
each HTTP200 and exact GitHub artifact length/digest match. Archives were not
recreated or normalized; credentials and signed redirects were not retained.

- CPU artifact11749895729:2811415 bytes, SHA256
  `165030b3e3da4e6937620a07f641e9391cc91ac2f83ef7bdbd16206991088a9e`.
- Diagnostic artifact11746994235:918460 bytes, SHA256
  `e405732ff98d27bac6202ed425d7fbf5ee9c75f56f71f4f55b4aabbd5e87ed36`.

Audit selected the exact CPU `report.json` ZIP entry, not suffix-matched model
acquisition reports. Report SHA256:
`775686ca96588aac51a84e677e7ab21eb2ef2259fbf300425df182890a1d07c9`.
It reports exactA2, successful/raw committed-byte match and no changed tracked
paths:3332 discovered,3323 executed,3235 successful,88 skips, zero failures,
errors, expected failures, unexpected successes or missing required successes.
All536 Python/16 Bash syntax inputs and six native targets passed.

Independent parsed JsonNode.DeepEquals comparison with exact06 found both the
entire skip ID/reason array and complete portable skip audit identical:78
platform/explicit prerequisite plus10 retained retired-schema skips. The nine
physical cases were executed separately in the local corrected-input lane.
External observer:31 responses completed, return0, both trace/control EOF and
successful=true. Original-child completion is not arbitrary descendant quiescence.

This is hosted CPU/diagnostic evidence, not hardware eligibility, full local
suite acceptance, complete consumers or Q1. Remaining gates are recorded in
`../sourceA2-checkpoint.v1.md`. Original diagnostic outcomes remain in its ZIP.
