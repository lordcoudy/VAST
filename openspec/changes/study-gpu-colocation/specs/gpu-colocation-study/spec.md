## Purpose

Конечное GPU-only study, которое проверяет, превосходит ли консолидированное исполнение четырёх TensorRT engines в одном CUDA context исполнение в четырёх независимых CUDA contexts при batch 1, с тремя заранее собранными arms, заранее фиксированными параметрами и отказом legacy gates.

## ADDED Requirements

### Requirement: The study kind is new, finite and rejected by legacy gates

Study SHALL иметь kind `gpu-colocation-study`, отличный от `finite-component-study` и всех legacy kinds. Плановые, runtime, arm reduction, study reduction, closed-input binding и operations artifacts этого study SHALL иметь собственные kind значения с префиксом `gpu-colocation-study` и флаги `qualification_eligible`, `q4_eligible`, `publication_eligible`, `full_run_eligible` и `legacy_full_run_eligible`, равные `false`. Qualification, promotion, Q4, publication и full entrypoints/validators SHALL отвергать любой artifact этого kind тем же exact-kind/full-readiness путём, каким они отвергают `finite-component-study`. Validators `finite-component-study` (`validate_study_plan`, finite runtime plan, closed-input binding loader, reducer) SHALL отвергать artifacts нового kind, а validators нового kind SHALL отвергать artifacts `finite-component-study`. Legacy и finite-study validators, их counts, historical receipts, результаты attempt K и отчёт `service-profile-latency-model` SHALL оставаться неизменными. `canonical_study_complete` finite study SHALL NOT устанавливаться или меняться этим study; собственный флаг завершения нового study SHALL называться `gpu_colocation_study_complete`.

#### Scenario: A legacy full consumer receives a colocation artifact
- **WHEN** artifact kind `gpu-colocation-study*` подаётся qualification, promotion, Q4, publication или full validator
- **THEN** validator SHALL отвергнуть его, и никакой full/Q4/publication grant SHALL NOT возникать.

#### Scenario: Finite and colocation artifacts are crossed
- **WHEN** finite-study plan, runtime plan или binding подаётся validator нового kind, либо artifact нового kind подаётся finite-study validator
- **THEN** каждый validator SHALL отвергнуть чужой kind без частичной обработки.

#### Scenario: The colocation study completes
- **WHEN** все 24 arms нового study закрыты и редуцированы
- **THEN** `gpu_colocation_study_complete` SHALL быть `true`, а все eligibility флаги и `canonical_study_complete` finite study SHALL оставаться `false`/неизменными.

### Requirement: Workload, accounting and clock domains are those of the finite study

Study SHALL использовать без изменений derived stimulus, intake gates, 6 streams из 2 recordings, 4 frozen branches (`damage`, `foreign_object`, `plate_number`, `vehicle_type`), seed 20260323, deadline 100 ms, фазы 30/180/10 s (warmup/measurement/drain), exact scaled schedule, partition equations accounting, определения Y100_frame и Y100_branch с полным planned знаменателем, nearest-rank quantiles и доказательство общего CLOCK_MONOTONIC domain, как они заданы требованиями `finite-component-study` «Derived stimulus is bounded and independently decoded», «The exact offered schedule and full denominators are reconciled» и «Wait and backend observations retain actual clock domains». Analytics placement SHALL быть только GPU/TensorRT (policy `gpu_only`); любой decision с `selected_resource` ≠ `gpu` SHALL делать arm failed. Decoder placement, transport variant (final variant attempt K `branch-channel`), queue capacities, one in-flight на branch route и per-route lock bridge SHALL быть одинаковыми во всех arms. Те же 4 OpenVINO CPU workers, что и в attempt K, SHALL запускаться и оставаться без запросов во всех arms, чтобы `contexts4_default` воспроизводил условия GPU arms K; это SHALL NOT считаться причинным сравнением с K. MPS SHALL NOT использоваться: readiness каждого arm SHALL доказывать отсутствие MPS control daemon и MPS переменных окружения у всех participants, иначе arm SHALL NOT начинаться.

#### Scenario: Reused finite-study gates pass
- **WHEN** intake, schedule, accounting и clock-domain gates проходят так же, как в finite study
- **THEN** arm SHALL сохранять те же denominators и labels, а report SHALL называть workload искусственным systems proxy без accuracy или ordinary-camera capacity claim.

#### Scenario: A non-GPU decision or MPS presence is observed
- **WHEN** policy выбирает CPU для какого-либо request либо readiness обнаруживает MPS daemon/переменные
- **THEN** соответствующий arm SHALL быть failed (или SHALL NOT начинаться), без замены другим arm.

### Requirement: Three colocation arms are prespecified and prebuilt

Study SHALL иметь ровно три colocation arms, все реализованные, CI-tested и собранные в одном frozen source/image/binary до первой readiness кампании:

- `contexts4_default`: 4 TensorRT worker processes, по одному на branch, у каждого свой CUDA context, свой engine и один non-blocking CUDA stream с default priority; GPU делится default time-slicing драйвера.
- `context1_streams_priority`: один TensorRT worker process держит все 4 engines в одном CUDA context (primary context устройства этого process); каждый branch имеет свой execution context, свои device buffers и свой non-blocking CUDA stream с фиксированным приоритетом; requests разных branches могут исполняться на GPU одновременно.
- `context1_lanes`: тот же process и те же streams/приоритеты, что `context1_streams_priority`, плюс lane arbiter: GPU работа request (от начала H2D до завершения D2H) начинается только внутри окна своего branch, и в любой момент исполняется GPU работа не более одного request.

Во всех трёх arms SHALL совпадать: engine bytes и SHA256, устройство, batch 1, input/output tensors, host copy semantics (те же host buffers и тот же тип host памяти), worker protocol и capability каждого branch, число routes, one in-flight на branch route, per-route lock bridge, CUDA event instrumentation и source/image/binary одного frozen bundle. Arms SHALL отличаться только числом worker processes/CUDA contexts, приоритетами streams и наличием lane arbiter. Arm SHALL NOT использовать MPS, CUDA graphs, batch > 1, дополнительные streams на branch, pinned-memory изменения или иные изменения, не перечисленные здесь.

#### Scenario: Readiness confirms the context topology
- **WHEN** pool arm прошёл readiness
- **THEN** readiness record SHALL содержать actual container и process identity каждого GPU worker, сообщённую каждой engine session identity её CUDA context (4 различных context в 4 processes для `contexts4_default`; один context, общий для всех 4 sessions одного process, для `context1_*`), engine SHA256 каждого branch, actual stream priority range и назначенные приоритеты, а для `context1_lanes` — параметры arbiter; несоответствие SHALL делать arm failed до media. Список compute processes NVML SHALL записываться только описательно и SHALL быть `unknown`, если платформа (WSL2) его не предоставляет.

#### Scenario: Consolidated outputs differ from the accepted reference
- **WHEN** на parity inputs output какого-либо branch в любом arm не проходит принятый критерий model parity
- **THEN** readiness SHALL fail до кампании без поиска иной конфигурации или tolerance.

### Requirement: Every parameter is fixed in advance with documented provenance

Каждый параметр study SHALL быть зафиксирован в этом изменении до первого запуска и SHALL иметь в плане study поле provenance одного из видов `inherited_finite_study`, `first_principles` или `k_raw_archive`. Значения из отчётов, профилей или предсказаний `service-profile-latency-model` SHALL NOT использоваться, поскольку его `gpu_latency_profile_use_permitted` и `queueing_extrapolation_use_permitted` равны `false`; plan validator SHALL отвергать provenance с иным значением. Значения:

- Порядок branches для приоритетов и lanes: `foreign_object`, `damage`, `vehicle_type`, `plate_number` (`k_raw_archive`): убывание p50 per-branch completed latency, одинаковое во всех 12 GPU arms архивной редукции K (`study-results.original.json.gz`, 590982 B, SHA256 `c483d64fbb9ddac0127dcc93d8482cb0b409af0d35bb3870e1b2293181588d8b`, поле `reduction.arms.*.per_branch.*.latency_ms.p50`). Обоснование (`first_principles`): frame on-time требует завершения всех 4 branches, поэтому branch, который обычно завершается последним, получает первенство.
- Приоритеты streams в `context1_*`: при actual range `[greatest, least]` (`cudaDeviceGetStreamPriorityRange`, greatest численно меньше) branch ранга r ∈ {0,1,2,3} в указанном порядке получает `min(greatest + r, least)` (`first_principles`). Число различных уровней SHALL записываться; при менее чем 4 уровнях report SHALL указывать фактическое отображение без замены arm.
- Lane arbiter (`first_principles`): цикл 50 ms (deadline/2, чтобы ожидание своего окна не превышало половины deadline), 4 равных окна по 12.5 ms в указанном порядке; сетка циклов привязана к CLOCK_MONOTONIC моменту readiness pool и не сдвигается. Branch может начинать GPU работу своих requests последовательно, пока его окно открыто; начатая работа не прерывается; если работа предыдущего окна продолжается, окно начинается с её завершения, а если это завершение позже конца окна, окно этого цикла пропускается. Чужое окно SHALL NOT использоваться, даже если его branch не имеет запросов (non-work-conserving).
- Порог решения |ΔY100_frame| = 0.05 (`k_raw_archive`): ≈ 2.7 × наибольшей разности Y100_frame между repeat 1 и repeat 2 одинаковых GPU arms rate 1–2 в архиве K (0.0185, shared rate 2: 0.4074 против 0.3889).
- Rates 1 и 2 fps, deadline, фазы, seed, streams, branches, queue capacities, transport variant, policy `gpu_only` (`inherited_finite_study`).

#### Scenario: A parameter lacks allowed provenance
- **WHEN** plan содержит параметр без provenance либо со ссылкой на отчёт `service-profile-latency-model`
- **THEN** plan validator SHALL отвергнуть plan до любой readiness.

#### Scenario: The archive identity differs
- **WHEN** архив K, из которого документирован порядок branches, не совпадает по size или SHA256
- **THEN** plan SHALL NOT строиться; порядок SHALL NOT пересчитываться по иным данным.

### Requirement: The matrix is counterbalanced and executed once

Study SHALL исполнить ровно 2 rates × 2 topologies × 3 colocation arms × 2 repeats = 24 arms. Seed 20260323 SHALL определять сохранённый в plan до исполнения порядок 4 блоков (rate × topology) и порядок 3 arms внутри каждого блока для repeat 1; repeat 2 SHALL исполнять точное обращение всей последовательности repeat 1 (обращение AB/BA для трёх arms). Каждый arm SHALL запускать собственный свежий analytics pool (bridge/sidecar, 4 idle CPU workers и GPU workers вида этого arm) и собственные native processes, проходить readiness, исполнять 30/180/10 s и полностью завершать pool и native processes (все containers и processes завершены и reaped, sockets закрыты, pending recorder calls = 0) до readiness следующего arm; одинаковый жизненный цикл SHALL применяться ко всем arms, чтобы ни один arm не наследовал состояние GPU, caches или counters другого. Performance pilot, выбор конфигурации по наблюдениям, повтор arm, изменение порядка, rebuild, code edit или remote CI во время кампании SHALL NOT допускаться.

#### Scenario: All 24 arms finish in the stored order
- **WHEN** 24 arms исполнены в сохранённом порядке на одном bundle и проходят physical, operational и numerical checks
- **THEN** reducer SHALL публиковать per-arm результаты и 16 контрастов к `contexts4_default` (по 2 на каждую из 8 ячеек rate × topology × repeat) плюс 8 описательных контрастов `context1_lanes` − `context1_streams_priority`.

#### Scenario: An arm fails
- **WHEN** любой arm завершается integrity/infrastructure failure, timeout или cleanup uncertainty
- **THEN** кампания SHALL остановиться FAILED с сохранённым truthfully labelled partial raw, без автоматического retry и без заполнения недостающих arms.

### Requirement: The CUDA event interval around enqueueV3 is recorded with a truthful label

TensorRT backend SHALL записывать CUDA event на stream request непосредственно до и непосредственно после `enqueueV3` во всех arms и вычислять `enqueue_device_elapsed_ns` через `cudaEventElapsedTime`. Значение SHALL находиться внутри host CLOCK_MONOTONIC envelope от вызова `enqueueV3` до завершения synchronize; нарушение SHALL быть ошибкой request. Под kind `gpu-colocation-study` worker SHALL публиковать `enqueue_device_elapsed_ns` вместе с существующими H2D/D2H полями; под legacy и `finite-component-study` kinds response schema и все поля worker SHALL оставаться прежними. Report SHALL называть значение «stream-ordered device interval of the enqueued work; includes waiting behind other GPU work; not pure kernel time».

#### Scenario: An enqueue interval is published under the new kind
- **WHEN** request исполнен в arm нового kind
- **THEN** worker row SHALL содержать `enqueue_device_elapsed_ns`, и reducer SHALL публиковать его распределения per arm/branch с указанной меткой.

#### Scenario: A legacy or finite run uses the rebuilt backend
- **WHEN** worker запущен под legacy или `finite-component-study` kind
- **THEN** его response SHALL проходить прежний exact schema без нового поля.

### Requirement: gpu_queue_depth carries a real value only under the new kind

Под kind `gpu-colocation-study` native probe SHALL заполнять `gpu_queue_depth` policy request числом GPU analytics requests этого arm (все streams и branches), которые в момент чтения находятся на GPU routes bridge (ожидают или держат GPU route lock) и ещё не получили reply или failure; текущий request в это число не входит. Значение SHALL читаться из snapshot, который публикует единственный владелец счётчика (bridge), во время построения request и до отправки decide RPC; sequence snapshot, его CLOCK_MONOTONIC время публикации и CLOCK_MONOTONIC время чтения SHALL записываться в decision evidence, и время публикации SHALL NOT быть позже времени чтения. Неполное, разорванное или отсутствующее чтение SHALL делать request failed, а не 0. Под legacy и `finite-component-study` kinds `gpu_queue_depth` SHALL оставаться 0, и snapshot SHALL NOT читаться. Значение под новым kind SHALL NOT менять выбор resource (policy `gpu_only`), deadline или capacities и SHALL публиковаться только описательно.

#### Scenario: Decision under the new kind
- **WHEN** native probe строит policy request в arm `gpu-colocation-study`
- **THEN** `gpu_queue_depth` SHALL равняться прочитанному snapshot, а его sequence и времена SHALL присутствовать в evidence.

#### Scenario: Decision under a legacy or finite kind
- **WHEN** native probe работает под legacy или `finite-component-study` kind
- **THEN** `gpu_queue_depth` SHALL быть 0, как до этого изменения.

#### Scenario: Snapshot read fails
- **WHEN** snapshot отсутствует, разорван или его время публикации позже времени чтения
- **THEN** request SHALL быть failed с сохранённой причиной; 0 SHALL NOT подставляться.

### Requirement: Outcomes and the decision rule are fixed before execution

Primary outcome каждого arm SHALL быть Y100_frame по полному planned знаменателю. Для каждой из 8 ячеек (rate × topology × repeat) и каждого arm X ∈ {`context1_streams_priority`, `context1_lanes`} reducer SHALL вычислять ΔY100_frame = Y100_frame(X) − Y100_frame(`contexts4_default`) той же ячейки. Флаги SHALL определяться так:

- `<X>_beats_contexts4 = true` тогда и только тогда, когда все 8 Δ ≥ 0.05 и в каждой ячейке оба arms имеют полное accounting с `N_failed = 0` и `N_unknown = 0`;
- `<X>_worse_than_contexts4 = true` тогда и только тогда, когда все 8 Δ ≤ −0.05 при том же условии accounting;
- иначе исход X SHALL быть `inconclusive`;
- `consolidation_beats_contexts4_at_batch1 = true` тогда и только тогда, когда хотя бы один `<X>_beats_contexts4 = true`, с перечислением таких X.

Secondary outcomes SHALL публиковаться описательно: Y100_branch, completed frame и branch latency p50/p95/p99 с n, drops по причинам, распределения `enqueue_device_elapsed_ns`, H2D/D2H, worker residence, route wait, `gpu_queue_depth`, а для `context1_lanes` — число пропущенных окон и превышений окна с их длительностями. Пороги, флаги, состав ячеек и outcomes SHALL NOT меняться после первой readiness кампании без нового ревью спеки. Report SHALL NOT заявлять GPU utilization, energy, pure kernel time, причинность отдельных механизмов или выводы для batch > 1.

#### Scenario: Consolidation helps in every cell
- **WHEN** для X все 8 Δ ≥ 0.05 и accounting полон
- **THEN** `<X>_beats_contexts4` и `consolidation_beats_contexts4_at_batch1` SHALL быть `true`, а report SHALL называть ограничения: batch 1, один GPU, искусственный proxy.

#### Scenario: Mixed or small effects
- **WHEN** хотя бы одна Δ X лежит в (−0.05, 0.05) или знаки различаются по ячейкам
- **THEN** исход X SHALL быть `inconclusive`; пороги и ячейки SHALL NOT меняться posthoc, и такой исход SHALL считаться допустимым результатом.

### Requirement: Images, parity and pins are renewed for the new kind only

Изменения TensorRT backend/worker и native probe SHALL порождать новые runtime images с новыми source-set, dependency-set и build-context identities и новыми image IDs. До первой readiness SHALL быть выполнены: (a) для TensorRT worker — новый image (build registry, source allowlist), новый worker freeze receipt с source-set/dependency-set/build-context текущего build plan, новая запись analytics execution layer с image ID и worker implementation SHA256, model parity нового image для всех 4 branches в каждом из трёх arms против принятой reference (engines SHALL NOT пересобираться) и refreeze pins; (b) для native probe и GStreamer runtime — сборка в preparation этого study из pinned allowlisted source с проверкой source pins перед каждым arm, как в finite study, с обновлёнными allowlists; (c) обновлённый execution code closure; (d) проверка, что каждый исполняемый binary собран из текущего source (не старый compiled binary под новым source header). Новые pins и receipts SHALL быть отдельными файлами, привязанными к kind `gpu-colocation-study`; существующие pins, receipts, parity artifacts и все 227 сохраняемых образов SHALL оставаться неизменными, а удаление или offload любого образа SHALL требовать отдельного явного подтверждения пользователя. Повторный запуск legacy или finite kinds на новых bytes SHALL требовать их собственной renewal и не входит в это изменение.

#### Scenario: Renewal is complete
- **WHEN** новые images собраны, parity пройдена для всех branches во всех arms, freeze/refreeze pins, closure и allowlist обновлены и проверены на текущем source
- **THEN** readiness кампании MAY начинаться.

#### Scenario: A stale binary or pin is detected
- **WHEN** source отличается от собранного binary либо pin/receipt не соответствует actual image
- **THEN** readiness SHALL fail до любого arm; resealed старый receipt SHALL NOT заменять actual build/inspect.

### Requirement: Implementation is sequenced after the policy repair and repaired Q1

Код, тесты, Dockerfile, CI и image изменения этого study SHALL начинаться только после одновременного выполнения: спека этого изменения одобрена в его PR; изменение `fix-accepted-policy-preprocessing` (PR #9) слито в master; repaired Q1 (изменение `qualify-repaired-full-benchmark`) завершён и слит в master. До этого разрешены только документы этого изменения. Перед началом реализации ветка SHALL быть синхронизирована с master, и design SHALL быть сверен с фактическим кодом после merge; расхождение, затрагивающее требования, SHALL сначала проходить обновление спеки и повторное ревью.

#### Scenario: Implementation is requested before prerequisites land
- **WHEN** PR #9 или repaired Q1 ещё не слиты
- **THEN** реализация SHALL NOT начинаться, даже при одобренной спеке.

#### Scenario: Merged prerequisites change relevant code
- **WHEN** после merge PR #9 или repaired Q1 изменились seams, на которые опирается design
- **THEN** документы SHALL обновляться и повторно ревьюироваться до кода.

### Requirement: Budgets, single attempt and failure handling follow the finite study

Preparation attempt SHALL иметь непрерывный clock не более 14,400 s от первого source/tool hash, transfer, build или preflight до первой readiness кампании; кампания SHALL иметь отдельный непрерывный clock не более 14,400 s от первой readiness до редукции всех 24 arms и освобождения всех владельцев. Clocks SHALL NOT сбрасываться или приостанавливаться. Разрешена ровно одна preparation attempt и одна кампания; любая следующая attempt SHALL требовать явного решения человека. Bounded lifecycle, STOP/drain/abort, reap и raw reconciliation SHALL следовать требованию `finite-component-study` «Budgets, physical closure and raw reduction govern completion». Raw SHALL позволять независимую повторную редукцию.

#### Scenario: Campaign clock expires
- **WHEN** campaign clock истекает до редукции всех 24 arms
- **THEN** study SHALL быть FAILED с сохранённым partial raw, а `gpu_colocation_study_complete` SHALL быть `false`.

#### Scenario: Independent re-reduction
- **WHEN** reviewer повторно редуцирует закрытый raw
- **THEN** значения per-arm, контрастов и флагов SHALL совпадать с original reduction.
