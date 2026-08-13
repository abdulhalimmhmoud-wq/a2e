"""مهام خلفية بسيطة — طابور داخل العملية بدون Redis أو Celery.

الأداة بتشتغل على جهاز واحد لمستخدم واحد، فبنية توزيع كاملة هتبقى
تعقيد بلا فايدة. الحالة محفوظة في قاعدة البيانات مش في الذاكرة، يعني
لو الخادم اتقفل والمهمة كانت شغالة، حالتها بتفضل ظاهرة وتقدر تعيد
تشغيلها من حيث وقفت.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from app.core.db import session_scope
from app.models import Job

logger = logging.getLogger(__name__)

# طابوران منفصلان عن قصد: مهمة «التنفيذ المؤجَّل» بتفضل ماسكة خيطها
# وهي بتستنى نتيجة من Anthropic لمدة توصل لساعة. لو كانت بتشارك نفس
# الطابور، مهمتين مؤجَّلتين كانوا هيقفلوا الأداة كلها — الاستخراج
# والترجمة الفورية هيستنوا ساعة من غير سبب.
_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="job")
_slow_executor = ThreadPoolExecutor(max_workers=3, thread_name_prefix="job-slow")

# المهام اللي بتقضي وقتها في الانتظار مش في الشغل
_SLOW_KINDS = {"batch_translate"}

_lock = threading.Lock()
_running: set[str] = set()


def create_job(
    db, kind: str, project_id: str | None = None, file_id: str | None = None
) -> Job:
    job = Job(kind=kind, project_id=project_id, file_id=file_id, status="queued")
    db.add(job)
    db.flush()
    return job


def submit(
    job_id: str, handler: Callable[..., dict], slow: bool = False, **kwargs
) -> None:
    """جدولة مهمة. الـ handler بياخد (db, job, **kwargs) ويرجّع نتيجة.

    slow=True بيحطّها في طابور المهام الطويلة عشان ماتعطّلش الباقي.
    """
    with _lock:
        if job_id in _running:
            logger.warning("المهمة %s شغالة بالفعل", job_id)
            return
        _running.add(job_id)

    pool = _slow_executor if slow else _executor
    pool.submit(_run, job_id, handler, kwargs)


def _run(job_id: str, handler: Callable[..., dict], kwargs: dict) -> None:
    import json

    try:
        with session_scope() as db:
            job = db.get(Job, job_id)
            if job is None:
                return
            job.status = "running"
            job.message = "بدأت"
            # حفظ فوري عشان الواجهة تشوف إن المهمة بدأت
            db.commit()

            result = handler(db=db, job=job, **kwargs)

            db.refresh(job)
            if job.status == "cancelling":
                job.status = "cancelled"
                job.message = "اتلغت — الشغل اللي خلص محفوظ"
            else:
                job.status = "done"
                job.progress = job.total or job.progress
                job.message = "اكتملت"
            job.result = json.dumps(result or {}, ensure_ascii=False, default=str)

    except Exception as exc:  # noqa: BLE001
        logger.exception("فشلت المهمة %s", job_id)
        try:
            with session_scope() as db:
                job = db.get(Job, job_id)
                if job:
                    job.status = "failed"
                    job.error = f"{type(exc).__name__}: {exc}"
                    job.message = "فشلت"
                    job.result = json.dumps(
                        {"traceback": traceback.format_exc()[-2000:]},
                        ensure_ascii=False,
                    )
        except Exception:  # noqa: BLE001
            logger.exception("مافيش وسيلة لتسجيل فشل المهمة %s", job_id)
    finally:
        with _lock:
            _running.discard(job_id)


def is_running(job_id: str) -> bool:
    with _lock:
        return job_id in _running


def recover_stale_jobs() -> int:
    """معالجة المهام اللي كانت شغالة وقت ما الخادم اتقفل.

    الطابور في الذاكرة، فالمهمة بتموت مع العملية لكن صفّها في قاعدة
    البيانات بيفضل `running` للأبد. من غير المعالجة دي، حاجز منع
    الترجمة المكررة هيفضل شايف مهمة وهمية شغالة ويمنعك تبدأ من جديد.

    الشغل نفسه مابيضيعش: المقاطع اللي اتترجمت محفوظة، واللي لسه في
    `draft` بتتكمّل عند إعادة التشغيل من غير ما تدفع تاني.
    """
    from sqlalchemy import select

    from app.models import Job as JobModel

    recovered = 0
    with session_scope() as db:
        stale = db.execute(
            select(JobModel).where(
                JobModel.status.in_(["queued", "running", "cancelling"])
            )
        ).scalars().all()

        for job in stale:
            job.status = "failed"
            job.message = "اتوقفت"
            job.error = (
                "الخادم اتقفل والمهمة كانت شغالة. "
                "الشغل اللي خلص محفوظ — شغّلها تاني عشان تكمّل الباقي."
            )
            recovered += 1

    if recovered:
        logger.warning("اتعالجت %d مهمة معلّقة من تشغيلة سابقة", recovered)
    return recovered


def shutdown() -> None:
    _executor.shutdown(wait=False, cancel_futures=True)
    _slow_executor.shutdown(wait=False, cancel_futures=True)
