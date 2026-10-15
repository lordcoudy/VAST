## 1. Loader и наблюдение

- [ ] 1.1 Создать `scripts/service_profile_latency_model_v1.py` с загрузкой binding через `read_closed_rows` (размер+SHA256 binding из CLI, все descriptors, общие caps reducer, `_recheck_named` после расчёта) и собственным analysis deadline; проверить тестами на синтетическом binding: успех, несовпадение SHA, symlink, не 24 arms → ошибка без отчёта.
- [ ] 1.2 Вычислять observed через `reduce_study` над теми же decoded rows и сверять arm reductions с архивной `reduction` (JSON equality); проверить тестом, что изменение одного поля архива даёт ошибку.

## 2. Профиль обслуживания

- [ ] 2.1 Реализовать join `native_client`/`bridge_route`/`worker` по `request_id` и native terminal по `(input_frame_key, branch)`; компоненты prefix, route_wait, route_hold, client_overhead, post_route, worker backend/residence с `distribution` + mean/CV; проверить тестами: полный join (unknown=0), отсутствующий join (unknown++), дубликат `request_id`, отрицательный компонент → ошибка.

## 3. Предиктор

- [ ] 3.1 Реализовать discrete-event симуляцию по `stream_schedule` (6 streams, 4 FIFO routes, буфер 1 drop-newest на stream×branch, 200 реплик, seed 20260323) с выходом drop-доли, p50/p95 completed frame latency, Y100_frame над planned measurement frames; проверить тестами: детерминированный сервис ниже ёмкости → 0 drops и точная латентность; сервис выше интервала прихода → ожидаемая drop-доля; пустое распределение → `prediction: null`; одинаковый seed → байт-идентичный результат.

## 4. Валидация, gate, отчёт

- [ ] 4.1 Собрать группы (a) in-sample 24 arms, (b) rate 1↔2 внутри repeat/resource/topology, (c) r1↔r2; rate 0.25 только в (a)/(c) со сравнением route hold против rate 1; вычислить `ex_ante_parameter_use_permitted` по 8 GPU сравнениям (b) и порогам спеки; проверить тестами на синтетических результатах граничные значения порогов и `null`.
- [ ] 4.2 Писать отчёт kind `vast-service-profile-latency-model-v1` через exclusive create с выводом size+SHA256, всеми eligibility флагами `false`, descriptors, допущениями и меткой `new_descriptive_read_not_rereduction`; проверить тестами существующий путь/symlink → ошибка и отказ `scripts/publication_policy_contract.py` calibration loader принять отчёт по kind.
- [ ] 4.3 Проверить, что модуль отсутствует в `deploy/gstreamer_custom/publication/runtime-source-allowlist.txt` и Dockerfile `COPY`, зарегистрировать тест в CI selection при необходимости и пройти локальный CI (`scripts/run_ci_checks.py` или эквивалент) и hosted CI.

## 5. Запуск на attempt K

- [ ] 5.1 В WSL Python 3.12 среде K выполнить CLI над `/home/s-a-balashov/vffefab7aK/s/run/closed-inputs.original.json` (31496 B, SHA256 из retention) в новый файл; зафиксировать rc, время, size+SHA256 отчёта; raw не изменён (повторная проверка SHA выбранных файлов).
- [ ] 5.2 Закоммитить отчёт (или gzip) и краткую сводку `docs/service-profile-latency-model-K/README.md` с таблицами (b)/(c), gate и ограничениями; независимое ревью модели и отчёта агентом-ревьюером, вердикт и commit записать в PR.
