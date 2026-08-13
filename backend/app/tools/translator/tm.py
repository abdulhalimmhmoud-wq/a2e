"""ذاكرة الترجمة + قاعدة المصطلحات + محرّك الانتشار.

ده الجزء اللي بيحوّل الأداة من "مترجم" لـ "نظام ترجمة احترافي":

- **ذاكرة الترجمة (TM)**: كل مقطع معتمَد بيتخزّن. أي مشروع جديد فيه
  نفس النص بيتعبّى تلقائيًا وببلاش.
- **قاعدة المصطلحات (Termbase)**: ترجمات ملزمة بتتحقن في تعليمات
  النموذج وبتتفحص بعد الترجمة.
- **محرّك الانتشار**: لما المراجع يعدّل مقطع، التعديل بيتطبّق على كل
  المواضع المشابهة في الملف — بموافقته.

ليه الانتشار بموافقة مش تلقائي بالكامل؟ لأن نفس الكلمة ممكن يبقى ليها
ترجمة مختلفة حسب السياق. المطابقة **التامة** بتتحدّث تلقائيًا (نفس
النص حرفيًا = نفس الترجمة)، لكن التعديل على مستوى المصطلح بيتعرض على
المراجع بكل مواضعه قبل التطبيق. ده نفس منطق Trados و memoQ.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GlossaryTerm, Segment, TMEntry
from app.tools.translator.formats.base import strip_tags, text_hash


# ---------------------------------------------------------------------------
# ذاكرة الترجمة
# ---------------------------------------------------------------------------
@dataclass
class TMMatch:
    source_text: str
    target_text: str
    score: int          # 100 = تطابق تام
    entry_id: str = ""


def _normalize(text: str) -> str:
    """تطبيع للمقارنة: بدون وسوم، مسافات موحّدة، بدون تشكيل حدّي."""
    plain = strip_tags(text)
    return re.sub(r"\s+", " ", plain).strip()


def lookup_exact(
    db: Session,
    source_text: str,
    source_lang: str = "ar",
    target_lang: str = "en",
    domain: str = "general",
) -> TMMatch | None:
    """مطابقة تامة — بتتعبّى تلقائيًا وبتوفّر تكلفة كاملة."""
    digest = text_hash(source_text)

    # نفضّل نفس المجال، وبعدين أي مجال تاني
    for domain_filter in (domain, None):
        query = select(TMEntry).where(
            TMEntry.source_hash == digest,
            TMEntry.source_lang == source_lang,
            TMEntry.target_lang == target_lang,
        )
        if domain_filter is not None:
            query = query.where(TMEntry.domain == domain_filter)

        entry = db.execute(query.limit(1)).scalar_one_or_none()
        if entry:
            return TMMatch(
                source_text=entry.source_text,
                target_text=entry.target_text,
                score=100,
                entry_id=entry.id,
            )
    return None


def lookup_exact_many(
    db: Session,
    texts: list[str],
    source_lang: str = "ar",
    target_lang: str = "en",
    domain: str = "general",
) -> dict[str, TMMatch]:
    """بحث تام لمجموعة نصوص دفعة واحدة.

    النسخة المفردة بتعمل استعلام لكل مقطع — يعني 1500 استعلام لملف
    متوسط. النسخة دي بتعمل استعلامين مهما كان عدد المقاطع.

    بيرجّع: {بصمة النص: المطابقة}
    """
    if not texts:
        return {}

    digests = {text_hash(t) for t in texts}
    found: dict[str, TMMatch] = {}

    # نفس المجال له الأولوية، وبعدين أي مجال تاني للي مالقيناهوش
    for domain_filter in (domain, None):
        missing = digests - set(found)
        if not missing:
            break

        query = select(TMEntry).where(
            TMEntry.source_hash.in_(missing),
            TMEntry.source_lang == source_lang,
            TMEntry.target_lang == target_lang,
        )
        if domain_filter is not None:
            query = query.where(TMEntry.domain == domain_filter)

        for entry in db.execute(query).scalars():
            found.setdefault(
                entry.source_hash,
                TMMatch(
                    source_text=entry.source_text,
                    target_text=entry.target_text,
                    score=100,
                    entry_id=entry.id,
                ),
            )

    return found


def lookup_fuzzy(
    db: Session,
    source_text: str,
    source_lang: str = "ar",
    target_lang: str = "en",
    domain: str = "general",
    threshold: int = 75,
    limit: int = 5,
    max_candidates: int = 800,
) -> list[TMMatch]:
    """مطابقات تقريبية — بتتعرض كاقتراحات للمراجع مش بتتطبّق تلقائيًا.

    مبنية على تحسينين، من غيرهم العملية بتاخد عشرات المللي ثانية لكل
    مقطع وبتزيد خطيًا مع كبر الذاكرة:

    1. **الترشيح بالطول في SQL** — نصّان طول أحدهما ضعف الآخر مستحيل
       يتطابقوا 75%، فمفيش داعي نحمّلهم أصلًا. الفهرس على الطول
       بيخلّي الترشيح ده شبه مجاني.

    2. **المقارنة على مراحل** — `real_quick_ratio` و`quick_ratio` حدّان
       أعلى رخيصان للنسبة الحقيقية. لو الحد الأعلى تحت العتبة، النسبة
       الحقيقية أكيد تحتها، فبنستغنى عن الحساب الغالي.
    """
    normalized = _normalize(source_text)
    length = len(normalized)
    if length < 8:
        return []

    # نصّان بنسبة تشابه ≥ threshold لازم يكون طولهما متقارب
    ratio = threshold / 100
    low, high = int(length * ratio), int(length / ratio) + 1

    # الترتيب بالأقرب طولًا مهم مش تجميلي: مع ذاكرة كبيرة، الحد الأقصى
    # للمرشحين ممكن يقطع قبل المطابقة الصح لو المرشحين جايين بترتيب
    # عشوائي. كل ما الطول أقرب، كل ما احتمال التطابق العالي أكبر.
    candidates = db.execute(
        select(TMEntry)
        .where(
            TMEntry.source_lang == source_lang,
            TMEntry.target_lang == target_lang,
            TMEntry.domain == domain,
            TMEntry.source_length.between(low, high),
        )
        .order_by(func.abs(TMEntry.source_length - length))
        .limit(max_candidates)
    ).scalars().all()

    # النص المطلوب يتحط في `b` مش `a`: SequenceMatcher بيبني فهرسًا
    # داخليًا لـ `b` مرة واحدة ويعيد استخدامه، فبنثبّته ونغيّر `a` بس.
    matcher = SequenceMatcher(None, "", normalized, autojunk=False)
    matches: list[TMMatch] = []

    for entry in candidates:
        candidate = _normalize(entry.source_text)
        matcher.set_seq1(candidate)

        # الحدّان الرخيصان الأول — بيستبعدوا الأغلبية بتكلفة ضئيلة
        if matcher.real_quick_ratio() < ratio or matcher.quick_ratio() < ratio:
            continue

        score = int(matcher.ratio() * 100)
        if score >= threshold:
            matches.append(
                TMMatch(
                    source_text=entry.source_text,
                    target_text=entry.target_text,
                    score=score,
                    entry_id=entry.id,
                )
            )

    matches.sort(key=lambda m: m.score, reverse=True)
    return matches[:limit]


def store(
    db: Session,
    source_text: str,
    target_text: str,
    source_lang: str = "ar",
    target_lang: str = "en",
    domain: str = "general",
    project_id: str | None = None,
) -> None:
    """حفظ زوج معتمَد في الذاكرة (أو تحديثه لو موجود)."""
    if not source_text.strip() or not target_text.strip():
        return

    digest = text_hash(source_text)
    existing = db.execute(
        select(TMEntry).where(
            TMEntry.source_hash == digest,
            TMEntry.source_lang == source_lang,
            TMEntry.target_lang == target_lang,
            TMEntry.domain == domain,
        )
    ).scalar_one_or_none()

    if existing:
        existing.target_text = target_text
        existing.usage_count += 1
        # لازم يتحدّث كمان على المدخلات القديمة، وإلا هتفضل بطول 0
        # وتختفي من نتائج البحث التقريبي للأبد
        existing.source_length = len(_normalize(source_text))
    else:
        db.add(
            TMEntry(
                source_hash=digest,
                source_text=source_text,
                target_text=target_text,
                # الطول المطبَّع بيتخزّن عشان الترشيح في SQL
                source_length=len(_normalize(source_text)),
                source_lang=source_lang,
                target_lang=target_lang,
                domain=domain,
                origin_project_id=project_id,
            )
        )


# ---------------------------------------------------------------------------
# قاعدة المصطلحات
# ---------------------------------------------------------------------------
def load_glossary(
    db: Session,
    domain: str = "general",
    project_id: str | None = None,
    limit: int = 300,
) -> list[tuple[str, str]]:
    """مصطلحات المشروع + مصطلحات المجال العامة."""
    query = select(GlossaryTerm).where(
        GlossaryTerm.is_forbidden.is_(False),
        GlossaryTerm.domain.in_([domain, "general"]),
    )
    terms = db.execute(query.limit(limit)).scalars().all()

    scoped = [
        t for t in terms if t.project_id is None or t.project_id == project_id
    ]
    # الأطول الأول: عشان "عقد إذعان" تتطابق قبل "عقد"
    scoped.sort(key=lambda t: len(t.source_term), reverse=True)
    return [(t.source_term, t.target_term) for t in scoped]


def check_glossary(
    source: str, target: str, glossary: list[tuple[str, str]]
) -> list[str]:
    """المصطلحات اللي موجودة في المصدر ولم تُستخدم ترجمتها المعتمدة."""
    plain_source = strip_tags(source)
    plain_target = strip_tags(target).lower()

    violations: list[str] = []
    for source_term, target_term in glossary:
        if source_term and source_term in plain_source:
            if target_term.lower() not in plain_target:
                violations.append(f"{source_term} → {target_term}")
    return violations


# ---------------------------------------------------------------------------
# محرّك الانتشار
# ---------------------------------------------------------------------------
@dataclass
class PropagationTarget:
    segment_id: str
    location: str
    source_text: str
    current_target: str
    proposed_target: str
    match_type: str      # exact | term
    score: int = 100


@dataclass
class PropagationPlan:
    auto: list[PropagationTarget] = field(default_factory=list)
    needs_review: list[PropagationTarget] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.auto) + len(self.needs_review)


def plan_propagation(
    db: Session,
    edited: Segment,
    new_target: str,
    scope_file_id: str | None = None,
) -> PropagationPlan:
    """تحديد المواضع اللي المفروض يتطبّق عليها التعديل.

    مستويين:
      1. **مطابقة تامة** — مقاطع نصها المصدر مطابق حرفيًا → تلقائي.
      2. **مستوى المصطلح** — لو التعديل غيّر كلمة/عبارة، بندوّر على
         المقاطع اللي فيها نفس التغيير المحتمل → محتاجة موافقة.
    """
    plan = PropagationPlan()
    file_id = scope_file_id or edited.file_id

    # ---- 1) المطابقة التامة ----
    siblings = db.execute(
        select(Segment).where(
            Segment.file_id == file_id,
            Segment.source_hash == edited.source_hash,
            Segment.id != edited.id,
        )
    ).scalars().all()

    for segment in siblings:
        if segment.is_locked:
            continue
        if segment.target_text == new_target:
            continue
        target = PropagationTarget(
            segment_id=segment.id,
            location=segment.location,
            source_text=segment.source_text,
            current_target=segment.target_text,
            proposed_target=new_target,
            match_type="exact",
            score=100,
        )
        # المقاطع اللي حرّرها إنسان قبل كده مابتتغيّرش من غير موافقة
        if segment.edited_by_human:
            plan.needs_review.append(target)
        else:
            plan.auto.append(target)

    # ---- 2) مستوى المصطلح ----
    replacement = _infer_term_change(edited.target_text, new_target)
    if replacement:
        old_term, fresh_term = replacement
        candidates = db.execute(
            select(Segment).where(
                Segment.file_id == file_id,
                Segment.id != edited.id,
                Segment.source_hash != edited.source_hash,
            )
        ).scalars().all()

        pattern = re.compile(rf"\b{re.escape(old_term)}\b", re.IGNORECASE)
        for segment in candidates:
            if segment.is_locked or not segment.target_text:
                continue
            if not pattern.search(strip_tags(segment.target_text)):
                continue
            plan.needs_review.append(
                PropagationTarget(
                    segment_id=segment.id,
                    location=segment.location,
                    source_text=segment.source_text,
                    current_target=segment.target_text,
                    proposed_target=pattern.sub(fresh_term, segment.target_text),
                    match_type="term",
                    score=0,
                )
            )

    return plan


def _infer_term_change(before: str, after: str) -> tuple[str, str] | None:
    """استنتاج تغيير المصطلح من الفرق بين النص قبل وبعد التعديل.

    بنكتفي بالحالة الواضحة: استبدال متّصل واحد. لو التعديل كبير أو
    متفرّق، بنرجع None — أفضل من اقتراح انتشار غلط على المستند كله.
    """
    if not before.strip() or not after.strip():
        return None

    before_words = strip_tags(before).split()
    after_words = strip_tags(after).split()

    matcher = SequenceMatcher(None, before_words, after_words)
    replacements = [
        op for op in matcher.get_opcodes() if op[0] == "replace"
    ]
    if len(replacements) != 1:
        return None

    _, i1, i2, j1, j2 = replacements[0]
    old_term = " ".join(before_words[i1:i2]).strip(" .,;:")
    new_term = " ".join(after_words[j1:j2]).strip(" .,;:")

    # عبارة قصيرة ومعقولة فقط
    if not old_term or not new_term:
        return None
    if len(old_term) < 3 or i2 - i1 > 4:
        return None
    if old_term.lower() == new_term.lower():
        return None

    return old_term, new_term


def apply_propagation(
    db: Session, targets: list[PropagationTarget], origin: str = "propagated"
) -> int:
    """تنفيذ الانتشار على المقاطع المحدَّدة."""
    applied = 0
    for target in targets:
        segment = db.get(Segment, target.segment_id)
        if segment is None or segment.is_locked:
            continue
        segment.target_text = target.proposed_target
        segment.origin = origin
        if segment.status == "draft":
            segment.status = "translated"
        applied += 1
    return applied
