/**
 * لغة واجهة الأداة نفسها — عربي أو إنجليزي.
 *
 * ملاحظة مهمة: دي لغة **الواجهة**، مش لغة الترجمة. اتجاه أعمدة شاشة
 * المراجعة بيفضل تابع للغتَي المشروع، فلو بتترجم عربي→إنجليزي
 * والواجهة إنجليزي، عمود المصدر يفضل RTL.
 *
 * كل نص مكتوب باللغتين جنب بعض في نفس السطر عشان النقص يبان فورًا.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export type UiLang = "ar" | "en";

const STORAGE_KEY = "tarjuman.ui-lang";

type Entry = { ar: string; en: string };

const S = {
  // ------------------------------------------------------------ عام
  "app.name": { ar: "ترجمان الأحبة", en: "Tarjuman al-Ahibba" },
  "app.brandA": { ar: "ترجمان", en: "Tarjuman" },
  "app.brandB": { ar: "الأحبة", en: "al-Ahibba" },
  "nav.tools": { ar: "الأدوات", en: "Tools" },
  "nav.translator": { ar: "المترجم", en: "Translator" },
  "nav.glossary": { ar: "المصطلحات", en: "Glossary" },
  "lang.switch": { ar: "English", en: "العربية" },
  "lang.switchTitle": {
    ar: "Switch interface to English",
    en: "تحويل الواجهة للعربية",
  },
  "common.loading": { ar: "جارٍ التحميل…", en: "Loading…" },
  "common.cancel": { ar: "إلغاء", en: "Cancel" },
  "common.close": { ar: "إغلاق", en: "Close" },
  "common.delete": { ar: "حذف", en: "Delete" },
  "common.create": { ar: "إنشاء", en: "Create" },
  "common.add": { ar: "إضافة", en: "Add" },
  "common.settings": { ar: "إعدادات", en: "Settings" },
  "common.optional": { ar: "اختياري", en: "optional" },
  "common.words": { ar: "كلمة", en: "words" },
  "common.pages": { ar: "صفحة", en: "pages" },
  "common.segments": { ar: "مقطع", en: "segments" },
  "common.files": { ar: "ملف", en: "files" },
  "common.perPage": { ar: "صفحة", en: "page" },

  // ------------------------------------------------------------ الأدوات
  "hub.title": { ar: "الأدوات", en: "Tools" },
  "hub.subtitle": {
    ar: "منصّة أدوات محلية — كل شيء يعمل على جهازك",
    en: "A local tool suite — everything runs on your machine",
  },
  "hub.available": { ar: "متاحة", en: "Available" },
  "hub.noKeyTitle": { ar: "مفتاح Anthropic غير مضبوط.", en: "No Anthropic key set." },
  "hub.noKeyBody": {
    ar: "الترجمة الحقيقية لن تعمل حتى تضع ANTHROPIC_API_KEY في ملف .env في جذر المشروع. التشغيل التجريبي بدون تكلفة متاح من صفحة المشروع.",
    en: "Real translation will not run until you put ANTHROPIC_API_KEY in the .env file at the project root. The free dry run is available from the project page.",
  },
  "hub.newToolTitle": { ar: "أداة جديدة", en: "A new tool" },
  "hub.newToolBody": {
    ar: "المنصّة مبنية كسجلّ أدوات — إضافة أداة جديدة تحتاج ملف تعريف ومجلّد فقط، دون المساس بالأساس.",
    en: "The platform is built as a tool registry — adding a tool takes a manifest and a folder, without touching the core.",
  },

  // ------------------------------------------------------------ المشاريع
  "projects.title": { ar: "المترجم", en: "Translator" },
  "projects.subtitle": {
    ar: "ترجمة المستندات مع الحفاظ الكامل على التنسيق",
    en: "Document translation with formatting preserved exactly",
  },
  "projects.new": { ar: "مشروع جديد", en: "New project" },
  "projects.name": { ar: "اسم المشروع", en: "Project name" },
  "projects.namePlaceholder": {
    ar: "مثال: عقود الربع الثالث",
    en: "e.g. Q3 contracts",
  },
  "projects.sourceLang": { ar: "لغة المصدر", en: "Source language" },
  "projects.targetLang": { ar: "لغة الهدف", en: "Target language" },
  "projects.swap": { ar: "عكس اتجاه الترجمة", en: "Swap translation direction" },
  "projects.domain": { ar: "المجال", en: "Domain" },
  "projects.model": { ar: "الموديل", en: "Model" },
  "projects.engine": { ar: "محرّك الترجمة", en: "Translation engine" },
  "projects.noEngineKey": { ar: "(مفيش مفتاح)", en: "(no key)" },
  "projects.needsKey": {
    ar: "محتاج مفتاح {engine} في ملف .env",
    en: "Needs a {engine} key in the .env file",
  },
  "projects.styleNotes": {
    ar: "ملاحظات أسلوبية (اختياري)",
    en: "Style notes (optional)",
  },
  "projects.styleNotesPlaceholder": {
    ar: "مثال: استخدم صيغة المخاطب الرسمية، واكتب أسماء الشركات كما هي دون ترجمة",
    en: "e.g. Use formal register, and keep company names untranslated",
  },
  "projects.empty": {
    ar: "لا توجد مشاريع بعد. ابدأ بإنشاء مشروع جديد.",
    en: "No projects yet. Start by creating one.",
  },
  "projects.perMillion": {
    ar: "لكل مليون توكن",
    en: "per million tokens",
  },

  // ------------------------------------------------------------ المشروع
  "project.upload": { ar: "رفع ملفات", en: "Upload files" },
  "project.uploading": { ar: "جارٍ الرفع…", en: "Uploading…" },
  "project.delete": { ar: "حذف المشروع", en: "Delete project" },
  "project.settingsHint": {
    ar: "التغييرات بتأثّر على الترجمات الجديدة بس — المقاطع المترجمة بالفعل مابتتغيّرش.",
    en: "Changes affect new translations only — segments already translated are untouched.",
  },
  "project.noKeyNotice": {
    ar: "مفتاح Anthropic غير مضبوط — زر «ترجمة» معطّل. يمكنك تجربة الخط كاملًا بزر «تشغيل تجريبي» بدون أي تكلفة.",
    en: "No Anthropic key — the Translate button is disabled. You can exercise the whole pipeline with Dry run at no cost.",
  },
  "project.size": { ar: "الحجم", en: "Size" },
  "project.memoryCoverage": { ar: "تغطية الذاكرة", en: "Memory coverage" },
  "project.memoryCoverageHint": {
    ar: "مقاطع مترجمة سابقًا — بدون تكلفة",
    en: "Already-translated segments — free",
  },
  "project.promo": { ar: "(عرض)", en: "(promo)" },
  "project.deferred": { ar: "مؤجَّل", en: "deferred" },
  "project.saving": { ar: "وفر", en: "saves" },
  "project.actualCost": { ar: "التكلفة الفعلية", en: "Actual cost" },
  "project.perPageShort": { ar: "للصفحة", en: "per page" },
  "project.savedFromMemory": {
    ar: "وفّرت {n} مقطع من الذاكرة",
    en: "Saved {n} segments from memory",
  },
  "project.savedFromCache": {
    ar: "وفّرت ${n} من التخزين المؤقت",
    en: "Saved ${n} from prompt caching",
  },
  "project.emptyFiles": {
    ar: "لا توجد ملفات. ارفع ملف Word أو Excel أو PowerPoint أو PDF للبدء.",
    en: "No files yet. Upload a Word, Excel, PowerPoint or PDF file to start.",
  },
  "project.colFile": { ar: "الملف", en: "File" },
  "project.colFormat": { ar: "الصيغة", en: "Format" },
  "project.colSize": { ar: "الحجم", en: "Size" },
  "project.colProgress": { ar: "التقدّم", en: "Progress" },
  "project.colActions": { ar: "الإجراءات", en: "Actions" },
  "project.approvedOf": { ar: "معتمد", en: "approved" },
  "project.alerts": { ar: "تنبيه", en: "flagged" },
  "project.extract": { ar: "استخراج", en: "Extract" },
  "project.translate": { ar: "ترجمة", en: "Translate" },
  "project.deferredRun": { ar: "تنفيذ مؤجَّل", en: "Deferred run" },
  "project.deferredTitle": {
    ar: "تنفيذ غير فوري (قد يستغرق حتى ساعة أو أكثر). الوفر المتوقع لهذا الحجم: {pct}%",
    en: "Not immediate (can take an hour or more). Expected saving at this size: {pct}%",
  },
  "project.deferredTitlePlain": {
    ar: "تنفيذ غير فوري — أرخص، لكن النتيجة لا تصل فورًا",
    en: "Not immediate — cheaper, but the result does not arrive right away",
  },
  "project.dryRun": { ar: "تشغيل تجريبي", en: "Dry run" },
  "project.dryRunTitle": {
    ar: "يشغّل الخط كاملًا بترجمة وهمية — بدون تكلفة",
    en: "Runs the whole pipeline with placeholder text — no cost",
  },
  "project.review": { ar: "مراجعة", en: "Review" },
  "project.download": { ar: "تنزيل", en: "Download" },
  "project.stop": { ar: "إيقاف", en: "Stop" },
  "project.stopTitle": {
    ar: "بيوقف الدفعات اللي لسه ماابتدتش — المترجَم بيفضل محفوظ",
    en: "Stops batches that have not started — translated work is kept",
  },
  "project.engineTitle": { ar: "المحرّك: {engine}", en: "Engine: {engine}" },
  "project.confirmDeleteFile": {
    ar: "حذف «{name}» ومقاطعه وترجمته نهائيًا؟\nذاكرة الترجمة مش هتتأثر — المقاطع المعتمَدة بتفضل محفوظة فيها.",
    en: "Permanently delete “{name}” with its segments and translation?\nTranslation memory is unaffected — approved segments stay in it.",
  },
  "project.confirmDeleteProject": {
    ar: "حذف مشروع «{name}» نهائيًا؟\n\nهيتمسح: {files} ملف · كل المقاطع والترجمات · الملفات المرفوعة والمصدَّرة من على القرص.\n\nمش هيتمسح: ذاكرة الترجمة وقاعدة المصطلحات (بتفضل متاحة للمشاريع الجاية).\n\nالعملية دي مالهاش تراجع.",
    en: "Permanently delete project “{name}”?\n\nWill be removed: {files} file(s) · all segments and translations · uploaded and exported files on disk.\n\nWill be kept: translation memory and glossary (still available to future projects).\n\nThis cannot be undone.",
  },

  // ------------------------------------------------------------ المراجعة
  "review.title": { ar: "مراجعة", en: "Review" },
  "review.back": { ar: "رجوع للمشروع", en: "Back to project" },
  "review.approveAll": { ar: "اعتماد الكل", en: "Approve all" },
  "review.export": { ar: "تصدير الملف", en: "Export file" },
  "review.allStatuses": { ar: "كل الحالات", en: "All statuses" },
  "review.flaggedOnly": { ar: "التنبيهات فقط", en: "Flagged only" },
  "review.searchPlaceholder": {
    ar: "بحث في المصدر أو الترجمة…",
    en: "Search source or translation…",
  },
  "review.showing": {
    ar: "عرض {shown} من {total}",
    en: "Showing {shown} of {total}",
  },
  "review.shortcut": {
    ar: "للاعتماد والانتقال",
    en: "to approve and move on",
  },
  "review.colSource": { ar: "المصدر", en: "Source" },
  "review.colTarget": { ar: "الترجمة", en: "Translation" },
  "review.colStatus": { ar: "الحالة", en: "Status" },
  "review.notTranslatable": {
    ar: "غير قابل للترجمة — يمرّ كما هو",
    en: "Not translatable — passes through unchanged",
  },
  "review.suggestionsTitle": {
    ar: "من ذاكرة الترجمة — اضغط للاستخدام",
    en: "From translation memory — click to use",
  },
  "review.similarSource": { ar: "المصدر المشابه", en: "Similar source" },
  "review.loadMore": {
    ar: "تحميل المزيد ({n} متبقٍ)",
    en: "Load more ({n} remaining)",
  },
  "review.autoPropagated": {
    ar: "طُبّق التعديل تلقائيًا على {n} مقطع مطابق",
    en: "Applied automatically to {n} identical segments",
  },
  "review.propagated": {
    ar: "طُبّق التعديل على {n} مقطع",
    en: "Applied to {n} segments",
  },
  "review.approvedToast": {
    ar: "اعتُمد {n} مقطع وحُفظ في ذاكرة الترجمة",
    en: "Approved {n} segments and saved them to translation memory",
  },

  // ------------------------------------------------------------ الانتشار
  "prop.title": {
    ar: "تطبيق التعديل على مواضع أخرى",
    en: "Apply the edit elsewhere",
  },
  "prop.autoApplied": {
    ar: "طُبّق تلقائيًا على {n} مقطع مطابق تمامًا. ",
    en: "Applied automatically to {n} exactly matching segments. ",
  },
  "prop.needsApproval": {
    ar: "المواضع التالية تحتاج موافقتك لأن السياق قد يختلف.",
    en: "The places below need your approval because the context may differ.",
  },
  "prop.exactMatch": { ar: "مطابقة تامة", en: "Exact match" },
  "prop.exactMatchHint": {
    ar: "نفس النص المصدر، لكن مُعدَّل يدويًا من قبل",
    en: "Same source text, but edited by hand earlier",
  },
  "prop.termLevel": { ar: "على مستوى المصطلح", en: "Term level" },
  "prop.termLevelHint": {
    ar: "المصطلح نفسه يظهر في مقاطع أخرى — راجع كل موضع",
    en: "The same term appears elsewhere — review each place",
  },
  "prop.none": {
    ar: "لا توجد مواضع أخرى تحتاج مراجعة.",
    en: "No other places need review.",
  },
  "prop.apply": { ar: "تطبيق على {n} موضع", en: "Apply to {n} place(s)" },
  "prop.skip": { ar: "تخطّي", en: "Skip" },
  "prop.selectAll": { ar: "تحديد الكل", en: "Select all" },
  "prop.selectNone": { ar: "إلغاء التحديد", en: "Clear selection" },

  // ------------------------------------------------------------ المصطلحات
  "glossary.title": { ar: "قاعدة المصطلحات", en: "Glossary" },
  "glossary.subtitle": {
    ar: "ترجمات ملزمة تُحقن في تعليمات النموذج، وتُفحص بعد الترجمة تلقائيًا",
    en: "Binding renderings injected into the model instructions and checked automatically after translation",
  },
  "glossary.source": { ar: "المصطلح", en: "Term" },
  "glossary.target": { ar: "الترجمة", en: "Rendering" },
  "glossary.domain": { ar: "المجال", en: "Domain" },
  "glossary.sourcePlaceholder": {
    ar: "عقد إذعان",
    en: "contract of adhesion",
  },
  "glossary.targetPlaceholder": {
    ar: "Contract of Adhesion",
    en: "عقد إذعان",
  },
  "glossary.addOne": { ar: "إضافة مصطلح", en: "Add a term" },
  "glossary.bulkTitle": { ar: "إضافة دفعة واحدة", en: "Add in bulk" },
  "glossary.fromMemory": { ar: "من ذاكرة الترجمة", en: "From translation memory" },
  "glossary.fromMemoryHint": {
    ar: "الأزواج المعتمدة عندك بالفعل — مفيش رفع، والنموذج بيميّز المصطلح من الكلام العادي",
    en: "Pairs you have already approved — nothing to upload; the model separates terminology from ordinary wording",
  },
  "glossary.importTable": { ar: "استيراد جدول", en: "Import a table" },
  "glossary.importTableHint": {
    ar: "ملف CSV أو Excel بعمودين: المصطلح ثم ترجمته. بدون أي تكلفة.",
    en: "A CSV or Excel file with two columns: term, then its rendering. No cost.",
  },
  "glossary.fromPair": { ar: "من ملف وترجمته", en: "From a file and its translation" },
  "glossary.fromPairHint": {
    ar: "ارفع المستند الأصلي وترجمته المعتمدة — بنحاذيهم ونستخرج المصطلحات",
    en: "Upload the original document and its approved translation — we align them and extract the terminology",
  },
  "glossary.sourceFile": { ar: "الملف الأصلي", en: "Original file" },
  "glossary.targetFile": { ar: "الترجمة المعتمدة", en: "Approved translation" },
  "glossary.extracting": { ar: "جارٍ الاستخراج…", en: "Extracting…" },
  "glossary.candidates": {
    ar: "{n} مصطلح مرشّح — اختر اللي تضيفه",
    en: "{n} candidate terms — choose what to add",
  },
  "glossary.examined": {
    ar: "من {n} زوج · تكلفة ${cost}",
    en: "from {n} pairs · cost ${cost}",
  },
  "glossary.noCandidates": {
    ar: "مالقيناش مصطلحات تستحق الإضافة.",
    en: "No terms worth adding were found.",
  },
  "glossary.alreadyExists": { ar: "موجود", en: "already in" },
  "glossary.conflicts": {
    ar: "متعارض — الحالي: {current}",
    en: "conflicts — currently: {current}",
  },
  "glossary.addSelected": { ar: "إضافة {n} مصطلح", en: "Add {n} terms" },
  "glossary.selectAll": { ar: "تحديد الكل", en: "Select all" },
  "glossary.selectNone": { ar: "إلغاء التحديد", en: "Clear" },
  "glossary.added": {
    ar: "أُضيف {added} · حُدِّث {updated} · تُخطّي {skipped}",
    en: "{added} added · {updated} updated · {skipped} skipped",
  },
  "glossary.times": { ar: "×{n}", en: "×{n}" },
  "glossary.alternatives": {
    ar: "ترجمة منافسة — اختر واحدة بس",
    en: "competing rendering — pick one only",
  },
  "glossary.empty": {
    ar: "لا توجد مصطلحات بعد. المصطلحات المضافة هنا تُطبَّق على كل المشاريع في نفس المجال.",
    en: "No terms yet. Terms added here apply to every project in the same domain.",
  },

  // ------------------------------------------------------------ الحالات
  "status.draft": { ar: "مسودّة", en: "Draft" },
  "status.translated": { ar: "مترجَم", en: "Translated" },
  "status.reviewed": { ar: "مُراجَع", en: "Reviewed" },
  "status.approved": { ar: "معتمَد", en: "Approved" },
  "origin.engine": { ar: "المحرّك", en: "Engine" },
  "origin.tm_exact": { ar: "الذاكرة", en: "Memory" },
  "origin.human": { ar: "تعديل يدوي", en: "Hand edit" },
  "origin.propagated": { ar: "انتشار", en: "Propagated" },

  // ------------------------------------------------------------ أعلام الجودة
  "flag.empty": { ar: "فارغ", en: "Empty" },
  "flag.numbers_mismatch": { ar: "أرقام غير مطابقة", en: "Numbers do not match" },
  "flag.separator_changed": {
    ar: "فاصل رقمي مختلف عن المصدر",
    en: "Number separator differs from source",
  },
  "flag.untranslated": { ar: "غير مترجم", en: "Untranslated" },
  "flag.duplicated_word": {
    ar: "كلمة مكرّرة — راجع حدود التنسيق",
    en: "Duplicated word — check the formatting boundary",
  },
  "flag.formatting_simplified": {
    ar: "التنسيق الداخلي بُسّط عمدًا لسلامة الجملة",
    en: "Inline formatting simplified on purpose to keep the sentence sound",
  },
  "flag.wrong_script": { ar: "كتابة غير متوقعة", en: "Unexpected script" },
  "flag.too_short": { ar: "قصير بشكل غير معتاد", en: "Unusually short" },
  "flag.too_long": { ar: "طويل بشكل غير معتاد", en: "Unusually long" },
  "flag.tagsMissing": {
    ar: "وسم تنسيق ناقص ({tag})",
    en: "Missing formatting tag ({tag})",
  },
  "flag.tagsExtra": {
    ar: "وسم تنسيق زائد ({tag})",
    en: "Extra formatting tag ({tag})",
  },
  "flag.glossary": { ar: "مخالفة مصطلح: {detail}", en: "Glossary breach: {detail}" },
  // ------------------------------------------------------------ نص مقدّس
  "flag.quran_certain": { ar: "آية قرآنية — مقفول", en: "Quranic verse — locked" },
  "flag.quran_likely": {
    ar: "يُرجَّح أنه نص قرآني",
    en: "Likely Quranic text",
  },
  "flag.hadith_certain": { ar: "حديث نبوي — مقفول", en: "Hadith — locked" },
  "flag.hadith_likely": { ar: "يُرجَّح أنه حديث", en: "Likely a hadith" },
  "review.sacredLocked": {
    ar: "النص المقدّس مقفول ولم يُرسَل لأي محرّك. ضع الترجمة المعتمدة بنفسك ثم اعتمد المقطع.",
    en: "Sacred text is locked and was never sent to an engine. Paste the approved translation yourself, then approve the segment.",
  },
  "review.unlock": { ar: "فتح القفل", en: "Unlock" },
  "review.lock": { ar: "قفل", en: "Lock" },
  "file.sacredFound": {
    ar: "{locked} مقطع مقفول (آيات/أحاديث) · {flagged} مقطع يحتاج تدقيقًا",
    en: "{locked} locked segment(s) (Quran/Hadith) · {flagged} need checking",
  },

  "flag.ambiguousSeparator": {
    ar: "فاصل رقمي ملتبس ({value}) — راجع المعنى",
    en: "Ambiguous number separator ({value}) — check the meaning",
  },
} satisfies Record<string, Entry>;

export type StringKey = keyof typeof S;

type Vars = Record<string, string | number>;

function interpolate(template: string, vars?: Vars): string {
  if (!vars) return template;
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    name in vars ? String(vars[name]) : whole
  );
}

interface I18nValue {
  lang: UiLang;
  setLang: (lang: UiLang) => void;
  toggle: () => void;
  t: (key: StringKey, vars?: Vars) => string;
  /** اتجاه الواجهة — منفصل عن اتجاه نصوص الترجمة */
  dir: "rtl" | "ltr";
}

const I18nContext = createContext<I18nValue | null>(null);

function initialLang(): UiLang {
  const stored = localStorage.getItem(STORAGE_KEY);
  if (stored === "ar" || stored === "en") return stored;
  // نتبع لغة المتصفح لأول مرة بس
  return navigator.language.toLowerCase().startsWith("ar") ? "ar" : "en";
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [lang, setLangState] = useState<UiLang>(initialLang);

  const setLang = useCallback((next: UiLang) => {
    setLangState(next);
    localStorage.setItem(STORAGE_KEY, next);
  }, []);

  // اتجاه الصفحة ولغتها لازم يتغيّروا مع الواجهة عشان التخطيط
  // ينقلب صح وقارئ الشاشة ينطق الصح
  useEffect(() => {
    const dir = lang === "ar" ? "rtl" : "ltr";
    document.documentElement.setAttribute("lang", lang);
    document.documentElement.setAttribute("dir", dir);
  }, [lang]);

  const value = useMemo<I18nValue>(
    () => ({
      lang,
      setLang,
      toggle: () => setLang(lang === "ar" ? "en" : "ar"),
      t: (key, vars) => interpolate(S[key]?.[lang] ?? String(key), vars),
      dir: lang === "ar" ? "rtl" : "ltr",
    }),
    [lang, setLang]
  );

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>;
}

export function useI18n(): I18nValue {
  const value = useContext(I18nContext);
  if (!value) throw new Error("useI18n خارج I18nProvider");
  return value;
}

/** أسماء اللغات معروضة بلغة الواجهة الحالية. */
export const LANGUAGE_NAMES: Record<string, Entry> = {
  ar: { ar: "العربية", en: "Arabic" },
  en: { ar: "الإنجليزية", en: "English" },
  ru: { ar: "الروسية", en: "Russian" },
  tr: { ar: "التركية", en: "Turkish" },
  uk: { ar: "الأوكرانية", en: "Ukrainian" },
  az: { ar: "الأذربيجانية", en: "Azerbaijani" },
  fr: { ar: "الفرنسية", en: "French" },
  de: { ar: "الألمانية", en: "German" },
  es: { ar: "الإسبانية", en: "Spanish" },
  it: { ar: "الإيطالية", en: "Italian" },
};

export const DOMAIN_NAMES: Record<string, Entry> = {
  legal: { ar: "قانوني", en: "Legal" },
  medical: { ar: "طبي", en: "Medical" },
  scientific: { ar: "علمي", en: "Scientific" },
  technical: { ar: "تقني", en: "Technical" },
  religious: { ar: "شرعي", en: "Islamic sciences" },
  general: { ar: "عام", en: "General" },
};

/** اختيار النص من كائن {ar,en} جاي من الخادم. */
export function pick(
  value: { ar: string; en: string } | string | undefined,
  lang: UiLang
): string {
  if (!value) return "";
  return typeof value === "string" ? value : value[lang];
}

export function localName(
  table: Record<string, Entry>,
  code: string,
  lang: UiLang
): string {
  return table[code]?.[lang] ?? code;
}
