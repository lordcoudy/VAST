# Q1, попытка 4 — FAILED на шаге 14 (8–9 октября 2026)

Попытка 4 на `C_Q1'''` `0aeb955bdf49d35ddb429c6a8e83d897608b00aa`, тег `qualify_full_benchmark_20261008e`, корень `E:/STUDY/VAST/tmp/qfb-root-20261007a`. Запуск — по явной команде пользователя («Start Q1»); пункты 1–2 чек-листа хоста проверены (AC sleep/hibernate 0, Windows Update paused до 26 октября), Docker Desktop работает с 8 октября 01:10 МСК, `boot_id` `c062ef70…` прежний.

| Шаг | Итог (UTC) |
|---|---|
| 0 preflight, 1 stock host check (6.2) | PASS, 8 окт. 18:59 — C 84 / E 355 / WSL 758 GB, 0 контейнеров, 0 GPU compute |
| 2–5 transaction, preprocessing, code closure (`published`), capture plan 37 | rc 0, 19:28 / 19:31 / 19:31 / 19:33 |
| 6–7 guardian | `live_operational_nonpublication`, 8/8 attested |
| 8 runtime inputs | rc 0 |
| 9 owner execute | **rc 0**, 9 окт. 07:19:59 — 37/37 операций (4 native prechecks, Savant original, 32 cells; все 8 DeepStream cells прошли) |
| 10 authenticated stop | rc 0, `clean_stop_nonpublication` |
| 11 guardian terminal | rc 0; guardian rc 0, контейнеров 0 |
| 12 execution binding | rc 0, 07:22 |
| 13 cold closure 37/8 | rc 0, 11:39 (4 ч 17 мин), `cell_count` 32, 126 036 принятых запросов guardian |
| 14 индексы | **FAILED**: `q1_14_policy_index` rc 1, `q1_14_resource_index` rc 1 — `deepstream fragment validation failed: analytics execution binding index physical file is missing or escapes project_root` (`artifacts/analytics_execution_bindings/publication_v3/index.json`) |
| 15 promotion | не должна была запускаться; обе stock-команды rc 1 (`qualification index must remain under project_root`), выходов нет |

- **Ошибка оператора при запуске 12–15.** Шаги 12–15 были запущены одной цепочкой `a && b && …` в одном shell; в таком контексте bash отключает `set -e` внутри функций шагов. Поэтому `q1_14_indices` продолжил после отказа policy index, записал служебный `q1_14_indices.rc` = 0 и пустой `outputs.sha256`, а `q1_15_promotion` запустил promotion после отказа `q1__verify_outputs` и записал `q1_15_promotion.rc` = 0. Фактические rc stock-команд (`q1_14_policy_index.rc`, `q1_14_resource_index.rc`, `q1_15_*_promotion.rc`) = 1; индексов и promoted-каталогов нет. Записано в `q1_control/q1-failed-readonly-observation.txt` (SHA256 `d1581c2d…`).
- **Причина отказа (диагностика, не квалифицирующая).** Stock CLI шагов 14–15 используют `publication_policy_qualification._default_fragment_validator`: legacy-валидаторы с зашитыми идентичностями до qualification (`publication_v3` binding index, `configs/checkpoint_analytics_model_parity.accepted.*`, прежние worker image ID). На фрагментах попытки 4 отказывают все четыре системы: DeepStream — отсутствующий legacy index; Savant — `assess_qualification_fragment() missing … 'runtime_image_manifest'`; OpenVINO GVA и gstreamer_custom — `qualification fragment binding values drifted`. Transaction v2 (шаг 2) строит candidate index тем же билдером, но с `validate_publication_policy_qualification_fragment_from_authority_v2`; этот валидатор принимает все четыре фрагмента попытки 4. У CLI шагов 14–15 нет параметра выбора валидатора. Результаты дальнейшей диагностики — [diagnosis](diagnosis/README.md).
- После отказа: контейнеров 0, GPU compute 0, процессов VAST 0. Ничего не повторялось, не удалялось и не переименовывалось.

## Состав

- `q1_control/` — копии originals управления попыткой и read-only наблюдение.
- `closure/` — receipt cold closure, снимки authority/lifecycle guardian, execution binding.
- `guardian/` — authority, lifecycle, operational group.
- `pilot_checkpoint.v2.json` — checkpoint owner.
- `attempt4-namespaces.size-sha256.json` — все файлы namespaces попытки 4 (1774 файла, 3,52 GB) по пути, размеру и SHA256; остаются на месте и не переиспользуются без решения пользователя.
