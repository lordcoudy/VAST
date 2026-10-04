<!-- CURRENT BENCHMARK RECOVERY 2026-10-04: fix-decoder-preflight -->
# Актуальный план и прогресс — 4 октября 2026

PR3 фактически завершён: архив, conformance 4/12, CI точного E и независимое финальное ревью закрыты; merge 1ab80035c30f6a4f78d2b1aa7be4743288c3721d выполнен 2026-10-04T09:55:55Z и подтверждён remote master. [PR3](https://github.com/lordcoudy/VAST/pull/3) хранит реальные переходы, отрицательный результат 100 мс и ограничения. Это завершение диагностического этапа; общая задача сделать benchmark осмысленным продолжается.

Активное изменение: **fix-decoder-preflight**, ветка codex/fix-decoder-preflight, [Draft PR4](https://github.com/lordcoudy/VAST/pull/4). Спека точного P 3aa35c3b2eedc05d22cf16ba37d470143d080f6b прошла независимое ревью без блокеров; review5405414454 записан до кода. [33 задачи](C:/Users/s-a-balashov/.codex/worktrees/decoder-preflight-v6/VAST/openspec/changes/fix-decoder-preflight/tasks.md), [design](C:/Users/s-a-balashov/.codex/worktrees/decoder-preflight-v6/VAST/openspec/changes/fix-decoder-preflight/design.md).

Прогресс этого снимка: **18/33**. Hosted S1 CI37201708733 FAILED из-за18 обращений synthetic cold fixture к отсутствующему локальному Python path; failure сохранён. Устранена только переносимость fixtures с реальным resolved sys.executable и прежними FD/hash/epoch guards, production canonical argv неизменён. Полный portable root12/nested150 GREEN actuald76983/rc0; все150 success, оба real15s cases и original26/source15 stability подтверждены,5.2 закрыта. [Текущие evidence](C:/Users/s-a-balashov/.codex/worktrees/decoder-preflight-v6/VAST/docs/decoder-preflight-20261004/implementation-progress.v6.md). Новый S2/hosted CI/source root/dispatch review ещё впереди; S1 clone6289 files/347714725 bytes остаётся подготовкой прежнего S1. Metadata/research0, once namespaces не потреблены. Прежние143/150 GREEN/DrVFS/CI failures и original01–05 runs0/null/false-null cleanup не перепривязаны и не исправлены задним числом.

Последовательность выполнения:

1. Исправить общий held-FD readonly backing join для fresh/cache, строгие owner/VMA/epoch/cleanup checks и cached size+SHA; показать реальные RED и GREEN.
2. Исправить P/S/H и отдельные physical/review roots; ввести обязательные sealed metadata-only/research modes с правдивыми provisional/post-close predicates.
3. Запустить все66 inherited и новые regressions через isolated CI adapter; завершить source review и required CI на точном S.
4. Подготовить отдельный ext4 checkout S, один metadata-only preflight без AU/source/pipeline/run и независимый cold read. Лишь после успешной проверки — отдельный review и одна неизменная four×32-AU research попытка с независимым raw replay.
5. По фактическим данным завершить conformance, current docs, sync/archive и final latest-head review в том же PR4.

Новый стратегический маршрут после V6: отдельная рассмотренная задача на сохранение existing worker clocks/process CPU и измерение client/route lock waits. Shared branches используют общий client с mutex через send→recv; это подтверждённый source mechanism, но его численный вклад ещё неизвестен. Затем нужен небольшой заранее заданный end-to-end capacity/arrival-rate study с counterbalanced repetitions и losses/latency/throughput до большой матрицы. Он не заменяет невыполненные старые обязательства и не обещает положительный100ms SLO.

Full32 qualification/Q4/5600 arms, девять physical integrations и scientific/publication eligibility остаются unexecuted/false. Основной dirty checkout сохранён; рабочая реализация находится в отдельном managed worktree. Снимки ниже сохраняют прежний текст полностью и не задают актуальный статус.
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
