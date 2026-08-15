"""تصدير الترجمة على صفحة الـ PDF الأصلية بدل بناء ملف جديد.

المستند اللي بيتقرا ضوئيًا كان بيتبني من الأول كملف Word من كتل
النص، فكان بيضيّع كل حاجة مش حرف: الشعار والختم والتوقيع والإطار
والزخارف. الوحدة دي بتخلّيه يمشي على نفس قاعدة باقي الصيغ — الأصل
بيتنسخ والنص بس هو اللي بيتغيّر.

قيد حقيقي لازم يتقال: PyMuPDF مابيعملش تشكيل ولا ترتيب ثنائي الاتجاه
للحروف العربية. الكتابة بالعربي في الـ PDF بتطلع أشكال عرض مقلوبة —
وهو بالظبط العطل اللي الأداة موجودة عشان تمنعه. فالمسار ده بيشتغل
للأهداف اللاتينية بس، واللغات اللي بتتكتب من اليمين لليسار بترجع
للتصدير العادي بملف Word.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from app.tools.translator.formats import pdf_visual

logger = logging.getLogger(__name__)

# الخطوط المدمجة في الـ PDF بتغطي اللاتيني بس. الهدف بلغة تانية
# محتاج خط مضمَّن وتشكيل، وده مش متاح هنا.
_LATIN_TARGETS = {
    "en", "fr", "de", "es", "it", "pt", "nl", "tr", "az",
    "pl", "cs", "sv", "da", "no", "fi", "ro", "hu", "id", "ms",
}


@dataclass
class OverlayResult:
    output: Path
    pages_written: int = 0
    units_placed: int = 0
    units_skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def supports(target_lang: str) -> bool:
    """هل ينفع نكتب اللغة دي في الـ PDF مباشرة؟"""
    return target_lang.lower() in _LATIN_TARGETS


def load_layout(path: Path) -> list[dict]:
    """خريطة الصفحات اللي القراءة الضوئية سجّلتها."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data.get("units", [])


def _pages_for_units(
    layout: list[dict], translations: list[str]
) -> dict[int, list[str]]:
    """تجميع الترجمات حسب صفحتها الأصلية.

    الخريطة والوحدات الاتنين بترتيب المستند، فالمطابقة بالترتيب.
    لو الأعداد مختلفة بناخد الأقل ونعلّم الباقي — أحسن من إننا
    نحط ترجمة على صفحة غلط.
    """
    grouped: dict[int, list[str]] = {}
    for entry, text in zip(layout, translations):
        if not text.strip():
            continue
        grouped.setdefault(int(entry.get("page", 1)), []).append(text.strip())
    return grouped


def render(
    source_pdf: Path,
    layout_path: Path,
    translations: list[str],
    output: Path,
    target_lang: str = "en",
) -> OverlayResult:
    """كتابة الترجمة على الصفحات الأصلية.

    `translations` لازم تكون بترتيب وحدات المستند — نفس ترتيب خريطة
    الصفحات.
    """
    result = OverlayResult(output=output)

    if not supports(target_lang):
        result.warnings.append(
            f"اللغة «{target_lang}» محتاجة تشكيل حروف مش متاح في الـ PDF — "
            "التصدير هيرجع لملف Word"
        )
        return result

    layout = load_layout(layout_path)
    if not layout:
        result.warnings.append("مفيش خريطة صفحات — التصدير هيرجع لملف Word")
        return result

    if len(layout) != len(translations):
        result.warnings.append(
            f"عدد الوحدات مش مطابق للخريطة ({len(translations)} مقابل "
            f"{len(layout)}) — اتحطّت المشتركة بس"
        )
        result.units_skipped = abs(len(layout) - len(translations))

    grouped = _pages_for_units(layout, translations)

    document = fitz.open(str(source_pdf))
    try:
        for page_number, texts in sorted(grouped.items()):
            index = page_number - 1
            if not 0 <= index < document.page_count:
                result.units_skipped += len(texts)
                continue

            page = document[index]
            geometry = pdf_visual.text_spans(page, index)

            # الصفحة الممسوحة مالهاش مقاطع نص أصلًا، فمفيش حاجة نغطّيها:
            # بنكتب الترجمة في المساحة المخصصة للنص وسايبين الصورة تحتها.
            lines = [line for line in geometry.lines if line.text.strip()]

            if lines:
                replacements = _match_lines(lines, texts)
            else:
                replacements = _flow_into_page(page, texts)

            placed = pdf_visual.cover_and_write(page, replacements)
            result.units_placed += placed
            result.units_skipped += max(0, len(texts) - placed)
            result.pages_written += 1

        output.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output))
    finally:
        document.close()

    return result


def _match_lines(
    lines: list[pdf_visual.TextSpan], texts: list[str]
) -> list[tuple[tuple[float, float, float, float], str]]:
    """توزيع الترجمات على سطور الصفحة الأصلية.

    الأعداد نادرًا ما بتتطابق: القراءة بتجمّع السطور في فقرات. لما
    الترجمات تكون أقل من السطور بنوزّعها على أول السطور ونفضي الباقي،
    ولما تكون أكتر بندمج الزيادة في آخر سطر عشان ماتضيعش.
    """
    replacements: list[tuple[tuple[float, float, float, float], str]] = []
    if not lines:
        return replacements

    if len(texts) <= len(lines):
        for line, text in zip(lines, texts):
            replacements.append((line.bbox, text))
        # السطور الزيادة بتتفضّى عشان النص الأصلي مايفضلش ظاهر تحتها
        for line in lines[len(texts):]:
            replacements.append((line.bbox, " "))
        return replacements

    head = texts[: len(lines) - 1]
    tail = " ".join(texts[len(lines) - 1:])
    for line, text in zip(lines, head):
        replacements.append((line.bbox, text))
    replacements.append((lines[-1].bbox, tail))
    return replacements


def _flow_into_page(
    page, texts: list[str]
) -> list[tuple[tuple[float, float, float, float], str]]:
    """صفحة ممسوحة بلا مقاطع نص: بنوزّع الترجمة على مساحة الكتابة.

    مافيش مواضع أصلية نلتزم بيها، فبنقسّم المساحة المفيدة بالتساوي.
    الصورة اللي تحت (الشعار والختم) مابتتلمسش لأن التغطية بتحصل
    في حدود الصناديق دي بس.
    """
    rect = page.rect
    margin_x = rect.width * 0.08
    top = rect.height * 0.12
    bottom = rect.height * 0.95
    usable = bottom - top
    if not texts:
        return []

    height = usable / len(texts)
    return [
        (
            (margin_x, top + index * height,
             rect.width - margin_x, top + (index + 1) * height),
            text,
        )
        for index, text in enumerate(texts)
    ]
