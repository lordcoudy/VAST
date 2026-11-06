# Preserved original CI failure at 9cf04a1b

Workflow 40436076275, CPU job 121964936115, failed at exact source
9cf04a1b22dcea6e24b0f1be33a2ce8b8ec395ff. The preserved child report records
4578 tests: 4482 successes, 95 skips and one failure; no errors, expected
failures, unexpected successes or missing required successes. The sole failure
is the unchanged sample-count AST test requiring args.samples_per_branch < 30.
That issue was fixed at d9d5813180ad402c5efe720af65fdc88063bf2f1 and its local
14-method caller compatibility run passed. No CI run was replayed or relabelled.

Original uploaded artifact 12704774553 contains 202 members, 3278561 B, SHA256
a5576129cb2fe37dab9ddfbcc7bfe5c8c25515bc4e4dcdb0e9dd2075c64607a6.
The exact ZIP is retained under ci-9cf04a1b-originals. The download verified
Content-Length, guarded each 64 KiB read before a 4 MiB write ceiling and used
one 60-second cancellation token on every HTTP read. Actual size/hash, EOF,
fsync and close passed with no causes. Network timing and file/receipt
persistence are separate facts. There was no automatic HTTP retry.
An expired unused connector lease was refreshed before the sole local download;
no credentials or signed URL are included in these evidence files.

The job log is the exact connector-returned text encoded as UTF-8, not a claim
about raw HTTP response bytes: 202963 B, SHA256
16328985932eb6aa647df998327310bee44577cffb8cf24e74b754f12e15fe5c.
Its original leading BOM is preserved. The first text comparison incorrectly
used ReadAllText, which strips that BOM. Strict UTF-8 decoding of the raw file
bytes subsequently matched every connector-returned character. The file was
not rewritten or normalized. Explicit file fsync/close followed.

Inspection did not extract files. ZIP count/name guards preceded selection of
unittest-child.report.json. Its 2671597 actual decompressed bytes were checked
before every memory-buffer write against 8 MiB and against the declared size.
Framework JSON parsing used depth 32; root keys/count and selected array/failure/
string cardinalities were bounded, and the encoded summary was limited to
16 KiB. The first inspection refused an incomplete expected-key list; its
original return and command remain. The corrected read-only inspection allows
the existing discovery/selection/profile metadata and confirms the sole failure.
Both original inspection returns/commands are retained.

Independent preservation capacity review by /root/provider_route_review was
conditional CLEAR before allocation. ZIP/Git forms have 4 MiB each, decoded
log/Git forms 1 MiB each, records/source 128 KiB and Git/node tails 4 MiB:
14.125 MiB within a separate 16 MiB tranche. Fresh Linux/Windows capacity,
configuration/boot/UUID/source/hash and namespace checks preceded the download.
Cumulative direct allowance is 1824 MiB = 1912602624 B; derived C liability
70.302734375 GiB remains below 80 GiB above the 40 GiB floor. E 65 GiB/full
64 GiB pagefile and 192 MiB source/Git allowances remain unchanged.

This preserves an earlier failure. It does not pass current-head CI, qualify a
workload or close B3/task 1.5/B4, compiler/reader, genuine or final gates.

Independent outcome/identity/manifest/diagnosis review by
/root/provider_route_review is CLEAR. The reviewer verified all eight manifest
members and independently read the same bounded report. The original manifest
remains unchanged. A subsequent labelled source addendum retains the executed
preservation script with only its temporary URL replaced: 19652 B, SHA256
0822de93d7bd6e1eed442b302b212ac5f25d227e07c1b7eaaa6d1774f3b3edb5.
This redacted evidence is not a reusable execution admission.
