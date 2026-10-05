# Конечный VAST benchmark

Рабочее изменение `run-finite-component-study`, [PR5](https://github.com/lordcoudy/VAST/pull/5), reviewed planning commit `3288b0702b6b0136feb6596382566b8686f9bb5c`. Это процедура для текущего executable path. На этапе реализации actual preparation, pilot и 24 effect arms ещё не выполнены; успешные программные тесты не являются результатом benchmark. Текущий статус и доказательства находятся в [плане](../PLAN.md) и [задачах](../openspec/changes/run-finite-component-study/tasks.md).

Benchmark измеряет baseline/shared topology при CPU OpenVINO и GPU TensorRT analytics. Обе топологии используют NVDEC. Шесть логических потоков — пять копий front-gate и один underbody, четыре одинаково привязанные analytics branches. Это реплики двух записей. Результат не доказывает качество распознавания, чистое время GPU inference, энергопотребление или производительность при 30fps.

## Один запуск

Сначала зафиксируйте исходники, выполните обязательный CI и получите действительные model, worker и execution-code receipts для private Linux ext4 root. Нужны CPython3.12.3, проверенные `/usr/bin/ffmpeg` и `/usr/bin/ffprobe`, Docker с Unix socket, доступный NVIDIA/NVDEC и исходные AVI. Driver проверяет физические bytes, identities и contracts; копирование имени receipt не делает его действительным.

Задайте абсолютные пути `ROOT`, `PYTHON`, `ENGINE`, `ENGINE_SOCKET`, `FRONT_GATE`, `UNDERBODY`. `CAPABILITY`, `CALIBRATION`, `MODEL_PARITY`, `WORKER_FREEZE`, `CODE_CLOSURE` задаются **project-relative** путями внутри `ROOT` (например `configs/...`, `b/current-code-closure.original.json`): model-material loader принимает только canonical relative paths и отклоняет абсолютные. Root должен содержать также все receipts, на которые ссылается `artifacts/fix_benchmark_preparations_20260928g/qualification_image_identity_patch.json` (native/runtime freeze receipts). `OUTPUT` должен быть новым, ещё не существующим каталогом под `ROOT`. Используйте короткий private root, чтобы фактические Unix socket paths помещались в108 bytes. Хранилище должно вмещать реальный20GiB reserve и все ограниченные input/media/raw файлы.

Если Linux root и current inputs требуют переноса, перед **первым** source/tool hash, transfer, build или preflight сохраните настоящее `time.monotonic_ns()`, `/proc/sys/kernel/random/boot_id` и `readlink('/proc/self/ns/time')` в execution kernel. Передайте их в ту же команду как `--preparation-started-monotonic-ns "$PREPARATION_STARTED_NS" --preparation-boot-id "$PREPARATION_BOOT" --preparation-time-namespace "$PREPARATION_TIME_NAMESPACE"`. Все три поля обязательны вместе: driver проверит actual clock domain, запретит future/expired start и передаст исходный endpoint native helpers. Copy/bootstrap/current code closure расходуют этот же4h срок. При уже подготовленном root команда без этих полей начинает отсчёт сама. Campaign имеет свой отдельный исходный clock.

```bash
"$PYTHON" -B "$ROOT/scripts/run_canonical_systems_study_v1.py" study \
  --project-root "$ROOT" --output-dir "$OUTPUT" \
  --engine "$ENGINE" --engine-socket "$ENGINE_SOCKET" \
  --capability-manifest "$CAPABILITY" --calibration "$CALIBRATION" \
  --model-parity-receipt "$MODEL_PARITY" --worker-freeze-receipt "$WORKER_FREEZE" \
  --execution-code-closure "$CODE_CLOSURE" \
  --front-gate "$FRONT_GATE" --underbody "$UNDERBODY"
```

Режим `study` последовательно вызывает существующие `prepare` и `run` и передаёт actual descriptor закрытой подготовки без ручного изменения hashes. Подготовка имеет один непрерывный срок4h: актуальные hashes двух AVI, bounded contiguous contexts,442 original display ordinals, fixed normalization, ровно два одинаковых encode каждой записи, реальные SPS/VUI/native inventories, YUV/RGB equality, полный EOS и отдельный offered-prefix STOP. Исходная геометрия сохраняется. Nominal encoder30/1 и MP4 tracktimebase1/600 — разные величины; каждый AU занимает20 MP4 ticks.

Кампания имеет отдельный непрерывный срок4h от первой pilot readiness до reduction и освобождения владельцев. Сначала идут четыре pilot arms при1fps. Только заранее заданный median client-lock-wait/residence≥0.10, минимум30 наблюдений и полный accounting допускают один переход на уже собранные независимые branch connections и ещё четыре pilot arms. Все24 effect arms затем используют одну final variant: CPU/GPU×0.25/1/2fps×baseline/shared×два повтора, seed20260323, AB/BA order. Фазы каждого arm30s warmup,180s measurement,10s original drain. Во время campaign нельзя менять код, images, inputs или выполнять rebuild/CI.

Ни pilot, ни частичная матрица не закрывают study. При integrity, infrastructure, deadline или cap failure driver останавливает зависимое исполнение, сохраняет original failure и raw prefix и освобождает своих владельцев. Не запускайте повторно тот же output и не исправляйте failed receipt вручную.

## Проверка результата

Завершённая кампания сохраняет `study-results.original.json` и descriptor `closed-inputs.original.json`. Обязательный результат — все24 original arms и12 пар с полным accounting, actual owner closure и independent re-reduction. `canonical_study_complete:true` не выдаёт historical full-run, qualification, Q4 или publication eligibility.

Primary Y100 использует **все planned frames** и четыре действительных branch terminals в100ms от actual admission. Source punctuality относительно расписания считается отдельно. Missing latency не превращается в ноль; verified controlled drops дают отрицательный результат, а отсутствующие, foreign или unknown terminal records запрещают принятие arm. Completed latency quantiles имеют явные `n`, nearest-rank rule и undefined при `n=0`. Paired результаты описательные; common-completed subset сохраняет собственный denominator.

Для независимого пересчёта используйте descriptor `binding` из original result и **его исходный campaign deadline**: `started_monotonic_ns / 1e9 + 14400`. Reader должен работать в подтверждённом том же monotonic clock domain и завершиться до этого срока. Не вычисляйте новый срок от момента пересчёта. `REDUCED_OUTPUT` — новый absolute file; `BINDING`, `BINDING_SIZE`, `BINDING_SHA`, `CAMPAIGN_DEADLINE` получаются из сохранённых originals.

```bash
"$PYTHON" -B "$ROOT/scripts/reduce_canonical_systems_study_v1.py" \
  --binding "$BINDING" --binding-size-bytes "$BINDING_SIZE" \
  --binding-sha256 "$BINDING_SHA" --output "$REDUCED_OUTPUT" \
  --deadline-monotonic "$CAMPAIGN_DEADLINE"
```

Reducer проверяет все24 входа заново; его `raw_effect_matrix_complete:true` — проверка raw matrix. Сам reader сохраняет `canonical_study_complete:false`, поскольку не является владельцем physical campaign. Независимый reviewer сопоставляет его значения с original driver reduction, actual process/image/material identities и closure. Existing worker residence включает map/backend/copies; неизвестные pure inference, real utilization или неподтверждённый clock domain остаются неизвестными.
