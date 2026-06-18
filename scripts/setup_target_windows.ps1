param(
    [bool]$InstallWSL = $true,
    [switch]$InstallNativeOpenVino,
    [switch]$InstallNativeGStreamer,
    [switch]$InstallNativePython,
    [switch]$SkipRebootPrompt = $false
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host "[setup] $msg" -ForegroundColor Cyan
}

function Write-Warn($msg) {
    Write-Host "[warning] $msg" -ForegroundColor Yellow
}

function Ensure-Admin {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($currentIdentity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "Run PowerShell as Administrator."
    }
}

function Ensure-Choco {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        return
    }

    Write-Step "Installing Chocolatey"
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
}

function Install-BaseTools {
    Write-Step "Installing base Windows tools"
    choco install -y git docker-desktop nvidia-display-driver
}

function Install-NativePython {
    Write-Step "Installing native Python 3.12 for optional Windows-only tools"
    choco install -y python312
}

function Install-WSLPath {
    Write-Step "Installing WSL2 Ubuntu path (recommended for DeepStream + Savant)"
    $distros = @(wsl -l -q 2>$null | ForEach-Object { $_.Trim([char]0).Trim() } | Where-Object { $_ })
    if ($distros -contains "Ubuntu") {
        Write-Step "Ubuntu WSL distribution already exists"
    } else {
        wsl --install -d Ubuntu
    }

    if (-not $SkipRebootPrompt) {
        Write-Warn "A reboot may be required to finish WSL installation."
    }

    Write-Step "After first Ubuntu launch, run this inside WSL from your project folder:"
    Write-Host "bash scripts/setup_target.sh" -ForegroundColor Green
}

function Install-NativeOpenVino {
    Write-Step "Installing native OpenVINO Python packages on Windows Python 3.12"
    if (-not (Get-Command py -ErrorAction SilentlyContinue)) {
        Install-NativePython
    }
    py -3.12 -m pip install --upgrade pip
    py -3.12 -m pip install "openvino==2024.6.0" "openvino-dev==2024.6.0"
}

function Install-NativeGStreamer {
    Write-Step "Installing native GStreamer"
    choco install -y gstreamer
}

function Main {
    Ensure-Admin
    Ensure-Choco
    Install-BaseTools

    if ($InstallNativePython) {
        Install-NativePython
    }

    if ($InstallWSL) {
        Install-WSLPath
    }

    if ($InstallNativeOpenVino) {
        Install-NativeOpenVino
    }

    if ($InstallNativeGStreamer) {
        Install-NativeGStreamer
    }

    Write-Host "`n[done] Windows preparation complete." -ForegroundColor Green
    Write-Warn "DeepStream is Linux-first; use WSL2 Ubuntu (or native Ubuntu) for full stack parity."
    Write-Warn "Native Windows OpenVINO/GStreamer installation is optional; pass -InstallNativeOpenVino or -InstallNativeGStreamer only if you need Windows-native diagnostics."
}

Main
