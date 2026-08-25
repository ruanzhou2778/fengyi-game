$bak = Join-Path $PSScriptRoot 'index.html.bak_20260825_115237'
$new = Join-Path $PSScriptRoot 'index.html'

$bakContent = [System.IO.File]::ReadAllText($bak, [System.Text.Encoding]::UTF8)
$newContent = [System.IO.File]::ReadAllText($new, [System.Text.Encoding]::UTF8)

$bakFuncs = [regex]::Matches($bakContent, 'function\s+(\w+)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique
$newFuncs = [regex]::Matches($newContent, 'function\s+(\w+)') | ForEach-Object { $_.Groups[1].Value } | Sort-Object -Unique

Write-Host ("Backup functions: " + $bakFuncs.Count)
Write-Host ("New file functions: " + $newFuncs.Count)

$missing = $bakFuncs | Where-Object { $_ -notin $newFuncs }
Write-Host ("Missing from new file: " + $missing.Count)

if ($missing.Count -gt 0) {
    Write-Host "--- Missing Functions ---"
    $missing | ForEach-Object { Write-Host $_ }
} else {
    Write-Host "No missing functions found. Injection appears complete."
}