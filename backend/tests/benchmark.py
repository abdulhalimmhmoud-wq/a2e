"""قياس الأداء — بيحدد فين الوقت بيروح فعلًا قبل أي تحسين.

بيبني ملف كبير صناعي وذاكرة ترجمة كبيرة، وبيقيس كل مرحلة على حدة.
مفيش أي نداء API هنا.

الاختبار ده بيشتغل على **قاعدة بيانات منفصلة** مؤقتة. النسخة الأولى
منه كانت بتزرع أربع آلاف مدخل صناعي في ذاكرة الترجمة الحقيقية وتسيبهم،
فكانوا بيطلعوا بعد كده كمطابقات تقريبية في شغل حقيقي.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# لازم يتظبط قبل أي استيراد بيقرا الإعدادات: الإعدادات مخزّنة بـ lru_cache
# والمحرّك بيتبني وقت استيراد app.core.db
_BENCH_DIR = Path(tempfile.gettempdir()) / "tarjuman_benchmark"
_BENCH_DIR.mkdir(parents=True, exist_ok=True)
os.environ["DB_PATH"] = str(_BENCH_DIR / "benchmark.db")
os.environ["STORAGE_DIR"] = str(_BENCH_DIR)

from sqlalchemy import func, select  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.models import Project, Segment, SourceFile, TMEntry  # noqa: E402
from app.tools.translator import pipeline, tm  # noqa: E402
from app.tools.translator.costing import estimate_project  # noqa: E402
from app.tools.translator.formats.base import text_hash  # noqa: E402

BIG_DOC = _BENCH_DIR / "big_ar.docx"
SEGMENTS = 1500
TM_ENTRIES = 4000

_timings: dict[str, float] = {}


@contextmanager
def timed(label: str):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    _timings[label] = elapsed
    print(f"  {label:<44} {elapsed * 1000:>9.0f} مللي")


def build_big_docx(path: Path, paragraphs: int) -> None:
    if path.exists():
        return
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement

    doc = Document()
    for i in range(paragraphs):
        p = doc.add_paragraph(
            f"المادة {i + 1}. يلتزم الطرف الأول بتقديم الخدمات الاستشارية "
            f"المتفق عليها خلال مدة أقصاها {30 + i % 60} يومًا من تاريخ التوقيع."
        )
        ppr = p._p.get_or_add_pPr()  # noqa: SLF001
        ppr.append(OxmlElement("w:bidi"))
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def seed_tm(db, count: int, domain: str) -> None:
    existing = db.execute(
        select(func.count()).select_from(TMEntry).where(TMEntry.domain == domain)
    ).scalar_one()
    if existing >= count:
        print(f"  الذاكرة فيها {existing} مدخل بالفعل")
        return

    rows = []
    for i in range(existing, count):
        source = (
            f"بند تجريبي رقم {i} في وثيقة قياس الأداء بصياغة قانونية معتادة."
        )
        rows.append(
            {
                "source_hash": text_hash(source),
                "source_text": source,
                "target_text": f"Benchmark clause number {i} in standard legal wording.",
                "source_lang": "ar",
                "target_lang": "en",
                "domain": domain,
                "usage_count": 0,
            }
        )
    db.bulk_insert_mappings(TMEntry, rows)
    db.commit()
    print(f"  اتزرع {len(rows)} مدخل في الذاكرة")


def main() -> int:
    from app.core.config import settings

    # شبكة أمان: لو التوجيه فوق اتكسر لأي سبب، الاختبار يقف قبل ما
    # يزرع آلاف المدخلات الصناعية في ذاكرة الترجمة الحقيقية.
    if _BENCH_DIR not in settings.db_path.parents:
        print(f"!! قاعدة البيانات مش معزولة: {settings.db_path}")
        return 1

    init_db()
    print(f"  قاعدة معزولة: {settings.db_path}")
    print(f"=== تجهيز: {SEGMENTS} فقرة · {TM_ENTRIES} مدخل ذاكرة ===")
    build_big_docx(BIG_DOC, SEGMENTS)
    print(f"  حجم الملف: {BIG_DOC.stat().st_size / 1024:.0f} كب")

    db = SessionLocal()
    project = None
    try:
        seed_tm(db, TM_ENTRIES, "legal")

        project = Project(name="قياس الأداء", domain="legal")
        db.add(project)
        db.commit()

        print("\n=== المراحل ===")

        with timed("استيعاب الملف (نسخ + بصمة)"):
            file = pipeline.ingest(db, project, BIG_DOC, BIG_DOC.name)
            db.commit()

        with timed("الاستخراج + التقسيم + الحفظ"):
            stats = pipeline.extract_and_segment(db, file)
            db.commit()
        print(f"    → {stats.units} وحدة · {stats.segments} مقطع")

        segments = db.execute(
            select(Segment).where(
                Segment.file_id == file.id, Segment.is_translatable.is_(True)
            )
        ).scalars().all()

        texts = [s.source_text for s in segments]

        with timed(f"بحث تام — مفرد (المسار القديم، {len(segments)} مقطع)"):
            hits_one = sum(
                1 for t in texts if tm.lookup_exact(db, t, "ar", "en", "legal")
            )

        with timed(f"بحث تام — جماعي (المسار الحالي، {len(segments)} مقطع)"):
            hits_many = tm.lookup_exact_many(db, texts, "ar", "en", "legal")
        print(f"    → مفرد={hits_one} جماعي={len(hits_many)}")

        sample = segments[:20]
        with timed(f"بحث الذاكرة التقريبي ({len(sample)} مقطع)"):
            for s in sample:
                tm.lookup_fuzzy(db, s.source_text, "ar", "en", "legal")

        with timed("تقدير التكلفة (نقطة /estimate)"):
            file_ids = [file.id]
            rows = db.execute(
                select(Segment.source_text).where(
                    Segment.file_id.in_(file_ids), Segment.is_translatable.is_(True)
                )
            ).scalars().all()
            batch = rows[:500]
            covered = tm.lookup_exact_many(db, batch, "ar", "en", "legal")
            estimate_project(
                words=file.word_count,
                chars=file.char_count,
                pages=file.page_count,
                segments=file.segment_count,
                reuse_ratio=len(covered) / len(batch) if batch else 0.0,
            )

        with timed("ملخّص التقدّم (file_progress)"):
            pipeline.file_progress(db, file.id)

        with timed("صفحة مقاطع (200 مقطع)"):
            db.execute(
                select(Segment)
                .where(Segment.file_id == file.id)
                .order_by(Segment.order_index)
                .limit(200)
            ).scalars().all()

        with timed("إعادة تركيب الوحدات (تصدير)"):
            pipeline.assemble_units(db, file)

        with timed("الدمج والتصدير الفعلي"):
            pipeline.export_file(db, file)
            db.commit()

    finally:
        if project is not None:
            import shutil

            folder = pipeline.project_dir(project.id)
            db.query(Project).filter(Project.id == project.id).delete()
            db.commit()
            shutil.rmtree(folder, ignore_errors=True)
        db.close()

    print("\n=== الترتيب حسب الزمن ===")
    for label, seconds in sorted(_timings.items(), key=lambda kv: -kv[1]):
        share = seconds / sum(_timings.values()) * 100
        bar = "█" * max(1, round(share / 3))
        print(f"  {seconds * 1000:>8.0f} مللي  {share:>5.1f}%  {bar}  {label}")

    print(f"\n  الإجمالي: {sum(_timings.values()):.1f} ثانية "
          f"(بدون أي نداء API)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
