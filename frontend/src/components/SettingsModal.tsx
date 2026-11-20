import { useEffect, useState } from "react";
import { CheckCircle2, KeyRound, X } from "lucide-react";
import { api } from "../api/client";
import { useStudioStore } from "../store/useStudioStore";

export function SettingsModal() {
  const { settingsOpen, setSettingsOpen, env, refreshWorkspace, setToast, isTauri } = useStudioStore();
  const [provider, setProvider] = useState("deepseek");
  const [model, setModel] = useState("deepseek-flash");
  const [baseUrl, setBaseUrl] = useState("https://api.deepseek.com");
  const [apiKey, setApiKey] = useState("");
  const [qgisDir, setQgisDir] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (env && settingsOpen) {
      setProvider(env.credentials.provider || "deepseek");
      setModel(env.credentials.model || "deepseek-flash");
      setBaseUrl(env.credentials.base_url || "https://api.deepseek.com");
      setQgisDir(env.qgis_dir || "");
      setApiKey("");
    }
  }, [env, settingsOpen]);

  if (!settingsOpen) return null;

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      await api.saveCredentials({
        provider,
        model,
        base_url: baseUrl,
        ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
      });
      await api.saveQgis(qgisDir.trim() || null);
      await refreshWorkspace();
      setToast("模型凭据与环境配置已更新");
      setSettingsOpen(false);
    } catch (err: any) {
      setToast(err?.message || "保存设置失败");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 bg-black/50 flex items-center justify-center p-4">
      <form onSubmit={handleSave} className="bg-white rounded-xl shadow-2xl w-full max-w-lg border border-slate-200 overflow-hidden">
        <div className="px-4 py-3 bg-slate-50 border-b border-slate-200 flex items-center justify-between">
          <div className="flex items-center gap-2 font-semibold text-sm text-slate-800">
            <KeyRound className="w-4 h-4 text-sky-600" />
            <span>模型凭据与运行环境设置</span>
          </div>
          <button type="button" onClick={() => setSettingsOpen(false)} className="text-slate-400 hover:text-slate-700 cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="p-4 space-y-3.5 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">服务商</label>
              <select
                value={provider}
                onChange={(e) => {
                  const p = e.target.value;
                  setProvider(p);
                  if (p === "deepseek") {
                    setBaseUrl("https://api.deepseek.com");
                    setModel("deepseek-flash");
                  } else if (p === "openai") {
                    setBaseUrl("https://api.openai.com/v1");
                    setModel("gpt-4.1");
                  }
                }}
                className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-xs"
              >
                <option value="deepseek">DeepSeek</option>
                <option value="openai">OpenAI</option>
                <option value="compatible">OpenAI 兼容接口</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-medium text-slate-600 mb-1">模型 ID</label>
              <input
                value={model}
                onChange={(e) => setModel(e.target.value)}
                className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-xs font-mono"
              />
            </div>
          </div>

          <div>
            <label className="block text-xs font-medium text-slate-600 mb-1">API Base URL</label>
            <input
              value={baseUrl}
              onChange={(e) => setBaseUrl(e.target.value)}
              className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-xs font-mono"
            />
          </div>

          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-slate-600">API Key（加密保存至系统凭据库）</label>
              {env?.credentials.configured && (
                <span className="text-[11px] text-emerald-600 flex items-center gap-1">
                  <CheckCircle2 className="w-3 h-3" />
                  已配置 ({env.credentials.source})
                </span>
              )}
            </div>
            <input
              type="password"
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
              placeholder={env?.credentials.configured ? "留空保持现有密钥不变，输入则覆盖保存" : "sk-..."}
              className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-xs font-mono"
            />
          </div>

          <div className="pt-2 border-t border-slate-100">
            <div className="flex items-center justify-between mb-1">
              <label className="text-xs font-medium text-slate-600">桌面 QGIS 安装路径（可选增强，不装也可使用开源空间栈）</label>
              {isTauri && (
                <button
                  type="button"
                  onClick={async () => {
                    const p = await api.pickNativeFolder();
                    if (p) setQgisDir(p);
                  }}
                  className="text-[11px] text-sky-600 hover:underline cursor-pointer"
                >
                  浏览目录
                </button>
              )}
            </div>
            <input
              value={qgisDir}
              onChange={(e) => setQgisDir(e.target.value)}
              placeholder="例如 E:/exe/qgis（留空仅使用内置开源空间栈）"
              className="w-full border border-slate-300 rounded px-2.5 py-1.5 text-xs font-mono"
            />
            {env?.detected_qgis_dirs && env.detected_qgis_dirs.length > 0 && (
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {env.detected_qgis_dirs.map((d) => (
                  <button
                    key={d}
                    type="button"
                    onClick={() => setQgisDir(d)}
                    className="text-[11px] px-2 py-0.5 rounded bg-sky-50 text-sky-700 border border-sky-200 hover:bg-sky-100 cursor-pointer"
                  >
                    检测到：{d}
                  </button>
                ))}
              </div>
            )}
          </div>

          {env?.python && (
            <div className="text-[11px] text-slate-500 bg-slate-50 rounded p-2 font-mono truncate" title={env.python.executable}>
              Python {env.python.version} · {Object.keys(env.python.packages || {}).length} 空间核心库已就绪
            </div>
          )}
        </div>

        <div className="px-4 py-2.5 bg-slate-50 border-t border-slate-200 flex justify-end gap-2">
          <button type="button" onClick={() => setSettingsOpen(false)} className="px-3 py-1.5 text-xs rounded border border-slate-300">
            关闭
          </button>
          <button
            type="submit"
            disabled={saving}
            className="px-3.5 py-1.5 text-xs rounded bg-sky-600 hover:bg-sky-500 text-white font-medium disabled:opacity-50 cursor-pointer"
          >
            {saving ? "保存中..." : "保存设置"}
          </button>
        </div>
      </form>
    </div>
  );
}
