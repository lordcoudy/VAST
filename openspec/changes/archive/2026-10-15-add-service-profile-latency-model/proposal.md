## Why

VAST не имеет модели, которая объясняет или предсказывает измеренный результат: policy calibration хранит только плоские медианы `service_ms`, `rank_u_ms` равен `max(service+transfer)`, а native probe всегда передаёт `gpu_queue_depth = 0`. Attempt K (24/12, завершён 2026-10-06) дал полный набор per-request интервалов (native client, bridge route, worker), но их никто не сводит в профиль обслуживания и не проверяет, воспроизводит ли очередь наблюдаемые drops/Y100. Профиль и проверенный предиктор нужны до следующих runtime-исследований (GPU colocation, cross-stream batching), чтобы их параметры выбирались заранее из данных K, а не подбирались по результатам. Идея заимствована из OctopInf (profile-based latency + queueing estimate), код OctopInf не используется.

## What Changes

- Новый host-only аналитический инструмент `service-profile-latency-model-v1`: читает закрытые входы attempt K только через существующую проверку `size+SHA256` и held no-follow epochs, без изменения исходных файлов.
- Профиль обслуживания по measurement-окну каждой arm и branch: семь компонентов в порядке исполнения кода (prefix, probe_pre, native_wait, bridge_pre, route_wait, route_hold, bridge_post), сумма которых точно равна латентности reducer; worker backend/residence как отдельный диагностический слой.
- Полностью зафиксированный до первого запуска trace-driven discrete-event предиктор: frozen schedule плана, prefix server и analytics queue с буферами 1 drop-newest, FIFO route на branch для 6 streams; выход — drops по причинам, completed latency quantiles, Y100_frame над полным planned знаменателем.
- Отчёт валидации: in-sample (24 arms), load extrapolation rate 1 ↔ 2 и cross-repeat r1 ↔ r2. Наблюдаемые значения берутся из существующего per-arm reducer и обязаны совпасть с архивной редукцией K.
- Два заранее зафиксированных флага: `gpu_latency_profile_use_permitted` (GPU сравнения) и `queueing_extrapolation_use_permitted` (дополнительно CPU сравнения, где есть реальные drops). Они ограничивают, что последующие study changes могут брать из модели.
- Ничего не меняется в runtime, образах, allowlists, policy formulas, calibration, legacy validators и результатах K.

## Capabilities

### New Capabilities
- `service-profile-latency-model`: описательный профиль обслуживания и проверенный предиктор очередей/латентности по закрытым данным finite study, с provenance, полными знаменателями и запретом на использование вне назначенных study-целей.

### Modified Capabilities
<!-- Нет: требования finite-component-study, benchmark-launch-preparation и component-latency-diagnostics не меняются. -->

## Impact

- Новые файлы: модуль и CLI в `scripts/` (host-only, вне `deploy/gstreamer_custom/publication/runtime-source-allowlist.txt` и всех Dockerfile `COPY`), unit-тесты в `tests/`, отчёт по K и runbook-раздел в `docs/`.
- Переиспользуются: `scripts/reduce_canonical_systems_study_v1.py` (`read_closed_rows`, `reduce_arm`/`reduce_study`, `distribution`), `scripts/canonical_systems_study_plan_v1.py` (`validate_study_plan`, `stream_schedule`).
- Внешние данные: raw K в WSL ext4 `/home/s-a-balashov/vffefab7aK` (только чтение; binding `s/run/closed-inputs.original.json`, 31496 B).
- Packaged runtime bytes, parity, pins, closures и 227 сохраняемых образов не затрагиваются; конфликтов с `fix-accepted-policy-preprocessing` (PR #9) нет.
