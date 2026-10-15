## Context

Мотивация — см. proposal.md. Требования — `specs/service-profile-latency-model/spec.md`.

Что уже есть и переиспользуется:

- `scripts/reduce_canonical_systems_study_v1.py`: `read_closed_rows` (абсолютный путь, size+SHA256, held no-follow epochs, `observations` для повторной проверки), `_recheck_named`, `reduce_arm`/`reduce_study` (канонические partitions, Y100, wait distributions), `distribution`, `_write_exclusive_report`. Публичная функция `reduce_closed_study` требует исходный campaign deadline и не возвращает decoded rows, поэтому модуль повторяет её цикл чтения через `read_closed_rows` (те же caps `MAX_FILE_BYTES`/`MAX_DOCUMENT_BYTES`/`MAX_CAMPAIGN_BYTES`) и затем вызывает `reduce_study` над теми же rows.
- `scripts/canonical_systems_study_plan_v1.py`: `validate_study_plan`, `stream_schedule(plan, stream_id, rate)` — frozen slots с `measurement`, `transport_pts_ns`, `input_frame_key`.

Фактическая форма raw K (проверено чтением `s/run/effect-r1-gpu-1-shared`):

- `waits.decoded.jsonl`: три kind с общим `request_id` — `native_client` (branch, resource, stream_id, input_frame_key, attempt/acquired/reply/released_ns, PID probe), `bridge_route` (те же поля времени, PID bridge), `worker` (received/inference_started/inference_finished/completed_ns, worker_identity). В branch-channel варианте native-client wait ≈1e-6, а сериализация видна на bridge route (median wait fraction 0.33–0.97).
- `native_terminals.decoded.jsonl`: `accepted_record.native_decision_evidence` с `path_entry_timestamp_ms`, `terminal_timestamp_ms`, `terminal_status`, `actual_service_ms`; drops — записи `branch_terminal`.
- `admissions.decoded.jsonl`: `admission_timestamp_ms` (CLOCK_REALTIME, тот же domain, что native terminal; reducer уже вычитает эти отметки).
- Архив K: `openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/physical-K-completed-v1/s__run/study-results.original.json.gz` (`reduction`) и `s__run/closed-inputs.original.json` (31496 B) в репозитории; raw (≈12 GiB) только в WSL `/home/s-a-balashov/vffefab7aK`, пути binding абсолютные.

Наблюдение, влияющее на дизайн: GPU latency при 0.25 fps выше, чем при rate 1 (p50 ≈297 ms против ≈127 ms), значит профиль обслуживания зависит от rate (вероятно, «холодный» режим). Поэтому load extrapolation проверяется только между rate 1 и 2.

## Goals / Non-Goals

**Goals:**
- Один stdlib-only модуль, работающий в той же Python 3.12 среде WSL, что и reducer K.
- Детерминированный отчёт: одинаковые входы и seed дают байт-идентичный JSON.
- Проверяемость на синтетических фикстурах без доступа к raw K.

**Non-Goals:**
- Аналитические формулы (M/M/1, M/G/1) как основной предиктор; они не учитывают однослотовые буферы, детерминированные приходы и общую FIFO route.
- Объяснение причины rate-зависимости обслуживания (только фиксация).
- Использование отчёта в policy engine, calibration или runtime.

## Decisions

1. **Trace-driven discrete-event simulation, а не closed-form.** Система — 6 детерминированных источников, 4 общих FIFO route, буфер 1 drop-newest на stream×branch, frame = max из 4 branches. M/G/1 P-K даёт только среднее ожидание бесконечной очереди и не даёт drops/Y100. Симуляция на ≤2160 frames × 200 реплик × 24+ предсказаний укладывается в минуты на stdlib.
2. **Декомпозиция задержки branch request** (все длительности внутри одного clock domain):
   `L = prefix + route_wait + route_hold + client_overhead + post_route`, где prefix = `path_entry_ms − admission_ms`; route_wait/route_hold — `acquired−attempt` / `released−acquired` из bridge_route; client_overhead = `(native_client.released−native_client.attempt) − (bridge.released−bridge.attempt)`; post_route = `(terminal_ms − path_entry_ms) − native_client_residence`. В симуляции route_wait вычисляется моделью; observed route_wait служит проверкой. Отрицательный client_overhead/post_route ⇒ ошибка (не clamp): это обнаружит неверное соединение.
3. **Буфер.** Probe блокирует pad во время вызова; перед detector стоит `vastanalyticsqueue max-buffers=1` drop-newest. Модель: на stream×branch одна заявка «в работе/ожидает route» + одна в буфере; новая при полном буфере — controlled drop. FIFO порядок route по времени прихода — допущение (фактический порядок lock не наблюдается).
4. **Повторная выборка.** Каждая реплика выбирает компоненты независимо из empirical распределений calibration arm, раздельно по branch. Корреляции между компонентами одного request не сохраняются — допущение, отчёт показывает in-sample ошибку как меру его влияния.
5. **Observed = канонический reducer + сверка с архивом.** Своя реализация partitions исключена; JSON equality с архивной `reduction` K подтверждает, что прочитаны те же данные.
6. **Gate фиксируется в спеке до первого запуска** (8 GPU сравнений rate 1↔2, пороги 0.05/0.05/max(10 ms,10 %)). Альтернатива «выбрать пороги после просмотра» отвергнута: это post-hoc tuning, запрещённый finite-study практикой.
7. **Analysis deadline.** CLI принимает `--analysis-deadline-seconds` (≤ 14400), отсчитывается от старта процесса; отчёт фиксирует, что это новое чтение, а не 5.4 re-reduction.
8. **Размещение.** `scripts/service_profile_latency_model_v1.py` (модуль + `main`), не добавляется в runtime allowlist; тесты `tests/test_service_profile_latency_model_v1.py`. Если `scripts/ci_test_selection_v1.py` требует явной регистрации portable-тестов, тест регистрируется там.

## Risks / Trade-offs

- [In-sample перекрытие: профиль и наблюдение из одной arm] → основная оценка — out-of-sample группы (b) и (c); in-sample публикуется отдельно.
- [Независимая выборка компонентов искажает хвосты] → p95 публикуется, но gate использует только p50, drops и Y100.
- [FIFO-допущение для lock] → observed vs predicted route_wait в отчёте показывает величину ошибки.
- [Gate может оказаться `false`] → это допустимый результат; Changes 2–3 тогда используют заранее заданные фиксированные параметры вместо модели.
- [12 GiB raw только в WSL, без копии в репозитории] → запуск только в WSL; descriptors и SHA в отчёте; raw не копируется и не изменяется.
- [Объём памяти] → чтение по arm, освобождение decoded rows после профиля arm; caps reducer сохраняются.

## Migration Plan

Не требуется: новый host-only инструмент, runtime и данные не меняются. Откат — удаление модуля и отчёта.
