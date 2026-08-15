"""معالجات المهام الخلفية — بتربط الطابور بخط الأنابيب."""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.models import Job, Project, SourceFile
from app.tools.translator import pipeline, tm
from app.tools.translator.engine import (
    ClaudeBatchEngine,
    ClaudeEngine,
    EchoEngine,
)

logger = logging.getLogger(__name__)


def _mark_file_failed(file_id: str, stage: str) -> None:
    """إرجاع حالة الملف لـ failed بعد فشل المهمة.

    خط الأنابيب بيحطّ الحالة «extracting» أو «translating» وهو ماشي،
    ولو رمى استثناء الجلسة بتترجع فبتفضل الحالة دي محفورة. الملف كان
    بيبان في الواجهة «جارٍ الاستخراج» للأبد جنب رسالة خطأ، ومافيش
    طريقة يعيد المحاولة. لازم جلسة جديدة لأن جلسة المهمة اترجعت.
    """
    from app.core.db import session_scope

    try:
        with session_scope() as db:
            file = db.get(SourceFile, file_id)
            if file and file.status == stage:
                file.status = "failed"
    except Exception:  # noqa: BLE001
        logger.exception("مافيش وسيلة لتسجيل فشل الملف %s", file_id)


def run_extraction(db: Session, job: Job, file_id: str) -> dict:
    file = db.get(SourceFile, file_id)
    if file is None:
        raise ValueError("الملف غير موجود")

    job.message = "جارٍ استخراج النص"
    db.commit()

    try:
        stats = pipeline.extract_and_segment(db, file, job=job)
    except Exception:
        _mark_file_failed(file_id, "extracting")
        raise

    job.total = stats.segments
    job.progress = stats.segments
    result = {
        "units": stats.units,
        "segments": stats.segments,
        "words": stats.words,
        "chars": stats.chars,
        "pages": stats.pages,
    }
    if stats.ocr_pages:
        result["ocr_pages"] = stats.ocr_pages
        result["ocr_cost_usd"] = stats.ocr_cost_usd
        if stats.ocr_failed_pages:
            result["ocr_failed_pages"] = stats.ocr_failed_pages
    return result


def run_translation(
    db: Session,
    job: Job,
    file_id: str,
    engine_name: str = "claude",
    model: str | None = None,
    use_memory: bool = True,
) -> dict:
    file = db.get(SourceFile, file_id)
    if file is None:
        raise ValueError("الملف غير موجود")

    project = db.get(Project, file.project_id)
    glossary = tm.load_glossary(db, domain=project.domain, project_id=project.id)

    options = dict(
        model=model or project.model,
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        domain=project.domain,
        style_notes=project.style_notes,
        glossary=glossary,
    )

    # "auto" معناه استخدم محرّك المشروع؛ الباقي بيتجاوزه لتشغيلة واحدة
    if engine_name in ("auto", "", None):
        engine_name = project.engine or "claude"

    if engine_name == "echo":
        engine = EchoEngine()
    elif engine_name == "deepl":
        from app.tools.translator.deepl_engine import DeepLEngine

        # DeepL بيحدد جودته بـ model_type مش باسم موديل
        options.pop("model", None)
        engine = DeepLEngine(**options)
    elif engine_name == "batch":
        # نصف السعر، لكن التنفيذ مش فوري (عادة أقل من ساعة)
        engine = ClaudeBatchEngine(**options)
    else:
        engine = ClaudeEngine(**options)

    job.message = f"جارٍ الترجمة ({engine.model})"
    db.commit()

    try:
        stats = pipeline.translate_file(db, file, engine, job=job, use_memory=use_memory)
    except Exception:
        _mark_file_failed(file_id, "translating")
        raise

    return {
        "translated": stats.translated,
        "from_memory": stats.from_memory,
        "failed": stats.failed,
        "flagged": stats.flagged,
        "cost_usd": stats.cost_usd,
        "api_calls": stats.calls,
        "model": engine.model,
    }
