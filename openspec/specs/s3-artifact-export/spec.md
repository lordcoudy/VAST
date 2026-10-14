# S3 Artifact Export

## Purpose

Обеспечить выгрузку новых облачных артефактов VAST в выбранный S3 с проверяемым сохранением байтов, восстановлением после сбоя и безопасным удалением локальных копий только после подтверждённой долговременной записи.

## Requirements

### Requirement: Новые выгрузки используют явно связанный S3 destination

Новые production cloud runs SHALL использовать HTTPS endpoint `https://s3.savva-balashov.me`, bucket `vast-archive`, prefix `vast/`, region `us-east-1`, SigV4 и path-style из проверенного несекретного descriptor. Destination identity SHALL включать backend, endpoint, bucket, prefix, region и addressing mode; run/checkpoint SHALL сохранять эту identity. Новые cloud runs SHALL не требовать `seafile.txt` и SHALL не переключаться на Seafile при ошибке. Это требование SHALL охватывать существующие publication archive/receipt exports, а не автоматический backup inputs или всех локальных файлов.

#### Scenario: Новый запуск имеет корректную конфигурацию
- **WHEN** оператор подготавливает новый production cloud run с выбранным S3 descriptor
- **THEN** все его remote artifacts SHALL размещаться только внутри `vast/`, с сохранением существующих matrix/run/pair/content-hash имён, и destination SHALL входить в frozen launch identity.

#### Scenario: Endpoint или ключ объекта небезопасен
- **WHEN** конфигурация содержит HTTP, userinfo, query/fragment, альтернативный endpoint, пустой либо escaping prefix, traversal/control characters или ключ вне выбранного prefix
- **THEN** подготовка SHALL завершиться ошибкой до сети/запуска/выгрузки без нормализации в другой destination или fallback.

#### Scenario: Destination изменён при восстановлении
- **WHEN** backend, endpoint, bucket, prefix, region или addressing mode отличаются от checkpoint
- **THEN** resume SHALL отклоняться без переизмерения, переноса accepted pairs и изменения исторического evidence.

### Requirement: Credentials доступны сервису и не попадают в evidence

Windows tooling и WSL user service SHALL использовать явно выбранный внешний профиль `vast-s3` без передачи credentials через CLI argv, Git, launch manifest, remote metadata или опубликованные receipts. Service SHALL проверять доступ к выбранному credential source от своего UID до workload launch, исключать неявные ambient profiles/metadata credentials/другой endpoint и сохранять TLS certificate validation. Секреты, подписи, authorization headers и presigned URLs SHALL не появляться в логах, исключениях и conformance. Ротация credentials для той же identity SHALL требовать нового credential preflight без изменения существующих receipts; смена credential source/principal внутри frozen service context SHALL блокировать зависимые операции до явно подготовленного нового контекста.

#### Scenario: Сервис стартует без интерактивного shell
- **WHEN** WSL user unit использует тот же UID и явно подготовленный внешний `vast-s3` profile
- **THEN** credential resolution SHALL работать без Windows shell environment и интерактивного login; report SHALL содержать только безопасную конфигурацию и результат проверки.

#### Scenario: Профиль отсутствует или подменён
- **WHEN** выбранный credential source отсутствует, небезопасен, недоступен service UID либо ambient variables пытаются заменить его
- **THEN** preflight SHALL отказать до workload launch, сохраняя только sanitized cause без secret values или автоматического выбора другого account.

#### Scenario: SDK вернул секрет в diagnostic
- **WHEN** transport или SDK exception содержит credential, signature, request URL/query или authorization data
- **THEN** сохранённая ошибка SHALL содержать только разрешённые operation/status/code/stage facts; traceback/log/repr SHALL не раскрывать исходные secret-bearing поля.

### Requirement: Выгрузка создаёт объект без перезаписи и подтверждает все байты

Upload SHALL сохранять существующую physical custody локального единственного regular file от hashing через streaming. PUT и завершение multipart SHALL атомарно запрещать replacement существующего ключа. Уже существующий объект SHALL приниматься только после полного readback с совпадением размера и SHA-256; другой payload SHALL давать permanent integrity failure без overwrite/delete. Система SHALL проверять полный response body, а не принимать ETag, metadata checksum или успешный HTTP status как замену SHA-256. Unsupported conditional-create behavior SHALL блокировать cloud readiness, а не заменяться listing/HEAD-then-unconditional-write.

#### Scenario: Обычный и multipart upload завершаются
- **WHEN** новый small object или большой archive записан условным create и полностью прочитан обратно
- **THEN** успех SHALL требовать точного byte count/SHA-256 и неизменной physical source identity; multipart SHALL не менять критерий whole-object integrity.

#### Scenario: Совпадающий или конфликтующий ключ существует
- **WHEN** ключ уже занят либо другой writer первым завершил conditional create
- **THEN** matching full readback SHALL позволять idempotent verified reuse, а wrong size/hash SHALL оставаться permanent failure без изменения объекта.

#### Scenario: Файл или remote stream изменён
- **WHEN** held source/named file/ancestor изменяются, readback short/oversize либо завершённый stream имеет неверный hash
- **THEN** upload verification SHALL отказать и локальные raw/archives SHALL сохраняться; trace SHALL не утверждать verified result.

#### Scenario: Multipart прерван
- **WHEN** upload не завершился, завершение неоднозначно либо процесс погиб
- **THEN** checkpoint SHALL сохранять accepted pair и исходные файлы; восстановление SHALL сначала проверять готовый объект, затем продолжать или завершать только принадлежащий этому run upload с точным source/destination binding. Чужие uploads/objects SHALL не удаляться.

### Requirement: S3 receipts и ledger сохраняют порядок долговременной записи

Новые S3 cloud receipts, ledger entries и checkpoint bindings SHALL иметь явные version/backend/destination identity и exact object key/size/SHA-256, а VersionId SHALL сохраняться когда возвращён сервером. Upload archive и полный readback SHALL предшествовать upload receipt и его readback; оба SHALL предшествовать физически durable hash-chained ledger commit и local prune. Restore SHALL заново проверять ledger, destination и full archive bytes и сохранять существующие no-replace/owned-staging/fsync/unsafe-archive rejection guarantees. Новый ledger SHALL не смешивать backends или schema versions.

#### Scenario: Receipt или ledger commit не завершились
- **WHEN** archive проверен, но receipt upload/readback либо durable ledger commit отказали или были прерваны
- **THEN** local prune SHALL не начинаться; supported recovery SHALL использовать ту же accepted pair без повторного benchmark.

#### Scenario: Crash после ledger или во время prune
- **WHEN** восстановление видит durable verified S3 receipt/ledger и незавершённый owned prune
- **THEN** оно SHALL повторно проверить remote bytes и продолжать только существующий безопасный prune state machine без дополнительного acceptance или remeasurement.

#### Scenario: Архив восстанавливается из S3
- **WHEN** пользователь восстанавливает ledger-pinned pair в свежий owned destination
- **THEN** exact S3 destination/key/version при наличии, size и SHA-256 SHALL проверяться до no-replace publication; corruption, path escape, alias, чужая staging inode или существующий target SHALL отклоняться.

### Requirement: Ошибки S3 сохраняют действующую recovery policy

Supported connection/timeout/incomplete-read, throttling и retryable server/storage failures SHALL сохранять transient exit 75 и checkpoint recovery. Завершённый wrong size/hash, conditional collision с другим содержимым, invalid configuration/credentials/access denied, unsupported server semantics и unexpected failures SHALL сохранять permanent exit 78. Defaults SHALL оставлять zero unexpected retries; SDK/transport attempts SHALL быть ограничены и учитывать существующий absolute operation deadline без его сброса. Transport recovery SHALL не повторять measurements accepted arms.

#### Scenario: Endpoint недоступен или throttled
- **WHEN** разрешённая transport operation получает supported transient failure
- **THEN** run SHALL приостановить new-pair admission с exit 75, оставить local data и восстановимый checkpoint, сохранив bounded sanitized failure facts.

#### Scenario: Доступ запрещён или содержимое неверно
- **WHEN** S3 отказывает в доступе или full readback не соответствует ожидаемым байтам
- **THEN** run SHALL остановиться с exit 78 после разрешённой ограниченной проверки без unexpected retry, fallback или raw cleanup.

### Requirement: Listing и preflight ограничены destination namespace

Cloud preflight SHALL проверять selected bucket/prefix и обрабатывать полный paginated inventory только этой namespace в заданных bounds; truncated/unbounded/duplicate/inconsistent listing SHALL не считаться ready. Listing SHALL включать только видимые объекты, а multipart leftovers SHALL учитываться отдельно. Read-only доступ SHALL не выдавать write/readback, conditional create или capacity authority.

#### Scenario: Namespace содержит несколько страниц
- **WHEN** S3 возвращает continuation tokens
- **THEN** проверка SHALL обработать каждую страницу в пределах count/byte/time caps и получить точный inventory/size либо явно отказать; посторонние bucket keys SHALL не входить в run inventory.

#### Scenario: Поддержка сервера проверяется на owned smoke namespace
- **WHEN** проводится явно помеченный live smoke test
- **THEN** он SHALL проверить PUT и multipart conditional create, полный readback и restore только в свежей принадлежащей проверке namespace внутри `vast/`; ограниченный report SHALL сохранить реальные результаты, остатки/cleanup limitations и нулевые benchmark/scientific/full grants.

### Requirement: Исторические Seafile данные сохраняют исходные bindings

Legacy Seafile records/readers SHALL сохранять свои exact schemas, capability/destination checks, hashes и исходные outcomes. Новые S3 credentials SHALL не разрешать чтение исторического Seafile run как S3, rewriting, bulk migration или resume с другой storage identity. Frozen Q1 source/config/receipts SHALL не меняться в результате настройки нового export backend.

#### Scenario: Существующий Seafile run открыт для проверки
- **WHEN** reader получает корректный legacy Seafile ledger и его исходный backend context
- **THEN** прежняя strict validation SHALL оставаться доступной без переписывания records и без создания S3 success evidence.

#### Scenario: S3 настройка представлена как Q1 acceptance
- **WHEN** готовый S3 profile, smoke report или новая migration implementation используются для утверждения Q1 readiness/acceptance
- **THEN** эти artifacts SHALL не заменять frozen Q1 host/source/execution gates и SHALL не запускать или переопределять Q1.
