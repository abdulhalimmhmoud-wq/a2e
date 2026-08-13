"""الأساس المشترك لكل مستخرِجات الصيغ.

الفكرة المحورية: كل قطعة نص في المستند بتتمثّل كـ TextUnit ليها `unit_key`
فريد وثابت — ده العنوان اللي بيرجّعنا لنفس المكان بالظبط وقت التصدير.

شرط الثبات: المشي (traversal) اللي بيولّد الـ unit_key وقت الاستخراج
لازم يكون **مطابق تمامًا** للمشي وقت الدمج. عشان كده كل الدوال هنا
حتمية (deterministic) ومفيش أي اعتماد على ترتيب عشوائي.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

# صيغة وسوم التنسيق الداخلي.
# اخترنا شكل XML لأن النماذج اللغوية بتحافظ عليه بشكل أوثق من أي بديل.
TAG_OPEN = "<g{}>"
TAG_CLOSE = "</g{}>"
TAG_RE = re.compile(r"</?g(\d+)>")

# محارف عربية + أي حرف أبجدي — لتحديد إن كان النص يستحق الترجمة أصلًا
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


@dataclass
class TextUnit:
    """وحدة نص واحدة داخل المستند (فقرة / خلية / فقرة في شكل)."""

    unit_key: str
    text: str
    kind: str = "paragraph"
    location: str = ""
    order_index: int = 0
    # خريطة وسوم التنسيق: {"1": "<w:rPr>...</w:rPr>"}
    placeholders: dict[str, str] = field(default_factory=dict)
    meta: dict = field(default_factory=dict)


@dataclass
class ExtractionResult:
    units: list[TextUnit]
    page_count: int = 0
    meta: dict = field(default_factory=dict)


class Extractor(Protocol):
    """عقد المستخرِج: من ملف إلى وحدات نص."""

    def extract(self, path: Path) -> ExtractionResult: ...


# ---------------------------------------------------------------------------
# دوال مساعدة مشتركة
# ---------------------------------------------------------------------------
def text_hash(text: str) -> str:
    """بصمة النص المصدر — أساس ذاكرة الترجمة والانتشار.

    بنطبّع المسافات فقط، ومش بنغيّر حالة الأحرف ولا نحذف التشكيل،
    لأن الفرق بينهم ممكن يغيّر المعنى في العربية.
    """
    normalized = re.sub(r"\s+", " ", text).strip()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def is_translatable(text: str) -> bool:
    """هل النص ده يستاهل يتبعت للمترجم أصلًا؟

    بنستبعد: الفاضي، الأرقام لوحدها، الرموز، علامات الترقيم، المراجع الرقمية.
    ده بيوفّر تكلفة حقيقية — في ملفات إكسل ممكن ٤٠٪ من الخلايا تبقى أرقام.
    """
    stripped = strip_tags(text).strip()
    if not stripped:
        return False
    # لازم يحتوي على حرف أبجدي واحد على الأقل
    if not _LETTER_RE.search(stripped):
        return False
    # حرف واحد بس (زي "أ" في ترقيم البنود) — نسيبه زي ما هو
    if len(stripped) < 2:
        return False
    return True


def strip_tags(text: str) -> str:
    """إزالة وسوم التنسيق للحصول على النص الظاهر."""
    return TAG_RE.sub("", text)


def tags_in(text: str) -> set[str]:
    """أرقام الوسوم الموجودة في النص — لفحص سلامة التنسيق."""
    return set(TAG_RE.findall(text))


def count_words(text: str) -> int:
    """عدّ كلمات يشتغل صح مع العربية والإنجليزية."""
    return len([w for w in re.split(r"\s+", strip_tags(text).strip()) if w])


def parse_tagged_text(text: str) -> list[tuple[str | None, str]]:
    """تفكيك النص الموسوم إلى قطع (رقم_الوسم, النص).

    مثال:
        "عقد <g1>ملزم</g1> للطرفين"
        → [(None, "عقد "), ("1", "ملزم"), (None, " للطرفين")]

    بنتعامل مع الوسوم المتداخلة بأخذ أعمق وسم مفتوح (آخر واحد في المكدس)،
    لأن التنسيق المتداخل في Word بيتسطّح لتنسيق واحد لكل run.
    """
    pieces: list[tuple[str | None, str]] = []
    stack: list[str] = []
    cursor = 0

    for match in TAG_RE.finditer(text):
        chunk = text[cursor : match.start()]
        if chunk:
            pieces.append((stack[-1] if stack else None, chunk))
        token = match.group(0)
        tag_id = match.group(1)
        if token.startswith("</"):
            # نغلق أعمق ظهور لنفس الوسم — يتحمّل الوسوم غير المتوازنة
            for i in range(len(stack) - 1, -1, -1):
                if stack[i] == tag_id:
                    stack.pop(i)
                    break
        else:
            stack.append(tag_id)
        cursor = match.end()

    tail = text[cursor:]
    if tail:
        pieces.append((stack[-1] if stack else None, tail))

    return pieces
