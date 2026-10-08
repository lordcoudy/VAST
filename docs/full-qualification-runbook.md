# Runbook полной qualification Q1

Change OpenSpec `qualify-full-benchmark`, задача 6.1. Процедура одной объявленной попытки Q1 (раздел 7): свежие inputs, guardian 8/8, 4 native prechecks, Savant original, 32 cells, authenticated stop, closure 37/8, индексы, promotion. Документ сам ничего не разрешает. Q1 начинается только после выполнения предусловий, задачи 6.2 и явного разрешения пользователя.

Команды лежат в [full-qualification-runbook-commands.sh](full-qualification-runbook-commands.sh) в виде bash-функций `q1_NN_*`. `source` этого файла только задаёт переменные и функции и ничего не исполняет. Каждая функция:
- выполняется в отдельном subshell с `set -euo pipefail`;
- отказывает с кодом 64 (`Q1 REFUSED`), если нет входного receipt или выход уже существует;
- пишет `stdout`, `stderr`, `rc` и `launch.txt` в `$CTRL`; `launch.txt` содержит UTC, `boot_id`, commit, argv, uid/gid, cwd, `python -VV`, `sys.path` и `env` (значения переменных с именами вида TOKEN/SECRET/PASS/KEY/CRED/AUTH маскируются);
- сохраняет SHA256 входов и выходов (`*.inputs.sha256`, `*.outputs.sha256`); следующий шаг сверяет их перед стартом.

## Идентичности

| Что | Значение |
|---|---|
| Commit `C_Q1''` | `4947e35a70fcfd94cf53179f05c021f8fb9dd3d1` (Amendments 4–6: Docker Desktop 4.93.0, Python 3.10 в образах DeepStream/Savant, режимы read-only на drvfs, runtime ×4 пересобраны, пины `20261008d`; попытки 1–2 шли на `1112af0b` и `82c7a62e`) |
| Корень (WSL) | `/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a` (NTFS, `core.autocrlf=false`, без relocation) |
| Тег / namespace | `qualify_full_benchmark_20261008d` / `qfb-20261008d` (попытки 1–2: `20261007a`, `20261008c`) |
| Python | `/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python` (3.12.3), запуск `-B -E -s` |
| Docker | `/usr/bin/docker`, socket `/run/docker.sock` (`/var/run` на хосте — symlink на `/run`) |
| Логи Q1 | `$CTRL = <корень>/artifacts/qualify_full_benchmark_20261008d/q1_control/` |
| Docker engine | запись 6A.2 `docker-engine-identity.6A2.v1.json` (Docker Desktop 4.93.0, server 29.8.1, daemon `aa8f3d33-…`); preflight требует равенства |

Флаг `-I` не используется. В Python 3.12 он включает `-P`, и каталог `scripts/` не попадает в `sys.path`: `--help` любого stock-скрипта падает с `ModuleNotFoundError`. Поэтому запуск идёт `python -B -E -s`: `-E` игнорирует переменные `PYTHON*`, `-s` — user site-packages. Окружение задаётся явно: `TMPDIR=/var/tmp`.

Пути новых namespaces (`QUAL`, `PREP`, `OPS`, `GUARDIAN_OPS`, `EVID`, `PILOTS`, `CHECKPOINT`, `BINDING`, `CLOSURE`, индексы, promoted, `/var/tmp/vqfb1008d/{r,s}`) выбраны runbook. Код фиксирует только имена файлов внутри них. Полный список — в начале `.sh`. Шаг 0 проверяет, что ни один из этих путей не существует.

## Предусловия

### Receipts сборки (5.1–5.4), проверяются шагом 0

| Receipt | Путь (от корня) | SHA256 |
|---|---|---|
| Image identity patch | `artifacts/qualify_full_benchmark_20261008d/qualification_image_identity_patch.json` | `e39e6645…e351` (`image_capture/patch-file.sha256`) |
| Native A freeze | `…/native-a/native_probe.freeze.json` | `57f1a9f3…6ece0` (побайтовая копия) (`receipt-file.sha256`) |
| Worker2 freeze | `…/worker_images/analytics-worker.freeze.json` | `5509b370…f5b554` (побайтовая копия) (`receipt-file.sha256`) |
| Runtime ×4 freeze | `…/runtime_images/{deepstream,savant,openvino_gva,gstreamer_custom}.runtime.freeze.json` | image ID проверяются `docker image inspect` |
| Parity acceptance | `configs/checkpoint_analytics_model_parity.refreshed.v4.qfb-20261008d.accepted.{yaml,assessment.json,acceptance_receipt.json}` | `bad28745…`, `93921576…`, `0c0c786d…` |
| Execution config | `configs/analytics_execution_layer.refreshed.v4.qfb-20261008d.json` | `2079f480…2316` |
| Binding set | `…/model_parity_v4/bindings/index.json`, `…/model_parity_v4/acceptance_binding.v4.json` | `dafb90aa…`, `0a7a4534…` |

Полные значения SHA256 заданы в `q1_00_preflight`. Если хоть одно не совпадает, Q1 не начинается.

### Задачи, которые должны быть закрыты до Q1

Amendment 3 перенёс `C_Q1` на `1112af0b`, поэтому 5.5–5.7 повторяются на этом commit. Receipts на `e924f3dd` для Q1 недостаточны.

- **5.5.** Полный ext4 suite и hosted CI на `C_Q1`. Receipts — `openspec/changes/qualify-full-benchmark/evidence/physical-v1-ci/` (заполняет интегратор).
  - Локальный ext4 suite использует 8 эталонных файлов моделей OMZ из `.ci/model-assets.v1.json`. Они заранее скопированы в ignored `models/`, потому что хранилище OMZ недоступно из WSL NAT. `prepare_ci_model_assets.py` строго проверяет их по size, sha256 и sha384.
  - Hosted CI скачивает эти модели сам.
- **5.6.** Девять integration тестов на `C_Q1`. Прогон на `e924f3dd` лежит в `artifacts/qualify_full_benchmark_20261007a/integration_lane/` (9×rc 0).
- **5.7.** Ручные проверки на `C_Q1`:
  - R5/S5 — `evidence/manual-v1-checks/r5-s5-fresh-checkouts.v1.json`;
  - R14/S2 — `a269-evidence-snapshot.v1.json`;
  - R20/S1 — неприменим, пока корень не переносится;
  - R12/S1 — этот runbook.
- **6.2.** Отчёт о проверке хоста (шаг 1) и подтверждение пользователя в чате.

### Хост: подтверждает оператор до шага 2

Чек-лист — пункт runbook, а не код. Системные настройки меняет только оператор.

1. **Сон Windows отключён.** В PowerShell:
   - `powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`
   - `powercfg /query SCHEME_CURRENT SUB_SLEEP HIBERNATEIDLE`

   «Current AC Power Setting Index» должен быть `0x00000000`. Крышка или кнопка питания не используются.
2. **Windows Update приостановлен** на срок не меньше 12 ч (Settings → Windows Update → Pause). Срок можно прочитать: `Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings' | Select-Object PauseUpdatesExpiryTime`.
3. **Docker Desktop не трогается.** Запрещены: UI, «Stop/Delete all», bulk-действия, extensions, обновление и restart Docker Desktop. Автообновление Docker Desktop выключено. Цепочку g остановил внешний `/containers/bulk/:action`.
4. **WSL не перезапускается.** Запрещены `wsl --shutdown`, `wsl --terminate` и выход из системы. Никаких сборок, CI, `docker prune` и других GPU-нагрузок.
5. **Чужих контейнеров (`docker ps -a` пуст) и процессов VAST нет.** Проверяет шаг 1.
6. **GPU свободна:** в `nvidia-smi` нет compute-процессов. Значения памяти записываются.
7. **Место на дисках.** Шаг 1 кодом требует не меньше 20 GiB свободного места на `/` (корень WSL), `/mnt/c`, `/mnt/e` и `/var/tmp`, иначе отказывает (Amendment 3). Это существующий минимум.

Часы: шаг назад больше 10 ms в Python-рантаймах даёт fail closed (риск принят в design). Не менять время и синхронизацию во время Q1.

## Коды выхода и правило отказа

- `0` — успех.
- `78` — fail-closed отказ stock-скрипта. У guardian и stop это любой lifecycle, кроме `clean_stop_nonpublication`.
- `1` — необработанное исключение. Так завершаются runtime inputs, индексы и promotion: у них нет перехвата.
- `64` — отказ предусловия в функции runbook до запуска stock-команды.
- **Exit 75 и поддерживаемого resume в цепочке Q1 нет.** Owner прямо отказывает при существующем checkpoint. Transaction v2 умеет продолжать receipt-last префикс, но по правилу одной попытки это не используется без решения пользователя.

**Правило.** Попытка Q1 начинается запуском шага 2. После этого:
- любой ненулевой `rc` или отказ 64 означает **FAILED Q1**;
- исключение — read-only шаги 7 и 11 и `q1_watch`. Их можно повторить, только если ожидаемого файла ещё нет: для шага 7 — authority, для шага 11 — `rc` guardian. Неожиданное состояние никогда не «пережидается» повтором.

**При FAILED Q1:**
1. Остановиться и больше ничего не запускать.
2. Ничего не удалять и не переименовывать: `$CTRL`, все namespaces, `/var/tmp/vqfb1008d`, контейнеры.
3. Не выполнять `docker stop`, `rm` или `prune`. Не повторять шаг и не править receipts.
4. Сохранить read-only наблюдение (`q1_watch`, `docker ps -a`, хвосты логов).
5. Спросить пользователя. Если guardian ещё жив, предложить authenticated stop (шаг 10), чтобы зафиксировать lifecycle. Выполнять его только с разрешения.

Дальше по design (решение 6): reviewed amendment и новая попытка в этом MR либо archive и merge с честным статусом failed. Частичные cells не переиспользуются.

## Шаги

Обычные шаги выполняются в терминале WSL после `source "$CTRL/full-qualification-runbook-commands.sh"` (копия создаётся на шаге 0). Длительные шаги 6 и 9 запускаются независимым Windows-процессом, как в PR5: `q1_detach <шаг>` из WSL или эквивалент в PowerShell:

```powershell
Start-Process -FilePath wsl.exe -ArgumentList '-u','s-a-balashov','-e','/bin/bash','/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a/artifacts/qualify_full_benchmark_20261008d/q1_control/full-qualification-runbook-commands.sh','q1_06_guardian_start' -WindowStyle Hidden -PassThru
```

Аргументы не содержат пробелов: Start-Process склеивает их без кавычек. `-u s-a-balashov` запускает процесс от пользователя, а шаги 6 и 9 дополнительно проверяют `id -u` = 1000.

Порядок шагов (design, решение 6 с Amendment 3): inputs → preprocessing → code closure → capture plan → guardian → runtime inputs → owner execute → stop → bind → closure → индексы → promotion.

### 0. Preflight корня — `q1_00_preflight`

- **Цель.** Доказать, что корень находится на `C_Q1`, receipts целы и namespaces свежие.
- **Команда:**

  ```bash
  source /mnt/c/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/docs/full-qualification-runbook-commands.sh
  q1_00_preflight
  ```

- **Входы.** Receipts из таблицы выше, образы Docker, uid 1000, `/var/tmp` на ext4.
- **Проверки.** Отслеживаемые файлы вне `artifacts/` не изменены, Python 3.12.3, socket `/run/docker.sock` канонический. (Amendments 4–5) Идентичность Docker engine равна записи 6A.2, и live `_verify_live_images` нового patch проходит (полный inspect runtime ×4 и projection worker ×2) — до создания namespaces.
- **Выходы.** Создаются `$CTRL`, `PREP_PARENT` и `/var/tmp/vqfb1008d/{,s}` (700). В `$CTRL` — read-only копия `.sh` с SHA256 и `root-git-status.before.txt`.
- **Успех.** `Q1 preflight passed`, `$CTRL/q1_00_preflight.rc` = 0.
- **При отказе.** Q1 ещё не начат. Устранить причину по решению пользователя; namespaces не создавались, если отказ случился до `mkdir`.

### 1. Хост перед Q1 (задача 6.2) — `q1_01_host_check`

- **Цель.** Сохранить отчёт о хосте: место, RAM, GPU, контейнеры, процессы, `boot_id`.
- **Команда:** `q1_01_host_check`.
- **Выход.** `$CTRL/host-check.before.txt`.
- **Успех.** Не меньше 20 GiB на `/`, `/mnt/c`, `/mnt/e` и `/var/tmp`. Нет контейнеров и процессов VAST. Пользователь подтвердил пункты 1–4 чек-листа хоста в чате.
- **При отказе.** Q1 не начат: спросить пользователя.

### 2. Свежие inputs и bootstrap (7.1) — `q1_02_transaction`

- **Цель.** `publication_policy_qualification_transaction_v2.py`: фрагменты четырёх систем, candidate index/manifest/receipt и bootstrap-калибровки, receipt пишется последним. Bootstrap выполняется внутри transaction. Отдельный CLI `publication_policy_qualification_bootstrap_v2.py` **не запускается**: его выход не связан с transaction receipt.
- **Входы.** Patch и три файла parity acceptance.
- **Выходы** (`QUAL=artifacts/publication_policy_qualification_v2_qfb_20261008d`):
  - `qualification_input_transaction.v2.receipt.json`;
  - `candidate/*`;
  - `bootstrap/*` (mapping, receipt, 4 calibration);
  - `fragments/<system>/qualification_fragment.json`.
- **Успех.** rc 0, все выходы есть и записаны в `q1_02_transaction.outputs.sha256`.
- **При отказе.** FAILED Q1.

### 3. Preprocessing contract (7.1) — `q1_03_preprocessing`

- **Входы.** Transaction receipt.
- **Выходы.** `PREP/checkpoint_analytics_preprocessing_contract.v1.json` и `.receipt.json`.
- **Успех.** rc 0.
- **При отказе.** FAILED Q1.

### 4. Execution code closure (7.1) — `q1_04_code_closure`

- **Цель.** Зафиксировать исполняемый код `C_Q1`. Перед шагами 6, 8 и 9 closure перепроверяется с `--validate-only` (лог `code-closure-validate.*`).
- **Выход.** `$CTRL/qualification_execution_code_closure.v1.receipt.json`.
- **Успех.** rc 0, stdout `status` = `published` (для свежего пути `adopted` не ожидается).
- **При отказе.** FAILED Q1.

### 5. Capture plan 37 операций (7.1) — `q1_05_capture_plan`

- **Цель.** `publication_operational_stock_operations_v1.py --mode complete_qualification_operational_identity_v1 --container-engine-socket /run/docker.sock`. Ровно 37 originals: 4 native prechecks, Savant original и 32 cells. Резервирует namespaces вывода и guardian context.
- **Входы.** Candidate, bootstrap, transaction, preprocessing, code closure. `--pilot-root` и `--guardian-output-dir` должны совпадать с теми, что получат шаги 6 и 9: owner сверяет `measurement_dir` с namespace pilot, guardian — `output_dir` с context.
- **Выходы.** `OPS/capture-plan/{capture_plan_index,guardian_capture_context,original_operations,source_plan_inventory}.v1.json`, 37 `native_context_NN`, 37 `original-operations/*.original.json`.
- **Успех.** rc 0, счётчики 37/37.
- **При отказе.** FAILED Q1.

### 6. Guardian (7.2), длительный — `q1_detach q1_06_guardian_start`

- **Цель.** Production guardian с `--operational-accounting-context`. Работает до authenticated stop. Перед стартом проверяет `id -u` = 1000.
- **Значения флагов:**
  - `--config` — execution config qfb (на него ссылается parity receipt);
  - `--binding-set` — `model_parity_v4/bindings`;
  - `--policy-capability-manifest` — candidate manifest;
  - `--runtime-dir /var/tmp/vqfb1008d/r`, `--front-socket …/r/a.sock`;
  - `--evidence-root EVID`;
  - `--max-connections 202560`, `--max-requests-per-connection 4320000`, `--max-total-requests 29168640000` — это минимумы `PRODUCTION_*_MINIMUM` в коде.
- **Выходы.** `EVID/service_authority.v1.json`. После stop — `service_lifecycle.v1.json` и `GUARDIAN_OPS/operational_group.v1.json`.
- **Успех.** Проверяется шагом 7. `$CTRL/q1_06_guardian.rc` появляется только после stop.
- **При отказе.** `rc` появился раньше шага 10, или authority не появилась за `--startup-timeout-seconds` (по умолчанию 120 с): FAILED Q1.

### 7. Guardian 8/8 (7.2), read-only — `q1_07_guardian_ready`

- **Успех.**
  - `status=live_operational_nonpublication`;
  - `worker_count=attested_worker_count=8`;
  - front socket существует;
  - `--production-status-authority` возвращает побайтно ту же authority (`guardian-status.ready.json`).
- **При отказе.** Если authority ещё нет, повторить позже. Иначе FAILED Q1.

### 8. Runtime inputs (7.1) — `q1_08_runtime_inputs`

- **Цель.** 32 runtime bundles с `--operational-capture-plan`.
- **Почему после guardian.** Код требует живой seqpacket socket guardian (`--analytics-socket`, тип 0005). Поэтому шаг идёт после guardian (Amendment 3).
- **Флаги.** `--container-engine-socket /run/docker.sock`, `--scratch-root /var/tmp/vqfb1008d/s`, `--deadline-ms 100`, `--duration-s 180`.
- **Выход.** `QUAL/bootstrap/qualification-runtime-inputs-v2/qualification-runtime-inputs.materialization.v2.json`.
- **Успех.** rc 0.
- **При отказе.** FAILED Q1 (guardian остаётся жив, см. правило).

### 9. 4 prechecks, Savant original и 32 cells (7.2–7.3), длительный — `q1_detach q1_09_owner_execute`

- **Цель.** `publication_qualification_operational_owner_v1.py execute`. Пять held originals через stock diagnostic runner, затем 32 cells через `execute_qualification_pilots_v2` с обёрткой `runtime_registry`. Каждый original исполняется один раз под `capture_original_engine_processes_v1`, без автоповторов. После каждого original owner сам выполняет cold-проверку process/container receipts. По Amendment 3 она заменяет ad hoc аудиты prechecks и Savant из цепочки g. Перед стартом шаг проверяет `id -u` = 1000.
- **Входы.** Все receipts шагов 2–8, authority guardian, `--pilot-root PILOTS`, `--checkpoint-path CHECKPOINT` (не должен существовать).
- **Выходы:**
  - `OPS/process-captures/<op>/` ×37;
  - `OPS/diagnostics/<op>/evidence` ×5;
  - 32 каталога в `PILOTS`;
  - checkpoint.
- **Время.** Оценка 3–4 ч: 37 × (30 + 180 + 10 с плюс накладные расходы). Наблюдение только через `q1_watch`.
- **Успех.** rc 0, stdout `{"mode":"complete_qualification_operational_identity_v1",...}` с 37 `operation_ids`.
- **При отказе.** FAILED Q1. Guardian не останавливать без разрешения пользователя.

### 10. Authenticated stop (7.4) — `q1_10_guardian_stop`

- **Команда.** `checkpoint_gstreamer_analytics_sidecar.py --production-stop-authority EVID/service_authority.v1.json`.
- **Успех.** rc 0, lifecycle `status=clean_stop_nonpublication`.
- **При отказе.** FAILED Q1.

### 11. Терминал guardian (7.4), read-only — `q1_11_guardian_terminal`

- **Успех.**
  - `q1_06_guardian.rc` = 0;
  - `EVID/service_lifecycle.v1.json` с `clean_stop_nonpublication`;
  - `GUARDIAN_OPS/operational_group.v1.json` существует;
  - `docker ps -a` пуст, вывод сохраняется в `$CTRL/containers-after-stop.txt`.
- **Почему контейнеров быть не должно.** Guardian запускает workers через `docker run --rm` и останавливает их сам (`docker stop`/`kill`). Runtime-контейнеры cells тоже идут с `--rm`. Поэтому после выхода процесса guardian контейнеров не остаётся.
- **При отказе.** Если `rc` guardian ещё не появился, шаг ничего не проверяет, и его можно повторить через несколько секунд. Любое другое расхождение, включая непустой `docker ps -a`, означает FAILED Q1: оно записывается один раз и не пережидается повтором.

### 12. Execution binding (7.4) — `q1_12_owner_bind`

- **Цель.** `publication_qualification_operational_owner_v1.py bind`: cold-валидация всех 37 process/container receipts (`container_quiescence_verified`, terminal events) и точного namespace, затем `vast_original_operational_execution_binding_v1`.
- **Выход.** `BINDING`.
- **Успех.** rc 0.
- **При отказе.** FAILED Q1.

### 13. Cold closure 37/8 (7.4) — `q1_13_execution_closure`

- **Цель.** `publication_policy_qualification_execution_closure_v1.py --operational-accounting-binding BINDING`: сверка ровно 37 операций с guardian и 8 workers.
- **Выход.** `CLOSURE/qualification_execution_closure.v1.receipt.json`.
- **Успех.** rc 0.
- **При отказе.** FAILED Q1.

### 14. Индексы (7.5) — `q1_14_indices`

- **Команды.** `publication_policy_qualification_index_v2.py` и `full_resource_qualification_index_v1.py` с `--execution-closure-receipt`. Фрагменты передаются явно из `QUAL/fragments/…`: значения по умолчанию указывают на старые `artifacts/*_publication_v3/…`, а индекс требует фрагменты transaction.
- **Выходы.** `POLICY_INDEX_DIR/checkpoint_policy_qualification_index.v2.json`, `RESOURCE_INDEX`.
- **Успех.** Оба rc 0.
- **При отказе.** FAILED Q1.

### 15. Promotion (7.5) — `q1_15_promotion`

- **Команды.** `publication_policy_qualification.py` и `full_resource_qualification.py` (`--index-path`, `--output-dir`). Каждый сам выполняет cold-валидацию своего bundle.
- **Выходы.**
  - policy: capability manifest, calibration mapping, receipt `accepted_evidence_driven_policy_qualification`;
  - resource: capability manifest, receipt `accepted_pre_run_resource_capability_qualification`.
- **Успех.** Оба rc 0, stdout `"status":"promoted"`.
- **При отказе.** FAILED Q1.

Отдельного шага cold-проверки promoted bundles нет (Amendment 3). Его заменяют cold-валидация внутри promotion и независимая read-only проверка в 7.6.

### 16. Хост после Q1 — `q1_16_host_after`

- **Выходы.** `$CTRL/host-check.after.txt`, `root-git-status.after.txt`.
- **Успех.** HEAD корня по-прежнему `C_Q1`. Нет контейнеров и процессов VAST. `boot_id` равен значению до Q1: иначе WSL перезапускался, и это надо отметить в ревью.

После шага 16 — задача 7.6: независимая read-only проверка результатов Q1 и перенос evidence в change, как в PR5. Originals копируются в change; крупные файлы описываются по size + SHA256 с указанием местоположения.

## Открытые вопросы

- **TODO-1.** Receipts 5.5–5.7 на `C_Q1` = `1112af0b`:
  - ext4 suite и hosted CI — в `evidence/physical-v1-ci/`, каталог заполняет интегратор;
  - 9 integration тестов и ручные проверки — повторить на новом commit.
- **TODO-2.** В корне 51 путь изменён или не отслеживается: в `artifacts/` (fixtures тестов) и staging-каталоги `.publication-atomic-staging-v1`, `.publication-directory-journal-v1`, в том числе в `configs/`. Отслеживаемый source чист. Состояние записывается до и после Q1; допустимость подтверждает пользователь.
