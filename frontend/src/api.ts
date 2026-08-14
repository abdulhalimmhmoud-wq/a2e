/** طبقة الاتصال بالخادم. */

const BASE = "/api";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: init?.body instanceof FormData ? {} : { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let message = `خطأ ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail ?? message;
    } catch {
      /* الرد مش JSON */
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json();
}

// ---------------------------------------------------------------- الأنواع
export interface Tool {
  id: string;
  name: string;
  description: string;
  icon: string;
  path: string;
  status: string;
}

export interface ModelInfo {
  id: string;
  label: string;
  input_per_mtok: number;
  output_per_mtok: number;
  promo_active: boolean;
  note: string;
}

export interface LanguageInfo {
  id: string;
  label: string;
  rtl: boolean;
}

export interface EngineInfo {
  id: string;
  label: string;
  available: boolean;
  note: string;
  pricing: string;
}

export interface AppConfig {
  models: ModelInfo[];
  domains: { id: string; label: string }[];
  languages: LanguageInfo[];
  engines: EngineInfo[];
  default_model: string;
  legal_model: string;
  has_api_key: boolean;
  has_deepl_key: boolean;
}

/** لغات تُكتب من اليمين لليسار — تُستخدم لضبط اتجاه العرض. */
const RTL_LANGUAGES = new Set(["ar", "he", "fa", "ur"]);

export function isRtl(lang: string): boolean {
  return RTL_LANGUAGES.has(lang.split("-")[0].toLowerCase());
}

export interface Project {
  id: string;
  name: string;
  source_lang: string;
  target_lang: string;
  domain: string;
  engine: string;
  model: string;
  style_notes: string;
  status: string;
  created_at: string;
  file_count: number;
  word_count: number;
  cost_usd: number;
}

export interface FileProgress {
  total: number;
  draft: number;
  translated: number;
  reviewed: number;
  approved: number;
  flagged: number;
  done_pct: number;
}

export interface SourceFile {
  id: string;
  project_id: string;
  original_filename: string;
  fmt: string;
  size_bytes: number;
  page_count: number;
  word_count: number;
  char_count: number;
  unit_count: number;
  segment_count: number;
  status: string;
  error: string | null;
  progress: FileProgress | null;
}

export interface Segment {
  id: string;
  order_index: number;
  unit_key: string;
  kind: string;
  location: string;
  source_text: string;
  target_text: string;
  status: string;
  origin: string;
  tm_match_pct: number;
  is_translatable: boolean;
  is_locked: boolean;
  edited_by_human: boolean;
  qa_flags: string[];
  notes: string;
}

export interface SegmentPage {
  items: Segment[];
  total: number;
  offset: number;
  limit: number;
}

export interface PropagationTarget {
  segment_id: string;
  location: string;
  source_text: string;
  current_target: string;
  proposed_target: string;
  match_type: string;
  score: number;
}

export interface PropagationPlan {
  auto_applied: number;
  needs_review: PropagationTarget[];
}

export interface Job {
  id: string;
  kind: string;
  status: string;
  progress: number;
  total: number;
  message: string;
  error: string | null;
  result: Record<string, unknown>;
}

export interface Estimate {
  words: number;
  chars: number;
  pages: number;
  segments: number;
  memory_coverage_pct: number;
  estimated_input_tokens: number;
  estimated_output_tokens: number;
  options: {
    model: string;
    label: string;
    promo_active: boolean;
    cost_usd: number;
    cost_usd_batch: number;
    /** الوفر الفعلي للتنفيذ المؤجَّل — يتآكل كلما كبر الملف */
    batch_saving_pct: number;
    batches: number;
    /** لـ DeepL فقط: عدد الحروف المحاسَبة */
    chars?: number;
    note?: string;
    cost_per_page: number;
    cost_per_word: number;
  }[];
}

export interface CostReport {
  total_cost_usd: number;
  by_model: {
    model: string;
    calls: number;
    input_tokens: number;
    output_tokens: number;
    cache_read_tokens: number;
    cache_write_tokens: number;
    cost_usd: number;
  }[];
  words: number;
  pages: number;
  cost_per_word: number;
  cost_per_page: number;
  savings: {
    segments_from_memory: number;
    cache_read_tokens: number;
    cache_saving_usd: number;
  };
}

export interface GlossaryTerm {
  id: string;
  source_term: string;
  target_term: string;
  domain: string;
  project_id: string | null;
  notes: string;
}

// ---------------------------------------------------------------- النداءات
export const api = {
  config: () => request<AppConfig>("/config"),
  tools: () => request<Tool[]>("/tools"),

  listProjects: () => request<Project[]>("/projects"),
  getProject: (id: string) => request<Project>(`/projects/${id}`),
  createProject: (payload: Partial<Project>) =>
    request<Project>("/projects", { method: "POST", body: JSON.stringify(payload) }),
  updateProject: (id: string, payload: Partial<Project>) =>
    request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(payload) }),
  deleteProject: (id: string) =>
    request<{ deleted: boolean }>(`/projects/${id}`, { method: "DELETE" }),

  listFiles: (projectId: string) => request<SourceFile[]>(`/projects/${projectId}/files`),
  getFile: (id: string) => request<SourceFile>(`/files/${id}`),
  uploadFile: (projectId: string, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<SourceFile>(`/projects/${projectId}/files`, {
      method: "POST",
      body: form,
    });
  },
  deleteFile: (id: string) =>
    request<{ deleted: boolean }>(`/files/${id}`, { method: "DELETE" }),

  extract: (fileId: string) => request<Job>(`/files/${fileId}/extract`, { method: "POST" }),
  translate: (fileId: string, payload: { engine: string; use_memory: boolean }) =>
    request<Job>(`/files/${fileId}/translate`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  exportFile: (fileId: string) =>
    request<{ filename: string; size_bytes: number; download_url: string }>(
      `/files/${fileId}/export`,
      { method: "POST" }
    ),
  downloadUrl: (fileId: string) => `${BASE}/files/${fileId}/download`,

  getJob: (id: string) => request<Job>(`/jobs/${id}`),
  cancelJob: (id: string) => request<Job>(`/jobs/${id}/cancel`, { method: "POST" }),

  suggestions: (segmentId: string) =>
    request<{ matches: { source_text: string; target_text: string; score: number }[] }>(
      `/segments/${segmentId}/suggestions`
    ),

  listSegments: (fileId: string, params: Record<string, string | number | boolean>) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== "" && value !== false && value !== undefined) {
        query.set(key, String(value));
      }
    });
    return request<SegmentPage>(`/files/${fileId}/segments?${query}`);
  },
  updateSegment: (
    id: string,
    payload: {
      target_text?: string;
      source_text?: string;
      status?: string;
      notes?: string;
      is_locked?: boolean;
      plan_propagation?: boolean;
    }
  ) =>
    request<{ segment: Segment; propagation: PropagationPlan | null }>(`/segments/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
  propagate: (id: string, segmentIds: string[], targetTexts: Record<string, string>) =>
    request<{ applied: number }>(`/segments/${id}/propagate`, {
      method: "POST",
      body: JSON.stringify({ segment_ids: segmentIds, target_texts: targetTexts }),
    }),
  approveAll: (fileId: string) =>
    request<{ approved: number }>(`/files/${fileId}/approve-all`, { method: "POST" }),

  estimate: (projectId: string) => request<Estimate>(`/projects/${projectId}/estimate`),
  cost: (projectId: string) => request<CostReport>(`/projects/${projectId}/cost`),

  listTerms: (projectId?: string) =>
    request<GlossaryTerm[]>(`/glossary${projectId ? `?project_id=${projectId}` : ""}`),
  addTerm: (payload: Omit<GlossaryTerm, "id">) =>
    request<GlossaryTerm>("/glossary", { method: "POST", body: JSON.stringify(payload) }),
  deleteTerm: (id: string) =>
    request<{ deleted: boolean }>(`/glossary/${id}`, { method: "DELETE" }),
};

/** متابعة مهمة خلفية حتى تنتهي. */
export function watchJob(
  jobId: string,
  onProgress: (job: Job) => void
): () => void {
  const source = new EventSource(`${BASE}/jobs/${jobId}/stream`);
  source.addEventListener("progress", (event) => {
    const job = JSON.parse((event as MessageEvent).data) as Job;
    onProgress(job);
    if (job.status === "done" || job.status === "failed") source.close();
  });
  source.onerror = () => source.close();
  return () => source.close();
}
