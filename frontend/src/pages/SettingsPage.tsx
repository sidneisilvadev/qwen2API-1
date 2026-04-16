import { useState, useEffect, useCallback } from "react"
import { Settings2, RefreshCw, KeyRound, ServerCrash, Code } from "lucide-react"
import { Button } from "../components/ui/button"
import { toast } from "sonner"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"
import { useTranslation } from "react-i18next"
import CodeExamples from "../components/CodeExamples"

interface SettingsData {
  version?: string;
  max_inflight_per_account?: number;
  default_thinking?: boolean;
  default_search?: boolean;
  model_aliases?: Record<string, string>;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsData | null>(null)
  const [sessionKey, setSessionKey] = useState(() => localStorage.getItem('qwen2api_key') || "")
  const [maxInflight, setMaxInflight] = useState(3)
  const [modelAliases, setModelAliases] = useState("")
  const [defaultThinking, setDefaultThinking] = useState(false)
  const [defaultSearch, setDefaultSearch] = useState(false)
  const { t } = useTranslation()

  const [models, setModels] = useState<string[]>([])

  const fetchSettings = useCallback(() => {
    // Fetch settings
    fetch(`${API_BASE}/api/admin/settings`, { headers: getAuthHeader() })
      .then(res => {
        if(!res.ok) throw new Error("Unauthorized")
        return res.json()
      })
      .then(data => {
        setSettings(data)
        setMaxInflight(data.max_inflight_per_account || 3)
        setDefaultThinking(data.default_thinking || false)
        setDefaultSearch(data.default_search || false)
        setModelAliases(JSON.stringify(data.model_aliases || {}, null, 2))
      })
      .catch(() => toast.error(t("settings.messages.refresh_failed")))

    // Fetch models for examples
    fetch(`${API_BASE}/v1/models`)
      .then(res => res.json())
      .then(data => {
        if (data.data) {
          setModels(data.data.map((m: any) => m.id))
        }
      })
      .catch(() => {})
  }, [t])

  useEffect(() => {
    fetchSettings()
  }, [fetchSettings])

  const handleSaveSessionKey = () => {
    if (!sessionKey.trim()) {
      toast.error(t("settings.session.required"))
      return
    }
    localStorage.setItem('qwen2api_key', sessionKey.trim())
    toast.success(t("settings.session.saved"))
    fetchSettings()
  }

  const handleClearSessionKey = () => {
    localStorage.removeItem('qwen2api_key')
    setSessionKey("")
    toast.success(t("settings.session.cleared"))
  }

  const handleSaveConcurrency = () => {
    fetch(`${API_BASE}/api/admin/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ max_inflight_per_account: Number(maxInflight) })
    }).then(res => {
      if(res.ok) { toast.success(t("settings.core.save_success")); fetchSettings(); }
      else toast.error(t("settings.core.save_failed"))
    })
  }

  const handleToggleMode = (key: string, value: boolean) => {
    fetch(`${API_BASE}/api/admin/settings`, {
      method: "PUT",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({ [key]: value })
    }).then(res => {
      if(res.ok) { 
        toast.success(t("settings.core.save_success")); 
        fetchSettings(); 
      }
      else toast.error(t("settings.core.save_failed"))
    })
  }

  const handleSaveAliases = () => {
    try {
      const parsed = JSON.parse(modelAliases)
      fetch(`${API_BASE}/api/admin/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json", ...getAuthHeader() },
        body: JSON.stringify({ model_aliases: parsed })
      }).then(res => {
        if(res.ok) { toast.success(t("settings.aliases.save_success")); fetchSettings(); }
        else toast.error(t("settings.core.save_failed"))
      })
    } catch {
      toast.error(t("settings.aliases.json_error"))
    }
  }

  const baseUrl = API_BASE || `http://${window.location.hostname}:7860`



  return (
    <div className="space-y-6 max-w-4xl">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">{t("settings.title")}</h2>
          <p className="text-muted-foreground">{t("settings.subtitle")}</p>
        </div>
        <Button variant="outline" onClick={() => {fetchSettings(); toast.success(t("settings.refreshed"))}}>
          <RefreshCw className="mr-2 h-4 w-4" /> {t("settings.refresh")}
        </Button>
      </div>

      <div className="grid gap-6">
        {/* Session Key */}
        <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
          <div className="flex flex-col space-y-1.5 p-6 border-b bg-muted/30">
            <div className="flex items-center gap-2">
              <KeyRound className="h-5 w-5 text-primary" />
              <h3 className="font-semibold leading-none tracking-tight">{t("settings.session.title")}</h3>
            </div>
            <p className="text-sm text-muted-foreground">{t("settings.session.desc")}</p>
          </div>
          <div className="p-6">
            <div className="flex gap-2 items-center">
              <input 
                type="password" 
                value={sessionKey}
                onChange={e => setSessionKey(e.target.value)}
                placeholder={t("settings.session.placeholder")} 
                className="flex h-10 w-full flex-1 rounded-md border border-input bg-background px-3 py-2 text-sm"
              />
              <Button onClick={handleSaveSessionKey}>{t("settings.session.save")}</Button>
              <Button variant="ghost" onClick={handleClearSessionKey}>{t("settings.session.clear")}</Button>
            </div>
          </div>
        </div>

        {/* Connection Info */}
        <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
          <div className="flex flex-col space-y-1.5 p-6 border-b bg-muted/30">
            <div className="flex items-center gap-2">
              <ServerCrash className="h-5 w-5 text-primary" />
              <h3 className="font-semibold leading-none tracking-tight">{t("settings.connection.title")}</h3>
            </div>
          </div>
          <div className="p-6">
            <div className="space-y-1">
              <label className="text-sm font-medium">{t("settings.connection.base_url")}</label>
              <input type="text" readOnly value={baseUrl} className="flex h-10 w-full rounded-md border border-input bg-muted px-3 py-2 text-sm font-mono text-muted-foreground" />
            </div>
          </div>
        </div>

        {/* Core Settings */}
        <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
          <div className="flex flex-col space-y-1.5 p-6 border-b bg-muted/30">
            <div className="flex items-center gap-2">
              <Settings2 className="h-5 w-5 text-primary" />
              <h3 className="font-semibold leading-none tracking-tight">{t("settings.core.title")}</h3>
            </div>
            <p className="text-sm text-muted-foreground">{t("settings.core.desc")}</p>
          </div>
          <div className="p-6 space-y-4">
            <div className="flex justify-between items-center py-2 border-b">
              <div className="space-y-1">
                <span className="text-sm font-medium">{t("settings.core.version")}</span>
              </div>
              <span className="font-mono text-sm">{settings?.version || "..."}</span>
            </div>
            <div className="flex justify-between items-center py-2 border-b">
              <div className="space-y-1">
                <span className="text-sm font-medium">{t("settings.core.inflight")}</span>
                <p className="text-xs text-muted-foreground">{t("settings.core.inflight_desc")}</p>
              </div>
              <div className="flex gap-2 items-center">
                <input 
                  type="number" 
                  min="1" 
                  max="20" 
                  value={maxInflight} 
                  onChange={e => setMaxInflight(Number(e.target.value))}
                  className="flex h-8 w-20 rounded-md border border-input bg-background px-3 py-1 text-sm text-center"
                />
                <Button size="sm" onClick={handleSaveConcurrency}>{t("settings.core.save")}</Button>
              </div>
            </div>

            <div className="flex justify-between items-center py-4 border-b">
              <div className="space-y-1">
                <span className="text-sm font-medium">{t("settings.modes.thinking_title")}</span>
                <p className="text-xs text-muted-foreground">{t("settings.modes.thinking_desc")}</p>
              </div>
              <div 
                onClick={() => handleToggleMode("default_thinking", !defaultThinking)}
                className={`w-12 h-6 rounded-full p-1 cursor-pointer transition-colors duration-200 ease-in-out ${defaultThinking ? 'bg-primary' : 'bg-muted'}`}
              >
                <div className={`w-4 h-4 bg-white rounded-full transition-transform duration-200 ease-in-out transform ${defaultThinking ? 'translate-x-6' : 'translate-x-0'}`} />
              </div>
            </div>

            <div className="flex justify-between items-center py-4 border-b">
              <div className="space-y-1">
                <span className="text-sm font-medium">{t("settings.modes.search_title")}</span>
                <p className="text-xs text-muted-foreground">{t("settings.modes.search_desc")}</p>
              </div>
              <div 
                onClick={() => handleToggleMode("default_search", !defaultSearch)}
                className={`w-12 h-6 rounded-full p-1 cursor-pointer transition-colors duration-200 ease-in-out ${defaultSearch ? 'bg-primary' : 'bg-muted'}`}
              >
                <div className={`w-4 h-4 bg-white rounded-full transition-transform duration-200 ease-in-out transform ${defaultSearch ? 'translate-x-6' : 'translate-x-0'}`} />
              </div>
            </div>
          </div>
        </div>

        {/* Model Mapping */}
        <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
          <div className="flex flex-col space-y-1.5 p-6 border-b bg-muted/30">
            <h3 className="font-semibold leading-none tracking-tight">{t("settings.aliases.title")}</h3>
            <p className="text-sm text-muted-foreground">{t("settings.aliases.desc")}</p>
          </div>
          <div className="p-6">
            <textarea 
              rows={8}
              value={modelAliases}
              onChange={e => setModelAliases(e.target.value)}
              className="flex min-h-[160px] w-full rounded-md border border-input bg-slate-950 text-slate-300 px-3 py-2 text-sm font-mono"
            />
            <div className="mt-4 flex justify-end">
              <Button onClick={handleSaveAliases}>{t("settings.aliases.save")}</Button>
            </div>
          </div>
        </div>

        {/* Usage Examples */}
        <div className="rounded-xl border bg-card text-card-foreground shadow-sm">
          <div className="flex flex-col space-y-1.5 p-6 border-b bg-muted/30">
            <div className="flex items-center gap-2">
              <Code className="h-5 w-5 text-primary" />
              <h3 className="font-semibold leading-none tracking-tight">{t("settings.example.title")}</h3>
            </div>
            <p className="text-sm text-muted-foreground">
              Exemplos de integração via OpenAI SDK, REST e MCP — copie e substitua <code className="bg-muted px-1 rounded text-xs">YOUR_API_KEY</code>.
            </p>
          </div>
          <div className="p-6">
            <CodeExamples baseUrl={baseUrl} availableModels={models} />
          </div>
        </div>
      </div>
    </div>
  )
}
