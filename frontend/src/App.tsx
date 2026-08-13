import { NavLink, Route, Routes } from "react-router-dom";
import Hub from "./pages/Hub";
import Projects from "./pages/Projects";
import ProjectDetail from "./pages/ProjectDetail";
import Review from "./pages/Review";
import Glossary from "./pages/Glossary";

export default function App() {
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          ترجمان <span>الأحبة</span>
        </div>
        <NavLink to="/" end className="nav-link">
          الأدوات
        </NavLink>
        <NavLink to="/translator" className="nav-link">
          المترجم
        </NavLink>
        <NavLink to="/glossary" className="nav-link">
          المصطلحات
        </NavLink>
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
