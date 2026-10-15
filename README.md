# 运维工单与报告系统

给机房 / 数据中心运维人员用的内网单机工具。日常把处理过的故障与需求登记成工单，月底把工单导成 Excel 台账上交，再出一份 Word 格式的周报或月报。

Python + Flask 写在一个目录里，数据存在本地 SQLite 文件中。装好依赖双击 `start.bat` 就能用，运行期间只需要一台机器。

## 能做什么

**对外展示与登录**
打开首页即可看总览面板：当月、本周、本日工作量，按部门与按类别的分布，最近工单和未闭环工单。未登录状态就能看到这些，适合直接投屏或把地址给来访人员查看。工单、导出、报告、设置页需要登录；登录时勾选「记住我」可以 30 天免登录。

**工单登记**
一条工单记录报修、到场、完成三个时间点，以及部门、类别、需求/故障、原因、处理方法、操作人、备注。填写完成时间即视为闭环，未填就是待处理。可附处理前与处理后照片，各支持多张。

- 选中的照片由浏览器自动压缩后再上传（最长边 1600px、JPEG 质量 0.78），压缩失败就用原图，页面上会显示压缩前后的体积对比
- 填完「需求/故障」离开输入框时，类别会按关键词表自动选中，例如「交换机」→ 网络与专线、「精密空调」→ 机房基础设施
- 单张照片上限 10MB，接受 JPG / PNG / GIF / BMP / WEBP

**查找与维护**
工单列表支持按部门、类别、状态（已闭环 / 未闭环）、日期范围、关键词筛选，每页 20 条。详情页展示全部字段与照片，照片可点开大图、可单张删除，工单本身可编辑或删除（删除会一并清掉照片文件）。

**Excel 台账导出**
按月导出 xlsx，工作表名形如 `3月`，六列表头为「开始时间 | 部门 | 需求/故障 | 原因 | 处理方法 | 完成时间」。两种排版可选：按日期分组（每天一行日期分组行，当天工单排在其后）或每行完整日期时间。导出前显示该月工单条数与照片张数，该月无数据时导出按钮不可点。另外可选两件事：把处理前后各一张照片内嵌进台账、把只填了报修时间的未闭环工单也带上。

**周报 / 月报**
周期可选本周、上周、本月、上月或自定义日期范围。正文按「报告概述 / 日常巡检工作执行情况 / 售后服务工单处置情况 / 问题分析 / 下期工作计划 / 结语」组织，主要数字来自本期统计。生成前可以先预览该周期的统计。

配置了大模型就让模型来写正文，没配置或调用失败时由程序用本期统计数据合成，两种情况都能拿到 docx。生成的报告列在报告页，可以查看、下载、删除。

**Word 排版**
按 GB/T 9704—2012《党政机关公文格式》排版：A4 纵向、页边距上 3.7cm / 下 3.5cm / 左 2.8cm / 右 2.6cm、正文三号仿宋固定行距 28.8pt 首行缩进 2 字符、一至四级标题分别用黑体 / 楷体 / 仿宋、封面二号小标宋、页码四号宋体「— 1 —」且单页居右双页居左、附件另起一页且每页最多两张图。封面与目录不编页码，正文页码从 1 开始。

**设置页**
站点名称、报告抬头（单位名称 / 项目名称 / 编制人，默认留空由使用者填写）、大模型接口配置，以及用户管理：新增、编辑、删除、重置密码，角色分管理员与编辑两种。编辑角色进不了设置页。不能删除当前登录的账号，也不能停用或降级最后一个管理员。

## 环境要求

- Python 3.10 或更高版本，安装时勾选 `Add Python to PATH`

## 快速开始

1. 解压到任意目录
2. 双击 `start.bat`，它会检查 Python、安装缺失的依赖、启动服务并打开浏览器
3. 首次打开进入安装向导，填写站点名称与管理员账号密码
4. 用刚设置的账号登录

手动启动：

```bat
python -m pip install -r requirements.txt
python run.py
```

默认监听 `0.0.0.0:8080`，本机访问 <http://127.0.0.1:8080/>，内网其他电脑访问 `http://<本机IP>:8080/`。

常用参数：

```bat
python run.py --port 9000          # 换端口
python run.py --host 127.0.0.1     # 只允许本机访问
python run.py --threads 16         # 工作线程数，默认 8
python run.py --open-browser       # 启动后打开浏览器
```

也可以用环境变量 `OPS_PORT`、`OPS_HOST` 指定端口与监听地址。

## 目录结构

```
run.py                  启动入口（waitress）
start.bat               Windows 一键启动
requirements.txt        依赖清单
app/                    应用代码
  __init__.py           应用工厂、路由守卫、模板上下文
  config.py             路径、类别枚举、关键词表、默认设置
  schema.sql            SQLite 建表语句
  db.py                 数据库连接与配置读写
  auth.py               安装向导、登录、退出
  dashboard.py          总览面板
  records.py            工单增删改查与照片
  exports.py            Excel 台账导出
  reports.py            报告列表 / 生成 / 下载
  report_service.py     周期解析、正文合成、Word 落盘
  settings.py           站点、大模型与用户管理
  stats.py              统计口径
  llm.py                OpenAI 兼容接口调用与容错解析
  excel_export.py       openpyxl 排版
  docx_report.py        python-docx 公文排版
  utils.py              时间、类别识别、权限等通用工具
templates/              Jinja2 模板
static/                 样式与脚本
data/                   运行时产物（首次运行自动创建）
```

## 数据与备份

运行时产物全部集中在 `data/`：

| 路径 | 内容 |
| --- | --- |
| `data/app.db` | SQLite 数据库：工单、照片索引、报告、用户、设置 |
| `data/uploads/` | 工单照片，按工单编号分目录 |
| `data/reports/` | 生成的 Word 报告 |
| `data/exports/` | 导出的 Excel，超过一小时自动清理 |
| `data/secret_key` | 会话密钥，首次运行生成 |

**备份就是复制整个 `data` 目录**，恢复时把它放回程序目录即可。

## 大模型配置

在「设置 → 大模型设置」填接口地址、API Key、模型名、温度、超时、最大 token，保存后点「测试连接」。接口地址填到服务根地址即可，例如 `https://example.com/v1`，程序会自己补 `/chat/completions`。

模型返回的内容会做容错处理：包在 ` ```json ` 围栏里、前后夹带解释文字、结尾多一个逗号，都能提取出来正常解析。

## 需要改默认值的时候

| 想改的东西 | 位置 |
| --- | --- |
| 类别枚举、自动识别关键词表 | `app/config.py` 的 `CATEGORIES`、`CATEGORY_KEYWORDS` |
| 表单里的部门候选 | `app/config.py` 的 `DEFAULT_DEPARTMENTS` |
| 默认端口、监听地址 | `app/config.py` 的 `DEFAULT_PORT`、`DEFAULT_HOST` |
| 照片压缩参数、单张上限 | `app/config.py` 的 `PHOTO_MAX_EDGE`、`PHOTO_JPEG_QUALITY`、`MAX_PHOTO_BYTES` |
| 报告章节骨架 | `app/config.py` 的 `REPORT_SECTIONS` |
| 台账列宽与字体 | `app/excel_export.py` 的 `COLUMN_WIDTHS`、`FONT_NAME` |
| 颜色与表格密度 | `static/css/app.css` 顶部的 CSS 变量 |

改完重启服务生效。类别与部门是纯配置，改动不影响已有数据。

## 常见问题

**双击 `start.bat` 提示未检测到 Python**

安装 Python 时勾选 `Add Python to PATH`，或把 Python 安装目录和它的 `Scripts` 目录手动加入 PATH。

**浏览器打不开页面**

先看启动窗口有没有报错。端口被占用时换一个：`python run.py --port 9001`。

**内网其他电脑访问不了**

服务默认监听 `0.0.0.0`，确认 Windows 防火墙放行了该端口。

**忘记管理员密码**

停掉服务，在程序目录执行下面这条命令（把 `admin` 和 `新密码` 换成实际值），再重新启动：

```bat
python -c "import sqlite3;from werkzeug.security import generate_password_hash;c=sqlite3.connect('data/app.db');c.execute('update users set password_hash=? where username=?',(generate_password_hash('新密码'),'admin'));c.commit();print('已重置')"
```

**想清空重来**

停掉服务，删掉 `data` 目录，重新启动会回到安装向导。

**照片传不上去**

单张限 10MB，接受 JPG / PNG / GIF / BMP / WEBP。浏览器会先压缩，仍超限就手动缩小再传。

**导出的 Excel 里日期显示成数字**

台账的「开始时间」列存的是 Excel 日期序列号，套用日期格式后在 Excel 里显示为正常日期；用脚本读原始值时需要注意这一点。

## 技术栈与数据格式

Flask + waitress + SQLite（标准库 `sqlite3`）+ Jinja2 + openpyxl + python-docx + Pillow + requests；前端为原生 HTML / CSS / JavaScript。

时间列统一存 `YYYY-MM-DD HH:MM:SS` 文本，时区固定 UTC+8。SQLite 启用 WAL 模式与 busy timeout，多线程下不会出现 `database is locked`。
