## Purpose

Описательный профиль обслуживания и проверенный предиктор очередей и латентности, построенные по закрытым данным finite component study, чтобы последующие study changes выбирали параметры заранее, без влияния на legacy campaigns, policy formulas и калибровку.

## ADDED Requirements

### Requirement: Inputs are provenance-bound closed study raw

Model SHALL читать только закрытый finite-study binding kind `finite-component-study-closed-inputs`, заданный абсолютным путём, ожидаемым `size_bytes` и SHA256, и каждый перечисленный в нём файл SHALL проверяться по `size_bytes`+SHA256 с held no-follow named epochs и повторной проверкой epochs после расчёта. Binding SHALL покрывать ровно 24 effect arms плана, прошедшего `validate_study_plan`. Чтение SHALL иметь собственный явно заданный analysis deadline и SHALL NOT называться независимой повторной редукцией (5.4) или использовать либо продлевать исходный campaign deadline. Исходные файлы SHALL оставаться неизменными; отчёт SHALL перечислять все прочитанные descriptors.

#### Scenario: Binding and raw match their identities
- **WHEN** binding и все его файлы совпадают по size+SHA256, epochs стабильны и план валиден
- **THEN** model SHALL построить профиль и предсказания, а отчёт SHALL содержать все descriptors, binding identity, analysis deadline и метку `new_descriptive_read_not_rereduction: true`.

#### Scenario: A file differs or is replaced
- **WHEN** любой файл отличается по size/SHA256, является symlink, меняет epoch во время чтения или binding содержит не 24 effect arms
- **THEN** model SHALL завершиться ошибкой без отчёта; частичный профиль SHALL NOT записываться.

### Requirement: Observed metrics come from the canonical reducer and match the archived reduction

Наблюдаемые значения (frame/branch partitions, controlled drops, completed latency distributions, Y100_frame, Y100_branch, route/native-client wait distributions) SHALL вычисляться существующей finite-study reduction над теми же decoded rows, без отдельной реализации. Для attempt K вычисленная reduction SHALL совпадать (JSON equality по полям arm reduction) с архивной `reduction` K; расхождение SHALL быть ошибкой.

#### Scenario: Recomputed observation equals the archive
- **WHEN** reducer над проверенными rows даёт ту же arm reduction, что архив K
- **THEN** отчёт SHALL использовать эти значения как observed и указать identity архивной reduction.

#### Scenario: Recomputed observation differs
- **WHEN** хотя бы одно поле arm reduction отличается от архива
- **THEN** model SHALL завершиться ошибкой и SHALL NOT сравнивать предсказания с неподтверждёнными observed значениями.

### Requirement: Service profile keeps components, joins and unknowns explicit

Для каждой arm и branch model SHALL публиковать распределения (count, p50, p95, p99, mean, CV) по completed branch requests: prefix delay (native path entry минус common admission, оба CLOCK_REALTIME одного host), route wait и route hold (одна bridge route запись, CLOCK_MONOTONIC одного PID), client overhead (native client residence минус bridge route residence, только как разность длительностей) и post-route residual. Worker backend и worker residence SHALL публиковаться отдельно и SHALL NOT называться чистым GPU kernel time. Записи SHALL соединяться только по точному `request_id`; отсутствующее соединение SHALL учитываться как `unknown` и SHALL NOT заполняться нулём или оценкой; повторный `request_id` в одной роли SHALL быть ошибкой. Вычитание абсолютных отметок разных процессов или разных clock domains SHALL NOT выполняться. Отрицательная длительность компонента SHALL быть ошибкой.

#### Scenario: Every completed request is joined
- **WHEN** каждая completed branch request имеет ровно одну native client, одну bridge route и одну worker запись с тем же `request_id`
- **THEN** профиль SHALL содержать все компоненты с count, равным числу completed branch requests этой arm/branch, и `unknown = 0`.

#### Scenario: A join is missing
- **WHEN** у completed request нет bridge route или worker записи
- **THEN** профиль SHALL увеличить `unknown` для этого компонента, исключить request только из распределения этого компонента и сохранить его в observed знаменателях.

#### Scenario: Duplicate or inconsistent request rows
- **WHEN** `request_id` повторяется в одной роли, порядок отметок внутри записи нарушен или компонент получается отрицательным
- **THEN** model SHALL завершиться ошибкой без отчёта.

### Requirement: Prediction is trace-driven over the frozen schedule with full denominators

Предиктор SHALL моделировать целевую arm по профилю calibration arm: планируемые admissions из frozen schedule плана (не наблюдаемые admissions целевой arm), 6 streams, 4 branch routes с одним FIFO-обслуживанием на route для всех streams, однослотовый буфер на пару stream×branch с drop-newest при заполнении, длительности компонентов — повторная выборка из empirical распределений calibration arm. Предиктор SHALL выполнять фиксированное число реплик (200) с seed 20260323 и публиковать среднее и 2.5/97.5 перцентили по репликам для: controlled-drop доли branches, completed frame latency p50/p95, Y100_frame над всеми planned frames measurement окна (frame on-time только когда все 4 branches завершены и максимум ≤ deadline плана). Модельные допущения (FIFO-порядок route, независимость выборок, prefix как чистая задержка без собственной очереди) SHALL перечисляться в отчёте. Неисполнимая модель (пустое распределение компонента в calibration arm) SHALL давать `prediction: null` с причиной, а не значение.

#### Scenario: Calibration arm has complete components
- **WHEN** у calibration arm все компоненты для 4 branches непусты
- **THEN** отчёт SHALL содержать предсказание целевой arm с репликационными интервалами, числом planned frames, равным observed `N_planned`, и списком допущений.

#### Scenario: Offered load exceeds route capacity
- **WHEN** средняя route hold на calibration профиле превышает интервал прихода на route
- **THEN** предиктор SHALL выдавать controlled drops и не completed frames по модели буфера; предсказанные значения SHALL NOT ограничиваться или исправляться под observed.

#### Scenario: A component distribution is empty
- **WHEN** у calibration arm нет ни одного наблюдения обязательного компонента для какого-либо branch
- **THEN** предсказание этой пары SHALL быть `null` с причиной, и gate, зависящий от неё, SHALL быть `false`.

### Requirement: Validation plan and usability gate are fixed in advance

Отчёт SHALL содержать: (a) in-sample consistency — каждая из 24 arms по собственному профилю; (b) out-of-sample load extrapolation — для одинаковых repeat/resource/topology calibration rate 1 → target rate 2 и rate 2 → rate 1; (c) cross-repeat — r1 ↔ r2 для одинаковых resource/topology/rate; для каждого сравнения observed, predicted и разность. Rate 0.25 SHALL участвовать только в (a) и (c) и SHALL сопровождаться сравнением route hold с rate 1 той же конфигурации, без вывода о причине различия. Флаг `ex_ante_parameter_use_permitted` SHALL быть `true` тогда и только тогда, когда для всех 8 GPU сравнений группы (b) предсказание не `null`, |ΔY100_frame| ≤ 0.05, |Δ controlled-drop доли branches| ≤ 0.05 и |Δ p50 completed frame latency| ≤ max(10 ms, 10 % observed). Пороги и состав группы SHALL NOT меняться после первого запуска на данных K без нового ревью спеки. CPU сравнения SHALL публиковаться без gate.

#### Scenario: All GPU load-extrapolation predictions are within thresholds
- **WHEN** все 8 GPU сравнений группы (b) укладываются в пороги
- **THEN** `ex_ante_parameter_use_permitted` SHALL быть `true`, и отчёт SHALL перечислять, какие профили (по rate 1 и 2) разрешены для ex-ante параметров последующих study changes.

#### Scenario: Any GPU load-extrapolation prediction fails
- **WHEN** хотя бы одно GPU сравнение группы (b) выходит за порог или равно `null`
- **THEN** `ex_ante_parameter_use_permitted` SHALL быть `false`, отчёт SHALL назвать нарушившие сравнения, и последующие study changes SHALL NOT выводить свои параметры из этой модели.

### Requirement: Outputs are descriptive and cannot enter legacy or policy paths

Отчёт SHALL иметь kind `vast-service-profile-latency-model-v1`, все флаги `qualification_eligible`, `q4_eligible`, `publication_eligible`, `full_run_eligible`, `canonical_study_complete` и `policy_calibration_eligible` равными `false`, и метку «descriptive, not a policy formula». Отчёт SHALL записываться только в новый, ранее не существовавший файл (exclusive create) с выводом его size+SHA256. Существующие policy calibration loaders, qualification/Q4/publication/full validators и finite-study driver SHALL отвергать этот kind. Инструмент SHALL NOT входить в runtime source allowlists, Dockerfile `COPY` или execution closures и SHALL NOT изменять policy formulas, calibration artifacts или K artifacts.

#### Scenario: Report is offered to a calibration or legacy consumer
- **WHEN** отчёт подаётся policy calibration loader либо qualification/Q4/publication/full entrypoint
- **THEN** consumer SHALL отвергнуть его по kind.

#### Scenario: Output path already exists
- **WHEN** путь отчёта уже существует или является symlink
- **THEN** инструмент SHALL завершиться ошибкой, не изменяя существующий файл.
