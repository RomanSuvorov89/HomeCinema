param(
    [string]$PanelPath = (Join-Path $env:LOCALAPPDATA 'HomeCinemaWsl-Ubuntu\server-panel.ps1')
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
Write-Host 'PowerShell parser and WSL argument regression checks passed.'
& $PanelPath -Check
if (-not $?) { throw 'Panel integration check failed.' }
