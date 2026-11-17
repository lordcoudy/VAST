# Prospective exact pager-acknowledgement warning disposition

Same change/branch/DraftPR9/product605eb02733fe256ad5ef14f358eaa81ee1a0ae44.
Replace the inapplicable prospective UI-leaf exception with the exact case below.
Every earlier receipt remains at its original scope/HOLD. Diagnostic04 disclosed
only root privacy/Table; its contents have not been published or accepted.

## Source-backed distinction
Installed26-config-reference.md550 documents privacy.privacy_banner_acked as a
pager-local RFC3339UTC timestamp recording banner dismissal. Pinned public source
2bdd1d6a6369de0e8c68132ea4539e9abd9e14a8: util/config/mcp.rs73 defines PrivacyConfig
with only that optionalString; load.rs108 reads the raw privacy section,
persist.rs58 round-trips it; pager/app/app_view.rs981/1213 uses it for visibility.
It is NOT safe to infer harmlessness from serde unknown-field alone: a raw-layer
consumer exists. Account coding-data retention/training is separately updated
by shell/extensions/privacy.rs through an authenticated API/auth-cache update.
The acknowledgement is preserved, never treated as an account/privacy override.

Permit exactly ONE warning only if target=configKey,kind=unknown-field,path
EXACT privacy (one raw root component, no wrappers). Both byte-identical parsed
original/sealed configs must contain exactdict privacy with EXACTkeyset
{privacy_banner_acked}; its value must be exactString≤64UTF8bytes, strict
RFC3339UTC (Z or+00:00, up to9fractiondigits), with valid calendar/time. No
additional key, malformed/missing/wrong-type value or other warning is accepted.
Do not print/hash the timestamp, normalize/edit/remove the table, change account
policy or infer privacy intent. Record only fixed private-check success/failure.

All source/runtime/token/custody/fingerprint controls remain. Require recognized
configured model/provider/auth fields independently, original policy absence,
zero effective plugins/hooks/experiments, all discovered MCPs disabled, zero
standalone lists, exact user+feature-overlay layers and no MCP/config problems.
Actual response must separately match session/CWD/model/end_turn/bounded turns.
Raw response/thought/private identifiers or values stay outside public evidence.

## Finite caller
One readonly preflight per admitted snapshot,45s observation/60s total; current04
may be checked without fresh auth because it launches no Grok/network. One actual
review requires renewed05, exact reviewed successful preflight, expiry>launch+
900s and separate execution admission. Review600s total: collect570s, post-compare
585s, close/persist600s. Keep512KiB per channel, finite60000/1000/1000polls,
original suspended-root Job ownership/retirement/EOF/I/O/closure proof, exact
prompt03/source and unchanged selectedsession/provider/model inputs. New .gm1
owns only one directory/two private files; existing snapshot ACLs stay unchanged.
No model/provider/leader override, tools, fallback, replay or continuation.

Six proposed source caps total112KiB; retain model5MiB plus a separately funded
2MiB supplement (total7MiB=7340032B), per the reviewed capacity supplement.
Preflight04
outputs have their separate2MiB row; all old diagnostic liabilities remain.
Exact source/pure refusal controls/packing/capacity/frozen-body review and fresh
admission precede every finite entry. Private preflight outcome must be reviewed
before renewal/model release. All whole1.5/compiler/Docker/reader/lifecycle/
runtime/genuine/conformance/OpenSpecarchive/task/final gates remain open.
