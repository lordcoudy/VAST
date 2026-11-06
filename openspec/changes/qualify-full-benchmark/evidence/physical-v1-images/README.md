# Образы `qualify_full_benchmark_20261007a` (задачи 5.1–5.2)

Корень `/mnt/e/STUDY/VAST/tmp/qfb-root-20261007a` — exact-commit clone с `core.autocrlf=false`. Все сборки выполнены на commit `3a7f799d8469d50d85480162f8c3af2af7063315` (входы образов заморожены). Рецепты взяты из `20260928g`; каждое отличие записано в `*.recipe-diff.txt` и касается только путей, тега и namespace.

## Хронология
| Время UTC | Шаг | Итог |
|---|---|---|
| 05:12 | native-a на `0e3f4edf` | FAILED: в DeepStream и Savant native-образы не попадает `checkpoint_study_reference.hpp` → [`native-a.failed-01-missing-header`](native-a.failed-01-missing-header/). Исправлено в `8622c0a9` (test-first, `software-v2-native-include`). |
| 05:15–05:19 | native A/B и worker на `8622c0a9` | A==B. Сборки устарели после следующего исправления заголовка → `*.superseded-8622c0a9`. |
| 05:19 | runtime на `8622c0a9` | FAILED: DeepStream runtime компилирует с `-Werror`, заголовок даёт misleading-indentation → [`runtime_images.failed-01-werror`](runtime_images.failed-01-werror/). Исправлено в `3a7f799d` (test-first). |
| 05:23–05:28 | native A/B, worker, runtime ×4 на `3a7f799d` | native A==B (receipt `57f1a9f3…`), worker `5509b370…`, runtime ×4 rc=0 |
| 05:29 | refreeze: capture ×4 → assemble → verify-patch | rc=0, patch `938a2cdd…`. Ожидаемые блокеры `analytics_worker:{cpu,gpu}_identity_changed_requires_parity_refresh` снимает parity (5.3). |
| 05:30 | packaged checks, попытка 1 | ошибка адаптера: каталог `tests/` не importable → [`packaged_checks.failed-01-loader`](packaged_checks.failed-01-loader/) |
| 05:31 | packaged checks, попытка 2 | **23/23 passed** |

## Неизменность входов worker2
[`worker_images/input-equality-vs-20260928g.v1.txt`](worker_images/input-equality-vs-20260928g.v1.txt): у обоих worker совпадают `source_set`, `dependency_set` и `build_context`, `registry_sha256` тоже равен. Различаются только base, build и image ID, производные от них labels и digests, `image_inspect_sha256`. Это следствие нового native base (Amendment 2).

## Адаптация packaged checks
Replay берёт те же 23 команды из `20260926d` с той же картой 9 image ID. Отличия от прогона `20260928g` (записаны в `summary.json`):
- **Пути и тесты.** Монтируются текущие тесты и configs корня. Старые файлы тестов больше не соответствуют коду: clock-изменения затронули service-clock и bridge тесты.
- **Helper-файлы `20260926d`** скопированы в `packaged_inputs_20260926d/` с проверкой SHA256.
- **`expected_packaged_sha256`** — это SHA256 текущего исходника с тем же именем. Исходник обязан быть в allowlist runtime-образа.
- **`tests_run`** — число тестов, которое host loader находит в том же смонтированном файле. Bridge 9→10 и sidecar 50→55: тесты добавлены в PR5 и в этом change.
