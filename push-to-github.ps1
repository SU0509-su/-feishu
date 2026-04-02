# 在 GitHub 网页上新建空仓库后执行（将 URL 换成你的仓库地址）:
#   .\push-to-github.ps1 -RemoteUrl "https://github.com/USER/feishu-news-bot.git"
param(
    [Parameter(Mandatory = $true)]
    [string] $RemoteUrl
)

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
Write-Host "完成。请到仓库 Settings - Secrets - Actions 添加 FEISHU_WEBHOOK。"
