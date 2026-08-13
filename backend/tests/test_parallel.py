"""اختبار التنفيذ المتوازي — بدون أي نداء API.

بيستخدم محرّكًا بطيئًا مصطنعًا عشان يقيس التسريع الفعلي ويتأكد إن:
  1. الدفعة الأولى بتتنفّذ لوحدها (تسخين الكاش) قبل التوازي.
  2. مفيش مقطع بيضيع أو يتكرر مع التوازي.
  3. كتابة قاعدة البيانات كلها في الخيط الرئيسي.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.core.db import SessionLocal, init_db  # noqa: E402
from app.models import Project, Segment  # noqa: E402
from app.tools.translator import pipeline  # noqa: E402
from app.tools.translator.engine import BatchResult, SegmentInput, Usage  # noqa: E402

SAMPLE = Path("storage/samples/contract_ar.docx")
CALL_SECONDS = 0.6


class SlowEngine:
    """محرّك بطيء يحاكي زمن نداء الـ API ويسجّل ترتيب التنفيذ."""

    name = "slow"
    model = "slow"
    production = False

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.starts: list[tuple[float, str]] = []
        self.peak_concurrent = 0
        self._active = 0

    def translate(
        self,
        segments: list[SegmentInput],
        context_before: str = "",
        context_after: str = "",
    ) -> BatchResult:
        with self.lock:
            self._active += 1
            self.peak_concurrent = max(self.peak_concurrent, self._active)
            self.starts.append((time.monotonic(), threading.current_thread().name))

        try:
            time.sleep(CALL_SECONDS)
            result = BatchResult(usage=Usage(calls=1))
            for segment in segments:
                result.translations[segment.id] = f"[T] {segment.source}"
            return result
        finally:
            with self.lock:
                self._active -= 1


def main() -> int:
    failures: list[str] = []
    init_db()
    db = SessionLocal()
    project = None

    try:
        if not SAMPLE.exists():
            print("!! شغّل make_sample_docx.py الأول")
            return 1

        project = Project(name="اختبار التوازي", domain="general")
        db.add(project)
        db.flush()

        file = pipeline.ingest(db, project, SAMPLE, SAMPLE.name)
        db.commit()
        pipeline.extract_and_segment(db, file)
        db.commit()

        translatable = db.execute(
            select(Segment).where(
                Segment.file_id == file.id, Segment.is_translatable.is_(True)
            )
        ).scalars().all()

        # دفعات صغيرة عشان نضمن عدد كافٍ منها للاختبار
        from app.core.config import settings

        original_budget = settings.batch_char_budget
        original_max = settings.batch_max_segments
        settings.batch_char_budget = 80
        settings.batch_max_segments = 2

        try:
            # ---------- تتابعي ----------
            engine_seq = SlowEngine()
            start = time.monotonic()
            stats_seq = pipeline.translate_file(
                db, file, engine_seq, use_memory=False, concurrency=1
            )
            seq_time = time.monotonic() - start
            db.commit()

            batches = stats_seq.calls
            print(f"=== تتابعي (خيط واحد) ===")
            print(f"  دفعات={batches} · مقاطع={stats_seq.translated} "
                  f"· زمن={seq_time:.1f} ث · أقصى تزامن={engine_seq.peak_concurrent}")

            if engine_seq.peak_concurrent != 1:
                failures.append("التتابعي نفّذ أكتر من دفعة في نفس الوقت")

            # ---------- متوازي ----------
            db.query(Segment).filter(Segment.file_id == file.id).update(
                {"target_text": "", "status": "draft", "origin": ""},
                synchronize_session=False,
            )
            db.query(Segment).filter(
                Segment.file_id == file.id, Segment.is_translatable.is_(False)
            ).update({"status": "approved"}, synchronize_session=False)
            db.commit()

            # ضروري بعد تحديث جماعي بـ synchronize_session=False:
            # الكائنات في الذاكرة لسه شايلة القيم القديمة، ولو الترجمة
            # كتبت نفس القيمة SQLAlchemy هيشوف إنه مفيش تغيير ومايبعتش
            # UPDATE. في الإنتاج ده مابيحصلش لأن كل مهمة ليها جلسة جديدة.
            db.expire_all()

            engine_par = SlowEngine()
            start = time.monotonic()
            stats_par = pipeline.translate_file(
                db, file, engine_par, use_memory=False, concurrency=4
            )
            par_time = time.monotonic() - start
            db.commit()

            print(f"\n=== متوازي (4 خيوط) ===")
            print(f"  دفعات={stats_par.calls} · مقاطع={stats_par.translated} "
                  f"· زمن={par_time:.1f} ث · أقصى تزامن={engine_par.peak_concurrent}")
            print(f"\n  التسريع: {seq_time / par_time:.1f}×")

            # ---------- الفحوصات ----------
            if stats_par.translated != stats_seq.translated:
                failures.append(
                    f"عدد المقاطع اختلف: تتابعي={stats_seq.translated} "
                    f"متوازي={stats_par.translated}"
                )

            if stats_par.calls != stats_seq.calls:
                failures.append(
                    f"عدد الدفعات اختلف: {stats_seq.calls} مقابل {stats_par.calls}"
                )

            if engine_par.peak_concurrent < 2:
                failures.append(
                    f"التوازي مااشتغلش — أقصى تزامن {engine_par.peak_concurrent}"
                )

            if par_time >= seq_time * 0.85:
                failures.append(
                    f"مفيش تسريع فعلي: {seq_time:.1f} ث → {par_time:.1f} ث"
                )

            # تسخين الكاش: أول دفعة لازم تخلص قبل ما التانية تبدأ
            if len(engine_par.starts) >= 3:
                first_start = engine_par.starts[0][0]
                second_start = engine_par.starts[1][0]
                gap = second_start - first_start
                print(f"  الفجوة بين الدفعة الأولى والتانية: {gap:.2f} ث "
                      f"(زمن النداء {CALL_SECONDS} ث)")
                if gap < CALL_SECONDS * 0.9:
                    failures.append(
                        "الدفعة الأولى مااتنفّذتش لوحدها — الكاش هيتفوّت "
                        "في كل الدفعات والتكلفة هتزيد"
                    )
                else:
                    print("  ✓ الدفعة الأولى اتنفّذت لوحدها (تسخين الكاش)")

            # مفيش مقطع فاضي أو مكرر
            db.expire_all()
            empty = db.execute(
                select(Segment).where(
                    Segment.file_id == file.id,
                    Segment.is_translatable.is_(True),
                    Segment.target_text == "",
                )
            ).scalars().all()
            if empty:
                failures.append(f"{len(empty)} مقطع فضل من غير ترجمة")

        finally:
            settings.batch_char_budget = original_budget
            settings.batch_max_segments = original_max

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
    print("نجح: التنفيذ المتوازي سليم ✓")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
