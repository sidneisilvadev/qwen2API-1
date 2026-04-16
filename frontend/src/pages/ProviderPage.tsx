import { useState } from "react"
import { useTranslation } from "react-i18next"
import { Cpu, Play, Download, CheckCircle2, ChevronRight, RefreshCw } from "lucide-react"
import { toast } from "sonner"
import { fetchWithAuth } from "../lib/auth"


export default function ProviderPage() {
    const { t } = useTranslation()
    const [loading, setLoading] = useState<string | null>(null)
    const [activeProvider, setActiveProvider] = useState<string | null>(null)

    const providers = [
        {
            id: "qwen",
            type: "account",
            name: "Qwen",
            title: "Qwen AI (Alibaba)",
            url: "chat.qwen.ai",
            description: "Acesso via chat.qwen.ai. Recomendado para modelos Qwen-Max e Plus.",
            icon: Cpu,
            color: "from-blue-500 to-indigo-600"
        }
    ]

    const onLaunch = async (providerId: string) => {
        console.log(`[DEBUG] onLaunch called with provider: ${providerId}`)
        console.log(`[DEBUG] current loading: ${loading}, activeProvider: ${activeProvider}`)
        setLoading(`launch-${providerId}`)
        try {
            console.log(`[DEBUG] Sending POST to /admin/accounts/capture/launch with provider: ${providerId}`)
            const res = await fetchWithAuth("/admin/accounts/capture/launch", {
                method: "POST",
                body: JSON.stringify({ provider: providerId })
            })
            console.log(`[DEBUG] Response status: ${res.status}`)
            const data = await res.json()
            console.log(`[DEBUG] Response data:`, data)
            if (data.ok) {
                toast.success(data.message || "Navegador aberto!")
                setActiveProvider(providerId)
            } else {
                toast.error("Falha ao abrir navegador", {
                    description: data.message || "O servidor não retornou uma mensagem detalhada.",
                    duration: 10000
                })
            }
        } catch (err) {
            console.error(`[DEBUG] onLaunch error:`, err)
            toast.error("Erro na conexão com o servidor")
        } finally {
            setLoading(null)
        }
    }

    const onExtract = async (providerId: string) => {
        setLoading(`extract-${providerId}`)
        try {
            const res = await fetchWithAuth("/admin/accounts/capture/extract", {
                method: "POST"
            })
            const data = await res.json()
            if (data.ok) {
                toast.success(data.message || "Sessão capturada!")
                setActiveProvider(null)
            } else {
                toast.error(data.message || "Falha na extração. Verifique se você está logado.")
            }
        } catch {
            toast.error("Erro na extração")
        } finally {
            setLoading(null)
        }
    }


    return (
        <div className="space-y-8 pb-12">
            <div>
                <h1 className="text-3xl font-extrabold tracking-tight">{t("nav.provider")}</h1>
                <p className="text-muted-foreground mt-2">
                    Gerencie o acesso direto aos provedores oficiais através da captura de sessão manual.
                </p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                {providers.map((p) => (
                    <div key={p.id} className="group relative overflow-hidden rounded-2xl border border-border/40 bg-card p-1 shadow-sm transition-all hover:shadow-md">
                        <div className={`absolute inset-0 bg-gradient-to-br ${p.color} opacity-0 group-hover:opacity-[0.03] transition-opacity pointer-events-none`} />

                        <div className="p-6 flex flex-col h-full space-y-4">
                            <div className="flex items-center justify-between">
                                <div className={`p-3 rounded-xl bg-gradient-to-br ${p.color} text-white shadow-lg shadow-indigo-500/10`}>
                                    <p.icon className="h-6 w-6" />
                                </div>
                                {activeProvider === p.id && (
                                    <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-500 text-xs font-bold animate-pulse">
                                        <CheckCircle2 className="h-3 w-3" />
                                        ATIVO
                                    </span>
                                )}
                            </div>

                            <div>
                                <h3 className="text-xl font-bold">{p.title}</h3>
                                <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                                    {p.description}
                                </p>
                            </div>

                            <div className="pt-4 flex flex-wrap gap-2">
                                {p.type === "account" ? (
                                    <>
                                        <button
                                            onClick={() => onLaunch(p.id)}
                                            disabled={!!loading || (!!activeProvider && activeProvider !== p.id)}
                                            className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-primary text-primary-foreground font-semibold text-sm transition-all hover:brightness-110 disabled:opacity-50 min-w-[140px]"
                                        >
                                            {loading === `launch-${p.id}` ? (
                                                <RefreshCw className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <Play className="h-4 w-4" />
                                            )}
                                            {loading === `launch-${p.id}` ? `Abrindo ${p.url}...` : "Abrir Navegador"}
                                        </button>

                                        <button
                                            onClick={() => onExtract(p.id)}
                                            disabled={loading === `extract-${p.id}` || activeProvider !== p.id}
                                            className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-background border border-border font-semibold text-sm transition-all hover:bg-muted disabled:opacity-50 min-w-[120px]"
                                        >
                                            {loading === `extract-${p.id}` ? (
                                                <RefreshCw className="h-4 w-4 animate-spin" />
                                            ) : (
                                                <Download className="h-4 w-4" />
                                            )}
                                            {loading === `extract-${p.id}` ? "Extraindo..." : "Extrair Dados"}
                                        </button>
                                    </>
                                ) : (
                                    <button
                                        onClick={async () => {
                                            setLoading(`sync-${p.id}`)
                                            try {
                                                const res = await fetchWithAuth("/admin/models/sync", { method: "POST" })
                                                const data = await res.json()
                                                if (data.ok) toast.success(`Discovery completo: ${data.count} modelos encontrados.`)
                                                else toast.error("Falha na sincronização")
                                            } catch {
                                                toast.error("Erro ao sincronizar modelos")
                                            } finally {
                                                setLoading(null)
                                            }
                                        }}
                                        disabled={loading !== null}
                                        className="flex items-center justify-center gap-2 px-4 py-2 rounded-lg bg-orange-500 text-white font-semibold text-sm transition-all hover:bg-orange-600 disabled:opacity-50 min-w-[200px]"
                                    >
                                        <RefreshCw className={`h-4 w-4 ${loading === `sync-${p.id}` ? "animate-spin" : ""}`} />
                                        Sincronizar Modelos Turbo
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>
                ))}
            </div>

            <div className="rounded-2xl border border-border/40 bg-muted/30 p-6">
                <h4 className="font-bold flex items-center gap-2">
                    <ChevronRight className="h-4 w-4 text-primary" />
                    Como funciona a captura?
                </h4>
                <div className="mt-4 space-y-3 text-sm text-muted-foreground leading-relaxed">
                    <p>
                        1. Selecione um provedor acima e clique em <b>Abrir Navegador</b>. Um navegador seguro será aberto na página de login oficial.
                    </p>
                    <p>
                        2. Realize o login manualmente no site da Qwen conforme solicitado no navegador externo.
                    </p>
                    <p>
                        3. Após o login bem-sucedido, volte a esta tela e clique em <b>Extrair Dados</b>. O sistema irá capturar os tokens e cookies necessários para automatizar suas requisições via API.
                    </p>
                    <p>
                        4. O navegador será fechado e a conta será adicionada automaticamente ao seu pool de contas.
                    </p>
                </div>
            </div>
        </div>
    )
}
