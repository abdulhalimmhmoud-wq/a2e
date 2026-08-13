import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  api,
  isRtl,
  type Project,
  type PropagationPlan,
  type Segment,
  type SourceFile,
} from "../api";
import PropagationDialog from "../components/PropagationDialog";

const FLAG_LABEL: Record<string, string> = {
  empty: "فارغ",
  numbers_mismatch: "أرقام غير مطابقة",
  untranslated: "غير مترجم",
  wrong_script: "كتابة غير متوقعة",
  too_short: "قصير بشكل غير معتاد",
  too_long: "طويل بشكل غير معتاد",
};

const STATUS_LABEL: Record<string, string> = {
  draft: "مسودّة",
  translated: "مترجَم",
  reviewed: "مُراجَع",
  approved: "معتمَد",
};

const LANG_LABEL: Record<string, string> = {
  ar: "عربي",
  en: "إنجليزي",
  fr: "فرنسي",
  de: "ألماني",
  es: "إسباني",
  tr: "تركي",
};

const ORIGIN_LABEL: Record<string, string> = {
  engine: "المحرّك",
  tm_exact: "الذاكرة",
  human: "تعديل يدوي",
  propagated: "انتشار",
};

/** إبراز وسوم التنسيق حتى لا يحذفها المراجع بالخطأ. */
function renderWithTags(text: string) {
  const parts = text.split(/(<\/?g\d+>)/g);
  return parts.map((part, index) =>
    /^<\/?g\d+>$/.test(part) ? (
      <span key={index} className="tag">
        {part}
      </span>
    ) : (
      <span key={index}>{part}</span>
    )
  );
}

function flagLabel(flag: string) {
  if (flag.startsWith("tags_missing:")) return `وسم تنسيق ناقص (${flag.split(":")[1]})`;
  if (flag.startsWith("tags_extra:")) return `وسم تنسيق زائد (${flag.split(":")[1]})`;
  if (flag.startsWith("glossary:")) return `مخالفة مصطلح: ${flag.slice(9)}`;
  if (flag.startsWith("ambiguous_separator:"))
    return `فاصل رقمي ملتبس (${flag.slice(20)}) — راجع المعنى`;
  return FLAG_LABEL[flag] ?? flag;
}

export default function Review() {
  const { projectId = "", fileId = "" } = useParams();
  const [file, setFile] = useState<SourceFile | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [segments, setSegments] = useState<Segment[]>([]);
  const [total, setTotal] = useState(0);
  const [filters, setFilters] = useState({ status: "", flagged: false, search: "" });
  const [active, setActive] = useState<string | null>(null);
  const [plan, setPlan] = useState<{ source: Segment; plan: PropagationPlan } | null>(null);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [suggestions, setSuggestions] = useState<
    Record<string, { source_text: string; target_text: string; score: number }[]>
  >({});
  const drafts = useRef<Record<string, string>>({});

  /** مطابقات تقريبية من الذاكرة — بتتجاب عند التركيز على المقطع فقط،
   *  عشان مانحمّلش الذاكرة كلها لكل مقطع في الصفحة. */
  const loadSuggestions = async (segmentId: string) => {
    if (suggestions[segmentId]) return;
    try {
      const result = await api.suggestions(segmentId);
      setSuggestions((prev) => ({ ...prev, [segmentId]: result.matches }));
    } catch {
      setSuggestions((prev) => ({ ...prev, [segmentId]: [] }));
    }
  };

  const load = useCallback(
    async (offset = 0) => {
      try {
        const page = await api.listSegments(fileId, {
          offset,
          limit: 200,
          status: filters.status,
          flagged: filters.flagged,
          search: filters.search,
        });
        setTotal(page.total);
        setSegments((prev) => (offset === 0 ? page.items : [...prev, ...page.items]));
      } catch (e) {
        setError((e as Error).message);
      }
    },
    [fileId, filters]
  );

  useEffect(() => {
    api.getFile(fileId).then(setFile).catch(() => undefined);
    api.getProject(projectId).then(setProject).catch(() => undefined);
  }, [fileId, projectId]);

  // اتجاه كل عمود بيتبع لغته: عربي→إنجليزي يعرض المصدر RTL والهدف LTR،
  // وإنجليزي→عربي بيعكسهم. من غير ده الترجمة العربية هتظهر مقلوبة.
  const sourceDir = isRtl(project?.source_lang ?? "ar") ? "rtl" : "ltr";
  const targetDir = isRtl(project?.target_lang ?? "en") ? "rtl" : "ltr";
  const sourceStyle = { direction: sourceDir, textAlign: sourceDir === "rtl" ? "right" : "left" } as const;
  const targetStyle = { direction: targetDir, textAlign: targetDir === "rtl" ? "right" : "left" } as const;

  useEffect(() => {
    load(0);
  }, [load]);

  const save = async (segment: Segment, text: string, alsoApprove = false) => {
    if (text === segment.target_text && !alsoApprove) return;
    try {
      const result = await api.updateSegment(segment.id, {
        target_text: text !== segment.target_text ? text : undefined,
        status: alsoApprove ? "approved" : undefined,
        plan_propagation: true,
      });

      setSegments((prev) =>
        prev.map((s) => (s.id === segment.id ? result.segment : s))
      );
      delete drafts.current[segment.id];

      const propagation = result.propagation;
      if (propagation) {
        if (propagation.auto_applied > 0) {
          setToast(`طُبّق التعديل تلقائيًا على ${propagation.auto_applied} مقطع مطابق`);
          setTimeout(() => setToast(""), 4000);
          load(0);
        }
        if (propagation.needs_review.length > 0) {
          setPlan({ source: result.segment, plan: propagation });
        }
      }
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const approveAll = async () => {
    const result = await api.approveAll(fileId);
    setToast(`اعتُمد ${result.approved} مقطع وحُفظ في ذاكرة الترجمة`);
    setTimeout(() => setToast(""), 4000);
    load(0);
  };

  const stats = file?.progress;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{file?.original_filename ?? "مراجعة"}</h1>
          <p className="sub">
            <Link to={`/translator/${projectId}`}>رجوع للمشروع</Link>
            {stats && (
              <>
                {" "}· {stats.total} مقطع · {stats.approved} معتمَد
                {stats.flagged > 0 && ` · ${stats.flagged} تنبيه`}
              </>
            )}
          </p>
        </div>
        <div className="row">
          <button className="btn" onClick={approveAll}>
            اعتماد الكل
          </button>
          <a className="btn primary" href={api.downloadUrl(fileId)}>
            تصدير الملف
          </a>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {toast && (
        <div className="notice" style={{ background: "var(--ok-soft)", color: "var(--ok)" }}>
          {toast}
        </div>
      )}

      <div className="review-toolbar">
        <div className="row">
          <select
            style={{ width: 150 }}
            value={filters.status}
            onChange={(e) => setFilters({ ...filters, status: e.target.value })}
          >
            <option value="">كل الحالات</option>
            <option value="draft">مسودّة</option>
            <option value="translated">مترجَم</option>
            <option value="approved">معتمَد</option>
          </select>

          <button
            className={`btn sm ${filters.flagged ? "primary" : ""}`}
            onClick={() => setFilters({ ...filters, flagged: !filters.flagged })}
          >
            التنبيهات فقط
          </button>

          <input
            style={{ width: 260 }}
            placeholder="بحث في المصدر أو الترجمة…"
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value })}
          />

          <div className="spacer" />
          <span className="muted" style={{ fontSize: 12.5 }}>
            عرض {segments.length} من {total} · <kbd>Ctrl</kbd>+<kbd>Enter</kbd> للاعتماد
            والانتقال
          </span>
        </div>
      </div>

      <div className="seg-head">
        <div>#</div>
        <div>المصدر ({LANG_LABEL[project?.source_lang ?? "ar"] ?? project?.source_lang})</div>
        <div>الترجمة ({LANG_LABEL[project?.target_lang ?? "en"] ?? project?.target_lang})</div>
        <div>الحالة</div>
      </div>

      {segments.map((segment, index) => {
        const draft = drafts.current[segment.id] ?? segment.target_text;
        const classes = [
          "seg",
          active === segment.id ? "active" : "",
          segment.qa_flags.length ? "flagged" : "",
          segment.is_locked ? "locked" : "",
        ]
          .filter(Boolean)
          .join(" ");

        return (
          <div key={segment.id} className={classes} onFocus={() => setActive(segment.id)}>
            <div className="idx">{segment.order_index + 1}</div>

            <div className="source" style={sourceStyle}>
              {renderWithTags(segment.source_text)}
              <div className="loc">{segment.location}</div>
            </div>

            <div className="target" style={targetStyle}>
              {segment.is_translatable ? (
                <textarea
                  style={targetStyle}
                  defaultValue={draft}
                  rows={Math.min(6, Math.ceil(segment.source_text.length / 60) || 1)}
                  onChange={(e) => {
                    drafts.current[segment.id] = e.target.value;
                  }}
                  onFocus={() => loadSuggestions(segment.id)}
                  onBlur={(e) => save(segment, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                      e.preventDefault();
                      save(segment, e.currentTarget.value, true);
                      const next = document.querySelectorAll<HTMLTextAreaElement>(
                        ".seg .target textarea"
                      )[index + 1];
                      next?.focus();
                    }
                  }}
                />
              ) : (
                <span className="muted" style={{ fontSize: 12.5 }}>
                  غير قابل للترجمة — يمرّ كما هو
                </span>
              )}

              {active === segment.id && suggestions[segment.id]?.length > 0 && (
                <div className="suggestions">
                  <div className="loc">من ذاكرة الترجمة — اضغط للاستخدام</div>
                  {suggestions[segment.id].map((match, i) => (
                    <button
                      key={i}
                      type="button"
                      className="suggestion"
                      style={targetStyle}
                      onClick={() => {
                        drafts.current[segment.id] = match.target_text;
                        save(segment, match.target_text);
                      }}
                      title={`المصدر المشابه: ${match.source_text}`}
                    >
                      <span className="badge accent">{match.score}%</span>
                      <span>{match.target_text}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="meta">
              <span
                className={`badge ${
                  segment.status === "approved"
                    ? "ok"
                    : segment.status === "draft"
                    ? ""
                    : "accent"
                }`}
              >
                {STATUS_LABEL[segment.status] ?? segment.status}
              </span>
              {segment.origin && (
                <span className="loc">{ORIGIN_LABEL[segment.origin] ?? segment.origin}</span>
              )}
              {segment.qa_flags.map((flag) => (
                <span key={flag} className="badge warn" title={flagLabel(flag)}>
                  {flagLabel(flag).slice(0, 26)}
                </span>
              ))}
            </div>
          </div>
        );
      })}

      {segments.length < total && (
        <div style={{ padding: 18, textAlign: "center" }}>
          <button className="btn" onClick={() => load(segments.length)}>
            تحميل المزيد ({total - segments.length} متبقٍ)
          </button>
        </div>
      )}

      {plan && (
        <PropagationDialog
          source={plan.source}
          plan={plan.plan}
          onClose={() => setPlan(null)}
          onApplied={(count) => {
            setPlan(null);
            setToast(`طُبّق التعديل على ${count} مقطع`);
            setTimeout(() => setToast(""), 4000);
            load(0);
          }}
        />
      )}
    </>
  );
}
