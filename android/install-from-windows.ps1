param(
    [Parameter(Mandatory = $true)]
    [string]$ServerUrl,
    [string]$AdbPath = 'adb.exe'
)

$ErrorActionPreference = 'Stop'
$server = $ServerUrl.TrimEnd('/')
$apk = Join-Path $env:TEMP 'home-cinema-lampa.apk'
$builder = "$server/lampac.apk?overwritehost=$([Uri]::EscapeDataString($server))"

if (-not (Get-Command $AdbPath -ErrorAction SilentlyContinue)) {
    if (-not (Get-Command winget.exe -ErrorAction SilentlyContinue)) {
        throw 'adb and winget are unavailable. Install Android Platform Tools manually.'
    }
    & winget install --id Google.PlatformTools -e --silent --accept-package-agreements --accept-source-agreements
}

if (-not (Get-Command $AdbPath -ErrorAction SilentlyContinue)) {
    throw 'Android Platform Tools were installed, but adb is not visible in this PowerShell session. Reopen PowerShell.'
}

Invoke-WebRequest -Uri $builder -OutFile $apk -UseBasicParsing
$bytes = [System.IO.File]::ReadAllBytes($apk)
if ($bytes.Length -lt 100000 -or $bytes[0] -ne 0x50 -or $bytes[1] -ne 0x4B) {
    $message = [System.Text.Encoding]::UTF8.GetString($bytes)
    throw "Lampac did not return a valid APK. Server response: $message"
}

& $AdbPath install -r $apk
if ($LASTEXITCODE -ne 0) { throw 'adb install failed' }
Write-Host 'Lampa APK was installed on Android TV.' -ForegroundColor Green
