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
- Минимальные изменения, достаточные для трёх prebuilt arms, без изменения поведения legacy и finite kinds, кроме пересборки bytes.
- Одинаковые instrumentation, host copies, protocol и lifecycle во всех arms, чтобы различие arms сводилось к contexts/priorities/arbiter.
- Переиспользование существующих finite-study seams (intake, schedule, accounting, clock domain, reducer, lifecycle) через параметр kind, без копирования.

**Non-Goals:**
- MPS, CUDA graphs, batch > 1, cross-stream batching (Change 3), pinned host memory, изменение per-route lock.
- Изменение policy formulas, calibration, legacy validators, отчёта PR #10 или результатов K.
- Повторный запуск legacy/finite kinds на новых bytes и их renewal.

## Decisions

### 1. Новый kind поверх finite-study seams

Новый модуль plan `scripts/gpu_colocation_study_plan_v1.py` (kind `gpu-colocation-study`) импортирует из `canonical_systems_study_plan_v1.py` schedule/stimulus helpers и строит собственную матрицу; `validate_study_plan` finite study не меняется и продолжает требовать свой kind. Driver `run_canonical_systems_study_v1.py` и reducer `reduce_canonical_systems_study_v1.py` получают явную ветку по kind плана: `prepare` (stimulus, encodes, reference, сборка native/runtime) переиспользуется без изменений; `run` для нового kind исполняет новую матрицу и per-arm pool lifecycle; `reduce_arm` переиспользуется, а study reduction нового kind добавляет контрасты, флаги, enqueue/lane/queue-depth распределения. Runtime plan: `build_gpu_colocation_runtime_plan_v1` рядом с finite builder в `checkpoint_runtime_plan.py`; legacy dispatch в `checkpoint_runtime.py:576` получает отдельную ветку, а finite ветка остаётся байт-эквивалентной по поведению.

Альтернатива: расширить `finite-component-study` новыми arms. Отклонено: изменило бы требования и counts finite study, которые закрыты archive.

Отказ legacy gates получается так же, как у finite study: все artifacts имеют новые exact kinds, и legacy validators принимают только свои. Тесты явно подают артефакты нового kind в qualification/Q4/publication/full validators и finite validators и ожидают отказ.

### 2. Матрица и порядок

Блоки: (rate, topology) ∈ {1, 2} × {baseline, shared}. `random.Random(20260323)` перемешивает 4 блока, затем для каждого блока — перестановку трёх arms; результат repeat 1 сохраняется в plan, repeat 2 — точное обращение всей последовательности repeat 1. При обращении каждый arm внутри блока и каждый блок занимает в среднем одинаковую позицию, что уравновешивает линейный дрейф. Порядок не пересчитывается после сохранения.

Альтернатива: попарные AB/BA блоки `default`↔`X` (4 arms на блок). Отклонено: 32 arms и двойные запуски `default` без выигрыша в балансе линейного дрейфа.

### 3. Per-arm pool lifecycle

K использовал held pool, потому что arms различались только native topology/resource. Здесь различается сам GPU pool, поэтому каждый arm поднимает свежий analytics pool (sidecar/bridge, 4 idle OpenVINO workers, GPU workers своего вида) и свои native processes, а затем полностью его retire через существующие `start_pool`/closure пути (`run_canonical_systems_study_v1.py:887-922`). Единый lifecycle для всех arms исключает перенос GPU/engine/cache состояния. Оценка бюджета: ≈ 259 s/arm как в K плюс старт/остановка pool; при запасе 90 s/arm — ≈ 8,400 s из 14,400 s. Фактическое время старта pool измеряется в preparation (без media, без performance observation) и SHALL укладываться в оставшийся бюджет; иначе preparation fails до кампании.

Альтернатива: держать обе разновидности GPU pool одновременно. Отклонено: лишние contexts присутствовали бы во время `context1_*` arms и опровергали бы «один context».

### 4. Consolidated worker

`tensorrt_worker.py` получает режим `--colocation-mode {context1_streams_priority,context1_lanes}` с 4 bindings и 4 sockets (по одному на branch) в одном container/process. Backend добавляет C API для shared-context sessions: все 4 sessions создаются в одном process после одного `cudaSetDevice`/`cudaFree(nullptr)`, каждая со своим `IRuntime`/engine/execution context/buffers и stream `cudaStreamCreateWithPriority(cudaStreamNonBlocking, p_b)`. Каждый branch обслуживается своим host thread (ctypes освобождает GIL на время foreign call), один request в полёте на branch, поэтому bridge routes, per-route locks и capabilities остаются прежними; меняется только process identity в capability/readiness. В `contexts4_default` worker запускается в прежнем режиме (один binding), с тем же новым backend (events), stream default priority.

Readiness: каждая session сообщает process id и context identity (`cuCtxGetId` через driver API при наличии, иначе адрес `CUcontext` внутри process) и actual `cudaDeviceGetStreamPriorityRange`; driver проверяет 4 различных context в 4 processes либо 1 общий context в 1 process. NVML process list на WSL2 недоступен и записывается как `unknown`. Readiness выполняет ровно одно синтетическое inference на engine (нулевой input) во всех arms; его outputs не используются.

### 5. Приоритеты и порядок branches

Порядок `foreign_object`, `damage`, `vehicle_type`, `plate_number` взят из архива K: ранжирование по p50 per-branch completed latency одинаково во всех 12 GPU arms (например r1-gpu-1-shared: 113.9 / 96.3 / 92.8 / 81.0 ms). Это raw распределение K, а не профиль или предсказание PR #10. Первые принципы: frame on-time требует всех 4 branches, поэтому первенство получает branch, который обычно завершается последним (critical-path-first). Отображение `min(greatest + r, least)` даёт 4 различных уровня на устройствах с диапазоном ≥ 4 (ожидаемо `[-5, 0]` для compute capability 8.6, проверяется в readiness); меньший диапазон записывается без замены arm.

Альтернатива: shortest-first (минимум среднего ожидания). Отклонено: primary outcome — Y100_frame, определяемый самым поздним branch кадра. Альтернатива: веса из worker backend K. Отклонено: интервалы K измерены при 4 contexts и уже содержат тот эффект, который study проверяет.

### 6. Lane arbiter

Реализуется в backend (C++), общий для 4 sessions одного process: mutex + condition variable на CLOCK_MONOTONIC сетке. Цикл 50 ms = deadline/2: ожидание начала своего окна не превышает 37.5 ms, что оставляет больше половины deadline на остальной путь. 4 равных окна по 12.5 ms: равная доля — нейтральный выбор, поскольку пропорциональные окна требовали бы per-branch service time, а единственные доступные (K) измерены при 4 contexts. Проверка ёмкости из первых принципов и K: при rate 2 на branch приходит 6 streams × 2 fps = 12 requests/s, окно своего branch открывается 20 раз/s; K worker backend p50 6.6–8.5 ms < 12.5 ms, поэтому типичный request помещается в окно, а хвост (p95 16–35 ms) даст превышения, которые записываются. Арбитр gate-ит интервал от начала H2D до завершения D2H; начатая работа не прерывается; окно, начало которого съедено превышением предыдущего, пропускается; простаивающее окно не передаётся (non-work-conserving), так как предмет arm — временная изоляция. На каждый request записываются cycle index, номинальные и фактические границы окна, ожидание окна, превышение.

Альтернатива: work-conserving round-robin. Отклонено: фактически совпадает с exclusive mutex без временной изоляции и плохо отличим от `context1_streams_priority` с сериализацией.

### 7. CUDA events вокруг enqueueV3

В `Session` добавляются `enqueue_start_event`/`enqueue_end_event`; `cudaEventRecord` непосредственно до и после `enqueueV3` на stream session; `cudaEventElapsedTime` после `cudaStreamSynchronize`. Host envelope: monotonic до record start и после synchronize; device interval, выходящий за envelope, — ошибка request (как существующая проверка H2D/D2H). `VastCudaTransferTiming` расширяется полем `enqueue_device_elapsed_ns` и host endpoints. События записываются под всеми kinds (одинаковая GPU работа во всех arms и вне study); worker публикует поле только при `--study-kind gpu-colocation-study`, поэтому legacy и finite exact schemas не меняются.

Метка: «stream-ordered device interval of the enqueued work; includes waiting behind other GPU work; not pure kernel time». При 4 contexts интервал включает time-slices других contexts, при priority streams — вытеснение более приоритетными, при lanes — почти исключительно собственную работу.

### 8. gpu_queue_depth

Владелец счётчика — bridge в sidecar: при попытке захвата GPU route lock счётчик увеличивается, после reply или failure и освобождения lock — уменьшается. Bridge публикует snapshot (seqlock: sequence, count, publish CLOCK_MONOTONIC ns) в memfd размером одна страница с seals `F_SEAL_SHRINK|F_SEAL_GROW|F_SEAL_SEAL`; read-only FD передаётся native client через `SCM_RIGHTS` при handshake на `analytics.sock` только под новым kind. Native probe читает snapshot перед decide RPC: чётная и неизменная sequence до и после чтения; ограниченное число попыток в пределах исходного request deadline; неудача — request failed. В decision evidence записываются sequence, publish/read ns и значение. Под legacy/finite kinds FD не передаётся, probe ставит 0, как сейчас.

Альтернатива: локальный счётчик native process. Отклонено: в baseline (process на stream×branch) он всегда 0 и не отражает GPU. Альтернатива: счётчик в policy coordinator по issued-not-terminal decisions. Отклонено: смешивает decide-to-terminal residence с GPU очередью и требует, чтобы coordinator переписывал поле request.

### 9. Решение и пороги

Primary — Y100_frame, единственная метрика, в которой K показал воспроизводимую разницу между повторами (max |Δ| 0.0185 для одинаковых GPU arms rate 1–2). Порог 0.05 ≈ 2.7 × этого шума; требование «все 8 ячеек» защищает от единичного выброса без статистических тестов, которые при 2 повторах неинформативны. Inconclusive — допустимый исход.

### 10. Images, parity и pins

- TensorRT worker: новый build target в `configs/publication_image_build_v1.json` (новый tag, прежний `publication-v3` не трогается), обновлённый allowlist, новая запись `configs/analytics_execution_layer.gpu-colocation-v1.json`, новый worker freeze receipt и refreeze entry; model parity `configs/checkpoint_analytics_model_parity.gpu-colocation-v1.*` по принятой reference для всех 4 branches в каждом из 3 arms (engines те же).
- Native probe / GStreamer runtime: собираются в `prepare` нового study из pinned allowlisted source (`deploy/native_gst_probe/publication/openvino-source-allowlist.txt`, `deploy/gstreamer_custom/publication/runtime-*-allowlist.txt`), source pins проверяются перед каждым arm.
- Execution code closure обновляется под новые scripts; новые receipts — отдельные файлы нового kind.
- Существующие pins/receipts/parity и все 227 образов не меняются; новые образы добавляются. Перед сборкой проверяются свободное место и пороги хранилища (C: 40 GiB floor); удаление/offload любого образа — только с явного подтверждения пользователя. Docker Desktop остаётся на закреплённой сборке.

### 11. Последовательность

Реализация стартует после merge PR #9 и repaired Q1 (`qualify-repaired-full-benchmark`). Первая задача реализации — синхронизировать ветку с master и сверить разделы Context/Decisions с фактическим кодом (номера строк, seams, pins); изменения, затрагивающие требования, проходят `/opsx:update` и повторное ревью до кода.

## Risks / Trade-offs

- [WSL2/WDDM scheduling отличается от Linux bare-metal: time-slicing contexts и поддержка stream priorities определяются Windows драйвером и HAGS] → readiness записывает actual priority range, версии драйвера и состояние HAGS; выводы ограничены этим host.
- [Stream priorities могут не дать эффекта, если kernels короткие и GPU не насыщен] → допустимый `inconclusive`; enqueue interval показывает, где тратится время.
- [Non-work-conserving lanes могут ухудшить Y100 при rate 1] → это предмет измерения; `worse_than_contexts4` — допустимый исход.
- [Свежий pool на каждый arm увеличивает время кампании] → бюджет оценён (~8,400 s из 14,400 s) и проверяется измерением старта pool в preparation.
- [Пересборка TensorRT backend делает текущие finite/legacy worker receipts устаревшими для повторных запусков] → это изменение не перезапускает их; renewal для них — отдельная задача. Исторические образы и receipts сохраняются.
- [Shared counter в sidecar добавляет работу в GPU route path] → атомарный инкремент/seqlock запись на request; присутствует только под новым kind, одинаково во всех трёх arms.
- [Параметры могут оказаться неудачными] → пороги и параметры не меняются posthoc; новое ревью спеки обязательно для любых изменений.

## Migration Plan

Миграции данных нет. Новые images добавляются рядом со старыми; откат — не использовать новый kind (legacy/finite пути не зависят от него). Merge после archive в этом же PR.

## Open Questions

- Точное время старта pool и его вариация измеряются в preparation; они не меняют параметры, только подтверждают бюджет.
