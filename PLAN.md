<!-- CURRENT FULL CAMPAIGN 2026-10-07: qualify-full-benchmark -->
## Актуальный план — 7 октября 2026

**Текущий этап: подготовка к одной Q1, запуск ожидает отдельной команды пользователя.** [Draft PR #7](https://github.com/lordcoudy/VAST/pull/7), OpenSpec `qualify-full-benchmark`: **25/34** задач отмечено выполненными, 9 открыты. Execution commit **`1112af0b53cae995984708390cf9d04c18da3c0d`** (C_Q1), корень **`E:/STUDY/VAST/tmp/qfb-root-20261007a`**. Рабочие [planning artifacts и tasks](https://github.com/lordcoudy/VAST/blob/codex/qualify-full-benchmark/openspec/changes/qualify-full-benchmark/tasks.md) находятся в ветке `codex/qualify-full-benchmark`; master на `a54d0d99` не содержит текущую реализацию. Published head `53083fbe` добавляет только docs/evidence после C_Q1.

**Что подготовлено:** runtime clocks, full-consumer kind rejection и owner 37 операций; native3 A/B, worker2 input-hash equivalence, runtime ×4/refreeze; packaged checks 23/23; parity 480/32 с независимой сверкой A244; 99 pin sites; физическая integration-полоса 9/9; fresh checkout 164/164 при autocrlf true и false; исторические evidence g/A269 сохранены. [CI на C_Q1](https://github.com/lordcoudy/VAST/actions/runs/37584336063) SUCCESS. [CI документационного head `53083fbe`](https://github.com/lordcoudy/VAST/actions/runs/37591141619) завершён **SUCCESS**; ожидание hosted CI закрыто.

**До запуска Q1:**
1. **Docker readiness проверена: PASS, 11:48 МСК.** Q1 CLI `/usr/bin/docker` через канонический `/run/docker.sock` использует Docker Desktop **29.8.1** (`docker-desktop`); **10/10 pinned image IDs**, контейнеров 0, чужих VAST/CI processes 0, GPU compute jobs 0. Сохранён [read-only host report](C:/Users/s-a-balashov/.codex/worktrees/qualify-full-benchmark/VAST/openspec/changes/qualify-full-benchmark/evidence/physical-v1-host/pre-q1-ready-host-check.v1.json). Прежний Docker startup блокер снят; образы и пины не менялись.
2. **Ext4 skip закрыт как блокер.** Пользователь 7 октября, **11:40 МСК**, подтвердил: «ext4 skip is within approved skips». Набор 88 skip ID разрешён; результаты — 3 200 run / 3 112 success / 0 failures/errors. Исходный **successful=false** из-за отличия текста причины canonical venv bind сохраняется в evidence. Checklist 5.5/6.0 остаётся выполненным; повтор suite ради этого skip и изменение allowlist не требуются.
3. Предварительная host-проверка **PASS (11:48 МСК)**: C: ~90 GiB, E: ~337 GiB, WSL `/` и `/var/tmp` ~707 GiB; все выше 20 GiB. C_Q1, clean source, uid1000, Python3.12.3, receipt hashes и fresh Q1 namespaces подтверждены. **6.2 остаётся открытой:** после команды пользователя повторить текущие host checks и сохранить финальный stock report непосредственно перед Q1. AC sleep Never, AC hibernate 0, Windows Update paused до **26 октября, 15:01 МСК**. Работать от сети, не перезапускать WSL/Docker и не запускать параллельные builds/CI/GPU jobs.
4. Получить отдельную команду пользователя **«запускай Q1»**. До неё Q1 namespaces не создавать и шаги qualification не исполнять. Read-only проверка подтвердила C_Q1, source clean, Python3.12.3 и исходные hashes; весь runbook не запускался. Historical TODO о повторах 5.5–5.7 сверять с уже сохранёнными актуальными evidence.

**После разрешения:** выполнить [runbook](https://github.com/lordcoudy/VAST/blob/codex/qualify-full-benchmark/docs/full-qualification-runbook.md) по frozen [commands](https://github.com/lordcoudy/VAST/blob/codex/qualify-full-benchmark/docs/full-qualification-runbook-commands.sh): transaction/bootstrap → preprocessing → execution closure → capture plan → guardian8/8 → runtime inputs → owner (4 native prechecks, Savant, 32 cells) → authenticated stop → binding/cold closure37/37 и8 workers → policy/resource promotion. Одна попытка, ориентир **5–8 часов**. Любой ненулевой исход после начала Q1 — FAILED: сохранять originals, остановиться и запросить решение пользователя; автоматических повторов нет.

Затем 7.6 independent acceptance и conformance8.1 по каждому requirement/scenario; sync/archive8.2 **в том же PR**, commit/push, CI на последнем архивном commit, финальное ревью и отдельно разрешённый merge. Пока Q1 не принята, archive успешной qualification и promotion не заявляются.

**Следующие отдельные change/MR:**
- S3 migration: **S3 вместо Seafile — реализация и выгрузка проверены.** [PR #8](https://github.com/lordcoudy/VAST/pull/8), change `migrate-artifact-storage-to-s3`, software source `9bedfb14`. Новые publication exports используют `https://s3.savva-balashov.me` / `vast-archive` / `vast/`. Profile `vast-s3` хранится вне Git; приватный WSL credentials file доступен UID1000 (0700/0600), включая проверенный isolated user unit. Live smoke 7 октября, 14:31 МСК: PUT/multipart/reuse/две conditional collisions/full readback/restore — 7/7, 2 объекта, 0 leftover uploads. Первоначальный failed EOF report сохранён отдельно. Полный CI на `2f954a24`: 3170 executed / 3082 success / 88 audited skips, 0 failures/errors; ext4: 3165 executed / 3079 success / 86 audited skips, 0 failures/errors. Все шесть CPU builds и source-before/after прошли; обе WSL runtime проверки реально выполнены. Conformance покрывает 8 requirements / 23 scenarios, два review axes — 0 открытых findings. Основные specs синхронизированы, change архивирован; финальные archive-head CI/review проверяются на exact head в [PR #8](https://github.com/lordcoudy/VAST/pull/8). До их фактического завершения merge остаётся blocked. **S3 capacity/full launch blocked:** фактические accepted 280 Q4 sizing pairs отсутствуют. Оператор подтвердил **600 GiB = 644245094400 bytes** для VAST; UTC записи подтверждения `2026-10-07T12:17:31Z`, reference `operator-vast-archive-600GiB-20261007`. Exact guarantee сохранена отдельно от округлённых 1.9 TiB cluster free; sizing-bound attestation не создана. Canonical WSL user-manager bus остаётся отдельным full-launch prerequisite. Q1 не запускалась; её frozen source/config/receipts не перепривязаны к S3. В master эта реализация ещё не слита; код, архив и evidence находятся в S3 worktree/PR #8.
- Q4 + capacity: 560 A, identity/grant boundary, 560 B, 280 sizing pairs и датированная attestation точного destination. Использовать подтверждённые 600 GiB только пока guarantee актуальна (24h); после actual sizing проверить формулу и current preflight. Историческую Seafile гарантию не переносить.
- Full matrix: исправный persistent WSL user service (`systemctl --user` сейчас не подключается к bus), 5 600 accepted arms / 2 800 durable pairs, прежние workload/order/seed и `--max-unexpected-retries 0`, stock `verify → finalize → export`.

**Обслуживание C:** очищены pip/uv/npm download caches; фактический прирост при той очистке составил 16.5 GiB. На проверке 16:08 МСК свободно **74.23 GiB на C:** и **335.52 GiB на E:**. После успешного ext4 CI удалён только собственный временный checkout (~11 GiB); 51 original report/log/mount observations и проверенные hosted CI ZIP сохранены на E:. Guest space освобождён; физический VHDX не сжимался, WSL/Docker не останавливались. Docker images, canonical runtime, frozen Q1 roots, datasets/models и исходные evidence сохранены. 262 reviewed installer extractions (~38.9 GiB) из [списка](E:/STUDY/VAST/tmp/maintenance-20261007/temp-cleanup-candidates.json) сохранены: automatic approval review повторно отклонил удаление даже после прямого разрешения пользователя («blocked by policy»). Дополнительное пользовательское подтверждение не требуется.
<!-- END CURRENT FULL CAMPAIGN --><!-- CURRENT BENCHMARK RECOVERY 2026-10-04: run-finite-component-study -->
**Статус 2026-10-06 (после attempt K): исследование выполнено, 24/24 effect arms и 12/12 pairs.** По решению пользователя («Расследовать и сразу K») и amendment 11 выполнена ровно одна attempt K на `fefab7a93ab5e850ddcb90ac4c9d8eb351811fa0` (corrected-source CI [37463682987](https://github.com/lordcoudy/VAST/actions/runs/37463682987) SUCCESS). Preparation 454 s из 4 h (start 773940841836485 ns, boot dde50e69…, `timens-offsets:monotonic=0,0;boottime=0,0`): 442 AU на stream, active YUV и common-prefix RGB bit-exact, full442 actual EOS, offered-prefix STOP gate PASS. Campaign 8277,7 s из 14400 s: 4 initial pilots → trigger TRUE (shared native-client median wait 0,795 CPU / 0,501 GPU ≥0,10, n≥30) → единственный switch на prebuilt `branch-channel` после закрытия global-client pool → 4 conditional pilots (shared native-client wait ≈1e-6) → 24 effect arms в stored order → closure branch-channel pool → `canonical_study_complete=true`, `study_rc=0`. Во всех 24 arms raw reconciliation complete, unknown/failed/censored = 0, original close/infra errors = []. Независимая повторная редукция (5.4) по binding `closed-inputs.original.json` (31496 B, SHA256 `8f92bb40…05ba90`) с исходным campaign deadline (788794,93 s monotonic) завершилась rc=0 и совпала с исходной `reduction` (JSON equality). Описательно: CPU насыщен уже на rate 1 (≈50 % controlled drops, completed p50 ≈3,5 s) и на rate 2 (≈97 % drops); CPU Y100_frame = 0 на всех rates. GPU: на rates 1–2 Y100 shared−baseline = +0,17…+0,21 в обоих повторах, на 0,25 — 0 / +0,03. Ограничения: K — не первое наблюдение (pilot J запечатан и не смешан); два повтора дают описательные диапазоны без significance; qualification/Q4/publication/legacy full eligibility = false. [Evidence K](openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/physical-K-completed-v1/retention.original.json), [таблицы](openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/physical-K-completed-v1/results-tables.v1.md); raw 7,64 GB (3318 файлов, size+SHA256) хранятся в `/home/s-a-balashov/vffefab7aK`.

**Статус 2026-10-06 (после attempt J, историческое).** Исследование по заранее объявленному правилу — **FAILED**; дальнейшие попытки только с новым явным решением пользователя. История: D (SPS flag0), E (time-namespace proof), F (reference caps), G (material paths), rehearsals R1 (consumer FD JSON), R2 (STOP на границе окна), H (peer list clone в pool readiness), I (`threading` NameError в первом pilot) — все до первых данных; исправлены через amendments 1–10 с независимым ревью, R3 впервые прошла всю подготовку. Attempt J (`f299235e`, CI37449539530 SUCCESS): preparation и pool readiness прошли, **первый pilot (cpu/baseline) выполнен полностью** (arm, decode, reduce), второй pilot (cpu/shared) упал через ~127 с: sidecar `ProtocolError: failed to send analytics execution datagram: [Errno 32] Broken pipe` на маршруте foreign_object/cpu, native-клиент получил EOF («response missing or truncated»), канал отравлен, arm аварийно завершён; транспортный таймаут клиента 300 с не достигнут (max exchange ~1,3 с). Первопричина обрыва соединения не установлена. [Evidence J](openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/physical-J-failed-v1/retention.original.json); raw пилотов (274 MB) в `/home/s-a-balashov/vff299235J`. Effect arms: 0/24. Static gate undefined names теперь в CI.

**Статус 2026-10-05, corrected source E.** Amendment `bf9c5289` (x264 `force-cfr=1`) независимо рассмотрен: PASS_WITH_NOTES, blocking findings[] — [COMMENT5993674923](https://github.com/lordcoudy/VAST/pull/5#issuecomment-5993674923). Task2.6 encoder/SPS: genuine RED на старом рецепте (`ValueError: actual SPS/VUI is not frozen30fps/auto<=5.1`, как в D) → GREEN после одного токена; старый D trace/flag0/600fps/level52/missing поля по-прежнему отклоняются; CI ставит `ffmpeg`, тест не скипается. Source E `95a51ae54bcce49aab23381f79ebc12ca4d7ee9a`, corrected-source CI [37304552920](https://github.com/lordcoudy/VAST/actions/runs/37304552920). Новая exclusive namespace `vf95a51ae5` наследует ИСХОДНЫЙ preparation clock 671708114023685→686108114023685ns (boot dde50e69…, time:[4026531834]); failed D namespace сохранена. Запуск bootstrap+study — только после SUCCESS этого CI. Истечение clock = FAILED, без renewal. Accepted preparation/pilots/effects пока 0; задачи 3.1–6.2 открыты.

Текущая цель — полностью работающий и содержательный VAST benchmark: все 24 реальных запуска, 12 пар, независимый пересчёт исходных данных и критическая проверка выводов. Частичная матрица не завершает работу.

Рабочее изменение: `run-finite-component-study`, ветка `codex/run-finite-component-study`, [Draft PR5](https://github.com/lordcoudy/VAST/pull/5). Постановка рассмотрена на commit `3288b0702b6b0136feb6596382566b8686f9bb5c`; технический COMMENT5409655596 предшествовал коду. Пользователь явно разрешил автономную реализацию и доставку всех необходимых изменений. Это разрешение сохраняется; технические комментарии не выдаются за человеческий APPROVE.

Фактический прогресс — **9/24 задач**: закрыты постановка1.1–1.4 и software2.1–2.5;2.6 повторно открыта после real SPS failure. Full CI D и независимое acceptance исходных результатов завершены без блокеров. Bootstrap завершён за41.043469261s; stock study first preparation FAILED на actual fixed_frame_rate_flag0 до pilot. Готовится reviewed force-cfr=1 amendment; original4h clock не reset. Пилоты/effect arms и accepted physical preparation — **0**.

Текущий опубликованный source: `42725b4fc7b2e5c0cc71d79ea57a1f1fa48fef9a`. [Full CI37279566144](https://github.com/lordcoudy/VAST/actions/runs/37279566144): CPU111664198463 SUCCESS, host111664198751 SUCCESS; run completed08:12:41UTC. Actual originals:3110 discovered/3101 run/3013 successes/88 прежних skips/9 declared integration deferrals,0failures/errors/xFail/xPass/missing-required; sourcechanged[], raw checkout равен commit. Независимое source review v4 прошло без блокеров; technical COMMENT5411401634 привязан к этому commit. Все38 staged files совпали с raw Git blobs; проверка source/docs whitespace с сохранением CRLF прошла. Код не меняется во время этого CI.

Предыдущие full CI A/B/C завершились FAILED и сохранены с original logs, ZIPs, provider digests и CRC. В C:3101 tests run,3007 successes,88 skips,6 errors,0 failures. Причина оставшихся шести ошибок — fixtures pin текущий runtime SHA, но оставляли historical native SHA. Исправлены только helpers двух fixtures; production fragments/hashes/predicates, все8 прежних methods и78 assertions сохранены. Реальный RED2errors → focused GREEN2success/0errors/failures/skips. Расширенный local run с отсутствующими artifacts остаётся FAILED. Новый full CI дал3013 successes/88 прежних skips/9 declared integration deferrals; все6 residual methods действительно SUCCESS. Два остальных GST fixture methods сохраняют прежний declared integration disposition; все8 IDs сохранены. Original CPU/HOST logs и ZIPs retained с provider digests/CRC; независимое acceptance PASS_SOURCE_CI_ONLY закрыто:253 ZIP members/6665 Git blobs,3101 unique starts и terminals, native6+3, assets8 и observer24/24/24/EOF подтверждены.

Последовательность выполнения:

1. **Software gate,2.1–2.6.** Закрыто: full CI D SUCCESS и независимый PASS_SOURCE_CI_ONLY по original metadata/logs/ZIPs, raw Git/source before/after, test inventory, шести исправленным methods, native6+3, assets8 и observer closure. Receipt15195792 и original reader tools сохранены; первый FAILED reader остаётся FAILED, его лишнее требование пустого checkout исправлено только для четырёх progress docs. Следующее действие — физическая подготовка.
2. **Preparation,3.1–3.4.** Один исходный четырёхчасовой clock начинается до первого source/tool hash, переноса или build. Новый private Linux root `vf42725b4f` получает exact Git tree и полные original model/parity inputs; bootstrap и последующая команда `study` наследуют тот же start, boot и time namespace. Затем: два original AVI; ≤448 contiguous coded-AU context и442 original display ordinals; фиксированная нормализация, ровно четыре deterministic encodes; actual SPS/VUI, NVDEC YUV/RGB equality, full EOS и отдельный genuine offered-prefix STOP; selected builds с обеими prebuilt connection variants; восемь held workers, current material/placement/clock/readiness и допустимая calibration. Любой отказ сохраняется и блокирует pilot.
3. **Pilot,4.1–4.4.** Отдельный исходный четырёхчасовой campaign clock включает first readiness, pilots,24 arms, reduction и retirement. Сначала4 arms при1fps. Только prespecified median client-lock-wait/residence≥0.10 при n≥30 и полном raw accounting допускает один switch на заранее собранные branch channels, после закрытия прежнего pool, и ещё4 pilots. Иначе switch явно не применяется. Одна final variant используется во всей effect matrix.
4. **Effects,5.1–5.3.** Все24 arms/12 пар: CPU/GPU ×0.25/1/2fps ×baseline/shared ×два повтора. Обе топологии используют NVDEC; шесть logical streams являются пятью front-gate и одной underbody репликами двух записей, с четырьмя одинаковыми analytics branches. Seed20260323, frozen AB/BA order,30s warmup/180s measurement/10s drain;100ms от actual durable central admission. Во время campaign code/build/CI не меняются. Полностью согласовать planned→offered→admitted→delivered→четыре branch outcomes, original source/worker/native identities, idle/reset boundaries и owned closure. Unknown, missing, duplicate, foreign или infrastructure-failed raw не принимаются.
5. **Independent result,5.4 и6.1.** Повторно reduce все24 original arms/12 пар в пределах исходного campaign deadline. Сверить с driver result, actual source/material/process closure и всеми7 requirements/20 scenarios+двумя R1 scenarios. Y100 имеет denominator всех planned frames; source punctuality считается отдельно. Missing latency не становится нулём. Полный отрицательный performance result допустим. После данных заново критически проверить выбранную архитектуру и прежние предположения.
6. **Delivery,6.2.** Supported sync/archive в той же ветке/PR/change; сохранить не затронутые main requirements, commit/push archive. Затем CI последнего commit, final review и authorized merge. Эти финальные gates фиксируются отдельным release ledger; scientific campaign не повторяется ради документации.

[Tasks](openspec/changes/archive/2026-10-06-run-finite-component-study/tasks.md), [runbook](docs/finite-component-study-runbook.md), [validation](openspec/changes/archive/2026-10-06-run-finite-component-study/implementation-validation.md) и [conformance](openspec/changes/archive/2026-10-06-run-finite-component-study/conformance.md) содержат подробные критерии и original evidence. Bootstrap реально CLOSEDexit0 за41.043469261s, receipt0fd1e154; исходный start671708114023685ns/bootdde50e69-39bf-45bd-bdb7-bc33c9adcb0b/time:[4026531834] передан stock study. Selected deterministic builds завершились, но physical preparation FAILED на SPS flag0; failed receipt/75 originals retained,30 named PIDs сейчас отсутствуют без group/globalclaim. Amendment review→real encoder test-first fix→corrected-source CI→новая namespace под тем же original prepclock. Technical COMMENT5411962964 фиксирует independent exact-D source/CI gate.

PR4 decoder-preflight уже слит как `a1b76a63ac7aa08a34a32cc2f0b177e4b45891ee` с final CI SUCCESS. Его128 AU/64 пары и прежние component результаты сохраняют отдельный scope. Qualification/Q4/publication/full eligibility не выдаются новым finite study. История ниже сохранена побайтно.
<!-- END CURRENT BENCHMARK RECOVERY 2026-10-04 -->


## Фактический этап — 4 октября 2026

Offline CLI реализован: 35 tests passed, 0 skips; два замечания reviewer воспроизведены RED и исправлены. Все четыре original CPU08/GPU02 directories обработаны однократно, каждый CLI exit0. Все 20 исходных файлов (109 802 522 bytes) сохранили SHA256 и семь полей named/held identity. Benchmark/engine/model не повторялись.

[Четырёх-arm отчёт](docs/latency-diagnostics-20261004/four-arm-report.md) показывает исходные counts/drops/100ms misses и критический путь всех 3 325 completed frames. GPU per-frame decoder share p50 — 93,23% / 91,94%; это residence envelope. True queue wait, pure inference и NVDEC busy остаются unknown.

Научная сверка и conformance 4/12 завершены без блокеров. CI реализации A 2a75b470 прошёл: 2 939 successes, 88 точных разрешённых skips, ноль failures/errors; hardware acceptance false. Все девять задач выполнены; спецификация синхронизирована и change архивирован 4 октября. Финальные CI/review/merge архивного коммита фиксируются в [PR3](https://github.com/lordcoudy/VAST/pull/3) после фактического выполнения. [Задачи текущего изменения](openspec/changes/archive/2026-10-04-explain-benchmark-latency/tasks.md) задают фактический статус. Все PR2 gates уже закрыты.

Следующий научный шаг — отдельно рассмотренный decoder/intake preflight по реальной setup ошибке attempt05; identity correction ещё не реализована. Полный путь остаётся неизменным: три stale sibling runtime renewals (native3/worker2 source совпали), patch-bound parity, original owner/binding для 37 producing operations, 32 qualification cells, Q4 560+560 / 280 sizing, capacity, 5 600 accepted arms / 2 800 durable pairs. Они не исполнены; full eligibility false.

## Предыдущая постановка текущего этапа

# Актуальный план VAST — 4 октября 2026

PR [#2](https://github.com/lordcoudy/VAST/pull/2) завершён и слит: merge `c07de9c78e3beaaf276ee54b5f414a3a4b5d035c`, 3 октября, 19:18:11 МСК. Измеренный источник — B `a00aa57f`; исправления CI — D `3c025b29`; финальный проверенный архивный commit — E2 `1f44b9f9`. Это разные источники, их результаты не перепривязаны.

## Выполнено и проверено

- [x] Настоящие CPU08 и GPU02: четыре GStreamer baseline/shared arms, cold validation, штатная остановка guardian и освобождение резервов.
- [x] Независимая обработка всех четырёх arms; 1 080 admissions на arm, без censoring. CPU завершил 516/664 frames, GPU — 1 070/1 075. Дедлайн 100 мс выполнен 0/0 и 3/1 раз соответственно.
- [x] Hosted E2 CI: 2 904 successes, 88 разрешённых skips, ноль failures/errors, шесть native builds и три обязательных native regressions. Независимый ext4 D: 2 906/86, ноль failures/errors.
- [x] Conformance 20 requirements/118 scenarios, sync/archive, окончательное ревью, снятие Draft и merge. Все пять process gates 18.13/18.14/22.3/23.5/24.4 закрыты в фактическом ledger PR2. В архиве оставлен исходный снимок до этих действий.
- [x] Временный owned runtime bind D снят после закрытия consumers; глобальный runtime и измеренный ext4 checkout сохранены.

## Ближайшие задачи: explain-benchmark-latency

Пользователь поручил проверить и выполнить следующий необходимый этап автономно. [Задачи текущего изменения](openspec/changes/archive/2026-10-04-explain-benchmark-latency/tasks.md) — источник статуса реализации; после archive ссылка переносится в архив.

1. Проверить текущие статусы и сохранить исторические исходники документов.
2. Реализовать небольшой offline CLI для критического пути по сохранённым frame events и доступным native policy timings. Отдельно показывать decoder envelope, остаток пути, frame/branch drops и observation gaps.
3. Проверить parser и расчёты на положительных/отрицательных случаях; выполнить анализ всех четырёх реальных arms и независимое научное ревью. Нулевые queue spans в promoted CSV не означают отсутствие ожидания: истинные queue wait/worker service из этих данных отдельно не измерены.
4. Обновить воспроизводимый runbook, проверить соответствие спеки, обязательный CI, archive и окончательное ревью в одном новом PR.

## Оставшийся полный объём

Он не завершён компонентными результатами и не удалён из плана:

- Технический долг: прямые отрицательные проверки всех full consumers (R13/S6), четыре ручных conformance checks, девять физических интеграций; причина исходного CPU07 EPIPE остаётся неизвестной.
- Научный этап: изучить фактические decoder/pacing/queue envelopes; causal correction, изменение intake/corpus/deadline или сравнительные performance claims требуют отдельного контролируемого эксперимента и ревью.
- Full qualification: свежие допустимые all-backend inputs/images/parity/operational identities, четыре native pre-checks, все 32 cells, остановка guardian и stock promotion. Старые A269 partial cells и component authority не дают такого допуска.
- Q4: 560 операций A, граница identities/grants, 560 B, 280 sizing pairs и фактическая датированная storage-capacity attestation.
- Full run: ровно 5 600 accepted arms/2 800 verified durable pairs, прежние workload/order/seed, zero unexpected retries и stock verify → finalize → export.

Полные qualification/Q4/publication/full eligibility остаются false. Новые запуски возможны только после их реальных prerequisites; уже принятые arms не повторяются ради обновления документов. Практический действующий entry point: [component runbook](docs/gstreamer-component-benchmark-runbook.md).

## Исторический план

Ниже сохранён весь прежний документ. Его датированные статусы описывают прошлые попытки; текущий статус и очередность заданы выше.

# Подготовка и запуск полной матрицы VAST

> Статус сверён 21 сентября 2026 в 10:21 UTC. A269 failed после 8/32 cells: guardian exit78 (analytics execution memfd SHA-256 differs from the contract), затем pilot exit1 (savant_endpoint_socket_identity_changed); verifier/promotion также exit1. Все original identities сохранены, MainPID=0, Restart=no. 8 historical DeepStream proofs проверены по 176 descriptors / 141 физическому файлу; qualification не принята. Причина memfd mismatch ещё не установлена. Перезапуск и promotion не выполнялись; Q4/full matrix не запущены. A268 suite/A261 images/A262 parity и предыдущие prerequisites сохранены. Полный объём: все32qualificationcells; Q4 560A+identity/grantboundary+560B+280sizingpairs; 5600acceptedarms/2800verifiedSeafilepairs; verify -> finalize -> export. Seafile capacity question без ответа; publication_ready=false. [Failure evidence](artifacts/publication_qualification_runtime_v1_20260921_attempt269/failed-state-check-20260921/failure-analysis.json). Исходные требования ниже сохранены.

## Исходный снимок перед выполнением (6 сентября 2026)
> Текущая безопасная процедура подготовки описана в [docs/benchmark-preparation-runbook.md](docs/benchmark-preparation-runbook.md). Она не меняет исходные numbered obligations ниже и не разрешает запуск полной матрицы.


Методика матрицы согласована: **5 600 запусков / 2 800 пар**, фиксированные параметры, парное сравнение, воспроизводимый порядок и корректная обработка отрицательных результатов. Следующий снимок описывает условия до начала выполнения; актуальный статус приведён выше и в progress.md.

На момент исходной проверки `progress.md` отставал от следующих результатов:

- A131/A132 завершены; актуальная привязка образов и паритета подтверждена.
- [A133 завершён успешно](E:/STUDY/VAST/artifacts/full_suite_ext4_20260906_attempt133/result.json): 2 421 тест, 87 прежних пропусков. Текущие исходники и фикстуры совпадают с проверенными хешами.
- Входы, preprocessing и execution closure A134 готовы. Guardian, runtime bundles, видеодиагностика Savant и 32 пилота ещё не выполнены.
- На **C: свободно 0 байт**; на E: около 327 ГиБ. Активных контейнеров и процессов бенчмарка нет.

Эти исходные условия потребовали очистки C: и двух эксплуатационных исправлений. Они уже выполнены; доказательства и оставшиеся этапы перечислены в progress.md. Разделы ниже сохраняют исходные требования плана и критерии полного завершения.

## 1. Очистка и восстановление окружения

Применить выбранную политику: удалить тяжёлые устаревшие данные, сохранив компактные логи, хеши, receipts и причины отказов.

- Составить перечень удаления с абсолютными путями, размерами и проверкой зависимостей. Сохранить data/models, действующий runtime, A131–A134 и необходимые исторические фикстуры, перечисленные в A133. Старые каталоги не удалять только по номеру попытки.
- Основные кандидаты: зеркало qualification attempt41 — **46,74 ГБ**; старые `vt*`, `vq66g` и временный Python; две устаревшие копии worker image примерно по **10,49 ГБ**; дубли транскодирования примерно **17,9 ГБ**; явно относящиеся к VAST/Docker временные файлы Windows — около **1 ГБ**.
- Перед рекурсивным удалением размонтировать вложенные bind mounts и проверить их отсутствие. Иначе удаление старого тестового зеркала может затронуть настоящие данные.
- Docker очищать выборочно. Реально освобождаемый build cache составляет около **1,86 ГБ**, а не весь показанный объём кэша. Сохранить используемые образы и базовые слои, включая необходимые образы без тегов.
- Выполнить trim, согласованную остановку Docker Desktop и WSL, затем сжатие Ubuntu `ext4.vhdx` и Docker `docker_data.vhdx`. Их текущие размеры — **390,68 и 118,47 ГиБ**; фактическое освобождение измерить после операции. Сжатие выполнять только при отключённых виртуальных дисках. [Требование Microsoft](https://learn.microsoft.com/en-us/powershell/module/hyper-v/optimize-vhd?view=windowsserver2025-ps).
- Восстановить Docker, WSL и три canonical mount штатными helpers; проверить доступность GPU, образы и сохранённые зависимости. Оставить `memory=24GB`.

## 2. Два ограниченных исправления

**Контроль диска.** Сейчас свободное место проверяется однократно и только на диске результатов.

- Добавить необязательный `RunnerCallbacks.before_pair`, проверяющий место перед началом каждой новой пары.
- Проверять файловые системы результатов, фактического scratch/temp и `/mnt/c`, где размещены WSL/Docker.
- Использовать существующий минимум 20 ГиБ на каждом необходимом томе; считать его эксплуатационным порогом, не доказанной оценкой пикового потребления.
- При недостатке места возвращать временную остановку `75`. Восстановление уже принятой пары, которой осталось завершить выгрузку и очистку, должно проходить и через entrypoint/service preflight.

**Seafile readback.** Изолированно воспроизведено: тайм-аут, сброс соединения и `IncompleteRead` ошибочно превращаются в постоянную ошибку целостности.

- Классифицировать эти транспортные исключения как `ArtifactStoreError`, допускающий продолжение через `75`.
- Завершённое чтение с неверным размером или SHA оставить постоянной ошибкой `78`.
- Сохранить порядок: upload → readback → receipt/ledger → удаление локальных raw.

Форматы результатов и параметры эксперимента сохраняются. Эти host-модули не входят в образы или execution closure A134: **пересборка A131, повтор паритета A132 и повтор готовых входных транзакций A134 не нужны**.

## 3. Ограниченная проверка перед допуском

- Добавить регрессии: C: заполнен при свободном E:; место заканчивается между парами; новая пара не запускается; принятая пара восстанавливает offload без повторного измерения.
- Проверить три транспортных сбоя Seafile, сохранение постоянного отказа при неверных SHA/размере и отсутствие повторного исполнения принятых запусков.
- После обеих правок выполнить **один итоговый полный ext4 suite**, проверить пропуски и совпадение исходников до/после. Новый результат потребуется именно из-за изменения кода.
- Создать отсутствующий A134 `operations.py` с фактическими receipts и новым тестовым допуском; обновить ссылку на этот допуск в диагностике A135.
- Выполнить canonical-проверки, запустить guardian с подтверждением 8/8 workers, материализовать 32 runtime bundles.
- Выполнить **одну видеодиагностику Savant A135**. При отказе сохранить доказательства и установить причину; повтор без исправления или новых оснований запрещён.

## 4. Полный запуск и критерии результата

После успешной диагностики:

1. Выполнить все 32 квалификационные ячейки, штатно остановить guardian, проверить lifecycle и завершить policy/resource qualification.
2. Запустить guardian принятой конфигурации; выполнить Q4: 560 запусков фазы A, необходимые identity/grants, 560 запусков фазы B и 280 sizing pairs.
3. Связать гарантию облачного объёма пользователя с полученным sizing через штатную operator attestation. Использовать существующие ссылки Seafile; проверка quota API и создание новой структуры облака не требуются.
4. Завершить проверки identities и canonical `plan/preflight`; запустить полную матрицу через постоянный WSL user service с `--max-unexpected-retries 0`.
5. Подтвердить работающий процесс и первую принятую, выгруженную пару. Возобновлять тот же checkpoint; `78` останавливает выполнение, транспортный `75` допускает продолжение.

Матрицу сохранить полностью: 4 системы × 2 кодека × 2 топологии × 7 политик × 5 дедлайнов × 10 повторов; 6 потоков, seed `20260323`, прогрев 30 секунд и измерение 180 секунд.

Минимальная длительность измерительных окон вместе с Q4 и пилотами — **около 16,4 суток**, дополнительно потребуются запуск процессов, финализация и выгрузка. Полное завершение подтверждается 5 600 принятыми запусками, 2 800 проверенными облачными парами и успешными `verify → finalize → export`.
