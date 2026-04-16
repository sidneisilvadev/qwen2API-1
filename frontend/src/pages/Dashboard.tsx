import { useEffect, useState } from "react"
import { Server, Activity, ShieldAlert, ActivityIcon, FileJson, Cpu, Shield, Globe, ImageIcon } from "lucide-react"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"

interface DashboardStatus {
  accounts: {
    valid: number;
    pending: number;
    rate_limited: number;
    invalid: number;
  };
  browser_engine: {
    pool_size: number;
    queue: number;
  };
}

export default function Dashboard() {
  const [status, setStatus] = useState<DashboardStatus | null>(null)
  const { t } = useTranslation()

  useEffect(() => {
    fetch(`${API_BASE}/api/admin/status`, { headers: getAuthHeader() })
      .then(res => {
        if (!res.ok) throw new Error("Unauthorized")
        return res.json()
      })
      .then(data => setStatus(data))
      .catch(() => toast.error(t("common.status_failed")))
  }, [t])

  return (
    <div className="space-y-8 max-w-5xl relative">
      <div className="relative z-10">
        <div className="absolute -top-10 -left-10 w-40 h-40 bg-primary/20 blur-[100px] rounded-full pointer-events-none" />
        <h2 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-foreground to-foreground/60 bg-clip-text text-transparent">{t("dashboard.title")}</h2>
        <p className="text-muted-foreground mt-2 text-lg">{t("dashboard.subtitle")}</p>
      </div>

      <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4 relative z-10">
        <div className="group rounded-2xl border border-border/50 bg-card/40 backdrop-blur-md shadow-xl hover:shadow-primary/5 transition-all duration-500 overflow-hidden relative">
          <div className="absolute inset-0 bg-gradient-to-br from-primary/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
          <div className="p-6 relative z-10">
            <div className="flex flex-row items-center justify-between space-y-0 pb-4">
              <h3 className="tracking-tight text-sm font-semibold text-foreground/80 uppercase">{t("dashboard.valid_accounts")}</h3>
              <div className="p-2 bg-primary/10 rounded-lg"><Server className="h-5 w-5 text-primary" /></div>
            </div>
            <div className="text-4xl font-black bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent">
              {status?.accounts?.valid || 0}
            </div>
          </div>
        </div>

        <div className="group rounded-2xl border border-border/50 bg-card/40 backdrop-blur-md shadow-xl hover:shadow-blue-500/5 transition-all duration-500 overflow-hidden relative">
          <div className="absolute inset-0 bg-gradient-to-br from-blue-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
          <div className="p-6 relative z-10">
            <div className="flex flex-row items-center justify-between space-y-0 pb-4">
              <h3 className="tracking-tight text-sm font-semibold text-foreground/80 uppercase">{t("dashboard.active_engines")}</h3>
              <div className="p-2 bg-blue-500/10 rounded-lg"><Activity className="h-5 w-5 text-blue-400" /></div>
            </div>
            <div className="text-4xl font-black bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent flex items-baseline gap-2">
              {status?.browser_engine?.pool_size || 0} <span className="text-lg font-bold text-muted-foreground">{t("common.pages")}</span>
            </div>
          </div>
        </div>

        <div className={`group rounded-2xl border transition-all duration-500 overflow-hidden relative shadow-xl backdrop-blur-md ${
          (status?.browser_engine?.queue || 0) > 0 
          ? "border-destructive/20 bg-card/40 hover:shadow-destructive/10" 
          : "border-border/50 bg-card/40 hover:shadow-primary/5"
        }`}>
          <div className={`absolute inset-0 bg-gradient-to-br transition-opacity duration-500 opacity-0 group-hover:opacity-100 ${
            (status?.browser_engine?.queue || 0) > 0 ? "from-destructive/10 to-transparent" : "from-primary/10 to-transparent"
          }`} />
          <div className="p-6 relative z-10">
            <div className="flex flex-row items-center justify-between space-y-0 pb-4">
              <h3 className={`tracking-tight text-sm font-semibold uppercase ${
                (status?.browser_engine?.queue || 0) > 0 ? "text-destructive" : "text-foreground/80"
              }`}>{t("dashboard.queued_requests")}</h3>
              <div className={`p-2 rounded-lg ${
                (status?.browser_engine?.queue || 0) > 0 ? "bg-destructive/10" : "bg-primary/10"
              }`}>
                {(status?.browser_engine?.queue || 0) > 0 
                  ? <ShieldAlert className="h-5 w-5 text-destructive" /> 
                  : <ActivityIcon className="h-5 w-5 text-primary" />
                }
              </div>
            </div>
            <div className={`text-4xl font-black ${(status?.browser_engine?.queue || 0) > 0 ? "text-destructive drop-shadow-[0_0_15px_rgba(239,68,68,0.3)]" : "bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent"}`}>
              {status?.browser_engine?.queue || 0}
            </div>
          </div>
        </div>

        <div className="group rounded-2xl border border-border/50 bg-card/40 backdrop-blur-md shadow-xl hover:shadow-orange-500/5 transition-all duration-500 overflow-hidden relative">
          <div className="absolute inset-0 bg-gradient-to-br from-orange-500/10 to-transparent opacity-0 group-hover:opacity-100 transition-opacity duration-500" />
          <div className="p-6 relative z-10">
            <div className="flex flex-row items-center justify-between space-y-0 pb-4">
              <h3 className="tracking-tight text-sm font-semibold text-foreground/80 uppercase">{t("dashboard.limited_invalid")}</h3>
              <div className="p-2 bg-orange-500/10 rounded-lg"><ActivityIcon className="h-5 w-5 text-orange-400" /></div>
            </div>
            <div className="text-4xl font-black bg-gradient-to-r from-foreground to-foreground/70 bg-clip-text text-transparent">
              {status?.accounts?.rate_limited || 0} <span className="text-muted-foreground font-light mx-1">/</span> {status?.accounts?.invalid || 0}
            </div>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-border/50 bg-card/30 backdrop-blur-xl shadow-2xl relative overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-b from-black/[0.02] dark:from-white/[0.02] to-transparent pointer-events-none" />
        <div className="flex flex-col space-y-2 p-8 border-b border-border/50 bg-muted/10 relative z-10">
          <h3 className="font-extrabold text-2xl tracking-tight flex items-center gap-3">
            <span className="bg-primary w-2 h-8 rounded-full shadow-[0_0_10px_rgba(168,85,247,0.5)]"></span>
            {t("dashboard.api_pool")}
          </h3>
          <p className="text-base text-muted-foreground ml-5">{t("dashboard.api_pool_desc")}</p>
        </div>
        <div className="p-0 relative z-10">
          <div className="divide-y divide-border/50 text-sm">
            <div className="flex justify-between items-center px-8 py-5 hover:bg-black/5 dark:hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-md bg-emerald-500/10"><FileJson className="h-5 w-5 text-emerald-500 dark:text-emerald-400" /></div>
                <div className="font-semibold text-foreground/80">POST /v1/chat/completions</div>
              </div>
              <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-bold bg-emerald-500/10 text-emerald-600 dark:bg-emerald-500/20 dark:text-emerald-300 ring-1 ring-emerald-500/20 dark:ring-emerald-500/30">OpenAI</span>
            </div>
            <div className="flex justify-between items-center px-8 py-5 hover:bg-black/5 dark:hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-md bg-blue-500/10"><Cpu className="h-5 w-5 text-blue-500 dark:text-blue-400" /></div>
                <div className="font-semibold text-foreground/80">POST /v1/messages</div>
              </div>
              <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-bold bg-blue-500/10 text-blue-600 dark:bg-blue-500/20 dark:text-blue-300 ring-1 ring-blue-500/20 dark:ring-blue-500/30">Anthropic</span>
            </div>
            <div className="flex justify-between items-center px-8 py-5 hover:bg-black/5 dark:hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-md bg-yellow-500/10"><Globe className="h-5 w-5 text-yellow-600 dark:text-yellow-400" /></div>
                <div className="font-semibold text-foreground/80">POST /v1/models/gemini-pro:generateContent</div>
              </div>
              <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-bold bg-yellow-500/10 text-yellow-600 dark:bg-yellow-500/20 dark:text-yellow-300 ring-1 ring-yellow-500/20 dark:ring-yellow-500/30">Gemini</span>
            </div>
            <div className="flex justify-between items-center px-8 py-5 hover:bg-black/5 dark:hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-md bg-purple-500/10"><ImageIcon className="h-5 w-5 text-purple-500 dark:text-purple-400" /></div>
                <div className="font-semibold text-foreground/80">POST /v1/images/generations</div>
              </div>
              <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-bold bg-purple-500/10 text-purple-600 dark:bg-purple-500/20 dark:text-purple-300 ring-1 ring-purple-500/20 dark:ring-purple-500/30">Image Gen</span>
            </div>
            <div className="flex justify-between items-center px-8 py-5 hover:bg-black/5 dark:hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-md bg-indigo-500/10"><Server className="h-5 w-5 text-indigo-500 dark:text-indigo-400" /></div>
                <div className="font-semibold text-foreground/80">GET /v1/models</div>
              </div>
              <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-bold bg-indigo-500/10 text-indigo-600 dark:bg-indigo-500/20 dark:text-indigo-300 ring-1 ring-indigo-500/20 dark:ring-indigo-500/30">Model Discovery</span>
            </div>
            <div className="flex justify-between items-center px-8 py-5 hover:bg-black/5 dark:hover:bg-white/[0.02] transition-colors">
              <div className="flex items-center gap-4">
                <div className="p-2 rounded-md bg-slate-500/10"><Shield className="h-5 w-5 text-slate-600 dark:text-slate-400" /></div>
                <div className="font-semibold text-foreground/80">GET /</div>
              </div>
              <span className="inline-flex items-center rounded-full px-3 py-1 text-xs font-bold bg-slate-500/10 text-slate-600 dark:bg-slate-500/20 dark:text-slate-300 ring-1 ring-slate-500/20 dark:ring-slate-500/30">{t("dashboard.health_check")}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
