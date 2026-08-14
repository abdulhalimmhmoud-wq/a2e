"""محرّك DeepL — بديل لمحرّك Claude بنفس البروتوكول.

**DeepL مش مفتوح المصدر ولا مجاني** — خدمة تجارية ألمانية. فيه باقة
API مجانية بحد 500 ألف حرف شهريًا، وبعدها بتتحاسب بالحرف.

ليه نضيفه أصلًا مع إن Claude عندنا؟
  - **أسرع بكتير**: أجزاء من الثانية بدل ~34 ثانية للدفعة.
  - **ثابت**: نفس الإدخال بيدي نفس الإخراج دايمًا، عكس النماذج اللغوية.
  - **مجاني** ضمن حد الباقة المجانية.
  - **مفيش خطر إهمال مقطع**: بنبعت قائمة نصوص وبنستلم قائمة بنفس
    الترتيب. مع النموذج اللغوي بنطلب JSON فيه معرّفات، ووارد يهمل واحد.

وليه Claude يفضل الافتراضي؟
  - تعليمات المجال عندنا صفحة كاملة لكل مجال؛ DeepL بيسمح بـ 10
    تعليمات × 300 حرف بس، فبنبعتله نسخة مكثّفة.
  - Claude بيفهم الغموض المتعمّد في النص القانوني ويحافظ عليه.

اللي DeepL بيدعمه ومستخدمينه هنا:
  - `tag_handling="xml"` → وسوم التنسيق `<g1>` بتاعتنا بتتحافظ وبتتحرك
    مع الكلمات اللي تخصّها.
  - `context` → المقاطع المجاورة، و**محارفه مش محسوبة في الفاتورة**.
  - `custom_instructions` → نسخة مكثّفة من تعليمات المجال.
  - قاعدة مصطلحات → بننشئها من مصطلحاتنا ونعيد استخدامها.
"""
from __future__ import annotations

import hashlib
import logging

from app.core.config import settings
from app.tools.translator.engine import BatchResult, SegmentInput, Usage

logger = logging.getLogger(__name__)

# DeepL بيطلب صيغة إقليمية للإنجليزية والبرتغالية كلغة هدف
_TARGET_CODES = {
    "en": "EN-US",
    "pt": "PT-PT",
    "ar": "AR",
    "ru": "RU",
    "tr": "TR",
    "uk": "UK",
    "az": "AZ",
    "fr": "FR",
    "de": "DE",
    "es": "ES",
    "it": "IT",
    "zh": "ZH",
}
_SOURCE_CODES = {
    "en": "EN", "ar": "AR", "ru": "RU", "tr": "TR", "uk": "UK",
    "az": "AZ", "fr": "FR", "de": "DE", "es": "ES", "it": "IT",
    "zh": "ZH", "pt": "PT",
}

# تعليمات مكثّفة لكل مجال — الحد 300 حرف للتعليمة و10 تعليمات كحد أقصى.
# دي نسخة مختصرة من `prompts.py`، والاختصار مقصود مش إهمال.
_DOMAIN_INSTRUCTIONS: dict[str, list[str]] = {
    "legal": [
        "Translate legal text literally. Prefer a close rendering over an "
        "elegant one whenever the two conflict.",
        "Preserve deliberate vagueness. Do not resolve ambiguity, narrow a "
        "general term, or add qualifiers that are not in the source.",
        "Keep terminology identical throughout. Never vary the wording of a "
        "defined term for stylistic variety.",
        "Reproduce article, clause, annex and schedule numbers and all "
        "cross-references exactly as written.",
        "Use standard legal register: shall for obligations, may for "
        "permissions, shall not for prohibitions.",
    ],
    "medical": [
        "Use standard clinical terminology and anatomical nomenclature.",
        "Reproduce dosages, concentrations, frequencies and routes of "
        "administration exactly. An error here is a patient-safety error.",
        "Use the International Nonproprietary Name for drugs; keep brand "
        "names as written.",
        "Keep diagnostic codes (ICD, SNOMED) and lab reference ranges "
        "verbatim.",
    ],
    "scientific": [
        "Use established discipline terminology rather than literal wording.",
        "Reproduce units, symbols, equations, chemical formulae, taxonomic "
        "names and citation markers verbatim.",
        "Preserve hedging exactly: 'may indicate' must not become "
        "'indicates'. Overstating certainty is a factual error.",
    ],
    "technical": [
        "Keep product names, UI labels, menu paths, API names and code "
        "identifiers unchanged.",
        "Reproduce code snippets, file paths and configuration keys exactly.",
        "Use consistent terminology for repeated interface elements.",
    ],
    "general": [
        "Produce natural, fluent text that reads as if originally written in "
        "the target language.",
        "Preserve the register and tone of the source.",
    ],
}

# قواعد عامة بتتبعت مع أي مجال
_BASE_INSTRUCTIONS = [
    "Reproduce every digit, date, percentage, currency amount and code "
    "exactly. Never convert number systems or separators.",
    "A number written as 150.000 may mean one hundred fifty thousand. Copy "
    "it character for character; never reinterpret the separator.",
    "Translate only. Add no notes, explanations or bracketed remarks.",
]

_MAX_INSTRUCTIONS = 10
_MAX_INSTRUCTION_CHARS = 300

# لغات هدف رفضت `custom_instructions`. الـ API مابيعلنش عن القدرة دي
# لكل لغة، فبنكتشفها من رفض فعلي ونفتكرها لباقي الجلسة بدل ما ندفع
# رحلة فاشلة كل مرة.
_NO_CUSTOM_INSTRUCTIONS: set[str] = set()

# نفس الحكاية مع معالجة الوسوم — بعض اللغات ممكن ترفضها
_NO_TAG_HANDLING: set[str] = set()


def _map_source(lang: str) -> str | None:
    return _SOURCE_CODES.get(lang.split("-")[0].lower())


def _map_target(lang: str) -> str:
    code = lang.split("-")[0].lower()
    if code not in _TARGET_CODES:
        raise ValueError(f"DeepL مابيدعمش اللغة دي كهدف: {lang}")
    return _TARGET_CODES[code]


def _build_instructions(domain: str, style_notes: str) -> list[str]:
    """تجميع التعليمات مع احترام حدود DeepL."""
    items = list(_BASE_INSTRUCTIONS)
    items.extend(_DOMAIN_INSTRUCTIONS.get(domain, _DOMAIN_INSTRUCTIONS["general"]))

    if style_notes.strip():
        items.append(style_notes.strip())

    # القصّ عند الحد بدل ما DeepL يرفض الطلب كله
    trimmed = [item[:_MAX_INSTRUCTION_CHARS] for item in items]
    if len(trimmed) > _MAX_INSTRUCTIONS:
        logger.warning(
            "تعليمات DeepL أكتر من الحد (%d) — هتتقص لأول %d",
            len(trimmed),
            _MAX_INSTRUCTIONS,
        )
    return trimmed[:_MAX_INSTRUCTIONS]


class DeepLEngine:
    """محرّك DeepL. بيتبع نفس بروتوكول محرّك Claude."""

    name = "deepl"
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
    ) -> None:
        key = api_key or settings.deepl_api_key
        if not key:
            raise RuntimeError(
                "مفيش مفتاح DeepL. حط DEEPL_API_KEY في ملف .env — "
                "تقدر تجيب مفتاح مجاني من deepl.com/pro-api"
            )

        import deepl

        self.client = deepl.DeepLClient(key)
        self.model = model or f"deepl-{settings.deepl_model_type}"
        self.model_type = settings.deepl_model_type
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.domain = domain

        self.source_code = _map_source(source_lang)
        self.target_code = _map_target(target_lang)
        self.instructions = _build_instructions(domain, style_notes)
        self._glossary_terms = glossary or []
        self._glossary_id: str | None = None
        self._glossary_resolved = False

    # -- قاعدة المصطلحات ----------------------------------------------------
    def _glossary_name(self) -> str:
        """اسم حتمي مبني على المصطلحات نفسها.

        كده لو المصطلحات ماتغيّرتش بنعيد استخدام نفس القاعدة بدل ما
        ننشئ واحدة جديدة كل مرة وتتكدّس في الحساب.
        """
        payload = "\n".join(f"{s}\t{t}" for s, t in sorted(self._glossary_terms))
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]
        return f"tarjuman-{self.domain}-{self.source_lang}-{self.target_lang}-{digest}"

    def _resolve_glossary(self):
        """إنشاء قاعدة المصطلحات أو إعادة استخدام الموجودة."""
        if self._glossary_resolved:
            return self._glossary_id
        self._glossary_resolved = True

        if not self._glossary_terms or not self.source_code:
            return None

        name = self._glossary_name()
        try:
            for existing in self.client.list_glossaries():
                if existing.name == name:
                    self._glossary_id = existing.glossary_id
                    logger.info("استخدام قاعدة مصطلحات DeepL موجودة: %s", name)
                    return self._glossary_id

            entries = {source: target for source, target in self._glossary_terms}
            created = self.client.create_glossary(
                name,
                source_lang=self.source_code,
                target_lang=self.target_code.split("-")[0],
                entries=entries,
            )
            self._glossary_id = created.glossary_id
            logger.info("اتنشأت قاعدة مصطلحات DeepL: %s (%d مصطلح)", name, len(entries))
        except Exception as exc:  # noqa: BLE001
            # زوج اللغات ممكن مايدعمش المصطلحات — الترجمة تكمّل من غيرها
            logger.warning("قاعدة مصطلحات DeepL مش متاحة: %s", exc)
            self._glossary_id = None

        return self._glossary_id

    # -- التنفيذ مع التراجع عن الميزات غير المدعومة ------------------------
    def _translate_with_fallback(self, texts: list[str], options: dict):
        """نداء DeepL مع إسقاط أي ميزة اللغة الهدف مابتدعمهاش.

        DeepL مابيعلنش في `get_target_languages` أي لغة بتدعم
        `custom_instructions` أو `tag_handling` — بيرفض بس وقت الطلب.
        فبنجرّب بالكامل، ولو رفض بنشيل الميزة المرفوضة ونعيد، ونفتكر
        القرار لباقي الجلسة عشان مانكررش الرحلة الفاشلة.

        النتيجة: اللغة اللي مابتدعمش التعليمات بتترجم من غيرها بدل ما
        الملف كله يفشل.
        """
        feature_errors = [
            ("custom_instructions", _NO_CUSTOM_INSTRUCTIONS, "custom_instructions"),
            ("tag_handling", _NO_TAG_HANDLING, "tag_handling"),
        ]

        for _attempt in range(len(feature_errors) + 1):
            try:
                return self.client.translate_text(texts, **options)
            except Exception as exc:  # noqa: BLE001
                message = str(exc).lower()
                dropped = False
                for option_key, memo, marker in feature_errors:
                    if marker in message and option_key in options:
                        options.pop(option_key)
                        memo.add(self.target_code)
                        logger.warning(
                            "DeepL: %s مش مدعوم للغة %s — بنكمّل من غيره",
                            option_key,
                            self.target_code,
                        )
                        dropped = True
                        break
                if not dropped:
                    raise
        raise RuntimeError("DeepL رفض الطلب بعد إسقاط كل الميزات الاختيارية")

    # -- الترجمة ------------------------------------------------------------
    def translate(
        self,
        segments: list[SegmentInput],
        context_before: str = "",
        context_after: str = "",
    ) -> BatchResult:
        if not segments:
            return BatchResult()

        import deepl

        result = BatchResult()
        texts = [segment.source for segment in segments]

        # السياق مجاني في فاتورة DeepL، فبنبعته كامل من غير تردد
        context = " ".join(part for part in (context_before, context_after) if part)

        options: dict = {
            "target_lang": self.target_code,
            "preserve_formatting": True,
        }
        if self.target_code not in _NO_TAG_HANDLING:
            options["tag_handling"] = "xml"
        if self.target_code not in _NO_CUSTOM_INSTRUCTIONS:
            options["custom_instructions"] = self.instructions
        if self.source_code:
            options["source_lang"] = self.source_code
        if context:
            options["context"] = context

        model_type = {
            "quality_optimized": deepl.ModelType.QUALITY_OPTIMIZED,
            "prefer_quality_optimized": deepl.ModelType.PREFER_QUALITY_OPTIMIZED,
            "latency_optimized": deepl.ModelType.LATENCY_OPTIMIZED,
        }.get(self.model_type)
        if model_type is not None:
            options["model_type"] = model_type

        glossary_id = self._resolve_glossary()
        if glossary_id:
            options["glossary"] = glossary_id

        try:
            responses = self._translate_with_fallback(texts, options)
        except Exception as exc:  # noqa: BLE001
            logger.exception("فشل نداء DeepL")
            return BatchResult(
                missing=[s.id for s in segments],
                warnings=[f"DeepL: {type(exc).__name__}: {exc}"],
            )

        if not isinstance(responses, list):
            responses = [responses]

        # الردود بترجع بنفس ترتيب النصوص المرسلة — مفيش معرّفات
        # نطابق بيها، وده أأمن من طلب JSON من نموذج لغوي.
        if len(responses) != len(segments):
            result.warnings.append(
                f"DeepL رجّع {len(responses)} نص مقابل {len(segments)} مقطع"
            )

        for segment, response in zip(segments, responses):
            result.translations[segment.id] = response.text

        result.missing = [s.id for s in segments[len(responses):]]

        # DeepL بيحاسب بحروف المصدر؛ محارف السياق مش محسوبة
        billed_chars = sum(len(text) for text in texts)
        result.usage = Usage(
            input_tokens=billed_chars,
            output_tokens=0,
            calls=1,
            cost_usd=round(
                billed_chars * settings.deepl_usd_per_million_chars / 1_000_000, 6
            ),
        )
        return result

    # -- تشخيص --------------------------------------------------------------
    def check_usage(self) -> dict:
        """استهلاك الحساب — بيبيّن كام فاضل من الباقة المجانية."""
        usage = self.client.get_usage()
        info: dict = {"any_limit_reached": usage.any_limit_reached}
        if usage.character is not None:
            info["characters_used"] = usage.character.count
            info["characters_limit"] = usage.character.limit
            if usage.character.limit:
                info["percent_used"] = round(
                    100 * usage.character.count / usage.character.limit, 1
                )
        return info
