"""اختبار مسار الـ PDF: تشخيص → تحويل لـ Word → استخراج → تطبيع.

بيتحقق من:
  1. التمييز بين PDF فيه طبقة نص و PDF ممسوح ضوئيًا.
  2. إن التحويل بيطلع ملف Word يقدر معالج Word يقراه.
  3. إن أشكال العرض العربية بترجع لحروفها الأساسية.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402

from app.tools.translator.formats import pdf_fmt, registry  # noqa: E402
from app.tools.translator.formats.base import strip_tags  # noqa: E402
from app.tools.translator.formats.textnorm import (  # noqa: E402
    analyze,
    has_presentation_forms,
    normalize_arabic,
)
from app.tools.translator.segment import split_sentences  # noqa: E402

SAMPLES = Path("storage/samples")
_ARABIC_FONT = Path("C:/Windows/Fonts/arial.ttf")


def build_latin_pdf(path: Path) -> None:
    """PDF بنص لاتيني — لاختبار خط التحويل نفسه."""
    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "Technical Performance Report",
        "System uptime reached 99.2 percent during Q1 2026.",
        "Article 4. The supplier shall provide technical support.",
        "Total contract value: 150,000 SAR.",
    ]
    y = 100
    for line in lines:
        page.insert_text((72, y), line, fontsize=13)
        y += 30
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def build_scanned_pdf(path: Path) -> None:
    """PDF بصور فقط بدون طبقة نص."""
    doc = fitz.open()
    for _ in range(3):
        page = doc.new_page()
        pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 400, 300))
        pixmap.set_rect(pixmap.irect, (230, 230, 235))
        page.insert_image(fitz.Rect(72, 72, 472, 372), pixmap=pixmap)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))
    doc.close()


def main() -> int:
    failures: list[str] = []
    work = SAMPLES / "work"
    work.mkdir(parents=True, exist_ok=True)

    # ---------- 1) تشخيص وتحويل PDF فيه نص ----------
    latin_pdf = SAMPLES / "report.pdf"
    build_latin_pdf(latin_pdf)

    info = pdf_fmt.diagnose(latin_pdf)
    print("=== PDF فيه طبقة نص ===")
    print(f"  صفحات={info.page_count} حروف={info.char_count} ممسوح={info.is_scanned}")
    if info.is_scanned:
        failures.append("PDF فيه نص اتصنّف غلط كممسوح ضوئيًا")

    working_path, working_fmt, meta = pdf_fmt.prepare(latin_pdf, work)
    print(f"  صيغة العمل: {working_fmt} → {Path(working_path).name}")
    if working_fmt != "docx":
        failures.append(f"المفروض يتحوّل لـ docx، طلع: {working_fmt}")
    else:
        result = registry.extract("docx", Path(working_path), normalize=True)

        # التحويل بيحط سطور الصفحة في فقرة واحدة بفواصل أسطر، والمقسّم
        # هو اللي بيفصلهم — فبنقيس المقاطع مش الوحدات الخام.
        segments = [
            span.text
            for unit in result.units
            for span in split_sentences(unit.text)
            if span.text.strip()
        ]
        print(f"  الوحدات={len(result.units)} المقاطع={len(segments)}")
        for text in segments[:6]:
            print(f"    → {strip_tags(text)[:64]}")

        if len(segments) < 3:
            failures.append(f"استخراج ضعيف بعد التحويل: {len(segments)} مقطع")

        joined = " ".join(strip_tags(t) for t in segments)
        for needle in ("99.2", "150,000", "Article 4"):
            if needle not in joined:
                failures.append(f"محتوى ضاع أثناء التحويل: {needle!r}")

    # ---------- 2) تطبيع أشكال العرض العربية ----------
    print("\n=== تطبيع النص العربي ===")
    # نص بأشكال العرض زي ما بيطلع من ملفات PDF العربية المبنية بصريًا
    raw = "ﺗﻘﺮﻳﺮ ﻓﻨﻲ ﻋﻦ ﺃﺩﺍء ﺍﻟﻨﻈﺎﻡ"
    before = analyze(raw)
    fixed = normalize_arabic(raw)
    print(f"  قبل : {raw}")
    print(f"  بعد : {fixed}")
    print(f"  أشكال عرض قبل={before['has_presentation_forms']} "
          f"بعد={has_presentation_forms(fixed)}")

    if not before["has_presentation_forms"]:
        failures.append("عيّنة الاختبار مافيهاش أشكال عرض أصلًا")
    if has_presentation_forms(fixed):
        failures.append("التطبيع مانجحش — لسه فيه أشكال عرض")
    if "تقرير" not in fixed:
        failures.append(f"التطبيع طلع نص غلط: {fixed!r}")

    # التطويل ومحارف الاتجاه
    decorated = "الـــنـــص\u200fالـعـ__ـربي"
    cleaned = normalize_arabic(decorated)
    if "ـ" in cleaned or "\u200f" in cleaned:
        failures.append(f"التطويل/محارف الاتجاه ماتشالتش: {cleaned!r}")
    print(f"  تطويل: {decorated!r} → {cleaned!r}")

    # ---------- 3) PDF ممسوح ضوئيًا ----------
    scanned_pdf = SAMPLES / "scanned.pdf"
    build_scanned_pdf(scanned_pdf)

    scan_info = pdf_fmt.diagnose(scanned_pdf)
    print("\n=== PDF ممسوح ضوئيًا ===")
    print(f"  صفحات={scan_info.page_count} حروف={scan_info.char_count} "
          f"ممسوح={scan_info.is_scanned}")
    if not scan_info.is_scanned:
        failures.append("PDF ممسوح ماتصنّفش صح — هيطلع ملف مترجم فاضي")

    _, scan_fmt, scan_meta = pdf_fmt.prepare(scanned_pdf, work)
    print(f"  صيغة العمل: {scan_fmt}  محتاج OCR: {scan_meta.get('needs_ocr')}")
    if not scan_meta.get("needs_ocr"):
        failures.append("الملف الممسوح مااتعلّمش إنه محتاج OCR")

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)} مشكلة")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: مسار الـ PDF سليم ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
