# 6D.3–6D.7: корень, пересборка runtime ×4, refreeze, проверки и parity на теге `20261008e`

Amendment 7. Корень `E:/STUDY/VAST/tmp/qfb-root-20261007a`, рецепты — копии рецептов 6C со сдвигом тега (`*.recipe-diff.txt`).

| Шаг | Итог |
|---|---|
| 6D.3 корень `C_Q1''` → `C_B'''` `4de28110` ([root-move](root-move/), [root_move_v1.sh](root_move_v1.sh)) | изменённый receipt-bound вход — ровно `scripts/checkpoint_deepstream_runtime.py`; tracked drift нет до и после; engine равен 6A.2 |
| 6D.4 копии ([prep_tag_20261008e.sh](prep_tag_20261008e.sh)) | native-a/native-b/worker и запись engine побайтно равны `20261008d`; native3/worker2 live по ID — 5/5 |
| 6D.4 сборка runtime ×4 ([run_build_6d4.sh](run_build_6d4.sh)), 16:55–16:57Z | rc 0, A==B у всех четырёх; DeepStream `sha256:3a9aa20a…bb984` (новый), Savant `045ccc35…`, OpenVINO GVA `bbdb026a…`, gstreamer_custom `80772c78…` — равны `20261008d` |
| 6D.4 refreeze ([run_capture_6d4.sh](run_capture_6d4.sh)) | capture ×4 / assemble / `verify-patch` rc 0; patch `ceb0900b…34dd` |
| 6D.4 diff patch d→e ([patch_expected_diff_6d4.py](patch_expected_diff_6d4.py), [результат](build_prep/patch-expected-diff.result.v1.json)) | 10 tag, 12 DeepStream, 10 производных хешей, **0 unexpected** |
| 6D.4 сырые inspect ([inspect_refs_6d4.sh](inspect_refs_6d4.sh), [build_prep/inspect](build_prep/inspect/)) | 12/12; у трёх неизменных образов отличается только `Identity.Build` (история BuildKit build refs) → новый `inspect_full_sha256` при том же ID и содержимом |
| 6D.4 live `_verify_live_images` | PASS ([build_prep/live-verify-new-patch.v1.json](build_prep/live-verify-new-patch.v1.json)) |
| 6D.5 packaged checks ([run_packaged_6d5.sh](run_packaged_6d5.sh)) | 23/23 |
| 6D.5 in-image H(a)–(c) | PASS ([in-image-h/SUMMARY.txt](in-image-h/SUMMARY.txt)) |
| 6D.6 parity ([run_parity_6d6.sh](run_parity_6d6.sh)), 17:01–17:13Z | rc 0, accepted 480/32 |
| 6D.6 независимый аудит ([independent_audits](independent_audits/)) | verified: 3 535 descriptors, 2 478 файлов, 480 tensor-пар = A244 |
| 6D.7 корень `C_B'''` → `C_Q1'''` `0aeb955b` ([root-move-cq1ppp](root-move-cq1ppp/), [root_move_cq1ppp.sh](root_move_cq1ppp.sh)) | 5 untracked configs `qfb-20261008e` перенесены в `untracked-configs-before-cq1/` и побайтно равны закоммиченным; drift нет |

Engine равен 6A.2 до и после сборки, refreeze, packaged и parity (`build_prep/engine.*.v1.json`). Перепривязка пинов — [software-v11-repin-20261008e](../software-v11-repin-20261008e/).

**Замечание для Q1.** Любая повторная сборка этих образов до Q1 снова изменит `Identity.Build` и полный inspect — preflight откажет (класс попытки 1). Сборки до конца Q1 не выполняются.
