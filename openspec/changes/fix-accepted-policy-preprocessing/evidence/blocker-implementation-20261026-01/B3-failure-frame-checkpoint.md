# B3 fixed producer failure-frame source checkpoint

Same C: worktree, branch and Draft PR9; base8b76aefff3a3ba0fec8222aa4af6bf86c1b15803.
This is a controlled source repair. Exact-commit review, configured Grok and
latest-head CI remain pending at this checkpoint. No task is newly checked.

Both CLI tails now catch after main/source unwinding and make at most one checked
unbuffered stderr write. The frame includes LF within485376B; partial/failed
delivery remains nonzero with no retry or implicit traceback. Parser-origin
identity distinguishes help/argument exits from a body's SystemExit0. In-process
main() still raises its original error objects and forwards no extra default
keywords. Unknown exceptions cannot supply names, str/repr, equality, hashes,
notes or arbitrary attributes to the frame.

Fixed state retains the actual source context, named report encoding/writer/clock
events, assessor return and cold-reader return/call-site argument. Facts project
once in fixed roles; errors have bounded identity links/short metadata. Intended
paths/encoded hashes, retained-channel hashes, confirmed raw-file prefixes and
returned persistence remain distinct. Exact canonical compiler errors expose only
bounded causes and heterogeneous-facts availability, with no qualified reference.
The frozen compiler, D16 owner/program and report encoder are byte-unchanged.

The shape/contract audits and review-corrections document describe the fixed
geometry. Independent blocker/provider reviews accepted the implementation
corrections without a formal OpenSpec amendment; capacity review confirmed the
same byte ceilings. Its first cases-archive proposal had a missing leading t in
the literal path roster; independent review caught it before any archive attempt.
The corrected command was reviewed and used. No original bytes were modified.

Actual local execution, each phase once:
- RED:3methods/five intended callback/directory assertions,.043s,noerrors/skips.
  Child1/outer0; stderr5925B; bothEOF/normal closure/no forcing; actual outer
  resultwrite2560B with fsync/close.
- GREEN:88methods including22new,1.066s,noerrors/skips. Child0/outer0; normal
  closure/bothEOF/no forcing/overflow/unknown/deadline; actual outer resultwrite
  2722B with fsync/close. No replay.
- Exactly six tiny Python CLI cases produced statuses1,1,1,1,0,2. Production mains
  were forbidden sentinels; the same CLI/parser/codec ran with controlled entries.
  The separate definition-only __main__ namespace/AST-tail control covered owned
  class identity and actual wiring without another child or case file.
- The maximum synthetic frame is273513B, SHA256
  2ebef1dc83d55611c6dabc9b9fe0b86d6f7fbad3d904b494e292982f9b2cfbe4.
  Assertions retain22worst640-codepoint references,6captureblocks each with64codes/
  identities,64errors,64compiler codes and11preceding+onefailed sidecar records.
- Seven fresh C: case directories retain19files/293423B. Their seven writer
  receipts were returned in outer stdout; none self-attests its future writer.
  All15 GREEN source originals match the final264608B reviewed/current pins.
  Independent /root/blocker_plan_review verified these exact joins.

Byte-exact original archives, all loose originals retained:
- RED:21members,255752B,SHA256
  d0a3c887c8ef368641215535d0dc1bc7204337684319855ae326b0bac9cefd1b.
- GREEN:21members,309430B,SHA256
  be0d4249ae1fc2c5523d49e730579c6aafe98f71c3267fe82dcea517fd8dead7.
- Cases:19members,297753B,SHA256
  b67b4b13a805b8d15b933086ac5edc1d39d32eb6a1c12a65108968ea67b232d0.
The bounded audit checked all61 CRCs/manifest hashes/loose-original joins and all
15 current source pins. Original command/admission/tool returns are retained.

Capacity review admitted only this96MiB pair:91.75MiB rows plus4.25MiB slack,
then explicitly charged256KiB slack for archive command/return/Git forms, leaving
4MiB slack. Cumulative direct allowance2192MiB=2298478592B; derived C additional
quote71.099609375GiB<80GiB above40GiB. E65GiB/fullpagefile,source/Git192MiB and
prior448MiB VHD scatter remain. Fresh Windows/Linux floors, units, same Ubuntu
boot/UUID,21B config hash,<=24GiB RAM/6GiB swap, source pins and fresh namespaces
passed before each phase; archive guards were renewed. No cleanup/sharing credit.

This closes neither complete compiler fact transport nor actual environment/
heap/other-stderr/drain/deadline fit. Whole1.5, actual compiler/reader admissions,
receipt-bound Docker probes, lifecycle atomic-publication repair, runtime renewal,
parity/tensor/identity pins, genuine3840-first/3968/promoted126016/29/20/42,
nine physical integrations/conformance/archive/final review/merge remain open.
Dedicated conformance CI is absent; no CI redesign occurred. Tasks stay24/46.
D27/Native57 remains parked; freshQ1/Q4/fullcampaign follow repair acceptance.
