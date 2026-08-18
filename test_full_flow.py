"""
端到端测试脚本：验证 24h 窗口逻辑 + 日期过滤 + URL 校验
不依赖真实搜索API，用模拟数据覆盖核心逻辑
"""

import sys
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

# 确保能导入 app 模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.news_fetcher import (
    get_time_window, parse_date_to_cst, is_valid_url,
    parse_search_result_item, score_relevance, deduplicate,
    is_within_window,
)
from app.config import REPORT, OUTPUT_DIR

CST = timezone(timedelta(hours=8))

PASS = "✅ PASS"
FAIL = "❌ FAIL"
results = []

def check(name, condition, detail=""):
    status = PASS if condition else FAIL
    results.append((status, name, detail))
    print(f"  {status}  {name}  {detail}")

print("╔════════════════════════════════════════╗")
print("║  商飞供应链日报 v2.1 — 端到端测试     ║")
print("╚════════════════════════════════════════╝\n")

# ══════════════════════════════════════
# Test 1: 时间窗口计算
# ══════════════════════════════════════
print("【Test 1】时间窗口计算")
now = datetime(2026, 8, 18, 8, 0, 0, tzinfo=CST)  # 8月18日 08:00
start, end = get_time_window(now)
expected_start = datetime(2026, 8, 17, 8, 0, 0, tzinfo=CST)
expected_end = datetime(2026, 8, 18, 8, 0, 0, tzinfo=CST)

check("窗口结束 = 当天08:00", end == expected_end, f"got {end}")
check("窗口开始 = 前一天08:00", start == expected_start, f"got {start}")
check("窗口跨度 = 24小时", (end - start) == timedelta(hours=24), f"got {end-start}")

# 测试凌晨边界（还没到08:00的情况）
now_early = datetime(2026, 8, 18, 3, 0, 0, tzinfo=CST)
start2, end2 = get_time_window(now_early)
check("凌晨3点→窗口往前推一天", end2 == datetime(2026, 8, 17, 8, 0, 0, tzinfo=CST), f"got {end2}")

print()

# ══════════════════════════════════════
# Test 2: 日期解析器
# ══════════════════════════════════════
print("【Test 2】日期解析器")
fallback = datetime(2026, 8, 18, 8, 0, 0, tzinfo=CST)

cases = [
    ("2026-08-17", datetime(2026, 8, 17, tzinfo=CST), "标准格式 YYYY-MM-DD"),
    ("2026/8/17", datetime(2026, 8, 17, tzinfo=CST), "斜杠格式"),
    ("2026年8月17日", datetime(2026, 8, 17, tzinfo=CST), "中文格式"),
    ("8月17日", datetime(2026, 8, 17, tzinfo=CST), "短格式（默认当年）"),
    ("昨天", fallback - timedelta(days=1), "相对时间：昨天"),
    ("3小时前", fallback - timedelta(hours=3), "相对时间：3小时前"),
    ("刚刚", fallback, "相对时间：刚刚"),
    ("", None, "空字符串返回None"),
    ("无效日期xyz", None, "无效日期返回None"),
]
for date_str, expected, desc in cases:
    result = parse_date_to_cst(date_str, fallback)
    if expected is None:
        check(desc, result is None, f'input="{date_str}" → {result}')
    else:
        check(desc, result is not None and result.date() == expected.date(),
              f'input="{date_str}" → {result}')

print()

# ══════════════════════════════════════
# Test 3: URL 校验
# ══════════════════════════════════════
print("【Test 3】URL 校验")
url_cases = [
    ("https://www.example.com/news/1", True, "标准https链接"),
    ("http://news.sina.com.cn/article", True, "标准http链接"),
    ("", False, "空字符串"),
    ("javascript:alert(1)", False, "javascript伪协议"),
    ("about:blank", False, "about:blank"),
    ("http://example.com", False, "长度不足12"),
    ("not-a-url", False, "非URL文本"),
    ("https://example.com", False, "长度不足（短域名）"),
]
for url, expected_valid, desc in url_cases:
    result = is_valid_url(url)
    check(desc, result == expected_valid, f'"{url}" → {result}')

print()

# ══════════════════════════════════════
# Test 4: 窗口内新闻过滤（核心！）
# ══════════════════════════════════════
print("【Test 4】24h窗口过滤（核心逻辑）")
window_start = datetime(2026, 8, 17, 8, 0, 0, tzinfo=CST)
window_end = datetime(2026, 8, 18, 8, 0, 0, tzinfo=CST)

news_cases = [
    # (标题, 日期字符串, 期望: 是否在窗口内)
    ("商飞新增供应商", "2026-08-17", True, "窗口第一天"),
    ("商飞大订单", "2026年8月18日", True, "窗口最后一天"),
    ("商飞供应链动态", "2026-08-16", False, "窗口前一天→丢弃"),
    ("商飞国际合作", "2026-08-19", False, "窗口后一天→丢弃"),
    ("商飞产能提速", "昨天", True, "相对时间昨天(在窗口内)"),
    ("商飞新协议", "3天前", False, "3天前→丢弃"),
]
for title, date_str, should_keep, desc in news_cases:
    parsed = parse_date_to_cst(date_str, fallback=window_end)
    in_window = is_within_window(parsed, window_start, window_end)
    check(f"{desc}: {title}", in_window == should_keep,
          f'date="{date_str}" → in_window={in_window}')

print()

# ══════════════════════════════════════
# Test 5: parse_search_result_item 完整流程
# ══════════════════════════════════════
print("【Test 5】新闻条目解析（含URL校验+窗口过滤）")
raw_valid = {
    "title": "商飞与某公司签署50亿采购协议",
    "url": "https://finance.sina.com.cn/2026-08-17/news-abc.html",
    "snippet": "中国商飞与某材料集团签署战略采购协议，合同金额达50亿元",
    "source": "新浪财经",
    "date": "2026-08-17",
}
item = parse_search_result_item(raw_valid, "大额订单", window_start, window_end)
check("有效新闻→保留", item is not None, f'title={item["title"][:20] if item else "None"}')
if item:
    check("  → 日期正确", item["date"] == "2026-08-17", f'got {item["date"]}')
    check("  → URL保留", item["url"].startswith("https://"), f'got {item["url"][:30]}')

# 无URL → 丢弃
raw_no_url = {"title": "商飞新闻", "url": "", "snippet": "test", "date": "2026-08-17"}
item2 = parse_search_result_item(raw_no_url, "综合动态", window_start, window_end)
check("无URL新闻→丢弃", item2 is None, "")

# 伪URL → 丢弃
raw_bad_url = {"title": "商飞新闻", "url": "javascript:void(0)", "snippet": "test", "date": "2026-08-17"}
item3 = parse_search_result_item(raw_bad_url, "综合动态", window_start, window_end)
check("伪URL新闻→丢弃", item3 is None, "")

# 过时新闻 → 丢弃
raw_old = {
    "title": "商飞2025年规划",
    "url": "https://example.com/old-news",
    "snippet": "2025年的旧新闻",
    "date": "2025-01-01",
}
item4 = parse_search_result_item(raw_old, "政策法规", window_start, window_end)
check("过时新闻(2025)→丢弃", item4 is None, "")

print()

# ══════════════════════════════════════
# Test 6: 相关度打分
# ══════════════════════════════════════
print("【Test 6】相关度打分")
high_item = {
    "title": "中国商飞C919新增供应商名单公布",
    "snippet": "商飞宣布新增5家供应商，涉及亿元级采购合同",
}
score_high = score_relevance(high_item)
check("高相关新闻≥7分", score_high >= 7, f'got {score_high}/10')

low_item = {
    "title": "今日天气晴好",
    "snippet": "北京今天天气不错，适合出行",
}
score_low = score_relevance(low_item)
check("无关新闻≤3分", score_low <= 3, f'got {score_low}/10')

print()

# ══════════════════════════════════════
# Test 7: 去重
# ══════════════════════════════════════
print("【Test 7】去重")
dup_items = [
    {"title": "商飞新增供应商A公司", "url": "https://a.com/1"},
    {"title": "商飞新增供应商A公司（详细报道）", "url": "https://b.com/2"},  # 前20字符相同
    {"title": "商飞与B公司签署大订单", "url": "https://c.com/3"},
]
unique = deduplicate(dup_items)
check("相似标题去重", len(unique) == 2, f'got {len(unique)} (expected 2)')

print()

# ══════════════════════════════════════
# Test 8: PDF命名
# ══════════════════════════════════════
print("【Test 8】PDF 文件命名")
from app.pdf_generator import generate_report
sample = {
    "新增供应商": [{
        "title": "景航公司入选商飞钛合金供应商",
        "url": "https://www.example.com/news/1",
        "snippet": "景航公司正式通过中国商飞供应商审核，成为钛合金材料合格供应商。",
        "source": "航空新闻网",
        "date_display": "2026年08月17日",
        "relevance": 9,
        "summary": "景航公司正式通过中国商飞供应商审核。",
        "key_points": ["通过商飞供应商审核", "提供钛合金原材料"],
        "amount": "",
    }],
    "大额订单": [{
        "title": "商飞与材料集团签署50亿元采购协议",
        "url": "https://www.example.com/news/2",
        "snippet": "中国商飞与某大型材料集团签署战略采购协议，合同金额达50亿元人民币。",
        "source": "财新网",
        "date_display": "2026年08月17日",
        "relevance": 10,
        "summary": "中国商飞与材料集团签署50亿元采购协议。",
        "key_points": ["合同金额50亿元", "覆盖三年供应"],
        "amount": "50亿元人民币",
    }],
    "政策法规": [],
    "综合动态": [],
}

test_date = datetime(2026, 8, 18, 8, 0, 0, tzinfo=CST)
result = generate_report(sample, test_date, issue_no=230)
expected_name = "商飞供应链动态日报-20260818.pdf"
check("文件名=采集当天日期", result["filename"] == expected_name, f'got {result["filename"]}')
check("PDF文件已生成", Path(result["pdf"]).exists(), f'path={result["pdf"]}')

print(f"\n📄 PDF 生成路径: {result['pdf']}")
print(f"📄 HTML 生成路径: {result['html']}")

# ══════════════════════════════════════
# 汇总
# ══════════════════════════════════════
print("\n" + "═"*48)
passed = sum(1 for r in results if r[0] == PASS)
failed = sum(1 for r in results if r[0] == FAIL)
total = len(results)
print(f"  总计: {total}  |  ✅ {passed} 通过  |  ❌ {failed} 失败")
if failed > 0:
    print("\n  失败项:")
    for status, name, detail in results:
        if status == FAIL:
            print(f"    ❌ {name}  {detail}")
    sys.exit(1)
else:
    print("\n  🎉 全部通过！24h窗口逻辑验证成功")
    sys.exit(0)
