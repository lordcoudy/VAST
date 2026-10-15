## 0. Спека (этот этап)

- [ ] 0.1 Документы изменения проходят `openspec validate study-gpu-colocation --strict`; Draft PR открыт; независимое ревью спеки с вердиктом и рассмотренным коммитом записано в PR
- [ ] 0.2 Перед началом реализации: PR #9 (`fix-accepted-policy-preprocessing`) и repaired Q1 (`qualify-repaired-full-benchmark`) слиты в master — проверка `gh pr view 9 --json state` и состояния PR repaired Q1, ссылки записаны в PR
- [ ] 0.3 Ветка синхронизирована с master; Context/Decisions design сверены с фактическим кодом после merge; при расхождении в требованиях выполнено `/opsx:update study-gpu-colocation` и повторное ревью — результат сверки записан в PR

## 1. Plan и kind

- [ ] 1.1 `scripts/gpu_colocation_study_plan_v1.py`: kind `gpu-colocation-study`, 24 arms (2 rates × 2 topologies × 3 colocation arms × 2 repeats), seed-порядок repeat 1 и обращение repeat 2, параметры с provenance; проверка — unit-тесты на точный порядок, обращение, запрет provenance со ссылкой на `service-profile-latency-model` и отказ при неверной identity архива K
- [ ] 1.2 Runtime plan `build_gpu_colocation_runtime_plan_v1` и dispatch по kind в `checkpoint_runtime.py`; проверка — тесты, что finite runtime plan проходит прежние тесты без изменений, а планы разных kinds взаимно отвергаются
- [ ] 1.3 Отказ legacy gates: тесты подают plan/runtime/arm/study/binding artifacts нового kind в qualification, promotion, Q4, publication, full и finite validators и ожидают отказ; finite artifacts — в validators нового kind

## 2. TensorRT backend и worker

- [ ] 2.1 CUDA events до/после `enqueueV3` в `deploy/analytics_execution/tensorrt_backend.cpp`, `enqueue_device_elapsed_ns` с проверкой host envelope; проверка — C++/ctypes тест на GPU host (интервал положителен и внутри envelope) и тест нарушения envelope
- [ ] 2.2 Shared-context sessions с `cudaStreamCreateWithPriority`, отчёт context identity и priority range; проверка — GPU тест: 4 sessions одного process сообщают один context и назначенные приоритеты `min(greatest + r, least)`
- [ ] 2.3 Lane arbiter (цикл 50 ms, окна 12.5 ms, порядок foreign_object/damage/vehicle_type/plate_number, non-work-conserving, пропуск съеденного окна, запись overrun); проверка — детерминированные тесты арбитра на инжектируемых часах и GPU тест исключительности (не более одной GPU работы одновременно)
- [ ] 2.4 `tensorrt_worker.py`: режим `--colocation-mode` с 4 bindings/sockets и host thread на branch; `--study-kind`, публикация `enqueue_device_elapsed_ns` и lane полей только под новым kind; проверка — тесты exact schema: legacy/finite response без новых полей, новый kind с полями; два одновременных requests разных branches реально перекрываются, второй request того же branch запрещён до terminal

## 3. Sidecar, bridge и native probe

- [ ] 3.1 Sidecar: запуск 4 GPU containers или 1 consolidated container по arm, тот же набор routes/capabilities; проверка — тесты фабрики и readiness (context topology, отказ при несоответствии)
- [ ] 3.2 Bridge: GPU outstanding counter и seqlock snapshot в sealed memfd, передача read-only FD при handshake только под новым kind; проверка — тесты счётчика при ожидании/удержании/failure и отсутствия FD под legacy/finite
- [ ] 3.3 Native probe: kind `gpu-colocation-study` в `--checkpoint-study-kind` и source coordinator; чтение snapshot перед decide, запись sequence/publish/read ns; `gpu_queue_depth = 0` под legacy/finite; проверка — C++ тесты (torn read → failed, legacy → 0) и `tests/cpp/checkpoint_native_policy_client_test.cpp`
- [ ] 3.4 Отказ при non-GPU decision и при MPS daemon/переменных; проверка — тесты driver readiness и arm failure

## 4. Driver, lifecycle и reducer

- [ ] 4.1 Driver: per-arm свежий pool и native processes, полная retirement между arms, clocks 14,400 s preparation/campaign, одна attempt, без retry; проверка — тесты lifecycle с fake factory (порядок arms, retirement перед следующей readiness, остановка FAILED с partial raw)
- [ ] 4.2 Reducer: `reduce_arm` для нового kind, 16 контрастов + 8 описательных, флаги `<X>_beats_contexts4`/`<X>_worse_than_contexts4`/`inconclusive`/`consolidation_beats_contexts4_at_batch1`, распределения enqueue/H2D/D2H/route wait/`gpu_queue_depth`/lane; проверка — тесты на синтетических arms для каждого исхода и границы 0.05
- [ ] 4.3 Независимая повторная редукция на синтетическом закрытом raw даёт идентичный результат; проверка — тест

## 5. Images, parity, pins

- [ ] 5.1 Проверить место (C: 40 GiB floor, пороги файловых систем) и собрать новый TensorRT worker image (новый tag в `configs/publication_image_build_v1.json`, allowlist); проверка — `docker image inspect` identities и labels source/dependency/build-context; ни один из 227 образов не удалён
- [ ] 5.2 Новый worker freeze receipt, refreeze entry и `configs/analytics_execution_layer.gpu-colocation-v1.json`; проверка — `_current_workers` принимает новый receipt для нового kind и отвергает старый receipt при новом source
- [ ] 5.3 Model parity нового image для всех 4 branches в каждом из 3 arms против принятой reference; проверка — новые `configs/checkpoint_analytics_model_parity.gpu-colocation-v1.*` assessment/acceptance receipts
- [ ] 5.4 Обновлённые native/runtime allowlists и execution code closure; проверка — `prepare` собирает native/runtime из текущего source и source pins проходят перед arm; stale binary приводит к отказу

## 6. CI, документы, исполнение

- [ ] 6.1 Обязательный CI зелёный на коммите реализации; inventory skip-тестов не растёт; проверка — hosted CI run в PR
- [ ] 6.2 Runbook `docs/gpu-colocation-study-runbook.md` (команда, бюджеты, запрет изменений во время кампании); проверка — ревью
- [ ] 6.3 Preparation attempt: intake, сборки, readiness трёх видов pool без media, измеренное время старта pool укладывается в бюджет; проверка — closed preparation descriptor
- [ ] 6.4 Кампания 24 arms и редукция; проверка — `study-results.original.json`, closed-inputs binding, `gpu_colocation_study_complete`, флаги
- [ ] 6.5 Независимая повторная редукция и conformance report по каждому требованию (где реализовано, каким тестом подтверждено, расхождения, что не проверено автоматически); проверка — отчёт в каталоге изменения и ревью в PR
