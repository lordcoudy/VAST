<!-- CURRENT BENCHMARK RECOVERY 2026-10-04: fix-decoder-preflight -->
# Актуальный план и прогресс — 4 октября 2026

Общая цель: работоспособный и осмысленный benchmark, с воспроизводимым запуском, объяснимыми метриками, потерями и ограничениями. Диагностический PR3 завершён и слит в 1ab80035c30f6a4f78d2b1aa7be4743288c3721d; задача продолжается в [Draft PR4](https://github.com/lordcoudy/VAST/pull/4), изменение **fix-decoder-preflight**, ветка codex/fix-decoder-preflight.

Фактический прогресс текущих задач: **20/33** до уточнения плановых документов. P1 3aa35c3b2eedc05d22cf16ba37d470143d080f6b рассмотрен до кода. S2 503b33b224b8f98b429d9a9cf80a0cf30402fcba прошёл CI37204647176: 3039 executed = 2951 success + 88 audited skips; 9 deferred integrations отдельно, root12/nested150 успешны, шесть native builds и три required regressions подтверждены. S1 CI FAILED сохранён. Fresh ext4 S2 и окончательная проверка 24 физических входов/источников закрыты. [Задачи](C:/Users/s-a-balashov/.codex/worktrees/decoder-preflight-v6/VAST/openspec/changes/fix-decoder-preflight/tasks.md) задают проверяемое поведение, а не обещания будущего успеха.

Один оригинальный metadata-only запуск выполнен: actual exec8ab2d5/wait210954, exit0. Guest/controller/external закрылись, source/AU/run count0, result null; штатное удаление собственного контейнера подтверждено. Независимый cold read197ebe/fcda64 завершился **FAILED**: целиком сравнивались шестипольная identity controller и восьмипольная identity external capture. Все шесть основных фактов совпадают; внешние group/session нужны для containment и сохраняются. Отказ, оригиналы и отсутствие записанных процессов/групп проверены independently. Metadata eligibility пока false; research0. [Разбор исходного отказа](C:/Users/s-a-balashov/.codex/worktrees/decoder-preflight-v6/VAST/docs/decoder-preflight-20261004/cold-result-independent-review.v1.json).

Дальнейшие задачи в порядке зависимостей:

1. Уточнить четыре существующих OpenSpec документа в том же PR: строгий join шести основных полей и отдельная проверка внешних group/session; самостоятельная версия исправленного observer при неизменном producer S2/P1. Закоммитить плановый P2 и пройти независимое ревью точного commit до кода.
2. Исправить reader и добавить реальную совместимость форматов 6/8 полей с отрицательными случаями. Проверить canonical suite и hosted CI новой версии. Повторно проверить те же закрытые metadata оригиналы исправленным source-pinned observer в новом exclusive отчёте; исходный FAILED не перезаписывать и metadata не повторять.
3. Только после принятия metadata отдельно проверить условия допуска и выполнить один неизменный four×32-AU research запуск. Независимо восстановить raw данные, пары, PTS, RGB и timing; частичный/отрицательный результат сохранить без повторов и без научного продвижения.
4. Завершить conformance, runbook, sync/archive, latest-head CI, финальное ревью и merge в PR4.
5. Пересмотреть канонический маршрут benchmark отдельной рассмотренной спецификацией: небольшой ограниченный capacity/intake experiment с сопоставимыми inputs, counterbalanced pairs, потерями, latency и throughput. Измерить ожидание client/route locks до изменения каналов; учесть confound coded600fps/media pacing. Явно определить, какие старые тяжёлые кампании заменяются новым маршрутом, сохранив их unexecuted историю.
6. Выполнить новый маршрут до воспроизводимого end-to-end результата и независимо проверить выводы. В конце пересмотреть исходные предположения и достаточность проверки реальных стыков компонентов.

Отрицательный100ms результат PR2 не означает отказ запуска. Full32/Q4/5600 arms, девять physical integrations, qualification/publication остаются unexecuted/false; этот снимок не даёт их допуска. Dirty primary и вся история ниже сохранены. Реализация ведётся в отдельном managed worktree.
<!-- END CURRENT BENCHMARK RECOVERY 2026-10-04 -->
