"""كشف الآيات القرآنية والأحاديث النبوية داخل النص.

ليه الملف ده موجود؟
  آية قرآنية مش نص عادي يتترجم. الترجمات المعتمدة للقرآن اتعملت
  بمراجعة علمية، والنموذج مهما كان كويس بيطلّع صياغة جديدة كل مرة —
  وده غير مقبول في مستند رسمي أو بحث شرعي. نفس الكلام على الحديث.

فالسياسة هنا: **مانترجمش، نكشف ونقفل**.
  - اللي إحنا متأكدين منه بيتقفل وبيتحوّل لمراجع بشري ياخد الترجمة
    المعتمدة ويحطها بنفسه.
  - اللي إحنا شاكّين فيه بيتعلّم بس من غير قفل، عشان مانوقّفش الشغل
    على شك.

الكشف بيشتغل على كل المستندات مش الدينية بس — الآيات بتظهر في عقود
المعاملات الإسلامية وقوانين الأحوال الشخصية والأبحاث برضه.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# محارف دالّة
# ---------------------------------------------------------------------------

# الأقواس المزخرفة — بتتحط حوالين الآيات تقريبًا حصريًا
_ORNATE_OPEN = "﴿"   # ﴿
_ORNATE_CLOSE = "﴾"  # ﴾

# نهاية الآية ۝ ورمز البسملة المدمج ﷽
_END_OF_AYAH = "۝"
_BISMILLAH_LIGATURE = "﷽"

# علامات الضبط القرآني (سجدة، وقف لازم، ...) — نادرة جدًا خارج المصحف
_QURANIC_SIGNS = re.compile(r"[ۖ-ۭ]")

# التشكيل بشكل عام
_TASHKEEL = re.compile(r"[ً-ْٰٓ-ٖـ]")
_ARABIC_LETTER = re.compile(r"[ء-غف-ي]")

# الأقواس المزخرفة أحيانًا بتتكتب بأقواس عادية مع النص المشكول
_QUOTE_PAIRS = [("«", "»"), ("“", "”"), ('"', '"'), ("﴿", "﴾")]


# ---------------------------------------------------------------------------
# عبارات تمهيدية
# ---------------------------------------------------------------------------

# تمهيد للآية: بعده بييجي كلام الله
_QURAN_INTRODUCERS = [
    "قال تعالى",
    "قال الله تعالى",
    "قال الله عز وجل",
    "قال عز وجل",
    "قال سبحانه وتعالى",
    "قال سبحانه",
    "يقول الله تعالى",
    "يقول تعالى",
    "قوله تعالى",
    "لقوله تعالى",
    "في قوله تعالى",
    "مصداقا لقوله تعالى",
    "عملا بقوله تعالى",
    "في محكم التنزيل",
    "في محكم كتابه",
    "كما قال تعالى",
    "لقول الله تعالى",
]

# تمهيد للحديث
_HADITH_INTRODUCERS = [
    "قال رسول الله",
    "قال النبي",
    "قال صلى الله عليه وسلم",
    "عن رسول الله",
    "عن النبي",
    "روي عن النبي",
    "في الحديث الشريف",
    "في الحديث القدسي",
    "الحديث النبوي",
    "حديث شريف",
]

# تخريج الحديث ودرجته — صيغ لا تُستعمل إلا مع الحديث
_HADITH_ATTRIBUTIONS = [
    "رواه البخاري",
    "رواه مسلم",
    "أخرجه البخاري",
    "أخرجه مسلم",
    "متفق عليه",
    "رواه الترمذي",
    "رواه أبو داود",
    "رواه النسائي",
    "رواه ابن ماجه",
    "رواه أحمد",
    "أخرجه أحمد",
    "حديث صحيح",
    "حديث حسن",
]

# أسماء كتب — قرينة مساعدة مش دليل قاطع. سطر في قائمة المراجع
# مكتوب فيه «صحيح البخاري» مش حديث، وقفله بيوقّف الشغل بلا سبب.
_HADITH_SOURCE_TITLES = [
    "صحيح البخاري",
    "صحيح مسلم",
    "سنن الترمذي",
    "سنن أبي داود",
    "سنن النسائي",
    "سنن ابن ماجه",
    "مسند أحمد",
]

# رواة مشهورون: "عن أبي هريرة رضي الله عنه قال"
_NARRATOR_PATTERN = re.compile(
    r"(?<![ء-ي])عن\s+\S+(?:\s+\S+)?\s+رضي\s+الله\s+عن(?:ه|ها|هم|هما)(?![ء-ي])"
)

# ---------------------------------------------------------------------------
# مطابقة العبارات
# ---------------------------------------------------------------------------
# العربية بتلزق السوابق بالكلمة (و، ف، ب، ك، ل)، فمطابقة الحدود
# الصارمة بتفوّت «وقال تعالى». وفي المقابل المطابقة كسلسلة حرة بتقع في
# فخ العكس: «متفق عليه» (درجة حديث) بتتلاقى جوه «المتفق عليها» في بند
# قانوني عادي. الحل: نسمح بسابقة ملزوقة، ونمنع أي حرف عربي بعد آخر
# حرف في العبارة.
#
# أداة التعريف «ال» مستبعَدة عمدًا من السوابق المسموحة: «متفق عليه»
# درجةُ حديث، و«المتفق عليه» وصفٌ في كلام عادي — الألف واللام بيغيّروا
# التركيب مش بيضيفوا تعريف وبس. والعبارات اللي محتاجة تعريف مكتوبة بيه
# في القايمة أصلًا («في الحديث الشريف»).
_PROCLITIC = r"[وفبكل]?"


def _compile_phrase(phrase: str) -> re.Pattern[str]:
    body = r"\s+".join(re.escape(word) for word in phrase.split())
    return re.compile(rf"(?<![ء-ي]){_PROCLITIC}{body}(?![ء-ي])")


def _compile_all(phrases: list[str]) -> list[tuple[str, re.Pattern[str]]]:
    # الأطول الأول عشان «قال الله تعالى» تكسب على «قال تعالى»
    ordered = sorted(phrases, key=len, reverse=True)
    return [(phrase, _compile_phrase(phrase)) for phrase in ordered]


_QURAN_INTRODUCER_PATTERNS = _compile_all(_QURAN_INTRODUCERS)
_HADITH_INTRODUCER_PATTERNS = _compile_all(_HADITH_INTRODUCERS)
_HADITH_ATTRIBUTION_PATTERNS = _compile_all(_HADITH_ATTRIBUTIONS)
_HADITH_TITLE_PATTERNS = _compile_all(_HADITH_SOURCE_TITLES)

# ---------------------------------------------------------------------------
# أسماء السور — لكشف الإحالات زي [البقرة: 255]
# ---------------------------------------------------------------------------
_SURAH_NAMES = {
    "الفاتحة", "البقرة", "آل عمران", "النساء", "المائدة", "الأنعام",
    "الأعراف", "الأنفال", "التوبة", "يونس", "هود", "يوسف", "الرعد",
    "إبراهيم", "الحجر", "النحل", "الإسراء", "الكهف", "مريم", "طه",
    "الأنبياء", "الحج", "المؤمنون", "النور", "الفرقان", "الشعراء",
    "النمل", "القصص", "العنكبوت", "الروم", "لقمان", "السجدة",
    "الأحزاب", "سبأ", "فاطر", "يس", "الصافات", "ص", "الزمر", "غافر",
    "فصلت", "الشورى", "الزخرف", "الدخان", "الجاثية", "الأحقاف",
    "محمد", "الفتح", "الحجرات", "ق", "الذاريات", "الطور", "النجم",
    "القمر", "الرحمن", "الواقعة", "الحديد", "المجادلة", "الحشر",
    "الممتحنة", "الصف", "الجمعة", "المنافقون", "التغابن", "الطلاق",
    "التحريم", "الملك", "القلم", "الحاقة", "المعارج", "نوح", "الجن",
    "المزمل", "المدثر", "القيامة", "الإنسان", "المرسلات", "النبأ",
    "النازعات", "عبس", "التكوير", "الانفطار", "المطففين", "الانشقاق",
    "البروج", "الطارق", "الأعلى", "الغاشية", "الفجر", "البلد",
    "الشمس", "الليل", "الضحى", "الشرح", "التين", "العلق", "القدر",
    "البينة", "الزلزلة", "العاديات", "القارعة", "التكاثر", "العصر",
    "الهمزة", "الفيل", "قريش", "الماعون", "الكوثر", "الكافرون",
    "النصر", "المسد", "الإخلاص", "الفلق", "الناس",
}

# [البقرة: 255] أو (سورة البقرة، الآية 255) أو (البقرة ٢٥٥)
_CITATION = re.compile(
    r"[\[\(]\s*(?:سورة\s+)?([ء-ي\s]+?)\s*[:،,]?\s*"
    r"(?:الآية\s*)?[\d٠-٩]+\s*[\]\)]"
)


@dataclass
class SacredSpan:
    """جزء من النص اتكشف إنه نص مقدّس."""

    kind: str          # quran | hadith
    confidence: str    # certain | likely
    text: str
    start: int
    end: int
    reason: str


@dataclass
class Detection:
    """خلاصة الفحص لمقطع واحد."""

    spans: list[SacredSpan] = field(default_factory=list)

    @property
    def found(self) -> bool:
        return bool(self.spans)

    @property
    def certain(self) -> bool:
        return any(s.confidence == "certain" for s in self.spans)

    @property
    def kinds(self) -> set[str]:
        return {s.kind for s in self.spans}

    def flags(self) -> list[str]:
        """أعلام الجودة المعروضة للمراجع."""
        out: list[str] = []
        for kind in sorted(self.kinds):
            level = "certain" if any(
                s.kind == kind and s.confidence == "certain" for s in self.spans
            ) else "likely"
            out.append(f"{kind}_{level}")
        return out

    def note(self) -> str:
        """شرح للمراجع: إيه اللي اتكشف وليه."""
        lines = []
        for span in self.spans:
            label = "آية قرآنية" if span.kind == "quran" else "حديث نبوي"
            certainty = "" if span.confidence == "certain" else " (يُرجَّح)"
            lines.append(f"{label}{certainty}: {span.reason}")
        return " · ".join(lines)


# ---------------------------------------------------------------------------
# أدوات مساعدة
# ---------------------------------------------------------------------------

def vocalization_ratio(text: str) -> float:
    """نسبة الحروف المشكّلة — النص القرآني بيتكتب مضبوطًا بالكامل.

    النثر العربي الحديث بيبقى شبه خالي من التشكيل، فالنسبة العالية
    على مدى كلمات كتير مؤشّر قوي.
    """
    letters = len(_ARABIC_LETTER.findall(text))
    if letters < 8:  # قصير أوي على حكم إحصائي
        return 0.0
    return len(_TASHKEEL.findall(text)) / letters


def _find_quoted_after(text: str, position: int) -> tuple[int, int] | None:
    """أقرب نص مقتبس بعد موضع معيّن."""
    best: tuple[int, int] | None = None
    for opener, closer in _QUOTE_PAIRS:
        start = text.find(opener, position)
        if start == -1:
            continue
        end = text.find(closer, start + len(opener))
        if end == -1:
            continue
        span = (start, end + len(closer))
        if best is None or span[0] < best[0]:
            best = span
    return best


def _has_any(
    text: str, compiled: list[tuple[str, re.Pattern[str]]]
) -> tuple[str, int] | None:
    """أبكر عبارة مطابقة مع نهاية موضعها (عشان ندوّر على الاقتباس بعدها)."""
    best: tuple[str, int] | None = None
    best_start = len(text) + 1
    for phrase, pattern in compiled:
        match = pattern.search(text)
        if match and match.start() < best_start:
            best_start = match.start()
            best = (phrase, match.end())
    return best


def _is_citation_only(text: str) -> bool:
    """هل المقطع حاشية تخريج بحتة من غير نص حديث؟

    الحواشي في الكتب الشرعية شكلها «(١) أخرجه البخاري (٧٩)، ومسلم
    (٢٢٨٢).» — أسماء مخرّجين وأرقام وعلامات ترقيم. النص المقدّس نفسه
    مش موجود فيها، فقفلها بيمنع ترجمة مرجع عادي.

    بنشيل عبارات التخريج وأسماء الكتب والأرقام، ونشوف الباقي: لو فضل
    كلام قليل يبقى إحالة مش حديث.
    """
    remainder = text
    for phrases in (_HADITH_ATTRIBUTIONS, _HADITH_SOURCE_TITLES):
        for phrase in phrases:
            remainder = remainder.replace(phrase, " ")

    # الأرقام (عربية وهندية) وعلامات الترقيم مش كلام
    remainder = re.sub(r"[\d٠-٩]+", " ", remainder)
    remainder = re.sub(r"[^ء-ي\s]", " ", remainder)

    words = [word for word in remainder.split() if len(word) > 1]
    return len(words) <= 3


def _citation_surah(text: str) -> str | None:
    """اسم السورة لو النص فيه إحالة زي [البقرة: 255]."""
    for match in _CITATION.finditer(text):
        name = match.group(1).strip()
        if name.startswith("سورة "):
            name = name[5:].strip()
        if name in _SURAH_NAMES:
            return name
    return None


# ---------------------------------------------------------------------------
# الكشف
# ---------------------------------------------------------------------------

def detect(text: str) -> Detection:
    """فحص مقطع واحد ورجوع بكل ما اتكشف فيه.

    التطبيع بيفك الليجاتورات المدمجة (ﷺ → صلى الله عليه وسلم) فالمطابقة
    النصية بتشتغل على الشكلين.
    """
    result = Detection()
    if not text or not _ARABIC_LETTER.search(text):
        return result

    normalized = unicodedata.normalize("NFKC", text)

    # ---- 1) الأقواس المزخرفة: أوضح دليل على الإطلاق ----
    depth_start = normalized.find(_ORNATE_OPEN)
    while depth_start != -1:
        end = normalized.find(_ORNATE_CLOSE, depth_start + 1)
        if end == -1:
            # قوس فاتح من غير قافل — المقطع اتقسم في نص الآية
            result.spans.append(
                SacredSpan(
                    kind="quran",
                    confidence="certain",
                    text=normalized[depth_start:],
                    start=depth_start,
                    end=len(normalized),
                    reason="قوس آية مفتوح — الآية ممتدة على أكتر من مقطع",
                )
            )
            break
        result.spans.append(
            SacredSpan(
                kind="quran",
                confidence="certain",
                text=normalized[depth_start : end + 1],
                start=depth_start,
                end=end + 1,
                reason="بين قوسين مزخرفين ﴿﴾",
            )
        )
        depth_start = normalized.find(_ORNATE_OPEN, end + 1)

    # ---- 2) علامة نهاية الآية أو رمز البسملة ----
    if _END_OF_AYAH in normalized and not result.spans:
        result.spans.append(
            SacredSpan(
                kind="quran", confidence="certain", text=normalized,
                start=0, end=len(normalized),
                reason="علامة نهاية آية ۝",
            )
        )
    if _BISMILLAH_LIGATURE in text:
        result.spans.append(
            SacredSpan(
                kind="quran", confidence="certain", text=normalized,
                start=0, end=len(normalized), reason="رمز البسملة ﷽",
            )
        )

    # ---- 3) عبارة تمهيدية للآية ----
    hit = _has_any(normalized, _QURAN_INTRODUCER_PATTERNS)
    if hit and not any(s.kind == "quran" and s.confidence == "certain"
                       for s in result.spans):
        introducer, position = hit
        quoted = _find_quoted_after(normalized, position)
        if quoted:
            result.spans.append(
                SacredSpan(
                    kind="quran", confidence="certain",
                    text=normalized[quoted[0] : quoted[1]],
                    start=quoted[0], end=quoted[1],
                    reason=f"بعد «{introducer}» وبين علامتَي اقتباس",
                )
            )
        else:
            result.spans.append(
                SacredSpan(
                    kind="quran", confidence="likely", text=normalized,
                    start=0, end=len(normalized),
                    reason=f"بعد «{introducer}» من غير علامة اقتباس واضحة",
                )
            )

    # ---- 4) الضبط الكامل + علامات المصحف ----
    if not any(s.kind == "quran" for s in result.spans):
        ratio = vocalization_ratio(normalized)
        if ratio >= 0.35:
            has_signs = bool(_QURANIC_SIGNS.search(normalized))
            result.spans.append(
                SacredSpan(
                    kind="quran",
                    confidence="certain" if has_signs else "likely",
                    text=normalized, start=0, end=len(normalized),
                    reason=(
                        f"ضبط كامل ({ratio:.0%}) مع علامات ضبط قرآني"
                        if has_signs
                        else f"ضبط كامل بالشكل ({ratio:.0%}) — غير معتاد "
                             "في النثر الحديث"
                    ),
                )
            )

    # ---- 5) إحالة لسورة وآية ----
    surah = _citation_surah(normalized)
    if surah and not any(s.kind == "quran" and s.confidence == "certain"
                         for s in result.spans):
        result.spans.append(
            SacredSpan(
                kind="quran", confidence="certain", text=normalized,
                start=0, end=len(normalized),
                reason=f"إحالة لسورة {surah}",
            )
        )

    # ---- 6) الحديث: التخريج أقوى دليل ----
    attribution = _has_any(normalized, _HADITH_ATTRIBUTION_PATTERNS)
    introduction = _has_any(normalized, _HADITH_INTRODUCER_PATTERNS)
    title = _has_any(normalized, _HADITH_TITLE_PATTERNS)
    narrator = _NARRATOR_PATTERN.search(normalized)

    # حاشية تخريج زي «(١) أخرجه البخاري (٧٩)، ومسلم (٢٢٨٢).» فيها
    # التخريج من غير نص الحديث. قفلها بيمنع ترجمتها بلا سبب — مافيش
    # فيها نص مقدّس أصلًا، دي إحالة مرجعية.
    if attribution and not introduction and _is_citation_only(normalized):
        result.spans.append(
            SacredSpan(
                kind="hadith", confidence="likely", text=normalized,
                start=0, end=len(normalized),
                reason=f"حاشية تخريج «{attribution[0]}» بدون نص حديث",
            )
        )
        return result

    if attribution or introduction:
        # بندوّر على الاقتباس بعد التمهيد، وإلا فبعد التخريج
        _anchor, position = introduction or attribution
        quoted = _find_quoted_after(normalized, position)
        # التخريج صيغة خاصة بالحديث فبيكفي وحده. التمهيد لوحده ممكن
        # يبقى كلام *عن* حديث مش الحديث نفسه، فمحتاج نص مقتبس معاه.
        certain = bool(attribution) or bool(quoted)
        reason_parts = []
        if introduction:
            reason_parts.append(f"«{introduction[0]}»")
        if attribution:
            reason_parts.append(f"تخريج «{attribution[0]}»")
        if title:
            reason_parts.append(f"مصدر «{title[0]}»")
        if narrator:
            reason_parts.append("سند راوٍ")

        if quoted:
            result.spans.append(
                SacredSpan(
                    kind="hadith", confidence="certain",
                    text=normalized[quoted[0] : quoted[1]],
                    start=quoted[0], end=quoted[1],
                    reason=" + ".join(reason_parts) + " مع نص مقتبس",
                )
            )
        else:
            result.spans.append(
                SacredSpan(
                    kind="hadith",
                    confidence="certain" if certain else "likely",
                    text=normalized, start=0, end=len(normalized),
                    reason=" + ".join(reason_parts),
                )
            )
    elif narrator:
        # سند من غير تمهيد ولا تخريج — يرجَّح إنه حديث
        result.spans.append(
            SacredSpan(
                kind="hadith", confidence="likely", text=normalized,
                start=0, end=len(normalized),
                reason="سند راوٍ (عن فلان رضي الله عنه)",
            )
        )

    return result


def scan(texts: list[str]) -> dict[int, Detection]:
    """فحص مجموعة مقاطع — بيرجّع اللي فيه كشف بس."""
    found: dict[int, Detection] = {}
    for index, text in enumerate(texts):
        detection = detect(text)
        if detection.found:
            found[index] = detection
    return found
