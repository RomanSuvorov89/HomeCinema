param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Distribution = 'Ubuntu',
    [string]$RepositoryPath = '~/HomeCinema',
    [string]$ServerUrl = 'http://localhost:9118/',
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
$TaskName = "HomeCinemaWsl-$Distribution"
$InstallDirectory = Join-Path $env:LOCALAPPDATA $TaskName
$Desktop = [Environment]::GetFolderPath('Desktop')
$ShortcutName = if ($Distribution -eq 'Ubuntu') { 'HomeCinema.lnk' } else { "HomeCinema ($Distribution).lnk" }
$ShortcutPath = Join-Path $Desktop $ShortcutName
$ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

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
    Write-Host "Removed $TaskName and its desktop shortcut. WSL services, data and panel configuration were preserved."
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
if (Test-Path -LiteralPath $ConfigPath) {
    $Previous = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if (-not $PSBoundParameters.ContainsKey('RepositoryPath') -and $Previous.RepositoryPath) { $RepositoryPath = $Previous.RepositoryPath }
    if (-not $PSBoundParameters.ContainsKey('ServerUrl') -and $Previous.ServerUrl) { $ServerUrl = $Previous.ServerUrl }
}
$Uri = $null
if (-not [Uri]::TryCreate($ServerUrl, [UriKind]::Absolute, [ref]$Uri) -or $Uri.Scheme -notin @('http','https')) {
    throw 'ServerUrl must be an absolute HTTP or HTTPS URL.'
}
if ([string]::IsNullOrWhiteSpace($RepositoryPath) -or $RepositoryPath.Contains("`n") -or $RepositoryPath.Contains("`r")) {
    throw 'RepositoryPath must be a Linux path to the HomeCinema checkout.'
}
New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
foreach ($File in $Files) {
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot $File) -Destination (Join-Path $InstallDirectory $File) -Force
}
@{ Distribution=$Distribution; RepositoryPath=$RepositoryPath; ServerUrl=$Uri.AbsoluteUri } |
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
    -Principal $Principal -Settings $Settings -Description 'Keep HomeCinema WSL running without a console window; recover the hidden host periodically.' -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName

$Shell = New-Object -ComObject WScript.Shell
$Shortcut = $Shell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $WscriptPath
$Shortcut.Arguments = "`"$Launcher`" panel"
$Shortcut.WorkingDirectory = $InstallDirectory
$Shortcut.Description = 'HomeCinema server: start, status, Docker containers and logs'
$Shortcut.IconLocation = (Join-Path $env:SystemRoot 'System32\shell32.dll') + ',15'
$Shortcut.Save()
Write-Host "Started hidden background task: $TaskName"
Write-Host "Desktop control panel: $ShortcutPath"
Write-Host 'Closing the panel does not stop WSL or the server.'
