<#
.SYNOPSIS
    Registers a Windows Task Scheduler task that auto-starts the audio bridge at login.

.DESCRIPTION
    Run once (as Administrator) to register the task.
    After that, the audio bridge starts automatically whenever you log in to Windows.

.PARAMETER BridgeScriptPath
    Path to audio_bridge.py on Windows. Default: C:\Github\tools\audio-bridge\audio_bridge.py

.PARAMETER RepoRoot
    Root of the ai-cam repo on Windows. Default: auto-detected relative to this script.

.PARAMETER TaskName
    Scheduled task name. Default: ai-cam audio-bridge

.EXAMPLE
    # Register with defaults (run from Windows PowerShell as Administrator):
    powershell.exe -ExecutionPolicy Bypass -File C:\Github\ai-cam\scripts\register_audio_bridge_task.ps1

    # Unregister:
    Unregister-ScheduledTask -TaskName "ai-cam audio-bridge" -Confirm:$false
#>
param(
    [string]$BridgeScriptPath = "C:\Github\tools\audio-bridge\audio_bridge.py",
    [string]$RepoRoot = "",
    [string]$TaskName = "ai-cam audio-bridge"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Resolve repo root from script location if not provided.
if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = Split-Path -Parent $PSScriptRoot
}

$startScript = Join-Path $RepoRoot "scripts\start_audio_bridge.ps1"

if (-not (Test-Path -LiteralPath $startScript)) {
    throw "start_audio_bridge.ps1 not found at: $startScript"
}

# Build the action: run powershell.exe -WindowStyle Hidden -File <start_audio_bridge.ps1>
$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -BridgeScriptPath `"$BridgeScriptPath`""

# Trigger: at current user login
$trigger = New-ScheduledTaskTrigger -AtLogOn

# Settings: restart up to 3 times if it fails, 1 min between restarts
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -MultipleInstances IgnoreNew

# Run as current user (no password needed for interactive session)
$principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -LogonType Interactive `
    -RunLevel Limited

# Register (or update if already exists)
if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Write-Host "[task] Updating existing task: $TaskName"
    Set-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal
} else {
    Write-Host "[task] Registering new task: $TaskName"
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description "Starts the ai-cam audio bridge (BT speaker keepalive + WAV playback) at login."
}

Write-Host "[task] Done. The audio bridge will now start automatically at every login."
Write-Host ""
Write-Host "To start it now without rebooting:"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To remove the task later:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
