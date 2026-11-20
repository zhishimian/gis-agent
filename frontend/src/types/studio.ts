export type ExecutionPolicy = "auto" | "plan_first" | "step_review";
export type WorkspaceTab = "map" | "figures" | "code";
export type MapToolMode = "pan" | "identify" | "bbox" | "polygon" | "select_fid";
export type BasemapKind = "offline" | "positron" | "dark" | "osm";

export interface PlanStep {
  content: string;
  status: "pending" | "in_progress" | "completed";
}

export interface PlanSnapshot {
  goal: string;
  steps: PlanStep[];
}

export interface CheckpointOption {
  id: string;
  label: string;
  description?: string;
  recommended?: boolean;
}

export interface CheckpointRequest {
  request_id: string;
  checkpoint_kind?: "clarification" | "plan_approval" | "cartography_review" | "parameter_tuning" | string;
  summary: string;
  question?: string;
  options?: CheckpointOption[];
  reason?: string;
  artifacts?: string[];
  unresolved?: string[];
}

export interface UsageStats {
  calls: number;
  prompt_tokens: number;
  cached_tokens: number;
  completion_tokens: number;
  cache_hit_ratio: number;
  estimated_cny: number;
}

export interface EnvInfo {
  project_dir: string;
  has_qgis: boolean;
  qgis_dir: string | null;
  detected_qgis_dirs: string[];
  python: {
    executable: string;
    version: string;
    has_qgis: boolean;
    packages: Record<string, string>;
  };
  credentials: {
    configured: boolean;
    source: string;
    provider: string;
    model: string;
    base_url: string;
    api_key_env: string;
    keyring_backend: string | null;
  };
}

export interface WorkspaceFileItem {
  name: string;
  path: string;
  rel_path: string;
  is_dir: boolean;
  kind: string;
  bytes: number;
  is_spatial?: boolean;
  attached?: boolean;
}

export interface SessionSummary {
  session_id: string;
  busy: boolean;
  waiting: boolean;
  status: string;
  message_count: number;
  usage: UsageStats;
}

export interface FigureSvgLayer {
  id: string;
  semantic: boolean;
  child_count: number;
}

export interface FigureItem {
  id: string;
  name: string;
  version: number;
  directory: string;
  png_path: string | null;
  svg_path: string | null;
  preview_path: string | null;
  manifest_path: string | null;
  bytes: number;
  layout_diagnostics?: Record<string, any>;
  warnings?: string[];
  figure_meta?: { width_mm?: number; height_mm?: number; dpi?: number };
  svg_layers: FigureSvgLayer[];
}

export interface FigureAnnotation {
  id: string;
  figure_path: string;
  norm_bbox: [number, number, number, number];
  note: string;
  target_gid?: string;
}

export interface GeoJsonFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    properties?: Record<string, any> | null;
    geometry: Record<string, any> | null;
  }>;
  meta?: Record<string, any>;
}

export interface LayerItem {
  id: string;
  path: string;
  name: string;
  kind: "vector" | "raster";
  visible: boolean;
  opacity: number;
  color: string;
  styleField: string | null;
  breaks: number[];
  palette: string[];
  band: number;
  bandCount: number;
  colormap: string;
  bboxWgs84: [number, number, number, number] | null;
  fields: string[];
  geometryType?: string;
  totalFeatures?: number;
  truncated?: boolean;
  geojson?: GeoJsonFeatureCollection;
  rasterBounds?: [number, number, number, number];
  rasterUrl?: string;
  stats?: { min?: number | null; max?: number | null; vmin?: number | null; vmax?: number | null };
  loading?: boolean;
  error?: string;
}

export interface ToolActivity {
  id: string;
  tool: string;
  status: "running" | "ok" | "error";
  elapsedMs?: number;
  outputs?: any[];
}

export interface IdentifyResult {
  lon: number;
  lat: number;
  tolerance_m: number;
  results: Array<{
    path: string;
    type: "vector" | "raster";
    hits?: Array<{ fid: number; distance: number; properties: Record<string, any> }>;
    inside?: boolean;
    bands?: Array<{
      band: number;
      raw_value: number | null;
      physical_value: number | null;
      unit: string | null;
      is_nodata: boolean;
    }>;
  }>;
}

export interface ExecutionRow {
  execution_id: string;
  tool: string;
  status: string;
  elapsed_ms?: number;
  script_snapshot?: string;
  stdout_path?: string;
  stderr_path?: string;
  outputs?: Array<{ path?: string; kind?: string; bytes?: number }>;
}
