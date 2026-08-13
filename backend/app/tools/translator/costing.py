"""حاسبة التكلفة — تقدير مسبق + احتساب فعلي.

كل نداء API بيتسجّل بتفاصيله، والتكلفة بتتحسب من جدول أسعار في
ملف الإعدادات (مش مكتوبة في الكود) عشان تتحدّث من غير تعديل برمجي.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from app.core.config import (
    BATCH_DISCOUNT,
    CACHE_READ_MULTIPLIER,
    CACHE_WRITE_MULTIPLIER,
    MODEL_PRICING,
    settings,
)
from app.tools.translator.langs import tokens_per_char


@dataclass
class Rates:
    """أسعار المليون توكن لموديل معيّن في تاريخ معيّن."""

    model: str
    input_per_mtok: float
    output_per_mtok: float
    label: str
    promo_active: bool = False


def rates_for(model: str, on: date | None = None) -> Rates:
    """أسعار الموديل، مع مراعاة العروض التعريفية المؤقتة."""
    pricing = MODEL_PRICING.get(model)
    if pricing is None:
        raise ValueError(f"مفيش أسعار مسجّلة للموديل: {model}")

    on = on or date.today()
    input_price = float(pricing["input"])
    output_price = float(pricing["output"])
    promo_active = False

    promo_ends = pricing.get("promo_ends")
    if promo_ends:
        if on <= date.fromisoformat(str(promo_ends)):
            promo_active = True
        else:
            # العرض خلص — نرجع للسعر الأساسي
            input_price = float(pricing.get("input_after_promo", input_price))
            output_price = float(pricing.get("output_after_promo", output_price))

    return Rates(
        model=model,
        input_per_mtok=input_price,
        output_per_mtok=output_price,
        label=str(pricing.get("label", model)),
        promo_active=promo_active,
    )


def compute_cost(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    is_batch: bool = False,
    on: date | None = None,
) -> float:
    """تكلفة نداء واحد بالدولار.

    التوكنز المقروءة من الكاش بتتكلّف عُشر سعر الإدخال، والمكتوبة
    للكاش بتتكلّف 1.25 ضعف. الـ Batch API بيخصم 50% من الإجمالي.
    """
    rates = rates_for(model, on)
    million = 1_000_000

    cost = (
        input_tokens * rates.input_per_mtok
        + cache_read_tokens * rates.input_per_mtok * CACHE_READ_MULTIPLIER
        + cache_write_tokens * rates.input_per_mtok * CACHE_WRITE_MULTIPLIER
        + output_tokens * rates.output_per_mtok
    ) / million

    if is_batch:
        cost *= 1 - BATCH_DISCOUNT

    return round(cost, 6)


# ---------------------------------------------------------------------------
# التقدير المسبق
# ---------------------------------------------------------------------------
# العربية أكثف بالتوكن من الإنجليزية. النسب دي تقديرية أولية وبتتعدّل
# تلقائيًا بعد أول ملف من القياس الفعلي عبر count_tokens.
_CONTEXT_OVERHEAD_RATIO = 1.25  # سياق المقاطع المجاورة + هيكل الطلب
# نسبة طول النص المترجَم لطول المصدر بالحروف (الإنجليزية أطول بالحروف
# من العربية لنفس المعنى، والعكس صحيح)
_CHAR_EXPANSION = {("ar", "en"): 1.2, ("en", "ar"): 0.85}

# حجم تعليمات النظام (مقيس فعليًا: 1577 عام → 1990 قانوني بمصطلحات)
_SYSTEM_TOKENS = 1800


@dataclass
class Estimate:
    words: int
    chars: int
    pages: int
    segments: int
    input_tokens: int
    output_tokens: int
    options: list[dict] = field(default_factory=list)

    @property
    def cheapest(self) -> dict | None:
        return min(self.options, key=lambda o: o["cost_usd"]) if self.options else None


def estimate_project(
    words: int,
    chars: int,
    pages: int,
    segments: int,
    models: list[str] | None = None,
    reuse_ratio: float = 0.0,
    source_lang: str = "ar",
    target_lang: str = "en",
) -> Estimate:
    """تقدير التكلفة قبل التشغيل — المستخدم يوافق قبل ما يتصرف قرش.

    reuse_ratio: نسبة المقاطع المتوقّع تغطيتها من ذاكرة الترجمة (ببلاش).
    """
    models = models or [settings.default_model, settings.legal_model]
    billable = max(0.0, 1.0 - reuse_ratio)

    billable_chars = chars * billable

    # كثافة التوكن بتختلف جذريًا بين اللغات: العربية ~0.42 توكن/حرف
    # والإنجليزية ~0.25. تقدير باتجاه واحد بيطلع غلط في الاتجاه التاني.
    source_density = tokens_per_char(source_lang)
    target_density = tokens_per_char(target_lang)
    expansion = _CHAR_EXPANSION.get(
        (source_lang.split("-")[0], target_lang.split("-")[0]), 1.0
    )

    content_in = int(billable_chars * source_density * _CONTEXT_OVERHEAD_RATIO)
    content_out = int(billable_chars * expansion * target_density)

    # عدد الدفعات بيحدد تكلفة التعليمات، وهي بند كبير في الفاتورة
    batch_count = max(1, -(-int(billable_chars) // settings.batch_char_budget))
    per_batch_in = content_in // batch_count
    per_batch_out = content_out // batch_count

    options: list[dict] = []
    for model in models:
        try:
            rates = rates_for(model)
        except ValueError:
            continue

        # فوري: أول دفعة بتكتب التعليمات في الكاش، والباقي بيقراها بعُشر السعر
        realtime = compute_cost(
            model,
            input_tokens=per_batch_in,
            output_tokens=per_batch_out,
            cache_write_tokens=_SYSTEM_TOKENS,
        )
        if batch_count > 1:
            realtime += (batch_count - 1) * compute_cost(
                model,
                input_tokens=per_batch_in,
                output_tokens=per_batch_out,
                cache_read_tokens=_SYSTEM_TOKENS,
            )

        # مجمّع: خصم 50% لكن كل طلب بيكتب نسخته من التعليمات (مفيش قراءة)
        batched = batch_count * compute_cost(
            model,
            input_tokens=per_batch_in,
            output_tokens=per_batch_out,
            cache_write_tokens=_SYSTEM_TOKENS,
            is_batch=True,
        )

        realtime = round(realtime, 6)
        batched = round(batched, 6)
        saving = round((1 - batched / realtime) * 100, 1) if realtime else 0.0

        options.append(
            {
                "model": model,
                "label": rates.label,
                "promo_active": rates.promo_active,
                "cost_usd": realtime,
                "cost_usd_batch": batched,
                # الوفر الحقيقي بيتآكل كل ما الملف يكبر: الوضع الفوري
                "batch_saving_pct": saving,
                "batches": batch_count,
                "cost_per_page": round(realtime / pages, 4) if pages else 0.0,
                "cost_per_word": round(realtime / words, 6) if words else 0.0,
            }
        )

    return Estimate(
        words=words,
        chars=chars,
        pages=pages,
        segments=segments,
        input_tokens=content_in + _SYSTEM_TOKENS * batch_count,
        output_tokens=content_out,
        options=options,
    )


def pages_from_words(words: int) -> int:
    """عدد صفحات تقريبي لما الملف مايكونش فيه عدد صفحات حقيقي."""
    return max(1, round(words / settings.words_per_page))
