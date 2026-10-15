"""报告业务：周期解析、本地合成、大模型增强与 Word 落盘。"""

import json
import re
from datetime import date, timedelta

from . import db as database
from .config import REPORT_DIR, REPORT_SECTIONS, UPLOAD_DIR
from .docx_report import build_document
from .llm import generate_sections, is_configured
from .stats import query_records, summarize
from .utils import month_label, month_range, now_local, today_local, week_label, week_range

MAX_ATTACHMENT_PHOTOS = 12


# ---------- 周期 ----------


def _parse_date(text):
    try:
        return date.fromisoformat((text or "").strip())
    except ValueError:
        return None


def _range_label(start, end):
    if start == end:
        return f"{start.year} 年 {start.month} 月 {start.day} 日"
    if start.year == end.year:
        return f"{start.year} 年 {start.month} 月 {start.day} 日—{end.month} 月 {end.day} 日"
    return (
        f"{start.year} 年 {start.month} 月 {start.day} 日—"
        f"{end.year} 年 {end.month} 月 {end.day} 日"
    )


def resolve_period(period, start_text="", end_text=""):
    """把页面上的周期选择解析为 (period_type, start, end, 中文周期标签)。"""
    today = today_local()
    period = period or "this_month"

    if period == "this_week":
        start, end = week_range(today)
        return "week", start, end, week_label(start, end)
    if period == "last_week":
        start, end = week_range(today - timedelta(days=7))
        return "week", start, end, week_label(start, end)
    if period == "last_month":
        anchor = today.replace(day=1) - timedelta(days=1)
        start, end = month_range(anchor)
        return "month", start, end, month_label(anchor)
    if period == "custom":
        start = _parse_date(start_text) or today
        end = _parse_date(end_text) or start
        if end < start:
            start, end = end, start
        period_type = "week" if (end - start).days <= 13 else "month"
        return period_type, start, end, _range_label(start, end)

    start, end = month_range(today)
    return "month", start, end, month_label(today)


# ---------- 正文合成 ----------


def _pct(value):
    return f"{value * 100:.1f}%"


def _dist_text(items, limit=6):
    return "、".join(f"{item['name']} {item['count']} 条（{_pct(item['ratio'])}）" for item in items[:limit])


def _clean_paragraphs(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def build_local_content(stats, label, title, settings, start, end):
    """用统计数据拼装报告正文，大模型不可用时报告照常生成。"""
    total = stats["total"]
    closed = stats["closed"]
    open_count = stats["open"]
    dept_dist = stats["dept_dist"]
    cat_dist = stats["cat_dist"]
    anomalies = stats["anomalies"]
    major = ("机房基础设施", "网络与专线")
    major_count = sum(item["count"] for item in cat_dist if item["name"] in major)

    # 一、报告概述
    overview = [
        f"本报告统计周期为{label}，共登记运维工单 {total} 条，其中已闭环 {closed} 条、"
        f"未闭环 {open_count} 条，闭环率 {_pct(stats['close_rate'])}。"
    ]
    if dept_dist:
        overview.append(f"按部门分布：{_dist_text(dept_dist)}。")
    if stats["avg_total"]:
        overview.append(
            f"本期工单平均总时长 {stats['avg_total']}，平均响应时长 "
            f"{stats['avg_response'] or '暂无'}，平均处理时长 {stats['avg_handle'] or '暂无'}。"
        )
    else:
        overview.append("本期没有同时具备报修时间与完成时间的工单，暂不统计时长均值。")

    # 二、日常巡检工作执行情况
    if total:
        patrol = [
            f"本期涉及机房基础设施与网络专线的工单共 {major_count} 条，"
            f"占全部工单的 {_pct(major_count / total)}，是日常巡检与值守的主要工作面。"
        ]
    else:
        patrol = ["本期没有登记工单，日常巡检与值守未发现需要登记处理的故障。"]
    if cat_dist:
        patrol.append(f"按类别分布：{_dist_text(cat_dist)}。")
    patrol.append(
        f"其余 {closed} 条已闭环工单均按报修、到场、完成三个时间点留痕，并附处理现场照片。"
        if closed
        else "本期暂无闭环工单，相关处理记录待补充。"
    )

    # 三、售后服务工单处置情况
    handling = [
        f"本期共受理工单 {total} 条，已闭环 {closed} 条，未闭环 {open_count} 条，"
        f"闭环率 {_pct(stats['close_rate'])}。"
    ]
    if stats["avg_response"] or stats["avg_total"]:
        handling.append(
            f"平均响应时长 {stats['avg_response'] or '暂无'}，平均处理时长 "
            f"{stats['avg_handle'] or '暂无'}，平均总时长 {stats['avg_total'] or '暂无'}。"
        )
    if dept_dist:
        handling.append(f"受理量最大的部门为{dept_dist[0]['name']}，共 {dept_dist[0]['count']} 条。")

    # 四、问题分析
    analysis = []
    if cat_dist:
        top = cat_dist[0]
        analysis.append(
            f"从类别分布看，{top['name']}类工单最多，共 {top['count']} 条，占 {_pct(top['ratio'])}，"
            "是本期需要重点跟踪的问题来源。"
        )
    if open_count:
        analysis.append(f"截至统计期末仍有 {open_count} 条工单未闭环，需要继续跟进处理结果。")
    if anomalies:
        analysis.append(
            f"本期有 {len(anomalies)} 条工单的完成时间早于报修时间，属于登记异常，"
            "未计入时长统计，建议核对原始记录后修正。"
        )
    if not analysis:
        analysis.append("本期工单数据分布平稳，未发现集中性问题。")

    # 五、下期工作计划
    plan = []
    if open_count:
        plan.append(f"跟踪 {open_count} 条未闭环工单，补齐到场时间与处理结果，直至全部闭环。")
    if cat_dist:
        plan.append(f"针对{cat_dist[0]['name']}类问题安排专项检查，减少同类故障重复发生。")
    plan.append("继续按报修、到场、完成三个时间点登记工单，并上传处理前后照片，保证台账可追溯。")
    plan.append("按月导出运维台账并归档，保持数据连续、可核对。")

    closing = [
        f"本期运维服务工作已按计划推进，工单登记、现场处理与台账归档同步进行。"
        f"下一周期将继续按上述计划落实，保证故障响应及时、处理过程留痕。"
    ]

    bodies = [overview, patrol, handling, analysis, plan, closing]
    return {
        "title": title,
        "period_label": label,
        "sections": [
            {"heading": heading, "level": 1, "paragraphs": paragraphs}
            for heading, paragraphs in zip(REPORT_SECTIONS, bodies)
        ],
    }


def _merge_sections(base_sections, llm_sections):
    """把大模型返回的段落按章节并入骨架，缺失的章节保留本地合成内容。"""
    by_heading = {}
    for item in llm_sections:
        if isinstance(item, dict) and item.get("heading"):
            by_heading[str(item["heading"]).strip()] = item
    merged = []
    for index, base in enumerate(base_sections):
        item = by_heading.get(base["heading"])
        if item is None and index < len(llm_sections) and isinstance(llm_sections[index], dict):
            item = llm_sections[index]
        paragraphs = _clean_paragraphs(item.get("paragraphs")) if item else []
        merged.append({**base, "paragraphs": paragraphs or base["paragraphs"]})
    return merged


def collect_attachment_images(records, limit=MAX_ATTACHMENT_PHOTOS):
    """收集报告附件用的现场照片（处理后优先）。"""
    ids = [row["id"] for row in records]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = database.get_db().execute(
        f"SELECT filename FROM record_photos WHERE record_id IN ({placeholders}) "
        "ORDER BY (stage = 'after') DESC, record_id, sort_order, id",
        ids,
    ).fetchall()
    paths = []
    for row in rows:
        path = UPLOAD_DIR / row["filename"]
        if path.is_file():
            paths.append(str(path))
        if len(paths) >= limit:
            break
    return paths


def _safe_filename(text, fallback="report"):
    cleaned = re.sub(r'[\\/:*?"<>|\s]+', "_", (text or "").strip())
    cleaned = cleaned.strip("_")[:60]
    return cleaned or fallback


# ---------- 生成 ----------


def generate_report(period_type, label, start, end, title, use_llm, settings):
    """生成报告并落盘，返回 (report_id, 降级原因或 None)。"""
    records = query_records(start, end, include_open=True)
    stats = summarize(records)

    title = (title or "").strip() or f"运维服务工作{'周报' if period_type == 'week' else '月报'}"
    content = build_local_content(stats, label, title, settings, start, end)
    content["cover"] = {
        "org": settings.get("report_org", ""),
        "project": settings.get("report_project", ""),
        "author": settings.get("report_author", ""),
        "date": end.strftime("%Y-%m-%d"),
    }
    images = collect_attachment_images(records)
    content["attachments"] = (
        [{"heading": "附件：现场处理照片", "images": images}] if images else []
    )
    content["source"] = "local"

    degrade = None
    llm_model = ""
    if use_llm and is_configured(settings):
        result, error = generate_sections(stats, label, settings, content)
        if result and result.get("sections"):
            content["sections"] = _merge_sections(content["sections"], result["sections"])
            content["source"] = "llm"
            llm_model = settings.get("llm_model") or ""
        else:
            degrade = error or "大模型返回内容无法解析"

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{_safe_filename(title)}_{start:%Y%m%d}_{end:%Y%m%d}_{now_local():%H%M%S}.docx"
    )
    out_path = REPORT_DIR / filename
    build_document(content, out_path)

    conn = database.get_db()
    cursor = conn.execute(
        "INSERT INTO reports (period_type, period_start, period_end, title, status, "
        "content_json, stats_json, docx_path, llm_model, error_message) "
        "VALUES (?, ?, ?, ?, 'generated', ?, ?, ?, ?, ?)",
        (
            period_type,
            start.isoformat(),
            end.isoformat(),
            title,
            json.dumps(content, ensure_ascii=False),
            json.dumps(stats, ensure_ascii=False),
            f"reports/{filename}",
            llm_model,
            degrade,
        ),
    )
    conn.commit()
    return cursor.lastrowid, degrade
