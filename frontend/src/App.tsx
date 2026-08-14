import { NavLink, Route, Routes } from "react-router-dom";
import Hub from "./pages/Hub";
import Projects from "./pages/Projects";
import ProjectDetail from "./pages/ProjectDetail";
import Review from "./pages/Review";
import Glossary from "./pages/Glossary";
import { useI18n } from "./i18n";

export default function App() {
  const { t, toggle, lang } = useI18n();

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          {t("app.brandA")} <span>{t("app.brandB")}</span>
        </div>
        <NavLink to="/" end className="nav-link">
          {t("nav.tools")}
        </NavLink>
        <NavLink to="/translator" className="nav-link">
          {t("nav.translator")}
        </NavLink>
        <NavLink to="/glossary" className="nav-link">
          {t("nav.glossary")}
        </NavLink>

        <div className="spacer" />
        {/* لغة الواجهة — منفصلة تمامًا عن لغتَي الترجمة */}
        <button
          className="btn lang-toggle"
          onClick={toggle}
          title={t("lang.switchTitle")}
          aria-label={t("lang.switchTitle")}
        >
          <span aria-hidden>🌐</span>
          <span>{t("lang.switch")}</span>
          <span className="badge">{lang.toUpperCase()}</span>
        </button>
      </aside>

      <main className="main">
        <Routes>
          <Route path="/" element={<Hub />} />
          <Route path="/translator" element={<Projects />} />
          <Route path="/translator/:projectId" element={<ProjectDetail />} />
          <Route path="/translator/:projectId/review/:fileId" element={<Review />} />
          <Route path="/glossary" element={<Glossary />} />
        </Routes>
      </main>
    </div>
  );
}
