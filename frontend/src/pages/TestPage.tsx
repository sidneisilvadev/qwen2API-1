import React, { useEffect, useRef, useState } from "react"
import { Button } from "../components/ui/button"
import { Send, RefreshCw, Bot } from "lucide-react"
import { getAuthHeader } from "../lib/auth"
import { API_BASE } from "../lib/api"
import { toast } from "sonner"
import { useTranslation } from "react-i18next"

// Render message content: automatically render Markdown images and image URLs as <img>
function MessageContent({ content }: { content: string }) {
  type Seg = { start: number; end: number; url: string }
  const segs: Seg[] = []
  const fullRe = /!\[[^\]]*\]\((https?:\/\/[^)\s]+)\)|(https?:\/\/[^\s"<>]+\.(?:jpg|jpeg|png|webp|gif)[^\s"<>]*)/gi
  let m: RegExpExecArray | null
  while ((m = fullRe.exec(content)) !== null) {
    segs.push({ start: m.index, end: m.index + m[0].length, url: (m[1] || m[2]) as string })
  }

  if (segs.length === 0) {
    return <div className="whitespace-pre-wrap leading-relaxed">{content}</div>
  }

  const nodes: React.ReactElement[] = []
  let cursor = 0
  segs.forEach((seg, i) => {
    if (seg.start > cursor) {
      nodes.push(<span key={"t" + i}>{content.slice(cursor, seg.start)}</span>)
    }
    nodes.push(
      <div key={"i" + i} className="my-2">
        <img
          src={seg.url}
          alt="generated"
          className="max-w-full rounded-lg shadow-md border"
          loading="lazy"
          onError={e => { (e.currentTarget as HTMLImageElement).style.display = "none" }}
        />
        <div className="text-xs text-muted-foreground mt-1 break-all font-mono">{seg.url}</div>
      </div>
    )
    cursor = seg.end
  })
  if (cursor < content.length) {
    nodes.push(<span key="tail">{content.slice(cursor)}</span>)
  }
  return <div className="whitespace-pre-wrap leading-relaxed">{nodes}</div>
}

export default function TestPage() {
  const [messages, setMessages] = useState<{ role: string; content: string; error?: boolean }[]>([])
  const [input, setInput] = useState("")
  const [loading, setLoading] = useState(false)
  const [model, setModel] = useState("qwen-max")
  const [stream, setStream] = useState(true)
  const [thinking, setThinking] = useState(false)
  const [search, setSearch] = useState(false)
  const [responseTime, setResponseTime] = useState<number | null>(null)
  const startTimeRef = useRef<number>(0)
  const bottomRef = useRef<HTMLDivElement>(null)
  const { t } = useTranslation()

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages])

  const handleSend = async () => {
    if (!input.trim() || loading) return
    const userMsg = { role: "user", content: input }
    setMessages(prev => [...prev, userMsg])
    setInput("")
    setLoading(true)
    setResponseTime(null)
    startTimeRef.current = Date.now()

    try {
      const payload = { 
        model, 
        messages: [...messages, userMsg], 
        stream,
        enable_thinking: thinking,
        enable_search: search
      }
      
      if (!stream) {
        const res = await fetch(`${API_BASE}/v1/chat/completions`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeader() },
          body: JSON.stringify(payload)
        })
        const data = await res.json()
        setResponseTime(Date.now() - startTimeRef.current)
        if (data.error) {
          setMessages(prev => [...prev, { role: "assistant", content: `❌ ${data.error}`, error: true }])
        } else if (data.choices?.[0]) {
          setMessages(prev => [...prev, data.choices[0].message])
        } else {
          setMessages(prev => [...prev, { role: "assistant", content: `❌ ${t("test.messages.unknown_response")}: ${JSON.stringify(data)}`, error: true }])
        }
      } else {
        const res = await fetch(`${API_BASE}/v1/chat/completions`, {
          method: "POST",
          headers: { "Content-Type": "application/json", ...getAuthHeader() },
          body: JSON.stringify(payload)
        })

        if (!res.ok) {
          const errText = await res.text()
          setMessages(prev => [...prev, { role: "assistant", content: `❌ HTTP ${res.status}: ${errText}`, error: true }])
          return
        }

        if (!res.body) throw new Error("No response body")

        setMessages(prev => [...prev, { role: "assistant", content: "" }])
        const reader = res.body.getReader()
        const decoder = new TextDecoder()
        let hasContent = false

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          const chunk = decoder.decode(value, { stream: true })
          for (const rawLine of chunk.split("\n")) {
            const line = rawLine.trim()
            if (!line || line.startsWith(":") || line === "data: [DONE]") continue
            
            if (!hasContent) {
              setResponseTime(Date.now() - startTimeRef.current)
            }

            if (line.startsWith("data: ")) {
              try {
                const data = JSON.parse(line.slice(6))
                if (data.error) {
                  setMessages(prev => {
                    const msgs = [...prev]
                    msgs[msgs.length - 1] = { role: "assistant", content: `❌ ${data.error}`, error: true }
                    return msgs
                  })
                  hasContent = true
                  break
                }
                const content: string = data.choices?.[0]?.delta?.content ?? ""
                if (content) {
                  hasContent = true
                  setMessages(prev => {
                    const msgs = [...prev]
                    const last = msgs[msgs.length - 1]
                    msgs[msgs.length - 1] = { ...last, content: last.content + content }
                    return msgs
                  })
                }
              } catch { /* skip */ }
            }
          }
        }

        if (!hasContent) {
          setMessages(prev => {
            const msgs = [...prev]
            msgs[msgs.length - 1] = { role: "assistant", content: `❌ ${t("test.messages.empty_response")}`, error: true }
            return msgs
          })
        }
      }
    } catch (err: unknown) {
      toast.error(`${t("test.messages.network_error")}: ${(err as Error).message}`)
      setMessages(prev => [...prev, { role: "assistant", content: `❌ ${t("test.messages.network_error")}: ${(err as Error).message}`, error: true }])
    } finally {
      setLoading(false)
    }
  }

  const [availableModels, setAvailableModels] = useState<{id: string; name?: string}[]>([])

  useEffect(() => {
    const fetchModels = async () => {
      try {
        const res = await fetch(`${API_BASE}/api/admin/models`, {
          headers: getAuthHeader()
        })
        const data = await res.json()
        if (data.models && data.models.length > 0) {
          setAvailableModels(data.models)
          // Se o modelo atual não estiver na lista, seleciona o primeiro
          if (!data.models.some((m: {id: string; name?: string}) => m.id === model)) {
            setModel(data.models[0].id)
          }
        } else {
          // Fallback: show a default list if discovery hasn't run yet
          setAvailableModels([
            { id: "qwen-max" }, { id: "qwen-plus" }, { id: "qwen-turbo" }
          ])
        }
      } catch (err) {
        console.error("Failed to fetch models", err)
        // Ensure there's always at least one option
        setAvailableModels([
          { id: "qwen-max" }, { id: "qwen-plus" }, { id: "qwen-turbo" }
        ])
      }
    }
    fetchModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <div className="flex flex-col h-[calc(100vh-10rem)] space-y-4 max-w-5xl mx-auto">
      <div className="flex flex-col md:flex-row justify-between items-start md:items-center gap-4">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">{t("test.title")}</h2>
          <p className="text-muted-foreground">{t("test.subtitle")}</p>
        </div>
        <div className="flex flex-wrap gap-3 items-center">
          {/* Model Selector */}
          <div className="flex items-center gap-2 text-sm bg-card border px-3 py-1.5 rounded-md">
            <span className="font-medium text-muted-foreground">{t("test.model")}:</span>
            <select value={model} onChange={e => setModel(e.target.value)} className="bg-card text-foreground font-sans outline-none cursor-pointer">
              {availableModels.map(m => (
                <option key={m.id} value={m.id} className="bg-card text-foreground">
                  {m.name || m.id}
                </option>
              ))}
            </select>
          </div>

          <div
            className="flex items-center gap-2 text-sm bg-card border px-3 py-1.5 rounded-md cursor-pointer select-none"
            onClick={() => setStream(!stream)}
          >
            <input type="checkbox" checked={stream} readOnly className="cursor-pointer" />
            <span className="font-medium">{t("test.stream")}</span>
          </div>

          <div
            className={`flex items-center gap-2 text-sm border px-3 py-1.5 rounded-md cursor-pointer transition-colors select-none ${thinking ? 'bg-primary/10 border-primary/30 text-primary' : 'bg-card'}`}
            onClick={() => setThinking(!thinking)}
          >
            <div className={`w-3 h-3 rounded-full ${thinking ? 'bg-primary animate-pulse' : 'bg-muted-foreground/30'}`} />
            <span className="font-medium">{t("settings.modes.thinking_title")}</span>
          </div>

          <div
            className={`flex items-center gap-2 text-sm border px-3 py-1.5 rounded-md cursor-pointer transition-colors select-none ${search ? 'bg-primary/10 border-primary/30 text-primary' : 'bg-card'}`}
            onClick={() => setSearch(!search)}
          >
            <Bot className={`h-3 w-3 ${search ? 'text-primary' : 'text-muted-foreground/30'}`} />
            <span className="font-medium">Search</span>
          </div>

          <Button variant="outline" onClick={() => {setMessages([]); setResponseTime(null)}}>
            <RefreshCw className="mr-2 h-4 w-4" /> {t("test.clear")}
          </Button>
        </div>
      </div>

      <div className="flex-1 rounded-xl border bg-card overflow-hidden flex flex-col shadow-sm">
        <div className="flex-1 overflow-y-auto p-6 space-y-6 flex flex-col">
          {messages.length === 0 && (
            <div className="h-full flex flex-col items-center justify-center text-muted-foreground space-y-4">
              <Bot className="h-12 w-12 text-muted-foreground/30" />
              <p className="text-sm">{t("test.empty")}</p>
            </div>
          )}
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[80%] rounded-xl px-4 py-3 text-sm shadow-sm
                ${msg.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : msg.error
                    ? "bg-red-500/10 border border-red-500/30 text-red-400"
                    : "bg-muted/30 border text-foreground"}`}>
                {msg.role === "assistant" && !msg.content && loading ? (
                  <span className="animate-pulse flex items-center gap-2 text-muted-foreground">
                    <Bot className="h-4 w-4" /> {thinking ? t("test.thinking") : "Aguardando resposta..."}
                  </span>
                ) : msg.role === "assistant" && !msg.error ? (
                  <MessageContent content={msg.content} />
                ) : (
                  <div className="whitespace-pre-wrap leading-relaxed">{msg.content}</div>
                )}
              </div>
            </div>
          ))}
          <div ref={bottomRef} />
        </div>

        {responseTime !== null && (
          <div className="px-6 py-1 text-[10px] font-mono text-muted-foreground bg-muted/10 border-t flex justify-between items-center">
            <span>Performance: {thinking ? "Reasoning Mode" : "Express Mode"}</span>
            <span>First Token: <span className={responseTime > 3000 ? "text-amber-500" : "text-emerald-500"}>{responseTime}ms</span></span>
          </div>
        )}

        <div className="p-4 border-t bg-muted/30 flex gap-3 items-center">
          <input
            type="text"
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={e => e.key === "Enter" && handleSend()}
            className="flex h-12 w-full rounded-md border border-input bg-background px-4 py-2 text-sm shadow-sm transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
            placeholder={t("test.placeholder")}
            disabled={loading}
          />
          <Button onClick={handleSend} disabled={loading || !input.trim()} className="h-12 px-6">
            {loading ? <RefreshCw className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  )
}
