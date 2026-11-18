param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Distribution = 'Ubuntu',
    [string]$RepositoryPath = '~/HomeCinema',
    [string]$ServerUrl = 'http://localhost:9118/',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$LegacyTaskName = "HomeCinemaWsl-$Distribution"
$TaskName = "WslServer-$Distribution"
$InstallDirectory = Join-Path $env:LOCALAPPDATA $TaskName
$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutName = "$Distribution.lnk"
$ShortcutPath = Join-Path $Desktop $ShortcutName
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$LegacyTask = Get-ScheduledTask -TaskName $LegacyTaskName -ErrorAction SilentlyContinue

if ($Remove) {
    if ($null -ne $ExistingTask) {
        Stop-ScheduledTask -TaskName $TaskName
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }
    if (Test-Path -LiteralPath $ShortcutPath) {
        $Shell = New-Object -ComObject WScript.Shell
        $Shortcut = $Shell.CreateShortcut($ShortcutPath)
        if ($Shortcut.Arguments.Contains($InstallDirectory)) { Remove-Item -LiteralPath $ShortcutPath -Force }
    }
    Write-Host "Removed $TaskName and its desktop shortcut. Linux services, data and panel configuration were preserved."
    return
}

$WslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'
$Distributions = @(& $WslPath --list --quiet) | ForEach-Object { ($_ -replace "`0", '').Trim() }
if ($LASTEXITCODE -ne 0 -or $Distribution -notin $Distributions) {
    throw "WSL distribution '$Distribution' was not found for this Windows user."
}
$Files = @('wsl-keepalive.ps1','hidden-launcher.vbs','server-panel.ps1','wsl-server-control.sh')
foreach ($File in $Files) {
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot $File) -PathType Leaf)) {
        throw "Missing panel file: $File"
    }
}
$ConfigPath = Join-Path $InstallDirectory 'server-panel.json'
New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
foreach ($File in $Files) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $File) -Destination (Join-Path $InstallDirectory $File) -Force
}
@{ Distribution=$Distribution } |
    ConvertTo-Json | Set-Content -LiteralPath $ConfigPath -Encoding UTF8

$UserId = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$Launcher = Join-Path $InstallDirectory 'hidden-launcher.vbs'
$WscriptPath = Join-Path $env:SystemRoot 'System32\wscript.exe'
$Arguments = "`"$Launcher`" worker `"$Distribution`""
$Action = New-ScheduledTaskAction -Execute $WscriptPath -Argument $Arguments
$LogonTrigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$RecoveryTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
    -RepetitionInterval (New-TimeSpan -Minutes 5)
$Principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)

# Replace the old host only after all new files and configuration are ready.
if ($null -ne $ExistingTask) { Stop-ScheduledTask -TaskName $TaskName }
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger @($LogonTrigger,$RecoveryTrigger) `
    -Principal $Principal -Settings $Settings -Description 'Keep this Linux WSL distribution running without a console; recover its hidden host periodically.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
if ($null -ne $LegacyTask) {
    Stop-ScheduledTask -TaskName $LegacyTaskName
    Unregister-ScheduledTask -TaskName $LegacyTaskName -Confirm:$false
}
$LegacyShortcutPath = Join-Path $Desktop 'HomeCinema.lnk'
if (Test-Path -LiteralPath $LegacyShortcutPath) {
    $LegacyShell = New-Object -ComObject WScript.Shell
    $LegacyShortcut = $LegacyShell.CreateShortcut($LegacyShortcutPath)
    if ($LegacyShortcut.Arguments.Contains((Join-Path $env:LOCALAPPDATA $LegacyTaskName))) {
        Remove-Item -LiteralPath $LegacyShortcutPath -Force
    }
}

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $WscriptPath
$Shortcut.Arguments = "`"$Launcher`" panel"
$Shortcut.WorkingDirectory = $InstallDirectory
$Shortcut.Description = 'Linux / WSL: terminal, distribution status and all Docker containers'
$Shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',15'
$Shortcut.Save()
Write-Host "Started hidden background task: $TaskName"
Write-Host "Desktop control panel: $ShortcutPath"
Write-Host 'Closing the panel does not stop Linux, its services or its Docker containers.'
