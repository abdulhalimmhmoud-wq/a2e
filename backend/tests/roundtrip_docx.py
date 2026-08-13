"""اختبار الدورة الكاملة للـ DOCX: استخراج → تقسيم → "ترجمة" → دمج → تحقّق.

مش بنستدعي أي API هنا — بنستبدل النص بترجمة وهمية عشان نختبر
سلامة الأنابيب (الـ Anchors والوسوم والتقسيم) لوحدها.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.translator.formats import docx_fmt  # noqa: E402
from app.tools.translator.formats.base import (  # noqa: E402
    is_translatable,
    parse_tagged_text,
    strip_tags,
    tags_in,
)
from app.tools.translator.segment import split_sentences, verify_coverage  # noqa: E402


def fake_translate(text: str) -> str:
    """ترجمة وهمية: بتقلب النص وتحافظ على الوسوم في مكانها."""
    pieces = parse_tagged_text(text)
    out = []
    for tag, chunk in pieces:
        translated = f"[EN:{chunk.strip()}]" if chunk.strip() else chunk
        out.append(f"<g{tag}>{translated}</g{tag}>" if tag else translated)
    return "".join(out)


def main() -> int:
    sample = Path("storage/samples/contract_ar.docx")
    if not sample.exists():
        print("!! الملف النموذجي مش موجود — شغّل make_sample_docx.py الأول")
        return 1

    failures: list[str] = []

    # ---------- 1) الاستخراج ----------
    result = docx_fmt.extract(sample)
    print(f"\n=== الاستخراج: {len(result.units)} وحدة نص، ~{result.page_count} صفحة ===")
    for unit in result.units[:20]:
        preview = strip_tags(unit.text)[:60]
        tag_note = f"  وسوم={sorted(unit.placeholders)}" if unit.placeholders else ""
        print(f"  [{unit.kind:9}] {unit.location:22} | {preview}{tag_note}")

    if len(result.units) < 10:
        failures.append(f"عدد الوحدات قليل بشكل مريب: {len(result.units)}")

    # تأكيد إن الترويسة والتذييل والجدول اتلقطوا
    kinds = {u.kind for u in result.units}
    for required in ("header", "footer", "cell"):
        if required not in kinds:
            failures.append(f"نوع مفقود من الاستخراج: {required}")

    # تأكيد إن الفقرة المختلطة التنسيق طلعت بوسوم
    mixed = [u for u in result.units if u.placeholders]
    if not mixed:
        failures.append("مفيش أي وحدة بوسوم تنسيق — تجميع الـ runs مش شغال")
    else:
        print(f"\n  وحدات بتنسيق مختلط: {len(mixed)}")
        print(f"  مثال: {mixed[0].text[:110]}")

    # ---------- 2) التقسيم ----------
    print("\n=== التقسيم ===")
    total_segments = 0
    for unit in result.units:
        spans = split_sentences(unit.text)
        total_segments += len(spans)
        if not verify_coverage(unit.text, spans):
            failures.append(f"التقسيم فقد نصًا في {unit.unit_key}")

    multi = [u for u in result.units if len(split_sentences(u.text)) > 1]
    print(f"  إجمالي المقاطع: {total_segments} (من {len(result.units)} وحدة)")
    if multi:
        print(f"  مثال على وحدة متعددة المقاطع ({len(split_sentences(multi[-1].text))} مقاطع):")
        for span in split_sentences(multi[-1].text):
            print(f"    → {strip_tags(span.text)[:70]}")

    # الفخ: "المادة 1." و "150.000" مايتقسموش
    for unit in result.units:
        plain = strip_tags(unit.text)
        if "150.000" in plain:
            spans = split_sentences(unit.text)
            if len(spans) > 1:
                failures.append("الرقم العشري 150.000 اتقسم غلط لجملتين")
        if plain.startswith("المادة 1."):
            spans = split_sentences(unit.text)
            if len(spans) > 1:
                failures.append("ترقيم المادة اتقسم غلط لجملتين")

    # ---------- 3) الترجمة الوهمية + الدمج ----------
    translations = {
        unit.unit_key: fake_translate(unit.text)
        for unit in result.units
        if is_translatable(unit.text)
    }
    print(f"\n=== الدمج: {len(translations)} وحدة قابلة للترجمة ===")

    output = Path("storage/samples/contract_en.docx")
    docx_fmt.merge(sample, output, translations, target_rtl=False)
    print(f"  اتكتب: {output}  ({output.stat().st_size:,} بايت)")

    # ---------- 4) التحقّق ----------
    print("\n=== التحقّق بعد الدمج ===")
    after = docx_fmt.extract(output)

    before_keys = {u.unit_key for u in result.units}
    after_keys = {u.unit_key for u in after.units}
    if before_keys != after_keys:
        missing = before_keys - after_keys
        added = after_keys - before_keys
        failures.append(f"مفاتيح الوحدات اتغيّرت بعد الدمج (ناقص={len(missing)} زائد={len(added)})")

    after_map = {u.unit_key: u for u in after.units}
    untranslated = []
    tag_lost = []
    for key, expected in translations.items():
        unit = after_map.get(key)
        if unit is None:
            untranslated.append(key)
            continue
        if "[EN:" not in unit.text:
            untranslated.append(key)
        source_unit = next(u for u in result.units if u.unit_key == key)
        if tags_in(source_unit.text) and not tags_in(unit.text):
            tag_lost.append(key)

    if untranslated:
        failures.append(f"وحدات ماوصلتهاش الترجمة: {len(untranslated)} → {untranslated[:3]}")
    if tag_lost:
        failures.append(f"وحدات ضاع تنسيقها: {len(tag_lost)} → {tag_lost[:3]}")

    print(f"  الوحدات بعد الدمج: {len(after.units)}")
    print(f"  وصلتها الترجمة: {len(translations) - len(untranslated)}/{len(translations)}")
    print(f"  حافظت على التنسيق: {len(mixed) - len(tag_lost)}/{len(mixed)}")

    # تأكيد إن الرابط لسه موجود
    from docx import Document
    doc = Document(str(output))
    rel_count = sum(
        1 for rel in doc.part.rels.values() if "hyperlink" in rel.reltype
    )
    print(f"  الروابط المحفوظة: {rel_count}")
    if rel_count < 1:
        failures.append("الرابط ضاع بعد الدمج")

    # تأكيد قلب الاتجاه
    from docx.oxml.ns import qn
    bidi_left = len(list(doc.element.iter(qn("w:bidi"))))
    rtl_left = len(list(doc.element.iter(qn("w:rtl"))))
    print(f"  عناصر RTL متبقية: bidi={bidi_left} rtl={rtl_left}")
    if bidi_left or rtl_left:
        failures.append(f"قلب الاتجاه ناقص: bidi={bidi_left} rtl={rtl_left}")

    # ---------- النتيجة ----------
    print("\n" + "=" * 60)
    if failures:
        print(f"فشل: {len(failures)} مشكلة")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: الدورة الكاملة سليمة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
