"""大模型接入：配置检查、连接测试、容错 JSON 提取、报告章节生成。

API 地址、Key、模型名全部来自设置页，默认都是空字符串。
任何网络异常、超时、返回结构异常或解析失败都统一返回中文失败原因，
由调用方降级为本地合成，保证报告一定能生成出来。
"""

import json
import re
import time

import requests

from .config import REPORT_SECTIONS

__all__ = ["is_configured", "test_connection", "extract_json", "generate_sections"]

# 设置项缺省值（与 config.DEFAULT_SETTINGS 保持一致）
DEFAULT_TIMEOUT = 60.0
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.3

# 超时与 token 的合理边界，避免用户填 0 或超大值
MIN_TIMEOUT, MAX_TIMEOUT = 1.0, 600.0
MIN_MAX_TOKENS, MAX_MAX_TOKENS = 16, 32768

_CHAT_PATH = "/chat/completions"

_FENCE_RE = re.compile(r"```[A-Za-z0-9_+-]*\s*(.*?)```", re.S)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_HEADING_PREFIX_RE = re.compile(r"^[\s（(【\[]*[一二三四五六七八九十百零〇]+[）)】\]、.．，,:：]*\s*")
_HEADING_NOISE_RE = re.compile(r"[\s、。，．,.:：;；\-—_（）()【】\[\]「」“”\"'#*]+")
_MARKDOWN_PREFIX_RE = re.compile(r"^\s*(?:#{1,6}|[-*+>]|\d+[.、)])\s*")


# ---------- 设置项读取 ----------


def _opt(settings, key, default=""):
    """兼容 dict 与 sqlite3.Row 读取设置项，缺失或 None 时返回默认值。"""
    if settings is None:
        return default
    try:
        value = settings[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def _as_bool(value):
    """把 ``1/0/true/false/on/off/yes/no`` 这类设置值转成布尔。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "启用", "是"}


def _as_float(value, default):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_int(value, default):
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _short(text, limit=200):
    """压掉换行并截断，用于拼错误信息与提示语。"""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit] + "…"


def _timeout_of(settings):
    value = _as_float(_opt(settings, "llm_timeout", DEFAULT_TIMEOUT), DEFAULT_TIMEOUT)
    return min(max(value, MIN_TIMEOUT), MAX_TIMEOUT)


# ---------- 地址与请求 ----------


def _candidate_urls(api_base):
    """由用户填写的 API 地址推导候选的 chat/completions 地址。

    容忍：结尾斜杠、填或不填 ``/v1``、直接填完整的 ``/chat/completions``。
    仅在没有协议前缀时补 ``http://``（内网常见写法）。
    """
    base = str(api_base or "").strip()
    if not base:
        return []
    if "://" not in base:
        base = "http://" + base
    base = base.rstrip("/")
    if base.endswith(_CHAT_PATH):
        return [base]
    if base.endswith("/v1"):
        return [base + _CHAT_PATH]
    # 没写 /v1：先按补 /v1 试，遇到 404/405 再退回不补的形式
    return [base + "/v1" + _CHAT_PATH, base + _CHAT_PATH]


def _build_headers(settings):
    headers = {"Content-Type": "application/json"}
    key = str(_opt(settings, "llm_api_key") or "").strip()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _build_payload(settings, messages):
    temperature = min(max(_as_float(_opt(settings, "llm_temperature", DEFAULT_TEMPERATURE), DEFAULT_TEMPERATURE), 0.0), 2.0)
    max_tokens = _as_int(_opt(settings, "llm_max_tokens", DEFAULT_MAX_TOKENS), DEFAULT_MAX_TOKENS)
    max_tokens = min(max(max_tokens, MIN_MAX_TOKENS), MAX_MAX_TOKENS)
    return {
        "model": str(_opt(settings, "llm_model") or "").strip(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


def _post_chat(settings, messages):
    """POST 到 OpenAI 兼容接口，返回 ``(响应字典, 中文错误)``，二者必有其一为空。"""
    api_base = str(_opt(settings, "llm_api_base") or "").strip()
    if not api_base:
        return None, "未配置 API 地址"
    model = str(_opt(settings, "llm_model") or "").strip()
    if not model:
        return None, "未配置模型名"

    urls = _candidate_urls(api_base)
    payload = _build_payload(settings, messages)
    headers = _build_headers(settings)
    timeout = _timeout_of(settings)

    last_error = "接口地址不可达"
    for index, url in enumerate(urls):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.Timeout:
            return None, f"连接超时：{timeout:g} 秒内没有响应"
        except requests.RequestException as exc:
            return None, f"网络请求失败：{_short(exc, 160)}"

        if response.status_code in (404, 405):
            last_error = f"接口地址不存在（HTTP {response.status_code}）"
            if index < len(urls) - 1:
                continue  # 可能是少了或多了 /v1，换下一种写法重试
            return None, last_error
        if response.status_code >= 400:
            return None, f"接口返回错误（HTTP {response.status_code}）：{_short(response.text, 160)}"

        try:
            data = response.json()
        except ValueError:
            return None, "接口返回的不是合法 JSON"
        if not isinstance(data, dict):
            return None, "接口返回的 JSON 顶层不是对象"
        return data, ""
    return None, last_error


def _content_text(value):
    """把 message.content 归一成文本（兼容字符串与分段列表两种形态）。"""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(part.strip() for part in parts if part.strip())
    return ""


def _read_content(data):
    """从接口响应里取出首条回复的文本，返回 ``(文本, 中文错误)``。"""
    choices = data.get("choices") if isinstance(data, dict) else None
    if not isinstance(choices, list) or not choices:
        return "", "接口返回缺少 choices 字段"
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first.get("message"), dict) else {}
    text = _content_text(message.get("content"))
    if not text:
        text = _content_text(first.get("text"))
    if not text:
        return "", "接口返回内容为空"
    return text, ""


# ---------- 对外接口 ----------


def is_configured(settings):
    """启用开关打开，且 API 地址与模型名都非空时才算配置完成。"""
    if not _as_bool(_opt(settings, "llm_enabled")):
        return False
    if not str(_opt(settings, "llm_api_base") or "").strip():
        return False
    return bool(str(_opt(settings, "llm_model") or "").strip())


def test_connection(settings):
    """向配置的接口发一次最小请求，验证能否正常返回。

    只校验地址与模型名，不要求先打开启用开关，方便设置页保存前试连。
    返回 ``{"ok": bool, "message": 中文提示, "elapsed": 耗时秒数}``，绝不抛异常。
    """
    started = time.perf_counter()

    def result(ok, message):
        return {"ok": ok, "message": message, "elapsed": round(time.perf_counter() - started, 2)}

    if not str(_opt(settings, "llm_api_base") or "").strip():
        return result(False, "未填写 API 地址")
    if not str(_opt(settings, "llm_model") or "").strip():
        return result(False, "未填写模型名")

    try:
        data, error = _post_chat(settings, [{"role": "user", "content": "请只回复「连接正常」四个字。"}])
        if error:
            return result(False, error)
        content, error = _read_content(data)
        if error:
            return result(False, error)
    except Exception as exc:  # 兜底：任何未预料的异常都转成失败结果
        return result(False, f"测试连接失败：{type(exc).__name__}")

    return result(True, f"连接成功，模型返回：{_short(content, 60)}")


def _strip_trailing_commas(text):
    """去掉对象/数组结尾多余逗号（``{"a": 1,}``）。"""
    return _TRAILING_COMMA_RE.sub(r"\1", text)


def _json_variants(text):
    """产生候选 JSON 文本：原文 → 去代码围栏 → 去尾逗号 → 截取花括号片段。"""
    seen = []

    def push(value):
        value = (value or "").strip()
        if value and value not in seen:
            seen.append(value)

    push(text)
    for item in list(seen):
        for match in _FENCE_RE.finditer(item):
            push(match.group(1))
    for item in list(seen):
        push(_strip_trailing_commas(item))
    for item in list(seen):
        start, end = item.find("{"), item.rfind("}")
        if start != -1 and end > start:
            push(item[start : end + 1])
            push(_strip_trailing_commas(item[start : end + 1]))
    return seen


def _balanced_objects(text):
    """扫描文本，按出现顺序产出括号配平的 ``{...}`` 片段（从最外层开始）。"""
    length = len(text)
    for start in range(length):
        if text[start] != "{":
            continue
        depth = 0
        in_string = False
        escaped = False
        for cursor in range(start, length):
            char = text[cursor]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    yield text[start : cursor + 1]
                    break


def extract_json(text):
    """从模型回复里尽力提取 JSON 对象，全部失败返回 None。

    依次容忍：```json 围栏包裹、前后夹带解释文字、结尾多余逗号，
    最后再按花括号配平逐段尝试；顶层不是对象的 JSON 视为失败。
    """
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None

    for candidate in _json_variants(raw):
        try:
            parsed = json.loads(candidate)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, dict):
            return parsed

    for fragment in _balanced_objects(raw):
        for candidate in (fragment, _strip_trailing_commas(fragment)):
            try:
                parsed = json.loads(candidate)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


# ---------- 报告章节生成 ----------


def _skeleton_from_base(base):
    """取得章节骨架：优先用 ``base`` 里的 sections，否则用配置里的六章标题。"""
    skeleton = []
    sections = base.get("sections") if isinstance(base, dict) else None
    if isinstance(sections, list):
        for item in sections:
            if not isinstance(item, dict):
                continue
            heading = str(item.get("heading") or "").strip()
            if not heading:
                continue
            level = item.get("level")
            skeleton.append({"heading": heading, "level": level if isinstance(level, int) else 1})
    if not skeleton:
        skeleton = [{"heading": heading, "level": 1} for heading in REPORT_SECTIONS]
    return skeleton


def _heading_key(text):
    """归一化标题，便于和骨架章节比对（忽略序号、标点与空白）。"""
    value = _HEADING_PREFIX_RE.sub("", str(text or "").strip())
    return _HEADING_NOISE_RE.sub("", value)


def _clean_paragraphs(value):
    """把模型给的段落值归一成非空字符串列表。"""
    if isinstance(value, str):
        lines = []
        for line in value.splitlines():
            line = _MARKDOWN_PREFIX_RE.sub("", line).strip()
            if line:
                lines.append(line)
        return lines
    if isinstance(value, list):
        paragraphs = []
        for item in value:
            if isinstance(item, dict):
                for key in ("text", "content", "paragraph"):
                    if isinstance(item.get(key), str):
                        paragraphs.extend(_clean_paragraphs(item[key]))
                        break
            else:
                paragraphs.extend(_clean_paragraphs(item))
        return paragraphs
    return []


def _read_section(item):
    """读出一个模型返回的章节，返回 ``(标题, 段落列表)``。"""
    if isinstance(item, str):
        return "", _clean_paragraphs(item)
    if not isinstance(item, dict):
        return "", []
    heading = ""
    for key in ("heading", "title", "name", "section"):
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            heading = value.strip()
            break
    paragraphs = []
    for key in ("paragraphs", "content", "body", "text"):
        if key in item:
            paragraphs = _clean_paragraphs(item[key])
            if paragraphs:
                break
    return heading, paragraphs


def _normalize_sections(payload, skeleton):
    """把模型返回的章节对齐到本地骨架，返回 ``[{heading, level, paragraphs}]``。"""
    raw_sections = payload.get("sections") if isinstance(payload, dict) else None
    if not isinstance(raw_sections, list):
        return []

    matched = {}
    leftovers = []
    for item in raw_sections:
        heading, paragraphs = _read_section(item)
        if not paragraphs:
            continue
        target = None
        key = _heading_key(heading)
        if key:
            for index, section in enumerate(skeleton):
                if index not in matched and _heading_key(section["heading"]) == key:
                    target = index
                    break
        if target is not None:
            matched[target] = paragraphs
        else:
            leftovers.append(paragraphs)

    # 标题写得不一致的章节，按剩余顺序依次回填到骨架空位
    cursor = 0
    for index, section in enumerate(skeleton):
        if index in matched:
            continue
        if cursor < len(leftovers):
            matched[index] = leftovers[cursor]
            cursor += 1

    return [
        {"heading": section["heading"], "level": section["level"], "paragraphs": matched[index]}
        for index, section in enumerate(skeleton)
        if index in matched
    ]


def _stats_digest(stats):
    """把统计字典压缩成便于模型阅读的中文摘要。"""
    data = stats if isinstance(stats, dict) else {}
    close_rate = _as_float(data.get("close_rate"), 0.0)

    def dist(items):
        if not isinstance(items, list):
            return []
        result = []
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            count = item.get("count", 0)
            ratio = _as_float(item.get("ratio"), 0.0)
            result.append(f"{name} {count} 单（占 {round(ratio * 100, 1)}%）")
        return result

    return {
        "工单总数": data.get("total", 0),
        "已闭环": data.get("closed", 0),
        "未闭环": data.get("open", 0),
        "闭环率": f"{round(close_rate * 100, 1)}%",
        "平均总时长": data.get("avg_total") or "无样本",
        "平均响应时长": data.get("avg_response") or "无样本",
        "平均处理时长": data.get("avg_handle") or "无样本",
        "部门分布": dist(data.get("dept_dist")),
        "类别分布": dist(data.get("cat_dist")),
        "时间倒挂工单数": len(data.get("anomalies") or []),
    }


def _build_messages(stats, period_label, skeleton):
    """构造对话消息：要求模型只输出一个含 sections 的 JSON 对象。"""
    system = (
        "你是一名运维服务报告撰写助手。请依据给定的统计数据，为报告的每个章节撰写正式、"
        "简洁、客观的中文正文，直接陈述事实与做法，不要空话套话。\n"
        "只输出一个 JSON 对象，不要输出解释文字、不要使用 Markdown 代码块标记。\n"
        'JSON 结构：{"sections": [{"heading": "章节标题", "paragraphs": ["第一段", "第二段"]}]}\n'
        "要求：章节顺序与给定标题完全一致；每章 1 至 3 段，每段 80 至 200 字；"
        "不得编造统计数据中不存在的内容，不得出现具体单位名称、人名、IP 地址或域名。"
    )
    user = "\n".join(
        [
            f"报告周期：{period_label or '未指定'}",
            "",
            "统计数据：",
            json.dumps(_stats_digest(stats), ensure_ascii=False, indent=2),
            "",
            "需要撰写的章节（标题与顺序保持不变）：",
            "\n".join(f"{index}. {section['heading']}" for index, section in enumerate(skeleton, 1)),
            "",
            "请为以上每个章节各写 1 至 3 段正文。",
        ]
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def generate_sections(stats, period_label, settings, base):
    """调用大模型生成报告六个章节的正文段落。

    参数:
        stats: :func:`app.stats.summarize` 的返回字典。
        period_label: 周期中文标签，如「2026 年 3 月」。
        settings: 设置字典（``llm_*`` 键）。
        base: 本地合成的报告内容骨架（``content`` 结构），用于取章节标题与层级。

    返回:
        成功 ``({"sections": [{"heading", "level", "paragraphs"}]}, "")``；
        任何失败都返回 ``(None, 中文原因)``，由调用方降级为本地合成。
    """
    try:
        if not is_configured(settings):
            return None, "未启用大模型，或未配置 API 地址与模型名"

        skeleton = _skeleton_from_base(base)
        data, error = _post_chat(settings, _build_messages(stats, period_label, skeleton))
        if error:
            return None, error

        content, error = _read_content(data)
        if error:
            return None, error

        payload = extract_json(content)
        if payload is None:
            return None, "模型返回内容无法解析为 JSON"

        sections = _normalize_sections(payload, skeleton)
        if not sections:
            return None, "模型返回的 JSON 中没有可用的章节正文"
        return {"sections": sections}, ""
    except Exception as exc:  # 兜底：绝不把异常抛到视图层
        return None, f"调用大模型时发生未预期错误：{type(exc).__name__}"
