"""نماذج قاعدة البيانات."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# المشروع
# ---------------------------------------------------------------------------
class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(300))
    source_lang: Mapped[str] = mapped_column(String(10), default="ar")
    target_lang: Mapped[str] = mapped_column(String(10), default="en")
    # legal | scientific | medical | technical | general
    domain: Mapped[str] = mapped_column(String(30), default="general")
    model: Mapped[str] = mapped_column(String(50), default="claude-sonnet-5")
    # ملاحظات أسلوبية يكتبها المستخدم وتُحقن في الـ system prompt
    style_notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    files: Mapped[list[SourceFile]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# الملف المصدر
# ---------------------------------------------------------------------------
class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )

    original_filename: Mapped[str] = mapped_column(String(500))
    stored_path: Mapped[str] = mapped_column(String(1000))
    # مسار الملف بعد التحويل (PDF → DOCX) إن وُجد
    working_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    fmt: Mapped[str] = mapped_column(String(10))  # docx | xlsx | pptx | pdf | txt ...
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    sha256: Mapped[str] = mapped_column(String(64), default="")

    # إحصاءات
    page_count: Mapped[int] = mapped_column(Integer, default=0)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    unit_count: Mapped[int] = mapped_column(Integer, default=0)
    segment_count: Mapped[int] = mapped_column(Integer, default=0)

    # pending | extracting | extracted | translating | translated | failed
    status: Mapped[str] = mapped_column(String(30), default="pending")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    project: Mapped[Project] = relationship(back_populates="files")
    segments: Mapped[list[Segment]] = relationship(
        back_populates="file", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# المقطع — وحدة الترجمة والمراجعة
# ---------------------------------------------------------------------------
class Segment(Base):
    __tablename__ = "segments"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )

    order_index: Mapped[int] = mapped_column(Integer)

    # العنوان الدقيق داخل الملف الأصلي (مفتاح الوحدة الحاوية)
    unit_key: Mapped[str] = mapped_column(String(400), index=True)
    # ترتيب المقطع داخل وحدته (فقرة واحدة قد تحوي عدة جُمل)
    unit_order: Mapped[int] = mapped_column(Integer, default=0)
    # نوع الحاوية: paragraph | cell | shape | note | header | footer | comment
    kind: Mapped[str] = mapped_column(String(30), default="paragraph")
    # وصف مقروء للموضع يُعرض للمراجع
    location: Mapped[str] = mapped_column(String(300), default="")

    source_text: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    target_text: Mapped[str] = mapped_column(Text, default="")

    # النص الفاصل بعد هذا المقطع (مسافات/أسطر) لإعادة التركيب بدقة
    trailing_ws: Mapped[str] = mapped_column(String(50), default="")

    # draft | translated | reviewed | approved
    status: Mapped[str] = mapped_column(String(20), default="draft", index=True)
    # هل حرّره إنسان؟ (يمنع الكتابة فوقه عند إعادة الترجمة)
    edited_by_human: Mapped[bool] = mapped_column(Boolean, default=False)
    is_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    # هل هو نص غير قابل للترجمة (أرقام/رموز فقط)؟
    is_translatable: Mapped[bool] = mapped_column(Boolean, default=True)

    # مصدر الترجمة: engine | tm_exact | tm_fuzzy | human | propagated
    origin: Mapped[str] = mapped_column(String(20), default="")
    tm_match_pct: Mapped[int] = mapped_column(Integer, default=0)
    engine_model: Mapped[str] = mapped_column(String(50), default="")

    # أعلام فحوصات الجودة (JSON list)
    qa_flags: Mapped[str] = mapped_column(Text, default="[]")
    notes: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    file: Mapped[SourceFile] = relationship(back_populates="segments")

    __table_args__ = (
        Index("ix_segments_file_order", "file_id", "order_index"),
        Index("ix_segments_file_unit", "file_id", "unit_key", "unit_order"),
    )


# ---------------------------------------------------------------------------
# وحدة النص — تخزين بيانات التنسيق (placeholders) لإعادة البناء
# ---------------------------------------------------------------------------
class TextUnitRecord(Base):
    __tablename__ = "text_units"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    file_id: Mapped[str] = mapped_column(
        ForeignKey("source_files.id", ondelete="CASCADE"), index=True
    )
    unit_key: Mapped[str] = mapped_column(String(400))
    kind: Mapped[str] = mapped_column(String(30), default="paragraph")
    location: Mapped[str] = mapped_column(String(300), default="")
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    source_text: Mapped[str] = mapped_column(Text, default="")
    # خريطة وسوم التنسيق: {"1": "<w:rPr>...</w:rPr>", ...}
    placeholders: Mapped[str] = mapped_column(Text, default="{}")
    meta: Mapped[str] = mapped_column(Text, default="{}")

    __table_args__ = (
        UniqueConstraint("file_id", "unit_key", name="uq_text_unit"),
    )


# ---------------------------------------------------------------------------
# ذاكرة الترجمة
# ---------------------------------------------------------------------------
class TMEntry(Base):
    __tablename__ = "tm_entries"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_hash: Mapped[str] = mapped_column(String(64), index=True)
    source_text: Mapped[str] = mapped_column(Text)
    target_text: Mapped[str] = mapped_column(Text)
    # طول النص المطبَّع — بيسمح بترشيح المرشحين في SQL بدل ما نحمّل
    # الذاكرة كلها ونرشّح في بايثون. الفرق بيكبر مع كبر الذاكرة.
    source_length: Mapped[int] = mapped_column(Integer, default=0, index=True)
    source_lang: Mapped[str] = mapped_column(String(10), default="ar")
    target_lang: Mapped[str] = mapped_column(String(10), default="en")
    domain: Mapped[str] = mapped_column(String(30), default="general", index=True)
    # عدد مرات إعادة الاستخدام (لقياس الوفورات)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    origin_project_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)

    __table_args__ = (
        UniqueConstraint(
            "source_hash", "source_lang", "target_lang", "domain", name="uq_tm"
        ),
    )


# ---------------------------------------------------------------------------
# قاعدة المصطلحات
# ---------------------------------------------------------------------------
class GlossaryTerm(Base):
    __tablename__ = "glossary_terms"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    source_term: Mapped[str] = mapped_column(String(500), index=True)
    target_term: Mapped[str] = mapped_column(String(500))
    domain: Mapped[str] = mapped_column(String(30), default="general", index=True)
    source_lang: Mapped[str] = mapped_column(String(10), default="ar")
    target_lang: Mapped[str] = mapped_column(String(10), default="en")
    # مصطلح ممنوع استخدامه (للتحذير في فحوصات الجودة)
    is_forbidden: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[str] = mapped_column(Text, default="")
    # نطاق المصطلح: عام لكل المشاريع أم لمشروع بعينه
    project_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ---------------------------------------------------------------------------
# سجلّ الاستهلاك والتكلفة
# ---------------------------------------------------------------------------
class UsageRecord(Base):
    __tablename__ = "usage_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

    model: Mapped[str] = mapped_column(String(50))
    operation: Mapped[str] = mapped_column(String(40), default="translate")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)

    is_batch: Mapped[bool] = mapped_column(Boolean, default=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    segments_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)


# ---------------------------------------------------------------------------
# المهام الخلفية
# ---------------------------------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    file_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)

    kind: Mapped[str] = mapped_column(String(40))  # extract | translate | export
    # queued | running | done | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(500), default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[str] = mapped_column(Text, default="{}")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now, onupdate=_now)


# ---------------------------------------------------------------------------
# سجلّ التدقيق — من عدّل إيه وإمتى
# ---------------------------------------------------------------------------
class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    segment_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    project_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    before: Mapped[str] = mapped_column(Text, default="")
    after: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now, index=True)
