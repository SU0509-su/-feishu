# 在 GitHub 网页上新建「空仓库」后，在本机执行（把 URL 换成你的仓库地址）：
#   .\push-to-github.ps1 -RemoteUrl "https://github.com/你的用户名/feishu-news-bot.git"
param(
    [Parameter(Mandatory = $true)]
    [string] $RemoteUrl
)

$ErrorActionPreference = "Stop"
$git = "C:\Program Files\Git\bin\git.exe"
if (-not (Test-Path $git)) {
    $git = "git"
}

Set-Location $PSScriptRoot

& $git branch -M main
$existing = & $git remote 2>$null
if ($existing -match "origin") {
    Write-Host "已存在 origin，将设为：" $RemoteUrl
    & $git remote set-url origin $RemoteUrl
} else {
    & $git remote add origin $RemoteUrl
}

Write-Host "正在推送到 GitHub..."
& $git push -u origin main
Write-Host "完成。请到仓库 Settings → Secrets → Actions 添加 FEISHU_WEBHOOK。"
