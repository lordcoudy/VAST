# Q1, попытка 2 — FAILED (8 октября 2026)

Попытка 2 на `C_Q1'` `82c7a62ee59cf04db113d4897289b7da4a6f807d`, тег `qualify_full_benchmark_20261008c`, корень `E:/STUDY/VAST/tmp/qfb-root-20261007a`. Запуск — по явной команде пользователя («start Q1»).

| Шаг | Итог (UTC) |
|---|---|
| 0 preflight (вкл. engine identity и live `_verify_live_images`) | PASS |
| 1 stock host check (6.2), 05:22 | PASS |
| 2 transaction / bootstrap | rc 0, 05:51 |
| 3 preprocessing | rc 0, 05:55 |
| 4 execution code closure | rc 0 (`published`), 05:55 |
| 5 capture plan (37) | rc 0, 05:57 |
| 6–7 guardian | `live_operational_nonpublication`, 8/8 attested |
| 8 runtime inputs | rc 0, 06:00 |
| 9 owner execute | **rc 78**, 07:37:50 — `original operational owner failed: empty failed original channel custody drifted` |

- Выполнены 4 native prechecks (openvino_gva cpu/gpu, gstreamer_custom cpu/gpu). Пятая операция — Savant diagnostic `savant-original-savant-cpu-h264-independent-processes`: контейнер `docker run … arm` завершился **rc 2 через ~5,85 с** (`engine_02.terminal.v1.json`), stdout пуст.
- При записи пустого failure-канала stdout `scripts/publication_operational_process_custody_v1.py` (`_write_failure_channel`) требует `S_IMODE == 0o444`. На drvfs (`/mnt/e`, 9p без metadata) файл с режимом 0444 отображается как 0555 (проверено отдельной пробой во временном каталоге). Общий слой custody (`publication_physical_io_v1.py`, `_mode_matches`) это учитывает, путь пустого канала — нет. Поэтому owner упал до записи stderr: причина rc 2 Savant не сохранена.
- После отказа, с разрешения пользователя, выполнен authenticated stop тем же stock-вызовом, что в шаге 10, под отдельным именем `q1_10_guardian_stop_after_failed_owner` (функция `q1_10` требует успешного шага 9): rc 0, guardian rc 0, lifecycle `clean_stop_nonpublication`, operational group записан, контейнеров 0.

## Состав

- `q1_control/` — копии всех originals управления попыткой; `savant-capture/` — process capture пятой операции; `guardian/` — authority, lifecycle, operational group.
- `attempt2-namespaces.size-sha256.json` — все файлы namespaces попытки 2 (422 файла, 447,6 MB) по пути, размеру и SHA256; они остаются на месте и не переиспользуются.

Дальнейшие действия — Amendment 6 (решение пользователя 8 октября: остановить guardian и подготовить amendment).
