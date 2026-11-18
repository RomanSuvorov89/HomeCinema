param(
    [string]$PanelPath = (Join-Path $env:LOCALAPPDATA 'WslServer-Ubuntu\server-panel.ps1')
)
$ErrorActionPreference = 'Stop'
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($PanelPath,[ref]$tokens,[ref]$errors)
if ($errors.Count) { throw ($errors.Message -join '; ') }
$quote = $ast.Find({param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Quote-Argument'},$true)
if ($null -eq $quote) { throw 'Argument quoting function missing.' }
. ([scriptblock]::Create($quote.Extent.Text))
foreach ($flag in @('--distribution','Ubuntu','--exec','bash','-s','--','status','/home/user/HomeCinema')) {
    if ((Quote-Argument $flag) -ne $flag) { throw "WSL flag was incorrectly quoted: $flag" }
}
if ((Quote-Argument '') -ne '""') { throw 'Empty argument lost.' }
if ((Quote-Argument '/home/user/my project') -ne '"/home/user/my project"') { throw 'Path with spaces not quoted.' }
if ((Quote-Argument 'a"b') -ne '"a\"b"') { throw 'Embedded quote not escaped.' }
$guiExe = Join-Path (Split-Path -Parent $PanelPath) 'server-panel.exe'
if (-not (Test-Path -LiteralPath $guiExe)) { throw 'GUI launcher executable missing.' }
$binary = [System.IO.File]::ReadAllBytes($guiExe)
$pe = [BitConverter]::ToInt32($binary,0x3c)
$subsystem = [BitConverter]::ToUInt16($binary,$pe+24+68)
if ($subsystem -ne 2) { throw 'Launcher must be a Windows GUI executable, not a console executable.' }
Write-Host 'Native GUI executable, PowerShell parser and WSL argument checks passed.'
& $PanelPath -Check
if (-not $?) { throw 'Panel integration check failed.' }
