param(
    [string]$RepoEnvPath = "",
    [string]$BridgeScriptPath = "C:\Github\tools\audio-bridge\audio_bridge.py",
    [string]$AllowedCallers = "camera-voice-bridge"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Get-DotEnvValue {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Key
    )
    foreach ($raw in Get-Content -Path $Path -ErrorAction Stop) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith("#")) {
            continue
        }
        $eq = $line.IndexOf("=")
        if ($eq -lt 1) {
            continue
        }
        $name = $line.Substring(0, $eq).Trim()
        if ($name -ne $Key) {
            continue
        }
        return $line.Substring($eq + 1).Trim()
    }
    return ""
}

if ([string]::IsNullOrWhiteSpace($RepoEnvPath)) {
    $repoRoot = Split-Path -Parent $PSScriptRoot
    $RepoEnvPath = Join-Path $repoRoot ".env"
}

if (-not (Test-Path -LiteralPath $RepoEnvPath)) {
    throw "Missing .env file: $RepoEnvPath"
}
if (-not (Test-Path -LiteralPath $BridgeScriptPath)) {
    throw "Missing audio bridge script: $BridgeScriptPath"
}

$token = Get-DotEnvValue -Path $RepoEnvPath -Key "CAMERA_VOICE_AUDIO_BRIDGE_TOKEN"
if ([string]::IsNullOrWhiteSpace($token)) {
    throw "CAMERA_VOICE_AUDIO_BRIDGE_TOKEN is empty in $RepoEnvPath"
}

$env:AUDIO_BRIDGE_TOKEN = $token
$env:AUDIO_BRIDGE_ALLOWED_CALLERS = $AllowedCallers

# Optional: partial name of the Bluetooth speaker for keepalive targeting.
$btSpeakerName = Get-DotEnvValue -Path $RepoEnvPath -Key "AUDIO_BRIDGE_BT_SPEAKER_NAME"
if (-not [string]::IsNullOrWhiteSpace($btSpeakerName)) {
    $env:BT_SPEAKER_NAME = $btSpeakerName
}

Write-Host "[audio-bridge] Using env file: $RepoEnvPath"
Write-Host "[audio-bridge] Allowed callers: $AllowedCallers"
Write-Host "[audio-bridge] Token loaded: yes"
Write-Host "[audio-bridge] Starting: $BridgeScriptPath"

if (Get-Command py -ErrorAction SilentlyContinue) {
    $pyCmd = "py"
    $pyArgs = @("-3")
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
    $pyCmd = "python"
    $pyArgs = @()
} else {
    throw "Python executable not found (tried: py, python)"
}

$probeCode = "import sounddevice, soundfile; print('ok')"
$probeOk = $false
try {
    & $pyCmd @pyArgs -c $probeCode 1>$null 2>$null
    $probeOk = ($LASTEXITCODE -eq 0)
} catch {
    $probeOk = $false
}

if (-not $probeOk) {
    Write-Host "[audio-bridge] Missing Python deps. Installing: sounddevice, soundfile"
    & $pyCmd @pyArgs -m ensurepip --upgrade *> $null
    & $pyCmd @pyArgs -m pip install --upgrade pip
    & $pyCmd @pyArgs -m pip install sounddevice soundfile
}

if (-not (Get-Command ffmpeg -ErrorAction SilentlyContinue)) {
    Write-Warning "[audio-bridge] ffmpeg not found in PATH. Audio conversion will fail until ffmpeg is installed."
}

# Keep Bluetooth speaker awake by playing silent audio every 4 minutes
$keepaliveScript = Join-Path $PSScriptRoot "keepalive_speaker.py"
if (Test-Path $keepaliveScript) {
    Start-Process $pyCmd -ArgumentList ($pyArgs + @($keepaliveScript)) -WindowStyle Hidden
    Write-Host "[audio-bridge] Speaker keepalive started."
}

& $pyCmd @pyArgs $BridgeScriptPath
