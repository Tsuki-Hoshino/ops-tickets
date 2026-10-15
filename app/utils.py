"""通用工具：时间、类别识别、图片校验、密钥持久化、权限装饰器。"""

import functools
import secrets
import unicodedata
from datetime import datetime, timedelta, timezone

from flask import abort, g, redirect, request, url_for
from werkzeug.utils import secure_filename

from .config import (
    CATEGORY_KEYWORDS,
    FALLBACK_CATEGORY,
    SECRET_KEY_FILE,
    TIMEZONE,
)

# 中国标准时间固定为 UTC+8（无夏令时）
TZ = timezone(timedelta(hours=8), TIMEZONE)

DT_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


# ---------- 时间 ----------


def now_local():
    return datetime.now(TZ).replace(tzinfo=None, microsecond=0)


def today_local():
    return now_local().date()


def parse_dt(value):
    """把表单/数据库里的时间文本解析为 datetime，失败返回 None。"""
    if value is None:
        return None
    text = str(value).strip().replace("T", " ")
    if not text:
        return None
    for fmt in DT_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def to_iso(value):
    """统一存成 YYYY-MM-DD HH:MM:SS 文本。"""
    dt = parse_dt(value)
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def fmt_dt(value, fmt="%Y-%m-%d %H:%M"):
    dt = parse_dt(value)
    return dt.strftime(fmt) if dt else ""


def to_input_value(value):
    """转为 <input type="datetime-local"> 的 value。"""
    dt = parse_dt(value)
    return dt.strftime("%Y-%m-%dT%H:%M") if dt else ""


def duration_text(delta):
    """把 timedelta 变成「1 小时 20 分钟」这类中文描述。"""
    if delta is None:
        return ""
    seconds = int(delta.total_seconds())
    if seconds < 0:
        return "时间倒挂"
    days, rem = divmod(seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if minutes and not days:
        parts.append(f"{minutes} 分钟")
    if not parts:
        parts.append("不足 1 分钟")
    return " ".join(parts)


# ---------- 周期 ----------


def week_range(anchor=None):
    """返回包含 anchor 的那一周（周一开始）的 (start_date, end_date)。"""
    day = anchor or today_local()
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def month_range(anchor=None):
    """返回 anchor 所在月份的 (start_date, end_date)。"""
    day = anchor or today_local()
    start = day.replace(day=1)
    next_month = (start + timedelta(days=32)).replace(day=1)
    return start, next_month - timedelta(days=1)


def week_label(start, end):
    return f"{start.month} 月 {start.day} 日—{end.month} 月 {end.day} 日"


def month_label(day):
    return f"{day.year} 年 {day.month} 月"


# ---------- 类别识别 ----------


def guess_category(symptom, cause=""):
    """按关键词表顺序匹配，先命中者胜；全部未命中返回兜底类别。"""
    text = f"{symptom or ''} {cause or ''}".lower()
    for keyword, category in CATEGORY_KEYWORDS:
        if keyword.lower() in text:
            return category
    return FALLBACK_CATEGORY


# ---------- 图片 ----------


def safe_original_name(name):
    """保留一个可读的原始文件名（去掉路径与危险字符）。"""
    base = secure_filename(name or "") or "photo"
    return unicodedata.normalize("NFC", base)[:120]


# ---------- 密钥 ----------


def get_or_create_secret_key():
    """首次运行生成随机密钥并持久化到 data/，保证重启不掉登录态。"""
    if SECRET_KEY_FILE.exists():
        key = SECRET_KEY_FILE.read_text(encoding="utf-8").strip()
        if key:
            return key
    key = secrets.token_hex(32)
    SECRET_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    SECRET_KEY_FILE.write_text(key, encoding="utf-8")
    return key


# ---------- 权限 ----------


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        if g.user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped
