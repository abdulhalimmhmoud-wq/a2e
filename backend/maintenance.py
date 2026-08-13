"""أدوات صيانة قاعدة البيانات.

التشغيل:
    python backend/maintenance.py tm-stats
    python backend/maintenance.py tm-clean        # حذف مدخلات المحرّك التجريبي
    python backend/maintenance.py tm-clean --all  # تفريغ الذاكرة بالكامل
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from sqlalchemy import func, select  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.models import Segment, TMEntry  # noqa: E402

# بصمة مخرجات المحرّك التجريبي
_ECHO_MARKER = "[EN]"


def tm_stats() -> None:
    db = SessionLocal()
    try:
        total = db.execute(select(func.count()).select_from(TMEntry)).scalar_one()
        polluted = db.execute(
            select(func.count())
            .select_from(TMEntry)
            .where(TMEntry.target_text.like(f"%{_ECHO_MARKER}%"))
        ).scalar_one()

        by_domain = db.execute(
            select(TMEntry.domain, func.count()).group_by(TMEntry.domain)
        ).all()

        print(f"مدخلات ذاكرة الترجمة: {total}")
        print(f"  منها من محرّك تجريبي: {polluted}")
        for domain, count in by_domain:
            print(f"  {domain}: {count}")

        echo_segments = db.execute(
            select(func.count())
            .select_from(Segment)
            .where(Segment.engine_model == "echo")
        ).scalar_one()
        print(f"\nمقاطع مترجمة بمحرّك تجريبي: {echo_segments}")
    finally:
        db.close()


def tm_clean(everything: bool = False) -> None:
    db = SessionLocal()
    try:
        if everything:
            removed = db.query(TMEntry).delete()
            print(f"اتحذفت كل مدخلات الذاكرة: {removed}")
        else:
            removed = (
                db.query(TMEntry)
                .filter(TMEntry.target_text.like(f"%{_ECHO_MARKER}%"))
                .delete(synchronize_session=False)
            )
            print(f"اتحذفت مدخلات المحرّك التجريبي: {removed}")

        # المقاطع اللي اتعبّت من مدخلات ملوّثة ترجع لطابور الترجمة
        reset = (
            db.query(Segment)
            .filter(
                Segment.origin == "tm_exact",
                Segment.target_text.like(f"%{_ECHO_MARKER}%"),
            )
            .update(
                {"target_text": "", "status": "draft", "origin": "", "tm_match_pct": 0},
                synchronize_session=False,
            )
        )
        print(f"مقاطع رجعت لطابور الترجمة: {reset}")
        db.commit()
    finally:
        db.close()


def clean_orphans(dry_run: bool = False) -> None:
    """حذف مجلدات الملفات اللي مشاريعها اتمسحت.

    بيحصل لو الحذف اتقطع في نصّه، أو لو حد مسح صف المشروع من قاعدة
    البيانات مباشرة. المجلدات دي بتفضل واخدة مساحة بلا فايدة.
    """
    import shutil

    from app.core.config import settings
    from app.models import Project

    root = settings.storage_dir / "projects"
    if not root.exists():
        print("مفيش مجلد مشاريع")
        return

    db = SessionLocal()
    try:
        alive = {row[0] for row in db.execute(select(Project.id)).all()}
    finally:
        db.close()

    freed = 0
    removed = 0
    for folder in root.iterdir():
        if not folder.is_dir() or folder.name in alive:
            continue
        size = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
        print(f"  {'[تجريبي] ' if dry_run else ''}حذف {folder.name} "
              f"({size / 1024:.0f} كب)")
        if not dry_run:
            shutil.rmtree(folder, ignore_errors=True)
        freed += size
        removed += 1

    verb = "هيتحذف" if dry_run else "اتحذف"
    print(f"{verb}: {removed} مجلد · {freed / 1024 / 1024:.1f} ميجابايت")


def tm_reindex() -> None:
    """إعادة حساب أطوال النصوص في الذاكرة.

    الترحيل التلقائي بيعبّي الطول من طول النص الخام. الطول المطبَّع
    (بدون وسوم ولا مسافات مكررة) أدق، وهو اللي البحث التقريبي بيرشّح
    بيه. الفرق بسيط عادةً، لكن مع نصوص فيها وسوم تنسيق كتير بيفرق.
    """
    from app.tools.translator.tm import _normalize

    db = SessionLocal()
    try:
        entries = db.execute(select(TMEntry)).scalars().all()
        changed = 0
        for entry in entries:
            correct = len(_normalize(entry.source_text))
            if entry.source_length != correct:
                entry.source_length = correct
                changed += 1
        db.commit()
        print(f"اتصحّح طول {changed} مدخل من {len(entries)}")
    finally:
        db.close()


def main() -> int:
    init_db()
    command = sys.argv[1] if len(sys.argv) > 1 else "tm-stats"

    if command == "tm-stats":
        tm_stats()
    elif command == "tm-clean":
        tm_clean(everything="--all" in sys.argv)
        print()
        tm_stats()
    elif command == "clean-orphans":
        clean_orphans(dry_run="--dry-run" in sys.argv)
    elif command == "tm-reindex":
        tm_reindex()
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
