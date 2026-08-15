"""اختبار كشف ترميز الـ PDF المكسور — بدون أي نداء API.

العيب اللي الاختبار ده موجود عشانه: كتاب شرعي فيه ١١٧ صفحة، ٧٩ منها
بتستخدم خطوط مجمع الملك فهد للمصحف (QCF_P001…QCF_P604). الخطوط دي فيها
خط مستقل لكل صفحة من المصحف، والشكل جواه رقمه هو ترتيبه على الصفحة،
فالنص المستخرَج منها نقاط ترميز متتالية مالهاش أي معنى.

الأخطر إن التطبيع بعد كده بيحوّل الأرقام دي لحروف عربية شكلها سليم،
فالمقطع بيعدّي على كل فحص وبيتبعت للترجمة وبيوصل للملف النهائي.
الفحص القديم كان بيعدّ الحروف بس، والحروف كانت موجودة.
"""
from __future__ import annotations

import io
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import fitz  # noqa: E402

from app.tools.translator.formats import pdf_fmt  # noqa: E402

WORK = Path("storage/samples/pdfenc")


def main() -> int:  # noqa: C901
    failures: list[str] = []

    # ---------- 1) أسماء الخطوط ----------
    print("=== 1) التعرّف على الخطوط اللي بترقّم الأشكال ===")
    glyph_indexed = [
        "QCF_P049", "QCF_P001", "QCF_P604", "QCFP123",
        "KFGQPCArabicSymbols01", "kfgqpc-hafs",
    ]
    ordinary = [
        "SakkalMajalla", "TimesNewRomanPSMT", "KalligArb-Regular",
        "mylotus", "Calibri", "AGA-Arabesque", "GESSTwoBold-Bold",
        # مايتلغبطش مع خط اسمه بيبدأ بحروف قريبة
        "QuattrocentoSans", "Qahiri", "KFC-Display",
    ]
    for name in glyph_indexed:
        hit = bool(pdf_fmt._GLYPH_INDEXED_FONTS.match(name))  # noqa: SLF001
        print(f"  {'✓' if hit else '✗'} {name:<26} → مرقَّم")
        if not hit:
            failures.append(f"خط مرقَّم مااتكشفش: {name}")
    for name in ordinary:
        hit = bool(pdf_fmt._GLYPH_INDEXED_FONTS.match(name))  # noqa: SLF001
        print(f"  {'✓' if not hit else '✗'} {name:<26} → عادي")
        if hit:
            failures.append(f"خط عادي اتعلّم كمرقَّم: {name} — هيروح OCR بلا داعي")

    # ---------- 2) التسلسل ----------
    print("\n=== 2) كشف تسلسل نقاط الترميز ===")
    cases = [
        # المسافات بين الأشكال هي اللي كانت بتخفي المشكلة عن الفحص
        ("ﯛ ﯜﯝ ﯞ ﯟ ﯠ ﯡ", 7, "أشكال مرقَّمة بمسافات"),
        ("ﯛﯜﯝﯞﯟﯠ", 6, "أشكال مرقَّمة ملتصقة"),
        ("بسم الله الرحمن الرحيم", 2, "نص عربي سليم"),
        ("المادة 1. يلتزم الطرف الأول بتقديم الخدمات", 2, "بند قانوني"),
        ("The First Party shall provide the services", 2, "نص إنجليزي"),
        ("abcdef", 6, "لاتيني متسلسل — حالة حدّية"),
    ]
    for text, expected_min, label in cases:
        run = pdf_fmt._longest_sequential_run(text)  # noqa: SLF001
        flagged = run >= pdf_fmt._SEQUENTIAL_RUN  # noqa: SLF001
        should = expected_min >= pdf_fmt._SEQUENTIAL_RUN  # noqa: SLF001
        ok = flagged == should
        print(f"  {'✓' if ok else '✗'} {label:<28} أطول تسلسل={run}")
        if not ok:
            failures.append(f"{label}: تسلسل={run} والحكم غلط")

    # النص العربي الطبيعي مالوش يطلع تسلسل طويل أبدًا
    natural = (
        "قال تعالى وأحل الله البيع وحرم الربا وهو ما استقر عليه "
        "العمل في المصارف الإسلامية المعاصرة"
    )
    if pdf_fmt._longest_sequential_run(natural) >= pdf_fmt._SEQUENTIAL_RUN:  # noqa: SLF001
        failures.append("نص عربي طبيعي اتعلّم كترميز مكسور")

    # ---------- 3) التطبيع بيغسل الغلط ----------
    print("\n=== 3) ليه العيب كان خفي: التطبيع بيغسل الأرقام لحروف ===")
    garbage = "".join(chr(0xFBDB + i) for i in range(10))
    washed = unicodedata.normalize("NFKC", garbage)
    print(f"  خام     : {[hex(ord(c)) for c in garbage[:5]]}")
    print(f"  بعد NFKC: {washed[:14]!r}")
    print("  ^ أرقام أشكال بقت حروفًا عربية شكلها سليم ومعناها صفر")
    arabic_after = sum(1 for c in washed if 0x0600 <= ord(c) <= 0x06FF)
    if arabic_after == 0:
        failures.append(
            "التطبيع مابقاش بيحوّل الأشكال لحروف — الافتراض اللي "
            "الكشف مبني عليه اتغيّر"
        )

    # ---------- 4) الحكم على مستوى الملف ----------
    print("\n=== 4) عتبة الحكم على الملف ===")
    scenarios = [
        (117, 79, True, "الكتاب الشرعي الحقيقي (٦٨٪)"),
        (100, 5, False, "خمس صفحات بس (٥٪) — مايستاهلش OCR للملف كله"),
        (100, 30, True, "ثلث الملف"),
        (100, 0, False, "ملف سليم"),
        (10, 2, True, "ملف صغير خُمسه مكسور"),
    ]
    for pages, broken, expected, label in scenarios:
        info = pdf_fmt.PdfDiagnosis(
            page_count=pages,
            char_count=pages * 900,
            is_scanned=False,
            has_text_layer=True,
            pages_without_text=[],
            unreliable_pages=list(range(1, broken + 1)),
        )
        ok = info.needs_ocr == expected
        print(f"  {'✓' if ok else '✗'} {label:<38} "
              f"{info.unreliable_ratio:>4.0%} → OCR={info.needs_ocr}")
        if not ok:
            failures.append(f"{label}: الحكم {info.needs_ocr} والمتوقع {expected}")

    # ---------- 5) ملف حقيقي ----------
    print("\n=== 5) ملف PDF مبني للاختبار ===")
    WORK.mkdir(parents=True, exist_ok=True)

    clean = WORK / "clean.pdf"
    document = fitz.open()
    for _ in range(4):
        page = document.new_page()
        for row in range(8):
            page.insert_text(
                (50, 80 + row * 30),
                "This is an ordinary page with a real text layer.",
                fontsize=12,
            )
    document.save(str(clean))
    document.close()

    info = pdf_fmt.diagnose(clean)
    print(f"  ملف سليم    : مكسور={len(info.unreliable_pages)} · "
          f"OCR={info.needs_ocr}")
    if info.needs_ocr:
        failures.append("ملف سليم اتوجّه للـ OCR — ده بيكلّف فلوس بلا داعي")

    # صفحة مرقَّمة بالأشكال مش ممكن تتبني هنا: الخط الافتراضي مالوش
    # أشكال للنقاط دي فبيستبدلها كلها بـ «·»، وبناء الحالة بجد محتاج
    # خط مصحف مضمَّن. الفحص المركَّب بيتختبر على صفحة صورية بدل كده.
    print("\n=== 6) الفحص المركَّب على مستوى الصفحة ===")

    class StubPage:
        def __init__(self, fonts: list[str], text: str) -> None:
            self._fonts = fonts
            self._text = text

        def get_fonts(self, full=True):  # noqa: ARG002, FBT002
            # PyMuPDF بيرجّع البادئة العشوائية مع اسم الخط
            return [
                (0, "", "Type0", f"ABCDEF+{name}", "", "Identity-H")
                for name in self._fonts
            ]

        def get_text(self):
            return self._text

    page_cases = [
        (["QCF_P049", "SakkalMajalla"], "نص عادي هنا", True,
         "خط مصحف مع خط عادي"),
        (["SakkalMajalla"], " ".join(chr(0xFBDB + i) for i in range(12)), True,
         "خط عادي لكن النص متسلسل"),
        (["SakkalMajalla", "mylotus"], "بسم الله الرحمن الرحيم وبعد", False,
         "صفحة سليمة تمامًا"),
        (["KalligArb-Regular"], "المادة 1. يلتزم الطرف الأول بالتسليم", False,
         "بند قانوني بخط عربي عادي"),
    ]
    for fonts, text, expected, label in page_cases:
        got = pdf_fmt._page_is_unreliable(StubPage(fonts, text))  # noqa: SLF001
        ok = got == expected
        print(f"  {'✓' if ok else '✗'} {label:<32} → مكسور={got}")
        if not ok:
            failures.append(f"{label}: الحكم {got} والمتوقع {expected}")

    # ---------- 7) السبب بيتسجّل ----------
    print("\n=== 7) سبب اللجوء للـ OCR بيتسجّل ===")
    real_diagnose = pdf_fmt.diagnose
    pdf_fmt.diagnose = lambda _path: pdf_fmt.PdfDiagnosis(  # type: ignore[assignment]
        page_count=117,
        char_count=121_795,
        is_scanned=False,
        has_text_layer=True,
        pages_without_text=[],
        unreliable_pages=list(range(1, 80)),
    )
    try:
        _, fmt, meta = pdf_fmt.prepare(clean, WORK / "work")
    finally:
        pdf_fmt.diagnose = real_diagnose  # type: ignore[assignment]

    print(f"  صيغة العمل={fmt} · needs_ocr={meta.get('needs_ocr')} · "
          f"السبب={meta.get('ocr_reason')} · "
          f"صفحات مكسورة={meta.get('unreliable_page_count')}")
    if not meta.get("needs_ocr"):
        failures.append("ملف ترميزه مكسور عدّى من غير OCR — ده العيب الأصلي")
    if meta.get("ocr_reason") != "unreliable_encoding":
        failures.append("سبب اللجوء للـ OCR مااتسجّلش — المستخدم مش هيعرف ليه اتكلّف")
    if meta.get("unreliable_page_count") != 79:
        failures.append("عدد الصفحات المكسورة مااتسجّلش")

    print("\n" + "=" * 64)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: الترميز المكسور بيتكشف قبل ما يوصل للترجمة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
