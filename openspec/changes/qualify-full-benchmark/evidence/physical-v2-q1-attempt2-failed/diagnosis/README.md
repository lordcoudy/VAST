# Диагностика попытки 2 (8 октября 2026, неквалифицирующая)

- Репродукция Savant arm во временном каталоге `/var/tmp/claude-savant-diag-a1` (копии 35 материализованных входов, свой слушающий socket, `docker run --rm --network none` того же образа `8335a23e…`): stderr `savant publication runtime blocked: module 'sys' has no attribute 'exception'` — SHA256 `08c385ced70a3a2f5b49e856ad238525489c583a725ae8438b694a6a62f8df4b`, 78 bytes, rc 2, 6,18 с; совпадает с хешем stderr в `savant-capture/…/engine_02.terminal.v1.json`. Traceback: `checkpoint_runtime.py:1472` (`run_worker_processes`). Временные каталоги и контейнеры удалены.
- Python в runtime-образах: DeepStream 3.10.12, Savant 3.10.12, OpenVINO GVA 3.12.3, GStreamer 3.12.3.
- `py310-api-scan.json` — AST-скан 83 Python-файлов allowlists DeepStream/Savant (`py310_scan.py`): 2 × `sys.exception`, 17 × `add_note`. Компиляция тех же файлов Python 3.10.12 внутри образа Savant — 0 синтаксических ошибок.
- `drvfs_probe.py` — файл, созданный с режимом 0444 на `/mnt/e` (9p drvfs), отображается как 0555; fstat и lstat совпадают.
