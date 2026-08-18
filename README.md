# 商飞供应链动态日报 · Web 版 v2.1

> 自动采集商飞新增供应商 / 大额订单新闻 → 生成 PDF → 一键分享微信群

## ✨ 功能特性

- 🤖 **全自动**：每天 08:00（北京时间）自动采集 → 生成 PDF
- 📅 **24h 窗口**：采集前一天 08:00 → 当天 08:00 的完整一天新闻
- 🔍 **真实搜索**：调用搜索引擎获取真实网页，不编造新闻
- 🔗 **原文链接**：每条新闻附带可点击的原文 URL
- 📂 **往期归档**：网页上可查看/下载最近 30 天的历史日报
- 📱 **微信分享**：一键下载 PDF，直接发微信群
- 🔄 **手动补生成**：选日期 → 点按钮 → 30 秒出报告
- 💰 **零成本**：部署在 Render 免费层 + GitHub Actions 免费额度

## 🏗️ 项目结构

```
comac_web/
├── app/
│   ├── __init__.py
│   ├── main.py              ← FastAPI 网页 + API
│   ├── config.py            ← 配置中心（关键词/阈值/时间窗口）
│   ├── news_fetcher.py      ← 搜索 + 过滤 + 打分 + 去重
│   ├── content_processor.py ← 摘要/要点/金额/公司提取
│   ├── pdf_generator.py     ← HTML → PDF（红头简报风格）
│   └── templates/
│       └── index.html       ← 网页界面（商飞蓝浅色商务风）
├── .github/
│   └── workflows/
│       └── daily_report.yml  ← GitHub Actions 定时任务
├── output/                  ← 生成的 PDF/HTML/缓存（自动创建）
├── requirements.txt          ← Python 依赖
├── render.yaml              ← Render 一键部署配置
├── Procfile                 ← 进程启动
├── run.py                   ← 本地开发启动
├── test_full_flow.py        ← 端到端测试（38项）
├── test_with_real_search.py ← 真实搜索测试
└── README.md
```

## ⏰ 时间逻辑

| 环节 | 时间 | 说明 |
|------|------|------|
| **触发** | 每天 **08:00**（北京时间） | GitHub Actions cron 触发 |
| **采集窗口** | 前一天 08:00 → 当天 08:00 | 覆盖完整 24 小时 |
| **PDF 命名** | `商飞供应链动态日报-YYYYMMDD.pdf` | 用采集当天日期 |
| **手动补生成** | 随时可选任意日期 | 网页上点按钮即可 |

## 🚀 三步部署（约 15 分钟）

### Step 1：推送到 GitHub

```bash
cd comac_web
git init
git add .
git commit -m "商飞供应链日报 v2.1"
git remote add origin https://github.com/YOUR_USERNAME/comac-daily.git
git push -u origin main
```

### Step 2：部署到 Render（免费）

1. 打开 https://render.com → 用 GitHub 账号登录
2. 点 **New → Web Service** → 选刚才的仓库
3. 配置：
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt && python -m playwright install chromium`
   - **Start Command**: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
4. 点 **Create Web Service**
5. 等 3-5 分钟，拿到网址如 `https://comac-daily.onrender.com`

### Step 3：启用 GitHub Actions

1. 打开 GitHub 仓库 → **Settings → Actions → General**
2. 确保 **Read and write permissions** 已开启
3. Actions 会自动从 `daily_report.yml` 读取定时任务
4. 测试：手动触发一次 → **Actions → Daily COMAC Report → Run workflow**

## 📋 每日使用流程

```
早上 08:00 → 系统自动生成日报（无需操作）
早上 08:05 → 打开网站 → 点「往期归档」→ 找到今天的日期
               → 点「⬇️ PDF」下载 → 发到微信群 ✅
```

## 🔧 自定义配置

编辑 `app/config.py`：

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `lookback_hours` | 采集窗口小时数 | `24` |
| `anchor_hour` | 每天几点执行 | `8` |
| `min_relevance_score` | 最低相关度（1-10） | `3` |
| `KEYWORD_GROUPS` | 搜索关键词组 | 4 类 23 条 |
| `SOURCE_WEIGHTS` | 来源域名权重 | 政府站+3 / 官媒+2 |
| `EXCLUDE_WORDS` | 排除词 | 招聘/天气/广告等 |

## 🧪 本地开发

```bash
# 安装依赖
pip install -r requirements.txt

# 启动开发服务器
python run.py
# → 访问 http://localhost:8000

# 运行测试
python test_full_flow.py
# → 38/38 全部通过
```

## 📡 API 接口

| 接口 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 网页界面 |
| `/api/generate` | POST | 生成日报（可指定日期） |
| `/api/generate-and-download` | POST | 生成 + 返回下载链接 |
| `/api/preview` | GET | JSON 预览数据 |
| `/api/archive` | GET | 往期归档列表 |
| `/api/download?file=xxx` | GET | 下载 PDF/HTML |
| `/api/health` | GET | 健康检查 |

## ⚠️ 重要说明

- **新闻真实性**：系统不编造新闻，所有内容来自搜索引擎的真实网页
- **原文核实**：每条新闻都附原文链接，点进去即可验证
- **URL 强制校验**：无有效链接的新闻直接丢弃，不会出现在日报中
- **日期严格过滤**：不在 24h 窗口内的新闻一律丢弃

## 📄 License

MIT
