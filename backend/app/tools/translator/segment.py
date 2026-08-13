"""مقسّم الجُمل — واعٍ بالعربية والسياق القانوني/العلمي.

ليه مقسّم مخصص بدل واحد جاهز؟
- علامات الترقيم العربية (؟ ؛ ،) مختلفة عن الإنجليزية.
- الترقيم القانوني (المادة 5. البند 3.) بيخدع أي مقسّم ساذج.
- الأرقام العشرية والاختصارات والمراجع العلمية (Fig. 3) بتتكسر غلط.
- لازم نحافظ على وسوم التنسيق سليمة جوّه المقاطع.

الضمان الأساسي:
    "".join(s.text + s.trailing for s in spans) == النص الأصلي
ده اللي بيخلّي إعادة التركيب وقت التصدير مطابقة حرف بحرف.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# نهايات الجُمل: نقطة، استفهام عربي/إنجليزي، تعجب، فاصلة منقوطة عربية
_SENT_END = r"[.؟?!؛]"

# أرقام لاتينية وعربية-هندية
_DIGITS = r"\d٠-٩"

# اختصارات شائعة مايتقسمش بعدها
_ABBREVIATIONS = {
    # إنجليزي
    "mr", "mrs", "ms", "dr", "prof", "st", "vs", "etc", "eg", "ie", "cf",
    "fig", "figs", "no", "vol", "pp", "ed", "eds", "al", "inc", "ltd", "co",
    "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
    "nov", "dec", "approx", "dept", "univ", "art", "sec", "para",
    # عربي
    "د", "أ", "م", "ص", "ط", "هـ",
    "ج", "ق", "ش",
}

# ترقيم قائمة في بداية السطر: "1." أو "أ)" أو "(3)"
_LIST_PREFIX_RE = re.compile(
    r"^\s*(?:\(?\d+\)?|\(?[ء-يa-zA-Z]\)?)[.)\-]\s*"
)

# كلمات دالّة على ترقيم/إحالة
_ENUMERATOR_WORDS = {
    # عربي
    "المادة", "مادة",
    "البند", "بند",
    "الفقرة", "فقرة",
    "الملحق", "ملحق",
    "الفصل", "فصل",
    "الباب", "باب",
    "القسم", "قسم",
    "الجدول", "جدول",
    "الشكل", "شكل",
    "رقم", "المرفق",
    "مرفق", "الشرط",
    "شرط",
    # إنجليزي
    "article", "section", "clause", "item", "figure", "fig", "table",
    "no", "paragraph", "para", "part", "chapter", "annex", "appendix",
    "rule", "exhibit", "schedule",
}

# رأس سطر على هيئة "كلمة ترقيم + رقم/حرف" — مثل "المادة 12" أو "البند (أ)".
# الشرط إنه يبدأ السطر: ده اللي بيفرّق بين الترقيم والإحالة.
#   "المادة 12. يلتزم..."      -> ترقيم في بداية السطر -> مش نهاية جملة
#   "راجع الجدول 3. القيم..."  -> إحالة وسط الكلام     -> نهاية جملة فعلية
_ENUM_HEAD_RE = re.compile(
    r"^[\s\-–—•]*([^\s]+)[\s ]+"
    r"(?:[(\[{]?[" + _DIGITS + r"]+[)\]}]?"
    r"|[(\[{][ء-يa-zA-Z][)\]}])$"
)

_STRIP_CHARS = "()[]{}،,:؛-"


@dataclass
class Span:
    """مقطع: النص نفسه + الفاصل اللي بعده مباشرة."""

    text: str
    trailing: str


def _is_digit(char: str) -> bool:
    """رقم لاتيني (0-9) أو عربي-هندي (٠-٩)."""
    return char.isdigit() or "٠" <= char <= "٩"


def _is_false_break(text: str, pos: int) -> bool:
    """هل علامة الترقيم دي نهاية جملة حقيقية ولا خدعة؟"""
    char = text[pos]

    if char != ".":
        return False

    # 1) رقم عشري أو فاصل آلاف: 3.14 / 150.000
    if 0 < pos < len(text) - 1:
        if _is_digit(text[pos - 1]) and _is_digit(text[pos + 1]):
            return True

    # 2) نقاط متتالية (...)
    if text[pos : pos + 3] == "..." or (pos > 0 and text[pos - 1] == "."):
        return True

    # 3) اختصار معروف قبل النقطة
    before = text[:pos]
    word_match = re.search(r"([^\s.،؛:()\[\]]+)$", before)
    if word_match:
        word = word_match.group(1).lower().strip()
        if word in _ABBREVIATIONS:
            return True
        # حرف مفرد متبوع بنقطة (اختصار اسم: A. Smith)
        if len(word) == 1 and word.isalpha():
            return True

    # حدود السطر الحالي (بدون النقطة نفسها)
    line_start = text.rfind("\n", 0, pos) + 1
    line_head = text[line_start:pos]

    # 4) ترقيم بند في بداية السطر: "1." / "(أ)."
    if _LIST_PREFIX_RE.fullmatch(line_head + ". ") or re.fullmatch(
        r"\s*\(?[" + _DIGITS + r"ء-يa-zA-Z]{1,3}\)?", line_head
    ):
        return True

    # 5) إحالة مرقّمة في بداية السطر: "المادة 12." / "Article 5." / "البند (أ)."
    head_match = _ENUM_HEAD_RE.fullmatch(line_head)
    if head_match:
        word = head_match.group(1).strip(_STRIP_CHARS).lower()
        if word in _ENUMERATOR_WORDS:
            return True

    return False


def split_sentences(text: str, min_len: int = 2) -> list[Span]:
    """تقسيم النص لمقاطع مع تغطية كاملة للنص الأصلي."""
    if not text.strip():
        return [Span(text=text, trailing="")] if text else []

    boundaries: list[int] = []
    i = 0
    n = len(text)

    while i < n:
        char = text[i]

        # فاصل سطر صريح = نهاية مقطع دائمًا
        if char == "\n":
            boundaries.append(i + 1)
            i += 1
            continue

        if re.match(_SENT_END, char):
            if _is_false_break(text, i):
                i += 1
                continue
            # نبتلع علامات الترقيم/الإغلاق المتتالية بعد نهاية الجملة
            j = i + 1
            while j < n and text[j] in ".!?؟؛\"'»)]":
                j += 1
            # لازم يبقى بعدها مسافة أو نهاية النص
            if j >= n or text[j].isspace():
                boundaries.append(j)
                i = j
                continue
        i += 1

    if not boundaries or boundaries[-1] < n:
        boundaries.append(n)

    spans: list[Span] = []
    start = 0
    for end in boundaries:
        raw = text[start:end]
        start = end
        if not raw:
            continue

        if not raw.strip():
            # مسافات خالصة — تنضم لفاصل المقطع السابق
            if spans:
                spans[-1] = Span(spans[-1].text, spans[-1].trailing + raw)
            else:
                spans.append(Span(text="", trailing=raw))
            continue

        body = raw.lstrip()
        leading = raw[: len(raw) - len(body)]
        core = body.rstrip()
        trailing = body[len(core) :]

        if leading:
            if spans:
                # المسافة البادئة تخصّ فاصل المقطع السابق مش نص المقطع ده
                spans[-1] = Span(spans[-1].text, spans[-1].trailing + leading)
            else:
                core = leading + core

        spans.append(Span(text=core, trailing=trailing))

    # دمج المقاطع القصيرة جدًا مع اللي قبلها
    merged: list[Span] = []
    for span in spans:
        if merged and span.text.strip() and len(span.text.strip()) < min_len:
            prev = merged[-1]
            merged[-1] = Span(prev.text + prev.trailing + span.text, span.trailing)
        else:
            merged.append(span)

    return merged or [Span(text=text, trailing="")]


def verify_coverage(original: str, spans: list[Span]) -> bool:
    """تأكيد إن التقسيم مافقدش ولا حرف — يُستخدم في الاختبارات."""
    return "".join(s.text + s.trailing for s in spans) == original
