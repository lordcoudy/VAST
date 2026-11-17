# Full consumers: перечень и R13/S6 (задачи 3.1–3.3)

Изменение: `qualify-full-benchmark`. Базовый commit 3.1–3.2: `36c395be`; 3.3 (amendment 1): `fd009f0f`. Требование: MODIFIED «Recovery first proves a bounded genuine native pair», сценарий «Component authority reaches a full entrypoint».

Тесты: `tests/test_full_consumers_foreign_kind_v1.py`.

- Каждый тест подаёт в реальный вход consumer три чужих kind:
  - component (`vast_gstreamer_component_authority_v1`, либо ближайший аналог: `vast_gstreamer_component_runtime_bundle_v1` или `vast_guardian_component_preprocessing_contract_materialization_v1`);
  - study (`finite-component-study`);
  - unknown (`vast_unknown_full_authority_kind_v1`).
- Чужой kind подставляется в валидную fixture существующих тестов модуля. Меняется только `artifact_kind`; self-hash пересчитывается там, где он проверяется раньше kind.
- Проверяется ошибка или exit code самого consumer и текст именно kind-проверки.
- Снимок всего свежего temp root (inputs, output roots, work roots) должен совпасть побайтно до и после вызова.
- С 3.3 к каждому тесту (включая раздел A) добавлен creation tripwire: audit hook (`sys.addaudithook`) записывает каждый `open(O_CREAT)`, `os.mkdir`, `os.rename`, `os.link` и `os.symlink` под temp root во время вызова. Поэтому временное создание с последующим откатом тоже считается нарушением.

Логи:
- `red.original.log`:
  - первая секция — 3.1 (новый файл тестов на `36c395be`);
  - секция «Amendment 1 / task 3.3 RED» — разделы B/C на `fd009f0f`, до изменений кода 3.3;
- `green.original.log`: 3.2, затем секция 3.3;
- `regression.original.log`: существующие модули тестов изменённых consumers и модулей, которые их импортируют; секции 3.3 дописаны в конец. Две ошибки `test_full_publication_identity_parity_v4_dispatch` средовые: тест пишет в gitignored `<repo>/staging`, которого нет в свежем worktree. Повтор с временно созданным `staging/` — OK.

## Как собран перечень

1. `grep -l '^def main('` по `scripts/*.py` с фильтром по `qualification|accepted_policy|promot|q4|full_publication|full_resource`: 63 CLI.
2. Для каждого CLI проверено, принимает ли он на вход full kinds (qualification, accepted-policy, promotion, Q4, full publication) и не является ли он только producer'ом или компонентом. Проверялись константы `*_KIND`, проверки `artifact_kind ==` и цепочка вызовов.
3. В раздел A вошли девять consumers из задачи 3.1. Остальные CLI, найденные grep'ом, — в разделе B; их приёмка — задача 3.3 (amendment 1).

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
| 8 | `scripts/backend_q4_two_phase_executor_v1.py` `main` → `run_cli` (exit 78) → `execute_backend_q4_two_phase_v1` | Q4 source registry | `_validate_source_registry` :3967–3974 | до 3.2: `_ensure_directory(work_dir)` стоял перед `_validate_source_registry` | **FAIL 3/3**: созданы `fresh/`, `fresh/q4-work/` | pass: `_validate_source_registry` перенесён раньше `_ensure_directory` :6249 |
| 9 | `scripts/full_publication_entrypoint.py` `main` :3618 (exit 78), команды `preflight run status verify finalize export` | identity artifact manifest (`--identity-artifacts`) | `scripts/full_publication_identity_artifacts.py:1835` | run root создаётся только в `runner.run()`. `_validated_run_root` :441 ничего не создаёт | pass (18/18) | pass, код не менялся |

Команда `plan` в full publication не читает kind-bearing входов и не создаёт файлов, поэтому не тестируется. Tripwire 3.3 для всех строк раздела A после 3.2 нарушений не нашёл.

## B. Дополнительные CLI из grep (задача 3.3, amendment 1)

Правило 3.3: read-only preflight kind до любого побочного эффекта.

Документ, который объявляет `artifact_kind`, должен объявлять ожидаемый full kind. Иначе — отказ: component, study и unknown отклоняются до первого `mkdir` или `O_CREAT`.

Исключение — документы без `artifact_kind` (а для index builders — не-JSON evidence). Supervisor и WSL `materialize` строже: любой разобранный JSON/YAML-объект identity manifest проходит общий валидатор заголовка loader'а целиком (точный набор полей, schema 2, `vast_full_publication_identity_artifact_manifest`); не разбираемый файл остаётся preflight'у entrypoint. Preflight их пропускает, их и дальше проверяет прежняя строгая валидация. Причина: существующие fixtures этих модулей используют такие placeholder'ы (`{"fixture": ...}`, текстовые acceptance, `identity_artifacts\n`). Требовать kind безусловно нельзя без правки существующих тестов, а это запрещено задачей.

| CLI | Чужой kind подаётся в | До 3.3 (RED) | Исправление (GREEN) |
|---|---|---|---|
| `scripts/publication_policy_qualification_index_v2.py` `build_policy_qualification_index_v2` | `checkpoint_qualification_pilot_acceptance.json` одной ячейки | **FAIL 3/3**: отказа нет, index и candidate записываются | `_require_pilot_acceptance_kind` :213, вызов в `_build_pilots` :408 до commit. JSON-объект должен иметь `artifact_kind == vast_checkpoint_qualification_pilot_acceptance_v1` |
| `scripts/full_resource_qualification_index_v1.py` `build_full_resource_qualification_index_v1` | то же | **FAIL 3/3**: index записывается | тот же helper в `_build_pilots` :384, ошибка оборачивается в `FullResourceQualificationIndexV1Error` |
| `scripts/publication_q4_authority_source_request_v1.py` `materialize_…` (production inputs, как в `run_cli`) | accepted policy qualification receipt | **FAIL 3/3**: отказ «header drifted» уже после `_ensure_owned_directory` (создание и rollback) | `reject_foreign_accepted_source_kinds_v1` вызывается :2007 до `_ensure_owned_directory` :2015 |
| `scripts/publication_q4_authority_source_material_v1.py` `materialize_…` | вложенный accepted source (policy qualification receipt) | **FAIL 3/3**: отказа по kind нет; сбой descriptor после `custody.ensure_directory` | `ACCEPTED_SOURCE_KINDS_V1` и `reject_foreign_accepted_source_kinds_v1` :796, вызов :1275 до `ensure_directory` :1286 |
| `scripts/full_publication_identity_manifest_v2.py` `build_…` | policy qualification receipt | **FAIL 3/3**: tripwire видит `open(O_CREAT)` private candidate `.full-identity-v2.<token>.json` | `_reject_declared_foreign_kinds` :134, вызов :392 до `write_exclusive_identity` :403. Покрыты receipts и outputs parity, policy, resource и backend (v1/v3) |
| `scripts/full_publication_supervisor.py` `main` | `--identity-artifacts` в аргументах entrypoint | **FAIL 3/3**: state dir и lock созданы, дочерний entrypoint запущен, state записан (`vast_full_publication_supervisor_state`) | `_reject_foreign_identity_manifest` :272, вызов в `main` :668 до `FullPublicationSupervisor.run` / `_exclusive_lock`. Разобранный manifest-объект проходит общий валидатор заголовка `validate_full_publication_identity_manifest_header_v1` (`full_publication_identity_artifacts.py:98`; им же пользуется loader, :1841) |
| `scripts/full_publication_wsl_user_service_v1.py` `materialize_bundle_v1` | identity artifact manifest | **FAIL 3/3**: отказа нет, bundle закоммичен | `_reject_foreign_identity_manifest` :207, вызов :897 до `tempfile.mkdtemp` :963; тот же общий валидатор заголовка |
| `scripts/publication_q4_runtime_registry_materializer_v4.py` | plan `PLAN_KIND` | проверка в `main` до записи | соответствует, код не менялся |
| `scripts/backend_q4_two_phase_source_registry_v1.py` `run_cli` | path plan `PATH_PLAN_KIND` | проверка :466 до commit | соответствует, код не менялся |
| `scripts/publication_q4_evidence_runner_v4.py` | Q4 request/runner kinds | read-only, нет output roots (fence запрещает mkdir/O_CREAT) | не применимо |

## C. Остаточные слоты внутри reviewed consumers

- **Q4 executor, production context** (`--phase1-receipt`, `--phase2-receipt`, `--source-materialization-result`).
  - До 3.3 kind проверялся только в `_prepare_backend_q4_production_context_v1` перед Phase B.
  - RED: **FAIL 9/9**, work dir создан до отказа.
  - GREEN: ранний read-only `_preflight_production_receipt_kinds_v1` :793. Вызывается :6248, после `_validate_source_registry` и до `_ensure_directory` :6249 и lock :6262. Он требует `schema_version == 1` и точный kind каждого из трёх receipts; применяется, когда в production context есть все три пути (CLI передаёт их всегда).
  - Полная загрузка цепочки (:6417), проверки под lock и порядок Phase A/B не изменены.
- **Pilot executor, checkpoint** (`--checkpoint`). Это собственный output и resume-state executor, а не authority input. Kind проверяется под lock (как и раньше).
