# Gate G9 (Amendment 9, задача 6F.4) — PASS (10 октября 2026)

Не квалифицирующий прогон: F1 `policy-assess` (с валидатором pilots F5) и `resource-assess` на индексах G8 `…_a8diag` (выходы FAILED попытки 4). Корень `E:/STUDY/VAST/tmp/qfb-root-20261007a` на `C_B'''''` `d1a78805dd41f9f946e3f6c4ca673bfeced228b5` (перенос 6F.3: [root-move](root-move/), скрипт — [root_move_v2.sh](../physical-v9-g8-a8diag/root_move_v2.sh)). Команды — [g9-commands.sh](g9-commands.sh) (рецепт — `g8-commands.sh`; шаги индексов убраны, вместо них сверяются SHA256 выходов G8 и попытки 4). Управление — `artifacts/qualify_full_benchmark_20261008e/a9diag_control/` (копии: [a9diag_control](a9diag_control/), SHA256 originals — [a9diag_control.originals.sha256](a9diag_control.originals.sha256)); `commands.sha256` закрепляет и модуль F1 корня.

| Шаг | UTC | Итог |
|---|---|---|
| `g9_00_prepare` | 10 окт. 02:41 | rc 0: HEAD `d1a78805`, drift нет, выходы попытки 4 и индексы G8 не изменены |
| `g9_01_policy_assess` | 02:41–06:44 (4 ч 03 мин) | rc 0, `passed: true`, `ready_for_atomic_promotion`: 32 bindings, 32 cells, 126 016 samples |
| `g9_02_resource_assess` | 06:44–10:51 (4 ч 07 мин) | rc 0, `passed: true`, `ready_for_atomic_promotion`: 8 bindings, 32 cells, 100 988 branch samples |

Обе оценки выполнены целиком в одном проходе: cold-проверка closure, вывод manifest, `_validate_samples` по 32 cells с глобальной уникальностью, агрегация калибровки (policy) и resource-оценка. Promotion receipts не создавались; оценки ничего не пишут (`root-git-status.before/after` совпадают). Контейнеры и GPU-нагрузка не использовались. Измеренное время уточняет оценку попытки 5: шаг 15 ≈ 8 ч, вся цепочка ≈ 29 ч.
