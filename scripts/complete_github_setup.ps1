# 使用本机已保存的 GitHub 凭据设置 Actions Secret，并可触发工作流。
# 依赖: Git、GitHub CLI（gh）。默认仓库: SU0509-su/-feishu
param(
    [switch] $SkipWorkflow
)

$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent

$git = "C:\Program Files\Git\bin\git.exe"
if (-not (Test-Path $git)) { $git = "git" }

$gh = "${env:ProgramFiles}\GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) { $gh = "gh" }

$configPath = Join-Path $Root "config.json"
if (-not (Test-Path $configPath)) {
    Write-Error "未找到 config.json，请将 config.example.json 复制为 config.json 并填写 webhook。"
    exit 1
}

$credIn = "protocol=https`nhost=github.com`n`n"
$out = $credIn | & $git credential fill 2>&1
$token = ($out | Where-Object { $_ -match '^password=' }) -replace '^password=', ''
if (-not $token) {
    Write-Error "无法从 git credential 读取 GitHub 令牌。请先通过浏览器登录 GitHub 或使用 gh auth login。"
    exit 1
}

$env:GITHUB_TOKEN = $token

$cfg = Get-Content $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$hook = $cfg.feishu_webhook.Trim()
if (-not $hook) {
    Write-Error "config.json 中 feishu_webhook 为空。"
    exit 1
}

Write-Host "正在设置仓库 Secret: FEISHU_WEBHOOK ..."
& $gh secret set FEISHU_WEBHOOK --repo "SU0509-su/-feishu" --body $hook
Write-Host "Secret 已更新。"

if (-not $SkipWorkflow) {
    Write-Host "正在触发工作流..."
    & $gh workflow run "feishu-daily-news.yml" --repo "SU0509-su/-feishu" --ref main
    Write-Host "已触发。请到 Actions 查看运行结果: https://github.com/SU0509-su/-feishu/actions"
}
