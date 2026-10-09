# Диагностика шагов 14–15 после попытки 4 (не квалифицирующая)

Решение пользователя 9 октября: диагностический прогон шагов 14–15, без изменения frozen root и без повторов Q1. Скрипты лежат здесь, результаты — `*.result.json`.

## Прогоны

| Прогон | Что | Итог |
|---|---|---|
| A ([diag_a8_validators.py](diag_a8_validators.py)) | stock `publication_policy_qualification._default_fragment_validator` на фрагментах попытки 4, корень read-only | отказ всех 4 систем: DeepStream — нет legacy `artifacts/analytics_execution_bindings/publication_v3/index.json` (зашитые идентичности `checkpoint_deepstream_qualification_fragment_v1.py:50-75`); Savant — `assess_qualification_fragment() missing … 'runtime_image_manifest'`; OpenVINO GVA, gstreamer_custom — `qualification fragment binding values drifted` |
| B ([diag_a8_validators_v2.py](diag_a8_validators_v2.py)) | `validate_publication_policy_qualification_fragment_from_authority_v2` (им transaction v2 строит candidate index, `publication_policy_qualification_transaction_v2.py:428-440`) | **все 4 фрагмента приняты** |
| C ([diag_a8_index.py](diag_a8_index.py)), выход вне корня | индексы in-process с v2-валидатором | отказ: `output_dir must remain under project_root` |
| 1 ([run1](run1-scratch-index.result.json)) | копия корня на ext4 (`/var/tmp/a8-diag-root`, 28 GB) | policy: closure receipt `not readonly` (0555 с drvfs на ext4 — артефакт копии); resource: `deepstream/cpu binding material fields drifted` |
| 2 ([run2](run2-scratch-index-modes.result.json)) | копия, режимы 0555→0444 (как drvfs) | policy: `qualification checkpoint physical input[0] drifted` — closure привязывает физическую идентичность (inode/ctime), копия её не сохраняет; resource — без изменений |
| 3 ([run3](run3-scratch-fragment-only.result.json), [скрипт](diag_a8_index_run3.py)) | policy index без closure; resource с ослабленным `resource_v2_evidence` | policy: `completed qualification index requires an execution closure receipt`; resource: `binding material identity drifted` (ожидается `vast_<system>_resource_binding_material_v1`, у transaction v2 — `vast_publication_policy_qualification_authority_binding_v2`) |
| P ([diag_a8_pilots.py](diag_a8_pilots.py)) | stock `validate_checkpoint_qualification_pilot_acceptance_v1` на 32 pilot acceptance, корень read-only | выполняется (I/O-ёмкая перепроверка; результат будет добавлен в `pilots.result.json`) |

## Выводы (с независимым read-only расследованием кода)

1. **Валидатор фрагментов.** CLI `publication_policy_qualification_index_v2.py` (`main`, fallback :729), `full_resource_qualification_index_v1.py` (:614) и promotion (`publication_policy_qualification.py:986-988`, вызов в `_derive_fragment_bound_manifest` :492) используют legacy `_default_fragment_validator`; параметра выбора нет. Resource promotion фрагменты не перепроверяет.
2. **Схема resource index.** `full_resource_qualification_index_v1._read_binding` (:151-271) ждёт `vast_<system>_resource_binding_material_v1` с `resource_v2_evidence`; такой материал пишет только GVA v3 producer — даже legacy-пути Savant/GStreamer/DeepStream его не давали. `resource_v2_evidence` — статические дескрипторы источников (контракт v2, scope, валидаторы, `native_emitters`), не данные прогона.
3. **Topology contract в resource promotion.** `full_resource_qualification.py:622` проверяет pilots с `contract_version: 1`, а сценарии checkpoint — версии 2 (`configs/experiments.yaml:415,518`); вероятен отказ всех 32 cells.
4. **Ни один тест не проходил 14–15 на реальных выходах transaction v2** — везде fake-валидаторы.
5. **Closure.** Файлы `publication_policy_qualification.py`, `…_index_v2.py`, DeepStream v1 validator входят в execution code closure (AST-граф от 13 seed, `…execution_code_closure_v1.py:26-39`) и в allowlists runtime-образов; `full_resource_qualification*.py` — host-only, вне closure. Правка closure-файлов ломает closure попытки и требует пересборки образов; новый host-only модуль — нет.
6. Проверка шагов 13–15 на копии корня невозможна (физическая идентичность в closure); полноценная предварительная проверка — только в настоящем корне, в отдельных неквалифицирующих namespaces.
