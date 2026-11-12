param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Distribution = 'Ubuntu',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = "HomeCinemaWsl-$Distribution"
$InstallDirectory = Join-Path $env:LOCALAPPDATA $TaskName
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

if ($Remove) {
    if ($null -ne $ExistingTask) {
        Stop-ScheduledTask -TaskName $TaskName
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    Write-Host "Removed $TaskName. Existing WSL services and data were preserved."
    return
}

$WslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'
$Distributions = @(& $WslPath --list --quiet) | ForEach-Object { ($_ -replace "`0", '').Trim() }
if ($LASTEXITCODE -ne 0 -or $Distribution -notin $Distributions) {
    throw "WSL distribution '$Distribution' was not found for this Windows user."
}

$Source = Join-Path $PSScriptRoot 'wsl-keepalive.ps1'
if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) {
    throw "Missing keepalive script: $Source"
}
if ($null -ne $ExistingTask) { Stop-ScheduledTask -TaskName $TaskName }
New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
$ScriptPath = Join-Path $InstallDirectory 'wsl-keepalive.ps1'
Copy-Item -LiteralPath $Source -Destination $ScriptPath -Force

$UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$PowerShellPath = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`" -Distribution `"$Distribution`""
$Action = New-ScheduledTaskAction -Execute $PowerShellPath -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Description 'Keep the HomeCinema WSL distribution running after Windows logon.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Write-Host "Started $TaskName. WSL will start in the background at this user's Windows logon."
Write-Host 'Docker must be enabled in the distribution and containers must have a restart policy.'
