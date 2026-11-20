import { useEffect } from "react";
import { Code2, Image as ImageIcon, Loader2, Map as MapIcon, X } from "lucide-react";
import { ChatPanel } from "./components/ChatPanel";
import { CodeEvidencePanel } from "./components/CodeEvidencePanel";
import { FigureWorkbench } from "./components/FigureWorkbench";
import { MapCanvas } from "./components/MapCanvas";
import { SettingsModal } from "./components/SettingsModal";
import { TopBar } from "./components/TopBar";
import { useStudioStore } from "./store/useStudioStore";

export default function App() {
  const { ready, initError, activeTab, setActiveTab, figures, toast, setToast, bootstrap } = useStudioStore();

  useEffect(() => {
    void bootstrap();
  }, []);

  useEffect(() => {
    if (!toast) return;
    const id = setTimeout(() => setToast(null), 4000);
    return () => clearTimeout(id);
  }, [toast]);

  if (!ready) {
    return (
      <div className="h-screen w-screen flex flex-col items-center justify-center bg-slate-900 text-slate-100 gap-3">
        {initError ? (
          <div className="max-w-md text-center space-y-2 p-6 bg-slate-800 rounded-xl border border-rose-500/40">
            <div className="text-rose-400 font-semibold">无法启动 OpenGIS Studio</div>
            <div className="text-xs text-slate-300">{initError}</div>
            <button onClick={() => void bootstrap()} className="mt-2 px-4 py-1.5 rounded bg-sky-600 text-xs font-medium cursor-pointer">
              重试连接
            </button>
          </div>
        ) : (
          <>
            <Loader2 className="w-7 h-7 animate-spin text-sky-400" />
            <span className="text-xs text-slate-300">正在连接本地空间引擎与会话状态机…</span>
          </>
        )}
      </div>
    );
  }

  return (
    <div className="h-screen w-screen flex flex-col bg-slate-100 overflow-hidden">
      <TopBar />

      <main className="flex-1 flex min-h-0">
        {/* Left ~32%: HIL Chat & Plan */}
        <div className="w-[34%] min-w-[320px] max-w-[460px] h-full shrink-0">
          <ChatPanel />
        </div>

        {/* Right ~66%: Tri-View Spatial & Figure Workspace */}
        <section className="flex-1 flex flex-col min-w-0 h-full bg-white">
          <div className="h-9 border-b border-slate-200 px-3 bg-slate-50 flex items-center gap-1 shrink-0 text-xs">
            <button
              onClick={() => setActiveTab("map")}
              className={`px-3 py-1 rounded-md flex items-center gap-1.5 font-medium transition cursor-pointer ${
                activeTab === "map" ? "bg-white text-sky-700 shadow-sm border border-slate-200" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <MapIcon className="w-3.5 h-3.5" /> 空间地图画布
            </button>
            <button
              onClick={() => setActiveTab("figures")}
              className={`px-3 py-1 rounded-md flex items-center gap-1.5 font-medium transition cursor-pointer ${
                activeTab === "figures" ? "bg-white text-sky-700 shadow-sm border border-slate-200" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <ImageIcon className="w-3.5 h-3.5" /> 成图精修与对比
              {figures.length > 0 && (
                <span className="px-1.5 py-0.2 rounded-full bg-sky-100 text-sky-700 text-[10px]">{figures.length}</span>
              )}
            </button>
            <button
              onClick={() => setActiveTab("code")}
              className={`px-3 py-1 rounded-md flex items-center gap-1.5 font-medium transition cursor-pointer ${
                activeTab === "code" ? "bg-white text-sky-700 shadow-sm border border-slate-200" : "text-slate-600 hover:text-slate-900"
              }`}
            >
              <Code2 className="w-3.5 h-3.5" /> 代码与证据
            </button>
          </div>

          <div className="flex-1 min-h-0 relative">
            <div className={activeTab === "map" ? "h-full" : "hidden"}>
              <MapCanvas />
            </div>
            {activeTab === "figures" && <FigureWorkbench />}
            {activeTab === "code" && <CodeEvidencePanel />}
          </div>
        </section>
      </main>

      <SettingsModal />

      {toast && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 bg-slate-900 text-white text-xs px-4 py-2 rounded-full shadow-lg flex items-center gap-2">
          <span>{toast}</span>
          <button onClick={() => setToast(null)} className="text-slate-400 hover:text-white cursor-pointer">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
