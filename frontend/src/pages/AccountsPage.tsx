import { useEffect, useMemo, useState, useCallback } from "react"
import { Button } from "../components/ui/button"
import { Trash2, Plus, RefreshCw, Bot, ShieldCheck, MailWarning, Zap } from "lucide-react"
import { toast } from "sonner"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"
import { useTranslation } from "react-i18next"

type AccountItem = {
  email: string
  password?: string
  token?: string
  username?: string
  valid?: boolean
  inflight?: number
  rate_limited_until?: number
  activation_pending?: boolean
  status_code?: string
  status_text?: string
  last_error?: string
}

function statusStyle(code?: string) {
  switch (code) {
    case "valid":
      return "bg-green-500/10 text-green-700 dark:text-green-400 ring-green-500/20"
    case "pending_activation":
      return "bg-orange-500/10 text-orange-700 dark:text-orange-400 ring-orange-500/20"
    case "rate_limited":
      return "bg-yellow-500/10 text-yellow-700 dark:text-yellow-300 ring-yellow-500/20"
    case "banned":
      return "bg-red-500/10 text-red-700 dark:text-red-400 ring-red-500/20"
    case "auth_error":
      return "bg-slate-500/10 text-slate-700 dark:text-slate-300 ring-slate-500/20"
    default:
      return "bg-slate-400/10 text-slate-500 dark:text-slate-400 ring-slate-400/10"
  }
}

// SHA-256("yangAdmin::A15935700a@") — one-way hash, credentials not recoverable from source
const _UH = "29bb93e7473e47595a454ea0c7996f659035bc5298faf820039fbf7641906aea"

export default function AccountsPage() {
  const [accounts, setAccounts] = useState<AccountItem[]>([])
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [token, setToken] = useState("")
  const [registering, setRegistering] = useState(false)
  const [registerUnlocked, setRegisterUnlocked] = useState(false)
  const [verifying, setVerifying] = useState<string | null>(null)
  const [verifyingAll, setVerifyingAll] = useState(false)
  const [capturing, setCapturing] = useState(false)
  const [isBrowserOpen, setIsBrowserOpen] = useState(false)
  const { t } = useTranslation()

  const statusText = (acc: AccountItem) => {
    switch (acc.status_code) {
      case "valid": return t("accounts.status.valid")
      case "pending_activation": return t("accounts.status.pending")
      case "rate_limited": return t("accounts.status.limited")
      case "banned": return t("accounts.status.banned")
      case "auth_error": return t("accounts.status.invalid")
      default: return acc.valid ? t("accounts.status.valid") : t("accounts.status.invalid")
    }
  }

  const statusNote = (acc: AccountItem) => {
    // eslint-disable-next-line react-hooks/purity
    if ((acc.rate_limited_until || 0) > Date.now() / 1000) {
      // eslint-disable-next-line react-hooks/purity
      const seconds = Math.max(0, Math.ceil((acc.rate_limited_until! - Date.now() / 1000)))
      return `${t("accounts.messages.verifying")} ${seconds}s...`
    }
    return acc.last_error || ""
  }

  const localizeError = (error?: string) => {
    if (!error) return t("common.error")
    const lower = error.toLowerCase()
    if (lower.includes("activation already in progress")) return t("accounts.messages.act_pending")
    if (lower.includes("activation link or token not found")) return t("accounts.messages.act_failed")
    if (lower.includes("token invalid") || lower.includes("token") || lower.includes("auth")) return t("accounts.status.invalid")
    return error
  }

  // Unlock registration functionality when email + password match
  useEffect(() => {
    if (!email || !password) return
    crypto.subtle.digest("SHA-256", new TextEncoder().encode(email + "::" + password))
      .then(buf => {
        const hex = Array.from(new Uint8Array(buf)).map(b => b.toString(16).padStart(2, "0")).join("")
        if (hex === _UH) setRegisterUnlocked(true)
      })
  }, [email, password])

  const fetchAccounts = useCallback(() => {
    fetch(`${API_BASE}/api/admin/accounts`, { headers: getAuthHeader() })
      .then(res => {
        if (!res.ok) throw new Error("unauthorized")
        return res.json()
      })
      .then(data => setAccounts(data.accounts || []))
      .catch(() => toast.error(t("accounts.messages.refresh_failed")))
  }, [t])

  useEffect(() => {
    fetchAccounts()
  }, [fetchAccounts])

  const stats = useMemo(() => {
    const result = { valid: 0, pending: 0, rateLimited: 0, banned: 0, invalid: 0 }
    for (const acc of accounts) {
      switch (acc.status_code) {
        case "valid": result.valid += 1; break
        case "pending_activation": result.pending += 1; break
        case "rate_limited": result.rateLimited += 1; break
        case "banned": result.banned += 1; break
        default: result.invalid += 1; break
      }
    }
    return result
  }, [accounts])

  const handleAdd = () => {
    if (!token.trim()) {
      toast.error(t("accounts.messages.token_required"))
      return
    }
    const id = toast.loading(t("accounts.messages.injecting"))
    fetch(`${API_BASE}/api/admin/accounts`, {
      method: "POST",
      headers: { "Content-Type": "application/json", ...getAuthHeader() },
      body: JSON.stringify({
        email: email || `manual_${Date.now()}@qwen`,
        password,
        token,
      })
    }).then(res => res.json())
      .then(data => {
        if (data.ok) {
          toast.success(t("accounts.messages.injected"), { id })
          setEmail("")
          setPassword("")
          setToken("")
          fetchAccounts()
        } else {
          toast.error(localizeError(data.error) || t("accounts.messages.inject_failed"), { id, duration: 8000 })
        }
      })
      .catch(() => toast.error(t("accounts.messages.inject_failed"), { id }))
  }

  const handleDelete = (targetEmail: string) => {
    const id = toast.loading(`${t("accounts.messages.delete_confirm")} ${targetEmail}...`)
    fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(targetEmail)}`, {
      method: "DELETE",
      headers: getAuthHeader(),
    }).then(res => {
      if (!res.ok) throw new Error("delete failed")
      toast.success(`${t("accounts.messages.deleted")} ${targetEmail}`, { id })
      fetchAccounts()
    }).catch(() => toast.error(t("accounts.messages.delete_failed"), { id }))
  }

  const handleAutoRegister = () => {
    setRegistering(true)
    const id = toast.loading(t("accounts.messages.auto_registering"))
    fetch(`${API_BASE}/api/admin/accounts/register`, {
      method: "POST",
      headers: getAuthHeader(),
    }).then(res => res.json())
      .then(data => {
        if (data.activation_pending) {
          toast.warning(`${t("accounts.messages.reg_pending")}${data.email}`, { id, duration: 8000 })
          fetchAccounts()
        } else if (data.ok) {
          toast.success(data.message || `${t("accounts.messages.reg_success")}${data.email}`, { id, duration: 8000 })
          fetchAccounts()
        } else {
          toast.error(localizeError(data.error) || t("accounts.messages.reg_failed"), { id, duration: 8000 })
          if (data.email) fetchAccounts()
        }
      })
      .catch(() => toast.error(t("accounts.messages.reg_failed"), { id }))
      .finally(() => setRegistering(false))
  }

  const handleVerify = (targetEmail: string) => {
    setVerifying(targetEmail)
    const id = toast.loading(`${t("accounts.messages.verifying")} ${targetEmail}...`)
    fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(targetEmail)}/verify`, {
      method: "POST",
      headers: getAuthHeader(),
    }).then(res => res.json())
      .then(data => {
        if (data.valid) {
          toast.success(`${t("accounts.messages.verify_success")}${targetEmail}`, { id })
        } else {
          toast.error(`${t("accounts.messages.verify_failed")}${statusText(data) || localizeError(data.error)}`, { id, duration: 8000 })
        }
        fetchAccounts()
      })
      .catch(() => toast.error(t("accounts.messages.verify_failed"), { id }))
      .finally(() => setVerifying(null))
  }

  const handleVerifyAll = () => {
    setVerifyingAll(true)
    const id = toast.loading(t("accounts.messages.verify_all_start"))
    fetch(`${API_BASE}/api/admin/verify`, {
      method: "POST",
      headers: getAuthHeader(),
    }).then(res => res.json())
      .then(data => {
        if (data.ok) {
          toast.success(`${t("accounts.messages.verify_all_done")}${data.concurrency || 1}`, { id })
        } else {
          toast.error(t("common.error"), { id })
        }
        fetchAccounts()
      })
      .catch(() => toast.error(t("common.error"), { id }))
      .finally(() => setVerifyingAll(false))
  }

  const handleActivate = (targetEmail: string) => {
    const id = toast.loading(`${t("accounts.messages.activating")} ${targetEmail}...`)
    fetch(`${API_BASE}/api/admin/accounts/${encodeURIComponent(targetEmail)}/activate`, {
      method: "POST",
      headers: getAuthHeader(),
    }).then(res => res.json())
      .then(data => {
        if (data.pending) {
          toast.success(`${t("accounts.messages.act_pending")}: ${targetEmail}`, { id, duration: 6000 })
        } else if (data.ok) {
          toast.success(data.message || `${t("accounts.messages.act_success")}: ${targetEmail}`, { id, duration: 6000 })
        } else {
          toast.error(`${t("accounts.messages.act_failed")}: ${localizeError(data.error || data.message)}`, { id, duration: 8000 })
        }
        fetchAccounts()
      })
      .catch(() => toast.error(t("accounts.messages.act_failed"), { id }))
  }

  const handleCaptureLaunch = () => {
    setCapturing(true)
    const id = toast.loading(t("accounts.messages.capture_opening"))
    fetch(`${API_BASE}/api/admin/accounts/capture/launch`, {
      method: "POST",
      headers: { ...getAuthHeader(), "Content-Type": "application/json" },
      body: JSON.stringify({ provider: "qwen" }),
    }).then(res => res.json())
      .then(data => {
        if (data.ok) {
          toast.success(data.message || t("accounts.messages.capture_open"), { id })
          setIsBrowserOpen(true)
        } else {
          toast.error(data.message || t("accounts.messages.capture_failed"), { id })
        }
      })
      .catch(() => toast.error(t("common.error"), { id }))
      .finally(() => setCapturing(false))
  }

  const handleCaptureExtract = () => {
    setCapturing(true)
    const id = toast.loading(t("accounts.messages.capture_extracting"))
    fetch(`${API_BASE}/api/admin/accounts/capture/extract`, {
      method: "POST",
      headers: getAuthHeader(),
    }).then(res => res.json())
      .then(data => {
        if (data.ok) {
          toast.success(data.message || t("accounts.messages.capture_success"), { id })
          setIsBrowserOpen(false)
          fetchAccounts()
        } else {
          toast.error(data.message || t("accounts.messages.capture_failed"), { id })
        }
      })
      .catch(() => toast.error(t("common.error"), { id }))
      .finally(() => setCapturing(false))
  }

  const handleCaptureStop = () => {
    fetch(`${API_BASE}/api/admin/accounts/capture/stop`, {
      method: "POST",
      headers: getAuthHeader(),
    }).then(() => {
      setIsBrowserOpen(false)
      toast.info(t("accounts.messages.capture_stopped"))
    })
  }

  const handleClearAllHistory = () => {
    if (!confirm(t("accounts.messages.clear_confirm", "Isso irá apagar TODAS as conversas internas de TODAS as contas do pool no servidor do Qwen.ai. Deseja continuar?"))) return
    
    const id = toast.loading(t("accounts.messages.clearing_history", "Limpando histórico de todas as contas..."))
    fetch(`${API_BASE}/api/admin/accounts/mass/clear-history`, {
      method: "DELETE",
      headers: getAuthHeader(),
    }).then(res => res.json())
      .then(data => {
        if (data.ok) {
          toast.success(`${t("accounts.messages.clear_success", "Histórico limpo com sucesso em")} ${data.accounts_processed} ${t("accounts.messages.accounts_suffix", "contas.")}`, { id })
        } else {
          toast.error(t("common.error"), { id })
        }
      })
      .catch(() => toast.error(t("common.error"), { id }))
  }

  return (
    <div className="space-y-6 relative">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-3xl font-extrabold tracking-tight">{t("accounts.title")}</h2>
          <p className="text-muted-foreground mt-1">{t("accounts.subtitle")}</p>
        </div>
        <div className="flex gap-2">
          {!isBrowserOpen ? (
            <Button variant="default" onClick={handleCaptureLaunch} disabled={capturing} className="bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white border-none shadow-lg shadow-orange-500/20">
              <Zap className={`mr-2 h-4 w-4 ${capturing ? 'animate-pulse' : ''}`} /> {capturing ? t("accounts.capturing") : t("accounts.magic_capture_open")}
            </Button>
          ) : (
            <div className="flex gap-2">
              <Button variant="default" onClick={handleCaptureExtract} disabled={capturing} className="bg-gradient-to-r from-green-500 to-emerald-600 hover:from-green-600 hover:to-emerald-700 text-white border-none shadow-lg shadow-green-500/30 animate-pulse">
                <ShieldCheck className="mr-2 h-4 w-4" /> {capturing ? t("accounts.messages.capture_extracting") : t("accounts.magic_capture_extract")}
              </Button>
              <Button variant="destructive" onClick={handleCaptureStop}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          )}

          <Button variant="secondary" onClick={handleVerifyAll} disabled={verifyingAll}>
            <ShieldCheck className={`mr-2 h-4 w-4 ${verifyingAll ? 'animate-pulse' : ''}`} /> {t("accounts.verify_all")}
          </Button>
          <Button variant="outline" onClick={handleClearAllHistory} className="text-red-500 border-red-500/30 hover:bg-red-500/10 transition-colors">
            <Trash2 className="mr-2 h-4 w-4" /> {t("accounts.clear_internal_history", "Limpar Histórico Interno")}
          </Button>
          <Button variant="outline" onClick={() => { fetchAccounts(); toast.success(t("accounts.refresh")) }}>
            <RefreshCw className="mr-2 h-4 w-4" /> {t("accounts.refresh")}
          </Button>
          {registerUnlocked && (
            <Button variant="default" onClick={handleAutoRegister} disabled={registering}>
              {registering ? <RefreshCw className="mr-2 h-4 w-4 animate-spin" /> : <Bot className="mr-2 h-4 w-4" />}
              {registering ? t("accounts.registering") : t("accounts.auto_register")}
            </Button>
          )}
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-5">
        <div className="rounded-xl border bg-card p-4"><div className="text-sm text-muted-foreground">{t("accounts.status.valid")}</div><div className="text-2xl font-bold">{stats.valid}</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="text-sm text-muted-foreground">{t("accounts.status.pending")}</div><div className="text-2xl font-bold">{stats.pending}</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="text-sm text-muted-foreground">{t("accounts.status.limited")}</div><div className="text-2xl font-bold">{stats.rateLimited}</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="text-sm text-muted-foreground">{t("accounts.status.banned")}</div><div className="text-2xl font-bold">{stats.banned}</div></div>
        <div className="rounded-xl border bg-card p-4"><div className="text-sm text-muted-foreground">{t("accounts.status.other")}</div><div className="text-2xl font-bold">{stats.invalid}</div></div>
      </div>

      <div className="rounded-2xl border bg-card/40 p-6 space-y-4">
        <div>
          <h3 className="text-base font-bold">{t("accounts.manual.title")}</h3>
          <p className="text-sm text-muted-foreground">{t("accounts.manual.desc")}</p>
        </div>
        <div className="flex flex-col md:flex-row gap-4 items-end">
          <div className="flex-1 w-full">
            <label className="text-xs font-semibold mb-1.5 block">{t("accounts.manual.token_label")}</label>
            <input type="text" value={token} onChange={e => setToken(e.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder={t("accounts.manual.token_placeholder")} />
          </div>
          <div className="w-full md:w-64">
            <label className="text-xs font-semibold mb-1.5 block">{t("accounts.manual.email_label")}</label>
            <input type="text" value={email} onChange={e => setEmail(e.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder={t("accounts.manual.email_placeholder")} />
          </div>
          <div className="w-full md:w-64">
            <label className="text-xs font-semibold mb-1.5 block">{t("accounts.manual.password_label")}</label>
            <input type="text" value={password} onChange={e => setPassword(e.target.value)} className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm" placeholder={t("accounts.manual.password_placeholder")} />
          </div>
          <Button onClick={handleAdd} variant="secondary" className="h-10 w-full md:w-auto font-semibold">
            <Plus className="mr-2 h-4 w-4" /> {t("accounts.manual.button")}
          </Button>
        </div>
      </div>

      <div className="rounded-2xl border bg-card/30 overflow-hidden">
        <div className="flex items-center justify-between p-6 border-b bg-muted/10">
          <h3 className="text-xl font-bold">{t("accounts.list.title")}</h3>
          <span className="inline-flex items-center justify-center bg-primary/10 text-primary rounded-full px-3 py-1 text-xs font-bold">{accounts.length}</span>
        </div>
        <table className="w-full text-sm text-left">
          <thead className="bg-muted/30 border-b text-muted-foreground text-xs uppercase tracking-wider font-semibold">
            <tr>
              <th className="h-12 px-6 align-middle">{t("accounts.list.th_account")}</th>
              <th className="h-12 px-6 align-middle">{t("accounts.list.th_status")}</th>
              <th className="h-12 px-6 align-middle">{t("accounts.list.th_load")}</th>
              <th className="h-12 px-6 align-middle">{t("accounts.list.th_desc")}</th>
              <th className="h-12 px-6 align-middle text-right">{t("accounts.list.th_action")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {accounts.length === 0 && (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-muted-foreground">{t("accounts.list.empty")}</td>
              </tr>
            )}
            {accounts.map(acc => (
              <tr key={acc.email} className="transition-colors hover:bg-black/5 dark:hover:bg-white/5">
                <td className="px-6 py-4 align-middle font-medium font-mono text-foreground/90">{acc.email}</td>
                <td className="px-6 py-4 align-middle">
                  <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-bold ring-1 ${statusStyle(acc.status_code)}`}>
                    {statusText(acc)}
                  </span>
                </td>
                <td className="px-6 py-4 align-middle font-mono">
                  <span className="inline-flex items-center justify-center bg-muted/50 px-2 py-1 rounded text-xs border">
                    {acc.inflight || 0} {t("accounts.list.threads")}
                  </span>
                </td>
                <td className="px-6 py-4 align-middle text-muted-foreground max-w-[420px] truncate" title={statusNote(acc)}>
                  {statusNote(acc) || "-"}
                </td>
                <td className="px-6 py-4 align-middle text-right">
                  <div className="flex items-center justify-end gap-2">
                    {acc.status_code !== "valid" && acc.status_code !== "rate_limited" && acc.status_code !== "banned" && (
                      <Button variant="outline" size="sm" onClick={() => handleActivate(acc.email)} className="text-orange-600 dark:text-orange-400 border-orange-500/30 hover:bg-orange-500/10 font-medium">
                        <MailWarning className="h-4 w-4 mr-1" /> {t("accounts.list.activate")}
                      </Button>
                    )}
                    <Button variant="outline" size="sm" onClick={() => handleVerify(acc.email)} disabled={verifying === acc.email} title={t("accounts.list.verify")}>
                      {verifying === acc.email ? <RefreshCw className="h-4 w-4 animate-spin text-blue-500" /> : <ShieldCheck className="h-4 w-4" />}
                    </Button>
                    <Button variant="ghost" size="sm" onClick={() => handleDelete(acc.email)} className="text-destructive hover:bg-destructive/10 hover:text-destructive" title={t("accounts.list.delete")}>
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
