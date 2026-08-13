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

const FORMAT_LABEL: Record<string, string> = {
  docx: "Word",
  xlsx: "Excel",
  pptx: "PowerPoint",
  pdf: "PDF",
  plain: "نص",
};

function bytes(size: number) {
  if (size < 1024) return `${size} ب`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} كب`;
  return `${(size / 1024 / 1024).toFixed(1)} مب`;
}

export default function ProjectDetail() {
  const { projectId = "" } = useParams();
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
    if (
      !confirm(
        `حذف «${file.original_filename}» ومقاطعه وترجمته نهائيًا؟\n` +
          `ذاكرة الترجمة مش هتتأثر — المقاطع المعتمَدة بتفضل محفوظة فيها.`
      )
    )
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
        `حذف مشروع «${project.name}» نهائيًا؟\n\n` +
          `هيتمسح: ${project.file_count} ملف · كل المقاطع والترجمات · ` +
          `الملفات المرفوعة والمصدَّرة من على القرص.\n\n` +
          `مش هيتمسح: ذاكرة الترجمة وقاعدة المصطلحات (بتفضل متاحة ` +
          `للمشاريع الجاية).\n\nالعملية دي مالهاش تراجع.`
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

  if (!project) return <div className="empty">جارٍ التحميل…</div>;

  const hasKey = config?.has_api_key ?? false;
  // الوفر الحقيقي للتنفيذ المؤجَّل بيتآكل كل ما الملف يكبر، لأن الوضع
  // الفوري بيستفيد من التخزين المؤقت والمؤجَّل لأ. بنعرض الرقم الفعلي.
  const batchSaving =
    estimate?.options.find((o) => o.model === project.model)?.batch_saving_pct ??
    null;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>{project.name}</h1>
          <p className="sub">
            <Link to="/translator">المترجم</Link> · {project.domain} · {project.model}
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
            {busy ? "جارٍ الرفع…" : "رفع ملفات"}
          </button>
          <button className="btn" onClick={() => setEditing((v) => !v)}>
            {editing ? "إغلاق" : "إعدادات"}
          </button>
          <button className="btn danger" onClick={removeProject}>
            حذف المشروع
          </button>
        </div>
      </div>

      {editing && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="row" style={{ alignItems: "flex-end" }}>
            <div className="field" style={{ flex: 1, minWidth: 200, marginBottom: 0 }}>
              <label>المجال</label>
              <select
                value={project.domain}
                onChange={(e) => saveSettings({ domain: e.target.value })}
              >
                {config?.domains.map((d) => (
                  <option key={d.id} value={d.id}>
                    {d.label}
                  </option>
                ))}
              </select>
            </div>
            <div className="field" style={{ flex: 1, minWidth: 220, marginBottom: 0 }}>
              <label>الموديل</label>
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
          </div>

          <div className="field" style={{ marginTop: 14, marginBottom: 0 }}>
            <label>ملاحظات أسلوبية</label>
            <textarea
              rows={2}
              defaultValue={project.style_notes}
              onBlur={(e) =>
                e.target.value !== project.style_notes &&
                saveSettings({ style_notes: e.target.value })
              }
              placeholder="مثال: احتفظ بأسماء الشركات كما هي دون ترجمة"
            />
          </div>
          <p className="muted" style={{ fontSize: 12, marginBottom: 0 }}>
            التغييرات بتأثّر على الترجمات الجديدة بس — المقاطع المترجمة
            بالفعل مابتتغيّرش.
          </p>
        </div>
      )}

      {error && <div className="error-box">{error}</div>}
      {!hasKey && (
        <div className="notice">
          مفتاح Anthropic غير مضبوط — زر «ترجمة» معطّل. يمكنك تجربة الخط كاملًا
          بزر «تشغيل تجريبي» بدون أي تكلفة.
        </div>
      )}

      {/* ------------------------------------------------ التكلفة */}
      {estimate && estimate.words > 0 && (
        <div className="grid cols-4" style={{ marginBottom: 18 }}>
          <div className="card stat">
            <div className="label">الحجم</div>
            <div className="value">{estimate.words.toLocaleString("ar-EG")}</div>
            <div className="hint">
              كلمة · {estimate.pages} صفحة · {estimate.segments} مقطع
            </div>
          </div>
          <div className="card stat">
            <div className="label">تغطية الذاكرة</div>
            <div className="value">{estimate.memory_coverage_pct}%</div>
            <div className="hint">مقاطع مترجمة سابقًا — بدون تكلفة</div>
          </div>
          {estimate.options.slice(0, 2).map((option) => (
            <div className="card stat" key={option.model}>
              <div className="label">
                {option.label}
                {option.promo_active && " (عرض)"}
              </div>
              <div className="value">${option.cost_usd.toFixed(3)}</div>
              <div className="hint">
                ${option.cost_per_page.toFixed(4)}/صفحة · مؤجَّل $
                {option.cost_usd_batch.toFixed(3)} (وفر{" "}
                {option.batch_saving_pct.toFixed(0)}%)
              </div>
            </div>
          ))}
        </div>
      )}

      {cost && cost.total_cost_usd > 0 && (
        <div className="card" style={{ marginBottom: 18 }}>
          <div className="row">
            <strong>التكلفة الفعلية: ${cost.total_cost_usd.toFixed(4)}</strong>
            <span className="muted">
              (${cost.cost_per_page.toFixed(4)} للصفحة)
            </span>
            <div className="spacer" />
            <span className="badge ok">
              وفّرت {cost.savings.segments_from_memory} مقطع من الذاكرة
            </span>
            {cost.savings.cache_saving_usd > 0 && (
              <span className="badge ok">
                وفّرت ${cost.savings.cache_saving_usd.toFixed(4)} من التخزين المؤقت
              </span>
            )}
          </div>
        </div>
      )}

      {/* ------------------------------------------------ الملفات */}
      {files.length === 0 ? (
        <div className="empty">
          لا توجد ملفات. ارفع ملف Word أو Excel أو PowerPoint أو PDF للبدء.
        </div>
      ) : (
        <div className="card" style={{ padding: 0 }}>
          <table>
            <thead>
              <tr>
                <th>الملف</th>
                <th style={{ width: 90 }}>الصيغة</th>
                <th style={{ width: 150 }}>الحجم</th>
                <th style={{ width: 210 }}>التقدّم</th>
                <th style={{ width: 300 }}>الإجراءات</th>
              </tr>
            </thead>
            <tbody>
              {files.map((file) => {
                const job = jobs[file.id];
                const running =
                  job &&
                  ["queued", "running", "cancelling"].includes(job.status);
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
                      {bytes(file.size_bytes)}
                      {file.segment_count > 0 && (
                        <>
                          <br />
                          {file.word_count.toLocaleString("ar-EG")} كلمة ·{" "}
                          {file.segment_count} مقطع
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
                            {progress.approved + progress.reviewed}/{progress.total} معتمد
                            {progress.flagged > 0 && ` · ${progress.flagged} تنبيه`}
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
                            استخراج
                          </button>
                        )}
                        {(file.status === "extracted" || file.status === "translated") && (
                          <>
                            <button
                              className="btn sm primary"
                              disabled={running || !hasKey}
                              onClick={() => translate(file, "claude")}
                            >
                              ترجمة
                            </button>
                            <button
                              className="btn sm"
                              disabled={running || !hasKey}
                              onClick={() => translate(file, "batch")}
                              title={
                                batchSaving !== null
                                  ? `تنفيذ غير فوري (قد يستغرق حتى ساعة أو أكثر). ` +
                                    `الوفر المتوقع لهذا الحجم: ${batchSaving}%`
                                  : "تنفيذ غير فوري — أرخص، لكن النتيجة لا تصل فورًا"
                              }
                            >
                              تنفيذ مؤجَّل
                            </button>
                            <button
                              className="btn sm"
                              disabled={running}
                              onClick={() => translate(file, "echo")}
                              title="يشغّل الخط كاملًا بترجمة وهمية — بدون تكلفة"
                            >
                              تشغيل تجريبي
                            </button>
                          </>
                        )}
                        {file.segment_count > 0 && (
                          <Link
                            className="btn sm"
                            to={`/translator/${projectId}/review/${file.id}`}
                          >
                            مراجعة
                          </Link>
                        )}
                        {file.status === "translated" && (
                          <a className="btn sm" href={api.downloadUrl(file.id)}>
                            تنزيل
                          </a>
                        )}
                        {running && job.kind === "translate" && (
                          <button
                            className="btn sm danger"
                            onClick={() => cancel(file.id, job.id)}
                            title="بيوقف الدفعات اللي لسه ماابتدتش — المترجَم بيفضل محفوظ"
                          >
                            إيقاف
                          </button>
                        )}
                        {!running && (
                          <button
                            className="btn sm danger"
                            onClick={() => removeFile(file)}
                          >
                            حذف
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
