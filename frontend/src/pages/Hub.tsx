import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type AppConfig, type Tool } from "../api";
import { pick, useI18n } from "../i18n";

export default function Hub() {
  const { t, lang } = useI18n();
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
          <h1>{t("hub.title")}</h1>
          <p className="sub">{t("hub.subtitle")}</p>
        </div>
      </div>

      {config && !config.has_api_key && (
        <div className="notice">
          <strong>{t("hub.noKeyTitle")}</strong> {t("hub.noKeyBody")}
        </div>
      )}

      <div className="grid cols-3">
        {tools.map((tool) => (
          <Link key={tool.id} to={tool.path} className="card" style={{ color: "inherit" }}>
            <div className="row" style={{ marginBottom: 8 }}>
              <strong style={{ fontSize: 16 }}>{pick(tool.name, lang)}</strong>
              <div className="spacer" />
              <span className="badge ok">{t("hub.available")}</span>
            </div>
            <p className="muted" style={{ margin: 0 }}>
              {pick(tool.description, lang)}
            </p>
          </Link>
        ))}

        <div className="card" style={{ borderStyle: "dashed", opacity: 0.7 }}>
          <div className="row" style={{ marginBottom: 8 }}>
            <strong style={{ fontSize: 16 }}>{t("hub.newToolTitle")}</strong>
          </div>
          <p className="muted" style={{ margin: 0 }}>
            {t("hub.newToolBody")}
          </p>
        </div>
      </div>
    </>
  );
}
