$pathNew = Join-Path $PSScriptRoot 'index.html'
$c = [System.IO.File]::ReadAllText($pathNew, [System.Text.Encoding]::UTF8)
$ms = [regex]::Matches($c, 'function\s+(\w+)')
$names = @()
foreach($m in $ms){ $names += $m.Groups[1].Value }
$names | Sort-Object -Unique
