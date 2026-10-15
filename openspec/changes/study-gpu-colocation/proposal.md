## Why

Сейчас GPU route исполняет 4 branches в 4 отдельных TensorRT worker processes: у каждого свой CUDA context, GPU делится default time-slicing драйвера, все arms закреплены на batch 1, а per-route lock сериализует 6 streams одного branch. Attempt K показал, что при rate 1–2 GPU Y100_frame равен лишь 0.16–0.41, а worker backend interval имеет тяжёлый хвост (p99 до 212 ms при p50 ≈ 8 ms). Неизвестно, даёт ли консолидация исполнения в одном CUDA context (без переключения contexts) выигрыш при batch 1. Это вторая из трёх идей обзора OctopInf (Change 1 — `add-service-profile-latency-model`, PR #10; Change 3 — cross-stream batching, идёт после этого изменения). Модель Change 1 вернула `gpu_latency_profile_use_permitted = false` и `queueing_extrapolation_use_permitted = false`, поэтому параметры этого study нельзя взять из её профилей или предсказаний: каждый параметр задаётся заранее из первых принципов или из raw распределений K и документируется.

## What Changes

- Новый study kind `gpu-colocation-study`: только GPU/TensorRT analytics, rates 1 и 2 fps, topologies baseline и shared, те же 6 streams из 2 recordings, 4 frozen branches, deadline 100 ms, фазы 30/180/10 s, seed 20260323 и derived inputs, что и `finite-component-study`. Три заранее заданных и заранее собранных colocation arms:
  - `contexts4_default` — текущая схема: 4 TensorRT worker processes, 4 CUDA contexts, default time-slicing;
  - `context1_streams_priority` — один TensorRT worker process, 4 engines в одном CUDA context, на каждый branch свой non-blocking CUDA stream с фиксированным приоритетом;
  - `context1_lanes` — то же плюс lane arbiter, который выдаёт каждому branch фиксированное временное окно исполнения в цикле 50 ms.
- Матрица: 2 rates × 2 topologies × 3 colocation arms × 2 repeats = 24 arms в 8 блоках; порядок внутри блока задан seed, repeat 2 исполняет обратный порядок (AB/BA-обращение для трёх arms). Без performance pilot и без выбора конфигурации по результатам.
- Все параметры фиксируются в спеке до первого запуска: порядок приоритетов и lanes (foreign_object, damage, vehicle_type, plate_number — ранг по p50 per-branch latency во всех 12 GPU arms архива K), цикл lanes 50 ms = deadline/2, равные окна 12.5 ms, порог решения |ΔY100_frame| ≥ 0.05 (≈ 2.7 × наибольшего расхождения повторов одинаковых GPU arms rate 1–2 в K). Значения из модели Change 1 не используются.
- CUDA event до и после `enqueueV3` в `deploy/analytics_execution/tensorrt_backend.cpp` во всех arms; worker публикует stream-ordered device interval только под новым kind, legacy и finite-study response schemas не меняются.
- `gpu_queue_depth` в policy request native probe (`deploy/native_gst_probe/vast_native_gst_probe.cpp:3023`) получает реальное значение только под `gpu-colocation-study`; legacy и `finite-component-study` сохраняют 0.
- Новый kind отвергается qualification, promotion, Q4, publication и full validators по образцу `finite-component-study`; legacy и finite-study validators, их counts и historical results не меняются.
- Новые runtime images (TensorRT worker, native GStreamer probe/runtime) с новыми identities, обновлённые parity, refreeze pins и execution closures только для нового kind; все 227 сохраняемых образов и существующие pins остаются нетронутыми. MPS исключён.
- Порядок реализации: код, меняющий packaged runtime bytes, начинается только после merge `fix-accepted-policy-preprocessing` (PR #9) и после того, как repaired Q1 (`qualify-repaired-full-benchmark`) завершён и слит. До этого разрешены только документы этого изменения.

## Capabilities

### New Capabilities
- `gpu-colocation-study`: конечное GPU-only study консолидированного исполнения при batch 1 — три prebuilt arms, фиксированные заранее параметры с документированным происхождением, сбалансированная матрица 24 arms, CUDA event instrumentation, реальный `gpu_queue_depth` только под новым kind, отказ legacy gates, renewal образов/parity/pins и последовательность относительно PR #9 и repaired Q1.

### Modified Capabilities
<!-- Нет. Требования finite-component-study, service-profile-latency-model, benchmark-launch-preparation и component-latency-diagnostics не меняются; новый kind переиспользует их механизмы через собственную спеку. -->

## Impact

- Код (после одобрения спеки и после PR #9 + repaired Q1): `deploy/analytics_execution/tensorrt_backend.cpp` (events, multi-engine session с приоритетом stream), `deploy/analytics_execution/tensorrt_worker.py` (consolidated worker с 4 branch channels и lane arbiter), Dockerfile TensorRT worker; `deploy/native_gst_probe/vast_native_gst_probe.cpp` (study kind, `gpu_queue_depth`), `checkpoint_source_coordinator.cpp`; study plan/driver/reducer и runtime plan в `scripts/` (новый kind рядом с `canonical_systems_study_plan_v1.py`, `run_canonical_systems_study_v1.py`, `reduce_canonical_systems_study_v1.py`, `checkpoint_runtime_plan.py`); тесты в `tests/`; runbook в `docs/`.
- Images: rebuild TensorRT worker и native probe/runtime images, новые identities, parity и refreeze pins, execution closures; старые образы и их receipts сохраняются, удаление или offload любого из 227 образов требует отдельного явного подтверждения пользователя.
- Данные: читается только архив K (`openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/physical-K-completed-v1/s__run/study-results.original.json.gz`) для документированного происхождения параметров; K и все исторические outputs не меняются.
- Зависимости: PR #9 (`fix-accepted-policy-preprocessing`) и repaired Q1 должны быть слиты до любого кода; PR #10 (`add-service-profile-latency-model`) даёт только отрицательные флаги использования и не является источником параметров. Change 3 (cross-stream batching) начинается после этого изменения.
