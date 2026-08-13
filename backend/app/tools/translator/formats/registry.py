"""سجلّ الصيغ — نقطة الدخول الموحّدة لكل معالجات الملفات."""
from __future__ import annotations

from pathlib import Path
from types import ModuleType

from app.tools.translator.formats import (
    docx_fmt,
    pdf_fmt,
    plain_fmt,
    pptx_fmt,
    xlsx_fmt,
)
from app.tools.translator.formats.base import ExtractionResult
from app.tools.translator.langs import direction_attrs
from app.tools.translator.formats.textnorm import (
    has_presentation_forms,
    normalize_arabic,
)

# الامتداد → الصيغة الداخلية
_EXTENSION_MAP: dict[str, str] = {
    ".docx": "docx",
    ".docm": "docx",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".pptx": "pptx",
    ".pptm": "pptx",
    ".pdf": "pdf",
    ".txt": "plain",
    ".md": "plain",
    ".markdown": "plain",
    ".csv": "plain",
}

# صيغ Office القديمة — محتاجة تحويل مش متاح على الجهاز حاليًا
_LEGACY = {
    ".doc": "Word 97-2003",
    ".xls": "Excel 97-2003",
    ".ppt": "PowerPoint 97-2003",
    ".rtf": "RTF",
}

_HANDLERS: dict[str, ModuleType] = {
    "docx": docx_fmt,
    "xlsx": xlsx_fmt,
    "pptx": pptx_fmt,
    "plain": plain_fmt,
}


class UnsupportedFormat(Exception):
    pass


def detect_format(filename: str) -> str:
    """تحديد الصيغة من اسم الملف."""
    suffix = Path(filename).suffix.lower()

    if suffix in _EXTENSION_MAP:
        return _EXTENSION_MAP[suffix]

    if suffix in _LEGACY:
        raise UnsupportedFormat(
            f"صيغة {_LEGACY[suffix]} القديمة ({suffix}) مش مدعومة حاليًا. "
            f"افتح الملف في Office واحفظه بالصيغة الحديثة "
            f"({suffix}x) ثم ارفعه مرة تانية."
        )

    raise UnsupportedFormat(f"صيغة غير مدعومة: {suffix or 'بدون امتداد'}")


def prepare(fmt: str, source: Path, work_dir: Path) -> tuple[Path, str, dict]:
    """تجهيز الملف للمعالجة.

    الـ PDF بيتحوّل هنا لـ DOCX فيرجع بصيغة عمل مختلفة عن صيغته الأصلية.
    باقي الصيغ بتتعامل مباشرة.
    """
    if fmt == "pdf":
        return pdf_fmt.prepare(source, work_dir)
    return source, fmt, {}


def extract(fmt: str, path: Path, normalize: bool = False) -> ExtractionResult:
    """استخراج وحدات النص.

    normalize=True بتتفعّل للملفات الجاية من PDF: بترجّع أشكال العرض
    العربية لحروفها الأساسية، وبدونها جودة الترجمة بتنخفض بشكل كبير.
    """
    handler = _HANDLERS.get(fmt)
    if handler is None:
        raise UnsupportedFormat(f"مفيش معالج استخراج للصيغة: {fmt}")

    result = handler.extract(path)

    if normalize:
        affected = 0
        for unit in result.units:
            if has_presentation_forms(unit.text):
                affected += 1
            unit.text = normalize_arabic(unit.text)
        result.meta["normalized_units"] = affected

    return result


def merge(
    fmt: str,
    source: Path,
    output: Path,
    translations: dict[str, str],
    target_lang: str = "en",
) -> None:
    """كتابة الترجمة في نسخة من الملف الأصلي بالاتجاه الصحيح للغة الهدف."""
    handler = _HANDLERS.get(fmt)
    if handler is None:
        raise UnsupportedFormat(f"مفيش معالج دمج للصيغة: {fmt}")

    attrs = direction_attrs(target_lang)
    handler.merge(
        source,
        output,
        translations,
        target_rtl=attrs["rtl"],
        lang_tag=attrs["lang_tag"],
    )


def output_extension(working_fmt: str) -> str:
    """امتداد ملف المخرجات حسب صيغة العمل."""
    return {
        "docx": ".docx",
        "xlsx": ".xlsx",
        "pptx": ".pptx",
        "plain": ".txt",
    }.get(working_fmt, ".out")


def supported_extensions() -> list[str]:
    return sorted(_EXTENSION_MAP)
