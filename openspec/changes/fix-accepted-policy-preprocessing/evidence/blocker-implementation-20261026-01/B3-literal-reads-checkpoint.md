# Literal observation and entrypoint reads

The positive producer now reads the fixed image-inspect-map.json and
device-probe-map.json through the existing PhysicalRootCustodyV1 descriptor
adapter, at most 16 MiB each. Custody is verified before parsing; each result
must be an exact dictionary and pass the frozen executor's existing _json_bound
before retention or the next read. Raw payloads are dropped after parsing.
Both producers hash their own entrypoint through a 2 MiB, capture=False
descriptor read and verify custody. The negative producer reuses both adapters.
The frozen compiler and physical I/O adapter remain byte-exact.

Positive producer: 15481 B, SHA256
e600c8ed292b25a4c1bbcd0fc00bed84e3e4e7e810e344ed67d07386266b3fb3.
Negative producer: 12272 B, SHA256
bcd8de1bcd5d97b64d9a2a740464cdf359ccf38eb5a657517ee63cde978cdd52.
New tests: 6891 B, SHA256
872cbced003e57b3e61fbe04a9cfebe87e453b1e1b8208d4a4d630c62f60428b.
The two existing argument-test files only gain adapter doubles; their assertions
are unchanged. Runner: 18634 B, SHA256
ad55c1174f81a99816f7bcf0ed796517310c4a70476c30981a0da6f7ca23078a.

Actual RED: four methods, sixteen intended failures, no errors/skips, 0.215 s.
Result 2187 B, SHA256
a1417313d16ee882734e02e8ddb690133ce0d2579a2df519ed4aa80484e62acd.
The independent working-source/RED/GREEN-recipe review by
/root/blocker_plan_review was CLEAR before GREEN.
Actual GREEN: seventeen methods/thirty-five calls passed, no errors/skips,
0.129 s. Result 2308 B, SHA256
4a591cb91453d548cfc04ab6d8fffd3c09511032e9c43f4a8f9bdfd888394623.
These adapter/argument tests double physical I/O and execute no image, compiler,
native, policy, or reader workload. They do not qualify real descriptor reads.

Both original outer returns report expected statuses, normal D16 child closure,
both EOFs and raw/result write/fsync/close, with no overflow, forcing, unknown
remainder or deadline breach. The twenty-six-member NoCompression ZIP is
265843 B, SHA256
1d2ae12430826660e14364fe15a2b44e2ea9145f635f5a956f4c6e94fbdc8b9e.
Its manifest binds every original; originals remain. Source copies total
111735 B RED and 112993 B GREEN, each 126976 B rounded at 4 KiB, below the
65536 B individual/131072 B aggregate guards. The paired archive/manifest/copy
allowance remains 5 MiB.

The two 16 MiB tranches follow the separate 16 MiB CI-failure preservation
tranche: cumulative 1856 MiB = 1946157056 B; C liability 70.333984375 GiB stays
within 80 GiB above the 40 GiB floor. E's 65 GiB/full 64 GiB pagefile and the
192 MiB source/Git allowances remain. Fresh Windows/Linux configuration, boot,
UUID, free-space, source/hash and collision checks preceded both phases.
Both namespaces are consumed. Exact-commit review, configured Grok and new-head
CI remain pending at this checkpoint.

The negative source-plan selector, literal child captures/raw-source proof,
inherited deadlines and persistence/causes remain open. Pre-parse heap and whole
metadata/capacity terms also remain open. This does not close B3/task 1.5/B4 or
assert genuine consumer acceptance.

Independent exact-commit review by /root/blocker_plan_review is CLEAR for
dc62b6bc0657a172aa82c760b51a22884bd21472, including all archive members and
the four exact live/future-archive attributes preserving original CI log/script
bytes. The configured Grok source-text review is also CLEAR at this commit:
one turn, exit0, 98.727 s, actual modelUsage grok-4.6-build, with no model or
reasoning override. It claims no independent hashes, CRCs, CI or re-execution.
Four-record source-review ZIP 57160 B, SHA256
4adc61688341cb2ef36c13f5aadeaafe33e251a6c63d73d32bb2fc23b884d3bf.
Exact-head CI 40451594787 was still in progress at the latest observation.

Subsequent fresh connector observation confirms run40451594787 SUCCESS at
dc62b6bc0657a172aa82c760b51a22884bd21472. Later source-head34f73eae also passed
40453426015; these CPU/structure/build/test checks supply no genuine acceptance.
