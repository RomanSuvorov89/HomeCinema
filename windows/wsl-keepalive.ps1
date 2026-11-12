param(
    [ValidatePattern('^[A-Za-z0-9_.-]+$')]
    [string]$Distribution = 'Ubuntu'
)

$ErrorActionPreference = 'Stop'
$WslPath = Join-Path $env:SystemRoot 'System32\wsl.exe'

# Keep a Windows-side WSL client attached: systemd services alone do not
# prevent WSL from stopping when the last client exits.
while ($true) {
    try {
        & $WslPath --distribution $Distribution --exec /bin/sleep infinity *> $null
    }
    catch {
        # WSL can be temporarily unavailable during updates or resume.
    }
    Start-Sleep -Seconds 10
}
