param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-f]{40}$')]
    [string]$ExpectedCommit
)

$ErrorActionPreference = 'Stop'
$repository = 'lordcoudy/VAST'
$branch = 'codex/fix-accepted-policy-preprocessing'
$api = 'https://api.github.com/repos/' + $repository
$oldPrompt = $env:GIT_TERMINAL_PROMPT
$fields = @{}
$headers = @{}
$entry = $null
try {
    $env:GIT_TERMINAL_PROMPT = '0'
    $entry = "protocol=https`nhost=github.com`n`n" |
        git -c credential.interactive=never credential fill 2>$null
    if ($LASTEXITCODE -ne 0) { throw 'Existing GitHub credential unavailable.' }
    foreach ($line in $entry) {
        $parts = $line.Split('=', 2)
        if ($parts.Count -eq 2) { $fields[$parts[0]] = $parts[1] }
    }
    if ([string]::IsNullOrEmpty($fields['password'])) {
        throw 'Existing GitHub credential unavailable.'
    }
    $headers = @{
        Authorization = 'Bearer ' + $fields['password']
        Accept = 'application/vnd.github+json'
        'X-GitHub-Api-Version' = '2026-03-10'
    }
    $ref = Invoke-RestMethod -Uri ($api + '/git/ref/heads/' + $branch) -Headers $headers
    if ($ref.object.sha -cne $ExpectedCommit) {
        throw 'Remote branch does not match the exact reviewed input commit.'
    }
    $workflow = Invoke-RestMethod -Uri ($api + '/actions/workflows/ci.yml') -Headers $headers
    if ($workflow.state -cne 'active' -or $workflow.path -cne '.github/workflows/ci.yml') {
        throw 'Expected existing CI workflow is not active.'
    }
    $body = @{ ref = $branch; return_run_details = $true } | ConvertTo-Json -Compress
    $response = Invoke-WebRequest -Method Post -Uri ($api + '/actions/workflows/ci.yml/dispatches') `
        -Headers $headers -ContentType 'application/json' -Body $body
    $result = $null
    if ($response.Content) { $result = $response.Content | ConvertFrom-Json }
    [ordered]@{
        status = 'dispatched'
        http_status = [int]$response.StatusCode
        repository = $repository
        branch = $branch
        expected_head_sha = $ExpectedCommit
        workflow_run_id = $result.workflow_run_id
        run_url = $result.run_url
        html_url = $result.html_url
        started_at_utc = [DateTime]::UtcNow.ToString('o')
        exact_run_head_and_checks_verified = $false
    } | ConvertTo-Json
} catch {
    # Do not emit credential/header objects or an HTTP exception's request data.
    $status = $_.Exception.Response.StatusCode.value__
    if ($null -ne $status) { Write-Error ("Hosted CI dispatch failed (HTTP " + $status + ').') }
    else { Write-Error 'Hosted CI dispatch refused or failed; no readiness is claimed.' }
    exit 1
} finally {
    $headers.Clear()
    $fields.Clear()
    $entry = $null
    $line = $null
    $parts = $null
    $response = $null
    $env:GIT_TERMINAL_PROMPT = $oldPrompt
}
