# Feishu Daily News Bot

每天 **北京时间 10:00** 向飞书群推送两类新闻：**科技/AI**、**财经**。每条含较完整摘要（正文 + 要点）、双语来源说明与原文链接。

## 推荐：云端定时（不依赖电脑开机）

使用 **GitHub Actions** 在云端执行，关机也能收到简报。

1. 将本目录推送到你自己的 **GitHub 仓库**（公开或私有均可）。
2. 在仓库 **Settings → Secrets and variables → Actions** 中新建 Secret：
   - 名称：`FEISHU_WEBHOOK`
   - 值：你的飞书机器人 Webhook 地址（与本地 `config.json` 里相同）。
3. 工作流已配置为每日 **UTC 02:00**（即 **北京时间 10:00**）运行，见 `.github/workflows/feishu-daily-news.yml`。
4. 推送代码后，可在 Actions 里手动 **Run workflow** 做一次测试。

**一键完成 Secret + 试跑（本机已登录 GitHub / Git 已保存凭据时）**：

```powershell
cd "d:\人工智能\cloud code"
.\scripts\complete_github_setup.ps1
```

（仅更新 Secret、不触发工作流：`.\scripts\complete_github_setup.ps1 -SkipWorkflow`）

### 某天没收到？先对照 Actions

在仓库 **Actions** 打开 **Feishu daily news brief**，看运行记录里的 **触发方式**：

| 显示 | 含义 |
|------|------|
| `schedule` | 定时任务触发（每天约北京时间 10:00，GitHub 可能晚几分钟到一小时） |
| `workflow_dispatch` | 手动点「Run workflow」或脚本触发 |
| `repository_dispatch` | 外部服务（见下）按 API 触发，可作定时兜底 |

- **工作流刚推到 GitHub 的当天早上**：若推送时间晚于当日 **UTC 02:00**（北京时间 10:00），**当天**不会再补跑，**次日**同一时间才会出现第一次 `schedule`。
- **GitHub `schedule` 可能整段不跑**（负载高、队列问题等），若某天 Actions 里**完全没有**当日的 `schedule` 记录，属于平台侧现象；已去掉易阻塞的 `concurrency`，并支持 **`repository_dispatch`** 由外部定时调用兜底（见下）。
- 若历史里**从未出现** `schedule`、只有手动运行：请拉取本仓库最新工作流，并确认 **Settings → Actions → General** 中 Actions 已启用。

**定时兜底（推荐在「总收不到 schedule」时配置）**：在 [cron-job.org](https://cron-job.org) 等外部定时服务，每天 **北京时间 10:05** 对你的仓库发一次 `repository_dispatch`（需 Personal Access Token，权限含 `contents` 或 `workflow`）：

```http
POST https://api.github.com/repos/SU0509-su/-feishu/dispatches
Authorization: Bearer <你的 PAT>
Accept: application/vnd.github+json
Content-Type: application/json

{"event_type":"daily"}
```

与内置 `cron: 0 2 * * *` 并存时，可能同一天触发两次；若你希望**只**用外部定时，可把 workflow 里的 `schedule` 整段删掉（需自行改 YAML）。

云端运行时 **不会读取** 仓库里的 `config.json`（已加入 `.gitignore` 防泄露），只使用 `config.example.json` 中的订阅源 + Secret 里的 Webhook。

推送前请确认：仓库根目录存在 `config.example.json` 与 `news_bot.py`、`requirements.txt`、`.github/workflows/feishu-daily-news.yml`。

### 本机已 `git init` 并提交后，推到 GitHub

1. 打开 [GitHub 新建仓库](https://github.com/new)，名称可填 `feishu-news-bot`，**不要**勾选添加 README（保持空仓库）。
2. 在项目目录执行（把 URL 换成你的仓库 HTTPS 地址）：

```powershell
cd "d:\人工智能\cloud code"
.\push-to-github.ps1 -RemoteUrl "https://github.com/你的用户名/feishu-news-bot.git"
```

若提示登录，按 GitHub 要求用浏览器或 Personal Access Token 完成认证。推送成功后，在仓库 **Settings → Secrets → Actions** 添加 `FEISHU_WEBHOOK`。

若你之前在本机建过「每天 10 点」的 Windows 计划任务，为避免 **重复推送两条**，请删除该任务：

```powershell
schtasks /Delete /TN "FeishuDailyNews" /F
```

## 本地运行（可选）

1. 安装 Python 3.10+。
2. `pip install -r requirements.txt`
3. 复制配置：`copy config.example.json config.json`，并填写 `feishu_webhook`。
4. 测试：`python news_bot.py --dry-run` 或 `python news_bot.py`

### 配置项说明

| 字段 | 含义 |
|------|------|
| `feishu_webhook` | 飞书自定义机器人 Webhook |
| `max_items_per_category` | 每个板块最多条数 |
| `summary_max_chars` | 单条摘要总长度上限（含「要点」列表） |
| `feishu_text_chunk_size` | 单条飞书消息最大字符数，超长自动分多条发送 |
| `feeds.tech_ai` / `feeds.finance` | RSS 地址列表 |

环境变量 `FEISHU_WEBHOOK` 可覆盖配置文件中的 Webhook（CI 使用）。

补发某天简报（本地执行，标题带「补发」）：`python news_bot.py --supplement`

## 说明

- 部分境外 RSS 在国内网络可能不稳定，可在 `feeds` 中增删源。
- 摘要由 RSS 正文提炼；专有名词可保留英文。
