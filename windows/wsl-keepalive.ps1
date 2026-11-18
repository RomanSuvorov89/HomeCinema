param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Distribution = 'Ubuntu'
)

$ErrorActionPreference = 'Stop'
$WslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'
$LogPath = Join-Path $PSScriptRoot 'background.log'
function Write-WorkerLog([string]$Message) {
    try {
        if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 65536) {
            $tail = @(Get-Content -LiteralPath $LogPath -Tail 80 -Encoding UTF8)
            $tail | Set-Content -LiteralPath $LogPath -Encoding UTF8
        }
        Add-Content -LiteralPath $LogPath -Encoding UTF8 -Value ((Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $Message)
    } catch { }
}

# This host belongs to Task Scheduler, never to the control-panel window.
# Explicit CreateNoWindow also prevents wsl.exe from creating a blank console.
Write-WorkerLog "Background host started for $Distribution."
while ($true) {
    $process = $null
    try {
        $info = New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName = $WslPath
        $info.Arguments = "--distribution $Distribution --exec /bin/sleep infinity"
        $info.UseShellExecute = $false
        $info.CreateNoWindow = $true
        $process = [System.Diagnostics.Process]::Start($info)
        $process.WaitForExit()
        Write-WorkerLog "WSL client exited: $($process.ExitCode). Retrying in 10 seconds."
    } catch {
        Write-WorkerLog "WSL start failed: $($_.Exception.Message)"
    } finally {
        if ($null -ne $process) { $process.Dispose() }
    }
    Start-Sleep -Seconds 10
}
