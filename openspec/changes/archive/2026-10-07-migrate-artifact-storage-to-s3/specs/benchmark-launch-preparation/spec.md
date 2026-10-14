## MODIFIED Requirements

### Requirement: Cloud admission uses an actual dated guarantee
Remote full-campaign capacity admission SHALL require a current explicit operator guarantee in bytes, with UTC timestamp/reference, bound to the existing destination, actual 280 Q4 sizing pairs and successful upload/readback. The required capacity SHALL be max(500 GiB, ceil(projected_remote_bytes times 1.25) plus 5 GiB), using ten repeats. Undated notes SHALL not count as confirmation and capability URLs SHALL not appear in published evidence. New S3 runs SHALL require explicitly typed S3 capacity evidence bound to the exact HTTPS endpoint, bucket, prefix, region and addressing mode, current successful conditional-create/upload/full-readback observation and unchanged Q4 sizing identity. S3 listing, missing quota API, local free space or historical Seafile guarantees SHALL NOT establish available S3 capacity or authorize S3 launch. Legacy Seafile evidence SHALL retain its existing strict destination validation and SHALL NOT be rebound to S3.

#### Scenario: Confirmation missing
- **WHEN** only an old 500-GiB estimate or undated 1500-GB note exists
- **THEN** full-campaign launch readiness SHALL remain blocked without fabricating confirmation; otherwise authorized qualification/Q4 SHALL not be blocked solely by that missing confirmation.

#### Scenario: Sizing or readback exceeds the guarantee
- **WHEN** actual required capacity exceeds the guarantee or upload/readback fails validation
- **THEN** cloud admission SHALL fail and full-run readiness SHALL remain false.

#### Scenario: S3 quota is unknown or an old destination guarantee is supplied
- **WHEN** bucket listing succeeds but no current operator guarantee is available, or an attestation belongs to Seafile or a different S3 destination
- **THEN** S3 full-cloud admission SHALL remain blocked, with qualification/Q4 and historical evidence retaining their original independent scope.

#### Scenario: Current S3 capacity evidence validates
- **WHEN** the dated operator guarantee meets the unchanged required-capacity formula and binds the exact S3 destination, actual accepted 280 Q4 sizing pairs and current successful conditional-create/upload/full-readback observation
- **THEN** only the remote-capacity gate SHALL be satisfied; all existing scientific, qualification, host, source, resource, lifecycle and full-launch gates SHALL remain mandatory.
