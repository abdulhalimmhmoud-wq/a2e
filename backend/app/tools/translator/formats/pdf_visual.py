"""الحفاظ على شكل صفحة الـ PDF مع استبدال نصّها.

المبدأ اللي المشروع كله ماشي عليه إننا **مانبنيش المستند من الأول** —
بننسخ الأصل ونستبدل النص في مكانه. Word و PowerPoint و Excel ماشيين
كده من البداية، والـ PDF الممسوح كان الاستثناء الوحيد: كان بيتقرا
ضوئيًا وبيتبني ملف Word جديد من كتل النص، فكان بيضيّع الشعار والختم
والتوقيع والإطار وكل حاجة مرئية.

الوحدة دي بتدّي الأدوات اللي بتخلي الـ PDF يمشي على نفس المبدأ:

  - `text_spans` بترجّع كل مقطع نص بإحداثياته وخطه وحجمه ولونه.
    ودي **مجانية وفورية**: الـ PDF نفسه شايل المعلومات دي حتى لما
    يكون ترميز الحروف مكسور. يعني الملف اللي ترميزه مكسور محتاج
    قراءة ضوئية للحروف بس، مش للمواضع.

  - `cover_and_write` بتغطّي موضع النص وتكتب مكانه، وسايبة كل حاجة
    تانية في الصفحة زي ما هي.

مفيش أي حاجة هنا مخصوصة بلغة: الأدوات بتشتغل على أي مستند بأي لغة.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# هامش بسيط حوالين الصندوق عشان التغطية ماتسيبش أطراف الحروف القديمة
_COVER_PADDING = 0.6

# أقل حجم خط نقبل ننزل ليه عشان النص المترجَم يدخل في مساحته
_MIN_FONT_SIZE = 5.0


@dataclass
class TextSpan:
    """مقطع نص في صفحة، بموضعه وشكله."""

    text: str
    bbox: tuple[float, float, float, float]
    font: str = ""
    size: float = 11.0
    color: int = 0
    page: int = 0
    # ترتيبه في قراءة الصفحة
    order: int = 0

    @property
    def rect(self) -> fitz.Rect:
        return fitz.Rect(*self.bbox)

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass
class PageGeometry:
    """كل نص الصفحة: بالمقاطع وبالسطور.

    المقطع مش وحدة صالحة للاستبدال: الـ PDF بيقسّم السطر لمقاطع كل ما
    يتغيّر الخط أو الحجم، فبيطلع مقاطع بحرف واحد في صندوق ٥×١٨ نقطة.
    الجملة المترجَمة مستحيل تدخل فيه. الوحدة العملية هي **السطر**.
    """

    number: int
    width: float
    height: float
    spans: list[TextSpan] = field(default_factory=list)
    lines: list[TextSpan] = field(default_factory=list)
    # بتفرّق بين صفحة مليانة وصفحة غلاف
    image_count: int = 0
    drawing_count: int = 0

    @property
    def has_text(self) -> bool:
        return any(span.text.strip() for span in self.spans)


def _color_tuple(value: int) -> tuple[float, float, float]:
    """لون PyMuPDF عدد صحيح — بنحوّله لثلاثية من صفر لواحد."""
    return (
        ((value >> 16) & 0xFF) / 255,
        ((value >> 8) & 0xFF) / 255,
        (value & 0xFF) / 255,
    )


def text_spans(page, page_number: int = 0) -> PageGeometry:
    """كل مقاطع النص في الصفحة بمواضعها وأشكالها.

    بتشتغل حتى لو ترميز الحروف مكسور: المواضع والخطوط والأحجام
    بتيجي من بنية الـ PDF مش من ترميز الحروف.
    """
    geometry = PageGeometry(
        number=page_number,
        width=page.rect.width,
        height=page.rect.height,
        image_count=len(page.get_images(full=True)),
        drawing_count=len(page.get_drawings()),
    )

    data = page.get_text("dict")
    order = line_order = 0
    for block in data.get("blocks", []):
        if block.get("type") != 0:  # 0 = نص، 1 = صورة
            continue
        for line in block.get("lines", []):
            parts: list[TextSpan] = []
            for span in line.get("spans", []):
                item = TextSpan(
                    text=span.get("text", ""),
                    bbox=tuple(span["bbox"]),
                    font=span.get("font", "").split("+")[-1],
                    size=float(span.get("size", 11.0)),
                    color=int(span.get("color", 0)),
                    page=page_number,
                    order=order,
                )
                geometry.spans.append(item)
                parts.append(item)
                order += 1

            merged = _merge_line(parts, page_number, line_order)
            if merged is not None:
                geometry.lines.append(merged)
                line_order += 1

    return geometry


def _merge_line(
    parts: list[TextSpan], page_number: int, order: int
) -> TextSpan | None:
    """دمج مقاطع السطر في وحدة واحدة صالحة للاستبدال.

    الخط والحجم بيتاخدوا من أعرض مقطع — هو اللي بيمثّل شكل السطر،
    والمقاطع الصغيرة عادةً علامات ترقيم أو أرقام.
    """
    usable = [part for part in parts if part.text]
    if not usable:
        return None

    dominant = max(usable, key=lambda part: part.width)
    return TextSpan(
        text="".join(part.text for part in usable),
        bbox=(
            min(part.bbox[0] for part in usable),
            min(part.bbox[1] for part in usable),
            max(part.bbox[2] for part in usable),
            max(part.bbox[3] for part in usable),
        ),
        font=dominant.font,
        size=dominant.size,
        color=dominant.color,
        page=page_number,
        order=order,
    )


def read_geometry(path, pages: list[int] | None = None) -> list[PageGeometry]:
    """قراءة هندسة النص لكل صفحات المستند (أو صفحات محددة)."""
    out: list[PageGeometry] = []
    with fitz.open(str(path)) as document:
        wanted = pages if pages is not None else range(document.page_count)
        for index in wanted:
            if 0 <= index < document.page_count:
                out.append(text_spans(document[index], index))
    return out


def _fit_font_size(
    rect: fitz.Rect, text: str, fontname: str, start: float
) -> float:
    """أكبر حجم خط النص بيدخل بيه في مساحته.

    الترجمة بتطول أو تقصر عن الأصل، والمساحة ثابتة. بنصغّر لحد ما
    يدخل بدل ما نسيبه يتقص.

    القياس بيحصل على صفحة مؤقتة مش على الصفحة الحقيقية: `insert_textbox`
    **بتكتب** حتى لو طلبت منها وضع غير مرئي، فالقياس على الصفحة نفسها
    كان بيسيب نسخة خفية من كل سطر — النص بيطلع مرتين في أي استخراج
    بعد كده.
    """
    scratch = fitz.open()
    try:
        page = scratch.new_page(width=rect.width + 2, height=rect.height + 2)
        box = fitz.Rect(0, 0, rect.width, rect.height)
        size = start
        while size >= _MIN_FONT_SIZE:
            overflow = page.insert_textbox(
                box, text, fontname=fontname, fontsize=size,
                align=fitz.TEXT_ALIGN_LEFT,
            )
            if overflow >= 0:
                return size
            size -= 0.5
        return _MIN_FONT_SIZE
    finally:
        scratch.close()


def cover_and_write(
    page,
    replacements: list[tuple[tuple[float, float, float, float], str]],
    fontname: str = "helv",
    rtl: bool = False,
    fill: tuple[float, float, float] | None = (1, 1, 1),
) -> int:
    """تغطية مواضع النص القديم وكتابة الجديد مكانه.

    كل حاجة تانية في الصفحة — صور، شعارات، أختام، تواقيع، إطارات،
    رسومات متجهة — مابتتلمسش خالص.

    بيرجّع عدد المواضع اللي اتكتبت بنجاح.
    """
    usable = [(bbox, text) for bbox, text in replacements if text.strip()]
    if not usable:
        return 0

    # المرحلة الأولى: حذف النص القديم **فعليًا**.
    #
    # الرسم بمستطيل أبيض فوقه بيخفيه بالعين بس بيسيبه في الملف: ينفع
    # يتحدد وينتسخ، وبيرجع تاني في أي تحويل بعد كده. الحذف بيشيل كائن
    # النص نفسه.
    #
    # القيم الافتراضية هنا مؤذية: PyMuPDF بيمسح بكسلات الصور
    # (images=2) وبيشيل الرسومات المغطّاة (graphics=1) — يعني الشعار
    # والإطار هيروحوا. بنعطّل الاتنين صراحة.
    for bbox, _ in usable:
        rect = fitz.Rect(*bbox)
        page.add_redact_annot(
            fitz.Rect(
                rect.x0 - _COVER_PADDING,
                rect.y0 - _COVER_PADDING,
                rect.x1 + _COVER_PADDING,
                rect.y1 + _COVER_PADDING,
            ),
            fill=fill,
            cross_out=False,
        )

    page.apply_redactions(
        images=fitz.PDF_REDACT_IMAGE_NONE,
        graphics=fitz.PDF_REDACT_LINE_ART_NONE,
        text=fitz.PDF_REDACT_TEXT_REMOVE,
    )

    # المرحلة التانية: كتابة النص الجديد في نفس المواضع
    written = 0
    for bbox, text in usable:
        rect = fitz.Rect(*bbox)

        # المساحة المتاحة أوسع شوية من الأصل لتحمّل فرق طول الترجمة
        target = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + rect.height * 0.4)
        size = _fit_font_size(target, text, fontname, max(rect.height * 0.8, 6))

        overflow = page.insert_textbox(
            target,
            text,
            fontname=fontname,
            fontsize=size,
            align=fitz.TEXT_ALIGN_RIGHT if rtl else fitz.TEXT_ALIGN_LEFT,
        )
        # القيمة السالبة معناها إن النص مادخلش فماتكتبش. العدّاد لازم
        # يعدّ اللي اتكتب فعلًا، مش اللي حاولنا نكتبه.
        if overflow < 0:
            logger.debug("نص مالوش مكان كافٍ في %s", bbox)
            continue
        written += 1
    return written


def page_image(page, dpi: int = 150) -> bytes:
    """صورة الصفحة كما هي — للمستندات الممسوحة اللي مالهاش طبقة نص."""
    from app.tools.translator.ocr import render_page

    return render_page(page, dpi=dpi)
