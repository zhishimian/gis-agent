import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import {
  ArrowDown,
  ArrowUp,
  BoxSelect,
  Check,
  Crosshair,
  Eye,
  EyeOff,
  FolderPlus,
  Hand,
  Hexagon,
  Layers,
  Maximize2,
  MousePointerClick,
  Table2,
  Trash2,
  X,
} from "lucide-react";
import { api } from "../api/client";
import { useStudioStore } from "../store/useStudioStore";
import type { BasemapKind, GeoJsonFeatureCollection, LayerItem } from "../types/studio";

function buildStyleSpec(basemap: BasemapKind): maplibregl.StyleSpecification {
  if (basemap === "offline") {
    return {
      version: 8,
      name: "OpenGIS Offline",
      sources: {},
      layers: [
        {
          id: "bg-offline",
          type: "background",
          paint: { "background-color": "#f3f5f8" },
        },
      ],
    };
  }
  const tiles: Record<Exclude<BasemapKind, "offline">, string[]> = {
    positron: ["https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png"],
    dark: ["https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png"],
    osm: ["https://tile.openstreetmap.org/{z}/{x}/{y}.png"],
  };
  return {
    version: 8,
    sources: {
      basemap: { type: "raster", tiles: tiles[basemap], tileSize: 256, maxzoom: 19 },
    },
    layers: [{ id: "basemap-tiles", type: "raster", source: "basemap" }],
  };
}

function rampFillExpression(layer: LayerItem): any {
  if (!layer.styleField || layer.breaks.length < 2) return layer.color;
  const expr: any[] = ["step", ["coalesce", ["to-number", ["get", layer.styleField]], 0], layer.palette[0]];
  for (let i = 1; i < Math.min(layer.breaks.length - 1, layer.palette.length); i++) {
    expr.push(layer.breaks[i], layer.palette[i]);
  }
  return expr;
}

export function MapCanvas() {
  const {
    isTauri,
    layers,
    files,
    basemap,
    mapTool,
    fitBoundsSeq,
    fitBoundsTarget,
    identifyPopup,
    selectedLayerPaths,
    selectedFids,
    attrLayerPath,
    setBasemap,
    setMapTool,
    setIdentifyPopup,
    setDrawnAoi,
    setClickedPoint,
    setSelectedFids,
    toggleLayerVisible,
    setLayerOpacity,
    moveLayer,
    removeLayer,
    zoomToLayer,
    styleVectorLayerByField,
    updateRasterStyle,
    toggleLayerSelectedForContext,
    addLayerByPath,
    attachAndAddLayer,
    setAttrLayerPath,
    setToast,
  } = useStudioStore();

  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const bboxStartRef = useRef<[number, number] | null>(null);
  const [bboxRect, setBboxRect] = useState<[number, number, number, number] | null>(null);
  const [polyVerts, setPolyVerts] = useState<Array<[number, number]>>([]);
  const [pickerOpen, setPickerOpen] = useState(false);

  // Attribute drawer state
  const [attrRows, setAttrRows] = useState<any[]>([]);
  const [attrFields, setAttrFields] = useState<string[]>([]);
  const [attrPage, setAttrPage] = useState(1);
  const [attrTotal, setAttrTotal] = useState(0);
  const [attrQuery, setAttrQuery] = useState("");

  // Initialize MapLibre
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: buildStyleSpec(basemap),
      center: [118.8, 32.1],
      zoom: 5,
      attributionControl: false,
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: true }), "bottom-right");
    map.addControl(new maplibregl.ScaleControl({ maxWidth: 120, unit: "metric" }), "bottom-left");
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Switch basemap cleanly then re-sync layers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setStyle(buildStyleSpec(basemap));
  }, [basemap]);

  // Fit bounds when triggered
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !fitBoundsTarget || fitBoundsTarget.length !== 4) return;
    const [w, s, e, n] = fitBoundsTarget;
    if ([w, s, e, n].every(Number.isFinite) && e >= w && n >= s) {
      map.fitBounds(
        [
          [w, s],
          [e, n],
        ],
        { padding: 36, duration: 550, maxZoom: 15 }
      );
    }
  }, [fitBoundsSeq]);

  // Sync OpenGIS layers into MapLibre style
  const syncMapLayers = () => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    const currentLayerIds = new Set<string>();
    const activeIds = new Set(layers.map((l) => l.id));

    for (const styleLyr of map.getStyle().layers || []) {
      if (styleLyr.id.startsWith("ogis-")) {
        const lid = styleLyr.id.split("-")[1];
        if (!activeIds.has(lid) && map.getLayer(styleLyr.id)) {
          map.removeLayer(styleLyr.id);
        }
      }
    }

    const ordered = [...layers].reverse(); // top layer renders last
    for (const lyr of ordered) {
      const srcId = `ogis-${lyr.id}`;
      const vis = lyr.visible ? "visible" : "none";
      if (lyr.kind === "vector" && lyr.geojson) {
        const existingSrc = map.getSource(srcId) as maplibregl.GeoJSONSource | undefined;
        if (!existingSrc) {
          map.addSource(srcId, { type: "geojson", data: lyr.geojson as any });
        } else {
          existingSrc.setData(lyr.geojson as any);
        }
        const fillId = `ogis-${lyr.id}-fill`;
        const lineId = `ogis-${lyr.id}-line`;
        const ptId = `ogis-${lyr.id}-pt`;
        const fillColor = rampFillExpression(lyr);
        if (!map.getLayer(fillId)) {
          map.addLayer({
            id: fillId,
            type: "fill",
            source: srcId,
            filter: ["in", ["geometry-type"], ["literal", ["Polygon", "MultiPolygon"]]],
            layout: { visibility: vis },
            paint: { "fill-color": fillColor, "fill-opacity": lyr.opacity * 0.55 },
          });
        } else {
          map.setLayoutProperty(fillId, "visibility", vis);
          map.setPaintProperty(fillId, "fill-color", fillColor);
          map.setPaintProperty(fillId, "fill-opacity", lyr.opacity * 0.55);
        }
        if (!map.getLayer(lineId)) {
          map.addLayer({
            id: lineId,
            type: "line",
            source: srcId,
            layout: { visibility: vis },
            paint: { "line-color": lyr.color, "line-width": 1.6, "line-opacity": lyr.opacity },
          });
        } else {
          map.setLayoutProperty(lineId, "visibility", vis);
          map.setPaintProperty(lineId, "line-opacity", lyr.opacity);
        }
        if (!map.getLayer(ptId)) {
          map.addLayer({
            id: ptId,
            type: "circle",
            source: srcId,
            filter: ["in", ["geometry-type"], ["literal", ["Point", "MultiPoint"]]],
            layout: { visibility: vis },
            paint: {
              "circle-color": fillColor,
              "circle-radius": 5,
              "circle-stroke-width": 1.2,
              "circle-stroke-color": "#ffffff",
              "circle-opacity": lyr.opacity,
            },
          });
        } else {
          map.setLayoutProperty(ptId, "visibility", vis);
          map.setPaintProperty(ptId, "circle-color", fillColor);
          map.setPaintProperty(ptId, "circle-opacity", lyr.opacity);
        }
        currentLayerIds.add(fillId);
      } else if (lyr.kind === "raster" && lyr.rasterUrl && lyr.rasterBounds) {
        const [w, s, e, n] = lyr.rasterBounds;
        const coords: [[number, number], [number, number], [number, number], [number, number]] = [
          [w, n],
          [e, n],
          [e, s],
          [w, s],
        ];
        const rId = `ogis-${lyr.id}-raster`;
        const existing = map.getSource(srcId) as maplibregl.ImageSource | undefined;
        if (!existing) {
          map.addSource(srcId, { type: "image", url: lyr.rasterUrl, coordinates: coords });
          map.addLayer({
            id: rId,
            type: "raster",
            source: srcId,
            layout: { visibility: vis },
            paint: { "raster-opacity": lyr.opacity, "raster-fade-duration": 0 },
          });
        } else {
          existing.updateImage({ url: lyr.rasterUrl, coordinates: coords });
          if (map.getLayer(rId)) {
            map.setLayoutProperty(rId, "visibility", vis);
            map.setPaintProperty(rId, "raster-opacity", lyr.opacity);
          }
        }
      }
    }

    // Drawn AOI preview overlay
    const aoiSrcId = "ogis-user-aoi";
    const state = useStudioStore.getState();
    const aoiGeom =
      state.drawnGeometryGeojson ||
      (state.drawnBboxWgs84
        ? {
            type: "Polygon",
            coordinates: [
              [
                [state.drawnBboxWgs84[0], state.drawnBboxWgs84[1]],
                [state.drawnBboxWgs84[2], state.drawnBboxWgs84[1]],
                [state.drawnBboxWgs84[2], state.drawnBboxWgs84[3]],
                [state.drawnBboxWgs84[0], state.drawnBboxWgs84[3]],
                [state.drawnBboxWgs84[0], state.drawnBboxWgs84[1]],
              ],
            ],
          }
        : null);
    const aoiData: GeoJsonFeatureCollection = aoiGeom
      ? { type: "FeatureCollection", features: [{ type: "Feature", properties: {}, geometry: aoiGeom as any }] }
      : { type: "FeatureCollection", features: [] };
    const existingAoi = map.getSource(aoiSrcId) as maplibregl.GeoJSONSource | undefined;
    if (!existingAoi) {
      map.addSource(aoiSrcId, { type: "geojson", data: aoiData });
      map.addLayer({ id: "ogis-user-aoi-fill", type: "fill", source: aoiSrcId, paint: { "fill-color": "#4f46e5", "fill-opacity": 0.14 } });
      map.addLayer({
        id: "ogis-user-aoi-line",
        type: "line",
        source: aoiSrcId,
        paint: { "line-color": "#4f46e5", "line-width": 2, "line-dasharray": [2, 2] },
      });
    } else {
      existingAoi.setData(aoiData);
    }
  };

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (map.isStyleLoaded()) {
      syncMapLayers();
    } else {
      const onStyle = () => syncMapLayers();
      map.once("styledata", onStyle);
      return () => {
        map.off("styledata", onStyle);
      };
    }
  }, [layers, basemap, fitBoundsSeq]);

  // Interactive mouse tool handlers
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    if (mapTool === "bbox") {
      map.dragPan.disable();
    } else {
      map.dragPan.enable();
    }

    const onClick = async (e: maplibregl.MapMouseEvent) => {
      const { lng, lat } = e.lngLat;
      if (mapTool === "identify") {
        const visLayers = layers.filter((l) => l.visible).map((l) => ({ path: l.path, type: l.kind }));
        if (!visLayers.length) {
          setToast("请先开启至少一个可见图层");
          return;
        }
        try {
          const res = await api.identify({ lon: lng, lat, zoom: map.getZoom(), layers: visLayers });
          setIdentifyPopup(res);
        } catch (err: any) {
          setToast(err?.message || "Identify 查询失败");
        }
      } else if (mapTool === "select_fid") {
        const feats = map.queryRenderedFeatures(e.point).filter((f) => f.layer.id.startsWith("ogis-"));
        const fid = feats[0]?.properties?._fid;
        if (typeof fid === "number") {
          setSelectedFids(selectedFids.includes(fid) ? selectedFids.filter((x) => x !== fid) : [...selectedFids, fid]);
        }
      } else if (mapTool === "polygon") {
        setPolyVerts((prev) => [...prev, [Number(lng.toFixed(6)), Number(lat.toFixed(6))]]);
      }
    };

    const onMouseDown = (e: maplibregl.MapMouseEvent) => {
      if (mapTool !== "bbox") return;
      bboxStartRef.current = [e.point.x, e.point.y];
      setBboxRect([e.point.x, e.point.y, e.point.x, e.point.y]);
    };

    const onMouseMove = (e: maplibregl.MapMouseEvent) => {
      if (mapTool !== "bbox" || !bboxStartRef.current) return;
      const [sx, sy] = bboxStartRef.current;
      setBboxRect([sx, sy, e.point.x, e.point.y]);
    };

    const onMouseUp = (e: maplibregl.MapMouseEvent) => {
      if (mapTool !== "bbox" || !bboxStartRef.current) return;
      const [sx, sy] = bboxStartRef.current;
      bboxStartRef.current = null;
      setBboxRect(null);
      if (Math.abs(e.point.x - sx) < 6 || Math.abs(e.point.y - sy) < 6) return;
      const sw = map.unproject([Math.min(sx, e.point.x), Math.max(sy, e.point.y)]);
      const ne = map.unproject([Math.max(sx, e.point.x), Math.min(sy, e.point.y)]);
      setDrawnAoi([
        Number(sw.lng.toFixed(6)),
        Number(sw.lat.toFixed(6)),
        Number(ne.lng.toFixed(6)),
        Number(ne.lat.toFixed(6)),
      ]);
      setMapTool("pan");
      syncMapLayers();
    };

    map.on("click", onClick);
    map.on("mousedown", onMouseDown);
    map.on("mousemove", onMouseMove);
    map.on("mouseup", onMouseUp);
    return () => {
      map.off("click", onClick);
      map.off("mousedown", onMouseDown);
      map.off("mousemove", onMouseMove);
      map.off("mouseup", onMouseUp);
      map.dragPan.enable();
    };
  }, [mapTool, layers, selectedFids]);

  // Tauri native drag-and-drop absolute file path support
  useEffect(() => {
    if (!isTauri) return;
    let unlisten: (() => void) | null = null;
    void (async () => {
      const { getCurrentWebviewWindow } = await import("@tauri-apps/api/webviewWindow");
      unlisten = await getCurrentWebviewWindow().onDragDropEvent(async (event) => {
        if (event.payload.type === "drop") {
          for (const filePath of event.payload.paths) {
            await attachAndAddLayer(filePath);
          }
        }
      });
    })();
    return () => {
      unlisten?.();
    };
  }, [isTauri]);

  // Load attributes drawer when active
  useEffect(() => {
    if (!attrLayerPath) return;
    void (async () => {
      try {
        const res = await api.getAttributes(attrLayerPath, { page: attrPage, page_size: 50, query: attrQuery || undefined });
        setAttrFields(res.fields || []);
        setAttrRows(res.rows || []);
        setAttrTotal(res.total || 0);
      } catch (err: any) {
        setToast(err?.message || "读取属性表失败");
      }
    })();
  }, [attrLayerPath, attrPage, attrQuery]);

  const finishPolygon = () => {
    if (polyVerts.length < 3) return;
    const ring = [...polyVerts, polyVerts[0]];
    const lons = ring.map((c) => c[0]);
    const lats = ring.map((c) => c[1]);
    setDrawnAoi(
      [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)],
      { type: "Polygon", coordinates: [ring] }
    );
    setPolyVerts([]);
    setMapTool("pan");
    syncMapLayers();
  };

  const spatialFiles = files.filter((f) => f.is_spatial);

  return (
    <div className="h-full flex flex-col relative">
      {/* Map Toolbar */}
      <div className="h-10 bg-white border-b border-slate-200 px-3 flex items-center justify-between gap-2 text-xs shrink-0">
        <div className="flex items-center gap-1">
          {[
            { id: "pan" as const, icon: Hand, label: "漫游" },
            { id: "identify" as const, icon: Crosshair, label: "Identify 点查" },
            { id: "bbox" as const, icon: BoxSelect, label: "框选 AOI" },
            { id: "polygon" as const, icon: Hexagon, label: "绘制多边形" },
            { id: "select_fid" as const, icon: MousePointerClick, label: "点选要素" },
          ].map((t) => {
            const Icon = t.icon;
            return (
              <button
                key={t.id}
                onClick={() => setMapTool(t.id)}
                className={`px-2 py-1 rounded flex items-center gap-1 transition cursor-pointer ${
                  mapTool === t.id ? "bg-sky-600 text-white" : "text-slate-600 hover:bg-slate-100"
                }`}
              >
                <Icon className="w-3.5 h-3.5" />
                <span>{t.label}</span>
              </button>
            );
          })}
          {mapTool === "polygon" && polyVerts.length >= 3 && (
            <button onClick={finishPolygon} className="ml-1 px-2 py-1 rounded bg-indigo-600 text-white flex items-center gap-1 cursor-pointer">
              <Check className="w-3.5 h-3.5" /> 完成绘区 ({polyVerts.length})
            </button>
          )}
        </div>

        <div className="flex items-center gap-2">
          <select
            value={basemap}
            onChange={(e) => setBasemap(e.target.value as BasemapKind)}
            className="border border-slate-300 rounded px-2 py-1 text-xs bg-white"
          >
            <option value="offline">离线纯色底图</option>
            <option value="positron">浅色 Carto 底图</option>
            <option value="dark">深色 Carto 底图</option>
            <option value="osm">OpenStreetMap</option>
          </select>

          <button
            onClick={async () => {
              if (isTauri) {
                const picked = await api.pickNativeSpatialFiles();
                for (const p of picked) await attachAndAddLayer(p);
              } else {
                setPickerOpen((v) => !v);
              }
            }}
            className="px-2.5 py-1 rounded bg-slate-900 text-white hover:bg-slate-800 flex items-center gap-1 cursor-pointer"
          >
            <FolderPlus className="w-3.5 h-3.5" /> 加载数据
          </button>
        </div>
      </div>

      <div className="flex-1 relative min-h-0">
        <div ref={containerRef} className={`w-full h-full ${mapTool !== "pan" ? "cursor-crosshair" : ""}`} />

        {/* BBox visual overlay */}
        {bboxRect && (
          <div
            style={{
              left: Math.min(bboxRect[0], bboxRect[2]),
              top: Math.min(bboxRect[1], bboxRect[3]),
              width: Math.abs(bboxRect[2] - bboxRect[0]),
              height: Math.abs(bboxRect[3] - bboxRect[1]),
            }}
            className="absolute border-2 border-indigo-600 bg-indigo-500/15 pointer-events-none z-10"
          />
        )}

        {/* Floating Layer Manager */}
        <div className="absolute top-3 left-3 z-10 w-64 max-h-[70%] bg-white/95 backdrop-blur rounded-xl shadow-lg border border-slate-200 flex flex-col overflow-hidden text-xs">
          <div className="px-3 py-2 bg-slate-50 border-b border-slate-200 flex items-center justify-between font-semibold text-slate-700">
            <span className="flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-sky-600" /> 图层 ({layers.length})
            </span>
            {spatialFiles.length > 0 && (
              <button onClick={() => setPickerOpen((v) => !v)} className="text-[11px] font-normal text-sky-600 hover:underline cursor-pointer">
                工作区数据 ({spatialFiles.length})
              </button>
            )}
          </div>

          <div className="overflow-y-auto p-2 space-y-2">
            {layers.length === 0 ? (
              <div className="text-[11px] text-slate-400 p-2 text-center">暂无加载图层，点击右上「加载数据」或让 Agent 运行分析</div>
            ) : (
              layers.map((lyr, idx) => (
                <div key={lyr.id} className="p-2 rounded-lg border border-slate-200 bg-white space-y-1.5">
                  <div className="flex items-center justify-between gap-1">
                    <button onClick={() => toggleLayerVisible(lyr.id)} className="flex items-center gap-1.5 min-w-0 font-medium text-slate-800 cursor-pointer">
                      {lyr.visible ? <Eye className="w-3.5 h-3.5 text-sky-600 shrink-0" /> : <EyeOff className="w-3.5 h-3.5 text-slate-400 shrink-0" />}
                      <span className="truncate" title={lyr.path}>{lyr.name}</span>
                    </button>
                    <div className="flex items-center gap-0.5 shrink-0 text-slate-400">
                      <button onClick={() => zoomToLayer(lyr.bboxWgs84)} title="缩放到图层" className="p-0.5 hover:text-slate-700 cursor-pointer">
                        <Maximize2 className="w-3 h-3" />
                      </button>
                      {lyr.kind === "vector" && (
                        <button onClick={() => setAttrLayerPath(lyr.path)} title="查看属性表" className="p-0.5 hover:text-slate-700 cursor-pointer">
                          <Table2 className="w-3 h-3" />
                        </button>
                      )}
                      {idx > 0 && (
                        <button onClick={() => moveLayer(lyr.id, -1)} className="p-0.5 hover:text-slate-700 cursor-pointer">
                          <ArrowUp className="w-3 h-3" />
                        </button>
                      )}
                      {idx < layers.length - 1 && (
                        <button onClick={() => moveLayer(lyr.id, 1)} className="p-0.5 hover:text-slate-700 cursor-pointer">
                          <ArrowDown className="w-3 h-3" />
                        </button>
                      )}
                      <button onClick={() => removeLayer(lyr.id)} className="p-0.5 hover:text-rose-600 cursor-pointer">
                        <Trash2 className="w-3 h-3" />
                      </button>
                    </div>
                  </div>

                  <div className="flex items-center gap-2 text-[11px] text-slate-500">
                    <span>透明</span>
                    <input
                      type="range"
                      min={0.1}
                      max={1}
                      step={0.05}
                      value={lyr.opacity}
                      onChange={(e) => setLayerOpacity(lyr.id, Number(e.target.value))}
                      className="flex-1 accent-sky-600"
                    />
                    <button
                      onClick={() => toggleLayerSelectedForContext(lyr.path)}
                      className={`px-1.5 py-0.5 rounded border text-[10px] cursor-pointer ${
                        selectedLayerPaths.includes(lyr.path) ? "bg-sky-600 text-white border-sky-600" : "border-slate-300 text-slate-600"
                      }`}
                    >
                      {selectedLayerPaths.includes(lyr.path) ? "已绑定" : "引用"}
                    </button>
                  </div>

                  {lyr.kind === "vector" && lyr.fields.length > 0 && (
                    <select
                      value={lyr.styleField || ""}
                      onChange={(e) => void styleVectorLayerByField(lyr.id, e.target.value || null)}
                      className="w-full border border-slate-200 rounded px-1.5 py-0.5 text-[11px] bg-slate-50"
                    >
                      <option value="">单色填充 ({lyr.totalFeatures ?? "?"} 要素)</option>
                      {lyr.fields.slice(0, 12).map((f) => (
                        <option key={f} value={f}>按 {f} 分级设色</option>
                      ))}
                    </select>
                  )}

                  {lyr.kind === "raster" && (
                    <div className="flex gap-1">
                      <select
                        value={lyr.band}
                        onChange={(e) => updateRasterStyle(lyr.id, Number(e.target.value), lyr.colormap)}
                        className="flex-1 border border-slate-200 rounded px-1 py-0.5 text-[11px] bg-slate-50"
                      >
                        {lyr.bandCount >= 3 && <option value={0}>RGB 合成</option>}
                        {Array.from({ length: lyr.bandCount }, (_, i) => i + 1).map((b) => (
                          <option key={b} value={b}>波段 {b}</option>
                        ))}
                      </select>
                      <select
                        value={lyr.colormap}
                        onChange={(e) => updateRasterStyle(lyr.id, lyr.band, e.target.value)}
                        className="flex-1 border border-slate-200 rounded px-1 py-0.5 text-[11px] bg-slate-50"
                      >
                        <option value="viridis">Viridis</option>
                        <option value="terrain">Terrain</option>
                        <option value="RdYlBu">RdYlBu</option>
                        <option value="magma">Magma</option>
                        <option value="cividis">Cividis</option>
                      </select>
                    </div>
                  )}

                  {lyr.truncated && (
                    <div className="text-[10px] text-amber-700 bg-amber-50 px-1.5 py-0.5 rounded">
                      要素较多，已视口抽稀显示
                    </div>
                  )}
                </div>
              ))
            )}
          </div>
        </div>

        {/* Workspace quick file picker dropdown */}
        {pickerOpen && (
          <div className="absolute top-3 right-3 z-20 w-72 bg-white rounded-xl shadow-xl border border-slate-200 p-3 text-xs space-y-2 max-h-72 overflow-y-auto">
            <div className="flex items-center justify-between font-semibold">
              <span>从当前目录加载</span>
              <button onClick={() => setPickerOpen(false)} className="cursor-pointer"><X className="w-3.5 h-3.5" /></button>
            </div>
            {spatialFiles.map((f) => (
              <button
                key={f.path}
                onClick={() => {
                  void addLayerByPath(f.path, f.kind === "raster" ? "raster" : "vector");
                  setPickerOpen(false);
                }}
                className="w-full text-left px-2 py-1.5 rounded hover:bg-sky-50 flex items-center justify-between cursor-pointer"
              >
                <span className="truncate">{f.rel_path}</span>
                <span className="text-[10px] uppercase text-slate-400">{f.kind}</span>
              </button>
            ))}
          </div>
        )}

        {/* Identify Popup */}
        {identifyPopup && (
          <div className="absolute bottom-4 right-4 z-20 w-80 max-h-80 bg-white rounded-xl shadow-2xl border border-slate-200 flex flex-col overflow-hidden text-xs">
            <div className="px-3 py-2 bg-slate-900 text-white flex items-center justify-between">
              <span className="font-mono">
                Identify ({identifyPopup.lon.toFixed(4)}, {identifyPopup.lat.toFixed(4)})
              </span>
              <button onClick={() => setIdentifyPopup(null)} className="cursor-pointer"><X className="w-3.5 h-3.5" /></button>
            </div>
            <div className="p-2.5 overflow-y-auto space-y-2.5">
              {identifyPopup.results.map((r, i) => (
                <div key={i} className="border border-slate-200 rounded-lg p-2 space-y-1">
                  <div className="font-semibold text-slate-700 truncate">{r.path.split(/[\\/]/).pop()}</div>
                  {r.type === "vector" && (!r.hits || r.hits.length === 0) && <div className="text-slate-400">未命中矢量要素</div>}
                  {r.hits?.map((h) => (
                    <div key={h.fid} className="bg-slate-50 rounded p-1.5 text-[11px] space-y-0.5">
                      <div className="font-mono text-sky-700">FID #{h.fid}</div>
                      {Object.entries(h.properties).slice(0, 8).map(([k, v]) => (
                        <div key={k} className="flex justify-between gap-2">
                          <span className="text-slate-500">{k}</span>
                          <span className="font-mono text-slate-800 truncate">{String(v)}</span>
                        </div>
                      ))}
                    </div>
                  ))}
                  {r.type === "raster" && r.bands?.map((b) => (
                    <div key={b.band} className="flex justify-between text-[11px] bg-slate-50 px-2 py-1 rounded">
                      <span>波段 {b.band}</span>
                      <span className="font-mono font-medium">
                        {b.is_nodata ? "NoData" : `${b.physical_value} ${b.unit || ""}`}
                      </span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
            <div className="px-2.5 py-2 border-t border-slate-200 bg-slate-50 flex justify-end">
              <button
                onClick={() => {
                  setClickedPoint([Number(identifyPopup.lon.toFixed(6)), Number(identifyPopup.lat.toFixed(6))]);
                  setIdentifyPopup(null);
                }}
                className="px-2.5 py-1 rounded bg-sky-600 text-white text-[11px] hover:bg-sky-500 cursor-pointer"
              >
                将此点位加入对话上下文
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Collapsible Attribute Table Drawer */}
      {attrLayerPath && (
        <div className="h-56 border-t border-slate-300 bg-white flex flex-col shrink-0 text-xs">
          <div className="px-3 py-1.5 bg-slate-50 border-b border-slate-200 flex items-center justify-between gap-2">
            <span className="font-semibold text-slate-700 truncate">
              属性表：{attrLayerPath.split(/[\\/]/).pop()}（共 {attrTotal} 条）
            </span>
            <div className="flex items-center gap-2">
              <input
                value={attrQuery}
                onChange={(e) => {
                  setAttrQuery(e.target.value);
                  setAttrPage(1);
                }}
                placeholder="筛选关键字..."
                className="border border-slate-300 rounded px-2 py-0.5 text-xs"
              />
              <button onClick={() => setAttrLayerPath(null)} className="text-slate-500 hover:text-slate-900 cursor-pointer">
                <X className="w-4 h-4" />
              </button>
            </div>
          </div>
          <div className="flex-1 overflow-auto">
            <table className="w-full text-left border-collapse text-[11px]">
              <thead className="sticky top-0 bg-slate-100 border-b border-slate-200">
                <tr>
                  <th className="px-2 py-1 font-mono">_fid</th>
                  {attrFields.map((f) => (
                    <th key={f} className="px-2 py-1 whitespace-nowrap">{f}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {attrRows.map((row) => (
                  <tr
                    key={row._fid}
                    onClick={() => row._bbox_wgs84 && zoomToLayer(row._bbox_wgs84)}
                    className="hover:bg-sky-50 cursor-pointer"
                  >
                    <td className="px-2 py-1 font-mono text-sky-700">{row._fid}</td>
                    {attrFields.map((f) => (
                      <td key={f} className="px-2 py-1 max-w-[180px] truncate">{String(row[f] ?? "")}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
