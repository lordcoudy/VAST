# Runbook подготовки полного benchmark VAST

## Фактический этап — 4 октября 2026

Offline CLI реализован: 35 tests passed, 0 skips; два замечания reviewer воспроизведены RED и исправлены. Все четыре original CPU08/GPU02 directories обработаны однократно, каждый CLI exit0. Все 20 исходных файлов (109 802 522 bytes) сохранили SHA256 и семь полей named/held identity. Benchmark/engine/model не повторялись.

[Четырёх-arm отчёт](latency-diagnostics-20261004/four-arm-report.md) показывает исходные counts/drops/100ms misses и критический путь всех 3 325 completed frames. GPU per-frame decoder share p50 — 93,23% / 91,94%; это residence envelope. True queue wait, pure inference и NVDEC busy остаются unknown.

Научная сверка и conformance 4/12 завершены без блокеров. CI реализации A 2a75b470 прошёл: 2 939 successes, 88 точных разрешённых skips, ноль failures/errors; hardware acceptance false. Все девять задач выполнены; спецификация синхронизирована и change архивирован 4 октября. Финальные CI/review/merge архивного коммита фиксируются в [PR3](https://github.com/lordcoudy/VAST/pull/3) после фактического выполнения. [Задачи текущего изменения](../openspec/changes/archive/2026-10-04-explain-benchmark-latency/tasks.md) задают фактический статус. Все PR2 gates уже закрыты.

Следующий научный шаг — отдельно рассмотренный decoder/intake preflight по реальной setup ошибке attempt05; identity correction ещё не реализована. Полный путь остаётся неизменным: три stale sibling runtime renewals (native3/worker2 source совпали), patch-bound parity, original owner/binding для 37 producing operations, 32 qualification cells, Q4 560+560 / 280 sizing, capacity, 5 600 accepted arms / 2 800 durable pairs. Они не исполнены; full eligibility false.

## Предыдущая постановка текущего этапа


## Текущий указатель — 4 октября 2026

PR2 завершён и merged; исходный component benchmark работает. Актуальные статусы, оставшиеся задачи и порядок задаёт [PLAN.md](../PLAN.md), воспроизводимый component entry point — [component runbook](gstreamer-component-benchmark-runbook.md). Полный launch по-прежнему требует fresh all-backend source/image closures,32 qualification cells/promotion,Q4 и storage gates; этот исторический preparation snapshot не даёт допуска. Ниже сохранены исходные даты/счётчики; текущий configured CI существует в .github/workflows/ci.yml.

Этот документ описывает только подготовку: canonical `plan`, текущий `preflight`, materialize неустановленного WSL user-service и его неустановленную validation. Он не разрешает запуск матрицы. До его применения должны быть приняты все repair/qualification/Q4/capacity gates из OpenSpec change `fix-benchmark-preparations-spec`; текущий статус и исторические отказы остаются в [progress.md](../progress.md), а исходные numbered obligations — в [PLAN.md](../PLAN.md).

## Текущее наблюдение g — 28 сентября 2026, 08:29 UTC

Выполнено **33/47** задач; 6.2 прошла. Единственная Savant CPU/H264/independent-processes diagnostic сохранила original invocation `87d5f14c0a7f42ed95cd929edfde8f04`, actual PID 82336 / UID-GID 1000, успешные original process и последующий same-boot root manager terminal. Sole stock terminal/cold auditor PID 82648 / UID-GID 1000 вернул original 0, empty stderr; все 117 descriptors совпали до/после. [Stock receipt](../artifacts/fix_benchmark_preparations_20260928g/qualification_control/savant-original-terminal-audit.v1.json), SHA-256 `bea99007087098f3ed9d9e11b61b8899d2a482e89c3b7c87f86b9c08370ea84f`; [original execution](../artifacts/fix_benchmark_preparations_20260928g/qualification_control/savant-terminal-audit.original.execution.v1.json), SHA-256 `3ebcdae8e78878e57a9b14f8449aacef57e1fb55c87f6e51162d6cdbf1cb7662`. Ни diagnostic, ни auditor не повторялись.

Это nonpromoting diagnostic gate: full-resource coverage/publication bundle binding остаются false. Qualification32 пока не запущена: lifetime guardian counters и measurement-only workload проверяются на согласованность до pilot launch. Q4/capacity/preflight/package/handoff остаются впереди; configured CI отсутствует. `preparation_ready=false`, `publication_ready=false`, **0/5 600 full-run arms**. Приведённые ниже команды применяются только после всех обязательных gates; archive/sync/merge не выполнены.

## Предыдущее наблюдение g — 28 сентября 2026, 08:02:13 UTC

Задача [10.9](../openspec/changes/fix-benchmark-preparations-spec/tasks.md) прошла; выполнено **32/47** задач. Четыре свежих native prechecks имеют original terminal exit 0 и отдельные resource/model audit exits 0, UID/GID 1000. Все четыре chains привязаны к original guardian InvocationID `4728ecc49e5e408ca09cfa1ecf1a81b4` / MainPID `77089` и неизменным физическим evidence:

- **OpenVINO GVA CPU:** original exec `25203` / producer PID `79985`; resource/model auditor PID `80175`/`80203`, оба original exit 0/UID-GID 1000. [Неизменяемая audit chain](../artifacts/fix_benchmark_preparations_20260928g/independent_audits/native_prechecks/openvino_gva_cpu.v1/audit-chain.summary.v1.json), SHA-256 `ce8dee1b76d4c1c123776e6bf84695f33f158d0f2a85f45c5d3d7e923f36910f`.
- **OpenVINO GVA GPU:** original exec `29126` / producer PID `80433`; resource/model auditor PID `80670`/`80698`, оба original exit 0/UID-GID 1000. [Неизменяемая audit chain](../artifacts/fix_benchmark_preparations_20260928g/independent_audits/native_prechecks/openvino_gva_gpu.v1/audit-chain.summary.v1.json), SHA-256 `7c5621556c87e4fe451d59e465b6f68fdffbfd52a9ad0e7e150284d62aa0a333`.
- **GStreamer Custom CPU:** original exec `31005` / producer PID `80893`; resource/model auditor PID `81116`/`81144`, оба original exit 0/UID-GID 1000. [Неизменяемая audit chain](../artifacts/fix_benchmark_preparations_20260928g/independent_audits/native_prechecks/gstreamer_custom_cpu.corrected-live-path.v2/audit-chain.summary.v1.json), SHA-256 `55282b7b26edd09721fa59f9fa07db81cfe41d3b8cacfee1db450e5763dc6207`.
- **GStreamer Custom GPU:** original exec `13356` / producer PID `81383`; resource/model auditor PID `81656`/`81684`, оба original exit 0/UID-GID 1000. [Неизменяемая audit chain](../artifacts/fix_benchmark_preparations_20260928g/independent_audits/native_prechecks/gstreamer_custom_gpu.v1/audit-chain.summary.v1.json), SHA-256 `7b809663ee8d4eb27f6671953e554fbced3514de2abbf71bc59844442a0791f2`.

Это **nonpromoting** evidence: каждый результат сохраняет `accepted=false`, `publication_ready=false`. Savant cold acceptance, qualification32 и Q4 ещё не приняты; capacity guarantee, configured CI, live preflight, current uninstalled package и handoff остаются обязательными. `preparation_ready=false`, **0/5 600 full-run arms**; archive/sync/merge не выполнены. Делегированное self-review остаётся COMMENT. Этот snapshot не разрешает выполнение команд runbook до всех перечисленных ниже gates. [Предыдущие snapshots и отказы](../progress.md), [текущие validation receipts](../openspec/changes/fix-benchmark-preparations-spec/implementation-validation.md), [conformance](../openspec/changes/fix-benchmark-preparations-spec/conformance-progress.md) и локальный [last_run.md](E:/STUDY/VAST/last_run.md).

## Граница операции

Не использовать этот runbook для install, enable, start, launch, `run`, `verify`, `finalize` или `export`. Полученный service receipt не является разрешением на дальнейшее действие. Отдельный запрос на выполнение обязан повторить live preflight и использовать exact receipt.

Шаблоны не публикуют содержимое `seafile.txt`, capability URL, токены, private destination metadata или внутренний baseline manifest. В журнал сохраняют только sanitized argv, descriptors возвращённых receipts, exit code и время наблюдения.

## Проверить перед подготовкой

- Exact planning commit change одобрен, apply явно разрешён, а runtime baseline и source/image/config/data/model identities записаны.
- Repair и пакетные regression checks приняты; прежняя A269 остаётся historical failed attempt. Нельзя переиспользовать её cells, guardian, helpers или checkpoint.
- Приняты свежие 32 qualification cells, lifecycle/closure и policy/resource promotion, затем Q4: 560 phase A, identity/grant boundary, 560 phase B и 280 sizing pairs.
- Есть current dated capacity attestation, связанная с этими 280 sizing pairs и live upload/readback. Старая оценка или недатированная заметка не подходит.
- Live preflight будет выполнять проверки guardian/backend identities, памяти и резерва 20 GiB на results, scratch, temp и host volumes.

Если любой пункт отсутствует или идентичность изменилась после наблюдения, подготовка остаётся blocked. Не запускать зависимый этап и не заменять evidence историческими файлами.

## Контракт путей и переменных

`PROJECT_ROOT` — canonical existing project directory без symlink alias. `runs/full_publication` в нём уже существует. `ATTEMPT_ID` — новый один компонент, точно соответствующий stock grammar `[a-z0-9][a-z0-9._-]{0,79}`: первый символ — строчная латинская буква или цифра, остальные — такие же буквы, цифры, `.`, `_` или `-`; общая длина 1–80. Он не может ссылаться на прошлую попытку. Поэтому `RUN_ROOT` должен быть ровно `PROJECT_ROOT/runs/full_publication/ATTEMPT_ID`, а `STATE_PATH` — ровно `RUN_ROOT/full_publication_supervisor_state.v1.json`.

`SERVICE_DIR` — свежий прямой child `PROJECT_ROOT/artifacts`; он не может быть symlink и не должен перезаписывать прежний bundle. `LINKS_FILE` должен указывать на существующий `PROJECT_ROOT/seafile.txt`, но его содержимое не выводится. `PYTHON` — проверенный frozen interpreter. Все остальные пути должны описывать принятые identity и capacity records.

Разрешённый набор shell variables: `PROJECT_ROOT`, `PYTHON`, `ATTEMPT_ID`, `IDENTITY`, `CAPACITY`, `LINKS_FILE`, `DESTINATION_ID`, `SERVICE_DIR`, `RUN_ROOT`, `STATE_PATH`, `MATRIX_SHA`, `POLICY_SHA`, `ENTRY_ARGS`, `SERVICE_RECEIPT`. Не добавлять неявные переменные и не подставлять capability значения в argv или лог.

## Materialize unstarted bundle

Сначала подставить значения только из принятых records. Команды ниже не выполняют workload и не устанавливают service.

```bash
set -euo pipefail
: "${PROJECT_ROOT:?canonical accepted runtime checkout}"
: "${PYTHON:?verified frozen Python executable}"
: "${ATTEMPT_ID:?fresh single-component full-run attempt ID}"
: "${IDENTITY:?accepted identity manifest path}"
: "${CAPACITY:?accepted dated capacity attestation path}"
: "${LINKS_FILE:?existing private capability file path}"
: "${DESTINATION_ID:?existing accepted destination}"
: "${SERVICE_DIR:?fresh direct child of PROJECT_ROOT/artifacts}"
RUN_ROOT="$PROJECT_ROOT/runs/full_publication/$ATTEMPT_ID"
STATE_PATH="$RUN_ROOT/full_publication_supervisor_state.v1.json"
MATRIX_SHA=a1115ea9fa5f496f45d75636b8376366a48413cdc4c9787cb7ca4baac04b230e
POLICY_SHA=4168818527ced4b3611c9aeabff6b04a7962314f4d80beb3da9dc814ba369016
cd "$PROJECT_ROOT"
ENTRY_ARGS=(
  --project-root "$PROJECT_ROOT" --run-root "$RUN_ROOT"
  --config "$PROJECT_ROOT/configs/experiments.yaml"
  --datasets "$PROJECT_ROOT/configs/datasets.yaml"
  --models "$PROJECT_ROOT/configs/checkpoint_analytics_models_openvino.yaml"
  --identity-artifacts "$IDENTITY" --capacity-attestation "$CAPACITY"
  --cloud-links-file "$LINKS_FILE" --cloud-destination-id "$DESTINATION_ID"
  --expected-matrix-sha256 "$MATRIX_SHA"
  --expected-policy-contract-sha256 "$POLICY_SHA"
  --minimum-free-gib 20 --cloud-timeout-s 120
)
"$PYTHON" scripts/full_publication_entrypoint.py "${ENTRY_ARGS[@]}" plan
"$PYTHON" scripts/full_publication_entrypoint.py "${ENTRY_ARGS[@]}" preflight
"$PYTHON" scripts/full_publication_wsl_user_service_v1.py materialize \
  --project-root "$PROJECT_ROOT" --attempt-id "$ATTEMPT_ID" \
  --run-root "$RUN_ROOT" --state-path "$STATE_PATH" \
  --output-dir "$SERVICE_DIR" --python-executable "$PYTHON" \
  --config "$PROJECT_ROOT/configs/experiments.yaml" \
  --datasets "$PROJECT_ROOT/configs/datasets.yaml" \
  --models "$PROJECT_ROOT/configs/checkpoint_analytics_models_openvino.yaml" \
  --identity-artifacts "$IDENTITY" --capacity-attestation "$CAPACITY" \
  --cloud-links-file "$LINKS_FILE" --cloud-destination-id "$DESTINATION_ID" \
  --expected-matrix-sha256 "$MATRIX_SHA" \
  --expected-policy-contract-sha256 "$POLICY_SHA" \
  --minimum-free-gib 20 --cloud-timeout-s 120 --preflight-timeout-s 900 \
  --max-unexpected-retries 0
```

The entrypoint parser accepts `plan` and `preflight`; both use the frozen matrix and policy SHA-256 values shown above. Its `run_root` must remain below the canonical project root. The materialize example explicitly supplies the canonical inputs, including options for which the parser provides defaults. The materializer checks the exact run-root, state-file basename, direct artifacts child, `seafile.txt`, positive timeouts and non-negative retry budget. The explicit `--max-unexpected-retries 0` is mandatory for this package. An unexpected failure becomes permanent exit 78; supported transport or low-storage recovery remains exit 75 and resumes the same accepted checkpoint.

## Validate only the returned receipt

Read `SERVICE_RECEIPT` from the successful materialize payload without copying a stale path. This validation checks the uninstalled bundle only.

```bash
set -euo pipefail
: "${PROJECT_ROOT:?same accepted runtime checkout}"
: "${PYTHON:?same verified frozen interpreter}"
: "${SERVICE_RECEIPT:?exact receipt path returned by materialize}"
cd "$PROJECT_ROOT"
"$PYTHON" scripts/full_publication_wsl_user_service_v1.py validate \
  --receipt "$SERVICE_RECEIPT"
```

Save the returned descriptor hashes and sanitized argv with the current observation time. A successful validation leaves the service uninstalled, disabled and unstarted. It does not make `preparation_ready`, `full_run_started` or `publication_ready` true by itself.

## Handoff boundary

The later execution owner must recheck every live prerequisite, including guardian and backend identities, host resources, capacity and the service receipt. Preserve the original terminal outcome and the accepted-pair offload order: upload, readback, receipt/ledger, then raw cleanup. A remote size or SHA-256 mismatch remains permanent and retains unverified raw evidence; transient transport/storage recovery must not remeasure accepted pairs.
