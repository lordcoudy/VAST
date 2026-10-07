## Context

Мотивация и product scope описаны в [proposal.md](proposal.md). Исследована чистая база `a54d0d991b6279190417f839e4704aabbe54ca9d`, отдельно от PR #7 и подготовленного Q1. Production path: entrypoint создаёт `SeafileArtifactStore`; runtime вызывает `preflight`/`list_remote_files`; `PublicationCloudTransaction` вызывает `upload_and_verify`, `verify_remote`, `materialize_remote`. WSL service descriptor, argv и supervisor также жёстко связаны с `seafile.txt`. Ledger сейчас имеет exact schema `vast-cloud-ledger/v2`, pending journal `/v1`, remote pair receipt `/v1`; их validators нельзя молча расширить или переименовать.

Существующий store удерживает FD единственного physical source, сверяет named/held/ancestor identity и полный digest, а remote materialization использует immutable intent, lock, held staging inode, fsync и no-replace commit. Cloud transaction обеспечивает проверенный archive, проверенный receipt, durable ledger и owned prune; эти функции остаются основой миграции. Operator-neutral sizing loader уже существует: `load_operator_sizing_rows_v1` в `backend_pair_archive_sizing_receipts_v1.py`.

На 2026-10-07 проверены только credentials/TLS, bucket visibility, HEAD bucket и limited listing. AWS CLI в WSL сообщает `aws-cli/1.46.1`, Python3.12.3, botocore1.43.62. Возможности конкретного S3 сервера по conditional writes, multipart, права записи и capacity ещё не подтверждены. AWS documentation задаёт ожидаемый протокол, а не доказательство совместимости этого endpoint.

## Goals / Non-Goals

**Goals:** новый S3 adapter в существующем transaction path; явная frozen destination identity; immutable create и полный readback; независимый от interactive shell credential source; versioned S3 evidence; preserved legacy read/recovery; проверяемые failures и актуальный runbook.

**Non-Goals:** перенос/удаление Seafile archives, sync всех inputs, новый background uploader, обобщённая plugin registry, public/presigned sharing, управление bucket policy/versioning/lifecycle/quota, запуск qualification/Q4/full/Q1. Остановка на отсутствующей capacity guarantee является корректным результатом настройки, а не поводом ослабить gate.

## Decisions

### 1. Явный S3 descriptor и небольшой общий contract

Добавить versioned несекретный `configs/artifact-storage.yaml` с kind `vast_s3_destination_v1`, backend `s3`, endpoint, bucket `vast-archive`, prefix `vast/`, region `us-east-1`, addressing_style `path`, credential_profile `vast-s3`. Parser требует exact keys/types, HTTPS без userinfo/query/fragment и разрешённый endpoint. Canonical destination digest включает backend/endpoint/bucket/prefix/region/addressing; profile является локальным credential locator, не remote object identity. Descriptor физически проверяется и hash-bound в launch/service context.

Run namespace: `vast/<matrix_sha256>/<run_id>/`, с существующими flat archive/receipt basenames внутри. Это сохраняет provenance имени и позволяет listing одного run, не всего bucket. Проверять matrix hash/run identifier и remote basename до формирования key; запретить абсолютные/escaping/control/empty components. Separate live probes используют `vast/preflight/<fresh-uuid>/` и никогда не проходят run inventory check.

Выделить только используемые store operations и общие error/physical-custody helpers в `artifact_store.py`; добавить `s3_artifact_store.py`. Seafile module сохраняет совместимые exports/import identities и legacy journal semantics. Сохранять точные Seafile schemas и caller predicates. Выбор backend производится при создании нового run либо при explicit legacy reader dispatch; никакого автоматического fallback. Альтернативы: shell `aws s3 cp` не даёт контроля held FD/conditional finalize; большая backend registry здесь не нужна.

### 2. SDK с управляемым streaming, без transfer manager

Использовать закреплённый `botocore==1.43.62` напрямую, без `boto3` transfer manager и фоновых multipart threads. Установить его полную совместимую dependency closure в production requirements и `.ci/requirements.txt`; добавить её в существующие dependency/source manifests там, где imports реально reachable. Проверить API model наличие `IfNoneMatch` у PUT и multipart complete и совместимость с Python3.12.3 до deployment. AWS CLI остаётся отдельным operator tool, а не runtime dependency.

PUT для объектов меньше64MiB; последовательный multipart начиная с64MiB, part size64MiB, stream read chunks до8MiB. Не удерживать целый part/archive в RAM; использовать seekable view того же held FD с ограниченным part range и проверкой source epochs/hash до и после streaming. Для объектов, которым нужно больше10,000 parts по этой фиксированной схеме, отказать до upload с явным size-limit result; не менять sizes/limits во время run. Empty object допускается transport adapter, но acceptance архивов остаётся прежней strict обязанностью transaction layer.

`PutObject` и `CompleteMultipartUpload` отправляют `IfNoneMatch='*'`. При412 заново читать существующий object и принимать только exact expected size/full SHA-256. При409 или ambiguous transport terminal сначала проверять окончательный object; не выполнять unconditional overwrite. Если итоговый object отсутствует, сохранить transient checkpoint; новая multipart attempt допустима лишь в supported recovery того же accepted pair и после abort/reconciliation предыдущего owned upload. Persist owned upload intent/UploadId/source/destination binding для hard crash: максимум2 active intents/run,2MiB/intent,10000 ordered part descriptors и retained local failure facts в прежних enclosing limits; overflow запрещает дальнейший upload. Abort разрешён только exact-owned incomplete upload, failure/leftovers остаются явными. Не менять bucket lifecycle для их уборки. Complete response должен пройти SDK XML/error validation даже при HTTP200 с embedded error; readback и ledger commit до этого запрещены.

HEAD/ETag/metadata — сведения для conditional read, не proof SHA-256. GET использует returned VersionId при наличии, иначе observed ETag как `IfMatch`; весь body имеет exact byte count/full hash, после чтения проверяется стабильность object identity. Без versioning долговременная защита от внешнего администратора не доказана; каждый restore/reverify заново проверяет байты. Server semantics, включая conditional completion, обязательны: их отсутствие блокирует readiness и требует нового design review, не HEAD-then-PUT обхода.

Основание: [AWS conditional writes](https://docs.aws.amazon.com/AmazonS3/latest/userguide/conditional-writes.html), [S3 PutObject](https://docs.aws.amazon.com/AmazonS3/latest/API/API_PutObject.html), [CompleteMultipartUpload](https://docs.aws.amazon.com/AmazonS3/latest/API/API_CompleteMultipartUpload.html). Никакие AWS-specific возможности не считаются поддержанными данным сервером до live проверки.

### 3. Явные credentials и bounded transport

SDK получает credentials только из явно заданного внешнего profile source; service фиксирует безопасный locator, profile и nonsecret principal identity, не credential bytes/hash. Отключить implicit environment/instance-metadata credential fallback, endpoint overrides, SDK wire/debug logging; TLS verify остаётся включённым. Windows использует существующий protected `.aws` profile. Для canonical WSL unit подготовить приватный ext4 profile/config вне Git под service UID, directory0700/files0600 через ограниченный operator setup. Существующий WSL `.aws` symlink на NTFS не считать Linux0600: импорт источника возможен только после явной проверки выбранного Windows path/ACL, без вывода его contents. Проверять конечные физические paths/ownership и доступ service UID без интерактивной среды; manifest/argv содержат только locators. Credentials никогда не копируются в repo/images/evidence. В существующем child-env filter `run_experiments.py` исключить AWS access/secret/session/security-token variables и credential-profile/file locators для measurement children; cloud client остаётся только у publication owner. Проверить actual child environment отрицательными tests, сохранив прежнее исключение Seafile tokens.

Explicit botocore Config: SigV4, path-style, fixed endpoint/region, bounded connect/read waits. `total_max_attempts=1` отключает скрытые SDK retries; разрешённый transport recovery остаётся в existing controller. Global profile `max_attempts=2` не переопределяет runtime contract. Timeout каждой сети не превышает `cloud_timeout_s` и оставшееся время existing outer operation, а backoff/streaming/abort расходуют ту же deadline. Нового relative deadline или повышения benchmark/service limits нет. Если существующий caller не передаёт достаточную deadline, propagated outer containment обязательно до принятия результата, а не только socket timeout.

Sanitized error mapping: network/timeout/incomplete stream,429/5xx и documented temporary storage failure → `ArtifactStoreError`/exit75; completed integrity mismatch → `ArtifactIntegrityError`/exit78; invalid config/profile/TLS trust/access denied/unsupported operations/unexpected exceptions → permanent78. Сохранять allowlisted operation/status/code/stage, не `str(exception)`, headers, signed requests или raw traceback SDK. Fresh credential preflight допускает rotation того же principal вне active frozen context; никаких secret-dependent published fingerprints.

Основание: [SDK configuration](https://docs.aws.amazon.com/boto3/latest/guide/configuration.html), [attempt count semantics](https://docs.aws.amazon.com/boto3/latest/guide/retries.html). Это требования к явному runtime Config; существующая CLI конфигурация не доказывает их выполнение.

### 4. S3 evidence нового формата и прежний commit/prune порядок

Создать exact S3 schemas: `vast-s3-cloud-ledger/v1`, `vast-s3-cloud-ledger-pending/v1`, `vast-s3-cloud-pair-receipt/v1`, `vast_s3_preflight_v1`, `vast_s3_operator_capacity_attestation_v1`. Каждый новый ledger entry связывает immutable destination digest/run prefix и object descriptors (key, size, sha256, version_id or null); receipt сохраняет acceptance/article-statistics/archive bindings. Frozen run identity и service manifest имеют отдельный S3 storage binding. Mixed schema/backend, неизвестные keys/versions и mismatched namespace запрещены. Legacy readers используют прежние точные schemas; S3 receipt не предоставляет legacy full authority.

Сохранить существующие transition states, append hash chain, immutable receipt/pending reconciliation и owned prune machinery; не менять исторические entries. Failure на каждом upload/readback/receipt/ledger/fsync/prune boundary оставляет original state и accepted pair. При resume сначала complete ledger/destination/remote verification, затем существующий recovery. Materialization делит backend-independent held-inode engine с Seafile, сохраняя versioned journal isolation и непрерывную physical custody; extraction по-прежнему проверяет safe members и no-replace target publication.

### 5. Capacity и сервис подключаются целиком

S3 attestation заменяет Seafile-specific binding только у новых runs. Оно содержит exact destination digest, UTC confirmation/reference, available bytes, original280 Q4 sizing descriptors/projection, SDK/source identity и actual verified live preflight descriptor. Формула неизменна: max(500GiB, ceil(projected_remote_bytes×1.25)+5GiB), десять repeats. Ни bucket object totals, ни local free bytes, ни прежнее1500GB сообщение не выдаются за guarantee. Current dated available allocation после учёта других данных подтверждает оператор.

Entrypoint принимает `--cloud-config-file` и S3 capacity input, создаёт S3 store; runtime проверяет run inventory/identity. WSL materializer/validator/argv/launch source descriptors и supervisor получают тот же S3 contract и безопасные credential locators; `--cloud-links-file` остаётся только explicit legacy path. Helper provisions existing bucket/prefix, не создаёт bucket и не меняет account policy. Обновить `PLAN.md`, `progress.md`, runbook и `.env.example` после implementation с честным distinction configured/access/write/capacity/launch-ready. Не переписывать current frozen Q1 документы как принявшие S3.

### 6. Проверка без запуска workload

Portable tests используют controllable S3 responses и настоящие bounded local files/FDs, проверяя негативные ветви и все transaction crash boundaries; отдельный real S3 integration фиксирует exact source/config/SDK/test owner. Listing ограничен run namespace: page≤1,000 rows, total≤10,000 objects, encoded inventory≤16MiB и existing outer deadline. Pagination loops, duplicates, invalid sizes/keys или overflow fail closed; multipart intents имеют отдельный bound и не входят в verified object inventory.

Live smoke в fresh probe prefix: tiny PUT, forced multipart8MiB+1byte (first part8MiB, final1byte), GET/full hash, matching reuse и conflicting PUT/multipart completion, restore в owned temp destination. Разрешение test-only forced threshold не доступно production entrypoint. Максимум4 completed probe objects,64MiB uploaded/readback payload на каждую категорию направления,1MiB report, общий120s плюс cleanup не более15s в remaining outer budget. Probe objects остаются как scoped evidence; DeleteObject permission не требуется. Abort только exact-owned uploads; любой остаток явно записывается. Проверить service credential resolution от UID1000 без benchmark/container start. Listing/read-only checks уже выполнены; write/conditional/capacity acceptance пока не утверждается.

## Risks / Trade-offs

- S3-compatible server может игнорировать/не поддерживать conditional completion → отрицательный live collision test блокирует admission; никаких silent fallbacks.
- Capacity неизвестна → preserve blocked full-cloud readiness до dated operator evidence; это не блокирует отдельно разрешённый Q1/qualification.
- У новых dependencies/source bindings есть влияние на package closure → обновить реальные reachable inventories и affected source checks; не rebind старые image/qualification receipts.
- SDK buffering/stream retry может открыть path заново или скрыть attempt → held-FD range reader, explicit attempts1, portable faults и current-source dependency validation до live use.
- Crash leaves incomplete multipart/receipt → durable owned intents, reconcile before recovery, явные leftovers; не включать global bucket cleanup.
- Remote администратор может позднее заменить/удалить объект → при каждом restore/reverify full hash; Object Lock/versioning policy не обещается и автоматически не настраивается.
- PR #7 меняет часть общих entrypoints → до apply выбрать согласованный merged base либо явно подтвердить order/dependency в этом же PR; resolve planning drift до dependent edits. Q1 execution source остаётся отдельным.
- CI не имеет отдельного full conformance gate → сохранить existing OpenSpec/native/portable gates; добавить requirement/scenario evidence mapping и manual review в этот PR, не называть document validation доказательством поведения. Новый универсальный CI conformance framework — отдельная согласованная задача.

## Migration Plan

1. Одобрить planning commit этого Draft PR, затем отдельно разрешить apply. Не менять frozen Q1, работающий run или прежний PR.
2. В этой же ветке реализовать contract/adapter/evidence/capacity/service path, обновить dependency/source closure и portable regressions. Старые readers должны пройти unchanged legacy fixtures.
3. Пройти current required CI, source-before/after и conformance; выполнить ограниченный S3 smoke и service-UID credential check. Если нет подтверждённой capacity, доставить configured S3 с явно blocked full launch; гарантию не изобретать.
4. Обновить operator runbook и status, выполнить reviewed sync/archive в том же PR, push и latest-head CI/final review до merge. Specification approval и final merge approval — отдельные gates.
5. После merge новые cloud runs материализуют новые S3 bindings. Старый Seafile checkpoint остаётся на исходном reader/backend; bulk migration не производится. Rollback означает остановку новых S3 runs с сохранением local/remote evidence и возврат deployment к прошлой reviewed version; существующий S3 run не продолжается через Seafile, а поддерживается своим versioned S3 reader.

Implementation checkboxes заканчиваются физическим reviewed sync/archive с проверкой сохранности документов. Commit/push archive в тот же PR, latest archive-head CI, финальное exact-commit approval и отдельное разрешение merge остаются обязательными post-archive gates, с evidence на exact PR head. Эти зависимости представлены отдельно, поскольку archive lint требует закрытого implementation checklist до запуска archive-head CI. Такое представление не закрывает будущий gate заранее и не снижает критерии приёмки; исходные failed/pending outcomes сохраняются.
