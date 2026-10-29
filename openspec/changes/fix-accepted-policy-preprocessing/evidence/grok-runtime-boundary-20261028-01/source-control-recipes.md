# Bounded Grok volume: implementation qualification recipe

Planning scope: amendment44e8cef19d70f555e2f37dd4ea07651bd9b8125f, DraftPR9, same change/branch/C:worktree. This prospective recipe grants no storage/execution authority or fit acceptance. Required exact-head planning CI and delegated AGENT specification approval precede implementation. Whole1.5 and all application/Grok/acceptance gates remain open.

## Fixed native route

Use ONLY the installed LOCAL Microsoft Hyper-V provider, root/virtualization/v2, sole Msvm_ImageManagementService instance, with fixed CreateVirtualHardDisk and AttachVirtualHardDisk calls through Invoke-CimMethod. This exposes44e8's original backend-job contract without changing provider, operation, path, capacity, rights, interface, deadline or acceptance. Independent blocker-plan and provider reviewers agreed this is source qualification within44e8, requiring exact recipe review before code, not a substantive design amendment or CI restart.

Hyper-V2.0 delegates to a compiled830464B nested module, SHA256f410e8332eb7eafbd04a7233d8812dd6235578f163a4b705882c72b01f0de944. No authenticated original provider-job extraction from its New-VHD/Mount-VHD outputs was established. -AsJob yields a PowerShell job, which does not prove VMMS ownership/completion.

Literal new target: E:/VAST-pr9/grok-bounded-review-20261028-07.vhd. Internal capacity134217728B, classic FIXED VHD; candidate V: must be absent in both ordinary/elevated namespaces and immediately before assignment. No generic/remote CIM dispatcher, alternate provider, retries, rollback, detach, deletion, job cancellation, original-store changes, S96/E16 activation or protected-image action is included.

## Original completion contract

Each Hyper-V call retains original ReturnValue and returned Job reference BEFORE a dependent action:
- ReturnValue0: documented synchronous completion, followed by matching postconditions.
- ReturnValue4096: nonnull original local Msvm_ConcreteJob reference. Bind actual CIM Path/server/namespace/class and typed key bindings, retaining InstanceID exactly as present (including null), before refreshing ONLY that reference under the inherited deadline and finite poll count. Require observed JobState7 AND ErrorCode0, then matching postconditions.
- Other code, missing/disappearing/drifting reference, unknown/failed/unfinished state, timeout or inconsistent postcondition: HOLD; retain partials and original identities. Caller exit, cancellation, PercentComplete and unrelated-job listings are not completion proof.

Storage CDXML binds Initialize-Disk to MSFT_Disk.Initialize, New-Partition to CreatePartition, Format-Volume to MSFT_Volume.Format and Add-PartitionAccessPath to AddAccessPath. These expose synchronous outcomes, without Hyper-V output-job references. Require successful call and exact-object postconditions within the original deadline; failure/timeout holds dependents. Do not invent a provider job.

## Identity/effect order

Before any new directory/file: approved source/admission identities, actual elevated setup token, ordinary caller SID, qualified installed commands/provider/schema, unused namespaces, one original deadline, complete finite peak and fresh physical floors. Default/read-only or failed-prerequisite paths have ZERO storage effects.

Use typed Msvm_VirtualHardDiskSettingData: Type2, Format2, MaxInternalSize134217728, literal Path, reviewed sectors and no parent. Qualify the installed runtime's supported embedded-instance serializer before reliance. Do not use CimInstance.ToString(), hand-built XML or an unqualified serializer envelope.

After original create completion, prove same held file identity/VhdId, normal dense allocation, exact footer/length/type and no reparse/compression/sparse/EFS/hardlink alias. Logical134218240B includes512B footer; rounded allocation on4KiB E: is134221824B.

Attach without a drive letter, settle original backend completion, then authenticate exactly ONE newly added RAW disk: expected size, no partitions, false boot/system/cluster, actual CIM Path/UniqueId. Reverse Get-VHD for that disk must join the SAME held new backing file/VhdId. Disk number alone is insufficient.

Revalidate ownership before EVERY effect. Initialize ONLY the proved actual disk object as GPT; create the aligned basic-data partition from its returned object; format ONLY the proved returned partition as NTFS4096B. Verify disk/partition/backing joins and fresh volumeGUID/serial/geometry/usable capacity/private ACLs before V: assignment. Never select all RAW disks or format by letter.

Grok retains its ordinary principal. Setup privilege never transfers to it. Independently validate the setup receipt in the ordinary process before separately admitted private copy/model phases. Keep immutable source/.g5/.gm2 and every failure. Mutable outputs require directory/filesystem custody compatible with legitimate lock/replace, with sealing after original process/Job retirement and settled I/O.

## Capacity terms still open

Approved authoring16MiB retains ALL earlier charges:2455MiB/C73.3564453125GiB. This recipe uses its existing named ordinary-record slot.

Read-only facts: C:/E: NTFS allocation4096B; vmms/vmcompute Running, vds Stopped; current token nonadmin. No service/storage/elevation action occurred. Four existing enabled Circular logs have maxima1052672B each for VMMS Admin/Operational and VHDMP Operational, plus33554432B StorageManagement/Operational. Charge the full36712448B WITHOUT baseline credit. Candidate C73.3906364441GiB leaves7096750080B inside80GiB.

These EVTX caps do NOT bound SetupAPI/PnP text logs or every native outside writer. E129MiB includes134221824B VHD and only1044480B exterior metadata remainder; setup fit remains UNVALIDATED. Prospective E free-space threshold71002226688B includes inherited65GiB reserve and1GiB floor. Full pagefile, C40GiB, retained failures and other floors remain mandatory. Close exterior terms or separately review a derived exterior allowance BEFORE allocation; do not enlarge the128MiB execution filesystem to hide them.

## Controlled behavior contract

Test the actual orchestrator, fake only boundary I/O, and make every real storage call a tripwire. Assert effect trace/exact object custody/returned facts/first and identity-distinct causes, not source-string similarity. Required cases:

1. Default invocation: zero storage effects.
2. Missing/foreign/unapproved authority: zero effects.
3. Nonadmin token: zero effects.
4. Expired inherited deadline: zero effects.
5. Occupied V: in either namespace: zero effects.
6. Existing/aliased target or parent: zero effects.
7. Insufficient/unknown complete C:/E: peak: zero effects.
8. Success using synchronous and exact original-job completion; joins precede effects.
9. Wrong backing/footer/VhdId: stop before attach/initialize.
10. Missing/extra/foreign RAW or reverse-joined disk: no initialization.
11. Foreign partition/volume: no format/assignment.
12. Provider failure retains original cause; no next operation.
13. Unknown job retains identity/state; no retry/detach/delete.
14. Midstep identity drift or new V: occupation stops the next effect.
15. Partial persistence/close failures retain truthful extent and distinct causes; all closers attempted.

Controlled success is not live privilege/device/fit proof. Preserve meaningful original RED/GREEN and obtain independent exact-source review before setup admission/OS-action request. No Pester install or replay of consumed D-stage cases is needed.

## Primary sources

- [Create](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/createvirtualharddisk-msvm-imagemanagementservice)
- [Attach](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/attachvirtualharddisk-msvm-imagemanagementservice)
- [Original job](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/msvm-concretejob)
- [Typed settings](https://learn.microsoft.com/en-us/windows/win32/hyperv_v2/msvm-virtualharddisksettingdata)
- [Reverse Get-VHD](https://learn.microsoft.com/en-us/powershell/module/hyper-v/get-vhd?view=windowsserver2025-ps)
- [Initialize](https://learn.microsoft.com/en-us/windows-hardware/drivers/storage/initialize-msft-disk)
- [Format](https://learn.microsoft.com/en-us/windows-hardware/drivers/storage/format-msft-volume)
- [Allocation](https://learn.microsoft.com/en-us/windows/win32/api/winbase/ns-winbase-file_standard_info)
- [File rights](https://learn.microsoft.com/en-us/windows/win32/fileio/file-security-and-access-rights)
- [SetupAPI logs](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/setting-the-directory-path-of-the-text-logs)

## Installed client-only serialization and identity qualification

Actual pwsh7.5.5/.NET9.0.14/MI1.0.0.0 client-only serialization produced1442B UTF16LE without BOM: full root INSTANCE CLASSNAME=Msvm_VirtualHardDiskSettingData, exactly seven typed properties, no MI_XML envelope. All seven property names/types/values and text/byte XML roundtrips passed. Pass the full Unicode-decoded serializer result; do not extract/reconstruct its XML. MicrosoftDocs' example passes the full result to a Hyper-V embedded-string parameter (ModifySystemSettings, not a VHD-specific example): https://github.com/MicrosoftDocs/windowsserverdocs/blob/main/WindowsServerDocs/manage/windows-admin-center/use/vm-conversion-extension-faq.yml#L120-L158 .

All four original qualification commands/returns, including two intervening refusals, are retained in the15920B source-control packet, SHA2567b366108626d886c305b8cf7b72f4a4cca620a318e728c67b0b6c36c05ecc594. Those refusals were a CimDeserializer call without class metadata and an XML control using PowerShell's adapted .Name instead of .LocalName; neither queried/refused the provider. No file, provider call, storage effect or elevation was involved in these controls.

Additional actual client-only reflection confirms MI CimSystemProperties exposes four readable strings: ClassName, Namespace, Path, ServerName. Installed Get-CimInstance has mandatory InputObject:CimInstance in its two input-object parameter sets. Refresh ONLY the retained returned Job object through Get-CimInstance -InputObject; never use enumeration or remote overrides. Preserve/compare its actual Path/server/namespace/class and typed key bindings. Do not invent nonnull InstanceID: Microsoft's job documentation is inconsistent about that property. Missing/insufficient identity or foreign server holds the operation.

ClientOnly does not validate the installed provider schema. Elevated read-only qualification of the exact service, class/property types and TWO method signatures still precedes every storage effect. Original provider result/reference and success postconditions remain mandatory. Primary identity/refresh sources:
- https://learn.microsoft.com/en-us/dotnet/api/microsoft.management.infrastructure.cimsystemproperties?view=powershellsdk-7.4.0
- https://learn.microsoft.com/en-us/powershell/module/cimcmdlets/get-ciminstance?view=powershell-7.5#-inputobject

This qualification revision replaces8584B/6b718e04035a15b4b879572c67d564cd69a68df25f0855a23ffdecb27def13cf only as a prospective recipe. The earlier reviews remain historical; independently review this precise clarification before code.

## Additional installed metadata qualification originals (append-only)

This public original-evidence append preserves the preceding exact 11,282-byte recipe prefix, SHA256 77c6b793bb7626e90dc53e3be41a53d995a4f2df143fe2dba822e8f804b7fbfa. It adds no implementation, storage, provider, privilege or execution authority. No private payload was read or included.

Encoding: gzip/Base64 of exact UTF-8 JSON. Decoded original JSON: 30,929 bytes; SHA256 72be38f960fb3b2a48cf4899541b65c49f97bd90ace4ad82559223b70a7e8b42. Gzip: 5519 bytes; SHA256 f7eb6651d2737a95580f79b3d1a23a25960cc8097a04922d59064c144ac5bf95. Base64: 7360 ASCII characters.

The packet retains every literal command and original return for MI member/refresh reflection, the initial PE selector with no matching definitions, the revised PE reference inspection, installed Get-VHD output property/enum metadata, and generated Storage CDXML parameter metadata. These are client-only/metadata observations; no provider or storage command was invoked.

```gzip-base64
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
```


## Existing capacity diagnostics: original read-only outcomes

These historical observations do not establish storage fit or grant setup, elevation or model admission. Native return objects are preserved; the Node census retains returned values and explicitly discloses its unavailable outer wrapper.

RawUTF8bytes=11019; SHA256=fca396849d65d92271456b4cf05ca13793727bbb8df5b93a9c9b6e7d61e50de1; codec=gzip+base64

H4sIAAAAAAACCt1a63PbNrb/VzCc7ErcUhRFUi9q3DRxnTZbu+lNsskH08uByEMJDQUwACRLtfW/3zkgqYcfqZtu587eT6LwOMB5/w6AG0ulogQrsmDNlGZ8lkigmeDFJklpSVOmN0nG6IwLpVmqklKCArmimgme4DDLsUopVsApT8GKbqyCaZC0SKicLRfAtbIi6y2kYgUSMpJLsSB6DiQVi7IADRnRQhSdlBYF2U0hjBM9Z4pIWDG4BklSwVcglVl3QrjQBNaQLnE+nVHGXcuxONVsBYkEvZQcl30j2YxxWpixSSoWC8ozUvUTMf0VUo1LaMo4ZLhmvuQprqCI0kKCISoySFLganlEsSICGVnRYgkPEmskSn4WGZBZIaa0UBMiGhJiqUGSi9NfyLWkZQmSXFNlWNtRwe2yqi2nU8lSqiHDXeH26AySnOlEyKSSBaqEZgumFBPcinJaKNjuxIISVlZ0eWMVdAqFFVkK9LKkJUskzJjScpOgsFVCeZbkbA1ZUohZkrMCkgVomlFNLcdCdRl72YvUcqwDbd9Y6SKzIuvZmZRCvjAC/UVCDhJ4Cietd1qUrZg/01R9eiuu1cnlqSgKqATv/gAcJEvdc6b0ZSXWq6so4nDdtmOeCwk0nbfN5A8MrlHQ37UvL1gqhRK5dj8yHvju25ojHHIVRc3fQeg8dWjg2/ZNzIlZ6SVVcPKML4tiYv7/BJvqb8yJlpub/aBHyf8Em6soelMCx3E/webxTf/IVnAVRecipcUFTeeMg7Nj2D7YQbOqi2TfLadItfXuzav3H1+8PYvjHf04/sh4Jq5VHJ8upQSuP4BEI4njd2gDLeeZMRY75oSwvG1YIx34TJq17JudutwXWda+FDJDf7767gZt5uRSacn47Gq3zYkJFFyfVJS39iQVXDO+hC0uYsb9TBegTr5rN4u4P4D+gO5kOtr27cc5SOi8MUZAbp4lpLOgOp2T1r/Pxay1tSe41x0l91QsuSadmSaD0L7RcymuSauxbcLpAkhKy5bZwJEh4XQ0pD0t++aQtHsOfKbnhnTPH32Jdq0dxrOTe2xh655orUjTc3/sfpxjtPEFu8Xhb0rjPVdR9L34WeizdUl5dsZXTAqOblkxNWmUePL7+kOWTnabmHxCjo5GITdGlKQRFbaQzu84ZCMI3OpHITPnSUP/B4faeyt0V3uxmXHVTqBQcKg4Y8OtczH7hep562A6U0kGOV0WOmE8P2kf829CesVI62/vNkrD4q0Q+m9xzHjectrPgK+iffs3rarDtvcSdoWeg0xKqudJ4wodjOOPbKHa/7GTNf+MW24b37xn7/CZeH/CP7VcwgQDvRGpOvG2Nq61zTFJFZubfTzgcDceoMV+z1QpFLTt7eT+UIxO9j48HgzexnxbJ4FXrDBxwJ4ceeU50LwK760mU7kZrNxCzFrOvSZXFNlhMy3LuyPrJjOysSU0jJN/CsY7+EUeVS3ZbQm5fA9KVxM65xXcMX92FInpfL8pgeCUeq3XGhYnP4Du4MejM18JmcJkL5hvDp1175VmK9ONBnWyI17HqQnVWrLpEvuOFG/GvNh1brfoLzdPW+pOPN82ynsLalnow4kGUZ60djjyPsyoAMYBrGhNmr6TvR2/Fy+kpJu2PWn8JGMSUi3kxsyuGTc7N9kFuDbotd4jtuVstpQVWE3nlM9g19kgKFFCNaDhrBL9e1jrkwMGb08NANXvReefSnDSORULFIkine+h1HMyQru4xGnuGU9FhkKPon+9fzXCmP5yo8G4a3tH3TbpZNQbe7t80ogDoWG51HVGuTwVXIkCIcFHyTScMw4HZCzHuhbyU8akFVmnURz/S4FUcaw6tDOlBVVzsYpjNxUZrOMYh2oJoOI4Z+sOTVMoNWSdUhQs3XRKCaUUKSjF+CyOP7x4995yrELMWAMoHWtB10m1wUSLT4BI2/c8b+tYDbStIbiBgvMl/5QwxIPTQT4eI1a8pkWRaLaAREEqeKasyHN7g/5wNB44WIjoBHdrRd4BSbNUkqIMragXBI5V7cGKrJu4qmJiK4qtP2J2seXghKo7RmwcWxguDaE9ZjTD0B1M+7mYncMKCtOKadG0mlxmmkwYja2oHwxGo6E/Hm6dh8gG/p8le+XE1iOeUfOyI343WBqKJnjEqLzBwPfHTmzt44aZ9UKmc7aC2DIcPEoM46khWIeIeFd6PDirjsJ/fMaj66AgDv2/6aia74eAg/57UWBHNJYxt7ZbZ18unSVc54rxXCRCZoxTuamtMgPOaPFHaqNcLTUrSEWONHTJWfTf48152g8Gj3mzNxz0hsMjZ+495szDA1c2JSPpR+RFitvG4heFC5l7Xx+wLguWMr339AVds8VyYRx9StNPy/KgtDXo5j9Wv0725es94PLX16VfLkon/59K0smDldp3bUT1F3SN2f8d+w1aTuvFUouXRuvnYmZQQcvBUTPGZ/u+fdsFXZuZOyjYIJx7aJd08CDmsTKVdDD4UMbVvoD8E5XWHpjv97TdVbp1Q4O/n15nYsnxcBE3+T+u3x4ue+3tdu9j3+xg4fYvr0sOAWD7KbB2F4ek0FWeOYC1GCB2bEyOMej2d0Fl3/46VBl64/A+qvyvgZO9/hMSEO310xF9FE72wuFw3HsinAzHT4eTj6u7gpMY054OJQ9C2KOI6Hfp3I98X0/rXsD806TqOPt0Og9A468S0106f0ZMD+zpa8X0CKkvickg3GPw2gDUq6MrCnPKj45So5xFWiaJ6ZdQFknyq7qHdYxrWCsqMT68KNlLRLYMjw6uMPe2sYcTkZPLgzOXomg5rQxWYvrr/o/URf0nzWeLmQx88/fKvkFAgnTKk9Zp1K0zf7c6Zgn8busbPsFupU/oNWWa5Oq0vnxylaa6XZo4qLSr2G/wbRD0+2EY+HYV4AxMa7emBpETHGEinW1ITu9TRJdG7SPValXMh+pk6mrxzny3W0ud9wYFtGzXnDi3u5dxvPa9Thyvh3B1M3D8/mDbndnPn19eGSJmGArNdV0O1+Qd6HZN2M1ZoUG21cm33XMxaz+PLuj61v1H+3mECr/FY59bU/vdXlD16bayp1vcom3fXtD1uZjdGlD04pfXcey2n0cZrG5pWdq3O3PuMleD0m1l2/bV5FiTbrlU87Y50Im4Y8q+aOoW5qzIUXPq9wdRSstTuSm1cFMJVMOPVM3braqzZbvLMqMa2lPbzdgM12nNYd2ynSb0JTWvUS0HVxUshbbnhJ7twBozwK6rWvjbEA8aUyNdsG++tGNABUdgcs7z5+AuQCk6g6293dZm+5rnZ1wbq20/qO+Myfah6b3++VXLublmeo5ixoM6FeFB6Na2G3WtT75du0wZS7H//vfuvxvrP1ZB+3kUx+7tM7vRwNrFbdvGYo+21jA+CI8N11y1kULMSE4XrNiQypUPjLgSDoZB0PTQLwH98mgR++aLjnRHBt3WN1Btd3K0xqH8qwG12dQuuLW3GFTeQlm41wgicKy5ZZzWGoyOFeo0BxXmRtGwGR2tuLUnWJsxXWA0es1ViXc+jCtNiwIy0tg/OarozcWLMtekU7HkWSXHTi3H3aXlfSwBWVMQRjfWna2bO1IkfHBFioHMcqojEysKh2Ov74WOVfmHFVlpNvSzIBsP6dTPM5qPYQy9cTCmo/GU5tMxHUAW9vxBSMHrDXxv5NExDCEbZ/1pEEyHlmPddSUrurROqaZFlassxzp/88Ob87MPZ+f4XbVeYPR27mejfVudVqoGE2WqTww1zdcut+LN8p1Tl8Om+sCnmoZhy3IeSKrWFaIudPl9GmzkuU8Ze2n2xv3+wDsUpu+n46k/nIa9fBCkMAhoj+ahN6S9wRAGUzoKYJiOvZHXp8F02h8Ox6NBnvf6YR4EdNB7RJh3+T/k+kggNWcPsH1POF9mtU6Ie1bHXq/nH3AapOnYG4492k/DoDccenRAgaZemo8G/WkQjiFMgQ76ad73vNAPsmDkDYJe3x/1/UEvDZ7IqWHsKew8LBkjjy9wepjt97wGoReMDn0kAOj1Mz/ohSHNRt40mA7SqU/9YZj6NAzzMPPyIc283Mum00GYQr8f+gEMwvHYG9A0e5zZxxX2lTZ/j9krx7ofwR4OFLByfc/ve0MvSHphOOiH9V52wSMI+4F/IL/7c8e9UeJ5/XEY3JnrDwM/8L4wd+AFfpj0fC8I7q4besNR/8tzB7huP/DC/p25/Z43GI8fm3s0tj5O3l5ttyg0yVaQNU+ImIm3n7i45gmsgGsUpga5wGYllhKfEFl48daRUAqJz3tysZTklMl0WVBJLqojPlTca471r6pe4KjqUdDnJUgGGZlujt8PuQd2ORj2/DAcORY+QRK8AsKXPa/vD4a+c/e3AZtXjjWlCgrGIUklZExbERapjSCwWq4Osrq0OjfPCJ7FG0BapSg6RVBPdq8Gqo2TTFTvmZSm04KpOaFkTmVG8qVeSiB0NpMwo7qiRITE50HATfozSc8l7+dQiQlBWkbq9fHoNAeqCSX6WnTMZqhSy0VZPaKipDojJWjqkKnwgr10ycsaRlcORliGS+Wbh/KuY/Zd+0W3KYeJggXl+FjMPJ/SefVuqjow3+Vko6mNefFUH/CSi1fvyW+CAx76UnLwzqxap5bKTIprPScpsILx2YSkldAJLQqR1huoJF4grZRynLyiBUPh4NOznuOFoROOvJdEwoIynoF0yVkBKyM9hIsdLPnJ5yUtWM5qqkaDpDboSvL1fCLh85LJ6mVWKYXBLogoVvPMvIgTM5bSImnyXRD6vZEfeo4lK9CShN54cNht+g0tPJXKkrOeP75gL/dD+v5gECACWfKGtSyZC4UXIDVLVtTzwjAcGSPF84ykYAtmnuP9LPZ4CnFnSTeFoBXrzt4+q4rTIWBEYxTx4cfviSkQmOBdqjVN51hJdnMhF1TjazeHLEQG5oGc3KC1Ns8ISXU4hM8EK4stJcPuCuzi0pUNl8tpwdID6NfgMoJKcYweCqb0IShE2zYm2a10j8BeLLWhii/wkMn6hqjSEVvg7U0VcUwWmWtdqqjbLYBK7i52R5qpWHSBd5aqe13B5g5a4TWV0M3QEqTq1jvtNpGgo2GtO4WYYa39n6GLgu3oOXR293wdfFnSEblp/YsW3DFUVFCyU2Aq/UOL4G/gd2nJ8IuJVBddrjrNdwfDQ7ISxXIBiUns02Weg/yKJdAEmOguqNIgTbDrYDwFzOXNe8qD3L1zpfF47PdDb7v9X1QDKEoLKwAA


## Incident: unplanned debugger extension initialization

The original static-image debugger invocation unexpectedly initialized its extension gallery. Internal writers, network activity and descendant retirement were not bounded or established. These remain UNKNOWN for task1.5; this is no capacity or setup admission. No further debugger invocation is permitted by this record.

RawUTF8bytes=26759; SHA256=3d62df3bd6cabd88b79c5e6752de9f8ae0b5de5720b5a09fd5af29e63c0fe099; codec=gzip+base64

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


## Fresh transport successor v2 — proposed, not yet invoked

Exact UTF-8/LF caller: 5644 bytes, SHA256 7d1a4ada57dade966f70c15b34d320b1e421356fc58edff2aab3bc2f1cc5b4c6. The final LF immediately before the closing fence belongs to the caller. Earlier invocations and failures remain preserved in PR9; this source needs separate finite entry approval. No metadata, elevation, VHD or model authority follows.

```python
import base64,ctypes,gzip,hashlib,json,os,sys,types
from pathlib import Path
root=Path(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST")
base=root/"openspec/changes/fix-accepted-policy-preprocessing/evidence"
def snapshot(path,size,pin):
    before=path.lstat()
    if path.is_symlink() or before.st_size!=size or before.st_nlink!=1 or getattr(before,"st_file_attributes",0)&0x400: raise ValueError("source custody")
    descriptor=os.open(path,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT)
    try:
        opened=os.fstat(descriptor)
        raw=os.read(descriptor,size+1)
        after=os.fstat(descriptor)
        if (opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns)!=(before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns) or (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns)!=(opened.st_dev,opened.st_ino,opened.st_size,opened.st_mtime_ns): raise ValueError("source drift")
        if len(raw)!=size or hashlib.sha256(raw).hexdigest()!=pin: raise ValueError("source pin")
        return raw
    finally: os.close(descriptor)
raw=snapshot(base/"grok-runtime-boundary-20261028-01/grok_bounded_model_capture_v1.proposed.py",50200,"b892bb9a46bfbce2be2db8c8d18bc9d7929c4a2a43190785e42068da862faff7")
jobraw=snapshot(base/"blocker-implementation-20261026-01/grok_reviewed_job_definitions_v1.proposed.py",7981,"54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3")
module=types.ModuleType("pr9_frozen_metadata_worker_controls")
exec(compile(raw,"authenticated-metadata-worker","exec"),module.__dict__)
job=module.load_reviewed_job_definitions(jobraw)
observe=module.WindowsObservation()
for drive,minimum in (("C:\\",120*1024**3),("E:\\",66*1024**3)):
    available=ctypes.c_ulonglong()
    query=ctypes.WinDLL("kernel32",use_last_error=True).GetDiskFreeSpaceExW
    query.argtypes=[ctypes.c_wchar_p,ctypes.POINTER(ctypes.c_ulonglong),ctypes.c_void_p,ctypes.c_void_p]
    query.restype=ctypes.c_int
    if not query(drive,ctypes.byref(available),None,None) or available.value<minimum: raise ValueError("fresh capacity")
environment={key:os.environ[key] for key in ("SystemRoot","WINDIR","TEMP","TMP") if key in os.environ}
rows=[]
for mode in ("control_normal","control_descendant","control_overflow"):
    original_deadline=observe.tick()+30000
    result=module.capture_literal(mode=mode,executable=sys.executable,cwd=root,environment=environment,deadline_tick_ms=original_deadline,job_type=job,observation=observe,private_outputs=None)
    facts=result["facts"]
    channels=result["private_channel_bytes"]
    errors=[] if result["private_primary"] is None else [{"code":result["private_primary"][0],"type":type(result["private_primary"][1]).__name__}]
    errors.extend({"code":code,"type":type(error).__name__} for code,error in result["private_secondary"])
    row={"facts":facts,"prefixes_base64":[None if value is None else base64.b64encode(value).decode("ascii") for value in channels],"errors":errors}
    rows.append(row)
    closed=facts["active_after_retirement"]==0 and facts["returncode"] is not None and facts["job_handle_closed"] and facts["process_handle_closed"] and all(facts["pipe_handles_closed"]) and all(facts["parent_writers_closed"]) and all(value["eof"] and value["io_settled"] and not value["quarantined"] for value in facts["channels"])
    expected=facts["complete"] if mode=="control_normal" else not facts["complete"]
    if mode=="control_normal": expected=expected and channels==[b"out\n",b"err\n"] and not facts["forced"]
    if mode=="control_descendant": expected=expected and facts["forced"] and facts["primary_code"]=="capture_read" and errors==[{"code":"capture_read","type":"TimeoutError"}]
    if mode=="control_overflow": expected=expected and facts["channels"][0]["overflow"] and facts["channels"][0]["written_prefix_bytes"]==1024 and facts["primary_code"]=="channel_overflow" and errors==[{"code":"channel_overflow","type":"OverflowError"}]
    known=(facts["deadline_exceeded"] is False and facts["secondary_codes"]==[] and facts["cause_overflow"] is False
        and type(facts["original_pid"]) is int and facts["original_pid"]>0
        and type(facts["original_creation_filetime"]) is str and facts["original_creation_filetime"].isdigit()
        and type(facts["retirement_completed_tick"]) is int and type(facts["retirement_end_tick"]) is int
        and facts["retirement_completed_tick"]<facts["retirement_end_tick"]<original_deadline
        and len(channels)==2 and all(type(value) is bytes and len(value)<=1024 and len(value)==channel["written_prefix_bytes"]
            and channel["close_completed"] is True and channel["write_extent_unknown"] is False
            and channel["retention_failed"] is False and channel["remainder_unknown"] is False
            for value,channel in zip(channels,facts["channels"])))
    row["expected"]=bool(expected and closed and known)
    if not row["expected"]: break
original=json.dumps({"scope":"three_sequential_owned_transport_controls_successor_v2","rows":rows,"storage_operations":0,"configuration_changes":0,"capacity_accepted":False,"application_authority":False},separators=(",",":"),ensure_ascii=True).encode("ascii")
if len(original)>16384: raise ValueError("public control output cap")
print(json.dumps({"bytes":len(original),"sha256":hashlib.sha256(original).hexdigest(),"codec":"gzip-base64","original_gzip_base64":base64.b64encode(gzip.compress(original,mtime=0)).decode("ascii")}))
if any(value is not None for value in module._QUARANTINED_READERS):
    sys.stdout.flush();os._exit(2)
sys.exit(0 if len(rows)==3 and all(row["expected"] for row in rows) else 1)
```


## Read-only metadata closed-schema encoding bound (source-only)

This is one pure DATA construction against driver43,339/87059b9a. It executes no native metadata operation, does not admit entry, and does not close capacity. Native parser callbacks receive fixed in-memory width maxima. The later appended runtime-census function does not change this driver prefix.

Exact Python recipe:

```python
import ctypes,hashlib,importlib.util,json,struct
from pathlib import Path
path=Path("openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01/grok_bounded_model_driver_v1.proposed.py")
with path.open("rb") as stream: source=stream.read(65537)
assert len(source)<=65536
spec=importlib.util.spec_from_file_location("pr9_metadata_shape_only",path)
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
U32=(1<<32)-1;U64=(1<<64)-1;I64=(1<<63)-1;S64=-(1<<63)
api=object.__new__(m.MetadataWin32)
api.create=lambda *args:17
api.close=lambda handle:True
def basic(handle,pointer):
    p=pointer._obj
    p.attributes=U32;p.serial=U32;p.links=U32
    p.size_high=I64>>32;p.size_low=U32;p.id_high=U32;p.id_low=U32
    return True
def standard(handle,kind,pointer,size):
    assert kind==1 and size==24
    p=pointer._obj;p.allocation=I64;p.eof=I64;p.links=U32;p.delete_pending=0;p.directory=0
    return True
def volume(handle,label,label_size,serial,maximum,flags,filesystem,filesystem_size):
    assert label_size==261 and filesystem_size==64
    serial._obj.value=U32;filesystem.value="NTFS";return True
def device(handle,code,inp,insize,out,outsize,count,overlapped):
    data=bytearray(outsize)
    if code==0x90064:
        assert outsize==96
        struct.pack_into("<Q",data,0,U64)
        for offset in (8,16,24,32,56,64,72,80,88):struct.pack_into("<q",data,offset,S64)
        for offset in (40,44,48,52):struct.pack_into("<I",data,offset,U32)
    else:
        assert code==0x900f4 and outsize==80
        struct.pack_into("<QQ",data,40,U64,U64)
    ctypes.memmove(out,bytes(data),len(data));count._obj.value=len(data);return True
api.basic=basic;api.standard=standard;api.volume=volume;api.device=device
native_ntfs=api.ntfs_e()
paths=(r"E:\$MFT",r"E:\$LogFile",r"E:\$Secure",r"E:\VAST-pr9")
facts={"v_namespace":{"absent":False},"ntfs_E":native_ntfs}
facts.update({name:api.file_metadata(path) for name,path in zip(("E_MFT","E_logfile","E_secure","E_parent"),paths)})
class WideError(OSError):pass
WideError.__name__="e"*128
def error():
    value=WideError();value.winerror=U32;return value
length=lambda value:len(m.bounded_json(value,262144))
records=[];chosen=[]
for name,value in facts.items():
    options=[
        {"operation":name,"complete":False,"deadline_exceeded":False,"facts":value},
        m.metadata_failure(error(),name),
    ]
    if name!="v_namespace":
        options.extend((
            m.metadata_failure(ExceptionGroup("bounded",[error(),error()]),name),
            m.metadata_failure(m.MetadataReadCloseError(value,error()),name),
            {"operation":name,"complete":False,"deadline_exceeded":None,"facts":value,
             "clock_failure":m.metadata_failure(error(),"observation_clock")},
        ))
    record=max(options,key=length);records.append(record)
    chosen.append({"operation":name,"maximum_candidate_bytes":length(record)})
parent={"sid":m.SID,"elevated":True,"pid":U32,"creation_filetime":str(U64),
        "boot_filetime":str(U64),"free_bytes":{"C:\\":U64,"E:\\":U64}}
from types import SimpleNamespace
ready=SimpleNamespace(v_absent=lambda:False,ntfs_e=lambda:native_ntfs,
                      file_metadata=lambda path:facts[dict(zip(paths,("E_MFT","E_logfile","E_secure","E_parent")))[path]])
tick=I64-180001
body=m.collect_metadata(I64-1,now=lambda:tick,api_factory=lambda:ready,parent_check=lambda:parent)
body.update(complete=False,deadline_exceeded=False,finished_tick_ms=I64)
body["records"]=records+[m.metadata_failure(error(),"completion_clock")]
fallback={"scope":"metadata_terminal_failure","collection_returned":True,"completed_collection":body,
          "collection_failure":None,"post_failures":[m.cause("stdout_write",error()),m.cause("stdout_flush",error())],
          "stdout":{"known_written_bytes":6144,"write_extent_unknown":False,"write_completed":False,"flush_completed":False},
          "complete":False,"capacity_accepted":False,"application_authority":False}
result={"scope":"pure_closed_schema_size_bound_not_operational_evidence","source_bytes":len(source),
        "source_sha256":hashlib.sha256(source).hexdigest(),"maximum_collection_bytes":length(body),
        "collection_ceiling":6144,"maximum_fallback_bytes":length(fallback),"fallback_ceiling":8192,
        "per_operation_candidates":chosen,
        "assumptions":["six fixed operations","actual native parser keys/width maxima","128-character diagnostic type upper bound",
                       "read/close group at most three causes; completed-read close at most two",
                       "include one extra completion-clock failure and conservative longest header scalars",
                       "post-collection write+flush faults at most two; encoder fault writes no stdout bytes",
                       "OS native values are integers/booleans/fixed strings; no external text fields"],
        "capacity_accepted":False,"execution_authority":False}
print(json.dumps(result,separators=(",",":")))
assert length(body)<=6144 and length(fallback)<=8192

```

Complete actual tool return:

```json
{"chunk_id":"405f6e","wall_time_seconds":2.6229906,"exit_code":0,"original_token_count":287,"output":"{\"scope\":\"pure_closed_schema_size_bound_not_operational_evidence\",\"source_bytes\":43339,\"source_sha256\":\"87059b9acd9635200e690b1465d64bbe1b0a23edca8e52fa5ef28ea0423e6641\",\"maximum_collection_bytes\":4725,\"collection_ceiling\":6144,\"maximum_fallback_bytes\":5371,\"fallback_ceiling\":8192,\"per_operation_candidates\":[{\"operation\":\"v_namespace\",\"maximum_candidate_bytes\":305},{\"operation\":\"ntfs_E\",\"maximum_candidate_bytes\":1054},{\"operation\":\"E_MFT\",\"maximum_candidate_bytes\":618},{\"operation\":\"E_logfile\",\"maximum_candidate_bytes\":626},{\"operation\":\"E_secure\",\"maximum_candidate_bytes\":624},{\"operation\":\"E_parent\",\"maximum_candidate_bytes\":625}],\"assumptions\":[\"six fixed operations\",\"actual native parser keys/width maxima\",\"128-character diagnostic type upper bound\",\"read/close group at most three causes; completed-read close at most two\",\"include one extra completion-clock failure and conservative longest header scalars\",\"post-collection write+flush faults at most two; encoder fault writes no stdout bytes\",\"OS native values are integers/booleans/fixed strings; no external text fields\"],\"capacity_accepted\":false,\"execution_authority\":false}\r\n"}
```


## Proposed source-fix census successor (01/02 consumed/HOLD)

Original child deadline90s including retirement; active1/512MiB Job;65536B channels;262144B complete public original and1MiB outer wire. Source4 and Python3.14.7 pins are literal. This ordinary same-SID snapshot includes explicit C/E free-space guards, no protected E metadata query, no elevation, VHD operation or Grok request. All controlled Python startup uses only the fixed five Windows environment variables; the disposable tool-shell environment must be cleared before startup. ExactHEAD is checked separately before/after, not inside this Python caller. Entry requires independent review and a fresh separate approval.

```python
import base64,ctypes,gzip,hashlib,json,os,re,sys,types
from ctypes import wintypes
from pathlib import Path
root=Path(r"C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST")
here=root/"openspec/changes/fix-accepted-policy-preprocessing/evidence/grok-runtime-boundary-20261028-01"
pins={"capture":{"bytes":49678,"sha256":"fa7ffe33b2a6d460a01074cf4e3a1a67f02cd8e6be0700adac9fa2756ccc38ca"},"driver":{"bytes":65441,"sha256":"11282e873d7f580a6165c6c7a561ed75e88db42b2e98de89b9866418b01348ed"},"guard":{"bytes":13365,"sha256":"5dee93c6b04c37144fad47aafb72153de90f9bf5e88dc5e40e7119a9c8ca963d"},"jobs":{"bytes":7981,"sha256":"54f1e5d8cd33ac0c1735325722f10d222bfc41fd91432f21bd792a79b231ddb3"}}
kernel=ctypes.WinDLL("kernel32",use_last_error=True)
tick=kernel.GetTickCount64
tick.argtypes=[];tick.restype=ctypes.c_ulonglong
deadline_text=os.environ.get("PR9_CENSUS_OUTER_DEADLINE","")
if not deadline_text.isascii() or not deadline_text.isdecimal() or len(deadline_text)>15:
    raise ValueError("inherited outer census deadline")
original_deadline=int(deadline_text)
if str(original_deadline)!=deadline_text or not 0<original_deadline-tick()<=90000:
    raise ValueError("inclusive outer census deadline")
capture=None
custody=None
errors=[]
close_facts=None
remaining=None
retirement=None
finished=None
principal=None
def failed(phase,error):
    if not any(error is old for _,old in errors):
        errors.append((phase,error))
def typed(phase,error):
    seen=[]
    def visit(value,depth=0):
        if any(value is prior for prior in seen) or len(seen)>=16 or depth>3:
            return {"type":"unavailable","detail_bound":True}
        seen.append(value)
        name=type(value).__name__
        row={"type":name if re.fullmatch("[A-Za-z0-9_]{1,128}",name) else "unavailable"}
        if isinstance(value,BaseExceptionGroup):
            row["causes"]=[visit(child,depth+1) for child in value.exceptions[:16]]
            row["cause_bound_exceeded"]=len(value.exceptions)>16
        return row
    return {"phase":phase,**visit(error)}
def retire_census_custody(custody,failed):
    facts={"returned_causes":None,"close_causes":None,"close_failure_count":None,
           "close_cause_bound_exceeded":None,"retired":None,"remaining_handles":None,"available":[]}
    try:
        value=custody.retire()
        facts["returned_causes"]=value
        facts["available"].append("returned_causes")
    except BaseException as error:
        failed("runtime_retirement",error)
    for field in ("close_causes","close_failure_count","close_cause_bound_exceeded","retired","remaining_handles"):
        try:
            value=len(custody.handles) if field=="remaining_handles" else getattr(custody,field)
        except BaseException as error:
            failed("runtime_observation_"+field,error)
        else:
            facts[field]=value
            facts["available"].append(field)
    return facts
def snapshot(path,expected,content=True):
    before=path.lstat()
    if path.resolve(strict=True)!=path or before.st_size!=expected["bytes"] or before.st_nlink!=1 or getattr(before,"st_file_attributes",0)&0x400:
        raise ValueError("literal source identity")
    descriptor=os.open(path,os.O_RDONLY|os.O_BINARY|os.O_NOINHERIT)
    primary=None
    raw=bytearray()
    digest=hashlib.sha256()
    count=0
    try:
        opened=os.fstat(descriptor)
        identity=lambda row:(row.st_dev,row.st_ino,row.st_size,row.st_mtime_ns)
        if identity(opened)!=identity(before): raise ValueError("opened source identity")
        while True:
            part=os.read(descriptor,min(65536,expected["bytes"]-count+1))
            if not part: break
            count+=len(part)
            if count>expected["bytes"]: raise ValueError("source grew")
            digest.update(part)
            if content: raw.extend(part)
        if count!=expected["bytes"] or digest.hexdigest()!=expected["sha256"] or identity(os.fstat(descriptor))!=identity(opened) or identity(path.lstat())!=identity(opened):
            raise ValueError("source pin changed")
    except BaseException as error:
        primary=error
    try:
        os.close(descriptor)
    except BaseException as error:
        if primary is not None and error is not primary:
            raise BaseExceptionGroup("source read and close",[primary,error])
        raise
    if primary is not None: raise primary
    return bytes(raw)
try:
    if Path.cwd()!=root or tuple(sys.version_info[:3])!=(3,14,7) or any(getattr(sys.flags,key)!=1 for key in ("isolated","no_site","no_user_site","dont_write_bytecode")):
        raise ValueError("fixed isolated runtime")
    if Path(sys.executable)!=Path(r"C:\Python314\python.exe"): raise ValueError("fixed executable")
    snapshot(Path(sys.executable),{"bytes":106208,"sha256":"4942b86a6597e5aee0128daa00050ed79bc21f6e709a78eb19cbfeb0c2f39ac9"},False)
    admin=ctypes.WinDLL("shell32").IsUserAnAdmin
    admin.argtypes=[];admin.restype=wintypes.BOOL
    if admin(): raise ValueError("ordinary same-SID census required")
    advapi=ctypes.WinDLL("advapi32",use_last_error=True)
    token=wintypes.HANDLE()
    current=kernel.GetCurrentProcess
    current.argtypes=[];current.restype=wintypes.HANDLE
    opener=advapi.OpenProcessToken
    opener.argtypes=[wintypes.HANDLE,wintypes.DWORD,ctypes.POINTER(wintypes.HANDLE)]
    opener.restype=wintypes.BOOL
    close=kernel.CloseHandle
    close.argtypes=[wintypes.HANDLE];close.restype=wintypes.BOOL
    if not opener(current(),8,ctypes.byref(token)): raise ctypes.WinError(ctypes.get_last_error())
    sid=wintypes.LPWSTR()
    token_errors=[]
    try:
        query=advapi.GetTokenInformation
        query.argtypes=[wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(wintypes.DWORD)]
        query.restype=wintypes.BOOL
        needed=wintypes.DWORD()
        query(token,1,None,0,ctypes.byref(needed))
        if not 0<needed.value<=65536: raise ValueError("bounded token")
        buffer=ctypes.create_string_buffer(needed.value)
        if not query(token,1,buffer,len(buffer),ctypes.byref(needed)): raise ctypes.WinError(ctypes.get_last_error())
        convert=advapi.ConvertSidToStringSidW
        convert.argtypes=[ctypes.c_void_p,ctypes.POINTER(wintypes.LPWSTR)];convert.restype=wintypes.BOOL
        if not convert(ctypes.cast(buffer,ctypes.POINTER(ctypes.c_void_p))[0],ctypes.byref(sid)): raise ctypes.WinError(ctypes.get_last_error())
        if sid.value!="S-1-5-21-3110146144-1192974603-3912567380-24130": raise ValueError("same SID")
        principal={"sid":sid.value,"elevated":False}
    except BaseException as error:
        token_errors.append(error)
    finally:
        if sid:
            try:
                release=kernel.LocalFree
                release.argtypes=[ctypes.c_void_p];release.restype=ctypes.c_void_p
                if release(ctypes.cast(sid,ctypes.c_void_p)): raise ctypes.WinError(ctypes.get_last_error())
            except BaseException as error: token_errors.append(error)
        try:
            if not close(token): raise ctypes.WinError(ctypes.get_last_error())
        except BaseException as error: token_errors.append(error)
    if token_errors: raise BaseExceptionGroup("principal read and closure",token_errors)
    boot_buffer=ctypes.create_string_buffer(48)
    boot_length=wintypes.ULONG()
    boot_query=ctypes.WinDLL("ntdll").NtQuerySystemInformation
    boot_query.argtypes=[ctypes.c_int,ctypes.c_void_p,wintypes.ULONG,ctypes.POINTER(wintypes.ULONG)]
    boot_query.restype=ctypes.c_long
    if boot_query(3,boot_buffer,48,ctypes.byref(boot_length))!=0 or boot_length.value!=48: raise ValueError("bounded actual boot")
    principal["boot_filetime"]=str(int.from_bytes(boot_buffer.raw[:8],"little"))
    principal["free_bytes"]={}
    space=kernel.GetDiskFreeSpaceExW
    space.argtypes=[wintypes.LPCWSTR,ctypes.POINTER(ctypes.c_ulonglong),ctypes.c_void_p,ctypes.c_void_p]
    space.restype=wintypes.BOOL
    for drive,minimum in (("C:\\",120*1024**3),("E:\\",66*1024**3)):
        available=ctypes.c_ulonglong()
        if not space(drive,ctypes.byref(available),None,None) or available.value<minimum: raise ValueError("fresh retained peak floor")
        principal["free_bytes"][drive]=available.value
    raw=snapshot(here/"grok_bounded_model_driver_v1.proposed.py",pins["driver"])
    driver=types.ModuleType("pr9_authenticated_census_driver")
    exec(compile(raw,"authenticated-census-driver","exec"),driver.__dict__)
    custody=driver.RuntimeCustody()
    sources={}
    for role,path in driver.SOURCE_PATHS.items():
        custody.hold_ancestors(path);custody.hold(path)
        sources[role]=snapshot(path,pins[role])
    custody.hold_ancestors(Path(sys.executable));custody.hold(Path(sys.executable))
    snapshot(Path(sys.executable),{"bytes":106208,"sha256":"4942b86a6597e5aee0128daa00050ed79bc21f6e709a78eb19cbfeb0c2f39ac9"},False)
    worker=types.ModuleType("pr9_authenticated_census_worker")
    exec(compile(sources["capture"],"authenticated-census-worker","exec"),worker.__dict__)
    job_type=worker.load_reviewed_job_definitions(sources["jobs"])
    observe=worker.WindowsObservation()
    encoded_pins=base64.b64encode(json.dumps(pins,separators=(",",":")).encode("ascii")).decode("ascii")
    environment={"SystemRoot":r"C:\Windows","WINDIR":r"C:\Windows","USERPROFILE":r"C:\Users\s-a-balashov",
        "TEMP":r"C:\Users\s-a-balashov\AppData\Local\Temp","TMP":r"C:\Users\s-a-balashov\AppData\Local\Temp",
        "PR9_METADATA_DEADLINE_TICK":str(original_deadline),"PR9_METADATA_DRIVER_SHA256":pins["driver"]["sha256"],
        "PR9_RUNTIME_CENSUS_PINS":encoded_pins}
    capture=worker.capture_literal(mode="runtime_census",executable=r"C:\Python314\python.exe",cwd=root,
        environment=environment,deadline_tick_ms=original_deadline,job_type=job_type,observation=observe,private_outputs=None)
except BaseException as error:
    failed("census_entry",error)
finally:
    if custody is not None:
        retirement=retire_census_custody(custody,failed)
        close_facts=retirement["returned_causes"]
        remaining=retirement["remaining_handles"]
    if principal is not None and "boot_filetime" in principal:
        try:
            after_boot=ctypes.create_string_buffer(48)
            after_length=wintypes.ULONG()
            if boot_query(3,after_boot,48,ctypes.byref(after_length))!=0 or after_length.value!=48:
                raise ValueError("bounded post boot")
            principal["post_boot_filetime"]=str(int.from_bytes(after_boot.raw[:8],"little"))
            if principal["post_boot_filetime"]!=principal["boot_filetime"]: raise ValueError("boot changed")
        except BaseException as error:
            failed("post_boot",error)
    try: finished=tick()
    except BaseException as error: failed("completion_clock",error)
public_capture=None
if capture is not None:
    public_capture={"facts":capture["facts"],"prefixes_base64":[None if raw is None else base64.b64encode(raw).decode("ascii") for raw in capture["private_channel_bytes"]],
        "causes":([] if capture["private_primary"] is None else [typed(*capture["private_primary"])])+[typed(*row) for row in capture["private_secondary"]]}
original={"scope":"ordinary_fixed_runtime_census_capture_v1","source_pins":pins,"principal":principal,
    "original_deadline_tick_ms":original_deadline,"finished_tick_ms":finished,
    "capture":public_capture,"causes":[typed(*row) for row in errors],"runtime_close_causes":close_facts,
    "remaining_runtime_handles":remaining,"runtime_retirement":retirement,"capacity_accepted":False,"application_authority":False}
raw=json.dumps(original,separators=(",",":"),ensure_ascii=True).encode("ascii")
if len(raw)>262144: raise ValueError("complete original frame ceiling")
wire=json.dumps({"original_bytes":len(raw),"original_sha256":hashlib.sha256(raw).hexdigest(),
    "original_gzip_base64":base64.b64encode(gzip.compress(raw,mtime=0)).decode("ascii")},separators=(",",":"))
if len(wire)>1048576: raise ValueError("complete outer wire ceiling")
print(wire)
sys.stdout.flush()
if any(value is not None for value in getattr(worker,"_QUARANTINED_READERS",())) if "worker" in globals() else False:
    os._exit(2)
sys.exit(0 if not errors and capture is not None and capture["facts"]["complete"] and close_facts==[] and remaining==0 and retirement["close_failure_count"]==0 and retirement["close_cause_bound_exceeded"] is False and retirement["retired"] is True and len(retirement["available"])==6 and finished is not None and finished<original_deadline else 1)
```


## Proposed complete ordinary outer command (not executed)

Composition is fixed DATA substitution only: replace the single __PROGRAM_DATA__ with the immediately preceding exact Python block excluding its final LF, and __PROGRAM_SHA256__ with its SHA256. The hash check restores that LF; the native -c program omits it. No delimiter occurs in the fixed DATA. Full composed command is retained in RAM for lossless PR publication and exact peer review before entry; no placeholder is executed. The outer90s deadline is inherited before Python starts, with1s reserved for original-controller retirement. The caller samples actual boot before/after; exactGitHEAD is checked separately outside this command before/after. stdout/stderr inherit bounded tool capture; originalchildchannels64KiB,completeoriginal256KiB/1MiBwire. Metadata:Python12581B/SHA61370a8382d46378141813471b477d69c6bc9ad4349e5d9ab68bd6b648eeda1a,fullPowerShell16540B/SHA61694bee558641a9e0d5af59577cb47f79b0c136ab1790dcfddcc8759a78bc49.

```powershell
$ErrorActionPreference='Stop'
$pr9Deadline=[Environment]::TickCount64+90000L
$pr9Program=@'
__PROGRAM_DATA__
'@
if([Convert]::ToHexString([Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($pr9Program+([char]10)))).ToLowerInvariant() -cne '__PROGRAM_SHA256__'){throw 'frozen census program hash'}
$pr9Process=$null;$pr9Started=$false;$pr9Id=$null;$pr9Creation=$null
$pr9Exited=$null;$pr9Exit=$null;$pr9Forced=$false;$pr9Closed=$null
$pr9Causes=[Collections.Generic.List[object]]::new()
$pr9Seen=[Collections.Generic.List[object]]::new()
function Add-Pr9CensusCause([string]$Phase,[Exception]$Problem){
    foreach($prior in $pr9Seen){if([object]::ReferenceEquals($Problem,$prior)){return}}
    $pr9Seen.Add($Problem)
    $name=$Problem.GetType().Name
    if($name -notmatch '^[A-Za-z0-9_]{1,128}$'){$name='unavailable'}
    if($pr9Causes.Count -ge 8){throw 'fixed outer cause bound'}
    $pr9Causes.Add([ordered]@{phase=$Phase;type=$name})
}
try {
    $info=[Diagnostics.ProcessStartInfo]::new()
    $info.FileName='C:\Python314\python.exe'
    $info.UseShellExecute=$false
    $info.WorkingDirectory='C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST'
    $info.Environment.Clear()
    $info.Environment['SystemRoot']='C:\Windows'
    $info.Environment['WINDIR']='C:\Windows'
    $info.Environment['USERPROFILE']='C:\Users\s-a-balashov'
    $info.Environment['TEMP']='C:\Users\s-a-balashov\AppData\Local\Temp'
    $info.Environment['TMP']='C:\Users\s-a-balashov\AppData\Local\Temp'
    $info.Environment['PR9_CENSUS_OUTER_DEADLINE']=$pr9Deadline.ToString([Globalization.CultureInfo]::InvariantCulture)
    foreach($a in @('-I','-B','-S','-c',$pr9Program)){$info.ArgumentList.Add($a)}
    if($pr9Program.Length -gt 16000 -or [Environment]::TickCount64 -ge $pr9Deadline-1000L){throw 'original pre-start bound'}
    $pr9Process=[Diagnostics.Process]::new()
    $pr9Process.StartInfo=$info
    if(-not $pr9Process.Start()){throw 'original census controller start'}
    $pr9Started=$true
    $pr9Id=$pr9Process.Id
    $pr9Creation=$pr9Process.StartTime.ToUniversalTime().ToFileTimeUtc().ToString([Globalization.CultureInfo]::InvariantCulture)
} catch {Add-Pr9CensusCause 'start' $_.Exception}
finally {
    if($pr9Started){
        try {
            $left=[Math]::Max(0L,$pr9Deadline-[Environment]::TickCount64-1000L)
            $pr9Exited=$pr9Process.WaitForExit([int][Math]::Min(90000L,$left))
            if(-not $pr9Exited){
                $pr9Process.Kill($false);$pr9Forced=$true
                $left=[Math]::Max(0L,$pr9Deadline-[Environment]::TickCount64)
                $pr9Exited=$pr9Process.WaitForExit([int][Math]::Min(1000L,$left))
            }
            if($pr9Exited){$pr9Exit=$pr9Process.ExitCode}
        } catch {Add-Pr9CensusCause 'retirement' $_.Exception}
    }
    if($pr9Process){
        try {$pr9Process.Dispose();$pr9Closed=$true}
        catch {$pr9Closed=$false;Add-Pr9CensusCause 'process_close' $_.Exception}
    }
}
$pr9Wire=([ordered]@{
    scope='actual_ordinary_census_controller_retirement_v1'
    original_pid=$pr9Id;original_creation_filetime=$pr9Creation
    started=$pr9Started;exited=$pr9Exited;exit_code=$pr9Exit
    forced_original_controller=$pr9Forced;process_handle_close_completed=$pr9Closed
    original_deadline_tick_ms=$pr9Deadline;finished_tick_ms=[Environment]::TickCount64
    causes=$pr9Causes.ToArray();ambient_console_input_owned=$false
    backend_retirement_inferred_from_controller=$false
    qualification_accepted=$false;capacity_accepted=$false;application_authority=$false
}|ConvertTo-Json -Depth 6 -Compress)
if([Text.Encoding]::UTF8.GetByteCount($pr9Wire) -gt 4095){throw 'outer receipt output bound'}
[Console]::Out.WriteLine($pr9Wire)
if(-not $pr9Started -or -not $pr9Exited -or $pr9Exit -ne 0 -or $pr9Forced -or -not $pr9Closed -or $pr9Causes.Count -ne 0 -or [Environment]::TickCount64 -ge $pr9Deadline){exit 1}
```

Attempts01/02 are consumed/HOLD (originals PR6478524480/6479196653): ValueError without a completed census. This successor joins creation time; the bounded diagnostic remains. Failed stderr remains a raw bounded stream: preserve both complete JSON records plus every partial/trailing byte. The optional second record reports only fixed-source function/line locations, max32 hops/8 retained frames/4096B inclLF. It requires known flushed stderr<=60928B, reserves512B for the existing handler and never retries a diagnostic write. New entry requires exact re-review/fresh separate admission.
Creation slot and producer/consumer column are now birthtime_ns. All seven components remain; missing birth time refuses.
