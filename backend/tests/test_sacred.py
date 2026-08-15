"""اختبار كشف الآيات والأحاديث — بدون أي نداء API.

الحالات السلبية هنا مهمة قد الإيجابية: قفل مقطع عادي بالغلط بيوقّف
الشغل ويخلّي المستخدم يلغّي الميزة كلها.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from app.tools.translator import sacred  # noqa: E402

# (النص، النوع المتوقع أو None، الثقة المتوقعة أو None، وصف الحالة)
CASES: list[tuple[str, str | None, str | None, str]] = [
    # ---------------------------------------------------- قرآن مؤكَّد
    (
        "قال تعالى: ﴿وَأَحَلَّ اللَّهُ الْبَيْعَ وَحَرَّمَ الرِّبَا﴾",
        "quran", "certain", "أقواس مزخرفة",
    ),
    (
        "﴿وَتَعَاوَنُوا عَلَى الْبِرِّ وَالتَّقْوَىٰ﴾ [المائدة: 2]",
        "quran", "certain", "أقواس مزخرفة مع إحالة",
    ),
    (
        "واستدل الباحث بقوله تعالى \"وأوفوا بالعقود\" في تأصيل مبدأ "
        "القوة الملزمة للعقد.",
        "quran", "certain", "تمهيد + اقتباس",
    ),
    (
        "يقول الله تعالى في محكم التنزيل ما يفيد وجوب الوفاء بالعهد.",
        "quran", "likely", "تمهيد بدون اقتباس",
    ),
    (
        "نصت المادة على مبدأ مستمد من قوله عز وجل في سورة البقرة "
        "[البقرة: 282] بشأن توثيق الديون.",
        "quran", "certain", "إحالة لسورة وآية",
    ),
    (
        "بِسْمِ اللَّهِ الرَّحْمَٰنِ الرَّحِيمِ",
        "quran", "likely", "بسملة مشكولة بالكامل",
    ),

    # ---------------------------------------------------- حديث
    (
        "قال رسول الله صلى الله عليه وسلم: «المسلمون على شروطهم» "
        "رواه البخاري.",
        "hadith", "certain", "تمهيد + اقتباس + تخريج",
    ),
    (
        "عن أبي هريرة رضي الله عنه قال: نهى النبي عن بيع الغرر، "
        "أخرجه مسلم.",
        "hadith", "certain", "سند + تخريج",
    ),
    # كلام *عن* حديث مش الحديث نفسه — يتعلّم ولا يتقفل، مافيش نص
    # مقدّس هنا أصلًا عشان يتقفل
    (
        "وهو ما يفهم من الحديث النبوي الوارد في هذا الباب.",
        "hadith", "likely", "إشارة لحديث بدون نصه",
    ),
    (
        "عن ابن عمر رضي الله عنهما أن البيع خيار ما لم يتفرقا.",
        "hadith", "likely", "سند بدون تخريج",
    ),
    # حواشي التخريج في الكتب الشرعية: تخريج وأرقام بدون نص حديث.
    # قفلها بيمنع ترجمة مرجع عادي، فبتتعلّم بس.
    (
        "(١) أخرجه البخاري (٧٩)، ومسلم (٢٢٨٢).",
        "hadith", "likely", "حاشية تخريج بدون نص",
    ),
    (
        "رواه البخاري (٥٠٢٧) ورواه مسلم (٧٩١).",
        "hadith", "likely", "تخريج بأرقام فقط",
    ),

    # ---------------------------------------------------- سلبية: نص عادي
    (
        "المادة 1. يلتزم الطرف الأول بتقديم الخدمات الاستشارية المتفق "
        "عليها خلال ثلاثين يومًا.",
        None, None, "بند قانوني عادي",
    ),
    (
        "تبلغ قيمة العقد 150.000 ريال سعودي تدفع على ثلاث دفعات.",
        None, None, "بند مالي",
    ),
    (
        "أظهرت نتائج الدراسة انخفاضًا في معدل الالتهاب بنسبة 42% بعد "
        "أربعة أسابيع من العلاج.",
        None, None, "نص علمي",
    ),
    (
        "The First Party shall provide the agreed consultancy services.",
        None, None, "نص إنجليزي",
    ),
    (
        "قال المدير التنفيذي إن الشركة حققت أرباحًا قياسية هذا العام.",
        None, None, "«قال» عادية مش تمهيد",
    ),
    (
        "الحمد لله رب العالمين والصلاة والسلام على أشرف المرسلين.",
        None, None, "افتتاحية دينية مش آية ولا حديث",
    ),
    (
        "صدر الحكم من محكمة النقض بجلستها المنعقدة يوم الثلاثاء.",
        None, None, "حكم قضائي",
    ),
    (
        "يهدف هذا البحث إلى دراسة أحكام الشريعة الإسلامية في المعاملات "
        "المالية المعاصرة.",
        None, None, "كلام عن الشريعة مش نص مقدّس",
    ),
    # «متفق عليه» درجة حديث، و«المتفق عليها» بند قانوني عادي —
    # المطابقة كسلسلة حرة بتخلط بينهم
    (
        "تسري الشروط المتفق عليها بين الطرفين من تاريخ التوقيع.",
        None, None, "«المتفق عليها» مش «متفق عليه»",
    ),
    (
        "راجع الباحث صحيح البخاري ضمن قائمة المراجع المعتمدة في الرسالة.",
        None, None, "اسم كتاب في قائمة مراجع",
    ),
    (
        "وقال المحكّم إن الاتفاق المتفق عليه سلفًا ملزم للطرفين.",
        None, None, "«المتفق عليه» بسابقة ملزوقة",
    ),
]

# عبارات لازم تتلاقى حتى لو قبلها سابقة ملزوقة (و/ف/ب/ك/ل)
PROCLITIC_CASES = [
    ("وقال تعالى: ﴿إن الله يأمر بالعدل والإحسان﴾", "quran"),
    ("فقال رسول الله صلى الله عليه وسلم: «إنما الأعمال بالنيات»", "hadith"),
    ("وروى البخاري في صحيحه هذا الخبر.", None),
]


def main() -> int:
    failures: list[str] = []

    print("=" * 68)
    print("الحالات الإيجابية")
    print("=" * 68)
    for text, want_kind, want_confidence, label in CASES:
        if want_kind is None:
            continue
        detection = sacred.detect(text)
        kinds = detection.kinds
        ok = want_kind in kinds
        confidence = "—"
        if ok:
            levels = [s.confidence for s in detection.spans if s.kind == want_kind]
            confidence = "certain" if "certain" in levels else "likely"
            ok = confidence == want_confidence

        print(f"  {'✓' if ok else '✗'} {label}")
        print(f"      {text[:58]}")
        print(f"      كُشف: {sorted(kinds) or 'لا شيء'} · ثقة: {confidence}"
              f" (متوقع {want_kind}/{want_confidence})")
        if detection.found:
            print(f"      السبب: {detection.note()[:78]}")
        if not ok:
            failures.append(
                f"{label}: متوقع {want_kind}/{want_confidence}، "
                f"طلع {sorted(kinds) or 'لا شيء'}/{confidence}"
            )

    print()
    print("=" * 68)
    print("الحالات السلبية — نص عادي مالوش يتقفل")
    print("=" * 68)
    for text, want_kind, _want_confidence, label in CASES:
        if want_kind is not None:
            continue
        detection = sacred.detect(text)
        ok = not detection.certain
        clean = not detection.found
        mark = "✓" if clean else ("~" if ok else "✗")
        print(f"  {mark} {label}")
        print(f"      {text[:58]}")
        if detection.found:
            print(f"      كُشف: {sorted(detection.kinds)} · "
                  f"{detection.note()[:66]}")
        if not ok:
            failures.append(
                f"{label}: اتقفل بالغلط ({sorted(detection.kinds)}) — "
                "قفل نص عادي بيوقّف الشغل"
            )

    # ---------- السوابق الملزوقة ----------
    print()
    print("=" * 68)
    print("سوابق ملزوقة (و/ف/ب/ك/ل)")
    print("=" * 68)
    for text, want_kind in PROCLITIC_CASES:
        detection = sacred.detect(text)
        ok = want_kind is None or want_kind in detection.kinds
        print(f"  {'✓' if ok else '✗'} {text[:52]}")
        print(f"      كُشف: {sorted(detection.kinds) or 'لا شيء'}")
        if not ok:
            failures.append(
                f"سابقة ملزوقة فوّتت الكشف: {text[:36]} (متوقع {want_kind})"
            )

    # ---------- نسبة التشكيل ----------
    print()
    print("=" * 68)
    print("نسبة التشكيل")
    print("=" * 68)
    ratios = [
        ("وَٱلْعَصْرِ إِنَّ ٱلْإِنسَٰنَ لَفِى خُسْرٍ", 0.35, True),
        ("يلتزم الطرف الأول بتقديم الخدمات الاستشارية المتفق عليها", 0.35, False),
        ("قال المدير إن الشركة حققت أرباحًا قياسية هذا العام", 0.35, False),
    ]
    for text, threshold, should_exceed in ratios:
        ratio = sacred.vocalization_ratio(text)
        ok = (ratio >= threshold) == should_exceed
        print(f"  {'✓' if ok else '✗'} {ratio:5.0%}  {text[:46]}")
        if not ok:
            failures.append(f"نسبة تشكيل غلط ({ratio:.0%}): {text[:34]}")

    # ---------- الفحص الجماعي ----------
    print()
    print("=" * 68)
    print("الفحص الجماعي")
    print("=" * 68)
    texts = [case[0] for case in CASES]
    found = sacred.scan(texts)
    expected = sum(1 for case in CASES if case[1] is not None)
    print(f"  مقاطع: {len(texts)} · فيها كشف: {len(found)} "
          f"(المتوقع على الأقل {expected})")
    if len(found) < expected:
        failures.append("الفحص الجماعي فوّت مقاطع الكشف فيها مؤكَّد")

    locked = [i for i, d in found.items() if d.certain]
    print(f"  هيتقفل: {len(locked)} مقطع")
    print(f"  هيتعلّم بس: {len(found) - len(locked)} مقطع")

    print("\n" + "=" * 68)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: كشف النص المقدّس سليم ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
