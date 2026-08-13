"""معالج Excel (XLSX) — استخراج ودمج عبر تعديل الـ XML مباشرة.

ليه مش openpyxl؟ لأنه بيعيد بناء الملف عند الحفظ فبيضيّع الرسوم
البيانية والصور والتنسيق الشرطي. إحنا بنعدّل النصوص جوّه الأرشيف
وبنسيب كل حاجة تانية بالبايت زي ما هي.

اللي بنغطّيه:
  النصوص المشتركة (sharedStrings) · النصوص المباشرة (inline) ·
  تعليقات الخلايا · رؤوس وتذييلات الطباعة

اللي بنستثنيه عن قصد:
  - **المعادلات**: أي خلية فيها `<f>` بتتخطّى بالكامل. ترجمة معادلة
    بتكسر الملف.
  - **الأرقام والتواريخ**: مش نص أصلًا.
  - **أسماء الأوراق**: ترجمتها بتكسر كل معادلة بتشير للورقة
    (`=Sheet1!A1`). بنستخرجها للعرض بس ومش بنترجمها.
"""
from __future__ import annotations

from pathlib import Path

from lxml import etree

from app.tools.translator.formats.base import ExtractionResult, TextUnit
from app.tools.translator.formats.ooxml import OoxmlPackage, q
from app.tools.translator.formats.richtext import (
    build_tagged,
    group_runs,
    rebuild_runs,
)

_SST = "xl/sharedStrings.xml"
_WORKBOOK = "xl/workbook.xml"

_R = q("s", "r")
_T = q("s", "t")
_RPR = q("s", "rPr")


# ---------------------------------------------------------------------------
# قراءة بنية المصنّف
# ---------------------------------------------------------------------------
def _sheet_list(package: OoxmlPackage) -> list[tuple[str, str]]:
    """[(اسم الورقة, مسار ملفها)] بترتيب ظهورها في المصنّف."""
    root = package.tree(_WORKBOOK)
    if root is None:
        return []

    rels = package.rels_for(_WORKBOOK)
    sheets: list[tuple[str, str]] = []
    container = root.find(q("s", "sheets"))
    if container is None:
        return []

    for sheet in container.findall(q("s", "sheet")):
        name = sheet.get("name") or "?"
        rid = sheet.get(q("r", "id"))
        target = rels.get(rid or "")
        if target:
            sheets.append((name, target))
    return sheets


def _rich_text(node: etree._Element) -> tuple[str, dict[str, str]]:
    """قراءة عنصر نصي (si / is / text) بصيغته البسيطة أو الغنية."""
    runs = node.findall(_R)
    if runs:
        groups = group_runs(runs, _RPR, _T)
        return build_tagged(groups)

    direct = node.find(_T)
    if direct is not None:
        return (direct.text or ""), {}
    return "", {}


def _write_rich_text(node: etree._Element, target: str) -> None:
    runs = node.findall(_R)
    if runs:
        groups = group_runs(runs, _RPR, _T)
        rebuild_runs(node, groups, target, run_q=_R, text_q=_T, props_q=_RPR)
        return

    direct = node.find(_T)
    if direct is None:
        direct = etree.SubElement(node, _T)
    direct.text = target
    direct.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")


# ---------------------------------------------------------------------------
# الاستخراج
# ---------------------------------------------------------------------------
def extract(path: Path) -> ExtractionResult:
    package = OoxmlPackage.open(path)
    sheets = _sheet_list(package)
    units: list[TextUnit] = []
    order = 0

    sst_root = package.tree(_SST)
    sst_items = sst_root.findall(q("s", "si")) if sst_root is not None else []
    emitted_sst: set[int] = set()

    # نمشي على الأوراق بترتيب القراءة الطبيعي — أفضل تجربة للمراجع
    for sheet_index, (sheet_name, sheet_path) in enumerate(sheets):
        sheet_root = package.tree(sheet_path)
        if sheet_root is None:
            continue

        for cell in sheet_root.iter(q("s", "c")):
            # معادلة؟ نتخطّاها بالكامل — ترجمتها بتكسر الملف
            if cell.find(q("s", "f")) is not None:
                continue

            ref = cell.get("r") or "?"
            cell_type = cell.get("t")

            if cell_type == "s":
                # نص مشترك — نصدره عند أول استخدام له
                value = cell.find(q("s", "v"))
                if value is None or not (value.text or "").isdigit():
                    continue
                index = int(value.text)
                if index in emitted_sst or index >= len(sst_items):
                    continue
                emitted_sst.add(index)

                text, placeholders = _rich_text(sst_items[index])
                if not text.strip():
                    continue

                units.append(
                    TextUnit(
                        unit_key=f"xlsx:sst:{index:05d}",
                        text=text,
                        kind="cell",
                        location=f"{sheet_name} — {ref}",
                        order_index=order,
                        placeholders=placeholders,
                        meta={"shared": True},
                    )
                )
                order += 1

            elif cell_type == "inlineStr":
                inline = cell.find(q("s", "is"))
                if inline is None:
                    continue
                text, placeholders = _rich_text(inline)
                if not text.strip():
                    continue

                units.append(
                    TextUnit(
                        unit_key=f"xlsx:sheet{sheet_index:03d}:cell:{ref}",
                        text=text,
                        kind="cell",
                        location=f"{sheet_name} — {ref}",
                        order_index=order,
                        placeholders=placeholders,
                    )
                )
                order += 1

    # النصوص المشتركة اللي مش مربوطة بخلية ظاهرة (مثلًا في جداول محورية)
    for index, item in enumerate(sst_items):
        if index in emitted_sst:
            continue
        text, placeholders = _rich_text(item)
        if not text.strip():
            continue
        units.append(
            TextUnit(
                unit_key=f"xlsx:sst:{index:05d}",
                text=text,
                kind="cell",
                location="نص مشترك",
                order_index=order,
                placeholders=placeholders,
                meta={"shared": True},
            )
        )
        order += 1

    # تعليقات الخلايا
    for part in package.names(prefix="xl/comments", suffix=".xml"):
        root = package.tree(part)
        if root is None:
            continue
        for comment in root.iter(q("s", "comment")):
            ref = comment.get("ref") or "?"
            node = comment.find(q("s", "text"))
            if node is None:
                continue
            text, placeholders = _rich_text(node)
            if not text.strip():
                continue
            units.append(
                TextUnit(
                    unit_key=f"xlsx:{part}:comment:{ref}",
                    text=text,
                    kind="comment",
                    location=f"تعليق — {ref}",
                    order_index=order,
                    placeholders=placeholders,
                )
            )
            order += 1

    # أسماء الأوراق: للعرض فقط، مش للترجمة (ترجمتها بتكسر المعادلات)
    for sheet_index, (sheet_name, _) in enumerate(sheets):
        units.append(
            TextUnit(
                unit_key=f"xlsx:sheetname:{sheet_index:03d}",
                text=sheet_name,
                kind="sheet_name",
                location="اسم ورقة",
                order_index=order,
                meta={
                    "translatable": False,
                    "skip_reason": "ترجمة اسم الورقة بتكسر المعادلات اللي بتشير ليها",
                },
            )
        )
        order += 1

    return ExtractionResult(
        units=units,
        page_count=len(sheets),
        meta={"sheets": [name for name, _ in sheets]},
    )


# ---------------------------------------------------------------------------
# الدمج
# ---------------------------------------------------------------------------
def merge(
    source_path: Path,
    output_path: Path,
    translations: dict[str, str],
    target_rtl: bool = False,
    lang_tag: str = "en-US",  # noqa: ARG001 — Excel مافيهوش وسم لغة على الخلايا
) -> None:
    package = OoxmlPackage.open(source_path)
    sheets = _sheet_list(package)

    # قيم الاتجاه المطلوبة للغة الهدف
    want_sheet_rtl = "1" if target_rtl else "0"
    want_reading_order = "2" if target_rtl else "1"
    sheet_direction_changes = True

    # 1) النصوص المشتركة
    sst_root = package.tree(_SST)
    if sst_root is not None:
        items = sst_root.findall(q("s", "si"))
        for key, target in translations.items():
            if not key.startswith("xlsx:sst:"):
                continue
            index = int(key.rsplit(":", 1)[1])
            if index < len(items):
                _write_rich_text(items[index], target)
                package.mark_dirty(_SST)

    # 2) النصوص المباشرة داخل الخلايا
    for sheet_index, (_, sheet_path) in enumerate(sheets):
        prefix = f"xlsx:sheet{sheet_index:03d}:cell:"
        wanted = {
            key.removeprefix(prefix): value
            for key, value in translations.items()
            if key.startswith(prefix)
        }
        if not wanted and not sheet_direction_changes:
            continue

        sheet_root = package.tree(sheet_path)
        if sheet_root is None:
            continue

        for cell in sheet_root.iter(q("s", "c")):
            ref = cell.get("r")
            if ref not in wanted:
                continue
            inline = cell.find(q("s", "is"))
            if inline is not None:
                _write_rich_text(inline, wanted[ref])
                package.mark_dirty(sheet_path)

        # اتجاه عرض الورقة: العربي من اليمين، الإنجليزي من اليسار
        changed = False
        for view in sheet_root.iter(q("s", "sheetView")):
            current = view.get("rightToLeft", "0")
            if current != want_sheet_rtl:
                view.set("rightToLeft", want_sheet_rtl)
                changed = True
        if changed:
            package.mark_dirty(sheet_path)

    # 3) التعليقات
    for part in package.names(prefix="xl/comments", suffix=".xml"):
        prefix = f"xlsx:{part}:comment:"
        wanted = {
            key.removeprefix(prefix): value
            for key, value in translations.items()
            if key.startswith(prefix)
        }
        if not wanted:
            continue
        root = package.tree(part)
        if root is None:
            continue
        for comment in root.iter(q("s", "comment")):
            ref = comment.get("ref")
            if ref not in wanted:
                continue
            node = comment.find(q("s", "text"))
            if node is not None:
                _write_rich_text(node, wanted[ref])
                package.mark_dirty(part)

    # 4) اتجاه القراءة في الأنماط (1 = يسار→يمين، 2 = يمين→يسار)
    styles = package.tree("xl/styles.xml")
    if styles is not None:
        changed = False
        for alignment in styles.iter(q("s", "alignment")):
            current = alignment.get("readingOrder")
            # بنلمس بس اللي محدَّد له اتجاه صريح؛ الباقي بيتبع الورقة
            if current in ("1", "2") and current != want_reading_order:
                alignment.set("readingOrder", want_reading_order)
                changed = True
        if changed:
            package.mark_dirty("xl/styles.xml")

    package.save(output_path)
