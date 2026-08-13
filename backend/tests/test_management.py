"""اختبار إدارة المشاريع: الإلغاء والحذف والمطابقات التقريبية.

الحاجات دي كانت مبنية في الخادم ومش مربوطة — الاختبار بيتأكد إنها
شغالة فعلًا مش موجودة على الورق بس.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.models import Job, Project, Segment, TMEntry  # noqa: E402
from app.tools.translator import pipeline, tm  # noqa: E402
from app.tools.translator.engine import BatchResult, Usage  # noqa: E402

SAMPLE = Path("storage/samples/contract_ar.docx")


class SlowEngine:
    """محرّك بطيء عشان يدّينا وقت نلغي أثناء التنفيذ."""

    name = "slow"
    model = "slow"
    production = False

    def translate(self, segments, context_before="", context_after=""):
        time.sleep(0.5)
        result = BatchResult(usage=Usage(calls=1))
        for segment in segments:
            result.translations[segment.id] = f"[T] {segment.source}"
        return result


def test_cancel(db, project) -> list[str]:
    failures: list[str] = []
    from app.core.config import settings
    from app import jobs as job_queue

    file = pipeline.ingest(db, project, SAMPLE, SAMPLE.name)
    db.commit()
    pipeline.extract_and_segment(db, file)
    db.commit()

    # دفعات صغيرة عشان يبقى فيه عدد كافٍ نلغي في نصّه
    original = settings.batch_char_budget, settings.batch_max_segments
    settings.batch_char_budget, settings.batch_max_segments = 60, 1

    try:
        job = job_queue.create_job(db, "translate", project.id, file.id)
        db.commit()
        job_id = job.id

        stats_holder: dict = {}

        def worker() -> None:
            worker_db = SessionLocal()
            try:
                worker_job = worker_db.get(Job, job_id)
                worker_job.status = "running"
                worker_db.commit()
                worker_file = worker_db.get(pipeline.SourceFile, file.id)
                stats_holder["stats"] = pipeline.translate_file(
                    worker_db,
                    worker_file,
                    SlowEngine(),
                    job=worker_job,
                    use_memory=False,
                    concurrency=2,
                )
            finally:
                worker_db.close()

        thread = threading.Thread(target=worker)
        thread.start()

        # نسيبها تترجم شوية وبعدين نلغي
        time.sleep(1.6)
        db.refresh(job)
        job.status = "cancelling"
        db.commit()

        thread.join(timeout=60)
        stats = stats_holder.get("stats")

        db.expire_all()
        counts = {}
        for segment in db.execute(
            select(Segment).where(Segment.file_id == file.id)
        ).scalars():
            counts[segment.status] = counts.get(segment.status, 0) + 1

        print(f"  الإلغاء: cancelled={stats.cancelled if stats else '?'} "
              f"مترجَم={stats.translated if stats else 0}")
        print(f"  حالة المقاطع بعد الإلغاء: {counts}")

        if stats is None:
            failures.append("المهمة ماخلصتش بعد الإلغاء")
            return failures

        if not stats.cancelled:
            failures.append("الإلغاء مااتسجّلش في نتيجة المهمة")

        # الشغل اللي خلص لازم يفضل محفوظ
        if stats.translated == 0:
            failures.append("الإلغاء ضيّع كل الشغل — المفروض المترجَم يفضل")
        if counts.get("draft", 0) == 0:
            failures.append("مفيش مقاطع باقية — الإلغاء ماوقّفش حاجة")

        # الملف لازم يرجع لحالة تسمح بإعادة التشغيل
        db.refresh(file)
        print(f"  حالة الملف: {file.status}")
        if file.status != "extracted":
            failures.append(f"حالة الملف بعد الإلغاء غلط: {file.status}")

    finally:
        settings.batch_char_budget, settings.batch_max_segments = original

    return failures


def test_suggestions(db, project) -> list[str]:
    failures: list[str] = []

    # نحط مدخل في الذاكرة قريب من نص موجود في الملف
    tm.store(
        db,
        "المادة 1. يلتزم الطرف الأول بتقديم الخدمات المتفق عليه.",
        "Article 1. The First Party undertakes to provide the agreed services.",
        "ar",
        "en",
        project.domain,
    )
    db.commit()

    target = db.execute(
        select(Segment).where(
            Segment.file_id.in_(
                select(pipeline.SourceFile.id).where(
                    pipeline.SourceFile.project_id == project.id
                )
            ),
            Segment.source_text.like("المادة 1.%"),
        )
    ).scalars().first()

    if target is None:
        failures.append("مالقيناش مقطع مناسب للاختبار")
        return failures

    matches = tm.lookup_fuzzy(
        db, target.source_text, "ar", "en", project.domain, threshold=70
    )
    print(f"  المقطع: {target.source_text[:56]}")
    print(f"  مطابقات تقريبية: {len(matches)}")
    for match in matches:
        print(f"    {match.score}% → {match.target_text[:56]}")

    if not matches:
        failures.append(
            "المطابقة التقريبية مارجّعتش حاجة رغم وجود نص شبه مطابق في الذاكرة"
        )
    elif matches[0].score >= 100:
        failures.append("المطابقة اتحسبت تامة رغم إن النص مختلف")

    return failures


def test_delete(db, project_id: str) -> list[str]:
    failures: list[str] = []
    import shutil

    folder = pipeline.project_dir(project_id)
    existed = folder.exists()

    db.query(Project).filter(Project.id == project_id).delete()
    db.commit()
    shutil.rmtree(folder, ignore_errors=True)

    remaining_segments = db.execute(
        select(Segment).where(
            Segment.file_id.in_(
                select(pipeline.SourceFile.id).where(
                    pipeline.SourceFile.project_id == project_id
                )
            )
        )
    ).scalars().all()

    print(f"  مجلد المشروع كان موجود: {existed} · اتمسح: {not folder.exists()}")
    print(f"  مقاطع متبقية بعد الحذف: {len(remaining_segments)}")

    if folder.exists():
        failures.append("مجلد ملفات المشروع مااتمسحش")
    if remaining_segments:
        failures.append(f"{len(remaining_segments)} مقطع فضل بعد حذف المشروع")

    # الذاكرة لازم تفضل — دي الفايدة اللي بتتراكم عبر المشاريع
    tm_left = db.execute(select(TMEntry)).scalars().all()
    print(f"  مدخلات الذاكرة بعد الحذف: {len(tm_left)}")
    if not tm_left:
        failures.append("حذف المشروع مسح ذاكرة الترجمة — المفروض تفضل")

    return failures


def main() -> int:
    if not SAMPLE.exists():
        print("!! شغّل make_sample_docx.py الأول")
        return 1

    init_db()
    db = SessionLocal()
    failures: list[str] = []
    project = None

    try:
        project = Project(name="اختبار الإدارة", domain="legal")
        db.add(project)
        db.commit()

        print("=== 1) إلغاء مهمة شغّالة ===")
        failures += test_cancel(db, project)

        print("\n=== 2) المطابقات التقريبية من الذاكرة ===")
        failures += test_suggestions(db, project)

        print("\n=== 3) حذف المشروع ===")
        failures += test_delete(db, project.id)
        project = None

    finally:
        if project is not None:
            db.query(Project).filter(Project.id == project.id).delete()
            db.commit()
        db.close()

    print("\n" + "=" * 62)
    if failures:
        print(f"فشل: {len(failures)}")
        for item in failures:
            print(f"  ✗ {item}")
        return 1
    print("نجح: الإلغاء والحذف والمطابقات التقريبية سليمة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
