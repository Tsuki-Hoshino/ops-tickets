"""Word 报告生成模块（GB/T 9704—2012《党政机关公文格式》排版）。

排版逐条对齐 GB/T 9704—2012 的版式与字体规定：A4 纵向（210mm × 297mm）、上 3.7cm / 下 3.5cm /
左 2.8cm / 右 2.6cm（版心 15.6cm × 22.5cm）、页脚区高度 2.8cm、正文三号仿宋两端对齐、
固定行距 28.8pt、首行缩进 2 字符（32pt）；一级标题三号黑体、二级标题三号楷体、
三/四级标题三号仿宋；封面标题二号小标宋；成文日期右空四字；页码四号宋体「— 1 —」
（单页居右空一字、双页居左空一字）；阿拉伯数字与外文用 Times New Roman；附件另起
一页、附件图片每页最多 2 张且宽不超版心、高不超过 8cm、等比缩放。

另有封面空行规则、目录规则（题名「目　　录」黑体、条目仿宋、每层缩进 2 字符、
右对齐制表位加点线前导、页码未知输出占位符「—」）、封面不编页码而正文页码从 1 开始
（分节符 + 页脚断开继承）、奇偶页不同页脚。

python-docx 实现要点：
1. 中文字体除 ``font.name``（写 ``w:ascii``/``w:hAnsi``）外，必须同时写 ``w:eastAsia``，
   并置 ``w:hint="eastAsia"``，否则中文与全角标点会回退成默认字体；
2. 页码用域实现：``w:fldChar``（begin / separate / end）+ ``w:instrText``（``PAGE``）；
3. 封面不编页码、正文从 1 开始：封面、目录、正文各成一节，脚均断开与前一节的链接，
   正文节再写 ``w:pgNumType/@w:start="1"``；
4. 奇偶页页脚不同：在 ``settings.xml`` 写 ``w:evenAndOddHeaders``，并分别定义默认
   （奇数页）与 even（偶数页）页脚；
5. 行距用固定值（``w:lineRule="exact"``）；图片段落除外——固定行距
   会把高于行距的内嵌图片裁掉，故图片段落用单倍行距。

仅依赖 python-docx 与标准库；读取图片像素尺寸优先用 Pillow，不可用时退回
python-docx 自带的图片头解析。
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT, WD_SECTION
from docx.enum.text import (
    WD_ALIGN_PARAGRAPH,
    WD_LINE_SPACING,
    WD_TAB_ALIGNMENT,
    WD_TAB_LEADER,
)
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

__all__ = ["build_document"]


# ---------- 排版常量（GB/T 9704—2012） ----------

PAGE_WIDTH = Cm(21)  # 6.1 纸张：A4 210mm × 297mm
PAGE_HEIGHT = Cm(29.7)
MARGIN_TOP = Cm(3.7)  # 6.2 页边距
MARGIN_BOTTOM = Cm(3.5)
MARGIN_LEFT = Cm(2.8)
MARGIN_RIGHT = Cm(2.6)
BODY_WIDTH = Cm(15.6)  # 6.2 版心：21 - 2.8 - 2.6 = 15.6cm
FOOTER_DISTANCE = Cm(2.8)  # 7.3.6 页脚区高度（页码上边缘距页面下边缘）

LINE_SPACING = Pt(28.8)  # 7.3.3 / 6.4 正文固定行距
FIRST_LINE_INDENT = Pt(32)  # 6.3 / 7.3.3 首行缩进 2 字符（三号 16pt × 2）
CHAR_WIDTH_3 = 16.0  # 三号字宽（pt），用于按「字」折算缩进
CHAR_WIDTH_4 = 14.0  # 四号字宽（pt）
DATE_RIGHT_INDENT = Pt(CHAR_WIDTH_3 * 4)  # 7.3.5.1 成文日期右空四字
PAGE_NUMBER_INDENT = Pt(CHAR_WIDTH_4 * 1)  # 7.3.6 页码居右/居左空一字

FONT_FANGSONG = "仿宋"  # 正文
FONT_HEITI = "黑体"  # 一级标题、目录题名、附件标识
FONT_KAITI = "楷体"  # 二级标题
FONT_SONG = "宋体"  # 页码
FONT_TITLE = "方正小标宋_GBK"  # 7.3.1 封面标题
FONT_TITLE_FALLBACK = "华文中宋"  # 小标宋缺失时整体替换
FONT_WEST = "Times New Roman"  # 阿拉伯数字与外文

SIZE_2 = Pt(22)  # 二号
SIZE_3 = Pt(16)  # 三号
SIZE_4 = Pt(14)  # 四号

TOC_TITLE = "目\u3000\u3000录"  # 中间两个全角空格
PAGE_PLACEHOLDER = "—"  # 目录页码未知时的占位符
PAGE_NUMBER_PREFIX = "— "
PAGE_NUMBER_SUFFIX = " —"
PAGE_FIELD_INSTR = " PAGE "
PAGE_FIELD_PLACEHOLDER = "1"  # 域结果占位，Word 打开/打印时自动刷新

IMAGES_PER_PAGE = 2  # 附件图片每页最多 2 张
IMAGE_MAX_WIDTH_CM = 15.6  # 宽度上限＝版心宽
IMAGE_MAX_HEIGHT_CM = 8.0  # 高度上限
IMAGE_SPACE_AFTER = Pt(6)  # 图片段落下间距
FALLBACK_DPI = 96.0  # 图片未标注 DPI 时按屏幕 96 DPI 折算
MIN_DPI = 36.0
MAX_DPI = 600.0

# 成文日期：ISO 文本转公文写法（如 2026-03-31 → 2026年3月31日）
_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$")
# 附件标题里可能带的「附件」「附件1：」前缀
_ATTACHMENT_PREFIX_RE = re.compile(r"^\s*附件\s*[0-9０-９一二三四五六七八九十]*\s*[：:、.．]?\s*")


# ---------- 基础工具 ----------


def _set_run_font(run, *, cn_font: str, size, bold: bool = False) -> None:
    """设置 run 字体：西文/数字用 Times New Roman，中文用指定字体。

    必须同时写 ``w:eastAsia``，否则中文回退默认字体；``w:hint="eastAsia"`` 让
    全角标点等「歧义宽度」字符走中文字体。
    """
    run.font.name = FONT_WEST  # 写入 w:ascii 与 w:hAnsi
    run.font.size = size
    run.font.bold = bold
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.get_or_add_rFonts()
    rfonts.set(qn("w:eastAsia"), cn_font)
    rfonts.set(qn("w:hint"), "eastAsia")


def _format_paragraph(
    paragraph,
    *,
    align=WD_ALIGN_PARAGRAPH.JUSTIFY,
    first_line_indent=None,
    left_indent=None,
    right_indent=None,
    exact_spacing=LINE_SPACING,
    space_after=Pt(0),
    page_break_before=False,
):
    """统一段落格式：固定行距、指定对齐、缩进方式。"""
    fmt = paragraph.paragraph_format
    fmt.alignment = align
    fmt.space_before = Pt(0)
    fmt.space_after = space_after
    fmt.first_line_indent = first_line_indent
    fmt.left_indent = left_indent
    fmt.right_indent = right_indent
    fmt.page_break_before = page_break_before
    if exact_spacing is None:
        # 图片段落：固定行距会把图片裁切，改用单倍行距
        fmt.line_spacing_rule = WD_LINE_SPACING.SINGLE
    else:
        fmt.line_spacing = exact_spacing
        fmt.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    return paragraph


def _add_blank_lines(document, count: int) -> None:
    """写入若干空行（按三号字固定行距占位），用于封面留白。"""
    for _ in range(count):
        _format_paragraph(document.add_paragraph())


def _configure_section(section) -> None:
    """按 GB/T 9704—2012 设置纸张、页边距与页脚区高度。"""
    section.orientation = WD_ORIENT.PORTRAIT
    section.page_width = PAGE_WIDTH
    section.page_height = PAGE_HEIGHT
    section.top_margin = MARGIN_TOP
    section.bottom_margin = MARGIN_BOTTOM
    section.left_margin = MARGIN_LEFT
    section.right_margin = MARGIN_RIGHT
    section.footer_distance = FOOTER_DISTANCE


def _add_section(document):
    """插入「下一页」分节符并完成页面设置，返回新节。"""
    section = document.add_section(WD_SECTION.NEW_PAGE)
    _configure_section(section)
    return section


def _clear_footer(footer):
    """断开与前一节的页脚链接，清空内容，返回可写的页脚段落。"""
    footer.is_linked_to_previous = False
    paragraph = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
    for run in list(paragraph.runs):  # 清掉默认模板里可能带的空 run
        run._element.getparent().remove(run._element)
    _format_paragraph(
        paragraph,
        align=WD_ALIGN_PARAGRAPH.LEFT,
        exact_spacing=None,  # 页脚内容短，用单倍行距避免裁切
    )
    return paragraph


def _restart_page_numbering(section, start: int = 1) -> None:
    """在节属性里写 ``w:pgNumType/@w:start``，让本节页码从 start 重新计数。"""
    sect_pr = section._sectPr
    for old in sect_pr.findall(qn("w:pgNumType")):
        sect_pr.remove(old)
    element = OxmlElement("w:pgNumType")
    element.set(qn("w:start"), str(start))
    # 必须按 CT_SectPr 子元素顺序插入，否则 Word 报文档损坏
    sect_pr.insert_element_before(
        element,
        "w:cols",
        "w:formProt",
        "w:vAlign",
        "w:noEndnote",
        "w:titlePg",
        "w:textDirection",
        "w:bidi",
        "w:rtlGutter",
        "w:docGrid",
        "w:printerSettings",
        "w:sectPrChange",
    )


def _add_page_number_field(paragraph) -> None:
    """往段落插入 PAGE 域：begin → instrText(PAGE) → separate → 占位结果 → end。"""
    specs = (
        ("w:fldChar", "begin"),
        ("w:instrText", None),
        ("w:fldChar", "separate"),
        ("w:t", None),
        ("w:fldChar", "end"),
    )
    for tag, char_type in specs:
        run = paragraph.add_run()
        _set_run_font(run, cn_font=FONT_SONG, size=SIZE_4)
        element = OxmlElement(tag)
        if tag == "w:fldChar":
            element.set(qn("w:fldCharType"), char_type)
        elif tag == "w:instrText":
            element.set(qn("xml:space"), "preserve")
            element.text = PAGE_FIELD_INSTR
        else:
            element.text = PAGE_FIELD_PLACEHOLDER
        run._element.append(element)


def _write_page_number(paragraph, text_before: str, text_after: str) -> None:
    """写「— 页码 —」：连字符与数字分别走中文字体与 Times New Roman。"""
    run = paragraph.add_run(text_before)
    _set_run_font(run, cn_font=FONT_SONG, size=SIZE_4)
    _add_page_number_field(paragraph)
    run = paragraph.add_run(text_after)
    _set_run_font(run, cn_font=FONT_SONG, size=SIZE_4)


def _suppress_footer(section) -> None:
    """本节（封面、目录）不显示页码：断开继承并置空奇偶两种页脚。"""
    _clear_footer(section.footer)
    _clear_footer(section.even_page_footer)


def _enable_page_numbers(section) -> None:
    """正文节：页码从 1 开始，奇数页居右空一字、偶数页居左空一字。"""
    _restart_page_numbering(section, 1)
    # 默认页脚＝奇数页（单页码）
    paragraph = _clear_footer(section.footer)
    _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.RIGHT, right_indent=PAGE_NUMBER_INDENT, exact_spacing=None)
    _write_page_number(paragraph, PAGE_NUMBER_PREFIX, PAGE_NUMBER_SUFFIX)
    # even 页脚＝偶数页（双页码）
    paragraph = _clear_footer(section.even_page_footer)
    _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.LEFT, left_indent=PAGE_NUMBER_INDENT, exact_spacing=None)
    _write_page_number(paragraph, PAGE_NUMBER_PREFIX, PAGE_NUMBER_SUFFIX)


@lru_cache(maxsize=1)
def _detect_title_font() -> str:
    """探测「方正小标宋_GBK」是否安装，缺失时整体换成「华文中宋」。"""
    key_path = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
    try:
        import winreg
    except ImportError:  # 非 Windows：保持标准字体名，由 Word 自行替换
        return FONT_TITLE
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        try:
            key = winreg.OpenKey(hive, key_path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
        except OSError:
            continue
        try:
            index = 0
            while True:
                try:
                    name, _value, _type = winreg.EnumValue(key, index)
                except OSError:
                    break
                index += 1
                if "小标宋" in name:
                    return FONT_TITLE
        finally:
            key.Close()
    return FONT_TITLE_FALLBACK


def _normalize_dpi(dpi) -> tuple[float, float]:
    """图片自带 DPI 缺失或异常时按 96 DPI 处理。"""
    if not dpi:
        return FALLBACK_DPI, FALLBACK_DPI
    try:
        x, y = float(dpi[0]), float(dpi[1])
    except (TypeError, ValueError, IndexError):
        return FALLBACK_DPI, FALLBACK_DPI
    if MIN_DPI <= x <= MAX_DPI and MIN_DPI <= y <= MAX_DPI:
        return x, y
    return FALLBACK_DPI, FALLBACK_DPI


def _image_natural_cm(path: Path) -> tuple[float, float]:
    """读取图片自然尺寸（厘米）：优先 Pillow，退回 python-docx 的图片头解析。"""
    try:
        from PIL import Image

        with Image.open(path) as image:
            px_width, px_height = image.size
            dpi = image.info.get("dpi")
    except Exception:
        from docx.image.image import Image as DocxImage

        image = DocxImage.from_file(str(path))
        px_width, px_height = image.px_width, image.px_height
        dpi = (image.horz_dpi, image.vert_dpi)
    dpi_x, dpi_y = _normalize_dpi(dpi)
    return px_width / dpi_x * 2.54, px_height / dpi_y * 2.54


def _fit_image_size(path: Path):
    """等比缩放图片：宽不超版心、高不超过 8cm，且不放大小图。"""
    width_cm, height_cm = _image_natural_cm(path)
    if width_cm <= 0 or height_cm <= 0:
        return Cm(IMAGE_MAX_WIDTH_CM), Cm(IMAGE_MAX_HEIGHT_CM)
    scale = min(1.0, IMAGE_MAX_WIDTH_CM / width_cm, IMAGE_MAX_HEIGHT_CM / height_cm)
    return Cm(width_cm * scale), Cm(height_cm * scale)


def _format_cover_date(value) -> str:
    """成文日期按公文写法输出（阿拉伯数字、月日不编虚位）。"""
    text = str(value or "").strip()
    matched = _ISO_DATE_RE.match(text)
    if not matched:
        return text
    year, month, day = matched.groups()
    return f"{year}年{int(month)}月{int(day)}日"


def _clamp_level(value) -> int:
    """标题层级限定在 1~4 级。"""
    try:
        level = int(value)
    except (TypeError, ValueError):
        return 1
    return min(4, max(1, level))


def _heading_font(level: int) -> str:
    """7.3.3：一级黑体、二级楷体、三/四级仿宋。"""
    if level == 1:
        return FONT_HEITI
    if level == 2:
        return FONT_KAITI
    return FONT_FANGSONG


# ---------- 封面 ----------


def _build_cover(document, content: dict, title_font: str) -> None:
    """封面：标题上方 4 空行、标题与信息之间 2 空行、信息与署名之间 6 空行。"""
    cover = content.get("cover") or {}
    _add_blank_lines(document, 4)

    title = str(content.get("title") or "").strip()
    if title:
        paragraph = document.add_paragraph()
        _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=Pt(0))
        _set_run_font(paragraph.add_run(title), cn_font=title_font, size=SIZE_2)

    _add_blank_lines(document, 2)

    # 单位名称、项目名称：默认空字符串，为空则整行不排版
    for value in (cover.get("org"), cover.get("project")):
        text = str(value or "").strip()
        if not text:
            continue
        paragraph = document.add_paragraph()
        _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=Pt(0))
        _set_run_font(paragraph.add_run(text), cn_font=FONT_FANGSONG, size=SIZE_3)

    _add_blank_lines(document, 6)

    # 署名：编制人、成文日期，均右空四字
    for value in (cover.get("author"), _format_cover_date(cover.get("date"))):
        text = str(value or "").strip()
        if not text:
            continue
        paragraph = document.add_paragraph()
        _format_paragraph(
            paragraph,
            align=WD_ALIGN_PARAGRAPH.RIGHT,
            first_line_indent=Pt(0),
            right_indent=DATE_RIGHT_INDENT,
        )
        _set_run_font(paragraph.add_run(text), cn_font=FONT_FANGSONG, size=SIZE_3)


# ---------- 目录 ----------


def _build_toc(document, sections: list) -> None:
    """目录：题名黑体，条目仿宋、每层缩进 2 字符、右对齐制表位加点线前导。"""
    paragraph = document.add_paragraph()
    _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=Pt(0))
    _set_run_font(paragraph.add_run(TOC_TITLE), cn_font=FONT_HEITI, size=SIZE_3)

    for section in sections:
        heading = str((section or {}).get("heading") or "").strip()
        if not heading:
            continue
        level = _clamp_level((section or {}).get("level"))
        paragraph = document.add_paragraph()
        _format_paragraph(
            paragraph,
            align=WD_ALIGN_PARAGRAPH.LEFT,
            first_line_indent=Pt(0),
            left_indent=Pt(CHAR_WIDTH_3 * 2 * level),  # 每层缩进 2 字符
            exact_spacing=None,  # 目录条目用单倍行距，条目密集不撑页
        )
        # 条目与页码之间：右对齐制表位 + 点线前导
        paragraph.paragraph_format.tab_stops.add_tab_stop(
            BODY_WIDTH, WD_TAB_ALIGNMENT.RIGHT, WD_TAB_LEADER.DOTS
        )
        # 页码由 Word 分页决定，这里先输出占位符
        _set_run_font(
            paragraph.add_run(f"{heading}\t{PAGE_PLACEHOLDER}"),
            cn_font=FONT_FANGSONG,
            size=SIZE_3,
        )


# ---------- 正文 ----------


def _add_section_heading(document, text: str, level: int) -> None:
    """标题段落：三号（黑体/楷体/仿宋），首行缩进 2 字符，固定行距 28.8pt。"""
    paragraph = document.add_paragraph()
    _format_paragraph(paragraph, first_line_indent=FIRST_LINE_INDENT)
    _set_run_font(paragraph.add_run(text), cn_font=_heading_font(level), size=SIZE_3)


def _add_body_paragraph(document, text: str) -> None:
    """正文段落：三号仿宋、两端对齐、固定行距 28.8pt、首行缩进 2 字符。"""
    paragraph = document.add_paragraph()
    _format_paragraph(paragraph, first_line_indent=FIRST_LINE_INDENT)
    _set_run_font(paragraph.add_run(text), cn_font=FONT_FANGSONG, size=SIZE_3)


def _build_body(document, content: dict, title_font: str) -> None:
    """正文：报告标题、周期、各章节标题与段落。"""
    title = str(content.get("title") or "").strip()
    if title:
        paragraph = document.add_paragraph()
        _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=Pt(0))
        _set_run_font(paragraph.add_run(title), cn_font=title_font, size=SIZE_2)

    period = str(content.get("period_label") or "").strip()
    if period:
        paragraph = document.add_paragraph()
        _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=Pt(0))
        _set_run_font(paragraph.add_run(period), cn_font=FONT_KAITI, size=SIZE_3)

    for section in content.get("sections") or []:
        section = section or {}
        heading = str(section.get("heading") or "").strip()
        if heading:
            # 序号形式（一、／（一）／1.／（1））由 content 提供，本模块只按级套字体
            _add_section_heading(document, heading, _clamp_level(section.get("level")))
        for item in section.get("paragraphs") or []:
            text = str(item or "").strip()
            if text:
                _add_body_paragraph(document, text)


# ---------- 附件 ----------


def _attachment_title(heading: str) -> str:
    """去掉「附件」「附件1：」前缀，得到附件标题。"""
    text = _ATTACHMENT_PREFIX_RE.sub("", heading or "", count=1).strip()
    return text or (heading or "").strip()


def _build_attachments(document, attachments: list) -> None:
    """附件另起一页：「附件」三号黑体顶格第一行，标题居中第三行，其后排图片。"""
    for index, attachment in enumerate(attachments, start=1):
        attachment = attachment or {}
        # 第一行：附件标识（多附件带顺序号），顶格
        paragraph = document.add_paragraph()
        _format_paragraph(
            paragraph,
            align=WD_ALIGN_PARAGRAPH.LEFT,
            first_line_indent=Pt(0),
            page_break_before=True,  # 附件另起一页
        )
        label = f"附件{index}" if len(attachments) > 1 else "附件"
        _set_run_font(paragraph.add_run(label), cn_font=FONT_HEITI, size=SIZE_3)

        _add_blank_lines(document, 1)  # 第二行留空

        # 第三行：附件标题居中
        title = _attachment_title(str(attachment.get("heading") or "").strip())
        if title:
            paragraph = document.add_paragraph()
            _format_paragraph(paragraph, align=WD_ALIGN_PARAGRAPH.CENTER, first_line_indent=Pt(0))
            _set_run_font(paragraph.add_run(title), cn_font=FONT_HEITI, size=SIZE_3)

        images = [Path(str(item)) for item in attachment.get("images") or []]
        images = [path for path in images if path.is_file()]
        for position, path in enumerate(images):
            new_page = position > 0 and position % IMAGES_PER_PAGE == 0  # 每页最多 2 张
            paragraph = document.add_paragraph()
            _format_paragraph(
                paragraph,
                align=WD_ALIGN_PARAGRAPH.CENTER,
                first_line_indent=Pt(0),
                exact_spacing=None,  # 固定行距会裁切图片
                space_after=IMAGE_SPACE_AFTER,
                page_break_before=new_page,
            )
            width, height = _fit_image_size(path)
            paragraph.add_run().add_picture(str(path), width=width, height=height)


# ---------- 入口 ----------


def build_document(content: dict, out_path: Path) -> Path:
    """按 GB/T 9704—2012 排版生成 Word 报告，返回写入的文件路径。

    ``content`` 的字段为 title / period_label / cover / sections / attachments /
    source。分三节：封面（不编页码）、目录（不编页码，
    以保证正文页码确从 1 开始）、正文与附件（页码从 1 起，奇偶页页脚不同）。
    """
    content = dict(content or {})
    out_path = Path(out_path)

    document = Document()
    # 基准样式：三号仿宋 + eastAsia，未显式设字体的段落也不会回退
    style = document.styles["Normal"]
    style.font.name = FONT_WEST
    style.font.size = SIZE_3
    style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), FONT_FANGSONG)
    # 奇偶页不同页脚
    document.settings.odd_and_even_pages_header_footer = True

    title_font = _detect_title_font()
    sections = [item for item in (content.get("sections") or []) if isinstance(item, dict)]

    # 第一节：封面（不编页码）
    cover_section = document.sections[0]
    _configure_section(cover_section)
    _suppress_footer(cover_section)
    _build_cover(document, content, title_font)

    # 第二节：目录（不编页码）
    if any(str(item.get("heading") or "").strip() for item in sections):
        toc_section = _add_section(document)
        _suppress_footer(toc_section)
        _build_toc(document, sections)

    # 第三节：正文 + 附件（页码从 1 开始）
    body_section = _add_section(document)
    _enable_page_numbers(body_section)
    _build_body(document, content, title_font)
    _build_attachments(document, content.get("attachments") or [])

    out_path.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(out_path))
    return out_path
