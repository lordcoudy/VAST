# Seven fixed-role artifact reads, scoped B3 checkpoint

Replace seven unbounded `Path.read_bytes()` calls in the current physical fixture
with inline use of the existing PhysicalRootCustodyV1 bounded capture API and
verification before the existing parse/forward operation. Image patch and candidate
capability use16MiB; original operation1MiB; source plan/calibration16MiB each;
native payload and runtime receipt64MiB each. No generic loader, default reader,
schema, executor, provider, predicate or compiler authority changes. JSON behavior
and exact original native payload are preserved. Transient JSON input references
are dropped after parsing; this is not a claim that process RSS is reclaimed.

The9-method RED runs each selected read through the public fixture path with
bounded I/O/setup doubles and no actual artifact/native/compiler execution:
9failures/no errors/skips,0.023s. Original physical24596B/SHA
2de98c617931dad711a794b1ea2de3f0080c92988efff67c7acaa48ebb664bb6,
test6791B/SHA2fbe138736df76ed9c750f4db5a437a88b6bb72e0f06189f59d770e4cd6351f7
and runner13749B/SHA8d249ef040ab983b8b4edcaaddd3a44517470e5a9c0393386ca897dbb71ff33f
were copied before invocation. RED result2176B/SHA
9f47fd23616797cdfed1e387ed3b8b9654c5b8c622c2a77aaedb24ac510ccb59;
stderr22986B/SHA101517a800451d573521ee00f0994f115421322f6c942f430e4dbf37b5d69231;
stdout0. All nine failures identify the chosen unbounded read; upstream valid
payloads let each test reach its own target rather than only the first read.

Independent source review accepted corrected physical26823B/SHA
41fa154953fefc162eff22095329d0d60b6f8042a47b05e2b4945929fbaac407
before the unused GREEN. GREEN ran all9new methods plus the exact14existing
pre-write probe/refusal and empty-map/reply controls:23passed,0.354s, no skips,
errors or failures. The real-ELF positive setup method is excluded. Those14cases
use tiny temporary patch inputs and before-write provider spies; no cc invocation
or genuine runtime setup is admitted. Test/runner bytes are unchanged from RED.
GREEN result4257B/SHA6f9dfe72389e2c8e3eee3d5d812b466250158ddb4653f63507eab963344a4155;
stderr4670B/SHA64bd8fb3d84d70fe01cd86f7e7ec5acc35e3a74a9b0319b69dfc3643f23a0140;
stdout0. Both phases have normal owned closure, EOF, no unknown/overflow/discard,
forcing/signal/deadline breach and complete raw/result write/fsync/close.

The16-member ZIP/manifest retains both phase admissions, channels, results, outer
tool returns and six pre-run copies. Archive137744B/SHA
691f2dc304db62e5de357488b1f9653d53f51874c1cb598acfb31d85ac2b47e1.
All originals remain; NoCompression ZIP bounds were checked before creation.
Two16MiB tranches add32MiB: cumulative1536MiB=1,610,612,736B,
derived C70.021484375GiB<80GiB above40GiB floor. E65GiB/full64GiB pagefile and
192MiB cumulative source/Git cap remain. All14temporary roots and14patch files
were priced without cleanup credit; their conservative516096B allocation/metadata
quote fits the4MiB tail. Fresh Windows/Linux/config/pagefile/USN/UUID/boot/source
and collision checks preceded EACH phase. Both names are consumed. Independent
outcome/archive review is CLEAR; exact-commit source/Grok/CI remain separate.

This closes only these seven file-allocation boundaries. Conditional metadata
cardinality/heap, actual preparse inventory, the captured16MiB engine pin,
finalization hash/CSV/candidate bounds and caller clocks/persistence remain open.
Unchanged custody internals and later default readers require their own admitted
inputs/qualification. No real compiler, Docker, reader or genuine cohort ran;
full B3/task1.5/physical/default3840-first acceptance and46/24 tasks stay open.
