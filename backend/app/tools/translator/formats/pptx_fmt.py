"""معالج PowerPoint (PPTX) — استخراج ودمج عبر تعديل الـ XML مباشرة.

اللي بنغطّيه:
  الأشكال · الأشكال المجمّعة · الجداول · الرسوم البيانية ·
  **صفحات الملاحظات** (بينساها أغلب الأدوات)

ملاحظة على الروابط: في PowerPoint الرابط بيتخزّن جوّه `a:rPr` نفسه،
يعني بصمة التنسيق بتحافظ عليه تلقائيًا من غير معالجة خاصة — عكس Word.

تحذير التمدّد: النص الإنجليزي بيطول عن العربي بحوالي 15–25%، والشرائح
مساحتها ثابتة. بنطلع تقرير بالأشكال المرشّحة للطفح بعد الترجمة.
"""
from __future__ import annotations

import copy
from pathlib import Path

from lxml import etree

from app.tools.translator.formats.base import (
    ExtractionResult,
    TextUnit,
    parse_tagged_text,
    strip_tags,
    tags_in,
)
from app.tools.translator.formats.ooxml import OoxmlPackage, q
from app.tools.translator.formats.richtext import build_tagged, group_runs, tag_map

_PRESENTATION = "ppt/presentation.xml"

_A_P = q("a", "p")
_A_R = q("a", "r")
_A_T = q("a", "t")
_A_RPR = q("a", "rPr")
_A_PPR = q("a", "pPr")
_A_BR = q("a", "br")
_A_FLD = q("a", "fld")


# ---------------------------------------------------------------------------
# ترتيب الأجزاء
# ---------------------------------------------------------------------------
def _ordered_parts(package: OoxmlPackage) -> list[tuple[str, str, str]]:
    """[(المسار, النوع, الوصف)] بترتيب الشرائح الحقيقي."""
    parts: list[tuple[str, str, str]] = []
    root = package.tree(_PRESENTATION)
    if root is None:
        return parts

    rels = package.rels_for(_PRESENTATION)
    slide_list = root.find(q("p", "sldIdLst"))
    if slide_list is None:
        return parts

    for index, slide_id in enumerate(slide_list.findall(q("p", "sldId")), start=1):
        rid = slide_id.get(q("r", "id"))
        slide_path = rels.get(rid or "")
        if not slide_path:
            continue
        parts.append((slide_path, "slide", f"شريحة {index}"))

        # صفحة الملاحظات المرتبطة بالشريحة
        for target in package.rels_for(slide_path).values():
            if target.startswith("ppt/notesSlides/"):
                parts.append((target, "notes", f"ملاحظات شريحة {index}"))
            elif target.startswith("ppt/charts/"):
                parts.append((target, "chart", f"رسم بياني — شريحة {index}"))

    return parts


def _shape_label(paragraph: etree._Element) -> str:
    """اسم الشكل اللي الفقرة جوّاه — بيساعد المراجع يحدد الموضع."""
    node = paragraph.getparent()
    in_table = False
    while node is not None:
        if node.tag == q("a", "tbl"):
            in_table = True
        if node.tag in (q("p", "sp"), q("p", "graphicFrame"), q("p", "pic")):
            for cnv in node.iter(q("p", "cNvPr")):
                name = cnv.get("name")
                if name:
                    return f"{name} (جدول)" if in_table else name
            break
        node = node.getparent()
    return "جدول" if in_table else "شكل"


# ---------------------------------------------------------------------------
# قراءة الفقرة
# ---------------------------------------------------------------------------
def _paragraph_text(paragraph: etree._Element) -> tuple[str, dict[str, str], bool]:
    """(النص الموسوم، خريطة الوسوم، هل نتخطّاها؟).

    بنتخطّى الفقرات اللي فيها حقول تلقائية (رقم الشريحة/التاريخ) لأن
    محتواها بيتولّد وقت العرض ومش نص ثابت.
    """
    if paragraph.find(_A_FLD) is not None:
        return "", {}, True

    runs = [child for child in paragraph if child.tag == _A_R]
    if not runs:
        return "", {}, True

    groups = group_runs(runs, _A_RPR, _A_T)

    # فواصل الأسطر بتتحوّل لمحرف \n جوّه نص المجموعة السابقة
    has_break = any(child.tag == _A_BR for child in paragraph)
    if has_break:
        rebuilt: list[str] = []
        group_index = 0
        for child in paragraph:
            if child.tag == _A_BR:
                if group_index and rebuilt:
                    groups[group_index - 1].text += "\n"
            elif child.tag == _A_R:
                group_index = next(
                    (i + 1 for i, g in enumerate(groups) if child in g.runs),
                    group_index,
                )
                rebuilt.append("")

    text, placeholders = build_tagged(groups)
    return text, placeholders, not text.strip()


def _write_paragraph(paragraph: etree._Element, target: str) -> None:
    """كتابة النص المترجم في الفقرة مع الحفاظ على التنسيق."""
    runs = [child for child in paragraph if child.tag == _A_R]
    if not runs:
        return

    groups = group_runs(runs, _A_RPR, _A_T)
    mapping = tag_map(groups)
    dominant = max(range(len(groups)), key=lambda i: len(groups[i].text), default=None)

    pieces = parse_tagged_text(target)
    if not set(mapping).issubset(tags_in(target)) or dominant is None:
        # وضع آمن: التنسيق بيتبسّط لكن النص مابيضيعش
        pieces = [(None, strip_tags(target))]

    assignments: list[tuple[int, str]] = []
    for tag, text in pieces:
        if not text:
            continue
        index = mapping.get(tag, dominant) if tag else dominant
        if assignments and assignments[-1][0] == index:
            assignments[-1] = (index, assignments[-1][1] + text)
        else:
            assignments.append((index, text))

    new_children: list[etree._Element] = []
    for index, text in assignments:
        template = groups[index].runs[0]
        # فواصل الأسطر بترجع عناصر a:br حقيقية
        chunks = text.split("\n")
        for position, chunk in enumerate(chunks):
            if position:
                new_children.append(etree.Element(_A_BR))
            if not chunk:
                continue
            run = copy.deepcopy(template)
            for child in list(run):
                if child.tag != _A_RPR:
                    run.remove(child)
            node = etree.SubElement(run, _A_T)
            node.text = chunk
            new_children.append(run)

    # نحافظ على خصائص الفقرة في الأول وخصائص النهاية في الآخر
    head = [c for c in paragraph if c.tag == _A_PPR]
    tail = [c for c in paragraph if c.tag == q("a", "endParaRPr")]

    for child in list(paragraph):
        paragraph.remove(child)
    for child in head:
        paragraph.append(child)
    for child in new_children:
        paragraph.append(child)
    for child in tail:
        paragraph.append(child)


# ---------------------------------------------------------------------------
# الاستخراج
# ---------------------------------------------------------------------------
def extract(path: Path) -> ExtractionResult:
    package = OoxmlPackage.open(path)
    units: list[TextUnit] = []
    order = 0
    slide_count = 0

    for part_path, kind, label in _ordered_parts(package):
        if kind == "slide":
            slide_count += 1
        root = package.tree(part_path)
        if root is None:
            continue

        for index, paragraph in enumerate(root.iter(_A_P)):
            text, placeholders, skip = _paragraph_text(paragraph)
            if skip:
                continue

            location = label if kind != "slide" else f"{label} — {_shape_label(paragraph)}"
            units.append(
                TextUnit(
                    unit_key=f"pptx:{part_path}:p:{index:05d}",
                    text=text,
                    kind="notes" if kind == "notes" else "shape",
                    location=location,
                    order_index=order,
                    placeholders=placeholders,
                    meta={"part": part_path, "slide_label": label},
                )
            )
            order += 1

    return ExtractionResult(
        units=units,
        page_count=slide_count,
        meta={"slides": slide_count},
    )


# ---------------------------------------------------------------------------
# الدمج
# ---------------------------------------------------------------------------
def merge(
    source_path: Path,
    output_path: Path,
    translations: dict[str, str],
    target_rtl: bool = False,
    lang_tag: str = "en-US",  # noqa: ARG001 — PowerPoint بيحدد اللغة على الـ run
) -> None:
    package = OoxmlPackage.open(source_path)

    want_rtl = "1" if target_rtl else "0"
    # المحاذاة لبداية السطر بتنقلب مع الاتجاه
    flip_align = ("r", "l") if target_rtl else ("l", "r")

    for part_path, _kind, _label in _ordered_parts(package):
        root = package.tree(part_path)
        if root is None:
            continue

        touched = False
        for index, paragraph in enumerate(root.iter(_A_P)):
            target = translations.get(f"pptx:{part_path}:p:{index:05d}")
            if target is None:
                continue
            _write_paragraph(paragraph, target)
            touched = True

        for ppr in root.iter(_A_PPR):
            if ppr.get("rtl", "0") != want_rtl:
                ppr.set("rtl", want_rtl)
                touched = True
            # المحاذاة للوسط والضبط مابيتغيروش
            if ppr.get("algn") == flip_align[1]:
                ppr.set("algn", flip_align[0])
                touched = True

        if touched:
            package.mark_dirty(part_path)

    package.save(output_path)


# ---------------------------------------------------------------------------
# تقرير مخاطر طفح النص
# ---------------------------------------------------------------------------
def overflow_report(
    source_units: list[TextUnit], translations: dict[str, str], threshold: float = 1.25
) -> list[dict]:
    """الأشكال اللي النص المترجم فيها أطول بشكل قد يسبب طفحًا.

    مش قياس دقيق للبكسل — مؤشّر عملي يوجّه المراجع لأماكن يتفقّدها.
    """
    report: list[dict] = []
    for unit in source_units:
        target = translations.get(unit.unit_key)
        if not target:
            continue
        source_len = len(strip_tags(unit.text))
        target_len = len(strip_tags(target))
        if source_len >= 20 and target_len > source_len * threshold:
            report.append(
                {
                    "unit_key": unit.unit_key,
                    "location": unit.location,
                    "source_chars": source_len,
                    "target_chars": target_len,
                    "growth": round(target_len / source_len, 2),
                }
            )
    report.sort(key=lambda item: item["growth"], reverse=True)
    return report
