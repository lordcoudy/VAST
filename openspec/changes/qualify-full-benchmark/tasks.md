## 1. Постановка

- [ ] 1.1 Draft MR с этим change и независимое техническое ревью спеки на exact planning commit. Готово, когда в MR есть комментарий с вердиктом без блокеров и указанием commit.
- [ ] 1.2 Обновить PLAN.md и progress.md: этапный roadmap (qualification → Q4 + capacity → full matrix + `verify/finalize/export`), текущий этап и пользовательские предпосылки. Готово, когда ссылки на этот change резолвятся.

## 2. Часы Python runtime (test-first)

- [ ] 2.1 RED: тесты `scripts/non_decreasing_wall_clock_v1.py`. Сырые `[t, t−2 ms, t+1]` дают строго растущий выход и `max_clamp`; `t−11 ms` даёт `ClockStepError`; проверить потокобезопасность. Готово, когда тесты падают на отсутствующем модуле.
- [ ] 2.2 GREEN: модуль часов. Готово, когда тесты 2.1 проходят.
- [ ] 2.3 RED→GREEN для DeepStream:
  - fanout и NVDEC интервалы при откате на 2 ms проходят `record_fanout` и `record_nvdec`;
  - protocol bridge: callback/admission и decision/path при откате проходят.
  Предикаты `checkpoint_deepstream_resource_runtime_v3.py` не меняются. Готово при genuine RED на текущем коде и GREEN после подключения.
- [ ] 2.4 RED→GREEN для guardian recorder: `clock_ns=[t, t−2 ms]` для begin и terminal, после чего `publication_operational_request_reconciliation_v1` сверку проходит. Готово при genuine RED и GREEN.
- [ ] 2.5 Static gate в CI: в покрытых runtime-файлах нет прямых wall-clock вызовов для упорядоченных полей вне общего модуля. Все legacy Dockerfile копируют `checkpoint_admission_transport.hpp`. Готово при RED на подставленном нарушении и GREEN на дереве.
- [ ] 2.6 `max_clamp_ns` сохраняется в существующей evidence процессов DeepStream, Savant и guardian. Готово, когда focused тесты проверяют поле.

## 3. Full consumers (R13/S6, test-first)

- [ ] 3.1 RED: для каждого full consumer подать component, study и неизвестный kind. Consumers: qualification runtime inputs v2, pilot executor v2, execution closure v1, accepted-policy preprocessing, policy promotion, resource promotion, Q4 authority plan pipeline, Q4 executor, full publication entrypoint. Ожидаемое поведение: отказ, в свежем root нет новых каталогов и файлов. Готово, когда все тесты есть, а падения записаны.
- [ ] 3.2 GREEN: перенести проверку kind раньше создания каталогов только в упавших consumers. Готово, когда все тесты 3.1 проходят, а прежние тесты не изменены.

## 4. Owner 37 операций (test-first)

- [ ] 4.1 RED: e2e тест `publication_qualification_operational_owner_v1` с реальными process и container validators на fixtures из 2 и 37 операций. Missing, extra, duplicate и foreign операции дают fail closed; binding валиден в cold-closure. Готово, когда тест падает на отсутствующем owner.
- [ ] 4.2 GREEN: stock owner. Prechecks и Savant идут через held operation, 32 cells — через `runtime_registry` в pilot executor; stock writer `vast_original_operational_execution_binding_v1`. Готово, когда 4.1 проходит, а существующие тесты 37/32 и closure не изменены.
- [ ] 4.3 Независимое source-ревью 2–4 и conformance раздела 5C прежнего change. Готово, когда в MR есть ревью без блокеров.

## 5. Образы, parity, пины, CI

- [ ] 5.1 Зафиксировать source commit сборки, после чего source не меняется до конца раздела 7. Пересобрать native3 A/B: receipts побайтно равны. Доказать неизменность worker2 против `analytics-worker.freeze.json`. Готово при сохранённых receipts и сравнении.
- [ ] 5.2 Пересобрать четыре runtime-образа, затем refreeze (capture ×4, assemble, `verify-patch`) и 23 packaged checks. Готово при SUCCESS и сохранённых receipts.
- [ ] 5.3 Parity 480/32 на новом patch и независимый аудит descriptors, groups и tensor hashes против A244. Готово при accepted parity receipt и аудите без расхождений.
- [ ] 5.4 Перепривязать frozen-identity пины тестов и host-констант от `20260928g` к новым receipts. Готово при focused GREEN и diff только по пинам.
- [ ] 5.5 Полный ext4 suite и hosted CI на commit с пинами. Готово при 0 failures/errors и skips, равных разрешённому списку.
- [ ] 5.6 Девять физических integration тестов на стенде. Готово, когда сохранены исходные логи и каждый тест SUCCESS либо записан как FAILED, без замены.
- [ ] 5.7 Ручные проверки R5/S5 (две свежие checkout), R14/S2 (хеши g и A269), R20/S1 (relocation custody) и R12/S1 (runbook). Готово, когда сохранены результаты каждой.

## 6. Runbook и готовность хоста

- [ ] 6.1 Runbook qualification. Команды каждого шага, отказ при отсутствии receipts, `bash -n` для примеров, флаги сверены с argparse. Предстартовые подтверждения оператора: сон Windows, Windows Update, запрет действий Docker Desktop UI. Готово при проверенном runbook.
- [ ] 6.2 Предстартовая проверка хоста: место на C:, E: и ext4, GPU, отсутствие чужих контейнеров и процессов. Готово при сохранённом отчёте. Подтверждение настроек питания запрашивается у пользователя.

## 7. Физическая qualification Q1 (одна попытка)

- [ ] 7.1 Свежие inputs, bootstrap, preprocessing, execution code closure, capture plan (37) и runtime inputs. Готово при сохранённых receipts.
- [ ] 7.2 Guardian 8/8, 4 native prechecks и их аудиты, Savant diagnostic и cold-проверка. Готово при SUCCESS каждого шага.
- [ ] 7.3 32 cells одним owner, без автоповторов. Готово при 32 принятых cells.
- [ ] 7.4 Authenticated stop, lifecycle, cold-closure с точной сверкой 37 операций и 8 workers. Готово при `clean_stop_nonpublication` и успешной closure.
- [ ] 7.5 Policy и resource promotion, cold-проверка promoted bundles. Готово при принятых promotion receipts.
- [ ] 7.6 Независимая проверка результатов Q1 и сохранение evidence в change (originals; raw — по size+SHA256). Готово при ревью без блокеров. Любой отказ в 7.1–7.5 означает FAILED Q1, сохранение evidence и вопрос пользователю.

## 8. Завершение

- [ ] 8.1 Conformance по каждому затронутому требованию и сценарию с фактическими данными; обновить PLAN и progress. Готово при опубликованном отчёте.
- [ ] 8.2 Archive и sync в той же ветке, CI последнего commit, финальное ревью; merge — только с разрешения пользователя. Готово при закоммиченном archive и release ledger с фактическими статусами.
