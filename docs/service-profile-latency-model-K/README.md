# Профиль обслуживания и предиктор латентности — attempt K

Изменение OpenSpec `add-service-profile-latency-model`, [спека](../../openspec/changes/add-service-profile-latency-model/specs/service-profile-latency-model/spec.md). Описательный анализ, не формула политики; все флаги eligibility (`qualification`, `q4`, `publication`, `full_run`, `canonical_study_complete`, `policy_calibration`) = `false`. Это новое descriptive чтение закрытых входов K, а не независимая повторная редукция (5.4).

## Итог

**`gpu_latency_profile_use_permitted = false`, `queueing_extrapolation_use_permitted = false`.** Не прошли все 20 GPU сравнений групп (a)+(b) и 16 из 20 CPU. По спеке это допустимый результат: последующие study changes (GPU colocation, cross-stream batching) **не выводят параметры из этой модели** и задают их заранее фиксированными значениями.

Описательно (без вывода о причине):
- GPU при rate 1–2: модель систематически **недооценивает Y100_frame** (in-sample на 0.10–0.19, load extrapolation на 0.06–0.25); in-sample p50 выше наблюдаемого на 1–24 ms. При 0.25 fps Y100 слегка переоценён (на 0.006–0.06), p50 выше наблюдаемого на 34–126 ms. Controlled drops в GPU arms нет ни в наблюдении, ни в модели.
- CPU: доля drops in-sample при rate 1 совпадает в пределах 0.002 (0.122–0.129 против 0.123–0.130), при rate 2 — в пределах 0.07; p50 completed latency расходится на сотни–тысячи ms; при rate 2 baseline prefix пулы содержат 1–5 `prefix_unqueued` requests, у r2-cpu-2-baseline пул `foreign_object` пуст (`prediction: null`), как заранее указано в спеке.
- `route_hold` GPU при 0.25 fps ниже, чем при rate 1 (например plate_number 6.3–6.6 против 8.9–9.2 ms), хотя completed latency при 0.25 fps выше (p50 ≈284–386 против ≈116–142 ms).

## Запуски на данных K

| # | Что | Результат |
|---|---|---|
| dev-smoke | Во время реализации, до первого CLI-запуска: функции модуля на 3 arms (`r1-gpu-1-shared`, `r1-cpu-1-baseline`, `r1-gpu-2-shared`), 5 реплик, без отчёта. Модель после него не менялась. | in-sample GPU Y100 0.153/0.271 против 0.350/0.407 |
| run-1 | CLI, commit `ff41ffb11664bc470e7efcdfe62969af373112fc`, module SHA256 `8b8d7071…6548`, analysis deadline 14400 s, Python 3.12.3 (WSL, runtime K) | rc 0, 252.5 s; отчёт 331828 B, SHA256 `403b8544c6ae601de32b86cfd0eed44d67383eb7a751c1351d0c1b234c85ab8d` ([gzip](run-1.report.json.gz), 69996 B, SHA256 `50a8d79b…025d`) |

Две предшествующие попытки запуска CLI не исполнили модуль (ошибки quoting/path conversion в обёртке, отчёт и stdout не созданы). SHA256 binding (`8f92bb40…5ba90`) и двух raw файлов совпали до и после run-1; модуль сам проверил size+SHA256 и epochs всех 145 входов binding и архива и совпадение всех 24 arm reductions с архивом.

## Группа (b) — load extrapolation (gate)

| comparison | obs Y100 | pred Y100 | obs drop | pred drop | obs p50 ms | pred p50 ms | pass | failures |
|---|---|---|---|---|---|---|---|---|
| r1-cpu-1-baseline → r1-cpu-2-baseline | 0.000 | 0.000 | 0.518 | 0.477 | 4224.8 | 6385.1 | no | p50_ms |
| r1-cpu-2-baseline → r1-cpu-1-baseline | 0.000 | 0.000 | 0.125 | 0.195 | 3543.8 | 6969.7 | no | drop_fraction, p50_ms |
| r1-cpu-1-shared → r1-cpu-2-shared | 0.000 | 0.000 | 0.514 | 0.477 | 4115.1 | 3665.3 | no | p50_ms |
| r1-cpu-2-shared → r1-cpu-1-shared | 0.000 | 0.000 | 0.123 | 0.213 | 3499.4 | 4975.8 | no | drop_fraction, p50_ms |
| r1-gpu-1-baseline → r1-gpu-2-baseline | 0.196 | 0.058 | 0.000 | 0.000 | 119.6 | 131.7 | no | Y100_frame, p50_ms |
| r1-gpu-2-baseline → r1-gpu-1-baseline | 0.164 | 0.097 | 0.000 | 0.000 | 126.8 | 121.4 | no | Y100_frame |
| r1-gpu-1-shared → r1-gpu-2-shared | 0.407 | 0.161 | 0.000 | 0.000 | 107.6 | 139.3 | no | Y100_frame, p50_ms |
| r1-gpu-2-shared → r1-gpu-1-shared | 0.350 | 0.271 | 0.000 | 0.000 | 115.6 | 113.7 | no | Y100_frame |
| r2-cpu-1-baseline → r2-cpu-2-baseline | 0.000 | 0.000 | 0.517 | 0.482 | 4250.0 | 5387.6 | no | p50_ms |
| r2-cpu-2-baseline → r2-cpu-1-baseline | 0.000 | — | 0.130 | — | 3589.5 | — | no | prediction null: empty calibration pool: foreign_object |
| r2-cpu-1-shared → r2-cpu-2-shared | 0.000 | 0.000 | 0.518 | 0.476 | 4170.6 | 3669.1 | no | p50_ms |
| r2-cpu-2-shared → r2-cpu-1-shared | 0.000 | 0.000 | 0.123 | 0.194 | 3484.3 | 4601.8 | no | drop_fraction, p50_ms |
| r2-gpu-1-baseline → r2-gpu-2-baseline | 0.202 | 0.039 | 0.000 | 0.000 | 120.5 | 153.8 | no | Y100_frame, p50_ms |
| r2-gpu-2-baseline → r2-gpu-1-baseline | 0.162 | 0.099 | 0.000 | 0.000 | 142.1 | 121.5 | no | Y100_frame, p50_ms |
| r2-gpu-1-shared → r2-gpu-2-shared | 0.389 | 0.149 | 0.000 | 0.000 | 108.5 | 139.7 | no | Y100_frame, p50_ms |
| r2-gpu-2-shared → r2-gpu-1-shared | 0.332 | 0.269 | 0.000 | 0.000 | 118.0 | 114.3 | no | Y100_frame |

## Группа (a) — in-sample (gate)

| comparison | obs Y100 | pred Y100 | obs drop | pred drop | obs p50 ms | pred p50 ms | pass | failures |
|---|---|---|---|---|---|---|---|---|
| r1-cpu-0.25-baseline | 0.000 | 0.000 | 0.000 | 0.000 | 1058.5 | 983.7 | yes | — |
| r1-cpu-0.25-shared | 0.000 | 0.000 | 0.000 | 0.000 | 1044.0 | 897.7 | no | p50_ms |
| r1-gpu-2-baseline | 0.196 | 0.096 | 0.000 | 0.000 | 119.6 | 121.4 | no | Y100_frame |
| r1-gpu-2-shared | 0.407 | 0.274 | 0.000 | 0.000 | 107.6 | 113.6 | no | Y100_frame |
| r1-gpu-1-baseline | 0.164 | 0.058 | 0.000 | 0.000 | 126.8 | 131.6 | no | Y100_frame |
| r1-gpu-1-shared | 0.350 | 0.160 | 0.000 | 0.000 | 115.6 | 139.4 | no | Y100_frame, p50_ms |
| r1-cpu-2-baseline | 0.000 | 0.000 | 0.518 | 0.517 | 4224.8 | 7177.7 | no | p50_ms |
| r1-cpu-2-shared | 0.000 | 0.000 | 0.514 | 0.583 | 4115.1 | 5538.3 | no | drop_fraction, p50_ms |
| r1-cpu-1-baseline | 0.000 | 0.000 | 0.125 | 0.123 | 3543.8 | 6162.1 | no | p50_ms |
| r1-cpu-1-shared | 0.000 | 0.000 | 0.123 | 0.122 | 3499.4 | 3414.8 | yes | — |
| r1-gpu-0.25-baseline | 0.000 | 0.013 | 0.000 | 0.000 | 296.8 | 350.6 | no | p50_ms |
| r1-gpu-0.25-shared | 0.000 | 0.040 | 0.000 | 0.000 | 386.0 | 471.2 | no | p50_ms |
| r2-gpu-0.25-shared | 0.033 | 0.060 | 0.000 | 0.000 | 284.1 | 318.5 | no | p50_ms |
| r2-gpu-0.25-baseline | 0.000 | 0.006 | 0.000 | 0.000 | 296.1 | 421.9 | no | p50_ms |
| r2-cpu-1-shared | 0.000 | 0.000 | 0.123 | 0.122 | 3484.3 | 3410.8 | yes | — |
| r2-cpu-1-baseline | 0.000 | 0.000 | 0.130 | 0.129 | 3589.5 | 5106.9 | no | p50_ms |
| r2-cpu-2-shared | 0.000 | 0.000 | 0.518 | 0.545 | 4170.6 | 5139.4 | no | p50_ms |
| r2-cpu-2-baseline | 0.000 | — | 0.517 | — | 4250.0 | — | no | prediction null: empty calibration pool: foreign_object |
| r2-gpu-1-shared | 0.332 | 0.150 | 0.000 | 0.000 | 118.0 | 139.6 | no | Y100_frame, p50_ms |
| r2-gpu-1-baseline | 0.162 | 0.039 | 0.000 | 0.000 | 142.1 | 153.7 | no | Y100_frame |
| r2-gpu-2-shared | 0.389 | 0.268 | 0.000 | 0.000 | 108.5 | 114.4 | no | Y100_frame |
| r2-gpu-2-baseline | 0.202 | 0.099 | 0.000 | 0.000 | 120.5 | 121.4 | no | Y100_frame |
| r2-cpu-0.25-shared | 0.000 | 0.000 | 0.000 | 0.000 | 1042.0 | 905.4 | no | p50_ms |
| r2-cpu-0.25-baseline | 0.000 | 0.000 | 0.000 | 0.000 | 1053.6 | 984.6 | yes | — |

## Группа (c) — cross-repeat (без gate)

| comparison | obs Y100 | pred Y100 | obs drop | pred drop | obs p50 ms | pred p50 ms | pass | failures |
|---|---|---|---|---|---|---|---|---|
| r1-cpu-0.25-baseline → r2-cpu-0.25-baseline | 0.000 | 0.000 | 0.000 | 0.000 | 1053.6 | 984.1 | yes | — |
| r2-cpu-0.25-baseline → r1-cpu-0.25-baseline | 0.000 | 0.000 | 0.000 | 0.000 | 1058.5 | 982.0 | yes | — |
| r1-cpu-1-baseline → r2-cpu-1-baseline | 0.000 | 0.000 | 0.130 | 0.123 | 3589.5 | 6160.9 | no | p50_ms |
| r2-cpu-1-baseline → r1-cpu-1-baseline | 0.000 | 0.000 | 0.125 | 0.129 | 3543.8 | 5104.5 | no | p50_ms |
| r1-cpu-2-baseline → r2-cpu-2-baseline | 0.000 | 0.000 | 0.517 | 0.517 | 4250.0 | 7180.0 | no | p50_ms |
| r2-cpu-2-baseline → r1-cpu-2-baseline | 0.000 | — | 0.518 | — | 4224.8 | — | no | prediction null: empty calibration pool: foreign_object |
| r1-cpu-0.25-shared → r2-cpu-0.25-shared | 0.000 | 0.000 | 0.000 | 0.000 | 1042.0 | 900.3 | no | p50_ms |
| r2-cpu-0.25-shared → r1-cpu-0.25-shared | 0.000 | 0.000 | 0.000 | 0.000 | 1044.0 | 906.3 | no | p50_ms |
| r1-cpu-1-shared → r2-cpu-1-shared | 0.000 | 0.000 | 0.123 | 0.122 | 3484.3 | 3417.3 | yes | — |
| r2-cpu-1-shared → r1-cpu-1-shared | 0.000 | 0.000 | 0.123 | 0.122 | 3499.4 | 3409.9 | yes | — |
| r1-cpu-2-shared → r2-cpu-2-shared | 0.000 | 0.000 | 0.518 | 0.584 | 4170.6 | 5542.0 | no | drop_fraction, p50_ms |
| r2-cpu-2-shared → r1-cpu-2-shared | 0.000 | 0.000 | 0.514 | 0.545 | 4115.1 | 5145.7 | no | p50_ms |
| r1-gpu-0.25-baseline → r2-gpu-0.25-baseline | 0.000 | 0.015 | 0.000 | 0.000 | 296.1 | 348.1 | no | p50_ms |
| r2-gpu-0.25-baseline → r1-gpu-0.25-baseline | 0.000 | 0.006 | 0.000 | 0.000 | 296.8 | 417.4 | no | p50_ms |
| r1-gpu-1-baseline → r2-gpu-1-baseline | 0.162 | 0.058 | 0.000 | 0.000 | 142.1 | 131.7 | no | Y100_frame |
| r2-gpu-1-baseline → r1-gpu-1-baseline | 0.164 | 0.040 | 0.000 | 0.000 | 126.8 | 153.4 | no | Y100_frame, p50_ms |
| r1-gpu-2-baseline → r2-gpu-2-baseline | 0.202 | 0.097 | 0.000 | 0.000 | 120.5 | 121.4 | no | Y100_frame |
| r2-gpu-2-baseline → r1-gpu-2-baseline | 0.196 | 0.098 | 0.000 | 0.000 | 119.6 | 121.4 | no | Y100_frame |
| r1-gpu-0.25-shared → r2-gpu-0.25-shared | 0.033 | 0.040 | 0.000 | 0.000 | 284.1 | 465.8 | no | p50_ms |
| r2-gpu-0.25-shared → r1-gpu-0.25-shared | 0.000 | 0.059 | 0.000 | 0.000 | 386.0 | 323.5 | no | Y100_frame, p50_ms |
| r1-gpu-1-shared → r2-gpu-1-shared | 0.332 | 0.162 | 0.000 | 0.000 | 118.0 | 138.7 | no | Y100_frame, p50_ms |
| r2-gpu-1-shared → r1-gpu-1-shared | 0.350 | 0.151 | 0.000 | 0.000 | 115.6 | 139.5 | no | Y100_frame, p50_ms |
| r1-gpu-2-shared → r2-gpu-2-shared | 0.389 | 0.274 | 0.000 | 0.000 | 108.5 | 113.6 | no | Y100_frame |
| r2-gpu-2-shared → r1-gpu-2-shared | 0.407 | 0.268 | 0.000 | 0.000 | 107.6 | 114.4 | no | Y100_frame |

Порог сравнения: |ΔY100_frame| ≤ 0.05, |Δdrop_fraction| ≤ 0.05, observed completed frames > 0, p50 определён во всех 200 репликах, |Δp50| ≤ max(10 ms, 10 % observed). Предсказание — среднее по 200 репликам; интервалы 2.5/97.5 % — в отчёте.

## Немоделируемые факторы

Порядок захвата route `threading.Lock` не гарантированно FIFO; общий Python bridge process (GIL) с pre-route preprocessing; конкуренция routes на одном GPU и CPU; decode как часть prefix server; policy decide RPC учтён в prefix server, хотя исполняется после analytics queue; prefix выбирается независимо от кортежа; работа probe после release принята нулевой. Полные распределения компонентов, размеры пулов и разрывы `prefix_unqueued` по arm/branch — в отчёте (`profiles`).

## Воспроизведение

```bash
python -I -B scripts/service_profile_latency_model_v1.py --study attempt-K   --binding /home/s-a-balashov/vffefab7aK/s/run/closed-inputs.original.json   --archive "$PWD/openspec/changes/archive/2026-10-06-run-finite-component-study/evidence/physical-K-completed-v1/s__run/study-results.original.json.gz"   --output /path/to/new-report.json --source-commit "$(git rev-parse HEAD)"
```

Каждый новый запуск пишется в новый файл и добавляется в таблицу запусков. Изменение модели, порогов или групп требует нового ревью спеки.
