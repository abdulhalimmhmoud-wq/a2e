import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  api,
  watchJob,
  type AppConfig,
  type CostReport,
  type Estimate,
  type Job,
  type Project,
  type SourceFile,
} from "../api";
import { DOMAIN_NAMES, localName, useI18n } from "../i18n";

const FORMAT_LABEL: Record<string, string> = {
  docx: "Word",
  xlsx: "Excel",
  pptx: "PowerPoint",
  pdf: "PDF",
  plain: "Text",
};

function bytes(size: number, lang: string) {
  const units = lang === "ar" ? ["ب", "كب", "مب"] : ["B", "KB", "MB"];
  if (size < 1024) return `${size} ${units[0]}`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} ${units[1]}`;
  return `${(size / 1024 / 1024).toFixed(1)} ${units[2]}`;
}

export default function ProjectDetail() {
  const { projectId = "" } = useParams();
  const { t, lang } = useI18n();
  const navigate = useNavigate();
  const [project, setProject] = useState<Project | null>(null);
  const [editing, setEditing] = useState(false);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [config, setConfig] = useState<AppConfig | null>(null);
  const [estimate, setEstimate] = useState<Estimate | null>(null);
  const [cost, setCost] = useState<CostReport | null>(null);
  const [jobs, setJobs] = useState<Record<string, Job>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [p, f] = await Promise.all([
        api.getProject(projectId),
        api.listFiles(projectId),
      ]);
      setProject(p);
      setFiles(f);
      api.estimate(projectId).then(setEstimate).catch(() => undefined);
      api.cost(projectId).then(setCost).catch(() => undefined);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [projectId]);

  useEffect(() => {
    refresh();
    api.config().then(setConfig).catch(() => undefined);
  }, [refresh]);

  const track = (fileId: string, job: Job) => {
    setJobs((prev) => ({ ...prev, [fileId]: job }));
    watchJob(job.id, (update) => {
      setJobs((prev) => ({ ...prev, [fileId]: update }));
      if (update.status === "done" || update.status === "failed") refresh();
    });
  };

  const upload = async (fileList: FileList | null) => {
    if (!fileList?.length) return;
    setBusy(true);
    setError("");
    try {
      for (const file of Array.from(fileList)) {
        const record = await api.uploadFile(projectId, file);
        // الاستخراج يبدأ تلقائيًا — لا معنى لملف مرفوع بدون تحليل
        const job = await api.extract(record.id);
        track(record.id, job);
      }
      refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
      if (inputRef.current) inputRef.current.value = "";
    }
  };

  const translate = async (file: SourceFile, engine: string) => {
    setError("");
    try {
      const job = await api.translate(file.id, { engine, use_memory: true });
      track(file.id, job);
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const cancel = async (fileId: string, jobId: string) => {
    try {
      const job = await api.cancelJob(jobId);
      setJobs((prev) => ({ ...prev, [fileId]: job }));
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const removeFile = async (file: SourceFile) => {
    if (!confirm(t("project.confirmDeleteFile", { name: file.original_filename })))
      return;
    try {
      await api.deleteFile(file.id);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const removeProject = async () => {
    if (!project) return;
    if (
      !confirm(
        t("project.confirmDeleteProject", {
          name: project.name,
          files: project.file_count,
        })
      )
    )
      return;
    try {
      await api.deleteProject(project.id);
      navigate("/translator");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const saveSettings = async (changes: Partial<Project>) => {
    try {
      setProject(await api.updateProject(projectId, changes));
      setEditing(false);
      refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  };

  if (!project) return <div className="empty">{t("common.loading")}</div>;

  const hasKey = config?.has_api_key ?? false;
  // زر «ترجمة» بيستخدم محرّك المشروع، فبنتأكد إن مفتاحه موجود
  const engineReady =
    config?.engines.find((e) => e.id === project.engine)?.available ?? hasKey;
  // الوفر الحقيقي للتنفيذ المؤجَّل بيتآكل كل ما الملف يكبر
  const batchSaving =
    estimate?.options.find((o) => o.model === project.model)?.batch_saving_pct ?? null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{project.name}</h1>
          <p className="sub">
            <Link to="/translator">{t("nav.translator")}</Link> · {project.source_lang}→
            {project.target_lang} · {localName(DOMAIN_NAMES, project.domain, lang)} ·{" "}
            {project.engine === "deepl" ? "DeepL" : project.model}
          </p>
        </div>
        <div className="row">
          <input
            ref={inputRef}
            type="file"
            multiple
            style={{ display: "none" }}
            onChange={(e) => upload(e.target.files)}
            accept=".docx,.docm,.xlsx,.xlsm,.pptx,.pptm,.pdf,.txt,.md,.csv"
          />
          <button
            className="btn primary"
            onClick={() => inputRef.current?.click()}
            disabled={busy}
          >
            {busy ? t("project.uploading") : t("project.upload")}
          </button>
          <button className="btn" onClick={() => setEditing((v) => !v)}>
            {editing ? t("common.close") : t("common.settings")}
          </button>
          <button className="btn danger" onClick={removeProject}>
            {t("project.delete")}
          </button>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}
      {!hasKey && <div className="notice">{t("project.noKeyNotice")}</div>}

      {editing && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <div className="field" style={{ flex: 1, minWidth: 170, marginBottom: 0 }}>
              <label>{t("projects.domain")}</label>
              <select
                value={project.domain}
                onChange={(e) => saveSettings({ domain: e.target.value })}
              >
                {config?.domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {localName(DOMAIN_NAMES, d.id, lang)}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ flex: 1, minWidth: 150, marginBottom: 0 }}>
              <label>{t("projects.engine")}</label>
              <select
                value={project.engine}
                onChange={(e) => saveSettings({ engine: e.target.value })}
              >
                {config?.engines.map((e) => (
                  <option key={e.id} value={e.id} disabled={!e.available}>
                    {e.label}
                    {!e.available && ` ${t("projects.noEngineKey")}`}
                  </option>
                ))}
              </select>
            </div>
            {project.engine === "claude" && (
              <div className="field" style={{ flex: 1, minWidth: 200, marginBottom: 0 }}>
                <label>{t("projects.model")}</label>
                <select
                  value={project.model}
                  onChange={(e) => saveSettings({ model: e.target.value })}
                >
                  {config?.models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>

          <div className="field" style={{ marginTop: 14, marginBottom: 0 }}>
            <label>{t("projects.styleNotes")}</label>
            <textarea
              rows={2}
              defaultValue={project.style_notes}
              onBlur={(e) =>
                e.target.value !== project.style_notes &&
                saveSettings({ style_notes: e.target.value })
              }
              placeholder={t("projects.styleNotesPlaceholder")}
            />
          </div>
          <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
            {t("project.settingsHint")}
          </p>
        </div>
      )}

      {/* ------------------------------------------------ التكلفة */}
      {estimate && estimate.words > 0 && (
        <div className="grid cols-4" style={{ marginBottom: 18 }}>
          <div className="card stat">
            <div className="label">{t("project.size")}</div>
            <div className="value">{estimate.words.toLocaleString()}</div>
            <div className="hint">
              {t("common.words")} · {estimate.pages} {t("common.pages")} ·{" "}
              {estimate.segments} {t("common.segments")}
            </div>
          </div>
          <div className="card stat">
            <div className="label">{t("project.memoryCoverage")}</div>
            <div className="value">{estimate.memory_coverage_pct}%</div>
            <div className="hint">{t("project.memoryCoverageHint")}</div>
          </div>
          {estimate.options.slice(0, 2).map((option) => (
            <div className="card stat" key={option.model}>
              <div className="label">
                {option.label}
                {option.promo_active && ` ${t("project.promo")}`}
              </div>
              <div className="value">${option.cost_usd.toFixed(3)}</div>
              <div className="hint">
                ${option.cost_per_page.toFixed(4)}/{t("common.perPage")} ·{" "}
                {t("project.deferred")} ${option.cost_usd_batch.toFixed(3)} (
                {t("project.saving")} {option.batch_saving_pct.toFixed(0)}%)
              </div>
            </div>
          ))}
        </div>
      )}

      {cost && cost.total_cost_usd > 0 && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="row">
            <strong>
              {t("project.actualCost")}: ${cost.total_cost_usd.toFixed(4)}
            </strong>
            <span className="muted">
              (${cost.cost_per_page.toFixed(4)} {t("project.perPageShort")})
            </span>
            <div className="spacer" />
            <span className="badge ok">
              {t("project.savedFromMemory", { n: cost.savings.segments_from_memory })}
            </span>
            {cost.savings.cache_saving_usd > 0 && (
              <span className="badge ok">
                {t("project.savedFromCache", {
                  n: cost.savings.cache_saving_usd.toFixed(4),
                })}
              </span>
            )}
          </div>
        </div>
      )}

      {/* ------------------------------------------------ الملفات */}
      {files.length === 0 ? (
        <div className="empty">{t("project.emptyFiles")}</div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>{t("project.colFile")}</th>
                <th style={{ width: 90 }}>{t("project.colFormat")}</th>
                <th style={{ width: 150 }}>{t("project.colSize")}</th>
                <th style={{ width: 210 }}>{t("project.colProgress")}</th>
                <th style={{ width: 320 }}>{t("project.colActions")}</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => {
                const job = jobs[file.id];
                const running =
                  job && ["queued", "running", "cancelling"].includes(job.status);
                const progress = file.progress;

                return (
                  <tr key={file.id}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{file.original_filename}</div>
                      {file.error && (
                        <div style={{ color: "var(--danger)", fontSize: 12 }}>
                          {file.error}
                        </div>
                      )}
                      {job?.error && (
                        <div style={{ color: "var(--danger)", fontSize: 12 }}>
                          {job.error}
                        </div>
                      )}
                    </td>
                    <td>
                      <span className="badge">{FORMAT_LABEL[file.fmt] ?? file.fmt}</span>
                    </td>
                    <td className="muted" style={{ fontSize: 12.5 }}>
                      {bytes(file.size_bytes, lang)}
                      {file.segment_count > 0 && (
                        <>
                          <br />
                          {file.word_count.toLocaleString()} {t("common.words")} ·{" "}
                          {file.segment_count} {t("common.segments")}
                        </>
                      )}
                    </td>
                    <td>
                      {running ? (
                        <>
                          <div className="bar">
                            <div
                              style={{
                                width: `${
                                  job.total ? (job.progress / job.total) * 100 : 15
                                }%`,
                              }}
                            />
                          </div>
                          <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                            {job.message || job.status}
                          </div>
                        </>
                      ) : progress ? (
                        <>
                          <div className="bar">
                            <div style={{ width: `${progress.done_pct}%` }} />
                          </div>
                          <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                            {progress.approved + progress.reviewed}/{progress.total}{" "}
                            {t("project.approvedOf")}
                            {progress.flagged > 0 &&
                              ` · ${progress.flagged} ${t("project.alerts")}`}
                          </div>
                        </>
                      ) : (
                        <span className="muted">{file.status}</span>
                      )}
                    </td>
                    <td>
                      <div className="row">
                        {file.status === "pending" && (
                          <button
                            className="btn sm"
                            disabled={running}
                            onClick={async () => track(file.id, await api.extract(file.id))}
                          >
                            {t("project.extract")}
                          </button>
                        )}
                        {(file.status === "extracted" || file.status === "translated") && (
                          <>
                            <button
                              className="btn sm primary"
                              disabled={running || !engineReady}
                              onClick={() => translate(file, "auto")}
                              title={t("project.engineTitle", {
                                engine:
                                  project.engine === "deepl" ? "DeepL" : project.model,
                              })}
                            >
                              {t("project.translate")}
                            </button>
                            {/* التنفيذ المؤجَّل خاص بـ Claude — DeepL مالوش وضع مجمّع */}
                            {project.engine === "claude" && (
                              <button
                                className="btn sm"
                                disabled={running || !hasKey}
                                onClick={() => translate(file, "batch")}
                                title={
                                  batchSaving !== null
                                    ? t("project.deferredTitle", {
                                        pct: batchSaving.toFixed(0),
                                      })
                                    : t("project.deferredTitlePlain")
                                }
                              >
                                {t("project.deferredRun")}
                              </button>
                            )}
                            <button
                              className="btn sm"
                              disabled={running}
                              onClick={() => translate(file, "echo")}
                              title={t("project.dryRunTitle")}
                            >
                              {t("project.dryRun")}
                            </button>
                          </>
                        )}
                        {file.segment_count > 0 && (
                          <Link
                            className="btn sm"
                            to={`/translator/${projectId}/review/${file.id}`}
                          >
                            {t("project.review")}
                          </Link>
                        )}
                        {file.status === "translated" && (
                          <a className="btn sm" href={api.downloadUrl(file.id)}>
                            {t("project.download")}
                          </a>
                        )}
                        {running && job.kind === "translate" && (
                          <button
                            className="btn sm danger"
                            onClick={() => cancel(file.id, job.id)}
                            title={t("project.stopTitle")}
                          >
                            {t("project.stop")}
                          </button>
                        )}
                        {!running && (
                          <button
                            className="btn sm danger"
                            onClick={() => removeFile(file)}
                          >
                            {t("common.delete")}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
