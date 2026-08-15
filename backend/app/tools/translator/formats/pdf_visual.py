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
from pathlib import Path

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
    rect: fitz.Rect,
    text: str,
    fontname: str,
    start: float,
    fontfile: str | None = None,
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
                box, text, fontname=fontname, fontfile=fontfile, fontsize=size,
                align=fitz.TEXT_ALIGN_LEFT,
            )
            if overflow >= 0:
                return size
            size -= 0.5
        return _MIN_FONT_SIZE
    finally:
        scratch.close()


_render_cache: dict[str, tuple[str, str | None] | None] = {}

# الخطوط بالترتيب: المدمج الأول لأنه مضمون الوجود وأخف، وبعده خطوط
# النظام اللي تغطيتها أوسع. القايمة دي **مش** قايمة لغات — إضافة خط
# هنا بتوسّع التغطية تلقائيًا لأي لغة يشيلها، من غير ما حد يحدد أنهي
# لغات بقت مدعومة.
_FONT_CANDIDATES: list[tuple[str, str | None]] = [
    ("helv", None),
    ("arial", r"C:\Windows\Fonts\arial.ttf"),
    ("segoeui", r"C:\Windows\Fonts\segoeui.ttf"),
    ("dejavu", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ("noto", "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf"),
]


def _renders_with(sample: str, fontname: str, fontfile: str | None) -> bool:
    """تجربة واحدة: نكتب ونستخرج ونقارن."""
    if fontfile and not Path(fontfile).exists():
        return False
    scratch = fitz.open()
    try:
        page = scratch.new_page(width=600, height=200)
        overflow = page.insert_textbox(
            fitz.Rect(5, 5, 595, 195), sample,
            fontname=fontname, fontfile=fontfile, fontsize=9,
        )
        got = " ".join(page.get_text().split())
        # الخط اللي مالوش شكل للحرف بيرمي «؟»، واللي محتاج تشكيل
        # بيرجّع الحروف بأشكال عرض مقلوبة — الحالتين مش هيطابقوا الأصل
        return overflow >= 0 and got == sample
    except Exception:  # noqa: BLE001
        return False
    finally:
        scratch.close()


def pick_font(text: str) -> tuple[str, str | None] | None:
    """أول خط يكتب النص ده ويرجّعه سليم — أو None لو مفيش.

    القياس بدل القايمة. البديل كان قايمة لغات مسموحة مكتوبة بالإيد،
    وهي بتغلط في الاتجاهين: بترفض لغة كانت هتشتغل، وبتقبل لغة الخط
    مش شايلها فتطلع ناقصة بصمت. (القايمة القديمة كانت بتقبل
    الأذربيجاني، والقياس أثبت إن الخط الأساسي مش شايل حروفه.)

    السؤال الحقيقي مش عن اللغة — هو عن قدرة الخط على المحارف، وده
    بيتحدد بتجربة. أي لغة تدخل المشروع بعد كده بتتحكم بنفس القاعدة.
    """
    sample = " ".join(text.split())[:120]
    if not sample:
        return _FONT_CANDIDATES[0]

    # المفتاح على مجموعة الكتابات مش على النص نفسه: نتيجة الخط واحدة
    # لكل نص من نفس الكتابة
    key = "".join(sorted({_script_of(char) for char in sample}))
    if key in _render_cache:
        return _render_cache[key]

    chosen = None
    for fontname, fontfile in _FONT_CANDIDATES:
        if _renders_with(sample, fontname, fontfile):
            chosen = (fontname, fontfile)
            break

    _render_cache[key] = chosen
    return chosen


def can_render(text: str) -> bool:
    """هل فيه خط متاح يكتب النص ده سليم؟"""
    return pick_font(text) is not None


def _script_of(char: str) -> str:
    """تصنيف خشن للمحرف — كافي لتجميع نتائج الاختبار."""
    code = ord(char)
    if code < 0x0250:
        return "latin"
    if 0x0370 <= code <= 0x03FF:
        return "greek"
    if 0x0400 <= code <= 0x04FF:
        return "cyrillic"
    if 0x0590 <= code <= 0x05FF:
        return "hebrew"
    if 0x0600 <= code <= 0x06FF or 0xFB50 <= code <= 0xFEFF:
        return "arabic"
    if 0x0900 <= code <= 0x097F:
        return "devanagari"
    if 0x4E00 <= code <= 0x9FFF:
        return "han"
    return "other"


def uniform_size(
    replacements: list[tuple[tuple[float, float, float, float], str]],
    fontname: str = "helv",
    ceiling: float = 14.0,
    fontfile: str | None = None,
) -> float:
    """حجم خط واحد يدخل بيه **كل** النص في مساحاته.

    الاشتقاق من ارتفاع الصندوق لوحده بيدّي إخراجًا عشوائيًا: سطر من
    كلمتين في صندوق عالي بيطلع بخط ضخم، وفقرة كاملة في صندوق قصير
    بتطلع مجهرية. الصفحة الواحدة المفروض يكون ليها حجم نص أساسي واحد.
    """
    size = ceiling
    for bbox, text in replacements:
        if not text.strip():
            continue
        rect = fitz.Rect(*bbox)
        size = min(size, _fit_font_size(rect, text, fontname, size, fontfile))
        if size <= _MIN_FONT_SIZE:
            break
    return max(size, _MIN_FONT_SIZE)


def cover_and_write(
    page,
    replacements: list[tuple[tuple[float, float, float, float], str]],
    fontname: str = "helv",
    rtl: bool = False,
    fill: tuple[float, float, float] | None = (1, 1, 1),
    font_size: float | None = None,
    fontfile: str | None = None,
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

        # التمدد خارج الصندوق بيخلي النص يركب على اللي بعده. بنسمح
        # بهامش صغير بس لتحمّل فرق طول الترجمة.
        target = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y1 + rect.height * 0.1)

        if font_size is not None:
            # حجم موحّد للصفحة كلها، وبنصغّره لو مادخلش في صندوق بعينه
            size = _fit_font_size(target, text, fontname, font_size, fontfile)
        else:
            size = _fit_font_size(
                target, text, fontname, max(rect.height * 0.8, 6), fontfile
            )

        overflow = page.insert_textbox(
            target,
            text,
            fontname=fontname,
            fontfile=fontfile,
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
