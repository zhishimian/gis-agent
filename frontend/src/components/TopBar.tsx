import { useState } from "react";
import { FolderOpen, Globe, Plus, Settings, ShieldCheck } from "lucide-react";
import { api } from "../api/client";
import { useStudioStore } from "../store/useStudioStore";
import type { ExecutionPolicy } from "../types/studio";

export function TopBar() {
  const {
    isTauri,
    projectDir,
    sessions,
    activeSessionId,
    executionPolicy,
    usage,
    env,
    switchProject,
    selectSession,
    createNewSession,
    setExecutionPolicy,
    setSettingsOpen,
    setToast,
  } = useStudioStore();

  const [folderPromptOpen, setFolderPromptOpen] = useState(false);
  const [folderInput, setFolderInput] = useState(projectDir);
  const [newSessPromptOpen, setNewSessPromptOpen] = useState(false);
  const [newSessName, setNewSessName] = useState("");

  const handleOpenFolder = async () => {
    if (isTauri) {
      const picked = await api.pickNativeFolder();
      if (picked) {
        try {
          await switchProject(picked);
        } catch (err: any) {
          setToast(err?.message || "切换目录失败");
        }
      }
      return;
    }
    setFolderInput(projectDir);
    setFolderPromptOpen(true);
  };

  const handleSubmitFolder = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!folderInput.trim()) return;
    try {
      await switchProject(folderInput.trim());
      setFolderPromptOpen(false);
    } catch (err: any) {
      setToast(err?.message || "目录无效");
    }
  };

  const handleCreateSession = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      await createNewSession(newSessName.trim() || undefined);
      setNewSessName("");
      setNewSessPromptOpen(false);
    } catch (err: any) {
      setToast(err?.message || "新建会话失败");
    }
  };

  const hitPct = (usage.cache_hit_ratio * 100).toFixed(1);

  return (
    <header className="h-11 bg-slate-900 text-slate-100 px-3 flex items-center justify-between gap-2 border-b border-slate-800 select-none shrink-0">
      <div className="flex items-center gap-2.5 min-w-0">
        <div className="flex items-center gap-1.5 font-semibold text-sm tracking-tight text-white shrink-0">
          <Globe className="w-4 h-4 text-sky-400" />
          <span>OpenGIS Studio</span>
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-sky-500/20 text-sky-300 font-normal">v9.1</span>
        </div>

        <div className="h-4 w-px bg-slate-700" />

        <button
          onClick={handleOpenFolder}
          title={projectDir}
          className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-800 hover:bg-slate-700 text-xs text-slate-200 max-w-[230px] truncate transition cursor-pointer"
        >
          <FolderOpen className="w-3.5 h-3.5 text-amber-400 shrink-0" />
          <span className="truncate">{projectDir || "选择工作文件夹"}</span>
        </button>

        <div className="flex items-center gap-1">
          <select
            value={activeSessionId}
            onChange={(e) => void selectSession(e.target.value)}
            className="bg-slate-800 border border-slate-700 text-xs text-slate-100 rounded px-2 py-1 max-w-[160px] focus:outline-none focus:border-sky-500"
          >
            {sessions.map((s) => (
              <option key={s.session_id} value={s.session_id}>
                {s.session_id} {s.waiting ? "(待确认)" : s.busy ? "(运行中)" : ""}
              </option>
            ))}
          </select>
          <button
            onClick={() => setNewSessPromptOpen(true)}
            title="新建会话"
            className="p-1 rounded bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white transition cursor-pointer"
          >
            <Plus className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <div className="flex items-center gap-1 text-xs bg-slate-800 rounded px-2 py-0.5 border border-slate-700">
          <span className="text-slate-400">交互策略</span>
          <select
            value={executionPolicy}
            onChange={(e) => setExecutionPolicy(e.target.value as ExecutionPolicy)}
            className="bg-transparent text-slate-100 font-medium focus:outline-none cursor-pointer"
            title="auto: 自动完成; plan_first: 重计算前先审计划; step_review: 出图后等人工批注确认"
          >
            <option value="auto" className="bg-slate-900">自动推进 (auto)</option>
            <option value="plan_first" className="bg-slate-900">先审计划 (plan_first)</option>
            <option value="step_review" className="bg-slate-900">出图精修 (step_review)</option>
          </select>
        </div>

        <div
          className="hidden md:flex items-center gap-1.5 text-xs bg-slate-800/80 px-2.5 py-1 rounded border border-slate-700/80 text-slate-300"
          title={`Prompt ${usage.prompt_tokens.toLocaleString()} / 缓存 ${usage.cached_tokens.toLocaleString()} / 输出 ${usage.completion_tokens.toLocaleString()}`}
        >
          <span>¥{usage.estimated_cny.toFixed(2)}</span>
          <span className="text-slate-600">·</span>
          <span className="text-emerald-400">缓存 {hitPct}%</span>
        </div>

        <button
          onClick={() => setSettingsOpen(true)}
          className={`flex items-center gap-1 px-2.5 py-1 rounded text-xs transition cursor-pointer ${
            env?.credentials.configured
              ? "bg-slate-800 hover:bg-slate-700 text-slate-200"
              : "bg-amber-600 hover:bg-amber-500 text-white font-medium"
          }`}
        >
          {env?.credentials.configured ? (
            <ShieldCheck className="w-3.5 h-3.5 text-emerald-400" />
          ) : (
            <Settings className="w-3.5 h-3.5" />
          )}
          <span>{env?.credentials.configured ? env.credentials.model : "配置密钥"}</span>
        </button>
      </div>

      {folderPromptOpen && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <form onSubmit={handleSubmitFolder} className="bg-white text-slate-900 rounded-lg shadow-xl w-full max-w-md p-4 space-y-3">
            <h3 className="font-semibold text-sm">切换工作文件夹</h3>
            <input
              type="text"
              value={folderInput}
              onChange={(e) => setFolderInput(e.target.value)}
              className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-sm font-mono focus:outline-none focus:border-sky-500"
              placeholder="输入绝对路径，如 D:/gis_project"
            />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setFolderPromptOpen(false)} className="px-3 py-1.5 text-xs rounded border border-slate-300">
                取消
              </button>
              <button type="submit" className="px-3 py-1.5 text-xs rounded bg-sky-600 text-white hover:bg-sky-500">
                确定切换
              </button>
            </div>
          </form>
        </div>
      )}

      {newSessPromptOpen && (
        <div className="fixed inset-0 bg-black/50 z-50 flex items-center justify-center p-4">
          <form onSubmit={handleCreateSession} className="bg-white text-slate-900 rounded-lg shadow-xl w-full max-w-sm p-4 space-y-3">
            <h3 className="font-semibold text-sm">新建分析会话</h3>
            <input
              type="text"
              value={newSessName}
              onChange={(e) => setNewSessName(e.target.value)}
              className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-sm focus:outline-none focus:border-sky-500"
              placeholder="留空自动生成，如 jiangsu_flow"
            />
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setNewSessPromptOpen(false)} className="px-3 py-1.5 text-xs rounded border border-slate-300">
                取消
              </button>
              <button type="submit" className="px-3 py-1.5 text-xs rounded bg-sky-600 text-white hover:bg-sky-500">
                创建
              </button>
            </div>
          </form>
        </div>
      )}
    </header>
  );
}
