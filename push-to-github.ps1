# 在 GitHub 网页上新建空仓库后执行（将 URL 换成你的仓库地址）:
#   .\push-to-github.ps1 -RemoteUrl "https://github.com/USER/feishu-news-bot.git"
param(
    [Parameter(Mandatory = $true)]
    [string] $RemoteUrl
)

if ($RemoteUrl -match "你的用户名|仓库名") {
    Write-Host ""
    Write-Host "错误: 你仍在使用说明里的占位符地址。" -ForegroundColor Red
    Write-Host "请先到 https://github.com/new 创建空仓库，再把 -RemoteUrl 换成真实地址，例如:" -ForegroundColor Yellow
    Write-Host '  .\push-to-github.ps1 -RemoteUrl "https://github.com/你的GitHub登录名/feishu-news-bot.git"'
    Write-Host ""
    exit 1
}

if ($RemoteUrl -notmatch "^https://github\.com/[^/]+/[^/]+") {
    Write-Host "提示: 请使用 https://github.com/你的登录名/仓库名 形式的地址。" -ForegroundColor Yellow
}

$ErrorActionPreference = "Stop"
$git = "C:\Program Files\Git\bin\git.exe"
if (-not (Test-Path $git)) {
    $git = "git"
}

Set-Location -LiteralPath $PSScriptRoot

& $git branch -M main

$hasOrigin = $false
$remoteLines = @(& $git remote)
foreach ($line in $remoteLines) {
    if ($line -eq "origin") {
        $hasOrigin = $true
        break
    }
}

if ($hasOrigin) {
    Write-Host "已存在 origin，将更新为:" $RemoteUrl
    & $git remote set-url origin $RemoteUrl
}
else {
    & $git remote add origin $RemoteUrl
}

Write-Host "正在推送到 GitHub..."
& $git push -u origin main
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "推送失败。常见原因: 仓库不存在、地址打错、未登录 GitHub。" -ForegroundColor Red
    Write-Host "若提示 Authentication failed，请在浏览器登录 GitHub 或使用 Personal Access Token。"
    exit $LASTEXITCODE
}
Write-Host "完成。请到仓库 Settings - Secrets - Actions 添加 FEISHU_WEBHOOK。"
