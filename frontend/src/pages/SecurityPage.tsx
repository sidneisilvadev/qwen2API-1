import { useState, useEffect } from "react"
import { Button } from "../components/ui/button"
import { Plus, RefreshCw, Copy, Check, Trash2, ShieldCheck, ShieldAlert } from "lucide-react"
import { toast } from "sonner"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"
import { useTranslation } from "react-i18next"

interface AdminKey {
  key: string
  name: string
  created_at: string
}

export default function SecurityPage() {
  const [keys, setKeys] = useState<AdminKey[]>([])
  const [copied, setCopied] = useState<string | null>(null)
  const [newKeyName, setNewKeyName] = useState("")
  const { t } = useTranslation()

  const fetchKeys = () => {
    fetch(`${API_BASE}/api/admin/master-keys`, { headers: getAuthHeader() })
      .then(res => {
        if (!res.ok) throw new Error("Unauthorized")
        return res.json()
      })
      .then(data => setKeys(data.keys || []))
      .catch(() => toast.error("Falha ao carregar chaves administrativas"))
  }

  useEffect(() => {
    fetchKeys()
  }, [])

  const handleGenerate = () => {
    fetch(`${API_BASE}/api/admin/master-keys`, {
      method: "POST",
      headers: {
        ...getAuthHeader(),
        "Content-Type": "application/json"
      },
      body: JSON.stringify({ name: newKeyName || "Nova Chave ADM" })
    }).then(res => {
      if (res.ok) {
        toast.success("Chave administrativa gerada com sucesso")
        setNewKeyName("")
        fetchKeys()
      } else {
        toast.error("Erro ao gerar chave administrativa")
      }
    })
  }

  const handleDelete = (key: string) => {
    if (!confirm("Tem certeza que deseja excluir esta chave mestre? Isso pode causar perda de acesso se você não tiver outra.")) return

    fetch(`${API_BASE}/api/admin/master-keys/${encodeURIComponent(key)}`, {
      method: "DELETE",
      headers: getAuthHeader()
    }).then(res => {
      if (res.ok) {
        toast.success("Chave administrativa removida")
        fetchKeys()
      } else {
        toast.error("Falha ao remover chave")
      }
    })
  }

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
    setCopied(text)
    setTimeout(() => setCopied(null), 2000)
  }

  return (
    <div className="space-y-6 max-w-5xl">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <ShieldCheck className="text-primary h-6 w-6" />
            {t("nav.security")}
          </h2>
          <p className="text-muted-foreground pt-1">
            Gerencie chaves mestras dinâmicas para acesso administrativo ao painel.
          </p>
        </div>
        <div className="flex gap-2 w-full md:w-auto">
          <Button variant="outline" size="sm" onClick={() => { fetchKeys(); toast.success("Atualizado"); }}>
            <RefreshCw className="mr-2 h-4 w-4" /> Atualizar
          </Button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <div className="md:col-span-2 space-y-4">
          <div className="rounded-xl border bg-card overflow-hidden shadow-sm">
            <table className="w-full text-sm text-left">
              <thead className="bg-muted/50 border-b text-muted-foreground uppercase text-[10px] font-bold tracking-widest">
                <tr>
                  <th className="h-10 px-4 align-middle">Nome / Identificação</th>
                  <th className="h-10 px-4 align-middle">Chave Administrativa</th>
                  <th className="h-10 px-4 align-middle text-right">Ações</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border/40">
                {keys.length === 0 && (
                  <tr>
                    <td colSpan={3} className="p-8 text-center text-muted-foreground italic">
                      Nenhuma chave administrativa dinâmica cadastrada.
                    </td>
                  </tr>
                )}
                {keys.map((k) => (
                  <tr key={k.key} className="transition-colors hover:bg-muted/20">
                    <td className="p-4 align-middle">
                      <div className="font-semibold text-foreground">{k.name}</div>
                      <div className="text-[10px] text-muted-foreground mt-0.5">Criada em: {k.created_at}</div>
                    </td>
                    <td className="p-4 align-middle">
                        <div className="flex items-center gap-2 font-mono text-xs bg-muted/30 px-2 py-1 rounded border border-border/20 w-fit">
                            <span>{k.key}</span>
                        </div>
                    </td>
                    <td className="p-4 align-middle text-right space-x-1">
                      <Button variant="ghost" size="icon" onClick={() => copyToClipboard(k.key)} className="h-8 w-8 hover:bg-primary/10 hover:text-primary">
                        {copied === k.key ? <Check className="h-3.5 w-3.5 text-green-600" /> : <Copy className="h-3.5 w-3.5" />}
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => handleDelete(k.key)} className="h-8 w-8 text-destructive hover:bg-destructive/10 hover:text-destructive">
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          
          <div className="bg-blue-500/5 border border-blue-500/20 rounded-xl p-4 flex gap-4 text-blue-600 dark:text-blue-400">
            <ShieldAlert className="h-5 w-5 shrink-0 mt-0.5" />
            <div className="text-sm">
              <p className="font-medium">Atenção sobre Segurança</p>
              <p className="opacity-80 mt-1">
                A chave mestra estática definida no arquivo <code className="bg-blue-500/10 px-1 rounded">.env</code> continua funcionando como fallback de emergência. Recomendamos criar uma chave administrativa dinâmica aqui e usar apenas ela no dia a dia.
              </p>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="rounded-xl border bg-card p-5 shadow-sm space-y-4">
            <h3 className="font-bold flex items-center gap-2">
              <Plus className="h-4 w-4 text-primary" />
              Nova Chave Mestre
            </h3>
            <div className="space-y-3">
              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">Nome da Chave</label>
                <input 
                  type="text" 
                  value={newKeyName}
                  onChange={(e) => setNewKeyName(e.target.value)}
                  placeholder="Ex: Notebook Principal"
                  className="w-full bg-muted/50 border border-border/60 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-primary transition-all"
                />
              </div>
              <Button className="w-full shadow-lg shadow-primary/20" onClick={handleGenerate} disabled={!newKeyName.trim()}>
                Gerar Chave de Acesso
              </Button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
