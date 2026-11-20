import { useEffect, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Circle,
  Compass,
  Crosshair,
  FileCode2,
  Image as ImageIcon,
  Layers,
  Loader2,
  Send,
  Square,
  X,
} from "lucide-react";
import { useStudioStore } from "../store/useStudioStore";

export function ChatPanel() {
  const {
    plan,
    messages,
    toolFeed,
    busy,
    waiting,
    selectedLayerPaths,
    selectedFids,
    drawnBboxWgs84,
    clickedPointWgs84,
    figureAnnotations,
    sendMessage,
    replyCheckpoint,
    stopRun,
    cancelCheckpoint,
    toggleLayerSelectedForContext,
    setSelectedFids,
    setDrawnAoi,
    setClickedPoint,
    removeFigureAnnotation,
    addLayerByPath,
    setActiveTab,
    setSelectedExecId,
  } = useStudioStore();

  const [input, setInput] = useState("");
  const [planOpen, setPlanOpen] = useState(true);
  const [customReply, setCustomReply] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages.length, toolFeed.length, waiting]);

  const handleSend = async (e?: React.FormEvent) => {
    e?.preventDefault();
    const text = input.trim();
    if (!text) return;
    setInput("");
    if (waiting) {
      await replyCheckpoint(text);
    } else {
      await sendMessage(text);
    }
  };

  const completedSteps = plan.steps.filter((s) => s.status === "completed").length;

  const checkpointTitle: Record<string, string> = {
    plan_approval: "执行方案审批",
    cartography_review: "成图审阅与交互精修",
    parameter_tuning: "分析参数确认",
    clarification: "数据与口径确认",
  };

  return (
    <section className="flex flex-col h-full bg-white border-r border-slate-200 min-w-0">
      {plan.steps.length > 0 && (
        <div className="border-b border-slate-200 bg-slate-50/70 shrink-0">
          <button
            onClick={() => setPlanOpen((v) => !v)}
            className="w-full px-3 py-2 flex items-center justify-between text-xs font-medium text-slate-700 hover:bg-slate-100 cursor-pointer"
          >
            <div className="flex items-center gap-1.5 min-w-0">
              {planOpen ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
              <span className="truncate">{plan.goal || "执行计划"}</span>
            </div>
            <span className="text-[11px] px-1.5 py-0.5 rounded bg-sky-100 text-sky-700 shrink-0">
              {completedSteps}/{plan.steps.length}
            </span>
          </button>
          {planOpen && (
            <div className="px-3 pb-2.5 space-y-1 max-h-36 overflow-y-auto">
              {plan.steps.map((step, i) => (
                <div key={i} className="flex items-start gap-2 text-xs text-slate-700">
                  {step.status === "completed" ? (
                    <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 mt-0.5 shrink-0" />
                  ) : step.status === "in_progress" ? (
                    <Loader2 className="w-3.5 h-3.5 text-sky-500 animate-spin mt-0.5 shrink-0" />
                  ) : (
                    <Circle className="w-3.5 h-3.5 text-slate-300 mt-0.5 shrink-0" />
                  )}
                  <span className={step.status === "completed" ? "line-through text-slate-400" : ""}>{step.content}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3 text-sm">
        {messages.length === 0 && !busy && (
          <div className="p-4 rounded-xl bg-slate-50 border border-slate-200 text-slate-600 text-xs space-y-2">
            <div className="font-semibold text-slate-800 text-sm">开始空间分析与地图制图</div>
            <p>你可以把桌面上的 `.shp` / `.gpkg` / `.tif` 拖到右侧画布，点查属性、框选研究区，再让我执行分析并导出可编辑 SVG 成图。</p>
          </div>
        )}

        {messages.map((msg, idx) => {
          if (msg.role === "user" && msg.origin !== "program") {
            return (
              <div key={idx} className="flex justify-end">
                <div className="bg-sky-600 text-white rounded-2xl rounded-tr-sm px-3.5 py-2 max-w-[90%] text-xs whitespace-pre-wrap leading-relaxed shadow-sm">
                  {msg.content}
                </div>
              </div>
            );
          }

          if (msg.role === "assistant") {
            const calls: any[] = msg.tool_calls || [];
            if (calls.length > 0) {
              return (
                <div key={idx} className="space-y-1">
                  {calls.map((tc) => {
                    const fnName = tc.function?.name || "tool";
                    const toolMsg = messages.find((m, mIdx) => mIdx > idx && m.role === "tool" && m.tool_call_id === tc.id);
                    let parsed: any = null;
                    if (toolMsg && typeof toolMsg.content === "string") {
                      try {
                        parsed = JSON.parse(toolMsg.content);
                      } catch {
                        parsed = null;
                      }
                    }
                    const outputs: any[] = Array.isArray(parsed?.outputs) ? parsed.outputs : [];
                    return (
                      <div key={tc.id} className="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1.5 text-xs">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-mono text-slate-700 font-medium">{fnName}</span>
                          <div className="flex items-center gap-1.5">
                            {fnName === "run_python_script" && toolMsg?.execution_id && (
                              <button
                                onClick={() => {
                                  setSelectedExecId(toolMsg.execution_id);
                                  setActiveTab("code");
                                }}
                                className="text-[11px] text-sky-600 hover:underline flex items-center gap-0.5 cursor-pointer"
                              >
                                <FileCode2 className="w-3 h-3" /> 脚本
                              </button>
                            )}
                            {parsed && (
                              <span className={parsed.ok === false ? "text-rose-600" : "text-emerald-600"}>
                                {parsed.ok === false ? "异常" : "✓"}
                              </span>
                            )}
                          </div>
                        </div>
                        {outputs.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {outputs.slice(0, 6).map((out, oIdx) => {
                              const p = out?.path;
                              if (!p) return null;
                              const name = String(p).split(/[\\/]/).pop();
                              const isFig = /\.(png|svg|jpg)$/i.test(String(p));
                              const isMap = /\.(shp|gpkg|geojson|fgb|tif|tiff)$/i.test(String(p));
                              return (
                                <button
                                  key={oIdx}
                                  onClick={() => {
                                    if (isFig) setActiveTab("figures");
                                    else if (isMap) {
                                      void addLayerByPath(p);
                                      setActiveTab("map");
                                    }
                                  }}
                                  className="text-[11px] px-1.5 py-0.5 rounded bg-white border border-slate-200 text-slate-600 hover:border-sky-400 hover:text-sky-700 truncate max-w-[200px] cursor-pointer"
                                  title={p}
                                >
                                  {name}
                                </button>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              );
            }

            if (msg.content) {
              return (
                <div key={idx} className="bg-slate-100 text-slate-800 rounded-2xl rounded-tl-sm px-3.5 py-2.5 text-xs whitespace-pre-wrap leading-relaxed">
                  {msg.content}
                </div>
              );
            }
          }
          return null;
        })}

        {busy && (
          <div className="rounded-lg border border-sky-200 bg-sky-50/70 p-2.5 text-xs space-y-1.5">
            <div className="flex items-center gap-2 text-sky-700 font-medium">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Agent 正在思考并执行空间步骤…</span>
            </div>
            {toolFeed.map((t) => (
              <div key={t.id} className="flex items-center justify-between text-[11px] text-slate-600 font-mono pl-5">
                <span>{t.tool}</span>
                <span>{t.status === "running" ? "执行中" : `${((t.elapsedMs || 0) / 1000).toFixed(1)}s`}</span>
              </div>
            ))}
          </div>
        )}

        {waiting && !busy && (
          <div className="rounded-xl border-2 border-amber-400 bg-amber-50/80 p-3 space-y-2.5 shadow-sm">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-amber-900">
                {checkpointTitle[waiting.checkpoint_kind || "clarification"] || "人机确认检查点"}
              </span>
              <button onClick={() => void cancelCheckpoint()} className="text-[11px] text-slate-500 hover:text-rose-600 cursor-pointer">
                取消任务
              </button>
            </div>
            <p className="text-xs text-slate-800 whitespace-pre-wrap leading-relaxed">{waiting.question || waiting.summary}</p>
            {waiting.options && waiting.options.length > 0 && (
              <div className="space-y-1.5">
                {waiting.options.map((opt) => (
                  <button
                    key={opt.id}
                    onClick={() => void replyCheckpoint(customReply.trim(), opt.id)}
                    className={`w-full text-left px-3 py-2 rounded-lg border text-xs transition cursor-pointer ${
                      opt.recommended
                        ? "bg-white border-sky-500 hover:bg-sky-50 text-slate-900 font-medium"
                        : "bg-white/80 border-slate-200 hover:bg-white text-slate-700"
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span>{opt.label}</span>
                      {opt.recommended && <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-100 text-sky-700">推荐</span>}
                    </div>
                    {opt.description && <div className="text-[11px] text-slate-500 mt-0.5">{opt.description}</div>}
                  </button>
                ))}
              </div>
            )}
            <div className="flex gap-1.5">
              <input
                value={customReply}
                onChange={(e) => setCustomReply(e.target.value)}
                placeholder="或补充自定义意见（可同步在右侧成图上圈注）"
                className="flex-1 bg-white border border-amber-300 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:border-sky-500"
              />
              <button
                onClick={() => {
                  if (customReply.trim() || figureAnnotations.length > 0) {
                    void replyCheckpoint(customReply.trim() || "请根据附带的图上圈注继续修改。");
                    setCustomReply("");
                  }
                }}
                className="px-3 py-1.5 rounded bg-amber-600 hover:bg-amber-500 text-white text-xs font-medium cursor-pointer"
              >
                提交
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Context Chips Strip */}
      {(selectedLayerPaths.length > 0 ||
        drawnBboxWgs84 ||
        selectedFids.length > 0 ||
        clickedPointWgs84 ||
        figureAnnotations.length > 0) && (
        <div className="px-3 py-1.5 bg-slate-50 border-t border-slate-200 flex flex-wrap gap-1.5 shrink-0">
          {selectedLayerPaths.map((p) => (
            <span key={p} className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-sky-100 text-sky-800">
              <Layers className="w-3 h-3" />
              {p.split(/[\\/]/).pop()}
              <button onClick={() => toggleLayerSelectedForContext(p)} className="hover:text-rose-600 cursor-pointer">
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
          {drawnBboxWgs84 && (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-indigo-100 text-indigo-800">
              <Compass className="w-3 h-3" />
              AOI 范围
              <button onClick={() => setDrawnAoi(null, null)} className="hover:text-rose-600 cursor-pointer">
                <X className="w-3 h-3" />
              </button>
            </span>
          )}
          {selectedFids.length > 0 && (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800">
              FID x{selectedFids.length}
              <button onClick={() => setSelectedFids([])} className="hover:text-rose-600 cursor-pointer">
                <X className="w-3 h-3" />
              </button>
            </span>
          )}
          {clickedPointWgs84 && (
            <span className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-teal-100 text-teal-800">
              <Crosshair className="w-3 h-3" />
              {clickedPointWgs84[0].toFixed(3)}, {clickedPointWgs84[1].toFixed(3)}
              <button onClick={() => setClickedPoint(null)} className="hover:text-rose-600 cursor-pointer">
                <X className="w-3 h-3" />
              </button>
            </span>
          )}
          {figureAnnotations.map((ann) => (
            <span key={ann.id} className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full bg-rose-100 text-rose-800 max-w-[200px]">
              <ImageIcon className="w-3 h-3 shrink-0" />
              <span className="truncate">图注：{ann.note}</span>
              <button onClick={() => removeFigureAnnotation(ann.id)} className="hover:text-rose-950 shrink-0 cursor-pointer">
                <X className="w-3 h-3" />
              </button>
            </span>
          ))}
        </div>
      )}

      <form onSubmit={handleSend} className="p-2.5 border-t border-slate-200 bg-white flex items-end gap-2 shrink-0">
        <textarea
          rows={2}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void handleSend();
            }
          }}
          placeholder={waiting ? "输入对当前检查点的补充指令..." : "描述空间分析或制图任务（Enter 发送，Shift+Enter 换行）"}
          className="flex-1 resize-none border border-slate-300 rounded-lg px-3 py-2 text-xs focus:outline-none focus:border-sky-500"
        />
        {busy ? (
          <button
            type="button"
            onClick={() => void stopRun()}
            className="h-9 px-3 rounded-lg bg-rose-600 hover:bg-rose-500 text-white text-xs font-medium flex items-center gap-1.5 shrink-0 cursor-pointer"
            title="协作中止当前子进程并在原会话继续纠偏"
          >
            <Square className="w-3.5 h-3.5 fill-current" />
            停止并纠偏
          </button>
        ) : (
          <button
            type="submit"
            disabled={!input.trim()}
            className="h-9 px-3.5 rounded-lg bg-sky-600 hover:bg-sky-500 disabled:opacity-40 text-white text-xs font-medium flex items-center gap-1 shrink-0 cursor-pointer"
          >
            <Send className="w-3.5 h-3.5" />
            发送
          </button>
        )}
      </form>
    </section>
  );
}
