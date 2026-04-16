import asyncio
import logging
import random
import time
from typing import Optional, List, Dict, Set
from backend.core.sqlite_db import AsyncSQLiteDB
from backend.core.config import settings

log = logging.getLogger("qwen2api.accounts")


def _jitter_seconds() -> float:
    low = max(0, settings.REQUEST_JITTER_MIN_MS)
    high = max(low, settings.REQUEST_JITTER_MAX_MS)
    return random.uniform(low, high) / 1000.0


class Account:
    def __init__(
        self,
        email="",
        password="",
        token="",
        cookies="",
        username="",
        provider="qwen",
        activation_pending=False,
        status_code="",
        last_error="",
        **kwargs,
    ):
        self.email = email
        self.password = password
        self.token = token
        self.cookies = cookies
        self.username = username
        self.provider = provider or "qwen"
        self.activation_pending = activation_pending
        self.valid = not activation_pending
        self.last_used = 0.0
        self.inflight = 0
        self.rate_limited_until = 0.0
        self.healing = False
        self.status_code = status_code or ("pending_activation" if activation_pending else "valid")
        self.last_error = last_error or ""
        self.last_request_started = float(kwargs.get("last_request_started", 0.0) or 0.0)
        self.last_request_finished = float(kwargs.get("last_request_finished", 0.0) or 0.0)
        self.consecutive_failures = int(kwargs.get("consecutive_failures", 0) or 0)
        self.rate_limit_strikes = int(kwargs.get("rate_limit_strikes", 0) or 0)
        
        # Enterprise point 12: RTT tracking (Smooth EMA)
        self.rtt_ema = float(kwargs.get("rtt_ema", 0.5) or 0.5) # Default 500ms

    def is_rate_limited(self) -> bool:
        return self.rate_limited_until > time.time()

    def is_available(self) -> bool:
        return self.valid and not self.is_rate_limited()

    def next_available_at(self, pool_size: int = 1) -> float:
        # Turbo V6: Dynamic Scaling of safety margin
        # 1 account: 0.5s safety (High risk of banning)
        # 2-3 accounts: 0.1s safety
        # >3 accounts: 0s safety (Rotation handles it)
        base_interval = max(0, settings.ACCOUNT_MIN_INTERVAL_MS)
        dynamic_interval = (base_interval / max(1, pool_size)) / 1000.0
        
        if pool_size <= 1:
            safety_margin = 0.5
        elif pool_size <= 3:
            safety_margin = 0.1
        else:
            safety_margin = 0.0
        
        effective_interval = max(safety_margin, dynamic_interval)
        return max(self.rate_limited_until, self.last_request_started + effective_interval)

    def get_status_code(self) -> str:
        if self.activation_pending:
            return "pending_activation"
        if self.is_rate_limited():
            return "rate_limited"
        if self.valid:
            return "valid"
        if self.status_code == "banned":
            return "banned"
        if self.status_code == "auth_error":
            return "auth_error"
        return self.status_code or "invalid"

    def get_status_text(self) -> str:
        return self.get_status_code()

    def to_dict(self):
        return {
            "email": self.email,
            "password": self.password,
            "token": self.token,
            "cookies": self.cookies,
            "username": self.username,
            "provider": self.provider,
            "activation_pending": self.activation_pending,
            "status_code": self.status_code,
            "last_error": self.last_error,
            "last_request_started": self.last_request_started,
            "last_request_finished": self.last_request_finished,
            "consecutive_failures": self.consecutive_failures,
            "rate_limit_strikes": self.rate_limit_strikes,
        }


class AccountPool:
    def __init__(self, db: AsyncSQLiteDB, max_inflight: int = settings.MAX_INFLIGHT):
        self.db = db
        self.max_inflight = max_inflight
        self.discovered_models: list[dict] = []
        self.accounts: list[Account] = []
        self._lock = asyncio.Lock()
        self._waiters: list[asyncio.Event] = []
        self._sticky_email: Optional[str] = None

    async def load_from_db(self):
        # 1. Load accounts
        rows = await self.db.fetch_all("SELECT * FROM accounts")
        self.accounts = [Account(**dict(r)) for r in rows]
        log.info(f"Loaded {len(self.accounts)} upstream account(s) from SQLite")
        
        # 2. Load persistent models
        saved_models = await self.db.get_setting("discovered_models", [])
        if saved_models:
            self.discovered_models = saved_models
            log.info(f"[Pool] Loaded {len(self.discovered_models)} persistent models from DB")

    async def save_account(self, acc: Account):
        # Using INSERT OR REPLACE (Upsert)
        data = acc.to_dict()
        # Convert bools to int for SQLite
        if "activation_pending" in data: data["activation_pending"] = 1 if data["activation_pending"] else 0
        data["valid"] = 1 if acc.valid else 0
        
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?" for _ in data])
        sql = f"INSERT OR REPLACE INTO accounts ({columns}) VALUES ({placeholders})"
        await self.db.execute(sql, tuple(data.values()))
        await self.db.commit()

    async def save(self):
        """Persist all accounts in the pool to the database.
        Called by auth_resolver and qwen_client after updating account properties."""
        for acc in self.accounts:
            await self.save_account(acc)

    async def update_discovered_models(self, provider: str, models: list[dict]):
        """Atualiza a lista de modelos preservando os de outros provedores e persiste no banco."""
        # Filtra os modelos atuais mantendo apenas os de OUTROS provedores
        others = [m for m in self.discovered_models if m.get("provider") != provider]
        
        # Adiciona os novos modelos do provedor atual
        for m in models:
            m["provider"] = provider
            
        self.discovered_models = others + models
        
        # Persistência Real: Salva no banco de dados para evitar amnésia do servidor
        await self.db.set_setting("discovered_models", self.discovered_models, "json")
        
        log.info(f"[Pool] Modelos atualizados para o provedor '{provider}'. Total agora: {len(self.discovered_models)} (Salvo no BD)")

    async def add(self, account: Account):
        async with self._lock:
            # Update memory
            self.accounts = [a for a in self.accounts if a.email != account.email]
            self.accounts.append(account)
            # Update DB
            await self.save_account(account)

    async def remove(self, email: str):
        async with self._lock:
            self.accounts = [a for a in self.accounts if a.email != email]
            await self.db.execute("DELETE FROM accounts WHERE email = ?", (email,))
            await self.db.commit()

    def set_max_inflight(self, value: int):
        self.max_inflight = max(1, int(value))

    async def acquire(self, exclude: set = None, provider: str = None, preferred_email: str = None) -> Optional[Account]:
        async with self._lock:
            now = time.time()
            
            # Multi-provider filter: Default to 'qwen' if not specified
            target_provider = provider or "qwen"
            accounts_subset = [a for a in self.accounts if a.provider == target_provider]
                
            # Safety Valve: If only 1 valid account exists, don't let 'exclude' kill the request
            valid_accounts = [a for a in accounts_subset if a.valid]
            
            available = [a for a in accounts_subset if a.is_available() and (not exclude or a.email not in exclude)]
            
            if not available and len(valid_accounts) == 1 and exclude:
                # If the ONLY valid account was excluded, ignore exclusion as a last resort
                available = [a for a in valid_accounts if a.is_available()]
                if available:
                    log.info(f"[SafetyValve] Ignoring exclusion for the only valid account: {available[0].email}")

            if not available:
                return None

            # Stale Protection: If an account has been in-flight for too long (>10m), reset it
            for a in self.accounts:
                if a.inflight > 0 and (now - a.last_request_started) > 600:
                    log.warning(f"[Pool] Forcing release of stale account: {a.email} (in-use for {int(now - a.last_request_started)}s)")
                    a.inflight = 0

            valid_count = len(valid_accounts)
            
            # Sticky Selection: Try preferred email first if available and not excluded
            if preferred_email and (not exclude or preferred_email not in exclude):
                target = next((a for a in available if a.email == preferred_email), None)
                if target and target.inflight < self.max_inflight and target.next_available_at(valid_count) <= now:
                    log.info(f"[Pool] Account {target.email} acquired via STICKY HINT")
                    target.inflight += 1
                    target.last_used = now
                    target.last_request_started = now + _jitter_seconds()
                    return target

            ready = [a for a in available if a.inflight < self.max_inflight and a.next_available_at(valid_count) <= now]
            if not ready:
                return None

            # Enterprise point 12: Sort by RTT (lowest first) for maximum throughput
            ready.sort(key=lambda a: (a.inflight, a.rtt_ema, a.last_request_started or 0.0))
            best = ready[0]
            best.inflight += 1
            log.info(f"[Pool] Account {best.email} acquired (inflight={best.inflight})")
            best.last_used = now
            best.last_request_started = now + _jitter_seconds()
            self._sticky_email = best.email if len(ready) == 1 else None
            return best

    async def acquire_wait(self, timeout: float = 60, exclude: set = None, provider: str = None, preferred_email: str = None) -> Optional[Account]:
        deadline = time.time() + timeout
        while True:
            acc = await self.acquire(exclude, provider, preferred_email=preferred_email)
            if acc:
                return acc

            evt = asyncio.Event()
            async with self._lock:
                target_provider = provider or "qwen"
                subset = [a for a in self.accounts if a.provider == target_provider]
                
                valid_accounts = [a for a in subset if a.valid]
                candidates = [
                    a for a in subset
                    if a.valid and (not exclude or a.email not in exclude)
                ]
                
                if not candidates and len(valid_accounts) == 1 and exclude:
                    # Safety Valve in wait logic too
                    candidates = valid_accounts

                if not candidates:
                    return None
                valid_count = len(valid_accounts)
                next_ready_at = min((a.next_available_at(valid_count) for a in candidates), default=time.time())
                self._waiters.append(evt)

            # Wait until next candidate is ready or timeout
            remaining = deadline - time.time()
            if remaining <= 0:
                async with self._lock:
                    if evt in self._waiters: self._waiters.remove(evt)
                return None

            wait_timeout = min(remaining, max(0.1, next_ready_at - time.time() + 0.1))
            try:
                await asyncio.wait_for(evt.wait(), timeout=wait_timeout)
            except asyncio.TimeoutError:
                pass
            finally:
                async with self._lock:
                    if evt in self._waiters:
                        self._waiters.remove(evt)

    def release(self, acc: Account):
        now = time.time()
        # Update RTT EMA (Exponential Moving Average) - Weight 0.3 for new sample
        if acc.last_request_started > 0:
            sample_rtt = now - acc.last_request_started
            acc.rtt_ema = (acc.rtt_ema * 0.7) + (sample_rtt * 0.3)
            
        acc.inflight = max(0, acc.inflight - 1)
        acc.last_request_finished = now
        log.info(f"[Pool] Account {acc.email} released (inflight={acc.inflight}, rtt={acc.rtt_ema:.3f}s)")
        if self._waiters:
            evt = self._waiters.pop(0)
            evt.set()

    def mark_invalid(self, acc: Account, reason: str = "invalid", error_message: str = ""):
        acc.valid = False
        acc.status_code = reason or "invalid"
        acc.last_error = error_message or acc.last_error
        acc.consecutive_failures += 1
        if reason == "pending_activation":
            acc.activation_pending = True
        if self._sticky_email == acc.email:
            self._sticky_email = None
        log.warning(f"[Account] {acc.email} marked as unavailable, status={acc.status_code}")
        
        # Hardening: Persist change to DB task (non-blocking)
        asyncio.create_task(self.save_account(acc))

    def mark_success(self, acc: Account):
        acc.consecutive_failures = 0
        acc.rate_limit_strikes = 0
        if acc.status_code == "rate_limited":
            acc.status_code = "valid"
        if not acc.activation_pending:
            acc.valid = True
            
        # Hardening: Persist change to DB task (non-blocking)
        asyncio.create_task(self.save_account(acc))

    def mark_rate_limited(self, acc: Account, cooldown: int | None = None, error_message: str = ""):
        acc.rate_limit_strikes += 1
        base = cooldown if cooldown is not None else settings.RATE_LIMIT_BASE_COOLDOWN
        dynamic = min(settings.RATE_LIMIT_MAX_COOLDOWN, int(base * (2 ** max(0, acc.rate_limit_strikes - 1))))
        dynamic += int(_jitter_seconds())
        acc.rate_limited_until = time.time() + dynamic
        acc.status_code = "rate_limited"
        acc.last_error = error_message or acc.last_error
        if self._sticky_email == acc.email:
            self._sticky_email = None
        log.warning(f"[Account] {acc.email} rate-limited cooldown for {dynamic} seconds")
        
        # Hardening: Persist change to DB task (non-blocking)
        asyncio.create_task(self.save_account(acc))

    def status(self) -> dict:
        try:
            total = len(self.accounts)
            valid = len([a for a in self.accounts if a.valid])
            now = time.time()
            rate_limited = len([a for a in self.accounts if a.rate_limited_until > now])
            pending = len([a for a in self.accounts if a.activation_pending])
            in_use = sum(a.inflight for a in self.accounts)
            
            return {
                "total": total,
                "valid": valid,
                "rate_limited": rate_limited,
                "activation_pending": pending,
                "invalid": total - valid,
                "in_use": in_use,
                "waiting": len(self._waiters),
                "models_count": len(getattr(self, "discovered_models", []) or []),
                "max_inflight": self.max_inflight,
                "account_min_interval_ms": settings.ACCOUNT_MIN_INTERVAL_MS,
            }
        except Exception as e:
            log.error(f"[Pool Status Error] {e}", exc_info=True)
            return {"error": str(e), "total": 0, "valid": 0}
