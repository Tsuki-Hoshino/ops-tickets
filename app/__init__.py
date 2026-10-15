"""Flask 应用工厂：配置、蓝图注册、全局守卫与模板上下文。"""

from datetime import timedelta

from flask import (
    Blueprint,
    Flask,
    g,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)

from . import db as database
from .config import (
    BASE_DIR,
    CATEGORIES,
    DEFAULT_SETTINGS,
    MAX_PHOTO_BYTES,
    PHOTO_JPEG_QUALITY,
    PHOTO_MAX_EDGE,
    REMEMBER_DAYS,
    UPLOAD_DIR,
)
from .utils import duration_text, fmt_dt, get_or_create_secret_key, to_input_value

# 允许未登录访问的 endpoint：登录 / 安装页，以及供只读浏览的总览面板
PUBLIC_ENDPOINTS = {"auth.login", "auth.install", "static", "dashboard.index"}

main = Blueprint("main", __name__)


@main.route("/uploads/<path:filename>")
def uploaded_file(filename):
    """工单照片（需登录，由全局守卫拦截）。"""
    return send_from_directory(UPLOAD_DIR, filename)


def _load_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    row = database.get_db().execute(
        "SELECT id, username, display_name, role, is_active FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    if row is None or not row["is_active"]:
        session.clear()
        return None
    return row


def create_app():
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.update(
        SECRET_KEY=get_or_create_secret_key(),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=REMEMBER_DAYS),
        MAX_CONTENT_LENGTH=64 * 1024 * 1024,  # 单张限 10MB，一次可传多张
        JSON_AS_ASCII=False,
        INSTALLED=database.is_installed(),
    )

    # ---------- 蓝图 ----------
    from . import auth, dashboard, exports, records, reports
    from . import settings as settings_views

    app.register_blueprint(main)
    app.register_blueprint(auth.bp)
    app.register_blueprint(dashboard.bp)
    app.register_blueprint(records.bp)
    app.register_blueprint(exports.bp)
    app.register_blueprint(reports.bp)
    app.register_blueprint(settings_views.bp)

    # ---------- 请求钩子 ----------
    @app.before_request
    def guard():
        endpoint = request.endpoint or ""
        if endpoint.startswith("static"):
            return None
        if not app.config["INSTALLED"]:
            if endpoint == "auth.install":
                return None
            return redirect(url_for("auth.install"))
        g.user = _load_current_user()
        if endpoint in PUBLIC_ENDPOINTS:
            return None
        if g.user is None:
            if request.method == "GET":
                return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
            return redirect(url_for("auth.login"))
        return None

    @app.teardown_appcontext
    def teardown(exc=None):
        database.close_db(exc)

    # ---------- 模板上下文 ----------
    @app.context_processor
    def inject_globals():
        if app.config.get("INSTALLED"):
            site_name = database.get_setting("site_name") or DEFAULT_SETTINGS["site_name"]
        else:
            site_name = DEFAULT_SETTINGS["site_name"]
        return {
            "site_name": site_name,
            "current_user": g.get("user"),
            "categories": CATEGORIES,
            "photo_config": {
                "max_edge": PHOTO_MAX_EDGE,
                "quality": PHOTO_JPEG_QUALITY,
                "max_bytes": MAX_PHOTO_BYTES,
            },
            "fmt_dt": fmt_dt,
            "to_input_value": to_input_value,
            "duration_text": duration_text,
        }

    # ---------- 错误页 ----------
    @app.errorhandler(403)
    def forbidden(_e):
        return render_template("error.html", code=403, message="没有权限执行该操作"), 403

    @app.errorhandler(404)
    def not_found(_e):
        return render_template("error.html", code=404, message="页面或数据不存在"), 404

    @app.errorhandler(413)
    def too_large(_e):
        return (
            render_template("error.html", code=413, message="上传内容过大，请压缩后重试"),
            413,
        )

    @app.errorhandler(500)
    def server_error(_e):
        return render_template("error.html", code=500, message="服务器内部错误"), 500

    return app
