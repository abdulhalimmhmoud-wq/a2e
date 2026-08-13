import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AppConfig, type Project } from "../api";

export default function Projects() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({
    name: "",
    source_lang: "ar",
    target_lang: "en",
    domain: "legal",
    model: "claude-sonnet-5",
    style_notes: "",
  });

  const swapLanguages = () =>
    setForm({ ...form, source_lang: form.target_lang, target_lang: form.source_lang });

  const load = () => api.listProjects().then(setProjects).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    api.config().then(setConfig).catch(() => undefined);
  }, []);

  // المجال القانوني يستحق موديلًا أقوى — نقترحه تلقائيًا
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
          <h1>المترجم</h1>
          <p className="sub">ترجمة المستندات مع الحفاظ الكامل على التنسيق</p>
        </div>
        <button className="btn primary" onClick={() => setCreating((v) => !v)}>
          {creating ? "إلغاء" : "مشروع جديد"}
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {creating && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="field">
            <label>اسم المشروع</label>
            <input
              autoFocus
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="مثال: عقود الربع الثالث"
            />
          </div>

          <div className="row" style={{ alignItems: "flex-end" }}>
            <div className="field" style={{ flex: 1, minWidth: 130 }}>
              <label>لغة المصدر</label>
              <select
                value={form.source_lang}
                onChange={(e) => setForm({ ...form, source_lang: e.target.value })}
              >
                {config?.languages.map((l) => (
                  <option key={l.id} value={l.id} disabled={l.id === form.target_lang}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>

            <button
              className="btn"
              style={{ marginBottom: 14 }}
              onClick={swapLanguages}
              title="عكس اتجاه الترجمة"
            >
              ⇄
            </button>

            <div className="field" style={{ flex: 1, minWidth: 130 }}>
              <label>لغة الهدف</label>
              <select
                value={form.target_lang}
                onChange={(e) => setForm({ ...form, target_lang: e.target.value })}
              >
                {config?.languages.map((l) => (
                  <option key={l.id} value={l.id} disabled={l.id === form.source_lang}>
                    {l.label}
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="row" style={{ alignItems: "flex-start" }}>
            <div className="field" style={{ flex: 1, minWidth: 180 }}>
              <label>المجال</label>
              <select value={form.domain} onChange={(e) => onDomainChange(e.target.value)}>
                {config?.domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="field" style={{ flex: 1, minWidth: 180 }}>
              <label>الموديل</label>
              <select
                value={form.model}
                onChange={(e) => setForm({ ...form, model: e.target.value })}
              >
                {config?.models.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.label} — ${m.input_per_mtok}/${m.output_per_mtok} لكل مليون توكن
                  </option>
                ))}
              </select>
            </div>
          </div>

          <div className="field">
            <label>ملاحظات أسلوبية (اختياري)</label>
            <textarea
              rows={2}
              value={form.style_notes}
              onChange={(e) => setForm({ ...form, style_notes: e.target.value })}
              placeholder="مثال: استخدم صيغة المخاطب الرسمية، واكتب أسماء الشركات كما هي دون ترجمة"
            />
          </div>

          <button className="btn primary" onClick={create} disabled={!form.name.trim()}>
            إنشاء
          </button>
        </div>
      )}

      {projects.length === 0 ? (
        <div className="empty">لا توجد مشاريع بعد. ابدأ بإنشاء مشروع جديد.</div>
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
                <span className="badge accent">{project.domain}</span>
              </div>
              <div className="row muted" style={{ fontSize: 12.5, gap: 14 }}>
                <span className="mono">
                  {project.source_lang} → {project.target_lang}
                </span>
                <span>{project.file_count} ملف</span>
                <span>{project.word_count.toLocaleString("ar-EG")} كلمة</span>
                <span>${project.cost_usd.toFixed(4)}</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
