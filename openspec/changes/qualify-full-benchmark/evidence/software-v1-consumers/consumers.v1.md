# Full consumers: перечень и R13/S6 (задачи 3.1–3.2)

Изменение: `qualify-full-benchmark`. Базовый commit: `36c395be`. Требование: MODIFIED «Recovery first proves a bounded genuine native pair», сценарий «Component authority reaches a full entrypoint».

Тесты: `tests/test_full_consumers_foreign_kind_v1.py`.

- Каждый тест подаёт в реальный вход consumer три чужих kind:
  - component (`vast_gstreamer_component_authority_v1`, либо ближайший аналог: `vast_gstreamer_component_runtime_bundle_v1` или `vast_guardian_component_preprocessing_contract_materialization_v1`);
  - study (`finite-component-study`);
  - unknown (`vast_unknown_full_authority_kind_v1`).
- Чужой kind подставляется в валидную fixture существующих тестов модуля. Меняется только `artifact_kind`; self-hash пересчитывается там, где он проверяется раньше kind.
- Проверяется ошибка или exit code самого consumer и текст именно kind-проверки.
- Снимок всего свежего temp root (inputs, output roots, work roots) должен совпасть побайтно до и после вызова.

Логи:
- `red.original.log` — код до изменений (новый файл тестов на `36c395be`);
- `green.original.log` — после 3.2;
- `regression.original.log` — существующие модули тестов изменённых consumers и модулей, которые их импортируют (29 + 38 + 60 тестов, OK).

## Как собран перечень

1. `grep -l '^def main('` по `scripts/*.py` с фильтром по `qualification|accepted_policy|promot|q4|full_publication|full_resource`: 63 CLI.
2. Для каждого CLI проверено, принимает ли он на вход full kinds (qualification, accepted-policy, promotion, Q4, full publication) и не является ли он только producer'ом или компонентом. Проверялись константы `*_KIND`, проверки `artifact_kind ==` и цепочка вызовов.
3. В список «reviewed» вошли девять consumers из задачи 3.1. Дополнительные CLI, найденные grep'ом, приведены во второй таблице с решением.

## A. Reviewed full consumers (задача 3.1): тест, RED и GREEN

| # | Consumer, вход | Чужой kind подаётся в | Проверка kind (file:line) | Первая запись (file:line) | RED (до) | GREEN (после) |
|---|---|---|---|---|---|---|
| 1 | `scripts/publication_policy_qualification_runtime_inputs_v2.py` `main` :3499 → `materialize_…` :3426 | candidate index; qualification transaction receipt | executor `_load_qualification_inputs` :1167 (index kind :1212), `_validate_input_transaction_receipt` :987; вызов :3086 | `tempfile.mkdtemp` :3213, `_write_exclusive_bytes` :1668, `_copy_engine_asset` :2657 — все после kind | pass (6/6) | pass, код не менялся |
| 2 | `scripts/publication_policy_qualification_pilot_executor_v2.py` `main` :4864 → `execute_qualification_pilots_v2` :4799 | candidate index; runtime-input materialization receipt | :1212; «runtime-input materialization receipt binding drifted» :1824 | до 3.2: `_ensure_output_root(pilot_root)` и lock `.qualification-pilot-executor-v2.lock` в `_entry_held` до любой проверки; checkpoint parent :4199 до проверки operational inputs | **FAIL 6/6**: созданы `fresh/`, `fresh/pilots/`, lock-файл, для runtime receipt ещё `fresh-state/` | pass: read-only `_preflight_qualification_authority_v2` :4638 вызывается :4739 до `_ensure_output_root` :4761 |
| 3 | `scripts/publication_policy_qualification_execution_closure_v1.py` `main` :3363 (exit 78) | qualification transaction receipt; guardian preprocessing receipt | transaction :1345–1358; preprocessing :1428–1440 (self-hash :1425 раньше kind, тест его пересчитывает) | `PhysicalRootCustodyV1.open` и `ensure_directory` :3092–3095 после `_validate_chain` | pass (6/6) | pass, код не менялся |
| 4 | `scripts/publication_guardian_accepted_policy_preprocessing_contract_v1.py` `materialize_accepted_policy_guardian_preprocessing_contract_v1` :946 (main :1163, exit 78) | accepted policy qualification receipt; completed qualification index | accepted receipt :548–556; completed index :459–471 | `_commit_receipt_last_bundle_v1` (intent-файл, output, atomic staging) :1001 после `_source_material` | pass (6/6) | pass, код не менялся |
| 5 | `scripts/publication_policy_qualification.py` `main` :1394 → `promote_policy_qualification` :1294 | qualification index | `assess_policy_qualification` :957–964 | `custody.ensure_directory` :1329 после `assessment["passed"]` | pass (3/3) | pass, код не менялся |
| 6 | `scripts/full_resource_qualification.py` `main` :1367 → `promote_full_resource_qualification` :1262 | qualification index | `assess_full_resource_qualification` :914–923 | `custody.ensure_directory` :1301 | pass (3/3) | pass, код не менялся |
| 7 | `scripts/publication_q4_authority_plan_pipeline_v1.py` `main` :2787 → `run_cli` :2698 (exit 78), фазы `source-spec`, `phase1`, `phase2` | source material; source spec; Phase1 receipt | `validate_…_source_spec_v1` :665–677; `validate_…_phase1_receipt_v1` :1693–1706 | `commit_or_adopt_exact_identity` :1106; `_create_output_custody` → `mkdir_child_exclusive` :855 — только после kind | pass (9/9) | pass, код не менялся. Опасение design.md про :855 не подтвердилось |
| 8 | `scripts/backend_q4_two_phase_executor_v1.py` `main` :6549 → `run_cli` :6492 (exit 78) → `execute_backend_q4_two_phase_v1` :6164 | Q4 source registry | `_validate_source_registry` :3931–3938 | до 3.2: `_ensure_directory(work_dir)` стоял перед `_validate_source_registry` | **FAIL 3/3**: созданы `fresh/`, `fresh/q4-work/` | pass: `_validate_source_registry` перенесён раньше `_ensure_directory` :6212 |
| 9 | `scripts/full_publication_entrypoint.py` `main` :3618 (exit 78), команды `preflight run status verify finalize export` | identity artifact manifest (`--identity-artifacts`) | `scripts/full_publication_identity_artifacts.py:1835` | run root создаётся только в `runner.run()`. `_validated_run_root` :441 ничего не создаёт | pass (18/18) | pass, код не менялся |

Команда `plan` в full publication не читает kind-bearing входов и не создаёт файлов, поэтому не тестируется.

## B. Дополнительные CLI из grep (вне reviewed списка 3.1)

Поведение определено статическим разбором. Тесты здесь не добавлялись и код не менялся: эти CLI не входят в согласованный перечень задачи 3.1. Для отмеченных «gap» нужно решение на ревью (amendment к 3.1/3.2 или явное исключение из R13/S6).

| CLI | Что принимает | Поведение при чужом kind | Статус |
|---|---|---|---|
| `scripts/publication_policy_qualification_index_v2.py` `main` :788, `build_policy_qualification_index_v2` :683 | fragments, execution closure, pilot acceptances | fragment и closure kind проверяются до commit. Kind `checkpoint_qualification_pilot_acceptance.json` в `_build_pilots` :342 не проверяется, только хешируется: index записывается, отказ наступает позже, в promotion (строки 5–6 таблицы A) | gap (builder, не authority) |
| `scripts/full_resource_qualification_index_v1.py` `main` :668, `build_…` :580 | то же плюс resource binding material | то же: pilot acceptance в `_build_pilots` :341 без проверки kind | gap (builder) |
| `scripts/publication_q4_authority_source_request_v1.py` `run_cli` :2141 | accepted qualification/policy/resource | `_ensure_owned_directory` до `prepare()` :2026. При ошибке `_rollback_owned` удаляет созданное: на диске после отказа пусто, но каталог временно создаётся | gap (транзиентно) |
| `scripts/publication_q4_authority_source_material_v1.py` | request kind `REQUEST_KIND` :60 | request kind :405 проверяется до `ensure_directory` :1217. Вложенные accepted sources грузятся после mkdir | gap для вложенных inputs |
| `scripts/publication_q4_runtime_registry_materializer_v4.py` | plan `PLAN_KIND` | plan проверяется в `main` до записи | соответствует |
| `scripts/backend_q4_two_phase_source_registry_v1.py` `run_cli` | path plan `PATH_PLAN_KIND` :35 | проверка :466 до commit | соответствует |
| `scripts/publication_q4_evidence_runner_v4.py` | Q4 request/runner kinds | read-only, нет output roots (fence запрещает mkdir/O_CREAT) | не применимо |
| `scripts/full_publication_supervisor.py` `main` :602 | аргументы entrypoint, сам identity kinds не читает | `_exclusive_lock` :218 создаёт state dir и lock до запуска дочернего entrypoint; state пишется после exit 78 | gap (Stage 3) |
| `scripts/full_publication_wsl_user_service_v1.py` `materialize` | `--identity-artifacts` только хешируется (:855) | kind не проверяется, bundle коммитится через `mkdtemp` :930. `start` делегирует в `preflight` entrypoint | gap (Stage 3) |
| `scripts/full_publication_identity_manifest_v2.py` `build_…` :374 | accepted receipts через identity loader | кандидат `.full-identity-v2.<token>.json` пишется :309 до проверки kind и удаляется в `finally`: после отказа дерево не меняется | gap (транзиентно) |

## C. Остаточные слоты внутри reviewed consumers (не покрыты 3.2)

- **Q4 executor, production context** (`--phase1-receipt`, `--phase2-receipt`, `--source-materialization-result`). Kind проверяется только в `_prepare_backend_q4_production_context_v1` :793, вызов :6380. Это после work dir, lock :6225, checkpoint, всей Phase A и boundary. При не-default `execute_production_arm` проверка не выполняется вовсе. Перенос меняет порядок Phase A/B и требует решения на ревью (этап 2, Q4 в этом change не исполняется).
- **Pilot executor, checkpoint** (`--checkpoint`). Это собственный output и resume-state executor, а не authority input. Kind проверяется под lock (как и раньше).
