import { Outlet, Link, useLocation } from "react-router-dom"
import { Activity, Key, Settings, LayoutDashboard, MessageSquare, Menu, X, Image, Languages, Loader2, Globe, LogOut, ShieldCheck, Sun, Moon } from "lucide-react"
import { useState, useEffect } from "react"
import { useTranslation } from "react-i18next"
import { checkSession } from "../lib/auth"
import LoginOverlay from "../components/LoginOverlay"

export default function AdminLayout() {
  const loc = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const { t, i18n } = useTranslation()
  const [isAuth, setIsAuth] = useState<boolean | null>(null)

  useEffect(() => {
    const initAuth = async () => {
      const valid = await checkSession();
      setIsAuth(valid);
    };
    initAuth();
  }, [])

  const changeLanguage = (lng: string) => {
    i18n.changeLanguage(lng)
  }

  const [theme, setTheme] = useState<"light" | "dark">(() => {
    const saved = localStorage.getItem("qwen2api_theme")
    if (saved === "light" || saved === "dark") return saved
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light"
  })

  useEffect(() => {
    const root = document.documentElement
    if (theme === "dark") {
      root.classList.add("dark")
    } else {
      root.classList.remove("dark")
    }
    localStorage.setItem("qwen2api_theme", theme)
  }, [theme])

  const toggleTheme = () => {
    setTheme(prev => prev === "light" ? "dark" : "light")
  }

  const handleLogout = () => {
    localStorage.removeItem("qwen2api_key")
    setIsAuth(false)
  }

  if (isAuth === null) {
    return (
      <div className="flex h-screen w-full flex-col items-center justify-center bg-background gap-4">
        <Loader2 className="h-10 w-10 animate-spin text-primary opacity-40" />
        <div className="text-sm font-medium text-muted-foreground animate-pulse">
          {t("auth.verifying_connection", "Verificando conexão com o servidor...")}
        </div>
      </div>
    )
  }

  if (isAuth === false) {
    return <LoginOverlay onSuccess={() => setIsAuth(true)} />
  }

  const navs = [
    { name: t("nav.dashboard"), path: "/", icon: LayoutDashboard },
    { name: t("nav.accounts"), path: "/accounts", icon: Activity },
    { name: t("nav.provider"), path: "/provider", icon: Globe },
    { name: t("nav.tokens"), path: "/tokens", icon: Key },
    { name: t("nav.test"), path: "/test", icon: MessageSquare },
    { name: t("nav.images"), path: "/images", icon: Image },
    { name: t("nav.settings"), path: "/settings", icon: Settings },
    { name: t("nav.security"), path: "/security", icon: ShieldCheck },
  ]

  return (
    <div className="flex min-h-screen w-full bg-background text-foreground transition-colors duration-300">
      {/* Mobile sidebar backdrop */}
      {mobileOpen && (
        <div 
          className="fixed inset-0 bg-black/20 dark:bg-black/50 z-40 md:hidden backdrop-blur-sm transition-opacity"
          onClick={() => setMobileOpen(false)}
        />
      )}

      <aside className={`fixed md:sticky top-0 left-0 w-[260px] min-w-[260px] max-w-[260px] h-screen flex-shrink-0 flex-col border-r border-border/40 bg-card/90 md:bg-card/50 backdrop-blur-xl flex z-50 shadow-2xl shadow-black/5 dark:shadow-black/50 transition-transform duration-300 ${
        mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
      }`}>
        <div className="h-16 flex-shrink-0 flex items-center justify-between px-6 border-b border-border/40">
          <div className="font-extrabold text-xl tracking-tight bg-gradient-to-br from-indigo-500 to-purple-500 bg-clip-text text-transparent">qwen2API</div>
          <button className="md:hidden text-muted-foreground hover:text-foreground transition-colors" onClick={() => setMobileOpen(false)}>
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-1">
          {navs.map(n => {
            const active = loc.pathname === n.path
            return (
              <Link
                key={n.path}
                to={n.path}
                onClick={() => setMobileOpen(false)}
                className={`flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors duration-200 ${
                  active 
                  ? "bg-primary/10 text-primary shadow-sm ring-1 ring-primary/20" 
                  : "text-muted-foreground hover:bg-black/5 dark:hover:bg-white/5 hover:text-foreground"
                }`}
              >
                <n.icon className={`h-4 w-4 ${active ? "opacity-100" : "opacity-70"}`} />
                {n.name}
              </Link>
            )
          })}
        </nav>
        
        {/* Language & Logout */}
        <div className="p-4 border-t border-border/40 space-y-3">
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 px-3 pb-1 text-[10px] font-bold text-muted-foreground/60 uppercase tracking-widest">
              {theme === "dark" ? <Moon className="h-3 w-3" /> : <Sun className="h-3 w-3" />}
              {t("common.theme", "Interface")}
            </div>
            <button
              onClick={toggleTheme}
              className="flex items-center justify-between w-full px-3 py-2 rounded-lg bg-muted/30 hover:bg-muted/60 transition-all text-sm font-medium"
            >
              <div className="flex items-center gap-2">
                {theme === "dark" ? (
                  <><Moon className="h-4 w-4 text-primary" /> {t("common.dark", "Escuro")}</>
                ) : (
                  <><Sun className="h-4 w-4 text-amber-500" /> {t("common.light", "Claro")}</>
                )}
              </div>
              <div className="w-8 h-4 bg-background rounded-full p-0.5 border relative">
                <div className={`w-3 h-3 rounded-full transition-all duration-300 ${theme === "dark" ? "translate-x-4 bg-primary" : "translate-x-0 bg-amber-500"}`} />
              </div>
            </button>
          </div>
          
          <div className="space-y-1.5">
            <div className="flex items-center gap-2 px-3 pb-1 text-[10px] font-bold text-muted-foreground/60 uppercase tracking-widest">
              <Languages className="h-3 w-3" />
              Language
            </div>
            <div className="grid grid-cols-2 gap-1">
              {[
                { code: 'en', label: 'EN' },
                { code: 'pt', label: 'PT' }
              ].map((lang) => (
                <button
                  key={lang.code}
                  onClick={() => changeLanguage(lang.code)}
                  className={`px-1 py-1.5 rounded-md text-[10px] font-bold transition-all ${
                    i18n.language === lang.code
                    ? "bg-primary text-primary-foreground shadow-lg"
                    : "bg-muted/50 text-muted-foreground hover:bg-muted"
                  }`}
                >
                  {lang.label}
                </button>
              ))}
            </div>
          </div>
          
          <button
            onClick={handleLogout}
            className="flex items-center gap-3 w-full px-3 py-2.5 rounded-lg text-sm font-medium text-red-500 hover:bg-red-500/10 transition-all duration-300"
          >
            <LogOut className="h-4 w-4" />
            Sair do Painel
          </button>
        </div>
      </aside>

      <main className="flex-1 flex flex-col overflow-hidden relative">
        <header className="h-16 flex items-center justify-between px-6 border-b border-border/40 bg-card/80 backdrop-blur-xl md:hidden z-10 shadow-sm">
           <div className="font-extrabold text-lg bg-gradient-to-br from-indigo-500 to-purple-500 bg-clip-text text-transparent">qwen2API</div>
           <button className="text-muted-foreground hover:text-foreground transition-colors" onClick={() => setMobileOpen(true)}>
             <Menu className="h-6 w-6" />
           </button>
        </header>
        <div className="flex-1 p-6 md:p-8 overflow-y-auto z-0">
          <div className="max-w-6xl mx-auto animate-fade-in-up">
            <Outlet />
          </div>
        </div>
      </main>
    </div>
  )
}
