"""اختبار الـ Batch API — نصف السعر مقابل تنفيذ غير فوري.

بيستهلك API. الدفعات المجمّعة عادة بتخلص في دقايق للطلبات الصغيرة،
والحد الأقصى الرسمي 24 ساعة.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.translator.engine import (  # noqa: E402
    ClaudeBatchEngine,
    ClaudeEngine,
    SegmentInput,
    validate_translation,
)
from app.tools.translator.formats.base import strip_tags  # noqa: E402

BATCHES = [
    (
        [
            SegmentInput(id="a1", source="المادة 1. يلتزم الطرف الأول بتقديم الخدمات."),
            SegmentInput(id="a2", source="مدة العقد اثنا عشر شهرًا."),
        ],
        "",
        "",
    ),
    (
        [
            SegmentInput(id="b1", source="تبلغ قيمة العقد 75.000 ريال."),
            SegmentInput(id="b2", source="يحق للطرفين إنهاء العقد بإشعار كتابي."),
        ],
        "",
        "",
    ),
]

GLOSSARY = [("الطرف الأول", "First Party")]


def main() -> int:
    failures: list[str] = []

    engine = ClaudeBatchEngine(
        domain="legal", glossary=GLOSSARY, poll_seconds=10, max_wait_hours=1
    )
    print(f"=== الدفعات المجمّعة ({engine.model}) ===")
    print(f"  {len(BATCHES)} دفعة · {sum(len(b[0]) for b in BATCHES)} مقطع")

    def report(phase: str, done: int, total: int, batch_id: str) -> None:
        print(f"  [{phase}] {done}/{total}  ({batch_id})")

    start = time.monotonic()
    results = engine.translate_many(BATCHES, progress=report)
    elapsed = time.monotonic() - start

    print(f"\n  الزمن: {elapsed:.0f} ثانية")

    total_cost = 0.0
    translated = 0
    for index, result in enumerate(results):
        segments = BATCHES[index][0]
        for warning in result.warnings:
            print(f"  ! {warning}")
        for segment in segments:
            target = result.translations.get(segment.id)
            print(f"\n  [{segment.id}]")
            print(f"    ع: {strip_tags(segment.source)}")
            if target is None:
                print("    E: (مارجعش)")
                failures.append(f"المقطع {segment.id} مارجعش")
                continue
            print(f"    E: {strip_tags(target)}")
            problems = validate_translation(segment.source, target)
            if problems:
                print(f"    ⚠ {problems}")
            translated += 1
        total_cost += result.usage.cost_usd

    from app.tools.translator.costing import compute_cost

    tokens_in = sum(r.usage.input_tokens for r in results)
    tokens_out = sum(r.usage.output_tokens for r in results)
    cache_write = sum(r.usage.cache_write_tokens for r in results)
    cache_read = sum(r.usage.cache_read_tokens for r in results)
    model = ClaudeEngine(domain="legal", glossary=GLOSSARY).model

    print(f"\n=== الاستهلاك ===")
    print(f"  إدخال={tokens_in:,} إخراج={tokens_out:,}")
    print(f"  كتابة للكاش={cache_write:,} قراءة من الكاش={cache_read:,}")

    # مقارنة عادلة: **نفس** ملف الاستهلاك بالظبط، بالخصم وبدونه
    same_no_discount = compute_cost(
        model,
        input_tokens=tokens_in,
        output_tokens=tokens_out,
        cache_read_tokens=cache_read,
        cache_write_tokens=cache_write,
        is_batch=False,
    )

    print(f"\n=== التكلفة ===")
    print(f"  بالدفعات المجمّعة: ${total_cost:.6f}")
    print(f"  نفس الاستهلاك بدون خصم: ${same_no_discount:.6f}")
    if same_no_discount > 0:
        print(f"  الخصم المطبَّق: {(1 - total_cost / same_no_discount) * 100:.0f}%")

    # الحقيقة العملية: الدفعات المجمّعة بتفقد فايدة التخزين المؤقت،
    # لأن كل طلب بيكتب نسخته من التعليمات بدل ما يقرا نسخة واحدة.
    if cache_read == 0 and cache_write > 0:
        print("\n  ⚠ صفر قراءة من الكاش — كل طلب كتب نسخته من التعليمات.")
        print("     يعني الخصم 50% بيتآكل جزء منه في تكرار كتابة الكاش.")

    if translated < sum(len(b[0]) for b in BATCHES):
        failures.append("مقاطع ماترجعتش من الدفعة المجمّعة")
    if total_cost <= 0:
        failures.append("التكلفة صفر — سجلّ الاستهلاك مش شغّال")
    elif abs(total_cost / same_no_discount - 0.5) > 0.02:
        failures.append(
            f"الخصم مش 50%: ${total_cost:.6f} مقابل ${same_no_discount:.6f}"
        )

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: الدفعات المجمّعة سليمة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
