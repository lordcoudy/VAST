# 5.5: ext4 suite и hosted CI на `C_Q1` `1112af0b53cae995984708390cf9d04c18da3c0d`

- **Hosted CI** [37584336063](https://github.com/lordcoudy/VAST/actions/runs/37584336063): cpu-checks SUCCESS, host prerequisite diagnostics SUCCESS.
- **Локальный ext4 suite** (`scripts/run_ci_checks.py --expected-commit`, свежий clone `/home/s-a-balashov/work/vast-qfb-ci-20261007-1112af0b`, 2783 с):
  - 3209 discovered, 3200 run, 3112 successes, 88 skips;
  - 0 failures, errors, expected failures и unexpected successes; 0 missing required;
  - сырой checkout совпадает с commit, `changed_tracked_paths` пуст.
- **Итог local suite: `successful=false`** — по одной причине, окружение этого хоста.
  - Тест `test_backend_publication_output_transaction_production_v3…test_canonical_wsl_venv_requires_plain_copied_python` пропущен с причиной «canonical WSL publication venv bind is not mounted». Разрешённая причина — «…venv is not installed».
  - Набор 88 skip ID совпадает с разрешённым. На этом хосте venv установлен, но его bind в `<checkout>/.publication-runtime/…` не смонтирован. Для монтирования нужен `sudo mount --bind`, системные mount не менялись.
  - Тот же класс расхождения записан в истории (decision29-D). Обязательный gate — hosted CI, он зелёный.
- **Модели OMZ.** Local suite использует 8 скопированных и проверенных файлов `.ci/model-assets.v1.json`: хранилище OMZ доступно только через Windows proxy, недоступный из WSL NAT (Amendment 3). Hosted CI скачивает модели сам.
- **Прежние прогоны** `012232c7` и `e924f3dd` упали на загрузке моделей (сетевой timeout) до тестов. Прогон `e924f3dd` с моделями прерван как устаревший после переноса `C_Q1`.

Архив: `ext4-suite-1112af0b.report.tar.gz` (report.json и логи этих прогонов).

**Подтверждение пользователя, 7 октября 2026, 11:40 МСК.** Для этого ext4 прогона на `1112af0b53cae995984708390cf9d04c18da3c0d` пользователь уточнил: «ext4 skip is within approved skips». Набор 88 skip ID соответствует разрешённому; этот skip не блокирует готовность к Q1 и не требует повторного suite. Исходный `successful=false`, текст причины, архив и allowlist остаются неизменными. Это подтверждение относится к ext4 skip; запуск Q1 по-прежнему требует отдельной команды и предстартовой проверки хоста.
