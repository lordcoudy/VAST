# Exact checkout bytes for the existing benchmark source inventory

This is a read-only design recommendation, not an applied amendment or acceptance receipt. The current physical source manifest has 165 members and aggregate SHA-256 `f7e2b75bf6eaf847b810fedc417782af3bb1238f4b23ab030463219690667ecc`. The reviewed image gates may continue against those explicitly pinned physical bytes; the current checkout must not be described as byte-identical to the committed tree.

The minimum amendment that preserves these physical bytes is one finite root `.gitattributes` block and raw staging of exactly the existing 22 line-ending-only source files. Use [the 156-path proposed block](byte-freeze.minimum-proposed.gitattributes.v1.txt), appended after current rules. It assigns `-text !eol` to the 155 inventory paths whose `text/eol` attributes are unspecified, plus `deploy/savant/canonical_distributed_module.yml`. The remaining nine inventory paths already have explicit LF rules and byte-identical committed/physical content; preserve those rules. The [uniform 165-path alternative](byte-freeze.proposed.gitattributes.v1.txt) would also work, but overrides nine existing LF contracts unnecessarily.

`-text` disables Git's end-of-line conversion during both staging and checkout. `!eol` clears a previous `eol` value explicitly; it does not enable automatic text conversion when `text` is unset. Later exact-path rules override earlier root rules for each attribute. Therefore the Savant YAML exception overrides `*.yml text eol=lf` without changing the style of any other YAML file. These are finite benchmark-source exceptions, not an extension-wide formatting policy. [Git attributes documentation](https://git-scm.com/docs/gitattributes).

The YAML exception is required: current nonwriting `hash-object` observations produce blob ID `4882798103a5a188442ad6d736ba231a9eee5849` with either `core.autocrlf=true` or `false`, but its original raw bytes produce `8fe84e9981778611516f88e92abc6f2cb49d7f8d`. Existing `text eol=lf` thus prevents ordinary staging from preserving its pinned bytes even when local `core.autocrlf=false` is set. Conversely, `scripts/checkpoint_savant_native_module.py` has unspecified attributes: with `autocrlf=false` its filtered and raw IDs are both `bbc0108e6b363da02478f00dfd441dda8d27a346`; with `true`, its cleaned ID is `89d7e35561534aa0ae7c2116d2b04f0d67be3ecf`. These probes did not write objects or modify the index. [Git hash-object documentation](https://git-scm.com/docs/git-hash-object).

The 22 existing files have the same code after replacing only CRLF with LF, as independently verified in audit v4. Seventeen contain a mixture of LF and CRLF. Setting `text eol=crlf` would generate uniform CRLF on checkout and cannot reconstruct the mixed originals. Freezing only the 22 differences also leaves the other unspecified LF source paths exposed to checkout conversion when `core.autocrlf=true`. A repository-local `core.autocrlf=false` is insufficient as a distributed contract: it is not committed, and the YAML's explicit rule still applies. [Git configuration documentation](https://git-scm.com/docs/git-config).

All 165 effective `filter`, `ident`, and `working-tree-encoding` attributes are currently unspecified. `-text` disables newline conversion only; it does not disable independent clean/smudge, identity, or encoding transformations. Preserve their current unset behavior and require effective-attribute checks on the verification checkouts. Fail the byte comparison if a higher-precedence `.git/info/attributes` or nested rule changes a pinned path. There is no reason to install a filter or change a global Git setting for this amendment.

The raw staging candidates are exactly these paths, also carrying physical size/SHA-256 and newline counts in [the observations](byte-freeze-readonly-observations.v1.json):

```text
CMakeLists.txt
deploy/gstreamer_adaptivescheduler/gstadaptivescheduler.c
deploy/gstreamer_analytics_terminal/checkpoint_analytics_model_provenance.hpp
deploy/gstreamer_analytics_terminal/gstvastanalyticsqueue.cpp
deploy/gstreamer_analytics_terminal/gstvastanalyticsterminal.cpp
deploy/gstreamer_analytics_terminal/gstvastcheckpointprefixqueue.cpp
deploy/native_gst_probe/checkpoint_admission_transport.hpp
deploy/native_gst_probe/checkpoint_analytics_execution_client.hpp
deploy/native_gst_probe/checkpoint_analytics_terminal_transport.hpp
deploy/native_gst_probe/checkpoint_runtime_emitter.hpp
deploy/native_gst_probe/checkpoint_source_coordinator.cpp
deploy/savant/canonical_distributed_module.yml
scripts/analytics_model_contract.py
scripts/benchmark_contract.py
scripts/checkpoint_gstreamer_analytics_bridge.py
scripts/checkpoint_model_parity.py
scripts/checkpoint_publication_runtime.py
scripts/checkpoint_runtime_plan.py
scripts/checkpoint_savant_native_module.py
scripts/collect_metrics.py
scripts/full_resource_contract.py
scripts/topology_contract.py
```

Recheck the 22 physical descriptors before staging. Do not use `git add -A`, `git add --renormalize .`, a worktree-wide checkout, or cleanup of unrelated dirty files. Stage the reviewed attributes change and these exact 22 paths only after effective attributes have the intended values. Inspect the index blobs directly with `git cat-file --batch`: their physical size and SHA-256 must equal the current captured descriptors. An ignored-CR diff supports code review, but does not replace raw byte equality. The source change must record that those staged differences are the captured original line endings, not newly generated normalization.

Reviewable completion criteria:

1. The source commit includes the finite attributes amendment and exactly these 22 raw source replacements; unrelated existing dirty paths remain untouched. Preserve any already-authorized concurrent staged changes explicitly rather than overwriting the index.
2. In fresh isolated checkouts of that exact commit with `core.autocrlf=false` and `true`, all 165 files reproduce the current physical sizes/SHA-256 values, and the aggregate remains `f7e2b75bf6eaf847b810fedc417782af3bb1238f4b23ab030463219690667ecc`. Set the mode before initial checkout. Do not rely on a second checkout that happens to reuse already-correct files.
3. `git check-attr` reports `text=unset,eol=unspecified` for all 156 exceptions; the nine retained explicit LF paths retain their existing attributes. No pinned path has a transforming filter, identity expansion, or working-tree encoding. Both verification checkouts have a clean index/worktree for the declared paths.
4. Recompute the original native/worker source, dependency, and context hashes; all native3 and worker2 hashes must equal the original byte-bound freeze receipts. Recompute all four actual runtime contexts, including the native builders' third metadata manifest, and all 78 host code-closure source descriptors against the current audit. Existing exact COPY and source-closure validators must pass.
5. Publish a nonauthorizing source/checkout proof tied to the exact amendment commit. Existing image or model evidence may be used only through unchanged stock validators and fresh live inspection where required. A clean checkout creates different physical inode/owner witnesses: emit fresh stock host-code custody receipts there; never relabel an old receipt as custody of the new checkout.

This preservation amendment does not alter any current production file bytes, Docker COPY members, allowlist order, native implementation, or host import graph. `.gitattributes` is absent from the present 165 source inventory and the explicit image/host closures. Provided raw byte equality is proven, none of their existing physical hash scopes changes merely because these bytes are represented faithfully in Git. Existing invalidations from the two approved runtime repairs still require their current real image gates; this recommendation supplies no image, parity, or benchmark grant.

Canonicalizing the 22 files to LF is a valid alternative only with a deliberate source-identity roll-forward. It changes all native3 source/context identities, all four runtime contexts, and affected host-script hashes. Worker2 has none of these 22 members and remains unchanged if no other files change. Downstream package, aggregate runtime patch, parity, and candidate authorities must then be regenerated or revalidated through their actual dependency rules; old source-bound receipts cannot be rebound. This costs substantially more than preserving the existing byte-bound native identities.

The read-only observations record commit `a5b3812457cc2eddfd19eaf7687a4e868a7d085b` while preserving the current source bytes. Audit v4's historical Git comparison was against `7f3dfa42858c85d6e3db2cb1274dd13af35696c9`; the two semantic repairs have since been committed. This review wrote only the adjacent recommendation/proposal/observation artifacts. It performed no source edit, staging, configuration mutation, checkout, image build, or workload.
