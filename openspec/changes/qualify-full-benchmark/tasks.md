## 1. Постановка

**Статус 2026-10-06.** Спека одобрена: BLOCK на `da5b0e95` → PASS_WITH_NOTES на `d9b7a8ed`, примечания применены в `36c395be` ([комментарий](https://github.com/lordcoudy/VAST/pull/7#issuecomment-6022112930)). Roadmap внесён в PLAN.md и progress.md.

- [x] 1.1 Draft MR с этим change и независимое техническое ревью спеки на exact planning commit. Готово, когда в MR есть комментарий с вердиктом без блокеров и указанием commit.
- [x] 1.2 Обновить PLAN.md и progress.md: этапный roadmap (qualification → Q4 + capacity → full matrix + `verify/finalize/export`), текущий этап и пользовательские предпосылки. Готово, когда ссылки на этот change резолвятся.

## 2. Часы Python runtime (test-first)

**Статус 2026-10-07.** Выполнено в `qfb/clock` (`f524f6e9`…`90d4e272`), слито в PR. RED/GREEN — [evidence/software-v1-clock](evidence/software-v1-clock/). Финальный прогон: 816 тестов OK, 2 skip. Native-исходники изменились, поэтому пересборка native3 и runtime-образов обязательна (раздел 5). Пин probe `fanout_binding_sha256` перепривязан.

- [x] 2.1 RED: тесты `scripts/non_decreasing_wall_clock_v1.py`. Сырые `[t, t−2 ms, t+1]` дают строго растущий выход и `max_clamp`; `t−11 ms` даёт `ClockStepError`; проверить потокобезопасность. Готово, когда тесты падают на отсутствующем модуле.
- [x] 2.2 GREEN: модуль часов. Готово, когда тесты 2.1 проходят.
- [x] 2.3 RED→GREEN для DeepStream и Savant (откатывающийся raw-источник подставляется в обёртку):
  - fanout и NVDEC интервалы при откате на 2 ms проходят `record_fanout` и `record_nvdec`;
  - protocol bridge: callback/admission и decision/path при откате проходят;
  - Savant: serialized fanout и `canonical_fanout_interval_end_ns` при откате проходят.
  Предикаты `checkpoint_deepstream_resource_runtime_v3.py` и Savant не меняются. Готово при genuine RED на текущем коде и GREEN после подключения.
- [x] 2.4 RED→GREEN для guardian recorder: `clock_ns=[t, t−2 ms]` для begin и terminal, после чего `publication_operational_request_reconciliation_v1` сверку проходит. Готово при genuine RED и GREEN.
- [x] 2.5 Static gate в CI: в покрытых runtime-файлах нет прямых wall-clock вызовов для упорядоченных полей вне общего модуля; каждый native Dockerfile, собирающий probe, копирует `checkpoint_admission_transport.hpp`. Готово при RED на подставленном нарушении и GREEN на дереве.
- [x] 2.6 (Amendment 1) `max_clamp_ns` пишется в guardian operational group; reader принимает исторические группы без поля. Native, DeepStream и Savant выводят clamp в stderr на всех контролируемых путях выхода: обычный return, исключение (включая `ClockStepError`) и ненулевой код. Строку сохраняют existing owners как failure evidence. Готово, когда focused тесты проверяют writer, историческое чтение без отображения clamp 0, недопустимые значения и наличие строки stderr на путях исключения.
- [x] 2.7 Новый модуль добавлен в Dockerfile, source allowlist затронутых runtime-образов и в execution code closure. Готово, когда существующие closure и allowlist тесты проходят с модулем и падают без него.

## 3. Full consumers (R13/S6, test-first)

**Статус 2026-10-07.** Выполнено в `qfb/consumers` (`fd009f0f`, `f11d86a4`), слито в PR. Из 9 consumers раздела A изменены 2: pilot executor v2 и Q4 executor. Все gap-consumers разделов B и C исправлены. 23 теста с audit-hook перехватом любого создания файлов; RED 30 → GREEN 23/23. Ранняя проверка срабатывает по объявленному `artifact_kind`; документы без kind отклоняются прежними строгими проверками. Подробности — [evidence/software-v1-consumers](evidence/software-v1-consumers/consumers.v1.md).

- [x] 3.1 RED: для каждого full consumer подать component, study и неизвестный kind. Перечень сверяется по grep принимаемых kind; найденные сверх списка consumers добавлены задачей 3.3 (Amendment 1). Consumers: qualification runtime inputs v2, pilot executor v2, execution closure v1, accepted-policy preprocessing, policy promotion, resource promotion, Q4 authority plan pipeline, Q4 executor, full publication entrypoint. Ожидаемое поведение: отказ, в свежем root нет новых каталогов и файлов. Готово, когда все тесты есть, а падения записаны.
- [x] 3.2 GREEN: перенести проверку kind раньше создания каталогов только в упавших consumers. Готово, когда все тесты 3.1 проходят, а прежние тесты не изменены.
- [x] 3.3 (Amendment 1) RED→GREEN для consumers со статусом gap из разделов B и C `evidence/software-v1-consumers/consumers.v1.md` (без checkpoint pilot executor): index builders отклоняют чужой kind pilot acceptance до записи index; Q4 source request, source material (вложенные sources), identity manifest v2, supervisor, WSL service `materialize` и phase receipts Q4 executor (ранний read-only preflight только по kind переданных путей, без инжектируемого loader) отклоняют component, study и неизвестный kind до любого создания файлов, включая временные. Готово, когда новые тесты проходят, существующие не изменены, а порядок Phase A/B не изменён.

## 4. Owner 37 операций (test-first)

**Статус 2026-10-07.** Owner реализован в `qfb/owner` (`7705ba7a`, `a8e20c41`). Независимое source-ревью разделов 2–4: PASS_WITH_NOTES, блокеров нет; held-путь prechecks/Savant проверен настоящим `held_stock_operational_request_v1` и `_open_pin` (`f948d0b6`, мутационная проверка M1–M3). Не проверены и остаются риском Q1: финализатор held-операций и реальный старт SDK/OpenVINO. Примечание к R13/S6: «unknown kind» — объявленный чужой `artifact_kind`; документы без kind закрываются downstream-валидаторами (записать в conformance 8.1).

- [x] 4.1 RED: e2e тест `publication_qualification_operational_owner_v1` с реальными process и container validators на fixtures из 2 и 37 операций. Missing, extra, duplicate и foreign операции дают fail closed; binding валиден в cold-closure. Готово, когда тест падает на отсутствующем owner.
- [x] 4.2 GREEN: stock owner. Prechecks и Savant идут через held operation, 32 cells — через `runtime_registry` в pilot executor; stock writer `vast_original_operational_execution_binding_v1`. Готово, когда 4.1 проходит, а существующие тесты 37/32 и closure не изменены.
  - Evidence: `evidence/software-v1-owner/red.original.log` (genuine RED: модуль owner отсутствует; второй RED — held prechecks/Savant до изменения stock runner) и `green.original.log` (19/19 новых, 162 существующих без изменений). Реальны process/container validators, capture, container custody через stock `_invoke_engine`, transfer chain, coordinator, guardian и cold closure; fixture — локальный ELF вместо Docker, in-process producer, stand-in loops held runner/pilot executor, mocked stock CSV cohort (как в существующем тесте 37-binding). Физическая приёмка не заявляется.
- [x] 4.3 Независимое source-ревью 2–4 и conformance раздела «5C. Qualification reconciles the complete operational request domain» (`git show 0cf5f946:openspec/changes/fix-benchmark-preparations-spec/verification-plan.md`, строка 53; задачи 12.2–12.4 в архиве `2026-10-03-fix-benchmark-preparations-spec`). Готово, когда в MR есть ревью без блокеров.

## 5. Образы, parity, пины, CI

**Статус 2026-10-07.** 5.1–5.2 выполнены на `3a7f799d` в корне `qfb-root-20261007a`: native A==B, входы worker2 неизменны, runtime ×4 собраны, refreeze прошёл, packaged checks 23/23. По пути найдены и исправлены test-first два дефекта legacy-сборки, внесённых PR5: нет `checkpoint_study_reference.hpp` в DeepStream/Savant native-образах; заголовок не компилируется под `-Werror` в DeepStream runtime. Подробности — [evidence/physical-v1-images](evidence/physical-v1-images/README.md).

5.3: parity 480/32 на patch `938a2cdd…` (11,5 мин), независимый аудит verified: 3 535 descriptors, 2 478 файлов, все 480 tensor-пар равны A244 ([evidence/physical-v1-parity](evidence/physical-v1-parity/)). 5.4: инвентарь по фактическим значениям, 224 соответствия, 99 мест пинов в 8 файлах, план до применения, diff closure-модулей только по плану (`c9bb5a74`, [evidence/software-v3-pins](evidence/software-v3-pins/)). Новые `.ci`-фикстуры — побайтовые копии с обновлёнными `additional-origins`. Отдельно и явно (не по mapping): `OPENVINO_GVA_EMBEDDED_SET_SHA256` устарел ещё с `95127526` и не совпадал ни с одним receipt; привязан к фактическому `embedded_set_sha256` нового OpenVINO freeze (`0d277622…`).

- [x] 5.0 Предварительная проверка хоста до сборок: место на C:, E: и ext4, отсутствие чужих контейнеров и процессов. Готово при сохранённом отчёте; при нехватке места — остановка и решение пользователя. Отчёт: [pre-build-host-check](evidence/physical-v1-host/pre-build-host-check.v1.txt) — три base-образа по digest на месте, контейнеров 0; свободно C: около 123 GB (88% занято), E: 373 GB, ext4 805 GB.
- [x] 5.1 Зафиксировать commit сборки: входы образов (allowlists, Dockerfile) не меняются до конца раздела 7. Closure и commit Q1 (`C_Q1`) фиксируются после 5.4 (Amendment 2, B1). (Amendment 2) Подготовить корень `E:/STUDY/VAST/tmp/qfb-root-20261007a` (exact commit; копии `models/`, `data/` и нужных `artifacts/` с проверкой SHA256), проверить base-образы по digest. Пересобрать native3 A/B: receipts побайтно равны. Пересобрать worker2 от native-a и доказать равенство `source_set`, `dependency_set` и `build_context` hashes с freeze `20260928g` (неизменность входов). Копии в корне проверяются полным манифестом с обеих сторон. Готово при сохранённых receipts и сравнении.
- [x] 5.2 Пересобрать четыре runtime-образа через существующую детерминированную сборку, затем refreeze (capture ×4, assemble, `verify-patch`) и 23 packaged checks. Готово при SUCCESS и сохранённых receipts.
- [x] 5.3 Parity 480/32 на новом patch и независимый аудит descriptors, groups и tensor hashes против A244. Готово при accepted parity receipt и аудите без расхождений.
- [x] 5.4 (Amendment 2) Инвентарь пинов по фактическим старым значениям идентичностей (включая decision28 и динамически импортируемые fragment-скрипты), план замен до применения, литеральные замены old→new. Для `.ci`-фикстур — новые побайтовые копии артефактов и обновлённый `additional-origins.v1.json`. Новые `configs/*qfb-20261007a*` коммитятся. Готово при focused GREEN и diff closure-модулей между commit сборки и `C_Q1`, состоящем только из замен по плану.
- [x] 5.5 Полный ext4 suite и hosted CI на `C_Q1` (commit с пинами). Готово при 0 failures/errors и skips, равных разрешённому списку. Итог на `C_Q1` `1112af0b`: hosted CI [37584336063](https://github.com/lordcoudy/VAST/actions/runs/37584336063) SUCCESS. Локальный ext4 suite: 3200 run / 3112 ok / 88 skip, 0 failures/errors; набор skip ID равен разрешённому, но у одного теста причина отличается из-за отсутствующего на хосте bind mount venv (`successful=false`, отклонение окружения, как decision29-D) — [evidence/physical-v1-ci](evidence/physical-v1-ci/README.md).
- [x] 5.6 Девять физических integration тестов на стенде. Готово, когда сохранены исходные логи и все тесты SUCCESS. FAILED тест блокирует раздел 7 до диагностики и reviewed amendment. Итог: 9/9 SUCCESS на `C_Q1` `1112af0b` ([evidence/physical-v1-integration](evidence/physical-v1-integration/integration_lane/results.txt)); прежние прогоны на `012232c7`/`e924f3dd` и неудачная попытка вызова сохранены. Тесту DeepStream нужен исторический артефакт `artifacts/deepstream_publication_v3/` — скопирован с манифестом.
- [x] 5.7 Ручные проверки R5/S5 (две свежие checkout), R14/S2 (хеши g и A269), R20/S1 (relocation custody — только если корень Q1 переносится; иначе записать как неприменимое) и R12/S1 (runbook). Готово, когда сохранены результаты каждой. Итог: R5/S5 — две свежие checkout `1112af0b` (autocrlf true/false) воспроизводят все 164 входа образов, деревья чистые; на `012232c7` autocrlf=true давал 4 расхождения → исправлено `.gitattributes` (test-first). R14/S2 — g lifecycle/stop-investigation не менялись с добавления (`a2369f35…` совпадает); A269 — 329 файлов, последнее изменение 2026-09-21, снимок хешей. R20/S1 — неприменим (корень не переносится). R12/S1 — runbook 6.1. [evidence/manual-v1-checks](evidence/manual-v1-checks/).

**Уточнение к 5.5, 7 октября 2026, 11:40 МСК.** Пользователь подтвердил: «ext4 skip is within approved skips». Skip не блокирует Q1; исходный `successful=false` и разница текста причины сохраняются в [evidence/physical-v1-ci](evidence/physical-v1-ci/README.md). Выполненные 5.5/6.0 не переоткрываются из-за этого skip.

## 6. Runbook и готовность хоста

- [x] 6.0 (Amendment 3) RED→GREEN: `publication_operational_stock_operations_v1.py --container-engine-socket` (по умолчанию прежний путь, проверки socket без изменений). Затем новый `C_Q1`, повтор 5.5 (ext4 suite и hosted CI), 5.6 (integration-полоса) и R5/S5 на нём. Готово при genuine RED/GREEN и зелёных повторах.

- [x] 6.1 Runbook qualification. Команды каждого шага, отказ при отсутствии receipts, `bash -n` для примеров, флаги сверены с argparse. Предстартовые подтверждения оператора: сон Windows, Windows Update, запрет действий Docker Desktop UI. Готово при проверенном runbook. Итог: [docs/full-qualification-runbook.md](../../../docs/full-qualification-runbook.md) и [commands.sh](../../../docs/full-qualification-runbook-commands.sh); `bash -n` и сверка 16 вызовов с argparse на `1112af0b` — без расхождений.
- [ ] 6.2 Предстартовая проверка хоста непосредственно перед Q1: место, GPU, отсутствие чужих контейнеров и процессов. Готово при сохранённом отчёте и подтверждении пользователем настроек питания и Windows Update. Предварительная read-only проверка 7 октября, 11:48 МСК — PASS: Docker Desktop 29.8.1, 10/10 pinned images, containers/VAST/CI/compute jobs 0, все тома ≥20 GiB, AC sleep/hibernate 0, Windows Update paused. [Snapshot](evidence/physical-v1-host/pre-q1-ready-host-check.v1.json). Q1 не запущена; финальный stock report и повтор текущей host-проверки — после отдельной команды пользователя непосредственно перед запуском.

**Попытка 1 (7 октября 2026).** Stock 6.2 report попытки 1 сохранён ([host-check.before](evidence/physical-v1-q1-attempt1-failed/q1_control/host-check.before.txt)), шаги 0–1 PASS; шаг 2 — rc 78, попытка FAILED ([evidence](evidence/physical-v1-q1-attempt1-failed/README.md)). Для попытки 2 задача 6.2 выполняется заново после 6A.

## 6A. Amendment 4: re-freeze и подготовка попытки 2

- [x] 6A.1 Failure record попытки 1 в change: originals `q1_control`, манифест namespaces (size+SHA256), read-only диагностика. Готово при закоммиченном evidence.
- [ ] 6A.2 Оператор отключил автообновления Docker Desktop (собственное, Chocolatey, UniGetUI) до конца Q1; версия Docker Desktop/engine/API записана. Готово при подтверждении пользователя в чате и сохранённом наблюдении версии.
- [ ] 6A.3 Re-freeze без пересборки в тег `qualify_full_benchmark_20261008b`: побайтовые копии native/worker/savant-materialized receipts с манифестом, рецепт с diff только тега, capture ×4 → assemble → `verify-patch`, сырые `docker image inspect` в evidence. Готово при SUCCESS и равенстве `image_id`, `inspect_projection_sha256`, `embedded_set_sha256`, `source_identity` прежним receipts (отличается только `inspect_full_sha256`); иначе стоп и решение пользователя.
- [ ] 6A.4 23 packaged checks на тех же образах. Готово при 23/23.
- [ ] 6A.5 Parity 480/32 на новом patch (namespace `qfb-20261008b`) и независимый аудит против A244. Готово при accepted receipt и аудите без расхождений.
- [ ] 6A.6 Перепривязка пинов по инвентарю фактических значений (как 5.4, B2 для `.ci`-фикстур), commit `C_Q1'`. Готово, когда diff от `C_Q1` состоит только из замен по плану и новых `configs/*qfb-20261008b*`.
- [ ] 6A.7 Перевод корня `qfb-root-20261007a` на `C_Q1'`: untracked `configs/*qfb-20261008b*` из parity переносятся в `artifacts/qualify_full_benchmark_20261008b/untracked-configs-before-cq1/` с SHA256 (как перед `C_Q1`), затем `git checkout --detach C_Q1'` и проверка, что закоммиченные configs побайтно равны перенесённым; tracked drift вне `artifacts/` отсутствует до и после; artifacts попытки 1 не тронуты. Готово при сохранённых git status и сверке хешей.
- [ ] 6A.8 Runbook попытки 2: константы `20261008b`, новые SHA256 receipts; в `q1_00_preflight` read-only сверка полного inspect четырёх runtime и projection двух worker с patch, сверка версии Docker; `bash -n` и сверка флагов с argparse. Готово при проверенном runbook.
- [ ] 6A.9 На `C_Q1'`: hosted CI, ext4 suite (одобренный набор skips), integration 9/9, R5/S5; обновить R14/S2 и R12/S1. Готово при зелёных результатах с сохранёнными originals.

## 7. Физическая qualification Q1 (одна попытка)

**Попытка 1 — FAILED** на 7.1 (transaction rc 78), 7 октября 2026. Задачи 7.1–7.6 относятся к попытке 2 на `C_Q1'` после 6A и 6.2 (Amendment 4).

- [ ] 7.1 Свежие inputs, bootstrap, preprocessing, execution code closure, capture plan (37) и runtime inputs. Готово при сохранённых receipts.
- [ ] 7.2 Guardian 8/8, 4 native prechecks и Savant diagnostic через owner со встроенными проверками process/container validators (Amendment 3). Готово при SUCCESS каждого шага.
- [ ] 7.3 32 cells одним owner, без автоповторов. Готово при 32 принятых cells.
- [ ] 7.4 Authenticated stop, lifecycle, cold-closure с точной сверкой 37 операций и 8 workers. Готово при `clean_stop_nonpublication`, успешной closure и наличии container terminal events в evidence.
- [ ] 7.5 Policy и resource promotion; их собственная валидация результата (Amendment 3). Готово при принятых promotion receipts.
- [ ] 7.6 Независимая проверка результатов Q1 и сохранение evidence в change (originals; raw — по size+SHA256). Готово при ревью без блокеров. Любой отказ в 7.1–7.5 означает FAILED Q1, сохранение evidence и вопрос пользователю: amendment и новая попытка в этом MR либо archive и merge кода с честным статусом failed (design, решение 6).

## 8. Завершение

- [ ] 8.1 Conformance по каждому затронутому требованию и сценарию с фактическими данными; обновить PLAN и progress. Готово при опубликованном отчёте.
- [ ] 8.2 Archive и sync в той же ветке, CI последнего commit, финальное ревью; merge — только с разрешения пользователя. Готово при закоммиченном archive и release ledger с фактическими статусами.
