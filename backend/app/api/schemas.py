"""مخططات الطلب والاستجابة."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=300)
    source_lang: str = "ar"
    target_lang: str = "en"
    domain: str = "general"
    engine: str = "claude"
    model: str = "claude-sonnet-5"
    style_notes: str = ""


class ProjectUpdate(BaseModel):
    name: str | None = None
    domain: str | None = None
    engine: str | None = None
    model: str | None = None
    style_notes: str | None = None


class ProjectOut(BaseModel):
    id: str
    name: str
    source_lang: str
    target_lang: str
    domain: str
    engine: str
    model: str
    style_notes: str
    status: str
    created_at: datetime
    file_count: int = 0
    word_count: int = 0
    cost_usd: float = 0.0


class FileOut(BaseModel):
    id: str
    project_id: str
    original_filename: str
    fmt: str
    size_bytes: int
    page_count: int
    word_count: int
    char_count: int
    unit_count: int
    segment_count: int
    status: str
    error: str | None = None
    progress: dict | None = None


class SegmentOut(BaseModel):
    id: str
    order_index: int
    unit_key: str
    kind: str
    location: str
    source_text: str
    target_text: str
    status: str
    origin: str
    tm_match_pct: int
    is_translatable: bool
    is_locked: bool
    edited_by_human: bool
    qa_flags: list[str] = []
    notes: str = ""


class SegmentPage(BaseModel):
    items: list[SegmentOut]
    total: int
    offset: int
    limit: int


class SegmentUpdate(BaseModel):
    target_text: str | None = None
    source_text: str | None = None
    status: str | None = None
    notes: str | None = None
    is_locked: bool | None = None
    # هل نحسب خطة انتشار للتعديل ده؟
    plan_propagation: bool = True


class PropagationTargetOut(BaseModel):
    segment_id: str
    location: str
    source_text: str
    current_target: str
    proposed_target: str
    match_type: str
    score: int


class PropagationPlanOut(BaseModel):
    auto_applied: int = 0
    needs_review: list[PropagationTargetOut] = []


class SegmentUpdateResult(BaseModel):
    segment: SegmentOut
    propagation: PropagationPlanOut | None = None


class PropagationApply(BaseModel):
    segment_ids: list[str]
    target_texts: dict[str, str] = {}


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    progress: int
    total: int
    message: str
    error: str | None = None
    result: dict = {}


class GlossaryTermIn(BaseModel):
    source_term: str
    target_term: str
    domain: str = "general"
    project_id: str | None = None
    notes: str = ""


class GlossaryTermOut(GlossaryTermIn):
    id: str


class TermCandidateOut(BaseModel):
    source_term: str
    target_term: str
    frequency: int = 1
    sample: str = ""
    note: str = ""
    # هل الزوج ده موجود في القاعدة بالفعل؟
    exists: bool = False
    conflicts_with: str | None = None
    # ترجمات تانية لنفس المصطلح ظهرت في **نفس** النتيجة.
    # لو المستخدم اختار أكتر من واحدة، الأخيرة بتاكل اللي قبلها بصمت.
    alternatives: list[str] = []


class ExtractionOut(BaseModel):
    candidates: list[TermCandidateOut] = []
    pairs_examined: int = 0
    cost_usd: float = 0.0
    warnings: list[str] = []


class MineRequest(BaseModel):
    """استخراج من ذاكرة الترجمة."""

    source_lang: str = "ar"
    target_lang: str = "en"
    domain: str = "general"
    limit: int = 200


class BulkTermsIn(BaseModel):
    terms: list[GlossaryTermIn]


class SacredResolutionOut(BaseModel):
    """نتيجة محاولة جلب ترجمة معتمدة لمقطع مقفول."""

    segment_id: str
    kind: str                      # quran | hadith
    # resolved | ambiguous | not_found | manual
    status: str
    reference: str = ""            # 2:275 أو رقم الحديث
    text: str = ""
    attribution: str = ""          # اسم الترجمة والمصدر
    note: str = ""
    url: str = ""


class SacredResolveOut(BaseModel):
    checked: int = 0
    resolved: int = 0
    ambiguous: int = 0
    manual: int = 0
    # اتفكّ قفلهم عشان المحرّك يترجمهم — مالقيناش لهم مصدر معتمد
    released: int = 0
    translation_name: str = ""
    items: list[SacredResolutionOut] = []


class EstimateRequest(BaseModel):
    models: list[str] | None = None


class TranslateRequest(BaseModel):
    # auto  = محرّك المشروع | claude | deepl | batch
    # echo  = تشغيل تجريبي بدون تكلفة ولا نداءات API
    engine: str = "auto"
    model: str | None = None
    use_memory: bool = True
