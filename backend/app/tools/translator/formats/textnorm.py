"""تطبيع النص العربي المستخرَج من ملفات PDF.

المشكلة: كتير من ملفات PDF العربية بتخزّن الحروف بـ **أشكال العرض**
(Arabic Presentation Forms) بدل الحروف الأساسية. يعني بدل ما تلاقي
"ن" (U+0646) تلاقي "ﻥ" أو "ﻨ" أو "ﻧ" — أربع صور مختلفة لنفس الحرف
حسب موقعه في الكلمة.

ليه ده مهم؟
  - النموذج بيترجم النص ده بجودة أقل بكتير لأنه شكل نادر في التدريب.
  - ذاكرة الترجمة مش هتلاقي تطابق لأن البصمة مختلفة.
  - البحث والاستبدال في شاشة المراجعة مش هيشتغل.

الحل: تطبيع NFKC بيرجّع كل أشكال العرض لحرفها الأساسي — عملية
قياسية وآمنة ومافيهاش فقدان معنى.
"""
from __future__ import annotations

import re
import unicodedata

# نطاقات أشكال العرض العربية في Unicode
_PRESENTATION_FORMS = re.compile(r"[ﭐ-﷿ﹰ-﻿]")

# التطويل (الكشيدة) — محرف زخرفي مالوش معنى لغوي
_TATWEEL = "ـ"

# محارف التحكم في الاتجاه — بتلخبط الترجمة والمقارنة
_BIDI_CONTROLS = re.compile(r"[\u200E\u200F\u202A-\u202E\u2066-\u2069]")


def has_presentation_forms(text: str) -> bool:
    """هل النص فيه أشكال عرض عربية؟ (مؤشّر على PDF مبني بصريًا)"""
    return bool(_PRESENTATION_FORMS.search(text))


def normalize_arabic(text: str, strip_tatweel: bool = True) -> str:
    """إرجاع النص العربي لصورته القياسية.

    - أشكال العرض → الحروف الأساسية (NFKC)
    - إزالة التطويل الزخرفي
    - إزالة محارف التحكم في الاتجاه
    - توحيد المسافات المتعددة
    """
    if not text:
        return text

    # NFKC بيفك اللام-ألف المدمجة (ﻻ) لحرفين وبيرجّع أشكال العرض لأصلها
    normalized = unicodedata.normalize("NFKC", text)
    normalized = _BIDI_CONTROLS.sub("", normalized)

    if strip_tatweel:
        normalized = normalized.replace(_TATWEEL, "")

    # مسافات متعددة داخل السطر (شائعة في استخراج الـ PDF)
    normalized = re.sub(r"[ \t]{2,}", " ", normalized)
    return normalized


def analyze(text: str) -> dict:
    """تقرير تشخيصي عن حالة النص المستخرَج."""
    return {
        "has_presentation_forms": has_presentation_forms(text),
        "has_tatweel": _TATWEEL in text,
        "has_bidi_controls": bool(_BIDI_CONTROLS.search(text)),
        "char_count": len(text),
    }
