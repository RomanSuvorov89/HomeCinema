$ErrorActionPreference = 'Stop'

$AppDirectory = Join-Path $env:LOCALAPPDATA 'HomeCinemaMpvBridge'
$ConfigPath = Join-Path $AppDirectory 'config.json'

if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "Config not found: $ConfigPath"
}

$Config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$Port = [int]$Config.port
$AllowedOrigins = @($Config.allowedOrigins)
$MpvPath = [string]$Config.mpvPath
$Volume = [int]$Config.volume
$VolumeMax = [int]$Config.volumeMax
$Fullscreen = [bool]$Config.fullscreen

if (-not (Test-Path -LiteralPath $MpvPath -PathType Leaf)) {
    throw "mpv.exe not found: $MpvPath"
}

$script:Session = $null
$script:LastTime = 0.0
$script:LastDuration = 0.0

function Test-Origin {
    param([string]$Origin)

    if ([string]::IsNullOrWhiteSpace($Origin)) {
        return $false
    }

    return $AllowedOrigins -contains $Origin
}

function Write-HttpResponse {
    param(
        [System.Net.Sockets.TcpClient]$Client,
        [int]$StatusCode,
        [string]$StatusText,
        [string]$Body,
        [string]$Origin,
        [string]$ContentType = 'application/json; charset=utf-8'
    )

    $Encoding = New-Object System.Text.UTF8Encoding($false)
    $BodyBytes = $Encoding.GetBytes($Body)
    $Headers = New-Object System.Text.StringBuilder
    [void]$Headers.Append("HTTP/1.1 $StatusCode $StatusText`r`n")
    [void]$Headers.Append("Content-Type: $ContentType`r`n")
    [void]$Headers.Append("Content-Length: $($BodyBytes.Length)`r`n")
    [void]$Headers.Append("Cache-Control: no-store`r`n")
    [void]$Headers.Append("Connection: close`r`n")

    if (Test-Origin $Origin) {
        [void]$Headers.Append("Access-Control-Allow-Origin: $Origin`r`n")
        [void]$Headers.Append("Vary: Origin`r`n")
        [void]$Headers.Append("Access-Control-Allow-Methods: GET, POST, OPTIONS`r`n")
        [void]$Headers.Append("Access-Control-Allow-Headers: Content-Type`r`n")
        [void]$Headers.Append("Access-Control-Allow-Private-Network: true`r`n")
    }

    [void]$Headers.Append("`r`n")
    $HeaderBytes = $Encoding.GetBytes($Headers.ToString())
    $Stream = $Client.GetStream()
    $Stream.Write($HeaderBytes, 0, $HeaderBytes.Length)
    if ($BodyBytes.Length -gt 0) {
        $Stream.Write($BodyBytes, 0, $BodyBytes.Length)
    }
    $Stream.Flush()
}

function ConvertTo-JsonBody {
    param($Value)
    return ($Value | ConvertTo-Json -Compress -Depth 8)
}

function Stop-CurrentMpv {
    if ($null -eq $script:Session) {
        return
    }

    try {
        $Process = Get-Process -Id ([int]$script:Session.processId) -ErrorAction SilentlyContinue
        if ($null -ne $Process) {
            Stop-Process -Id $Process.Id -Force -ErrorAction SilentlyContinue
        }
    }
    catch {
    }
}

function Start-Mpv {
    param($Request)

    $Url = [string]$Request.url
    if ($Url -notmatch '^https?://') {
        throw 'Only http/https stream URLs are allowed'
    }

    Stop-CurrentMpv

    $Id = [Guid]::NewGuid().ToString('N')
    $PipeName = "roman-mpv-$Id"
    $Start = [Math]::Max(0, [double]$Request.start)
    $SafeUrl = $Url.Replace('"', '%22')

    $Arguments = @(
        "--input-ipc-server=\\.\pipe\$PipeName"
        '--force-window=yes'
        '--ontop'
        '--keep-open=no'
        '--slang=rus,ru'
        '--alang=rus,ru'
        '--sid=auto'
        '--subs-with-matching-audio=yes'
        '--subs-fallback=no'
        '--subs-fallback-forced=no'
        "--volume-max=$VolumeMax"
        "--volume=$Volume"
        "--start=$Start"
    )

    if ($Fullscreen) {
        $Arguments += '--fs'
    }

    $Arguments += "`"$SafeUrl`""
    $Process = Start-Process -FilePath $MpvPath -ArgumentList $Arguments -PassThru

    $script:LastTime = $Start
    $script:LastDuration = 0.0
    $script:Session = [pscustomobject]@{
        id = $Id
        pipeName = $PipeName
        processId = $Process.Id
        startedAt = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    }

    return $script:Session
}

function Invoke-MpvCommand {
    param(
        [string]$PipeName,
        [object[]]$Command,
        [int]$RequestId
    )

    $Pipe = [System.IO.Pipes.NamedPipeClientStream]::new(
        '.',
        $PipeName,
        [System.IO.Pipes.PipeDirection]::InOut,
        [System.IO.Pipes.PipeOptions]::None
    )

    try {
        $Pipe.Connect(700)
        $Encoding = New-Object System.Text.UTF8Encoding($false)
        $Writer = New-Object System.IO.StreamWriter($Pipe, $Encoding, 4096, $true)
        $Reader = New-Object System.IO.StreamReader($Pipe, $Encoding, $false, 4096, $true)
        $Writer.AutoFlush = $true
        $Request = @{
            command = $Command
            request_id = $RequestId
        } | ConvertTo-Json -Compress
        $Writer.WriteLine($Request)

        for ($Attempt = 0; $Attempt -lt 10; $Attempt++) {
            $Line = $Reader.ReadLine()
            if ($null -eq $Line) {
                break
            }

            $Response = $Line | ConvertFrom-Json
            if ([int]$Response.request_id -eq $RequestId) {
                if ([string]$Response.error -eq 'success') {
                    return $Response.data
                }
                return $null
            }
        }
    }
    finally {
        if ($null -ne $Reader) { $Reader.Dispose() }
        if ($null -ne $Writer) { $Writer.Dispose() }
        $Pipe.Dispose()
    }

    return $null
}

function Invoke-MpvProperty {
    param(
        [string]$PipeName,
        [string]$Property,
        [int]$RequestId
    )

    return Invoke-MpvCommand `
        -PipeName $PipeName `
        -Command @('get_property', $Property) `
        -RequestId $RequestId
}

function Select-RussianFullSubtitle {
    param([string]$PipeName)

    $Tracks = $null
    for ($Attempt = 0; $Attempt -lt 24; $Attempt++) {
        Start-Sleep -Milliseconds 250
        try {
            $Tracks = Invoke-MpvProperty `
                -PipeName $PipeName `
                -Property 'track-list' `
                -RequestId 20
        }
        catch {
            $Tracks = $null
        }

        if ($null -ne $Tracks -and @($Tracks).Count -gt 0) {
            break
        }
    }

    if ($null -eq $Tracks) {
        return
    }

    $Candidates = @($Tracks | Where-Object {
        if ([string]$_.type -ne 'sub') { return $false }

        $Language = [string]$_.lang
        $Title = [string]$_.title
        $IsRussian = $Language -match '^(ru|rus)([-_]|$)' -or
            $Title -match '(^|[^a-z])(ru|rus|russian)([^a-z]|$)'
        $IsForced = [bool]$_.forced -or
            $Title -match '(forced|signs?|songs?)'

        return $IsRussian -and -not $IsForced
    } | Sort-Object -Property @(
        @{ Expression = { if ([string]$_.title -match '(full|complete)') { 1 } else { 0 } }; Descending = $true },
        @{ Expression = { if ([string]$_.title -match '(sdh|hearing)') { 0 } else { 1 } }; Descending = $true },
        @{ Expression = { [int]$_.id }; Descending = $false }
    ))

    $Selected = $Candidates | Select-Object -First 1
    $SubtitleId = $(if ($null -ne $Selected) { [int]$Selected.id } else { 'no' })

    try {
        [void](Invoke-MpvCommand `
            -PipeName $PipeName `
            -Command @('set_property', 'sid', $SubtitleId) `
            -RequestId 21)
    }
    catch {
    }
}

function Get-MpvStatus {
    param([string]$Id)

    if ($null -eq $script:Session -or $script:Session.id -ne $Id) {
        return [pscustomobject]@{
            found = $false
            state = 'unknown'
            time = 0
            duration = 0
        }
    }

    $Process = Get-Process -Id ([int]$script:Session.processId) -ErrorAction SilentlyContinue
    if ($null -eq $Process) {
        return [pscustomobject]@{
            found = $true
            state = 'ended'
            time = $script:LastTime
            duration = $script:LastDuration
        }
    }

    try {
        $CurrentTime = Invoke-MpvProperty -PipeName $script:Session.pipeName -Property 'time-pos' -RequestId 1
        $Duration = Invoke-MpvProperty -PipeName $script:Session.pipeName -Property 'duration' -RequestId 2
        $Paused = Invoke-MpvProperty -PipeName $script:Session.pipeName -Property 'pause' -RequestId 3
        $Tracks = Invoke-MpvProperty -PipeName $script:Session.pipeName -Property 'track-list' -RequestId 4
        $Aid = Invoke-MpvProperty -PipeName $script:Session.pipeName -Property 'aid' -RequestId 5
        $Sid = Invoke-MpvProperty -PipeName $script:Session.pipeName -Property 'sid' -RequestId 6

        if ($null -ne $CurrentTime) { $script:LastTime = [double]$CurrentTime }
        if ($null -ne $Duration) { $script:LastDuration = [double]$Duration }

        return [pscustomobject]@{
            found = $true
            state = $(if ([bool]$Paused) { 'paused' } else { 'playing' })
            tracks = @($Tracks)
            aid = $Aid
            sid = $Sid
            time = $script:LastTime
            duration = $script:LastDuration
        }
    }
    catch {
        return [pscustomobject]@{
            found = $true
            state = 'starting'
            time = $script:LastTime
            duration = $script:LastDuration
        }
    }
}

function Read-HttpRequest {
    param([System.Net.Sockets.TcpClient]$Client)

    $Stream = $Client.GetStream()
    $Encoding = New-Object System.Text.UTF8Encoding($false)
    $Reader = New-Object System.IO.StreamReader($Stream, $Encoding, $false, 4096, $true)
    $RequestLine = $Reader.ReadLine()
    if ([string]::IsNullOrWhiteSpace($RequestLine)) {
        return $null
    }

    $Parts = $RequestLine.Split(' ')
    if ($Parts.Length -lt 2) {
        return $null
    }

    $Headers = @{}
    while ($true) {
        $Line = $Reader.ReadLine()
        if ([string]::IsNullOrEmpty($Line)) {
            break
        }
        $Separator = $Line.IndexOf(':')
        if ($Separator -gt 0) {
            $Name = $Line.Substring(0, $Separator).Trim().ToLowerInvariant()
            $Value = $Line.Substring($Separator + 1).Trim()
            $Headers[$Name] = $Value
        }
    }

    $ContentLength = 0
    if ($Headers.ContainsKey('content-length')) {
        $ContentLength = [int]$Headers['content-length']
    }

    $Body = ''
    if ($ContentLength -gt 0) {
        $Buffer = New-Object char[] $ContentLength
        $Read = 0
        while ($Read -lt $ContentLength) {
            $Count = $Reader.Read($Buffer, $Read, $ContentLength - $Read)
            if ($Count -le 0) { break }
            $Read += $Count
        }
        $Body = -join $Buffer[0..($Read - 1)]
    }

    return [pscustomobject]@{
        method = $Parts[0].ToUpperInvariant()
        target = $Parts[1]
        headers = $Headers
        body = $Body
    }
}

$Listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Loopback, $Port)
$Listener.Start()

try {
    while ($true) {
        $Client = $Listener.AcceptTcpClient()
        try {
            $Request = Read-HttpRequest -Client $Client
            if ($null -eq $Request) {
                Write-HttpResponse -Client $Client -StatusCode 400 -StatusText 'Bad Request' -Body '{"error":"bad request"}' -Origin ''
                continue
            }

            $Origin = ''
            if ($Request.headers.ContainsKey('origin')) {
                $Origin = [string]$Request.headers['origin']
            }

            if ($Request.method -eq 'OPTIONS') {
                if (-not (Test-Origin $Origin)) {
                    Write-HttpResponse -Client $Client -StatusCode 403 -StatusText 'Forbidden' -Body '{"error":"origin denied"}' -Origin ''
                }
                else {
                    Write-HttpResponse -Client $Client -StatusCode 204 -StatusText 'No Content' -Body '' -Origin $Origin
                }
                continue
            }

            if ($Request.target -eq '/health' -and $Request.method -eq 'GET') {
                Write-HttpResponse -Client $Client -StatusCode 200 -StatusText 'OK' -Body (ConvertTo-JsonBody @{ ok = $true; mpv = $MpvPath; trackMemoryVersion = 1 }) -Origin $Origin
                continue
            }

            if (-not (Test-Origin $Origin)) {
                Write-HttpResponse -Client $Client -StatusCode 403 -StatusText 'Forbidden' -Body '{"error":"origin denied"}' -Origin ''
                continue
            }

            if ($Request.target -eq '/play' -and $Request.method -eq 'POST') {
                $Payload = $Request.body | ConvertFrom-Json
                $Started = Start-Mpv -Request $Payload
                Write-HttpResponse -Client $Client -StatusCode 200 -StatusText 'OK' -Body (ConvertTo-JsonBody @{ ok = $true; id = $Started.id }) -Origin $Origin
                continue
            }

            if ($Request.target -eq '/track-selection' -and $Request.method -eq 'POST') {
                $Payload = $Request.body | ConvertFrom-Json
                if ($null -eq $script:Session -or [string]$Payload.id -ne $script:Session.id) {
                    throw 'Stale playback session'
                }
                $Tracks = @(Invoke-MpvProperty -PipeName $script:Session.pipeName -Property 'track-list' -RequestId 30)
                foreach ($Property in @('aid','sid')) {
                    $Value = $Payload.selection.$Property
                    if ($null -eq $Value) { continue }
                    $Kind = $(if ($Property -eq 'aid') { 'audio' } else { 'sub' })
                    if ([string]$Value -eq 'no' -and $Property -eq 'sid') { $Selected = 'no' }
                    elseif ([string]$Value -match '^\d+$' -and @($Tracks | Where-Object { $_.type -eq $Kind -and [string]$_.id -eq [string]$Value }).Count -gt 0) {
                        $Selected = [int]$Value
                    }
                    else { throw 'Invalid track selection' }
                    [void](Invoke-MpvCommand -PipeName $script:Session.pipeName -Command @('set_property',$Property,$Selected) -RequestId 31)
                }
                Write-HttpResponse -Client $Client -StatusCode 200 -StatusText 'OK' -Body '{"ok":true}' -Origin $Origin
                continue
            }

            if ($Request.target -match '^/status\?id=([a-f0-9]+)$' -and $Request.method -eq 'GET') {
                $Status = Get-MpvStatus -Id $Matches[1]
                Write-HttpResponse -Client $Client -StatusCode 200 -StatusText 'OK' -Body (ConvertTo-JsonBody $Status) -Origin $Origin
                continue
            }

            Write-HttpResponse -Client $Client -StatusCode 404 -StatusText 'Not Found' -Body '{"error":"not found"}' -Origin $Origin
        }
        catch {
            try {
                Write-HttpResponse -Client $Client -StatusCode 500 -StatusText 'Internal Server Error' -Body (ConvertTo-JsonBody @{ error = $_.Exception.Message }) -Origin ''
            }
            catch {
            }
        }
        finally {
            $Client.Close()
        }
    }
}
finally {
    $Listener.Stop()
}
