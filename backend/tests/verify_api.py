"""التحقق من ربط المفتاح والاتصال الفعلي بالـ API.

بيتدرّج من الأرخص للأغلى:
  1. تحميل المفتاح من .env (مجاني)
  2. عدّ التوكنز — نداء مجاني بيتحقق من صلاحية المفتاح
  3. ترجمة حقيقية لمقاطع قليلة (بضعة أعشار السنت)
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.tools.translator.engine import (  # noqa: E402
    ClaudeEngine,
    SegmentInput,
    validate_translation,
)
from app.tools.translator.formats.base import strip_tags  # noqa: E402

SAMPLES = [
    SegmentInput(id="s1", source="المادة 1. يلتزم الطرف الأول بتقديم الخدمات الاستشارية المتفق عليها."),
    SegmentInput(id="s2", source="تبلغ قيمة العقد 150.000 ريال سعودي شاملة ضريبة القيمة المضافة."),
    SegmentInput(
        id="s3",
        source="<g1>أُبرم هذا العقد في </g1><g2>اليوم الخامس عشر من شهر مارس</g2><g3> بين الطرفين.</g3>",
    ),
]


def main() -> int:
    failures: list[str] = []

    # ---------- 1) تحميل المفتاح ----------
    print("=== 1) المفتاح ===")
    key = settings.anthropic_api_key
    if not key:
        print("  ✗ المفتاح مش متحمّل من .env")
        print("    تأكد إن السطر شكله كده بالظبط (من غير مسافات ولا علامات تنصيص):")
        print("    ANTHROPIC_API_KEY=sk-ant-...")
        return 1

    print(f"  محمّل: {key[:14]}…{key[-4:]}  (الطول {len(key)})")
    print(f"  الموديل الافتراضي: {settings.default_model}")
    print(f"  موديل المستندات القانونية: {settings.legal_model}")

    if not key.startswith("sk-ant-"):
        failures.append("شكل المفتاح غير معتاد — المفروض يبدأ بـ sk-ant-")

    # ---------- 2) نداء مجاني للتحقق من الصلاحية ----------
    print("\n=== 2) التحقق من الاتصال (عدّ التوكنز — مجاني) ===")
    try:
        engine = ClaudeEngine(domain="legal", glossary=[("الطرف الأول", "First Party")])
        tokens = engine.count_tokens(SAMPLES)
        print(f"  ✓ الاتصال شغّال — {tokens:,} توكن إدخال للعيّنة")
        print(f"  الموديل: {engine.model} · مستوى الجهد: {engine.effort}")
        print(f"  حجم تعليمات النظام: {len(engine.system_prompt):,} حرف")
    except Exception as exc:  # noqa: BLE001
        name = type(exc).__name__
        print(f"  ✗ فشل الاتصال: {name}: {exc}")
        if "authentication" in str(exc).lower() or name == "AuthenticationError":
            print("    المفتاح مرفوض — اتأكد إنه صح ومفعّل في الكونسول")
        elif name == "APIConnectionError":
            print("    مشكلة شبكة — اتأكد من الإنترنت أو البروكسي")
        return 1

    # ---------- 3) ترجمة حقيقية ----------
    print("\n=== 3) ترجمة حقيقية للعيّنة ===")
    result = engine.translate(SAMPLES)

    for warning in result.warnings:
        print(f"  ! {warning}")

    for sample in SAMPLES:
        target = result.translations.get(sample.id)
        print(f"\n  [{sample.id}]")
        print(f"    عربي     : {strip_tags(sample.source)}")
        if target is None:
            print("    إنجليزي  : (مارجعش)")
            failures.append(f"المقطع {sample.id} مارجعش من النموذج")
            continue
        print(f"    إنجليزي  : {strip_tags(target)}")

        problems = validate_translation(sample.source, target)
        if problems:
            print(f"    تنبيهات  : {problems}")
        else:
            print("    الفحوصات : سليمة ✓")

    # فحوصات محدَّدة على العيّنة
    s2 = result.translations.get("s2", "")
    if s2 and "150" not in s2:
        failures.append("الرقم 150.000 ضاع في الترجمة")

    s3 = result.translations.get("s3", "")
    if s3:
        from app.tools.translator.formats.base import tags_in

        if tags_in(s3) != {"1", "2", "3"}:
            failures.append(f"وسوم التنسيق اتغيّرت: {sorted(tags_in(s3))}")

    # ---------- 4) التكلفة ----------
    usage = result.usage
    print("\n=== 4) الاستهلاك والتكلفة ===")
    print(f"  إدخال={usage.input_tokens:,}  إخراج={usage.output_tokens:,}")
    print(f"  كتابة للكاش={usage.cache_write_tokens:,}  "
          f"قراءة من الكاش={usage.cache_read_tokens:,}")
    print(f"  التكلفة: ${usage.cost_usd:.6f}")

    if usage.input_tokens == 0:
        failures.append("مافيش استهلاك مسجّل — الحاسبة مش هتشتغل")

    # ---------- 5) الكاش في النداء التاني ----------
    print("\n=== 5) التخزين المؤقت (نداء تاني بنفس التعليمات) ===")
    second = engine.translate(
        [SegmentInput(id="s4", source="مدة العقد اثنا عشر شهرًا من تاريخ التوقيع.")]
    )
    print(f"  قراءة من الكاش: {second.usage.cache_read_tokens:,} توكن")
    print(f"  تكلفة النداء: ${second.usage.cost_usd:.6f}")
    if second.usage.cache_read_tokens > 0:
        print("  ✓ التخزين المؤقت شغّال — التعليمات بتتقرا بعُشر السعر")
    else:
        print("  ملاحظة: مافيش قراءة من الكاش — التعليمات أقصر من الحد الأدنى")
        print("           (مش خطأ؛ بيحصل مع المصطلحات القليلة)")

    total = usage.cost_usd + second.usage.cost_usd
    print(f"\n  إجمالي تكلفة الاختبار ده: ${total:.6f}")

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)} مشكلة")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: المفتاح مربوط والترجمة الحقيقية شغّالة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
