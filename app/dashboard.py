"""总览面板：工作量、分布图、最近工单、未闭环工单。"""

from flask import Blueprint, render_template

from . import db as database
from .stats import query_records, summarize
from .utils import month_range, today_local, week_label, week_range

bp = Blueprint("dashboard", __name__)


@bp.route("/")
def index():
    today = today_local()
    month_start, month_end = month_range(today)
    week_start, week_end = week_range(today)

    month_stat = summarize(query_records(month_start, month_end))
    week_stat = summarize(query_records(week_start, week_end))
    today_stat = summarize(query_records(today, today))

    conn = database.get_db()
    recent_records = conn.execute(
        "SELECT * FROM records ORDER BY reported_at DESC, id DESC LIMIT 8"
    ).fetchall()
    open_records = conn.execute(
        "SELECT * FROM records WHERE status = 'open' ORDER BY reported_at ASC, id ASC LIMIT 10"
    ).fetchall()

    period_labels = {
        "month": f"{today.year} 年 {today.month} 月",
        "week": week_label(week_start, week_end),
        "today": f"{today.year} 年 {today.month} 月 {today.day} 日",
    }

    return render_template(
        "dashboard.html",
        month_stat=month_stat,
        week_stat=week_stat,
        today_stat=today_stat,
        dept_dist=month_stat["dept_dist"],
        cat_dist=month_stat["cat_dist"],
        recent_records=recent_records,
        open_records=open_records,
        period_labels=period_labels,
    )
