import { useEffect, useState } from "react";
import { Copy, FileCode2, FolderOpen, Layers } from "lucide-react";
import { api } from "../api/client";
import { useStudioStore } from "../store/useStudioStore";

export function CodeEvidencePanel() {
  const { activeSessionId, executions, selectedExecId, setSelectedExecId, files, attachedFiles, addLayerByPath, setActiveTab, setToast } =
    useStudioStore();

  const [scriptText, setScriptText] = useState("");
  const [logText, setLogText] = useState("");

  useEffect(() => {
    if (!activeSessionId || !selectedExecId) return;
    void (async () => {
      try {
        const [scr, errLog] = await Promise.all([
          api.getExecutions(activeSessionId, selectedExecId, "script"),
          api.getExecutions(activeSessionId, selectedExecId, "stderr"),
        ]);
        setScriptText(scr.text || "(无脚本快照)");
        setLogText(errLog.text || "");
      } catch {
        setScriptText("(读取执行详情失败)");
      }
    })();
  }, [activeSessionId, selectedExecId]);

  const scriptExecs = executions.filter((e) => e.tool === "run_python_script" || e.script_snapshot);

  return (
    <div className="h-full grid grid-cols-12 bg-slate-50">
      <div className="col-span-4 border-r border-slate-200 bg-white flex flex-col overflow-hidden">
        <div className="px-3 py-2 border-b border-slate-200 text-xs font-semibold text-slate-700">脚本执行记录</div>
        <div className="flex-1 overflow-y-auto divide-y divide-slate-100">
          {scriptExecs.length === 0 ? (
            <div className="p-4 text-xs text-slate-400">暂无 Python 脚本执行记录</div>
          ) : (
            scriptExecs.map((row) => (
              <button
                key={row.execution_id}
                onClick={() => setSelectedExecId(row.execution_id)}
                className={`w-full text-left px-3 py-2 text-xs hover:bg-slate-50 cursor-pointer ${
                  selectedExecId === row.execution_id ? "bg-sky-50 border-l-2 border-sky-600" : ""
                }`}
              >
                <div className="flex items-center justify-between font-mono">
                  <span className="font-medium text-slate-800">{row.execution_id}</span>
                  <span className={row.status === "succeeded" ? "text-emerald-600" : "text-rose-600"}>{row.status}</span>
                </div>
                <div className="text-[11px] text-slate-400 mt-0.5">{((row.elapsed_ms || 0) / 1000).toFixed(2)}s</div>
              </button>
            ))
          )}
        </div>

        <div className="px-3 py-2 border-y border-slate-200 text-xs font-semibold text-slate-700 bg-slate-50">
          工作文件夹与附加数据
        </div>
        <div className="h-52 overflow-y-auto p-2 space-y-1">
          {[...attachedFiles, ...files].map((f) => (
            <div key={f.path} className="flex items-center justify-between px-2 py-1 rounded hover:bg-slate-100 text-xs">
              <div className="flex items-center gap-1.5 min-w-0">
                {f.is_dir ? (
                  <FolderOpen className="w-3.5 h-3.5 text-amber-500 shrink-0" />
                ) : (
                  <Layers className="w-3.5 h-3.5 text-slate-400 shrink-0" />
                )}
                <span className="truncate" title={f.path}>
                  {f.rel_path || f.name}
                </span>
              </div>
              {f.is_spatial && (
                <button
                  onClick={() => {
                    void addLayerByPath(f.path, f.kind === "raster" ? "raster" : "vector");
                    setActiveTab("map");
                  }}
                  className="text-[11px] text-sky-600 hover:underline shrink-0 ml-2 cursor-pointer"
                >
                  上图
                </button>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="col-span-8 flex flex-col overflow-hidden">
        <div className="px-3 py-2 bg-white border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-700">
            <FileCode2 className="w-4 h-4 text-sky-600" />
            <span>{selectedExecId ? `快照：${selectedExecId}` : "选择左侧执行节点查看完整复现代码"}</span>
          </div>
          {scriptText && (
            <button
              onClick={() => {
                void navigator.clipboard.writeText(scriptText);
                setToast("脚本代码已复制到剪贴板");
              }}
              className="flex items-center gap-1 text-xs px-2 py-1 rounded border border-slate-200 hover:bg-slate-100 cursor-pointer"
            >
              <Copy className="w-3 h-3" /> 复制代码
            </button>
          )}
        </div>
        <pre className="flex-1 overflow-auto p-3 text-xs font-mono bg-slate-900 text-slate-100 leading-relaxed">{scriptText}</pre>
        {logText && (
          <div className="h-36 border-t border-slate-300 bg-slate-950 text-amber-200 p-2.5 overflow-auto text-[11px] font-mono">
            <div className="text-slate-400 mb-1">stderr 日志：</div>
            <pre className="whitespace-pre-wrap">{logText}</pre>
          </div>
        )}
      </div>
    </div>
  );
}
