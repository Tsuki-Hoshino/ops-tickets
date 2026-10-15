"""全局配置：路径、常量、类别枚举与关键词表。"""

from pathlib import Path

# ---------- 路径 ----------
BASE_DIR = Path(__file__).resolve().parent.parent
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
EXPORT_DIR = DATA_DIR / "exports"
DB_PATH = DATA_DIR / "app.db"
SECRET_KEY_FILE = DATA_DIR / "secret_key"
SCHEMA_FILE = APP_DIR / "schema.sql"

# ---------- 服务 ----------
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
TIMEZONE = "Asia/Shanghai"

# ---------- 上传 ----------
MAX_PHOTO_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}

# 浏览器端压缩参数（注入页面，前端按此执行）
PHOTO_MAX_EDGE = 1600
PHOTO_JPEG_QUALITY = 0.78

# ---------- 类别 ----------
FALLBACK_CATEGORY = "其他"
CATEGORIES = [
    "机房基础设施",
    "网络与专线",
    "云桌面与虚拟化",
    "叫号与信息发布",
    "终端与外设",
    "新增接入与配置",
    FALLBACK_CATEGORY,
]

# 关键词表：按声明顺序匹配，先命中者胜
CATEGORY_KEYWORDS = [
    ("ups", "机房基础设施"),
    ("精密空调", "机房基础设施"),
    ("配电", "机房基础设施"),
    ("市电", "机房基础设施"),
    ("消防", "机房基础设施"),
    ("交换机", "网络与专线"),
    ("路由", "网络与专线"),
    ("vpn", "网络与专线"),
    ("专线", "网络与专线"),
    ("光电转换", "网络与专线"),
    ("无线", "网络与专线"),
    ("链路", "网络与专线"),
    ("云桌面", "云桌面与虚拟化"),
    ("虚拟机", "云桌面与虚拟化"),
    ("超融合", "云桌面与虚拟化"),
    ("宿主机", "云桌面与虚拟化"),
    ("叫号", "叫号与信息发布"),
    ("取号", "叫号与信息发布"),
    ("大屏", "叫号与信息发布"),
    ("信息发布", "叫号与信息发布"),
    ("打印", "终端与外设"),
    ("扫描仪", "终端与外设"),
    ("高拍仪", "终端与外设"),
    ("终端", "终端与外设"),
    ("显示器", "终端与外设"),
    ("台式机", "终端与外设"),
    ("电脑", "终端与外设"),
    ("新增", "新增接入与配置"),
    ("入网", "新增接入与配置"),
    ("配网", "新增接入与配置"),
    ("迁移", "新增接入与配置"),
    ("重装", "新增接入与配置"),
]

# 默认部门候选（示例名称，作为表单输入提示）
DEFAULT_DEPARTMENTS = ["综合科", "业务一科", "后勤组"]

# ---------- 设置键 ----------
DEFAULT_SETTINGS = {
    "site_name": "运维工单系统",
    "report_org": "",
    "report_project": "",
    "report_author": "",
    "llm_enabled": "0",
    "llm_api_base": "",
    "llm_api_key": "",
    "llm_model": "",
    "llm_temperature": "0.3",
    "llm_timeout": "60",
    "llm_max_tokens": "2048",
}

# ---------- 报告 ----------
REPORT_SECTIONS = [
    "一、报告概述",
    "二、日常巡检工作执行情况",
    "三、售后服务工单处置情况",
    "四、问题分析",
    "五、下期工作计划",
    "结语",
]

PERIOD_PRESETS = [
    ("this_week", "本周"),
    ("last_week", "上周"),
    ("this_month", "本月"),
    ("last_month", "上月"),
    ("custom", "自定义"),
]

# ---------- 会话 ----------
REMEMBER_DAYS = 30
