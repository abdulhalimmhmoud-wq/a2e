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


def run_extraction(db: Session, job: Job, file_id: str) -> dict:
    file = db.get(SourceFile, file_id)
    if file is None:
        raise ValueError("الملف غير موجود")

    job.message = "جارٍ استخراج النص"
    db.commit()

    stats = pipeline.extract_and_segment(db, file, job=job)

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

    if engine_name == "echo":
        engine = EchoEngine()
    elif engine_name == "batch":
        # نصف السعر، لكن التنفيذ مش فوري (عادة أقل من ساعة)
        engine = ClaudeBatchEngine(**options)
    else:
        engine = ClaudeEngine(**options)

    job.message = f"جارٍ الترجمة ({engine.model})"
    db.commit()

    stats = pipeline.translate_file(db, file, engine, job=job, use_memory=use_memory)

    return {
        "translated": stats.translated,
        "from_memory": stats.from_memory,
        "failed": stats.failed,
        "flagged": stats.flagged,
        "cost_usd": stats.cost_usd,
        "api_calls": stats.calls,
        "model": engine.model,
    }
