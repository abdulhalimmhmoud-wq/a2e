"""اختبار جلب الترجمات المعتمدة على خادم شغّال.

شغّل الخادم الأول: python -m uvicorn app.main:app --port 8000

بيرفع مستندًا فيه آية وحديث، ويتأكد إن الآية بتتجاب بإسنادها من
quran.com وإن المقطع بيفضل مقفولًا وغير معتمد.

نداءات quran.com مجانية ومفيش أي استهلاك API مدفوع هنا.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

import requests  # noqa: E402

BASE = "http://127.0.0.1:8000/api"
WORK = Path("storage/samples/sacred")

PARAGRAPHS = [
    "عقد مرابحة إسلامية",
    "المادة 1. يلتزم البائع بتسليم البضاعة في الموعد المتفق عليه.",
    "قال تعالى: ﴿وَأَحَلَّ اللَّهُ الْبَيْعَ وَحَرَّمَ الرِّبَا﴾",
    "المادة 2. تسري على هذا العقد أحكام الشريعة الإسلامية.",
    "قال رسول الله صلى الله عليه وسلم: «المسلمون على شروطهم» رواه البخاري.",
]


def build_docx(path: Path) -> None:
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement

    doc = Document()
    for line in PARAGRAPHS:
        paragraph = doc.add_paragraph(line)
        paragraph._p.get_or_add_pPr().append(OxmlElement("w:bidi"))  # noqa: SLF001
        paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def main() -> int:  # noqa: C901
    failures: list[str] = []
    project_id = None

    try:
        requests.get(f"{BASE}/config", timeout=5)
    except requests.RequestException:
        print("!! الخادم مش شغّال على 8000")
        return 1

    # ---------- 0) الترجمات المتاحة ----------
    print("=== 0) المصادر ===")
    catalogue = requests.get(f"{BASE}/sources/translations", timeout=60)
    if catalogue.status_code != 200:
        failures.append(f"قائمة الترجمات: HTTP {catalogue.status_code}")
    else:
        data = catalogue.json()
        current = [
            t for t in data["translations"] if t["id"] == data["current"]
        ]
        print(f"  ترجمات متاحة: {len(data['translations'])}")
        print(f"  المختارة: id={data['current']} · "
              f"{current[0]['name'] if current else '؟'}")
        print(f"  مفتاح sunnah.com: {data['has_sunnah_key']}")
        if not current:
            failures.append("معرّف الترجمة المضبوط مش في قائمة quran.com")

    source = WORK / "resolve_ar.docx"
    build_docx(source)

    try:
        # ---------- 1) مشروع وملف ----------
        project = requests.post(
            f"{BASE}/projects",
            json={
                "name": "__اختبار المصادر المعتمدة__",
                "source_lang": "ar",
                "target_lang": "en",
                "domain": "religious",
            },
            timeout=60,
        )
        project.raise_for_status()
        project_id = project.json()["id"]

        with source.open("rb") as handle:
            upload = requests.post(
                f"{BASE}/projects/{project_id}/files",
                files={"file": (source.name, handle, "")},
                timeout=120,
            )
        upload.raise_for_status()
        file_id = upload.json()["id"]

        # الرفع بيحفظ الملف بس؛ الاستخراج مهمة منفصلة لازم تتطلب
        import time

        started = requests.post(f"{BASE}/files/{file_id}/extract", timeout=60)
        started.raise_for_status()

        for _ in range(90):
            info = requests.get(f"{BASE}/files/{file_id}", timeout=30).json()
            if info.get("segment_count"):
                break
            if info.get("status") == "failed":
                failures.append(f"الاستخراج فشل: {info}")
                break
            time.sleep(1)

        segments = requests.get(
            f"{BASE}/files/{file_id}/segments?limit=200", timeout=60
        ).json()["items"]
        locked = [s for s in segments if s["is_locked"]]
        print(f"\n=== 1) الاستخراج ===")
        print(f"  مقاطع: {len(segments)} · مقفول: {len(locked)}")
        for segment in locked:
            print(f"    🔒 {segment['source_text'][:50]}")

        if len(locked) < 2:
            failures.append(f"متوقع مقطعين مقفولين على الأقل، طلع {len(locked)}")

        # ---------- 2) الجلب ----------
        print("\n=== 2) جلب الترجمات المعتمدة ===")
        response = requests.post(
            f"{BASE}/files/{file_id}/sacred/resolve", timeout=300
        )
        if response.status_code != 200:
            failures.append(
                f"الجلب: HTTP {response.status_code} — {response.text[:200]}"
            )
            raise SystemExit(1)

        result = response.json()
        print(f"  مفحوص: {result['checked']} · اتجاب: {result['resolved']} · "
              f"ملتبس: {result['ambiguous']} · يدوي: {result['manual']}")
        print(f"  الترجمة: {result['translation_name']}")
        for item in result["items"]:
            print(f"\n    [{item['kind']}] {item['status']}  {item['reference']}")
            if item["attribution"]:
                print(f"      إسناد: {item['attribution']}")
            if item["text"]:
                print(f"      {item['text'][:70]}")
            if item["note"]:
                print(f"      {item['note'][:70]}")
            print(f"      {item['url'][:70]}")

        if not result["translation_name"]:
            failures.append("اسم الترجمة مااترجعش — الإسناد ناقص")

        quran = [i for i in result["items"] if i["kind"] == "quran"]
        if not quran:
            failures.append("الآية مااتفحصتش")
        elif quran[0]["status"] != "resolved":
            failures.append(f"الآية مااتجابتش: {quran[0]['status']}")
        else:
            if quran[0]["reference"] != "2:275":
                failures.append(
                    f"الآية اتحدّدت غلط: {quran[0]['reference']} بدل 2:275"
                )
            if not quran[0]["attribution"]:
                failures.append("الآية اتجابت من غير إسناد")

        hadith = [i for i in result["items"] if i["kind"] == "hadith"]
        if not hadith:
            failures.append("الحديث مااتفحصش")
        elif not hadith[0]["url"].startswith("https://sunnah.com"):
            failures.append("الحديث مااترجعش برابط sunnah.com")

        # ---------- 3) المقطع بعد الجلب ----------
        print("\n=== 3) حالة المقاطع بعد الجلب ===")
        segments = requests.get(
            f"{BASE}/files/{file_id}/segments?limit=200", timeout=60
        ).json()["items"]
        for segment in segments:
            if not segment["is_locked"]:
                continue
            print(f"  🔒 {segment['source_text'][:44]}")
            print(f"     الهدف: {segment['target_text'][:56]}")
            print(f"     الحالة: {segment['status']} · المصدر: {segment['origin']}")
            print(f"     ملاحظات: {segment['notes'][:70]}")

            if segment["status"] == "approved":
                failures.append(
                    "المقطع اتعتمد تلقائيًا — النقل من مصدر خارجي مش اعتماد"
                )
            if not segment["is_locked"]:
                failures.append("القفل اتفك بعد الجلب")

        filled = [
            s for s in segments if s["is_locked"] and s["target_text"].strip()
        ]
        if not filled:
            failures.append("مفيش أي مقطع مقفول اتملى بترجمة")
        for segment in filled:
            if segment["origin"] != "source":
                failures.append(
                    f"المصدر اتسجّل «{segment['origin']}» مش «source» — "
                    "ده اللي بيمنع دخوله ذاكرة الترجمة"
                )
            if not segment["notes"]:
                failures.append("الإسناد مااتسجّلش مع المقطع")

        # ---------- 4) الاعتماد مايدخّلش الذاكرة ----------
        # ترجمة منقولة من مصدر خارجي مش شغلك، فمالهاش تتخزّن في ذاكرتك
        # وترجع في مشاريع تانية كأنها ترجمتك.
        print("\n=== 4) الاعتماد مايدخّلش ترجمة منقولة في الذاكرة ===")
        from app.core.db import SessionLocal
        from app.models import TMEntry

        db = SessionLocal()
        try:
            before = db.query(TMEntry).count()
            requests.post(f"{BASE}/files/{file_id}/approve-all", timeout=120)
            db.expire_all()
            after = db.query(TMEntry).count()
            verse_rows = (
                db.query(TMEntry)
                .filter(TMEntry.source_text.like("%وَأَحَلَّ%"))
                .count()
            )
            print(f"  مدخلات الذاكرة: {before} → {after}")
            print(f"  الآية في الذاكرة: {verse_rows} (المفروض 0)")
            if verse_rows:
                failures.append(
                    "ترجمة منقولة من quran.com دخلت ذاكرتك — هتترجع في "
                    "مشاريع تانية كأنها ترجمتك"
                )
        finally:
            db.close()

    finally:
        if project_id:
            requests.delete(f"{BASE}/projects/{project_id}", timeout=120)
            print("\n  اتمسح المشروع الاختباري")

    print("\n" + "=" * 64)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: الترجمات المعتمدة بتتجاب بإسنادها ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
