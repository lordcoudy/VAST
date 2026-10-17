# Q1, попытка 3 — FAILED (8 октября 2026)

Попытка 3 на `C_Q1''` `4947e35a70fcfd94cf53179f05c021f8fb9dd3d1`, тег `qualify_full_benchmark_20261008d`, корень `E:/STUDY/VAST/tmp/qfb-root-20261007a`. Запуск — по явной команде пользователя («Start Q1»). Пункты 1–2 чек-листа хоста проверены (AC sleep/hibernate 0, Windows Update paused до 26 октября); пункты 3–4 приняты по команде запуска (Docker Desktop работает с 01:10 МСК, `boot_id` `c062ef70…` тот же, что в попытке 2).

| Шаг | Итог (UTC) |
|---|---|
| 0 preflight (engine identity, live `_verify_live_images`) | PASS, 12:23 |
| 1 stock host check (6.2) | PASS, 12:23 — C 80 / E 334 / WSL 706 GiB, 0 контейнеров, 0 GPU compute |
| 2 transaction / bootstrap | rc 0, 12:52 |
| 3 preprocessing | rc 0, 12:55 |
| 4 execution code closure | rc 0 (`published`), 12:55 |
| 5 capture plan (37) | rc 0, 12:57 |
| 6–7 guardian | `live_operational_nonpublication`, 8/8 attested |
| 8 runtime inputs | rc 0, 13:00 |
| 9 owner execute | **rc 78**, 15:02:14 — `original operational owner failed: original container custody failed: original_measurement_failed` |

- Выполнены 5 операций: 4 native prechecks (openvino_gva cpu/gpu, gstreamer_custom cpu/gpu) и Savant original (пройдена точка отказа попытки 2). Шестая операция — первая cell `qualification-cell-deepstream-cpu-h264-independent-processes`: контейнер DeepStream (`engine_02`, `docker run … --topology-kind independent_processes --policy cpu_only`) завершился **rc 2**, stderr (95 B): `deepstream publication runtime blocked: worker_id is outside the supported ASCII source domain`.
- Вероятная причина (точное значение `worker_id` в логах не сохранено): в режиме operational capture `scripts/checkpoint_native_policy_runtime.py:741` вызывает `validate_native_request_source_v1`, где `scripts/publication_operational_request_domain_v1.py:299` ограничивает `worker_id` 37 символами. DeepStream worker = `process_id` (`checkpoint_deepstream_launcher.py:149`), а для independent processes `checkpoint_deepstream_runtime.py:328` строит `deepstream-stream-N-branch-<branch>`: `foreign_object` — 41, `vehicle_type`/`plate_number` — 39, `damage` — 33 символа. Shared `deepstream-stream-N-shared-video-dag` — 36. OpenVINO GVA, gstreamer_custom и Savant используют `stream-N-…` (≤ 30) и проходят. Все DeepStream independent-processes cells упали бы одинаково.
- Одновременно guardian завершился сам: `analytics production service failed: failed to receive analytics execution datagram: [Errno 104] Connection reset by peer` (15:02:06), lifecycle **`failed_stop_nonpublication`**, guardian rc 78, `protocol_failure_diagnostic.v1.json` с `attribution: unavailable`. Сброс соединения одним клиентом (упавшим контейнером DeepStream) завершил весь сервис — тот же класс, что Broken pipe в attempt J (PR5). Authenticated stop (шаг 10) неприменим: guardian уже терминален. Контейнеров после отказа 0, GPU compute 0, процессов VAST 0.
- Ничего не повторялось, не удалялось и не переименовывалось; `docker stop/rm/prune` не выполнялись.

## Состав

- `q1_control/` — копии всех originals управления попыткой, включая `q1-failed-readonly-observation.txt` (SHA256 `eaea530e…876f25`) и `q1-attempt3-failed-readonly-observation.v1.json`.
- `cell-capture/` — process capture шестой операции (DeepStream cell): launch/terminal/failure, container custody.
- `guardian/` — authority, lifecycle, protocol failure diagnostic, operational group.
- `pilot_checkpoint.v2.json` — checkpoint owner (`status: in_progress`).
- `attempt3-namespaces.size-sha256.json` — все файлы namespaces попытки 3 (467 файлов, 526,2 MB) по пути, размеру и SHA256; они остаются на месте и не переиспользуются. `/var/tmp/vqfb1008d` содержит только каталоги (0 файлов).
- `originals.sha256` — SHA256 всех файлов этого каталога.

Дальнейшие действия — Amendment 7 (решение пользователя 8 октября: вариант (а), записать отказ в PR #7 и docs).
