"""اختبار المصادر المعتمدة (quran.com و sunnah.com).

بيعمل نداءات شبكة حقيقية لكن مجانية بالكامل — مفيش أي استهلاك API
مدفوع هنا. quran.com مفتوح من غير مفتاح، و sunnah.com بيتفحص حسب
وجود المفتاح.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.core.config import settings  # noqa: E402
from app.tools.translator import sources  # noqa: E402

# (النص، مفتاح الآية المتوقع أو None، وصف الحالة)
VERSES = [
    ("﴿وَأَحَلَّ اللَّهُ الْبَيْعَ وَحَرَّمَ الرِّبَا﴾", "2:275", "آية مشكولة بين أقواس"),
    ("يا أيها الذين آمنوا أوفوا بالعقود", "5:1", "بإملاء حديث مش رسم المصحف"),
    ("﴿وَتَعَاوَنُوا عَلَى الْبِرِّ وَالتَّقْوَىٰ﴾", "5:2", "جزء من آية طويلة"),
    ("إن الله يأمر بالعدل والإحسان", "16:90", "بدون تشكيل"),
    ("وَٱلْعَصْرِ إِنَّ ٱلْإِنسَٰنَ لَفِى خُسْرٍ", "103:1", "اقتباس ممتد على آيتين"),
]

NOT_VERSES = [
    ("المادة الأولى يلتزم الطرف الأول بتقديم الخدمات الاستشارية", "بند قانوني"),
    ("تبلغ قيمة العقد مئة وخمسين ألف ريال سعودي", "بند مالي"),
    ("أظهرت نتائج الدراسة انخفاضا في معدل الالتهاب بعد أربعة أسابيع", "نص علمي"),
]


def main() -> int:  # noqa: C901
    failures: list[str] = []

    # ---------- 1) الهيكل يتخطّى فرق الرسم ----------
    print("=== 1) هيكل الحروف يتخطّى فرق رسم المصحف ===")
    pairs = [
        ("الربا", "الربوا", "رسم المصحف بيزوّد واو"),
        ("الإحسان", "الاحسن", "رسم المصحف بيسقط ألف"),
        ("يا أيها", "يايها", "منفصلة مقابل متصلة"),
        ("آمنوا", "ءامنوا", "صور الهمزة"),
        ("الشيطان", "الشيطن", "ألف محذوفة"),
    ]
    for modern, uthmani, why in pairs:
        same = sources.skeleton(modern) == sources.skeleton(uthmani)
        print(f"  {'✓' if same else '✗'} {modern} ≡ {uthmani}   ({why})")
        if not same:
            failures.append(f"الهيكل مااتطابقش: {modern}/{uthmani}")

    # كلمتين مختلفتين فعلًا مايتطابقوش
    if sources.skeleton("الكتاب") == sources.skeleton("الحساب"):
        failures.append("الهيكل بيطابق كلمات مختلفة — المطابقة هتبقى عشوائية")

    # ---------- 2) تحديد الآية ----------
    print("\n=== 2) تحديد الآية والتحقق منها ===")
    for text, expected, label in VERSES:
        match = sources.find_verse(text)
        got = match.verse_key if match else None
        ok = got == expected
        print(f"  {'✓' if ok else '✗'} {label}")
        print(f"      {text[:52]}")
        print(f"      اتحدّد: {got} (متوقع {expected})")
        if match:
            if match.note:
                print(f"      {match.note}")
            if match.translation:
                print(f"      [{match.translation_name}] "
                      f"{match.translation[:64]}")
            print(f"      {match.url}")
        if not ok:
            failures.append(f"{label}: اتحدّد {got} بدل {expected}")
        elif match and not match.translation:
            failures.append(f"{label}: مفيش ترجمة مع المطابقة")

    # ---------- 3) نص عادي مايتطابقش ----------
    print("\n=== 3) نص عادي — مالوش يتطابق مع أي آية ===")
    for text, label in NOT_VERSES:
        match = sources.find_verse(text)
        ok = match is None
        print(f"  {'✓' if ok else '✗'} {label}: "
              f"{'مفيش مطابقة' if ok else match.verse_key}")
        if not ok:
            failures.append(
                f"{label} اتطابق مع {match.verse_key} — "
                "نص عادي هيتحط مكانه آية"
            )

    # ---------- 4) النص القصير المشترك ----------
    print("\n=== 4) عبارة قصيرة مشتركة بين آيات ===")
    short = sources.find_verse("فإن الله غفور رحيم")
    if short is None:
        print("  ✓ اترفضت لقصرها — اختيار آية منها يبقى ترجيح بلا مرجّح")
    elif short.ambiguous:
        print(f"  ✓ اتعلّمت كملتبسة: {short.candidates}")
    else:
        print(f"  ✗ اختارت {short.verse_key} من غير ما تنبّه للالتباس")
        failures.append(
            "عبارة قصيرة موجودة في آيات كتير اتربطت بآية واحدة بلا تنبيه"
        )

    # ---------- 5) قائمة الترجمات ----------
    print("\n=== 5) الترجمات المتاحة ===")
    try:
        translations = sources.list_translations("en")
        print(f"  متاح: {len(translations)} ترجمة إنجليزية")
        current = [
            t for t in translations
            if t["id"] == settings.quran_translation_id
        ]
        if current:
            print(f"  المختارة حاليًا: id={current[0]['id']} · "
                  f"{current[0]['name']}")
        else:
            failures.append(
                f"معرّف الترجمة المضبوط ({settings.quran_translation_id}) "
                "مش موجود في قائمة quran.com"
            )
    except Exception as exc:  # noqa: BLE001
        failures.append(f"جلب قائمة الترجمات فشل: {exc}")

    # ---------- 5ب) قراءة الإحالة من النص ----------
    #
    # واجهة sunnah.com مافيهاش بحث نصي — بتاخد المجموعة ورقم الحديث.
    # فالمفتاح بيتقرا من المستند نفسه، وده أدق من البحث بالنص أصلًا.
    print("\n=== 5ب) قراءة إحالة الحديث من النص ===")
    citation_cases = [
        ("(١) أخرجه البخاري (٧٩)، ومسلم (٢٢٨٢).",
         [("bukhari", "79"), ("muslim", "2282")], "مخرّجان بأرقام عربية"),
        ("رواه الترمذي (2678) وأبو داود (4607).",
         [("tirmidhi", "2678"), ("abudawud", "4607")], "أرقام لاتينية"),
        ("متفق عليه.", [], "تخريج بدون رقم"),
        ("المادة الأولى: يلتزم الطرف الأول (٣) بالتسليم.",
         [], "رقم في نص قانوني عادي"),
    ]
    for text, expected, label in citation_cases:
        got = sources.citations(text)
        ok = got == expected
        print(f"  {'✓' if ok else '✗'} {label:<26} → {got}")
        if not ok:
            failures.append(f"قراءة الإحالة غلط في «{label}»: {got}")

    # ---------- 6) sunnah.com ----------
    print("\n=== 6) sunnah.com ===")
    lead = sources.fetch_hadith("قال رسول الله: «المسلمون على شروطهم» "
                                "أخرجه البخاري (٢٧٣٥).")
    print(f"  مفتاح مضبوط: {bool(settings.sunnah_api_key)}")
    print(f"  متاح نصًا: {lead.available}")
    print(f"  رابط البحث: {lead.search_url[:76]}")
    if lead.note:
        print(f"  ملاحظة: {lead.note}")
    if not lead.search_url.startswith("https://sunnah.com/search"):
        failures.append("رابط بحث sunnah.com مش مظبوط")
    if lead.available and not lead.text:
        failures.append("اتعلّم متاح من غير نص")

    print("\n" + "=" * 64)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: المصادر المعتمدة شغّالة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
