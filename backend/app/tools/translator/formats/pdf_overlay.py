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

# نسبة الوحدات اللي ممكن نصّها ما يطابقش الخريطة قبل ما نلغي المسار.
# فوقها معناها إن ترتيب الوحدات اتغيّر، وساعتها الترجمة هتتحط على
# صفحات غلط — والمستند الغلط أسوأ من المستند العادي.
_MAX_DRIFT = 0.20


@dataclass
class OverlayResult:
    output: Path
    pages_written: int = 0
    units_placed: int = 0
    units_skipped: int = 0
    warnings: list[str] = field(default_factory=list)


def supports(sample_text: str) -> bool:
    """هل ينفع نكتب النص ده في الـ PDF ونرجّعه سليم؟

    الفحص على **النص نفسه** مش على اسم اللغة. لغة الهدف اسم؛ اللي
    بيفرق هو محارف النص وقدرة الخط عليها. كده أي لغة جديدة تتحكم
    بنفس القاعدة من غير ما حد يضيفها لقائمة.
    """
    return pdf_visual.can_render(sample_text)


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


def drift(layout: list[dict], sources: list[str]) -> float:
    """نسبة الوحدات اللي نصّها المصدري مش مطابق للخريطة.

    الخريطة والوحدات بيتبنوا من نفس الملف بترتيب المستند، فالمفروض
    يتطابقوا واحدة بواحدة. لو الترتيب اتغيّر لأي سبب — تغيير في
    مولّد الملف أو في قارئه — الترجمة هتتحط على صفحات غلط **من غير
    ما حد ياخد باله**. الفحص ده هو اللي بيمنع ده.
    """
    if not sources:
        return 0.0

    mismatched = 0
    for entry, source in zip(layout, sources):
        expected = " ".join(str(entry.get("text", "")).split())
        actual = " ".join(source.split())
        if not expected or not actual:
            continue
        # المقارنة على البداية: الوحدة ممكن تتقسّم لجمل عند التقطيع
        head = min(len(expected), len(actual), 40)
        if expected[:head] != actual[:head]:
            mismatched += 1
    return mismatched / len(sources)


def render(
    source_pdf: Path,
    layout_path: Path,
    translations: list[str],
    output: Path,
    target_lang: str = "en",
    sources: list[str] | None = None,
) -> OverlayResult:
    """كتابة الترجمة على الصفحات الأصلية.

    `translations` لازم تكون بترتيب وحدات المستند — نفس ترتيب خريطة
    الصفحات.
    """
    result = OverlayResult(output=output)

    sample = " ".join(text for text in translations[:12] if text.strip())
    font = pdf_visual.pick_font(sample)
    if font is None:
        result.warnings.append(
            f"مفيش خط متاح يكتب النص ده سليم في الـ PDF (هدف: "
            f"{target_lang}) — التصدير هيرجع لملف Word"
        )
        return result
    fontname, fontfile = font

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

    # الخريطة بتربط الوحدة بصفحتها بالترتيب. لو الترتيب انزاح، كل
    # ترجمة بعد نقطة الانزياح بتروح صفحة غلط بصمت — فبنتأكد الأول.
    if sources is not None:
        ratio = drift(layout, sources)
        if ratio > _MAX_DRIFT:
            result.warnings.append(
                f"ترتيب الوحدات مش مطابق للخريطة ({ratio:.0%} مختلفة) — "
                "التصدير هيرجع لملف Word بدل ما يحط الترجمة في صفحات غلط"
            )
            return result

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
                # صفحة ممسوحة: المواضع بتتكشف بصريًا وبتتجمّع في كتل.
                # التوزيع التقديري آخر حل مش أول حل.
                blocks = _detected_blocks(page)
                replacements = (
                    _match_boxes(blocks, texts) if blocks
                    else _flow_into_page(page, texts)
                )

            # حجم واحد للصفحة كلها. من غيره كل صندوق بيحسب حجمه لوحده
            # فالصفحة بتطلع بخطوط متضاربة — عنوان ضخم جنب فقرة مجهرية.
            size = pdf_visual.uniform_size(
                replacements, fontname=fontname, fontfile=fontfile
            )
            placed = pdf_visual.cover_and_write(
                page, replacements,
                fontname=fontname, fontfile=fontfile, font_size=size,
            )
            result.units_placed += placed
            result.units_skipped += max(0, len(texts) - placed)
            result.pages_written += 1

        output.parent.mkdir(parents=True, exist_ok=True)
        document.save(str(output))
    finally:
        document.close()

    return result


def _detected_blocks(page) -> list[tuple[float, float, float, float]]:
    """كتل النص في صفحة ممسوحة، بالكشف البصري.

    الكشف بيرجّع سطورًا مفردة؛ الدمج بيحوّلها لكتل بحجم الفقرة. من
    غير الدمج، الحجم الموحّد للصفحة بيتحدد بأصغر سطر والصفحة كلها
    بتطلع بخط مجهري.
    """
    from app.tools.translator.formats import line_detect

    try:
        image = pdf_visual.page_image(page)
    except Exception as exc:  # noqa: BLE001
        logger.warning("رسم الصفحة للكشف فشل: %s", exc)
        return []

    boxes = line_detect.detect_lines(image, page.rect.width, page.rect.height)
    if not boxes:
        return []

    blocks = line_detect.merge_lines(boxes)
    logger.info("كشف بصري: %d سطر → %d كتلة", len(boxes), len(blocks))
    return blocks


def _match_boxes(
    boxes: list[tuple[float, float, float, float]], texts: list[str]
) -> list[tuple[tuple[float, float, float, float], str]]:
    """توزيع الترجمات على مواضع مكتشَفة.

    الكشف بيرجّع سطورًا، والقراءة بترجّع فقرات — فالأعداد مختلفة
    بطبيعتها. بندمج السطور المتلاصقة في كتل بعدد الترجمات عشان كل
    ترجمة تاخد مساحة متصلة بدل ما تتحشر في سطر واحد.
    """
    if not boxes or not texts:
        return []

    if len(texts) >= len(boxes):
        return _match_lines(
            [pdf_visual.TextSpan(text="x", bbox=box) for box in boxes], texts
        )

    # كل ترجمة بتاخد نصيبها من السطور، وصندوقها اتحاد صناديقهم
    per = len(boxes) / len(texts)
    replacements: list[tuple[tuple[float, float, float, float], str]] = []
    for index, text in enumerate(texts):
        chunk = boxes[round(index * per):round((index + 1) * per)] or [boxes[-1]]
        replacements.append((
            (
                min(b[0] for b in chunk),
                min(b[1] for b in chunk),
                max(b[2] for b in chunk),
                max(b[3] for b in chunk),
            ),
            text,
        ))
    return replacements


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

    التقسيم بالتساوي بيدّي إخراجًا مشوَّهًا: سطر «SUMMONS» بياخد نفس
    ارتفاع فقرة من أربع أسطر، فيطلع بخط ضخم والفقرة تطلع مجهرية
    وتفيض على اللي بعدها. الارتفاع هنا بيتوزّع **بنسبة طول النص**،
    فكل كتلة بتاخد قد ما تحتاج.

    الصورة اللي تحت (الشعار والختم) مابتتلمسش: التغطية بتحصل في حدود
    الصناديق دي بس.
    """
    if not texts:
        return []

    rect = page.rect
    margin_x = rect.width * 0.08
    top = rect.height * 0.12
    usable = rect.height * 0.95 - top
    width = rect.width - 2 * margin_x

    # سطر قصير محتاج سطرًا واحدًا مهما قصر، والفقرة محتاجة بنسبة حروفها
    weights = [max(1.0, len(text) / 60) for text in texts]
    total = sum(weights)

    boxes: list[tuple[tuple[float, float, float, float], str]] = []
    cursor = top
    for text, weight in zip(texts, weights):
        height = usable * weight / total
        boxes.append(
            ((margin_x, cursor, margin_x + width, cursor + height), text)
        )
        cursor += height
    return boxes
