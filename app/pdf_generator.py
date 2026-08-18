"""
PDF 生成器
- 生成红头公文风格的 HTML 简报
- 使用 weasyprint 或 playwright 转为 PDF
- 每条新闻含可点击原文链接
"""

import re
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from app.config import REPORT, OUTPUT_DIR


# ──────────────────────────────────────────────
# 分类配置
# ──────────────────────────────────────────────
CATEGORY_CONFIG = {
    "新增供应商": {
        "icon": "🟢",
        "label": "新增供应商动态",
        "color": "#16a34a",
        "bg": "#f0fdf4",
        "border": "#22c55e",
    },
    "大额订单": {
        "icon": "🟠",
        "label": "大额订单与采购",
        "color": "#ea580c",
        "bg": "#fff7ed",
        "border": "#f97316",
    },
    "政策法规": {
        "icon": "🔵",
        "label": "政策法规与行业规划",
        "color": "#2563eb",
        "bg": "#eff6ff",
        "border": "#3b82f6",
    },
    "综合动态": {
        "icon": "⚪",
        "label": "产业链综合动态",
        "color": "#4b5563",
        "bg": "#f9fafb",
        "border": "#9ca3af",
    },
}

CATEGORY_ORDER = ["新增供应商", "大额订单", "政策法规", "综合动态"]


# ──────────────────────────────────────────────
# HTML 生成
# ──────────────────────────────────────────────
def generate_html(
    categorized: Dict[str, List[Dict]],
    report_date: datetime,
    issue_no: int = 1,
) -> str:
    """生成完整 HTML 简报"""

    date_str = report_date.strftime(REPORT["display_date_format"])
    weekday_cn = ["一", "二", "三", "四", "五", "六", "日"][report_date.weekday()]
    total_count = sum(len(v) for v in categorized.values())
    linked_count = sum(
        1 for items in categorized.values() for i in items
        if i.get("url") and i["url"].startswith(("http://", "https://"))
    )

    # 构建各分类 HTML
    sections_html = ""
    for cat_key in CATEGORY_ORDER:
        items = categorized.get(cat_key, [])
        if not items:
            continue
        cfg = CATEGORY_CONFIG[cat_key]
        sections_html += _render_section(cat_key, items, cfg)

    # 无新闻提示
    if total_count == 0:
        sections_html = """
        <div style="text-align:center; padding:60px 20px; color:#999; font-size:16px;">
            <p style="font-size:48px; margin-bottom:16px;">📭</p>
            <p>今日暂未监测到符合条件的商飞供应链相关新闻。</p>
            <p style="font-size:14px; margin-top:8px; color:#bbb;">系统将于明日继续监测。</p>
        </div>
        """

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{REPORT["title"]} {date_str}</title>
<style>
@page {{
    size: A4;
    margin: 20mm 18mm 22mm 18mm;
    @top-center {{
        content: "{REPORT["title"]} · {date_str}";
        font-size: 9pt;
        color: #999;
    }}
    @bottom-center {{
        content: "— 第 " counter(page) " 页 —";
        font-size: 9pt;
        color: #999;
    }}
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    font-family: "Noto Sans CJK SC", "WenQuanYi Micro Hei", "Microsoft YaHei", sans-serif;
    font-size: 10.5pt;
    line-height: 1.7;
    color: #1a1a1a;
    background: #fff;
}}
a {{ color: #2563eb; text-decoration: none; }}
a:hover {{ text-decoration: underline; }}

/* 红头标题区 */
.header {{
    text-align: center;
    padding: 16px 0 10px;
    border-bottom: 3px solid #c62828;
    margin-bottom: 6px;
}}
.header .red-bar {{
    background: #c62828;
    color: #fff;
    font-size: 11pt;
    padding: 4px 16px;
    display: inline-block;
    border-radius: 2px;
    margin-bottom: 10px;
    letter-spacing: 2px;
}}
.header h1 {{
    font-size: 22pt;
    color: #c62828;
    font-weight: 900;
    letter-spacing: 4px;
    margin: 6px 0 4px;
}}
.header .subtitle {{
    font-size: 10pt;
    color: #888;
    letter-spacing: 1px;
}}
.header .meta {{
    display: flex;
    justify-content: center;
    gap: 24px;
    margin-top: 8px;
    font-size: 9.5pt;
    color: #666;
}}
.header .meta span {{
    background: #f5f5f5;
    padding: 2px 10px;
    border-radius: 12px;
}}

/* 分隔线 */
.divider {{
    border: none;
    border-top: 1px dashed #ddd;
    margin: 10px 0;
}}

/* 分类区块 */
.section {{
    margin: 14px 0;
    break-inside: avoid;
}}
.section-header {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 0;
    border-bottom: 2px solid;
    margin-bottom: 10px;
}}
.section-header .icon {{ font-size: 16pt; }}
.section-header .title {{
    font-size: 13pt;
    font-weight: 700;
    letter-spacing: 1px;
}}
.section-header .count {{
    margin-left: auto;
    font-size: 9pt;
    color: #888;
    background: #f5f5f5;
    padding: 2px 8px;
    border-radius: 10px;
}}

/* 新闻卡片 */
.news-item {{
    padding: 10px 14px;
    margin-bottom: 10px;
    border-left: 4px solid;
    border-radius: 0 6px 6px 0;
    break-inside: avoid;
}}
.news-item .item-header {{
    display: flex;
    align-items: flex-start;
    gap: 6px;
    margin-bottom: 4px;
    flex-wrap: wrap;
}}
.news-item .item-title {{
    font-size: 11pt;
    font-weight: 700;
    color: #1a1a1a;
    flex: 1;
    min-width: 200px;
}}
.news-item .badge {{
    display: inline-block;
    font-size: 8pt;
    padding: 1px 7px;
    border-radius: 10px;
    color: #fff;
    white-space: nowrap;
    margin-top: 2px;
}}
.news-item .stars {{
    font-size: 9pt;
    color: #f59e0b;
    white-space: nowrap;
    margin-top: 2px;
}}
.news-item .summary {{
    font-size: 9.5pt;
    color: #444;
    line-height: 1.65;
    margin: 4px 0;
    text-align: justify;
}}
.news-item .key-points {{
    margin: 5px 0 4px 0;
    padding-left: 0;
    list-style: none;
}}
.news-item .key-points li {{
    font-size: 9pt;
    color: #555;
    padding-left: 14px;
    position: relative;
    line-height: 1.6;
}}
.news-item .key-points li::before {{
    content: "▸";
    position: absolute;
    left: 0;
    color: #999;
}}
.news-item .item-footer {{
    display: flex;
    flex-wrap: wrap;
    gap: 12px;
    font-size: 8.5pt;
    color: #888;
    margin-top: 5px;
    padding-top: 4px;
    border-top: 1px dotted #eee;
}}
.news-item .item-footer .source {{
    color: #666;
}}
.news-item .item-footer .date {{
    color: #666;
}}
.news-item .item-footer .amount {{
    color: #c62828;
    font-weight: 600;
}}
.news-item .item-footer .link a {{
    color: #2563eb;
    word-break: break-all;
}}
.news-item .item-footer .link.no-link {{
    color: #999;
}}

/* 页脚 */
.footer {{
    margin-top: 24px;
    padding-top: 12px;
    border-top: 2px solid #c62828;
    text-align: center;
    font-size: 8.5pt;
    color: #999;
    line-height: 1.8;
}}
.footer .disclaimer {{
    margin-top: 4px;
    font-size: 8pt;
    color: #bbb;
}}

/* 空状态 */
.empty-section {{
    text-align: center;
    padding: 20px;
    color: #bbb;
    font-size: 10pt;
}}
</style>
</head>
<body>

<!-- 红头区 -->
<div class="header">
    <div class="red-bar">内部资讯 · 每日简报</div>
    <h1>{REPORT["title"]}</h1>
    <div class="subtitle">{REPORT["subtitle"]}</div>
    <div class="meta">
        <span>📅 {date_str} 星期{weekday_cn}</span>
        <span>{REPORT["issue_prefix"]}{issue_no}{REPORT["issue_suffix"]}</span>
        <span>📰 共 {total_count} 条新闻</span>
        <span>🔗 {linked_count} 条含原文链接</span>
    </div>
</div>

<hr class="divider">

<!-- 正文区块 -->
{sections_html}

<!-- 页脚 -->
<div class="footer">
    <div>本简报由系统自动采集生成，仅供内部参考</div>
    <div class="disclaimer">
        新闻来源为公开网络信息，内容真实性请以原文为准<br>
        每条新闻均附原文链接，点击可查看完整报道
    </div>
</div>

</body>
</html>"""

    return html


def _render_section(cat_key: str, items: List[Dict], cfg: Dict) -> str:
    """渲染单个分类区块"""
    color = cfg["color"]
    bg = cfg["bg"]
    border = cfg["border"]
    icon = cfg["icon"]
    label = cfg["label"]

    cards = ""
    for item in items:
        cards += _render_news_card(item, border, bg)

    if not cards:
        cards = f'<div class="empty-section">本类暂无符合条件的动态</div>'

    return f"""
<div class="section">
    <div class="section-header" style="border-color: {border};">
        <span class="icon">{icon}</span>
        <span class="title" style="color: {color};">{label}</span>
        <span class="count">{len(items)} 条</span>
    </div>
    {cards}
</div>
"""


def _render_news_card(item: Dict, border_color: str, bg_color: str) -> str:
    """渲染单条新闻卡片"""
    title = item.get("title", "").strip()
    summary = item.get("summary", item.get("snippet", "")).strip()
    url = item.get("url", "").strip()
    source = item.get("source", "未知来源").strip()
    date_display = item.get("date_display", "").strip()
    relevance = int(item.get("relevance", 0))
    amount = item.get("amount", "")
    key_points = item.get("key_points", [])

    # 相关度星级
    stars = "★" * relevance + "☆" * (10 - relevance)

    # 金额标签
    amount_html = f'<span class="amount">💰 {amount}</span>' if amount else ""

    # 原文链接
    if url and (url.startswith("http://") or url.startswith("https://")):
        link_html = f'<span class="link"><a href="{url}" target="_blank" rel="noopener">🔗 原文链接</a></span>'
    else:
        link_html = '<span class="link no-link">⚠️ 无原文链接</span>'

    # 关键要点
    kp_html = ""
    if key_points:
        kp_items = "".join(f"<li>{kp}</li>" for kp in key_points)
        kp_html = f'<ul class="key-points">{kp_items}</ul>'

    return f"""
<div class="news-item" style="border-color: {border_color}; background: {bg_color};">
    <div class="item-header">
        <span class="item-title">{title}</span>
        <span class="badge" style="background: {border_color};">{source}</span>
        <span class="stars" title="相关度 {relevance}/10">{stars}</span>
    </div>
    <div class="summary">{summary}</div>
    {kp_html}
    <div class="item-footer">
        <span class="source">📌 {source}</span>
        <span class="date">📅 {date_display}</span>
        {amount_html}
        {link_html}
    </div>
</div>
"""


# ──────────────────────────────────────────────
# PDF 生成（使用 weasyprint）
# ──────────────────────────────────────────────
def html_to_pdf(html: str, output_path: str) -> str:
    """将 HTML 转为 PDF"""
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration

        font_config = FontConfiguration()
        HTML(string=html).write_pdf(
            output_path,
            font_config=font_config,
        )
        print(f"[INFO] PDF 已生成 (weasyprint): {output_path}")
        return output_path

    except ImportError:
        print("[WARN] weasyprint 不可用，尝试 playwright...")

    try:
        import asyncio
        from playwright.async_api import async_playwright

        async def _render():
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                await page.set_content(html, wait_until="networkidle")
                await page.pdf(
                    path=output_path,
                    format="A4",
                    print_background=True,
                    margin={"top": "20mm", "bottom": "22mm", "left": "18mm", "right": "18mm"},
                )
                await browser.close()

        asyncio.run(_render())
        print(f"[INFO] PDF 已生成 (playwright): {output_path}")
        return output_path

    except ImportError:
        print("[WARN] playwright 也不可用，保存 HTML 作为替代...")

    # 最终回退：保存 HTML
    html_path = output_path.replace(".pdf", ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[INFO] HTML 已保存 (PDF引擎不可用): {html_path}")
    return html_path


# ──────────────────────────────────────────────
# 对外主入口
# ──────────────────────────────────────────────
def generate_report(
    categorized: Dict[str, List[Dict]],
    report_date: datetime,
    issue_no: int = 1,
    output_dir: Optional[str] = None,
) -> Dict[str, str]:
    """
    生成日报 HTML + PDF
    返回: {"html": 路径, "pdf": 路径, "filename": 文件名}
    """
    if output_dir is None:
        output_dir = str(OUTPUT_DIR)
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # 文件名: 商飞供应链动态日报-YYYYMMDD
    date_str_file = report_date.strftime(REPORT["date_format"])
    filename = REPORT["filename_pattern"].format(date=date_str_file)
    base_name = filename.replace(".pdf", "")

    html_path = str(Path(output_dir) / f"{base_name}.html")
    pdf_path = str(Path(output_dir) / f"{base_name}.pdf")

    # 生成 HTML
    html = generate_html(categorized, report_date, issue_no)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[INFO] HTML 已生成: {html_path}")

    # 转 PDF
    result_path = html_to_pdf(html, pdf_path)

    return {
        "html": html_path,
        "pdf": result_path if result_path.endswith(".pdf") else html_path,
        "filename": filename,
        "is_pdf": result_path.endswith(".pdf"),
    }


# ──────────────────────────────────────────────
# 测试入口
# ──────────────────────────────────────────────
if __name__ == "__main__":
    # 用模拟数据测试 HTML 渲染
    sample = {
        "新增供应商": [
            {
                "title": "景航公司成功入选商飞钛合金供应商名录",
                "url": "https://www.example.com/news/1",
                "snippet": "近日，景航公司正式通过中国商飞供应商审核，成为钛合金材料合格供应商，将为民机项目提供关键原材料。",
                "source": "航空新闻网",
                "date_display": "2026年08月17日",
                "relevance": 9,
                "summary": "景航公司正式通过中国商飞供应商审核，成为钛合金材料合格供应商。",
                "key_points": ["通过商飞供应商审核", "提供钛合金关键原材料", "涉及民机项目供应链"],
                "amount": "",
            },
        ],
        "大额订单": [
            {
                "title": "商飞与某材料集团签署50亿元采购协议",
                "url": "https://www.example.com/news/2",
                "snippet": "中国商飞与某大型材料集团签署战略采购协议，合同金额达50亿元人民币，覆盖未来三年机身材料供应。",
                "source": "财新网",
                "date_display": "2026年08月17日",
                "relevance": 10,
                "summary": "中国商飞与某大型材料集团签署战略采购协议，合同金额达50亿元人民币。",
                "key_points": ["合同金额50亿元", "覆盖三年机身材料供应", "战略级合作协议"],
                "amount": "50亿元人民币",
            },
        ],
        "政策法规": [],
        "综合动态": [],
    }

    result = generate_report(sample, datetime.now(), issue_no=27)
    print(f"\n✅ 测试完成: {result}")
