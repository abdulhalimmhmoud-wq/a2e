"""عرض حالة أحدث مشروع وعيّنة من ترجمته — أداة تشخيص."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.core.db import SessionLocal  # noqa: E402
from app.models import Project, Segment, SourceFile, UsageRecord  # noqa: E402


def main() -> int:
    db = SessionLocal()
    try:
        project = db.execute(
            select(Project).order_by(Project.created_at.desc()).limit(1)
        ).scalar_one_or_none()
        if project is None:
            print("مفيش مشاريع")
            return 1

        print(f"المشروع: {project.name}  [{project.domain} / {project.model}]")

        for file in db.execute(
            select(SourceFile).where(SourceFile.project_id == project.id)
        ).scalars():
            print(f"\nالملف: {file.original_filename}")
            print(f"  حالة={file.status} مقاطع={file.segment_count} "
                  f"كلمات={file.word_count} صفحات={file.page_count}")

            segments = db.execute(
                select(Segment)
                .where(Segment.file_id == file.id)
                .order_by(Segment.order_index)
            ).scalars().all()

            shown = 0
            print("\n  --- عيّنة ---")
            for segment in segments:
                if not segment.is_translatable or not segment.target_text.strip():
                    continue
                print(f"  [{segment.location}]")
                print(f"    ع: {segment.source_text[:92]}")
                print(f"    E: {segment.target_text[:92]}")
                if segment.qa_flags != "[]":
                    print(f"    ! {segment.qa_flags}")
                shown += 1
                if shown >= 10:
                    break

            empty = [
                s for s in segments
                if s.is_translatable and not s.target_text.strip()
            ]
            flagged = [s for s in segments if s.qa_flags != "[]"]
            print(f"\n  فاضية: {len(empty)}   عليها تنبيه: {len(flagged)}")
            for segment in flagged[:8]:
                print(f"    {segment.location}: {segment.qa_flags[:90]}")

        usage = db.execute(
            select(
                func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
                func.count(),
                func.coalesce(func.sum(UsageRecord.cache_read_tokens), 0),
                func.coalesce(func.sum(UsageRecord.input_tokens), 0),
                func.coalesce(func.sum(UsageRecord.output_tokens), 0),
            ).where(UsageRecord.project_id == project.id)
        ).one()
        print(f"\nالتكلفة: ${usage[0]:.4f}  نداءات={usage[1]}  "
              f"كاش_قراءة={usage[2]:,}  إدخال={usage[3]:,}  إخراج={usage[4]:,}")
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
