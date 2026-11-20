import { create } from "zustand";
import { api, buildAuthedUrl, initBackendConnection, isTauriRuntime } from "../api/client";
import type {
  BasemapKind,
  CheckpointRequest,
  EnvInfo,
  ExecutionPolicy,
  ExecutionRow,
  FigureAnnotation,
  FigureItem,
  IdentifyResult,
  LayerItem,
  MapToolMode,
  PlanSnapshot,
  SessionSummary,
  ToolActivity,
  UsageStats,
  WorkspaceFileItem,
  WorkspaceTab,
} from "../types/studio";

const LAYER_COLORS = ["#1d4ed8", "#0d9488", "#b45309", "#7c3aed", "#dc2626", "#0369a1"];
const RAMP_PALETTES = ["#eff6ff", "#93c5fd", "#3b82f6", "#1d4ed8", "#1e3a8a"];

interface StudioState {
  ready: boolean;
  initError: string | null;
  isTauri: boolean;
  env: EnvInfo | null;
  projectDir: string;
  files: WorkspaceFileItem[];
  attachedFiles: WorkspaceFileItem[];
  sessions: SessionSummary[];
  activeSessionId: string;
  busy: boolean;
  plan: PlanSnapshot;
  waiting: CheckpointRequest | null;
  messages: any[];
  toolFeed: ToolActivity[];
  executions: ExecutionRow[];
  figures: FigureItem[];
  layers: LayerItem[];
  activeTab: WorkspaceTab;
  mapTool: MapToolMode;
  basemap: BasemapKind;
  fitBoundsSeq: number;
  fitBoundsTarget: [number, number, number, number] | null;
  identifyPopup: IdentifyResult | null;
  selectedLayerPaths: string[];
  selectedFids: number[];
  drawnBboxWgs84: [number, number, number, number] | null;
  drawnGeometryGeojson: Record<string, any> | null;
  clickedPointWgs84: [number, number] | null;
  figureAnnotations: FigureAnnotation[];
  executionPolicy: ExecutionPolicy;
  usage: UsageStats;
  attrLayerPath: string | null;
  selectedExecId: string | null;
  settingsOpen: boolean;
  toast: string | null;

  bootstrap: () => Promise<void>;
  refreshWorkspace: () => Promise<void>;
  switchProject: (dir: string) => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  createNewSession: (name?: string) => Promise<void>;
  attachAndAddLayer: (filePath: string) => Promise<void>;
  addLayerByPath: (filePath: string, kindHint?: "vector" | "raster") => Promise<void>;
  toggleLayerVisible: (id: string) => void;
  setLayerOpacity: (id: string, opacity: number) => void;
  moveLayer: (id: string, dir: -1 | 1) => void;
  removeLayer: (id: string) => void;
  zoomToLayer: (bbox: [number, number, number, number] | null) => void;
  styleVectorLayerByField: (id: string, field: string | null) => Promise<void>;
  updateRasterStyle: (id: string, band: number, colormap: string) => void;
  toggleLayerSelectedForContext: (path: string) => void;
  setActiveTab: (tab: WorkspaceTab) => void;
  setMapTool: (tool: MapToolMode) => void;
  setBasemap: (bm: BasemapKind) => void;
  setIdentifyPopup: (popup: IdentifyResult | null) => void;
  setSelectedFids: (fids: number[]) => void;
  setDrawnAoi: (bbox: [number, number, number, number] | null, geojson?: Record<string, any> | null) => void;
  setClickedPoint: (pt: [number, number] | null) => void;
  addFigureAnnotation: (ann: FigureAnnotation) => void;
  removeFigureAnnotation: (id: string) => void;
  setExecutionPolicy: (policy: ExecutionPolicy) => void;
  setAttrLayerPath: (path: string | null) => void;
  setSelectedExecId: (id: string | null) => void;
  setSettingsOpen: (open: boolean) => void;
  setToast: (msg: string | null) => void;
  sendMessage: (text: string) => Promise<void>;
  replyCheckpoint: (text: string, optionId?: string) => Promise<void>;
  stopRun: () => Promise<void>;
  cancelCheckpoint: () => Promise<void>;
  buildWorkspaceContext: () => Record<string, any>;
}

let activeEventSource: EventSource | null = null;

function openEventStream(sessionId: string) {
  if (activeEventSource) {
    activeEventSource.close();
    activeEventSource = null;
  }
  if (!sessionId) return;
  const es = new EventSource(buildAuthedUrl(`/api/sessions/${encodeURIComponent(sessionId)}/events`));
  activeEventSource = es;

  const parseMsg = (ev: MessageEvent) => {
    try {
      return JSON.parse(ev.data);
    } catch {
      return null;
    }
  };

  es.addEventListener("turn_started", () => {
    useStudioStore.setState({ busy: true, toolFeed: [] });
  });

  es.addEventListener("plan_updated", (ev) => {
    const parsed = parseMsg(ev);
    if (parsed?.payload) {
      useStudioStore.setState({ plan: parsed.payload });
    }
  });

  es.addEventListener("tool_started", (ev) => {
    const parsed = parseMsg(ev);
    if (!parsed?.payload) return;
    const { call_id, tool } = parsed.payload;
    useStudioStore.setState((s) => ({
      toolFeed: [...s.toolFeed, { id: String(call_id || Math.random()), tool: String(tool), status: "running" }],
    }));
  });

  es.addEventListener("tool_finished", (ev) => {
    const parsed = parseMsg(ev);
    if (!parsed?.payload) return;
    const { call_id, ok, elapsed_ms, outputs } = parsed.payload;
    useStudioStore.setState((s) => ({
      toolFeed: s.toolFeed.map((item) =>
        item.id === String(call_id)
          ? { ...item, status: ok === false ? "error" : "ok", elapsedMs: elapsed_ms, outputs }
          : item
      ),
    }));
  });

  es.addEventListener("artifact_published", (ev) => {
    const parsed = parseMsg(ev);
    const p = parsed?.payload;
    if (!p?.path) return;
    if (p.kind === "vector" || p.kind === "raster") {
      void useStudioStore.getState().addLayerByPath(p.path, p.kind);
    } else if (p.kind === "figure") {
      void api.listFigures(sessionId).then((res) => {
        useStudioStore.setState({ figures: res.figures });
      });
    }
  });

  es.addEventListener("interaction_required", (ev) => {
    const parsed = parseMsg(ev);
    if (parsed?.payload) {
      useStudioStore.setState({ waiting: parsed.payload });
    }
  });

  es.addEventListener("usage_updated", (ev) => {
    const parsed = parseMsg(ev);
    if (parsed?.payload) {
      useStudioStore.setState({ usage: parsed.payload });
    }
  });

  es.addEventListener("session_settled", () => {
    void useStudioStore.getState().selectSession(sessionId);
    void useStudioStore.getState().refreshWorkspace();
  });

  es.addEventListener("error", (ev) => {
    if (ev instanceof MessageEvent && ev.data) {
      const parsed = parseMsg(ev);
      if (parsed?.payload?.error) {
        useStudioStore.setState({ busy: false, toast: String(parsed.payload.error) });
      }
    }
  });
}

export const useStudioStore = create<StudioState>((set, get) => ({
  ready: false,
  initError: null,
  isTauri: isTauriRuntime(),
  env: null,
  projectDir: "",
  files: [],
  attachedFiles: [],
  sessions: [],
  activeSessionId: "",
  busy: false,
  plan: { goal: "", steps: [] },
  waiting: null,
  messages: [],
  toolFeed: [],
  executions: [],
  figures: [],
  layers: [],
  activeTab: "map",
  mapTool: "pan",
  basemap: "offline",
  fitBoundsSeq: 0,
  fitBoundsTarget: null,
  identifyPopup: null,
  selectedLayerPaths: [],
  selectedFids: [],
  drawnBboxWgs84: null,
  drawnGeometryGeojson: null,
  clickedPointWgs84: null,
  figureAnnotations: [],
  executionPolicy: "auto",
  usage: { calls: 0, prompt_tokens: 0, cached_tokens: 0, completion_tokens: 0, cache_hit_ratio: 0, estimated_cny: 0 },
  attrLayerPath: null,
  selectedExecId: null,
  settingsOpen: false,
  toast: null,

  bootstrap: async () => {
    try {
      await initBackendConnection();
      const [env, sessRes] = await Promise.all([api.getEnv(), api.listSessions()]);
      let sid = sessRes.sessions[0]?.session_id || "";
      if (!sid) {
        const created = await api.createSession();
        sid = created.session_id;
      }
      set({
        ready: true,
        initError: null,
        isTauri: isTauriRuntime(),
        env,
        projectDir: env.project_dir,
        sessions: sessRes.sessions,
        settingsOpen: !env.credentials.configured,
      });
      await get().selectSession(sid);
      await get().refreshWorkspace();
    } catch (err: any) {
      set({ ready: false, initError: err?.message || "连接后端服务失败" });
    }
  },

  refreshWorkspace: async () => {
    const sid = get().activeSessionId;
    const [filesRes, sessRes, env] = await Promise.all([
      api.listFiles(sid || undefined),
      api.listSessions(),
      api.getEnv(),
    ]);
    set({
      projectDir: filesRes.project_dir,
      files: filesRes.items,
      attachedFiles: filesRes.attached || [],
      sessions: sessRes.sessions,
      env,
    });
  },

  switchProject: async (dir: string) => {
    await api.selectWorkspace(dir);
    set({ layers: [], figures: [], selectedLayerPaths: [], drawnBboxWgs84: null, drawnGeometryGeojson: null });
    const sessRes = await api.listSessions();
    let sid = sessRes.sessions[0]?.session_id || "";
    if (!sid) {
      sid = (await api.createSession()).session_id;
    }
    await get().selectSession(sid);
    await get().refreshWorkspace();
  },

  selectSession: async (sessionId: string) => {
    const det = await api.getSessionDetail(sessionId);
    set({
      activeSessionId: sessionId,
      busy: Boolean(det.busy),
      plan: det.plan || { goal: "", steps: [] },
      waiting: det.waiting || null,
      messages: det.messages || [],
      executions: det.executions || [],
      figures: det.figures || [],
      usage: det.usage || { calls: 0, prompt_tokens: 0, cached_tokens: 0, completion_tokens: 0, cache_hit_ratio: 0, estimated_cny: 0 },
    });
    openEventStream(sessionId);
    for (const lyr of det.layers || []) {
      const exists = get().layers.some((x) => x.path === lyr.path);
      if (!exists) {
        void get().addLayerByPath(lyr.path, lyr.kind);
      }
    }
  },

  createNewSession: async (name?: string) => {
    const res = await api.createSession(name);
    set({
      layers: [],
      figures: [],
      toolFeed: [],
      selectedLayerPaths: [],
      selectedFids: [],
      figureAnnotations: [],
    });
    await get().selectSession(res.session_id);
    await get().refreshWorkspace();
  },

  attachAndAddLayer: async (filePath: string) => {
    const att = await api.attachFile(filePath);
    await get().refreshWorkspace();
    if (att.kind === "vector" || att.kind === "raster") {
      await get().addLayerByPath(att.path, att.kind);
    } else {
      set({ toast: `已附加文件：${att.name}` });
    }
  },

  addLayerByPath: async (filePath: string, kindHint?: "vector" | "raster") => {
    const existing = get().layers.find((l) => l.path === filePath);
    const id = existing?.id || `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    const color = existing?.color || LAYER_COLORS[get().layers.length % LAYER_COLORS.length];
    try {
      const meta = await api.getLayerMeta(filePath);
      if (meta.kind === "container" && meta.layers?.length) {
        for (const sub of meta.layers.slice(0, 4)) {
          await get().addLayerByPath(sub.source, "vector");
        }
        return;
      }
      const kind: "vector" | "raster" = kindHint || (meta.kind === "raster" ? "raster" : "vector");
      const name = filePath.split(/[\\/]/).pop() || filePath;
      const baseLayer: LayerItem = {
        id,
        path: filePath,
        name,
        kind,
        visible: existing?.visible ?? true,
        opacity: existing?.opacity ?? (kind === "raster" ? 0.85 : 0.78),
        color,
        styleField: existing?.styleField ?? null,
        breaks: existing?.breaks ?? [],
        palette: RAMP_PALETTES,
        band: existing?.band ?? 1,
        bandCount: meta.bands?.length || 1,
        colormap: existing?.colormap ?? "viridis",
        bboxWgs84: meta.bbox_wgs84 || null,
        fields: (meta.fields || []).map((f: any) => f.name || String(f)),
        geometryType: meta.geometry_type,
        totalFeatures: meta.feature_count,
        loading: true,
      };
      set((s) => ({
        layers: existing ? s.layers.map((l) => (l.id === id ? baseLayer : l)) : [baseLayer, ...s.layers],
      }));
      if (kind === "vector") {
        const gj = await api.getVectorGeojson(filePath, { zoom: 9, max_features: 5000 });
        const b = gj.meta?.bbox_wgs84 || meta.bbox_wgs84 || null;
        set((s) => ({
          layers: s.layers.map((l) =>
            l.id === id
              ? {
                  ...l,
                  geojson: gj,
                  truncated: Boolean(gj.meta?.truncated),
                  bboxWgs84: b,
                  fields: gj.meta?.fields || l.fields,
                  loading: false,
                }
              : l
          ),
          ...(b && !existing ? { fitBoundsTarget: b, fitBoundsSeq: s.fitBoundsSeq + 1 } : {}),
        }));
      } else {
        const url = buildAuthedUrl("/api/spatial/raster/preview", {
          path: filePath,
          band: baseLayer.band,
          colormap: baseLayer.colormap,
          width: 1024,
          height: 1024,
          _ts: Date.now(),
        });
        const b = meta.bbox_wgs84 || null;
        set((s) => ({
          layers: s.layers.map((l) =>
            l.id === id ? { ...l, rasterUrl: url, rasterBounds: b || undefined, loading: false } : l
          ),
          ...(b && !existing ? { fitBoundsTarget: b, fitBoundsSeq: s.fitBoundsSeq + 1 } : {}),
        }));
      }
    } catch (err: any) {
      set({ toast: `加载图层失败 (${filePath.split(/[\\/]/).pop()}): ${err?.message || err}` });
    }
  },

  toggleLayerVisible: (id) =>
    set((s) => ({ layers: s.layers.map((l) => (l.id === id ? { ...l, visible: !l.visible } : l)) })),

  setLayerOpacity: (id, opacity) =>
    set((s) => ({ layers: s.layers.map((l) => (l.id === id ? { ...l, opacity } : l)) })),

  moveLayer: (id, dir) =>
    set((s) => {
      const idx = s.layers.findIndex((l) => l.id === id);
      const next = idx + dir;
      if (idx < 0 || next < 0 || next >= s.layers.length) return {};
      const copy = [...s.layers];
      const [item] = copy.splice(idx, 1);
      copy.splice(next, 0, item);
      return { layers: copy };
    }),

  removeLayer: (id) => set((s) => ({ layers: s.layers.filter((l) => l.id !== id) })),

  zoomToLayer: (bbox) => {
    if (!bbox) return;
    set((s) => ({ fitBoundsTarget: bbox, fitBoundsSeq: s.fitBoundsSeq + 1, activeTab: "map" }));
  },

  styleVectorLayerByField: async (id, field) => {
    const lyr = get().layers.find((l) => l.id === id);
    if (!lyr) return;
    if (!field) {
      set((s) => ({ layers: s.layers.map((l) => (l.id === id ? { ...l, styleField: null, breaks: [] } : l)) }));
      return;
    }
    const res = await api.getAttributes(lyr.path, { page: 1, page_size: 10, stats_field: field });
    const breaks: number[] = res.stats?.quantile_breaks || [];
    set((s) => ({ layers: s.layers.map((l) => (l.id === id ? { ...l, styleField: field, breaks } : l)) }));
  },

  updateRasterStyle: (id, band, colormap) => {
    set((s) => ({
      layers: s.layers.map((l) =>
        l.id === id
          ? {
              ...l,
              band,
              colormap,
              rasterUrl: buildAuthedUrl("/api/spatial/raster/preview", {
                path: l.path,
                band,
                colormap,
                width: 1024,
                height: 1024,
                _ts: Date.now(),
              }),
            }
          : l
      ),
    }));
  },

  toggleLayerSelectedForContext: (path) =>
    set((s) => ({
      selectedLayerPaths: s.selectedLayerPaths.includes(path)
        ? s.selectedLayerPaths.filter((x) => x !== path)
        : [...s.selectedLayerPaths, path],
    })),

  setActiveTab: (activeTab) => set({ activeTab }),
  setMapTool: (mapTool) => set({ mapTool }),
  setBasemap: (basemap) => set({ basemap }),
  setIdentifyPopup: (identifyPopup) => set({ identifyPopup }),
  setSelectedFids: (selectedFids) => set({ selectedFids }),
  setDrawnAoi: (drawnBboxWgs84, drawnGeometryGeojson = null) => set({ drawnBboxWgs84, drawnGeometryGeojson }),
  setClickedPoint: (clickedPointWgs84) => set({ clickedPointWgs84 }),
  addFigureAnnotation: (ann) => set((s) => ({ figureAnnotations: [...s.figureAnnotations, ann] })),
  removeFigureAnnotation: (id) => set((s) => ({ figureAnnotations: s.figureAnnotations.filter((a) => a.id !== id) })),
  setExecutionPolicy: (executionPolicy) => set({ executionPolicy }),
  setAttrLayerPath: (attrLayerPath) => set({ attrLayerPath }),
  setSelectedExecId: (selectedExecId) => set({ selectedExecId }),
  setSettingsOpen: (settingsOpen) => set({ settingsOpen }),
  setToast: (toast) => set({ toast }),

  buildWorkspaceContext: () => {
    const s = get();
    return {
      project_path: s.projectDir || undefined,
      selected_layers: s.selectedLayerPaths.length ? s.selectedLayerPaths : s.layers.filter((l) => l.visible).map((l) => l.path),
      visible_layers: s.layers.filter((l) => l.visible).map((l) => l.path),
      selected_feature_ids: s.selectedFids,
      drawn_bbox_wgs84: s.drawnBboxWgs84,
      drawn_geometry_geojson: s.drawnGeometryGeojson,
      clicked_point_wgs84: s.clickedPointWgs84,
      figure_annotations: s.figureAnnotations.map(({ figure_path, norm_bbox, note, target_gid }) => ({
        figure_path,
        norm_bbox,
        note,
        ...(target_gid ? { target_gid } : {}),
      })),
      execution_policy: s.executionPolicy,
    };
  },

  sendMessage: async (text: string) => {
    const s = get();
    if (!s.activeSessionId) return;
    set({
      busy: true,
      messages: [...s.messages, { role: "user", origin: "user", content: text }],
    });
    try {
      await api.sendMessage(s.activeSessionId, text, s.buildWorkspaceContext());
      set({ figureAnnotations: [] });
    } catch (err: any) {
      set({ busy: false, toast: err?.message || "发送失败" });
    }
  },

  replyCheckpoint: async (text: string, optionId?: string) => {
    const s = get();
    if (!s.activeSessionId || !s.waiting) return;
    set({ busy: true });
    try {
      await api.replyCheckpoint(s.activeSessionId, {
        text,
        option_id: optionId,
        request_id: s.waiting.request_id,
        workspace_context: s.buildWorkspaceContext(),
      });
      set({ waiting: null, figureAnnotations: [] });
    } catch (err: any) {
      set({ busy: false, toast: err?.message || "提交检查点回复失败" });
    }
  },

  stopRun: async () => {
    const sid = get().activeSessionId;
    if (!sid) return;
    await api.stopSession(sid);
    set({ toast: "正在停止当前任务并安全回收子进程…" });
  },

  cancelCheckpoint: async () => {
    const sid = get().activeSessionId;
    if (!sid) return;
    await api.cancelCheckpoint(sid);
    await get().selectSession(sid);
  },
}));
