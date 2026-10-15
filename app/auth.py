"""身份认证：安装向导、登录、退出。"""

from flask import (
    Blueprint,
    current_app,
    flash,
    g,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from . import db as database
from .config import DEFAULT_SETTINGS
from .utils import now_local, to_iso

bp = Blueprint("auth", __name__)


def _safe_next(target):
    """只允许跳回本站内部路径。"""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return url_for("dashboard.index")


@bp.route("/install", methods=["GET", "POST"])
def install():
    if current_app.config["INSTALLED"]:
        return redirect(url_for("auth.login"))

    form = {
        "site_name": DEFAULT_SETTINGS["site_name"],
        "username": "",
        "display_name": "",
    }
    error = None

    if request.method == "POST":
        form["site_name"] = (request.form.get("site_name") or "").strip()
        form["username"] = (request.form.get("username") or "").strip()
        form["display_name"] = (request.form.get("display_name") or "").strip()
        password = request.form.get("password") or ""
        password2 = request.form.get("password2") or ""

        if not form["site_name"]:
            error = "请填写站点名称"
        elif not form["username"]:
            error = "请填写管理员账号"
        elif not password:
            error = "请填写密码"
        elif password != password2:
            error = "两次输入的密码不一致"

        if error is None:
            database.init_db()
            conn = database.get_db()
            conn.execute(
                "INSERT INTO users (username, password_hash, display_name, role) "
                "VALUES (?, ?, ?, 'admin')",
                (
                    form["username"],
                    generate_password_hash(password),
                    form["display_name"] or form["username"],
                ),
            )
            conn.commit()

            values = dict(DEFAULT_SETTINGS)
            values["site_name"] = form["site_name"]
            database.set_settings(values)

            current_app.config["INSTALLED"] = True
            flash("安装完成，请使用刚才设置的账号登录", "success")
            return redirect(url_for("auth.login"))

    return render_template("install.html", form=form, error=error)


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.get("user") is not None:
        return redirect(url_for("dashboard.index"))

    username = ""
    error = None
    next_url = request.args.get("next") or request.form.get("next") or ""

    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        row = database.get_db().execute(
            "SELECT * FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None or not row["is_active"] or not check_password_hash(
            row["password_hash"], password
        ):
            error = "用户名或密码错误"
        else:
            session.clear()
            session["user_id"] = row["id"]
            # 勾选「记住我」→ 30 天；不勾选则关闭浏览器即失效
            session.permanent = bool(request.form.get("remember"))
            conn = database.get_db()
            conn.execute(
                "UPDATE users SET last_login_at = ? WHERE id = ?",
                (to_iso(now_local()), row["id"]),
            )
            conn.commit()
            flash(f"欢迎回来，{row['display_name'] or row['username']}", "success")
            return redirect(_safe_next(next_url))

    return render_template("login.html", error=error, username=username, next=next_url)


@bp.post("/logout")
def logout():
    session.clear()
    flash("已退出登录", "success")
    return redirect(url_for("auth.login"))
