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
import {
  LANGUAGE_NAMES,
  localName,
  useI18n,
  type StringKey,
} from "../i18n";

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

export default function Review() {
  const { projectId = "", fileId = "" } = useParams();
  const { t, lang } = useI18n();
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

  /** ترجمة علم الجودة — بعضها يحمل تفاصيل بعد النقطتين. */
  const flagLabel = (flag: string) => {
    if (flag.startsWith("tags_missing:"))
      return t("flag.tagsMissing", { tag: flag.split(":")[1] });
    if (flag.startsWith("tags_extra:"))
      return t("flag.tagsExtra", { tag: flag.split(":")[1] });
    if (flag.startsWith("glossary:"))
      return t("flag.glossary", { detail: flag.slice(9) });
    if (flag.startsWith("ambiguous_separator:"))
      return t("flag.ambiguousSeparator", { value: flag.slice(20) });
    return t(`flag.${flag}` as StringKey);
  };

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

  useEffect(() => {
    load(0);
  }, [load]);

  // اتجاه كل عمود بيتبع **لغته**، مش لغة الواجهة. عربي→إنجليزي يعرض
  // المصدر RTL والهدف LTR مهما كانت لغة الواجهة.
  const sourceDir = isRtl(project?.source_lang ?? "ar") ? "rtl" : "ltr";
  const targetDir = isRtl(project?.target_lang ?? "en") ? "rtl" : "ltr";
  const sourceStyle = {
    direction: sourceDir,
    textAlign: sourceDir === "rtl" ? "right" : "left",
  } as const;
  const targetStyle = {
    direction: targetDir,
    textAlign: targetDir === "rtl" ? "right" : "left",
  } as const;

  const save = async (segment: Segment, text: string, alsoApprove = false) => {
    if (text === segment.target_text && !alsoApprove) return;
    try {
      const result = await api.updateSegment(segment.id, {
        target_text: text !== segment.target_text ? text : undefined,
        status: alsoApprove ? "approved" : undefined,
        plan_propagation: true,
      });

      setSegments((prev) => prev.map((s) => (s.id === segment.id ? result.segment : s)));
      delete drafts.current[segment.id];

      const propagation = result.propagation;
      if (propagation) {
        if (propagation.auto_applied > 0) {
          setToast(t("review.autoPropagated", { n: propagation.auto_applied }));
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
    setToast(t("review.approvedToast", { n: result.approved }));
    setTimeout(() => setToast(""), 4000);
    load(0);
  };

  const stats = file?.progress;
  const sourceName = localName(LANGUAGE_NAMES, project?.source_lang ?? "ar", lang);
  const targetName = localName(LANGUAGE_NAMES, project?.target_lang ?? "en", lang);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{file?.original_filename ?? t("review.title")}</h1>
          <p className="sub">
            <Link to={`/translator/${projectId}`}>{t("review.back")}</Link>
            {stats && (
              <>
                {" "}· {stats.total} {t("common.segments")} · {stats.approved}{" "}
                {t("status.approved")}
                {stats.flagged > 0 && ` · ${stats.flagged} ${t("project.alerts")}`}
              </>
            )}
          </p>
        </div>
        <div className="row">
          <button className="btn" onClick={approveAll}>
            {t("review.approveAll")}
          </button>
          <a className="btn primary" href={api.downloadUrl(fileId)}>
            {t("review.export")}
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
            <option value="">{t("review.allStatuses")}</option>
            <option value="draft">{t("status.draft")}</option>
            <option value="translated">{t("status.translated")}</option>
            <option value="approved">{t("status.approved")}</option>
          </select>

          <button
            className={`btn sm ${filters.flagged ? "primary" : ""}`}
            onClick={() => setFilters({ ...filters, flagged: !filters.flagged })}
          >
            {t("review.flaggedOnly")}
          </button>

          <input
            style={{ width: 260 }}
            placeholder={t("review.searchPlaceholder")}
            value={filters.search}
            onChange={(e) => setFilters({ ...filters, search: e.target.value })}
          />

          <div className="spacer" />
          <span className="muted" style={{ fontSize: 12.5 }}>
            {t("review.showing", { shown: segments.length, total })} ·{" "}
            <kbd>Ctrl</kbd>+<kbd>Enter</kbd> {t("review.shortcut")}
          </span>
        </div>
      </div>

      <div className="seg-head">
        <div>#</div>
        <div>
          {t("review.colSource")} ({sourceName})
        </div>
        <div>
          {t("review.colTarget")} ({targetName})
        </div>
        <div>{t("review.colStatus")}</div>
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
              {segment.is_locked && (
                <div
                  className="notice"
                  style={{ margin: "0 0 8px", fontSize: 12 }}
                >
                  {t("review.sacredLocked")}
                  {segment.notes && (
                    <div className="muted" style={{ marginTop: 4 }}>
                      {segment.notes}
                    </div>
                  )}
                </div>
              )}
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
                  {t("review.notTranslatable")}
                </span>
              )}

              {active === segment.id && suggestions[segment.id]?.length > 0 && (
                <div className="suggestions">
                  <div className="loc">{t("review.suggestionsTitle")}</div>
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
                      title={`${t("review.similarSource")}: ${match.source_text}`}
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
                {t(`status.${segment.status}` as StringKey)}
              </span>
              {segment.origin && (
                <span className="loc">{t(`origin.${segment.origin}` as StringKey)}</span>
              )}
              {segment.qa_flags.map((flag) => (
                <span key={flag} className="badge warn" title={flagLabel(flag)}>
                  {flagLabel(flag).slice(0, 30)}
                </span>
              ))}
              {segment.is_translatable && (
                <button
                  className="btn sm"
                  onClick={async () => {
                    const locked = !segment.is_locked;
                    await api.updateSegment(segment.id, {
                      is_locked: locked,
                      plan_propagation: false,
                    });
                    // تحديث المقطع ده بس — إعادة التحميل من الأول
                    // بترمي الصفحات اللي المراجع نزّلها بالتمرير
                    setSegments((prev) =>
                      prev.map((s) =>
                        s.id === segment.id ? { ...s, is_locked: locked } : s
                      )
                    );
                  }}
                >
                  {t(segment.is_locked ? "review.unlock" : "review.lock")}
                </button>
              )}
            </div>
          </div>
        );
      })}

      {segments.length < total && (
        <div style={{ padding: 18, textAlign: "center" }}>
          <button className="btn" onClick={() => load(segments.length)}>
            {t("review.loadMore", { n: total - segments.length })}
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
            setToast(t("review.propagated", { n: count }));
            setTimeout(() => setToast(""), 4000);
            load(0);
          }}
        />
      )}
    </>
  );
}
