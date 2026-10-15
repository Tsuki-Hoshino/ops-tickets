"""设置页：站点信息、大模型配置与用户管理。"""

from flask import (
    Blueprint,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.security import generate_password_hash

from . import db as database
from .config import DEFAULT_SETTINGS
from .llm import test_connection
from .utils import admin_required

bp = Blueprint("settings", __name__, url_prefix="/settings")

ROLES = ("admin", "editor")
MASK_CHARS = set("*●•·")


def _masked(value):
    """密码框里可能提交的是掩码占位，视为「不修改」。"""
    text = (value or "").strip()
    return bool(text) and set(text) <= MASK_CHARS


def _clamped(text, default, low, high, integer=False):
    try:
        value = float(str(text).strip())
    except (TypeError, ValueError):
        value = float(default)
    value = min(max(value, low), high)
    return str(int(value)) if integer else f"{value:g}"


def _active_admin_count(exclude_id=None):
    sql = "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = 1"
    params = ()
    if exclude_id is not None:
        sql += " AND id <> ?"
        params = (exclude_id,)
    return database.get_db().execute(sql, params).fetchone()[0]


def _username_taken(username, exclude_id=None):
    sql = "SELECT COUNT(*) FROM users WHERE username = ?"
    params = [username]
    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)
    return database.get_db().execute(sql, params).fetchone()[0] > 0


# ---------- 站点与大模型 ----------


@bp.get("/")
@admin_required
def index():
    return render_template("settings/index.html", s=database.get_settings())


@bp.post("/site")
@admin_required
def update_site():
    site_name = (request.form.get("site_name") or "").strip()
    database.set_settings(
        {
            "site_name": site_name or DEFAULT_SETTINGS["site_name"],
            "report_org": (request.form.get("report_org") or "").strip(),
            "report_project": (request.form.get("report_project") or "").strip(),
            "report_author": (request.form.get("report_author") or "").strip(),
        }
    )
    flash("站点设置已保存", "success")
    return redirect(url_for("settings.index"))


@bp.post("/llm")
@admin_required
def update_llm():
    values = {
        "llm_enabled": "1" if request.form.get("llm_enabled") else "0",
        "llm_api_base": (request.form.get("llm_api_base") or "").strip(),
        "llm_model": (request.form.get("llm_model") or "").strip(),
        "llm_temperature": _clamped(
            request.form.get("llm_temperature"), DEFAULT_SETTINGS["llm_temperature"], 0, 2
        ),
        "llm_timeout": _clamped(
            request.form.get("llm_timeout"), DEFAULT_SETTINGS["llm_timeout"], 5, 600, integer=True
        ),
        "llm_max_tokens": _clamped(
            request.form.get("llm_max_tokens"),
            DEFAULT_SETTINGS["llm_max_tokens"],
            64,
            32768,
            integer=True,
        ),
    }
    # API Key 留空或仍是掩码时不覆盖已保存的值
    api_key = request.form.get("llm_api_key") or ""
    if api_key.strip() and not _masked(api_key):
        values["llm_api_key"] = api_key.strip()
    database.set_settings(values)
    flash("大模型设置已保存", "success")
    return redirect(url_for("settings.index"))


@bp.post("/llm/test")
@admin_required
def test_llm():
    return jsonify(test_connection(database.get_settings()))


# ---------- 用户管理 ----------


@bp.get("/users")
@admin_required
def users():
    rows = database.get_db().execute("SELECT * FROM users ORDER BY id").fetchall()
    return render_template("settings/users.html", users=rows)


@bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def user_new():
    if request.method == "POST":
        form = {
            "username": (request.form.get("username") or "").strip(),
            "display_name": (request.form.get("display_name") or "").strip(),
            "role": request.form.get("role") or "editor",
            "is_active": 1 if request.form.get("is_active") else 0,
        }
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        error = None
        if not form["username"]:
            error = "请填写用户名"
        elif not password:
            error = "请填写密码"
        elif password != password2:
            error = "两次输入的密码不一致"
        elif form["role"] not in ROLES:
            error = "角色不合法"
        elif _username_taken(form["username"]):
            error = "用户名已存在"

        if error:
            flash(error, "error")
            return render_template("settings/user_form.html", user=form, mode="new")

        conn = database.get_db()
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name, role, is_active) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                form["username"],
                generate_password_hash(password),
                form["display_name"] or form["username"],
                form["role"],
                form["is_active"],
            ),
        )
        conn.commit()
        flash(f"用户 {form['username']} 已创建", "success")
        return redirect(url_for("settings.users"))

    return render_template("settings/user_form.html", user=None, mode="new")


@bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id):
    conn = database.get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)

    if request.method == "POST":
        form = {
            "id": user_id,
            "username": (request.form.get("username") or "").strip(),
            "display_name": (request.form.get("display_name") or "").strip(),
            "role": request.form.get("role") or user["role"],
            "is_active": 1 if request.form.get("is_active") else 0,
        }
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        error = None
        if not form["username"]:
            error = "请填写用户名"
        elif form["role"] not in ROLES:
            error = "角色不合法"
        elif _username_taken(form["username"], exclude_id=user_id):
            error = "用户名已存在"
        elif password and not _masked(password) and password != password2:
            error = "两次输入的密码不一致"
        if error is None:
            still_admin = form["role"] == "admin" and form["is_active"] == 1
            if not still_admin and _active_admin_count(exclude_id=user_id) == 0:
                error = "不能停用或降级最后一个管理员"

        if error:
            flash(error, "error")
            return render_template("settings/user_form.html", user=form, mode="edit")

        sql = (
            "UPDATE users SET username = ?, display_name = ?, role = ?, is_active = ? "
            "WHERE id = ?"
        )
        params = [
            form["username"],
            form["display_name"] or form["username"],
            form["role"],
            form["is_active"],
            user_id,
        ]
        if password and not _masked(password):
            sql = (
                "UPDATE users SET username = ?, display_name = ?, role = ?, is_active = ?, "
                "password_hash = ? WHERE id = ?"
            )
            params = params[:4] + [generate_password_hash(password), user_id]
        conn.execute(sql, params)
        conn.commit()
        flash(f"用户 {form['username']} 已更新", "success")
        return redirect(url_for("settings.users"))

    return render_template("settings/user_form.html", user=user, mode="edit")


@bp.post("/users/<int:user_id>/reset-password")
@admin_required
def user_reset_password(user_id):
    conn = database.get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    password = request.form.get("password") or ""
    password2 = request.form.get("password2") or ""
    if not password:
        flash("请填写新密码", "error")
    elif password != password2:
        flash("两次输入的密码不一致", "error")
    else:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (generate_password_hash(password), user_id),
        )
        conn.commit()
        flash(f"用户 {user['username']} 的密码已重置", "success")
    return redirect(url_for("settings.users"))


@bp.post("/users/<int:user_id>/delete")
@admin_required
def user_delete(user_id):
    conn = database.get_db()
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        abort(404)
    if user_id == g.user["id"]:
        flash("不能删除当前登录的账号", "error")
    elif user["role"] == "admin" and _active_admin_count() <= 1:
        flash("不能删除最后一个管理员", "error")
    else:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        flash(f"用户 {user['username']} 已删除", "success")
    return redirect(url_for("settings.users"))
