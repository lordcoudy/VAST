# Runbook подготовки полного benchmark VAST

Этот документ описывает только подготовку: canonical `plan`, текущий `preflight`, materialize неустановленного WSL user-service и его неустановленную validation. Он не разрешает запуск матрицы. До его применения должны быть приняты все repair/qualification/Q4/capacity gates из OpenSpec change `fix-benchmark-preparations-spec`; текущий статус и исторические отказы остаются в [progress.md](../progress.md), а исходные numbered obligations — в [PLAN.md](../PLAN.md).

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

`PROJECT_ROOT` — canonical existing project directory без symlink alias. `runs/full_publication` в нём уже существует. `ATTEMPT_ID` — новый один компонент из строчных латинских букв, цифр, `.`, `_` или `-`, длиной 1–80; он не может ссылаться на прошлую попытку. Поэтому `RUN_ROOT` должен быть ровно `PROJECT_ROOT/runs/full_publication/ATTEMPT_ID`, а `STATE_PATH` — ровно `RUN_ROOT/full_publication_supervisor_state.v1.json`.

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

The entrypoint parser accepts `plan` and `preflight`; both use the frozen matrix and policy SHA-256 values shown above. Its `run_root` must remain below the canonical project root. The service parser requires all materialize arguments shown above; it independently checks the exact run-root, state-file basename, direct artifacts child, `seafile.txt`, positive timeouts and non-negative retry budget. The explicit `--max-unexpected-retries 0` is mandatory for this package. An unexpected failure becomes permanent exit 78; supported transport or low-storage recovery remains exit 75 and resumes the same accepted checkpoint.

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
