# Finite producer clock-loss correction

Continue approved B3 at base674c98636f63256c00bf38c1d72d92843605acd7, same C: worktree,
branch/change/PR9. Independently audited concrete losses remain in both producers:
positive _fresh_json loses actual returned writer facts if its following clock
query raises; negative finalization queries the clock outside its aggregation and
can replace the original body/report error. These are existing B3 implementation
requirements, not a new design amendment or physical admission.

Fix only those two losses. Extend the existing report-refusal wrapper to retain
the exact facts object and original clock error as primary, with no fabricated
secondary exception. Copy original cause codes and add only the fixed
fixture_report_clock_unavailable status; never label an unavailable clock late.
Catch the post-write query once, preserve the original error as __cause__, and
do not repeat encoding/writing. Existing timely/late behavior stays exact.
Move the negative finalizer clock query into guarded remember/break handling:
keep any original primary and identity-distinct clock error, stop remaining source
calls when time is unavailable, and preserve the original observe_end/deadline.
No owner, clock reset, report file, compiler, source-helper or runtime gate change.

Add one method/two vectors to the existing report-persistence tests: complete
writer facts and existing fsync/close failure causes, each followed by the same
actual controlled clock exception. Assert original facts identity/unchanged content,
original primary/cause identity, explicit clock-unknown code and exactly one write.
Add one method/two vectors to producer-failure tests: clock unavailable before
after-proof and after that proof. Assert original body primary, original distinct
clock secondary, source-call counts and no later source spawns. Existing assertions
stay unchanged; the harness adds only those explicit clock faults.

RED producerclock-red-01 selects those two methods/four vectors against unchanged
production sources. Expected four actual assertions fail on lost facts/primary,
with no missing APIs/import/errors/skips. GREEN producerclock-green-01 selects
both complete modified modules:12 methods/31 controlled vectors. All I/O, clocks,
source, compiler and fixture effects remain doubled; actual case-file allocation0.
Use unchanged D16 outer capture/writer, one inherited300s test deadline and fresh
namespaces. Before each invocation independently review exact tests/source/launch
and numeric admission; preserve failed originals and actual enclosing returns.

Assign a separate16MiB pair within unchanged C80GiB above40GiB:4MiB two-phase raw
channels;128KiB result/outer/admission;1MiB five source forms plus their funded Git
copy;4MiB capture ZIP/Git (ZIP<=2MiB, manifest<=16KiB);5MiB one configured Grok
review's prompt/channel/ZIP/Git forms;1MiB command/checkpoint/manifest/copy/namespace
tails including the capture manifest/Git<=32KiB; remaining896KiB slack. Five source
copies per phase, each<=64KiB, aggregate<=128KiB. At most four retained test-command
forms, each<=16KiB/aggregate<=64KiB; no old ceiling increases. Configured review
same session/model, max4turns/600s, prompt<=128KiB (direct core<=64KiB), channels
<=512KiB each, outer<=16KiB, ZIP<=1.5MiB. No continuation is covered.

Cumulative direct reservation becomes2096MiB=2197815296B; derived C additional
quote71.005859375GiB<80GiB including the preceding448MiB ext4 scattering charge.
E65GiB/full64GiB pagefile and source/Git192MiB remain. Same Ubuntu boot/UUID/config,
allocation units<=4096, RAM<=24GiB and exactly6GiB swap; fresh physical floors
before allocations. This pair has no new ext4 fixture/VHD allocation or cleanup
credit. Source-only exact review/configuredGrok/new-head CI follow actual GREEN.

Whole1.5, full pre-stringification/CLI failure-frame transport, actual compiler/
reader/environment/heap qualification, controller/runtime/genuine/final gates stay
OPEN. B4 CI40497268170 concerns its previous head only. No task checkbox closes.
