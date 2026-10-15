## 1. Loader и наблюдение

- [x] 1.1 Создать `scripts/service_profile_latency_model_v1.py` с загрузкой binding через `read_closed_rows` в порядке `reduce_closed_study`, общими caps reducer, собственным analysis deadline ≤ 14400 s и `_recheck_named` после расчёта; проверить тестами на синтетическом binding: успех и полный список descriptors; несовпадение SHA; symlink; не 24 arms; epoch drift до повторной проверки; истёкший deadline — каждый случай даёт ошибку без отчёта.
- [x] 1.2 Проверять pins K (binding 31496 B/`8f92bb40…5ba90`, архив 590982 B/`c483d64f…8d8b`) и сверять каждую `reduce_arm` (canonical JSON) с `reduction.arms[arm_id]`, top-level `binding` и `closed_input_descriptors` архива; проверить тестами, что изменение одного поля arm, binding или descriptor даёт ошибку.

## 2. Профиль обслуживания

- [x] 2.1 Реализовать отбор measured completed requests, join (terminal по `input_frame_key`+branch, wait rows по `request_id`), 7 компонентов в порядке кода с проверкой `clock_domain` для cross-PID компонентов, тождество суммы (0.001 ms), worker backend/residence, `prefix_unqueued` (порог 10 ms, корзины ≤10/10–100/>100 ms), совпадение identity полей native client row и terminal и статистики через `distribution`; проверить тестами: полный join и replay суммы; отсутствующий join (unknown++); дубликат `request_id`; отрицательный компонент; расхождение суммы; чужой boot_id/ненулевые offsets → `unknown`; warmup/drain только в counts; разрыв 2 ms считается queued, 150 ms — unqueued; несовпадение identity поля → ошибка.

## 3. Предиктор

- [x] 3.1 Реализовать discrete-event симуляцию строго по требованию спеки (все слоты schedule, prefix server на pipeline process с буфером 1, analytics buffer 1, совместный кортеж, FIFO route на branch, censoring после `drain_ns`, оценка только measurement, 200 реплик, seed из SHA256, метрики и nearest-rank интервалы); проверить тестами: детерминированный сервис ниже ёмкости → 0 drops и точная латентность; route hold выше интервала → ожидаемая доля `native_pre_detector_queue_full_drop_newest`; prefix выше интервала → shared отбрасывает 4 branches, baseline один; пустой пул → `null`; два запуска → байт-идентичное тело.
- [x] 3.2 Проверить тестом, что ёмкости 1 совпадают с `analytics_queue.max_buffers` и `vastcheckpointprefixqueue max-buffers` на commit `fefab7a93ab5e850ddcb90ac4c9d8eb351811fa0` (`git show`), с явным skip-причиной при недоступном commit.

## 4. Валидация, gates, отчёт

- [x] 4.1 Собрать группы (a), (b), (c), сравнение `route_hold` rate 0.25 против rate 1, пороги сравнения и флаги `gpu_latency_profile_use_permitted`/`queueing_extrapolation_use_permitted`; проверить тестами граничные значения каждого порога, `null`, observed completed = 0, неопределённый p50 и все три сценария флагов.
- [x] 4.2 Писать отчёт `kind` `vast-service-profile-latency-model-v1` без `artifact_kind`, с eligibility = false, SHA256 модуля, source commit, descriptors, немоделируемыми факторами и `new_descriptive_read_not_rereduction`, через exclusive create; elapsed только в stdout receipt; проверить тестами существующий путь/symlink → ошибка и отказ policy calibration validator (`scripts/publication_policy_contract.py`) и finite-study binding loader (`reduce_closed_study`) принять отчёт.
- [ ] 4.3 Проверить, что модуль отсутствует в `deploy/gstreamer_custom/publication/runtime-source-allowlist.txt`, Dockerfile `COPY` и execution closures, зарегистрировать тест в CI selection при необходимости и пройти локальный CI и hosted CI на последнем коммите.

## 5. Запуск на attempt K

- [ ] 5.1 В WSL Python 3.12 среде K выполнить CLI над `/home/s-a-balashov/vffefab7aK/s/run/closed-inputs.original.json` в новый файл; зафиксировать rc, elapsed, size+SHA256 отчёта и что raw не изменён (SHA выбранных файлов до и после); каждый запуск сохранить отдельным файлом.
- [ ] 5.2 Закоммитить отчёт (gzip) и сводку `docs/service-profile-latency-model-K/README.md` со списком всех запусков, таблицами групп (a)–(c), флагами и немоделируемыми факторами; получить независимое ревью реализации и отчёта, записать commit, вердикт и решение по замечаниям в PR.
