# Задержки четырёх исходных arms — 4 октября 2026

Новый offline CLI успешно разобрал все четыре оригинальных CPU08/GPU02 arms. Бенчмарк не повторялся: анализ прочитал 20 сохранённых файлов, 109 802 522 байта. Полные SHA256 и семь полей file identity совпали до и после анализа; все удержанные leaf handles закрыты. Это проверка диагностического чтения, а не новая cold acceptance или hardware attestation.

Измерения остаются на источнике B `a00aa57f7d9534f8e7920f14f70d6a75a23570ed`; их финальная repository closure — PR2, merge `c07de9c78e3beaaf276ee54b5f414a3a4b5d035c`. Анализатор имеет отдельный SHA256 `4023c5846098a2055961fed2899038eeb2317854a6bd89ba4142c682ffd260b4`. Его независимое source review закрыло два найденных замечания после настоящего RED; финальные 35 тестов проходят без skips. [Исходные terminal facts](original-cli-execution-v1/invocation-terminal.v1.json), [source review](source-independent-review.v2.json), [независимый исходный расчёт](raw-independent-review/calculation.v2.json).

Независимая сверка новых выходов завершена без блокеров: совпали все 3 325 критических кадров, 59 291 stage rows и 15 522 native branch paths. [Полный review](raw-independent-review/cli-output-independent-review.v1.json), SHA256 `ce2a0adaf8bb82d90f06f2338443124a69e19358f5214965cae076ff9d858de7`, подтверждает численные результаты и ограничения этого отчёта; меняется только прежний статус ожидания. Conformance 4/12 и обязательный CI реализации A 2a75b470 завершены: 2 939 successes/88 точных разрешённых skips, ноль failures/errors; hardware acceptance false. Все девять задач выполнены, spec sync/archive завершены 4 октября; последующие финальные checks/review/merge архивного коммита записываются в [PR3](https://github.com/lordcoudy/VAST/pull/3) по факту.

## Реальные популяции и задержки

В каждом arm ровно 1 080 admissions, censoring отсутствует. Квантили относятся только к полностью завершённым frames; dropped frames остаются отдельной популяцией.

- **CPU baseline:** completed 516, dropped 564; branch drops 764. Дедлайн 100 мс выполнили 0 frames. E2E p50/p95 — 5 727,5 / 9 713,25 мс. Критический decoder prefix p50 — 2 071,5 мс; остаток до frame join p50 — 3 113 мс. Последняя ветка всех 516 completed frames — `foreign_object`.
- **CPU shared:** completed 664, dropped 416; branch drops 949. Дедлайн выполнили 0 frames. E2E p50/p95 — 3 621 / 8 026,85 мс. Decoder prefix p50 — 1 237,5 мс; остаток p50 — 1 926 мс. Критическая ветка меняется между frames.
- **GPU baseline:** completed 1 070, dropped 10; branch drops 25. Дедлайн выполнили 3 frames. E2E p50/p95 — 2 127 / 6 301 мс. Decoder prefix p50 — 2 010 мс; остаток p50 — 120 мс. Медиана доли decoder prefix в E2E каждого completed frame — 93,23%.
- **GPU shared:** completed 1 075, dropped 5; branch drops 20. Дедлайн выполнил 1 frame. E2E p50/p95 — 2 168 / 6 364 мс. Decoder prefix p50 — 2 006 мс; остаток p50 — 152 мс. Медиана доли decoder prefix — 91,94%.

Для каждого из 3 325 completed frames анализ выбирает последнюю required postprocess branch; при равенстве — лексикографически большую. Baseline использует decoder этой ветки, shared — общий decoder. `prefix = decode_end − ingress`, `residual = frame_egress − decode_end`, `prefix + residual = original E2E` проверено отдельно для каждого frame. Aggregate join может завершаться позднее последней ветки. **Складывать приведённые медианы prefix и residual нельзя:** это разные marginal quantiles, а не разложение одного медианного frame.

Попарно совпадают все 1 080 admissions по stream/frame/input. Но CPU имеет только 464 общих completed inputs, 52 baseline-only и 200 shared-only; GPU — 1 070 общих и ещё 5 shared-only. Меньшая CPU медиана shared сама по себе не доказывает причинный speedup: популяции завершённых frames различаются. Есть только одна baseline-first пара на каждый ресурс и два исходных recording, размноженных в шесть logical streams.

## Что измерено, а что неизвестно

Все 59 291 promoted stage rows записывают одинаковые queue-enter и stage-start timestamps. Источник задаёт start временем завершения прямого parent, затем копирует его в queue-enter (`checkpoint_publication_runtime.py:908,931–932`). Нулевой записанный span не означает нулевое реальное ожидание. Stage spans показывают parent-to-completion envelopes. Истинные queue wait, pure inference service и NVDEC busy time в новых JSON явно `null` с причиной.

Native policy-path evidence сопоставлено отдельно для всех 15 522 completed measurement branches, включая успешные branches dropped frames: 3 556 / 3 371 / 4 295 / 4 300 по arms. Path entry → terminal включает подготовку, transport, map/hash, client/route waits и execution. Исходный `actual_service_ms` также описывает этот envelope; допустимое расхождение отдельно сериализованных floats ограничено 0,001 мс. Это не чистое время модели. Native terminal может предшествовать postprocess; CSV comparison сохраняет исходную миллисекундную точность.

GPU наблюдение локализует основную задержку **до decode completion**, но не доказывает её внутреннюю причину. Decoder/display reordering и paced encoded input — проверяемые гипотезы. На CPU после decode остаются секунды. Source review обнаруживает сериализацию native client и per-route inference; имеющиеся timestamps не разделяют их вклад причинно.

Оба CPU/GPU analytics режима используют NVDEC. Intake остаётся 1 fps на logical stream / 6 fps суммарно, H.264, timestamp scale 600 из encoded 600 fps timeline, seed 20260323, 30 с warmup + 180 с measurement + 10 с drain, deadline 100 мс. Partial overlapping `C_obs` не становится CPU work, NVDEC busy или energy. Accuracy, population inference и causal shared-decoder superiority не заявлены.

## Следующие необходимые шаги

Текущие conformance, CI реализации и независимая численная сверка завершены; spec sync/archive выполнены. Финальные repository transitions остаются зафиксированными отдельно в PR3. Следующий научный шаг — контролируемый decoder/intake preflight с настоящими packet/decoded-frame clocks. Original attempt05 закончился до первого AU на сравнении библиотечного FD/name device 77 с VMA backing device 2112 при одинаковом inode. [Разбор setup failure](decoder-attempt05-setup-review.v1.json) предлагает separately reviewed held-FD mmap identity bridge; исправление ещё не реализовано. Различие совместимо с [OverlayFS identity semantics](https://docs.kernel.org/filesystems/overlayfs.html), однако конкретный storage driver исходные записи не устанавливают.

Новый preflight должен сохранить исходные четыре default/zero display-delay runs, по 32 original paced AUs, их order, caps, ownership и failure evidence. Сначала проверяется identity correction на чистых regression fixtures и отдельном metadata-only preflight; затем допускается independently reviewed fresh research attempt. Автоматический retry, inode-only waiver, новые capabilities и scientific adoption не разрешаются этим отчётом. Изменение corpus, cadence, decoder, deadlines или метрик требует отдельной рассмотренной постановки и проверенного эксперимента.

Полный publication маршрут остаётся отдельным обязательством: renew три stale DeepStream/GVA/Savant runtime closures; native3/worker2 и selected GStreamer source closures совпали и не требуют rebuild только из-за исходников. Нужно наблюдать реальные image identities, получить patch-bound parity через действующий путь, обеспечить original owner/binding для 37 producing operations через штатные runtime runners, затем принять 32 qualification cells. Только далее — Q4 560 A + identity/grant boundary + 560 B / 280 sizing pairs, фактическая capacity attestation, 5 600 accepted arms / 2 800 durable pairs и stock verify → finalize → export. [Source-only карта команд и prerequisites](raw-independent-review/full-route.source-facts.v2.json) фиксирует конкретные ограничения; она не является execution grant. Все full eligibility/counts остаются false/unexecuted.

## Пересмотр собственного подхода

Главная коррекция — перестать считать успешный запуск или множество receipts объяснением результата. Оперируемость, выполненный deadline и причинное преимущество — разные утверждения. Текущий experiment исполняется и даёт отрицательный SLO результат; объяснение должно сохранить его потери и неудобные числа.

Я бы не начинал большой campaign ради заполнения матрицы, пока декодирование поглощает почти всю GPU задержку, а нулевой queue span создан самим promotion. Минимальный полезный путь — локализовать интервал по существующим данным, проверить конкретный setup blocker и провести малый контролируемый decoder experiment. Большая перестройка runtime или scheduler пока не обоснована измерениями.

Независимый reviewer нашёл в новом анализаторе две ошибки после первоначально зелёных тестов. Их реальные RED failures и отдельный исправленный GREEN сохранены. Это причина проверять исходные populations и raw joins независимо от собственного parser, а не принимать зелёный тест или красивую сводку за доказательство.
