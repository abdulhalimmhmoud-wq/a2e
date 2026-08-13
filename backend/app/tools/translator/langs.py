"""خصائص اللغات — الاتجاه والكتابة وكثافة التوكن.

كل حاجة في النظام كانت بتفترض عربي→إنجليزي. الملف ده بيجمع
الافتراضات دي في مكان واحد عشان أي زوج لغات يشتغل.
"""
from __future__ import annotations

import re

# لغات تُكتب من اليمين لليسار
RTL_LANGUAGES = {"ar", "he", "fa", "ur", "ps", "sd", "yi"}

LANGUAGE_NAMES = {
    "ar": "Arabic",
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
    "it": "Italian",
    "tr": "Turkish",
    "ru": "Russian",
    "zh": "Chinese",
    "fa": "Persian",
    "he": "Hebrew",
    "ur": "Urdu",
}

LANGUAGE_LABELS_AR = {
    "ar": "العربية",
    "en": "الإنجليزية",
    "fr": "الفرنسية",
    "de": "الألمانية",
    "es": "الإسبانية",
    "it": "الإيطالية",
    "tr": "التركية",
    "ru": "الروسية",
    "zh": "الصينية",
    "fa": "الفارسية",
    "he": "العبرية",
    "ur": "الأردية",
}

# متوسط التوكنز لكل حرف — العربية أكثف بكتير من اللاتينية.
# مقيس تقريبيًا؛ الحاسبة بتستخدمه للتقدير المسبق فقط، والتكلفة
# الفعلية بتتسجّل من ردود الـ API.
TOKENS_PER_CHAR = {
    "ar": 0.42,
    "fa": 0.42,
    "ur": 0.42,
    "he": 0.40,
    "ru": 0.35,
    "zh": 0.70,
    "en": 0.25,
    "fr": 0.28,
    "de": 0.30,
    "es": 0.28,
    "it": 0.28,
    "tr": 0.32,
}

# نطاقات المحارف لتحديد كتابة النص
_SCRIPT_RANGES = {
    "arabic": [("؀", "ۿ"), ("ݐ", "ݿ"), ("ﭐ", "﷿"),
               ("ﹰ", "﻿")],
    "hebrew": [("֐", "׿")],
    "cyrillic": [("Ѐ", "ӿ")],
    "cjk": [("一", "鿿"), ("぀", "ヿ")],
    "latin": [("a", "z"), ("A", "Z"), ("À", "ɏ")],
}

# كتابة كل لغة — بنستخدمها للتأكد إن الترجمة فعلًا اتغيّرت كتابتها
LANGUAGE_SCRIPT = {
    "ar": "arabic", "fa": "arabic", "ur": "arabic",
    "he": "hebrew",
    "ru": "cyrillic",
    "zh": "cjk",
    "en": "latin", "fr": "latin", "de": "latin",
    "es": "latin", "it": "latin", "tr": "latin",
}

_WORD_RE = re.compile(r"[^\W\d_]", re.UNICODE)


def is_rtl(lang: str) -> bool:
    """هل اللغة دي بتتكتب من اليمين لليسار؟"""
    return lang.split("-")[0].lower() in RTL_LANGUAGES


def language_name(lang: str) -> str:
    """الاسم الإنجليزي للغة — بيتحط في تعليمات النموذج."""
    return LANGUAGE_NAMES.get(lang.split("-")[0].lower(), lang)


def language_label(lang: str) -> str:
    """الاسم العربي للعرض في الواجهة."""
    return LANGUAGE_LABELS_AR.get(lang.split("-")[0].lower(), lang)


def tokens_per_char(lang: str) -> float:
    return TOKENS_PER_CHAR.get(lang.split("-")[0].lower(), 0.30)


def script_of(lang: str) -> str:
    return LANGUAGE_SCRIPT.get(lang.split("-")[0].lower(), "latin")


def script_ratio(text: str, script: str) -> float:
    """نسبة حروف الكتابة دي من إجمالي الحروف في النص.

    بنتجاهل الأرقام والرموز لأنها مشتركة بين كل الكتابات ومش بتفرّق.
    """
    ranges = _SCRIPT_RANGES.get(script)
    if not ranges:
        return 0.0

    letters = [c for c in text if _WORD_RE.match(c)]
    if not letters:
        return 0.0

    matched = sum(
        1 for c in letters if any(low <= c <= high for low, high in ranges)
    )
    return matched / len(letters)


def direction_attrs(lang: str) -> dict:
    """قيم الاتجاه الجاهزة لكل صيغة ملف."""
    rtl = is_rtl(lang)
    return {
        "rtl": rtl,
        # Word: w:jc — بداية السطر في المستند
        "align_start": "right" if rtl else "left",
        "align_end": "left" if rtl else "right",
        # Excel: sheetView@rightToLeft
        "xlsx_rtl": "1" if rtl else "0",
        # Excel: alignment@readingOrder (1 = يسار→يمين، 2 = يمين→يسار)
        "reading_order": "2" if rtl else "1",
        # PowerPoint: a:pPr@rtl و @algn
        "pptx_rtl": "1" if rtl else "0",
        "pptx_align": "r" if rtl else "l",
        # Word: w:lang@val
        "lang_tag": {"ar": "ar-SA", "en": "en-US", "fr": "fr-FR",
                     "de": "de-DE", "es": "es-ES"}.get(
            lang.split("-")[0].lower(), "en-US"
        ),
    }
