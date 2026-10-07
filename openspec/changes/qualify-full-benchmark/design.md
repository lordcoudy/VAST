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
   - **Evidence.** Заменено Amendment 1: persisted поле только в guardian operational group; native и SDK процессы выводят clamp в stderr на всех контролируемых путях выхода.
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
4. **Образы.** Native3 пересобираются A/B двумя прогонами через `publication_image_build_v1.py`, receipts должны совпасть побайтно. Неизменность worker2 доказывается сравнением source/dependency/context hashes с `analytics-worker.freeze.json`. Четыре runtime-образа собираются через `build_publication_runtime_images_after_refreeze_v1.py`, затем refreeze (capture ×4 → assemble → `verify-patch`) и 23 packaged checks. Parity 480/32 — через `checkpoint_model_parity_materializer_v4.py`, с независимым аудитом tensor hashes против принятого A244. После этого механически перепривязываются frozen-identity пины тестов, затем выполняются полный ext4 suite и hosted CI. Входы образов фиксируются до сборки; closure фиксируется на `C_Q1` после перепривязки пинов (Amendment 2). Задачи 5.5, 5.6 и весь раздел 7 исполняются на `C_Q1`; между 5.4 и Q1 допустимы только коммиты docs и evidence.
5. **Физическая полоса.** Девять отложенных integration тестов исполняются на стенде по актуальным receipts (`python3.12 -I -B -m unittest <id>`), исходные логи сохраняются. Четыре ручные conformance проверки:
   - R5/S5 — две свежие checkout с autocrlf true и false;
   - R12/S1 — runbook;
   - R14/S2 — хеши g и A269 не менялись;
   - R20/S1 — ext4 relocation custody.
6. **Одна попытка Q1 с заранее объявленными правилами.** Порядок (уточнён Amendment 3): inputs (transaction v2, включая bootstrap) → preprocessing → execution code closure → capture plan (37) → guardian 8/8 → runtime inputs → 4 prechecks → Savant diagnostic → 32 cells → authenticated stop → bind → closure (`--operational-accounting-binding`) → индексы → promotion. Host-скрипты запускаются `python -B -E -s` с записью окружения.
   - Запуск — независимым Windows-процессом (`Start-Process wsl.exe`), как в PR5.
   - Любой отказ означает FAILED Q1 с сохранением evidence. Новая попытка требует reviewed amendment и явного решения человека. Частичные cells не переиспользуются.
   - Перед стартом оператор подтверждает: сон Windows отключён, Windows Update отложен, Docker Desktop UI и extensions не трогаются. Это пункт runbook, не код.
   - Q1 исполняется на одном зафиксированном commit (записывается в receipts). Заменено Amendment 2 (B1): входы образов фиксируются на 5.1, commit Q1 (`C_Q1`) — после перепривязки пинов 5.4, diff closure-модулей ограничен заменами по плану.
   - Container terminal events и первый snapshot маршрута (существующее поведение PR2, задача 23.2 архива `2026-10-03-fix-benchmark-preparations-spec`) проверяются в evidence Q1.
   - **Исход MR при FAILED Q1.** В MR фиксируется FAILED с evidence, пользователю задаётся вопрос. Варианты: (а) reviewed amendment и новая попытка в том же MR; (б) archive и merge уже проверенного кода с честным статусом qualification = failed — только по явному решению пользователя.
7. **Roadmap.** Этапы 2 (Q4, sizing, capacity) и 3 (service, full matrix, `verify/finalize/export`) — отдельные будущие change. Их предпосылки фиксируются в PLAN:
   - для этапа 2 — датированная гарантия ёмкости Seafile от пользователя нужна для приёмки этапа 2 (capacity attestation), а не для старта Q4: требование «Cloud admission uses an actual dated guarantee» не блокирует Q4;
   - для этапа 3 — работающий `systemctl --user` в WSL (WSLg overlay) и место на C:.

## Amendment 1 (2026-10-07, по результатам реализации разделов 2–3)

- **Clamp в evidence.** Сохранять `max_clamp_ns` при успехе можно только там, где процесс уже пишет структурированную evidence. Это guardian operational group (`vast_guardian_operational_group_v1`): writer всегда пишет поле, reader принимает исторические группы без него (R14/S2), а при наличии требует целое 0..10 000 001.
  - У native probe, DeepStream и Savant SDK runtime при успехе сохраняются только size и sha256 process capture, а `native_runtime/` удаляется после arm. Новое поле в строгих валидаторах terminal, acceptance и CSV было бы изменением форматов вне объёма.
  - Поэтому эти процессы выводят clamp в stderr при выходе, а существующие owners сохраняют stderr как failure evidence. Требование уточнено соответственно; предикаты порядка не меняются.
- **Полный перечень full consumers.** Grep показал ещё consumers, принимающие full kinds, с побочными эффектами до отказа или без проверки kind (`evidence/software-v1-consumers/consumers.v1.md`, разделы B и C):
  - index builders не проверяют kind pilot acceptance;
  - `publication_q4_authority_source_request_v1` и `full_publication_identity_manifest_v2` создают и потом откатывают файлы;
  - `publication_q4_authority_source_material_v1` грузит вложенные sources после mkdir;
  - `full_publication_supervisor` создаёт state и lock до проверки;
  - `full_publication_wsl_user_service_v1 materialize` не проверяет kind;
  - Q4 executor проверяет phase receipts только перед Phase B.

- **Уточнения по ревью amendment 1:**
  - (N1) строка clamp выводится и при выходе по исключению или с ненулевым кодом. Процесс, убитый owner (`_terminate_processes`), строку не выведет — остаточный риск.
  - (N2) Q4 preflight проверяет только kind переданных путей, независимо от адаптера и без инжектируемого `production_receipt_loader`.
  - (N3) checkpoint pilot executor — собственный resume-state, а не authority, поэтому вне 3.3. Строки раздела B с пометками «соответствует» и «не применимо» тоже вне 3.3.
  - (N4) supervisor и WSL `materialize` вызывают существующий валидатор identity (`full_publication_identity_artifacts.py`), а не копию проверки.
  - (N5) поле `max_clamp_ns` добавлено без смены `schema_version: 1` — осознанно. Отсутствие поля в исторической группе означает «не наблюдалось» и не отображается как clamp 0.

  Чтобы MODIFIED R13/S6 после archive описывал фактическое поведение, все они входят в этот change. Правило одно: read-only preflight kind до любого побочного эффекта. Временное создание с откатом считается нарушением. В Q4 executor добавляется только ранний read-only preflight переданных receipts, порядок Phase A/B и проверки под lock не меняются.

## Amendment 2 (2026-10-07, перед разделом 5)

- **Worker2 пересобираются, неизменность доказывается по входам.** В `configs/publication_image_build_v1.json` оба worker-образа имеют `base.kind = "produced_image"` от native-образов (OpenVINO и DeepStream). Native-исходники изменились, поэтому native image ID сменятся.
  - `publication_image_build_v1.py` (:526) и refreeze `assemble`/`verify-patch` (`publication_qualification_image_refreeze_v1.py` :1197–1199, :1351) требуют, чтобы `base_image_id` worker был равен новому native `image_id`.
  - Поэтому worker2 пересобираются (`--group analytics_worker --producer-receipt <native-a>`), как в цепочке `20260928g`.
  - «Неизменность входов worker2» означает равенство `source_set`, `dependency_set` и `build_context` hashes нового `analytics-worker.freeze.json` и freeze `20260928g`. Image ID меняется только из-за base.
  - Patch получит блокер `analytics_worker:*_identity_changed_requires_parity_refresh`; его снимает parity 480/32 на новом patch (5.3).
- **Корень сборки и тег.** Тег `qualify_full_benchmark_20261007a`, namespace `qfb-20261007a`. Корень — свежий exact-commit checkout `E:/STUDY/VAST/tmp/qfb-root-20261007a` (NTFS, по схеме `20260928g`, `core.autocrlf=false`). Внутри — копии `models/`, `data/` и нужных git-ignored `artifacts/` (A244, шаблоны packaged checks `20260926d`, рецепты `20260928g`).
  - Копии проверяются полным манифестом с обеих сторон: относительный путь, размер, SHA256. Отказ при extra, missing, link или reparse point.
  - Источник каждого набора (NTFS-копия или ext4 `~/vf*/`) и ожидаемые хеши записываются в манифест до копирования.
  - Сборки, parity и Q1 идут из этого корня без relocation, как в цепочке g. Поэтому R20/S1 (relocation custody) неприменим, если корень не переносится; при переносе он обязателен до 7.1.
  - Рецепты `20260928g` копируются в `artifacts/qualify_full_benchmark_20261007a/` и меняются только в путях, теге и namespace. Diff сохраняется в evidence.
  - Ext4 используется для полного suite (5.5): свежий clone, `scripts/run_ci_checks.py --expected-commit`.
- **Source freeze и пины (B1).** Ожидаемые идентичности образов лежат и внутри модулей execution code closure: `EXPECTED_IMAGE_ID`, `EXPECTED_BASE_IMAGE_ID` и labels в `scripts/checkpoint_gstreamer_publication_runtime_v3.py` и `scripts/checkpoint_openvino_gva_publication_runtime_v3.py`. Pin GStreamer указывает на `decision28-2a6a42c9`, а не на g. Поэтому:
  - на 5.1 замораживаются входы сборки образов (allowlists и Dockerfile);
  - closure и commit для Q1 (`C_Q1`) — это commit после перепривязки пинов 5.4;
  - diff closure-модулей между commit сборки и `C_Q1` должен состоять только из рассмотренных литеральных замен по плану;
  - инвентарь пинов строится по фактическим старым значениям идентичностей (image ID, base ID, sha, size, пути), а не по строке `20260928g`. В него входят и pinned пути/size/sha в `checkpoint_*_qualification_fragment_v3.py`, которые импортируются динамически и не видны статическому closure.
- **Перепривязка пинов шире инструмента `20260928g`.** Кроме 7 файлов g, пины есть в:
  - `tests/test_publication_gstreamer_component_inputs_v1.py`;
  - `.ci/fixtures/additional-origins.v1.json`;
  - копиях фикстур `.ci/fixtures/gstreamer_fragment_unit_v1/artifacts/fix_benchmark_preparations_20260928g/**`.

  Инструмент расширяется на эти файлы. План замен сохраняется до применения, применяются только строковые замены old→new (исключение — `.ci`-фикстуры, см. ниже), diff проверяется. Новые `configs/*qfb-20261007a*` из parity коммитятся.
  - **`.ci`-фикстуры (B2)** строковой заменой не правятся. Создаются проверенные побайтовые копии новых артефактов по новому пути (`.ci/fixtures/.../artifacts/qualify_full_benchmark_20261007a/**`). Связки `fixture_path`↔`original_path` в `additional-origins.v1.json` обновляются на новые пары. Существующие тесты origin-связок должны проходить.
- **Сеть.** BuildKit обращается к registry за метаданными закреплённых по digest base-образов даже при `--pull=false`. Сеть доступна напрямую. Proxy обходится только в окружении отдельной команды (`env -u HTTPS_PROXY -u HTTP_PROXY`), постоянные настройки системы не меняются. Base-образы проверены `docker image inspect <ref@digest>` (5.0).

## Amendment 3 (2026-10-07, по результатам runbook 6.1 и ручных проверок 5.7)

- **B1: Docker socket в capture plan.** `publication_operational_stock_operations_v1.py` зашивает `/var/run/docker.sock`, а проверка socket требует, чтобы путь совпадал с `resolve()`. На этом хосте `/var/run` — symlink на `/run`, поэтому шаг capture plan гарантированно падает с кодом 78. Component runbook уже передаёт `/run/docker.sock` явно.
  - Добавляется флаг `--container-engine-socket`. По умолчанию прежнее значение, проверки socket не меняются. Test-first.
  - Это closure-модуль, поэтому `C_Q1` переносится на новый commit, а 5.5–5.7 повторяются на нём. Входы образов не меняются, пересборка не нужна.
- **R5/S5.** Свежая checkout с `core.autocrlf=true` превращала в CRLF четыре входа образов, добавленные после byte freeze. Добавлены точные правила `text eol=lf` и тест «каждый вход образа имеет явное EOL-правило». Blob'ы уже были LF, поэтому байты образов не изменились.
- **Ext4 suite и сеть.** Хранилище моделей OMZ доступно только через Windows proxy `127.0.0.1:12334`, недоступный из WSL NAT. Локальный suite получает 8 эталонных файлов `.ci/model-assets.v1.json`, заранее положенных в ignored `models/`. `prepare_ci_model_assets.py` сам проверяет их по size, sha256 и sha384, а при расхождении отказывает. Hosted CI скачивает модели как обычно.
- **Уточнения порядка Q1 (по коду, runbook `docs/full-qualification-runbook.md`):**
  - runtime inputs строятся после старта guardian: им нужен живой socket guardian, как в цепочке g;
  - bootstrap выполняется внутри transaction v2;
  - host-скрипты запускаются `python -B` без `-I`: в Python 3.12 `-I` убирает `scripts/` из `sys.path`;
  - resume по exit 75 в цепочке Q1 не поддерживается, owner отказывает при существующем checkpoint. Любой отказ означает FAILED Q1.
- **Проверки prechecks и Savant.** Ad hoc аудиты цепочки g заменяются встроенными проверками owner: настоящие process/container validators и ledger 37 операций на шагах execute и bind.
- **Promoted bundles.** Promotion сама валидирует свой результат. Отдельный вызов приватных `_cold_validate_promoted_*` не делается; вместо него — независимая read-only проверка результатов Q1 в 7.6.
- **Место на дисках.** Используется существующий минимум 20 GiB на каждом нужном томе (C:, E:, ext4) перед стартом Q1.
- **Перенос evidence Q1 (7.6)** — как в PR5: originals копируются в change, крупные файлы описываются size+SHA256 с указанием местоположения.

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
