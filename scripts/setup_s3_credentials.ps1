param([string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$credentialPath = Join-Path ([Environment]::GetFolderPath('UserProfile')) '.aws\credentials'
$profileRoot = Split-Path -Parent $credentialPath
$currentSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$allowedSids = @($currentSid, 'S-1-5-18')
foreach ($candidate in @($profileRoot, $credentialPath)) {
    $item = Get-Item -LiteralPath $candidate -Force
    if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'AWS profile source is redirected' }
    $acl = Get-Acl -LiteralPath $candidate
    if ($candidate -eq $profileRoot -and -not $acl.AreAccessRulesProtected) { throw 'AWS profile directory ACL inheritance is enabled' }
    $ownerSid = ([Security.Principal.NTAccount]$acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value
    if ($ownerSid -ne $currentSid) { throw 'AWS profile source belongs to another principal' }
    foreach ($rule in $acl.Access) {
        $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
        if ($rule.AccessControlType -eq 'Allow' -and $sid -notin $allowedSids) { throw 'AWS profile ACL grants another principal' }
    }
}
$links = @(& fsutil hardlink list $credentialPath)
if ($LASTEXITCODE -ne 0 -or @($links | Where-Object { $_.Trim() }).Count -ne 1) { throw 'AWS credential source has unsafe physical aliases' }
$bootstrapPath = Join-Path $PSScriptRoot 's3_credential_bootstrap.py'
$wslBootstrapPath = (& wsl -d $Distribution --exec wslpath -a $bootstrapPath.Replace('\', '/')).Trim()
if ($LASTEXITCODE -ne 0) { throw 'WSL bootstrap path resolution failed' }
# Secret bytes travel only over stdin; neither argv nor evidence contains them.
Get-Content -LiteralPath $credentialPath -Raw | & wsl -d $Distribution --exec /usr/bin/python3 $wslBootstrapPath --acl-verified-stdin
if ($LASTEXITCODE -ne 0) { throw 'WSL credential bootstrap failed' }
