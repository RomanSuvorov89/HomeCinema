param(
    [Parameter(Mandatory = $true)]
    [string]$ServerUrl,
    [string]$MpvPath = ''
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$InstallDirectory = Join-Path $env:LOCALAPPDATA 'HomeCinemaMpvBridge'
$MpvConfigDirectory = Join-Path $env:APPDATA 'mpv.net'

function Find-MpvNet {
    $command = Get-Command mpvnet.exe -ErrorAction SilentlyContinue
    if ($null -ne $command) { return $command.Source }

    $roots = @(
        (Join-Path $env:LOCALAPPDATA 'Programs'),
        $env:ProgramFiles,
        ${env:ProgramFiles(x86)}
    ) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

    foreach ($searchRoot in $roots) {
        $match = Get-ChildItem -LiteralPath $searchRoot -Filter mpvnet.exe -File -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -ne $match) { return $match.FullName }
    }
    return ''
}

if ([string]::IsNullOrWhiteSpace($MpvPath)) {
    $MpvPath = Find-MpvNet
}

if ([string]::IsNullOrWhiteSpace($MpvPath)) {
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if ($null -eq $winget) {
        throw 'winget is unavailable. Install App Installer or pass -MpvPath explicitly.'
    }

    & winget install --id Microsoft.DotNet.DesktopRuntime.10 -e --silent --accept-package-agreements --accept-source-agreements
    & winget install --id mpv.net -e --silent --accept-package-agreements --accept-source-agreements
    $MpvPath = Find-MpvNet
}

if ([string]::IsNullOrWhiteSpace($MpvPath) -or -not (Test-Path -LiteralPath $MpvPath -PathType Leaf)) {
    throw 'mpv.net was not found after installation. Pass -MpvPath explicitly.'
}

New-Item -ItemType Directory -Path $InstallDirectory -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $MpvConfigDirectory 'scripts') -Force | Out-Null

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
foreach ($name in @('mpv.conf', 'input.conf')) {
    $destination = Join-Path $MpvConfigDirectory $name
    if (Test-Path -LiteralPath $destination) {
        Copy-Item -LiteralPath $destination -Destination "$destination.before-home-cinema-$stamp" -Force
    }
    Copy-Item -LiteralPath (Join-Path $Root "mpv-config\$name") -Destination $destination -Force
}

Copy-Item -LiteralPath (Join-Path $Root 'mpv-config\scripts\russian-full-subs.lua') `
    -Destination (Join-Path $MpvConfigDirectory 'scripts\russian-full-subs.lua') -Force
Copy-Item -LiteralPath (Join-Path $Root 'mpv-bridge.ps1') `
    -Destination (Join-Path $InstallDirectory 'mpv-bridge.ps1') -Force

$origin = ([Uri]$ServerUrl).GetLeftPart([System.UriPartial]::Authority)
$config = [ordered]@{
    port = 19777
    allowedOrigins = @($origin)
    mpvPath = (Resolve-Path -LiteralPath $MpvPath).Path
    volume = 130
    volumeMax = 300
    fullscreen = $true
}
$config | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $InstallDirectory 'config.json') -Encoding UTF8

$TaskName = 'HomeCinemaMpvBridge'
$ScriptPath = Join-Path $InstallDirectory 'mpv-bridge.ps1'
$Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$ScriptPath`""
$Action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $Arguments
$Trigger = New-ScheduledTaskTrigger -AtLogOn
$Principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
$Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew

foreach ($oldTask in @('HomeCinemaMpvBridge', 'RomanMpvBridge')) {
    Stop-ScheduledTask -TaskName $oldTask -ErrorAction SilentlyContinue
}
Unregister-ScheduledTask -TaskName 'RomanMpvBridge' -Confirm:$false -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process | Where-Object {
    $_.CommandLine -like '*mpv-bridge.ps1*'
} | Invoke-CimMethod -MethodName Terminate -ErrorAction SilentlyContinue | Out-Null

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger `
    -Principal $Principal -Settings $Settings -Force | Out-Null
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 2

$health = Invoke-RestMethod http://127.0.0.1:19777/health -TimeoutSec 5
if (-not $health.ok) { throw 'MPV Bridge health check failed' }

Write-Host 'mpv.net and Home Cinema MPV Bridge are ready.' -ForegroundColor Green
Write-Host "Player: $MpvPath"
Write-Host "Server: $origin"
