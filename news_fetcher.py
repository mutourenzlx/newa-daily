"""
新闻搜索与过滤引擎 v2.1
- 调用 web_search 获取真实新闻
- 严格过滤：仅保留 24h 窗口内新闻 + 有效URL
- 相关度打分 + 分类
- 时间窗口：前一天08:00 → 当天08:00
"""

import re
import json
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any

from app.config import (
    KEYWORD_GROUPS, SOURCE_WEIGHTS, EXCLUDE_WORDS,
    HIGH_RELEVANCE_KEYWORDS, REPORT, SCHEDULER
)

# ──────────────────────────────────────────────
# 日期工具
# ──────────────────────────────────────────────
CST = timezone(timedelta(hours=8))


def get_today_cst() -> datetime:
    """获取中国标准时间当前日期时间"""
    return datetime.now(CST)


def get_time_window(target: Optional[datetime] = None) -> tuple[datetime, datetime]:
    """
    计算 24 小时采集窗口

    逻辑：以 target（默认为当前时间）为基准
      - 窗口结束 = target 当天 08:00
      - 窗口开始 = 前一天 08:00

    举例：target = 8月18日 08:00
      → 窗口 = 8月17日 08:00 ~ 8月18日 08:00

    这样保证每天 08:00 跑时，覆盖的是"过去完整一天"的新闻。
    """
    if target is None:
        target = get_today_cst()

    # 窗口结束 = 当天 08:00
    anchor_hour = REPORT.get("anchor_hour", 8)
    today_anchor = target.replace(
        hour=anchor_hour, minute=0, second=0, microsecond=0
    )

    # 如果当前时间还没到今天的 anchor（比如凌晨跑），窗口往前推一天
    if target < today_anchor:
        today_anchor = today_anchor - timedelta(days=1)

    window_end = today_anchor
    window_start = today_anchor - timedelta(hours=REPORT.get("lookback_hours", 24))

    return window_start, window_end


def parse_date_to_cst(date_str: str, fallback: datetime) -> Optional[datetime]:
    """
    将各种格式的中文/英文日期解析为 CST datetime
    解析失败返回 None
    """
    if not date_str:
        return None

    date_str = date_str.strip()
    now = fallback

    # 相对时间表达
    rel_rules = [
        (r"刚刚|刚才", timedelta(minutes=0)),
        (r"(\d+)\s*分钟前", lambda m: timedelta(minutes=int(m.group(1)))),
        (r"(\d+)\s*小时前", lambda m: timedelta(hours=int(m.group(1)))),
        (r"(\d+)\s*天前|(\d+)\s*日前", lambda m: timedelta(days=int(m.group(1) or m.group(2)))),
        (r"昨天|昨日", timedelta(days=1)),
        (r"前天|前日", timedelta(days=2)),
        (r"今天|今日", timedelta(days=0)),
        (r"今天\s*\d{1,2}:\d{2}", timedelta(days=0)),
    ]
    for pat, delta in rel_rules:
        m = re.search(pat, date_str)
        if m:
            try:
                d = delta if isinstance(delta, timedelta) else delta(m)
            except Exception:
                d = timedelta(days=0)
            return now - d

    # 标准格式: 2026-08-17 / 2026/08/17 / 2026.08.17
    # 设为中午12:00，避免00:00被窗口边界（08:00）误判为窗口外
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", date_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 12, 0, 0, tzinfo=CST)

    # 中文格式: 2026年8月17日
    m = re.search(r"(\d{4})年(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), 12, 0, 0, tzinfo=CST)

    # 短格式: 8月17日（默认当年）
    m = re.search(r"(\d{1,2})月(\d{1,2})日", date_str)
    if m:
        return datetime(now.year, int(m.group(1)), int(m.group(2)), 12, 0, 0, tzinfo=CST)

    # 英文格式: Aug 17, 2026
    eng_months = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
        "july": 7, "august": 8, "september": 9, "october": 10,
        "november": 11, "december": 12,
    }
    m = re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", date_str)
    if m:
        mon = eng_months.get(m.group(1).lower())
        if mon:
            return datetime(int(m.group(3)), mon, int(m.group(2)), tzinfo=CST)

    return None


def is_within_window(dt: Optional[datetime], start: datetime, end: datetime) -> bool:
    """
    判断日期是否在 24h 窗口内
    使用日期级别比较（忽略具体时分秒），避免边界误判
    """
    if dt is None:
        return False
    dt_date = dt.date()
    start_date = start.date()
    end_date = end.date()
    return start_date <= dt_date <= end_date


# ──────────────────────────────────────────────
# URL 校验
# ──────────────────────────────────────────────
def is_valid_url(url: str) -> bool:
    """严格校验 URL：必须以 http/https 开头，排除伪链接"""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not (url.startswith("http://") or url.startswith("https://")):
        return False
    if len(url) < 12:
        return False
    invalid_patterns = [
        r"^https?://#", r"^javascript:", r"^about:blank",
        r"^http://example", r"^https://example",
        r"placeholder", r"xxx\.xxx",
    ]
    for pat in invalid_patterns:
        if re.match(pat, url, re.IGNORECASE):
            return False
    return True


# ──────────────────────────────────────────────
# 新闻解析
# ──────────────────────────────────────────────
def parse_search_result_item(
    raw: Dict, category: str, window_start: datetime, window_end: datetime
) -> Optional[Dict]:
    """
    将单条搜索结果解析为标准化新闻条目
    严格校验：日期必须在 24h 窗口内 + URL 必须有效
    """
    title = (raw.get("title") or raw.get("name") or "").strip()
    url = (raw.get("url") or raw.get("link") or "").strip()
    snippet = (raw.get("snippet") or raw.get("description") or raw.get("summary") or "").strip()
    source = (raw.get("source") or raw.get("site") or "").strip()
    date_str = (raw.get("date") or raw.get("publish_date") or raw.get("time") or "").strip()

    # 必须字段
    if not title or not url:
        return None

    # URL 校验
    if not is_valid_url(url):
        return None

    # 日期解析：先用原始 date_str
    parsed_date = parse_date_to_cst(date_str, fallback=window_end)
    if not is_within_window(parsed_date, window_start, window_end):
        # 尝试从 snippet 或 url 中再找日期
        for text in [snippet, url]:
            d = parse_date_to_cst(text, fallback=window_end)
            if is_within_window(d, window_start, window_end):
                parsed_date = d
                break
        else:
            return None  # 不在窗口内，丢弃

    return {
        "title": title,
        "url": url,
        "snippet": snippet,
        "source": source or extract_domain(url),
        "date": parsed_date.strftime("%Y-%m-%d"),
        "date_display": parsed_date.strftime("%Y年%m月%d日"),
        "category": category,
        "relevance": 0,
    }


def extract_domain(url: str) -> str:
    """从 URL 提取域名作为来源名"""
    m = re.search(r"https?://(?:www\.)?([^/]+)", url)
    return m.group(1) if m else url[:40]


# ──────────────────────────────────────────────
# 相关度打分
# ──────────────────────────────────────────────
def score_relevance(item: Dict) -> int:
    """1-10 相关度评分"""
    score = 3
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()

    for kw in HIGH_RELEVANCE_KEYWORDS:
        if kw.lower() in text:
            score += 1
            if kw in ("商飞", "中国商飞", "comac", "c919", "c929"):
                score += 1

    if re.search(r"[0-9]+[\.0-9]*\s*(亿|万|元|美元|eur|usd)", text):
        score += 1

    domain = item.get("source", "").lower()
    for key, weight in SOURCE_WEIGHTS.items():
        if key.lower() in domain:
            score += weight
            break

    for w in EXCLUDE_WORDS:
        if w.lower() in text:
            score -= 3
            break

    return max(1, min(10, score))


def classify_category(item: Dict, all_categories: List[str]) -> str:
    """根据内容细分类别"""
    text = (item.get("title", "") + " " + item.get("snippet", "")).lower()

    supplier_kw = ["供应商", "准入", "认证", "入选", "中标", "招标", "配套"]
    order_kw = ["订单", "采购", "合同", "协议", "交付", "购买", "亿元", "签约"]
    policy_kw = ["政策", "规划", "法规", "管制", "适航", "民航局", "工信部", "发改委"]

    for kw in supplier_kw:
        if kw in text:
            return "新增供应商"
    for kw in order_kw:
        if kw in text:
            return "大额订单"
    for kw in policy_kw:
        if kw in text:
            return "政策法规"

    return item.get("category", "综合动态")


# ──────────────────────────────────────────────
# 去重
# ──────────────────────────────────────────────
def deduplicate(items: List[Dict]) -> List[Dict]:
    """
    基于标题相似度去重
    策略：提取标题核心词（去标点+去常见后缀），用前25字符做指纹
    """
    seen_fingerprints = []
    unique = []
    for item in items:
        # 清洗标题：去标点、转小写
        clean = re.sub(r"[^\u4e00-\u9fff\w]", "", item["title"]).lower()
        # 去掉常见冗余后缀
        clean = re.sub(r"(详细报道|最新|全文|快讯|速递|独家)$", "", clean)
        # 取前25字符作为指纹
        fingerprint = clean[:25]
        if fingerprint in seen_fingerprints:
            continue
        seen_fingerprints.append(fingerprint)
        unique.append(item)
    return unique


# ──────────────────────────────────────────────
# 核心流程：搜索 → 解析 → 过滤 → 打分 → 排序
# ──────────────────────────────────────────────
def fetch_all_news(target_date: Optional[datetime] = None) -> Dict[str, List[Dict]]:
    """
    主入口：执行全部搜索并返回分类好的新闻
    时间窗口 = 前一天08:00 → 当天08:00（24h）
    """
    if target_date is None:
        target_date = get_today_cst()

    window_start, window_end = get_time_window(target_date)
    print(f"[INFO] ════════════════════════════════════════")
    print(f"[INFO] 采集窗口: {window_start.strftime('%Y-%m-%d %H:%M')} → {window_end.strftime('%Y-%m-%d %H:%M')} (CST)")
    print(f"[INFO] ════════════════════════════════════════")

    all_items = []

    # 构建所有搜索 query
    queries = []
    for category, keywords in KEYWORD_GROUPS.items():
        for kw in keywords:
            queries.append((kw, category))

    print(f"[INFO] 共 {len(queries)} 条关键词 query")

    for kw, category in queries:
        try:
            # 在 query 中附加日期限定，提高当日命中率
            date_hint = window_end.strftime("%Y年%m月")
            full_query = f"{kw} {date_hint}"

            from web_search import web_search
            result = web_search(
                description=f"搜索商飞供应链新闻: {kw}",
                query=[full_query]
            )

            raw_items = _extract_raw_items(result)

            for raw in raw_items:
                if not isinstance(raw, dict):
                    continue
                item = parse_search_result_item(raw, category, window_start, window_end)
                if item is not None:
                    all_items.append(item)

            print(f"  [✓] {kw} → {len(raw_items)} 条原始结果")

        except Exception as e:
            print(f"  [✗] {kw} → 搜索失败: {e}")
            continue

    print(f"[INFO] 窗口内有效新闻: {len(all_items)} 条")

    # 去重
    all_items = deduplicate(all_items)
    print(f"[INFO] 去重后: {len(all_items)} 条")

    # 打分
    for item in all_items:
        item["relevance"] = score_relevance(item)

    # 过滤低分
    min_score = REPORT["min_relevance_score"]
    all_items = [i for i in all_items if i["relevance"] >= min_score]
    print(f"[INFO] 过滤相关度<{min_score}后: {len(all_items)} 条")

    # 重新分类
    for item in all_items:
        item["category"] = classify_category(item, list(KEYWORD_GROUPS.keys()))

    # 按分类分组
    categorized = {}
    for cat in ["新增供应商", "大额订单", "政策法规", "综合动态"]:
        categorized[cat] = [i for i in all_items if i["category"] == cat]

    # 各分类内按相关度降序 + 截断
    for cat in categorized:
        categorized[cat].sort(key=lambda x: x["relevance"], reverse=True)
        max_per = REPORT["max_items_per_category"]
        categorized[cat] = categorized[cat][:max_per]

    total = sum(len(v) for v in categorized.values())
    print(f"[INFO] 最终分类完成，总计 {total} 条")
    for cat, items in categorized.items():
        print(f"  {cat}: {len(items)} 条")

    return categorized


def _extract_raw_items(result) -> list:
    """从搜索结果中提取原始条目列表"""
    if isinstance(result, dict):
        return result.get("results", result.get("items", []))
    elif isinstance(result, list):
        return result
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
            if isinstance(parsed, dict):
                return parsed.get("results", parsed.get("items", []))
            elif isinstance(parsed, list):
                return parsed
        except json.JSONDecodeError:
            pass
    return []


# ──────────────────────────────────────────────
# 保存/加载缓存
# ──────────────────────────────────────────────
def save_cache(data: Dict, date_str: str, cache_dir: str = "output"):
    """保存搜索结果到 JSON 缓存"""
    from pathlib import Path
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    fpath = cache_path / f"cache_{date_str}.json"
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[INFO] 缓存已保存: {fpath}")


def load_cache(date_str: str, cache_dir: str = "output") -> Optional[Dict]:
    """加载缓存"""
    from pathlib import Path
    fpath = Path(cache_dir) / f"cache_{date_str}.json"
    if not fpath.exists():
        return None
    with open(fpath, "r", encoding="utf-8") as f:
        return json.load(f)


# ──────────────────────────────────────────────
# 入口：供定时任务调用（单次执行 = 采集+生成）
# ──────────────────────────────────────────────
def collect_and_generate(target_date: Optional[datetime] = None) -> str:
    """
    采集 + 生成一条龙（给 GitHub Actions 用）
    返回日期字符串 YYYYMMDD
    """
    if target_date is None:
        target_date = get_today_cst()

    date_str = target_date.strftime(REPORT["date_format"])

    # 1. 采集
    news = fetch_all_news(target_date)
    save_cache(news, date_str)

    # 2. 内容增强
    from app.content_processor import enrich_all
    news = enrich_all(news)

    # 3. 生成 PDF
    from app.pdf_generator import generate_report
    issue_no = (target_date - datetime(2026, 1, 1, tzinfo=CST)).days + 1
    result = generate_report(news, target_date, issue_no=issue_no)

    print(f"[INFO] ✅ 日报已生成: {result['filename']}")
    return date_str


# ──────────────────────────────────────────────
# 手动测试入口
# ──────────────────────────────────────────────
if __name__ == "__main__":
    test_date = get_today_cst()
    date_str = collect_and_generate(test_date)
    print(f"\n✅ 完成，日期: {date_str}")
