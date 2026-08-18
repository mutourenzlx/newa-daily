"""
内容处理器
- 智能摘要截断
- 关键要点提取
- 金额信号识别
- 公司名称提取
"""

import re
from typing import List, Dict, Optional

from app.config import REPORT


# ──────────────────────────────────────────────
# 摘要处理
# ──────────────────────────────────────────────
def smart_truncate(text: str, max_len: int = 200) -> str:
    """智能截断摘要，优先在句号/逗号处截断"""
    if not text:
        return ""
    text = text.strip()
    if len(text) <= max_len:
        return text

    # 在标点处截断
    cut_chars = ["。", "！", "？", "；", "，", ";", ",", ".", "!"]
    best_pos = -1
    for i in range(max_len - 20, max_len + 1):
        if i >= len(text):
            break
        if text[i] in cut_chars:
            best_pos = i + 1
            break

    if best_pos > 0:
        return text[:best_pos].strip()
    return text[:max_len].strip() + "…"


# ──────────────────────────────────────────────
# 关键要点提取
# ──────────────────────────────────────────────
def extract_key_points(text: str, max_points: int = 3) -> List[str]:
    """从新闻摘要中提取关键要点"""
    if not text:
        return []

    # 按句号/分号切分
    sentences = re.split(r"[。；！？!?;]+", text)
    sentences = [s.strip() for s in sentences if len(s.strip()) > 8]

    # 优先保留含关键信号的句子
    priority_kw = [
        "供应商", "采购", "订单", "合同", "协议", "交付",
        "亿元", "万元", "美元", "金额", "投资",
        "入选", "中标", "认证", "准入", "签署",
        "商飞", "中国商飞", "COMAC", "C919", "C929",
        "产能", "量产", "适航", "发动机",
    ]

    scored = []
    for s in sentences:
        score = 0
        for kw in priority_kw:
            if kw in s:
                score += 1
        # 长度适中加分
        if 15 <= len(s) <= 80:
            score += 0.5
        scored.append((score, s))

    scored.sort(key=lambda x: x[0], reverse=True)
    points = [s for _, s in scored[:max_points]]
    return points


# ──────────────────────────────────────────────
# 金额识别
# ──────────────────────────────────────────────
def extract_amount(text: str) -> Optional[str]:
    """提取金额信息"""
    if not text:
        return None

    patterns = [
        r"\d+(?:\.\d+)?\s*亿元人民币?",
        r"\d+(?:\.\d+)?\s*亿元",
        r"\d+(?:\.\d+)?\s*万美元",
        r"\d+(?:\.\d+)?\s*万人民币",
        r"\d+(?:\.\d+)?\s*亿美元",
        r"\d+(?:\.\d+)?\s*万元",
        r"\d+(?:\.\d+)?\s*亿日元",
        r"数十亿",
        r"上百亿",
        r"数亿",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(0)
    return None


# ──────────────────────────────────────────────
# 公司名称提取
# ──────────────────────────────────────────────
def extract_companies(text: str) -> List[str]:
    """提取公司/机构名称"""
    if not text:
        return []

    companies = set()

    # 模式1: XX公司/集团/股份/有限
    pat1 = r"[\u4e00-\u9fff]{2,8}(?:公司|集团|股份|有限|控股|科技|工业|航空|电子|材料|制造)"
    for m in re.finditer(pat1, text):
        name = m.group(0)
        # 过滤太短或太通用的
        if len(name) >= 4 and name not in ("中国商飞", "商飞", "中国"):
            companies.add(name)

    # 模式2: 已知企业
    known = [
        "中国商飞", "商飞", "COMAC", "中航工业", "中航西飞", "中航沈飞",
        "洪都航空", "中航光电", "宝钛股份", "西部超导", "抚顺特钢",
        "中国铝业", "宝钢股份", "中信特钢", "万泽股份", "铂力特",
        "航发动力", "航发控制", "长江动力", "东方航空", "南方航空",
        "中国国航", "海航控股", "春秋航空", "吉祥航空",
    ]
    for k in known:
        if k in text:
            companies.add(k)

    # 移除子串包含关系
    result = list(companies)
    final = []
    for c in sorted(result, key=len, reverse=True):
        if not any(c in other and c != other for other in result):
            final.append(c)

    return final[:5]


# ──────────────────────────────────────────────
# 综合处理单条新闻
# ──────────────────────────────────────────────
def enrich_item(item: Dict) -> Dict:
    """对单条新闻做内容增强"""
    snippet = item.get("snippet", "")
    title = item.get("title", "")

    # 合并标题+摘要用于提取
    full_text = title + "。" + snippet

    # 摘要截断
    item["summary"] = smart_truncate(snippet, REPORT["summary_max_length"])

    # 关键要点
    item["key_points"] = extract_key_points(full_text, REPORT["max_key_points"])

    # 金额
    item["amount"] = extract_amount(full_text)

    # 公司
    item["companies"] = extract_companies(full_text)

    # 确保有来源
    if not item.get("source"):
        url = item.get("url", "")
        from app.news_fetcher import extract_domain
        item["source"] = extract_domain(url)

    return item


# ──────────────────────────────────────────────
# 批量处理
# ──────────────────────────────────────────────
def enrich_all(categorized: Dict[str, List[Dict]]) -> Dict[str, List[Dict]]:
    """对所有分类的新闻做内容增强"""
    result = {}
    for cat, items in categorized.items():
        result[cat] = [enrich_item(item) for item in items]
    return result
