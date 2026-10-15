# Design: study-gpu-colocation

## Context

Мотивация — в proposal.md. Факты текущего кода (master `ead12cec`), на которые опирается решение:

- GPU route: analytics pool — 8 docker containers, по одному на (branch, resource) (`scripts/checkpoint_gstreamer_analytics_sidecar.py:94`, запуск `:4884-4930`, `DockerWorkerProcessFactory.start` `:4137-4229`, `--gpus all` только для GPU). Каждый TensorRT worker (`deploy/analytics_execution/tensorrt_worker.py:476-487`) создаёт одну native session: `cudaSetDevice` + `cudaFree(nullptr)` (primary context process), один engine, один execution context, один `cudaStreamNonBlocking` stream с default priority (`deploy/analytics_execution/tensorrt_backend.cpp:257-285`). Итого 4 CUDA contexts на одном RTX 3060, GPU делится time-slicing драйвера (на WSL2 — через WDDM).
- Inference (`tensorrt_backend.cpp:492-520`): H2D `cudaMemcpyAsync` из pageable host buffer, `cudaEventSynchronize(h2d_end)`, `enqueueV3` (`:506`), D2H, `cudaStreamSynchronize`. Events есть только вокруг H2D и D2H; интервала исполнения `enqueueV3` нет.
- Batch 1 закреплён: binding `[1,3,224,224]` (`docs/benchmark_model_parity.md:59,84-94`), bridge (`scripts/checkpoint_gstreamer_analytics_bridge.py:317,408`). Engines не пересобираются (`docs/benchmark_model_parity.md:95-100`).
- Worker protocol: AF_UNIX SEQPACKET + sealed memfd, serial worker, один request в полёте (`deploy/analytics_execution/README.md:9-13`, `scripts/analytics_execution_worker.py:415-416,534-541`).
- Bridge в sidecar: `threading.Lock` на route `(branch, resource)` (`checkpoint_gstreamer_analytics_bridge.py:486`, захват `:750/758`), сериализует 6 streams одного branch. Native client: final variant K `branch-channel` (отдельные connections на branch).
- Policy в study: `policy = <resource>_only` (`scripts/checkpoint_gstreamer_runtime.py:3085`), `gpu_only` возвращает `forced_policy_resource`; `queue_depths` участвуют только в score/tie-break (`scripts/checkpoint_native_policy_runtime.py:784-818`, `scripts/publication_policy_frozen_replay_v1.py:341-349`). `cpu_queue_depth` — уровень `vastanalyticsqueue` перед detector branch (`deploy/native_gst_probe/vast_native_gst_probe.cpp:3683-3709`), `gpu_queue_depth = 0` (`:3023`).
- Kind: `finite-component-study` (`scripts/canonical_systems_study_plan_v1.py:14`), native probe получает `--checkpoint-study-kind` (`vast_native_gst_probe.cpp:1414-1431`, `checkpoint_source_coordinator.cpp:244,259`). Legacy validators отвергают study kinds через exact-kind/shape проверки, а не явным списком (`validate_study_plan` `:200`, `checkpoint_runtime_plan.py:472-479`, Q4 exact `artifact_kind`).
- Images/pins: TensorRT worker — `deploy/analytics_execution/Dockerfile.tensorrt`, allowlist `deploy/analytics_execution/publication/tensorrt-source-allowlist.txt`, build registry `configs/publication_image_build_v1.json:102-111`, refreeze registry `configs/publication_qualification_image_refreeze_v1.json`, layer `configs/analytics_execution_layer*.json`, parity `configs/checkpoint_analytics_model_parity*`; `_current_workers` требует совпадения freeze receipt с текущим build plan (`scripts/publication_gstreamer_component_inputs_v1.py:122-142`). Native probe/GStreamer runtime собираются в study `prepare` (`scripts/run_canonical_systems_study_v1.py:367-415`) с source pins перед каждым arm (`:1082`).
- K: 32 arms (8 pilot + 24) заняли 8,278 s с held pool (≈ 259 s/arm). GPU worker backend interval (с mapping/copies) p50 6.6–8.5 ms, p95 16–35 ms, p99 23–212 ms в GPU arms rate 1–2.
- PR #10: оба флага use-permitted = `false`; этот design не берёт ни одного значения из его отчёта.

## Goals / Non-Goals

**Goals:**
- Минимальные изменения, достаточные для трёх prebuilt arms, без изменения runtime поведения legacy и finite kinds; их current-source gates при этом получают ожидаемый drift (§10).
- Одинаковые instrumentation, host copies, protocol и lifecycle во всех arms, чтобы различие arms сводилось к contexts/priorities/arbiter.
- Переиспользование существующих finite-study seams (intake, schedule, accounting, clock domain, reducer, lifecycle) через параметр kind, без копирования.

**Non-Goals:**
- MPS, CUDA graphs, batch > 1, cross-stream batching (Change 3), pinned host memory, изменение per-route lock.
- Изменение policy formulas, calibration, legacy validators, отчёта PR #10 или результатов K.
- Повторный запуск legacy/finite kinds на новых bytes и их renewal.

## Decisions

### 1. Новый kind поверх finite-study seams

Новый модуль plan `scripts/gpu_colocation_study_plan_v1.py` (kind `gpu-colocation-study`) импортирует из `canonical_systems_study_plan_v1.py` schedule/stimulus helpers и строит собственную матрицу; `validate_study_plan` finite study не меняется и продолжает требовать свой kind. Driver `run_canonical_systems_study_v1.py` и reducer `reduce_canonical_systems_study_v1.py` получают явную ветку по kind плана. `prepare` и `reduce_arm` сейчас выпускают finite kinds и вызывают finite `validate_study_plan` (`run_canonical_systems_study_v1.py:544,727`; `reduce_canonical_systems_study_v1.py:281,546`), поэтому их тела выносятся в ядра, параметризованные kind-дескриптором (kind строки, validator плана, limits); finite entrypoints вызывают ядро с finite дескриптором. Эквивалентность finite доказывается golden-тестом: на фиксированном finite fixture результат prepare-manifest и arm reduction байт-идентичен результату до рефакторинга (fixture и ожидаемый вывод фиксируются до рефакторинга). `run` для нового kind исполняет новую матрицу и per-arm pool lifecycle; study reduction нового kind добавляет контрасты, флаги, enqueue/lane/queue-depth/host-overhead распределения. Runtime plan: `build_gpu_colocation_runtime_plan_v1` рядом с finite builder в `checkpoint_runtime_plan.py`; dispatch в `checkpoint_runtime.py:576` получает отдельную ветку.

Места, где finite kind сейчас зашит строкой и которые получат ветку нового kind: `scripts/checkpoint_gstreamer_runtime.py` (`:988,1030,1064,1094,3085,3170`), `scripts/run_canonical_systems_study_v1.py` (`:544,726,727,738,742,747,1028,1163,1170,1183`, а также finite-study CLI флаги `:808-812,1088-1089`), `scripts/reduce_canonical_systems_study_v1.py` (`:281,546`), `scripts/checkpoint_native_policy_runtime.py:640`, `scripts/publication_operational_request_domain_v1.py:151-159`, `scripts/publication_operational_runtime_context_v1.py:190,209`, `scripts/publication_operational_capture_plan_v1.py:222,234,287,294`, `scripts/publication_guardian_component_preprocessing_contract_v1.py:275,310`, `deploy/native_gst_probe/checkpoint_source_coordinator.cpp:259,294,808`, `deploy/native_gst_probe/vast_native_gst_probe.cpp:1420,1584`, `scripts/checkpoint_admission.py:190-192` (finite runtime-plan validation), `scripts/checkpoint_gstreamer_analytics_sidecar.py:424-438,4308,5548` (finite-study guardian authority, operational context, front-request validators), `scripts/publication_gstreamer_component_inputs_v1.py:532` (`held_finite_study_model_material_v1`), `scripts/publication_image_build_v1.py:622-636` (`build_finite_study_native_image_v1`, prefix `vast/finite-study-`). Окончательный список подтверждается при task 0.3 grep по `finite[-_]study` и `finite-component-study`, а не только по полному kind.

Классификация: (a) gates — qualification, promotion, Q4, publication, full validators и finite validators — не меняются и отвергают новый kind; (b) study-path helpers — `publication_operational_request_domain_v1`, `publication_operational_runtime_context_v1`, `publication_operational_capture_plan_v1`, `publication_guardian_component_preprocessing_contract_v1`, `checkpoint_native_policy_runtime` — уже принимают finite kind только при переданном validated finite runtime plan; они принимают новый kind только при переданном validated runtime plan нового kind, а без plan (legacy publication path) их проверки и accepted modes прежние; (c) emitters evidence rows (native probe, source coordinator, runtime) пишут kind из validated plan; (d) material/image loaders — `held_finite_study_model_material_v1` и `build_finite_study_native_image_v1` остаются finite-only, а новый kind получает собственные `held_gpu_colocation_model_material_v1` (связан с новым worker freeze receipt, §10) и сборку native image с префиксом `vast/gpu-colocation-`; `checkpoint_admission.py` и validators sidecar относятся к (b). Для (b) и (c) существующие finite/legacy ветки сохраняются, а тесты на модуль доказывают прежний результат для finite/legacy входов; для общих ядер (prepare, reduce_arm) — golden-тест выше. Часть модулей лежит на publication path, поэтому их изменение меняет execution code closure (см. §10).

Альтернатива: расширить `finite-component-study` новыми arms. Отклонено: изменило бы требования и counts finite study, которые закрыты archive.

Отказ legacy gates получается так же, как у finite study: все artifacts имеют новые exact kinds, а legacy validators принимают только свои. Тесты явно подают артефакты нового kind в qualification/promotion/Q4/publication/full и finite validators и ожидают отказ.

### 2. Матрица и порядок

Блоки: (rate, topology) ∈ {1, 2} × {baseline, shared}. `random.Random(20260323)` перемешивает 4 блока, затем для каждого блока — перестановку трёх arms; результат repeat 1 сохраняется в plan, repeat 2 — точное обращение всей последовательности repeat 1. При обращении каждый arm внутри блока и каждый блок занимает в среднем одинаковую позицию, поэтому линейный дрейф уравновешивается в среднем по двум repeats; решающее правило использует именно это среднее Δ̄ (§9). Порядок не пересчитывается после сохранения.

Альтернатива: попарные AB/BA блоки `default`↔`X` (4 arms на блок). Отклонено: 32 arms и двойные запуски `default` без выигрыша в балансе линейного дрейфа.

### 3. Per-arm pool lifecycle и бюджет

K использовал held pool, потому что arms различались только native topology/resource. Здесь различается сам GPU pool, поэтому каждый arm поднимает свежий analytics pool (sidecar/bridge, 4 idle OpenVINO workers, GPU workers своего вида) в собственном новом namespace (`start_pool` отвергает уже использованный namespace, `run_canonical_systems_study_v1.py:892`) и свои native processes, а затем полностью их retire через существующие closure пути. Единый lifecycle исключает перенос GPU/engine/cache состояния между arms.

Бюджет — формула спеки: 24 × (max старт+readiness + max retirement + 220 s + 40 s) + 1,800 s ≤ 14,400 s, то есть старт+retirement pool должны укладываться в ≈ 265 s на arm. 40 s — per-arm overhead K сверх фаз (8,278 s / 32 arms ≈ 259 s). Preparation измеряет старт и retirement каждого вида pool один раз, без media; при превышении preparation fails.

Альтернатива: держать обе разновидности GPU pool одновременно. Отклонено: лишние contexts присутствовали бы во время `context1_*` arms и опровергали бы «один context».

### 4. Consolidated worker и различие host-части

`tensorrt_worker.py` получает режим `--colocation-mode {context1_streams_priority,context1_lanes}` с 4 bindings и 4 sockets (по одному на branch) в одном container/process. Backend добавляет C API для shared-context sessions: все 4 sessions создаются в одном process после одного `cudaSetDevice`/`cudaFree(nullptr)`, каждая со своим `IRuntime`/engine/execution context/buffers и stream `cudaStreamCreateWithPriority(cudaStreamNonBlocking, p_b)`. Каждый branch обслуживается своим host thread; ctypes освобождает GIL только на время foreign call, а JSON/validation/`np.ascontiguousarray`/buffers/response (`tensorrt_worker.py:256-300`, `analytics_execution_worker.py:440-510`) идут под GIL. Это объявлено в спеке частью treatment «один worker process»; чтобы его вклад был виден, каждый request публикует host overhead = residence − (`d2h_host_end` − `h2d_host_start`) − lane window wait (arbiter выдаёт окно до чтения `h2d_host_start`, поэтому интервалы не перекрываются), и reducer сравнивает его распределения между arms. Перенос serve loop в native threads во всех arms отклонён: он изменил бы и `contexts4_default`, который должен оставаться текущей схемой.

В `contexts4_default` worker запускается в прежнем режиме (один binding) под новым kind, с тем же backend и instrumentation, stream default priority. Bridge routes, per-route locks и capabilities остаются прежними; меняется только process identity в capability/readiness.

Readiness: каждая session сообщает CUDA context ID (`cuCtxGetId` driver API, CUDA ≥ 12.0); driver дополняет его container ID и host PID из `docker inspect` (у каждого container свой PID namespace). «Различны» доказывается 4 различными container/PID, «общий» — одним container/PID с равными context ID; context ID между processes не сравниваются. NVML process list на WSL2 недоступен и записывается как `unknown`. Readiness записывает также Windows build, NVIDIA driver, CUDA driver/runtime, HAGS (`HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers\HwSchMode`, только чтение) и Docker Desktop version; базой служит readiness record preparation (там же измерены priority range и бюджет pool), расхождение любого arm с ней — failure. Readiness выполняет ровно одно синтетическое inference на engine (нулевой input) во всех arms; его outputs не используются.

### 5. Приоритеты и порядок branches

Порядок `foreign_object`, `damage`, `vehicle_type`, `plate_number` взят из архива K: ранжирование по p50 per-branch completed latency одинаково во всех 12 GPU arms (например r1-gpu-1-shared: 113.9 / 96.3 / 92.8 / 81.0 ms). Это raw распределение K, а не профиль или предсказание PR #10. Первые принципы: frame on-time требует всех 4 branches, поэтому первенство получает branch, который обычно завершается последним (critical-path-first). Отображение `min(greatest + r, least)` даёт 4 различных уровня при диапазоне ≥ 4 (ожидаемо `[-5, 0]` для compute capability 8.6, проверяется в readiness). 2–3 уровня — arm действителен, отображение раскрывается. Менее 2 уровней — preparation fails: arm без приоритетов не исполнял бы свой treatment.

Альтернатива: shortest-first (минимум среднего ожидания). Отклонено: primary outcome — Y100_frame, определяемый самым поздним branch кадра. Альтернатива: веса из worker backend K. Отклонено: интервалы K измерены при 4 contexts и уже содержат тот эффект, который study проверяет.

### 6. Lane arbiter

Реализуется в backend (C++), общий для 4 sessions одного process: mutex + condition variable на CLOCK_MONOTONIC сетке. Правило окна — ровно правило спеки (единственный источник): старт GPU работы branch b разрешён только внутри номинального окна `[s_b, e_b)`, без чужой работы на GPU и не раньше завершения любой переходящей работы (в том числе из более ранних окон и из окна plate_number предыдущего цикла); после своей работы branch может начать следующую, пока t < e_b; начатая работа не прерывается (overrun); окно, переходящая работа которого завершилась в момент ≥ e_b, пропускается. Пример спеки: окно damage `[12.5, 25)`; foreign_object до 14.0 → damage стартует в 14.0; foreign_object до 26.0 → окно damage пропущено, vehicle_type стартует в 26.0. Arbiter gate-ит интервал от начала H2D до завершения D2H. На каждый request записываются cycle index, номинальные и фактические границы окна, ожидание окна, overrun; на каждое пропущенное окно — `lane_window_skipped`.

Параметры. Цикл 50 ms = deadline/2: ожидание начала своего окна ≤ 37.5 ms. Равные окна по 12.5 ms: пропорциональные окна требовали бы per-branch service time, а единственные доступные (K) измерены при 4 contexts. Анализ нагрузки из первых принципов: все 6 streams имеют общий schedule offset (`canonical_systems_study_plan_v1.py:111-127`, offset начинается с 0 для каждого stream), поэтому на тик кадра каждый branch получает пачку до 6 requests (K route wait p95 33–55 ms ≈ 5 × 8 ms подтверждает пачки). Суммарная GPU работа тика одинакова во всех arms; lanes меняют только порядок (пачки branches чередуются квантами ≈ окну, а не исполняются вперемешку time-slicing) и убирают переключения contexts. Пока у всех branches есть работа, окна заполнены; простой возникает только в окнах уже опустевших branches (non-work-conserving), не более 12.5 ms на опустевший branch за цикл. Знак эффекта заранее неизвестен; `worse_than_contexts4` и `inconclusive` — допустимые исходы.

Альтернатива: work-conserving round-robin. Отклонено: без простоя окон это exclusive round-robin без временной изоляции, а предмет arm — именно изоляция (OctopInf temporal lanes). Альтернатива: окна под пачку 6 requests. Отклонено: требует оценки service time, которую нельзя получить без 4-context искажения.

### 7. CUDA events вокруг enqueueV3

В `Session` добавляются `enqueue_start_event`/`enqueue_end_event`, создаваемые только при флаге instrumentation, который worker передаёт в `vast_trt_create` под kind `gpu-colocation-study`. При флаге: `cudaEventRecord` непосредственно до и после `enqueueV3` на stream session; `cudaEventElapsedTime` после `cudaStreamSynchronize`; host envelope — monotonic перед первым record и после synchronize; выход за envelope — ошибка request. Без флага (legacy/finite) последовательность CUDA calls и пути ошибок прежние. `VastCudaTransferTiming` расширяется полем `enqueue_device_elapsed_ns` и host endpoints, которые без флага остаются нулевыми и не публикуются; exact schemas legacy/finite не меняются.

Метка: «stream-ordered device interval of the enqueued work; includes waiting behind other GPU work; not pure kernel time». При 4 contexts интервал включает time-slices других contexts, при priority streams — вытеснение более приоритетными, при lanes — почти исключительно собственную работу.

Альтернатива: отдельный backend файл только для study. Отклонено: brief требует event в `tensorrt_backend.cpp`, а правки native probe (`gpu_queue_depth`) и bridge всё равно меняют legacy source sets (§10), так что отдельный файл не избавил бы от renewal legacy consumers, но удвоил бы код backend.

### 8. gpu_queue_depth

Владелец счётчика — bridge в sidecar: при попытке захвата GPU route lock счётчик увеличивается, после reply или failure и освобождения lock — уменьшается. Bridge публикует snapshot (seqlock: sequence, count, publish CLOCK_MONOTONIC ns) в memfd размером одна страница с seals `F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_SEAL`; read-only FD передаётся native client через `SCM_RIGHTS` при handshake на `analytics.sock` только под новым kind. Native probe читает snapshot перед decide RPC: чётная и неизменная sequence до и после чтения; ограниченное число попыток в пределах исходного request deadline; неудача — request failed. В decision evidence записываются sequence, publish/read ns и значение. Под legacy/finite kinds FD не передаётся, probe ставит 0, как сейчас. Под `gpu_only` значение влияет только на score/tie-break записи decision, но не на выбор resource.

Альтернатива: локальный счётчик native process. Отклонено: в baseline (process на stream×branch) он всегда 0 и не отражает GPU. Альтернатива: счётчик в policy coordinator по issued-not-terminal decisions. Отклонено: смешивает decide-to-terminal residence с GPU очередью и требует, чтобы coordinator переписывал поле request.

### 9. Решение и пороги

Primary — Y100_frame. Правило порога задано заранее: наименьшее кратное 0.01, не меньшее 2.5 × max |Δ| между repeats одинаковых GPU arms rate 1–2 в K (0.0185) → 0.05. Совпадение с порогом спеки PR #10 раскрывается в report; значение получено правилом, а не взято оттуда. Решение использует среднее по двум repeats Δ̄ для каждой из 4 ячеек (rate × topology), которое уравновешивает линейный дрейф благодаря обращению порядка, и дополнительно требует одинакового знака всех 8 per-repeat Δ. Ограничение: шум K оценён при held pool и всего по 4 парам; свежий pool на arm может добавить разброс, поэтому `inconclusive` вероятен и допустим.

### 10. Images, parity и pins

Правки на месте меняют allowlisted source трёх групп: TensorRT worker (`tensorrt_backend.cpp`, `tensorrt_worker.py` в `deploy/analytics_execution/publication/tensorrt-source-allowlist.txt`), native probe (`vast_native_gst_probe.cpp`, `checkpoint_source_coordinator.cpp` в `deploy/native_gst_probe/publication/openvino-source-allowlist.txt`) и execution code closure (bridge, sidecar, модули §1; `publication_policy_qualification_execution_code_closure_v1.py:29`). После merge реализации current-source gates legacy/finite/Q1 consumers (`_current_workers` `publication_gstreamer_component_inputs_v1.py:122-142`, source pins, closure) сообщат drift; это ожидаемое следствие, которое не ослабляется. Последующие legacy/finite/Q4/full запуски требуют своей renewal (новая model evidence для worker, refreeze, closure) — вне этого изменения. Решение пользователя от 2026-10-15: это изменение сливается **до** Q4/full. Следствие: change, который подготовит Q4/full после merge этого изменения, SHALL включать renewal legacy поверх нового source — новую model evidence и freeze для legacy TensorRT worker, пересборку и refreeze всех 4 runtime images (sidecar упакован во все 4), новые native images и execution code closure — и не может опираться на receipts, выпущенные до merge. Решение записано в PR (task 0.3).

Для нового kind:
- TensorRT worker: build registry `configs/gpu_colocation_image_build_v1.json` и refreeze registry `configs/gpu_colocation_image_refreeze_v1.json` с собственным loader (существующий loader требует ровно 5 images и хэширует весь файл, `publication_image_build_v1.py:268-286,303`, поэтому существующие registries не трогаются); новый tag; новая запись `configs/analytics_execution_layer.gpu-colocation-v1.json`; новый worker freeze receipt и собственный model-material loader `held_gpu_colocation_model_material_v1`, проверяющий текущий worker против этого receipt (legacy `_current_workers`/`held_finite_study_model_material_v1` не меняются); model parity `configs/checkpoint_analytics_model_parity.gpu-colocation-v1.*` по принятой reference для всех 4 branches в каждом из 3 arms (engines те же).
- Native probe / GStreamer runtime: собираются в `prepare` из pinned allowlisted source, source pins проверяются перед каждым arm (`run_canonical_systems_study_v1.py:367-415,1082`).
- Execution code closure нового kind; новые receipts — отдельные файлы.
- Существующие pins/receipts/parity и все 227 образов не меняются; новые образы добавляются. Перед сборкой проверяются свободное место и пороги хранилища (C: 40 GiB floor); удаление/offload любого образа — только с явного подтверждения пользователя. Docker Desktop остаётся на закреплённой сборке.

### 11. Последовательность

Реализация стартует после merge PR #9 и после того, как PR repaired Q1 (`qualify-repaired-full-benchmark`) слит с accepted Q1. Если repaired Q1 закрыт failed или без merge — изменение остаётся заблокированным до явного решения человека в PR. Первая задача реализации — синхронизировать ветку с master, сверить Context/Decisions с фактическим кодом (номера строк, seams, pins) и записать решение о порядке относительно Q4/full; изменения, затрагивающие требования, проходят `/opsx:update` и повторное ревью до кода.

## Risks / Trade-offs

- [WSL2/WDDM scheduling отличается от Linux bare-metal: time-slicing contexts и поддержка stream priorities определяются Windows драйвером и HAGS] → readiness записывает и фиксирует platform identity по всем arms; выводы ограничены этим host.
- [Stream priorities могут не дать эффекта, если GPU не насыщен или WDDM их игнорирует] → `inconclusive` допустим; менее 2 уровней — preparation fails; enqueue interval показывает распределение времени.
- [Общий Python interpreter в `context1_*` добавляет GIL contention на host] → объявлено частью treatment; host overhead публикуется per arm.
- [Non-work-conserving lanes простаивают в окнах опустевших branches] → объявленная цена; простой ограничен 12.5 ms на опустевший branch за цикл и измеряется.
- [Свежий pool на каждый arm увеличивает время кампании] → формула бюджета и измерение старта pool в preparation.
- [Правки на месте делают legacy/finite/Q1 receipts устаревшими для повторных запусков] → явно в спеке; пользователь решил сливать до Q4/full (2026-10-15), поэтому renewal legacy входит в будущий change Q4/full; исторические образы и receipts сохраняются.
- [Shared counter в sidecar добавляет работу в GPU route path] → атомарная запись seqlock на request; только под новым kind, одинаково во всех трёх arms.
- [Параметры могут оказаться неудачными] → не меняются posthoc; любое изменение — новое ревью спеки.

## Migration Plan

Миграции данных нет. Новые images и registries добавляются рядом со старыми; откат — не использовать новый kind. Merge после archive в этом же PR.

## Open Questions

- Точное время старта pool измеряется в preparation; оно не меняет параметры, только подтверждает бюджет по формуле спеки.
