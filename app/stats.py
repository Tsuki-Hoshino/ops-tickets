"""统计口径：区间查询、汇总指标与按日计数。

时间口径：
- 总时长 = ``finished_at − reported_at``
- 响应时长 = ``arrived_at − reported_at``
- 处理时长 = ``finished_at − arrived_at``，到场时间缺失时退化为总时长
- 闭环率 = 有完成时间的工单数 ÷ 总工单数
- 完成时间早于报修时间（倒挂）的工单不计入时长均值，单独列入 ``anomalies``
- 时长均值只统计两个端点都有值的工单

时间列统一是 ``YYYY-MM-DD HH:MM:SS`` 文本，一律用 :func:`app.utils.parse_dt` 解析。
"""

from collections import Counter
from datetime import date, datetime, timedelta

from .db import get_db
from .utils import duration_text, parse_dt

__all__ = ["query_records", "summarize", "daily_counts"]

# 部门/类别为空时的占位名，保证占比之和仍等于 1
UNKNOWN_NAME = "未填写"


# ---------- 内部工具 ----------


def _date_text(value):
    """把 date / datetime / 文本统一成 ``YYYY-MM-DD``，无法识别时返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, date):
        return value.isoformat()
    parsed = parse_dt(value)
    return parsed.strftime("%Y-%m-%d") if parsed else None


def _value(row, key, default=""):
    """兼容 sqlite3.Row 与 dict 取值，缺列或 NULL 时返回默认值。"""
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _hours(delta):
    """timedelta → 小时（float）。"""
    return delta.total_seconds() / 3600.0


def _mean(values):
    """算术平均，空列表返回 0.0。"""
    return sum(values) / len(values) if values else 0.0


def _dist(counter, total):
    """把 Counter 转成按 count 降序（同数按名称升序）的分布列表。"""
    items = sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    return [
        {"name": name, "count": count, "ratio": round(count / total, 4) if total else 0.0}
        for name, count in items
    ]


# ---------- 查询 ----------


def query_records(start_date, end_date, include_open=True):
    """按报修日期区间查询工单。

    参数:
        start_date: 起始日期（含），date / datetime / ``YYYY-MM-DD`` 文本均可。
        end_date: 结束日期（含），同上；与起始日期颠倒时自动纠正。
        include_open: 为 False 时只返回 ``status='closed'`` 的工单。

    返回:
        ``list[sqlite3.Row]``，按 ``reported_at, id`` 升序；日期无法识别时返回空列表。
    """
    start = _date_text(start_date)
    end = _date_text(end_date)
    if start is None or end is None:
        return []
    if start > end:
        start, end = end, start

    sql = ["SELECT * FROM records WHERE occurred_on >= ? AND occurred_on <= ?"]
    params = [start, end]
    if not include_open:
        sql.append("AND status = 'closed'")
    sql.append("ORDER BY reported_at, id")

    return get_db().execute(" ".join(sql), params).fetchall()


# ---------- 汇总 ----------


def summarize(records):
    """汇总一批工单，返回总览面板与报告共用的统计字典。

    返回结构::

        {
          "total": int, "closed": int, "open": int, "close_rate": float,   # 0~1
          "dept_dist": [{"name": str, "count": int, "ratio": float}],
          "cat_dist":  [{"name": str, "count": int, "ratio": float}],
          "avg_total": str, "avg_response": str, "avg_handle": str,        # 无样本为 ""
          "avg_total_hours": float, "avg_response_hours": float,
          "avg_handle_hours": float,                                        # 无样本为 0
          "anomalies": [{"id", "symptom", "reported_at", "finished_at"}],
        }

    倒挂（完成时间早于报修时间）的工单仍然计入总数与分布，但不参与任何时长均值。
    """
    rows = list(records or [])
    total = len(rows)

    closed = 0
    dept_counter = Counter()
    cat_counter = Counter()
    anomalies = []
    total_samples = []
    response_samples = []
    handle_samples = []

    for row in rows:
        dept = str(_value(row, "department")).strip() or UNKNOWN_NAME
        cat = str(_value(row, "category")).strip() or UNKNOWN_NAME
        dept_counter[dept] += 1
        cat_counter[cat] += 1

        reported = parse_dt(_value(row, "reported_at"))
        arrived = parse_dt(_value(row, "arrived_at"))
        finished = parse_dt(_value(row, "finished_at"))

        if finished is not None:
            closed += 1

        # 倒挂：两端都有值且完成早于报修，不计入时长均值，单独列出
        if reported and finished and finished < reported:
            anomalies.append(
                {
                    "id": _value(row, "id", None),
                    "symptom": str(_value(row, "symptom")),
                    "reported_at": str(_value(row, "reported_at")),
                    "finished_at": str(_value(row, "finished_at")),
                }
            )
            continue

        if reported and finished:
            total_samples.append(_hours(finished - reported))
        if reported and arrived:
            response_samples.append(_hours(arrived - reported))
        if finished and arrived:
            handle_samples.append(_hours(finished - arrived))
        elif finished and reported:
            # 到场时间缺失：处理时长退化为总时长
            handle_samples.append(_hours(finished - reported))

    avg_total_hours = _mean(total_samples)
    avg_response_hours = _mean(response_samples)
    avg_handle_hours = _mean(handle_samples)

    return {
        "total": total,
        "closed": closed,
        "open": total - closed,
        "close_rate": round(closed / total, 4) if total else 0.0,
        "dept_dist": _dist(dept_counter, total),
        "cat_dist": _dist(cat_counter, total),
        "avg_total": duration_text(timedelta(hours=avg_total_hours)) if total_samples else "",
        "avg_response": duration_text(timedelta(hours=avg_response_hours)) if response_samples else "",
        "avg_handle": duration_text(timedelta(hours=avg_handle_hours)) if handle_samples else "",
        "avg_total_hours": round(avg_total_hours, 2),
        "avg_response_hours": round(avg_response_hours, 2),
        "avg_handle_hours": round(avg_handle_hours, 2),
        "anomalies": anomalies,
    }


def daily_counts(records):
    """按报修日期统计每日工单数。

    分组键取 ``occurred_on``；该列为空时回退到 ``reported_at`` 的日期部分。
    只返回有工单的日期，按日期升序，形如 ``[{"date": "2026-03-02", "count": 3}]``。
    """
    counter = Counter()
    for row in records or []:
        day = str(_value(row, "occurred_on")).strip()
        if not day:
            reported = parse_dt(_value(row, "reported_at"))
            day = reported.strftime("%Y-%m-%d") if reported else ""
        if day:
            counter[day] += 1
    return [{"date": day, "count": counter[day]} for day in sorted(counter)]
