# V6 decoder: preparation и независимое чтение закрытого результата

## Текущий этап — 5 октября 2026

OpenSpec change `fix-decoder-preflight`, Draft [PR4](https://github.com/lordcoudy/VAST/pull/4). Immutable producer S3 однажды завершил четыре run32. S8 `470120a3b3f9692775656cdb8114471ab991f14b` прошёл независимый source review, один canonical root12/nested171 и latest hosted CI37249161136: 3040 selected, 2952 successes, 88 audited skips, zero failures/errors, все шесть native builds и три required regressions. Одна corrected cold-проверка закрытых S3 originals завершилась с rc0 за 42.715633661 с: `operation_completed`, `raw_join_complete` и `research_complete` true, 128 AU и 64 paired observations. Все 223 holds released, FD6→6, close errors пусты, late companion отсутствует. **Independent cold review PASS в scoped original research 4×32/128 AU/64 pairs** (review28578/e394e9fd; technical COMMENT5409320401); исходные `accepted:false`, `provisional_until_owner_final_close:true` и `publication_ready:false` сохранены. Этот guide описывает маршрут и состоявшиеся commands, а не разрешает новую операцию.

Исходный producer и проверяющий reader имеют **разные** source/repository bindings. Исправление reader не ретаргетит старую попытку. P1 `3aa35c3b2eedc05d22cf16ba37d470143d080f6b` остаётся original producer planning commit; последующие P2–P8 reviews расширяют только согласованные исправления. Фактические отказы и их причины разобраны в [decoder diagnosis](../../../docs/decoder-preflight-20261004/decoder-diagnosis.md).

## Что запускается и что остаётся проверкой файлов

Controller требует `--project-root`, `--review-repository-root`, lowercase40-hex `--source-commit`, явный `--mode metadata-only|research` и fresh `--output-dir`. Guest получает тот же mode в sealed plan и argv. Нет default mode, resume или retry. Physical root содержит исходные input/evidence; ordinary Linux ext4 review checkout содержит рассматриваемый source commit. Held runtime files сверяются с raw Git blobs. Позднейшие task-progress/archive документы могут отличаться от P1, поэтому original четыре raw P1 blobs читаются именно из P1, а не подменяются текущими tasks.

`metadata-only` выполняет packaged registry/GI/plugin/library/ABI preflight, но не создаёт source, AU, run directory или decoder pipeline. Его terminal имеет resultnull, runs_completed0 и research_completefalse. S3 metadata и независимый cold уже приняты в этом zero-AU scope. Это не допускает автоматический переход к research.

`research` выполняет только front_gate/default → front_gate/zero → underbody/zero → underbody/default, по32 AU. Source cadence, transport scale600, cohorts и ограничения сохраняются. Whole600s, shared prelaunch120s, run120s, startup45s, drain10s и cleanup15s — существующие абсолютные clocks; fast exit не отменяет final checks. Исходные metadata/research namespaces S2 и S3 уже заняты. Их producer commands приведены в original tool records и не являются рецептами повтора.

Cold reader — self-contained stdlib проверка закрытых original files; он не импортирует producer/GI/model и не запускает Docker/source/decoder. Он проверяет namespace members, declared source/P/observer identity, original tool returns, held FD/full SHA/seven epochs/ancestors, ABI backings и, в research, packet/ACK/causal/PTS/pixel/caps/cohort joins. Mapping backing identity не означает независимой проверки всех mapped memory bytes; unavailable unselected bytes остаются unknown.

## Проверка fixtures

Canonical host — CPython3.12.3 с `-I -B`. Disposable fixtures и их originals размещаются на native ext4: DrvFS может не позволить rename открытого файла и исчерпать фиксированный budget. Для самостоятельной CPU fixture проверки задайте **новый** `FIXTURES`; это не decoder experiment:

```bash
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
CODE=/home/s-a-balashov/work/vast-decoder-preflight-v6-20261005-s8470120a3-from-s6
: "${FIXTURES:?set a fresh native-ext4 fixture directory}"
RUNNER_TEMP="$FIXTURES" "$PY" -I -B "$CODE/tests/test_decoder_research_v6.py" -v
```

Adapter запускает один fresh child и обнаруживает шесть implementation test modules. Текущий проверенный S8 inventory —66 inherited+105 implementation=171 unique cases, root adapter12. Существующие120s body,15s retirement и1MiB на stdout/stderr сохраняются. Actual starts/terminals/origins/outcomes и before/after source15 записаны; nested count нельзя прибавлять арифметически к whole hosted discovery. Fixtures используют реальные temporary files/maps/Git/CPython children с явно synthetic engine/GI facts, без Docker/model/decoder workloads.

Единственный canonical S8 original завершился root12/nested171 GREEN, включая новую P8 EOF-clock regression и обе реальные15s close negatives. Old170 IDs сохранены; P6 partial-read cases остаются. P8 изменяет только допустимую timestamp chronology `run_fixture`, сохраняя старые outputs/assertions. Persisted adapter `successful:false` и provisional fields остаются исходными; отдельный actual outer rc0 закрывает fixture invocation. Fixtures не принимают реальные media или scientific cohort. [Originals](../../../openspec/changes/archive/2026-10-05-fix-decoder-preflight/evidence/P8-implementation-v1/) и [independent source review](../../../openspec/changes/archive/2026-10-05-fix-decoder-preflight/evidence/P8-implementation-independent-v1/review.v1.json) показывают этот scope. Latest exact-S8 hosted CI отдельно принят; следующий archived/docs commit ещё потребует своего final CI.

## Исполненный S6 reader — не повторять

После accepted D7 CI и current readiness grant COMMENT5408880947 уже исполнен **один** раз. Команда ниже — запись состоявшегося FAILED чтения старых S3 research originals; её report namespace занят. Ни producer, ни source/AU не повторяются. Concrete argv разделяет immutable producer S3 и observer S6; до этого чтения report и literal late companion отсутствовали; нынешний report сохраняется неизменным:

```bash
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
PHYS=/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec
PRODUCER=/home/s-a-balashov/work/vast-decoder-preflight-v6-20261004-s3bdb6cd81
PRODUCER_S=bdb6cd8104e2dc8d1dd764777bdbcfccbb6ded73
OBSERVER=/home/s-a-balashov/work/vast-decoder-preflight-v6-20261005-s6f9cde5ec-from-s5
OBSERVER_S=f9cde5ec53752d9f2af4fa5bffc1fb2c7e9c28ab
BASE="$PHYS/artifacts/benchmark_recovery_20260930"
ATTEMPT="$BASE/decoder-research-v6-clock-fixed-attempt-01"
EXTERNAL="$BASE/decoder-research-v6-clock-fixed-original-controller/attempt-01/terminal.v1.json"
TOOL=/mnt/e/STUDY/VAST/tmp/decoder-preflight-v6-20261004/research-original-tool-record.S3bdb6cd81.v1.json
REPORT="$BASE/decoder-research-v6-clock-fixed-cold/attempt-01/corrected-transport-read-verification.v1.json"
"$PY" -I -B "$OBSERVER/artifacts/benchmark_recovery_20260930/decoder-independent-v6/cold_reader.py" \
  --project-root "$PHYS" --review-repository-root "$PRODUCER" \
  --planning-commit 3aa35c3b2eedc05d22cf16ba37d470143d080f6b \
  --source-commit "$PRODUCER_S" --mode research --attempt "$ATTEMPT" \
  --external-terminal "$EXTERNAL" \
  --capture-source-sha256 0f6e7a40f14f25690694542a193dc4ba0fea54ffd0345dbd835244e241582666 \
  --capture-tool-record "$TOOL" --observer-repository-root "$OBSERVER" \
  --observer-commit "$OBSERVER_S" --report "$REPORT"
```

SHA указывает неизменный external helper copy, использованный original S3 producer; сам helper здесь не вызывается. Required flag —`--observer-commit`, не выдуманный `--observer-source-commit`. Capture tool record находится вне закрытого original namespace и содержит faithful exec/wait objects; producer не может сам доказать собственный последний write рекурсивным self-hash.

Original S3 `verification.v1.json` с namespace failure и corrected S5 `corrected-metadata-namespace-verification.v1.json` с short transport failure не заменяются. Новый report exclusive. Одна неуспешная проверка сохраняет failure/prefix и останавливает этот шаг; бюджет/caps/epoch guards не расширяются по результату.

## Исполненный S8 reader — namespace уже consumed

COMMENT5409200896 разрешил ровно одно corrected read после принятого exact-S8 CI. Следующий argv уже исполнен с rc0; это запись операции, **не команда для повтора и не reusable grant**. Producer S3/P1, physical attempt, helper hash и original producer tool record сохранены, observer отдельно S8:

```bash
PY=/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python
PHYS=/mnt/e/STUDY/VAST/tmp/openspec-review/fix-benchmark-preparations-spec
PRODUCER=/home/s-a-balashov/work/vast-decoder-preflight-v6-20261004-s3bdb6cd81
PRODUCER_S=bdb6cd8104e2dc8d1dd764777bdbcfccbb6ded73
OBSERVER=/home/s-a-balashov/work/vast-decoder-preflight-v6-20261005-s8470120a3-from-s6
OBSERVER_S=470120a3b3f9692775656cdb8114471ab991f14b
BASE="$PHYS/artifacts/benchmark_recovery_20260930"
ATTEMPT="$BASE/decoder-research-v6-clock-fixed-attempt-01"
EXTERNAL="$BASE/decoder-research-v6-clock-fixed-original-controller/attempt-01/terminal.v1.json"
TOOL=/mnt/e/STUDY/VAST/tmp/decoder-preflight-v6-20261004/research-original-tool-record.S3bdb6cd81.v1.json
REPORT="$BASE/decoder-research-v6-clock-fixed-cold/attempt-01/corrected-eof-clock-join-verification.v1.json"
"$PY" -I -B "$OBSERVER/artifacts/benchmark_recovery_20260930/decoder-independent-v6/cold_reader.py" \
  --project-root "$PHYS" --review-repository-root "$PRODUCER" \
  --planning-commit 3aa35c3b2eedc05d22cf16ba37d470143d080f6b \
  --source-commit "$PRODUCER_S" --mode research --attempt "$ATTEMPT" \
  --external-terminal "$EXTERNAL" \
  --capture-source-sha256 0f6e7a40f14f25690694542a193dc4ba0fea54ffd0345dbd835244e241582666 \
  --capture-tool-record "$TOOL" --observer-repository-root "$OBSERVER" \
  --observer-commit "$OBSERVER_S" --report "$REPORT"
```

Original `corrected-eof-clock-join-verification.v1.json` содержит128 AU/64 pairs, research/raw/operation complete,223 released holds, FD6→6/close[]/42.715633661s и no late companion. `accepted:false`, `provisional_until_owner_final_close:true`, `publication_ready:false` остаются literal. Independent cold review PASS в original research scope (review28578/e394e9fd). Original S3 namespace failure, S5 shortread и S6 clock-identity refusal сохранены отдельно; S6 failure disposition уже независимо закрыт. Ни один consumed report не перезаписывается. [Independent scoped review](../../../openspec/changes/archive/2026-10-05-fix-decoder-preflight/evidence/S8-cold-v1/) сохраняет original nonpromotion fields и named ownership limits.

## Когда результат можно интерпретировать

Sealed terminal provisional до actual owner final close. Нужны original post-close stdout/rc0, неизменный terminal size/SHA, exact namespaces, отсутствие primary/close/late failures, original positive container terminal, nonforce exact-CID removal и отдельное CID/name absence. External helper владеет только своим CPython child/group/streams; controller — Docker custody; reader — held input/report closure. Эти разные domains нельзя заменить одним outer exit0 или global-quiescence предположением.

Независимо сверенные descriptive числа этого закрытого report относятся к 16 central pairs на clip. Front-gate: p50 default 1013.664823 мс, zero 1009.732428 мс; median paired zero−default −2.445557 мс. Underbody: p50 default 2002.406025 мс, zero 2004.325781 мс; median paired Δ +1.648382 мс. Column p50 — nearest rank8 из16 central samples; paired Δ — statistical median16 per-AU differences, не разность column p50 и не median каждой even-sized колонки. Central pre-EOS означает положение samples относительно EOS, а не доказанную stationarity. Равные paired RGB hashes сравнивают наблюдавшиеся outputs, а не независимый software reference. Эти данные не доказывают causal setting benefit, pure NVDEC service/utilization, accuracy или 100 ms capacity. Для future decoder engineering default/unset остаётся provisional выбором только после отдельно accepted derived-YUV/RGB/EOS intake, а не adopted regime по этому report. Whole scoped result независимо прочитан; это не publication или campaign acceptance. Decoder adoption, qualification/parity/publication и legacy32/Q4/5600 не следуют из report. Следующий finite24/12 route требует отдельной официальной постановки, material/reference и native lifecycle/fault gates; property tuning не заменяет эти шаги. PR4 final conformance/sync/archive/final CI/review/merge ещё pending.
