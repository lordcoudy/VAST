# 6A.5 parity, запуски 2–3 — FAILED (8 октября 2026)

После запуска Docker Desktop оператором: engine равен 6A.2 (daemon `aa8f3d33-…`), live `_verify_live_images` нового patch `dce8407e…` — PASS, WSL перезагружен (boot ID `c062ef70-…`) — [engine-and-live-verify-after-desktop-restart.v1.json](engine-and-live-verify-after-desktop-restart.v1.json). Перезапуск Docker Desktop и WSL полный inspect не изменил.

## Запуск 2 (22:11:07Z) — orphaned writer intent

`publication_immutable_directory_v1`: «immutable directory writer is orphaned». Запуск 1 оставил два content-addressed intent в `.publication-directory-journal-v1` (`runtime_probes`, `bindings` нового тега), а их опубликованные каталоги были перенесены в `parity.failed-01-desktop-exit`. Запуск 2 получил тот же logical tree и тот же ключ intent — защита от ABA сработала штатно. Оба intent перенесены вместе с каталогами запуска 1 в `parity.failed-01-desktop-exit/journal/` с SHA256 до/после ([run1-journal](run1-journal/)); выходы запуска 2 — в `parity.failed-02-orphaned-intent`. Код не менялся.

## Запуск 3 (22:12:22Z → 22:15:08Z) — платформа Docker Desktop вне pin

Перед запуском engine и live-сверка снова PASS ([run3](run3/engine-and-live-verify-before-parity-run3.v1.json)). rc 1: `SidecarError: Docker Desktop containerd commit drifted` (`checkpoint_gstreamer_analytics_sidecar.py`, `_docker_desktop_platform_projection`).

- Production-код sidecar/guardian принимает только Docker Desktop с `ServerVersion` `29.7.2` (`_DOCKER_DESKTOP_SERVER_VERSION`) и containerd commit из `_DOCKER_DESKTOP_CONTAINERD_COMMIT_IDS` (`e53c7c15…`, `aad11006…`).
- Текущий Docker Desktop 4.93.0: `ServerVersion` `29.8.1`, containerd `1294c24a7da8e5a793ed378161673abe94118892` ([docker-info-platform-projection-inputs.20261008.json](docker-info-platform-projection-inputs.20261008.json)).
- Docker Desktop был обновлён явной командой `choco upgrade docker-desktop -y` 7 октября в 10:37:55 МСК с **4.89.0** до 4.93.0 (`C:\ProgramData\chocolatey\logs\chocolatey.log`), после freeze образов (08:28 МСК) и до попытки 1.
- Следствие: на текущем Docker Desktop guardian Q1 (шаг 6) отказал бы тем же предикатом. Amendment 4 это не покрывает: нужен либо возврат Docker Desktop к 4.89.0, либо reviewed amendment кода platform pin.

Контейнеров и процессов parity после отказа нет; выходы запуска 3 остаются на месте.
