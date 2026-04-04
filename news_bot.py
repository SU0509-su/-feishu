import argparse
import base64
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote, urlparse

import feedparser
import requests


SHANGHAI_TZ = timezone(timedelta(hours=8))
SOURCE_ZH_MAP = {
    "reuters.com": "路透社",
    "theverge.com": "The Verge科技媒体",
    "wired.com": "连线杂志",
    "technologyreview.com": "MIT科技评论",
    "wsj.com": "华尔街日报",
    "ft.com": "金融时报",
    "caixin.com": "财新",
    "36kr.com": "36氪",
    "wallstreetcn.com": "华尔街见闻",
    "bloomberg.com": "彭博社",
    "cnbc.com": "CNBC",
    "economist.com": "经济学人",
}

DEFAULT_SUMMARY_MAX_CHARS = 520
DEFAULT_CHUNK_SIZE = 3400
MAX_ENTRIES_PER_FEED = 35
# CI 去重：在仓库中记录「某日已发送」，避免多时段定时任务重复推飞书
MARKER_PATH = ".github/feishu-last-sent-date"
DEFAULT_BRANCH = "main"


@dataclass
class NewsItem:
    category: str
    title: str
    summary: str
    link: str
    source: str
    published_at: Optional[datetime]


def resolve_config_path(config_path: Path) -> Path:
    if config_path.exists():
        return config_path
    example = Path("config.example.json")
    if example.exists():
        return example
    raise FileNotFoundError(f"找不到配置文件: {config_path}（也无 config.example.json）")


def load_config(config_path: Path) -> Dict:
    path = resolve_config_path(config_path)
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    required = ["feishu_webhook", "max_items_per_category", "feeds"]
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Missing config keys: {missing}")
    for key in ("tech_ai", "finance"):
        if key not in data["feeds"] or not isinstance(data["feeds"][key], list):
            raise ValueError(f"feeds.{key} must be a list of RSS URLs")

    webhook = os.environ.get("FEISHU_WEBHOOK", "").strip()
    if webhook:
        data["feishu_webhook"] = webhook

    if not (data.get("feishu_webhook") or "").strip():
        raise ValueError(
            "未配置 feishu_webhook：请在 config.json 中填写，或在环境变量 FEISHU_WEBHOOK 中设置（推荐 GitHub Secrets）。"
        )

    if "summary_max_chars" not in data:
        data["summary_max_chars"] = DEFAULT_SUMMARY_MAX_CHARS
    if "feishu_text_chunk_size" not in data:
        data["feishu_text_chunk_size"] = DEFAULT_CHUNK_SIZE
    return data


def extract_source(url: str, fallback: str = "Unknown") -> str:
    try:
        host = urlparse(url).netloc.lower()
        host = re.sub(r"^www\.", "", host)
        return host or fallback
    except Exception:
        return fallback


def parse_published(entry) -> Optional[datetime]:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    try:
        return datetime(*parsed[:6], tzinfo=timezone.utc)
    except Exception:
        return None


def clean_text(text: str) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text: str) -> List[str]:
    if not text:
        return []
    parts = re.split(r"(?<=[.!?。！？])\s+", text)
    return [p.strip() for p in parts if p.strip()]


def build_detailed_summary(title: str, raw_summary: str, max_chars: int) -> str:
    title = clean_text(title)
    raw = clean_text(raw_summary)
    if raw and raw.lower().startswith(title.lower()):
        raw = raw[len(title) :].strip(" -:;,.")
    if not raw:
        raw = title

    sentences = split_sentences(raw)
    if not sentences:
        chunk = raw[:max_chars]
        return chunk + ("…" if len(raw) > max_chars else "")

    main_parts: List[str] = []
    used = 0
    soft_main_budget = int(max_chars * 0.58)
    for s in sentences:
        if main_parts and used + len(s) > soft_main_budget:
            break
        main_parts.append(s)
        used += len(s) + 1
        if used >= soft_main_budget and len(main_parts) >= 2:
            break
    main_text = " ".join(main_parts) if main_parts else sentences[0]

    rest = sentences[len(main_parts) :]
    bullets: List[str] = []
    budget_left = max_chars - len(main_text) - 20
    for s in rest:
        if budget_left <= 0:
            break
        line = s[: min(len(s), 220)]
        if len(s) > 220:
            line = line.rstrip() + "…"
        bullets.append(line)
        budget_left -= len(line) + 8
        if len(bullets) >= 6:
            break

    lines: List[str] = [main_text]
    if bullets:
        lines.append("要点：")
        for b in bullets:
            lines.append(f"  · {b}")

    out = "\n".join(lines)
    if len(out) > max_chars + 50:
        out = out[: max_chars + 47].rstrip() + "…"
    return out


def contains_english(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def is_mostly_chinese(text: str, ratio: float = 0.22) -> bool:
    if not text:
        return True
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    return cn / max(len(text), 1) >= ratio


def needs_translation(text: str) -> bool:
    if not text or not contains_english(text):
        return False
    # 只有中文占比足够高时才跳过翻译（避免英文里夹少量符号被误判）
    if is_mostly_chinese(text, ratio=0.35):
        return False
    return True


def _translate_google(text: str) -> str:
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "auto",
        "tl": "zh-CN",
        "dt": "t",
        "q": text,
    }
    resp = requests.get(url, params=params, timeout=(5, 18))
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, list) and data and isinstance(data[0], list):
        return "".join(part[0] for part in data[0] if isinstance(part, list) and part) or text
    return text


def _translate_mymemory_chunk(chunk: str) -> str:
    if not chunk.strip():
        return chunk
    r = requests.get(
        "https://api.mymemory.translated.net/get",
        params={"q": chunk, "langpair": "en|zh-CN"},
        timeout=(5, 20),
        headers={"User-Agent": "news-bot/1.0"},
    )
    r.raise_for_status()
    data = r.json()
    out = (data.get("responseData") or {}).get("translatedText") or chunk
    # API 偶发返回错误提示英文
    if "MYMEMORY WARNING" in out or "QUERY LENGTH LIMIT" in out:
        return chunk
    return out


def _translate_mymemory(text: str) -> str:
    text = text.strip()
    if len(text) <= 480:
        return _translate_mymemory_chunk(text)
    parts: List[str] = []
    for i in range(0, len(text), 450):
        parts.append(_translate_mymemory_chunk(text[i : i + 450]))
    return "".join(parts)


def translate_to_zh(text: str) -> str:
    text = (text or "").strip()
    if not needs_translation(text):
        return text
    original = text
    try:
        t = _translate_google(text)
        if t and not needs_translation(t):
            return t
        if t and is_mostly_chinese(t, ratio=0.12):
            return t
    except Exception:
        t = original
    try:
        t2 = _translate_mymemory(original)
        if t2 and t2.strip() != original.strip():
            return t2
    except Exception:
        pass
    return original


def translate_long_to_zh(text: str, max_chunk: int = 950) -> str:
    if not text:
        return text
    if not needs_translation(text):
        return text
    # Prefer few large chunks to avoid dozens of HTTP calls per article.
    if len(text) <= max_chunk:
        return translate_to_zh(text)
    blocks = text.split("\n\n")
    if len(blocks) > 1:
        out_blks: List[str] = []
        for blk in blocks:
            out_blks.append(
                translate_to_zh(blk[:max_chunk]) + ("…" if len(blk) > max_chunk else "")
                if needs_translation(blk)
                else blk
            )
        return "\n\n".join(out_blks)
    return translate_to_zh(text[:max_chunk]) + ("…" if len(text) > max_chunk else "")


def source_to_zh(source: str) -> str:
    source = (source or "").strip()
    if not source:
        return "未知来源"
    for domain, zh_name in SOURCE_ZH_MAP.items():
        if source == domain or source.endswith("." + domain):
            return zh_name
    return translate_to_zh(source)


def format_source(source: str) -> str:
    source_zh = source_to_zh(source)
    return f"{source}（{source_zh}）"


def fetch_feed_items(
    category: str, feed_url: str, summary_max_chars: int, timeout: Tuple[int, int] = (6, 14)
) -> List[NewsItem]:
    resp = requests.get(
        feed_url,
        timeout=timeout,
        headers={"User-Agent": "news-bot/1.0"},
    )
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    items: List[NewsItem] = []
    for entry in parsed.entries[:MAX_ENTRIES_PER_FEED]:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        if not title or not link:
            continue
        raw_summary = entry.get("summary") or entry.get("description") or ""
        source = extract_source(link, fallback=extract_source(feed_url))
        published_at = parse_published(entry)
        detailed = build_detailed_summary(title, raw_summary, summary_max_chars)
        items.append(
            NewsItem(
                category=category,
                title=title,
                summary=detailed,
                link=link,
                source=source,
                published_at=published_at,
            )
        )
    return items


def dedupe_items(items: List[NewsItem]) -> List[NewsItem]:
    seen: set[Tuple[str, str]] = set()
    result: List[NewsItem] = []
    for it in items:
        key = (it.title.lower(), it.link)
        if key in seen:
            continue
        seen.add(key)
        result.append(it)
    return result


def rank_items(items: List[NewsItem], limit: int) -> List[NewsItem]:
    def sort_key(it: NewsItem):
        ts = it.published_at.timestamp() if it.published_at else 0
        return ts

    return sorted(items, key=sort_key, reverse=True)[:limit]


def _localize_one(item: NewsItem) -> NewsItem:
    title_zh = translate_to_zh(item.title)
    summary_zh = translate_long_to_zh(item.summary)
    return NewsItem(
        category=item.category,
        title=title_zh,
        summary=summary_zh,
        link=item.link,
        source=format_source(item.source),
        published_at=item.published_at,
    )


def localize_items(items: List[NewsItem]) -> List[NewsItem]:
    if not items:
        return []
    workers = min(6, len(items))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(_localize_one, items))


def format_item_line(index: int, item: NewsItem) -> str:
    ts = ""
    if item.published_at:
        local_time = item.published_at.astimezone(SHANGHAI_TZ)
        ts = local_time.strftime("%m-%d %H:%M")
    suffix = f" | {ts}" if ts else ""
    return (
        f"{index}. {item.title}\n"
        f"摘要:\n{item.summary}\n"
        f"来源: {item.source}{suffix}\n"
        f"链接: {item.link}"
    )


def build_message(
    tech_items: List[NewsItem], finance_items: List[NewsItem], supplement: bool = False
) -> str:
    now_text = datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")
    tag = "【简报·补发】" if supplement else "【简报】"
    lines: List[str] = [
        f"{tag}每日新闻详细总结 {now_text}（北京时间）",
        "",
        "说明：标题与摘要已统一译为中文（机器翻译，Google 与备用接口）；专有名词可保留英文。",
        "",
        "────────",
        "一、科技 / AI",
        "────────",
        "",
    ]

    if tech_items:
        for idx, item in enumerate(tech_items, start=1):
            lines.append(format_item_line(idx, item))
            lines.append("")
    else:
        lines.append("本时段暂无可用科技/AI条目（源站可能超时或不可用）。")
        lines.append("")

    lines.extend(
        [
            "────────",
            "二、财经",
            "────────",
            "",
        ]
    )

    if finance_items:
        for idx, item in enumerate(finance_items, start=1):
            lines.append(format_item_line(idx, item))
            lines.append("")
    else:
        lines.append("本时段暂无可用财经条目（源站可能超时或不可用）。")
        lines.append("")

    lines.append("注：每条均附原始链接，便于溯源核对。")
    return "\n".join(lines).strip()


def send_to_feishu(webhook: str, message: str, timeout: int = 25) -> None:
    payload = {
        "msg_type": "text",
        "content": {"text": message},
    }
    resp = requests.post(webhook, json=payload, timeout=timeout)
    resp.raise_for_status()
    body = resp.json()
    if body.get("StatusCode", 0) != 0:
        raise RuntimeError(f"Feishu webhook error: {body}")


def send_to_feishu_chunked(webhook: str, message: str, chunk_size: int) -> None:
    if len(message) <= chunk_size:
        send_to_feishu(webhook, message)
        return
    parts: List[str] = []
    rest = message
    while rest:
        parts.append(rest[:chunk_size])
        rest = rest[chunk_size:]
    total = len(parts)
    for i, part in enumerate(parts):
        prefix = f"【简报 第{i + 1}/{total}部分】\n\n" if total > 1 else ""
        send_to_feishu(webhook, prefix + part)


def _today_shanghai() -> str:
    return datetime.now(SHANGHAI_TZ).strftime("%Y-%m-%d")


def _ci_dedup_enabled() -> bool:
    return os.environ.get("FEISHU_CI_DEDUP", "").strip().lower() in ("1", "true", "yes")


def _github_headers(token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def github_read_marker(repo: str, token: str) -> Tuple[Optional[str], Optional[str]]:
    enc = quote(MARKER_PATH, safe="")
    url = f"https://api.github.com/repos/{repo}/contents/{enc}"
    r = requests.get(
        url,
        headers=_github_headers(token),
        params={"ref": DEFAULT_BRANCH},
        timeout=25,
    )
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, dict) or data.get("type") != "file":
        return None, None
    sha = data.get("sha")
    b64 = data.get("content", "") or ""
    raw = base64.b64decode(b64).decode("utf-8").strip()
    return raw, sha


def github_write_marker(repo: str, token: str, date_str: str, old_sha: Optional[str]) -> None:
    content_b64 = base64.b64encode(date_str.encode("utf-8")).decode("ascii")
    enc = quote(MARKER_PATH, safe="")
    url = f"https://api.github.com/repos/{repo}/contents/{enc}"
    body: Dict[str, Any] = {
        "message": f"chore(bot): 简报已发送 {date_str}",
        "content": content_b64,
        "branch": DEFAULT_BRANCH,
    }
    if old_sha:
        body["sha"] = old_sha
    r = requests.put(url, headers=_github_headers(token), json=body, timeout=35)
    r.raise_for_status()


def ci_should_skip_duplicate_send() -> bool:
    if not _ci_dedup_enabled():
        return False
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not repo or not token:
        print("[WARN] FEISHU_CI_DEDUP 已开启但缺少 GITHUB_REPOSITORY/GITHUB_TOKEN，不去重。", flush=True)
        return False
    today = _today_shanghai()
    try:
        text, _ = github_read_marker(repo, token)
    except Exception as e:
        print(f"[WARN] 读取发送标记失败，继续发送: {e}", flush=True)
        return False
    return bool(text and text.strip() == today)


def ci_record_successful_send() -> None:
    if not _ci_dedup_enabled():
        return
    repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not repo or not token:
        return
    today = _today_shanghai()
    try:
        text, sha = github_read_marker(repo, token)
        if text and text.strip() == today:
            return
        github_write_marker(repo, token, today, sha)
        print(f"已写入今日发送标记: {today}", flush=True)
    except Exception as e:
        print(f"[WARN] 写入发送标记失败（极端情况下可能重复推送）: {e}", flush=True)


def collect_category_items(
    category: str, feeds: List[str], max_items: int, summary_max_chars: int
) -> List[NewsItem]:
    all_items: List[NewsItem] = []
    for url in feeds:
        try:
            all_items.extend(fetch_feed_items(category, url, summary_max_chars))
        except Exception as e:
            print(f"[WARN] Failed to read feed: {url} ({e})")
    all_items = dedupe_items(all_items)
    ranked_items = rank_items(all_items, max_items)
    return localize_items(ranked_items)


def main() -> None:
    parser = argparse.ArgumentParser(description="Daily news summary to Feishu group")
    parser.add_argument(
        "--config",
        default="config.json",
        help="Path to config JSON file (default: config.json, fallback: config.example.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print message without sending to Feishu",
    )
    parser.add_argument(
        "--supplement",
        action="store_true",
        help="Mark message as 补发 in title (e.g. make-up run for missed schedule)",
    )
    args = parser.parse_args()

    if _ci_dedup_enabled() and not args.supplement and ci_should_skip_duplicate_send():
        print("【简报】今日已成功发送过（仓库内标记），本次跳过。", flush=True)
        sys.exit(0)

    config = load_config(Path(args.config))
    max_items = int(config["max_items_per_category"])
    summary_max_chars = int(config.get("summary_max_chars", DEFAULT_SUMMARY_MAX_CHARS))
    chunk_size = int(config.get("feishu_text_chunk_size", DEFAULT_CHUNK_SIZE))

    print("【简报】正在抓取并生成摘要…", flush=True)
    tech_items = collect_category_items(
        "tech_ai", config["feeds"]["tech_ai"], max_items, summary_max_chars
    )
    print(f"科技/AI：已选 {len(tech_items)} 条", flush=True)
    finance_items = collect_category_items(
        "finance", config["feeds"]["finance"], max_items, summary_max_chars
    )
    print(f"财经：已选 {len(finance_items)} 条", flush=True)
    message = build_message(tech_items, finance_items, supplement=args.supplement)

    if args.dry_run:
        print(message)
        return

    send_to_feishu_chunked(config["feishu_webhook"], message, chunk_size)
    print("News sent to Feishu successfully.", flush=True)
    if _ci_dedup_enabled() and not args.supplement:
        ci_record_successful_send()


if __name__ == "__main__":
    main()
