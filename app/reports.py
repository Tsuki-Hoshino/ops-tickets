"""报告：列表、生成、查看、下载、删除。"""

import json
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

from . import db as database
from .config import DATA_DIR, PERIOD_PRESETS
from .llm import is_configured
from .report_service import generate_report, resolve_period
from .stats import query_records, summarize

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _get_or_404(report_id):
    report = database.get_db().execute(
        "SELECT * FROM reports WHERE id = ?", (report_id,)
    ).fetchone()
    if report is None:
        abort(404)
    return report


def _load_json(text):
    try:
        return json.loads(text) if text else {}
    except (TypeError, ValueError):
        return {}


@bp.get("/")
def index():
    reports = database.get_db().execute(
        "SELECT * FROM reports ORDER BY id DESC"
    ).fetchall()
    return render_template("reports/list.html", reports=reports)


@bp.route("/generate", methods=["GET", "POST"])
def generate():
    settings = database.get_settings()
    llm_ready = is_configured(settings)
    source = request.form if request.method == "POST" else request.args

    period = source.get("period") or "this_month"
    title = (source.get("title") or "").strip()
    use_llm = source.get("use_llm") in ("1", "on", "true")
    period_type, start, end, label = resolve_period(
        period, source.get("start") or "", source.get("end") or ""
    )

    if request.method == "POST" and request.form.get("action") != "preview":
        report_id, degrade = generate_report(
            period_type, label, start, end, title, use_llm, settings
        )
        if degrade:
            flash(f"大模型调用失败，已改用本地合成：{degrade}", "error")
        flash("报告已生成，可在列表中查看或下载", "success")
        return redirect(url_for("reports.view", report_id=report_id))

    preview = summarize(query_records(start, end))
    preview["period_label"] = label
    form = {
        "period": period,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "use_llm": use_llm or llm_ready,
        "title": title,
    }
    return render_template(
        "reports/generate.html",
        presets=PERIOD_PRESETS,
        form=form,
        llm_ready=llm_ready,
        preview=preview,
    )


@bp.get("/<int:report_id>")
def view(report_id):
    report = _get_or_404(report_id)
    return render_template(
        "reports/view.html",
        report=report,
        content=_load_json(report["content_json"]),
        stats=_load_json(report["stats_json"]),
    )


@bp.get("/<int:report_id>/download")
def download(report_id):
    report = _get_or_404(report_id)
    if not report["docx_path"]:
        abort(404)
    path = DATA_DIR / report["docx_path"]
    if not path.is_file():
        flash("报告文件已不存在，请重新生成", "error")
        return redirect(url_for("reports.view", report_id=report_id))
    return send_file(path, as_attachment=True, download_name=Path(path).name)


@bp.post("/<int:report_id>/delete")
def delete(report_id):
    report = _get_or_404(report_id)
    if report["docx_path"]:
        path = DATA_DIR / report["docx_path"]
        if path.is_file():
            path.unlink()
    conn = database.get_db()
    conn.execute("DELETE FROM reports WHERE id = ?", (report_id,))
    conn.commit()
    flash("报告已删除", "success")
    return redirect(url_for("reports.index"))
