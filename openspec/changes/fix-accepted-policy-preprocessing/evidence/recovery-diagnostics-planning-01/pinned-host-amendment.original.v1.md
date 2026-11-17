# Cold recovery diagnostics amendment

Status: PLANNING ONLY. Existing helpers and failed originals remain immutable. No new helper, test, storage rehearsal or recovery attempt is approved by this document's existence. Scope is a host prerequisite for the selected historical-image offload route, recorded with the existing repair PR; it does not confer Q1/Q4/publication acceptance.

## Verified initiating problem

Cold03 failed before loop attachment, mount, daemon startup and archive loading. Seven source and protected helpers freshly match their recorded bytes. The held Python helper SHA256 is `6a63c732ae26f3dc24187779a1434021a932e00725fdc31edab05d051dd9993f`; held launcher `54535e950c0782129172e1822058b2d4a64ff1cb7d55dab36510c1fc6b20cec0`; native guardian `e2cbb87a20667aac6039993c70395c600dc861992b85f91260daee9f30a2314a`; lease `8aae687de0b919f90c8a12f34bc7798920bc0c41250049aef3595225a4bd7fb4`.

Formatting has a 300-second budget. The helper captures an initiating exception, then its finally calls process termination: SIGTERM/wait30, SIGKILL/wait30. The second wait can raise before the command receipt is written, replacing the initiating exception. Original mkfs-specific TimeoutExpired30, missing0010-command result and 60.252662-second snapshot interval localize that defect. Operator stop was latched; no lease-expiry reason was latched in the retained last-valid snapshot. Launcher forced_kill=false is about wsl.exe and does not establish graceful formatter closure. Later cleanup_errors=[] does not cover this missing command outcome.

Published sequence53 was 2026-10-14T20:24:33.042996Z. Sequence54 temporary payload time was20:24:35.051881Z, its last-write20:24:48.518061Z, operator-stop last-write20:24:48.526246Z. Slow synchronous publication followed by a post-I/O budget failure is a supported inference. The actual throw/site/HRESULT and why formatter termination was delayed remain unproved. Do not call this format-budget exhaustion or assert a complete storage root cause.

## Bounded proposed correction

Prepare separately named future v6 helpers and tests, retaining all v5/source/protected originals unchanged. Reuse the existing recorder, launcher, isolated reader and native lease protocol; add no orchestration framework.

1. Preserve the initiating exception independently from termination, receipt, and cleanup failures. Retain bounded typed reasons/operation labels and process identity. Every started command must have an honest result record even if closure is unknown; unknown/forced closure fails acceptance. A record is not a substitute for proving terminal state.
2. Track all owned child commands, including mkfs, through cleanup. Save both signal/wait attempts, final observed return code or explicit unknown state, and propagate unresolved/forced closure to the final failure report. Later daemon cleanup cannot erase an earlier child failure.
3. Preserve bounded native operation/phase, sanitized reason/HRESULT/inner code and monotonic timing for sample/write/flush/move/post-check. Keep fail-closed stop behavior and independent original return codes. Save the actual cause before broad RuntimeException wrapping obscures it. Do not disclose credentials or unrelated process contents.
4. Retain current publication/lease/format/process/overall budgets and all resource, identity, authentication, custody and restore predicates. Diagnostics must not introduce a successful fallback, broaden trust, drop Size from restore equality or reclassify original failed evidence.

## Staged authority and verification

The first proposed authorization covers only new diagnostic helper preparation and isolated synthetic/offline tests after independent review of this exact planning artifact and recorded delegated approval. Tests must exercise publication-budget failures, operator stop, both wait-timeout paths, unknown closure, receipt failure and successful graceful termination; assert preserved initiating/finalization reasons and false recovery acceptance on incomplete closure. Use new controls with a small declared output cap, ordinary source input and no real images, daemon, mount, large disk or archive upload/deletion. Rehearse the entire recorder→launcher→guest reporting chain with controlled failures; preserve every failed/red original. Keep model/data, runtime binaries and protected source roots unchanged.

Synthetic green evidence does not authorize or qualify a real storage/restore attempt. A subsequent backing-storage rehearsal must have its own concrete path/extent/retention/identity/resource plan and independent review. Only its actual evidence can justify a separately reviewed ONE fresh full restore under a new authority/namespace. Do not consume a full restore authority during diagnostics or rerun cold03. Do not enlarge a budget, change format options or relocate control storage from an unproved hypothesis.

Before real work, refresh exact process/container/GPU/root/mount/engine ownership, C>=40GiB, original cold E admission/floors and inner reserve, physical backing peak and full-duration power/update protection. Preserve the failed100GiB scratch, failed provisioning roots, both TARs, all original helpers/receipts and every current image. The existing archive index/inventory have fresh conditional GET/hash matches, and current227 image projections match the archived projections. All archive parts, exact empty-engine restore, root-ready sets, command/daemon graceful closure and cold Size equality still require their genuine evidence.

The historical34-image file is a candidate manifest, not an executable allowlist. It must pass current-reference/dependency audit, recovery and independent exact-action review before asking the user to confirm that exact manifest/action. No deletion or offload follows from diagnostic approval, existing backup, or delegated approval. The remaining193 images—including the unclassified80 and six base roots—stay local under the current proposal. Logical reclaim and physical C capacity are separate measurements; whole-chain admission must remain held if capacity is still insufficient.

## Decision gate

Independent review must verify the source-localized defect, bounded change/test scope, unchanged numerical safety gates, original preservation, and separation of diagnostics, backing rehearsal, full restore and image confirmation. Record the exact reviewed artifact SHA256, actual reviewer verdict/evidence and disposition of findings in PR9 before delegated approval. A material revision requires repeat review; author analysis alone cannot approve this amendment.
