"""مقارنة تكلفة أوضاع التشغيل — حساب فقط، بدون أي نداء API.

السؤال العملي: إمتى «نصف السعر» بيوفّر فعلًا؟

الجواب مش بديهي. الدفعات المجمّعة بتاخد خصم 50%، لكنها بتفقد فايدة
التخزين المؤقت: في التنفيذ الفوري التعليمات بتتكتب مرة واحدة والباقي
بيقراها بعُشر السعر، أما في الدفعات المجمّعة كل طلب بيكتب نسخته
بـ 1.25 ضعف. كل ما التعليمات تكبر بالنسبة للمحتوى، الفرق ده يكبر.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.tools.translator.costing import compute_cost  # noqa: E402

# قياسات حقيقية من التشغيل الفعلي
SYSTEM_TOKENS = 1850      # تعليمات المجال القانوني
CONTENT_IN = 400          # مقاطع المصدر لكل دفعة
CONTENT_OUT = 330         # الترجمة لكل دفعة


def sync_cost(model: str, batches: int) -> float:
    """فوري: أول دفعة بتكتب الكاش، والباقي بيقراه."""
    total = compute_cost(
        model,
        input_tokens=CONTENT_IN,
        output_tokens=CONTENT_OUT,
        cache_write_tokens=SYSTEM_TOKENS,
    )
    if batches > 1:
        total += (batches - 1) * compute_cost(
            model,
            input_tokens=CONTENT_IN,
            output_tokens=CONTENT_OUT,
            cache_read_tokens=SYSTEM_TOKENS,
        )
    return total


def batch_cost(model: str, batches: int, cache_hit_rate: float = 0.0) -> float:
    """مجمّع: خصم 50%، لكن الكاش غالبًا مابيتقراش."""
    hits = int(batches * cache_hit_rate)
    misses = batches - hits
    total = misses * compute_cost(
        model,
        input_tokens=CONTENT_IN,
        output_tokens=CONTENT_OUT,
        cache_write_tokens=SYSTEM_TOKENS,
        is_batch=True,
    )
    total += hits * compute_cost(
        model,
        input_tokens=CONTENT_IN,
        output_tokens=CONTENT_OUT,
        cache_read_tokens=SYSTEM_TOKENS,
        is_batch=True,
    )
    return total


def main() -> int:
    model = settings.default_model
    print(f"الموديل: {model}")
    print(f"التعليمات: {SYSTEM_TOKENS} توكن · المحتوى: {CONTENT_IN} دخل / "
          f"{CONTENT_OUT} خرج لكل دفعة\n")

    header = f"{'الدفعات':>8} {'الصفحات':>8} {'فوري':>11} {'مجمّع':>11} {'الفرق':>9}"
    print(header)
    print("-" * len(header))

    for batches in (1, 3, 10, 25, 75, 200):
        pages = round(batches * 1.4)
        immediate = sync_cost(model, batches)
        batched = batch_cost(model, batches)
        delta = (1 - batched / immediate) * 100 if immediate else 0
        marker = "أرخص" if delta > 0 else "أغلى"
        print(f"{batches:>8} {pages:>8} {immediate:>10.4f}$ {batched:>10.4f}$ "
              f"{abs(delta):>7.0f}% {marker}")

    print("\nالخلاصة:")
    print("  الدفعات المجمّعة بتوفّر فعلًا لما المحتوى يغلب على التعليمات.")
    print("  مع ملف صغير أو تعليمات ضخمة (مصطلحات كتير)، التنفيذ الفوري")
    print("  مع الكاش بيطلع أرخص — والفرق مش بسيط.")

    # نقطة التعادل
    for batches in range(1, 500):
        if batch_cost(model, batches) < sync_cost(model, batches):
            print(f"\n  نقطة التعادل: {batches} دفعة (~{round(batches*1.4)} صفحة)")
            break
    else:
        print("\n  مفيش نقطة تعادل بالأرقام دي — الفوري أرخص دايمًا.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
