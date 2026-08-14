"""محرّك الترجمة — واجهة موحّدة + تنفيذ Claude.

التصميم عن قصد قابل للتبديل: أي محرّك تاني (DeepL / نموذج محلي) بيتنفّذ
نفس البروتوكول من غير ما يتغيّر أي حاجة في باقي النظام، وبيبلّغ عن
تكلفته فالحاسبة بتفضل شغالة مع الكل.

تقنيات مستخدمة لخفض التكلفة ورفع الجودة:
  - **Prompt Caching**: تعليمات المجال + المصطلحات ثابتة طول المشروع،
    فبتتدفع مرة وبعدها بتتقرا بعُشر السعر.
  - **Structured Outputs**: مخطّط JSON مقيّد يضمن إن كل مقطع يرجع
    مربوط بمعرّفه — بدون أي parsing هش للنص.
  - **السياق**: المقاطع المجاورة بتتبعت كسياق (مش للترجمة) عشان
    الضمائر والاتساق.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Protocol

from app.core.config import settings
from app.tools.translator.costing import compute_cost
from app.tools.translator.formats.base import strip_tags, tags_in
from app.tools.translator.langs import script_of, script_ratio
from app.tools.translator.prompts import DOMAIN_EFFORT, build_system_prompt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# أنواع البيانات
# ---------------------------------------------------------------------------
@dataclass
class SegmentInput:
    id: str
    source: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    calls: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens
        self.cost_usd = round(self.cost_usd + other.cost_usd, 6)
        self.calls += other.calls


@dataclass
class BatchResult:
    translations: dict[str, str] = field(default_factory=dict)
    usage: Usage = field(default_factory=Usage)
    missing: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # أعلام على مستوى المقطع الواحد يضيفها المحرّك، بتنضم لأعلام
    # الجودة عشان تظهر للمراجع: {segment_id: ["flag", ...]}
    segment_flags: dict[str, list[str]] = field(default_factory=dict)


class TranslationEngine(Protocol):
    name: str
    model: str
    # محرّك إنتاجي مخرجاته تستحق الحفظ في ذاكرة الترجمة؟
    # المحرّكات التجريبية بتطلع نصًا وهميًا — لو دخل الذاكرة هيلوّث
    # كل المشاريع الحقيقية بعد كده.
    production: bool

    def translate(
        self,
        segments: list[SegmentInput],
        context_before: str = "",
        context_after: str = "",
    ) -> BatchResult: ...


# ---------------------------------------------------------------------------
# تقسيم الدفعات
# ---------------------------------------------------------------------------
def make_batches(
    segments: list[SegmentInput],
    char_budget: int | None = None,
    max_segments: int | None = None,
) -> list[list[SegmentInput]]:
    """تقسيم المقاطع لدفعات متوازنة.

    دفعة كبيرة = تكلفة أقل (التعليمات بتتقسّم على مقاطع أكتر) لكن خطر
    أعلى إن النموذج يهمل مقطع. الحدود دي توازن عملي بين الاتنين.
    """
    char_budget = char_budget or settings.batch_char_budget
    max_segments = max_segments or settings.batch_max_segments

    batches: list[list[SegmentInput]] = []
    current: list[SegmentInput] = []
    size = 0

    for segment in segments:
        length = len(segment.source)
        if current and (size + length > char_budget or len(current) >= max_segments):
            batches.append(current)
            current, size = [], 0
        current.append(segment)
        size += length

    if current:
        batches.append(current)
    return batches


# ---------------------------------------------------------------------------
# مخطّط المخرجات المقيّد
# ---------------------------------------------------------------------------
_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "target": {"type": "string"},
                },
                "required": ["id", "target"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["segments"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# محرّك Claude
# ---------------------------------------------------------------------------
class ClaudeEngine:
    name = "claude"
    production = True

    def __init__(
        self,
        model: str | None = None,
        source_lang: str = "ar",
        target_lang: str = "en",
        domain: str = "general",
        style_notes: str = "",
        glossary: list[tuple[str, str]] | None = None,
        api_key: str | None = None,
        max_tokens: int = 16000,
    ) -> None:
        key = api_key or settings.anthropic_api_key
        if not key:
            raise RuntimeError(
                "مفيش مفتاح Anthropic. حط ANTHROPIC_API_KEY في ملف .env"
            )

        import anthropic

        self.client = anthropic.Anthropic(api_key=key)
        self.model = model or settings.default_model
        self.domain = domain
        self.max_tokens = max_tokens
        self.effort = DOMAIN_EFFORT.get(domain, "medium")
        self.system_prompt = build_system_prompt(
            source_lang=source_lang,
            target_lang=target_lang,
            domain=domain,
            style_notes=style_notes,
            glossary=glossary,
        )

    # -- بناء الطلب ---------------------------------------------------------
    def _system_blocks(self) -> list[dict]:
        """التعليمات ككتلة واحدة مخزَّنة مؤقتًا.

        ثابتة طول المشروع، فأول نداء بيدفع الكتابة والباقي بيقرا
        بعُشر السعر. لازم تفضل مطابقة بايت ببايت وإلا الكاش بيسقط.
        """
        return [
            {
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _user_message(
        self, segments: list[SegmentInput], context_before: str, context_after: str
    ) -> str:
        payload = [{"id": s.id, "text": s.source} for s in segments]
        parts = []

        if context_before:
            parts.append(
                "<context_before>\n"
                "Preceding text, for continuity only. Do NOT translate it.\n"
                f"{context_before}\n</context_before>"
            )

        parts.append(
            "<segments_to_translate>\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=1)}\n"
            "</segments_to_translate>"
        )

        if context_after:
            parts.append(
                "<context_after>\n"
                "Following text, for continuity only. Do NOT translate it.\n"
                f"{context_after}\n</context_after>"
            )

        return "\n\n".join(parts)

    def _request_params(
        self, segments: list[SegmentInput], context_before: str, context_after: str
    ) -> dict:
        """معاملات الطلب — مشتركة بين التنفيذ الفوري والـ Batch API."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": self._system_blocks(),
            "thinking": {"type": "adaptive"},
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA},
            },
            "messages": [
                {
                    "role": "user",
                    "content": self._user_message(
                        segments, context_before, context_after
                    ),
                }
            ],
        }

    # -- التنفيذ ------------------------------------------------------------
    def translate(
        self,
        segments: list[SegmentInput],
        context_before: str = "",
        context_after: str = "",
    ) -> BatchResult:
        if not segments:
            return BatchResult()

        response = self.client.messages.create(
            **self._request_params(segments, context_before, context_after)
        )
        return self._parse(response, segments)

    def _parse(self, response, segments: list[SegmentInput], is_batch: bool = False) -> BatchResult:
        result = BatchResult(usage=self._usage_from(response, is_batch))

        if response.stop_reason == "refusal":
            detail = getattr(response, "stop_details", None)
            category = getattr(detail, "category", None) if detail else None
            result.warnings.append(f"النموذج رفض ترجمة الدفعة (السبب: {category})")
            result.missing = [s.id for s in segments]
            return result

        text = next(
            (block.text for block in response.content if block.type == "text"), ""
        )
        if not text.strip():
            result.warnings.append("رد فارغ من النموذج")
            result.missing = [s.id for s in segments]
            return result

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            result.warnings.append(f"رد غير قابل للقراءة: {exc}")
            result.missing = [s.id for s in segments]
            return result

        for item in parsed.get("segments", []):
            segment_id = str(item.get("id", ""))
            target = item.get("target", "")
            if segment_id:
                result.translations[segment_id] = target

        # المقاطع اللي النموذج أهملها — بتترجع في محاولة منفصلة
        expected = {s.id for s in segments}
        result.missing = sorted(expected - set(result.translations))
        if result.missing:
            result.warnings.append(
                f"{len(result.missing)} مقطع مارجعش في الرد"
            )

        if response.stop_reason == "max_tokens":
            result.warnings.append("الرد اتقطع لوصوله للحد الأقصى للتوكن")

        return result

    def _usage_from(self, response, is_batch: bool = False) -> Usage:
        raw = response.usage
        usage = Usage(
            input_tokens=getattr(raw, "input_tokens", 0) or 0,
            output_tokens=getattr(raw, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(raw, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(raw, "cache_creation_input_tokens", 0) or 0,
            calls=1,
        )
        usage.cost_usd = compute_cost(
            self.model,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            is_batch=is_batch,
        )
        return usage

    def count_tokens(self, segments: list[SegmentInput]) -> int:
        """قياس فعلي للتوكنز — أدق بكتير من أي تقدير بالحروف."""
        response = self.client.messages.count_tokens(
            model=self.model,
            system=self._system_blocks(),
            messages=[{"role": "user", "content": self._user_message(segments, "", "")}],
        )
        return response.input_tokens


# ---------------------------------------------------------------------------
# محرّك الدفعات المجمّعة — خصم 50%
# ---------------------------------------------------------------------------
class ClaudeBatchEngine(ClaudeEngine):
    """نفس محرّك Claude لكن عبر الـ Batch API.

    الفرق: كل الدفعات بتتبعت في طلب واحد وبتتنفّذ على مهل عند Anthropic
    مقابل **نصف السعر**. أغلب الدفعات بتخلص في أقل من ساعة، والحد
    الأقصى 24 ساعة.

    مناسب لملف كبير مش مستعجل. مش مناسب لو محتاج النتيجة دلوقتي.
    """

    name = "claude-batch"

    def __init__(self, *args, poll_seconds: int = 20, max_wait_hours: int = 24, **kwargs):
        super().__init__(*args, **kwargs)
        self.poll_seconds = poll_seconds
        self.max_wait_hours = max_wait_hours

    def translate_many(
        self,
        items: list[tuple[list[SegmentInput], str, str]],
        progress=None,
    ) -> list[BatchResult]:
        """ترجمة كل الدفعات في طلب مجمّع واحد."""
        import time

        from anthropic.types.message_create_params import (
            MessageCreateParamsNonStreaming,
        )
        from anthropic.types.messages.batch_create_params import Request

        if not items:
            return []

        index_of: dict[str, int] = {}
        requests = []
        for index, (segments, before, after) in enumerate(items):
            custom_id = f"batch-{index:05d}"
            index_of[custom_id] = index
            requests.append(
                Request(
                    custom_id=custom_id,
                    params=MessageCreateParamsNonStreaming(
                        **self._request_params(segments, before, after)
                    ),
                )
            )

        submitted = self.client.messages.batches.create(requests=requests)
        logger.info("اتبعتت دفعة مجمّعة %s فيها %d طلب", submitted.id, len(requests))

        if progress:
            progress("submitted", 0, len(requests), submitted.id)

        deadline = time.monotonic() + self.max_wait_hours * 3600
        status = submitted
        while time.monotonic() < deadline:
            status = self.client.messages.batches.retrieve(submitted.id)
            if status.processing_status == "ended":
                break
            counts = status.request_counts
            done = counts.succeeded + counts.errored + counts.canceled + counts.expired
            if progress:
                progress("processing", done, len(requests), submitted.id)
            time.sleep(self.poll_seconds)
        else:
            raise TimeoutError(
                f"الدفعة المجمّعة {submitted.id} عدّت {self.max_wait_hours} ساعة"
            )

        results: list[BatchResult] = [BatchResult() for _ in items]
        for entry in self.client.messages.batches.results(submitted.id):
            index = index_of.get(entry.custom_id)
            if index is None:
                continue

            segments = items[index][0]
            kind = entry.result.type

            if kind == "succeeded":
                results[index] = self._parse(
                    entry.result.message, segments, is_batch=True
                )
            else:
                # فشل/انتهت صلاحيته/اتلغى — المقاطع بتفضل draft فتتكمّل
                # في تشغيلة تانية من غير ما تدفع تاني على اللي نجح
                message = getattr(
                    getattr(entry.result, "error", None), "type", kind
                )
                results[index] = BatchResult(
                    missing=[s.id for s in segments],
                    warnings=[f"الدفعة {entry.custom_id} فشلت: {message}"],
                )

        if progress:
            progress("done", len(requests), len(requests), submitted.id)
        return results


# ---------------------------------------------------------------------------
# محرّك اختباري بدون أي نداءات API
# ---------------------------------------------------------------------------
class EchoEngine:
    """محرّك وهمي للاختبار والتطوير بدون تكلفة.

    بيحافظ على الوسوم والأرقام عشان يعدّي نفس فحوصات الجودة
    اللي بيعدّيها المحرّك الحقيقي.
    """

    name = "echo"
    # مخرجاته وهمية — ممنوع تدخل ذاكرة الترجمة
    production = False

    def __init__(self, model: str = "echo", prefix: str = "[EN] ") -> None:
        self.model = model
        self.prefix = prefix

    def translate(
        self,
        segments: list[SegmentInput],
        context_before: str = "",
        context_after: str = "",
    ) -> BatchResult:
        from app.tools.translator.formats.base import parse_tagged_text

        result = BatchResult()
        for segment in segments:
            pieces = parse_tagged_text(segment.source)
            out = []
            for tag, chunk in pieces:
                body = f"{self.prefix}{chunk.strip()}" if chunk.strip() else chunk
                out.append(f"<g{tag}>{body}</g{tag}>" if tag else body)
            result.translations[segment.id] = "".join(out)

        result.usage = Usage(calls=1)
        return result


# ---------------------------------------------------------------------------
# فحص سلامة الترجمة قبل قبولها
# ---------------------------------------------------------------------------
# رقم بمجموعات آلاف بأي فاصل شائع (فاصلة، نقطة، مسافة عادية أو غير
# فاصلة)، مع كسر عشري اختياري. الترتيب مهم: النمط المجمَّع الأول عشان
# مايتقطّعش الرقم لأجزاء.
_NUMBER_RE = re.compile(
    r"\d{1,3}(?:[.,   ]\d{3})+(?:[.,]\d+)?"  # 150,000 / 150.000 / 150 000
    r"|\d+[.,]\d+"                                      # 3.14
    r"|\d+"                                             # 30
)


_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)


def _adjacent_duplicate(text: str) -> bool:
    """هل فيه كلمة مكرّرة مرتين ورا بعض؟

    بنتجاهل الكلمات الطويلة لأن التكرار الحقيقي فيها نادر ومقصود
    عادةً؛ العيب اللي بندوّر عليه بيحصل في حروف الجر والأدوات.
    """
    words = [w.lower() for w in _WORD_RE.findall(text)]
    return any(
        first == second and len(first) <= 4
        for first, second in zip(words, words[1:])
    )


def validate_translation(
    source: str,
    target: str,
    source_lang: str = "ar",
    target_lang: str = "en",
) -> list[str]:
    """مشاكل بنيوية في مقطع مترجم — بتتحوّل لأعلام في شاشة المراجعة.

    الفحوصات محايدة تجاه اتجاه الترجمة: بتقارن **كتابة** النص المصدر
    بكتابة الهدف بدل ما تفترض إن المصدر عربي والهدف إنجليزي.
    """
    problems: list[str] = []

    if not target.strip():
        problems.append("empty")
        return problems

    # الوسوم لازم تفضل زي ما هي
    source_tags, target_tags = tags_in(source), tags_in(target)
    if source_tags != target_tags:
        missing = source_tags - target_tags
        extra = target_tags - source_tags
        if missing:
            problems.append(f"tags_missing:{','.join(sorted(missing))}")
        if extra:
            problems.append(f"tags_extra:{','.join(sorted(extra))}")

    # الأرقام على مستويين: الأرقام نفسها، والاصطلاح اللي اتكتبت بيه.
    # تغيير الأرقام كارثة؛ تغيير الفاصل قرار تحريري محتاج مراجعة.
    plain_source = strip_tags(source)
    plain_target = strip_tags(target)

    source_numbers = _NUMBER_RE.findall(plain_source)
    target_numbers = _NUMBER_RE.findall(plain_target)

    def digits(values: list[str]) -> list[str]:
        return sorted(re.sub(r"\D", "", v) for v in values)

    if digits(source_numbers) != digits(target_numbers):
        # رقم اتغيّر أو ضاع — أخطر خطأ ممكن في عقد
        problems.append("numbers_mismatch")
    elif sorted(source_numbers) != sorted(target_numbers):
        # نفس الأرقام بفواصل مختلفة: 150,000 بقت 150.000 أو 150 000.
        # ده صحيح لغويًا في لغة الهدف لكنه بيغيّر شكل المستند، فبنرفعه
        # للمراجع بدل ما نقرر بدله.
        problems.append("separator_changed")

    # فاصل الآلاف الملتبس: "150.000" في العربية = مئة وخمسون ألفًا،
    # وفي الإنجليزية تُقرأ 150 فاصلة صفر. الأرقام متطابقة حرفيًا فالفحص
    # السابق مابيمسكهاش، لكن **المعنى اتغيّر** — وده كارثي في العقود
    # المالية. مابنصلّحهاش تلقائيًا (الاصطلاح بيختلف بين المصادر)،
    # بنرفعها للمراجع ياخد القرار.
    ambiguous = re.findall(r"\d+\.\d{3}(?!\d)", plain_source)
    if ambiguous:
        problems.append("ambiguous_separator:" + ",".join(ambiguous[:3]))

    # كتابة المصدر لسه غالبة على الهدف = مقطع ماتترجمش.
    # بنقارن الكتابتين بدل ما نفترض اتجاهًا معيّنًا، فالفحص شغّال
    # مع عربي→إنجليزي وإنجليزي→عربي بنفس المنطق.
    plain = strip_tags(target)
    source_script = script_of(source_lang)
    target_script = script_of(target_lang)
    if source_script != target_script:
        leftover = script_ratio(plain, source_script)
        if leftover > 0.3:
            problems.append("untranslated")
        elif script_ratio(plain, target_script) < 0.3 and len(plain) > 12:
            # مش بكتابة الهدف ولا المصدر — غالبًا رد غريب
            problems.append("wrong_script")

    # كلمة مكرّرة مرتين ورا بعض في الهدف ومش مكرّرة في المصدر.
    #
    # ده العَرَض الأشهر لعيب في محرّكات الترجمة الآلية: بتترجم كل جزء
    # موسوم بالتنسيق شبه مستقل، فحرف الجر اللي في آخر جزء بيتكرر في
    # أول الجزء اللي بعده:
    #   المصدر: <g1>signed in </g1><g2>Kyiv</g2>
    #   المخرَج: <g1>подписано в </g1><g2>в Киеве</g2>   ← "в в"
    # الفحص عام: مايفترضش لغة ولا محرّك.
    if _adjacent_duplicate(plain_target) and not _adjacent_duplicate(plain_source):
        problems.append("duplicated_word")

    # طول شاذ = مؤشّر حذف أو هلوسة
    source_len = len(strip_tags(source))
    if source_len >= 25:
        ratio = len(plain) / source_len
        if ratio < 0.4:
            problems.append("too_short")
        elif ratio > 3.0:
            problems.append("too_long")

    return problems
