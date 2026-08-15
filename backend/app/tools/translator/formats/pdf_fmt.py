"""معالج PDF — التحويل إلى Word ثم المعالجة كمستند Word.

القرار المعتمَد: المخرج النهائي ملف Word قابل للتعديل. يعني الـ PDF
بيتحوّل لـ DOCX بدري في الخط، وبعد كده بيستخدم **نفس** محرّك الاستخراج
والدمج بتاع Word — مش مسار منفصل. ده بيقلل السطح التقني بشكل كبير
وبيخلي أي تحسين في معالج Word يستفيد منه الـ PDF تلقائيًا.

الـ PDF الممسوح ضوئيًا (صور بدون طبقة نص) بيتكشف هنا ويتعلّم عليه
عشان الخط يوجّهه لمسار الـ OCR بدل ما يطلع ملف فاضي.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# أقل عدد حروف في الصفحة يعتبرها "فيها نص" — تحت كده غالبًا صورة ممسوحة
_TEXT_THRESHOLD_PER_PAGE = 40

# خطوط بترقّم الأشكال بدل ما ترمّزها.
#
# خطوط مجمع الملك فهد للمصحف (QCF_P001 … QCF_P604) فيها خط مستقل لكل
# صفحة من المصحف، والشكل جواه رقمه هو ترتيبه على الصفحة — مالوش أي
# معنى في Unicode. النص المستخرَج منها بيطلع نقاط ترميز متتالية
# (\u202A0xFBDB, 0xFBDC, 0xFBDD…\u202C) شكلها عربي ومعناها صفر.
_GLYPH_INDEXED_FONTS = re.compile(r"^(QCF[_-]?P?\d*|KFGQPC)", re.IGNORECASE)

# أقصر تسلسل نقاط ترميز متتالية نعتبره دليلًا على ترقيم أشكال.
# النص الطبيعي مابيجيش حروفه بترتيب النقاط أبدًا.
_SEQUENTIAL_RUN = 6

# فوق النسبة دي من الصفحات بترميز مكسور، مابنثقش في طبقة النص كلها
_UNRELIABLE_PAGE_RATIO = 0.10

_WHITESPACE = re.compile(r"\s+")


def _longest_sequential_run(text: str) -> int:
    """أطول سلسلة نقاط ترميز متتالية بعد تجاهل المسافات.

    المسافات بتتحط بين الأشكال في المخرجات دي، فلو ماتجاهلناهاش
    السلسلة بتتقطع والفحص بيفوّت المشكلة.
    """
    stripped = _WHITESPACE.sub("", text)
    best = run = 1
    for previous, current in zip(stripped, stripped[1:]):
        run = run + 1 if ord(current) == ord(previous) + 1 else 1
        best = max(best, run)
    return best


def _page_is_unreliable(page) -> bool:
    """هل نص الصفحة دي مرقَّم بالأشكال بدل ما يكون مرمَّزًا؟"""
    for font in page.get_fonts(full=True):
        name = font[3].split("+")[-1]
        if _GLYPH_INDEXED_FONTS.match(name):
            return True
    return _longest_sequential_run(page.get_text()) >= _SEQUENTIAL_RUN


@dataclass
class PdfDiagnosis:
    page_count: int
    char_count: int
    is_scanned: bool
    has_text_layer: bool
    pages_without_text: list[int]
    # صفحات نصها موجود لكن ترميزه مالوش معنى
    unreliable_pages: list[int] = field(default_factory=list)

    @property
    def unreliable_ratio(self) -> float:
        if not self.page_count:
            return 0.0
        return len(self.unreliable_pages) / self.page_count

    @property
    def text_is_unreliable(self) -> bool:
        return self.unreliable_ratio > _UNRELIABLE_PAGE_RATIO

    @property
    def needs_ocr(self) -> bool:
        # مفيش نص، أو فيه نص بس مالوش معنى — الحالتين محتاجين قراءة بصرية
        return self.is_scanned or self.text_is_unreliable


def diagnose(path: Path) -> PdfDiagnosis:
    """فحص الملف قبل التحويل.

    مش بس «فيه نص ولا لأ» — كمان «النص ده معناه صح ولا لأ». ملف فيه
    طبقة نص كاملة ممكن تكون بترقيم أشكال، وساعتها الاستخراج بيطلع
    حروفًا شكلها سليم ومعناها صفر، وده أخطر من الملف الفاضي لأنه
    بيعدّي على أي فحص بيعدّ الحروف بس.
    """
    total_chars = 0
    empty_pages: list[int] = []
    unreliable: list[int] = []

    with fitz.open(str(path)) as document:
        page_count = document.page_count
        for index, page in enumerate(document, start=1):
            text = page.get_text().strip()
            total_chars += len(text)
            if len(text) < _TEXT_THRESHOLD_PER_PAGE:
                empty_pages.append(index)
            elif _page_is_unreliable(page):
                unreliable.append(index)

    has_text = total_chars > 0
    # لو أغلب الصفحات مافيهاش نص → الملف ممسوح ضوئيًا
    is_scanned = page_count > 0 and len(empty_pages) > page_count * 0.6

    diagnosis = PdfDiagnosis(
        page_count=page_count,
        char_count=total_chars,
        is_scanned=is_scanned,
        has_text_layer=has_text,
        pages_without_text=empty_pages,
        unreliable_pages=unreliable,
    )

    if diagnosis.text_is_unreliable:
        logger.warning(
            "%d صفحة من %d ترميزها بترقيم أشكال — هتتقرا بصريًا بدل "
            "طبقة النص",
            len(unreliable),
            page_count,
        )
    return diagnosis


_patched = False


def _patch_pdf2docx_colors() -> None:
    """رقعة توافق بين PyMuPDF 1.25+ و pdf2docx 0.5.8.

    المشكلة: PyMuPDF الحديث بيرجّع ألوان النص كأعداد صحيحة **سالبة**
    (الأسود = -16777216، وهو 0xFF000000 بامتداد إشارة بايت الشفافية).
    و pdf2docx بيحوّلها بـ `hex(srgb)[2:]` اللي بيدّي 'x1000000' للأرقام
    السالبة بدل '1000000'، وبعدين `int(..., 16)` بيقع.

    النتيجة بدون الرقعة: **كل صفحة فيها نص أسود بتتساقط بالكامل** —
    يعني مسار الـ PDF كله معطّل عمليًا.

    الإصلاح: قناع 24 بت. قيم sRGB أصلًا 24 بت، وبايت الشفافية اللي
    بيسبّب السالب مالوش لازمة هنا — فالقناع بيرجّع القيمة الصحيحة.
    """
    global _patched
    if _patched:
        return

    from pdf2docx.common import share
    from pdf2docx.text import TextSpan

    original = share.rgb_component

    def safe_rgb_component(srgb: int):
        return original(srgb & 0xFFFFFF)

    share.rgb_component = safe_rgb_component
    # TextSpan عامل import مباشر للدالة، فلازم نستبدلها عنده كمان
    TextSpan.rgb_component = safe_rgb_component
    _patched = True
    logger.debug("تم تفعيل رقعة توافق ألوان pdf2docx")


def convert_to_docx(source: Path, output: Path) -> Path:
    """تحويل PDF إلى DOCX مع الحفاظ على التخطيط قدر الإمكان."""
    _patch_pdf2docx_colors()
    from pdf2docx import Converter

    output.parent.mkdir(parents=True, exist_ok=True)

    # pdf2docx بيطبع لوجات كتير — بنكتمها عشان تفضل مخرجاتنا نظيفة
    for name in ("pdf2docx", "fitz"):
        logging.getLogger(name).setLevel(logging.ERROR)

    converter = Converter(str(source))
    try:
        converter.convert(str(output))
    finally:
        converter.close()

    if not output.exists():
        raise RuntimeError("فشل تحويل الـ PDF إلى Word")
    return output


def prepare(source: Path, work_dir: Path) -> tuple[Path, str, dict]:
    """تجهيز الـ PDF للمعالجة.

    بيرجّع: (مسار ملف العمل، صيغة العمل، بيانات التشخيص)
    """
    info = diagnose(source)
    meta = {
        "original_format": "pdf",
        "page_count": info.page_count,
        "has_text_layer": info.has_text_layer,
        "is_scanned": info.is_scanned,
        "pages_without_text": info.pages_without_text[:20],
        "unreliable_pages": info.unreliable_pages[:20],
        "unreliable_page_count": len(info.unreliable_pages),
    }

    if info.needs_ocr:
        # إما مفيش نص، وإما فيه نص ترميزه مالوش معنى — الحالتين
        # بيتقروا بصريًا
        meta["needs_ocr"] = True
        meta["ocr_reason"] = (
            "scanned" if info.is_scanned else "unreliable_encoding"
        )
        return source, "pdf", meta

    target = work_dir / f"{source.stem}.converted.docx"
    convert_to_docx(source, target)
    meta["needs_ocr"] = False
    meta["converted_to"] = str(target)
    return target, "docx", meta
