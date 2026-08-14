"""اختبار محرّك DeepL بمحاكاة محلية — بدون مفتاح وبدون أي نداء شبكة.

بنستبدل عميل DeepL بواحد وهمي بيسجّل المعاملات المرسلة، فنقدر نتأكد
إن المحرّك بيبعت الإعدادات الصح (وسوم XML، السياق، تعليمات المجال،
قاعدة المصطلحات) من غير ما نستهلك أي حروف من الباقة.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import deepl  # noqa: E402

from app.tools.translator.engine import SegmentInput  # noqa: E402

SEGMENTS = [
    SegmentInput(id="s1", source="المادة 1. يلتزم الطرف الأول بتقديم الخدمات."),
    SegmentInput(id="s2", source="تبلغ قيمة العقد 150.000 ريال سعودي."),
    SegmentInput(
        id="s3",
        source="<g1>أُبرم هذا العقد في </g1><g2>اليوم الخامس عشر من مارس</g2>",
    ),
]

GLOSSARY = [("الطرف الأول", "First Party"), ("الطرف الثاني", "Second Party")]


class FakeGlossaryInfo:
    def __init__(self, name: str, glossary_id: str) -> None:
        self.name = name
        self.glossary_id = glossary_id


class FakeResult:
    def __init__(self, text: str) -> None:
        self.text = text
        self.detected_source_lang = "AR"


class FakeClient:
    """عميل DeepL وهمي بيسجّل كل استدعاء بدل ما يبعته للشبكة."""

    instances: list["FakeClient"] = []

    def __init__(self, key: str) -> None:
        self.key = key
        self.calls: list[dict] = []
        self.glossaries: list[FakeGlossaryInfo] = []
        self.created: list[dict] = []
        FakeClient.instances.append(self)

    def translate_text(self, texts, **options):
        self.calls.append({"texts": list(texts), "options": options})
        # ترجمة وهمية بتحافظ على الوسوم زي ما DeepL بيعمل
        return [FakeResult(f"[DE]{t}") for t in texts]

    def list_glossaries(self):
        return list(self.glossaries)

    def create_glossary(self, name, source_lang, target_lang, entries):
        self.created.append(
            {
                "name": name,
                "source_lang": source_lang,
                "target_lang": target_lang,
                "entries": dict(entries),
            }
        )
        info = FakeGlossaryInfo(name, f"gl-{len(self.created)}")
        self.glossaries.append(info)
        return info


def build_engine(**kwargs):
    from app.tools.translator.deepl_engine import DeepLEngine

    defaults = dict(
        source_lang="ar",
        target_lang="en",
        domain="legal",
        style_notes="احتفظ بأسماء الشركات كما هي",
        glossary=GLOSSARY,
        api_key="fake-key:fx",
    )
    defaults.update(kwargs)
    return DeepLEngine(**defaults)


def main() -> int:
    failures: list[str] = []

    # نستبدل العميل الحقيقي بالوهمي
    original = deepl.DeepLClient
    deepl.DeepLClient = FakeClient
    try:
        # ---------- 1) التعليمات ضمن حدود DeepL ----------
        from app.tools.translator.deepl_engine import (
            _MAX_INSTRUCTION_CHARS,
            _MAX_INSTRUCTIONS,
            _build_instructions,
            _map_source,
            _map_target,
        )

        print("=== 1) تعليمات المجال ===")
        for domain in ("legal", "medical", "scientific", "technical", "general"):
            items = _build_instructions(domain, "ملاحظة أسلوبية للاختبار")
            longest = max((len(i) for i in items), default=0)
            status = "✓" if len(items) <= _MAX_INSTRUCTIONS and longest <= _MAX_INSTRUCTION_CHARS else "✗"
            print(f"  {status} {domain:11} {len(items)} تعليمة · أطولها {longest} حرف")
            if len(items) > _MAX_INSTRUCTIONS:
                failures.append(f"{domain}: تعليمات أكتر من {_MAX_INSTRUCTIONS}")
            if longest > _MAX_INSTRUCTION_CHARS:
                failures.append(f"{domain}: تعليمة أطول من {_MAX_INSTRUCTION_CHARS} حرف")

        # ---------- 2) رموز اللغات ----------
        print("\n=== 2) رموز اللغات ===")
        cases = [("ar", "AR", "AR"), ("en", "EN", "EN-US")]
        for code, want_source, want_target in cases:
            got_source, got_target = _map_source(code), _map_target(code)
            ok = got_source == want_source and got_target == want_target
            print(f"  {'✓' if ok else '✗'} {code}: مصدر={got_source} هدف={got_target}")
            if not ok:
                failures.append(f"رمز اللغة {code} غلط: {got_source}/{got_target}")

        # الإنجليزية كهدف لازم تبقى بصيغة إقليمية وإلا DeepL بيرفض
        if _map_target("en") == "EN":
            failures.append("الإنجليزية كهدف لازم تكون EN-US مش EN")

        # ---------- 3) الترجمة والمعاملات المرسلة ----------
        print("\n=== 3) الترجمة ===")
        engine = build_engine()
        result = engine.translate(
            SEGMENTS, context_before="سياق سابق", context_after="سياق لاحق"
        )

        client = FakeClient.instances[-1]
        call = client.calls[0]
        options = call["options"]

        print(f"  مقاطع مرسلة: {len(call['texts'])} · مترجمة: {len(result.translations)}")
        for key in ("tag_handling", "target_lang", "source_lang", "context"):
            print(f"    {key:16} = {str(options.get(key))[:48]}")
        print(f"    custom_instructions = {len(options.get('custom_instructions', []))} تعليمة")
        print(f"    glossary         = {options.get('glossary')}")

        if len(result.translations) != len(SEGMENTS):
            failures.append("عدد الترجمات مش مطابق لعدد المقاطع")
        if options.get("tag_handling") != "xml":
            failures.append("معالجة الوسوم مش مفعّلة — وسوم التنسيق هتضيع")
        if options.get("target_lang") != "EN-US":
            failures.append(f"لغة الهدف غلط: {options.get('target_lang')}")
        if not options.get("context"):
            failures.append("السياق مااتبعتش — وهو مجاني في فاتورة DeepL")
        if not options.get("custom_instructions"):
            failures.append("تعليمات المجال مااتبعتتش")
        if not options.get("preserve_formatting"):
            failures.append("preserve_formatting مش مفعّل")

        # الترتيب هو رابط المطابقة — مفيش معرّفات
        if result.translations.get("s1") != f"[DE]{SEGMENTS[0].source}":
            failures.append("ترتيب الردود مش مطابق للمقاطع المرسلة")

        # ---------- 4) قاعدة المصطلحات ----------
        print("\n=== 4) قاعدة المصطلحات ===")
        print(f"  اتنشأت: {len(client.created)}")
        if client.created:
            created = client.created[0]
            print(f"    الاسم: {created['name']}")
            print(f"    اللغات: {created['source_lang']} → {created['target_lang']}")
            print(f"    مصطلحات: {len(created['entries'])}")
            if created["target_lang"] != "EN":
                failures.append(
                    f"لغة هدف المصطلحات لازم تبقى بدون إقليم: {created['target_lang']}"
                )
        else:
            failures.append("قاعدة المصطلحات ماتنشأتش")

        # إعادة الاستخدام: محرّك تاني بنفس المصطلحات مايعملش قاعدة جديدة
        engine2 = build_engine()
        engine2.client = client  # نفس العميل عشان يشوف القاعدة الموجودة
        engine2._glossary_resolved = False  # noqa: SLF001
        engine2._resolve_glossary()  # noqa: SLF001
        print(f"  بعد محرّك تاني بنفس المصطلحات: {len(client.created)} (المفروض تفضل 1)")
        if len(client.created) != 1:
            failures.append("اتعملت قاعدة مصطلحات مكررة بدل إعادة استخدام الموجودة")

        # ---------- 5) التكلفة بالحرف ----------
        print("\n=== 5) التكلفة ===")
        expected_chars = sum(len(s.source) for s in SEGMENTS)
        print(f"  حروف محاسَبة: {result.usage.input_tokens} (المتوقع {expected_chars})")
        print(f"  التكلفة: ${result.usage.cost_usd:.6f}")
        if result.usage.input_tokens != expected_chars:
            failures.append("عدّ الحروف غلط — الفاتورة هتطلع غلط")
        if result.usage.cost_usd <= 0:
            failures.append("التكلفة صفر — سجلّ الاستهلاك مش هيشتغل")

        # السياق مالوش تكلفة عند DeepL فمالوش لازمة في الحساب
        long_context = "س" * 5000
        result2 = engine.translate(SEGMENTS, context_before=long_context)
        if result2.usage.cost_usd != result.usage.cost_usd:
            failures.append("السياق اتحسب في التكلفة رغم إنه مجاني عند DeepL")
        else:
            print("  ✓ السياق مش محسوب في التكلفة")

        # ---------- 6) فشل الشبكة ----------
        print("\n=== 6) التعامل مع الفشل ===")

        def boom(*_args, **_kwargs):
            raise deepl.DeepLException("انقطاع محاكى")

        engine.client.translate_text = boom
        failed = engine.translate(SEGMENTS)
        print(f"  مقاطع راجعة كناقصة: {len(failed.missing)} · تحذيرات: {len(failed.warnings)}")
        if len(failed.missing) != len(SEGMENTS):
            failures.append("الفشل مارجّعش المقاطع كناقصة — هتتحسب مترجمة وهي مش مترجمة")
        if not failed.warnings:
            failures.append("الفشل عدّى من غير تحذير")

    finally:
        deepl.DeepLClient = original

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: محرّك DeepL سليم ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
