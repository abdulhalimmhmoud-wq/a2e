"""اختبار الحفاظ على شكل صفحة الـ PDF — بدون أي نداء API.

السؤال اللي الاختبار ده بيجاوب عليه: لما نستبدل نص الصفحة، هل
الشعارات والصور والرسومات بتفضل مكانها؟ ده كان العيب: مسار القراءة
الضوئية كان بيبني ملف Word جديد من كتل النص فبيضيّع كل حاجة مرئية.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fitz  # noqa: E402

from app.tools.translator.formats import pdf_visual  # noqa: E402

WORK = Path("storage/samples/pdfvisual")

LINES = [
    "Article 1. The seller shall deliver the goods on the agreed date.",
    "Article 2. Payment falls due within thirty days of delivery.",
    "Article 3. Disputes are referred to the competent court.",
]


def build_page(document, with_logo: bool = True):
    """صفحة فيها نص وشعار وإطار — يعني كل اللي بيضيع دلوقتي."""
    page = document.new_page(width=595, height=842)

    if with_logo:
        # «شعار»: صورة ملوّنة صغيرة فوق الصفحة
        pixmap = fitz.Pixmap(fitz.csRGB, 60, 60, bytes(
            bytearray([(x * 4) % 256 for _ in range(60) for x in range(60 * 3)])
        ), False)
        page.insert_image(fitz.Rect(60, 40, 120, 100), pixmap=pixmap)

    # إطار ورسومات متجهة
    page.draw_rect(fitz.Rect(40, 30, 555, 810), color=(0.2, 0.2, 0.6), width=2)
    page.draw_line(fitz.Point(40, 120), fitz.Point(555, 120), color=(0.6, 0, 0))

    for index, line in enumerate(LINES):
        page.insert_text((60, 200 + index * 40), line, fontsize=12)
    return page


def main() -> int:  # noqa: C901
    failures: list[str] = []
    WORK.mkdir(parents=True, exist_ok=True)

    # ---------- 1) قراءة الهندسة ----------
    print("=== 1) قراءة مواضع النص ===")
    source = WORK / "page.pdf"
    document = fitz.open()
    build_page(document)
    document.save(str(source))
    document.close()

    geometry = pdf_visual.read_geometry(source)[0]
    print(f"  مقاطع نص : {len(geometry.spans)}")
    print(f"  صور      : {geometry.image_count}")
    print(f"  رسومات   : {geometry.drawing_count}")
    print(f"  فيها نص  : {geometry.has_text}")

    if len(geometry.spans) < len(LINES):
        failures.append(
            f"مقاطع ناقصة: {len(geometry.spans)} بدل {len(LINES)} على الأقل"
        )
    if geometry.image_count != 1:
        failures.append(f"الشعار مااتقراش: صور={geometry.image_count}")
    if geometry.drawing_count < 2:
        failures.append("الرسومات المتجهة مااتقراتش")

    for span in geometry.spans[:3]:
        print(f"    x={span.bbox[0]:.0f} y={span.bbox[1]:.0f} "
              f"حجم={span.size:.0f} خط={span.font[:20]} — {span.text[:36]}")
        if span.width <= 0 or span.height <= 0:
            failures.append(f"صندوق مالوش أبعاد: {span.bbox}")

    # ---------- 2) الاستبدال بيحافظ على كل حاجة ----------
    print("\n=== 2) الاستبدال مع الحفاظ على المرئيات ===")
    target = WORK / "replaced.pdf"
    document = fitz.open(str(source))
    page = document[0]

    before_images = len(page.get_images(full=True))
    before_drawings = len(page.get_drawings())

    replacements = [
        (span.bbox, f"[AR] {'ترجمة المقطع رقم'} {index + 1}")
        for index, span in enumerate(geometry.spans)
        if span.text.strip()
    ]
    written = pdf_visual.cover_and_write(page, replacements)
    document.save(str(target))
    document.close()

    check = fitz.open(str(target))
    after = check[0]
    after_images = len(after.get_images(full=True))
    after_drawings = len(after.get_drawings())
    new_text = after.get_text()
    check.close()

    print(f"  مواضع اتكتبت : {written}")
    print(f"  صور     : {before_images} → {after_images}")
    print(f"  رسومات  : {before_drawings} → {after_drawings}")
    print(f"  النص القديم اختفى : {'Article 1.' not in new_text}")

    if after_images != before_images:
        failures.append(
            f"الشعار ضاع بعد الاستبدال: {before_images} → {after_images}"
        )
    if after_drawings < before_drawings:
        failures.append(
            f"رسومات ضاعت: {before_drawings} → {after_drawings}"
        )
    if "Article 1." in new_text:
        failures.append("النص الأصلي فضل ظاهر تحت الترجمة")
    if written != len(replacements):
        failures.append(f"اتكتب {written} من {len(replacements)}")

    # قياس حجم الخط كان بيحصل على الصفحة نفسها، و`insert_textbox`
    # بتكتب حتى في الوضع غير المرئي — فكل سطر كان بيتكتب مرتين.
    duplicated = new_text.count("ترجمة المقطع رقم")
    print(f"  ظهور نص الترجمة: {duplicated} (المفروض {len(replacements)})")
    if duplicated > len(replacements):
        failures.append(
            f"النص اتكتب مكرر: {duplicated} ظهور لـ{len(replacements)} سطر — "
            "أي تحويل بعد كده هيشيل النص مرتين"
        )

    # ---------- 3) نص أطول من مساحته ----------
    print("\n=== 3) ترجمة أطول من الأصل ===")
    document = fitz.open(str(source))
    page = document[0]
    span = geometry.spans[0]
    long_text = ("A considerably longer rendering of the same clause that "
                 "will not fit at the original size and must be reduced. ") * 2
    pdf_visual.cover_and_write(page, [(span.bbox, long_text)])
    overflow_target = WORK / "overflow.pdf"
    document.save(str(overflow_target))
    document.close()

    check = fitz.open(str(overflow_target))
    text = check[0].get_text()
    check.close()
    kept = text.count("considerably longer")
    print(f"  ظهر في المخرجات: {kept} مرة")
    if kept == 0:
        failures.append("النص الطويل اتقص بالكامل بدل ما يتصغّر")

    # ---------- 4) صفحة بدون نص ----------
    print("\n=== 4) صفحة غلاف (رسومات بدون نص) ===")
    cover = WORK / "cover.pdf"
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.draw_rect(fitz.Rect(60, 60, 535, 780), color=(0.3, 0.1, 0.1), width=3)
    document.save(str(cover))
    document.close()

    cover_geometry = pdf_visual.read_geometry(cover)[0]
    print(f"  مقاطع={len(cover_geometry.spans)} · "
          f"فيها نص={cover_geometry.has_text} · "
          f"رسومات={cover_geometry.drawing_count}")
    if cover_geometry.has_text:
        failures.append("صفحة بلا نص اتعلّمت إن فيها نص")

    # ---------- 5) صورة الصفحة ----------
    print("\n=== 5) صورة الصفحة للمستندات الممسوحة ===")
    document = fitz.open(str(source))
    data = pdf_visual.page_image(document[0])
    document.close()
    print(f"  حجم الصورة: {len(data) / 1024:.0f} ك.ب · "
          f"JPEG={data.startswith(b'\xff\xd8\xff')}")
    if not data.startswith(b"\xff\xd8\xff"):
        failures.append("صورة الصفحة مش JPEG")

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: الاستبدال بيحافظ على الشعارات والصور والرسومات ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
