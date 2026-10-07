## 1. Review и prerequisites

- [x] 1.1 Получить review approval planning commit в этом PR и отдельный запрос на apply; сохранить exact commit/решение в PR, не считать OpenSpec validation approval.
- [x] 1.2 Перед dependent edits согласовать implementation base относительно PR #7, сверить scoped исходники с рассмотренной спекой и сохранить source-before; frozen Q1 commit/config/receipts должны остаться byte-identical, а существенный drift пройти update/review.

## 2. Configuration, credentials и dependency closure

- [x] 2.1 Реализовать exact S3 descriptor/parser и canonical destination/run namespace binding; проверить unknown fields, HTTP/userinfo/query/fragment, foreign endpoint, traversal, controls и destination drift отрицательными portable tests.
- [x] 2.2 Подключить pinned botocore1.43.62 с полной production/CI dependency closure и только фактически reachable source manifests; проверить Python3.12.3 import/API model IfNoneMatch для PUT/complete, pip check и existing exact-source/package tests.
- [x] 2.3 Реализовать explicit external profile resolver, безопасный service-UID bootstrap и existing child-env filter для AWS credentials/profile locators без ambient/IMDS/endpoint fallback; проверить Windows source ACL, приватный WSL ext4 owner0700/0600, noninteractive resolution, фактическое отсутствие secrets у measurement children и в argv/manifest/log/error/remote metadata через fault tests.

## 3. Store operations

- [x] 3.1 Выделить минимальный общий store/error/physical-custody contract с сохранением legacy exports/journals; existing Seafile security/materialization/transport tests должны пройти без weakening predicates.
- [x] 3.2 Реализовать S3 run-scoped paginated listing и read-only preflight с bounds1000/page,10000objects/16MiB/deadline; tests должны отвергать repeated token, duplicate/foreign key, malformed size, truncation и overflow.
- [x] 3.3 Реализовать held-FD streaming PUT с atomic IfNoneMatch и full GET hash/size/stability verification; real-file tests должны проверить mutation/rebind/alias, matching reuse, collision/no overwrite, short/oversize/wrong hash и ETag-only rejection.
- [x] 3.4 Реализовать sequential bounded multipart64MiB parts,64MiB threshold и8MiB streaming без transfer threads; проверить seekable same-FD ranges, boundary sizes,10000parts limit, conditional completion и source-before/after custody.
- [x] 3.5 Реализовать durable owned multipart intent (2active/run,2MiB/intent,10000parts) и crash/ambiguous-complete recovery; fault tests должны подтвердить bounds, HTTP200 embedded-error rejection, verify-before-reupload, exact-owned abort, preservation чужих uploads и явные cleanup failures/leftovers без remeasurement.
- [x] 3.6 Реализовать safe S3 materialization поверх общей held-inode/no-replace machinery; physical fault tests должны проверить interrupted download/fsync/rename, foreign stage, existing target, path escape и corrupt archive rejection.
- [x] 3.7 Подключить allowlisted error sanitization, explicit SDK attempts1 и remaining-deadline transport containment; проверить75 для supported transient,78 для integrity/config/auth/TLS/unsupported/unexpected, отсутствие reset/retry/fallback и bounded cleanup.

## 4. Evidence и publication transaction

- [x] 4.1 Реализовать exact новые S3 ledger/pending/receipt/preflight schemas и destination/key/version binding; проверить mixed/unknown versions/keys/backend, tampered hash chain и чужой namespace, сохранив exact legacy validation fixtures.
- [x] 4.2 Подключить S3 к существующему archive→readback→receipt→readback→durable ledger→prune path; test_publication_cloud_transaction и новые boundary faults должны подтвердить запрет раннего prune и сохранение acceptance/article-statistics bindings.
- [x] 4.3 Реализовать supported S3 checkpoint recovery/restore; test_publication_storage_recovery и новые real-file crash cases должны подтвердить reverify-before-owned-prune, отсутствие accepted-arm remeasurement и backend/destination switch rejection.

## 5. Capacity, entrypoint и WSL service

- [x] 5.1 Добавить S3 operator capacity builder/validator с dated guarantee, exact destination, real preflight и original280 Q4 sizing/projection; negative/positive tests должны сохранить max500GiB/1.25/+5GiB/10 repeats и отказ для missing/stale/foreign Seafile/S3 guarantee.
- [x] 5.2 Подключить новый cloud-config/capacity input, store factory и identity guards в full_publication_entrypoint/runtime; entrypoint/runtime tests должны подтвердить отсутствие seafile.txt dependency у новых S3 runs и неизменные scientific/resource/model/full gates.
- [x] 5.3 Подключить S3 config/credential locators в WSL service materializer/manifest/argv/validator и supervisor; existing service/supervisor regressions и drift/secret faults должны подтвердить noninteractive UID binding, sanitized evidence и zero unexpected retries.
- [x] 5.4 Добавить ограниченный S3 operator preflight/setup helper для existing bucket/fresh probe namespace; CLI tests должны подтвердить запрет bucket/policy/global-delete/workload operations и smoke bounds, не выдавая capacity или benchmark grant из list-bucket success.

## 6. Integration и conformance

- [ ] 6.1 Выполнить portable/native/source checks текущего implementation commit с full inventory, exact skip identities и source-before/after; сохранить результаты и не заменить полный existing CI focused suite или историческим количеством tests.
- [x] 6.2 Выполнить один ограниченный live S3 smoke в fresh owned prefix: PUT, multipart8MiB+1byte, matching reuse, conflicting PUT/complete, full readback и restore; сохранить sanitized report/source/config/SDK/time/keys/outcomes, проверить original bytes после collision и явно перечислить leftovers при любом failure.
- [x] 6.3 Проверить credentials из WSL user service UID1000 без interactive shell и без запуска benchmark/containers; сохранить только безопасные locator/access facts, permissions и actual result.
- [x] 6.4 Получить и проверить dated available-capacity guarantee после actual Q4 sizing, если full-cloud admission требуется сейчас; иначе сохранить отдельный явный blocked disposition и не отмечать capacity accepted. Deliverable: validated attestation либо честный missing-evidence record без подставленного числа.
- [ ] 6.5 Составить conformance report для каждого requirement/scenario обеих delta specs: implementation location, exact test/manual evidence, расхождения и непроверенные факты; review должен разобрать gaps, не заменяя CI или live behavior OpenSpec format check.

## 7. Документация и завершение в том же PR

- [x] 7.1 Обновить current runbook, PLAN.md, progress.md и безопасный config/env example с S3 commands и раздельными configured/write/capacity/launch states; проверить реальные flags и shell syntax, сохранить frozen Q1 и исторические Seafile dispositions.
- [ ] 7.2 Push implementation в этот же PR и получить required CI на exact latest commit плюс conformance/source review; отсутствующие/failed обязательные checks должны оставаться blocking.
- [ ] 7.3 После фактического завершения implementation выполнить reviewed delta sync/archive навыком openspec-archive-change в этой же ветке; проверить обе capabilities, сохранность всех artifacts/.openspec.yaml, отсутствие незавершённых acceptance gaps и commit/push archive в тот же PR.
- [ ] 7.4 Пройти latest archive-head CI и финальное exact-commit approval; merge выполнять только после отдельного разрешения, с проверкой что approvals/archive/checks относятся к текущему head.
