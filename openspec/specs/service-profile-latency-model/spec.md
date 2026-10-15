# service-profile-latency-model Specification

## Purpose

Описательный профиль обслуживания и проверенный предиктор очередей и латентности, построенные по закрытым данным finite component study, чтобы последующие study changes выбирали параметры заранее, без влияния на legacy campaigns, policy formulas и калибровку.

## Requirements

### Requirement: Inputs are pinned closed study raw

Model SHALL читать только finite-study binding kind `finite-component-study-closed-inputs`, переданный абсолютным путём, `size_bytes` и SHA256. Для attempt K binding SHALL быть ровно 31496 B, SHA256 `8f92bb401f8de4b4403dc46ecd227d30acbfbe5e80243fd86f5d11b57805ba90`, архивная редукция — `openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/physical-K-completed-v1/s__run/study-results.original.json.gz` ровно 590982 B, SHA256 `c483d64fbb9ddac0127dcc93d8482cb0b409af0d35bb3870e1b2293181588d8b`. Каждый файл binding SHALL читаться с проверкой `size_bytes`+SHA256, held no-follow named epochs и повторной проверкой epochs после расчёта, с caps finite-study reducer. Binding SHALL покрывать ровно 24 effect arms плана, прошедшего `validate_study_plan`. Чтение SHALL иметь собственный явный analysis deadline (не более 14400 s от старта процесса) и SHALL NOT называться независимой повторной редукцией (5.4) или использовать исходный campaign deadline. Исходные файлы SHALL оставаться неизменными.

#### Scenario: Binding and raw match their identities
- **WHEN** binding, архив и все файлы binding совпадают по size+SHA256, epochs стабильны и план валиден
- **THEN** model SHALL построить профиль и предсказания, а отчёт SHALL содержать все прочитанные через binding descriptors в порядке чтения (без самого binding и архива), identities binding и архива, analysis deadline и `new_descriptive_read_not_rereduction: true`.

#### Scenario: A file differs, drifts or the deadline expires
- **WHEN** любой файл отличается по size/SHA256, является symlink, меняет epoch до повторной проверки, binding содержит не 24 effect arms или analysis deadline истёк
- **THEN** model SHALL завершиться ошибкой без отчёта; частичный результат SHALL NOT записываться.

### Requirement: Observed metrics come from the canonical reducer and equal the archive

Наблюдаемые значения SHALL вычисляться существующей per-arm finite-study reduction (`reduce_arm`) над теми же decoded rows, по одной arm за раз. Канонический JSON (sorted keys) каждой вычисленной arm reduction SHALL совпадать с `reduction.arms[<arm_id>]` архива; top-level `binding` архива SHALL совпадать с прочитанным binding descriptor; список прочитанных descriptors SHALL совпадать с `reduction.closed_input_descriptors` архива. Любое расхождение SHALL быть ошибкой без отчёта.

#### Scenario: Recomputed observation equals the archive
- **WHEN** все 24 arm reductions, binding и descriptors совпадают с архивом
- **THEN** отчёт SHALL использовать эти значения как observed.

#### Scenario: Recomputed observation differs
- **WHEN** хотя бы одно поле arm reduction, binding или descriptor отличается от архива
- **THEN** model SHALL завершиться ошибкой и SHALL NOT сравнивать предсказания с неподтверждёнными observed значениями.

### Requirement: Service profile follows the code-order stage sequence

Профиль SHALL строиться по completed branch requests только measurement-окна (слоты frozen schedule с `measurement = true`); warmup/drain requests SHALL публиковаться только как counts. Каждый request SHALL соединяться: native terminal по (`input_frame_key`, branch), `native_client`, `bridge_route` и `worker` wait rows — по точному `request_id`. Компоненты SHALL определяться в порядке исполнения кода:

1. `prefix` = native `path_entry_timestamp_ms` − `admission_timestamp_ms` (CLOCK_REALTIME одного host);
2. `probe_pre` = (`terminal_timestamp_ms` − `path_entry_timestamp_ms`) − native client residence (`released_ns` − `attempt_ns`), с допущением, что probe-работа после release равна нулю;
3. `native_wait` = native `acquired_ns` − `attempt_ns`;
4. `bridge_pre` = bridge `attempt_ns` − native `acquired_ns`;
5. `route_wait` = bridge `acquired_ns` − `attempt_ns`;
6. `route_hold` = bridge `released_ns` − `acquired_ns`;
7. `bridge_post` = native `released_ns` − bridge `released_ns`.

Компоненты 4 и 7 вычитают отметки разных процессов и SHALL допускаться только когда `clock_domain` обеих записей имеет `CLOCK_MONOTONIC`, одинаковый `boot_id` и `time_namespace` с monotonic и boottime offsets `0,0`, как доказано finite-study driver gate; иначе компонент SHALL быть `unknown`. Сумма компонентов 1–7 SHALL совпадать с наблюдаемой branch latency reducer с допуском 0.001 ms. Worker backend и residence SHALL публиковаться отдельно с меткой «не чистое GPU kernel time». Для каждого компонента и arm/branch SHALL публиковаться count, unknown, p50/p95/p99 (nearest-rank `distribution` reducer), mean и CV. Отсутствующее соединение SHALL увеличивать `unknown` без заполнения; повторный `request_id` в одной роли, нарушенный порядок отметок, отрицательный компонент или нарушение суммы SHALL быть ошибкой.

`prefix` включает ожидание в analytics queue, когда предыдущий request той же пары stream×branch ещё обрабатывался. Request SHALL считаться `prefix_unqueued`, когда у той же пары stream×branch нет предыдущего request в arm или `path_entry_timestamp_ms` больше предыдущего `terminal_timestamp_ms` той же пары более чем на 10 ms; только такие requests SHALL входить в prefix-выборку предиктора. Порог 10 ms SHALL обосновываться механизмом: request, ожидавший в analytics queue, входит в probe после завершения предыдущего за время terminal RPC, probe entry и policy decide (на K 1.7–5 ms), а у незанятого разрыв не меньше оставшейся части upstream prefix (на K > 10 ms более чем в 99.7 % случаев; при совпадении с decode/preprocess возможны разрывы 10–100 ms). Отчёт SHALL публиковать по каждой arm/branch число requests с разрывом ≤ 10 ms, 10–100 ms и > 100 ms и размер каждого prefix пула и пула кортежей.

Native client row SHALL совпадать с `decision_request` native terminal (тот же объект, который проверяет reducer) по `run_id`, `input_frame_key`, branch, `stream_id` и `frame_id`; несовпадение SHALL быть ошибкой. Тождество суммы выполняется по построению для средних компонентов и SHALL NOT считаться проверкой соединений; вложенность bridge внутри native client SHALL проверяться неотрицательностью компонентов 4 и 7.

#### Scenario: Every completed request is joined and sums exactly
- **WHEN** каждая completed measured request имеет native terminal и по одной `native_client`, `bridge_route`, `worker` записи, а clock domains допускают компоненты 4 и 7
- **THEN** профиль SHALL содержать все 7 компонентов с `unknown = 0`, и replay компонентов каждого request SHALL воспроизводить его latency reducer в пределах 0.001 ms.

#### Scenario: A join is missing
- **WHEN** у completed request нет `bridge_route` или `worker` записи
- **THEN** профиль SHALL увеличить `unknown` соответствующих компонентов, исключить request только из их распределений и сохранить его в observed знаменателях.

#### Scenario: Duplicate, disordered or inconsistent rows
- **WHEN** `request_id` повторяется в одной роли, порядок отметок внутри записи нарушен, компонент отрицателен, native client row не совпадает с terminal по identity полям или сумма расходится с latency больше чем на 0.001 ms
- **THEN** model SHALL завершиться ошибкой без отчёта.

### Requirement: The predictor is fully specified before its first run

Предиктор SHALL моделировать target arm по профилю calibration arm так:

- приходы — все слоты frozen schedule плана для rate target arm (warmup, measurement, drain), а не наблюдаемые admissions;
- prefix stage — один сервер на pipeline process (shared: один на stream; baseline: один на stream×branch) с буфером ёмкости 1 drop-newest; drop в shared отбрасывает все 4 branches кадра, в baseline — только свой branch; длительность — одна выборка на кадр и process из `prefix_unqueued` calibration arm (shared: одна выборка из общего пула по branches задаёт момент выхода кадра для всех 4 branches; baseline: пул своего branch);
- analytics queue — на stream×branch буфер ёмкости 1 drop-newest перед probe, который обрабатывает один request за раз;
- после выхода из analytics queue request проходит `probe_pre`, `native_wait`, `bridge_pre` как чистые задержки, затем FIFO route по branch, общий для всех 6 streams, с длительностью `route_hold`, затем `bridge_post`; кортеж (`probe_pre`, `native_wait`, `bridge_pre`, `route_hold`, `bridge_post`) SHALL выбираться совместно из одного completed measured request calibration arm того же branch;
- ёмкости буферов SHALL равняться значениям frozen source commit K `fefab7a93ab5e850ddcb90ac4c9d8eb351811fa0` (`analytics_queue.max_buffers` в `configs/experiments.yaml` и `max-buffers` `vastcheckpointprefixqueue` в native probe), обе равны 1;
- request, не завершённый к концу последнего слота плюс `drain_ns` плана, SHALL считаться censored;
- оцениваются только measurement-слоты; frame on-time только когда все 4 branches completed и максимум latency ≤ `deadline_ns` плана;
- 200 реплик; генератор каждой реплики инициализируется первыми 8 байтами SHA256 строки `20260323:<comparison_id>:<replica>`;
- метрики реплики: `drop_fraction` = branches `N_controlled_dropped` / branches `N_planned` (с разбивкой по `native_postdecode_preprocess_queue_full_drop_newest` и `native_pre_detector_queue_full_drop_newest`), `Y100_frame` = on-time frames / planned frames, p50 и p95 completed frame latency (nearest-rank); предсказание = среднее по репликам, интервал = nearest-rank 2.5/97.5 перцентили; p50 реплики без completed frames не определён.

Отчёт SHALL перечислять немоделируемые факторы: порядок захвата `threading.Lock` не гарантированно FIFO, общий Python bridge process (GIL), конкуренция routes на одном GPU и CPU, decode как часть prefix без отдельной очереди, policy decide RPC (исполняется в probe после analytics queue, но учитывается в prefix server), независимость prefix от остального кортежа. Пустой пул выборки SHALL давать `prediction: null` с причиной. Отчёт SHALL содержать SHA256 модуля и source commit реализации. Каждый запуск на данных K SHALL писать новый файл, и все такие запуски SHALL перечисляться в сводке; изменение любого пункта этого требования или требования «Service profile follows the code-order stage sequence» (компоненты, популяция, порог `prefix_unqueued`) после первого запуска на K SHALL требовать нового ревью спеки.

#### Scenario: Calibration profile has complete pools
- **WHEN** у calibration arm непусты пулы prefix и кортежей для всех 4 branches
- **THEN** отчёт SHALL содержать предсказание target arm с интервалами, planned frames, равным observed `N_planned`, и списком немоделируемых факторов.

#### Scenario: Offered load exceeds capacity
- **WHEN** route hold или prefix длительность превышает интервал приходов
- **THEN** предиктор SHALL выдавать controlled drops по соответствующей причине; значения SHALL NOT ограничиваться или исправляться под observed.

#### Scenario: Same inputs and seed
- **WHEN** модель дважды запускается на одинаковых входах
- **THEN** тело отчёта SHALL быть байт-идентичным; elapsed time и иные run-метаданные SHALL выводиться только в stdout receipt.

#### Scenario: A pool is empty
- **WHEN** у calibration arm пуст prefix пул или пул кортежей какого-либо branch
- **THEN** предсказание этой пары SHALL быть `null` с причиной, и gate, включающий её, SHALL быть `false`.

### Requirement: Validation groups and usability gates are fixed in advance

Отчёт SHALL содержать для каждого сравнения observed, predicted, интервал и разность: (a) in-sample — каждая из 24 arms по собственному профилю; (b) load extrapolation — для одинаковых repeat/resource/topology calibration rate 1 → target rate 2 и rate 2 → rate 1; (c) cross-repeat — r1 ↔ r2 для одинаковых resource/topology/rate. Rate 0.25 SHALL участвовать только в (a) и (c) и сопровождаться сравнением `route_hold` с rate 1 той же конфигурации, без вывода о причине. Сравнение SHALL проходить порог, когда предсказание не `null`, |ΔY100_frame| ≤ 0.05, |Δ`drop_fraction`| ≤ 0.05, observed completed frames > 0, p50 определён во всех репликах и |Δp50| ≤ max(10 ms, 0.10 × observed p50).

- `gpu_latency_profile_use_permitted` SHALL быть `true` тогда и только тогда, когда проходят все 12 GPU сравнений группы (a) и все 8 GPU сравнений группы (b).
- `queueing_extrapolation_use_permitted` SHALL быть `true` тогда и только тогда, когда `gpu_latency_profile_use_permitted` = `true` и проходят все 12 CPU сравнений группы (a) и все 8 CPU сравнений группы (b).

Когда `true` только `gpu_latency_profile_use_permitted`, последующие study changes SHALL ограничиваться распределениями GPU компонентов для параметров при rate ≤ 2 и SHALL NOT использовать предсказания waits и drops; использование предсказаний waits и drops под нагрузкой SHALL требовать `queueing_extrapolation_use_permitted` = `true`. При обоих `false` параметры из модели SHALL NOT выводиться. Отчёт SHALL заранее указывать, что CPU rate 2 arms имеют лишь 34–103 completed frames, а baseline CPU prefix пулы (по branch) при rate 2 содержат единицы `prefix_unqueued` requests, поэтому пустые пулы (`prediction: null`) и требование определённого p50 во всех репликах делают `queueing_extrapolation_use_permitted` = `false` вероятным исходом; такой исход SHALL считаться допустимым результатом, а не основанием менять пороги. Пороги, состав групп и правила флагов SHALL NOT меняться после первого запуска на K без нового ревью спеки.

#### Scenario: All gated comparisons pass
- **WHEN** все GPU и CPU сравнения групп (a) и (b) проходят пороги
- **THEN** оба флага SHALL быть `true`, и отчёт SHALL перечислять разрешённые профили.

#### Scenario: Only GPU comparisons pass
- **WHEN** все 20 GPU сравнений проходят, а хотя бы одно CPU сравнение — нет
- **THEN** `gpu_latency_profile_use_permitted` SHALL быть `true`, `queueing_extrapolation_use_permitted` — `false`, и отчёт SHALL назвать нарушившие сравнения.

#### Scenario: A GPU comparison fails
- **WHEN** хотя бы одно GPU сравнение групп (a) или (b) не проходит порог или равно `null`
- **THEN** оба флага SHALL быть `false`, и отчёт SHALL назвать нарушившие сравнения.

### Requirement: Outputs are descriptive and cannot enter calibration or study paths

Отчёт SHALL иметь `kind` = `vast-service-profile-latency-model-v1`, SHALL NOT содержать поле `artifact_kind`, SHALL иметь флаги `qualification_eligible`, `q4_eligible`, `publication_eligible`, `full_run_eligible`, `canonical_study_complete` и `policy_calibration_eligible` равными `false` и метку «descriptive, not a policy formula». Отчёт SHALL записываться только exclusive create в новый путь с выводом size+SHA256 в stdout receipt. Policy calibration validator (`artifact_kind`/`schema_version` проверка) и finite-study closed-input binding loader SHALL отвергать отчёт. Инструмент SHALL NOT входить в runtime source allowlists, Dockerfile `COPY` или execution closures и SHALL NOT изменять policy formulas, calibration artifacts или K artifacts.

#### Scenario: Report is offered to calibration or study loaders
- **WHEN** отчёт подаётся policy calibration validator или finite-study closed-input binding loader
- **THEN** каждый SHALL отвергнуть его.

#### Scenario: Output path already exists
- **WHEN** путь отчёта уже существует или является symlink
- **THEN** инструмент SHALL завершиться ошибкой, не изменяя существующий файл.
