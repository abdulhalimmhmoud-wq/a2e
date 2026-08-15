"""اختبار المجال الشرعي: قواعد الصياغة والمصطلحات المزروعة.

مفيش أي نداء API — بنفحص الـ prompt نفسه والمصطلحات في القاعدة.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.models import GlossaryTerm  # noqa: E402
from app.tools.translator import prompts, tm  # noqa: E402
from app.tools.translator.seed_terms import (  # noqa: E402
    RELIGIOUS_TERMS,
    seed_religious_terms,
)

DOMAIN = "religious"


def main() -> int:  # noqa: C901
    failures: list[str] = []
    init_db()

    # ---------- 1) المجال مسجَّل ----------
    print("=== 1) تسجيل المجال ===")
    print(f"  في قائمة المجالات: {DOMAIN in prompts.DOMAIN_LABELS}")
    print(f"  الاسم: {prompts.DOMAIN_LABELS.get(DOMAIN)}")
    print(f"  مستوى الجهد: {prompts.DOMAIN_EFFORT.get(DOMAIN)}")

    if DOMAIN not in prompts.DOMAIN_LABELS:
        failures.append("المجال الشرعي مش في قائمة المجالات — مش هيظهر للمستخدم")
    if prompts.DOMAIN_EFFORT.get(DOMAIN) != "high":
        failures.append("المجال الشرعي المفروض جهده عالي زي القانوني")

    # ---------- 2) قواعد الصياغة ----------
    print("\n=== 2) قواعد الصياغة في الـ prompt ===")
    system = prompts.build_system_prompt(
        source_lang="ar", target_lang="en", domain=DOMAIN, glossary=[]
    )
    required = [
        ("Quranic verses and hadith", "منع ترجمة الآيات والأحاديث"),
        # بالمدّة زي ما هي مكتوبة في القاعدة — "riba" بالـ ASCII
        # مش موجودة جوه "ribā"
        ("ribā", "الربا"),
        ("zak", "الزكاة"),
        ("makr", "المكروه مقابل المحرَّم"),
        ("Allah", "لفظ الجلالة"),
        ("narration", "سلسلة الرواة"),
    ]
    for needle, label in required:
        present = needle.lower() in system.lower()
        print(f"  {'✓' if present else '✗'} {label}")
        if not present:
            failures.append(f"قاعدة ناقصة في الـ prompt: {label}")

    print(f"  طول الـ prompt: {len(system)} حرف")

    # الـ prompt لازم يعدّي الحد الأدنى للكاش (1024 توكن ≈ 3000 حرف)
    if len(system) < 3000:
        failures.append(
            f"الـ prompt قصير ({len(system)} حرف) — تحت حد الكاش الأدنى "
            "فكل نداء هيتحاسب كامل"
        )

    # ---------- 3) المصطلحات المزروعة ----------
    print("\n=== 3) زرع المصطلحات ===")
    db = SessionLocal()
    try:
        before = db.execute(
            select(GlossaryTerm).where(GlossaryTerm.domain == DOMAIN)
        ).scalars().all()
        added = seed_religious_terms(db)
        after = db.execute(
            select(GlossaryTerm).where(GlossaryTerm.domain == DOMAIN)
        ).scalars().all()

        print(f"  قبل: {len(before)} · اتزرع: {added} · بعد: {len(after)}")
        if not after:
            failures.append("مافيش مصطلحات شرعية بعد الزرع")

        # الزرع تاني مايكررش
        again = seed_religious_terms(db)
        total = db.execute(
            select(GlossaryTerm).where(GlossaryTerm.domain == DOMAIN)
        ).scalars().all()
        print(f"  زرع تاني: {again} مصطلح · الإجمالي: {len(total)}")
        if again or len(total) != len(after):
            failures.append("الزرع التاني كرّر المصطلحات")

        # ---------- 4) الفروق اللي الإنجليزية بتدهسها ----------
        print("\n=== 4) الدرجات المتمايزة ===")
        by_source = {t.source_term: t.target_term for t in total}
        pairs = [("حرام", "مكروه"), ("فرض", "مندوب"), ("صحيح", "حسن")]
        for first, second in pairs:
            a, b = by_source.get(first), by_source.get(second)
            ok = a and b and a != b
            print(f"  {'✓' if ok else '✗'} {first}={a} · {second}={b}")
            if not ok:
                failures.append(f"الدرجتان {first}/{second} مش متمايزتين")

        # الربا والزكاة مش المفروض يترجموا لكلمة إنجليزية عامة
        for term, forbidden in (("الربا", "interest"), ("الزكاة", "charity")):
            rendering = (by_source.get(term) or "").lower()
            ok = forbidden not in rendering
            print(f"  {'✓' if ok else '✗'} {term} = {by_source.get(term)}")
            if not ok:
                failures.append(f"{term} اتترجم لـ {forbidden} — المعنى الشرعي بيضيع")

        # ---------- 5) التحميل مع المجال ----------
        print("\n=== 5) تحميل المصطلحات للمشروع ===")
        glossary = tm.load_glossary(db, domain=DOMAIN, project_id=None)
        print(f"  اتحمّل: {len(glossary)} مصطلح")
        sources = [source for source, _ in glossary]
        if "الربا" not in sources:
            failures.append("المصطلحات الشرعية ماوصلتش لمحمّل المشروع")

        # الأطول الأول عشان «مقاصد الشريعة» تسبق «الشريعة»
        lengths = [len(source) for source in sources]
        if lengths != sorted(lengths, reverse=True):
            failures.append("المصطلحات مش مرتّبة بالأطول أولًا")

        # ---------- 6) فحص المطابقة ----------
        print("\n=== 6) فحص استخدام المصطلح ===")
        violations = tm.check_glossary(
            "لا يجوز التعامل بالربا في هذا العقد.",
            "Dealing in interest is not permitted under this contract.",
            glossary,
        )
        print(f"  «الربا» مترجَمة كـ interest: {len(violations)} مخالفة")
        if not violations:
            failures.append(
                "ترجمة «الربا» بـ interest عدّت من غير تحذير رغم إنها في القاعدة"
            )

        correct = tm.check_glossary(
            "لا يجوز التعامل بالربا في هذا العقد.",
            "Dealing in ribā is not permitted under this contract.",
            glossary,
        )
        print(f"  «الربا» مترجَمة كـ ribā: {len(correct)} مخالفة")
        if correct:
            failures.append(f"الترجمة الصحيحة اتعلّمت كمخالفة: {correct}")

    finally:
        db.close()

    print(f"\n  إجمالي المصطلحات المعرَّفة في الملف: {len(RELIGIOUS_TERMS)}")

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: المجال الشرعي سليم ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
