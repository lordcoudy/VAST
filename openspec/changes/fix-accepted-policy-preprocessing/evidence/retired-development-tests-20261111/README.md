# Retired development tests, 2026-11-11

Byte-exact copies taken from PR #9 head `460a5096` (unchanged through `f9ccd598`).
They are retired from test discovery by design.md, "Whole-PR review fixes, 2026-11-11", R1.
The `.retired` suffix keeps them out of discovery and import.
In the resume test module, everything from the D22 comment block before `d22_sha` (line 2680 of the retired copy) to the end leaves discovery.
In the resume caller test module, everything from `_D22_BROTLI_DATA_PROGRAM` (line 2062 of the retired copy) to the end leaves discovery.
Both cut modules re-append their `if __name__ == '__main__'` guard.

| Original path | Copy | Size (B) | sha256 | Note |
|---|---|---|---|---|
| `tests/test_accepted_policy_fixture_compiler_gate2_resume_v1.py` | `test_accepted_policy_fixture_compiler_gate2_resume_v1.py.retired` | 521029 | `bdfaca98fbd3825cf383a4d3f22ae60ffaced76cee27f42cf462ba6dba7bd704` | whole module before the D22-D26 cut |
| `tests/test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py` | `test_accepted_policy_fixture_compiler_gate2_resume_caller_v1.py.retired` | 520323 | `3742a391657a85932a3ba776b36fbef87c7a097b7be067cf79ea27cfb3e5b24f` | whole module before the D22-D26 cut |
| `tests/test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py` | `test_accepted_policy_fixture_compiler_gate2_dictionary_v1.py.retired` | 194083 | `f4e4e2d4af02e75d4144420c2b119835309ec057867e64530b30a9afd0724e2c` | D27 development test, removed |
| `tests/test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py` | `test_accepted_policy_fixture_compiler_gate2_dictionary_caller_v1.py.retired` | 437426 | `cdf0449ef949135f6c2796c278fe6cfd1d74ff3ad294e19ea38b264060518b00` | D27 development test, removed |
| `tests/fixtures/gate2/d26-geometry-retained-v1.json` | `d26-geometry-retained-v1.json.retired` | 102199 | `408379cb8ee0d7ce2fd233d963a0939889485156e7c42a07481d3726b419578f` | D26 retained fixture, removed |
| `tests/fixtures/accepted_policy_fixture_compiler_component_v1.py` | `accepted_policy_fixture_compiler_component_v1.py.retired` | 32732 | `329fb13f2c6dcee0872e5a29ec1fd769dc6e57ce92ee1076fef6737f1da86d88` | pre-R1 operator fixture bytes |
| `tests/fixtures/accepted_policy_fixture_compiler_gate2_resume_v1.py` | `accepted_policy_fixture_compiler_gate2_resume_v1.py.retired` | 32739 | `5fd7d2d6ee62ff584d2a4662757ca804a3d3300d30bb966319901870c4c85670` | pre-R1/R4 operator fixture bytes |
