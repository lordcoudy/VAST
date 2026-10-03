# Recovery baseline test observations

Observed 2026-09-29, before implementation edits.

1. Windows default `python` is Python 3.14.7. Running `python -B -m unittest discover -s tests -p test_checkpoint_native_policy_runtime.py -v` exited 1 during module import because this interpreter has no `yaml` package. One import-error placeholder ran; no coordinator test executed. This is an environment-selection error, not a production regression.
2. Repeated discovery with the existing frozen WSL interpreter `/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python`, working directory `/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec`, exited 0. All 19 coordinator tests passed in 0.242 seconds with no skips. No package installation or dependency update was performed.

These are observed tool outcomes, not newly issued publication acceptance or CI receipts. The source snapshot is `initial-source-manifest.v1.json`. Future regressions use the pinned WSL interpreter and preserve their original logs and return code.
