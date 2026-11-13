$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$controls = 'E:\STUDY\VAST\tmp\host-cache-cleanup-20261012\guardian-lifetime-red-02'
$source = '\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-accepted-policy-repair-20261011a-source-06c828ce798d3454f1d4b8a992aed7133882b5a1'
$overlay = '\\wsl.localhost\Ubuntu\home\s-a-balashov\work\vast-guardian-lifetime-red-20261012-02'
$overlayLinux = '/home/s-a-balashov/work/vast-guardian-lifetime-red-20261012-02'
$managedTest = 'C:\Users\s-a-balashov\.codex\worktrees\fix-accepted-policy-preprocessing\VAST\tests\test_accepted_policy_guardian_lifecycle_fixture_v1.py'
$runtime = '/home/s-a-balashov/.local/state/vast/publication/runtime/full-publication-cp312-v1/bin/python'
$testHash = '19543d86e69094d36f4ef6a6268d486218f8eeab3d4358f89d77d046f4952c4d'
$helperHash = '2d3837adc2683eefbd9497de00ff724a0935bf8df9d8543ffac4844bbcc63910'
$testId = 'tests.test_accepted_policy_guardian_lifecycle_fixture_v1.AcceptedPolicyGuardianLifecycleFixtureTests.test_owner_lifetime_survives_fixture_clock_advance_and_explicit_close'

if ((Test-Path -LiteralPath $controls) -or (Test-Path -LiteralPath $overlay)) {
    throw 'RED controls and ext4 overlay must both be fresh.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath $managedTest).Hash.ToLowerInvariant() -ne $testHash) {
    throw 'Reviewed test bytes changed before execution.'
}
if ((Get-FileHash -Algorithm SHA256 -LiteralPath "$source\tests\fixtures\accepted_policy_guardian_lifecycle_fixture_v1.py").Hash.ToLowerInvariant() -ne $helperHash) {
    throw 'Frozen original lifecycle helper hash differs.'
}
New-Item -ItemType Directory -Path $controls | Out-Null

function Save-Json([string] $name, $value) {
    $path = Join-Path $controls $name
    if (Test-Path -LiteralPath $path) { throw "Control output already exists: $path" }
    [IO.File]::WriteAllText($path, ($value | ConvertTo-Json -Depth 20) + "`n", [Text.UTF8Encoding]::new($false))
}

function Invoke-Original([string] $name, [string[]] $arguments) {
    $stdout = Join-Path $controls "$name.stdout.raw"
    $stderr = Join-Path $controls "$name.stderr.raw"
    $info = [Diagnostics.ProcessStartInfo]::new('wsl.exe')
    $info.UseShellExecute = $false
    $info.RedirectStandardOutput = $true
    $info.RedirectStandardError = $true
    foreach ($argument in $arguments) { $info.ArgumentList.Add($argument) }
    $started = [DateTime]::UtcNow
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $info
    $outFile = [IO.File]::Open($stdout, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    $errFile = [IO.File]::Open($stderr, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try {
        if (-not $process.Start()) { throw 'Process creation failed.' }
        $outCopy = $process.StandardOutput.BaseStream.CopyToAsync($outFile)
        $errCopy = $process.StandardError.BaseStream.CopyToAsync($errFile)
        $process.WaitForExit()
        [void]($outCopy.GetAwaiter().GetResult())
        [void]($errCopy.GetAwaiter().GetResult())
        $code = $process.ExitCode
    } finally {
        if ($process.Id -and -not $process.HasExited) { $process.WaitForExit() }
        $outFile.Dispose()
        $errFile.Dispose()
        $process.Dispose()
    }
    $watch.Stop()
    $result = [ordered]@{
        executable = 'wsl.exe'; arguments = $arguments; started_utc = $started.ToString('o')
        finished_utc = [DateTime]::UtcNow.ToString('o'); elapsed_seconds = $watch.Elapsed.TotalSeconds
        original_exit_code = $code; stdout_path = $stdout; stderr_path = $stderr
        stdout_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $stdout).Hash.ToLowerInvariant()
        stderr_sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $stderr).Hash.ToLowerInvariant()
    }
    Save-Json "$name.result.v1.json" $result
    return $result
}

$ps = Invoke-Original 'linux-workers-before' @('-d', 'Ubuntu', '-u', 's-a-balashov', '--exec', 'ps', '-eo', 'pid,ppid,args')
if ($ps.original_exit_code -ne 0) { throw 'Original Linux worker observation failed.' }
$linuxMatches = @([IO.File]::ReadAllLines($ps.stdout_path) | Where-Object {
    $_ -match 'vast-accepted-policy-repair-20261011a-(source|ci)-06|build_production_fixture_v2|run_complete_consumers_v4'
})
$windowsMatches = @(Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -and $_.CommandLine -match 'Run-Repair06(Consumers|FullSuite|Integration)|Check-RepairSource06|Prepare-RepairSource06'
} | Select-Object ProcessId, ParentProcessId, CommandLine)
Save-Json 'owned-workers-before.v1.json' ([ordered]@{
    observed_utc = [DateTime]::UtcNow.ToString('o'); linux_matches = $linuxMatches
    windows_matches = $windowsMatches; scope = 'Previously owned repair/check producers only; no signals or mutations.'
})
if ($linuxMatches.Count -or $windowsMatches.Count) { throw 'Previously owned workers are still present; no copying or test execution.' }
$mount = Invoke-Original 'overlay-parent-mount' @('-d', 'Ubuntu', '-u', 's-a-balashov', '--exec', 'findmnt', '-T', '/home/s-a-balashov/work', '-n', '-o', 'SOURCE,FSTYPE,TARGET')
if ($mount.original_exit_code -ne 0 -or [IO.File]::ReadAllText($mount.stdout_path) -notmatch '\sext4\s') {
    throw 'External overlay parent is not confirmed ext4.'
}
$identity = Invoke-Original 'runtime-user' @('-d', 'Ubuntu', '-u', 's-a-balashov', '--exec', 'id')
if ($identity.original_exit_code -ne 0 -or [IO.File]::ReadAllText($identity.stdout_path) -notmatch '^uid=1000.*gid=1000') {
    throw 'Canonical test UID/GID observation failed.'
}

$inputs = [Collections.Generic.List[object]]::new()
foreach ($group in @('scripts', 'tests\fixtures')) {
    foreach ($file in Get-ChildItem -LiteralPath (Join-Path $source $group) -File -Recurse -Force) {
        if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Frozen copy input is linked.' }
        $relative = $file.FullName.Substring($source.Length + 1)
        $inputs.Add([ordered]@{relative_path = $relative; source_path = $file.FullName
            size_bytes = $file.Length; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.FullName).Hash.ToLowerInvariant()
            scope = 'Byte-identical SOURCE06 scripts or fixture input'})
    }
}
$sourceTestsInitializer = Join-Path $source 'tests\__init__.py'
$testsInitializerPresent = Test-Path -LiteralPath $sourceTestsInitializer
if ($testsInitializerPresent) {
    $file = Get-Item -LiteralPath $sourceTestsInitializer
    if ($file.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Frozen tests initializer is linked.' }
    $inputs.Add([ordered]@{relative_path = 'tests\__init__.py'; source_path = $sourceTestsInitializer
        size_bytes = $file.Length; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceTestsInitializer).Hash.ToLowerInvariant()
        scope = 'Byte-identical SOURCE06 tests package initializer when present'})
}
$inputs.Add([ordered]@{relative_path = 'tests\test_accepted_policy_guardian_lifecycle_fixture_v1.py'
    source_path = $managedTest; size_bytes = (Get-Item -LiteralPath $managedTest).Length
    sha256 = $testHash; scope = 'Only changed regression test; not frozen production code'})
Save-Json 'copy-plan.v1.json' ([ordered]@{source_commit = '06c828ce798d3454f1d4b8a992aed7133882b5a1'
    source_root = $source; destination_root = $overlay; lifecycle_helper_sha256 = $helperHash
    source_tests_initializer_present = $testsInitializerPresent; invented_package_initializer = $false
    files = @($inputs.ToArray()); campaign_authority = $false; physical_inference_observed = $false})
New-Item -ItemType Directory -Path $overlay | Out-Null
foreach ($entry in $inputs) {
    $destination = Join-Path $overlay $entry.relative_path
    New-Item -ItemType Directory -Path ([IO.Path]::GetDirectoryName($destination)) -Force | Out-Null
    Copy-Item -LiteralPath $entry.source_path -Destination $destination
    if ((Get-Item -LiteralPath $destination).Length -ne $entry.size_bytes -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -ne $entry.sha256 -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.source_path).Hash.ToLowerInvariant() -ne $entry.sha256) {
        throw 'Frozen input or copied overlay differs; test is not admitted.'
    }
}
Save-Json 'copy-proof.v1.json' ([ordered]@{observed_utc = [DateTime]::UtcNow.ToString('o')
    file_count = $inputs.Count; all_source_and_destination_bytes_verified = $true; helper_sha256 = $helperHash
    test_sha256 = $testHash; source_or_historical_writes = $false})
$singleInvocation = @"
import importlib
import json
from pathlib import Path
import sys
import unittest

root = Path('$overlayLinux')
if root.resolve(strict=True) != root or Path.cwd().resolve(strict=True) != root:
    raise RuntimeError('Focused regression overlay root is not canonical')
expected = {
    'tests.test_accepted_policy_guardian_lifecycle_fixture_v1': root / 'tests/test_accepted_policy_guardian_lifecycle_fixture_v1.py',
    'tests.fixtures.accepted_policy_guardian_lifecycle_fixture_v1': root / 'tests/fixtures/accepted_policy_guardian_lifecycle_fixture_v1.py',
    'checkpoint_gstreamer_analytics_sidecar': root / 'scripts/checkpoint_gstreamer_analytics_sidecar.py',
}
observed = {}
for name, path in expected.items():
    module = importlib.import_module(name)
    loaded = Path(module.__file__).resolve(strict=True)
    if loaded != path or path.resolve(strict=True) != path:
        raise RuntimeError(f'Focused regression module origin drifted: {name}: {loaded}')
    observed[name] = str(loaded)
print(json.dumps({'module_origin_guards_passed': True, 'loaded_paths': observed, 'test_execution_count_planned': 1}, sort_keys=True), flush=True)
suite = unittest.defaultTestLoader.loadTestsFromName('$testId')
if suite.countTestCases() != 1:
    raise RuntimeError('Focused regression loader did not select exactly one test')
result = unittest.TextTestRunner(stream=sys.stderr, verbosity=2).run(suite)
if result.testsRun != 1:
    raise RuntimeError('Focused regression runner did not execute exactly one test')
sys.exit(0 if result.wasSuccessful() else 1)
"@
$arguments = @('-d', 'Ubuntu', '-u', 's-a-balashov', '--cd', $overlayLinux, '--exec', 'env', '-u', 'PYTHONPATH', '-u', 'PYTHONHOME',
    'HOME=/home/s-a-balashov', $runtime, '-B', '-c', $singleInvocation)
Save-Json 'command.v1.json' ([ordered]@{executable = 'wsl.exe'; arguments = $arguments; test_id = $testId
    scope = 'One focused real Unix guardian protocol regression; only fixture module time reference is advanced.'
    expected = 'RED on frozen 1800-second fixture expiry; no production acceptance substitution'
    production_timeouts_changed = $false; retries = 0; campaign_authority = $false})
$test = Invoke-Original 'test-original' $arguments
foreach ($entry in $inputs) {
    $destination = Join-Path $overlay $entry.relative_path
    if ((Get-FileHash -Algorithm SHA256 -LiteralPath $destination).Hash.ToLowerInvariant() -ne $entry.sha256 -or
        (Get-FileHash -Algorithm SHA256 -LiteralPath $entry.source_path).Hash.ToLowerInvariant() -ne $entry.sha256) {
        throw 'Post-test frozen source or overlay bytes changed.'
    }
}
$post = Invoke-Original 'linux-workers-after' @('-d', 'Ubuntu', '-u', 's-a-balashov', '--exec', 'ps', '-eo', 'pid,ppid,args')
$postMatches = @([IO.File]::ReadAllLines($post.stdout_path) | Where-Object {
    $_ -match 'vast-guardian-lifetime-red-20261012-02|vast-accepted-policy-repair-20261011a-(source|ci)-06|build_production_fixture_v2|run_complete_consumers_v4'
})
Save-Json 'result.v1.json' ([ordered]@{closed_utc = [DateTime]::UtcNow.ToString('o'); original_test_exit_code = $test.original_exit_code
    original_test_result = $test; copied_file_count = $inputs.Count; frozen_source_and_overlay_bytes_unchanged = $true
    post_worker_observation_exit_code = $post.original_exit_code; post_matching_workers = $postMatches
    acceptance_asserted = $false; campaign_authority = $false; retries = 0})
Write-Output ($test | ConvertTo-Json -Depth 8)
exit $test.original_exit_code
