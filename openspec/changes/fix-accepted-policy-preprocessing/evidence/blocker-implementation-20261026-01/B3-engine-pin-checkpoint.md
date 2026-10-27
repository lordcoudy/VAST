# Held captured-engine pin, scoped B3 checkpoint

The public physical setup previously opened the captured engine, eagerly read its
path without a cap, and began cleanup only after reading/constructing its pin.
Read/construction failures could leak that FD; a later close could replace the
body's initiating exception. The new purpose-specific context streams the existing
16MiB captured-engine role through custody with capture=False. Complete before,
opened and exit file epochs plus the returned inode/size bind that hash to one
raw FD, held throughout the borrowing body. Existing path/fd/size/sha256/proc_path
fields remain unchanged. NOFOLLOW/NONBLOCK/CLOEXEC and explicit raw ownership
avoid buffered-wrapper ownership transfer. Exit verification runs even when the
body raises, then FD/custody closures preserve the initiating object and distinct
secondary objects without formatting messages or duplicating identical objects.

The original preparation clock guards hash/open/pre-yield boundaries; no fresh
deadline or duration is created. The enclosing caller's full execution/closure
clock remains separate unresolved B3 work. This source slice proves neither a
real16MiB read's timing nor unchanged custody internals or outer socket cleanup.

Actual original RED:12methods/10failures/no errors/skips,0.050s; two original-cause
controls pass. It reproduces eager capture, unprotected pre-yield ownership,
identity/size/nonblocking omissions and masked cleanup causes through the public
setup. Original physical26823B/SHA41fa154953fefc162eff22095329d0d60b6f8042a47b05e2b4945929fbaac407,
test9589B/SHAab69034bcb760f377827973c849121a4e2a9361037c09f97e918ff3fb1273037
and runner14121B/SHA832ca212f52dc10900a601bb13043abb5641fc06b2b14468c860a053be8cf722
were copied before invocation. RED result2175B/SHA
d1dd4aa3cc4cfead43ef29078ec1a47846ce2b529fceb97f645e8037f226bd6b.

Independent source review accepted corrected physical29076B/SHA
a2a0fb83cb559761183b5e97a509e0bae58566553961799c75b3b4f33f3e7108
and the unchanged test/runner before the unused GREEN. GREEN12passed,0.040s,
no failures/errors/skips. Result2178B/SHA
2ae7c520ac6569f94b47828b1f1405f96ca82218f1de1dae5e834a524a77fd2a;
stderr2197B/SHA42a517c8f6de93536a488e59366993347a2e27efda7c4d6be3e255e62355024a;
stdout0. Both phases have normal owned closure, both EOFs, no force/signal,
overflow/discard/unknown remainder/deadline breach and complete raw/result
write/fsync/close. Every filesystem/temp/socket/materializer/compiler/raw-FD/hash
effect is doubled;45B stand-in bytes were never executed. No real engine was
opened or qualified by these tests. Both phase names are consumed.

The16-member ZIP/manifest preserves all phase admissions/captures/results/outer
tool returns and six pre-run copies;131453B/SHA
bbf490a4ab1e567fb57a83390cf68bdc5254de6946d46b4aef2482a378374cae.
Local originals remain. NoCompression ZIP bound was checked before creation.
Two16MiB tranches increase cumulative direct allowance to1568MiB=1,644,167,168B,
derived C70.052734375GiB<80GiB above40GiB floor; E65GiB/full64GiB pagefile and
192MiB cumulative source/Git cap remain. Fresh Windows/Linux/config/pagefile/USN/
UUID/boot/source/collision checks preceded EACH phase. One initial dispatch was
aborted before any tool execution; all six destination names were independently
observed absent before the sole RED invocation, not treated as a consumed run.

Exact-commit source/outcome review, configured Grok and latest-head CI remain
separate required gates before dependent actual execution. Full B3/finalizer/
caller/source/metadata-heap, task1.5/B4/reader/physical/genuine3840-first acceptance
remain open. No protected image, storage/service/configuration or task state
changed;46/24 and D27/Native57 remain.
