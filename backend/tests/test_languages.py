"""اختبار حقيقي لأزواج اللغات الجديدة على المحرّكين.

بيستهلك API: DeepL (مجاني ضمن الباقة) و Claude (سنتات قليلة).

بيتحقق من حاجات مالهاش معنى إلا بنداء حقيقي:
  - الكتابة الصح في المخرجات (كيريلي للروسي والأوكراني، لاتيني للتركي)
  - الحروف الخاصة بالأذربيجانية (ə ğ ı ö ş ü ç) مابتتشالش
  - الأوكراني مش بيطلع روسي (Kyiv مش Kiev)
  - الأرقام بتتحافظ حرفيًا
  - وسوم التنسيق بتتنقل مع كلماتها
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import settings  # noqa: E402
from app.tools.translator.engine import SegmentInput, validate_translation  # noqa: E402
from app.tools.translator.formats.base import strip_tags, tags_in  # noqa: E402
from app.tools.translator.langs import script_of, script_ratio  # noqa: E402

# نص إنجليزي واحد بيتترجم لكل اللغات — بيسهّل المقارنة
EN_SOURCE = [
    SegmentInput(
        id="a",
        source="Article 1. The supplier shall deliver the goods within 30 days.",
    ),
    SegmentInput(
        id="b",
        source="The total contract value is 150,000 USD including VAT.",
    ),
    SegmentInput(
        id="c",
        source="<g1>The agreement was signed in </g1><g2>Kyiv</g2><g3> on 15 March 2026.</g3>",
    ),
]

# نصوص مصدر لكل لغة للاتجاه العكسي (إلى الإنجليزية)
TO_EN_SOURCES = {
    "ru": "Статья 1. Поставщик обязан поставить товар в течение 30 дней.",
    "uk": "Стаття 1. Постачальник зобов'язаний поставити товар протягом 30 днів.",
    "tr": "Madde 1. Tedarikçi malları 30 gün içinde teslim etmekle yükümlüdür.",
    "az": "Maddə 1. Təchizatçı malları 30 gün ərzində təhvil verməlidir.",
}

LANGS = ["ru", "uk", "tr", "az"]

# حروف الأذربيجانية اللي بتضيع لو المحرّك عاملها كتركية
AZ_SPECIAL = set("əğıöşüçİ")


def build_engine(engine_name: str, source: str, target: str):
    if engine_name == "deepl":
        from app.tools.translator.deepl_engine import DeepLEngine

        return DeepLEngine(source_lang=source, target_lang=target, domain="legal")

    from app.tools.translator.engine import ClaudeEngine

    return ClaudeEngine(
        model="claude-sonnet-5",
        source_lang=source,
        target_lang=target,
        domain="legal",
    )


def check_direction(engine_name: str, source: str, target: str, segments) -> list[str]:
    """ترجمة اتجاه واحد والتحقق من مخرجاته."""
    problems: list[str] = []
    try:
        engine = build_engine(engine_name, source, target)
    except Exception as exc:  # noqa: BLE001
        return [f"{engine_name} {source}->{target}: تعذّر التجهيز — {exc}"]

    result = engine.translate(segments)
    for warning in result.warnings:
        problems.append(f"{engine_name} {source}->{target}: {warning}")

    expected_script = script_of(target)
    for segment in segments:
        text = result.translations.get(segment.id)
        if not text:
            problems.append(f"{engine_name} {source}->{target}: مقطع {segment.id} فاضي")
            continue

        plain = strip_tags(text)
        print(f"      [{segment.id}] {plain[:74]}")

        # الكتابة الصح
        ratio = script_ratio(plain, expected_script)
        if ratio < 0.5:
            problems.append(
                f"{engine_name} {source}->{target} [{segment.id}]: "
                f"الكتابة مش {expected_script} (النسبة {ratio:.0%})"
            )

        # الأرقام والوسوم
        issues = validate_translation(segment.source, text, source, target)
        # تغيير الأرقام أو ضياع الوسوم = فشل. تغيير الفاصل = تنبيه
        # مقبول لأنه اصطلاح لغة الهدف، والمراجع بيقرر.
        blocking = [i for i in issues if i.startswith(("numbers_mismatch", "tags_"))]
        notices = [i for i in issues if i.startswith("separator_changed")]
        if blocking:
            problems.append(
                f"{engine_name} {source}->{target} [{segment.id}]: {blocking}"
            )
        if notices:
            print(f"          ملاحظة: اصطلاح الفاصل الرقمي اتغيّر (مرفوع للمراجعة)")

    return problems


def main() -> int:
    failures: list[str] = []
    engines = []
    if settings.anthropic_api_key:
        engines.append("claude")
    if settings.deepl_api_key:
        engines.append("deepl")

    if not engines:
        print("!! مفيش مفاتيح — الاختبار ده محتاج API")
        return 1
    print(f"المحرّكات المتاحة: {', '.join(engines)}\n")

    for engine_name in engines:
        print(f"{'=' * 66}\n{engine_name.upper()}\n{'=' * 66}")

        # ---------- الإنجليزية → اللغات الأربع ----------
        for target in LANGS:
            print(f"\n  --- en -> {target} ---")
            failures += check_direction(engine_name, "en", target, EN_SOURCE)

        # ---------- اللغات الأربع → الإنجليزية ----------
        for source in LANGS:
            print(f"\n  --- {source} -> en ---")
            segments = [SegmentInput(id="x", source=TO_EN_SOURCES[source])]
            failures += check_direction(engine_name, source, "en", segments)

    # ---------- فحوصات خاصة ----------
    print(f"\n{'=' * 66}\nفحوصات خاصة\n{'=' * 66}")

    for engine_name in engines:
        # الأوكراني لازم يطلع Kyiv مش Kiev
        try:
            engine = build_engine(engine_name, "uk", "en")
            out = engine.translate(
                [SegmentInput(id="k", source="Договір підписано в Києві.")]
            )
            text = out.translations.get("k", "")
            print(f"  [{engine_name}] الأوكرانية → الإنجليزية: {text[:60]}")
            if "Kiev" in text:
                failures.append(
                    f"{engine_name}: الأوكراني اتحوّل بقواعد روسية (Kiev بدل Kyiv)"
                )
            elif "Kyiv" in text:
                print("      ✓ Kyiv مش Kiev")
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{engine_name}: فحص الأوكرانية فشل — {exc}")

        # الأذربيجاني لازم يحافظ على حروفه الخاصة
        try:
            engine = build_engine(engine_name, "en", "az")
            out = engine.translate(
                [
                    SegmentInput(
                        id="z",
                        source="The supplier must deliver the goods and issue an invoice.",
                    )
                ]
            )
            text = out.translations.get("z", "")
            found = AZ_SPECIAL & set(text)
            print(f"  [{engine_name}] الإنجليزية → الأذربيجانية: {text[:60]}")
            print(f"      حروف أذربيجانية خاصة: {''.join(sorted(found)) or 'مفيش'}")
            if not found:
                failures.append(
                    f"{engine_name}: مفيش أي حرف أذربيجاني خاص — "
                    "غالبًا المخرَج تركي مش أذربيجاني"
                )
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{engine_name}: فحص الأذربيجانية فشل — {exc}")

    # ---------- الاستهلاك ----------
    if "deepl" in engines:
        from app.tools.translator.deepl_engine import DeepLEngine

        usage = DeepLEngine(source_lang="en", target_lang="ru").check_usage()
        print(f"\n  استهلاك DeepL: {usage.get('characters_used', '?'):,} / "
              f"{usage.get('characters_limit', '?'):,} حرف "
              f"({usage.get('percent_used', 0)}%)")

    print("\n" + "=" * 66)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: كل أزواج اللغات الجديدة سليمة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
