"""خط الأنابيب: استيعاب → استخراج → تقسيم → ترجمة → دمج → تصدير.

كل مرحلة بتشتغل على قاعدة البيانات وبتحدّث حالة المهمة، فالواجهة
تقدر تعرض تقدّمًا لحظيًا وتقدر تكمّل من حيث وقفت لو حصل انقطاع.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import (
    Job,
    Project,
    Segment,
    SourceFile,
    TextUnitRecord,
    UsageRecord,
)
from app.tools.translator import sacred, tm
from app.tools.translator.costing import pages_from_words
from app.tools.translator.engine import (
    BatchResult,
    SegmentInput,
    make_batches,
    validate_translation,
)
from app.tools.translator.formats import registry
from app.tools.translator.formats.base import (
    count_words,
    is_translatable,
    strip_tags,
    text_hash,
)
from app.tools.translator.segment import split_sentences

logger = logging.getLogger(__name__)


def project_dir(project_id: str) -> Path:
    path = settings.storage_dir / "projects" / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# 1) الاستيعاب
# ---------------------------------------------------------------------------
def ingest(
    db: Session, project: Project, source_path: Path, original_name: str
) -> SourceFile:
    """نسخ الملف المرفوع لمساحة المشروع وتسجيله."""
    fmt = registry.detect_format(original_name)

    folder = project_dir(project.id) / "source"
    folder.mkdir(parents=True, exist_ok=True)
    stored = folder / original_name
    if source_path.resolve() != stored.resolve():
        shutil.copyfile(source_path, stored)

    digest = hashlib.sha256(stored.read_bytes()).hexdigest()

    record = SourceFile(
        project_id=project.id,
        original_filename=original_name,
        stored_path=str(stored),
        fmt=fmt,
        size_bytes=stored.stat().st_size,
        sha256=digest,
        status="pending",
    )
    db.add(record)
    db.flush()
    return record


# ---------------------------------------------------------------------------
# 2) الاستخراج والتقسيم
# ---------------------------------------------------------------------------
@dataclass
class ExtractionStats:
    units: int
    segments: int
    words: int
    chars: int
    pages: int
    ocr_pages: int = 0
    ocr_cost_usd: float = 0.0
    ocr_failed_pages: list[int] = field(default_factory=list)
    # آيات وأحاديث: اتقفلت (مؤكَّدة) أو اتعلّمت للمراجعة (مرجَّحة)
    sacred_locked: int = 0
    sacred_flagged: int = 0


def _run_ocr(
    db: Session,
    file: SourceFile,
    source: Path,
    work_dir: Path,
    job: Job | None,
) -> tuple[Path, str, dict]:
    """قراءة مستند ممسوح ضوئيًا وتحويله لملف Word.

    بعد الخطوة دي الملف بيتعامل معاملة أي ملف Word عادي — نفس
    الاستخراج ونفس الدمج ونفس التصدير.
    """
    from app.tools.translator import ocr

    project = db.get(Project, file.project_id)
    if job:
        job.message = "قراءة ضوئية للصفحات"
        db.commit()

    def report(done: int, total: int) -> None:
        if job:
            job.progress, job.total = done, total
            job.message = f"قراءة ضوئية {done}/{total} صفحة"

    result = ocr.read_document(
        source,
        model=project.model if project else None,
        progress=report,
    )

    # تكلفة الـ OCR بتتسجّل زي أي نداء تاني عشان تظهر في الحاسبة
    db.add(
        UsageRecord(
            project_id=file.project_id,
            file_id=file.id,
            model=project.model if project else settings.default_model,
            operation="ocr",
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_tokens,
            cache_write_tokens=result.usage.cache_write_tokens,
            cost_usd=result.usage.cost_usd,
            segments_count=len(result.blocks),
        )
    )

    if not result.blocks:
        file.status = "failed"
        file.error = (
            f"القراءة الضوئية مانجحتش على أي صفحة ({result.pages} صفحة). "
            "جرّب ملفًا بجودة مسح أعلى."
        )
        db.commit()
        raise RuntimeError(file.error)

    if result.failed_pages:
        logger.warning(
            "صفحات مافيهاش نص مقروء في %s: %s",
            file.original_filename,
            result.failed_pages[:10],
        )

    target = work_dir / f"{source.stem}.ocr.docx"
    ocr.build_docx(
        result,
        target,
        title="",
        source_lang=project.source_lang if project else "ar",
    )

    file.page_count = result.pages
    db.commit()
    return target, "docx", {
        "pages": result.pages,
        "cost_usd": result.usage.cost_usd,
        "failed_pages": result.failed_pages,
    }


def extract_and_segment(
    db: Session,
    file: SourceFile,
    job: Job | None = None,
    allow_ocr: bool = True,
) -> ExtractionStats:
    """استخراج وحدات النص وتقسيمها لمقاطع قابلة للترجمة."""
    file.status = "extracting"
    db.flush()

    work_dir = project_dir(file.project_id) / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

    source = Path(file.stored_path)
    working_path, working_fmt, meta = registry.prepare(file.fmt, source, work_dir)

    if meta.get("needs_ocr"):
        if not (allow_ocr and settings.anthropic_api_key):
            file.status = "failed"
            file.error = (
                "الملف ممسوح ضوئيًا (صور بدون طبقة نص) والـ OCR محتاج "
                "مفتاح Anthropic. حط ANTHROPIC_API_KEY في ملف .env."
            )
            db.commit()
            raise RuntimeError(file.error)

        working_path, working_fmt, ocr_info = _run_ocr(
            db, file, source, work_dir, job
        )
        meta["ocr"] = ocr_info

    file.working_path = str(working_path)
    if meta.get("page_count"):
        file.page_count = int(meta["page_count"])

    # التطبيع بيتفعّل للملفات الجاية من PDF (أشكال العرض العربية)
    result = registry.extract(
        working_fmt, Path(working_path), normalize=(file.fmt == "pdf")
    )

    # تنظيف أي استخراج سابق لنفس الملف
    db.query(Segment).filter(Segment.file_id == file.id).delete()
    db.query(TextUnitRecord).filter(TextUnitRecord.file_id == file.id).delete()
    db.flush()

    order = 0
    total_words = total_chars = 0
    sacred_locked = sacred_flagged = 0

    for unit in result.units:
        db.add(
            TextUnitRecord(
                file_id=file.id,
                unit_key=unit.unit_key,
                kind=unit.kind,
                location=unit.location,
                order_index=unit.order_index,
                source_text=unit.text,
                placeholders=json.dumps(unit.placeholders, ensure_ascii=False),
                meta=json.dumps(unit.meta, ensure_ascii=False),
            )
        )

        unit_translatable = unit.meta.get("translatable", True)

        for unit_order, span in enumerate(split_sentences(unit.text)):
            if not span.text and not span.trailing:
                continue

            translatable = bool(
                unit_translatable and span.text and is_translatable(span.text)
            )
            plain = strip_tags(span.text)
            total_words += count_words(span.text)
            total_chars += len(plain)

            # الآيات والأحاديث: بنكشفها هنا قبل ما توصل لأي محرّك.
            # المؤكَّد بيتقفل فمايتبعتش للترجمة أصلًا، والمرجَّح بيتعلّم
            # للمراجع من غير ما يوقّف الشغل.
            sacred_hit = sacred.detect(plain) if translatable else sacred.Detection()

            db.add(
                Segment(
                    file_id=file.id,
                    order_index=order,
                    unit_key=unit.unit_key,
                    unit_order=unit_order,
                    kind=unit.kind,
                    location=unit.location,
                    source_text=span.text,
                    source_hash=text_hash(span.text),
                    trailing_ws=span.trailing,
                    is_translatable=translatable,
                    # النص غير القابل للترجمة بيعدّي زي ما هو
                    target_text="" if translatable else span.text,
                    status="draft" if translatable else "approved",
                    is_locked=sacred_hit.certain,
                    qa_flags=json.dumps(sacred_hit.flags(), ensure_ascii=False),
                    notes=sacred_hit.note(),
                )
            )
            if sacred_hit.certain:
                sacred_locked += 1
            elif sacred_hit.found:
                sacred_flagged += 1
            order += 1

    file.unit_count = len(result.units)
    file.segment_count = order
    file.word_count = total_words
    file.char_count = total_chars
    file.page_count = file.page_count or result.page_count or pages_from_words(total_words)
    file.status = "extracted"
    # حفظ فوري بدل ما القفل يفضل ماسك القاعدة لحد ما المهمة تخلص
    db.commit()

    ocr_info = meta.get("ocr") or {}
    return ExtractionStats(
        units=len(result.units),
        segments=order,
        words=total_words,
        chars=total_chars,
        pages=file.page_count,
        ocr_pages=int(ocr_info.get("pages", 0)),
        ocr_cost_usd=float(ocr_info.get("cost_usd", 0.0)),
        ocr_failed_pages=list(ocr_info.get("failed_pages", [])),
        sacred_locked=sacred_locked,
        sacred_flagged=sacred_flagged,
    )


# ---------------------------------------------------------------------------
# 3) الترجمة
# ---------------------------------------------------------------------------
@dataclass
class TranslationStats:
    translated: int = 0
    from_memory: int = 0
    failed: int = 0
    flagged: int = 0
    cost_usd: float = 0.0
    calls: int = 0
    cancelled: bool = False
    errors: list[str] = field(default_factory=list)


def translate_file(
    db: Session,
    file: SourceFile,
    engine,
    job: Job | None = None,
    use_memory: bool = True,
    context_size: int = 220,
    concurrency: int | None = None,
) -> TranslationStats:
    """ترجمة كل المقاطع المعلّقة في الملف.

    الدفعات بتتنفّذ بالتوازي. المقاطع اللي فشلت بتفضل في حالة `draft`
    فإعادة التشغيل بتكمّل من حيث وقفت من غير ما تدفع تاني على اللي خلص.
    """
    concurrency = concurrency or settings.translation_concurrency
    project = db.get(Project, file.project_id)
    stats = TranslationStats()

    # المقفول بيتستثنى هنا مش في مكان تاني: القفل معناه إن في إنسان
    # قرر إن المقطع ده مايتكتبش فوقه — سواء قفله بإيده أو اتقفل تلقائيًا
    # لأنه آية أو حديث. من غير الشرط ده، إعادة تشغيل الترجمة كانت
    # بتدوس على المقفول وتبعته للمحرّك.
    pending = db.execute(
        select(Segment)
        .where(
            Segment.file_id == file.id,
            Segment.is_translatable.is_(True),
            Segment.is_locked.is_(False),
            Segment.status == "draft",
        )
        .order_by(Segment.order_index)
    ).scalars().all()

    if not pending:
        return stats

    file.status = "translating"
    if job:
        job.total = len(pending)
        job.progress = 0
    db.flush()

    glossary = tm.load_glossary(db, domain=project.domain, project_id=project.id)

    # ---- المرحلة الأولى: ذاكرة الترجمة (ببلاش) ----
    remaining: list[Segment] = []
    if use_memory:
        # استعلام واحد لكل المقاطع بدل استعلام لكل مقطع — الفرق كبير
        # على الملفات الكبيرة (1500 مقطع كانوا 1500 استعلام)
        hits = tm.lookup_exact_many(
            db,
            [s.source_text for s in pending],
            project.source_lang,
            project.target_lang,
            project.domain,
        )
        for segment in pending:
            match = hits.get(segment.source_hash)
            if match:
                segment.target_text = match.target_text
                segment.status = "translated"
                segment.origin = "tm_exact"
                segment.tm_match_pct = 100
                stats.from_memory += 1
            else:
                remaining.append(segment)
    else:
        remaining = list(pending)

    if job:
        job.progress = stats.from_memory
        job.message = f"{stats.from_memory} مقطع من الذاكرة"
    # حفظ فوري: المهمة ممكن تاخد دقايق، والقفل الطويل على SQLite
    # بيمنع أي كتابة تانية ويخفي التقدّم عن الواجهة.
    db.commit()

    # ---- المرحلة الثانية: المحرّك ----
    by_id = {segment.id: segment for segment in remaining}
    inputs = [SegmentInput(id=s.id, source=s.source_text) for s in remaining]
    batches = make_batches(inputs)

    all_segments = db.execute(
        select(Segment).where(Segment.file_id == file.id).order_by(Segment.order_index)
    ).scalars().all()
    position = {segment.id: index for index, segment in enumerate(all_segments)}

    # نجهّز السياق لكل الدفعات مقدّمًا: السياق بيتحسب من قايمة المقاطع
    # نفسها مش من نتيجة الدفعة اللي قبلها، فالدفعات مستقلة تمامًا
    # وبالتالي التوازي آمن.
    prepared = [
        (batch, *_context_for(batch, all_segments, position, context_size))
        for batch in batches
    ]

    def apply(result: BatchResult) -> None:
        """كتابة نتيجة دفعة في قاعدة البيانات — بتتنفّذ في الخيط الرئيسي فقط."""
        _record_usage(db, project, file, engine, result)
        stats.cost_usd = round(stats.cost_usd + result.usage.cost_usd, 6)
        stats.calls += result.usage.calls

        for segment_id, target in result.translations.items():
            segment = by_id.get(segment_id)
            if segment is None:
                continue

            problems = validate_translation(
                segment.source_text,
                target,
                source_lang=project.source_lang,
                target_lang=project.target_lang,
            )
            violations = tm.check_glossary(segment.source_text, target, glossary)
            if violations:
                problems.append("glossary:" + " | ".join(violations[:3]))

            # أعلام المحرّك نفسه (مثلًا: بسّط التنسيق عن قصد)
            problems.extend(result.segment_flags.get(segment_id, []))

            # أعلام النص المقدّس اتحطّت وقت الاستخراج من فحص المصدر،
            # وفحوصات ما بعد الترجمة مابتعرفش عنها حاجة. من غير الدمج
            # ده كانت بتتمسح ساعة ما المقطع يترجم — وهي بالظبط اللحظة
            # اللي المراجع محتاج يشوفها فيها.
            problems.extend(
                flag for flag in json.loads(segment.qa_flags or "[]")
                if flag.startswith(("quran_", "hadith_"))
            )

            segment.target_text = target
            segment.status = "translated"
            # المحرّكات التجريبية بتتعلّم عشان مخرجاتها ماتدخلش الذاكرة
            segment.origin = "engine" if getattr(engine, "production", True) else "echo"
            segment.engine_model = engine.model
            segment.qa_flags = json.dumps(problems, ensure_ascii=False)

            stats.translated += 1
            if problems:
                stats.flagged += 1

        stats.failed += len(result.missing)
        for warning in result.warnings:
            logger.warning("ترجمة %s: %s", file.original_filename, warning)

        if job:
            job.progress = stats.from_memory + stats.translated
            job.message = f"{job.progress}/{job.total} مقطع"

        # حفظ بعد كل دفعة: التقدّم يبان لحظيًا، والقفل بيتساب فورًا،
        # ولو حصل انقطاع الشغل اللي خلص مايضيعش.
        db.commit()

    def cancelled() -> bool:
        """هل المستخدم طلب الإلغاء؟

        مافيش وسيلة نقتل بيها خيط شغّال في بايثون، فبنفحص بين الدفعات.
        النتيجة: الدفعة الحالية بتكمّل والباقي بيتلغي — والمقاطع اللي
        خلصت بتفضل محفوظة.
        """
        if job is None:
            return False
        db.refresh(job)
        return job.status == "cancelling"

    def run(item) -> BatchResult:
        batch, before, after = item
        return engine.translate(batch, before, after)

    # ---- مسار الدفعات المجمّعة (نصف السعر، تنفيذ غير فوري) ----
    if hasattr(engine, "translate_many"):
        def report(phase: str, done: int, total: int, batch_id: str) -> None:
            if not job:
                return
            labels = {
                "submitted": "اتبعتت للتنفيذ المجمّع",
                "processing": "جارٍ التنفيذ المجمّع",
                "done": "اكتمل التنفيذ المجمّع",
            }
            job.message = f"{labels.get(phase, phase)} · {done}/{total} دفعة"
            db.commit()

        for result in engine.translate_many(prepared, progress=report):
            apply(result)

        file.status = "translated"
        db.commit()
        return stats

    # ---- المسار الفوري (متوازي) ----
    if prepared:
        # الدفعة الأولى لوحدها عن قصد: هي اللي بتكتب التعليمات في الكاش.
        # لو بعتنا كل الدفعات مع بعض من الأول، كلها هتفوّت الكاش وتدفع
        # السعر الكامل — يعني التوازي كان هيزوّد التكلفة بدل ما يوفّرها.
        apply(run(prepared[0]))

    rest = prepared[1:]
    if rest and not cancelled():
        workers = max(1, min(concurrency, len(rest)))
        if job:
            job.message = f"{job.progress}/{job.total} مقطع · {workers} دفعات متوازية"
            db.commit()

        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tr") as pool:
            futures = [pool.submit(run, item) for item in rest]
            # النتائج بتتكتب هنا في الخيط الرئيسي — جلسة SQLAlchemy
            # مش آمنة للاستخدام من أكتر من خيط.
            for future in as_completed(futures):
                try:
                    apply(future.result())
                except Exception as exc:  # noqa: BLE001
                    logger.exception("فشلت دفعة ترجمة")
                    stats.errors.append(f"{type(exc).__name__}: {exc}")

                if cancelled():
                    # الدفعات اللي لسه ماابتدتش بتتلغى؛ اللي شغّالة بتكمّل
                    for pending_future in futures:
                        pending_future.cancel()
                    stats.cancelled = True
                    logger.info("اتلغت ترجمة %s بطلب المستخدم", file.original_filename)
                    break

    # المقاطع اللي ماترجمتش بتفضل draft، فإعادة التشغيل بتكمّل من حيث
    # وقفت من غير ما تدفع تاني على اللي خلص
    file.status = "extracted" if stats.cancelled else "translated"
    db.commit()
    return stats


def _context_for(
    batch: list[SegmentInput],
    all_segments: list[Segment],
    position: dict[str, int],
    size: int,
) -> tuple[str, str]:
    """نص المقاطع المجاورة — بيحسّن ترجمة الضمائر والإحالات."""
    if not batch:
        return "", ""

    first = position.get(batch[0].id)
    last = position.get(batch[-1].id)
    if first is None or last is None:
        return "", ""

    before_parts: list[str] = []
    index = first - 1
    while index >= 0 and sum(map(len, before_parts)) < size:
        before_parts.insert(0, strip_tags(all_segments[index].source_text))
        index -= 1

    after_parts: list[str] = []
    index = last + 1
    while index < len(all_segments) and sum(map(len, after_parts)) < size:
        after_parts.append(strip_tags(all_segments[index].source_text))
        index += 1

    return " ".join(before_parts)[-size:], " ".join(after_parts)[:size]


def _record_usage(
    db: Session, project: Project, file: SourceFile, engine, result: BatchResult
) -> None:
    if result.usage.calls == 0:
        return
    db.add(
        UsageRecord(
            project_id=project.id,
            file_id=file.id,
            model=engine.model,
            operation="translate",
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            cache_read_tokens=result.usage.cache_read_tokens,
            cache_write_tokens=result.usage.cache_write_tokens,
            cost_usd=result.usage.cost_usd,
            segments_count=len(result.translations),
        )
    )


# ---------------------------------------------------------------------------
# 4) التصدير
# ---------------------------------------------------------------------------
def assemble_units(db: Session, file: SourceFile) -> dict[str, str]:
    """إعادة تركيب نص كل وحدة من مقاطعها المترجمة.

    بنستخدم الفاصل الأصلي المخزَّن مع كل مقطع، فالنتيجة بتطابق بنية
    النص الأصلي بالظبط. المقاطع اللي لسه ماتترجمتش بيرجع مكانها المصدر
    عشان مايحصلش فقدان محتوى.
    """
    segments = db.execute(
        select(Segment)
        .where(Segment.file_id == file.id)
        .order_by(Segment.unit_key, Segment.unit_order)
    ).scalars().all()

    units: dict[str, list[str]] = {}
    for segment in segments:
        text = segment.target_text if segment.target_text.strip() else segment.source_text
        units.setdefault(segment.unit_key, []).append(text + segment.trailing_ws)

    return {key: "".join(parts) for key, parts in units.items()}


def export_file(db: Session, file: SourceFile) -> Path:
    """كتابة الملف المترجم بنفس صيغة وتنسيق الأصل.

    اتجاه المستند بيتضبط حسب لغة الهدف: عربي→إنجليزي بيشيل خصائص
    RTL، وإنجليزي→عربي بيضيفها.
    """
    project = db.get(Project, file.project_id)
    target_lang = project.target_lang if project else "en"

    working_path = Path(file.working_path or file.stored_path)
    working_fmt = "docx" if file.fmt == "pdf" else file.fmt

    translations = assemble_units(db, file)

    out_dir = project_dir(file.project_id) / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(file.original_filename).stem
    extension = registry.output_extension(working_fmt)
    output = out_dir / f"{stem}.{target_lang}{extension}"

    registry.merge(
        working_fmt, working_path, output, translations, target_lang=target_lang
    )
    return output


# ---------------------------------------------------------------------------
# اعتماد المقاطع وحفظها في الذاكرة
# ---------------------------------------------------------------------------
def approve_segment(db: Session, segment: Segment, save_to_memory: bool = True) -> None:
    project = db.get(Project, db.get(SourceFile, segment.file_id).project_id)
    segment.status = "approved"

    # حاجز أساسي: مخرجات المحرّكات التجريبية ممنوعة من الذاكرة.
    # لو دخلت، هتترجع في كل مشروع حقيقي بعد كده وتفسد المخرجات.
    if segment.origin == "echo" or segment.engine_model == "echo":
        return

    if save_to_memory and segment.target_text.strip():
        tm.store(
            db,
            segment.source_text,
            segment.target_text,
            project.source_lang,
            project.target_lang,
            project.domain,
            project.id,
        )


def file_progress(db: Session, file_id: str) -> dict:
    """ملخّص حالة المقاطع — بيغذّي شريط التقدّم في الواجهة."""
    rows = db.execute(
        select(Segment.status, func.count())
        .where(Segment.file_id == file_id)
        .group_by(Segment.status)
    ).all()
    counts = {status: count for status, count in rows}
    total = sum(counts.values())

    flagged = db.execute(
        select(func.count())
        .select_from(Segment)
        .where(Segment.file_id == file_id, Segment.qa_flags != "[]")
    ).scalar_one()

    return {
        "total": total,
        "draft": counts.get("draft", 0),
        "translated": counts.get("translated", 0),
        "reviewed": counts.get("reviewed", 0),
        "approved": counts.get("approved", 0),
        "flagged": flagged,
        "done_pct": round(
            100 * (counts.get("approved", 0) + counts.get("reviewed", 0)) / total
        )
        if total
        else 0,
    }
