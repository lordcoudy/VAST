# 6C.8: CI и ext4 suite на `C_Q1''` `4947e35a70fcfd94cf53179f05c021f8fb9dd3d1`

- **Hosted CI:** `C_B''` `8990a091` [37751411520](https://github.com/lordcoudy/VAST/actions/runs/37751411520), `C_Q1''` [37757783709](https://github.com/lordcoudy/VAST/actions/runs/37757783709), docs head `daea2c8c` [37757949251](https://github.com/lordcoudy/VAST/actions/runs/37757949251) — все SUCCESS (cpu-checks и host prerequisite diagnostics).
- **Локальный ext4 suite** (свежий clone, `run_ci_checks.py --expected-commit`, 2366 с): 3222 discovered, 3213 run, 3125 successes, 88 skips; 0 failures, errors, expected failures, unexpected successes, missing required; `raw_checkout_bytes_match_commit=true`, `changed_tracked_paths=[]`.
- **`successful=false`** — та же единственная причина, что в одобренном пользователем прогоне 5.5 (skip `test_canonical_wsl_venv_requires_plain_copied_python`, «venv bind is not mounted»); записи 88 skips и `child_failure` идентичны 5.5. +10 тестов — новые тесты Amendment 6.
- Исходный output — `ext4-suite-4947e35a.original-output.tar.gz`; clone удалён после сохранения.
