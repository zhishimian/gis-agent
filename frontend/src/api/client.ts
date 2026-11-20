import type {
  EnvInfo,
  ExecutionRow,
  FigureItem,
  IdentifyResult,
  SessionSummary,
} from "../types/studio";

declare global {
  interface Window {
    __TAURI_INTERNALS__?: Record<string, unknown>;
  }
}

interface BackendConnection {
  baseUrl: string;
  token: string;
  mode: "tauri" | "browser";
}

let conn: BackendConnection = {
  baseUrl: "",
  token: "",
  mode: "browser",
};

export function isTauriRuntime(): boolean {
  return Boolean(typeof window !== "undefined" && window.__TAURI_INTERNALS__);
}

export async function initBackendConnection(): Promise<BackendConnection> {
  if (isTauriRuntime()) {
    const { invoke } = await import("@tauri-apps/api/core");
    const cfg = await invoke<{ url: string; token: string }>("get_backend_config");
    conn = { baseUrl: cfg.url.replace(/\/$/, ""), token: cfg.token, mode: "tauri" };
    return conn;
  }
  const res = await fetch("/api/bootstrap");
  if (!res.ok) {
    throw new Error(`无法连接本地服务 (/api/bootstrap): HTTP ${res.status}`);
  }
  const data = (await res.json()) as { token: string };
  conn = { baseUrl: "", token: data.token, mode: "browser" };
  return conn;
}

export function getConnection(): BackendConnection {
  return conn;
}

export function buildAuthedUrl(path: string, params?: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && String(v) !== "") {
        qs.set(k, String(v));
      }
    }
  }
  if (conn.token) {
    qs.set("token", conn.token);
  }
  const query = qs.toString();
  return `${conn.baseUrl}${path}${query ? `?${query}` : ""}`;
}

export async function apiFetch<T = any>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers || {});
  if (conn.token) {
    headers.set("X-OpenGIS-Token", conn.token);
  }
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const res = await fetch(`${conn.baseUrl}${path}`, { ...init, headers });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const payload = await res.json();
      if (payload?.detail) msg = String(payload.detail);
    } catch {
      const text = await res.text();
      if (text) msg = text;
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

export const api = {
  getEnv: () => apiFetch<EnvInfo>("/api/env"),
  selectWorkspace: (project_dir: string) =>
    apiFetch<{ project_dir: string; files: any[] }>("/api/workspace/select", {
      method: "POST",
      body: JSON.stringify({ project_dir }),
    }),
  attachFile: (path: string) =>
    apiFetch<{ path: string; name: string; kind: string; bytes: number }>("/api/workspace/attach", {
      method: "POST",
      body: JSON.stringify({ path }),
    }),
  listFiles: (sessionId?: string, dir?: string) =>
    apiFetch<{ project_dir: string; current_dir: string; output_dir: string; items: any[]; attached: any[] }>(
      `/api/workspace/files?${new URLSearchParams({
        ...(sessionId ? { session_id: sessionId } : {}),
        ...(dir ? { dir } : {}),
      }).toString()}`
    ),
  saveCredentials: (payload: { api_key?: string; provider?: string; model?: string; base_url?: string }) =>
    apiFetch("/api/settings/credentials", { method: "POST", body: JSON.stringify(payload) }),
  saveQgis: (qgis_dir: string | null) =>
    apiFetch("/api/settings/qgis", { method: "POST", body: JSON.stringify({ qgis_dir }) }),
  listSessions: () => apiFetch<{ sessions: SessionSummary[] }>("/api/sessions"),
  createSession: (session_id?: string) =>
    apiFetch<{ session_id: string; output_dir: string }>("/api/sessions", {
      method: "POST",
      body: JSON.stringify({ session_id: session_id || null }),
    }),
  getSessionDetail: (sessionId: string) => apiFetch<any>(`/api/sessions/${encodeURIComponent(sessionId)}`),
  sendMessage: (sessionId: string, text: string, workspace_context?: Record<string, any> | null) =>
    apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/messages`, {
      method: "POST",
      body: JSON.stringify({ text, workspace_context }),
    }),
  replyCheckpoint: (
    sessionId: string,
    payload: { text: string; request_id?: string; option_id?: string; workspace_context?: Record<string, any> | null }
  ) =>
    apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/reply`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  stopSession: (sessionId: string) =>
    apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/stop`, { method: "POST" }),
  cancelCheckpoint: (sessionId: string) =>
    apiFetch(`/api/sessions/${encodeURIComponent(sessionId)}/cancel`, { method: "POST" }),
  getLayerMeta: (path: string) =>
    apiFetch<any>(`/api/spatial/layer-meta?${new URLSearchParams({ path }).toString()}`),
  getVectorGeojson: (
    path: string,
    opts: { bbox?: [number, number, number, number]; zoom?: number; max_features?: number } = {}
  ) =>
    apiFetch<any>(
      `/api/spatial/vector?${new URLSearchParams({
        path,
        ...(opts.bbox ? { bbox: opts.bbox.join(",") } : {}),
        ...(opts.zoom !== undefined ? { zoom: String(opts.zoom) } : {}),
        ...(opts.max_features !== undefined ? { max_features: String(opts.max_features) } : {}),
      }).toString()}`
    ),
  identify: (payload: { lon: number; lat: number; zoom: number; layers: Array<{ path: string; type: string }> }) =>
    apiFetch<IdentifyResult>("/api/spatial/identify", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  getAttributes: (
    path: string,
    opts: { page?: number; page_size?: number; sort_by?: string; order?: string; query?: string; stats_field?: string } = {}
  ) =>
    apiFetch<any>(
      `/api/spatial/attributes?${new URLSearchParams({
        path,
        ...(opts.page ? { page: String(opts.page) } : {}),
        ...(opts.page_size ? { page_size: String(opts.page_size) } : {}),
        ...(opts.sort_by ? { sort_by: opts.sort_by } : {}),
        ...(opts.order ? { order: opts.order } : {}),
        ...(opts.query ? { query: opts.query } : {}),
        ...(opts.stats_field ? { stats_field: opts.stats_field } : {}),
      }).toString()}`
    ),
  listFigures: (sessionId: string) =>
    apiFetch<{ session_id: string; figures: FigureItem[] }>(`/api/figures/${encodeURIComponent(sessionId)}`),
  getExecutions: (sessionId: string, executionId?: string, section = "summary") =>
    apiFetch<{ ok: boolean; items?: ExecutionRow[]; text?: string }>(
      `/api/executions/${encodeURIComponent(sessionId)}?${new URLSearchParams({
        ...(executionId ? { execution_id: executionId, section } : {}),
      }).toString()}`
    ),
  revealOrOpen: async (path: string, action: "reveal" | "open" = "reveal") => {
    if (isTauriRuntime()) {
      const { invoke } = await import("@tauri-apps/api/core");
      return invoke("open_path_external", { path, action });
    }
    return apiFetch("/api/os/reveal", { method: "POST", body: JSON.stringify({ path, action }) });
  },
  pickNativeFolder: async (): Promise<string | null> => {
    if (!isTauriRuntime()) return null;
    const { open } = await import("@tauri-apps/plugin-dialog");
    const chosen = await open({ directory: true, multiple: false, title: "选择 OpenGIS 工作文件夹" });
    return typeof chosen === "string" ? chosen : null;
  },
  pickNativeSpatialFiles: async (): Promise<string[]> => {
    if (!isTauriRuntime()) return [];
    const { open } = await import("@tauri-apps/plugin-dialog");
    const chosen = await open({
      multiple: true,
      title: "加载本地地理空间数据",
      filters: [{ name: "GIS Spatial Data", extensions: ["shp", "gpkg", "geojson", "fgb", "tif", "tiff", "csv"] }],
    });
    if (!chosen) return [];
    return Array.isArray(chosen) ? chosen : [chosen];
  },
};
