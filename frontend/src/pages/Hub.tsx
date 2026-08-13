import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AppConfig, type Tool } from "../api";

export default function Hub() {
  const [tools, setTools] = useState<Tool[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);

  useEffect(() => {
    api.tools().then(setTools).catch(() => setTools([]));
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>الأدوات</h1>
          <p className="sub">منصّة أدوات محلية — كل شيء يعمل على جهازك</p>
        </div>
      </div>

      {config && !config.has_api_key && (
        <div className="notice">
          <strong>مفتاح Anthropic غير مضبوط.</strong> الترجمة الحقيقية لن تعمل حتى
          تضع <code>ANTHROPIC_API_KEY</code> في ملف <code>.env</code> في جذر
          المشروع. التشغيل التجريبي بدون تكلفة متاح من صفحة المشروع.
        </div>
      )}

      <div className="grid cols-3">
        {tools.map((tool) => (
          <Link key={tool.id} to={tool.path} className="card" style={{ color: "inherit" }}>
            <div className="row" style={{ marginBottom: 8 }}>
              <strong style={{ fontSize: 16 }}>{tool.name}</strong>
              <div className="spacer" />
              <span className="badge ok">متاحة</span>
            </div>
            <p className="muted" style={{ margin: 0 }}>
              {tool.description}
            </p>
          </Link>
        ))}

        <div className="card" style={{ borderStyle: "dashed", opacity: 0.7 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <strong style={{ fontSize: 16 }}>أداة جديدة</strong>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            المنصّة مبنية كسجلّ أدوات — إضافة أداة جديدة تحتاج ملف تعريف ومجلّد
            فقط، دون المساس بالأساس.
          </p>
        </div>
      </div>
    </>
  );
}
