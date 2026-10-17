# 6A.5 parity, запуск 1 — FAILED (инфраструктура, 8 октября 2026)

- Рецепт `run_model_parity.sh` (diff только тег и namespace), старт 22:03:55Z, конец 22:06:35Z, rc 1.
- Отказ: `SidecarError: analytics worker container vast-gst-analytics-…-plate-number-cpu exited during startup: … Cannot connect to the Docker daemon at unix:///var/run/docker.sock` (`model_parity_control/stderr.log`).
- Причина: Docker Desktop 4.93.0 завершился без записи о штатной остановке в 22:03:59.73Z (`%LOCALAPPDATA%\Docker\log\host\com.docker.backend.exe.log`, последняя строка — обработка запроса parity). Окно Settings Docker Desktop было открыто в 22:00:23Z. После этого `/run/docker.sock` пересоздан в 22:06Z и обслуживается WSL docker-ce 29.7.2 (daemon `1e493309-…`), не Docker Desktop (`aa8f3d33-…`). Docker Desktop не запущен (только `com.docker.service`).
- Re-freeze (22:02Z), live `_verify_live_images` нового patch (22:02:58Z) и 23 packaged checks выполнены до остановки Docker Desktop.
- Контейнеров и процессов parity после отказа нет. Частичные выходы (`model_parity_v4/bindings` — 9 файлов, `runtime_probes` — 2, два untracked `configs/*qfb-20261008b*`) и `/var/tmp/vast-parity-qfb-20261008b` сохранены; хеши — `partial-outputs.sha256`.
- Повтор — только после запуска Docker Desktop оператором, сверки идентичности engine с 6A.2 и live-сверки полного inspect нового patch (Amendment 4: при расхождении — стоп и решение пользователя). Выходы запуска 1 переносятся в `*.failed-01-desktop-exit` по прецеденту `packaged_checks.failed-01-loader`.
