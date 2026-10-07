# Q1, попытка 1 — FAILED (7 октября 2026)

Единственная объявленная попытка Q1 на `C_Q1` `1112af0b53cae995984708390cf9d04c18da3c0d`, корень `E:/STUDY/VAST/tmp/qfb-root-20261007a`. Запуск — по явной команде пользователя («start Q1»).

| Шаг | UTC | Итог |
|---|---|---|
| 0 `q1_00_preflight` | 2026-10-07 18:57 | PASS |
| 1 `q1_01_host_check` (6.2) | 18:57:33 | PASS: C 89.9 GB, E 360 GB, WSL 758 GB; контейнеров, compute apps и процессов VAST нет |
| 2 `q1_02_transaction` | 18:57:38 → 19:01:42 | **rc 78** |

stderr шага 2: `qualification input transaction blocked: qualification fragment materialization failed closed: live deepstream runtime image differs from refreeze receipt`.

## Что проверяет отказавший предикат

`scripts/publication_policy_qualification_fragments_from_authority_v2.py`, `_verify_live_images`: для каждой из четырёх систем `Id` по `final_reference` равен `physical_identity.image_id` **и** SHA256 канонического полного `docker image inspect` равен `physical_identity.inspect_full_sha256` из patch. Значение пишет `publication_qualification_image_refreeze_v1.py` (:961) при refreeze.

## Read-only диагностика после отказа

- Все 4 runtime image ID совпадают с patch; оба worker image совпадают по ID и по `image_inspect_sha256` (projection). Поле `projection_ok: false` для систем в `q1-failed-readonly-observation.v1.json` вычислено неподходящей функцией (worker `_inspect_projection`); повторная read-only проверка 8 октября функцией refreeze `_image_projection` — projection всех четырёх систем равны receipts, все 12 ссылок (final и determinism-a/-b) указывают на прежние ID: [readonly-diagnosis-20261008.v1.json](readonly-diagnosis-20261008.v1.json).
- SHA256 полного inspect отличается **у всех четырёх** runtime images. Каноникализация обоих модулей даёт одинаковые байты, то есть меняется сам вывод inspect.
- Docker Desktop обновлён Chocolatey до **4.93.0** (engine 29.8.1, API 1.56) в 10:38:44–10:39:36 МСК 7 октября (события MsiInstaller, `chocolatey.log`). Refreeze receipts записаны раньше, в 08:28–08:29 МСК.
- Окно дрейфа: integration-тест `test_live_fix_benchmark_preflight_matches_runtime_materializer` прошёл `_verify_live_images` вживую в 06:57–06:59 UTC (09:57 МСК). В окне — обновление Docker Desktop (10:38 МСК) и перезагрузка WSL (11:39 МСК; WSL docker-ce `dockerd` запущен в 11:44). На `/run/docker.sock` претендуют WSL docker-ce и proxy Docker Desktop; отвечает Docker Desktop (daemon ID `aa8f3d33-…`).
- Вероятная причина: обновление или перезапуск engine изменили полный inspect неизменённых образов. Полный inspect на момент freeze не сохранялся, поэтому конкретное поле не доказано. Проверки готовности 11:48, 16:32 и 21:55 МСК сверяли только image ID.
- Guardian не запускался; после отказа контейнеров 0, процессов VAST 0. Ничего не удалялось, не переименовывалось и не повторялось.

## Состав

- `q1_control/` — побайтовые копии всех originals из `artifacts/qualify_full_benchmark_20261007a/q1_control/` (rc, launch, stdout/stderr, inputs SHA256, host-check, git status, копия runbook-команд и её SHA256, read-only наблюдение). Манифест — `originals.sha256`.
- `attempt1-namespaces.size-sha256.json` — namespaces, созданные попыткой (`publication_policy_qualification_v2_qfb_20261007a`, `publication_guardian_inputs_v1_qfb_20261007a`); оба пусты. Также созданы пустые `/var/tmp/vqfb1007a` и `/var/tmp/vqfb1007a/s`. Всё сохраняется на месте и больше не используется.

Дальнейшие действия — Amendment 4 в `design.md` (решение пользователя: вариант (а), новая попытка в этом MR).
