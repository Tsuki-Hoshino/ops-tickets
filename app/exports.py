"""Excel 台账导出：月份预览与下载。"""

import time
from datetime import date, timedelta

from flask import Blueprint, redirect, render_template, request, send_file, url_for

from .config import EXPORT_DIR
from .excel_export import export_month, month_photos
from .stats import query_records
from .utils import today_local

bp = Blueprint("exports", __name__, url_prefix="/export")

CLEANUP_SECONDS = 3600


def _month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year + (1 if month == 12 else 0), (month % 12) + 1, 1) - timedelta(days=1)
    return start, end


def _read_month_params(source):
    today = today_local()
    year = source.get("year", type=int) or today.year
    month = source.get("month", type=int) or today.month
    return min(max(year, 2000), 2100), min(max(month, 1), 12)


def _read_options(source):
    group_mode = source.get("group_mode") or "grouped"
    if group_mode not in ("grouped", "full"):
        group_mode = "grouped"
    return {
        "group_mode": group_mode,
        "include_open": source.get("include_open") in ("1", "on", "true"),
        "embed_photos": source.get("embed_photos") in ("1", "on", "true"),
    }


def _cleanup_old_files():
    """清掉超过一小时的临时导出文件。"""
    if not EXPORT_DIR.exists():
        return
    deadline = time.time() - CLEANUP_SECONDS
    for path in EXPORT_DIR.glob("*.xlsx"):
        try:
            if path.stat().st_mtime < deadline:
                path.unlink()
        except OSError:
            continue


@bp.get("/")
def index():
    year, month = _read_month_params(request.args)
    options = _read_options(request.args)
    start, end = _month_bounds(year, month)

    records = query_records(start, end, include_open=options["include_open"])
    photos = month_photos([r["id"] for r in records])
    photo_count = sum(
        len(item.get("before", [])) + len(item.get("after", [])) for item in photos.values()
    )

    return render_template(
        "export.html",
        year=year,
        month=month,
        record_count=len(records),
        photo_count=photo_count,
        has_data=bool(records),
        preview_rows=records[:10],
        form=options,
    )


@bp.post("/download")
def download():
    year, month = _read_month_params(request.form)
    options = _read_options(request.form)
    start, end = _month_bounds(year, month)

    records = query_records(start, end, include_open=options["include_open"])
    if not records:
        return redirect(url_for("exports.index", year=year, month=month))

    photos = month_photos([r["id"] for r in records])
    _cleanup_old_files()
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = EXPORT_DIR / f"ledger_{year}{month:02d}_{time.strftime('%Y%m%d_%H%M%S')}.xlsx"

    export_month(
        records,
        photos,
        year,
        month,
        out_path,
        group_mode=options["group_mode"],
        include_open=options["include_open"],
        embed_photos=options["embed_photos"],
    )

    return send_file(
        out_path,
        as_attachment=True,
        download_name=f"运维台账_{year}年{month}月.xlsx",
    )
