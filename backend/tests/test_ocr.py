"""اختبار مسار الـ OCR — بيستهلك API (بضعة سنتات).

بيبني PDF "ممسوح" (صور بدون طبقة نص) من نص عربي معروف، وبعدين
بيتأكد إن القراءة الضوئية رجّعت نفس المحتوى.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import fitz  # noqa: E402

from app.tools.translator import ocr  # noqa: E402
from app.tools.translator.formats import docx_fmt, pdf_fmt  # noqa: E402
from app.tools.translator.formats.base import strip_tags  # noqa: E402

SAMPLES = Path("storage/samples")

# بيانات وهمية بالكامل — الاختبار بيتحقق من القراءة الضوئية مش من
# محتوى بعينه، فمافيش أي داعي لاستخدام بيانات مريض حقيقية.
PAGE_HTML = [
    """
    <div style="font-family: Arial; font-size: 16pt; direction: rtl; text-align: right;">
      <h2>تقرير تجريبي — قسم التخاطب</h2>
      <p>اسم الحالة: حالة تجريبية أ</p>
      <p>نوع التقييم: تقييم لغوي دوري</p>
      <p>عدد الجلسات المكتملة: 24 جلسة خلال 6 أشهر.</p>
      <ul>
        <li>تحسن ملحوظ في نطق الأصوات الأمامية</li>
        <li>زيادة الحصيلة اللغوية إلى 120 كلمة</li>
      </ul>
    </div>
    """,
    """
    <div style="font-family: Arial; font-size: 16pt; direction: rtl; text-align: right;">
      <h2>التوصيات</h2>
      <p>يوصى باستمرار الجلسات بمعدل ثلاث جلسات أسبوعيًا.</p>
      <p>تاريخ المراجعة القادمة: 15/09/2026</p>
      <p>قيمة الاشتراك الشهري: 1.500 جنيه</p>
    </div>
    """,
]

# كلمات لازم تظهر في القراءة عشان نعتبرها ناجحة
EXPECTED = [
    ["تجريبية", "لغوي", "24", "120"],
    ["ثلاث", "15/09/2026", "1.500"],
]


def build_scanned_pdf(path: Path) -> None:
    """بناء PDF بصور فقط — بدون أي طبقة نص، زي المستند الممسوح."""
    # 1) صفحات فيها نص حقيقي
    source = fitz.open()
    for html in PAGE_HTML:
        page = source.new_page(width=595, height=842)  # A4
        page.insert_htmlbox(fitz.Rect(40, 40, 555, 802), html)

    # 2) نحوّل كل صفحة لصورة ونحطها في ملف جديد → مفيش طبقة نص
    scanned = fitz.open()
    for page in source:
        pixmap = page.get_pixmap(dpi=150)
        new_page = scanned.new_page(width=595, height=842)
        new_page.insert_image(fitz.Rect(0, 0, 595, 842), pixmap=pixmap)

    path.parent.mkdir(parents=True, exist_ok=True)
    scanned.save(str(path))
    scanned.close()
    source.close()


def main() -> int:
    failures: list[str] = []
    scanned = SAMPLES / "scanned_report_ar.pdf"
    build_scanned_pdf(scanned)

    # ---------- 1) التشخيص ----------
    info = pdf_fmt.diagnose(scanned)
    print("=== التشخيص ===")
    print(f"  صفحات={info.page_count} حروف_نص={info.char_count} "
          f"ممسوح={info.is_scanned}")
    if not info.is_scanned:
        failures.append("الملف المبني ماتصنّفش كممسوح — الاختبار نفسه غلط")
        return 1

    # ---------- 2) القراءة الضوئية ----------
    print("\n=== القراءة الضوئية ===")

    def report(done: int, total: int) -> None:
        print(f"  {done}/{total} صفحة")

    result = ocr.read_document(scanned, progress=report)

    print(f"\n  كتل مستخرجة: {len(result.blocks)}")
    print(f"  صفحات فشلت: {result.failed_pages or 'مفيش'}")
    print(f"  التكلفة: ${result.usage.cost_usd:.4f} "
          f"(إدخال={result.usage.input_tokens:,} إخراج={result.usage.output_tokens:,})")
    print(f"  قراءة من الكاش: {result.usage.cache_read_tokens:,} توكن")

    print("\n  --- الكتل ---")
    for block in result.blocks:
        label = block.kind[:9]
        body = block.text if block.text else " | ".join(block.cells)
        print(f"    [ص{block.page} {label:9}] {body[:70]}")

    if not result.blocks:
        failures.append("القراءة الضوئية مارجّعتش أي محتوى")
        return 1

    # ---------- 3) دقّة المحتوى ----------
    print("\n=== دقّة المحتوى ===")
    for page_index, keywords in enumerate(EXPECTED, start=1):
        page_text = " ".join(
            (b.text + " " + " ".join(b.cells))
            for b in result.blocks
            if b.page == page_index
        )
        found = [k for k in keywords if k in page_text]
        missing = [k for k in keywords if k not in page_text]
        print(f"  صفحة {page_index}: لُقِط {len(found)}/{len(keywords)}"
              + (f" · ناقص: {missing}" if missing else " ✓"))
        if missing:
            failures.append(f"صفحة {page_index}: محتوى ناقص من القراءة {missing}")

    # ---------- 4) بناء ملف Word ----------
    print("\n=== بناء ملف Word ===")
    docx_path = SAMPLES / "work" / "scanned_report_ar.ocr.docx"
    ocr.build_docx(result, docx_path)
    print(f"  {docx_path.name} ({docx_path.stat().st_size:,} بايت)")

    extracted = docx_fmt.extract(docx_path)
    print(f"  وحدات نص بعد البناء: {len(extracted.units)}")
    for unit in extracted.units[:8]:
        print(f"    [{unit.kind:9}] {strip_tags(unit.text)[:62]}")

    if len(extracted.units) < 5:
        failures.append(f"الملف المبني فيه {len(extracted.units)} وحدة بس")

    joined = " ".join(strip_tags(u.text) for u in extracted.units)
    for keyword in ("تجريبية", "لغوي", "1.500"):
        if keyword not in joined:
            failures.append(f"'{keyword}' ضاع أثناء بناء ملف Word")

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: مسار الـ OCR سليم ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
