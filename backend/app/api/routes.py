"""واجهة REST للأداة."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.api import schemas as sc
from app.core.config import MODEL_PRICING, settings
from app.core.db import SessionLocal, get_db
from app.models import (
    AuditLog,
    GlossaryTerm,
    Job,
    Project,
    Segment,
    SourceFile,
    TMEntry,
    UsageRecord,
)
from app.tools.translator import jobs_handlers, pipeline, sacred, sources, terms, tm
from app.tools.translator.costing import estimate_project, rates_for
from app.tools.translator.formats.base import strip_tags
from app.tools.translator.formats.registry import UnsupportedFormat, supported_extensions
from app.tools.translator.langs import is_rtl, language_label
from app.tools.translator.prompts import DOMAIN_LABELS
from app import jobs as job_queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api")


# ---------------------------------------------------------------------------
# مساعدات
# ---------------------------------------------------------------------------
def _project_or_404(db: Session, project_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(404, "المشروع غير موجود")
    return project


def _file_or_404(db: Session, file_id: str) -> SourceFile:
    file = db.get(SourceFile, file_id)
    if file is None:
        raise HTTPException(404, "الملف غير موجود")
    return file


def _segment_out(segment: Segment) -> sc.SegmentOut:
    try:
        flags = json.loads(segment.qa_flags or "[]")
    except json.JSONDecodeError:
        flags = []
    return sc.SegmentOut(
        id=segment.id,
        order_index=segment.order_index,
        unit_key=segment.unit_key,
        kind=segment.kind,
        location=segment.location,
        source_text=segment.source_text,
        target_text=segment.target_text,
        status=segment.status,
        origin=segment.origin,
        tm_match_pct=segment.tm_match_pct,
        is_translatable=segment.is_translatable,
        is_locked=segment.is_locked,
        edited_by_human=segment.edited_by_human,
        qa_flags=flags,
        notes=segment.notes,
    )


def _project_out(db: Session, project: Project) -> sc.ProjectOut:
    files = db.execute(
        select(func.count(), func.coalesce(func.sum(SourceFile.word_count), 0)).where(
            SourceFile.project_id == project.id
        )
    ).one()
    cost = db.execute(
        select(func.coalesce(func.sum(UsageRecord.cost_usd), 0.0)).where(
            UsageRecord.project_id == project.id
        )
    ).scalar_one()

    return sc.ProjectOut(
        id=project.id,
        name=project.name,
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        domain=project.domain,
        engine=project.engine,
        model=project.model,
        style_notes=project.style_notes,
        status=project.status,
        created_at=project.created_at,
        file_count=files[0],
        word_count=files[1],
        cost_usd=round(float(cost), 4),
    )


# ---------------------------------------------------------------------------
# النظام
# ---------------------------------------------------------------------------
@router.get("/health")
def health() -> dict:
    return {
        "ok": True,
        "app": settings.app_name,
        "has_api_key": bool(settings.anthropic_api_key),
        "has_deepl_key": bool(settings.deepl_api_key),
        "supported_extensions": supported_extensions(),
    }


@router.get("/tools")
def tools() -> list[dict]:
    """سجلّ الأدوات — الصفحة الرئيسية بتتبني منه.

    النصوص بترجع باللغتين لأن الواجهة بتتبدّل بين عربي وإنجليزي،
    والأدوات بتتسجّل هنا مش في الواجهة.
    """
    return [
        {
            "id": "translator",
            "name": {
                "ar": "المترجم الاحترافي",
                "en": "Professional Translator",
            },
            "description": {
                "ar": "ترجمة المستندات مع الحفاظ الكامل على التنسيق "
                      "ومراجعة ثنائية اللغة",
                "en": "Document translation with formatting preserved exactly, "
                      "and a bilingual review screen",
            },
            "icon": "languages",
            "path": "/translator",
            "status": "available",
        },
    ]


@router.get("/config")
def config() -> dict:
    models = []
    for model_id in MODEL_PRICING:
        rates = rates_for(model_id)
        models.append(
            {
                "id": model_id,
                "label": rates.label,
                "input_per_mtok": rates.input_per_mtok,
                "output_per_mtok": rates.output_per_mtok,
                "promo_active": rates.promo_active,
                "note": MODEL_PRICING[model_id].get("note", ""),
            }
        )
    languages = [
        {"id": code, "label": language_label(code), "rtl": is_rtl(code)}
        for code in ("ar", "en", "ru", "tr", "uk", "az", "fr", "de", "es", "it")
    ]
    engines = [
        {
            "id": "claude",
            "label": "Claude",
            "available": bool(settings.anthropic_api_key),
            "note": {
                "ar": "نموذج لغوي — يفهم تعليمات المجال والسياق والغموض "
                      "المتعمّد. الأدق للمستندات القانونية والطبية.",
                "en": "A language model — follows domain instructions, uses "
                      "context, and preserves deliberate ambiguity. The more "
                      "accurate choice for legal and medical documents.",
            },
            "pricing": {"ar": "بالتوكن", "en": "per token"},
        },
        {
            "id": "deepl",
            "label": "DeepL",
            "available": bool(settings.deepl_api_key),
            "note": {
                "ar": "ترجمة آلية متخصصة — أسرع بكتير وثابتة النتيجة، "
                      "ومجانية حتى 500 ألف حرف شهريًا. تعليمات المجال مختصرة.",
                "en": "A dedicated machine-translation engine — far faster and "
                      "deterministic, free up to 500k characters a month. "
                      "Domain instructions are condensed.",
            },
            "pricing": {"ar": "بالحرف", "en": "per character"},
        },
    ]
    return {
        "models": models,
        "domains": [{"id": k, "label": v} for k, v in DOMAIN_LABELS.items()],
        "languages": languages,
        "engines": engines,
        "default_model": settings.default_model,
        "legal_model": settings.legal_model,
        "has_api_key": bool(settings.anthropic_api_key),
        "has_deepl_key": bool(settings.deepl_api_key),
    }


# ---------------------------------------------------------------------------
# المشاريع
# ---------------------------------------------------------------------------
@router.post("/projects", response_model=sc.ProjectOut)
def create_project(payload: sc.ProjectCreate, db: Session = Depends(get_db)):
    project = Project(**payload.model_dump())
    db.add(project)
    db.commit()
    return _project_out(db, project)


@router.get("/projects", response_model=list[sc.ProjectOut])
def list_projects(db: Session = Depends(get_db)):
    projects = db.execute(
        select(Project).order_by(Project.created_at.desc())
    ).scalars().all()
    return [_project_out(db, p) for p in projects]


@router.get("/projects/{project_id}", response_model=sc.ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db)):
    return _project_out(db, _project_or_404(db, project_id))


@router.patch("/projects/{project_id}", response_model=sc.ProjectOut)
def update_project(
    project_id: str, payload: sc.ProjectUpdate, db: Session = Depends(get_db)
):
    project = _project_or_404(db, project_id)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(project, field, value)
    db.commit()
    return _project_out(db, project)


@router.delete("/projects/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    project = _project_or_404(db, project_id)
    db.delete(project)
    db.commit()
    shutil.rmtree(pipeline.project_dir(project_id), ignore_errors=True)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# الملفات
# ---------------------------------------------------------------------------
def _file_out(db: Session, file: SourceFile) -> sc.FileOut:
    progress = pipeline.file_progress(db, file.id) if file.segment_count else None
    return sc.FileOut(
        id=file.id,
        project_id=file.project_id,
        original_filename=file.original_filename,
        fmt=file.fmt,
        size_bytes=file.size_bytes,
        page_count=file.page_count,
        word_count=file.word_count,
        char_count=file.char_count,
        unit_count=file.unit_count,
        segment_count=file.segment_count,
        status=file.status,
        error=file.error,
        progress=progress,
    )


@router.get("/projects/{project_id}/files", response_model=list[sc.FileOut])
def list_files(project_id: str, db: Session = Depends(get_db)):
    _project_or_404(db, project_id)
    files = db.execute(
        select(SourceFile)
        .where(SourceFile.project_id == project_id)
        .order_by(SourceFile.created_at)
    ).scalars().all()
    return [_file_out(db, f) for f in files]


@router.post("/projects/{project_id}/files", response_model=sc.FileOut)
async def upload_file(
    project_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    project = _project_or_404(db, project_id)
    name = Path(file.filename or "upload").name

    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as tmp:
        temp_path = Path(tmp.name)
        size = 0
        limit = settings.max_upload_mb * 1024 * 1024
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                temp_path.unlink(missing_ok=True)
                raise HTTPException(
                    413, f"الملف أكبر من الحد المسموح ({settings.max_upload_mb} ميجابايت)"
                )
            tmp.write(chunk)

    try:
        record = pipeline.ingest(db, project, temp_path, name)
        db.commit()
    except UnsupportedFormat as exc:
        raise HTTPException(400, str(exc)) from exc
    finally:
        temp_path.unlink(missing_ok=True)

    return _file_out(db, record)


@router.get("/files/{file_id}", response_model=sc.FileOut)
def get_file(file_id: str, db: Session = Depends(get_db)):
    return _file_out(db, _file_or_404(db, file_id))


@router.delete("/files/{file_id}")
def delete_file(file_id: str, db: Session = Depends(get_db)):
    file = _file_or_404(db, file_id)
    db.delete(file)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# تشغيل المراحل
# ---------------------------------------------------------------------------
def _active_job(db: Session, file_id: str, kind: str) -> Job | None:
    """مهمة شغّالة بالفعل على نفس الملف.

    من غير الفحص ده، ضغطتين على «ترجمة» = ترجمتين = تكلفة مضاعفة.
    """
    return db.execute(
        select(Job)
        .where(
            Job.file_id == file_id,
            Job.kind == kind,
            Job.status.in_(["queued", "running", "cancelling"]),
        )
        .order_by(Job.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


@router.post("/files/{file_id}/extract", response_model=sc.JobOut)
def start_extraction(file_id: str, db: Session = Depends(get_db)):
    file = _file_or_404(db, file_id)

    running = _active_job(db, file.id, "extract")
    if running is not None:
        return _job_out(running)

    job = job_queue.create_job(db, "extract", file.project_id, file.id)
    db.commit()
    job_queue.submit(job.id, jobs_handlers.run_extraction, file_id=file.id)
    return _job_out(job)


@router.post("/files/{file_id}/translate", response_model=sc.JobOut)
def start_translation(
    file_id: str, payload: sc.TranslateRequest, db: Session = Depends(get_db)
):
    file = _file_or_404(db, file_id)

    # "auto" بيتحوّل لمحرّك المشروع قبل التحقق من المفتاح
    project = db.get(Project, file.project_id)
    wanted = payload.engine
    if wanted in ("auto", ""):
        wanted = (project.engine if project else "claude") or "claude"

    if wanted in ("claude", "batch") and not settings.anthropic_api_key:
        raise HTTPException(
            400,
            "مفيش مفتاح Anthropic. حط ANTHROPIC_API_KEY في ملف .env، "
            "أو استخدم engine=echo لتشغيل تجريبي بدون تكلفة.",
        )
    if wanted == "deepl" and not settings.deepl_api_key:
        raise HTTPException(
            400,
            "مفيش مفتاح DeepL. حط DEEPL_API_KEY في ملف .env — "
            "المفتاح المجاني من deepl.com/pro-api بيكفي 500 ألف حرف شهريًا.",
        )

    if file.status not in ("extracted", "translated", "translating"):
        raise HTTPException(
            400, f"الملف لازم يتستخرج الأول (حالته الحالية: {file.status})"
        )

    # لو فيه ترجمة شغالة على نفس الملف، نرجّعها بدل ما نبدأ تانية
    # (ترجمة مكررة = تكلفة مضاعفة)
    running = _active_job(db, file.id, "translate")
    if running is not None:
        return _job_out(running)

    job = job_queue.create_job(db, "translate", file.project_id, file.id)
    db.commit()
    job_queue.submit(
        job.id,
        jobs_handlers.run_translation,
        # التنفيذ المؤجَّل بيقعد ساعة مستني — طابور منفصل عشان
        # مايعطّلش الاستخراج والترجمة الفورية
        slow=(payload.engine == "batch"),
        file_id=file.id,
        engine_name=payload.engine,
        model=payload.model,
        use_memory=payload.use_memory,
    )
    return _job_out(job)


@router.post("/files/{file_id}/export")
def start_export(file_id: str, db: Session = Depends(get_db)):
    file = _file_or_404(db, file_id)
    output = pipeline.export_file(db, file)
    db.commit()
    return {
        "filename": output.name,
        "size_bytes": output.stat().st_size,
        "download_url": f"/api/files/{file_id}/download",
    }


@router.get("/files/{file_id}/download")
def download(file_id: str, db: Session = Depends(get_db)):
    file = _file_or_404(db, file_id)
    output = pipeline.export_file(db, file)
    db.commit()
    return FileResponse(
        path=output,
        filename=output.name,
        media_type="application/octet-stream",
    )


# ---------------------------------------------------------------------------
# المهام
# ---------------------------------------------------------------------------
def _job_out(job: Job) -> sc.JobOut:
    try:
        result = json.loads(job.result or "{}")
    except json.JSONDecodeError:
        result = {}
    return sc.JobOut(
        id=job.id,
        kind=job.kind,
        status=job.status,
        progress=job.progress,
        total=job.total,
        message=job.message,
        error=job.error,
        result=result,
    )


@router.get("/jobs/{job_id}", response_model=sc.JobOut)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "المهمة غير موجودة")
    return _job_out(job)


@router.post("/jobs/{job_id}/cancel", response_model=sc.JobOut)
def cancel_job(job_id: str, db: Session = Depends(get_db)):
    """طلب إلغاء مهمة شغّالة.

    مافيش وسيلة نقتل بيها خيط شغّال، فبنعلّم المهمة والخط بيفحص
    العلامة بين الدفعات. النتيجة: الدفعة الحالية بتكمّل والباقي بيقف،
    واللي اتترجم بيفضل محفوظ فإعادة التشغيل بتكمّل مش بتبدأ من الأول.
    """
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, "المهمة غير موجودة")

    if job.status not in ("queued", "running"):
        raise HTTPException(400, f"المهمة مش شغّالة (حالتها: {job.status})")

    job.status = "cancelling"
    job.message = "جارٍ الإلغاء — الدفعة الحالية هتكمّل"
    db.commit()
    return _job_out(job)


@router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str):
    """بث حالة المهمة لحظيًا للواجهة."""

    async def events():
        last = None
        for _ in range(3600):  # سقف أمان: ساعة تقريبًا
            db = SessionLocal()
            try:
                job = db.get(Job, job_id)
                if job is None:
                    yield {"event": "error", "data": json.dumps({"error": "not_found"})}
                    return
                payload = _job_out(job).model_dump()
            finally:
                db.close()

            snapshot = json.dumps(payload, ensure_ascii=False, default=str)
            if snapshot != last:
                last = snapshot
                yield {"event": "progress", "data": snapshot}

            if payload["status"] in ("done", "failed"):
                return
            await asyncio.sleep(1.0)

    return EventSourceResponse(events())


# ---------------------------------------------------------------------------
# المراجعة
# ---------------------------------------------------------------------------
@router.get("/files/{file_id}/segments", response_model=sc.SegmentPage)
def list_segments(
    file_id: str,
    offset: int = 0,
    limit: int = Query(200, le=1000),
    status: str | None = None,
    flagged: bool = False,
    search: str | None = None,
    db: Session = Depends(get_db),
):
    _file_or_404(db, file_id)
    query = select(Segment).where(Segment.file_id == file_id)

    if status:
        query = query.where(Segment.status == status)
    if flagged:
        query = query.where(Segment.qa_flags != "[]")
    if search:
        pattern = f"%{search}%"
        query = query.where(
            Segment.source_text.like(pattern) | Segment.target_text.like(pattern)
        )

    total = db.execute(
        select(func.count()).select_from(query.subquery())
    ).scalar_one()

    rows = db.execute(
        query.order_by(Segment.order_index).offset(offset).limit(limit)
    ).scalars().all()

    return sc.SegmentPage(
        items=[_segment_out(s) for s in rows],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.patch("/segments/{segment_id}", response_model=sc.SegmentUpdateResult)
def update_segment(
    segment_id: str, payload: sc.SegmentUpdate, db: Session = Depends(get_db)
):
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(404, "المقطع غير موجود")

    before = segment.target_text
    plan_out: sc.PropagationPlanOut | None = None

    if payload.source_text is not None and payload.source_text != segment.source_text:
        # تعديل المصدر بيبطّل الترجمة الحالية ويرجّع المقطع لطابور الترجمة
        from app.tools.translator.formats.base import text_hash

        segment.source_text = payload.source_text
        segment.source_hash = text_hash(payload.source_text)
        segment.status = "draft"
        segment.target_text = ""
        segment.origin = ""

    if payload.target_text is not None:
        segment.target_text = payload.target_text
        segment.edited_by_human = True
        segment.origin = "human"
        if segment.status == "draft":
            segment.status = "translated"

        # فحوصات الجودة بتتحدّث فورًا بعد التعديل اليدوي
        from app.tools.translator.engine import validate_translation

        file = db.get(SourceFile, segment.file_id)
        project = db.get(Project, file.project_id) if file else None
        problems = validate_translation(
            segment.source_text,
            payload.target_text,
            source_lang=project.source_lang if project else "ar",
            target_lang=project.target_lang if project else "en",
        )
        segment.qa_flags = json.dumps(problems, ensure_ascii=False)

        if payload.plan_propagation and payload.target_text != before:
            plan = tm.plan_propagation(db, segment, payload.target_text)
            applied = tm.apply_propagation(db, plan.auto)
            plan_out = sc.PropagationPlanOut(
                auto_applied=applied,
                needs_review=[
                    sc.PropagationTargetOut(**vars(t)) for t in plan.needs_review
                ],
            )

    if payload.status is not None:
        segment.status = payload.status
        if payload.status == "approved":
            pipeline.approve_segment(db, segment)

    if payload.notes is not None:
        segment.notes = payload.notes
    if payload.is_locked is not None:
        segment.is_locked = payload.is_locked

    db.add(
        AuditLog(
            segment_id=segment.id,
            action="edit_segment",
            before=before,
            after=segment.target_text,
        )
    )
    db.commit()

    return sc.SegmentUpdateResult(segment=_segment_out(segment), propagation=plan_out)


@router.get("/segments/{segment_id}/suggestions")
def segment_suggestions(
    segment_id: str, limit: int = 5, db: Session = Depends(get_db)
):
    """مطابقات تقريبية من ذاكرة الترجمة لمقطع معيّن.

    المطابقة التامة بتتعبّى تلقائيًا وقت الترجمة. المطابقة التقريبية
    (75–99%) مابتتطبّقش لوحدها — بتتعرض على المراجع لأنها محتاجة
    تعديل، لكنها بتوفّر وقت وبتثبّت المصطلحات عبر المشاريع.
    """
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(404, "المقطع غير موجود")

    file = db.get(SourceFile, segment.file_id)
    project = db.get(Project, file.project_id) if file else None
    if project is None:
        return {"matches": []}

    matches = tm.lookup_fuzzy(
        db,
        segment.source_text,
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        domain=project.domain,
        limit=limit,
    )
    return {
        "matches": [
            {
                "source_text": m.source_text,
                "target_text": m.target_text,
                "score": m.score,
            }
            for m in matches
        ]
    }


@router.post("/segments/{segment_id}/propagate")
def apply_propagation(
    segment_id: str, payload: sc.PropagationApply, db: Session = Depends(get_db)
):
    """تنفيذ الانتشار على المواضع اللي وافق عليها المراجع."""
    segment = db.get(Segment, segment_id)
    if segment is None:
        raise HTTPException(404, "المقطع غير موجود")

    applied = 0
    for target_id in payload.segment_ids:
        target = db.get(Segment, target_id)
        if target is None or target.is_locked:
            continue
        text = payload.target_texts.get(target_id)
        if text is None:
            continue
        db.add(
            AuditLog(
                segment_id=target.id,
                action="propagate",
                before=target.target_text,
                after=text,
                detail=f"من المقطع {segment_id}",
            )
        )
        target.target_text = text
        target.origin = "propagated"
        if target.status == "draft":
            target.status = "translated"
        applied += 1

    db.commit()
    return {"applied": applied}


@router.post("/files/{file_id}/approve-all")
def approve_all(file_id: str, db: Session = Depends(get_db)):
    """اعتماد كل المقاطع المترجمة وحفظها في ذاكرة الترجمة."""
    file = _file_or_404(db, file_id)
    segments = db.execute(
        select(Segment).where(
            Segment.file_id == file.id, Segment.status.in_(["translated", "reviewed"])
        )
    ).scalars().all()

    for segment in segments:
        pipeline.approve_segment(db, segment)
    db.commit()
    return {"approved": len(segments)}


# ---------------------------------------------------------------------------
# المصادر المعتمدة للنص المقدّس
# ---------------------------------------------------------------------------
@router.get("/sources/translations")
def available_translations(language: str = "en"):
    """الترجمات المتاحة على quran.com عشان المستخدم يختار واحدة."""
    try:
        items = sources.list_translations(language)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"تعذّر الاتصال بـ quran.com: {exc}") from exc

    return {
        "current": settings.quran_translation_id,
        "has_sunnah_key": bool(settings.sunnah_api_key),
        "translations": [
            {
                "id": item["id"],
                "name": item.get("name", ""),
                "author": item.get("author_name", ""),
            }
            for item in items
        ],
    }


@router.post("/files/{file_id}/sacred/resolve", response_model=sc.SacredResolveOut)
def resolve_sacred(file_id: str, db: Session = Depends(get_db)):
    """جلب الترجمات المعتمدة للمقاطع المقفولة من المصادر الرسمية.

    الآيات بتتحدَّد على quran.com وبتتجاب بالترجمة المختارة. الأحاديث
    محتاجة مفتاح sunnah.com؛ من غيره بيترجّع رابط بحث للمراجع.

    المقاطع بتفضل **مقفولة وغير معتمدة**: النقل من مصدر خارجي مش
    اعتماد، والمراجع لازم يشوف الإسناد ويوافق بنفسه.
    """
    file = _file_or_404(db, file_id)
    segments = db.execute(
        select(Segment)
        .where(Segment.file_id == file.id, Segment.is_locked.is_(True))
        .order_by(Segment.order_index)
    ).scalars().all()

    results: list[sc.SacredResolutionOut] = []
    resolved = ambiguous = manual = 0

    for segment in segments:
        flags = json.loads(segment.qa_flags or "[]")
        is_quran = any(flag.startswith("quran") for flag in flags)
        plain = strip_tags(segment.source_text)

        # المقطع بيحتوي التمهيد والتخريج مع النص المقدّس: «قال تعالى:
        # ﴿…﴾». البحث بالجملة كلها بيفشل لأن التمهيد مش من الآية،
        # فبنستخدم المدى اللي الكاشف حدّده بالظبط.
        detection = sacred.detect(plain)
        kind = "quran" if is_quran else "hadith"
        spans = [s for s in detection.spans if s.kind == kind]
        needle = spans[0].text if spans else plain

        if is_quran:
            try:
                match = sources.find_verse(needle)
            except Exception as exc:  # noqa: BLE001
                logger.warning("تحديد الآية فشل: %s", exc)
                match = None

            if match is None:
                manual += 1
                results.append(
                    sc.SacredResolutionOut(
                        segment_id=segment.id,
                        kind="quran",
                        status="not_found",
                        note="مالقيناش الآية — راجعها بنفسك على quran.com",
                        url="https://quran.com",
                    )
                )
                continue

            if match.ambiguous:
                ambiguous += 1
                results.append(
                    sc.SacredResolutionOut(
                        segment_id=segment.id,
                        kind="quran",
                        status="ambiguous",
                        reference="، ".join(match.candidates),
                        note=match.note,
                        url=match.url,
                    )
                )
                continue

            # الإسناد بيتكتب مع المقطع — لازم يبان في مستندك وتعرف
            # النص جاي منين
            attribution = (
                f"{match.translation_name} · quran.com/{match.verse_key}"
            )
            segment.target_text = match.translation
            segment.origin = "source"
            segment.notes = (
                f"{segment.notes} | {attribution}" if segment.notes else attribution
            )
            if match.note:
                segment.notes += f" · {match.note}"
            resolved += 1
            results.append(
                sc.SacredResolutionOut(
                    segment_id=segment.id,
                    kind="quran",
                    status="resolved",
                    reference=match.verse_key,
                    text=match.translation,
                    attribution=attribution,
                    note=match.note,
                    url=match.url,
                )
            )
            continue

        # ---- حديث ----
        lead = sources.search_hadith(needle)
        if lead.available and lead.text:
            attribution = f"sunnah.com · {lead.collection} {lead.reference}".strip()
            segment.target_text = lead.text
            segment.origin = "source"
            segment.notes = (
                f"{segment.notes} | {attribution}" if segment.notes else attribution
            )
            resolved += 1
            status = "resolved"
        else:
            manual += 1
            status = "manual"

        results.append(
            sc.SacredResolutionOut(
                segment_id=segment.id,
                kind="hadith",
                status=status,
                reference=lead.reference,
                text=lead.text,
                attribution=(
                    f"sunnah.com · {lead.collection} {lead.reference}".strip()
                    if lead.available
                    else ""
                ),
                note=lead.note,
                url=lead.search_url,
            )
        )

    db.commit()
    return sc.SacredResolveOut(
        checked=len(segments),
        resolved=resolved,
        ambiguous=ambiguous,
        manual=manual,
        translation_name=sources.translation_name(settings.quran_translation_id),
        items=results,
    )


# ---------------------------------------------------------------------------
# المصطلحات
# ---------------------------------------------------------------------------
@router.get("/glossary", response_model=list[sc.GlossaryTermOut])
def list_terms(
    domain: str | None = None,
    project_id: str | None = None,
    db: Session = Depends(get_db),
):
    query = select(GlossaryTerm)
    if domain:
        query = query.where(GlossaryTerm.domain == domain)
    if project_id:
        query = query.where(GlossaryTerm.project_id == project_id)
    terms = db.execute(query.order_by(GlossaryTerm.source_term)).scalars().all()
    return [
        sc.GlossaryTermOut(
            id=t.id,
            source_term=t.source_term,
            target_term=t.target_term,
            domain=t.domain,
            project_id=t.project_id,
            notes=t.notes,
        )
        for t in terms
    ]


@router.post("/glossary", response_model=sc.GlossaryTermOut)
def add_term(payload: sc.GlossaryTermIn, db: Session = Depends(get_db)):
    term = GlossaryTerm(**payload.model_dump())
    db.add(term)
    db.commit()
    return sc.GlossaryTermOut(id=term.id, **payload.model_dump())


def _mark_existing(
    db: Session, candidates, domain: str, project_id: str | None
) -> list[sc.TermCandidateOut]:
    """تعليم المرشّحين الموجودين بالفعل أو المتعارضين مع القاعدة.

    التعارض أهم من التكرار: مصطلح مصدره موجود بترجمة **مختلفة** معناه
    إن القاعدة هتبقى فيها ترجمتين لنفس الكلمة، وده بيضيّع الاتساق
    اللي القاعدة موجودة عشانه.
    """
    # المصطلحات العامة سارية على كل المشاريع، ومصطلحات المشروع بتغلبها.
    scope = GlossaryTerm.project_id.is_(None)
    if project_id:
        scope = or_(scope, GlossaryTerm.project_id == project_id)

    existing = db.execute(
        select(GlossaryTerm)
        .where(GlossaryTerm.domain == domain, scope)
        # الأخص آخر واحد عشان يكتب فوق العام في القاموس
        .order_by(GlossaryTerm.project_id.is_(None).desc())
    ).scalars().all()
    by_source: dict[str, str] = {t.source_term: t.target_term for t in existing}

    # المرحلة الأولى: دمج التكرار التام داخل نفس النتيجة.
    # الاستخراج على دفعات بيرجّع نفس الزوج من أكتر من دفعة، وعرضه
    # مرتين مالوش أي معنى للمراجع.
    merged: dict[tuple[str, str], sc.TermCandidateOut] = {}
    order: list[tuple[str, str]] = []
    for candidate in candidates:
        key = (candidate.source_term, candidate.target_term)
        if key in merged:
            merged[key].frequency += candidate.frequency
            continue
        current = by_source.get(candidate.source_term)
        merged[key] = sc.TermCandidateOut(
            source_term=candidate.source_term,
            target_term=candidate.target_term,
            frequency=candidate.frequency,
            sample=candidate.sample,
            note=candidate.note,
            exists=current == candidate.target_term,
            conflicts_with=(
                current if current and current != candidate.target_term else None
            ),
        )
        order.append(key)

    # المرحلة التانية: نفس المصطلح بترجمتين مختلفتين في **نفس** النتيجة.
    # لو المراجع اختار الاتنين، الإضافة بتضيف الأولى وتحدّثها بالتانية،
    # فيطلع بمصطلح واحد وهو فاكر إنه ضاف اتنين — وأي واحدة تكسب بيتحدد
    # بترتيب عشوائي. لازم يشوف المنافسة قبل ما يختار.
    renderings: dict[str, list[str]] = {}
    for key in order:
        renderings.setdefault(key[0], []).append(key[1])

    for key in order:
        source_term, target_term = key
        others = [r for r in renderings[source_term] if r != target_term]
        if others:
            merged[key].alternatives = others

    return [merged[key] for key in order]


@router.post("/glossary/import", response_model=sc.ExtractionOut)
async def import_glossary_table(
    domain: str = "general",
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """استيراد مصطلحات من جدول CSV أو Excel بعمودين — بدون أي نداء API."""
    name = Path(file.filename or "terms.csv").name
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as tmp:
        temp_path = Path(tmp.name)
        tmp.write(await file.read())

    try:
        result = terms.import_table(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)

    return sc.ExtractionOut(
        candidates=_mark_existing(db, result.candidates, domain, None),
        pairs_examined=result.pairs_examined,
        warnings=result.warnings,
    )


@router.post("/glossary/mine", response_model=sc.ExtractionOut)
def mine_glossary_from_memory(
    payload: sc.MineRequest, db: Session = Depends(get_db)
):
    """استخراج المصطلحات من ذاكرة الترجمة.

    أرخص مصدر: الأزواج المعتمدة موجودة عندك بالفعل، مفيش رفع ولا
    انتظار — بس نداء واحد أو اتنين للنموذج عشان يميّز المصطلح من
    الكلام العادي.
    """
    if not settings.anthropic_api_key:
        raise HTTPException(
            400,
            "استخراج المصطلحات محتاج مفتاح Anthropic. "
            "الاستيراد من جدول شغّال من غيره.",
        )

    entries = db.execute(
        select(TMEntry)
        .where(
            TMEntry.source_lang == payload.source_lang,
            TMEntry.target_lang == payload.target_lang,
            TMEntry.domain == payload.domain,
        )
        .order_by(TMEntry.usage_count.desc())
        .limit(payload.limit)
    ).scalars().all()

    if not entries:
        return sc.ExtractionOut(
            warnings=[
                "الذاكرة فاضية للزوج ده. اعتمد مقاطع في شاشة المراجعة "
                "الأول، أو استورد جدول مصطلحات."
            ]
        )

    result = terms.extract_from_pairs(
        [(e.source_text, e.target_text) for e in entries],
        source_lang=payload.source_lang,
        target_lang=payload.target_lang,
        domain=payload.domain,
    )
    return sc.ExtractionOut(
        candidates=_mark_existing(db, result.candidates, payload.domain, None),
        pairs_examined=result.pairs_examined,
        cost_usd=result.usage.cost_usd,
        warnings=result.warnings,
    )


@router.post("/glossary/extract", response_model=sc.ExtractionOut)
async def extract_glossary_from_pair(
    source_lang: str = "ar",
    target_lang: str = "en",
    domain: str = "general",
    source_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """استخراج المصطلحات من ملف وترجمته المعتمدة."""
    if not settings.anthropic_api_key:
        raise HTTPException(400, "الاستخراج من ملفين محتاج مفتاح Anthropic.")

    saved: list[Path] = []
    work_dir = settings.storage_dir / "work" / "terms"
    try:
        for upload in (source_file, target_file):
            name = Path(upload.filename or "file").name
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=Path(name).suffix
            ) as tmp:
                tmp.write(await upload.read())
                saved.append(Path(tmp.name))

        try:
            alignment = terms.align_documents(saved[0], saved[1], work_dir)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, str(exc)) from exc

        if not alignment.pairs:
            return sc.ExtractionOut(warnings=alignment.warnings or ["مفيش أزواج صالحة"])

        result = terms.extract_from_pairs(
            alignment.pairs,
            source_lang=source_lang,
            target_lang=target_lang,
            domain=domain,
        )
        return sc.ExtractionOut(
            candidates=_mark_existing(db, result.candidates, domain, None),
            pairs_examined=len(alignment.pairs),
            cost_usd=result.usage.cost_usd,
            warnings=alignment.warnings + result.warnings,
        )
    finally:
        for path in saved:
            path.unlink(missing_ok=True)


@router.post("/glossary/bulk")
def add_terms_bulk(payload: sc.BulkTermsIn, db: Session = Depends(get_db)):
    """إضافة المصطلحات اللي وافق عليها المستخدم.

    الموجود بنفس الترجمة بيتخطّى، والموجود بترجمة مختلفة بيتحدّث —
    المستخدم شاف التعارض في شاشة المراجعة قبل ما يوافق.
    """
    added = updated = skipped = 0
    for item in payload.terms:
        existing = db.execute(
            select(GlossaryTerm).where(
                GlossaryTerm.source_term == item.source_term,
                GlossaryTerm.domain == item.domain,
            )
        ).scalar_one_or_none()

        if existing is None:
            db.add(GlossaryTerm(**item.model_dump()))
            added += 1
        elif existing.target_term != item.target_term:
            existing.target_term = item.target_term
            updated += 1
        else:
            skipped += 1

    db.commit()
    return {"added": added, "updated": updated, "skipped": skipped}


@router.delete("/glossary/{term_id}")
def delete_term(term_id: str, db: Session = Depends(get_db)):
    term = db.get(GlossaryTerm, term_id)
    if term is None:
        raise HTTPException(404, "المصطلح غير موجود")
    db.delete(term)
    db.commit()
    return {"deleted": True}


# ---------------------------------------------------------------------------
# التكلفة
# ---------------------------------------------------------------------------
@router.get("/projects/{project_id}/estimate")
def estimate(project_id: str, db: Session = Depends(get_db)):
    """تقدير التكلفة قبل التشغيل — المستخدم يوافق قبل ما يتصرف قرش."""
    project = _project_or_404(db, project_id)

    totals = db.execute(
        select(
            func.coalesce(func.sum(SourceFile.word_count), 0),
            func.coalesce(func.sum(SourceFile.char_count), 0),
            func.coalesce(func.sum(SourceFile.page_count), 0),
            func.coalesce(func.sum(SourceFile.segment_count), 0),
        ).where(SourceFile.project_id == project_id)
    ).one()
    words, chars, pages, segments = (int(v) for v in totals)

    # نسبة التغطية المتوقعة من ذاكرة الترجمة
    file_ids = [
        row[0]
        for row in db.execute(
            select(SourceFile.id).where(SourceFile.project_id == project_id)
        ).all()
    ]
    reuse = 0.0
    if file_ids and segments:
        rows = db.execute(
            select(Segment.source_text).where(
                Segment.file_id.in_(file_ids), Segment.is_translatable.is_(True)
            )
        ).scalars().all()
        sample = rows[:500]  # عيّنة كافية لتقدير النسبة

        # استعلام واحد للعيّنة كلها. الصفحة دي بتتحمّل كل مرة تفتح
        # المشروع، فـ 500 استعلام هنا كانوا بيتحسّوا فعلًا.
        hits = tm.lookup_exact_many(
            db, sample, project.source_lang, project.target_lang, project.domain
        )
        reuse = len(hits) / len(sample) if sample else 0.0

    result = estimate_project(
        words=words,
        chars=chars,
        pages=max(pages, 1),
        segments=segments,
        reuse_ratio=reuse,
        source_lang=project.source_lang,
        target_lang=project.target_lang,
        billable_chars=int(chars * max(0.0, 1.0 - reuse)),
    )
    return {
        "words": result.words,
        "chars": result.chars,
        "pages": result.pages,
        "segments": result.segments,
        "memory_coverage_pct": round(reuse * 100, 1),
        "estimated_input_tokens": result.input_tokens,
        "estimated_output_tokens": result.output_tokens,
        "options": result.options,
    }


@router.get("/projects/{project_id}/cost")
def cost_report(project_id: str, db: Session = Depends(get_db)):
    """التكلفة الفعلية + الوفورات."""
    _project_or_404(db, project_id)

    rows = db.execute(
        select(
            UsageRecord.model,
            func.count(),
            func.coalesce(func.sum(UsageRecord.input_tokens), 0),
            func.coalesce(func.sum(UsageRecord.output_tokens), 0),
            func.coalesce(func.sum(UsageRecord.cache_read_tokens), 0),
            func.coalesce(func.sum(UsageRecord.cache_write_tokens), 0),
            func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
        )
        .where(UsageRecord.project_id == project_id)
        .group_by(UsageRecord.model)
    ).all()

    by_model = [
        {
            "model": model,
            "calls": calls,
            "input_tokens": int(inp),
            "output_tokens": int(out),
            "cache_read_tokens": int(cread),
            "cache_write_tokens": int(cwrite),
            "cost_usd": round(float(cost), 4),
        }
        for model, calls, inp, out, cread, cwrite, cost in rows
    ]

    total_cost = round(sum(item["cost_usd"] for item in by_model), 4)
    cache_read = sum(item["cache_read_tokens"] for item in by_model)

    file_ids = [
        row[0]
        for row in db.execute(
            select(SourceFile.id).where(SourceFile.project_id == project_id)
        ).all()
    ]
    from_memory = 0
    if file_ids:
        from_memory = db.execute(
            select(func.count())
            .select_from(Segment)
            .where(Segment.file_id.in_(file_ids), Segment.origin == "tm_exact")
        ).scalar_one()

    totals = db.execute(
        select(
            func.coalesce(func.sum(SourceFile.word_count), 0),
            func.coalesce(func.sum(SourceFile.page_count), 0),
        ).where(SourceFile.project_id == project_id)
    ).one()
    words, pages = int(totals[0]), int(totals[1])

    # وفورات الكاش: القراءة بتتكلّف 0.1× بدل 1.0×
    cache_saving = 0.0
    for item in by_model:
        try:
            rates = rates_for(item["model"])
        except ValueError:
            continue
        cache_saving += (
            item["cache_read_tokens"] * rates.input_per_mtok * 0.9 / 1_000_000
        )

    return {
        "total_cost_usd": total_cost,
        "by_model": by_model,
        "words": words,
        "pages": pages,
        "cost_per_word": round(total_cost / words, 6) if words else 0.0,
        "cost_per_page": round(total_cost / pages, 4) if pages else 0.0,
        "savings": {
            "segments_from_memory": from_memory,
            "cache_read_tokens": cache_read,
            "cache_saving_usd": round(cache_saving, 4),
        },
    }
