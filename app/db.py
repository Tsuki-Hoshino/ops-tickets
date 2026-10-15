"""SQLite 访问层：连接管理、建库、settings 读写。"""

import sqlite3

from flask import g

from .config import DB_PATH, DEFAULT_SETTINGS, SCHEMA_FILE


def get_db():
    """取得当前请求的数据库连接（每请求一个，WAL + 合理超时）。"""
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        g.db = conn
    return g.db


def close_db(exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    """按 schema.sql 建表（幂等）。"""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.executescript(SCHEMA_FILE.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def is_installed():
    """是否已完成安装向导（存在至少一个用户）。"""
    if not DB_PATH.exists():
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone()
        if row is None:
            return False
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] > 0
    finally:
        conn.close()


# ---------- settings ----------


def get_settings():
    """读取全部配置，缺失键用默认值补齐。"""
    values = dict(DEFAULT_SETTINGS)
    if DB_PATH.exists():
        conn = get_db()
        for row in conn.execute("SELECT k, v FROM settings"):
            values[row["k"]] = row["v"] if row["v"] is not None else ""
    return values


def get_setting(key, default=""):
    row = get_db().execute("SELECT v FROM settings WHERE k = ?", (key,)).fetchone()
    if row is None:
        return DEFAULT_SETTINGS.get(key, default)
    return row["v"] if row["v"] is not None else ""


def set_settings(mapping):
    """批量写入配置。"""
    conn = get_db()
    conn.executemany(
        "INSERT INTO settings (k, v, updated_at) VALUES (?, ?, datetime('now', 'localtime')) "
        "ON CONFLICT(k) DO UPDATE SET v = excluded.v, updated_at = excluded.updated_at",
        [(k, "" if v is None else str(v)) for k, v in mapping.items()],
    )
    conn.commit()
