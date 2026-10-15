# Инструкция для агентов: `study-gpu-colocation`

Этот документ описывает, как агент (Claude Code, Codex, Grok) ведёт изменение `study-gpu-colocation` от одобренной спеки до merge. Он ничего не добавляет к требованиям. Приоритет источников: `specs/gpu-colocation-study/spec.md` > `design.md` > `tasks.md` > этот документ > `AGENTS.md`/`CLAUDE.md` для общего процесса. Если документы противоречат друг другу или коду, остановитесь и выполните раздел 4.3.

В новом чате назовите изменение: `study-gpu-colocation`. Документы в `openspec/changes/study-gpu-colocation/` дают полный контекст; история переписки не нужна.

## 1. Статус и полномочия

- Ветка `claude/study-gpu-colocation`, Draft PR [#11](https://github.com/lordcoudy/VAST/pull/11). Имя изменения, ветку и PR менять нельзя; второй ветки или PR на эту задачу быть не должно.
- Спека одобрена делегированным self-approval агента 2026-10-15 после трёх раундов независимого ревью. Одобренный коммит записан в комментарии PR «Spec approval».
- Решения пользователя от 2026-10-15:
  1. «Work autonomously. Review and approve by yourself»: агент сам проходит gates, но каждое одобрение выдаёт только после независимого ревью субагентом на точном коммите (раздел 7).
  2. «Merge before Q4/full»: это изменение сливается до Q4/full. Change, который подготовит Q4/full, обязан включить renewal legacy поверх нового source (design §10).
- Только человек решает:
  - удаление или offload любого из 227 сохраняемых Docker образов;
  - вторую preparation attempt или вторую кампанию после провала;
  - обновление, перезапуск или смену версии Docker Desktop/WSL и любые системные или security настройки host;
  - продолжение работы, если repaired Q1 закрыт как failed или без merge.
- Делегирование не разрешает менять параметры, пороги, матрицу или правило решения после первой readiness кампании. До неё любое изменение требований проходит `/opsx:update`, новое независимое ревью и новое self-approval, записанные в PR.

## 2. Входные условия до любого кода

Код, тесты, Dockerfile, CI и images запрещены, пока не выполнены все три условия.

1. Спека одобрена в PR #11. Проверка: комментарий «Spec approval» с SHA коммита.
2. PR #9 (`fix-accepted-policy-preprocessing`) слит в master. Проверка:
   ```bash
   env -u HTTPS_PROXY -u HTTP_PROXY gh pr view 9 --json state,mergedAt,mergeCommit
   ```
   Нужно `state = MERGED`.
3. PR repaired Q1 (`qualify-repaired-full-benchmark`) слит в master с accepted результатом Q1. Найти PR:
   ```bash
   env -u HTTPS_PROXY -u HTTP_PROXY gh pr list --state all --search "qualify-repaired-full-benchmark in:title,body"
   ```
   Нужны `state = MERGED` и явная запись accepted Q1 в PR или в его архиве изменения. Если Q1 закрыт failed или без merge, остановитесь и спросите человека; решение запишите в PR #11.

Если условие не выполнено, не начинайте ничего, кроме документов этого изменения. Сообщите, какое условие не выполнено, и завершите работу.

## 3. Окружение host (обязательно знать до работы)

- **Сеть.** Proxy `127.0.0.1:12334` ненадёжен для GitHub. Выполняйте `git push`/`gh` с `env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy`. Системные proxy настройки не меняйте.
- **Git.** Длинные пути artifacts ломают Windows git («Filename too long») и дают ложные deleted/modified. Для clone/checkout таких деревьев используйте WSL git. WSL git не читает gitfile worktree Claude, поэтому git-зависимые тесты под WSL в `.claude/worktrees/*` пропускаются. Из Git Bash вызывайте `wsl.exe` с `MSYS_NO_PATHCONV=1`.
- **Python в images.** DeepStream и Savant images работают на Python 3.10.12; OpenVINO GVA, GStreamer и host CI — на 3.12. Sidecar и bridge упакованы во все 4 runtime images, поэтому код в них не должен использовать API 3.11+ (`sys.exception`, `add_note`, `ExceptionGroup`, `tomllib` и т. п.). Если на master есть `tests/test_runtime_image_python310_compat_v1.py`, он должен проходить.
- **Файловые системы.** На `/mnt/e` (drvfs) нельзя создать Unix socket (Errno 95), а режим 0444 читается как 0555. Physical runs и sockets — только в private WSL ext4 root (как K: `/home/s-a-balashov/...`, короткий путь, sockets ≤ 108 bytes).
- **Docker Desktop закреплён.** Sidecar принимает только точные наблюдавшиеся сборки, а freeze receipts хэшируют полный `docker image inspect`. Не обновляйте и не перезапускайте Docker Desktop/WSL; auto-updates (Docker Desktop, Chocolatey, UniGetUI) держите выключенными. Если Docker Desktop изменился, нужна новая amendment и пересборка, а не обход. Проверяйте `docker info` (daemon ID), потому что `/run/docker.sock` может уйти на WSL docker-ce.
- **CI.** Inventory разрешённых skips заморожен на 88 (`tests/test_ci_test_selection_v1.py`); новый skip — governance change, не обход. Hosted CI делает checkout depth 1, поэтому тесты не могут читать git историю. Сверку старых файлов делайте по SHA256 из закоммиченной evidence.
- **Хранилище.** Перед сборкой images проверяйте свободное место: C: не ниже 40 GiB плюс пороги файловых систем, которые используются. Если места не хватает, остановитесь: удалять образы нельзя (раздел 1).
- **GPU.** RTX 3060 под WSL2/WDDM. NVML не показывает процессы, MPS не поддерживается и запрещён спекой.

## 4. Начало реализации

### 4.1 Синхронизация

1. Синхронизируйте ветку с master. В worktree приложения используйте инструмент `sync_with_base_branch`, иначе `git fetch origin && git merge origin/master`. Конфликты в документах этого изменения разрешайте в пользу одобренного содержания.
2. Выполните `openspec validate study-gpu-colocation --strict`.

### 4.2 Сверка design с кодом (task 0.3)

1. Перепроверьте все `file:line` из design «Context», §1, §4, §8, §10 на текущем master.
2. Выполните grep по kind строкам:
   ```bash
   grep -rnE "finite[-_]study|finite-component-study" scripts deploy tests --include=*.py --include=*.cpp --include=*.hpp --include=*.h
   ```
   Каждое найденное место классифицируйте как gate, study-path helper, emitter или material/image loader (design §1). Новые места добавьте в design §1.
3. Проверьте, что PR #9 и repaired Q1 не изменили seams: `start_pool`, `reduce_arm`, `prepare`, `_current_workers`, registries, allowlists, closure.
4. Запишите результат сверки комментарием в PR #11 и отметьте task 0.2/0.3.

### 4.3 Если требования расходятся с кодом

Остановите код. Выполните `/opsx:update study-gpu-colocation` (Codex: `$openspec-update-change`), затем независимое ревью и новое self-approval (раздел 7). Только после этого продолжайте. Подгонять спеку под написанный код без ревью нельзя.

## 5. Реализация (`/opsx:apply study-gpu-colocation`)

Перед стартом прочитайте `SKILL.md` apply в `.claude/skills/` или `.agents/skills/`. Работайте строго по `tasks.md` в порядке групп. После каждой задачи:

- запустите её проверку из описания задачи;
- отметьте `- [x]` в `tasks.md`;
- закоммитьте код, тесты и `tasks.md` вместе.

### Группа 1: plan и kind

- Task 1.3 сначала: зафиксируйте finite golden fixture и ожидаемый prepare-manifest и arm reduction **до** рефакторинга, в отдельном коммите. Затем выносите ядра. Golden-тест должен давать байт-идентичный finite результат.
- Существующие finite и legacy ветки не переписывайте. Новый kind добавляется отдельным условием по exact kind. Study-path helpers принимают новый kind только при validated runtime plan нового kind.
- Provenance параметров — только `inherited_finite_study`, `first_principles`, `k_raw_archive`. Архив K проверяйте по size 590982 B и SHA256 `c483d64f…8d8b`. Ничего не читайте из отчётов `service-profile-latency-model`.

### Группа 2: backend и worker

- Events вокруг `enqueueV3` создаются и записываются только при флаге instrumentation нового kind. Без флага последовательность CUDA calls и пути ошибок должны остаться прежними; докажите это тестом.
- Context ID — `cuCtxGetId` (driver API, CUDA ≥ 12.0); сравнивайте его только внутри одного process.
- Приоритеты: `min(greatest + r, least)` в порядке foreign_object, damage, vehicle_type, plate_number. Менее 2 уровней — preparation fails.
- Lane arbiter реализуйте строго по правилу спеки: окно выдаётся до чтения `h2d_host_start`; учитывается любая переходящая работа, включая переход plate_number → foreign_object через границу цикла. Тесты на инжектируемых часах обязаны покрыть оба примера спеки (14.0 и 26.0) и этот переход.
- Host overhead = residence − (`d2h_host_end` − `h2d_host_start`) − lane wait; отрицательное значение — ошибка request.
- GPU тесты не исполняются в hosted CI. Запускайте их на host, сохраняйте stdout/stderr и SHA256 в `openspec/changes/study-gpu-colocation/evidence/` и отражайте в conformance как «проверено на host, не в CI».

### Группа 3: sidecar, bridge, probe

- Код sidecar и bridge должен быть совместим с Python 3.10 (раздел 3).
- Snapshot `gpu_queue_depth`: memfd с seals, read-only FD через `SCM_RIGHTS` только под новым kind. Под legacy/finite probe ставит 0 и FD не получает.
- Readiness проверяет тройки (container ID, host PID, context ID) и platform identity против readiness record preparation.

### Группа 4: driver и reducer

- Каждый arm использует свежий pool в новом namespace и полную retirement до следующей readiness.
- Бюджет: 24 × (max старт+readiness + max retirement + 220 s + 40 s) + 1,800 s ≤ 14,400 s.
- Флаги решения — ровно по спеке (Δ̄ по двум repeats ≥ 0.05 во всех 4 ячейках и все 8 per-repeat Δ одного знака). Тесты покрывают границу 0.05 и смешанные знаки.

### Группа 5: images, parity, pins

- Новые файлы: `configs/gpu_colocation_image_build_v1.json`, `configs/gpu_colocation_image_refreeze_v1.json`, `configs/analytics_execution_layer.gpu-colocation-v1.json`, `configs/checkpoint_analytics_model_parity.gpu-colocation-v1.*`, loader `held_gpu_colocation_model_material_v1`.
- Не меняйте `configs/publication_image_build_v1.json` (ровно 5 images), `configs/publication_qualification_image_refreeze_v1.json`, существующие receipts и parity.
- Engines не пересобираются. Parity для всех 4 branches в каждом из 3 arms.
- Legacy `_current_workers` после ваших правок должен отказывать с прежней причиной drift. Это ожидаемо (решение «merge до Q4/full»); ослаблять gate нельзя.

## 6. CI и проверки

- Локально (WSL, Python 3.12): `python -B scripts/run_ci_checks.py --output-dir <новый каталог>`. Для model assets OMZ нужны заранее скопированные файлы из `.ci/model-assets.v1.json`, потому что WSL не достаёт до proxy.
- Hosted CI (workflow `VAST CPU checks`) должен быть зелёным на последнем коммите PR. Если CI упал, читайте логи через `gh run view --log-failed`, исправляйте причину и делайте новый коммит. Не добавляйте skips и не ослабляйте проверки.
- OpenSpec CI проверяет структуру документов и архивов (`openspec validate --strict`).

## 7. Независимое ревью и self-approval

Gates, на которых обязательно независимое ревью:

| Gate | Что ревьюируется | Кто одобряет |
|---|---|---|
| G1 изменение требований до кода | дельта документов | агент после ревью |
| G2 реализация завершена (группы 1–5, CI зелёный) | весь diff master…HEAD против спеки | агент после ревью |
| G3 перед preparation attempt | readiness план, бюджет, images, pins, место на дисках | агент после ревью |
| G4 перед кампанией | closed preparation descriptor, readiness трёх pools, platform identity | агент после ревью |
| G5 результат | редукция, повторная редукция, conformance | агент после ревью |
| G6 перед merge | archive, основная спека, CI на последнем коммите | агент после ревью |

Процедура:
1. Запустите субагента-ревьюера (read-only) с точным SHA, ссылками на спеку и предметом gate. Ревьюер проверяет утверждения по коду и данным и отвечает `VERDICT: PASS | PASS_WITH_NOTES | BLOCK` с findings.
2. Исправьте blocker и major, затем повторите ревью на новом SHA. Minor исправьте или явно разберите в PR.
3. Запишите в PR #11 комментарий: gate, SHA, вердикты раундов, что исправлено, и строку `Delegated agent self-approval (user decision 2026-10-15) at <SHA>`.
4. Только после этого переходите к следующему этапу.

Ревьюер не должен быть тем же контекстом, который писал код: используйте нового субагента или продолжайте ревьюера предыдущего раунда той же темы.

## 8. Физическое исполнение

### 8.1 Preparation attempt (одна)

- Перед стартом проверьте: G3 одобрен; Docker Desktop и драйвер не менялись; место есть; root на WSL ext4 новый и пустой; ни одного несвязанного процесса на GPU.
- Сохраните `time.monotonic_ns()`, `boot_id` и `readlink /proc/self/ns/time` до первого hash/transfer/build (как в `docs/finite-component-study-runbook.md`). Clock — 14,400 s.
- Preparation собирает и проверяет всё, измеряет старт и retirement трёх видов pool без media и записывает readiness record (platform identity, priority range, бюджет). Performance наблюдать нельзя.
- Если preparation провалилась: сохраните original failure, запишите FAILED в PR и остановитесь. Вторая attempt — только по решению человека.

### 8.2 Кампания (одна)

- Перед стартом нужны G4 и решение «бюджет укладывается».
- Во время кампании запрещены code edits, rebuild, remote CI, изменения Docker/WSL/драйвера, повтор arm и изменение порядка.
- Не перезапускайте и не «чините» упавший arm. При failure кампания останавливается FAILED, raw сохраняется с честными метками, владельцы retire, всё фиксируется в PR. Следующая кампания — только по решению человека.

## 9. Результаты

- Сохраните `study-results.original.json`, closed-inputs binding и evidence в каталоге изменения (gzip, с size и SHA256, как в архиве finite study).
- Выполните независимую повторную редукцию (task 4.3 и 6.5); значения должны совпасть.
- Напишите `docs/gpu-colocation-study-<YYYYMMDD>/README.md`: флаги (`<X>_beats_contexts4`, `<X>_worse_than_contexts4`, `inconclusive`, `consolidation_beats_contexts4_at_batch1`), таблицы Δ по ячейкам и Δ̄, secondary outcomes с метками, ограничения (batch 1, один GPU, WSL2/WDDM, искусственный proxy, held/fresh pool, совпадение порога с PR #10). `inconclusive` и `worse` — нормальные результаты. Не заявляйте utilization, energy, pure kernel time или причинность.
- Conformance report `openspec/changes/study-gpu-colocation/conformance.md`: для каждого требования — где реализовано, каким тестом подтверждено, расхождения, что не проверено автоматически.

## 10. Archive и merge

1. `/opsx:archive study-gpu-colocation` (Codex: `$openspec-archive-change`) в этой же ветке. Подтвердите sync delta в `openspec/specs/gpu-colocation-study/spec.md`.
2. Проверьте: каталог перенесён в `openspec/changes/archive/YYYY-MM-DD-study-gpu-colocation/`, основная спека создана, документы сохранены. Закоммитьте и запушьте в PR #11.
3. Дождитесь зелёного CI на последнем коммите. Пройдите G6. Снимите Draft (`gh pr ready 11`) и выполните merge в master (`gh pr merge 11 --merge`), как решил пользователь: до Q4/full.
4. После merge оставьте hand-over для change Q4/full в PR #11 и в shared notes. Перечислите обязательную renewal legacy поверх нового source: model evidence и freeze legacy TensorRT worker, пересборка и refreeze всех 4 runtime images, native images, execution code closure. Receipts, выпущенные до merge, для Q4/full недействительны.

Чек-лист перед merge — из `AGENTS.md` (спека до кода, согласованные правки, задачи и тесты, CI соответствия, разобранные предупреждения, закоммиченный archive, зелёный последний коммит, финальное одобрение).

## 11. Когда остановиться и спросить человека

- repaired Q1 закрыт failed или без merge;
- нужно удалить или выгрузить образ, не хватает места или требуется изменить Docker Desktop/WSL/драйвер/системные настройки;
- провалилась preparation attempt или кампания;
- результат требует менять параметры, пороги или матрицу после первой readiness;
- любое действие вне этого изменения (другие PR, legacy receipts, Q4/full).

## 12. Продолжение в новом чате или другим агентом

- Назовите изменение `study-gpu-colocation` и прочитайте каталог изменения, PR #11 (описание и комментарии gates) и shared notes `study-gpu-colocation.md`, если они доступны.
- Текущее положение определяется отмеченными задачами в `tasks.md` и последним gate-комментарием в PR. Историю чата не восстанавливайте.
