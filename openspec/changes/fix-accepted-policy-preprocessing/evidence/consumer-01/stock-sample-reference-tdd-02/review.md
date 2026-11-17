# Approved Test-Only Stock Reference TDD

Design amendment67b1362fde9463a1e983b49dbc0ee545a5095231 was human-approved
before code in PR9comment6140141307. The code is published at
65c9fa91e2c396265183ec47cb090629ccdd174a, not accepted as complete qualification.

One original RED closed1 on2026-10-13,07:15:09.644384Z through07:15:11.496481Z:
one actual regression failure at the stock reference's missing stream-count
reset boundary, not an import/setup error. One fresh GREEN closed0 at
07:17:19.786352Z:29tests, zero failures/errors/skips,11.427seconds.
Eleven new reference regressions, eight existing real-refusal tests and ten
existing F5 tests ran. Correct three owned overlay imports and unchanged
authored/production/capturer/overlay hashes are retained in original captures.

The canonical ordinary unoptimized CPython3.12.3 used fresh ext4 overlays and
read-only A3 dependencies. An unexecuted earlier capturer lacked explicit
overlay test-package precedence; v2 corrects it and asserts actual module paths.
No frozen source, failed fixture, production stock/F5 or original receipt was
changed by TDD. No complete fixture, Docker/GPU lane or campaign was launched.

All13selected original files,26798bytes, were mechanically mirrored from
the closed red/green controls and sealed v2capturer. Fresh-destination,
1MiB cap and reparse guards passed; every source length/write epoch/SHA256
was equal before/after and every copied target SHA matched. Literal
active/archive attributes preserve original bytes without normalization.

- Capturer6757bytes: `e082c00cb4683d6c225b00cbd1e1d18acca1437e8359b78739fa543fdf4d8464`.
- RED stderr2415bytes: `b8f27f047857c13fbde2db0ffbd2af5e042c4820ad80b998b972ce1df8bd71f2`.
- RED stdout525bytes: `aa2079ada894782ed8a2201e6eae50a3067c52c3045b1d07637d28e1182af5d0`.
- GREEN stderr6473bytes: `f71ea58641eb3b0a4b36563b89610b2b1597e81c79fcca84413894f0720f418a`.
- GREEN stdout531bytes: `988397901ab058556a9cd8d6995e8ee1d907c16730828944b20beb250fedfebc`.

Independent review verifies the whole reference function differs only by its
name and the two approved reset keywords. Real reset/sidecar refusal tests
substitute only unavailable portable upstream acceptance; CPU/GPU sample
unit tests explicitly stub inputs and prove sample semantics only. Comparator
wiring does not invoke substituted inputs as genuine complete acceptance.

After GREEN, a whitespace check removed exactly one extra final LF from the
reference module. All preceding12613bytes are independently equal to the
captured GREEN file. Originals remain unchanged; the final published reference
SHA256 is `eeabb3b44e83f4dff767d3a4ded2235e1694a923517ed231c433d37b6bed7297`.
Renewed exact-input focused/full/hosted/physical and fresh complete consumers
must cover that final input. This reference is not a production assessor and
does not claim unchanged stock-default acceptance or campaign/Q1 authority.
