"""اختبار حجم صور القراءة الضوئية — بدون أي نداء API.

العيب اللي الاختبار ده موجود عشانه: صفحة مقاسها ٢٥.٨×٣٦.٨ بوصة
اترسمت PNG بدقة ١٥٠، فطلعت ٢٥.٩ ميجا بعد الترميز والواجهة البرمجية
رفضتها (الحد ١٠ ميجا). الملف كله وقف على رسالة خطأ خام.

سببان: PNG بلا فقد أسوأ صيغة لصورة ممسوحة، ومافيش أي قياس للحجم
الناتج — أي دقة ثابتة هتنفجر على مقاس صفحة ما.
"""
from __future__ import annotations

import io
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fitz  # noqa: E402

from app.tools.translator import ocr  # noqa: E402

# حد الواجهة البرمجية الفعلي للصورة بعد ترميز base64
API_LIMIT = 10 * 1024 * 1024

# (الاسم، العرض، الارتفاع) بالنقاط — 72 نقطة = بوصة
PAGES = [
    ("A5", 420, 595),
    ("A4", 595, 842),
    ("A3", 842, 1191),
    ("Legal", 612, 1008),
    # المقاس اللي كسر الحد فعلًا
    ("مستند الدليل", 1857, 2651),
    ("A0 مخطط", 2384, 3370),
    ("لوحة ضخمة", 5000, 7000),
    ("شريط طويل", 300, 8000),
]


def build_page(document, width: float, height: float):
    """صفحة تحاكي مسحًا حقيقيًا.

    الضوضاء هنا مش زخرفة: الصفحة المرسومة بنص متجهي بتتضغط في PNG
    لكام مئة كيلو، فاختبار مبني عليها كان هيعدّي على العيب الأصلي من
    غير ما يشوفه. المسح الحقيقي صورة فوتوغرافية فيها حبيبات عشوائية،
    وهي دي اللي بتخلي PNG بلا فقد يتضخّم لعشرات الميجات.
    """
    page = document.new_page(width=width, height=height)

    noise_w, noise_h = 300, 300
    samples = bytes(random.getrandbits(8) for _ in range(noise_w * noise_h * 3))
    noise = fitz.Pixmap(fitz.csRGB, noise_w, noise_h, samples, False)
    page.insert_image(page.rect, pixmap=noise)

    for row in range(0, int(height), 40):
        page.insert_text(
            (30, row + 30),
            "نموذج نص ممسوح ضوئيًا للاختبار 0123456789 sample scanned line",
            fontsize=11,
        )
    return page


def main() -> int:
    failures: list[str] = []

    print(f"الحد المسموح: {ocr.MAX_IMAGE_B64 / 1e6:.1f} ميجا "
          f"(حد الواجهة البرمجية 10.0)")
    print(f"أقصى ضلع: {ocr.MAX_EDGE_PX} بكسل · جودة JPEG: {ocr.JPEG_QUALITY}\n")

    print(f"  {'الصفحة':<16} {'بوصة':>12} {'PNG قديم':>11} {'JPEG جديد':>11}")
    print("  " + "-" * 54)

    for label, width, height in PAGES:
        document = fitz.open()
        page = build_page(document, width, height)

        # المسار القديم: PNG بدقة ثابتة من غير أي قياس
        old = page.get_pixmap(dpi=ocr.DEFAULT_DPI).tobytes("png")
        old_size = ocr._b64_size(len(old))  # noqa: SLF001

        data = ocr.render_page(page)
        new_size = ocr._b64_size(len(data))  # noqa: SLF001

        ok = new_size <= ocr.MAX_IMAGE_B64
        mark = "✓" if ok else "✗"
        print(f"  {label:<16} {width/72:>5.1f}×{height/72:<6.1f} "
              f"{old_size/1e6:>9.1f}م {new_size/1e6:>9.2f}م {mark}")

        if not ok:
            failures.append(
                f"{label}: {new_size/1e6:.1f} ميجا فوق الحد "
                f"({ocr.MAX_IMAGE_B64/1e6:.1f})"
            )

        # السبب الجذري كان دقّة بلا سقف: صفحة بمقاس مخططات بتطلع
        # ٣٨٦٩×٥٥٢٣ بكسل بدقة ثابتة. الحارس الحقيقي هنا هو سقف
        # الأبعاد، مش حجم ملف معيّن.
        rendered = fitz.Pixmap(io.BytesIO(data))
        if max(rendered.width, rendered.height) > ocr.MAX_EDGE_PX:
            failures.append(
                f"{label}: الضلع الأطول {max(rendered.width, rendered.height)} "
                f"بكسل فوق السقف ({ocr.MAX_EDGE_PX})"
            )

        # لازم تكون صورة JPEG فعلًا — الترويسة ثابتة
        if not data.startswith(b"\xff\xd8\xff"):
            failures.append(f"{label}: الناتج مش JPEG")

        # مش لازم نصغّر صفحة عادية بلا داعي
        if label == "A4":
            pixmap = fitz.open("pdf", document.tobytes())[0].get_pixmap(
                matrix=fitz.Matrix(ocr.DEFAULT_DPI / 72, ocr.DEFAULT_DPI / 72)
            )
            if pixmap.width > ocr.MAX_EDGE_PX:
                failures.append("A4 بالدقة الافتراضية تعدّت حد الضلع")

        document.close()

    # ---------- الميزانية بتتحترم لما تتشدّ ----------
    print("\n=== ميزانية مشدودة (100 كيلو) ===")
    document = fitz.open()
    page = build_page(document, 1857, 2651)
    tight = ocr.render_page(page, budget=100_000)
    tight_size = ocr._b64_size(len(tight))  # noqa: SLF001
    print(f"  الناتج: {tight_size/1000:.0f} كيلو "
          f"{'✓' if tight_size <= 100_000 else '✗'}")
    if tight_size > 100_000:
        failures.append(
            f"الميزانية المشدودة مااتحترمتش: {tight_size/1000:.0f} كيلو"
        )
    document.close()

    # ---------- حساب حجم base64 ----------
    print("\n=== حساب حجم base64 ===")
    import base64 as b64mod

    mismatches = []
    for raw_len in (1, 2, 3, 1000, 99999):
        expected = len(b64mod.standard_b64encode(b"x" * raw_len))
        got = ocr._b64_size(raw_len)  # noqa: SLF001
        if expected != got:
            mismatches.append(f"حساب base64 غلط لـ {raw_len}: {got} بدل {expected}")
    failures.extend(mismatches)
    print(f"  {'✓' if not mismatches else '✗'} الحساب مطابق للترميز الفعلي")

    print("\n" + "=" * 60)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: كل مقاسات الصفحات تحت الحد ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
