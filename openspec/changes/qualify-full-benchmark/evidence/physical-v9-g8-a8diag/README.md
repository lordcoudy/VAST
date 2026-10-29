# Gate G8 (Amendment 8, задача 6E.4) — FAILED на оценке policy (9–10 октября 2026)

Не квалифицирующий прогон на выходах FAILED попытки 4. Корень `E:/STUDY/VAST/tmp/qfb-root-20261007a` на `C_B''''` `ad9bda3d6eed425fae01ba1cd65a9907ba32df8a` (перенос 6E.3: [root-move](root-move/), [root_move_v2.sh](root_move_v2.sh)). Команды — [g8-commands.sh](g8-commands.sh) (helpers runbook корня, проба errexit; детачированный драйвер `g8_all`, шаги — отдельные команды под errexit). Управление и логи — `artifacts/qualify_full_benchmark_20261008e/a8diag_control/` (копии: [a8diag_control](a8diag_control/), SHA256 originals — [a8diag_control.originals.sha256](a8diag_control.originals.sha256)).

| Шаг | UTC | Итог |
|---|---|---|
| `g8_00_prepare` | 9 окт. 14:59 | rc 0: HEAD `ad9bda3d`, drift нет, выходы попытки 4 (`q1_02`, `q1_13`) не изменены |
| `g8_01_policy_index` (F1) | 14:59–17:20 | rc 0 — `publication_policy_qualification_index_v2_qfb_20261008e_a8diag/` |
| `g8_02_resource_index` (F1, F2) | 17:20–19:34 | rc 0 — `full_resource_qualification_index_v1_qfb_20261008e_a8diag.json` |
| `g8_03_policy_assess` | 19:34–21:50 | **rc 78**: `pilot sidecar revalidation failed: …/deepstream/cpu/h264/independent_processes/reset_evidence.csv: reset validation requires topology kind, stream count, and branch set` |
| `g8_04_resource_assess` | — | не запускался (драйвер остановлен errexit) |

Индексы и candidate manifest/receipt G8 — [a8diag_outputs](a8diag_outputs/) (SHA256 originals — [a8diag_outputs.originals.sha256](a8diag_outputs.originals.sha256)); остаются в корне, promotion receipts не создавались. Контейнеры и GPU-нагрузка не использовались.

## Диагностика (read-only, [diagnosis](diagnosis/))

Все прогоны — в WSL на корне без записи в него, по индексам G8; closure уже cold-проверен шагами 1–3 G8, поэтому не перезагружается.

| Прогон | Что | Итог |
|---|---|---|
| [diag_a9_pilots.py](diagnosis/diag_a9_pilots.py) `resource 0` | stock resource pilot validator (с F3) по 32 cells | **32/32 приняты** ([result](diagnosis/resource-inject0.result.json)) |
| `policy 0` | stock policy pilot validator | 0/32: та же причина, что в G8 ([result](diagnosis/policy-inject0.result.json)) |
| `policy 1` | с `expected_streams=6` | 24/32; 8 GPU cells — `GPU qualification sample lacks native transfer interval` ([result](diagnosis/policy-inject1.result.json)) |
| [diag_a9_transfer.py](diagnosis/diag_a9_transfer.py), [diag_a9_missing_detail.py](diagnosis/diag_a9_missing_detail.py) | GPU-решения без transfer-интервала | 20 решений в 8 cells (1–12 на cell); все — кадры с ingress terminal `drop`, интервалов у таких trace нет, branch terminal `completed` ([result](diagnosis/transfer.result.json)) |
| [diag_a9_candidate.py](diagnosis/diag_a9_candidate.py) | обе поправки (поток 6; решения не-completed кадров не samples) | **32/32 приняты** ([result](diagnosis/candidate.result.json)); в GPU cells исключены ровно 0–12 решений (= решения без transfer), в CPU cells — 1196–1779 (поэтому в Amendment 9 исключаются только GPU-решения без transfer) |

Выводы и исправление — design, Amendment 9.
