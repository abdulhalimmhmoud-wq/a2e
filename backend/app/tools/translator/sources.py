"""المصادر المعتمدة للنص المقدّس: quran.com و sunnah.com.

الفكرة: الأداة **ماتخزّنش** أي ترجمة جوّه المستودع. لما المراجع يطلب،
بنجيب الترجمة من المصدر الرسمي وقت الطلب، ونسجّل معاها اسم الترجمة
وصاحبها والرابط. النسخة المحفوظة محليًا هي كاش لشغلك إنت، مش نسخة
موزَّعة.

الاختيار بين الترجمات مش تفصيلة شكلية: الترجمات الحديثة محمية بحقوق
نشر، والقديمة وضعها بيختلف من ولاية قضائية للتانية. عشان كده الترجمة
اختيار صريح في الإعدادات، والإسناد بيتسجّل مع كل مقطع تلقائيًا عشان
يبان في مستندك وتعرف إنت وقّعت على إيه.

المطابقة أصعب مما تبدو: رسم المصحف بيختلف عن الإملاء الحديث (الربوا /
الربا · الاحسن / الإحسان · يايها / يا أيها)، فالمقارنة الحرفية بتفشل.
بنقارن **هيكل الحروف** بعد إسقاط الحروف الضعيفة، وده بيتخطّى الفرق ده.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field

import requests

from app.core.config import settings

logger = logging.getLogger(__name__)

QURAN_API = "https://api.quran.com/api/v4"
QURAN_SITE = "https://quran.com"
SUNNAH_API = "https://api.sunnah.com/v1"
SUNNAH_SITE = "https://sunnah.com"

_TIMEOUT = 25

# ---------------------------------------------------------------------------
# التطبيع والمطابقة
# ---------------------------------------------------------------------------
_DIACRITICS = re.compile(r"[ً-ٰٕۖ-ۭـ]")
_NON_ARABIC = re.compile(r"[^ء-ي\s]")

# الحروف الضعيفة (الألف بصورها، الواو، الياء، الهمزة) — دي بالظبط اللي
# رسم المصحف بيختلف فيها عن الإملاء الحديث، فبنسقطها من الطرفين
_WEAK = re.compile(r"[ء-اوىيٱ-ٵ]")

# أقل عدد كلمات نقبل عليه مطابقة تلقائية. «فإن الله غفور رحيم» بتظهر
# في آيات كتير، واختيار واحدة منها يبقى ترجيح بلا مرجّح.
_MIN_WORDS = 4


def plain_arabic(text: str) -> str:
    """نص عربي بدون تشكيل ولا علامات — الشكل المناسب للبحث."""
    text = _DIACRITICS.sub("", unicodedata.normalize("NFKC", text))
    return re.sub(r"\s+", " ", _NON_ARABIC.sub(" ", text)).strip()


def skeleton(text: str) -> str:
    """هيكل الحروف: بدون تشكيل ولا حروف ضعيفة ولا مسافات."""
    text = _DIACRITICS.sub("", unicodedata.normalize("NFKC", text))
    return re.sub(r"[^ب-ي]", "", _WEAK.sub("", text))


@dataclass
class VerseMatch:
    verse_key: str                 # "2:275"
    verse_keys: list[str]          # كل الآيات لو الاقتباس ممتد
    arabic: str
    translation: str = ""
    translation_name: str = ""
    translation_author: str = ""
    url: str = ""
    ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class HadithLead:
    """سنن.كوم محتاج مفتاح. من غيره بنرجّع رابط بحث جاهز للمراجع."""

    search_url: str
    text: str = ""
    reference: str = ""
    collection: str = ""
    available: bool = False
    note: str = ""


# ---------------------------------------------------------------------------
# quran.com
# ---------------------------------------------------------------------------
def list_translations(language: str = "en") -> list[dict]:
    """الترجمات المتاحة على quran.com."""
    response = requests.get(
        f"{QURAN_API}/resources/translations",
        params={"language": language},
        timeout=_TIMEOUT,
    )
    response.raise_for_status()
    return response.json().get("translations", [])


def _search(query: str, size: int = 6) -> list[dict]:
    response = requests.get(
        f"{QURAN_API}/search", params={"q": query, "size": size}, timeout=_TIMEOUT
    )
    response.raise_for_status()
    return response.json().get("search", {}).get("results", [])


def _verse(verse_key: str, translation_id: int | None) -> dict:
    params: dict[str, object] = {"fields": "text_uthmani"}
    if translation_id:
        params["translations"] = translation_id
    response = requests.get(
        f"{QURAN_API}/verses/by_key/{verse_key}", params=params, timeout=_TIMEOUT
    )
    response.raise_for_status()
    return response.json().get("verse", {})


_names_cache: dict[int, str] = {}


def translation_name(translation_id: int) -> str:
    """اسم الترجمة من معرّفها.

    نداء الآية بيرجّع resource_id بس من غير الاسم، والإسناد لازم يبان
    للمراجع بالاسم مش برقم.
    """
    if not _names_cache:
        try:
            for item in list_translations("en"):
                _names_cache[item["id"]] = item.get("name", "")
        except requests.RequestException as exc:
            logger.warning("جلب أسماء الترجمات فشل: %s", exc)
            return ""
    return _names_cache.get(translation_id, "")


def _window(verse_key: str, back: int = 2, forward: int = 4) -> list[str]:
    """مفاتيح الآيات حوالين آية معيّنة.

    البحث بيرجّع الآية اللي فيها أقوى تطابق، مش أول آية في الاقتباس.
    اقتباس زي «والعصر إن الإنسان لفي خسر» البحث بيرجّع فيه الآية
    **التانية**، فالمشي للأمام بس مش هيلاقي البداية أبدًا.
    """
    surah, number = verse_key.split(":")
    start = max(1, int(number) - back)
    return [f"{surah}:{n}" for n in range(start, int(number) + forward + 1)]


def find_verse(
    arabic_text: str,
    translation_id: int | None = None,
    max_span: int = 5,
) -> VerseMatch | None:
    """تحديد الآية من نصها العربي، والتحقق قبل الاعتماد.

    ترتيب البحث بيرجّع الأقرب، لكن الترتيب لوحده مش دليل — بنتحقق إن
    هيكل حروف المقتبَس موجود فعلًا جوّه الآية. والاقتباس الممتد على
    أكتر من آية بيتجمّع الآيات المتتالية لحد ما يكتمل.
    """
    query = plain_arabic(arabic_text)
    words = query.split()
    if len(words) < _MIN_WORDS:
        return None

    target = skeleton(query)
    if not target:
        return None

    try:
        results = _search(query)
    except requests.RequestException as exc:
        logger.warning("بحث quran.com فشل: %s", exc)
        return None

    if not results:
        return None

    # ---- 1) آية واحدة تحتوي الاقتباس كله ----
    contained = [
        hit["verse_key"]
        for hit in results
        if hit.get("verse_key") and target in skeleton(hit.get("text", ""))
    ]
    if contained:
        # أكتر من آية تحتوي نفس النص → ترجيح بلا مرجّح، نسيب القرار للمراجع
        if len(set(contained)) > 1:
            return VerseMatch(
                verse_key=contained[0],
                verse_keys=list(dict.fromkeys(contained)),
                arabic=arabic_text,
                ambiguous=True,
                candidates=list(dict.fromkeys(contained)),
                note="النص ده موجود في أكتر من آية — اختر أنت الموضع الصحيح",
            )
        return _build(contained[0], [contained[0]], translation_id)

    # ---- 2) اقتباس ممتد على آيات متتالية ----
    for hit in results[:2]:
        start = hit.get("verse_key")
        if not start:
            continue

        window: list[tuple[str, str]] = []
        for key in _window(start, back=max_span - 1, forward=max_span - 1):
            try:
                verse = _verse(key, None)
            except requests.RequestException:
                continue  # رقم آية مش موجود في السورة دي
            text = verse.get("text_uthmani", "")
            if text:
                window.append((key, skeleton(text)))

        if not window:
            continue

        joined = "".join(part for _, part in window)
        if target not in joined:
            continue

        # قصّ النطاق لأصغر مدى لسه بيحتوي الاقتباس، عشان مانسندش
        # الاقتباس لآيات مالهاش علاقة بيه
        low, high = 0, len(window) - 1
        while low < high and target in "".join(
            part for _, part in window[low + 1 : high + 1]
        ):
            low += 1
        while high > low and target in "".join(
            part for _, part in window[low:high]
        ):
            high -= 1

        keys = [key for key, _ in window[low : high + 1]]
        return _build(keys[0], keys, translation_id, spans=len(keys))

    return None


def _build(
    verse_key: str,
    verse_keys: list[str],
    translation_id: int | None,
    spans: int = 1,
) -> VerseMatch | None:
    translation_id = translation_id or settings.quran_translation_id
    parts: list[str] = []
    arabic_parts: list[str] = []
    name = author = ""

    for key in verse_keys:
        try:
            verse = _verse(key, translation_id)
        except requests.RequestException as exc:
            logger.warning("جلب الآية %s فشل: %s", key, exc)
            return None
        arabic_parts.append(verse.get("text_uthmani", ""))
        for item in verse.get("translations", []) or []:
            text = _strip_html(item.get("text", ""))
            if text:
                parts.append(text)
            name = name or item.get("resource_name", "") or translation_name(
                item.get("resource_id", translation_id)
            )

    surah = verse_key.split(":")[0]
    return VerseMatch(
        verse_key=verse_key,
        verse_keys=verse_keys,
        arabic=" ".join(arabic_parts).strip(),
        translation=" ".join(parts).strip(),
        translation_name=name,
        translation_author=author,
        url=f"{QURAN_SITE}/{surah}/{verse_key.split(':')[1]}",
        note=(
            f"الاقتباس ممتد على {spans} آيات ({verse_keys[0]}–{verse_keys[-1]})"
            if spans > 1
            else ""
        ),
    )


_TAG = re.compile(r"<[^>]+>")
_FOOTNOTE = re.compile(r"<sup[^>]*foot_note[^>]*>.*?</sup>", re.DOTALL)


def _strip_html(text: str) -> str:
    """ترجمات quran.com بتيجي فيها وسوم وحواشي — بنشيلها."""
    return re.sub(r"\s+", " ", _TAG.sub("", _FOOTNOTE.sub("", text))).strip()


# ---------------------------------------------------------------------------
# sunnah.com
# ---------------------------------------------------------------------------
def search_hadith(arabic_text: str) -> HadithLead:
    """البحث عن حديث على sunnah.com.

    الواجهة البرمجية بتاعتهم محتاجة مفتاح (بيتطلب منهم). من غير مفتاح
    بنرجّع رابط بحث جاهز — أنفع للمراجع من رسالة خطأ، وبيوصله لنص
    الحديث وترجمته المعتمدة على طول.
    """
    query = plain_arabic(arabic_text)
    # أول عشر كلمات كافية للبحث، والزيادة بتضيّق النتيجة لدرجة الصفر
    short = " ".join(query.split()[:10])
    search_url = f"{SUNNAH_SITE}/search?q={requests.utils.quote(short)}"

    key = settings.sunnah_api_key
    if not key:
        return HadithLead(
            search_url=search_url,
            note="مفيش مفتاح لـ sunnah.com — افتح الرابط وانسخ الترجمة المعتمدة",
        )

    try:
        response = requests.get(
            f"{SUNNAH_API}/hadiths",
            params={"q": short},
            headers={"X-API-Key": key},
            timeout=_TIMEOUT,
        )
        if response.status_code == 403:
            return HadithLead(
                search_url=search_url,
                note="مفتاح sunnah.com مرفوض — راجعه في .env",
            )
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("بحث sunnah.com فشل: %s", exc)
        return HadithLead(search_url=search_url, note=f"تعذّر الاتصال: {exc}")

    items = (response.json() or {}).get("data") or []
    if not items:
        return HadithLead(search_url=search_url, note="مفيش نتيجة مطابقة")

    first = items[0]
    english = ""
    for entry in first.get("hadith", []):
        if entry.get("lang") == "en":
            english = _strip_html(entry.get("body", ""))
            break

    return HadithLead(
        search_url=search_url,
        text=english,
        reference=str(first.get("hadithNumber", "")),
        collection=first.get("collection", ""),
        available=bool(english),
    )
