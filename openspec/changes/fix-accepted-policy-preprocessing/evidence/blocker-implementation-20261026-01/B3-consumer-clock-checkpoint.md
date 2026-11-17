# Early consumer reader-clock validation, scoped B3 checkpoint

The complete consumer previously materialized its execution chain before the
existing D16 reader checked its required clock. Import and call that same
_sealed_deadline_v2 at function entry before materialization. Discard its derived
copy; preserve the supplied object and the existing forwarding to the cold
reader. No new default window, reset, duration, deadline schema or D16 source
change is introduced. This is early validation, not whole-caller admission.

Original consumer15753B/SHAf40b77e53dfa4b1a3b2034508fb5eb14ae29d6728c0f532ca7947fa187794bb3,
test2936B/SHAa2f917b68c8e565737e4564f95787ead38669bcf54847b4cb2ac226c0200bff2,
runner15262B/SHA92e5349dba073be0f58af1abd75cd761c63a88e029ebf3ac1483927fcbc84b75
and unchanged reader33362B/SHA7fc7e536f4366fcc575240d1b81232bc8b9c3851bd13868c5d9981d40496507f
were copied before RED. RED4methods/9failures/no errors/skips,0.018s, demonstrates
missing/malformed/expired/no-observation windows entering the chain. The valid
unchanged-clock control passes. Result2194B/SHA
f10e1b600e8c292ece3e28717e9446de71378c71be63b982cd84cbca1b1da089.

Independent source review accepted consumer15835B/SHA
0597a2b55b7429d8bb04c0ffa87fc304a1ac232b6822810d8933e27c10683fd7
and unchanged test/runner/reader before unused GREEN. GREEN4passed,0.002s,
no failures/errors/skips. Result2194B/SHA
76a68448eff6293580363c98e37abc03c762514016369ae8b433fc1bb85dd58e;
stderr900B/SHAbae8fdb71721f33f25800f2edc064aa4a7e5119521cb8f906a0cc34486297430;
stdout0. Both phases have normal owned closure, both EOFs, no forcing/signal,
overflow/discard/unknown remainder/deadline breach and complete raw/result
write/fsync/close. Ten tiny invocations stop at a doubled chain boundary; only
the clock is controlled. No real materialization, I/O, compiler or reader runs.

The18-member NoCompression ZIP/manifest retains10phase artifacts and eight
pre-run copies,174528B/SHA
8c23ea147f2134b38a12d1182a388d42b0d2831f64704866db763359bd394f92.
All originals remain. For these four literal source-copy roles only, individual
copy limit65536B accommodates the unchanged33362B reader while aggregate128KiB
remains: actual67313B/67395B. No compiler/source/execution/output limit changed.
ZIP bounds were checked before creation. Two16MiB tranches yield cumulative
1648MiB=1,728,053,248B, derived C70.130859375GiB<80GiB above40GiB floor; E65GiB/
full64GiB pagefile and192MiB cumulative source/Git cap remain. Fresh Windows/
Linux/config/pagefile/USN/UUID/boot/source/collision checks preceded EACH phase.
Both names are consumed. Independent outcome/archive review is CLEAR.

Exact-commit source/Grok/latest-head CI remain separate. Literal producer clocks,
authority forwarding, candidate/report persistence, source preparse/metadata heap,
full B3/task1.5/B4/compiler/reader and genuine3840-first admission remain open.
No protected image, service/storage configuration or46/24task state changed.
