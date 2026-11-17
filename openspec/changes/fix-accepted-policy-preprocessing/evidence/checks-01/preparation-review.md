# Preparation Review

Status: recipes prepared, not executed. No clone, asset copy, full suite,
integration case, Docker command, sudo/unshare, or mount was run by this author.

Read-only source rehash on 2026-10-11 matched all 31 catalog files against the
preserved old-root bytes and accepted prior inventories. The catalog SHA-256 is
`8b9111ab5855bf73b0bac2532599b1a77d36235e05a544d0a08c47cdbcaac0e7`.
The nine IDs match the current committed manifest's exact sorted declarations;
`integration-test-ids.txt` SHA-256 is
`a036d62f684e27bc048622992cbde0710eb8de4f802c7eced51ba482bdd591e8`.
Root review of these exact catalog bytes is required before copy.

Static validation only: `bash -n` for each of the five shell recipe files passed;
`ast.parse` for both Python recipe helpers passed. `git diff --check` passed.
The first syntax-only command had a Windows-to-WSL quoting error before parsing
files; it was corrected to direct `wsl --exec /bin/bash -n <path>` invocations.
No test result or execution readiness is inferred from static syntax checks.

The skip review was read directly from the unchanged manifest and prior original
full-suite report: 88 declarations (78 physical/platform, 10 retired migration);
prior actual 88 skips included 87 exact matches and the one undeclared missing
canonical bind reason. The original harness reported failure, not green. The
private-mount recipe must make that canonical test execute successfully instead
of carrying an exception forward. Missing privilege/namespace support blocks
execution without changing production code or the skip whitelist.

Remaining execution gates include a committed full frozen repair SHA, fresh
repair root/input copies, independently reviewed inventory hashes, namespace
privilege, fresh paired images plus the historical DeepStream fixture image, and no
competing live Docker/GPU work. Hosted workflow dispatch is separate: the
retained non-master PR base is outside the current automatic PR branch filter.

## Private Root-WSL Launcher Fallback

Root reported `sudo -n true` requires a password; the WSL root entry point is
available. The prepared launcher now checks sudo and otherwise uses exact
`/mnt/c/Windows/System32/wsl.exe --distribution Ubuntu --user root --exec
unshare --mount --fork --propagation private /bin/bash` with the unchanged
explicit child arguments. The child verifies a different namespace and private
propagation before mounting, records that identity before the mount, and verifies
the CI account is UID 1000 before `runuser` with correct HOME/TMPDIR.

The parent retains its original namespace and full before/after mountinfo;
byte equality and unchanged parent namespace are success prerequisites. No
global remount, whitelist adjustment, or production CI edit was introduced.
Both modified shell files passed direct `wsl --exec /bin/bash -n` (exit 0).
No privileged launcher, unshare, bind, clone, or full test command was executed.

Prepared launcher SHA-256:
`ff1d6f9397a3464ee9aa9f903e05b79d0643e746c1daafa2c7c3b6e9032a9045`.
Prepared private helper SHA-256:
`0549f8d3d0f5580359e48a532893ae9540713e1e901e394ec7a40c4b051e6b62`.

## Additive Fresh Input Preparation

The passed independent parity audit was read without rerunning it. Its exact
SHA-256 is `75922812dde1281dc57f7969d5cd5bd3d32fa6cd10e34a6638b8e54ce51fb95b`:
status verified; physical build ACA; 480 executions, 960 tensor files, 1920
execution members, 2478 physical descriptors. Classification is 2466 fresh
artifact files, seven configs, five corpus files. The acceptance binding and
six renewed/fresh-held receipts extend the ignored artifact closure to 2473;
the selected-original receipt adds the eighth tracked cross-check. The old
31-row catalog and its bytes were not changed.

The two observations-02 maps were independently read and hashed, then explicitly
classified fixture-only and not parity-audited. They add two ordinary copies,
not authority or a worker/inference claim. The fully prepared clone therefore
has 2540 ignored inputs; copy/source/destination hashes are separately checked.

Evidence-only root override accepts only the original physical root or a fresh
canonical ext4 `source-<exact-final-SHA>` clone whose committed recipe, HEAD and
raw tracked bytes are exact. The new source-input wrapper reads the old root and
untouched physical ACA root, while preserving the final destination commit.
No live worker is interrupted and no metadata/epoch/path is rebound. A stock
accepted-v4 clone refusal remains a refusal, not a reason to change receipts.

Catalog rendering, review of the actual rendered catalog SHA, copying, clone
creation, full checks, private mounts and nine integrations remain unexecuted
by this author. The launcher hash above records the earlier fallback-only
version; adding the fresh copy stage changes that prepared launcher hash.

After the additive-source updates, direct `wsl --exec /bin/bash -n` passed
(exit 0) for `recipe_common.sh`, `prepare_source_inputs.sh`, and
`run_ext4_suite.sh`. Canonical Python `ast.parse` passed (exit 0) for
`prepare_fresh_check_catalog.py`, `copy_fresh_check_inputs.py`, and
`copy_check_inputs.py`. These are syntax checks, not execution evidence.
