"""فحص تشخيصي للنظام — بيدوّر على مشاكل كامنة قبل ما تظهر في الاستخدام."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.models import Job, Project, Segment, SourceFile, TMEntry, UsageRecord  # noqa: E402
from app.tools.translator.engine import make_batches, SegmentInput  # noqa: E402


def main() -> int:
    issues: list[str] = []
    db = SessionLocal()
    try:
        # ---------- مهام معلّقة ----------
        stuck = db.execute(
            select(Job).where(Job.status.in_(["queued", "running"]))
        ).scalars().all()
        print(f"=== المهام ===")
        print(f"  معلّقة الآن: {len(stuck)}")
        for job in stuck:
            age = datetime.now(timezone.utc) - job.updated_at.replace(tzinfo=timezone.utc)
            print(f"    {job.kind} · {job.status} · عمرها {age.total_seconds()/60:.0f} دقيقة")
            if age > timedelta(minutes=30):
                issues.append(
                    f"مهمة {job.kind} معلّقة من {age.total_seconds()/60:.0f} دقيقة — "
                    "غالبًا الخادم اتقفل وهي شغالة ومفيش آلية استرجاع"
                )

        failed = db.execute(
            select(func.count()).select_from(Job).where(Job.status == "failed")
        ).scalar_one()
        print(f"  فشلت سابقًا: {failed}")

        # ---------- زمن الترجمة ----------
        print(f"\n=== الأداء ===")
        records = db.execute(
            select(UsageRecord).order_by(UsageRecord.created_at)
        ).scalars().all()
        if len(records) >= 2:
            same_file = {}
            for record in records:
                same_file.setdefault(record.file_id, []).append(record)
            for file_id, group in same_file.items():
                if len(group) < 2:
                    continue
                span = (group[-1].created_at - group[0].created_at).total_seconds()
                per_call = span / max(1, len(group) - 1)
                file = db.get(SourceFile, file_id) if file_id else None
                name = file.original_filename[:34] if file else "?"
                print(f"  {name}: {len(group)} نداء · ~{per_call:.0f} ث/نداء")

        # ---------- تقدير زمن ملف كبير ----------
        big_segments = [
            SegmentInput(id=str(i), source="نص " * 40) for i in range(3000)
        ]
        batches = make_batches(big_segments)
        workers = settings.translation_concurrency
        per_call = 30

        # الدفعة الأولى بتتنفّذ لوحدها (تسخين الكاش)، والباقي بيتوازى
        rounds = 1 + -(-(len(batches) - 1) // workers)
        minutes = rounds * per_call / 60

        print(f"\n  ملف افتراضي 3000 مقطع (~100 صفحة):")
        print(f"    عدد الدفعات: {len(batches)} · تنفيذ متوازي {workers}")
        print(f"    الزمن المتوقع (~{per_call} ث/دفعة): ~{minutes:.0f} دقيقة")
        print(f"    لو كان تتابعيًا: ~{len(batches) * per_call / 60:.0f} دقيقة")
        print(f"    بالدفعات المجمّعة: نصف التكلفة (زمن غير مضمون)")

        if minutes > 25:
            issues.append(
                f"ملف كبير لسه هياخد ~{minutes:.0f} دقيقة — "
                f"زوّد TRANSLATION_CONCURRENCY لو حدود استخدامك بتسمح"
            )

        # ---------- المقاطع غير المترجمة ----------
        print(f"\n=== المقاطع ===")
        pending = db.execute(
            select(func.count())
            .select_from(Segment)
            .where(Segment.is_translatable.is_(True), Segment.status == "draft")
        ).scalar_one()
        flagged = db.execute(
            select(func.count()).select_from(Segment).where(Segment.qa_flags != "[]")
        ).scalar_one()
        total = db.execute(select(func.count()).select_from(Segment)).scalar_one()
        print(f"  إجمالي={total} · في انتظار الترجمة={pending} · عليها تنبيه={flagged}")

        # ---------- الذاكرة ----------
        tm_count = db.execute(select(func.count()).select_from(TMEntry)).scalar_one()
        echo = db.execute(
            select(func.count())
            .select_from(TMEntry)
            .where(TMEntry.target_text.like("%[EN]%"))
        ).scalar_one()
        print(f"\n=== الذاكرة ===")
        print(f"  مدخلات={tm_count} · منها تجريبية={echo}")
        if echo:
            issues.append(f"{echo} مدخل تجريبي في الذاكرة — شغّل maintenance.py tm-clean")

        # ---------- التخزين ----------
        print(f"\n=== التخزين ===")
        storage = settings.storage_dir
        size = sum(f.stat().st_size for f in storage.rglob("*") if f.is_file())
        projects = db.execute(select(func.count()).select_from(Project)).scalar_one()
        print(f"  مشاريع={projects} · حجم storage={size/1024/1024:.1f} ميجابايت")

        # ---------- ملفات يتيمة ----------
        project_ids = {
            row[0] for row in db.execute(select(Project.id)).all()
        }
        orphans = [
            d.name
            for d in (storage / "projects").iterdir()
            if d.is_dir() and d.name not in project_ids
        ] if (storage / "projects").exists() else []
        if orphans:
            print(f"  مجلدات يتيمة (مشاريع محذوفة): {len(orphans)}")
            issues.append(f"{len(orphans)} مجلد ملفات لمشاريع محذوفة — بياخد مساحة")

    finally:
        db.close()

    print("\n" + "=" * 62)
    if issues:
        print(f"نقاط تستحق الانتباه: {len(issues)}")
        for item in issues:
            print(f"  • {item}")
    else:
        print("مفيش مشاكل ظاهرة ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
