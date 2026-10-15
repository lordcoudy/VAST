## 0. Спека и предусловия

- [ ] 0.1 Документы изменения проходят `openspec validate study-gpu-colocation --strict`; Draft PR открыт; независимое ревью спеки с вердиктом и рассмотренным коммитом записано в PR
- [ ] 0.2 Перед началом реализации: PR #9 (`fix-accepted-policy-preprocessing`) слит в master, и PR repaired Q1 (`qualify-repaired-full-benchmark`) слит с accepted Q1 — проверка `gh pr view` обоих PR, ссылки и результат Q1 записаны в PR; если repaired Q1 закрыт failed или без merge, реализация не начинается без явного решения человека, записанного в PR
- [ ] 0.3 Ветка синхронизирована с master; Context/Decisions design сверены с фактическим кодом после merge (номера строк, seams, pins); решение человека о порядке merge этого изменения относительно Q4/full записано в PR; при расхождении в требованиях выполнено `/opsx:update study-gpu-colocation` и повторное ревью — результат сверки записан в PR

## 1. Plan и kind

- [ ] 1.1 `scripts/gpu_colocation_study_plan_v1.py`: kind `gpu-colocation-study`, 24 arms, seed-порядок repeat 1 и точное обращение repeat 2, параметры с provenance (`inherited_finite_study`/`first_principles`/`k_raw_archive`), проверка size+SHA256 архива K; проверка — unit-тесты на точный порядок, обращение, отказ при provenance со ссылкой на `service-profile-latency-model` и при неверной identity архива K
- [ ] 1.2 Runtime plan `build_gpu_colocation_runtime_plan_v1` и dispatch по kind в `checkpoint_runtime.py`; проверка — существующие finite/legacy тесты проходят без изменений, планы разных kinds взаимно отвергаются
- [ ] 1.3 Ветки нового kind в модулях с зашитым `finite-component-study` (`checkpoint_gstreamer_runtime.py`, `checkpoint_native_policy_runtime.py`, `publication_operational_request_domain_v1.py`, `publication_operational_runtime_context_v1.py`, `publication_operational_capture_plan_v1.py`, `publication_guardian_component_preprocessing_contract_v1.py`); finite/legacy ветки текстуально прежние; проверка — тест на модуль, что finite/legacy входы дают прежний результат, и diff review
- [ ] 1.4 Отказ legacy gates: тесты подают plan/runtime/arm/study/binding artifacts нового kind в qualification, promotion, Q4, publication, full и finite validators и ожидают отказ; finite artifacts — в validators нового kind

## 2. TensorRT backend и worker

- [ ] 2.1 CUDA events до/после `enqueueV3` в `deploy/analytics_execution/tensorrt_backend.cpp` только при флаге instrumentation нового kind, `enqueue_device_elapsed_ns` с проверкой host envelope; проверка — GPU тест (интервал положителен и внутри envelope), тест нарушения envelope и тест, что без флага последовательность CUDA calls и ошибки прежние
- [ ] 2.2 Shared-context sessions с `cudaStreamCreateWithPriority`, отчёт context ID (`cuCtxGetId`) и priority range; проверка — GPU тест: 4 sessions одного process сообщают равный context ID и приоритеты `min(greatest + r, least)`; тест отказа preparation при диапазоне < 2 уровней
- [ ] 2.3 Lane arbiter по правилу спеки (цикл 50 ms, окна 12.5 ms, порядок foreign_object/damage/vehicle_type/plate_number, старт только в своём окне и после переходящей работы, overrun, `lane_window_skipped`, non-work-conserving); проверка — детерминированные тесты на инжектируемых часах, включая оба случая примера спеки (переходящая работа до 14.0 и до 26.0), и GPU тест исключительности
- [ ] 2.4 `tensorrt_worker.py`: режим `--colocation-mode` с 4 bindings/sockets и host thread на branch; `--study-kind`; публикация `enqueue_device_elapsed_ns`, host overhead и lane полей только под новым kind; проверка — тесты exact schema (legacy/finite без новых полей), реальное перекрытие requests разных branches и запрет второго request того же branch до terminal

## 3. Sidecar, bridge и native probe

- [ ] 3.1 Sidecar: запуск 4 GPU containers или 1 consolidated container по arm с тем же набором routes/capabilities; readiness проверяет тройки (container ID, host PID, context ID) и platform identity (Windows build, driver, CUDA, HAGS, Docker Desktop); проверка — тесты фабрики и readiness, отказ при несоответствии топологии или drift платформы
- [ ] 3.2 Bridge: GPU outstanding counter и seqlock snapshot в sealed memfd, передача read-only FD при handshake только под новым kind; проверка — тесты счётчика при ожидании/удержании/failure и отсутствия FD под legacy/finite
- [ ] 3.3 Native probe: kind `gpu-colocation-study` в `--checkpoint-study-kind` и source coordinator; чтение snapshot перед decide, запись sequence/publish/read ns; `gpu_queue_depth = 0` под legacy/finite; проверка — C++ тесты (разорванное чтение → failed, publish позже read → failed, legacy → 0) и `tests/cpp/checkpoint_native_policy_client_test.cpp`
- [ ] 3.4 Отказ при non-GPU decision и при MPS daemon/переменных; проверка — тесты readiness и arm failure

## 4. Driver, lifecycle и reducer

- [ ] 4.1 Driver: per-arm свежий pool в новом namespace и свои native processes, полная retirement между arms, clocks 14,400 s preparation/campaign, одна attempt, без retry; измерение старта/retirement каждого вида pool в preparation и проверка формулы бюджета спеки; проверка — тесты с fake factory (порядок arms, retirement до следующей readiness, отказ при превышении бюджета, остановка FAILED с partial raw)
- [ ] 4.2 Reducer: `reduce_arm` для нового kind, 16 per-repeat и 8 средних по repeats контрастов, флаги `<X>_beats_contexts4`/`<X>_worse_than_contexts4`/`inconclusive`/`consolidation_beats_contexts4_at_batch1`, распределения enqueue/H2D/D2H/host overhead/route wait/`gpu_queue_depth`/lane, раскрытие совпадения порога с PR #10 и ограничения held/fresh pool; проверка — тесты на синтетических arms для каждого исхода, границы 0.05 и смешанных знаков
- [ ] 4.3 Независимая повторная редукция на синтетическом закрытом raw даёт идентичный результат; проверка — тест

## 5. Images, parity, pins

- [ ] 5.1 Проверить место (C: 40 GiB floor, пороги файловых систем) и собрать новый TensorRT worker image по `configs/gpu_colocation_image_build_v1.json` с собственным loader; проверка — `docker image inspect` identities/labels; существующие registries байт-идентичны; ни один из 227 образов не удалён
- [ ] 5.2 Новый worker freeze receipt, `configs/gpu_colocation_image_refreeze_v1.json` и `configs/analytics_execution_layer.gpu-colocation-v1.json`; проверка — consumer нового kind принимает их, а legacy `_current_workers` отказывает с прежней причиной drift (тест)
- [ ] 5.3 Model parity нового image для всех 4 branches в каждом из 3 arms против принятой reference, engines не пересобираются; проверка — `configs/checkpoint_analytics_model_parity.gpu-colocation-v1.*` assessment/acceptance receipts
- [ ] 5.4 Native/runtime allowlists и execution code closure нового kind; проверка — `prepare` собирает native/runtime из текущего source, source pins проходят перед arm, stale binary приводит к отказу

## 6. CI, документы, исполнение

- [ ] 6.1 Обязательный CI зелёный на коммите реализации; inventory skip-тестов не растёт; проверка — hosted CI run в PR
- [ ] 6.2 Runbook `docs/gpu-colocation-study-runbook.md` (команда, бюджеты, запрет изменений во время кампании, последствия для legacy receipts); проверка — ревью
- [ ] 6.3 Preparation attempt: intake, сборки, readiness трёх видов pool без media, бюджет pool по формуле; проверка — closed preparation descriptor
- [ ] 6.4 Кампания 24 arms и редукция; проверка — `study-results.original.json`, closed-inputs binding, `gpu_colocation_study_complete`, флаги
- [ ] 6.5 Независимая повторная редукция и conformance report по каждому требованию (где реализовано, каким тестом подтверждено, расхождения, что не проверено автоматически); проверка — отчёт в каталоге изменения и ревью в PR
