# 本地一键推送到华为云（无 Git 仓库时用）
# 用法（PowerShell）：
#   .\deploy\push-update.ps1 -Host 你的公网IP -User root

param(
    [Parameter(Mandatory = $true)]
    [string]$Host,

    [string]$User = "root",
    [string]$RemoteDir = "/opt/fengyi-game",
    [string]$KeyPath = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

Write-Host "========================================"
Write-Host "  上传更新到华为云: ${User}@${Host}"
Write-Host "========================================"

$scpArgs = @("-r")
if ($KeyPath) {
    $scpArgs += @("-i", $KeyPath)
}

# 排除不需要上传的目录
$items = @(
    "app.py", "ai_service.py", "events.py", "events.json", "models.py",
    "names.py", "npcs.py", "palace_extra.py", "player_traits.py",
    "scenarios.py", "family_backgrounds.py", "index.html",
    "requirements.txt", "Dockerfile", "docker-compose.yml", "Procfile",
    "js", "deploy"
)

foreach ($item in $items) {
    $localPath = Join-Path $ProjectRoot $item
    if (Test-Path $localPath) {
        Write-Host ">>> 上传 $item"
        & scp @scpArgs $localPath "${User}@${Host}:${RemoteDir}/"
    }
}

Write-Host ""
Write-Host ">>> 远程重建并重启..."
$sshArgs = @()
if ($KeyPath) { $sshArgs += @("-i", $KeyPath) }
$sshArgs += "${User}@${Host}", "cd $RemoteDir && bash deploy/update.sh"

& ssh @sshArgs

Write-Host ""
Write-Host "更新完成。访问: http://${Host}"
