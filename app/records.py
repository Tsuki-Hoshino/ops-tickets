"""工单：新建、列表、详情、编辑、删除与照片管理。"""

import io
import math
import shutil
import uuid

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    redirect,
    render_template,
    request,
    url_for,
)
from PIL import Image

from . import db as database
from .config import (
    ALLOWED_EXTENSIONS,
    CATEGORIES,
    CATEGORY_KEYWORDS,
    DEFAULT_DEPARTMENTS,
    MAX_PHOTO_BYTES,
    UPLOAD_DIR,
)
from .utils import (
    duration_text,
    guess_category,
    parse_dt,
    safe_original_name,
    to_iso,
)

bp = Blueprint("records", __name__, url_prefix="/records")

PER_PAGE = 20

FORMAT_EXT = {
    "JPEG": ".jpg",
    "MPO": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "BMP": ".bmp",
    "WEBP": ".webp",
}
FORMAT_MIME = {
    "JPEG": "image/jpeg",
    "MPO": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "BMP": "image/bmp",
    "WEBP": "image/webp",
}

EMPTY_FORM = {
    "reported_at": "",
    "arrived_at": "",
    "finished_at": "",
    "department": "",
    "category": "",
    "symptom": "",
    "cause": "",
    "solution": "",
    "operator": "",
    "notes": "",
}


# ---------- 内部工具 ----------


def _stage_files(name):
    """取出该字段下所有已选择的文件。"""
    return [f for f in request.files.getlist(name) if f and f.filename]


def _save_photos(record_id, stage, files):
    """校验并保存某个阶段的照片，返回 (张数, 错误信息列表)。

    Pillow 打开并校验图片时会关掉传入的流，所以先把字节读出来再校验。
    """
    conn = database.get_db()
    target_dir = UPLOAD_DIR / str(record_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    row = conn.execute(
        "SELECT COALESCE(MAX(sort_order), -1) AS m FROM record_photos "
        "WHERE record_id = ? AND stage = ?",
        (record_id, stage),
    ).fetchone()
    order = (row["m"] or -1) + 1

    saved, errors = 0, []
    for fs in files:
        name = fs.filename or ""
        ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
        if ext not in ALLOWED_EXTENSIONS:
            errors.append(f"「{name}」不是支持的图片格式（仅支持 JPG / PNG / GIF / BMP / WEBP）")
            continue
        raw = fs.stream.read()
        if not raw:
            errors.append(f"「{name}」是空文件")
            continue
        if len(raw) > MAX_PHOTO_BYTES:
            errors.append(f"「{name}」超过 10 MB 上限")
            continue
        try:
            with Image.open(io.BytesIO(raw)) as img:
                fmt = (img.format or "").upper()
                img.load()
        except Exception:
            errors.append(f"「{name}」无法识别为图片")
            continue
        out_ext = FORMAT_EXT.get(fmt)
        if out_ext is None:
            errors.append(f"「{name}」格式不受支持")
            continue
        filename = f"{uuid.uuid4().hex}{out_ext}"
        dest = target_dir / filename
        dest.write_bytes(raw)
        conn.execute(
            "INSERT INTO record_photos (record_id, stage, filename, original_name, mime, size, sort_order) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                record_id,
                stage,
                f"{record_id}/{filename}",
                safe_original_name(name),
                FORMAT_MIME.get(fmt, fs.mimetype or ""),
                dest.stat().st_size,
                order,
            ),
        )
        order += 1
        saved += 1
    conn.commit()
    return saved, errors


def _photos_of(record_id):
    rows = database.get_db().execute(
        "SELECT * FROM record_photos WHERE record_id = ? ORDER BY stage, sort_order, id",
        (record_id,),
    ).fetchall()
    return (
        [r for r in rows if r["stage"] == "before"],
        [r for r in rows if r["stage"] == "after"],
    )


def _departments():
    """表单部门候选：库中已用部门 + 预置候选。"""
    rows = database.get_db().execute(
        "SELECT DISTINCT department FROM records WHERE department <> '' ORDER BY department"
    ).fetchall()
    names = [r["department"] for r in rows]
    for item in DEFAULT_DEPARTMENTS:
        if item not in names:
            names.append(item)
    return names


def _read_form():
    """读取并规范化工单表单，返回 (数据 dict, 错误信息或 None)。"""
    data = {
        "reported_at": to_iso(request.form.get("reported_at")),
        "arrived_at": to_iso(request.form.get("arrived_at")),
        "finished_at": to_iso(request.form.get("finished_at")),
        "department": (request.form.get("department") or "").strip(),
        "category": (request.form.get("category") or "").strip(),
        "symptom": (request.form.get("symptom") or "").strip(),
        "cause": (request.form.get("cause") or "").strip(),
        "solution": (request.form.get("solution") or "").strip(),
        "operator": (request.form.get("operator") or "").strip(),
        "notes": (request.form.get("notes") or "").strip(),
    }
    if data["reported_at"] is None:
        return data, "请填写报修时间（格式 YYYY-MM-DD HH:MM）"
    if not data["department"]:
        return data, "请填写部门"
    if not data["symptom"]:
        return data, "请填写需求/故障"
    if data["category"] not in CATEGORIES:
        data["category"] = guess_category(data["symptom"], data["cause"])
    return data, None


def _warn_time_order(data):
    """时间倒挂不阻断保存，仅提示（统计时按异常数据处理）。"""
    reported = parse_dt(data["reported_at"])
    for key, label in (("arrived_at", "到场时间"), ("finished_at", "完成时间")):
        value = parse_dt(data[key])
        if value and value < reported:
            flash(
                f"{label}早于报修时间，已按异常数据保存，不计入时长统计",
                "error",
            )


def _form_view_values(data, record_id=None):
    """把提交值转回表单可回填的文本。"""
    values = {
        "reported_at": (data.get("reported_at") or "").replace(" ", "T"),
        "arrived_at": (data.get("arrived_at") or "").replace(" ", "T"),
        "finished_at": (data.get("finished_at") or "").replace(" ", "T"),
        "department": data.get("department") or "",
        "category": data.get("category") or "",
        "symptom": data.get("symptom") or "",
        "cause": data.get("cause") or "",
        "solution": data.get("solution") or "",
        "operator": data.get("operator") or "",
        "notes": data.get("notes") or "",
    }
    if record_id is not None:
        values["id"] = record_id
    return values


def _render_form(record, record_id=None, mode="new"):
    photos_before, photos_after = _photos_of(record_id) if record_id else ([], [])
    return render_template(
        "records/form.html",
        record=record,
        photos_before=photos_before,
        photos_after=photos_after,
        departments=_departments(),
        form_action=(
            url_for("records.edit", record_id=record_id)
            if record_id
            else url_for("records.new")
        ),
        mode=mode,
        keyword_map=CATEGORY_KEYWORDS,
    )


def _get_or_404(record_id):
    record = database.get_db().execute(
        "SELECT * FROM records WHERE id = ?", (record_id,)
    ).fetchone()
    if record is None:
        abort(404)
    return record


def _current_operator():
    if g.get("user") is None:
        return ""
    return g.user["display_name"] or g.user["username"]


def _durations(record):
    reported = parse_dt(record["reported_at"])
    arrived = parse_dt(record["arrived_at"])
    finished = parse_dt(record["finished_at"])
    total = finished - reported if reported and finished else None
    response = arrived - reported if reported and arrived else None
    handle = finished - arrived if finished and arrived else total
    if total is not None and total.total_seconds() < 0:
        total = None
    if response is not None and response.total_seconds() < 0:
        response = None
    if handle is not None and handle.total_seconds() < 0:
        handle = None
    return {
        "total": duration_text(total),
        "response": duration_text(response),
        "handle": duration_text(handle),
    }


def _is_anomaly(record):
    reported = parse_dt(record["reported_at"])
    finished = parse_dt(record["finished_at"])
    return bool(reported and finished and finished < reported)


# ---------- 视图 ----------


@bp.route("/", endpoint="list")
def list_records():
    filters = {
        "department": (request.args.get("department") or "").strip(),
        "category": (request.args.get("category") or "").strip(),
        "status": (request.args.get("status") or "").strip(),
        "start": (request.args.get("start") or "").strip(),
        "end": (request.args.get("end") or "").strip(),
        "q": (request.args.get("q") or "").strip(),
    }
    where, params = [], []
    if filters["department"]:
        where.append("department = ?")
        params.append(filters["department"])
    if filters["category"]:
        where.append("category = ?")
        params.append(filters["category"])
    if filters["status"] in ("open", "closed"):
        where.append("status = ?")
        params.append(filters["status"])
    if filters["start"]:
        where.append("occurred_on >= ?")
        params.append(filters["start"])
    if filters["end"]:
        where.append("occurred_on <= ?")
        params.append(filters["end"])
    if filters["q"]:
        like = f"%{filters['q']}%"
        where.append(
            "(symptom LIKE ? OR cause LIKE ? OR solution LIKE ? OR operator LIKE ? OR notes LIKE ?)"
        )
        params.extend([like] * 5)

    clause = (" WHERE " + " AND ".join(where)) if where else ""
    conn = database.get_db()
    total = conn.execute(f"SELECT COUNT(*) FROM records{clause}", params).fetchone()[0]
    pages = max(1, math.ceil(total / PER_PAGE))
    page = request.args.get("page", type=int) or 1
    page = min(max(page, 1), pages)

    records = conn.execute(
        f"SELECT * FROM records{clause} ORDER BY reported_at DESC, id DESC LIMIT ? OFFSET ?",
        params + [PER_PAGE, (page - 1) * PER_PAGE],
    ).fetchall()

    return render_template(
        "records/list.html",
        records=records,
        page=page,
        pages=pages,
        total=total,
        filters=filters,
        departments=_departments(),
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    if request.method == "POST":
        data, error = _read_form()
        if error:
            flash(error, "error")
            return _render_form(_form_view_values(data))

        conn = database.get_db()
        conn.execute(
            "INSERT INTO records (occurred_on, reported_at, arrived_at, finished_at, department, "
            "category, symptom, cause, solution, status, operator, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                data["reported_at"][:10],
                data["reported_at"],
                data["arrived_at"],
                data["finished_at"],
                data["department"],
                data["category"],
                data["symptom"],
                data["cause"],
                data["solution"],
                "closed" if data["finished_at"] else "open",
                data["operator"] or _current_operator(),
                data["notes"],
            ),
        )
        record_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.commit()

        saved, errors = _save_photos(record_id, "before", _stage_files("photos_before[]"))
        saved_after, errors_after = _save_photos(
            record_id, "after", _stage_files("photos_after[]")
        )
        saved += saved_after
        for message in errors + errors_after:
            flash(message, "error")
        _warn_time_order(data)
        flash(
            f"工单已保存，共上传照片 {saved} 张" if saved else "工单已保存",
            "success",
        )
        return redirect(url_for("records.detail", record_id=record_id))

    form_values = dict(EMPTY_FORM)
    form_values["operator"] = _current_operator()
    return _render_form(form_values)


@bp.get("/<int:record_id>")
def detail(record_id):
    record = _get_or_404(record_id)
    photos_before, photos_after = _photos_of(record_id)
    return render_template(
        "records/detail.html",
        record=record,
        photos_before=photos_before,
        photos_after=photos_after,
        durations=_durations(record),
        anomaly=_is_anomaly(record),
    )


@bp.route("/<int:record_id>/edit", methods=["GET", "POST"])
def edit(record_id):
    record = _get_or_404(record_id)
    if request.method == "POST":
        data, error = _read_form()
        if error:
            flash(error, "error")
            return _render_form(_form_view_values(data, record_id), record_id, mode="edit")

        conn = database.get_db()
        conn.execute(
            "UPDATE records SET occurred_on = ?, reported_at = ?, arrived_at = ?, finished_at = ?, "
            "department = ?, category = ?, symptom = ?, cause = ?, solution = ?, status = ?, "
            "operator = ?, notes = ?, updated_at = datetime('now', 'localtime') WHERE id = ?",
            (
                data["reported_at"][:10],
                data["reported_at"],
                data["arrived_at"],
                data["finished_at"],
                data["department"],
                data["category"],
                data["symptom"],
                data["cause"],
                data["solution"],
                "closed" if data["finished_at"] else "open",
                data["operator"] or _current_operator(),
                data["notes"],
                record_id,
            ),
        )
        conn.commit()

        saved, errors = _save_photos(record_id, "before", _stage_files("photos_before[]"))
        saved_after, errors_after = _save_photos(
            record_id, "after", _stage_files("photos_after[]")
        )
        saved += saved_after
        for message in errors + errors_after:
            flash(message, "error")
        _warn_time_order(data)
        flash(f"工单已更新，新增照片 {saved} 张" if saved else "工单已更新", "success")
        return redirect(url_for("records.detail", record_id=record_id))

    return _render_form(record, record_id, mode="edit")


@bp.post("/<int:record_id>/delete")
def delete(record_id):
    record = _get_or_404(record_id)
    conn = database.get_db()
    conn.execute("DELETE FROM record_photos WHERE record_id = ?", (record_id,))
    conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    shutil.rmtree(UPLOAD_DIR / str(record_id), ignore_errors=True)
    flash(f"工单 #{record['id']} 已删除", "success")
    return redirect(url_for("records.list"))


@bp.post("/<int:record_id>/photos/<int:photo_id>/delete")
def delete_photo(record_id, photo_id):
    conn = database.get_db()
    photo = conn.execute(
        "SELECT * FROM record_photos WHERE id = ? AND record_id = ?",
        (photo_id, record_id),
    ).fetchone()
    if photo is None:
        abort(404)
    conn.execute("DELETE FROM record_photos WHERE id = ?", (photo_id,))
    conn.commit()
    path = UPLOAD_DIR / photo["filename"]
    if path.is_file():
        path.unlink()
    flash("照片已删除", "success")
    target = request.form.get("next") or url_for(
        "records.detail", record_id=record_id
    )
    return redirect(target)
