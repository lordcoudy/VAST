## Why

Пользователь выбрал S3 `https://s3.savva-balashov.me` вместо Seafile для новых выгрузок VAST. Доступ к существующему bucket `vast-archive` через профиль `vast-s3` проверен, но production entrypoint и WSL service сейчас требуют `seafile.txt`, Seafile capacity attestation и Seafile store; одной настройки AWS CLI недостаточно.

## What Changes

- **BREAKING**: новые облачные выгрузки production publication используют только S3; Seafile capability links больше не являются обязательным входом нового запуска. Автоматического переключения обратно на Seafile нет.
- Добавить S3 store для существующих операций preflight, listing, upload/readback, повторной проверки и восстановления архива. Сохранить физическую привязку исходных файлов, потоковый SHA-256 и порядок archive → receipt → durable ledger → local prune.
- Зафиксировать endpoint, bucket `vast-archive`, prefix `vast/`, region `us-east-1`, SigV4 и path-style в несекретном destination descriptor. Credentials брать из выбранного внешнего профиля `vast-s3`, включая работу WSL user service без интерактивной сессии.
- Новые receipts/ledger/checkpoints привязать к типу S3 и точному destination. Существующие Seafile evidence и их строгие readers сохранить; перенос старых данных и продолжение старого run в другом backend не выполнять.
- Заменить Seafile-specific admission для новых запусков на S3 operator capacity attestation с прежней формулой и реальным upload/readback. Отсутствие quota API не считать гарантией свободного места.
- Проверить conditional create, multipart, сбои, восстановления и отсутствие секретов; обновить production runbook. S3 smoke test не запускает benchmark и не выдаёт scientific/full authority.

## Capabilities

### New Capabilities

- `s3-artifact-export`: выбранный S3 destination, безопасная конфигурация/credentials, неизменяемая выгрузка и readback, versioned evidence, восстановление и ограниченные live проверки.

### Modified Capabilities

- `benchmark-launch-preparation`: требование `Cloud admission uses an actual dated guarantee` явно связывает новые S3 запуски с endpoint/bucket/prefix и S3 capacity evidence, сохраняя прежние Q4, sizing и launch gates.

## Impact

Наблюдаемые точки изменения: `scripts/seafile_artifact_store.py` (общие ошибки/physical custody и legacy adapter), `publication_cloud_transaction.py`, `full_publication_runtime.py`, `full_publication_entrypoint.py`, `full_publication_supervisor.py`, `full_publication_wsl_user_service_v1.py`, `run_experiments.py` (существующий child secret-env filter), capacity helpers и operator-neutral `backend_pair_archive_sizing_receipts_v1.py`. Добавятся S3 adapter/config/capacity helpers и закреплённый Python SDK в production/CI dependency closure. Существующие cloud transaction/storage/security/entrypoint/service тесты расширятся; текущая CI уже проверяет OpenSpec, но отдельного автоматического полного conformance gate нет.

Граница: новые облачные benchmark/publication artifacts и их archive/receipt export, а не backup всего репозитория, моделей или datasets. Исторические данные Seafile, объект вне `vast/`, bucket policy/lifecycle и текущий frozen Q1 не меняются. Работа ведётся отдельно от PR #7 `qualify-full-benchmark`; его execution commit `1112af0b53cae995984708390cf9d04c18da3c0d` не переопределяется. Реализация потребует одобрения этой спеки на точном commit в данном Draft PR и отдельного запроса на apply.
