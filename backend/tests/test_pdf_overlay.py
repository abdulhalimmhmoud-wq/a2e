"""اختبار التصدير على صفحات الـ PDF الأصلية — بدون أي نداء API.

المطلوب إثباته: الترجمة بتتكتب على الصفحة الأصلية، والشعارات والصور
والزخارف بتفضل مكانها. وده كان العيب: الملف الممسوح كان بيتبني من
الأول فبيضيّع كل حاجة مش حرف.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fitz  # noqa: E402

from app.tools.translator.formats import pdf_overlay  # noqa: E402

WORK = Path("storage/samples/overlay")

ARABIC_LINES = [
    "المادة الأولى: يلتزم البائع بتسليم البضاعة في الموعد المتفق عليه.",
    "المادة الثانية: يستحق الثمن خلال ثلاثين يومًا من التسليم.",
    "المادة الثالثة: تختص محاكم المدينة بنظر أي نزاع.",
]
ENGLISH = [
    "Article 1. The seller shall deliver the goods on the agreed date.",
    "Article 2. Payment falls due within thirty days of delivery.",
    "Article 3. The city courts have jurisdiction over any dispute.",
]


def build_source(path: Path, pages: int = 2) -> None:
    """مستند فيه شعار وإطار ونص — يعني كل اللي كان بيضيع."""
    document = fitz.open()
    for page_index in range(pages):
        page = document.new_page(width=595, height=842)

        # «شعار»: صورة ملوّنة
        samples = bytes(bytearray(
            [(x * 5 + y * 3) % 256
             for y in range(40) for x in range(40 * 3)]
        ))
        pixmap = fitz.Pixmap(fitz.csRGB, 40, 40, samples, False)
        page.insert_image(fitz.Rect(70, 50, 110, 90), pixmap=pixmap)

        page.draw_rect(fitz.Rect(50, 40, 545, 800),
                       color=(0.15, 0.15, 0.5), width=2)

        for index, line in enumerate(ARABIC_LINES):
            page.insert_text((70, 220 + index * 45), line, fontsize=11)
    document.save(str(path))
    document.close()


def main() -> int:  # noqa: C901
    failures: list[str] = []
    WORK.mkdir(parents=True, exist_ok=True)

    source = WORK / "source.pdf"
    build_source(source, pages=2)

    # ---------- 1) اللغات المدعومة ----------
    print("=== 1) أي لغات ينفع نكتبها في الـ PDF ===")
    for lang, expected in [
        ("en", True), ("fr", True), ("tr", True), ("az", True),
        ("ar", False), ("ru", False), ("uk", False),
    ]:
        got = pdf_overlay.supports(lang)
        ok = got == expected
        print(f"  {'✓' if ok else '✗'} {lang}: {got}")
        if not ok:
            failures.append(f"دعم اللغة {lang} غلط: {got}")

    # العربي لازم يترفض: الكتابة بيه في الـ PDF بتطلع مقلوبة
    if pdf_overlay.supports("ar"):
        failures.append(
            "العربي اتقبل كهدف — الكتابة بيه بتطلع أشكال عرض مقلوبة، "
            "وده نفس العطل اللي الأداة موجودة عشان تمنعه"
        )

    # ---------- 2) خريطة الصفحات ----------
    layout_path = WORK / "layout.json"
    layout = [
        {"page": 1, "text": ARABIC_LINES[0], "kind": "paragraph"},
        {"page": 1, "text": ARABIC_LINES[1], "kind": "paragraph"},
        {"page": 2, "text": ARABIC_LINES[2], "kind": "paragraph"},
    ]
    layout_path.write_text(
        json.dumps({"source": str(source), "units": layout}, ensure_ascii=False),
        encoding="utf-8",
    )

    # ---------- 3) التصدير ----------
    print("\n=== 2) التصدير على الأصل ===")
    before = fitz.open(str(source))
    counts_before = [
        (len(before[i].get_images(full=True)), len(before[i].get_drawings()))
        for i in range(before.page_count)
    ]
    before.close()

    output = WORK / "translated.pdf"
    result = pdf_overlay.render(
        source, layout_path, ENGLISH, output, target_lang="en"
    )
    print(f"  صفحات اتكتبت : {result.pages_written}")
    print(f"  وحدات اتحطّت : {result.units_placed} (اتخطّت {result.units_skipped})")
    for warning in result.warnings:
        print(f"    ! {warning[:70]}")

    if result.pages_written != 2:
        failures.append(f"صفحات مكتوبة {result.pages_written} بدل 2")
    if not output.exists():
        failures.append("الملف المصدَّر مااتكتبش")
        print("\n".join(f"  ✗ {f}" for f in failures))
        return 1

    check = fitz.open(str(output))
    print("\n  المقارنة صفحة بصفحة:")
    for index in range(check.page_count):
        page = check[index]
        images = len(page.get_images(full=True))
        drawings = len(page.get_drawings())
        text = page.get_text()
        was_images, was_drawings = counts_before[index]
        print(f"    ص{index+1}: صور {was_images}→{images} · "
              f"رسومات {was_drawings}→{drawings}")

        if images != was_images:
            failures.append(f"ص{index+1}: الشعار ضاع ({was_images}→{images})")
        if drawings < was_drawings:
            failures.append(f"ص{index+1}: رسومات ضاعت")

        # النص العربي الأصلي لازم يختفي من المواضع المستبدَلة
        for line in ARABIC_LINES:
            if line in text:
                failures.append(f"ص{index+1}: نص أصلي فضل ظاهر")
                break

    joined = "\n".join(check[i].get_text() for i in range(check.page_count))
    placed = sum(1 for line in ENGLISH if line in joined)
    print(f"\n  ترجمات ظاهرة: {placed} من {len(ENGLISH)}")
    for line in ENGLISH:
        if joined.count(line) > 1:
            failures.append(f"ترجمة اتكتبت مكررة: {line[:34]}")
    if placed < len(ENGLISH):
        failures.append(f"{len(ENGLISH) - placed} ترجمة مأوصلتش للمخرجات")
    check.close()

    # ---------- 4) هدف عربي يرجع لمسار Word ----------
    print("\n=== 3) هدف بلغة محتاجة تشكيل ===")
    rtl_out = WORK / "rtl.pdf"
    rtl = pdf_overlay.render(
        source, layout_path, ARABIC_LINES, rtl_out, target_lang="ar"
    )
    print(f"  صفحات اتكتبت: {rtl.pages_written} (المفروض 0)")
    print(f"  تحذير: {rtl.warnings[0][:64] if rtl.warnings else '—'}")
    if rtl.pages_written:
        failures.append("هدف عربي اتكتب في الـ PDF رغم إن الحروف هتطلع مقلوبة")
    if not rtl.warnings:
        failures.append("الرجوع لمسار Word حصل من غير تحذير")

    # ---------- 5) عدد وحدات مختلف ----------
    print("\n=== 4) عدد الترجمات مش مطابق للخريطة ===")
    short = pdf_overlay.render(
        source, layout_path, ENGLISH[:1], WORK / "short.pdf", target_lang="en"
    )
    print(f"  وحدات اتحطّت: {short.units_placed} · تحذيرات: {len(short.warnings)}")
    if not short.warnings:
        failures.append("اختلاف الأعداد عدّى من غير تحذير")

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: الترجمة بتتكتب على الأصل والشعارات بتفضل ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
