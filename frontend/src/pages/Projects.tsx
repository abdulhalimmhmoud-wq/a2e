import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AppConfig, type Project } from "../api";
import { DOMAIN_NAMES, LANGUAGE_NAMES, localName, useI18n } from "../i18n";

export default function Projects() {
  const { t, lang } = useI18n();
  const [projects, setProjects] = useState<Project[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    source_lang: "ar",
    target_lang: "en",
    domain: "legal",
    engine: "claude",
    model: "claude-sonnet-5",
    style_notes: "",
  });

  const load = () => api.listProjects().then(setProjects).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    api.config().then(setConfig).catch(() => undefined);
  }, []);

  const swapLanguages = () =>
    setForm({ ...form, source_lang: form.target_lang, target_lang: form.source_lang });

  // المجال القانوني والطبي يستحقان موديلًا أقوى — نقترحه تلقائيًا
  const onDomainChange = (domain: string) => {
    const suggested =
      domain === "legal" || domain === "medical"
        ? config?.legal_model ?? "claude-opus-5"
        : config?.default_model ?? "claude-sonnet-5";
    setForm({ ...form, domain, model: suggested });
  };

  const create = async () => {
    if (!form.name.trim()) return;
    setError("");
    try {
      await api.createProject(form);
      setForm({ ...form, name: "", style_notes: "" });
      setCreating(false);
      load();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{t("projects.title")}</h1>
          <p className="sub">{t("projects.subtitle")}</p>
        </div>
        <button className="btn primary" onClick={() => setCreating((v) => !v)}>
          {creating ? t("common.cancel") : t("projects.new")}
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {creating && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="field">
            <label>{t("projects.name")}</label>
            <input
              autoFocus
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={t("projects.namePlaceholder")}
            />
          </div>

          <div className="row" style={{ alignItems: "flex-end" }}>
            <div className="field" style={{ flex: 1, minWidth: 130 }}>
              <label>{t("projects.sourceLang")}</label>
              <select
                value={form.source_lang}
                onChange={(e) => setForm({ ...form, source_lang: e.target.value })}
              >
                {config?.languages.map((l) => (
                  <option key={l.id} value={l.id} disabled={l.id === form.target_lang}>
                    {localName(LANGUAGE_NAMES, l.id, lang)}
                  </option>
                ))}
              </select>
            </div>

            <button
              className="btn"
              style={{ marginBottom: 14 }}
              onClick={swapLanguages}
              title={t("projects.swap")}
            >
              ⇄
            </button>

            <div className="field" style={{ flex: 1, minWidth: 130 }}>
              <label>{t("projects.targetLang")}</label>
              <select
                value={form.target_lang}
                onChange={(e) => setForm({ ...form, target_lang: e.target.value })}
              >
                {config?.languages.map((l) => (
                  <option key={l.id} value={l.id} disabled={l.id === form.source_lang}>
                    {localName(LANGUAGE_NAMES, l.id, lang)}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="row" style={{ alignItems: "flex-start" }}>
            <div className="field" style={{ flex: 1, minWidth: 180 }}>
              <label>{t("projects.domain")}</label>
              <select value={form.domain} onChange={(e) => onDomainChange(e.target.value)}>
                {config?.domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {localName(DOMAIN_NAMES, d.id, lang)}
                  </option>
                ))}
              </select>
            </div>

            {form.engine === "claude" && (
              <div className="field" style={{ flex: 1, minWidth: 180 }}>
                <label>{t("projects.model")}</label>
                <select
                  value={form.model}
                  onChange={(e) => setForm({ ...form, model: e.target.value })}
                >
                  {config?.models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label} — ${m.input_per_mtok}/${m.output_per_mtok}{" "}
                      {t("projects.perMillion")}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="field">
            <label>{t("projects.engine")}</label>
            <div className="row" style={{ gap: 10 }}>
              {config?.engines.map((engine) => (
                <button
                  key={engine.id}
                  type="button"
                  className={`btn ${form.engine === engine.id ? "primary" : ""}`}
                  style={{ flex: 1, minWidth: 190, textAlign: "start" }}
                  disabled={!engine.available}
                  onClick={() => setForm({ ...form, engine: engine.id })}
                  title={
                    engine.available
                      ? engine.note
                      : t("projects.needsKey", { engine: engine.label })
                  }
                >
                  <span style={{ display: "block" }}>
                    <strong>{engine.label}</strong>
                    {!engine.available && ` ${t("projects.noEngineKey")}`}
                  </span>
                </button>
              ))}
            </div>
            <p className="muted" style={{ fontSize: 12, marginTop: 6, marginBottom: 0 }}>
              {config?.engines.find((e) => e.id === form.engine)?.note}
            </p>
          </div>

          <div className="field">
            <label>{t("projects.styleNotes")}</label>
            <textarea
              rows={2}
              value={form.style_notes}
              onChange={(e) => setForm({ ...form, style_notes: e.target.value })}
              placeholder={t("projects.styleNotesPlaceholder")}
            />
          </div>

          <button className="btn primary" onClick={create} disabled={!form.name.trim()}>
            {t("common.create")}
          </button>
        </div>
      )}

      {projects.length === 0 ? (
        <div className="empty">{t("projects.empty")}</div>
      ) : (
        <div className="grid cols-3">
          {projects.map((project) => (
            <Link
              key={project.id}
              to={`/translator/${project.id}`}
              className="card"
              style={{ color: "inherit" }}
            >
              <div className="row" style={{ marginBottom: 10 }}>
                <strong style={{ fontSize: 15.5 }}>{project.name}</strong>
                <div className="spacer" />
                <span className="badge accent">
                  {localName(DOMAIN_NAMES, project.domain, lang)}
                </span>
              </div>
              <div className="row muted" style={{ fontSize: 12.5, gap: 14 }}>
                <span className="mono">
                  {project.source_lang} → {project.target_lang}
                </span>
                <span className="badge">
                  {project.engine === "deepl" ? "DeepL" : "Claude"}
                </span>
                <span>
                  {project.file_count} {t("common.files")}
                </span>
                <span>${project.cost_usd.toFixed(4)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
