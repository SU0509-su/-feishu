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

云端运行时 **不会读取** 仓库里的 `config.json`（已加入 `.gitignore` 防泄露），只使用 `config.example.json` 中的订阅源 + Secret 里的 Webhook。

推送前请确认：仓库根目录存在 `config.example.json` 与 `news_bot.py`、`requirements.txt`、`.github/workflows/feishu-daily-news.yml`。

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

## 说明

- 部分境外 RSS 在国内网络可能不稳定，可在 `feeds` 中增删源。
- 摘要由 RSS 正文提炼；专有名词可保留英文。
