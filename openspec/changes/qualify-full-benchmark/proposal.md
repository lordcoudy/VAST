## Why

Конечная цель VAST — полностью рабочий проверяемый продукт: полная qualification, Q4, датированная cloud capacity, полная матрица 5 600 arms / 2 800 пар и `verify → finalize → export`. Компонентный релиз (PR2) и finite study (PR5, attempt K: 24/24 arms) доказали работоспособность выбранного GStreamer пути, но полная кампания не исполнена ни на одной стадии: 0/32 qualification cells, 0/1 120 Q4, 0/5 600 arms. Последние попытки A269 и цепочка g остановились до приёмки, а исходники native/runtime образов изменились после последних receipts. Первый этап полной кампании — принятая полная qualification — нужен до любых Q4 и full run.

## What Changes

Это первый из трёх последовательных этапов полной кампании, каждый — отдельный change и MR:
1. **`qualify-full-benchmark` (этот change):** принятая свежая qualification 32 cells с authenticated guardian stop, полной сверкой 37 операций и policy/resource promotion.
2. Следующий change: Q4 (560 A, boundary, 560 B, 280 sizing) и датированная Seafile capacity attestation.
3. Следующий change: persistent service, полная матрица 5 600 / 2 800, `verify → finalize → export`.

Объём этого change:
- **Часы.** Python runtime-пути legacy кампании (DeepStream SDK runtime и protocol bridge, Savant runtime, guardian operational recorder) получают строго возрастающие wall stamps с той же семантикой, что native `NonDecreasingWallClock` из amendment 11 PR5: `max(last+1 ns, raw)`, fail-closed при шаге назад больше 10 ms, сохраняемый `max_clamp`. Предикаты порядка не ослабляются. Повод: J и, вероятно, CPU07 упали на шаге CLOCK_REALTIME назад около 2 ms, а при `--max-unexpected-retries 0` один такой случай останавливает кампанию.
- **Owner 37 операций.** Stock owner исполняет 4 native prechecks, Savant diagnostic и 32 cells под одним guardian с process capture и пишет `vast_original_operational_execution_binding_v1`, после чего cold-closure сверяет все 37 операций с guardian и 8 workers (задачи 12.2–12.4 прежнего change).
- **Full consumers.** Прямые негативные проверки (R13/S6): component, study или чужой kind отклоняется до создания каталогов.
- **Образы.** Пересборка native3 и четырёх runtime образов со свежего source, доказательство неизменности worker2, patch-bound parity 480/32, перепривязка frozen-identity пинов, полный ext4 suite, четыре ручные conformance проверки и девять физических integration тестов.
- **Исполнение.** Свежие inputs, guardian 8/8, prechecks, Savant diagnostic, 32 cells, authenticated stop, closure, promotion. Одна попытка с заранее объявленными правилами отказа; A269 и g остаются историей.
- **Документы.** Runbook qualification, conformance, PLAN и progress с этапным roadmap до полного продукта.

Научные критерии, матрица, seed, окна и пороги не меняются. Q4, capacity и full run в этом change не исполняются, их eligibility остаётся false.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `benchmark-launch-preparation`:
  - R1 снимает требование держать legacy full gates «explicitly unexecuted»: их можно исполнять отдельными reviewed этапами, не ослабляя strict predicates.
  - ADDED: строго возрастающие wall stamps для legacy runtime и recorder.
  - ADDED: этапное возобновление полной кампании, где каждый этап принимается только по своим receipts.
  - R13 (MODIFIED): full entrypoint отклоняет component или неизвестный kind до создания каталогов и файлов.

## Impact

- **Код:**
  - `scripts/checkpoint_deepstream_sdk_runtime.py`, `scripts/checkpoint_deepstream_protocol_bridge.py`, `scripts/checkpoint_savant_sdk_runtime_v3.py`, `scripts/publication_guardian_operational_recorder_v1.py`;
  - новый общий модуль часов;
  - stock owner операций рядом с `scripts/publication_operational_stock_operations_v1.py`, `scripts/publication_policy_qualification_pilot_executor_v2.py` и `scripts/publication_benchmark_native_diagnostic_v1.py`;
  - все full consumers, принимающие full kinds (задачи 3.1 и 3.3 после Amendment 1); код меняется только там, где RED-тест покажет побочный эффект до отказа или отсутствие проверки kind;
  - (Amendment 5) `scripts/checkpoint_gstreamer_analytics_sidecar.py` (точная карта наблюдённых сборок Docker Desktop) и `tests/test_analytics_peer_identity.py`;
  - тесты рядом.
- **Образы и конфигурация:** native3 и четыре runtime образа, `configs/publication_qualification_image_refreeze_v1.json`, parity receipts, frozen-identity test pins. Packaged изменения требуют пересборки и parity по зависимостям.
- **Хост и время:**
  - WSL, RTX 3060, Docker;
  - физическая цепочка около 5–8 часов плюс сборки и parity;
  - оператор должен исключить сон Windows и внешние Docker stop действия на время прогона (цепочку g остановил Docker bulk-stop).
- **Не входит в объём:** Q4, capacity, full run, изменения CI инфраструктуры, очистка Docker cache без отдельного решения.
