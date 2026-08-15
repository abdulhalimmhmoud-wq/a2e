"""مصطلحات جاهزة للمجال الشرعي.

المجال الشرعي مختلف عن باقي المجالات في نقطة واحدة: مصطلحاته مستقرة
من قرون ومتفق عليها في الكتابة الأكاديمية الإنجليزية، فمافيش سبب
يخلّي كل مستخدم يدخّلها من الأول بإيده.

باقي المجالات مصطلحاتها بتختلف من جهة للتانية (كل مكتب محاماة له
صياغته)، فسايبينها فاضية عمدًا — المستخدم يستخرجها من ملفاته هو
بشاشة المصطلحات.

المصطلحات دي بتتزرع مرة واحدة، والمستخدم يقدر يعدّلها أو يمسحها زي
أي مصطلح تاني.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import GlossaryTerm

# (المصطلح، الترجمة، ملاحظة للمراجع)
RELIGIOUS_TERMS: list[tuple[str, str, str]] = [
    # ---- العبادات ----
    ("الزكاة", "zakāh", "لا تُترجم إلى charity — لها نصاب ومصارف محددة"),
    ("الصلاة", "ṣalāh", ""),
    ("الحج", "ḥajj", ""),
    ("العمرة", "ʿumrah", ""),
    ("الصوم", "ṣawm", ""),
    ("الوضوء", "wuḍūʾ", ""),
    ("الطهارة", "ṭahārah", ""),

    # ---- الأحكام التكليفية: درجات لا مترادفات ----
    ("فرض", "farḍ (obligatory)", "درجة إلزام — غير المندوب"),
    ("واجب", "wājib (obligatory)", ""),
    ("مندوب", "mandūb (recommended)", "مستحب لا واجب"),
    ("مباح", "mubāḥ (permissible)", ""),
    ("مكروه", "makrūh (discouraged)", "ليس محرَّمًا"),
    ("حرام", "ḥarām (prohibited)", ""),

    # ---- المعاملات ----
    ("الربا", "ribā", "لا تُترجم إلى interest — المعنى الشرعي أوسع"),
    ("المرابحة", "murābaḥah", ""),
    ("المضاربة", "muḍārabah", ""),
    ("المشاركة", "mushārakah", ""),
    ("الإجارة", "ijārah", ""),
    ("السلم", "salam", "بيع آجل التسليم معجّل الثمن"),
    ("الاستصناع", "istiṣnāʿ", ""),
    ("الصكوك", "ṣukūk", ""),
    ("التكافل", "takāful", ""),
    ("الغرر", "gharar", "الجهالة المفسدة للعقد"),
    ("الوقف", "waqf", ""),
    ("الرهن", "rahn", ""),
    ("الكفالة", "kafālah", ""),
    ("الحوالة", "ḥawālah", ""),

    # ---- الأحوال الشخصية ----
    ("الطلاق", "ṭalāq", ""),
    ("الخلع", "khulʿ", "فسخ بطلب الزوجة مقابل عوض"),
    ("العدة", "ʿidda", ""),
    ("المهر", "mahr", "لا تُترجم إلى dowry — الاتجاه معكوس"),
    ("النفقة", "nafaqah", ""),
    ("الحضانة", "ḥaḍānah", ""),
    ("الميراث", "mīrāth", ""),
    ("الوصية", "waṣiyyah", ""),

    # ---- أصول الفقه ----
    ("الفقه", "fiqh", ""),
    ("الشريعة", "sharīʿah", ""),
    ("الاجتهاد", "ijtihād", ""),
    ("القياس", "qiyās", ""),
    ("الإجماع", "ijmāʿ", ""),
    ("المصلحة", "maṣlaḥah", ""),
    ("الفتوى", "fatwā", ""),
    ("المذهب", "madhhab", ""),
    ("السنة", "sunnah", ""),
    ("مقاصد الشريعة", "maqāṣid al-sharīʿah", ""),

    # ---- علوم الحديث: درجات لا مترادفات ----
    ("صحيح", "ṣaḥīḥ (sound)", "درجة حديث"),
    ("حسن", "ḥasan (good)", "درجة حديث أقل من الصحيح"),
    ("ضعيف", "ḍaʿīf (weak)", "درجة حديث"),
    ("متواتر", "mutawātir", ""),
    ("آحاد", "āḥād", ""),
    ("الإسناد", "isnād", ""),
    ("المتن", "matn", ""),

    # ---- ألفاظ متكررة ----
    ("صلى الله عليه وسلم", "peace and blessings be upon him", ""),
    ("رضي الله عنه", "may Allah be pleased with him", ""),
    ("رضي الله عنها", "may Allah be pleased with her", ""),
    ("سبحانه وتعالى", "glorified and exalted be He", ""),
]


def seed_religious_terms(db: Session, force: bool = False) -> int:
    """زرع مصطلحات المجال الشرعي لو القاعدة لسه فاضية منها.

    مابنكتبش فوق أي تعديل للمستخدم: لو المصطلح موجود بيتساب زي ما هو.
    """
    if not force:
        existing = db.execute(
            select(func.count())
            .select_from(GlossaryTerm)
            .where(GlossaryTerm.domain == "religious")
        ).scalar_one()
        if existing:
            return 0

    present = {
        term.source_term
        for term in db.execute(
            select(GlossaryTerm).where(GlossaryTerm.domain == "religious")
        ).scalars()
    }

    added = 0
    for source_term, target_term, note in RELIGIOUS_TERMS:
        if source_term in present:
            continue
        db.add(
            GlossaryTerm(
                source_term=source_term,
                target_term=target_term,
                domain="religious",
                notes=note,
                project_id=None,
            )
        )
        added += 1

    if added:
        db.commit()
    return added
