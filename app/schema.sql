-- 数据库结构：首次运行（安装向导）时一次性建库
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT    NOT NULL UNIQUE,
    password_hash TEXT    NOT NULL,
    display_name  TEXT    NOT NULL DEFAULT '',
    role          TEXT    NOT NULL DEFAULT 'admin',   -- admin | editor
    is_active     INTEGER NOT NULL DEFAULT 1,
    last_login_at TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS settings (
    k          TEXT PRIMARY KEY,
    v          TEXT,
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS records (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_on TEXT NOT NULL,                        -- 报修日期 YYYY-MM-DD，由 reported_at 派生
    reported_at TEXT,                                 -- 报修时间
    arrived_at  TEXT,                                 -- 到场时间
    finished_at TEXT,                                 -- 完成时间
    department  TEXT NOT NULL DEFAULT '',
    category    TEXT NOT NULL DEFAULT '其他',
    symptom     TEXT NOT NULL DEFAULT '',             -- 需求/故障
    cause       TEXT NOT NULL DEFAULT '',
    solution    TEXT NOT NULL DEFAULT '',
    status      TEXT NOT NULL DEFAULT 'open',         -- closed | open
    operator    TEXT NOT NULL DEFAULT '',
    notes       TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_records_occurred ON records (occurred_on);
CREATE INDEX IF NOT EXISTS idx_records_reported ON records (reported_at);
CREATE INDEX IF NOT EXISTS idx_records_dept     ON records (department);
CREATE INDEX IF NOT EXISTS idx_records_cat      ON records (category);
CREATE INDEX IF NOT EXISTS idx_records_status   ON records (status);

CREATE TABLE IF NOT EXISTS record_photos (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id     INTEGER NOT NULL,
    stage         TEXT    NOT NULL DEFAULT 'before',  -- before=处理前 | after=处理后
    filename      TEXT    NOT NULL,                   -- 相对 data/uploads 的文件名
    original_name TEXT    NOT NULL DEFAULT '',
    mime          TEXT    NOT NULL DEFAULT '',
    size          INTEGER NOT NULL DEFAULT 0,
    sort_order    INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_photos_record ON record_photos (record_id);
CREATE INDEX IF NOT EXISTS idx_photos_stage  ON record_photos (record_id, stage);

CREATE TABLE IF NOT EXISTS reports (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    period_type   TEXT    NOT NULL,                   -- week | month
    period_start  TEXT    NOT NULL,
    period_end    TEXT    NOT NULL,
    title         TEXT    NOT NULL,
    status        TEXT    NOT NULL DEFAULT 'draft',   -- draft | generated | failed
    content_json  TEXT,
    stats_json    TEXT,
    docx_path     TEXT,
    llm_model     TEXT,
    error_message TEXT,
    created_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at    TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
);
