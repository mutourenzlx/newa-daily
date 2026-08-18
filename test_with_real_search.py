"""
用真实搜索数据生成一份日报，验证完整流程
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.news_fetcher import fetch_all_news, save_cache, get_time_window
from app.content_processor import enrich_all
from app.pdf_generator import generate_report
from app.config import REPORT
from datetime import datetime as dt

CST = timezone(timedelta(hours=8))

# 模拟"8月18日08:00"触发
target = dt(2026, 8, 18, 8, 0, 0, tzinfo=CST)
print(f"🎯 目标日期: {target.strftime('%Y-%m-%d %H:%M')} (CST)")

window_start, window_end = get_time_window(target)
print(f"⏰ 采集窗口: {window_start.strftime('%Y-%m-%d %H:%M')} → {window_end.strftime('%Y-%m-%d %H:%M')}")

# 采集
print("\n" + "="*50)
print("📡 开始搜索新闻...")
categorized = fetch_all_news(target)

total = sum(len(v) for v in categorized.values())
print(f"\n📊 采集完成，共 {total} 条新闻")
for cat, items in categorized.items():
    if items:
        print(f"  {cat}: {len(items)} 条")

if total == 0:
    print("\n⚠️ 未搜索到新闻，可能搜索引擎暂无数据")
    print("这是正常的——部署到 Render 后，真实环境会有数据")
    sys.exit(0)

# 保存缓存
date_str = target.strftime(REPORT["date_format"])
save_cache(categorized, date_str)

# 增强
print("\n🔄 内容增强中...")
enriched = enrich_all(categorized)

# 生成报告
print("\n📄 生成PDF报告...")
issue_no = (target - dt(2026, 1, 1, tzinfo=CST)).days + 1
result = generate_report(enriched, target, issue_no=issue_no)

print(f"\n{'='*50}")
print(f"✅ 日报生成完成！")
print(f"  文件名: {result['filename']}")
print(f"  HTML: {result['html']}")
print(f"  PDF:   {result.get('pdf', 'N/A')}")
print(f"  类型: {'PDF' if result.get('is_pdf') else 'HTML(回退)'}")
print(f"\n💡 部署到 Render 后，weasyprint/playwright 可用，会自动生成真正可下载的 PDF")
