# Corrected source-derived mixed-cohort capacity geometry

Independent source review confirmed that _fixture_operation_sample_counts_v2
uses overrides.get(operation_id, samples_per_branch) for all 37 operations.
Overrides identify qualification cells only. The five ancillary operations
therefore retain the global count. Preserve this behavior.

The stock roster contains 32 qualification cells, four native prechecks and one
Savant CPU original: 21 independent and 16 shared operations. There are 17 drops,
nine independent and eight shared. Source anchors are
tests/fixtures/accepted_policy_physical_fixture_v2.py:289 and
scripts/publication_operational_stock_operations_v1.py:149.

For global 985 and sixteen qualification overrides to 984:

- Qualification frames: 31504. Ancillary frames: 5 * 985 = 4925.
- Total frames: 36429. Ingress: 36446.
- Native occurrences: 4 * 36429 + 3 * 17 = 145767.
- Native bytes per representation:
  37 * 65536 + 145767 * 9216 = 1345813504.
- Four charged representations total 5383254016 bytes.
- Guardian upper bound:
  8 * 65536 + 145767 * (768 + 256) + 1048576 = 150838272 bytes.

The four native forms are producer output, coordinator scratch payload, engine
operational output and separately materialized output. Their constructor is
tests/fixtures/accepted_policy_original_custody_fixture_v1.py:269.
The expected qualification sample total remains 4 * 31504 = 126016.

Withdraw the earlier provisional mixed figures 31654 frames, 126667 native
occurrences and 1169787904 native bytes per representation. The corrected
four-copy native liability is 704102400 bytes larger; the guardian bound is
19558400 bytes larger. All dependent coordinator, sidecar, reconciliation,
metadata and retained-copy terms must use the corrected geometry.

For the twelve CSV files, sum min(file_cap, 4096 + rows * row_cap) over the
existing structural formulas and maximize over the choice of sixteen
qualification overrides. Assigning the reductions to shared cells gives the
conservative maximum 3439116800 bytes. The existing packaging convention,
ceil4096(CSV) + 13942784, gives 3453063168 bytes. This is an upper bound over
override assignments, not an observation of one selected fixture.

The other source-derived cohort figures are unchanged:

- Default 3840/global 30: 1110 frames, 1127 ingress, 4491 native occurrences;
  native 43813888 bytes per form, guardian 6171648 bytes, packaged CSV 124104704.
- 3968/global 31: 1147 frames, 1164 ingress, 4639 occurrences;
  native 45177856 bytes per form, guardian 6323200 bytes, packaged CSV 127594496.
- Underfill/global 31 with one qualification cell at 29: 1145 frames,
  1162 ingress, 4631 occurrences; native 45104128 bytes per form,
  guardian 6315008 bytes, packaged CSV 127397888. Qualification count is 3960
  and genuine refusal remains required.

These are source-derived bounds, independently reviewed by /root/capacity_review.
They are neither runtime observations nor allocation admission. The universal
37 * 985 and per-file 64 MiB/sidecar 128 MiB ceilings remain conservative.
The local preparatory C 80 GiB/E 65 GiB reservations do not change. Whole-peak
fit, all physical operations and genuine cohorts remain unadmitted.
