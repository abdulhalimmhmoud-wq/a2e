"""فحص نقاط استخراج المصطلحات على خادم شغّال.

شغّل الخادم الأول: python -m uvicorn app.main:app --port 8000

كل الكتابة بتحصل في مجال مخصوص للاختبار (__test__) والاختبار بيمسح
اللي كتبه هو بس. النسخة الأولى من الفحص ده كانت بتمسح بالاسم، فمسحت
مصطلحات كانت موجودة قبله.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests  # noqa: E402

BASE = "http://127.0.0.1:8000/api"
DOMAIN = "__test__"
SAMPLES = Path("storage/samples/terms")


def show(result: dict, title: str) -> None:
    print(f"\n=== {title} ===")
    print(f"  أزواج مفحوصة: {result['pairs_examined']} · "
          f"مرشّحون: {len(result['candidates'])} · "
          f"تكلفة: ${result['cost_usd']:.6f}")
    for warning in result["warnings"]:
        print(f"    ! {warning[:76]}")
    for candidate in result["candidates"][:8]:
        marks = []
        if candidate["exists"]:
            marks.append("موجود")
        if candidate["conflicts_with"]:
            marks.append(f"متعارض مع «{candidate['conflicts_with']}»")
        if candidate["alternatives"]:
            marks.append(f"منافس: {'، '.join(candidate['alternatives'])}")
        suffix = f"   [{' · '.join(marks)}]" if marks else ""
        print(f"    {candidate['source_term']} → {candidate['target_term']}{suffix}")


def import_csv(path: Path) -> dict:
    with path.open("rb") as handle:
        response = requests.post(
            f"{BASE}/glossary/import",
            params={"domain": DOMAIN},
            files={"file": (path.name, handle, "text/csv")},
            timeout=60,
        )
    response.raise_for_status()
    return response.json()


def main() -> int:  # noqa: C901
    failures: list[str] = []
    created: list[str] = []

    if not (SAMPLES / "terms.csv").exists():
        print("!! شغّل test_terms.py الأول عشان يجهّز الملفات النموذجية")
        return 1

    try:
        requests.get(f"{BASE}/config", timeout=5)
    except requests.RequestException:
        print("!! الخادم مش شغّال على 8000")
        return 1

    # ---------- 1) استيراد جدول ----------
    imported = import_csv(SAMPLES / "terms.csv")
    show(imported, "1) استيراد جدول")
    if len(imported["candidates"]) != 3:
        failures.append(f"استيراد: متوقع 3، طلع {len(imported['candidates'])}")
    if imported["cost_usd"] != 0:
        failures.append("استيراد الجدول المفروض مجاني — مفيش نداء نموذج فيه")
    if any(c["exists"] for c in imported["candidates"]):
        failures.append("مجال الاختبار المفروض يبدأ فاضي")

    # ---------- 2) إضافة دفعة ----------
    payload = {
        "terms": [
            {
                "source_term": c["source_term"],
                "target_term": c["target_term"],
                "domain": DOMAIN,
                "project_id": None,
                "notes": c["note"],
            }
            for c in imported["candidates"]
        ]
    }
    added = requests.post(f"{BASE}/glossary/bulk", json=payload, timeout=60)
    added.raise_for_status()
    print(f"\n=== 2) إضافة دفعة ===\n  {added.json()}")
    if added.json()["added"] != 3:
        failures.append(f"إضافة دفعة: أُضيف {added.json()['added']} بدل 3")

    created = [
        t["id"]
        for t in requests.get(f"{BASE}/glossary", timeout=60).json()
        if t["domain"] == DOMAIN
    ]

    try:
        # ---------- 3) نفس الملف تاني ----------
        again = import_csv(SAMPLES / "terms.csv")
        show(again, "3) نفس الملف تاني — لازم يتعلّم «موجود»")
        if not all(c["exists"] for c in again["candidates"]):
            failures.append(
                "الاستيراد التاني ماعلّمش المصطلحات كموجودة — "
                "المراجع هيضيفها تاني وهو مش واخد باله"
            )

        # ---------- 4) ترجمة مختلفة لنفس المصطلح ----------
        clash_file = SAMPLES / "conflict.csv"
        clash_file.write_text(
            "المصطلح,الترجمة\nالقوة القاهرة,Act of God\n", encoding="utf-8-sig"
        )
        clash = import_csv(clash_file)
        show(clash, "4) ترجمة مختلفة — لازم يتعلّم «متعارض»")
        if not clash["candidates"]:
            failures.append("التعارض: مافيش مرشّحين أصلًا")
        else:
            first = clash["candidates"][0]
            if first["conflicts_with"] != "Force Majeure":
                failures.append(
                    "التعارض مااتكشفش — المراجع هيدوس على ترجمة موجودة "
                    "من غير ما يعرف"
                )
            if first["exists"]:
                failures.append("ترجمة مختلفة اتعلّمت «موجودة» — ده بيخفي التعارض")

        # ---------- 5) ترجمتين لنفس المصطلح في نفس النتيجة ----------
        rival_file = SAMPLES / "rivals.csv"
        rival_file.write_text(
            "المصطلح,الترجمة\n"
            "محكمة النقض,Court of Cassation\n"
            "محكمة النقض,Supreme Court\n"
            "محكمة النقض,Court of Cassation\n",
            encoding="utf-8-sig",
        )
        rivals = import_csv(rival_file)
        show(rivals, "5) ترجمتين لنفس المصطلح في نفس النتيجة")

        # الصف المكرر حرفيًا المفروض يتعرض مرة واحدة. (في جدول
        # مصطلحات، تكرار الصف مش دليل على شيوع المصطلح، فمش بيتحوّل
        # لعدّاد — على عكس الاستخراج من نص.)
        if len(rivals["candidates"]) != 2:
            failures.append(
                f"التكرار التام مااتدمجش: {len(rivals['candidates'])} مرشّح بدل 2"
            )
        if not all(c["alternatives"] for c in rivals["candidates"]):
            failures.append(
                "الترجمات المتنافسة في نفس النتيجة مااتعلّمتش — "
                "اختيار الاتنين بيدّي مصطلح واحد بصمت"
            )
        rivalry = {
            c["target_term"]: set(c["alternatives"]) for c in rivals["candidates"]
        }
        if rivalry.get("Court of Cassation") != {"Supreme Court"} or \
                rivalry.get("Supreme Court") != {"Court of Cassation"}:
            failures.append(f"المنافسة اتسجّلت غلط: {rivalry}")

        # ---------- 6) من ذاكرة الترجمة ----------
        mined = requests.post(
            f"{BASE}/glossary/mine",
            json={
                "source_lang": "ar",
                "target_lang": "en",
                "domain": "legal",
                "limit": 50,
            },
            timeout=300,
        )
        if mined.status_code != 200:
            failures.append(f"الذاكرة: HTTP {mined.status_code} — {mined.text[:160]}")
        else:
            show(mined.json(), "6) من ذاكرة الترجمة (قراءة فقط)")
            sources = [c["source_term"] for c in mined.json()["candidates"]]
            if len(sources) != len(set(sources)):
                failures.append("الاستخراج من الذاكرة رجّع نفس المصطلح مرتين")

        # ---------- 7) من ملف وترجمته ----------
        with (SAMPLES / "contract_ar.docx").open("rb") as source, \
             (SAMPLES / "contract_en.docx").open("rb") as target:
            extracted = requests.post(
                f"{BASE}/glossary/extract",
                params={
                    "source_lang": "ar",
                    "target_lang": "en",
                    "domain": DOMAIN,
                },
                files={
                    "source_file": ("contract_ar.docx", source, ""),
                    "target_file": ("contract_en.docx", target, ""),
                },
                timeout=300,
            )
        if extracted.status_code != 200:
            failures.append(
                f"من ملفين: HTTP {extracted.status_code} — {extracted.text[:200]}"
            )
        else:
            result = extracted.json()
            show(result, "7) من ملف وترجمته")
            if not result["candidates"]:
                failures.append("من ملفين: مفيش مصطلحات من عقد قانوني واضح")
            known = [
                c for c in result["candidates"]
                if c["source_term"] == "القوة القاهرة"
            ]
            if known and not (known[0]["exists"] or known[0]["conflicts_with"]):
                failures.append(
                    "مصطلح موجود بالفعل في القاعدة مااتعلّمش في نتيجة الاستخراج"
                )

    finally:
        # بنمسح بالمُعرّف اللي إحنا عملناه، مش بالاسم
        for term_id in created:
            requests.delete(f"{BASE}/glossary/{term_id}", timeout=60)
        leftovers = [
            t for t in requests.get(f"{BASE}/glossary", timeout=60).json()
            if t["domain"] == DOMAIN
        ]
        for term in leftovers:
            requests.delete(f"{BASE}/glossary/{term['id']}", timeout=60)
        print(f"\n  اتنظّف {len(created) + len(leftovers)} مصطلح اختباري")

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: نقاط استخراج المصطلحات شغّالة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
