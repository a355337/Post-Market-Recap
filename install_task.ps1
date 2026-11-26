param(
    [string]$TaskName = "TaiwanMarketPodcast",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $ProjectDir "podcast.py"

if (-not $PythonPath) {
    $VenvPython = Join-Path $ProjectDir ".venv\Scripts\python.exe"
    if (Test-Path $VenvPython) {
        $PythonPath = $VenvPython
    }
    else {
        $PythonCommand = Get-Command python -ErrorAction Stop
        $PythonPath = $PythonCommand.Source
    }
}

if (-not (Test-Path $PythonPath)) {
    throw "Python executable not found: $PythonPath"
}

$Action = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "`"$ScriptPath`" --schedule" `
    -WorkingDirectory $ProjectDir
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "Creates a Taiwan-workday US market podcast at 06:00 Asia/Taipei." `
    -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Output "Installed and started scheduled task '$TaskName'."
