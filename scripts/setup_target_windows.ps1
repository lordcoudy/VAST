param(
    [switch]$InstallWSL = $true,
    [switch]$InstallNativeOpenVino = $true,
    [switch]$InstallNativeGStreamer = $true,
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
    choco install -y git python docker-desktop nvidia-display-driver
}

function Install-WSLPath {
    Write-Step "Installing WSL2 Ubuntu path (recommended for DeepStream + Savant)"
    wsl --install -d Ubuntu

    if (-not $SkipRebootPrompt) {
        Write-Warn "A reboot may be required to finish WSL installation."
    }

    Write-Step "After first Ubuntu launch, run this inside WSL from your project folder:"
    Write-Host "bash scripts/setup_target.sh" -ForegroundColor Green
}

function Install-NativeOpenVino {
    Write-Step "Installing native OpenVINO Python packages"
    py -m pip install --upgrade pip
    py -m pip install openvino openvino-dev
}

function Install-NativeGStreamer {
    Write-Step "Installing native GStreamer"
    choco install -y gstreamer
}

function Main {
    Ensure-Admin
    Ensure-Choco
    Install-BaseTools

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
}

Main
