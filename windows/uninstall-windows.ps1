$ErrorActionPreference = 'Stop'
$TaskName = 'HomeCinemaMpvBridge'
$InstallDirectory = Join-Path $env:LOCALAPPDATA 'HomeCinemaMpvBridge'

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

Get-CimInstance Win32_Process |
    Where-Object { $_.CommandLine -like "*$InstallDirectory*mpv-bridge.ps1*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

if (Test-Path -LiteralPath $InstallDirectory) {
    Remove-Item -LiteralPath $InstallDirectory -Recurse -Force
}

Write-Host 'Home Cinema MPV Bridge was removed.' -ForegroundColor Green
Write-Host 'mpv.net and its configuration were preserved.'
