## Context

`origin/master` `ca52381b` содержит код всех стадий полной кампании (qualification, Q4, capacity, service, full run, `verify/finalize/export`), но ни одна стадия не исполнена. Факты, на которые опирается решение:

- **A269 (21.09).** Упала после 8/32 cells: guardian exit 78 «analytics execution memfd SHA-256 differs from the contract», затем `savant_endpoint_socket_identity_changed` как следствие гибели guardian. Доказанные дефекты исправлены в PR2: native client хеширует собственный снимок payload, guardian проверяет envelope до резервирования и пишет диагностику. Исходный источник неверных байтов не установлен.
- **Цепочка g (28.09).** Native prechecks и Savant diagnostic прошли. Затем внешний Docker bulk-stop (`/containers/bulk/:action`) остановил ровно 8 worker-контейнеров, guardian завершился `failed_stop_nonpublication` exit 78. Инициатор неизвестен; защиты в коде нет.
- **EPIPE.** J в PR5 доказан как шаг CLOCK_REALTIME назад примерно на 2 ms внутри процесса probe. CPU07 имеет ту же сигнатуру: native exit 1, затем sidecar EPIPE при `response_send`, но stderr не сохранён. Native probe теперь использует `NonDecreasingWallClock`. Python-рантаймы сохраняют сырой `time.time_ns()` при проверках порядка и ширины:
  - DeepStream: `checkpoint_deepstream_sdk_runtime.py` (fanout и NVDEC интервалы, проверки в `checkpoint_deepstream_resource_runtime_v3.py:185,232`) и `checkpoint_deepstream_protocol_bridge.py` (callback и admission, decision);
  - guardian recorder: `publication_guardian_operational_recorder_v1.py` (`at_ns`, проверка `terminal.at_ns >= begin.at_ns` в `publication_operational_request_reconciliation_v1.py:451`);
  - Savant runtime защищён лишь частично: точечные `max()` стоят на :445 и :554, но serialized fanout ms берётся из сырого `fanout_completed_ns` (:478), а `canonical_fanout_interval_end_ns` при откате может выдать «moved backwards».
- **Транспорт.** Legacy-прогоны используют только `global-client`; `branch-channel` доступен лишь в finite study и от гонки часов не защищает.
- **Owner 37 операций.** Есть stock planning (`publication_operational_stock_operations_v1.py --mode complete_qualification_operational_identity_v1`), capture plan, recorder и cold-closure с проверкой «ровно 37/32» (`publication_policy_qualification_execution_closure_v1.py`). Нет host owner, который открывает `capture_original_engine_processes_v1` для каждой операции; нет обёртки `runtime_registry` для 32 cells в pilot executor; нет stock-писателя `vast_original_operational_execution_binding_v1` (он есть только в тесте); prechecks и Savant в цепочке g запускались неотслеживаемыми ad hoc скриптами.
- **R13/S6.** Прямых negative kind-тестов для full consumers нет. `publication_policy_qualification_runtime_inputs_v2` (`mkdir` на :1668, :2657) и `publication_q4_authority_plan_pipeline_v1` (:855), вероятно, создают каталоги раньше отказа.
- **Образы.** После последних receipts (`20260928g`) коммиты PR5 изменили 6–7 файлов `deploy/native_gst_probe/*` из allowlist всех трёх native-образов и 16–22 файла в каждом из четырёх runtime allowlist. Allowlist worker не менялся. Frozen-identity тесты захардкожены на `20260928g`.
- **Хост.** RTX 3060 12 GB, WSL 24 GB. На C: свободно 118 GB, там же `docker_data.vhdx` 134 GB и build cache 98 GB. Windows уходит в сон через 15 мин на AC. `systemctl --user` в WSL не работает: WSLg перекрывает `/run/user/1000`.

## Goals / Non-Goals

**Goals:**
- Принятая свежая qualification: 4 native prechecks, Savant diagnostic и 32 cells под одним guardian, authenticated stop, lifecycle, cold-closure всех 37 операций, policy и resource promotion. Все receipts сохраняются в этом MR.
- Устранить известный класс single-shot отказов (часы) в Python runtime-путях до исполнения.
- Привести образы, parity и пины к текущему source, без исполнения на stale identities.
- Этапный roadmap до полного продукта в PLAN и progress.

**Non-Goals:**
- Q4, capacity attestation, persistent service, full run, `verify/finalize/export` — следующие change.
- Изменение научных критериев, матрицы, seed, окон, порогов, бюджетов и лимитов.
- Перенос `branch-channel` в legacy runners.
- Расследование A269 memfd сверх уже исправленного (новый отказ будет диагностироваться по сохранённой диагностике PR2).
- Очистка Docker cache и VHDX без отдельного решения пользователя; изменение системных настроек Windows (делает оператор).

## Decisions

1. **Общий Python-модуль `scripts/non_decreasing_wall_clock_v1.py`.** Семантика как в C++ `NonDecreasingWallClock`: `max(last+1, raw)`, `ClockStepError` при шаге назад больше 10 ms, потокобезопасно, `max_clamp_ns()`.
   - **Seam.** Класс `NonDecreasingWallClock(raw_ns=time.time_ns)` оборачивает именно сырой источник; процессный экземпляр отдаёт `wall_time_ns()`.
   - **Подключение.** В DeepStream SDK runtime и Savant runtime встроенные `time.time_ns()` для упорядоченных полей заменяются вызовом процессного экземпляра (новый тестовый seam — подстановка raw-источника). В DeepStream bridge и guardian recorder значение по умолчанию у `clock_ms`/`clock_ns` берётся от процессного экземпляра. Тесты RED→GREEN подставляют откатывающийся raw-источник в обёртку, а не готовые метки, иначе обёртка обходится.
   - **Evidence.** `max_clamp_ns` пишется в существующую persisted evidence Python-процесса. Для native процессов значение из stderr попадает в evidence через owner-retained stderr capture (задача 2.6 проверяет оба пути).
   - **Упаковка.** Модуль добавляется в Dockerfile и source allowlist тех runtime-образов, которые исполняют затронутые скрипты (по фактическим allowlist), и в execution code closure.
   - Почему: минимальное изменение, одинаковая семантика в native и Python. Проверки остаются строгими, а не допускают нулевую ширину.
   - Отклонено: ослабить предикаты (нарушает спеку), monotonic вместо wall (меняет сохраняемые форматы).
   - Static gate в CI запрещает прямые `time.time_ns()` и `time.time()` для упорядоченных полей в перечисленных файлах и проверяет, что каждый native Dockerfile, собирающий probe, копирует `checkpoint_admission_transport.hpp`.
2. **Stock owner 37 операций `scripts/publication_qualification_operational_owner_v1.py`.** Тонкий слой над существующими компонентами:
   - читает stock plan и capture plan;
   - для каждой операции открывает `capture_original_engine_processes_v1`;
   - prechecks и Savant исполняет через `publication_benchmark_native_diagnostic_v1` (held operation);
   - 32 cells — через `execute_qualification_pilots_v2` с обёрткой `runtime_registry`;
   - пишет `vast_original_operational_execution_binding_v1` по рецепту из теста.
   Новых форматов, лимитов и authority не вводится. Missing, extra, duplicate и foreign операции дают fail closed. Ad hoc `qualification_control/*.py` не используются.
3. **Full consumers: проверка kind до побочных эффектов.** Сначала RED-тест на каждый consumer: component, study или неизвестный kind отклонён, в свежем root нет новых каталогов. GREEN только там, где тест упал: проверка переносится раньше `mkdir`. Остальные consumers получают тест без изменения кода.
4. **Образы.** Native3 пересобираются A/B двумя прогонами через `publication_image_build_v1.py`, receipts должны совпасть побайтно. Неизменность worker2 доказывается сравнением source/dependency/context hashes с `analytics-worker.freeze.json`. Четыре runtime-образа собираются через `build_publication_runtime_images_after_refreeze_v1.py`, затем refreeze (capture ×4 → assemble → `verify-patch`) и 23 packaged checks. Parity 480/32 — через `checkpoint_model_parity_materializer_v4.py`, с независимым аудитом tensor hashes против принятого A244. После этого механически перепривязываются frozen-identity пины тестов, затем выполняются полный ext4 suite и hosted CI. Все исходники фиксируются до сборки: после начала physical chain source не меняется.
5. **Физическая полоса.** Девять отложенных integration тестов исполняются на стенде по актуальным receipts (`python3.12 -I -B -m unittest <id>`), исходные логи сохраняются. Четыре ручные conformance проверки:
   - R5/S5 — две свежие checkout с autocrlf true и false;
   - R12/S1 — runbook;
   - R14/S2 — хеши g и A269 не менялись;
   - R20/S1 — ext4 relocation custody.
6. **Одна попытка Q1 с заранее объявленными правилами.** Порядок: inputs → bootstrap → preprocessing → execution code closure → capture plan (37) → runtime inputs → guardian 8/8 → 4 prechecks → Savant diagnostic → 32 cells → authenticated stop → closure (`--operational-accounting-binding`) → индексы → promotion.
   - Запуск — независимым Windows-процессом (`Start-Process wsl.exe`), как в PR5.
   - Любой отказ означает FAILED Q1 с сохранением evidence. Новая попытка требует reviewed amendment и явного решения человека. Частичные cells не переиспользуются.
   - Перед стартом оператор подтверждает: сон Windows отключён, Windows Update отложен, Docker Desktop UI и extensions не трогаются. Это пункт runbook, не код.
   - Q1 исполняется на одном зафиксированном commit (записывается в receipts). «Source» для фиксации — файлы образных allowlist и execution code closure. Перепривязка пинов меняет только тесты и host-константы вне этих файлов, что доказывается сравнением closure hashes до и после.
   - Container terminal events и первый snapshot маршрута (существующее поведение PR2, задача 23.2 архива `2026-10-03-fix-benchmark-preparations-spec`) проверяются в evidence Q1.
   - **Исход MR при FAILED Q1.** В MR фиксируется FAILED с evidence, пользователю задаётся вопрос. Варианты: (а) reviewed amendment и новая попытка в том же MR; (б) archive и merge уже проверенного кода с честным статусом qualification = failed — только по явному решению пользователя.
7. **Roadmap.** Этапы 2 (Q4, sizing, capacity) и 3 (service, full matrix, `verify/finalize/export`) — отдельные будущие change. Их предпосылки фиксируются в PLAN:
   - для этапа 2 — датированная гарантия ёмкости Seafile от пользователя нужна для приёмки этапа 2 (capacity attestation), а не для старта Q4: требование «Cloud admission uses an actual dated guarantee» не блокирует Q4;
   - для этапа 3 — работающий `systemctl --user` в WSL (WSLg overlay) и место на C:.

## Risks / Trade-offs

- **[Неизвестная причина A269 memfd]** → PR2 diagnostic сохраняет первый отказ; при повторе — FAILED и amendment, без повторного запуска наугад.
- **[Внешняя остановка Docker (g)]** → операторский запрет в runbook плюс сохранение container terminal events; код от этого не защищает.
- **[Шаг часов больше 10 ms]** → fail closed с явной ошибкой. Это новый single-shot риск в Python-рантаймах (например, после resume WSL или makestep chrony), принимаемый осознанно: молча принимать неверный порядок хуже. Host clock вне объёма; наблюдаемые в PR5 шаги около 2 ms.
- **[Одна попытка при неустановленной причине A269 memfd]** → риск принимается явно; диагностика PR2 сохраняет первый отказ.
- **[Межпроцессные сравнения часов]** (`arrival_ms`, admission и `source_read`) → остаточный риск, уже задокументирован (≥5,7 ms и p1 = 3 ms запаса), предикаты не меняются.
- **[Длительные сборки и parity, место на C:]** → сборки идут на ext4 (750 GB свободно), C: контролируется перед стартом; при нехватке — остановка и решение пользователя об очистке cache.
- **[Объём change]** → большой, но связный: всё необходимо для одного принятого результата. Q4 и full run вынесены, чтобы MR не жил месяцами.
- **[Время]** → около 1–2 недель работы плюс 5–8 ч физической цепочки.

## Open Questions

Нет вопросов, меняющих объём этого change. Решения пользователя нужны позже:
- до Q1 — подтвердить настройки питания и Windows Update (система);
- до этапа 2 — датированная гарантия ёмкости Seafile;
- по желанию — очистка Docker build cache (около 35 GB освобождаемо).
