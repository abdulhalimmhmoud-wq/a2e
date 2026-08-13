import { useEffect, useState } from "react";
import { api, type AppConfig, type GlossaryTerm } from "../api";

export default function Glossary() {
  const [terms, setTerms] = useState<GlossaryTerm[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [error, setError] = useState("");
  const [form, setForm] = useState({
    source_term: "",
    target_term: "",
    domain: "legal",
    notes: "",
  });

  const load = () => api.listTerms().then(setTerms).catch((e) => setError(e.message));

  useEffect(() => {
    load();
    api.config().then(setConfig).catch(() => undefined);
  }, []);

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

  return (
    <>
      <div className="page-head">
        <div>
          <h1>قاعدة المصطلحات</h1>
          <p className="sub">
            ترجمات ملزمة تُحقن في تعليمات النموذج، وتُفحص بعد الترجمة تلقائيًا
          </p>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="row" style={{ alignItems: "flex-end" }}>
          <div className="field" style={{ flex: 1, minWidth: 170, marginBottom: 0 }}>
            <label>المصطلح (عربي)</label>
            <input
              value={form.source_term}
              onChange={(e) => setForm({ ...form, source_term: e.target.value })}
              placeholder="عقد إذعان"
            />
          </div>
          <div className="field" style={{ flex: 1, minWidth: 170, marginBottom: 0 }}>
            <label>الترجمة (إنجليزي)</label>
            <input
              className="ltr"
              value={form.target_term}
              onChange={(e) => setForm({ ...form, target_term: e.target.value })}
              placeholder="Contract of Adhesion"
            />
          </div>
          <div className="field" style={{ width: 150, marginBottom: 0 }}>
            <label>المجال</label>
            <select
              value={form.domain}
              onChange={(e) => setForm({ ...form, domain: e.target.value })}
            >
              {config?.domains.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.label}
                </option>
              ))}
            </select>
          </div>
          <button className="btn primary" onClick={add}>
            إضافة
          </button>
        </div>
      </div>

      {terms.length === 0 ? (
        <div className="empty">
          لا توجد مصطلحات بعد. المصطلحات المضافة هنا تُطبَّق على كل المشاريع في
          نفس المجال.
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>المصطلح</th>
                <th>الترجمة</th>
                <th style={{ width: 110 }}>المجال</th>
                <th style={{ width: 80 }} />
              </tr>
            </thead>
            <tbody>
              {terms.map((term) => (
                <tr key={term.id}>
                  <td>{term.source_term}</td>
                  <td className="ltr">{term.target_term}</td>
                  <td>
                    <span className="badge">{term.domain}</span>
                  </td>
                  <td>
                    <button
                      className="btn sm danger"
                      onClick={async () => {
                        await api.deleteTerm(term.id);
                        load();
                      }}
                    >
                      حذف
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
