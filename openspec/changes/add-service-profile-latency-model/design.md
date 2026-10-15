## Context

Мотивация — см. proposal.md. Требования, включая полностью зафиксированную модель и gates, — `specs/service-profile-latency-model/spec.md`; здесь только обоснование и способ реализации.

Что переиспользуется:

- `scripts/reduce_canonical_systems_study_v1.py`: `read_closed_rows` (абсолютный путь, size+SHA256, held no-follow epochs, `observations`), `_recheck_named`, `reduce_arm` (канонические partitions, Y100, wait distributions одной arm), `distribution` (nearest-rank), `_write_exclusive_report`, caps `MAX_FILE_BYTES`/`MAX_DOCUMENT_BYTES`/`MAX_CAMPAIGN_BYTES`/`MAX_INPUT_FILES`. `reduce_closed_study` не используется: он требует все 24 arms в памяти, исходный campaign deadline и не отдаёт decoded rows. Модуль повторяет его порядок чтения (plan, затем по arms: closure, роли в sorted порядке), чтобы список descriptors совпадал с архивным `closed_input_descriptors`.
- `scripts/canonical_systems_study_plan_v1.py`: `validate_study_plan`, `stream_schedule` (слоты с `measurement`, `input_frame_key`, offsets).

Форма raw K (проверено на `effect-r1-gpu-1-shared` и при ревью ещё на двух GPU arms): общий `request_id` у `native_client` (PID probe 42), `bridge_route` (PID bridge 6065) и `worker` (PID `null`, namespace unknown) rows; 0 пропусков и 0 дубликатов; `waits` содержит также warmup/drain requests (5040 rows против 4320 measured branch requests в gpu-1-shared). Native terminals: `accepted_record.native_decision_evidence.{path_entry_timestamp_ms, terminal_timestamp_ms, terminal_status}`; drops — `branch_terminal` с `terminal_reason`.

Порядок исполнения одного request (код K `fefab7a9`): admission → decode → `queue` → `vastcheckpointprefixqueue max-buffers=1` → videoconvert/videoscale → [shared: tee] → `vastanalyticsqueue max-buffers=1` → probe: `path_entry`, `enter_path` RPC, frame map, SHA (`vast_native_gst_probe.cpp:3049–3117`) → native client lock → bridge: preprocessing, SHA (`checkpoint_gstreamer_analytics_bridge.py:707–759`) → route `threading.Lock` (:486) → worker → reply → terminal. Измерено при ревью (gpu-1-shared): `bridge_pre` p50 25.75 ms (min 7.15), `bridge_post` p50 0.21 ms.

Наблюдения, повлиявшие на дизайн:
- GPU latency при 0.25 fps выше, чем при rate 1 (p50 ≈297 ms против ≈127 ms) → обслуживание зависит от rate; load extrapolation проверяется только между rate 1 и 2.
- GPU arms при rate 1–2 не имеют controlled drops в measurement окне, route utilisation ≈15 % → GPU сравнения почти не проверяют очередь; поэтому разрешение на предсказания под нагрузкой требует CPU сравнений, где drops ≈50–97 %.
- В нагруженных CPU arms около половины requests входят в probe в пределах 3 ms после предыдущего terminal той же пары stream×branch → `prefix` содержит ожидание в analytics queue; отсюда фильтр `prefix_unqueued`.

## Goals / Non-Goals

**Goals:**
- Один stdlib-only модуль для той же Python 3.12 среды WSL, что и reducer K.
- Байт-идентичное тело отчёта при одинаковых входах.
- Проверяемость на синтетических фикстурах без raw K.

**Non-Goals:**
- Closed-form формулы (M/M/1, M/G/1) как предиктор: не дают drops/Y100 при однослотовых буферах и детерминированных приходах.
- Объяснение rate-зависимости обслуживания.
- Использование отчёта в policy engine, calibration или runtime.

## Decisions

1. **Discrete-event симуляция по зафиксированной в спеке схеме.** Альтернатива — аналитическая модель — отвергнута (см. Non-Goals). Объём: ≤2400 слотов × 6 streams × 4 branches × 200 реплик × ~68 сравнений; событийная очередь на `heapq`, ожидаемое время — минуты.
2. **Компоненты в порядке кода, с cross-PID вычитанием только при доказанном общем domain.** Исходная версия ставила клиентские накладные расходы после route и синхронизировала приходы 6 streams на FIFO, завышая route wait. Finite-study spec уже определяет общий CLOCK_MONOTONIC domain (одинаковый boot_id, offsets `0 0`), и K driver проверил это до media; модуль повторно проверяет поля `clock_domain` каждой пары rows. Тождество суммы (допуск 0.001 ms из-за ms-float отметок) выполняется по построению и служит только защитой от ошибок реализации; соединения проверяются совпадением identity полей native client row и terminal, вложенность bridge в native — неотрицательностью `bridge_pre`/`bridge_post`.
3. **Совместная выборка кортежа после analytics queue, отдельная — prefix.** Сохраняет корреляцию клиентских компонентов одного request; prefix берётся только из `prefix_unqueued`, чтобы не учитывать ожидание в analytics queue дважды.
4. **Prefix как сервер с буфером 1, одна выборка на кадр и process.** Prefix queue стоит перед CPU videoconvert/videoscale; в K она дала все drops gpu-2-shared и 16 drops cpu-1-shared. Decode не отделим по наблюдениям и входит в длительность сервера — допущение в отчёте.
5. **Observed = `reduce_arm` + сверка с архивом по arms, binding и descriptors.** Своя реализация partitions исключена; per-arm вызов позволяет освобождать rows после каждой arm.
6. **Два флага вместо одного.** Профиль GPU компонентов и предсказание очереди — разные утверждения с разной доказательной базой (см. Context); флаги разделяют их до первого запуска.
7. **Детерминизм.** Seed на реплику из SHA256 (`20260323:<comparison_id>:<replica>`), независимый от порядка вычислений; тело отчёта без elapsed/времени запуска (они в stdout receipt); `json.dumps(sort_keys=True, separators=(",", ":"), allow_nan=False)`.
8. **Размещение.** `scripts/service_profile_latency_model_v1.py` (модуль + `main`) вне runtime allowlist; тесты `tests/test_service_profile_latency_model_v1.py`; регистрация в `scripts/ci_test_selection_v1.py`, если selection требует явного списка. Ёмкости буферов проверяются тестом через `git show fefab7a9…:<path>`, тест пропускается с явной причиной, если commit недоступен в checkout.

## Risks / Trade-offs

- [In-sample перекрытие профиля и наблюдения] → решающие группы включают out-of-sample (b); (a) публикуется отдельно и входит в gate только как необходимое условие.
- [Немоделируемые bridge GIL, конкуренция GPU/CPU, не-FIFO lock] → перечислены в отчёте; observed vs predicted `route_wait` и drops по причинам показывают величину ошибки; CPU gate ловит их влияние под нагрузкой.
- [Порог 10 ms для `prefix_unqueued`] → выбран по механизму (ожидавший request входит в probe через terminal RPC + probe entry + decide, на K 1.7–5 ms; незанятый — не раньше следующего прихода, ≥100 ms); первая версия с 1 ms не исключала ни одного request (ревью). Отчёт публикует разрывы по корзинам ≤10 / 10–100 / >100 ms.
- [CPU gate почти недостижим: CPU rate 2 даёт 34–103 completed frames] → заявлено заранее; `false` — допустимый исход.
- [Gates могут оказаться `false`] → допустимый результат; Changes 2–3 тогда задают параметры заранее фиксированными значениями без модели.
- [12 GiB raw только в WSL] → запуск только там; descriptors и SHA в отчёте; raw не копируется и не изменяется.

## Migration Plan

Не требуется: новый host-only инструмент, runtime и данные не меняются. Откат — удаление модуля и отчёта.
