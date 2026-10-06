## Purpose

Define a finite, reproducible selected baseline/shared systems study with honest workload, loss, latency, wait and physical-closure evidence, while preserving strict legacy campaign authority and historical results.

## ADDED Requirements

### Requirement: Canonical scope is finite and distinct from legacy campaigns

Study SHALL исследовать selected GStreamer/H.264 baseline/shared systems proxy на6 streams из2 recordings и4 frozen analytics branches, с CPU/OpenVINO и GPU/TensorRT analytics placement. Оно SHALL сохранять seed 20260323,100ms deadline и30/180/10s phases. Report SHALL различать proxy models/objects и accuracy, analytics placement и decoder placement, stream replicates и независимые scenes. Study kind SHALL NOT удовлетворять qualification/Q4/publication/full gates. Historical receipts, original 72/82 register и unexecuted false/zero counts SHALL сохраняться.

#### Scenario: Canonical matrix completes
- **WHEN** все24 prescribed effect arms на одном final bundle и12 pairs проходят physical, operational и numerical checks
- **THEN** report SHALL разрешать только canonical study completion и actual 24/12 counts; legacy campaign execution/eligibility SHALL оставаться неизменными и false/zero там, где они исторически не исполнялись.

#### Scenario: Pilot or partial result exists
- **WHEN** завершились metadata,4/8pilot arms или неполный effect matrix
- **THEN** canonical completion SHALL быть false; report SHALL назвать actual completed/failed/missing arms без замены недостающих historical outputs.

#### Scenario: A legacy full consumer receives a study kind
- **WHEN** study artifact поступает qualification, promotion, Q4, publication или full entrypoint
- **THEN** прежний exact-kind/full-readiness validator SHALL отвергать его; canonical scope SHALL NOT выдавать новый full grant.

### Requirement: Derived stimulus is bounded and independently decoded

Study SHALL использовать новые inputs из первых442 decoder presentation ordinals0..441 **original AVI** каждого clip. Parent hash/decoded ordinal/observed source timestamp и derived ordinal/PTS SHALL сохраняться раздельно; proprietary camera-clock alignment и442 уникальных pixel values SHALL NOT подразумеваться. Source decode SHALL быть ограничен448 contiguous coded AUs от original start плюс initialization, без seek/loop/hidden pre-roll; actual sufficiency SHALL проверяться. Context outputs после441 SHALL NOT попадать в encoder/analytics offers. Normalized CFR600 prefix SHALL NOT подменять original AVI ordinal domain. Original AVI и historical normalized media SHALL оставаться byte-identical.

Только actual frozen front `yuv420p`8-bit1920×1080 и underbody `yuvj422p`8-bit1700×236 SHALL быть допустимыми parents. Before encode pinned FFmpeg6.1.1/libswscale SHALL выполнять fixed normalization без geometry resize: front limited709/left assumptions при unspecified metadata; underbody observed full601(bt470bg)/center422 через два явно заданных scale contexts с bounded BGR24 intermediate. Оба contexts SHALL иметь bilinear+accurate_rnd+bitexact/threads1, input chroma underbody=(128,0) и output left420=(0,128) в luma-grid/256; front input=(0,128). Actual decoded input tuple, source ordinals, recipe и normalized active plane identities SHALL сохраняться; иной input/format/depth/negotiated tuple SHALL давать refusal. Output SHALL быть8-bit420 limited709/left; primaries/transfer709 SHALL оставаться declared derived interpretation без original color-accuracy claim. Pre-encode conversion SHALL NOT называться packing-only; bounded BGR intermediate SHALL NOT называться RGB source/resizing. Flags alone SHALL NOT доказывать conversion.

Каждая derivative SHALL иметь ровно442 actual all-I/no-B pictures, новые byte/recipe/software-tool/dependency identities, fixed nominal encoded30/1 и encoder timebase1/30, MP4 tracktimescale600 с packet PTS=DTS20*i ticks/duration20ticks (i/30s и1/30s), origin0. 600 SHALL быть container timescale only; actual SPS/PPS/VUI30fps/profile/level<=5.1/current hardware support/inventory SHALL проверяться, включая actual vui_parameters_present_flag=timing_info_present_flag=fixed_frame_rate_flag=1 и time_scale=60*num_units_in_tick при positive tick; frozen x264 recipe SHALL явно задавать force-cfr=1 вместе с FFmpeg CFR output, x264 level SHALL оставаться auto без blind lower-level relabel или compatibility claim. Ровно два identical encodes на recording (четыре всего) одной frozen recipe SHALL требовать exact byte determinism внутри preparation budget, без parameter search. Fixed derived limited BT709 matrix/primaries/transfer и mpeg2(left) chroma reinterpretation SHALL быть согласованы encoder VUI и actual native/reference caps; original color/accuracy SHALL NOT заявляться. Independent software decode **производной** SHALL дать exact active YUV420 planes; native NV12 packing-only normalization SHALL совпасть bit-exact. Reference/native SHALL использовать один и тот же pinned Gst NV12→RGB converter/config/caps; во всех трёх reference modes (media, independent nv12, transport STOP) reference NV12 caps SHALL наблюдаться на actual sink pad pinned converter (после pinned NV12 capsfilter), а RGB caps — на actual output; из fixed actual caps SHALL удаляться только GStreamer default `multiview-mode=mono` и `multiview-flags=0:ffffffff` (flags0/full mask, может отсутствовать), после чего SHALL требоваться structural equality (`gst_caps_is_equal`, field-order independent) с pinned prefix caps; per frame SHALL записываться pinned canonical text только при этой equality и SHA256 actual negotiated caps text, а сам actual text — в retained native stderr; decoder caps до filter SHALL NOT быть acceptance input; любое другое поле/значение SHALL отклоняться; output full-range/RGB-matrix/BT709-transfer/BT709-primaries/original dimensions/30fps и exact active RGB comparison, без subjective/posthoc tolerance или lossy parent-pixel equality. Actual WSL software toolchain availability/pins SHALL быть proven до encode; historical executable hashes SHALL NOT сообщаться как current WSL proof. Flags/property/metadata success SHALL NOT заменять actual decode/EOS/reference checks. Для study decoder default/unset SHALL быть provisional engineering choice по dated accepted S3 research/S8 cold; final current setting binding SHALL требовать actual all-I derived YUV/RGB/EOS parity gate до pilot; original FAILED cold/prefixes SHALL сохраняться, posthoc favourable pilot/effect setting selection SHALL NOT допускаться.

#### Scenario: Actual derived intake satisfies the gate
- **WHEN** каждый bounded original context действительно даёт selected AVI display ordinals0..441 с fixed actual-parent normalization/plane identities, обе derivatives имеют442 all-I/no-B pictures, exact timeline/VUI и strict software-YUV/native-YUV/same-converter-RGB совпадение
- **THEN** frozen study input SHALL сохранять original/derived mapping, новые identities, actual context и exact offered subset; report SHALL назвать artificial systems proxy без original color/accuracy/clock или parent→derived lossless claims.

#### Scenario: A flag hides an incompatible actual stream
- **WHEN**448-AU context не даёт442 selected original display outputs либо actual parent/normalization tuple/planes или derived stream/VUI/layout/timeline/pixels не соответствует fixed policy, несмотря на корректные-looking flags
- **THEN** preparation SHALL fail before pilot без увеличения448/442, смены source domain, поиска удобной decoder setting/tolerance или выдачи normalized-prefix/metadata success за acceptance.

#### Scenario: V6 does not establish a usable setting
- **WHEN** immutable accepted S3 research/S8 cold evidence не привязано к будущему study input либо actual derived YUV/RGB/EOS gate не подтверждает provisional default/unset
- **THEN** dependent pilot SHALL NOT start; metadata rc0 SHALL NOT сообщаться как research/decode acceptance.

### Requirement: The exact offered schedule and full denominators are reconciled

Study plan SHALL содержать nominal 0.25/1/2fps, exact scaled AU timeline и finite expected slots/key/payload/measurement membership до исполнения. Legacy600/1/600 validator SHALL оставаться строгим; новый study kind SHALL явно разрешать 120/30/15 scales над actual20/600s duration и запретить source cycle. Source evidence SHALL различать planned, actual offered, durable central source admission/parent acceptance, ACK, fanout enqueue, actual per-consumer delivery и native consumption. Accepted accounting SHALL использовать planned=not_offered+offered; offered=not_admitted+admitted; admitted=delivery_failed+delivered; delivered=complete+controlled_dropped+censored+failed. Admitted SHALL означать original common source/control admission anchor; delivered SHALL требовать actual receive/successful joined transport для всех required recipients, не queued status. Early failed/unknown prefix SHALL NOT сообщаться как complete или controlled censor. Central source admission SHALL сохранять original key/common admission clock до ACK/fanout; её SHALL NOT выдавать за delivery либо стирать при failed/partial delivery. Baseline четыре consumer recipients и shared один recipient на stream SHALL иметь отдельные expected/delivered/failed outcomes, связанные с тем же central key. Queued SHALL NOT означать delivered. Typed study context SHALL выводить finite admission/frame/operation bounds из validated study plan и передавать их native/source accounting, recorder producer и cold validators; legacy241/281 admissions,999999600ns schedule guard, frame_id280 и exact2/37 operation scopes SHALL оставаться неизменными для legacy kinds. Drain SHALL не создавать новых slots. Integer timebase/1ms boundary, late/catch-up offers и context SHALL не исчезать из denominator. Frame и branch populations SHALL публиковаться раздельно. Primary admission-anchored Y100_frame SHALL использовать весь planned frame denominator и только actual fully completed frames со всеми4 branches<=100ms от validated actual common admission; partial frame SHALL NOT считаться полностью completed. Source-lateness и actual offered/admitted rates SHALL публиковаться отдельно; admission-SLO SHALL NOT называться scheduled-slot SLO или доказательством punctual nominal cadence.

#### Scenario: Timebase rounding changes the boundary population
- **WHEN** actual AU durations дают boundary frame вне frozen measurement membership или отличается номинальное число frames
- **THEN** reducer SHALL использовать exact frozen schedule и raw classifications, а не заранее придуманное180/360 или округление к ожидаемому count.

#### Scenario: A slot is missing, late or not admitted
- **WHEN** planned opportunity не offered, предложена поздно, не delivered или not admitted
- **THEN** report SHALL сохранять её в N_planned и показывать source outcome/lateness; missing/not-delivered/not-admitted slot SHALL NOT получать выдуманное zero latency или completed/on-time status. Late offered slot с настоящими native completions SHALL сохранять независимые late-source и actual completion/admission-SLO признаки, без claim scheduled-slot SLO.

#### Scenario: Raw accounting is incomplete
- **WHEN** duplicate/foreign key, missing terminal, ACK/delivery mismatch или source/native/guardian inconsistency нарушает partition equations
- **THEN** arm/reduction SHALL fail; queue overflow и infrastructure exception SHALL NOT превращаться в controlled drop.

### Requirement: Counterbalanced effects use a fair immutable final bundle

Effect study SHALL выполнить ровно CPU/GPU×3 rates×2 repeats×baseline/shared=24 arms/12 pairs. Seed20260323 SHALL определять explicit stored resource/rate block order; repeat1 SHALL использовать AB, repeat2 reverse blocks/BA. Внутри каждой пары SHALL совпадать derived bytes/keys/pacing, decoder/model/preprocessing/worker images/devices/threads и queue/deadline/collector policy. Оба arms SHALL использовать один outer container/coordinator и те же8 analytics workers; baseline24 native consumer processes/clients против shared6 —declared topology effect. Global-client label SHALL означать process-local client, объединяющий4 branches одного shared stream, не общий client всех6 streams; backend/per-route contention SHALL сохраняться и в baseline. One in-flight на branch/resource worker SHALL сохраняться. Actual readiness/reset/idle/counter deltas и owner closure SHALL проверяться между arms без implicit cache-reset claim. Held variant pool SHALL сохранять cumulative counters и predeclared arm/route bindings; between-arm boundary SHALL требовать connections_active=0, started=completed+failed, pending recorder calls=0, предыдущие native owners retired и no failure, а новый arm SHALL использовать deltas, не stop()/restart либо стирание lifetime counters.

#### Scenario: Both repetitions finish on the final bundle
- **WHEN** valid 24 arms имеют prescribed order и одинаковые current bindings
- **THEN** reducer SHALL публиковать12 paired descriptive effects и per-rate/resource/repeat outcomes; common-completed subset SHALL быть secondary с явным denominator.

#### Scenario: One pair changes a bound input or execution policy
- **WHEN** bytes, source/image/binary/model identity, queue, worker capacity, order или timing policy различаются внутри пары
- **THEN** paired comparison SHALL fail; historical arm и best pilot SHALL NOT заполнять её missing member.

#### Scenario: All three rates give an unhelpful performance curve
- **WHEN** все rates saturated/unsaturated или Y100 низкий
- **THEN** truthful valid negative matrix SHALL оставаться admissible; knee/speedup SHALL не объявляться и rate grid SHALL не изменяться posthoc.

### Requirement: Wait and backend observations retain actual clock domains

Native client SHALL записывать actual lock attempt/acquisition/reply-or-failure/release self-interval и identity; bridge SHALL записывать actual route lock wait/self-residence; selected existing worker clocks SHALL сохраняться с request/worker identity. Worker received SHALL обозначать accepted/verified после memfd check. Report SHALL не приписывать backend interval pure kernel time и SHALL не вычитать cross-process endpoints без фактического общего clock domain. Общий CLOCK_MONOTONIC domain SHALL доказываться одинаковым actual `/proc/sys/kernel/random/boot_id` и actual `/proc/<pid>/timens_offsets` каждого participant (driver, native helpers, runtime, все8 workers) с monotonic и boottime offsets ровно `0 0`, причём actual `/proc/<pid>/ns/time` и `/proc/<pid>/ns/time_for_children` того же process SHALL совпадать (offsets file описывает time_for_children); inode `/proc/<pid>/ns/time` SHALL сохраняться только descriptively, потому что container runtime может создавать отдельный zero-offset time namespace на каждый container. Missing/unreadable/malformed offsets, расхождение time и time_for_children, любой nonzero offset или foreign boot SHALL отклоняться до media/output. Missing queue observations SHALL оставаться unknown, без constructed enter=start promotion.

#### Scenario: Same-domain timing is complete
- **WHEN** actual native/bridge/worker observations имеют свои owner/domain и ordered endpoints
- **THEN** reducer SHALL вычислять только поддерживаемые self-intervals/distributions и overlapping residence limits, без utilization/energy или additive-work claim.

#### Scenario: Containers have distinct zero-offset time namespaces
- **WHEN** driver, native helpers и workers имеют одинаковый boot_id, разные time namespace inodes, у каждого process ns/time==ns/time_for_children и actual monotonic/boottime offsets `0 0`
- **THEN** они SHALL считаться одним CLOCK_MONOTONIC domain; nonzero, missing или malformed offsets, time≠time_for_children, foreign boot или отсутствие proof SHALL оставаться refusal/unknown, без вычитания endpoints.

#### Scenario: A worker interval or queue estimate is mislabeled
- **WHEN** received occurred after verify, backend includes mapping/copies или queue events отсутствуют
- **THEN** report SHALL сохранять truthful labels/unknown и SHALL NOT называть их wire ingress, pure service/GPU kernel time или measured queue wait.

### Requirement: Pilot selects only a prespecified prebuilt configuration

Pilot SHALL состоять из4 arms при1fps; обе process-local global-client/branch-channel конфигурации SHALL быть реализованы, CI-tested и реально собраны в одном frozen source/image/binary до first pilot, с real two-route peer overlap/same-route serial/failure/close tests и current selected checks. Отдельные connected channels SHALL подтверждаться actual simultaneously in-flight different-route requests и запретом second same-route request до первого terminal; dup/concurrent recv общегоFD или simulated success SHALL NOT заменять этот gate. Extra4 SHALL допускаться только после единственного prespecified switch к этой prebuilt branch config. Trigger SHALL требовать valid accounting/no integrity failure, не менее30 finite native client observations и median(client_wait/client_residence)>=0.10 у shared CPU или GPU arm. Unknown/failure SHALL не быть trigger evidence. Switch SHALL сохранять one-in-flight per route/worker и resource symmetry, retire прежний pool и выполнить current config readiness. Active campaign SHALL NOT редактировать code, rebuild или запускать remoteCI. Final24 SHALL использовать один final variant; оба pilots SHALL сохраняться отдельно.

#### Scenario: Pilot does not meet the trigger
- **WHEN** median<0.10 или finite population не позволяет доказать threshold
- **THEN** driver SHALL сохранять current transport variant и truthful unknown limits; SHALL NOT добавлять channels по предположению о speedup.

#### Scenario: Pilot meets the trigger
- **WHEN** valid observed threshold выполнен и заранее проверенная branch config проходит actual switch/readiness/close checks
- **THEN** разрешены ровно4 additional pilot arms и один final frozen variant до matrix; extra worker/in-flight/capacity/deadline SHALL NOT вводиться.

#### Scenario: Pilot or correction fails
- **WHEN** integrity/infra failure, timeout, cleanup uncertainty или второй switch/неподготовленная correction понадобится
- **THEN** campaign SHALL stop failed/partial без automaticretry, favourable fallback pilot или pilot-as24 acceptance.

### Requirement: Budgets, physical closure and raw reduction govern completion

Каждая owned preparation attempt SHALL не превышать14,400s от первого physical source/tool hash/transfer/build/derived/preflight этой attempt; новая attempt со своим clock SHALL допускаться только до first pilot readiness, после retained FAILED/expired предыдущей attempt, independently reviewed source-explained pre-pilot defect, corrected exact-source CI и новой exclusive namespace; после D/E разрешены attempts F, G, H, каждая только после своего reviewed amendment, и по явным решениям человека от 2026-10-06 ровно одна attempt I (amendment9) и после её провала ровно одна attempt J (amendment10) — явно согласованное человеком исключение из правила «новая attempt только до first pilot readiness», поскольку I упала в первом pilot до первого кадра без performance observation; после провала J (один полный pilot уже выполнен, его raw запечатан) по решению человека ровно одна attempt K (amendment11), с явной пометкой в отчёте, что K не является первым наблюдением; любые дальнейшие attempts или rehearsals SHALL NOT допускаться без нового явного решения человека, а провал I, J или K в любой точке, включая после pilots, SHALL фиксироваться как FAILED study с сохранённым truthfully labelled partial raw; preparation attempts до pilot SHALL проходить без performance observation и без перебора configurations; каждая attempt SHALL включать original AVI/context/four encodes/reference/CI/build обеих configs/current readiness и завершаться до first pilot. Перед последней attempt допускаются не более трёх non-accepted prepare-only diagnostic rehearsals (stock `prepare`, R1–R3), каждый после reviewed fix предыдущего дефекта, в отдельной scratch namespace со своим clock; attempt H SHALL начинаться только после rehearsal с closed successful `study-plan.original.json` на том же source; rehearsal SHALL NOT считаться attempt, его outputs SHALL NOT переиспользоваться, run/pool/calibration/pilot/effects SHALL NOT запускаться, а его original outputs SHALL сохраняться как evidence до attempt H. Затем campaign SHALL иметь один непрерывный14,400s clock от first pilot readiness до all24 raw reduction/final retirement; possible prebuilt-config switch/readiness и extra4pilot SHALL расходовать только этот remaining campaign budget. Clocks SHALL NOT reset/pause; active campaign SHALL NOT выполнять code edits/rebuild/remoteCI. Existing standalone/native clocks SHALL не повышаться. Raw membership/hash/held epochs/current engine/image/model/source и mandatory cold/container/guardian/resource checks SHALL сохраняться в reusable existing seams. Storage/read caps SHALL быть fixed до запуска. One terminal run manifest SHALL сохранять actual schedule/results/bindings/failure и bounded outputs без новой authority hierarchy.

Native analytics и policy client (decide/path_ack/terminal_ack), а также owned source transport SHALL быть bounded исходными applicable absolute request/phase/lifecycle deadlines: client `MSG_DONTWAIT`/readiness poll, positive-progress pipe/ACK/partial-frame read/write и mutex admission учитывают один deadline без reset на fragment/readiness/EINTR/EAGAIN. Ordinary STOP SHALL сначала latch stop-offers/admission без ожидания admission/exchange mutex и разрешать already admitted work только в ORIGINAL remaining10s drain; normal STOP SHALL NOT превращать in-flight keys в failed/cancelled или начинать новый request/cleanup clock. Fatal error/drain expiry SHALL публиковать abort без этих mutex **до GST_NULL/joins**. Client lock acquisition SHALL использовать bounded timed/try-lock polling по тому же original deadline/abort и после acquisition повторно проверять stop/abort/eligibility original admitted key до RPC. FD close/reuse —только после actual callback/thread retirement. Runtime SHALL выполнить bounded actual wait/reap после KILL authentic owned children в одном remaining cleanup clock, попытаться retire остальные ресурсы и сохранить first failure/cleanup errors. Policy client SHALL использовать ORIGINAL native START/window/drain applicable absolute deadline и тот же stop/abort lifecycle; новый300s или policy100ms RPC deadline SHALL NOT вводиться. Никакие новые workers/queues/threads, увеличенные clocks, detach или successful cancellation/censor SHALL NOT вводиться; unresolved keys SHALL оставаться unknown/FAILED. Existing outer containment SHALL NOT доказывать normal completion.

До pilot SHALL пройти meaningful real-I/O RED/GREEN gates: genuine analytics seqpacket no-reply, silent policy-ACK peer, live source ACK peer, actual full pipe/partial header/body и **software-GStreamer real streaming callback teardown**; контроль original-clock failure до fixture peer release, actual owned FD/stream/child retirement и первичной ошибки. Primitive transport/mocked Gst success/global process absence SHALL NOT заменять эти joins. Реальные fault gates и минимальные соответствующие source fixes входят тот же reviewed canonical change/existing native/runtime/tests; отдельная wrapper/authority hierarchy SHALL NOT создаваться.

#### Scenario: Execution and reduction finish truthfully
- **WHEN** все24actual arms/12 pairs numerical reconciliation, existing physical checks, original owners/streams/FD retirement, currentCI и conformance проходят до deadline
- **THEN** completion SHALL отражать actual end-to-end matrix, planned-frame Y100_frame, separate branch yield и nearest-rank fully-completed frame critical-branch/per-branch p50/p95/p99 с раздельными n/undefined; raw evidence SHALL позволять независимый re-reduction.

#### Scenario: A deadline, cap or final close fails
- **WHEN** globalclock или clock текущей preparation attempt истёк, cap/namespace нарушен или final cleanup неизвестен
- **THEN** successful body/provisional terminal SHALL NOT давать completion; partial raw/failure и unknown unfinished keys сохраняются, bounded failed containment SHALL не добавлять scientific time или заменять authentic post-KILL wait/reap.

#### Scenario: Current source and executable do not match
- **WHEN** source header changed, но selected runtime использует старый compiled native binary, либо изменённый current source/image/model binding не renewed
- **THEN** readiness SHALL fail before dependent arm; source label/tag/resealed oldreceipt SHALL NOT заменять actual build/inspect/current validation.
