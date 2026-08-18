"""
商飞供应链动态日报 — Web 服务入口 v2.1
FastAPI 应用：网页界面 + API 接口 + 往期归档
"""

import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Dict, List

from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.config import REPORT, OUTPUT_DIR, SCHEDULER
from app.news_fetcher import (
    fetch_all_news, save_cache, load_cache,
    get_today_cst, get_time_window, collect_and_generate,
)
from app.content_processor import enrich_all
from app.pdf_generator import generate_report

CST = timezone(timedelta(hours=8))

app = FastAPI(
    title="商飞供应链动态日报",
    description="自动采集、生成商飞供应链新闻日报 · 24h窗口模式",
    version="2.1.0",
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 静态文件
STATIC_DIR = Path(__file__).resolve().parent / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# ──────────────────────────────────────────────
# 工具函数
# ──────────────────────────────────────────────
def date_str_to_datetime(date_str: str) -> datetime:
    return datetime.strptime(date_str, "%Y%m%d").replace(tzinfo=CST)

def get_issue_no(report_date: datetime) -> int:
    base = datetime(2026, 1, 1, tzinfo=CST)
    return (report_date - base).days + 1

def find_existing_report(date_str: str) -> Optional[Dict]:
    """查找某日期是否已生成过报告"""
    pdf_path = OUTPUT_DIR / f"商飞供应链动态日报-{date_str}.pdf"
    html_path = OUTPUT_DIR / f"商飞供应链动态日报-{date_str}.html"
    cache_path = OUTPUT_DIR / f"cache_{date_str}.json"

    result = {"date": date_str, "has_pdf": pdf_path.exists(), "has_html": html_path.exists(), "has_cache": cache_path.exists()}

    if pdf_path.exists():
        result["pdf"] = str(pdf_path)
        result["filename"] = pdf_path.name
    if html_path.exists():
        result["html"] = str(html_path)
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            result["news_count"] = sum(len(v) for v in cached.values())
        except Exception:
            result["news_count"] = 0

    return result if (result["has_pdf"] or result["has_html"] or result["has_cache"]) else None

# ──────────────────────────────────────────────
# 主页
# ──────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = Path(__file__).resolve().parent / "templates" / "index.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))
    return HTMLResponse(content=_get_fallback_html())

# ──────────────────────────────────────────────
# API: 生成日报（手动触发 / 自动均可）
# ──────────────────────────────────────────────
@app.post("/api/generate")
async def api_generate(
    background_tasks: BackgroundTasks,
    date: Optional[str] = Query(None, description="日期 YYYYMMDD，默认今天"),
    force_refresh: bool = Query(False, description="是否强制重新搜索"),
):
    """
    生成指定日期的日报（采集+增强+PDF一条龙）
    全自动模式每天08:00由 GitHub Actions 调用此接口
    """
    if date:
        try:
            target = date_str_to_datetime(date)
        except ValueError:
            raise HTTPException(400, "日期格式错误，应为 YYYYMMDD")
    else:
        target = get_today_cst()

    date_str = target.strftime(REPORT["date_format"])
    issue_no = get_issue_no(target)

    # 尝试缓存
    cached = None if force_refresh else load_cache(date_str)
    if cached:
        print(f"[INFO] 使用缓存: {date_str}")
        categorized = cached
    else:
        print(f"[INFO] 开始采集: {date_str}")
        try:
            categorized = fetch_all_news(target)
            save_cache(categorized, date_str)
        except Exception as e:
            raise HTTPException(500, f"采集失败: {e}")

    # 增强
    categorized = enrich_all(categorized)

    # 生成报告
    try:
        result = generate_report(categorized, target, issue_no=issue_no)
    except Exception as e:
        raise HTTPException(500, f"PDF生成失败: {e}")

    total = sum(len(v) for v in categorized.values())
    linked = sum(
        1 for items in categorized.values() for i in items
        if i.get("url", "").startswith(("http://", "https://"))
    )

    return {
        "status": "success",
        "date": date_str,
        "issue_no": issue_no,
        "total_news": total,
        "linked_news": linked,
        "filename": result["filename"],
        "pdf_url": f"/api/download?file={Path(result['pdf']).name}" if result.get("is_pdf") else None,
        "html_url": f"/api/download?file={Path(result['html']).name}",
        "categories": {k: len(v) for k, v in categorized.items()},
        "from_cache": cached is not None,
        "window": _get_window_info(target),
    }

# ──────────────────────────────────────────────
# API: 预览（JSON 数据供前端渲染）
# ──────────────────────────────────────────────
@app.get("/api/preview")
async def api_preview(
    date: Optional[str] = Query(None),
    force_refresh: bool = Query(False),
):
    if date:
        try:
            target = date_str_to_datetime(date)
        except ValueError:
            raise HTTPException(400, "日期格式错误，应为 YYYYMMDD")
    else:
        target = get_today_cst()

    date_str = target.strftime(REPORT["date_format"])
    issue_no = get_issue_no(target)

    cached = None if force_refresh else load_cache(date_str)
    if cached:
        categorized = cached
    else:
        categorized = fetch_all_news(target)
        save_cache(categorized, date_str)

    categorized = enrich_all(categorized)

    cat_labels = {
        "新增供应商": "新增供应商动态",
        "大额订单": "大额订单与采购",
        "政策法规": "政策法规与行业规划",
        "综合动态": "产业链综合动态",
    }
    cat_icons = {
        "新增供应商": "🟢", "大额订单": "🟠",
        "政策法规": "🔵", "综合动态": "⚪",
    }

    preview = {
        "date": date_str,
        "date_display": target.strftime(REPORT["display_date_format"]),
        "issue_no": issue_no,
        "weekday": ["一","二","三","四","五","六","日"][target.weekday()],
        "total": sum(len(v) for v in categorized.values()),
        "window": _get_window_info(target),
        "categories": {}
    }

    for cat_key in ["新增供应商", "大额订单", "政策法规", "综合动态"]:
        items = categorized.get(cat_key, [])
        preview["categories"][cat_key] = {
            "label": cat_labels.get(cat_key, cat_key),
            "icon": cat_icons.get(cat_key, "📌"),
            "count": len(items),
            "items": [
                {
                    "title": i.get("title", ""),
                    "summary": i.get("summary", i.get("snippet", "")),
                    "url": i.get("url", ""),
                    "source": i.get("source", ""),
                    "date_display": i.get("date_display", ""),
                    "relevance": i.get("relevance", 0),
                    "amount": i.get("amount", ""),
                    "key_points": i.get("key_points", []),
                    "companies": i.get("companies", []),
                    "has_link": bool(i.get("url", "").startswith(("http://", "https://"))),
                }
                for i in items
            ]
        }

    return preview

# ──────────────────────────────────────────────
# API: 往期归档列表
# ──────────────────────────────────────────────
@app.get("/api/archive")
async def api_archive(
    days: int = Query(30, description="往前查看多少天，默认30天"),
):
    """
    返回最近 N 天内有报告的日期列表
    每个条目包含：日期、新闻条数、是否有PDF、文件名
    """
    today = get_today_cst()
    archive = []

    for i in range(days):
        d = today - timedelta(days=i)
        date_str = d.strftime(REPORT["date_format"])
        info = find_existing_report(date_str)
        if info:
            info["date_display"] = d.strftime(REPORT["display_date_format"])
            info["weekday"] = ["一","二","三","四","五","六","日"][d.weekday()]
            archive.append(info)

    return {
        "count": len(archive),
        "archive": archive,
    }

# ──────────────────────────────────────────────
# API: 一键生成+下载
# ──────────────────────────────────────────────
@app.post("/api/generate-and-download")
async def api_generate_download(
    date: Optional[str] = Query(None),
    force_refresh: bool = Query(False),
):
    result = await api_generate(
        background_tasks=BackgroundTasks(),
        date=date,
        force_refresh=force_refresh,
    )
    if not result["pdf_url"]:
        raise HTTPException(500, "PDF生成失败，请检查服务器日志")
    return {
        "status": "success",
        "download_url": result["pdf_url"],
        "html_url": result["html_url"],
        "filename": result["filename"],
        "total_news": result["total_news"],
        "message": f"日报已生成，共 {result['total_news']} 条新闻",
    }

# ──────────────────────────────────────────────
# API: 下载文件
# ──────────────────────────────────────────────
@app.get("/api/download")
async def api_download(file: str = Query(..., description="文件名")):
    if "/" in file or "\\" in file or ".." in file:
        raise HTTPException(400, "非法文件名")

    file_path = OUTPUT_DIR / file
    if not file_path.exists():
        raise HTTPException(404, f"文件不存在: {file}")

    media_type = "application/pdf" if file.endswith(".pdf") else "text/html"
    return FileResponse(path=str(file_path), media_type=media_type, filename=file)

# ──────────────────────────────────────────────
# API: 健康检查
# ──────────────────────────────────────────────
@app.get("/api/health")
async def health():
    window_start, window_end = get_time_window()
    return {
        "status": "ok",
        "time": datetime.now(CST).isoformat(),
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "next_run": f"每天 {SCHEDULER['hour']:02d}:{SCHEDULER['minute']:02d} ({SCHEDULER['timezone']})",
    }

# ──────────────────────────────────────────────
# 内部工具
# ──────────────────────────────────────────────
def _get_window_info(target: datetime) -> Dict:
    from app.news_fetcher import get_time_window
    start, end = get_time_window(target)
    return {
        "start": start.strftime("%Y-%m-%d %H:%M"),
        "end": end.strftime("%Y-%m-%d %H:%M"),
        "hours": REPORT.get("lookback_hours", 24),
    }

# ──────────────────────────────────────────────
# 备用主页 HTML
# ──────────────────────────────────────────────
def _get_fallback_html() -> str:
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>商飞供应链动态日报</title>
<style>
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family:"Noto Sans CJK SC","Microsoft YaHei",sans-serif; background:#f0f2f5; color:#1a1a1a; }
  .container { max-width:960px; margin:0 auto; padding:20px; }
  .header { background:linear-gradient(135deg,#1a237e,#283593,#3949ab); color:#fff; padding:30px; border-radius:12px; text-align:center; margin-bottom:24px; }
  .header h1 { font-size:24pt; letter-spacing:3px; }
  .card { background:#fff; border-radius:10px; padding:20px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }
  .btn { display:inline-block; padding:10px 24px; border:none; border-radius:6px; font-size:11pt; cursor:pointer; }
  .btn-primary { background:#1a237e; color:#fff; }
  .btn-primary:hover { background:#0d1547; }
  .btn-secondary { background:#eee; color:#333; margin-left:8px; }
  input[type=date] { padding:8px 12px; font-size:11pt; border:1px solid #ddd; border-radius:6px; }
  .loading { display:none; text-align:center; padding:20px; color:#666; }
  .loading.show { display:block; }
  .result { display:none; margin-top:16px; padding:16px; background:#f8f9fa; border-radius:8px; }
  .result.show { display:block; }
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>🛩️ 商飞供应链动态日报</h1>
    <p>COMAC Supply Chain Daily Brief · v2.1</p>
  </div>
  <div class="card">
    <h2>📰 生成日报</h2>
    <p style="color:#666;margin:8px 0;">选择日期 → 点生成 → 等待30秒 → 下载PDF</p>
    <input type="date" id="dateInput">
    <button class="btn btn-primary" onclick="generateReport()">📄 生成PDF日报</button>
    <div class="loading" id="loading">⏳ 正在搜索新闻并生成日报...</div>
    <div class="result" id="result"></div>
  </div>
</div>
<script>
async function generateReport() {
  const dateInput = document.getElementById('dateInput');
  const loading = document.getElementById('loading');
  const result = document.getElementById('result');
  let dateParam = '';
  if (dateInput.value) {
    const d = new Date(dateInput.value);
    dateParam = `?date=${d.getFullYear()}${String(d.getMonth()+1).padStart(2,'0')}${String(d.getDate()).padStart(2,'0')}`;
  }
  loading.classList.add('show');
  result.classList.remove('show');
  try {
    const resp = await fetch('/api/generate-and-download' + dateParam, {method:'POST'});
    const data = await resp.json();
    loading.classList.remove('show');
    if (data.status === 'success') {
      result.innerHTML = `<h3 style="color:#16a34a;">✅ 生成成功</h3><p>文件: ${data.filename}</p><p>新闻: ${data.total_news}条</p><a class="btn btn-primary" href="${data.download_url}" target="_blank">⬇️ 下载PDF</a>`;
    } else {
      result.innerHTML = `<p style="color:#c62828;">❌ 失败: ${data.detail||''}</p>`;
    }
    result.classList.add('show');
  } catch(e) {
    loading.classList.remove('show');
    result.innerHTML = `<p style="color:#c62828;">❌ ${e.message}</p>`;
    result.classList.add('show');
  }
}
document.getElementById('dateInput').value = new Date().toISOString().slice(0,10);
</script>
</body>
</html>"""

# ──────────────────────────────────────────────
# 本地开发启动
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
    )
