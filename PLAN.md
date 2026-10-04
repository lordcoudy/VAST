<!-- CURRENT BENCHMARK RECOVERY 2026-10-04: fix-decoder-preflight -->
# Актуальный план и прогресс — 4 октября 2026

Цель: полностью operable VAST benchmark с воспроизводимыми throughput, latency, потерями и явно ограниченными выводами. Работа продолжается до фактического end-to-end результата. Draft PR4: https://github.com/lordcoudy/VAST/pull/4, change fix-decoder-preflight, branch codex/fix-decoder-preflight. Исторические планы ниже сохранены; они не становятся prerequisites новой конечной study.

Текущее состояние: C 6cdb60023fd07878cb65bf9d61bfe97b252c8878 и producer S2 503b33b224b8f98b429d9a9cf80a0cf30402fcba зафиксированы. Hosted CI37213382200 SUCCESS; canonical root12/nested159, прежние150 cases сохранены. Corrected metadata cold выполнен один раз и независимо принят: report82939B/cd92545dd947741c8decb6f003a3a2325ffb33f60f0d65724648e7947d7e882e, peer review27072B/808d8469f177fdbd201ebee2864b88002ab85027eb80349aa13d6acf2dbc6d5b. Это metadata eligibility, research counts0.

Оригинальный S2 research выполнен ровно один раз и FAILED. Front_gate/default и zero дали по32 packet/output/timing; run02 source exit0, decoder drain получен, но cleanup отказал: physical hash deadline exceeded. Кешированный package Pin сохранил deadline первого запуска; у второго cleanup текущий лимит действовал, но Pin проверял истёкший старый. От decoder drain до terminal около0.24s; исчерпание15s не доказано. Underbody/run03–04 не выполнялись, полный64-pair cohort не принят. Original tools/terminals/failed prefixes сохранены без переписывания.

C failed-research cold выполнен один раз: accepted=false, external original completion refusal, FD6→6, all held descriptors released, close_errors[], два hash-valid32 prefixes causal_join_complete=false/promoted_cohort=false. Report69117B/c2b64e11a6b628442d04f63459732d1840ecaf1ca3568baa31dc9df176b786a1. Независимое review отдельного failed cold закрывается. Benchmark arms0/native pairs0; matrix24/12 ещё не выполнялась.

Ближайший порядок выполнения:

1. В том же PR4 согласовать P3 уточнение четырёх существующих OpenSpec documents: текущий абсолютный deadline фазы для cached Pin, полный rehash/FD/epochs и прежние лимиты; два real-file clock regression cases. Независимое exact planning review до production change.
2. Реализовать узкую правку; RED→GREEN meaningful cases, canonical inherited/new tests, current hostedCI. Зафиксировать новую S3, ordinary source checkout и неизменные raw P1/P2 bindings плюс отдельный exact P3 checkpoint.
3. Создать отдельно reviewed copy external helper только с двумя новыми namespace prefixes. Старый helper43864, S2 failures и все old attempts неизменны. Выполнить одну новую S3 metadata attempt/independent cold; после принятия отдельно reviewed одну four-by32 research attempt и independent cold. Новые namespace parents, без автоматического retry.
4. Закрыть фактические decoder diagnosis, runbooks и conformance всех исходных25 scenarios плюс P3; сохранить остальные19 requirements/diagnostics. Supported sync/archive, same-PR commit/push, latestCI, exact final review и merge PR4.
5. Завершить проверку canonical-study drafts: выбранный decoder mode по настоящим данным; exact first442 display-frame/context mapping; independent reference pixel policy; material/build seam. Все transport variants заранее реализованы/CI-tested/rebuilt в одной source/image до pilot; late source offer отдельно от admission-anchored100ms outcome. Official new change/oneDraftPR/exact planning review.
6. Реализовать минимальный finite study driver/reducer: bounded all-I material, exact0.25/1/2fps schedules, planned/offered/admitted/completed/drop/censor partitions, native/bridge waits и реальный bounded blocked-recv/retirement gate. Selected native/GStreamer rebuild и actual source/media/model/runtime readiness.
7. Prespecified pilot4/max8, затем полностью matrix24arms/12pairs, independent raw numeric reconstruction, loss/Y100/quantiles/paired effects. Negative100ms performance допустим при полной integrity; failed cleanup и partial matrix не заменяют завершение. Conformance/archive/latestCI/finalreview; финально пересмотреть исходные решения и практические ограничения.

Задачи и текущие checkboxes: C:/Users/s-a-balashov/.codex/worktrees/decoder-preflight-v6/VAST/openspec/changes/fix-decoder-preflight/tasks.md. P3 planning amendment записан:32/43 задач;7.2/7.3 закрыты только как FAILED once-execution/independent prefix disposition. Пять новых P3 задач открыты; exact planning review и implementation pending. Evidence: E:/STUDY/VAST/tmp/decoder-preflight-v6-20261004/. Future drafts: E:/STUDY/VAST/tmp/benchmark-strategy-review-20261004/canonical-study-planning-v1/ — пока не approved change и не actual study completion.
<!-- END CURRENT BENCHMARK RECOVERY 2026-10-04 -->


## Фактический этап — 4 октября 2026

Offline CLI реализован: 35 tests passed, 0 skips; два замечания reviewer воспроизведены RED и исправлены. Все четыре original CPU08/GPU02 directories обработаны однократно, каждый CLI exit0. Все 20 исходных файлов (109 802 522 bytes) сохранили SHA256 и семь полей named/held identity. Benchmark/engine/model не повторялись.

[Четырёх-arm отчёт](docs/latency-diagnostics-20261004/four-arm-report.md) показывает исходные counts/drops/100ms misses и критический путь всех 3 325 completed frames. GPU per-frame decoder share p50 — 93,23% / 91,94%; это residence envelope. True queue wait, pure inference и NVDEC busy остаются unknown.

Научная сверка и conformance 4/12 завершены без блокеров. CI реализации A 2a75b470 прошёл: 2 939 successes, 88 точных разрешённых skips, ноль failures/errors; hardware acceptance false. Все девять задач выполнены; спецификация синхронизирована и change архивирован 4 октября. Финальные CI/review/merge архивного коммита фиксируются в [PR3](https://github.com/lordcoudy/VAST/pull/3) после фактического выполнения. [Задачи текущего изменения](openspec/changes/archive/2026-10-04-explain-benchmark-latency/tasks.md) задают фактический статус. Все PR2 gates уже закрыты.

Следующий научный шаг — отдельно рассмотренный decoder/intake preflight по реальной setup ошибке attempt05; identity correction ещё не реализована. Полный путь остаётся неизменным: три stale sibling runtime renewals (native3/worker2 source совпали), patch-bound parity, original owner/binding для 37 producing operations, 32 qualification cells, Q4 560+560 / 280 sizing, capacity, 5 600 accepted arms / 2 800 durable pairs. Они не исполнены; full eligibility false.

## Предыдущая постановка текущего этапа

# Актуальный план VAST — 4 октября 2026

PR [#2](https://github.com/lordcoudy/VAST/pull/2) завершён и слит: merge `c07de9c78e3beaaf276ee54b5f414a3a4b5d035c`, 3 октября, 19:18:11 МСК. Измеренный источник — B `a00aa57f`; исправления CI — D `3c025b29`; финальный проверенный архивный commit — E2 `1f44b9f9`. Это разные источники, их результаты не перепривязаны.

## Выполнено и проверено

- [x] Настоящие CPU08 и GPU02: четыре GStreamer baseline/shared arms, cold validation, штатная остановка guardian и освобождение резервов.
- [x] Независимая обработка всех четырёх arms; 1 080 admissions на arm, без censoring. CPU завершил 516/664 frames, GPU — 1 070/1 075. Дедлайн 100 мс выполнен 0/0 и 3/1 раз соответственно.
- [x] Hosted E2 CI: 2 904 successes, 88 разрешённых skips, ноль failures/errors, шесть native builds и три обязательных native regressions. Независимый ext4 D: 2 906/86, ноль failures/errors.
- [x] Conformance 20 requirements/118 scenarios, sync/archive, окончательное ревью, снятие Draft и merge. Все пять process gates 18.13/18.14/22.3/23.5/24.4 закрыты в фактическом ledger PR2. В архиве оставлен исходный снимок до этих действий.
- [x] Временный owned runtime bind D снят после закрытия consumers; глобальный runtime и измеренный ext4 checkout сохранены.

## Ближайшие задачи: explain-benchmark-latency

Пользователь поручил проверить и выполнить следующий необходимый этап автономно. [Задачи текущего изменения](openspec/changes/archive/2026-10-04-explain-benchmark-latency/tasks.md) — источник статуса реализации; после archive ссылка переносится в архив.

1. Проверить текущие статусы и сохранить исторические исходники документов.
2. Реализовать небольшой offline CLI для критического пути по сохранённым frame events и доступным native policy timings. Отдельно показывать decoder envelope, остаток пути, frame/branch drops и observation gaps.
3. Проверить parser и расчёты на положительных/отрицательных случаях; выполнить анализ всех четырёх реальных arms и независимое научное ревью. Нулевые queue spans в promoted CSV не означают отсутствие ожидания: истинные queue wait/worker service из этих данных отдельно не измерены.
4. Обновить воспроизводимый runbook, проверить соответствие спеки, обязательный CI, archive и окончательное ревью в одном новом PR.

## Оставшийся полный объём

Он не завершён компонентными результатами и не удалён из плана:

- Технический долг: прямые отрицательные проверки всех full consumers (R13/S6), четыре ручных conformance checks, девять физических интеграций; причина исходного CPU07 EPIPE остаётся неизвестной.
- Научный этап: изучить фактические decoder/pacing/queue envelopes; causal correction, изменение intake/corpus/deadline или сравнительные performance claims требуют отдельного контролируемого эксперимента и ревью.
- Full qualification: свежие допустимые all-backend inputs/images/parity/operational identities, четыре native pre-checks, все 32 cells, остановка guardian и stock promotion. Старые A269 partial cells и component authority не дают такого допуска.
- Q4: 560 операций A, граница identities/grants, 560 B, 280 sizing pairs и фактическая датированная storage-capacity attestation.
- Full run: ровно 5 600 accepted arms/2 800 verified durable pairs, прежние workload/order/seed, zero unexpected retries и stock verify → finalize → export.

Полные qualification/Q4/publication/full eligibility остаются false. Новые запуски возможны только после их реальных prerequisites; уже принятые arms не повторяются ради обновления документов. Практический действующий entry point: [component runbook](docs/gstreamer-component-benchmark-runbook.md).

## Исторический план

Ниже сохранён весь прежний документ. Его датированные статусы описывают прошлые попытки; текущий статус и очередность заданы выше.

# Подготовка и запуск полной матрицы VAST

> Статус сверён 21 сентября 2026 в 10:21 UTC. A269 failed после 8/32 cells: guardian exit78 (analytics execution memfd SHA-256 differs from the contract), затем pilot exit1 (savant_endpoint_socket_identity_changed); verifier/promotion также exit1. Все original identities сохранены, MainPID=0, Restart=no. 8 historical DeepStream proofs проверены по 176 descriptors / 141 физическому файлу; qualification не принята. Причина memfd mismatch ещё не установлена. Перезапуск и promotion не выполнялись; Q4/full matrix не запущены. A268 suite/A261 images/A262 parity и предыдущие prerequisites сохранены. Полный объём: все32qualificationcells; Q4 560A+identity/grantboundary+560B+280sizingpairs; 5600acceptedarms/2800verifiedSeafilepairs; verify -> finalize -> export. Seafile capacity question без ответа; publication_ready=false. [Failure evidence](artifacts/publication_qualification_runtime_v1_20260921_attempt269/failed-state-check-20260921/failure-analysis.json). Исходные требования ниже сохранены.

## Исходный снимок перед выполнением (6 сентября 2026)
> Текущая безопасная процедура подготовки описана в [docs/benchmark-preparation-runbook.md](docs/benchmark-preparation-runbook.md). Она не меняет исходные numbered obligations ниже и не разрешает запуск полной матрицы.


Методика матрицы согласована: **5 600 запусков / 2 800 пар**, фиксированные параметры, парное сравнение, воспроизводимый порядок и корректная обработка отрицательных результатов. Следующий снимок описывает условия до начала выполнения; актуальный статус приведён выше и в progress.md.

На момент исходной проверки `progress.md` отставал от следующих результатов:

- A131/A132 завершены; актуальная привязка образов и паритета подтверждена.
- [A133 завершён успешно](E:/STUDY/VAST/artifacts/full_suite_ext4_20260906_attempt133/result.json): 2 421 тест, 87 прежних пропусков. Текущие исходники и фикстуры совпадают с проверенными хешами.
- Входы, preprocessing и execution closure A134 готовы. Guardian, runtime bundles, видеодиагностика Savant и 32 пилота ещё не выполнены.
- На **C: свободно 0 байт**; на E: около 327 ГиБ. Активных контейнеров и процессов бенчмарка нет.

Эти исходные условия потребовали очистки C: и двух эксплуатационных исправлений. Они уже выполнены; доказательства и оставшиеся этапы перечислены в progress.md. Разделы ниже сохраняют исходные требования плана и критерии полного завершения.

## 1. Очистка и восстановление окружения

Применить выбранную политику: удалить тяжёлые устаревшие данные, сохранив компактные логи, хеши, receipts и причины отказов.

- Составить перечень удаления с абсолютными путями, размерами и проверкой зависимостей. Сохранить data/models, действующий runtime, A131–A134 и необходимые исторические фикстуры, перечисленные в A133. Старые каталоги не удалять только по номеру попытки.
- Основные кандидаты: зеркало qualification attempt41 — **46,74 ГБ**; старые `vt*`, `vq66g` и временный Python; две устаревшие копии worker image примерно по **10,49 ГБ**; дубли транскодирования примерно **17,9 ГБ**; явно относящиеся к VAST/Docker временные файлы Windows — около **1 ГБ**.
- Перед рекурсивным удалением размонтировать вложенные bind mounts и проверить их отсутствие. Иначе удаление старого тестового зеркала может затронуть настоящие данные.
- Docker очищать выборочно. Реально освобождаемый build cache составляет около **1,86 ГБ**, а не весь показанный объём кэша. Сохранить используемые образы и базовые слои, включая необходимые образы без тегов.
- Выполнить trim, согласованную остановку Docker Desktop и WSL, затем сжатие Ubuntu `ext4.vhdx` и Docker `docker_data.vhdx`. Их текущие размеры — **390,68 и 118,47 ГиБ**; фактическое освобождение измерить после операции. Сжатие выполнять только при отключённых виртуальных дисках. [Требование Microsoft](https://learn.microsoft.com/en-us/powershell/module/hyper-v/optimize-vhd?view=windowsserver2025-ps).
- Восстановить Docker, WSL и три canonical mount штатными helpers; проверить доступность GPU, образы и сохранённые зависимости. Оставить `memory=24GB`.

## 2. Два ограниченных исправления

**Контроль диска.** Сейчас свободное место проверяется однократно и только на диске результатов.

- Добавить необязательный `RunnerCallbacks.before_pair`, проверяющий место перед началом каждой новой пары.
- Проверять файловые системы результатов, фактического scratch/temp и `/mnt/c`, где размещены WSL/Docker.
- Использовать существующий минимум 20 ГиБ на каждом необходимом томе; считать его эксплуатационным порогом, не доказанной оценкой пикового потребления.
- При недостатке места возвращать временную остановку `75`. Восстановление уже принятой пары, которой осталось завершить выгрузку и очистку, должно проходить и через entrypoint/service preflight.

**Seafile readback.** Изолированно воспроизведено: тайм-аут, сброс соединения и `IncompleteRead` ошибочно превращаются в постоянную ошибку целостности.

- Классифицировать эти транспортные исключения как `ArtifactStoreError`, допускающий продолжение через `75`.
- Завершённое чтение с неверным размером или SHA оставить постоянной ошибкой `78`.
- Сохранить порядок: upload → readback → receipt/ledger → удаление локальных raw.

Форматы результатов и параметры эксперимента сохраняются. Эти host-модули не входят в образы или execution closure A134: **пересборка A131, повтор паритета A132 и повтор готовых входных транзакций A134 не нужны**.

## 3. Ограниченная проверка перед допуском

- Добавить регрессии: C: заполнен при свободном E:; место заканчивается между парами; новая пара не запускается; принятая пара восстанавливает offload без повторного измерения.
- Проверить три транспортных сбоя Seafile, сохранение постоянного отказа при неверных SHA/размере и отсутствие повторного исполнения принятых запусков.
- После обеих правок выполнить **один итоговый полный ext4 suite**, проверить пропуски и совпадение исходников до/после. Новый результат потребуется именно из-за изменения кода.
- Создать отсутствующий A134 `operations.py` с фактическими receipts и новым тестовым допуском; обновить ссылку на этот допуск в диагностике A135.
- Выполнить canonical-проверки, запустить guardian с подтверждением 8/8 workers, материализовать 32 runtime bundles.
- Выполнить **одну видеодиагностику Savant A135**. При отказе сохранить доказательства и установить причину; повтор без исправления или новых оснований запрещён.

## 4. Полный запуск и критерии результата

После успешной диагностики:

1. Выполнить все 32 квалификационные ячейки, штатно остановить guardian, проверить lifecycle и завершить policy/resource qualification.
2. Запустить guardian принятой конфигурации; выполнить Q4: 560 запусков фазы A, необходимые identity/grants, 560 запусков фазы B и 280 sizing pairs.
3. Связать гарантию облачного объёма пользователя с полученным sizing через штатную operator attestation. Использовать существующие ссылки Seafile; проверка quota API и создание новой структуры облака не требуются.
4. Завершить проверки identities и canonical `plan/preflight`; запустить полную матрицу через постоянный WSL user service с `--max-unexpected-retries 0`.
5. Подтвердить работающий процесс и первую принятую, выгруженную пару. Возобновлять тот же checkpoint; `78` останавливает выполнение, транспортный `75` допускает продолжение.

Матрицу сохранить полностью: 4 системы × 2 кодека × 2 топологии × 7 политик × 5 дедлайнов × 10 повторов; 6 потоков, seed `20260323`, прогрев 30 секунд и измерение 180 секунд.

Минимальная длительность измерительных окон вместе с Q4 и пилотами — **около 16,4 суток**, дополнительно потребуются запуск процессов, финализация и выгрузка. Полное завершение подтверждается 5 600 принятыми запусками, 2 800 проверенными облачными парами и успешными `verify → finalize → export`.
