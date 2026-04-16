import React, { useState } from 'react';
import { Lock, KeyRound, ArrowRight, ShieldCheck, AlertCircle } from 'lucide-react';
import { checkSession, setAuthKey } from '../lib/auth';
import { useTranslation } from 'react-i18next';

interface LoginOverlayProps {
  onSuccess: () => void;
}

export default function LoginOverlay({ onSuccess }: LoginOverlayProps) {
  const { t } = useTranslation();
  const [key, setKey] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;

    setLoading(true);
    setError(false);

    const isValid = await checkSession(key);
    
    if (isValid) {
      setAuthKey(key);
      onSuccess();
    } else {
      setError(true);
    }
    setLoading(false);
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-md animate-in fade-in duration-500">
      <div className="w-full max-w-md p-8 bg-card border border-border/40 rounded-2xl shadow-2xl relative overflow-hidden group">
        {/* Decorative background glow */}
        <div className="absolute -top-24 -right-24 w-48 h-48 bg-primary/10 rounded-full blur-3xl group-hover:bg-primary/20 transition-colors duration-700" />
        <div className="absolute -bottom-24 -left-24 w-48 h-48 bg-purple-500/10 rounded-full blur-3xl group-hover:bg-purple-500/20 transition-colors duration-700" />

        <div className="relative space-y-6">
          <div className="flex justify-center">
            <div className="p-4 bg-primary/10 rounded-2xl">
              <ShieldCheck className="h-10 w-10 text-primary drop-shadow-[0_0_8px_rgba(var(--primary),0.5)]" />
            </div>
          </div>

          <div className="text-center space-y-2">
            <h1 className="text-2xl font-bold tracking-tight">{t("auth.title")}</h1>
            <p className="text-muted-foreground text-sm">
              {t("auth.desc")}
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <div className="relative group/input">
                <div className="absolute inset-y-0 left-0 pl-3 flex items-center pointer-events-none">
                  <KeyRound className="h-4 w-4 text-muted-foreground group-focus-within/input:text-primary transition-colors" />
                </div>
                {/* Hidden username field for accessibility/React DevTools warning */}
                <input
                  type="text"
                  name="username"
                  autoComplete="username"
                  style={{ display: 'none' }}
                  readOnly
                  value="admin"
                />
                <input
                  type="password"
                  name="password"
                  value={key}
                  onChange={(e) => setKey(e.target.value)}
                  placeholder={t("auth.placeholder")}
                  className={`w-full pl-10 pr-4 py-3 bg-muted/50 border ${error ? 'border-destructive/50 ring-2 ring-destructive/10' : 'border-border/40'} rounded-xl focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all text-sm`}
                  autoFocus
                  autoComplete="current-password"
                />
              </div>
              {error && (
                <div className="flex items-center gap-2 text-destructive text-xs animate-in slide-in-from-top-1">
                  <AlertCircle className="h-3 w-3" />
                  {t("auth.invalid")}
                </div>
              )}
            </div>

            <button
              type="submit"
              disabled={loading || !key.trim()}
              className="w-full py-3 bg-primary text-primary-foreground rounded-xl font-semibold shadow-lg shadow-primary/20 hover:shadow-primary/30 active:scale-[0.98] transition-all disabled:opacity-50 disabled:scale-100 flex items-center justify-center gap-2 group/btn"
            >
              {loading ? (
                <div className="h-5 w-5 border-2 border-primary-foreground/30 border-t-primary-foreground rounded-full animate-spin" />
              ) : (
                <>
                  {t("auth.button")}
                  <ArrowRight className="h-4 w-4 group-hover/btn:translate-x-1 transition-transform" />
                </>
              )}
            </button>
          </form>

          <div className="pt-4 border-t border-border/40 text-center">
            <p className="text-[10px] text-muted-foreground uppercase tracking-widest font-semibold flex items-center justify-center gap-1.5">
              <Lock className="h-2.5 w-2.5" />
              {t("auth.secure")}
            </p>
          </div>

        </div>
      </div>
    </div>
  );
}
