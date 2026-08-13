"""اختبارات المقسّم العربي — الحالات اللي بتكسر المقسّمات الجاهزة."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.tools.translator.segment import split_sentences, verify_coverage  # noqa: E402

# (النص، العدد المتوقع للمقاطع، وصف الحالة)
CASES: list[tuple[str, int, str]] = [
    ("جملة واحدة بسيطة.", 1, "جملة واحدة"),
    ("الجملة الأولى. الجملة الثانية.", 2, "جملتان"),
    ("هل هذا صحيح؟ نعم صحيح.", 2, "استفهام عربي"),
    ("انتبه! هذا مهم.", 2, "تعجب"),
    # الأفخاخ
    ("المادة 1. يلتزم الطرف الأول بتقديم الخدمات.", 1, "ترقيم مادة قانونية"),
    ("المادة 12. تبلغ القيمة 150.000 ريال.", 1, "مادة + رقم بفواصل"),
    ("بلغت النسبة 3.14 بالمئة فقط.", 1, "رقم عشري"),
    ("Article 5. The party shall comply.", 1, "ترقيم إنجليزي"),
    ("راجع الجدول 3. القيم موضحة أعلاه.", 2, "إحالة لجدول ثم جملة جديدة"),
    ("انظر Fig. 2 للتوضيح.", 1, "اختصار علمي"),
    ("قال د. أحمد إن العقد سارٍ.", 1, "لقب مختصر"),
    ("النقاط الثلاث... ثم نكمل.", 1, "نقاط متتالية"),
    ("البند (أ). يسري هذا الشرط.", 1, "ترقيم بحرف"),
    ("سطر أول\nسطر ثانٍ", 2, "فاصل سطر"),
    ("جملة أولى. جملة ثانية. جملة ثالثة.", 3, "ثلاث جمل"),
    ('قال: "نعم." ثم غادر.', 2, "علامات اقتباس"),
]


def main() -> int:
    failures: list[str] = []
    print(f"{'الحالة':<28} {'متوقع':>6} {'فعلي':>6}   الحالة")
    print("-" * 70)

    for text, expected, label in CASES:
        spans = split_sentences(text)
        actual = len(spans)

        # الضمان الأهم: التقسيم مايفقدش ولا حرف
        if not verify_coverage(text, spans):
            failures.append(f"[{label}] فقدان نص أثناء التقسيم")
            status = "✗ فقدان"
        elif actual != expected:
            failures.append(f"[{label}] متوقع {expected} فعلي {actual}: {text!r}")
            status = "✗"
        else:
            status = "✓"

        print(f"{label:<28} {expected:>6} {actual:>6}   {status}")
        if actual != expected:
            for span in spans:
                print(f"        → {span.text!r}")

    # لا مقاطع تبدأ بمسافة
    for text, _, label in CASES:
        for span in split_sentences(text):
            if span.text != span.text.strip() and span.text.strip():
                failures.append(f"[{label}] مقطع فيه مسافات زائدة: {span.text!r}")

    print("-" * 70)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print(f"نجح: {len(CASES)}/{len(CASES)} حالة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
