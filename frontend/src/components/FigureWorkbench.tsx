import { useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Columns2, ExternalLink, FolderOpen, Highlighter, SplitSquareHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import { api, buildAuthedUrl } from "../api/client";
import { useStudioStore } from "../store/useStudioStore";

export function FigureWorkbench() {
  const { figures, figureAnnotations, addFigureAnnotation, setToast } = useStudioStore();
  const [selectedIdx, setSelectedIdx] = useState(0);
  const [compareIdx, setCompareIdx] = useState(0);
  const [mode, setMode] = useState<"single" | "side" | "swipe">("single");
  const [swipePos, setSwipePos] = useState(50);
  const [zoom, setZoom] = useState(1);
  const [annotating, setAnnotating] = useState(false);
  const [dragBox, setDragBox] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);
  const [pendingBox, setPendingBox] = useState<[number, number, number, number] | null>(null);
  const [noteInput, setNoteInput] = useState("");
  const imgContainerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (figures.length > 0) {
      setSelectedIdx(figures.length - 1);
      setCompareIdx(Math.max(0, figures.length - 2));
    }
  }, [figures.length]);

  const current = figures[selectedIdx];
  const prevFig = figures[compareIdx];

  const figureImgUrl = (path: string | null) =>
    path ? buildAuthedUrl("/api/figures/file", { path, _t: figures.length }) : "";

  const startDraw = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!annotating || !imgContainerRef.current) return;
    const rect = imgContainerRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    setDragBox({ x0: x, y0: y, x1: x, y1: y });
  };

  const moveDraw = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!dragBox || !imgContainerRef.current) return;
    const rect = imgContainerRef.current.getBoundingClientRect();
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    setDragBox({ ...dragBox, x1: x, y1: y });
  };

  const endDraw = () => {
    if (!dragBox) return;
    const x0 = Math.min(dragBox.x0, dragBox.x1);
    const y0 = Math.min(dragBox.y0, dragBox.y1);
    const x1 = Math.max(dragBox.x0, dragBox.x1);
    const y1 = Math.max(dragBox.y0, dragBox.y1);
    setDragBox(null);
    if (x1 - x0 > 0.02 && y1 - y0 > 0.02) {
      setPendingBox([
        Number(x0.toFixed(3)),
        Number(y0.toFixed(3)),
        Number(x1.toFixed(3)),
        Number(y1.toFixed(3)),
      ]);
      setNoteInput("");
    }
  };

  const submitAnnotation = (e: React.FormEvent) => {
    e.preventDefault();
    if (!pendingBox || !noteInput.trim() || !current) return;
    addFigureAnnotation({
      id: `${Date.now()}`,
      figure_path: current.png_path || current.svg_path || "",
      norm_bbox: pendingBox,
      note: noteInput.trim(),
    });
    setPendingBox(null);
    setNoteInput("");
    setAnnotating(false);
    setToast("已将图上圈注挂载到对话输入框上方，可直接发送修改");
  };

  if (figures.length === 0) {
    return (
      <div className="h-full flex flex-col items-center justify-center text-slate-400 text-xs p-6">
        <p className="text-sm font-medium text-slate-600 mb-1">尚未生成正式专题成图</p>
        <p>当 Agent 调用 export_figure 导出 PNG 与可编辑 SVG 后，所有迭代版本将自动出现于此供审阅与圈注对比。</p>
      </div>
    );
  }

  const hygiene = current?.layout_diagnostics?.hygiene || {};
  const typography = current?.layout_diagnostics?.typography || {};
  const hygieneChecks = [
    { label: "无冗余堆叠副标题", warn: Boolean(hygiene.subtitle_detected_warning) },
    { label: "无白底贴片遮挡", warn: Boolean(hygiene.callout_box_warning) },
    { label: "无双刻度重叠", warn: Boolean(hygiene.duplicate_axis_ticks_warning) },
    { label: "无文字出界裁切", warn: Boolean(hygiene.clipped_text_warning || hygiene.frame_overflow_warning) },
    { label: "留白 Margin 均衡", warn: Boolean(current?.layout_diagnostics?.excessive_margin_warning) },
  ];

  return (
    <div className="h-full flex flex-col bg-slate-100">
      {/* Toolbar */}
      <div className="h-10 bg-white border-b border-slate-200 px-3 flex items-center justify-between gap-2 shrink-0 text-xs">
        <div className="flex items-center gap-1.5 overflow-x-auto">
          {figures.map((fig, idx) => (
            <button
              key={fig.id}
              onClick={() => setSelectedIdx(idx)}
              className={`px-2.5 py-1 rounded font-medium shrink-0 cursor-pointer ${
                idx === selectedIdx ? "bg-sky-600 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
              }`}
            >
              v{fig.version} · {fig.name}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-1.5 shrink-0">
          <button
            onClick={() => setAnnotating((v) => !v)}
            className={`px-2.5 py-1 rounded flex items-center gap-1 border cursor-pointer ${
              annotating ? "bg-rose-600 text-white border-rose-600" : "bg-white border-slate-300 text-slate-700 hover:bg-slate-50"
            }`}
          >
            <Highlighter className="w-3.5 h-3.5" />
            {annotating ? "拖拽画框中..." : "红框批注"}
          </button>

          {figures.length > 1 && (
            <>
              <button
                onClick={() => setMode((m) => (m === "side" ? "single" : "side"))}
                className={`p-1.5 rounded border cursor-pointer ${mode === "side" ? "bg-sky-100 border-sky-400 text-sky-700" : "border-slate-300"}`}
                title="并排对比"
              >
                <Columns2 className="w-3.5 h-3.5" />
              </button>
              <button
                onClick={() => setMode((m) => (m === "swipe" ? "single" : "swipe"))}
                className={`p-1.5 rounded border cursor-pointer ${mode === "swipe" ? "bg-sky-100 border-sky-400 text-sky-700" : "border-slate-300"}`}
                title="卷帘对比"
              >
                <SplitSquareHorizontal className="w-3.5 h-3.5" />
              </button>
            </>
          )}

          <button onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))} className="p-1.5 rounded border border-slate-300 cursor-pointer">
            <ZoomOut className="w-3.5 h-3.5" />
          </button>
          <span className="text-[11px] w-10 text-center">{Math.round(zoom * 100)}%</span>
          <button onClick={() => setZoom((z) => Math.min(3, z + 0.25))} className="p-1.5 rounded border border-slate-300 cursor-pointer">
            <ZoomIn className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="flex-1 flex min-h-0">
        {/* Main viewport */}
        <div className="flex-1 overflow-auto p-4 flex items-center justify-center relative">
          {mode === "single" && current && (
            <div
              ref={imgContainerRef}
              onMouseDown={startDraw}
              onMouseMove={moveDraw}
              onMouseUp={endDraw}
              style={{ transform: `scale(${zoom})`, transformOrigin: "center" }}
              className={`relative shadow-lg bg-white inline-block transition-transform ${annotating ? "cursor-crosshair" : ""}`}
            >
              <img
                src={figureImgUrl(current.png_path || current.svg_path)}
                alt={current.name}
                className="max-h-[75vh] max-w-full block select-none"
                draggable={false}
              />
              {/* Saved red-box annotations */}
              {figureAnnotations.map((ann) => {
                const [x0, y0, x1, y1] = ann.norm_bbox;
                return (
                  <div
                    key={ann.id}
                    style={{ left: `${x0 * 100}%`, top: `${y0 * 100}%`, width: `${(x1 - x0) * 100}%`, height: `${(y1 - y0) * 100}%` }}
                    className="absolute border-2 border-rose-500 bg-rose-500/15 pointer-events-none"
                  >
                    <span className="bg-rose-600 text-white text-[10px] px-1 py-0.5 rounded-br">{ann.note}</span>
                  </div>
                );
              })}
              {/* Active drag box */}
              {dragBox && (
                <div
                  style={{
                    left: `${Math.min(dragBox.x0, dragBox.x1) * 100}%`,
                    top: `${Math.min(dragBox.y0, dragBox.y1) * 100}%`,
                    width: `${Math.abs(dragBox.x1 - dragBox.x0) * 100}%`,
                    height: `${Math.abs(dragBox.y1 - dragBox.y0) * 100}%`,
                  }}
                  className="absolute border-2 border-dashed border-rose-500 bg-rose-400/20 pointer-events-none"
                />
              )}
            </div>
          )}

          {mode === "side" && current && prevFig && (
            <div className="grid grid-cols-2 gap-4 w-full h-full items-center">
              <div className="bg-white p-2 rounded shadow flex flex-col items-center">
                <span className="text-xs text-slate-500 mb-1">对照 v{prevFig.version}</span>
                <img src={figureImgUrl(prevFig.png_path || prevFig.svg_path)} className="max-h-[68vh] object-contain" />
              </div>
              <div className="bg-white p-2 rounded shadow flex flex-col items-center">
                <span className="text-xs font-medium text-sky-700 mb-1">当前 v{current.version}</span>
                <img src={figureImgUrl(current.png_path || current.svg_path)} className="max-h-[68vh] object-contain" />
              </div>
            </div>
          )}

          {mode === "swipe" && current && prevFig && (
            <div className="relative bg-white shadow-lg inline-block overflow-hidden">
              <img src={figureImgUrl(current.png_path || current.svg_path)} className="max-h-[75vh] block select-none" />
              <div
                style={{ width: `${swipePos}%` }}
                className="absolute inset-y-0 left-0 overflow-hidden border-r-2 border-sky-500"
              >
                <img src={figureImgUrl(prevFig.png_path || prevFig.svg_path)} className="max-h-[75vh] max-w-none block select-none" />
              </div>
              <input
                type="range"
                min={0}
                max={100}
                value={swipePos}
                onChange={(e) => setSwipePos(Number(e.target.value))}
                className="absolute bottom-3 left-4 right-4 z-10 accent-sky-600"
              />
            </div>
          )}

          {pendingBox && (
            <form
              onSubmit={submitAnnotation}
              className="absolute bottom-5 left-1/2 -translate-x-1/2 bg-white shadow-2xl border border-slate-200 rounded-xl p-3 w-96 space-y-2 z-20"
            >
              <div className="text-xs font-semibold text-rose-700">添加局部修改批注 [{pendingBox.join(", ")}]</div>
              <input
                autoFocus
                value={noteInput}
                onChange={(e) => setNoteInput(e.target.value)}
                placeholder="例如：苏州无锡注记重叠，将次级标注微移并减字号"
                className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:border-rose-500"
              />
              <div className="flex justify-end gap-2">
                <button type="button" onClick={() => setPendingBox(null)} className="px-2.5 py-1 text-xs border rounded">
                  取消
                </button>
                <button type="submit" className="px-3 py-1 text-xs rounded bg-rose-600 text-white">
                  挂载批注
                </button>
              </div>
            </form>
          )}
        </div>

        {/* Right inspector sidebar */}
        {current && (
          <aside className="w-64 bg-white border-l border-slate-200 p-3 overflow-y-auto space-y-4 text-xs shrink-0">
            <div>
              <h4 className="font-semibold text-slate-800 mb-2">版面卫生 5 项质检</h4>
              <div className="space-y-1.5">
                {hygieneChecks.map((chk) => (
                  <div key={chk.label} className="flex items-center gap-1.5">
                    {chk.warn ? (
                      <AlertTriangle className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                    ) : (
                      <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                    )}
                    <span className={chk.warn ? "text-amber-700 font-medium" : "text-slate-600"}>{chk.label}</span>
                  </div>
                ))}
              </div>
              {typography.font_sizes_pt?.length > 0 && (
                <div className="mt-2 text-[11px] text-slate-500">
                  字号层级：{typography.font_sizes_pt.join(" / ")} pt
                </div>
              )}
            </div>

            {current.svg_layers?.length > 0 && (
              <div>
                <h4 className="font-semibold text-slate-800 mb-1.5">SVG 语义图层 ({current.svg_layers.length})</h4>
                <div className="max-h-44 overflow-y-auto space-y-1">
                  {current.svg_layers.map((lyr) => (
                    <div key={lyr.id} className="flex items-center justify-between px-2 py-1 rounded bg-slate-50 font-mono text-[11px]">
                      <span className={lyr.semantic ? "text-sky-700 font-medium" : "text-slate-500"}>{lyr.id}</span>
                      <span className="text-slate-400">{lyr.child_count}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="space-y-1.5 pt-2 border-t border-slate-200">
              <button
                onClick={() => void api.revealOrOpen(current.png_path || current.svg_path || "", "reveal")}
                className="w-full py-1.5 px-2.5 rounded border border-slate-300 hover:bg-slate-50 flex items-center justify-center gap-1.5 cursor-pointer"
              >
                <FolderOpen className="w-3.5 h-3.5" /> 在资源管理器中显示
              </button>
              {current.svg_path && (
                <button
                  onClick={() => void api.revealOrOpen(current.svg_path!, "open")}
                  className="w-full py-1.5 px-2.5 rounded bg-sky-50 border border-sky-200 text-sky-700 hover:bg-sky-100 flex items-center justify-center gap-1.5 cursor-pointer"
                >
                  <ExternalLink className="w-3.5 h-3.5" /> 外部软件精修 SVG
                </button>
              )}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
