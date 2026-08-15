import { useEffect, useRef, useState } from "react";
import {
  api,
  type AppConfig,
  type Extraction,
  type GlossaryTerm,
  type TermCandidate,
} from "../api";
import { DOMAIN_NAMES, LANGUAGE_NAMES, localName, useI18n } from "../i18n";

type Mode = "" | "memory" | "table" | "pair";

export default function Glossary() {
  const { t, lang } = useI18n();
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [error, setError] = useState("");
  const [toast, setToast] = useState("");
  const [mode, setMode] = useState<Mode>("");
  const [busy, setBusy] = useState(false);
  const [extraction, setExtraction] = useState<Extraction | null>(null);
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [langs, setLangs] = useState({ source_lang: "ar", target_lang: "en" });
  /** الملفين في الحالة مش في الـ ref — الـ ref مايعملش إعادة رسم
   *  فعلامة الاختيار كانت هتفضل مخفية بعد ما المستخدم يختار */
  const [pair, setPair] = useState<{ source?: File; target?: File }>({});

  const [form, setForm] = useState({
    source_term: "",
    target_term: "",
    domain: "legal",
    notes: "",
  });

  const tableRef = useRef<HTMLInputElement>(null);
  const sourceRef = useRef<HTMLInputElement>(null);
  const targetRef = useRef<HTMLInputElement>(null);

  const load = () => api.listTerms().then(setTerms).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    api.config().then(setConfig).catch(() => undefined);
  }, []);

  const notify = (message: string) => {
    setToast(message);
    setTimeout(() => setToast(""), 5000);
  };

  const add = async () => {
    if (!form.source_term.trim() || !form.target_term.trim()) return;
    try {
      await api.addTerm({ ...form, project_id: null });
      setForm({ ...form, source_term: "", target_term: "", notes: "" });
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  /** الموجود بنفس الترجمة مش مختار — إضافته بلا معنى. ولما يكون فيه
   *  أكتر من ترجمة لنفس المصطلح، بنختار الأولى بس ونسيب الباقي للمراجع. */
  const receive = (result: Extraction) => {
    setExtraction(result);
    const seen = new Set<string>();
    const initial = new Set<number>();
    result.candidates.forEach((candidate, i) => {
      if (candidate.exists || seen.has(candidate.source_term)) return;
      seen.add(candidate.source_term);
      initial.add(i);
    });
    setSelected(initial);
  };

  const run = async (fn: () => Promise<Extraction>) => {
    setBusy(true);
    setError("");
    setExtraction(null);
    try {
      receive(await fn());
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    if (!extraction) return;
    const chosen = extraction.candidates
      .filter((_, i) => selected.has(i))
      .map((c) => ({
        source_term: c.source_term,
        target_term: c.target_term,
        domain: form.domain,
        project_id: null,
        notes: c.note,
      }));
    if (!chosen.length) return;

    setBusy(true);
    try {
      const result = await api.addTermsBulk(chosen);
      notify(t("glossary.added", result));
      setExtraction(null);
      setMode("");
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  /** اختيار ترجمة بيلغي الترجمات المنافسة لنفس المصطلح — الإضافة
   *  بتحدّث المصطلح الموجود، فاختيار اتنين معناه إن التانية بتاكل
   *  الأولى بصمت والمراجع فاكر إنه ضاف الاتنين. */
  const toggle = (index: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
        return next;
      }
      const source = extraction?.candidates[index].source_term;
      extraction?.candidates.forEach((other, i) => {
        if (i !== index && other.source_term === source) next.delete(i);
      });
      next.add(index);
      return next;
    });

  const selectAll = () => {
    if (!extraction) return;
    // «تحديد الكل» بيختار أول ترجمة لكل مصطلح بس، مش كل المرشّحين
    const seen = new Set<string>();
    const picked = new Set<number>();
    extraction.candidates.forEach((candidate, i) => {
      if (seen.has(candidate.source_term)) return;
      seen.add(candidate.source_term);
      picked.add(i);
    });
    setSelected(picked);
  };

  const domainSelect = (
    <select
      value={form.domain}
      onChange={(e) => setForm({ ...form, domain: e.target.value })}
    >
      {config?.domains.map((d) => (
        <option key={d.id} value={d.id}>
          {localName(DOMAIN_NAMES, d.id, lang)}
        </option>
      ))}
    </select>
  );

  const languagePair = (
    <>
      <div className="field" style={{ width: 130, marginBottom: 0 }}>
        <label>{t("projects.sourceLang")}</label>
        <select
          value={langs.source_lang}
          onChange={(e) => setLangs({ ...langs, source_lang: e.target.value })}
        >
          {config?.languages.map((l) => (
            <option key={l.id} value={l.id}>
              {localName(LANGUAGE_NAMES, l.id, lang)}
            </option>
          ))}
        </select>
      </div>
      <div className="field" style={{ width: 130, marginBottom: 0 }}>
        <label>{t("projects.targetLang")}</label>
        <select
          value={langs.target_lang}
          onChange={(e) => setLangs({ ...langs, target_lang: e.target.value })}
        >
          {config?.languages.map((l) => (
            <option key={l.id} value={l.id}>
              {localName(LANGUAGE_NAMES, l.id, lang)}
            </option>
          ))}
        </select>
      </div>
    </>
  );

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("glossary.title")}</h1>
          <p className="sub">{t("glossary.subtitle")}</p>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {toast && (
        <div className="notice" style={{ background: "var(--ok-soft)", color: "var(--ok)" }}>
          {toast}
        </div>
      )}

      {/* ---------------------------------------- إضافة مصطلح واحد */}
      <div className="card" style={{ marginBottom: 14 }}>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 150, marginBottom: 0 }}>
            <label>{t("glossary.source")}</label>
            <input
              value={form.source_term}
              onChange={(e) => setForm({ ...form, source_term: e.target.value })}
              placeholder={t("glossary.sourcePlaceholder")}
            />
          </div>
          <div className="field" style={{ flex: 1, minWidth: 150, marginBottom: 0 }}>
            <label>{t("glossary.target")}</label>
            <input
              className="ltr"
              value={form.target_term}
              onChange={(e) => setForm({ ...form, target_term: e.target.value })}
              placeholder={t("glossary.targetPlaceholder")}
            />
          </div>
          <div className="field" style={{ width: 140, marginBottom: 0 }}>
            <label>{t("glossary.domain")}</label>
            {domainSelect}
          </div>
          <button className="btn primary" onClick={add}>
            {t("common.add")}
          </button>
        </div>
      </div>

      {/* ---------------------------------------- إضافة دفعة */}
      <div className="card" style={{ marginBottom: 18 }}>
        <div className="row" style={{ marginBottom: mode ? 14 : 0 }}>
          <strong>{t("glossary.bulkTitle")}</strong>
          <div className="spacer" />
          <button
            className={`btn sm ${mode === "memory" ? "primary" : ""}`}
            onClick={() => setMode(mode === "memory" ? "" : "memory")}
          >
            {t("glossary.fromMemory")}
          </button>
          <button
            className={`btn sm ${mode === "table" ? "primary" : ""}`}
            onClick={() => setMode(mode === "table" ? "" : "table")}
          >
            {t("glossary.importTable")}
          </button>
          <button
            className={`btn sm ${mode === "pair" ? "primary" : ""}`}
            onClick={() => setMode(mode === "pair" ? "" : "pair")}
          >
            {t("glossary.fromPair")}
          </button>
        </div>

        {mode === "memory" && (
          <>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
              {t("glossary.fromMemoryHint")}
            </p>
            <div className="row" style={{ alignItems: "flex-end" }}>
              {languagePair}
              <div className="field" style={{ width: 140, marginBottom: 0 }}>
                <label>{t("glossary.domain")}</label>
                {domainSelect}
              </div>
              <button
                className="btn primary"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    api.mineTerms({ ...langs, domain: form.domain, limit: 200 })
                  )
                }
              >
                {busy ? t("glossary.extracting") : t("glossary.fromMemory")}
              </button>
            </div>
          </>
        )}

        {mode === "table" && (
          <>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
              {t("glossary.importTableHint")}
            </p>
            <div className="row" style={{ alignItems: "flex-end" }}>
              <div className="field" style={{ width: 140, marginBottom: 0 }}>
                <label>{t("glossary.domain")}</label>
                {domainSelect}
              </div>
              <input
                ref={tableRef}
                type="file"
                accept=".csv,.tsv,.txt,.xlsx,.xlsm"
                style={{ display: "none" }}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) run(() => api.importTerms(form.domain, file));
                  e.target.value = "";
                }}
              />
              <button
                className="btn primary"
                disabled={busy}
                onClick={() => tableRef.current?.click()}
              >
                {busy ? t("glossary.extracting") : t("glossary.importTable")}
              </button>
            </div>
          </>
        )}

        {mode === "pair" && (
          <>
            <p className="muted" style={{ fontSize: 12.5, marginTop: 0 }}>
              {t("glossary.fromPairHint")}
            </p>
            <div className="row" style={{ alignItems: "flex-end" }}>
              {languagePair}
              <div className="field" style={{ width: 140, marginBottom: 0 }}>
                <label>{t("glossary.domain")}</label>
                {domainSelect}
              </div>
              <input
                ref={sourceRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) =>
                  setPair({ ...pair, source: e.target.files?.[0] })
                }
              />
              <input
                ref={targetRef}
                type="file"
                style={{ display: "none" }}
                onChange={(e) =>
                  setPair({ ...pair, target: e.target.files?.[0] })
                }
              />
              <button className="btn" onClick={() => sourceRef.current?.click()}>
                {pair.source ? `✓ ${pair.source.name.slice(0, 22)}` : t("glossary.sourceFile")}
              </button>
              <button className="btn" onClick={() => targetRef.current?.click()}>
                {pair.target ? `✓ ${pair.target.name.slice(0, 22)}` : t("glossary.targetFile")}
              </button>
              <button
                className="btn primary"
                disabled={busy || !pair.source || !pair.target}
                onClick={() => {
                  if (!pair.source || !pair.target) return;
                  const { source, target } = pair;
                  run(() =>
                    api.extractTerms(
                      { ...langs, domain: form.domain },
                      source,
                      target
                    )
                  );
                }}
              >
                {busy ? t("glossary.extracting") : t("common.add")}
              </button>
            </div>
          </>
        )}
      </div>

      {/* ---------------------------------------- مراجعة المرشّحين */}
      {extraction && (
        <div className="card" style={{ marginBottom: 18 }}>
          {extraction.warnings.map((warning, i) => (
            <div key={i} className="notice">
              {warning}
            </div>
          ))}

          {extraction.candidates.length === 0 ? (
            <div className="empty">{t("glossary.noCandidates")}</div>
          ) : (
            <>
              <div className="row" style={{ marginBottom: 10 }}>
                <strong>
                  {t("glossary.candidates", { n: extraction.candidates.length })}
                </strong>
                <span className="muted" style={{ fontSize: 12.5 }}>
                  {t("glossary.examined", {
                    n: extraction.pairs_examined,
                    cost: extraction.cost_usd.toFixed(4),
                  })}
                </span>
                <div className="spacer" />
                <button className="btn sm" onClick={selectAll}>
                  {t("glossary.selectAll")}
                </button>
                <button className="btn sm" onClick={() => setSelected(new Set())}>
                  {t("glossary.selectNone")}
                </button>
              </div>

              {extraction.candidates.map((candidate: TermCandidate, index) => (
                <label key={index} className="prop-item">
                  <input
                    type="checkbox"
                    style={{ width: 16, marginTop: 4 }}
                    checked={selected.has(index)}
                    onChange={() => toggle(index)}
                  />
                  <div style={{ minWidth: 0, flex: 1 }}>
                    <div className="row" style={{ gap: 8 }}>
                      <strong>{candidate.source_term}</strong>
                      <span className="muted">→</span>
                      <span className="ltr">{candidate.target_term}</span>
                      {candidate.frequency > 1 && (
                        <span className="badge">
                          {t("glossary.times", { n: candidate.frequency })}
                        </span>
                      )}
                      {candidate.exists && (
                        <span className="badge ok">{t("glossary.alreadyExists")}</span>
                      )}
                      {candidate.conflicts_with && (
                        <span className="badge warn">
                          {t("glossary.conflicts", {
                            current: candidate.conflicts_with,
                          })}
                        </span>
                      )}
                      {candidate.alternatives.length > 0 && (
                        <span className="badge danger">
                          {t("glossary.alternatives")}
                        </span>
                      )}
                    </div>
                    {candidate.note && (
                      <div className="muted" style={{ fontSize: 11.5, marginTop: 3 }}>
                        {candidate.note}
                      </div>
                    )}
                    {candidate.sample && (
                      <div
                        className="muted"
                        style={{
                          fontSize: 11.5,
                          marginTop: 3,
                          overflow: "hidden",
                          textOverflow: "ellipsis",
                          whiteSpace: "nowrap",
                        }}
                      >
                        {candidate.sample}
                      </div>
                    )}
                  </div>
                </label>
              ))}

              <div className="row" style={{ marginTop: 14 }}>
                <button
                  className="btn primary"
                  disabled={busy || !selected.size}
                  onClick={commit}
                >
                  {t("glossary.addSelected", { n: selected.size })}
                </button>
                <button className="btn" onClick={() => setExtraction(null)}>
                  {t("common.cancel")}
                </button>
              </div>
            </>
          )}
        </div>
      )}

      {/* ---------------------------------------- القاعدة الحالية */}
      {terms.length === 0 ? (
        <div className="empty">{t("glossary.empty")}</div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>{t("glossary.source")}</th>
                <th>{t("glossary.target")}</th>
                <th style={{ width: 110 }}>{t("glossary.domain")}</th>
                <th style={{ width: 80 }} />
              </tr>
            </thead>
            <tbody>
              {terms.map((term) => (
                <tr key={term.id}>
                  <td>{term.source_term}</td>
                  <td className="ltr">{term.target_term}</td>
                  <td>
                    <span className="badge">
                      {localName(DOMAIN_NAMES, term.domain, lang)}
                    </span>
                  </td>
                  <td>
                    <button
                      className="btn sm danger"
                      onClick={async () => {
                        await api.deleteTerm(term.id);
                        load();
                      }}
                    >
                      {t("common.delete")}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
